"""
A* pathing — incremental, free-space-assumption A*.

Architecture (much simpler than the previous incremental + exploration design):

  1. The single biggest change: **unseen tiles are treated as passable**
     during A* expansion (with a small UNSEEN_PENALTY so known terrain is
     preferred when equally direct).  This means A* can plan a complete
     path to a target outside vision range immediately, instead of
     getting stuck at the vision boundary and needing a separate
     "exploration" search.

  2. A* runs incrementally across turns:
       - On target change (or path invalidation), the search is reset and
         seeded from the bot's current position.
       - Otherwise expansion resumes where it left off, sharing CPU with
         the rest of the bot's logic via NODE_COST budgeting.
       - Once a goal-adjacent tile is found, the path is reconstructed
         once and cached as a list of (x,y) tuples.

  3. Each turn the cached path is validated:
       - Sync the bot's current position to a tile in the path (handles
         the bot drifting one tile via sidestep).
       - Scan the remaining path for newly-revealed walls or blocking
         buildings.  If anything along the path is now blocked, reset
         and replan.

  4. When following the path, the next tile is taken if free.  If a
     higher-priority ally bot occupies it, the bot sidesteps off the
     path.  If A* hasn't yet found the goal, the bot greedy-steps using
     the current g-wavefront as a hint.

  5. Truly unreachable targets (extremely rare with unseen-as-passable)
     fall through to the greedy step which moves toward the target
     best-effort.

Indicator colours:
  Pink   (255,100,255) — bot -> target
  Green  (0,255,0)     — following A* path
  Yellow (255,255,0)   — greedy fallback
  Orange (255,150,0)   — sidestepping for higher-priority ally
"""

from __future__ import annotations

import heapq

from cambc import Direction, Position, EntityType, Environment
from debug.indicators import draw_move_direction, draw_blocked_tile
from debug.profiling import cputimer
from helpers.directions import DIRECTIONS
from map.map_manager import MapManager


# ── Configuration ────────────────────────────────────────────────────────────

DEBUG = False

# Estimated CPU cost per A* node expansion (microseconds).
NODE_COST = 40
# Total CPU time available per turn (microseconds; round budget is ~2000).
CPU_LIMIT = 1800

# Heuristic weight for weighted A*.  W > 1 makes the search greedier and
# prefers tiles closer to the target, sacrificing optimality for speed.
H_WEIGHT = 4

# Penalty for stepping onto an empty (no building) tile — encourages
# routing through existing infrastructure when convenient.
EMPTY_PENALTY = 2

# Penalty for stepping onto an unseen tile — keeps A* preferring known
# terrain when paths are equally direct, but does NOT block planning
# through fog.  This is the key change vs. the old design.
UNSEEN_PENALTY = 1

# Penalty for stepping onto a tile occupied by a lower-id ally bot we
# would normally yield to.  Heavy enough that A* routes around them
# when possible without making them hard blockers.
BOT_PENALTY = 10

# Building types whose presence on the cached path triggers a replan.
BLOCKING_BUILDING_TYPES = frozenset({
    EntityType.HARVESTER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.GUNNER,
    EntityType.LAUNCHER,
    EntityType.BARRIER,
})

# Cached for hot-loop comparison.
WALL = Environment.WALL

# Precomputed direction deltas to avoid repeated d.delta() calls.
DELTAS = [(d, *d.delta()) for d in DIRECTIONS]


# ── Pathing ──────────────────────────────────────────────────────────────────

class Pathing:
    """Incremental weighted-A* pathing with free-space assumption.

    Public API:
      - ``Pathing(ct)``                                      — constructor
      - ``path_to(ct, mm, my_pos, target, move_fn, pass_fn)`` — main entry
      - ``current_target``                                   — current goal
      - ``_reachable``                                       — set of (x,y)
            tuples ever settled by A* (kept for forward compat / debug)
    """

    def __init__(self, ct) -> None:
        self.current_target: Position | None = None

        # A* search state (cleared on reset)
        self._open: list = []          # min-heap: (f, tiebreak, (x,y))
        self._cnt: int = 0             # monotonic tiebreaker
        self._g: dict = {}             # (x,y) -> best known g-cost
        self._from: dict = {}          # (x,y) -> parent (x,y)
        self._closed: set = set()      # tiles already expanded
        self._found: bool = False
        self._goal_key: tuple | None = None  # adjacent-to-target tile

        # Cached reconstructed path (built once when goal is found).
        self._path: list[tuple[int, int]] = []
        self._pidx: int = 0            # index of bot's current tile in _path

        # Persistent across resets — every tile A* has ever settled.
        # Not currently consumed externally, but cheap to maintain.
        self._reachable: set = set()

    # ── Reset ────────────────────────────────────────────────────────────

    def reset(self, ct, my_pos: Position, target: Position | None) -> None:
        """Restart A* from *my_pos*.  ``_reachable`` is preserved."""
        DEBUG and print(f"[A*] RESET from {my_pos}, target={target}")
        self.current_target = target
        self._open = []
        self._cnt = 0
        self._g = {}
        self._from = {}
        self._closed = set()
        self._found = False
        self._goal_key = None
        self._path = []
        self._pidx = 0

        if my_pos is not None and target is not None:
            s = (my_pos.x, my_pos.y)
            self._g[s] = 0
            h = H_WEIGHT * max(abs(my_pos.x - target.x), abs(my_pos.y - target.y))
            heapq.heappush(self._open, (h, self._cnt, s))
            self._cnt += 1

    # ── A* expansion ─────────────────────────────────────────────────────

    def _expand(self, ct, mm: MapManager, target: Position, pass_fn,
                budget: int) -> tuple[bool, int]:
        """Expand up to *budget* nodes.  Return (goal_reached, nodes_used).

        Unseen tiles are treated as passable with UNSEEN_PENALTY.  Walls
        are hard-blocked.  Other seen tiles defer to *pass_fn*.
        """
        w, h = mm.width, mm.height
        tx, ty = target.x, target.y
        g_map = self._g
        from_map = self._from
        open_list = self._open
        closed = self._closed
        reachable = self._reachable
        bld_grid = mm.building_grid
        tile_grid = mm.tile_grid
        bot_grid = mm.bot_grid
        my_id = ct.get_id()
        my_team = ct.get_team()
        expanded = 0

        while open_list and budget > 0:
            _f, _c, cur = heapq.heappop(open_list)
            if cur in closed:
                continue
            closed.add(cur)
            reachable.add(cur)
            budget -= 1
            expanded += 1

            DEBUG and draw_blocked_tile(ct, Position(cur[0], cur[1]), 255, 50, 50)

            cx, cy = cur
            # Goal: any tile chebyshev-adjacent to the target.
            if max(abs(cx - tx), abs(cy - ty)) <= 1:
                self._found = True
                self._goal_key = cur
                DEBUG and print(f"[A*] GOAL at {cur} after {expanded} expansions")
                return True, expanded

            g = g_map[cur]
            for _d, dx, dy in DELTAS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                nb = (nx, ny)
                if nb in closed:
                    continue

                # Free-space assumption: unseen tiles are passable.
                tile = tile_grid[nx][ny]
                if tile is None:
                    step = 1 + UNSEEN_PENALTY
                elif tile == WALL:
                    continue
                else:
                    if not pass_fn(ct, Position(nx, ny), mm):
                        continue
                    step = 1 + (EMPTY_PENALTY if bld_grid[nx][ny] is None else 0)

                # Soft penalty for tiles held by ally bots we'd yield to,
                # so A* routes around them when possible.
                other = bot_grid[nx][ny]
                if (other is not None and other.team == my_team
                        and my_id > other.id):
                    step += BOT_PENALTY

                ng = g + step
                if nb not in g_map or ng < g_map[nb]:
                    g_map[nb] = ng
                    from_map[nb] = cur
                    f = ng + H_WEIGHT * max(abs(nx - tx), abs(ny - ty))
                    heapq.heappush(open_list, (f, self._cnt, nb))
                    self._cnt += 1

        DEBUG and print(f"[A*] expanded {expanded}, open={len(open_list)}")
        return False, expanded

    # ── Path reconstruction ──────────────────────────────────────────────

    def _build_path(self) -> None:
        """Rebuild ``_path`` from ``_goal_key`` back through ``_from``."""
        self._path = []
        self._pidx = 0
        if not self._found or self._goal_key is None:
            return

        chain: list[tuple[int, int]] = []
        cur: tuple | None = self._goal_key
        seen: set = set()
        while cur is not None:
            if cur in seen:
                # Cycle safety; shouldn't happen with consistent _from.
                self._path = []
                return
            seen.add(cur)
            chain.append(cur)
            cur = self._from.get(cur)
        chain.reverse()
        self._path = chain

    def _sync_path(self, bk: tuple) -> bool:
        """Find the bot's tile in ``_path`` and update ``_pidx``.

        Fast path: check the current pidx and a couple of neighbours.
        Falls back to a full scan.  Returns False if the bot has drifted
        off the path entirely.
        """
        path = self._path
        plen = len(path)
        if plen == 0:
            return False

        # Most common case — bot is at pidx, pidx+1, pidx-1, or pidx+2.
        for di in (0, 1, -1, 2):
            i = self._pidx + di
            if 0 <= i < plen and path[i] == bk:
                self._pidx = i
                return True

        # Full scan fallback.
        for i in range(plen):
            if path[i] == bk:
                self._pidx = i
                return True
        return False

    def _path_invalidated(self, mm: MapManager) -> bool:
        """Return True if any tile in the remaining path is now blocked."""
        bld_grid = mm.building_grid
        tile_grid = mm.tile_grid
        path = self._path
        for i in range(self._pidx + 1, len(path)):
            x, y = path[i]
            if tile_grid[x][y] == WALL:
                return True
            b = bld_grid[x][y]
            if b is not None and b.entity_type in BLOCKING_BUILDING_TYPES:
                return True
        return False

    # ── Greedy fallback ──────────────────────────────────────────────────

    def _greedy_step(self, ct, mm: MapManager, my_pos: Position,
                     target: Position, pass_fn) -> Position | None:
        """Best-effort neighbour toward target.

        Uses the existing g-wavefront if the neighbour was reached by A*;
        otherwise scores it by raw heuristic distance.  Skips tiles
        blocked by bots and tiles failing the strict pass_fn (since
        we're about to actually step there).
        """
        w, h = mm.width, mm.height
        tx, ty = target.x, target.y
        g_map = self._g
        bot_grid = mm.bot_grid
        best: Position | None = None
        best_score = float('inf')

        for _d, dx, dy in DELTAS:
            nx, ny = my_pos.x + dx, my_pos.y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if bot_grid[nx][ny] is not None:
                continue
            npos = Position(nx, ny)
            if not pass_fn(ct, npos, mm):
                continue

            h_val = max(abs(nx - tx), abs(ny - ty))
            nb = (nx, ny)
            if nb in g_map:
                score = g_map[nb] + H_WEIGHT * h_val
            else:
                # Off-wavefront tiles are deprioritised but still legal.
                score = H_WEIGHT * h_val + 100

            if score < best_score:
                best_score = score
                best = npos

        return best

    # ── Sidestep (yield to higher-priority ally) ─────────────────────────

    def _sidestep(self, ct, mm: MapManager, my_pos: Position,
                  pass_fn, move_fn) -> Direction | None:
        """Step off the path so a higher-priority ally can pass.

        Picks the passable neighbour NOT on the path that's closest to
        path[pidx + 2] (the tile after the blocked one), so the bot
        stays oriented along the route.
        """
        w, h = mm.width, mm.height
        path = self._path
        plen = len(path)
        # The next few path tiles we want to keep clear / aim back to.
        path_set = set(path[self._pidx:self._pidx + 3])

        # Aim toward path[pidx + 2] if available, otherwise the next or last.
        if self._pidx + 2 < plen:
            ax, ay = path[self._pidx + 2]
        elif self._pidx + 1 < plen:
            ax, ay = path[self._pidx + 1]
        else:
            ax, ay = path[-1]

        best_d: Direction | None = None
        best_dist = 1_000_000_000

        for d, dx, dy in DELTAS:
            px, py = my_pos.x + dx, my_pos.y + dy
            if not (0 <= px < w and 0 <= py < h):
                continue
            if (px, py) in path_set:
                continue
            if mm.bot_grid[px][py] is not None:
                continue
            if not pass_fn(ct, Position(px, py), mm):
                continue

            dist = max(abs(px - ax), abs(py - ay))
            if dist < best_dist:
                best_dist = dist
                best_d = d

        if best_d is not None:
            DEBUG and draw_move_direction(ct, my_pos, my_pos.add(best_d),
                                          255, 150, 0)
            move_fn(ct, best_d)
            return best_d
        return None

    # ── Main entry point ─────────────────────────────────────────────────

    @cputimer
    def path_to(
        self,
        ct,
        map_manager: MapManager,
        my_pos: Position,
        target: Position,
        move_function,
        passability_function,
    ) -> Direction | None:
        DEBUG and draw_move_direction(ct, my_pos, target, 255, 100, 255)

        if my_pos == target:
            return None

        can_move = ct.get_move_cooldown() == 0

        # Adjacent → step directly, no search needed.
        if can_move and max(abs(my_pos.x - target.x),
                            abs(my_pos.y - target.y)) <= 1:
            d = my_pos.direction_to(target)
            DEBUG and print(f"[A*] ADJACENT step dir={d}")
            move_function(ct, d)
            return d

        # Target change → fresh search rooted at the bot.
        if self.current_target is None or target != self.current_target:
            DEBUG and print(f"[A*] TARGET CHANGED {self.current_target} -> {target}")
            self.reset(ct, my_pos, target)

        bk = (my_pos.x, my_pos.y)

        # ── Validate cached path (if any) ──
        path_valid = False
        if self._found and self._path:
            path_valid = self._sync_path(bk)
            if not path_valid:
                # Bot drifted off path (sidestep last turn etc.) — replan.
                DEBUG and print(f"[A*] off-path at {bk}, reset")
                self.reset(ct, my_pos, target)
            elif self._path_invalidated(map_manager):
                DEBUG and print("[A*] path invalidated by new walls/buildings, reset")
                self.reset(ct, my_pos, target)
                path_valid = False

        # ── Continue / start A* expansion until goal is found ──
        if not self._found:
            budget = max(0, (CPU_LIMIT - ct.get_cpu_time_elapsed()) // NODE_COST)
            if budget > 0:
                self._expand(ct, map_manager, target,
                             passability_function, budget)
            if self._found:
                self._build_path()
                path_valid = self._sync_path(bk)

        # On cooldown — expansion work is done, return early.
        if not can_move:
            return None

        # ── Follow the cached path ──
        if path_valid and self._pidx + 1 < len(self._path):
            nx, ny = self._path[self._pidx + 1]
            nxt = Position(nx, ny)
            other = map_manager.bot_grid[nx][ny]

            if other is not None:
                # Yield to higher-priority ally bot via sidestep.
                if (other.team == ct.get_team()
                        and ct.get_id() > other.id):
                    DEBUG and print(f"[A*] yield to ally id={other.id}, sidestep")
                    result = self._sidestep(ct, map_manager, my_pos,
                                            passability_function, move_function)
                    if result is not None:
                        return result
                # Else: fall through to greedy (try a different direction).
            elif passability_function(ct, nxt, map_manager):
                d = my_pos.direction_to(nxt)
                DEBUG and print(f"[A*] FOLLOW -> {nxt} dir={d}")
                DEBUG and draw_move_direction(ct, my_pos, nxt, 0, 255, 0)
                move_function(ct, d)
                return d
            else:
                # Tile became impassable since we planned (e.g., a new
                # building was placed).  Replan from scratch.
                DEBUG and print(f"[A*] next tile {nxt} not passable, reset")
                self.reset(ct, my_pos, target)

        # ── Greedy fallback (no path yet, or path stalled) ──
        nxt = self._greedy_step(ct, map_manager, my_pos, target,
                                passability_function)
        if nxt is not None:
            d = my_pos.direction_to(nxt)
            DEBUG and print(f"[A*] GREEDY -> {nxt} dir={d}")
            DEBUG and draw_move_direction(ct, my_pos, nxt, 255, 255, 0)
            move_function(ct, d)
            return d

        DEBUG and print(f"[A*] WAITING: no move available from {my_pos}")
        return None
