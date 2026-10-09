"""
A* pathing system with bug-nav hybrid — incremental, multi-turn computation
with bot injection and wall-following fallback.

Architecture:
  1. On target change, A* initialises from the bot's current position.
  2. Each turn, the bot's current position is injected into the open set
     with g=0, making it a fresh search root.  The heap self-balances:
     if the bot is closer (h-wise) to the target than the old frontier,
     expansion shifts to the bot's area; otherwise the old frontier
     keeps progressing undisturbed.
  3. While A* is still searching, the bot moves greedily toward the target.
  4. Once A* finds a tile adjacent to the target, the path is reconstructed
     on demand each turn by tracing the _from chain from the goal tile
     back to the bot's current position.  If the chain doesn't yet
     connect (re-expansion from the bot hasn't reached it), the bot
     moves greedily while expansion continues.
  5. If the open set is exhausted (target unreachable in known terrain),
     the bot moves toward the closest vision-boundary tile to explore.
  6. The *reachable* set (every tile ever settled) persists across resets.
  7. If partial-step movement oscillates (no distance progress over
     recent turns), bug navigation (wall-following) takes over until
     the bot gets past the obstacle, then A* resumes.

  No separate reconnect search is needed -- bot injection naturally keeps
  the search graph connected to the bot's actual position, and on-demand
  path reconstruction adapts each turn.

Indicator colours:
  Pink    (255,100,255) — bot -> target (always)
  Green   (0,255,0)     — following A* path
  Yellow  (255,255,0)   — greedy fallback
  Cyan    (0,200,255)   — exploration movement
  Orange  (255,150,0)   — dodging builder bot
  Purple  (200,0,200)   — bug nav wall following
"""

from __future__ import annotations

import heapq
from cambc import Direction, Position, EntityType
from debug.indicators import draw_move_direction, draw_blocked_tile
from debug.profiling import cputimer
from map.map_manager import MapManager
from vision.launcher_tracker import LauncherTracker

from nav.config import (
    DEBUG, NODE_COST, CPU_LIMIT, H_WEIGHT, EMPTY_PENALTY, BOT_PENALTY,
    BLOCKING_BUILDING_TYPES,
)
from nav.explore_astar import ExploreAStar
from nav.bug_nav import BugNav


# ── Helpers ──────────────────────────────────────────────────────────────────

def _adjacent_xy(ax: int, ay: int, bx: int, by: int) -> bool:
    return max(abs(ax - bx), abs(ay - by)) <= 1


# ── Pathing ──────────────────────────────────────────────────────────────────

class Pathing:
    def __init__(self, ct, launcher_tracker: LauncherTracker | None = None) -> None:
        self.current_target: Position | None = None
        self.launcher_tracker: LauncherTracker | None = launcher_tracker

        pos = ct.get_position()
        center_dir = pos.direction_to(
            Position(ct.get_map_width() // 2, ct.get_map_height() // 2))
        if center_dir == Direction.CENTRE:
            center_dir = Direction.NORTH
        left, right = center_dir, center_dir
        dirs = [center_dir]
        for _ in range(3):
            left = left.rotate_left()
            dirs.append(left)
            right = right.rotate_right()
            dirs.append(right)
        # After 3 iterations both sides meet at the opposite direction
        dirs.append(left.rotate_left())
        self._deltas = [(d, *d.delta()) for d in dirs]

        # A* state (cleared on reset)
        self._open: list = []       # min-heap: (f, tiebreak, (x,y))
        self._cnt: int = 0          # monotonic tiebreaker
        self._g: dict = {}          # (x,y) -> best known g-cost
        self._from: dict = {}       # (x,y) -> parent (x,y)
        self._closed: set = set()   # tiles already expanded

        # Persistent across resets
        self._reachable: set = set()

        # Goal state
        self._found: bool = False
        self._exhausted: bool = False
        self._goal_key: tuple | None = None  # (x,y) tile adjacent to target
        self._seed_key: tuple | None = None  # where A* was seeded from

        # Exploration A* (for pathing to boundary tiles through obstacles)
        self._explore: ExploreAStar | None = None
        self._explore_failed: set = set()  # explore tiles that were unreachable

        # Bug navigation
        self._bug = BugNav()

    # ── Reset ────────────────────────────────────────────────────────────

    def reset(self, ct, my_pos: Position, target: Position | None) -> None:
        """Restart A* from *my_pos*.  The reachable set is preserved."""
        DEBUG and print(f"[A*] RESET from {my_pos}, target={target}, reachable={len(self._reachable)}")
        self.current_target = target
        self._open = []
        self._cnt = 0
        self._g = {}
        self._from = {}
        self._closed = set()
        # self._reachable is intentionally kept
        self._found = False
        self._exhausted = False
        self._goal_key = None
        self._explore = None
        self._explore_failed = set()

        # Reset bug nav on target change
        self._bug.reset()

        if my_pos is not None and target is not None:
            s = (my_pos.x, my_pos.y)
            self._seed_key = s
            self._g[s] = 0
            h = H_WEIGHT * max(abs(my_pos.x - target.x), abs(my_pos.y - target.y))
            heapq.heappush(self._open, (h, self._cnt, s))
            self._cnt += 1

    # ── Incremental re-open ────────────────────────────────────────────

    def _reopen(self, ct, mm: MapManager, my_pos: Position,
                target: Position, pass_fn) -> None:
        """Re-open the frontier around newly-discovered tiles.

        Instead of a full reset, find closed tiles that border newly-seen
        tiles and re-inject them into the open set.  All old _g, _from,
        and _closed data is preserved — only the boundary is re-expanded.

        Also injects the bot's current position with g=0 so the _from
        chain stays connected to the bot.
        """
        newly_seen = mm.newly_seen
        if not newly_seen:
            return

        w, h = mm.width, mm.height
        tx, ty = target.x, target.y
        g_map = self._g
        closed = self._closed

        reopened = 0
        for sx, sy in newly_seen:
            # Check neighbors of each newly-seen tile
            for _d, dx, dy in self._deltas:
                nx, ny = sx + dx, sy + dy
                nb = (nx, ny)
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                # Re-open closed tiles that border new terrain
                if nb in closed and nb in g_map:
                    closed.discard(nb)
                    f = g_map[nb] + H_WEIGHT * max(abs(nx - tx), abs(ny - ty))
                    heapq.heappush(self._open, (f, self._cnt, nb))
                    self._cnt += 1
                    reopened += 1

        # Inject bot position so _from chains connect back
        bk = (my_pos.x, my_pos.y)
        if bk not in g_map or g_map[bk] > 0:
            g_map[bk] = 0
            self._from.pop(bk, None)
            closed.discard(bk)
            f = H_WEIGHT * max(abs(my_pos.x - tx), abs(my_pos.y - ty))
            heapq.heappush(self._open, (f, self._cnt, bk))
            self._cnt += 1

        self._exhausted = False
        self._explore = None
        self._explore_failed = set()
        DEBUG and print(f"[A*] REOPEN: {reopened} tiles reopened, {len(newly_seen)} newly seen")

    # ── A* expansion ─────────────────────────────────────────────────────

    def _expand(self, ct, mm: MapManager, target: Position, pass_fn,
                budget: int = 0) -> tuple[bool, int]:
        """Expand up to *budget* nodes.  Return (goal_reached, nodes_used)."""
        w, h = mm.width, mm.height
        tx, ty = target.x, target.y
        expanded = 0
        g_map = self._g
        from_map = self._from
        open_list = self._open
        closed = self._closed
        reachable = self._reachable
        bld_grid = mm.building_grid
        my_id = ct.get_id()
        my_team = ct.get_team()

        while open_list and budget > 0:
            _f, _c, cur = heapq.heappop(open_list)
            if cur in closed:
                continue
            closed.add(cur)

            reachable.add(cur)
            budget -= 1
            expanded += 1

            # Red dot: A* expansion
            DEBUG and draw_blocked_tile(ct, Position(cur[0], cur[1]), 255, 50, 50)

            cx, cy = cur
            if _adjacent_xy(cx, cy, tx, ty):
                self._found = True
                self._goal_key = cur
                DEBUG and print(f"[A*] GOAL REACHED at {cur} after {expanded} exp this turn")
                return True, expanded

            g = g_map[cur]
            for _d, dx, dy in self._deltas:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                nb = (nx, ny)
                if nb in closed:
                    continue
                if not pass_fn(ct, Position(nx, ny), mm):
                    continue

                ng = g + 1 + (EMPTY_PENALTY if bld_grid[nx][ny] is None else 0)
                other = mm.bot_grid[nx][ny]
                if other is not None and (other.team != my_team or my_id > other.id):
                    ng += BOT_PENALTY
                if nb not in g_map or ng < g_map[nb]:
                    g_map[nb] = ng
                    from_map[nb] = cur
                    f = ng + H_WEIGHT * max(abs(nx - tx), abs(ny - ty))
                    heapq.heappush(open_list, (f, self._cnt, nb))
                    self._cnt += 1

        if not open_list:
            self._exhausted = True
            DEBUG and print(f"[A*] FRONTIER EXHAUSTED reachable={len(reachable)}")

        DEBUG and print(f"[A*] expanded {expanded}, open={len(open_list)}")
        return False, expanded

    # ── Partial path following ───────────────────────────────────────────

    def _best_partial_step(self, ct, mm: MapManager, my_pos: Position,
                           target: Position, pass_fn) -> Position | None:
        """While A* is computing, pick the best passable neighbor using _g data.

        Prefers wavefront tiles (neighbors in _g) scored by g + h.
        Falls back to pure greedy (h only) if no wavefront neighbor exists.
        """
        w, h = mm.width, mm.height
        tx, ty = target.x, target.y
        g_map = self._g
        my_id = ct.get_id()
        my_team = ct.get_team()
        best_wave = None
        best_wave_score = float('inf')
        best_greedy = None
        best_greedy_score = float('inf')

        for _d, dx, dy in self._deltas:
            nx, ny = my_pos.x + dx, my_pos.y + dy
            nb = (nx, ny)
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if not pass_fn(ct, Position(nx, ny), mm):
                continue

            h_val = H_WEIGHT * max(abs(nx - tx), abs(ny - ty))
            bot_pen = 0
            other = mm.bot_grid[nx][ny]
            if other is not None and (other.team != my_team or my_id > other.id):
                bot_pen = BOT_PENALTY

            if nb in g_map:
                score = g_map[nb] + h_val + bot_pen
                if score < best_wave_score:
                    best_wave_score = score
                    best_wave = Position(nx, ny)
            else:
                score = h_val + bot_pen
                if score < best_greedy_score:
                    best_greedy_score = score
                    best_greedy = Position(nx, ny)

        return best_wave if best_wave is not None else best_greedy

    # ── Path reconstruction ──────────────────────────────────────────────

    def _reconstruct(self, from_key: tuple,
                     to_key: tuple) -> list[tuple] | None:
        """Trace _from from *from_key* backward toward *to_key*.

        Returns the path as a list of (x,y) tuples ordered from *to_key*
        (or nearest adjacent tile) to *from_key*.  If the chain reaches
        to_key exactly, that's used.  Otherwise, the chain tile closest
        to to_key (within 1 tile) is used as the start.
        """
        # Build the full chain from goal back to root
        chain = [from_key]
        cur = from_key
        seen = {from_key}
        while cur in self._from:
            cur = self._from[cur]
            if cur in seen:
                return None  # cycle safety
            seen.add(cur)
            chain.append(cur)
            if cur == to_key:
                chain.reverse()
                return chain

        # Chain didn't reach to_key exactly.
        # Find the chain tile nearest to to_key (prefer adjacent).
        bx, by = to_key
        best_idx = -1
        best_dist = 100_000_000
        for i, (cx, cy) in enumerate(chain):
            d = max(abs(cx - bx), abs(cy - by))
            if d < best_dist:
                best_dist = d
                best_idx = i

        # Only use if bot is adjacent to (or on) a chain tile
        if best_dist <= 1 and best_idx >= 0:
            result = chain[:best_idx + 1]
            result.reverse()
            # Prepend bot position if not already first
            if result[0] != to_key:
                result.insert(0, to_key)
            return result

        return None

    # ── Checks ───────────────────────────────────────────────────────────

    def _path_has_blocker(self, path: list[tuple],
                          mm: MapManager) -> bool:
        """Return True if a blocking building sits on any tile in *path*."""
        bld_grid = mm.building_grid
        for x, y in path:
            b = bld_grid[x][y]
            if b is not None and b.entity_type in BLOCKING_BUILDING_TYPES:
                DEBUG and print(f"[A*] PATH BLOCKED by {b.entity_type} at ({x},{y})")
                return True
        return False

    # ── Exploration fallback ─────────────────────────────────────────────

    def _explore_tile(self, mm: MapManager,
                      target: Position) -> tuple[int, int] | None:
        """Return the reachable vision-boundary tile closest to target."""
        w, h = mm.width, mm.height
        best: tuple[int, int] | None = None
        best_d = 100_000_000

        for rx, ry in self._reachable:
            if (rx, ry) in self._explore_failed:
                continue
            boundary = False
            for _d, dx, dy in self._deltas:
                nx, ny = rx + dx, ry + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if mm.tile_grid[nx][ny] is None:
                        boundary = True
                        break
            if not boundary:
                continue

            cd = max(abs(rx - target.x), abs(ry - target.y))
            if cd < best_d:
                best_d = cd
                best = (rx, ry)

        return best

    # ── Main entry point ─────────────────────────────────────────────────

    def _wrap_pass_fn(self, pass_fn, target: Position, avoid_launchers: bool):
        """Wrap a passability function to also reject launcher danger zones."""
        lt = self.launcher_tracker
        if not avoid_launchers or lt is None:
            return pass_fn

        tx, ty = target.x, target.y

        def wrapped(ct, pos, mm):
            if not pass_fn(ct, pos, mm):
                return False
            # Allow stepping onto the target even if in a launcher zone
            if pos.x == tx and pos.y == ty:
                return True
            return not lt.is_dangerous(pos)

        return wrapped

    @cputimer
    def path_to(
        self,
        ct,
        map_manager: MapManager,
        my_pos: Position,
        target: Position,
        move_function,
        passability_function,
        avoid_launchers: bool = True,
    ) -> Direction | None:
        print(f"Time before pathing: {ct.get_cpu_time_elapsed()}")
        DEBUG and draw_move_direction(ct, my_pos, target, 255, 255, 255)

        passability_function = self._wrap_pass_fn(passability_function, target, avoid_launchers)

        if my_pos == target:
            DEBUG and print(f"[A*] Already at target {target}")
            return None

        can_move = ct.get_move_cooldown() == 0
        DEBUG and print(f"[A*] pos={my_pos} target={target} can_move={can_move} cooldown={ct.get_move_cooldown()}")

        # Adjacent — just step there
        if can_move and max(abs(my_pos.x - target.x), abs(my_pos.y - target.y)) <= 1:
            d = my_pos.direction_to(target)
            DEBUG and print(f"[A*] ADJACENT move dir={d}")
            move_function(ct, d)
            return d

        # Target changed → full reset (reachable preserved)
        if self.current_target is None or target != self.current_target:
            DEBUG and print(f"[A*] TARGET CHANGED {self.current_target} -> {target}")
            self.reset(ct, my_pos, target)
        else:
            DEBUG and print(f"[A*] same target, found={self._found} exhausted={self._exhausted} open={len(self._open)} closed={len(self._closed)}")

        # Incremental re-open: if new terrain was discovered, re-open
        # the boundary instead of a full reset.
        bk = (my_pos.x, my_pos.y)
        if self._exhausted and map_manager.newly_seen:
            self._reopen(ct, map_manager, my_pos, target, passability_function)

        # Budget for this turn
        remaining_cpu = CPU_LIMIT - ct.get_cpu_time_elapsed()
        budget = max(0, remaining_cpu // NODE_COST)

        # ── Try to reconstruct path before expanding ──
        path = None

        if self._found and self._goal_key is not None:
            # Validate goal tile is still passable
            gx, gy = self._goal_key
            gb = map_manager.building_grid[gx][gy]
            if gb is not None and gb.entity_type in BLOCKING_BUILDING_TYPES:
                DEBUG and print(f"[A*] Goal tile blocked, resetting")
                self.reset(ct, my_pos, target)
            else:
                path = self._reconstruct(self._goal_key, bk)
                DEBUG and print(f"[A*] reconstruct from goal={self._goal_key} to bot={bk}: path={'len='+str(len(path)) if path else 'None'}")

        # ── If goal found but chain disconnected, re-seed from bot ──
        if self._found and path is None and self._goal_key is not None:
            tx, ty = target.x, target.y
            # Clear closed so expansion can propagate from bot through
            # the existing graph.  _g values are preserved — only tiles
            # that get a better cost from the bot will be updated.
            self._closed.clear()
            self._g[bk] = 0
            self._from.pop(bk, None)
            f = H_WEIGHT * max(abs(my_pos.x - tx), abs(my_pos.y - ty))
            heapq.heappush(self._open, (f, self._cnt, bk))
            self._cnt += 1
            self._exhausted = False
            DEBUG and print(f"[A*] RE-SEED from bot {bk}, cleared closed set to reconnect chain")

        # ── Expand if: goal not found, OR found but not connected to bot ──
        used_main = False
        if budget > 0 and (not self._found or path is None):
            DEBUG and print(f"[A*] expanding: found={self._found} path={path is not None} budget={budget}")
            _, n_expanded = self._expand(ct, map_manager, target, passability_function, budget)
            used_main = n_expanded > 0
            # Re-try reconstruction after expansion
            if self._found and self._goal_key is not None:
                path = self._reconstruct(self._goal_key, bk)
                DEBUG and print(f"[A*] post-expand reconstruct: path={'len='+str(len(path)) if path else 'None'}")

        # If on cooldown, we've done our expansion work — return early.
        if not can_move:
            return None

        # ── Bug nav: detect oscillation and wall-follow ─────────────────
        has_astar_path = path is not None and len(path) >= 2 and not self._path_has_blocker(path, map_manager)

        self._bug.track_position(my_pos)

        # Exit bug nav if A* found a complete usable path
        self._bug.exit_if_astar_ready(has_astar_path)

        # Detect oscillation → enter bug nav
        if self._bug.should_enter(my_pos, target, has_astar_path):
            self._bug.enter(ct, map_manager, my_pos, target,
                            passability_function)

        # Bug nav movement
        if self._bug.active:
            result = self._bug.step(ct, map_manager, my_pos, target,
                                    passability_function, move_function,
                                    reachable=self._reachable)
            if result is not None:
                return result
            # Bug nav exited or stuck — fall through to normal A* logic

        # ── Follow A* path ──
        if path is not None and len(path) >= 2:
            if self._path_has_blocker(path, map_manager):
                self.reset(ct, my_pos, target)
                DEBUG and print("[A*] Path blocked, falling through to bug")
            else:
                nxt_key = path[1]
                nxt = Position(nxt_key[0], nxt_key[1])
                d = my_pos.direction_to(nxt)

                # Bot on next tile — yield if we're lower priority (higher ID)
                other_bot = map_manager.bot_grid[nxt.x][nxt.y]
                if other_bot is not None and other_bot.team == ct.get_team() and ct.get_id() > other_bot.id:
                    DEBUG and print(f"[A*] YIELD: our id={ct.get_id()} > {other_bot.id}, sidestepping")
                    result = self._sidestep(ct, map_manager, my_pos, path,
                                            passability_function, move_function)
                    if result is not None:
                        return result
                    DEBUG and print(f"[A*] sidestep failed, falling through")

                elif passability_function(ct, nxt, map_manager):
                    DEBUG and print(f"[A*] FOLLOW -> {nxt} dir={d}")
                    DEBUG and draw_move_direction(ct, my_pos, nxt, 0, 255, 0)
                    move_function(ct, d)
                    return d
                else:
                    DEBUG and print(f"[A*] next tile {nxt} IMPASSABLE, falling through")

        # ── Exploration (frontier exhausted, target not in known map) ──
        if self._exhausted and not self._found:
            explore = self._explore_tile(map_manager, target)
            DEBUG and print(f"[A*] EXHAUSTED path, explore_tile={explore} explore_astar={'exists' if self._explore else 'None'}")
            if explore is not None:
                # Create or refresh Dijkstra if needed
                explore_exhausted = (self._explore is not None
                                     and not self._explore.found
                                     and not self._explore._open)
                if explore_exhausted:
                    DEBUG and print(f"[A*] explore exhausted, marking {explore} as failed")
                    self._explore_failed.add(explore)
                    self._explore = None
                    # Re-pick explore tile excluding failed ones
                    explore = self._explore_tile(map_manager, target)
                    DEBUG and print(f"[A*] next explore_tile={explore}")
                    if explore is None:
                        DEBUG and print(f"[A*] all explore tiles failed ({len(self._explore_failed)}), resetting")
                        self.reset(ct, my_pos, target)
                        return None

                needs_new = (self._explore is None
                             or (self._explore.found
                                 and not self._explore.sync(my_pos)))
                DEBUG and print(f"[A*] explore needs_new={needs_new} explore.found={self._explore.found if self._explore else 'N/A'} explore.open={len(self._explore._open) if self._explore else 'N/A'}")
                if needs_new:
                    DEBUG and print(f"[A*] EXPLORE Dijkstra from {my_pos} -> {explore}")
                    self._explore = ExploreAStar(my_pos, {explore}, self._deltas)

                # Expand explore Dijkstra (only if main A* didn't run)
                if not self._explore.found and not used_main and budget > 0:
                    self._explore.expand(ct, map_manager,
                                         passability_function, budget)

                # Follow explore path
                if self._explore.found and self._explore.path:
                    synced = self._explore.sync(my_pos)
                    DEBUG and print(f"[A*] explore synced={synced} pidx={self._explore.pidx} pathlen={len(self._explore.path)}")
                    if synced:
                        idx = self._explore.pidx
                        # If bot is adjacent to path[idx] but not on it, step onto it first
                        on_path = self._explore.path[idx] == my_pos
                        if not on_path:
                            nxt = self._explore.path[idx]
                            d = my_pos.direction_to(nxt)
                            DEBUG and print(f"[A*] EXPLORE stepping onto path[{idx}]={nxt} dir={d}")
                            if passability_function(ct, nxt, map_manager) and map_manager.bot_grid[nxt.x][nxt.y] is None:
                                DEBUG and draw_move_direction(ct, my_pos, nxt, 0, 200, 255)
                                move_function(ct, d)
                                return d
                            else:
                                DEBUG and print(f"[A*] EXPLORE path[{idx}]={nxt} blocked, falling through")
                        elif idx + 1 < len(self._explore.path):
                            nxt = self._explore.path[idx + 1]
                            d = my_pos.direction_to(nxt)
                            # Yield to higher-priority ally bot
                            other = map_manager.bot_grid[nxt.x][nxt.y]
                            if (other is not None and other.team == ct.get_team()
                                    and ct.get_id() > other.id):
                                DEBUG and print(f"[A*] EXPLORE YIELD to bot {other.id} at {nxt}")
                            elif passability_function(ct, nxt, map_manager):
                                self._explore.pidx = idx + 1
                                DEBUG and print(f"[A*] EXPLORE -> {nxt} dir={d} from={my_pos}")
                                DEBUG and draw_move_direction(ct, my_pos, nxt,
                                                             0, 200, 255)
                                move_function(ct, d)
                                return d
                            else:
                                DEBUG and print(f"[A*] EXPLORE next tile {nxt} IMPASSABLE")
                        else:
                            DEBUG and print("[A*] EXPLORE complete, reopening frontier")
                            self._reopen(ct, map_manager, my_pos, target,
                                         passability_function)
                    else:
                        DEBUG and print(f"[A*] EXPLORE sync failed, bot at {my_pos} not on/near path")

                # Explore A* computing — follow its partial wavefront
                nxt = (self._explore.best_partial_step(ct, map_manager, my_pos,
                                                       passability_function)
                       if self._explore is not None else None)
                if nxt is not None:
                    d = my_pos.direction_to(nxt)
                    DEBUG and print(f"[A*] EXPLORE PARTIAL -> {nxt} dir={d} from={my_pos}")
                    DEBUG and draw_move_direction(ct, my_pos, nxt, 0, 200, 255)
                    move_function(ct, d)
                    return d

                # Partial step failed — wait
                DEBUG and print(f"[A*] EXPLORE: no partial step available from {my_pos}")
                return None
            else:
                # Fully explored, no unseen boundary — passability may have
                # changed since original search.  Full reset to re-evaluate.
                DEBUG and print(f"[A*] EXHAUSTED: no explore tile in {len(self._reachable)} reachable, resetting to re-evaluate passability")
                self.reset(ct, my_pos, target)
                return None

        # ── Follow main A* partial wavefront ──
        nxt = self._best_partial_step(ct, map_manager, my_pos, target,
                                      passability_function)
        if nxt is not None:
            d = my_pos.direction_to(nxt)
            DEBUG and print(f"[A*] PARTIAL -> {nxt} dir={d} from={my_pos}")
            DEBUG and draw_move_direction(ct, my_pos, nxt, 255, 255, 0)
            move_function(ct, d)
            return d

        # ── No movement available ──
        DEBUG and print(f"[A*] WAITING: no move from {my_pos}, found={self._found} exhausted={self._exhausted} open={len(self._open)} can_move={can_move}")
        return None

    # ── Idle expansion ──────────────────────────────────────────────────

    def idle_expand(self, ct, map_manager: MapManager, my_pos: Position,
                    core_pos: Position, passability_function) -> None:
        """Expand A* toward *core_pos* when not actively pathing.

        Keeps the _reachable set up to date so future path queries
        start with better terrain knowledge.  No movement is performed.
        """
        remaining_cpu = CPU_LIMIT - ct.get_cpu_time_elapsed()
        budget = max(0, remaining_cpu // NODE_COST)
        if budget <= 0:
            return

        # If we're already pathing to something else, don't interfere
        if self.current_target is not None and self.current_target != core_pos:
            return

        # Initialize or re-target toward core
        if self.current_target != core_pos:
            self.reset(ct, my_pos, core_pos)

        # Inject bot position so expansion stays connected
        bk = (my_pos.x, my_pos.y)
        tx, ty = core_pos.x, core_pos.y
        if bk not in self._g or self._g[bk] > 0:
            self._g[bk] = 0
            self._from.pop(bk, None)
            self._closed.discard(bk)
            f = H_WEIGHT * max(abs(my_pos.x - tx), abs(my_pos.y - ty))
            heapq.heappush(self._open, (f, self._cnt, bk))
            self._cnt += 1

        # Re-open if new terrain discovered
        if map_manager.newly_seen:
            self._reopen(ct, map_manager, my_pos, core_pos, passability_function)

        if not self._exhausted:
            self._expand(ct, map_manager, core_pos, passability_function, budget)

    # ── Movement helpers ─────────────────────────────────────────────────

    def _sidestep(self, ct, mm, my_pos, path, pass_fn, move_fn):
        """Step off the path to let an ally pass, staying close to the path.

        Picks the passable neighbor NOT on the path that's closest to
        path[2] (the tile after the blocked one).  This keeps the bot
        oriented in the right direction.  Next turn, the adjacent sync
        in ExploreAStar/reconstruct will rejoin the path.
        """
        w, h = mm.width, mm.height
        path_set = set(path)

        # Aim toward path[2] if it exists, else the blocked tile path[1]
        aim = path[2] if len(path) >= 3 else path[1]
        ax, ay = aim

        best_d = None
        best_dist = 100_000_000

        for d, dx, dy in self._deltas:
            px, py = my_pos.x + dx, my_pos.y + dy
            if not (0 <= px < w and 0 <= py < h):
                continue
            nb = (px, py)
            if nb in path_set:
                continue  # don't step onto the path (ally is there)
            if mm.bot_grid[px][py] is not None:
                continue  # another bot already there
            if not pass_fn(ct, Position(px, py), mm):
                continue

            dist = max(abs(px - ax), abs(py - ay))
            if dist < best_dist:
                best_dist = dist
                best_d = d

        if best_d is not None:
            p = my_pos.add(best_d)
            DEBUG and draw_move_direction(ct, my_pos, p, 255, 150, 0)
            move_fn(ct, best_d)
            return best_d

        return None
