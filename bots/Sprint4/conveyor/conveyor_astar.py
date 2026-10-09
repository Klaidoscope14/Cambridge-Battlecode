"""Bidirectional A* conveyor path planner.

Finds optimal conveyor/bridge paths from a source to a destination (core or
specific target). Uses cardinal-only conveyor edges and bridge jump edges
within distance_squared <= 9. Bridges are naturally preferred over long
detours via the cost function.

Incremental: expands within CPU budget per turn. Vision-aware: only expands
tiles that have been seen by map_manager.
"""

from __future__ import annotations

import heapq
from cambc import Controller, EntityType, Direction, Position, ResourceType, Environment

from helpers.geometry import on_map
from map.map_manager import MapManager
from vision.storage_tracker import StorageTracker

# ── Cost constants (primary tuning knobs) ────────────────────────────────────

CONVEYOR_COST = 1       # cost of one cardinal conveyor step
BRIDGE_PENALTY = 7      # extra cost on top of manhattan distance for a bridge
                        # bridge_cost = manhattan(dx,dy) + BRIDGE_PENALTY
                        # so bridges only win when obstacles force a detour
H_WEIGHT = 3            # weighted A* heuristic multiplier
NODE_COST_EST = 50      # estimated CPU per node expansion

# CPU limit matching nav/config.py
CPU_LIMIT = 1800

DEBUG = True            # toggle debug prints

# ── Blocking type lists (matching proven rules from PathBuilder) ─────────────

ALLY_MILITARY = frozenset({
    EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL,
    EntityType.LAUNCHER, EntityType.GUNNER,
})

ENEMY_MILITARY = frozenset({
    EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL,
    EntityType.LAUNCHER, EntityType.GUNNER, EntityType.BARRIER,
})

# Types an enemy can have that we fire to clear (passable in A*)
ENEMY_FIREABLE = frozenset({
    EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER,
    EntityType.MARKER, EntityType.BRIDGE,
})

# Ally types we can destroy to clear (passable in A*)
ALLY_DESTROYABLE = frozenset({
    EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER,
})

# Isolate-mode blockers
ISOLATE_BLOCKERS = frozenset({
    EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER,
})

# ── Cardinal direction helpers ───────────────────────────────────────────────

CARDINAL_DELTAS = [
    (Direction.NORTH, 0, -1),
    (Direction.EAST, 1, 0),
    (Direction.SOUTH, 0, 1),
    (Direction.WEST, -1, 0),
]

# Reverse direction lookup for backward search
REVERSE_DIR = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
}

# ── Bridge offset table ───────────────────────────────────────────────────��─
# All (dx, dy) where dx*dx + dy*dy <= 9, excluding (0,0) and cardinal (±1,0),(0,±1)

BRIDGE_OFFSETS: list[tuple[int, int]] = []
for _dx in range(-3, 4):
    for _dy in range(-3, 4):
        dsq = _dx * _dx + _dy * _dy
        if dsq == 0 or dsq > 9:
            continue
        # Exclude cardinal-adjacent (those are conveyor edges)
        if abs(_dx) + abs(_dy) == 1:
            continue
        BRIDGE_OFFSETS.append((_dx, _dy))


# ── BuildStep ────────────────────────────────────────────────────────────────

class BuildStep:
    """One planned placement in the path."""
    __slots__ = ('pos', 'build_type', 'direction', 'bridge_target')

    def __init__(self, pos: Position, build_type: EntityType,
                 direction: Direction | None = None,
                 bridge_target: Position | None = None):
        self.pos = pos
        self.build_type = build_type
        self.direction = direction
        self.bridge_target = bridge_target

    def __repr__(self):
        if self.build_type == EntityType.BRIDGE:
            return f"BuildStep(BRIDGE {self.pos}->{self.bridge_target})"
        return f"BuildStep(CONV {self.pos} {self.direction})"


# ── Edge info stored in _from dicts ─────────────────────────────────���────────
# For conveyors: (parent_xy, 'conv', Direction)
# For bridges:   (parent_xy, 'bridge', None)
# We only need to distinguish type; direction is derived during reconstruction.


# ── Passability ──────────────────────────────────────────────────────────────

def _tile_buildable(x: int, y: int, mm: MapManager,
                    storage_tracker: StorageTracker,
                    my_team: int, ally_core_pos: Position | None,
                    dest_pos: Position | None, isolate: bool) -> bool:
    """Check if a tile can have a conveyor/bridge BUILT on it.

    This is BUILD passability, not movement passability. A bot can walk
    over an ally conveyor, but it can't build a new conveyor on top of one.

    Buildable tiles:
      - Empty (no building)
      - Ally ROAD/MARKER/BARRIER (will be destroyed then built on)
      - Enemy ROAD/CONVEYOR/SPLITTER/MARKER/BRIDGE (will be fired then built on)

    NOT buildable (even though bots can walk on them):
      - Ally CONVEYOR/BRIDGE/SPLITTER/HARVESTER/military/CORE/FOUNDRY
      - Enemy military
      - Walls, unseen tiles
    """
    w, h = mm.width, mm.height
    if not (0 <= x < w and 0 <= y < h):
        return False

    # Must have been seen (fog of war)
    if mm.tile_grid[x][y] is None:
        return False

    # Walls block
    if mm.tile_grid[x][y] == Environment.WALL:
        return False

    building = mm.building_grid[x][y]
    if building is None:
        return True  # Empty tile — can build here

    etype = building.entity_type
    team = building.team

    # Core always blocks for build purposes
    if etype == EntityType.CORE:
        return False

    # Ally entities
    if team == my_team:
        # Can destroy these to build on top
        if etype in ALLY_DESTROYABLE:
            return True
        # Everything else (conveyor, bridge, splitter, harvester, military, foundry)
        # already has a building we can't remove — not buildable
        return False

    # Enemy entities
    # Can fire on these to clear then build
    if etype in ENEMY_FIREABLE:
        return True
    # Enemy military etc — can't clear
    return False


def _tile_receivable(x: int, y: int, mm: MapManager,
                     storage_tracker: StorageTracker,
                     my_team: int, ally_core_pos: Position | None,
                     dest_pos: Position | None, isolate: bool) -> bool:
    """Check if a conveyor/bridge can OUTPUT to this tile.

    Matches the old PathBuilder.get_path_type conditions for what makes a
    valid conveyor output target. More permissive than _tile_buildable:
    existing non-full ally conveyors/bridges are valid output targets
    (resources flow into them).

    Old get_path_type says use BRIDGE (i.e. tile is NOT receivable) when:
      - Wall
      - Ally military (HARVESTER, BREACH, SENTINEL, LAUNCHER, GUNNER)
      - Enemy military (same + BARRIER)
      - Full conveyor/bridge
      - RAW_AXIONITE conveyor/bridge
      - CORE when dest != ally_core_pos
      - Isolate mode: existing ally CONVEYOR/BRIDGE/SPLITTER

    Everything else is receivable (conveyor output is fine):
      - Empty tiles
      - Non-full ally conveyors/bridges/splitters (resources flow in)
      - Ally ROAD/MARKER/BARRIER
      - Enemy fireable types
      - Core when dest == ally_core_pos
    """
    w, h = mm.width, mm.height
    if not (0 <= x < w and 0 <= y < h):
        return False

    if mm.tile_grid[x][y] is None:
        return False

    if mm.tile_grid[x][y] == Environment.WALL:
        return False

    building = mm.building_grid[x][y]
    if building is None:
        return True

    etype = building.entity_type
    team = building.team

    # Core: receivable only if we're pathing TO the core
    if etype == EntityType.CORE:
        if dest_pos is not None and ally_core_pos is not None and dest_pos == ally_core_pos:
            return True
        return False

    if team == my_team:
        if etype in ALLY_MILITARY:
            return False
        if etype in (EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER):
            if storage_tracker.is_full(building.id):
                return False
            if building.stored_resource == ResourceType.RAW_AXIONITE:
                return False
            if isolate:
                return False
            return True  # Non-full, non-axionite ally conveyor — resources flow in
        # ROAD/MARKER/BARRIER/FOUNDRY/HARVESTER — ROAD/MARKER/BARRIER are fine
        # FOUNDRY is fine (it accepts input)
        # HARVESTER blocks
        if etype == EntityType.HARVESTER:
            return False
        if etype == EntityType.FOUNDRY:
            return True
        return True  # ROAD, MARKER, BARRIER

    # Enemy
    if etype in ENEMY_MILITARY:
        return False
    return True


# ── Core-adjacent cell selection ─────────────────────────────────────────────

def _best_core_adjacent(core_pos: Position, source_pos: Position,
                        mm: MapManager) -> Position | None:
    """Pick the single core-adjacent cell closest to source_pos.

    The core occupies a 3x3 area centered at core_pos. We want positions
    cardinally adjacent to the core boundary that conveyors can feed into.
    """
    # Core occupies (cx-1..cx+1, cy-1..cy+1)
    cx, cy = core_pos.x, core_pos.y
    w, h = mm.width, mm.height

    # Generate all positions cardinally adjacent to any core tile
    # that are NOT core tiles themselves
    core_tiles = set()
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            core_tiles.add((cx + dx, cy + dy))

    candidates = set()
    for ctx, cty in core_tiles:
        for _, ddx, ddy in CARDINAL_DELTAS:
            nx, ny = ctx + ddx, cty + ddy
            if (nx, ny) not in core_tiles and 0 <= nx < w and 0 <= ny < h:
                candidates.add((nx, ny))

    best = None
    best_dist = float('inf')
    sx, sy = source_pos.x, source_pos.y
    for nx, ny in candidates:
        # Skip walls
        if mm.tile_grid[nx][ny] is None or mm.tile_grid[nx][ny] == Environment.WALL:
            continue
        dist = abs(nx - sx) + abs(ny - sy)
        if dist < best_dist:
            best_dist = dist
            best = Position(nx, ny)

    return best


# ── ConveyorAStar ────────────────────────────────────────────────────────────

class ConveyorAStar:
    """Bidirectional A* planner for conveyor/bridge paths."""

    def __init__(self, ct: Controller, brain):
        self.brain = brain
        self.storage_tracker: StorageTracker = brain.storage_tracker
        self.my_team = ct.get_team()

        # Planning parameters
        self.source_pos: Position | None = None
        self.dest_pos: Position | None = None
        self.isolate: bool = False

        # Forward search (source -> dest)
        self._f_open: list = []
        self._f_g: dict[tuple, float] = {}
        self._f_from: dict[tuple, tuple] = {}  # node -> (parent, edge_type)
        self._f_closed: set[tuple] = set()

        # Backward search (dest -> source)
        self._b_open: list = []
        self._b_g: dict[tuple, float] = {}
        self._b_from: dict[tuple, tuple] = {}
        self._b_closed: set[tuple] = set()

        self._cnt: int = 0  # monotonic tiebreaker

        # Meeting (bidirectional)
        self._best_cost: float = float('inf')
        self._meeting_node: tuple | None = None

        # Early goal: forward search found a node adjacent to a receivable
        # ally conveyor/bridge — can terminate by pointing into it
        self._early_goal_cost: float = float('inf')
        self._early_goal_node: tuple | None = None
        self._early_goal_target: tuple | None = None  # the receivable tile

        # Result
        self._path: list[BuildStep] | None = None
        self._path_index: int = 0
        self._exhausted: bool = False

    # ── Planning interface ───────────────────────────────────────────────

    def plan_path(self, ct: Controller, build_pos: Position,
                  dest_pos: Position, isolate: bool = False) -> None:
        """Initialize bidirectional search from build_pos toward dest_pos.

        build_pos is the OUTPUT of the current source — the first tile we
        actually build on. NOT the source entity's position. determine()
        already computes this correctly:
          - Harvester: cardinal neighbor closest to core
          - Conveyor:  pos.add(direction)  (the output tile)
          - Bridge:    bridge_target
        """
        mm: MapManager = self.brain.map_manager

        self.source_pos = build_pos
        self.dest_pos = dest_pos
        self.isolate = isolate
        self.my_team = ct.get_team()

        # Clear all state
        self._f_open = []
        self._f_g = {}
        self._f_from = {}
        self._f_closed = set()
        self._b_open = []
        self._b_g = {}
        self._b_from = {}
        self._b_closed = set()
        self._cnt = 0
        self._best_cost = float('inf')
        self._meeting_node = None
        self._early_goal_cost = float('inf')
        self._early_goal_node = None
        self._early_goal_target = None
        self._path = None
        self._path_index = 0
        self._exhausted = False
        self._dbg_f_expanded = 0
        self._dbg_b_expanded = 0

        # Determine the actual backward search seed
        # For core: pick best core-adjacent cell (where the last conveyor will be built)
        # For specific dest: seed from dest itself (we don't build there, it receives)
        ally_core_pos = mm.ally_core_pos
        if dest_pos == ally_core_pos and ally_core_pos is not None:
            back_seed = _best_core_adjacent(ally_core_pos, build_pos, mm)
            if back_seed is None:
                DEBUG and print(f"[ConvAStar] PLAN FAILED: no valid core-adjacent cell for core={ally_core_pos}")
                self._exhausted = True
                return
            # Store the actual core pos so reconstruction can point the last
            # conveyor into the core
            self._final_target = ally_core_pos
        else:
            back_seed = dest_pos
            self._final_target = dest_pos

        # Seed forward search from build_pos
        sk = (build_pos.x, build_pos.y)
        bk = (back_seed.x, back_seed.y)

        self._f_g[sk] = 0
        h = H_WEIGHT * (abs(build_pos.x - back_seed.x) + abs(build_pos.y - back_seed.y))
        heapq.heappush(self._f_open, (h, self._cnt, sk))
        self._cnt += 1

        # Seed backward search from dest side
        self._b_g[bk] = 0
        h = H_WEIGHT * (abs(back_seed.x - build_pos.x) + abs(back_seed.y - build_pos.y))
        heapq.heappush(self._b_open, (h, self._cnt, bk))
        self._cnt += 1

        self._back_seed = bk
        self._forward_seed = sk

        DEBUG and print(f"[ConvAStar] PLAN START: build_pos={build_pos} dest={dest_pos} back_seed={back_seed} final_target={self._final_target} isolate={isolate} manhattan={abs(sk[0]-bk[0])+abs(sk[1]-bk[1])}")

    def is_planned_for_dest(self, dest_pos: Position) -> bool:
        """Check if we have an active plan heading to this destination.

        We only check dest because the source changes as we build along
        the path (each new conveyor becomes the new 'source'). The path
        itself already covers the full route.
        """
        if self.dest_pos is None:
            return False
        if self._path is None and self._exhausted:
            return False
        return self.dest_pos == dest_pos

    def is_complete(self) -> bool:
        """True if a full path has been found."""
        return self._path is not None

    def is_exhausted(self) -> bool:
        """True if search is done and no path was found."""
        return self._exhausted

    # ── Per-turn expansion ───────────────────────────────────────────────

    def expand_turn(self, ct: Controller) -> bool:
        """Expand within CPU budget. Returns True if path was found this turn."""
        if self._path is not None or self._exhausted:
            return self._path is not None

        remaining_cpu = CPU_LIMIT - ct.get_cpu_time_elapsed()
        budget = max(0, remaining_cpu // NODE_COST_EST)
        initial_budget = budget

        DEBUG and print(f"[ConvAStar] EXPAND: cpu_remaining={remaining_cpu} budget={budget} f_open={len(self._f_open)} b_open={len(self._b_open)} f_closed={len(self._f_closed)} b_closed={len(self._b_closed)} best_cost={self._best_cost} meeting={self._meeting_node}")

        mm: MapManager = self.brain.map_manager
        ally_core_pos = mm.ally_core_pos

        while budget > 0:
            # Check termination: best known solution (meeting or early goal)
            f_min = self._f_open[0][0] if self._f_open else float('inf')
            b_min = self._b_open[0][0] if self._b_open else float('inf')
            best_solution = min(self._best_cost, self._early_goal_cost)

            if min(f_min, b_min) >= best_solution:
                if self._early_goal_cost <= self._best_cost and self._early_goal_node is not None:
                    # Early goal wins — connect into existing conveyor chain
                    DEBUG and print(f"[ConvAStar] EARLY GOAL: cost={self._early_goal_cost} node={self._early_goal_node} target={self._early_goal_target} f_expanded={self._dbg_f_expanded}")
                    self._reconstruct_early_goal(mm)
                else:
                    # Bidirectional meeting wins
                    DEBUG and print(f"[ConvAStar] MEETING CONFIRMED: cost={self._best_cost} node={self._meeting_node} f_expanded={self._dbg_f_expanded} b_expanded={self._dbg_b_expanded} used={initial_budget - budget} nodes")
                    self._reconstruct_path(mm)
                return True

            # Both exhausted without meeting
            if not self._f_open and not self._b_open:
                DEBUG and print(f"[ConvAStar] EXHAUSTED: no path found. f_expanded={self._dbg_f_expanded} b_expanded={self._dbg_b_expanded}")
                self._exhausted = True
                return False

            # Alternate: expand whichever has lower min f
            # If one is empty, expand the other
            if not self._b_open or (self._f_open and f_min <= b_min):
                self._expand_one_forward(ct, mm, ally_core_pos)
            else:
                self._expand_one_backward(ct, mm, ally_core_pos)

            budget -= 1

        DEBUG and print(f"[ConvAStar] BUDGET SPENT: used={initial_budget} f_expanded={self._dbg_f_expanded} b_expanded={self._dbg_b_expanded} best_cost={self._best_cost}")
        return False

    def _expand_one_forward(self, ct: Controller, mm: MapManager,
                            ally_core_pos: Position | None) -> None:
        """Expand one node from the forward frontier."""
        while self._f_open:
            _f, _c, cur = heapq.heappop(self._f_open)
            if cur in self._f_closed:
                continue
            self._f_closed.add(cur)
            self._dbg_f_expanded += 1

            g = self._f_g[cur]
            cx, cy = cur

            # Generate neighbors
            self._expand_neighbors(
                cx, cy, g, self._f_g, self._f_from, self._f_closed,
                self._f_open, self._b_g, self._back_seed,
                ct, mm, ally_core_pos, forward=True
            )
            return
        DEBUG and print("[ConvAStar] FWD open empty, nothing to expand")

    def _expand_one_backward(self, ct: Controller, mm: MapManager,
                             ally_core_pos: Position | None) -> None:
        """Expand one node from the backward frontier."""
        while self._b_open:
            _f, _c, cur = heapq.heappop(self._b_open)
            if cur in self._b_closed:
                continue
            self._b_closed.add(cur)
            self._dbg_b_expanded += 1

            g = self._b_g[cur]
            cx, cy = cur

            self._expand_neighbors(
                cx, cy, g, self._b_g, self._b_from, self._b_closed,
                self._b_open, self._f_g, self._forward_seed,
                ct, mm, ally_core_pos, forward=False
            )
            return
        DEBUG and print("[ConvAStar] BWD open empty, nothing to expand")

    def _expand_neighbors(self, cx: int, cy: int, g: float,
                          my_g: dict, my_from: dict, my_closed: set,
                          my_open: list, other_g: dict,
                          h_target: tuple,
                          ct: Controller, mm: MapManager,
                          ally_core_pos: Position | None,
                          forward: bool) -> None:
        """Expand cardinal (conveyor) and bridge neighbors from (cx, cy)."""
        tx, ty = h_target
        w, h = mm.width, mm.height

        # Cardinal neighbors (conveyor edges)
        for direction, dx, dy in CARDINAL_DELTAS:
            nx, ny = cx + dx, cy + dy
            nb = (nx, ny)
            if nb in my_closed:
                continue
            if not _tile_buildable(nx, ny, mm, self.storage_tracker,
                                  self.my_team, ally_core_pos,
                                  self.dest_pos, self.isolate):
                # Not buildable — but can we OUTPUT to it? (existing ally conveyor)
                # Only check on forward search: this node becomes the last build
                # position, with a conveyor pointing at the receivable neighbor.
                if forward and _tile_receivable(nx, ny, mm, self.storage_tracker,
                                                self.my_team, ally_core_pos,
                                                self.dest_pos, self.isolate):
                    # g is the cost to reach (cx,cy). No extra cost — we build
                    # the conveyor at (cx,cy) pointing at (nx,ny).
                    if g < self._early_goal_cost:
                        self._early_goal_cost = g
                        self._early_goal_node = (cx, cy)
                        self._early_goal_target = nb
                        DEBUG and print(f"[ConvAStar] EARLY GOAL CANDIDATE: ({cx},{cy}) -> receivable ({nx},{ny}) cost={g}")
                continue

            ng = g + CONVEYOR_COST
            if nb not in my_g or ng < my_g[nb]:
                my_g[nb] = ng
                # Store edge info: parent and type
                edge_dir = direction if forward else REVERSE_DIR[direction]
                my_from[nb] = ((cx, cy), 'conv', edge_dir)
                fval = ng + H_WEIGHT * (abs(nx - tx) + abs(ny - ty))
                heapq.heappush(my_open, (fval, self._cnt, nb))
                self._cnt += 1

            # Check meeting
            if nb in other_g:
                total = (my_g.get(nb, float('inf')) + other_g[nb])
                if total < self._best_cost:
                    self._best_cost = total
                    self._meeting_node = nb

        # Bridge neighbors (jump edges)
        # Bridge cost = manhattan distance of jump + penalty
        # This ensures bridges only win when obstacles force a longer conveyor detour
        for dx, dy in BRIDGE_OFFSETS:
            nx, ny = cx + dx, cy + dy
            nb = (nx, ny)
            if nb in my_closed:
                continue
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if not _tile_buildable(nx, ny, mm, self.storage_tracker,
                                  self.my_team, ally_core_pos,
                                  self.dest_pos, self.isolate):
                continue

            bridge_manhattan = abs(dx) + abs(dy)
            ng = g + bridge_manhattan + BRIDGE_PENALTY
            if nb not in my_g or ng < my_g[nb]:
                my_g[nb] = ng
                my_from[nb] = ((cx, cy), 'bridge', None)
                fval = ng + H_WEIGHT * (abs(nx - tx) + abs(ny - ty))
                heapq.heappush(my_open, (fval, self._cnt, nb))
                self._cnt += 1

            # Check meeting
            if nb in other_g:
                total = (my_g.get(nb, float('inf')) + other_g[nb])
                if total < self._best_cost:
                    self._best_cost = total
                    self._meeting_node = nb

    # ── Path reconstruction ──────────────────────────────────────────────

    def _reconstruct_early_goal(self, mm: MapManager) -> None:
        """Build path when forward search found a receivable neighbor.

        The path goes: build_pos -> ... -> early_goal_node, with the last
        conveyor/bridge at early_goal_node pointing at early_goal_target
        (an existing ally conveyor we connect into).
        """
        goal = self._early_goal_node
        target = self._early_goal_target

        # Trace forward chain: goal -> ... -> build_pos
        chain = [goal]
        cur = goal
        while cur in self._f_from:
            parent, _, _ = self._f_from[cur]
            chain.append(parent)
            cur = parent
        chain.reverse()  # build_pos -> ... -> goal

        DEBUG and print(f"[ConvAStar] EARLY GOAL CHAIN ({len(chain)} nodes): {chain} -> target {target}")

        # Every tile in chain is a build position. Last one points at target.
        steps: list[BuildStep] = []
        for i in range(len(chain)):
            ax, ay = chain[i]
            pos = Position(ax, ay)

            if i + 1 < len(chain):
                bx, by = chain[i + 1]
            else:
                # Last tile — point at the receivable target
                bx, by = target

            dx = bx - ax
            dy = by - ay
            dsq = dx * dx + dy * dy

            if dsq == 0:
                continue
            elif dsq == 1:
                direction = self._delta_to_direction(dx, dy)
                steps.append(BuildStep(pos, EntityType.CONVEYOR, direction=direction))
            elif dsq <= 9:
                steps.append(BuildStep(pos, EntityType.BRIDGE, bridge_target=Position(bx, by)))
            else:
                print(f"[ConvAStar] WARNING: invalid step distance {dsq} from ({ax},{ay}) to ({bx},{by})")
                self._exhausted = True
                return

        self._path = steps
        self._path_index = 0

        n_conv = sum(1 for s in steps if s.build_type == EntityType.CONVEYOR)
        n_bridge = sum(1 for s in steps if s.build_type == EntityType.BRIDGE)
        DEBUG and print(f"[ConvAStar] EARLY GOAL PATH: {len(steps)} steps ({n_conv} conveyors, {n_bridge} bridges)")
        if DEBUG:
            for i, s in enumerate(steps):
                print(f"  step[{i}]: {s}")

    def _reconstruct_path(self, mm: MapManager) -> None:
        """Build the path from forward_from and backward_from via meeting node.

        chain[0] = build_pos (first tile to build on)
        chain[-1] = backward seed (core-adjacent tile, or dest itself)

        Every tile in the chain is a build position EXCEPT:
        - For specific dest (not core): chain[-1] IS dest, don't build there
        - For core dest: chain[-1] is core-adjacent, DO build there pointing into core
        """
        if self._meeting_node is None:
            self._exhausted = True
            return

        meeting = self._meeting_node

        # Trace forward chain: meeting -> ... -> build_pos
        forward_chain = [meeting]
        cur = meeting
        while cur in self._f_from:
            parent, _, _ = self._f_from[cur]
            forward_chain.append(parent)
            cur = parent
        forward_chain.reverse()  # build_pos -> ... -> meeting

        # Trace backward chain: meeting -> ... -> back_seed
        backward_chain = []
        cur = meeting
        while cur in self._b_from:
            parent, _, _ = self._b_from[cur]
            backward_chain.append(parent)
            cur = parent

        # Full chain: build_pos -> ... -> meeting -> ... -> back_seed
        full_chain = forward_chain + backward_chain

        DEBUG and print(f"[ConvAStar] RAW CHAIN ({len(full_chain)} nodes): {full_chain}")

        if len(full_chain) < 2:
            DEBUG and print(f"[ConvAStar] Chain too short, nothing to build")
            self._path = []
            self._path_index = 0
            return

        # Determine which tiles we build on and what the final output target is.
        #
        # For core dest: back_seed = core-adjacent tile. We build there too,
        #   and the last conveyor/bridge points toward the core center.
        #   final_target = ally_core_pos
        #
        # For specific dest: back_seed = dest itself. We DON'T build at dest.
        #   The last conveyor/bridge points toward dest.
        #   final_target = dest
        ally_core_pos = mm.ally_core_pos
        is_core_dest = self.dest_pos == ally_core_pos and ally_core_pos is not None
        if is_core_dest:
            # Core: build on every tile including chain[-1], last one points to core
            build_tiles = full_chain
        else:
            # Specific dest: don't build on chain[-1] (the dest itself)
            build_tiles = full_chain[:-1]

        # Convert build_tiles to BuildSteps
        steps: list[BuildStep] = []
        ft = self._final_target
        for i in range(len(build_tiles)):
            ax, ay = build_tiles[i]
            pos = Position(ax, ay)

            # What does this conveyor/bridge point toward?
            if i + 1 < len(build_tiles):
                bx, by = build_tiles[i + 1]
            else:
                # Last build tile — point toward the destination.
                # For core: find the cardinal-adjacent core tile, not the center.
                # The core is 3x3 centered at ally_core_pos. The last build tile
                # is core-adjacent, so exactly one cardinal neighbor is a core tile.
                if is_core_dest:
                    cx, cy = ally_core_pos.x, ally_core_pos.y
                    bx, by = ft.x, ft.y  # fallback to center
                    for _, ddx, ddy in CARDINAL_DELTAS:
                        nx, ny = ax + ddx, ay + ddy
                        if cx - 1 <= nx <= cx + 1 and cy - 1 <= ny <= cy + 1:
                            bx, by = nx, ny
                            break
                else:
                    bx, by = ft.x, ft.y

            dx = bx - ax
            dy = by - ay
            dsq = dx * dx + dy * dy

            if dsq == 0:
                # Same position — skip (shouldn't happen)
                DEBUG and print(f"[ConvAStar] WARNING: zero-distance step at ({ax},{ay})")
                continue
            elif dsq == 1:
                direction = self._delta_to_direction(dx, dy)
                steps.append(BuildStep(pos, EntityType.CONVEYOR, direction=direction))
            elif dsq <= 9:
                target_pos = Position(bx, by)
                steps.append(BuildStep(pos, EntityType.BRIDGE, bridge_target=target_pos))
            else:
                print(f"[ConvAStar] WARNING: invalid step distance {dsq} from ({ax},{ay}) to ({bx},{by})")
                self._exhausted = True
                return

        self._path = steps
        self._path_index = 0

        n_conv = sum(1 for s in steps if s.build_type == EntityType.CONVEYOR)
        n_bridge = sum(1 for s in steps if s.build_type == EntityType.BRIDGE)
        DEBUG and print(f"[ConvAStar] PATH BUILT: {len(steps)} steps ({n_conv} conveyors, {n_bridge} bridges)")
        if DEBUG:
            for i, s in enumerate(steps):
                print(f"  step[{i}]: {s}")

    @staticmethod
    def _delta_to_direction(dx: int, dy: int) -> Direction:
        if dx == 1 and dy == 0:
            return Direction.EAST
        if dx == -1 and dy == 0:
            return Direction.WEST
        if dx == 0 and dy == 1:
            return Direction.SOUTH
        if dx == 0 and dy == -1:
            return Direction.NORTH
        return Direction.NORTH  # fallback, shouldn't happen

    # ── Build step access ────────────────────────────────────────────────

    def get_next_build_step(self) -> BuildStep | None:
        """Return the next step to build, or None if done."""
        if self._path is None or self._path_index >= len(self._path):
            return None
        return self._path[self._path_index]

    def advance(self) -> None:
        """Mark current step as built, move to next."""
        self._path_index += 1

    def remaining_steps(self) -> int:
        """Number of steps left to build."""
        if self._path is None:
            return 0
        return max(0, len(self._path) - self._path_index)

    # ── Vision updates ────────────────────────────────���──────────────────

    def handle_newly_seen(self, mm: MapManager) -> None:
        """Re-open frontier nodes adjacent to newly-seen tiles.

        Same pattern as Pathing._reopen() in nav/pathing.py.
        """
        newly_seen = mm.newly_seen
        if not newly_seen or self._path is not None:
            return

        DEBUG and print(f"[ConvAStar] NEWLY SEEN: {len(newly_seen)} tiles, reopening frontiers")

        # Re-open forward closed nodes adjacent to newly seen
        self._reopen_direction(newly_seen, self._f_g, self._f_closed,
                               self._f_open, self._back_seed, mm)
        # Re-open backward closed nodes adjacent to newly seen
        self._reopen_direction(newly_seen, self._b_g, self._b_closed,
                               self._b_open, self._forward_seed, mm)

        self._exhausted = False

    def _reopen_direction(self, newly_seen: set, g_map: dict,
                          closed: set, open_list: list,
                          h_target: tuple, mm: MapManager) -> None:
        """Re-open closed nodes adjacent to newly-seen tiles for one direction."""
        tx, ty = h_target
        w, h = mm.width, mm.height

        for sx, sy in newly_seen:
            for _, dx, dy in CARDINAL_DELTAS:
                nx, ny = sx + dx, sy + dy
                nb = (nx, ny)
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if nb in closed and nb in g_map:
                    closed.discard(nb)
                    fval = g_map[nb] + H_WEIGHT * (abs(nx - tx) + abs(ny - ty))
                    heapq.heappush(open_list, (fval, self._cnt, nb))
                    self._cnt += 1

    # ── Path validation ──────────────────────────────────────────────────

    def validate_next_step(self, ct: Controller) -> bool:
        """Check if the next build step is still valid."""
        step = self.get_next_build_step()
        if step is None:
            return False

        mm: MapManager = self.brain.map_manager
        x, y = step.pos.x, step.pos.y

        if not _tile_buildable(x, y, mm, self.storage_tracker,
                              self.my_team, mm.ally_core_pos,
                              self.dest_pos, self.isolate):
            building = mm.building_grid[x][y]
            DEBUG and print(f"[ConvAStar] VALIDATE FAIL at ({x},{y}): env={mm.tile_grid[x][y]} building={building.entity_type if building else None} team={'ally' if building and building.team == self.my_team else 'enemy' if building else 'none'}")
            return False

        # For the LAST step, validate that what it points at is still receivable.
        # A conveyor that was non-full during planning could be full now.
        is_last_step = self._path_index == len(self._path) - 1
        if is_last_step:
            if step.build_type == EntityType.CONVEYOR and step.direction is not None:
                # Check the tile this conveyor would point at
                ddx, ddy = step.direction.delta()
                tx, ty = x + ddx, y + ddy
                if not _tile_receivable(tx, ty, mm, self.storage_tracker,
                                       self.my_team, mm.ally_core_pos,
                                       self.dest_pos, self.isolate):
                    building = mm.building_grid[tx][ty] if 0 <= tx < mm.width and 0 <= ty < mm.height else None
                    DEBUG and print(f"[ConvAStar] VALIDATE FAIL last conv target ({tx},{ty}): building={building.entity_type if building else None} team={'ally' if building and building.team == self.my_team else 'enemy' if building else 'none'}")
                    return False
            elif step.build_type == EntityType.BRIDGE and step.bridge_target is not None:
                tx, ty = step.bridge_target.x, step.bridge_target.y
                if not _tile_receivable(tx, ty, mm, self.storage_tracker,
                                       self.my_team, mm.ally_core_pos,
                                       self.dest_pos, self.isolate):
                    building = mm.building_grid[tx][ty] if 0 <= tx < mm.width and 0 <= ty < mm.height else None
                    DEBUG and print(f"[ConvAStar] VALIDATE FAIL last bridge target ({tx},{ty}): building={building.entity_type if building else None} team={'ally' if building and building.team == self.my_team else 'enemy' if building else 'none'}")
                    return False

        # For non-last bridge steps, target must be buildable (we build there next)
        elif step.build_type == EntityType.BRIDGE and step.bridge_target is not None:
            tx, ty = step.bridge_target.x, step.bridge_target.y
            if not _tile_buildable(tx, ty, mm, self.storage_tracker,
                                  self.my_team, mm.ally_core_pos,
                                  self.dest_pos, self.isolate):
                building = mm.building_grid[tx][ty] if 0 <= tx < mm.width and 0 <= ty < mm.height else None
                DEBUG and print(f"[ConvAStar] VALIDATE FAIL bridge target ({tx},{ty}): building={building.entity_type if building else None}")
                return False

        return True

    def invalidate(self) -> None:
        """Clear the planned path, forcing a re-plan."""
        DEBUG and print(f"[ConvAStar] INVALIDATED: was at step {self._path_index}/{len(self._path) if self._path else 0}")
        self._path = None
        self._path_index = 0
        self._best_cost = float('inf')
        self._meeting_node = None
        self._early_goal_cost = float('inf')
        self._early_goal_node = None
        self._early_goal_target = None
        self._f_open = []
        self._f_g = {}
        self._f_from = {}
        self._f_closed = set()
        self._b_open = []
        self._b_g = {}
        self._b_from = {}
        self._b_closed = set()
        self._exhausted = False
