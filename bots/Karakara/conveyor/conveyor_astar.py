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
import math
from cambc import Controller, EntityType, Direction, Position, ResourceType, Environment

from helpers.geometry import on_map
from harvesters.resources import get_average_titanium_income
from map.map_manager import MapManager
from vision.storage_tracker import StorageTracker

# ── Cost constants (primary tuning knobs) ────────────────────────────────────

CONVEYOR_COST = 1       # cost of one cardinal conveyor step
ENEMY_TILE_PENALTY = 4  # extra cost for stepping onto an enemy-owned tile
                        # small enough not to force long detours, but enough to
                        # prefer enemy-free paths when distance is equal
BASE_ENEMY_TILE_PENALTY = 8  # baseline penalty always applied for enemy tiles
AVOID_ENEMY_TILE_PENALTY = 10_000  # penalty used when avoid_enemy=True — large
                        # enough that no reasonable path will ever walk through
                        # an enemy-owned tile unless it's the only option
BRIDGE_PENALTY = 18      # extra cost on top of manhattan distance for a bridge
                        # bridge_cost = manhattan(dx,dy) + BRIDGE_PENALTY
                        # so bridges only win when obstacles force a detour
H_WEIGHT = 3.0          # weighted A* heuristic multiplier
                        # Higher values push the search more aggressively toward
                        # the destination (greedy/faster but sub-optimal paths).
                        # 1.0 = true Dijkstra (optimal, slow)
TURN_PENALTY = 0.0      # disabled — was causing longer computation time
NODE_COST_EST = 40      # estimated CPU per node expansion

# CPU limit matching nav/config.py
CPU_LIMIT = 1800
EARLY_ROUNDS = 100

# Titanium income floor for the early-game exclusion bypass: when the rolling
# average is below this, the economy is still too thin to justify forcing
# builders to path all the way to the core, so let them hook in early.
EARLY_TITANIUM_INCOME_THRESHOLD = -10000

# After this many expand_turn() calls without a complete path, the search enters
# "desperate mode": the core exclusion zone and use_early_goals flag are bypassed
# so any receivable belt tile is accepted as an early-goal connection.
# invalidate() pre-sets _turns_expanded to this value so replans are immediately
# desperate — no point waiting 7 more turns when the previous plan already failed.
DESPERATE_TURNS = 7

# Master toggle for the "no-input priority reconnect" behavior. When False,
# ConveyorAStar never inspects mm.confirmed_input_positions and never promotes
# no-input orphan belts as priority early goals — the regular early-goal /
# meeting / desperate flow is all that runs. Flip to True to re-enable.
NO_INPUT_RECONNECT_ENABLED = False

DEBUG = False            # toggle debug prints

# ── Blocking type lists (matching proven rules from PathBuilder) ─────────────

ALLY_MILITARY = frozenset({
    EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL,
    EntityType.LAUNCHER, EntityType.GUNNER,
})

ENEMY_MILITARY = frozenset({
    EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL,
    EntityType.LAUNCHER, EntityType.GUNNER, EntityType.BARRIER,
})

# Types an enemy can have that we fire to clear (passable in A*).
# Only ROAD is considered passable — enemy conveyors, bridges, splitters and
# markers are treated as impassable so A* never routes our chain through them
# (we don't want to accidentally connect into enemy infrastructure).
ENEMY_FIREABLE = frozenset({
    EntityType.ROAD,
})

# Ally types we can destroy to clear (passable in A*)
ALLY_DESTROYABLE = frozenset({
    EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER,
})

# Isolate-mode blockers
ISOLATE_BLOCKERS = frozenset({
    EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER,
})

# Armoured conveyors behave identically to regular conveyors for feeder/sink/
# receivable semantics. Build emit sites stay regular-CONVEYOR-only — we never
# build armoured ourselves.
CONVEYOR_LIKE = frozenset({EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR})

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
      - Enemy ROAD (will be fired then built on)

    NOT buildable (even though bots can walk on them):
      - Ally CONVEYOR/BRIDGE/SPLITTER/HARVESTER/military/CORE/FOUNDRY
      - Enemy CONVEYOR/BRIDGE/SPLITTER/MARKER/military — impassable so we
        never accidentally route our chain through enemy infrastructure
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
        if etype in CONVEYOR_LIKE:
            dir: Direction = building.direction
            dx, dy = dir.delta()
            nx = x + dx
            ny = y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                return False
            next_building = mm.building_grid[nx][ny]
            if next_building != None and next_building.entity_type == EntityType.HARVESTER:
                return True

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
                     dest_pos: Position | None, isolate: bool,
                     ignore_full: bool = False) -> bool:
    """Check if a conveyor/bridge can OUTPUT to this tile.

    Matches the old PathBuilder.get_path_type conditions for what makes a
    valid conveyor output target. More permissive than _tile_buildable:
    existing non-full ally conveyors/bridges are valid output targets
    (resources flow into them).

    ignore_full=True: skip the is_full() check so that full conveyors/
    bridges are still accepted as connection targets. Used in desperate
    mode and when promoting fallback early goals — any connection is
    better than looping.

    Old get_path_type says use BRIDGE (i.e. tile is NOT receivable) when:
      - Wall
      - Ally military (HARVESTER, BREACH, SENTINEL, LAUNCHER, GUNNER)
      - Enemy military (same + BARRIER)
      - Full conveyor/bridge  (skipped when ignore_full=True)
      - RAW_AXIONITE conveyor/bridge
      - CORE when dest != ally_core_pos
      - Isolate mode: existing ally CONVEYOR/BRIDGE/SPLITTER

    Everything else is receivable (conveyor output is fine):
      - Empty tiles
      - Not-full ally conveyors/bridges/splitters (resources flow in)
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

    # Core: receivable only if we're pathing TO our own core. Enemy cores
    # are never a valid output target — the team check guards against an
    # early-goal landing next to an enemy core.
    if etype == EntityType.CORE:
        if (team == my_team
                and dest_pos is not None and ally_core_pos is not None
                and dest_pos == ally_core_pos):
            return True
        return False

    if team == my_team:
        if etype in ALLY_MILITARY:
            return False
        if etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER):
            if not ignore_full and storage_tracker.is_full(building.id):
                return False
            if building.stored_resource == ResourceType.RAW_AXIONITE:
                return False
            if isolate:
                return False
            if etype in CONVEYOR_LIKE:
                dir: Direction = building.direction
                dx, dy = dir.delta()
                nx = x + dx
                ny = y + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    return False
                # Conveyors pointing into ore tiles are harvesters feeding ore —
                # they don't route resources back to the core, so skip them as
                # early-goal connection targets.
                tile_env = mm.tile_grid[nx][ny]
                if tile_env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                    return False
                next_building = mm.building_grid[nx][ny]
                if next_building != None and next_building.entity_type == EntityType.HARVESTER:
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

    # Enemy — never receivable. We don't want our conveyor chain to
    # output into any enemy building (conveyors, bridges, splitters, etc.).
    # Enemy ROAD is buildable (we fire then replace) but not a useful
    # output target, so keep it non-receivable here too.
    return False


# ── Core-adjacent cell selection ─────────────────────────────────────────────

def _all_core_adjacent(core_pos: Position, mm: MapManager,
                       my_team: int, avoid_enemy: bool = False) -> list[Position]:
    """Return non-wall positions cardinally adjacent to the 3×3 core boundary
    that are buildable as a final approach to the core.

    Filters applied to core-adjacent tiles:
      - Out-of-bounds / wall / unseen tiles
      - Ally buildings whose type is not in ALLY_DESTROYABLE
        (skips ally CONVEYOR/BRIDGE/SPLITTER/HARVESTER/military/FOUNDRY —
        none of these can be replaced with a fresh conveyor)
      - All enemy buildings except ROAD (only enemy ROAD is fireable+rebuildable)
      - Enemy ROAD too when avoid_enemy=True (in enemy-reroute mode we shouldn't
        seed the backward search at a tile we'd be penalised for using anyway)

    Tiles directly inside the core footprint are still seeded (they pass
    _tile_buildable=False themselves but let the backward search expand
    outward through their neighbours).
    """
    cx, cy = core_pos.x, core_pos.y
    w, h = mm.width, mm.height

    core_tiles: set[tuple[int, int]] = set()
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            core_tiles.add((cx + dx, cy + dy))

    seen: set[tuple[int, int]] = set()
    candidates: list[Position] = []

    # Include the core tiles themselves
    for ctx, cty in core_tiles:
        if not (0 <= ctx < w and 0 <= cty < h):
            continue
        if mm.tile_grid[ctx][cty] is not None and mm.tile_grid[ctx][cty] == Environment.WALL:
            continue
        candidates.append(Position(ctx, cty))
        seen.add((ctx, cty))

    # Include positions cardinally adjacent to the core boundary
    for ctx, cty in core_tiles:
        for _, ddx, ddy in CARDINAL_DELTAS:
            nx, ny = ctx + ddx, cty + ddy
            if (nx, ny) in core_tiles or (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if mm.tile_grid[nx][ny] is None or mm.tile_grid[nx][ny] == Environment.WALL:
                continue
            building = mm.building_grid[nx][ny]
            if building is not None:
                if building.team == my_team:
                    # Ally side: only ALLY_DESTROYABLE types are
                    # buildable-over. Skips CONVEYOR/BRIDGE/SPLITTER/
                    # HARVESTER/military/FOUNDRY.
                    if building.entity_type not in ALLY_DESTROYABLE:
                        continue
                else:
                    # Enemy side: only ROAD is buildable-over.
                    if building.entity_type != EntityType.ROAD:
                        continue
                    # In enemy-reroute mode skip enemy ROAD too — the planner
                    # is actively trying to avoid enemy-owned tiles, no point
                    # seeding from one.
                    if avoid_enemy:
                        continue
            candidates.append(Position(nx, ny))

    return candidates


def _best_core_adjacent(core_pos: Position, source_pos: Position,
                        mm: MapManager, my_team: int,
                        avoid_enemy: bool = False) -> Position | None:
    """Pick the single core-adjacent cell closest to source_pos.

    Thin wrapper around _all_core_adjacent kept for backwards compatibility.
    """
    candidates = _all_core_adjacent(core_pos, mm, my_team, avoid_enemy)
    if not candidates:
        return None
    sx, sy = source_pos.x, source_pos.y
    return min(candidates, key=lambda p: abs(p.x - sx) + abs(p.y - sy))


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
        # When False the early-goal shortcut in _expand_neighbors is suppressed,
        # so the path never terminates by connecting into an existing conveyor chain.
        self.use_early_goals: bool = True
        # When True the planner treats enemy-owned tiles as (practically)
        # impassable via a huge cost penalty, and pre-arms desperate-mode so
        # any receivable ally belt is accepted as an early-goal connection.
        # Used by the enemy-reroute flow to hook the chain back into safety
        # as fast as possible.
        self.avoid_enemy: bool = False
        # When False the core exclusion zone check is skipped — every early
        # goal is accepted regardless of distance to the ally core. Used by
        # axionite pathing which always runs to its specific dest and should
        # never be rerouted just because a candidate sits near the core.
        self.use_core_exclusion: bool = True
        # When True, tiles cardinally adjacent to any harvester are treated as
        # impassable for both conveyor and bridge edges, EXCEPT the destination
        # itself (which may be a harvester-adjacent conveyor). Lets us bridge
        # over harvesters to reach the dest without building on neighbouring
        # tiles that would collide with the harvester's feed.
        self.avoid_harvester_adjacent: bool = False
        # If set, restricts the harvester-adjacency block to harvesters
        # sitting on this ore type. None = block adjacency to ANY harvester
        # (the original behavior). Used by callers that want to keep their
        # paths off only one resource's harvesters — e.g. axionite paths
        # avoid titanium harvesters, titanium paths avoid axionite ones.
        self.avoid_harvester_ore: "Environment | None" = None
        # When True, early-goal targets are restricted to ally CONVEYOR tiles
        # whose stored_resource is TITANIUM. Used by axionite pathing so the
        # fallback hop only hooks into the titanium transit network, never
        # into another axionite chain.
        self.early_goal_only_titanium: bool = False
        # Stored resource carried by the source entity (titanium conveyors,
        # axionite bridges, etc.) or None if the source has no resource
        # (harvesters). Used to block titanium chains from early-connecting
        # into RAW_AXIONITE belts, which would mix the streams.
        self.source_resource: "ResourceType | None" = None

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

        # Heuristic weight (set per-plan based on destination)
        self._h_weight: float = H_WEIGHT

        # Fixed dominant axis for turn-penalty (set once in plan_path)
        # True = prefer horizontal steps, False = prefer vertical steps
        self._dominant_horizontal: bool = True

        # Bidirectional search seeds (set in plan_path)
        self._back_seed: tuple | None = None
        self._forward_seed: tuple | None = None
        self._source_seed: tuple | None = None

        # Debug counters (set in plan_path)
        self._dbg_f_expanded: int = 0
        self._dbg_b_expanded: int = 0

        # Desperate-mode: after this many turns without a complete path, bypass
        # the core exclusion zone and use_early_goals flag so the search will
        # accept ANY receivable belt as an early-goal connection.
        self._turns_expanded: int = 0

        # Core exclusion zone: early-goal connections inside this radius (squared)
        # are treated as impassable. Computed dynamically in plan_path.
        self._core_exclusion_radius_sq: int = 64  # fallback: 8^2

        # Meeting (bidirectional)
        self._best_cost: float = float('inf')
        self._meeting_node: tuple | None = None

        # Early goal: forward search found a node adjacent to a receivable
        # ally conveyor/bridge — can terminate by pointing into it
        self._early_goal_cost: float = float('inf')
        self._early_goal_node: tuple | None = None
        self._early_goal_target: tuple | None = None  # the receivable tile

        # Fallback early goal: best early goal candidate that was rejected by the
        # core exclusion zone. Used only if the search exhausts without any meeting
        # or exclusion-passing early goal — avoids the broken _reset_without_exclusion
        # restart which re-seeds from a stale source_pos.
        self._fallback_goal_cost: float = float('inf')
        self._fallback_goal_node: tuple | None = None
        self._fallback_goal_target: tuple | None = None

        # Priority early goal: receivable target that is NOT in
        # mm.confirmed_input_positions — i.e. an orphaned belt with no feeder.
        # Always preferred over regular early goals and meeting, since
        # reconnecting the existing chain is cheap and almost always correct.
        self._priority_early_goal_cost: float = float('inf')
        self._priority_early_goal_node: tuple | None = None
        self._priority_early_goal_target: tuple | None = None

        # Result
        self._path: list[BuildStep] | None = None
        self._path_index: int = 0
        self._exhausted: bool = False

    # ── Planning interface ───────────────────────────────────────────────

    def plan_path(self, ct: Controller, source_pos: Position, build_pos: Position,
                  dest_pos: Position, isolate: bool = False,
                  use_early_goals: bool = True,
                  avoid_enemy: bool = False,
                  use_core_exclusion: bool = True,
                  avoid_harvester_adjacent: bool = False,
                  avoid_harvester_ore: "Environment | None" = None,
                  early_goal_only_titanium: bool = False,
                  source_resource: "ResourceType | None" = None) -> None:
        """Initialize bidirectional search from build_pos toward dest_pos.

        build_pos is the OUTPUT of the current source — the first tile we
        actually build on. NOT the source entity's position. determine()
        already computes this correctly:
          - Harvester: cardinal neighbor closest to core
          - Conveyor:  pos.add(direction)  (the output tile)
          - Bridge:    bridge_target

        avoid_enemy=True: the planner will strongly avoid enemy-owned tiles
        (huge cost penalty) and accept any receivable ally belt as an early
        goal so the chain reconnects as quickly as possible. Used when an
        enemy was spotted adjacent to the intended build pos.

        use_core_exclusion=False: skip the core exclusion zone so any tile is
        a valid early-goal target. Used by axionite pathing.
        avoid_harvester_adjacent=True: tiles cardinally adjacent to any
        harvester are impassable, except the destination itself.
        early_goal_only_titanium=True: restricts early-goal candidates to
        titanium-carrying conveyors.
        """
        mm: MapManager = self.brain.map_manager

        self.source_pos = build_pos
        self.dest_pos = dest_pos
        self.isolate = isolate
        self.use_early_goals = use_early_goals
        self.avoid_enemy = avoid_enemy
        self.use_core_exclusion = use_core_exclusion
        self.avoid_harvester_adjacent = avoid_harvester_adjacent
        self.avoid_harvester_ore = avoid_harvester_ore
        self.early_goal_only_titanium = early_goal_only_titanium
        self.source_resource = source_resource
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
        self._fallback_goal_cost = float('inf')
        self._fallback_goal_node = None
        self._fallback_goal_target = None
        self._priority_early_goal_cost = float('inf')
        self._priority_early_goal_node = None
        self._priority_early_goal_target = None
        self._path = None
        self._path_index = 0
        self._exhausted = False
        self._dbg_f_expanded = 0
        self._dbg_b_expanded = 0
        # Pre-arm desperate mode when avoiding enemies — we want any viable
        # early-goal connection accepted immediately, no 7-turn warmup.
        self._turns_expanded = DESPERATE_TURNS if avoid_enemy else 0

        ally_core_pos = mm.ally_core_pos
        self._h_weight = H_WEIGHT

        # Compute the core exclusion radius for this plan.
        # Tiles within this radius (distance squared) of the core are treated as
        # impassable for early-goal connections — builders near the core must
        # build their own path to the core rather than hooking into congested
        # segments close to it.
        #
        # Formula: base = 20% of the shorter map dimension.
        # Bonus: scaled by how far the core sits from the nearest map edge —
        # a core deep inside the map has more inbound routes converging on it,
        # so the exclusion zone should be proportionally larger.
        #
        # Early game: skip the exclusion zone entirely so builders can freely
        # hook into any nearby belt while the network is still sparse. Two
        # independent triggers, either one bypasses the zone:
        #   - round < EARLY_ROUNDS          : fixed warmup window
        #   - avg titanium income < threshold: economy hasn't spun up yet, so
        #                                     forcing long paths to the core
        #                                     would starve build cadence
        current_round = ct.get_current_round()
        avg_ti_income = get_average_titanium_income(ct)
        if not use_core_exclusion:
            self._core_exclusion_radius_sq = 0
            DEBUG and print(f"[ConvAStar] CORE EXCLUSION: disabled by caller flag")
        elif current_round < EARLY_ROUNDS or avg_ti_income < EARLY_TITANIUM_INCOME_THRESHOLD:
            self._core_exclusion_radius_sq = 0
            DEBUG and print(f"[ConvAStar] CORE EXCLUSION: disabled (round={current_round} < {EARLY_ROUNDS} or avg_ti_income={avg_ti_income:.2f} < {EARLY_TITANIUM_INCOME_THRESHOLD})")
        elif ally_core_pos is not None:
            map_w = ct.get_map_width()
            map_h = ct.get_map_height()
            short_side = min(map_w, map_h)
            core_edge_dist = min(
                ally_core_pos.x,
                ally_core_pos.y,
                map_w - 1 - ally_core_pos.x,
                map_h - 1 - ally_core_pos.y,
            )
            exclusion_radius = 16
            self._core_exclusion_radius_sq = exclusion_radius * exclusion_radius
            DEBUG and print(f"[ConvAStar] CORE EXCLUSION: radius={exclusion_radius} (sq={self._core_exclusion_radius_sq}) map={map_w}x{map_h} core={ally_core_pos} core_edge_dist={core_edge_dist}")

        # Determine the actual backward search seed(s).
        # For core: seed from EVERY position cardinally adjacent to the 3×3 core
        #   boundary so the backward search can find the cheapest entry point
        #   regardless of which side of the core the robot is approaching from.
        # For specific dest: seed from dest itself (we don't build there, it receives).
        if dest_pos == ally_core_pos and ally_core_pos is not None:
            all_back_seeds = _all_core_adjacent(ally_core_pos, mm, self.my_team, avoid_enemy)
            if not all_back_seeds:
                DEBUG and print(f"[ConvAStar] PLAN FAILED: no valid core-adjacent cells for core={ally_core_pos}")
                self._exhausted = True
                return
            # Best seed = closest to build_pos; used as heuristic target for the
            # forward search so A* priority estimates remain accurate.
            back_seed = min(
                all_back_seeds,
                key=lambda p: abs(p.x - build_pos.x) + abs(p.y - build_pos.y),
            )
            # Store the actual core pos so reconstruction can point the last
            # conveyor into the core
            self._final_target = ally_core_pos
        else:
            all_back_seeds = [dest_pos]
            back_seed = dest_pos
            self._final_target = dest_pos

        # Fix the dominant axis for the whole search based on the remaining
        # build_pos -> back_seed vector. Using the remaining vector (not the original
        # full source->dest) means replans after partial builds still prefer the
        # correct axis for the actual remaining path, preventing the search from
        # penalising the right direction because the overall vector has shifted.
        sk = (build_pos.x, build_pos.y)
        bk = (back_seed.x, back_seed.y)
        ssk = (source_pos.x, source_pos.y)
        remaining_dx = abs(build_pos.x - dest_pos.x)
        remaining_dy = abs(build_pos.y - dest_pos.y)
        # If perfectly diagonal (equal dx/dy) keep previous dominant axis so a
        # replan mid-path doesn't flip and cause a single staircase step.
        if remaining_dx != remaining_dy:
            self._dominant_horizontal = remaining_dx > remaining_dy
        # else: leave self._dominant_horizontal unchanged from its previous value

        # Seed forward search from build_pos.
        # Use the destination itself (core center, or specific dest) as the heuristic
        # target — NOT the back_seed. back_seed is the closest core-adjacent tile by
        # straight-line distance, but that tile may sit behind a wall. Pointing the
        # heuristic at that specific back_seed causes the forward search to hammer
        # into the wall-blocked quadrant and waste its budget there.
        # The dest/core-center is a valid admissible target: every core-adjacent tile
        # is within 2 manhattan steps of the center, so the heuristic underestimates
        # by at most 2, keeping it admissible while staying wall-agnostic.
        dest_key = (dest_pos.x, dest_pos.y)
        self._f_g[sk] = 0
        h = self._h_weight * (abs(build_pos.x - dest_pos.x) + abs(build_pos.y - dest_pos.y))
        heapq.heappush(self._f_open, (h, self._cnt, sk))
        self._cnt += 1

        # Seed backward search from ALL valid core-adjacent positions (or just dest
        # for non-core targets). Seeding every entry point lets the backward frontier
        # grow toward whichever side the forward frontier approaches, so the meeting
        # cost is minimised without committing to a single core tile upfront.
        # The backward search h_target stays as forward_seed (build_pos) — that IS
        # wall-agnostic from the dest side.
        self._back_seed = dest_key    # now points at dest center, not a wall-biased back_seed
        self._forward_seed = sk
        self._source_seed = ssk

        for seed in all_back_seeds:
            sbk = (seed.x, seed.y)
            if sbk not in self._b_g:
                self._b_g[sbk] = 0
                h = self._h_weight * (abs(seed.x - build_pos.x) + abs(seed.y - build_pos.y))
                heapq.heappush(self._b_open, (h, self._cnt, sbk))
                self._cnt += 1

        DEBUG and print(f"[ConvAStar] PLAN START: build_pos={build_pos} dest={dest_pos} "
                        f"back_seeds={[(s.x, s.y) for s in all_back_seeds]} "
                        f"h_target={dest_key} final_target={self._final_target} "
                        f"isolate={isolate} manhattan_to_dest={abs(build_pos.x - dest_pos.x) + abs(build_pos.y - dest_pos.y)}")
        if DEBUG and NO_INPUT_RECONNECT_ENABLED:
            inputs_sorted = sorted(mm.confirmed_input_positions)
            print(f"[ConvAStar] CONFIRMED_INPUT_POSITIONS ({len(inputs_sorted)}): {inputs_sorted}")

    def is_planned_for_dest(self, dest_pos: Position) -> bool:
        """Check if we have an active plan heading to this destination.

        We only check dest because the source changes as we build along
        the path (each new conveyor becomes the new 'source'). The path
        itself already covers the full route.

        Returns False if the plan was invalidated (path is None and both open
        lists are empty but not exhausted) so that determine() re-calls
        plan_path() with the freshly chosen build_pos.
        """
        if self.dest_pos is None:
            return False
        if self._path is None and self._exhausted:
            return False
        # After invalidate(), path is None and both open lists are empty.
        # Treat this the same as no plan so plan_path() is called fresh.
        if self._path is None and not self._f_open and not self._b_open:
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

        self._turns_expanded += 1
        # After DESPERATE_TURNS turns without a complete path, enter desperate mode:
        # bypass the core exclusion zone check and the use_early_goals flag so the
        # search accepts any receivable belt as an early-goal connection rather than
        # insisting on building all the way to the core.
        desperate = self._turns_expanded >= DESPERATE_TURNS

        if desperate:
            DEBUG and print(f"[ConvAStar] DESPERATE MODE (turn {self._turns_expanded}): ignoring exclusion zone and early-goal flag")

        remaining_cpu = CPU_LIMIT - ct.get_cpu_time_elapsed()
        budget = max(0, remaining_cpu // NODE_COST_EST)
        initial_budget = budget

        DEBUG and print(f"[ConvAStar] EXPAND: cpu_remaining={remaining_cpu} budget={budget} f_open={len(self._f_open)} b_open={len(self._b_open)} f_closed={len(self._f_closed)} b_closed={len(self._b_closed)} best_cost={self._best_cost} meeting={self._meeting_node}")

        mm: MapManager = self.brain.map_manager
        ally_core_pos = mm.ally_core_pos

        # Cache bot position and vision radius for the priority no-input check.
        # A tile outside vision might have an input we just can't see — only
        # treat "not in confirmed_input_positions" as meaningful for tiles
        # strictly inside vision (using vision_radius - 1 as a conservative
        # buffer so we don't get fooled by the fragile outer ring).
        my_pos = ct.get_position()
        vision_sq_raw = ct.get_vision_radius_sq()
        vision_r = int(math.isqrt(vision_sq_raw))
        inner_vision_r = max(0, vision_r - 1)
        self._no_input_vision_sq = inner_vision_r * inner_vision_r
        self._my_pos_x = my_pos.x
        self._my_pos_y = my_pos.y

        while budget > 0:
            # Check termination: best known solution (meeting or early goal).
            # Priority early goals (no-input receivable tiles) always win —
            # reconnecting an orphaned belt is always the right move, so we
            # treat it as the solution cost regardless of meeting/early.
            f_min = self._f_open[0][0] if self._f_open else float('inf')
            b_min = self._b_open[0][0] if self._b_open else float('inf')
            best_solution = min(self._best_cost, self._early_goal_cost,
                                self._priority_early_goal_cost)

            # Only terminate when we actually have a finite solution.
            # Without this guard, if both open lists are empty and no solution
            # has been found (best_solution == inf), min(inf, inf) >= inf is True
            # and we'd call _reconstruct_path with _meeting_node=None, wrongly
            # printing "MEETING CONFIRMED" with cost inf and returning True.
            if best_solution < float('inf') and min(f_min, b_min) >= best_solution:
                if self._priority_early_goal_node is not None:
                    # Priority wins — reconnect into orphaned belt
                    DEBUG and print(f"[ConvAStar] PRIORITY EARLY GOAL (no input): cost={self._priority_early_goal_cost} node={self._priority_early_goal_node} target={self._priority_early_goal_target} f_expanded={self._dbg_f_expanded}")
                    self._early_goal_node = self._priority_early_goal_node
                    self._early_goal_cost = self._priority_early_goal_cost
                    self._early_goal_target = self._priority_early_goal_target
                    self._reconstruct_early_goal(mm)
                elif self._early_goal_cost <= self._best_cost and self._early_goal_node is not None:
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
                # Priority goal (no-input orphan belt) — always promote first.
                if self._priority_early_goal_node is not None:
                    DEBUG and print(f"[ConvAStar] EXHAUSTED: promoting priority early goal at {self._priority_early_goal_node} -> {self._priority_early_goal_target} cost={self._priority_early_goal_cost}")
                    self._early_goal_node = self._priority_early_goal_node
                    self._early_goal_cost = self._priority_early_goal_cost
                    self._early_goal_target = self._priority_early_goal_target
                    self._reconstruct_early_goal(mm)
                    return True
                # If the search found an exclusion-zone-rejected early goal, promote
                # it now as a last resort. This avoids the broken _reset_without_exclusion
                # restart (which re-seeds from a stale source_pos). Meeting has already
                # been ruled out (open lists empty, no finite best_cost), so connecting
                # into a near-core belt is better than giving up entirely.
                if self._fallback_goal_node is not None:
                    DEBUG and print(f"[ConvAStar] EXHAUSTED: promoting fallback early goal at {self._fallback_goal_node} -> {self._fallback_goal_target} cost={self._fallback_goal_cost}")
                    self._early_goal_node = self._fallback_goal_node
                    self._early_goal_cost = self._fallback_goal_cost
                    self._early_goal_target = self._fallback_goal_target
                    self._reconstruct_early_goal(mm)
                    return True
                DEBUG and print(f"[ConvAStar] EXHAUSTED: no path found. f_expanded={self._dbg_f_expanded} b_expanded={self._dbg_b_expanded}")
                self._exhausted = True
                return False

            # Balanced alternation: keep the two frontiers within BALANCE_GAP of
            # each other so neither side can starve. Without this, the backward
            # search (many core-adjacent seeds, each with h = 3 * manhattan to
            # build_pos) routinely races to forward_seed and terminates via
            # meeting before forward expands even once — meaning the forward-only
            # early-goal check in _expand_neighbors never fires near build_pos.
            #
            # Rule: whichever side has fewer expansions goes next; on a tie, fall
            # back to the classic f_min comparison. Empty open lists force the
            # other side regardless.
            f_exp = self._dbg_f_expanded
            b_exp = self._dbg_b_expanded
            if not self._b_open:
                self._expand_one_forward(ct, mm, ally_core_pos, desperate=desperate)
            elif not self._f_open:
                self._expand_one_backward(ct, mm, ally_core_pos)
            elif f_exp < b_exp:
                self._expand_one_forward(ct, mm, ally_core_pos, desperate=desperate)
            elif b_exp < f_exp:
                self._expand_one_backward(ct, mm, ally_core_pos)
            elif f_min <= b_min:
                self._expand_one_forward(ct, mm, ally_core_pos, desperate=desperate)
            else:
                self._expand_one_backward(ct, mm, ally_core_pos)

            budget -= 1

        DEBUG and print(f"[ConvAStar] BUDGET SPENT: used={initial_budget} f_expanded={self._dbg_f_expanded} b_expanded={self._dbg_b_expanded} best_cost={self._best_cost}")
        return False

    def _reset_without_exclusion(self, mm: MapManager) -> None:
        """Reset all search state and re-seed with the exclusion zone disabled.

        Called when the search exhausts with no path while the exclusion zone
        was active. Keeps source_pos/dest_pos/h_weight/dominant_axis intact
        so the retry is a clean restart toward the same destination.
        """
        self._core_exclusion_radius_sq = 0

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
        self._priority_early_goal_cost = float('inf')
        self._priority_early_goal_node = None
        self._priority_early_goal_target = None
        self._path = None
        self._path_index = 0
        self._exhausted = False
        self._dbg_f_expanded = 0
        self._dbg_b_expanded = 0
        self._turns_expanded = 0

        build_pos = self.source_pos
        dest_pos = self.dest_pos
        ally_core_pos = mm.ally_core_pos

        if dest_pos == ally_core_pos and ally_core_pos is not None:
            all_back_seeds = _all_core_adjacent(ally_core_pos, mm, self.my_team, self.avoid_enemy)
            if not all_back_seeds:
                self._exhausted = True
                return
            self._final_target = ally_core_pos
        else:
            all_back_seeds = [dest_pos]
            self._final_target = dest_pos

        sk = (build_pos.x, build_pos.y)
        dest_key = (dest_pos.x, dest_pos.y)

        self._f_g[sk] = 0
        h = self._h_weight * (abs(build_pos.x - dest_pos.x) + abs(build_pos.y - dest_pos.y))
        heapq.heappush(self._f_open, (h, self._cnt, sk))
        self._cnt += 1

        self._back_seed = dest_key
        self._forward_seed = sk

        for seed in all_back_seeds:
            sbk = (seed.x, seed.y)
            if sbk not in self._b_g:
                self._b_g[sbk] = 0
                h = self._h_weight * (abs(seed.x - build_pos.x) + abs(seed.y - build_pos.y))
                heapq.heappush(self._b_open, (h, self._cnt, sbk))
                self._cnt += 1

        DEBUG and print(f"[ConvAStar] FALLBACK RETRY: exclusion disabled, re-seeding from {build_pos} to {dest_pos}")

    def _expand_one_forward(self, ct: Controller, mm: MapManager,
                            ally_core_pos: Position | None,
                            desperate: bool = False) -> None:
        """Expand one node from the forward frontier.

        desperate=True: bypass the core exclusion zone and use_early_goals flag
        so any receivable belt is accepted as an early-goal connection.
        """
        while self._f_open:
            _f, _c, cur = heapq.heappop(self._f_open)
            if cur in self._f_closed:
                continue
            self._f_closed.add(cur)
            self.brain.reachable.tiles.add(cur)
            self._dbg_f_expanded += 1

            g = self._f_g[cur]
            cx, cy = cur

            # Generate neighbors
            self._expand_neighbors(
                cx, cy, g, self._f_g, self._f_from, self._f_closed,
                self._f_open, self._b_g, self._back_seed,
                ct, mm, ally_core_pos, forward=True, desperate=desperate
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
            self.brain.reachable.tiles.add(cur)
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

    def _is_harvester_adj(self, x: int, y: int, mm: MapManager) -> bool:
        """True if (x, y) is cardinally adjacent to a harvester.

        Only checks building_grid — we're looking for placed harvester
        buildings, not roving harvester bots.

        If self.avoid_harvester_ore is set, only harvesters sitting on
        that ore type count (e.g. axionite paths set ORE_TITANIUM so
        they only avoid titanium harvesters, not axionite ones).
        """
        w, h = mm.width, mm.height
        building_grid = mm.building_grid
        tile_grid = mm.tile_grid
        ore_filter = self.avoid_harvester_ore
        for _, dx, dy in CARDINAL_DELTAS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            b = building_grid[nx][ny]
            if b is None or b.entity_type != EntityType.HARVESTER:
                continue
            if ore_filter is not None and tile_grid[nx][ny] is not ore_filter:
                continue
            return True
        return False

    def _expand_neighbors(self, cx: int, cy: int, g: float,
                          my_g: dict, my_from: dict, my_closed: set,
                          my_open: list, other_g: dict,
                          h_target: tuple,
                          ct: Controller, mm: MapManager,
                          ally_core_pos: Position | None,
                          forward: bool,
                          desperate: bool = False) -> None:
        """Expand cardinal (conveyor) and bridge neighbors from (cx, cy).

        desperate=True: bypass use_early_goals flag and core exclusion zone so
        any receivable belt tile is accepted as an early-goal target. Used when
        the search has not found a complete path after DESPERATE_TURNS turns.
        """
        tx, ty = h_target
        w, h = mm.width, mm.height
        dest_key = (self.dest_pos.x, self.dest_pos.y) if self.dest_pos is not None else None

        # Only penalise enemy tiles when enemies are actually visible nearby.
        # If no enemies are in sight there is nothing to avoid.
        has_enemies = bool(
            mm.nearby_enemy_harvester_ids or
            mm.nearby_enemy_conveyor_ids or
            mm.nearby_enemy_bridge_ids or
            mm.nearby_enemy_launcher_ids or
            mm.nearby_enemy_turret_pos
        )
        # In avoid-enemy mode we apply a near-prohibitive penalty regardless
        # of whether enemies are reported nearby — the caller flipped this
        # flag precisely because an enemy was observed, so we should route
        # away from any enemy-owned tile we still know about.
        if self.avoid_enemy:
            enemy_penalty = AVOID_ENEMY_TILE_PENALTY
        elif has_enemies:
            enemy_penalty = ENEMY_TILE_PENALTY
        else:
            enemy_penalty = 0

        # Cardinal neighbors (conveyor edges)
        for direction, dx, dy in CARDINAL_DELTAS:
            nx, ny = cx + dx, cy + dy
            nb = (nx, ny)
            if nb in my_closed:
                continue
            # Axionite mode: skip tiles cardinally adjacent to a harvester, except
            # the dest itself (the chain needs to terminate at a harvester-adjacent
            # conveyor). Bridges can still land on the dest even if it's harvester
            # adjacent; other harvester-adj tiles are blocked for both build and
            # bridge edges.
            if self.avoid_harvester_adjacent and nb != dest_key:
                if self._is_harvester_adj(nx, ny, mm):
                    continue
            if not _tile_buildable(nx, ny, mm, self.storage_tracker,
                                  self.my_team, ally_core_pos,
                                  self.dest_pos, self.isolate):
                # Priority early goal — ALWAYS check first, independent of
                # use_early_goals / desperate / exclusion zone. If nb is a
                # receivable ally belt with no confirmed input, we want to
                # reconnect into it no matter what other flags say.
                # Only trust "no input" when nb is strictly inside vision —
                # outside vision the set is incomplete and we'd otherwise
                # reconnect into a belt that actually has a hidden feeder.
                if NO_INPUT_RECONNECT_ENABLED and forward and nb != self._forward_seed and nb != self._source_seed:
                    dx_v = nx - self._my_pos_x
                    dy_v = ny - self._my_pos_y
                    in_vision = (dx_v * dx_v + dy_v * dy_v) <= self._no_input_vision_sq
                    no_input = in_vision and nb not in mm.confirmed_input_positions
                    if no_input:
                        receivable_priority = _tile_receivable(
                            nx, ny, mm, self.storage_tracker,
                            self.my_team, ally_core_pos,
                            self.dest_pos,
                            isolate=False,
                            ignore_full=False)
                        if receivable_priority and g < self._priority_early_goal_cost:
                            self._priority_early_goal_cost = g
                            self._priority_early_goal_node = (cx, cy)
                            self._priority_early_goal_target = nb
                            DEBUG and print(f"[ConvAStar] PRIORITY EARLY GOAL (no input): ({cx},{cy}) -> ({nx},{ny}) cost={g}")

                # Empty-history ally conveyor/bridge: always accept as early goal
                # regardless of use_early_goals or core exclusion zone. A belt
                # with no resource history has never carried anything and is a
                # free endpoint any chain should connect into.
                if forward and nb != self._forward_seed and nb != self._source_seed:
                    if 0 <= nx < w and 0 <= ny < h:
                        b_rec = mm.building_grid[nx][ny]
                        if (b_rec is not None and b_rec.team == self.my_team
                                and b_rec.entity_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE)):
                            if (not self.storage_tracker.get_recent_resources(b_rec.id)
                                    and self.storage_tracker.confirmed_empty(b_rec.id)):
                                if _tile_receivable(nx, ny, mm, self.storage_tracker,
                                                    self.my_team, ally_core_pos,
                                                    self.dest_pos, isolate=False, ignore_full=False):
                                    if g < self._early_goal_cost:
                                        self._early_goal_cost = g
                                        self._early_goal_node = (cx, cy)
                                        self._early_goal_target = nb
                                        DEBUG and print(f"[ConvAStar] EARLY GOAL (empty history): ({cx},{cy}) -> ({nx},{ny}) cost={g}")

                # Not buildable — but can we OUTPUT to it? (existing ally conveyor)
                # In normal mode, only check when early goals are enabled.
                # In desperate mode (search exceeded DESPERATE_TURNS turns), bypass
                # the use_early_goals flag and the isolate flag so any receivable
                # tile is accepted — we prefer a belt connection over no path at all.
                allow_early = self.use_early_goals or desperate
                if forward and allow_early:
                    # In desperate mode: ignore isolate AND ignore full so any
                    # belt tile is accepted. In normal mode: standard checks apply.
                    receivable = _tile_receivable(
                        nx, ny, mm, self.storage_tracker,
                        self.my_team, ally_core_pos,
                        self.dest_pos,
                        isolate=self.isolate and not desperate,
                        ignore_full=False)

                    if receivable:
                        # Never connect back into our own source — that would build a
                        # conveyor pointing backwards into the tile we started from.
                        if nb == self._forward_seed:
                            continue
                        if nb == self._source_seed:
                            continue

                        # Axionite mode: accept conveyors whose recent resource
                        # history is a subset of {TITANIUM} or a subset of
                        # {RAW_AXIONITE}. A conveyor that has carried BOTH
                        # in the window is already a mixed belt — splicing
                        # more raw axionite in would corrupt foundry math.
                        # Empty history is fine (counts as titanium-side).
                        # Anything else (e.g. refined axionite present) is
                        # also rejected.
                        if self.early_goal_only_titanium:
                            b = mm.building_grid[nx][ny]
                            if b is None or b.entity_type not in CONVEYOR_LIKE:
                                continue
                            recent = self.storage_tracker.get_recent_resources(b.id)
                            ti_only = recent <= {ResourceType.TITANIUM}
                            raw_ax_only = recent <= {ResourceType.RAW_AXIONITE}
                            if not (ti_only or raw_ax_only):
                                continue

                        # Titanium chains must never splice into a raw-axionite
                        # belt — the two streams would mix and corrupt both.
                        # History-based: if the candidate conveyor/bridge has
                        # carried RAW_AXIONITE in the last 15 rounds, treat it
                        # as an axionite belt (smooths over the empty-tick
                        # flicker that a snapshot stored_resource check would
                        # miss).
                        if self.source_resource == ResourceType.TITANIUM:
                            b = mm.building_grid[nx][ny]
                            if b is not None and b.entity_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE):
                                if ResourceType.RAW_AXIONITE in self.storage_tracker.get_recent_resources(b.id):
                                    continue

                        # "no input" is only trustworthy when nb is strictly
                        # inside vision — outside vision confirmed_input_positions
                        # is incomplete and the tile may actually have a hidden
                        # feeder. Gated by NO_INPUT_RECONNECT_ENABLED so the
                        # exclusion zone behaves normally when disabled.
                        if NO_INPUT_RECONNECT_ENABLED:
                            dx_v = nx - self._my_pos_x
                            dy_v = ny - self._my_pos_y
                            in_vision = (dx_v * dx_v + dy_v * dy_v) <= self._no_input_vision_sq
                            no_input = in_vision and nb not in mm.confirmed_input_positions
                        else:
                            no_input = False

                        # Reject early goals inside the core exclusion zone.
                        # In desperate mode this check is skipped entirely — any
                        # receivable tile, even near the core, is accepted.
                        # Also skipped when the candidate has no confirmed
                        # input (orphaned belt — reconnecting is always OK).
                        in_exclusion = False
                        if not desperate and not no_input and ally_core_pos is not None:
                            ddx_t, ddy_t = nx - ally_core_pos.x, ny - ally_core_pos.y
                            ddx_c, ddy_c = cx - ally_core_pos.x, cy - ally_core_pos.y
                            target_dsq = ddx_t * ddx_t + ddy_t * ddy_t
                            cur_dsq    = ddx_c * ddx_c + ddy_c * ddy_c
                            if target_dsq < self._core_exclusion_radius_sq or \
                                    cur_dsq < self._core_exclusion_radius_sq:
                                in_exclusion = True

                        if in_exclusion:
                            DEBUG and print(
                                f"[ConvAStar] EARLY GOAL REJECTED (inside exclusion zone): ({nx},{ny})"
                            )
                            # Cache as fallback (with or without full) — used if
                            # the search exhausts without any better solution.
                            if g < self._fallback_goal_cost:
                                self._fallback_goal_cost = g
                                self._fallback_goal_node = (cx, cy)
                                self._fallback_goal_target = nb
                        else:
                            # Normal early goal — passes both exclusion zone and full check
                            if g < self._early_goal_cost:
                                self._early_goal_cost = g
                                self._early_goal_node = (cx, cy)
                                self._early_goal_target = nb
                                DEBUG and print(f"[ConvAStar] EARLY GOAL CANDIDATE{'(desperate)' if desperate else ''}: ({cx},{cy}) -> receivable ({nx},{ny}) cost={g}")
                continue

            ng = g + CONVEYOR_COST
            building = mm.building_grid[nx][ny]
            if building is not None and building.team != self.my_team:
                ng += BASE_ENEMY_TILE_PENALTY
                if enemy_penalty:
                    ng += enemy_penalty

            if nb not in my_g or ng < my_g[nb]:
                my_g[nb] = ng
                # Store edge info: parent and type
                edge_dir = direction if forward else REVERSE_DIR[direction]
                my_from[nb] = ((cx, cy), 'conv', edge_dir)
                fval = ng + self._h_weight * (abs(nx - tx) + abs(ny - ty))
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
            # Same harvester-adjacent rule as cardinal edges — the bridge lands
            # (and a conveyor may be built) at nb, so the restriction still applies.
            if self.avoid_harvester_adjacent and nb != dest_key:
                if self._is_harvester_adj(nx, ny, mm):
                    continue
            if not _tile_buildable(nx, ny, mm, self.storage_tracker,
                                  self.my_team, ally_core_pos,
                                  self.dest_pos, self.isolate):
                # Priority early goal via bridge: the jump target is an existing
                # ally belt with no confirmed input — build a bridge at (cx,cy)
                # outputting into it. Only trust "no input" when nb is strictly
                # inside vision (confirmed_input_positions is incomplete outside
                # vision).
                if NO_INPUT_RECONNECT_ENABLED and forward and nb != self._forward_seed and nb != self._source_seed:
                    dx_v = nx - self._my_pos_x
                    dy_v = ny - self._my_pos_y
                    in_vision = (dx_v * dx_v + dy_v * dy_v) <= self._no_input_vision_sq
                    no_input = in_vision and nb not in mm.confirmed_input_positions
                    if no_input:
                        receivable_priority = _tile_receivable(
                            nx, ny, mm, self.storage_tracker,
                            self.my_team, ally_core_pos,
                            self.dest_pos,
                            isolate=False,
                            ignore_full=False)
                        if receivable_priority:
                            bridge_manhattan = abs(dx) + abs(dy)
                            priority_cost = g + bridge_manhattan + BRIDGE_PENALTY
                            if priority_cost < self._priority_early_goal_cost:
                                self._priority_early_goal_cost = priority_cost
                                self._priority_early_goal_node = (cx, cy)
                                self._priority_early_goal_target = nb
                                DEBUG and print(f"[ConvAStar] PRIORITY EARLY GOAL via BRIDGE (no input): ({cx},{cy}) -> ({nx},{ny}) cost={priority_cost}")

                # Empty-history ally conveyor/bridge via bridge edge.
                if forward and nb != self._forward_seed and nb != self._source_seed:
                    b_rec = mm.building_grid[nx][ny]
                    if (b_rec is not None and b_rec.team == self.my_team
                            and b_rec.entity_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE)):
                        if (not self.storage_tracker.get_recent_resources(b_rec.id)
                                and self.storage_tracker.confirmed_empty(b_rec.id)):
                            if _tile_receivable(nx, ny, mm, self.storage_tracker,
                                                self.my_team, ally_core_pos,
                                                self.dest_pos, isolate=False, ignore_full=False):
                                bridge_manhattan = abs(dx) + abs(dy)
                                empty_cost = g + bridge_manhattan + BRIDGE_PENALTY
                                if empty_cost < self._early_goal_cost:
                                    self._early_goal_cost = empty_cost
                                    self._early_goal_node = (cx, cy)
                                    self._early_goal_target = nb
                                    DEBUG and print(f"[ConvAStar] EARLY GOAL via BRIDGE (empty history): ({cx},{cy}) -> ({nx},{ny}) cost={empty_cost}")
                continue

            # Skip bridge targets not yet confirmed reachable by nav A*.
            # The reachable set is populated incrementally as the bot moves around.
            # Guard on non-empty so early-game (set still empty) allows all bridges.
            pathing_reachable = self.brain.reachable
            if pathing_reachable and nb not in pathing_reachable:
                continue

            bridge_manhattan = abs(dx) + abs(dy)
            ng = g + bridge_manhattan + BRIDGE_PENALTY
            landing = mm.building_grid[nx][ny]
            if landing is not None and landing.team != self.my_team:
                ng += BASE_ENEMY_TILE_PENALTY
            if nb not in my_g or ng < my_g[nb]:
                my_g[nb] = ng
                my_from[nb] = ((cx, cy), 'bridge', None)
                fval = ng + self._h_weight * (abs(nx - tx) + abs(ny - ty))
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
        raw_chain = forward_chain + backward_chain

        # Deduplicate: both searches may have explored the same tile (especially
        # near the meeting node), causing a node to appear in both forward_chain
        # and backward_chain. This creates a U-turn in the path — e.g.:
        #   forward: [S, A, B, M]  backward: [B, C, T]
        #   raw:     [S, A, B, M, B, C, T]  — B appears twice, M→B is a loop
        # Keeping only the first occurrence of each node removes the U-turn:
        #   deduped: [S, A, B, M, C, T]  — M now points correctly to C
        seen: set = set()
        full_chain = []
        for node in raw_chain:
            if node not in seen:
                seen.add(node)
                full_chain.append(node)

        DEBUG and print(f"[ConvAStar] RAW CHAIN ({len(raw_chain)} nodes): {raw_chain}")
        if len(full_chain) != len(raw_chain):
            DEBUG and print(f"[ConvAStar] DEDUPED CHAIN ({len(full_chain)} nodes, removed {len(raw_chain) - len(full_chain)} duplicates): {full_chain}")

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

    def get_path_dest(self) -> Position | None:
        """Return the tile the last build step outputs into — i.e. where
        the chain physically terminates. For early-goal connections this
        differs from self.dest_pos (the originally-requested dest), since
        the last step splices into an existing ally belt instead.

        Returns None if no path is built yet.
        """
        if not self._path:
            return None
        last = self._path[-1]
        if last.build_type == EntityType.BRIDGE:
            return last.bridge_target
        dx, dy = last.direction.delta()
        return Position(last.pos.x + dx, last.pos.y + dy)

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
        # Guard: plan_path hasn't been called yet
        if self._back_seed is None or self._forward_seed is None or self._source_seed is None:
            return

        DEBUG and print(f"[ConvAStar] NEWLY SEEN: {len(newly_seen)} tiles, reopening frontiers")

        f_before = len(self._f_open)
        b_before = len(self._b_open)

        # Re-open forward closed nodes adjacent to newly seen
        self._reopen_direction(newly_seen, self._f_g, self._f_closed,
                               self._f_open, self._back_seed, mm)
        # Re-open backward closed nodes adjacent to newly seen
        self._reopen_direction(newly_seen, self._b_g, self._b_closed,
                               self._b_open, self._forward_seed, mm)

        # Only clear the exhausted flag if nodes were actually reopened.
        # If nothing was added, the search state is unchanged — leaving
        # _exhausted=True lets determine() detect and trigger a fresh plan_path.
        if len(self._f_open) > f_before or len(self._b_open) > b_before:
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
                    fval = g_map[nb] + self._h_weight * (abs(nx - tx) + abs(ny - ty))
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

        # Peek one step ahead: if the next step in the path is no longer
        # buildable, the current step effectively becomes the last one.
        # - If the next pos is receivable (ally conveyor appeared there), truncate
        #   the path here so the current step is validated as a last step.
        # - If it's neither buildable nor receivable, the path is broken — fail now
        #   rather than wasting a turn building a conveyor pointing the wrong way.
        is_last_step = self._path_index == len(self._path) - 1
        if not is_last_step:
            next_step = self._path[self._path_index + 1]
            nx, ny = next_step.pos.x, next_step.pos.y
            if not _tile_buildable(nx, ny, mm, self.storage_tracker,
                                   self.my_team, mm.ally_core_pos,
                                   self.dest_pos, self.isolate):
                # ignore_full=True: a full conveyor that appeared at the next
                # tile is still a valid truncation target — better to connect
                # into it than to invalidate and loop.
                if _tile_receivable(nx, ny, mm, self.storage_tracker,
                                    self.my_team, mm.ally_core_pos,
                                    self.dest_pos, self.isolate,
                                    ignore_full=True):
                    # Truncate: current step is now the last, pointing at (nx,ny)
                    self._path = self._path[:self._path_index + 1]
                    is_last_step = True
                    DEBUG and print(
                        f"[ConvAStar] PATH TRUNCATED at step {self._path_index}: "
                        f"next pos ({nx},{ny}) already occupied but receivable"
                    )
                else:
                    DEBUG and print(
                        f"[ConvAStar] VALIDATE FAIL lookahead: next pos ({nx},{ny}) "
                        f"not buildable or receivable"
                    )
                    return False

        # For the LAST step, validate that what it points at is still receivable.
        # Use ignore_full=True so that a path planned to connect into a full
        # conveyor (fallback) isn't invalidated just because it's full — that
        # would cause an infinite replan loop.
        if is_last_step:
            if step.build_type == EntityType.CONVEYOR and step.direction is not None:
                # Check the tile this conveyor would point at
                ddx, ddy = step.direction.delta()
                tx, ty = x + ddx, y + ddy
                # If the target IS the planned dest, skip the receivable check —
                # the dest was pre-validated by the caller. Harvester-adjacent
                # conveyors (axionite targets) point into harvesters and fail
                # _tile_receivable, but they are valid connection targets.
                is_dest = self.dest_pos is not None and tx == self.dest_pos.x and ty == self.dest_pos.y
                if not is_dest and not _tile_receivable(tx, ty, mm, self.storage_tracker,
                                       self.my_team, mm.ally_core_pos,
                                       self.dest_pos, self.isolate,
                                       ignore_full=True):
                    building = mm.building_grid[tx][ty] if 0 <= tx < mm.width and 0 <= ty < mm.height else None
                    DEBUG and print(f"[ConvAStar] VALIDATE FAIL last conv target ({tx},{ty}): building={building.entity_type if building else None} team={'ally' if building and building.team == self.my_team else 'enemy' if building else 'none'}")
                    return False
            elif step.build_type == EntityType.BRIDGE and step.bridge_target is not None:
                tx, ty = step.bridge_target.x, step.bridge_target.y
                # Same dest exemption: skip receivable check when pointing at dest.
                is_dest = self.dest_pos is not None and tx == self.dest_pos.x and ty == self.dest_pos.y
                if not is_dest and not _tile_receivable(tx, ty, mm, self.storage_tracker,
                                       self.my_team, mm.ally_core_pos,
                                       self.dest_pos, self.isolate,
                                       ignore_full=True):
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
        self._fallback_goal_cost = float('inf')
        self._fallback_goal_node = None
        self._fallback_goal_target = None
        self._priority_early_goal_cost = float('inf')
        self._priority_early_goal_node = None
        self._priority_early_goal_target = None
        self._f_open = []
        self._f_g = {}
        self._f_from = {}
        self._f_closed = set()
        self._b_open = []
        self._b_g = {}
        self._b_from = {}
        self._b_closed = set()
        self._exhausted = False
        # Pre-arm desperate mode: the previous plan failed, so the replan should
        # immediately accept early-goal belt connections without waiting 7 turns.
        self._turns_expanded = DESPERATE_TURNS