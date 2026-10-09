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
    ALLY_STUCK_COOLDOWN, STUCK_BOT_PENALTY,
    BLOCKING_BUILDING_TYPES,
)
from nav.explore_astar import ExploreAStar
from nav.bug_nav import BugNav
from nav.pass_context import PassContext
from nav.reachability import is_reachable


# ── Helpers ──────────────────────────────────────────────────────────────────

def _adjacent_xy(ax: int, ay: int, bx: int, by: int) -> bool:
    return max(abs(ax - bx), abs(ay - by)) <= 1


def _bot_is_stuck(bot) -> bool:
    """A bot that can't yield/move out of the way within a turn or two.

    Works for any team — a parked enemy is just as much of an obstacle
    as a parked ally.  Uses the cooldowns populated in records.py:59-60.
    """
    return (bot.move_cooldown > ALLY_STUCK_COOLDOWN
            or bot.action_cooldown > ALLY_STUCK_COOLDOWN)


# ── Pathing ──────────────────────────────────────────────────────────────────

class Pathing:
    def __init__(self, ct, launcher_tracker: LauncherTracker) -> None:
        self.current_target: Position | None = None
        self.launcher_tracker: LauncherTracker = launcher_tracker

        # Per-turn (x,y) -> bool cache for passability checks.  Cleared at
        # the start of every path_to call (the bound pass_fn it creates
        # captures this dict).  Key: (x, y).  Value: passable bool.
        self._pass_cache: dict[tuple[int, int], bool] = {}

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
        # Subset of _reachable: tiles with at least one in-bounds
        # non-reachable neighbor.  Used to seed idle_expand without
        # scanning the full reachable set.  Pruned lazily.
        self._frontier: set = set()

        # Persistent BFS state for idle_expand — survives across turns.
        # Queue is only grown when newly_seen fires (or once at startup);
        # head advances as tiles are processed, queue is compacted lazily.
        self._idle_queue: list = []
        self._idle_head: int = 0
        self._idle_seeded: bool = False

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

        # Follow constraint: if set, refuse any move that would place
        # the bot more than 1 tile (Chebyshev) from this position.
        self.follow_pos: Position | None = None

        # If True, path_to plans but skips the actual move call. Used so
        # FollowState can veto in-turn movement and save a follow move
        # for end-of-turn (triggered by builder_brain).
        self.disable_moves: bool = False

    # ── Local reachable seeding ────────────────────────────────────────────

    def update(self, ct, mm: MapManager) -> None:
        """Seed the 3x3 around the bot into the reachable set.

        Uses the lightweight reachability check (terrain + walkable
        building) rather than full passability — resource-gated tiles
        still belong in the reachable set; path_to re-verifies under
        full rules before stepping onto them.
        """
        self.follow_pos = None
        self.disable_moves = False
        ctx = PassContext(ct, mm, self.launcher_tracker)
        w, h = mm.width, mm.height
        mx, my = ctx.my_x, ctx.my_y
        before = len(self._reachable)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = mx + dx, my + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if is_reachable(ctx, nx, ny):
                        self._reachable.add((nx, ny))
                        self._frontier.add((nx, ny))
        DEBUG and print(f"[REACH] update: +{len(self._reachable) - before} tiles "
                        f"(total={len(self._reachable)}, frontier={len(self._frontier)})")

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
                target: Position) -> None:
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
                budget: int = 0, ctx: PassContext | None = None) -> tuple[bool, int]:
        """Expand up to *budget* nodes.  Return (goal_reached, nodes_used).

        pass_fn is the bound (x, y) -> bool closure built in path_to.
        ctx, if provided, gates writes into _reachable via is_reachable
        so that tiles admitted to the reachable set are validated by the
        canonical lightweight check — not the (possibly launcher-wrapped)
        search pass_fn.
        """
        w, h = mm.width, mm.height
        tx, ty = target.x, target.y
        expanded = 0
        g_map = self._g
        from_map = self._from
        open_list = self._open
        closed = self._closed
        reachable = self._reachable
        frontier = self._frontier
        bld_grid = mm.building_grid
        bot_grid = mm.bot_grid
        my_id = ct.get_id()
        my_team = ct.get_team()
        reach_added = 0
        reach_rejected = 0

        while open_list and budget > 0:
            _f, _c, cur = heapq.heappop(open_list)
            if cur in closed:
                continue
            closed.add(cur)

            if ctx is None or is_reachable(ctx, cur[0], cur[1]):
                if cur not in reachable:
                    reach_added += 1
                reachable.add(cur)
                frontier.add(cur)
            else:
                reach_rejected += 1
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
                if not pass_fn(nx, ny):
                    continue

                ng = g + 1 + (EMPTY_PENALTY if bld_grid[nx][ny] is None else 0)
                other = bot_grid[nx][ny]
                if other is not None:
                    if _bot_is_stuck(other):
                        # Parked builder (either team) — route around, not through.
                        ng += STUCK_BOT_PENALTY
                    elif other.team != my_team or my_id > other.id:
                        ng += BOT_PENALTY
                if nb not in g_map or ng < g_map[nb]:
                    g_map[nb] = ng
                    from_map[nb] = cur
                    f = ng + H_WEIGHT * max(abs(nx - tx), abs(ny - ty))
                    heapq.heappush(open_list, (f, self._cnt, nb))
                    self._cnt += 1

        DEBUG and print(f"[REACH] _expand: +{reach_added} tiles, rejected={reach_rejected} "
                        f"(total={len(reachable)}, frontier={len(frontier)})")

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
        pass_fn is the bound (x, y) -> bool closure built in path_to.
        """
        w, h = mm.width, mm.height
        tx, ty = target.x, target.y
        g_map = self._g
        my_id = ct.get_id()
        my_team = ct.get_team()
        bot_grid = mm.bot_grid
        best_wave = None
        best_wave_score = float('inf')
        best_greedy = None
        best_greedy_score = float('inf')

        for _d, dx, dy in self._deltas:
            nx, ny = my_pos.x + dx, my_pos.y + dy
            nb = (nx, ny)
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if not pass_fn(nx, ny):
                continue

            h_val = H_WEIGHT * max(abs(nx - tx), abs(ny - ty))
            bot_pen = 0
            other = bot_grid[nx][ny]
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

    # ── Passability binding ──────────────────────────────────────────────

    def _bind_pass_fn(self, fast_fn, ctx: PassContext):
        """Create a cached (x, y) -> bool closure over fast_fn + ctx.

        Wraps fast_fn with:
          - Per-turn memoization keyed by (x, y).  Impassable tiles
            never enter A*'s closed set, so they get re-checked from
            every expanded neighbor — the cache turns those repeats
            into dict lookups.
          - Launcher-danger rejection (allowing the target tile).

        The cache is shared across _expand, bug_nav, sidestep,
        partial-step, and the explore A* within a single path_to call.
        """
        cache = self._pass_cache
        cache.clear()
        launcher_grid = ctx.launcher_grid
        gunner_danger = ctx.gunner_danger
        tx, ty = ctx.target_x, ctx.target_y

        def bound(x: int, y: int) -> bool:
            key = (x, y)
            if key in cache:
                return cache[key]
            r = fast_fn(ctx, x, y)
            if r and (x != tx or y != ty) and (
                launcher_grid[x][y] or key in gunner_danger
            ):
                r = False
            cache[key] = r
            return r

        return bound

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
        """Find/advance a path to *target*.

        *passability_function* must be a fast (ctx, x, y) -> bool
        function from nav.fast_passability.  Launcher avoidance is
        always applied on top of it (allowing the target tile itself).
        """
        print(f"Time before pathing: {ct.get_cpu_time_elapsed()}")
        DEBUG and draw_move_direction(ct, my_pos, target, 255, 255, 255)

        # Build turn snapshot + cached bound pass_fn.  All internal
        # callers (A*, bug nav, explore, sidestep) use the bound form.
        ctx = PassContext(ct, map_manager, self.launcher_tracker, target)
        passability_function = self._bind_pass_fn(passability_function, ctx)

        # Move-veto: FollowState can request that in-turn path_to calls
        # plan but don't actually move, so a follow move can be issued
        # at end of turn instead.
        if self.disable_moves:
            def move_function(ct, d):
                return False

        # Follow constraint: don't move beyond 1 tile of follow_pos
        fp = self.follow_pos
        if fp is not None:
            _inner_move = move_function
            fpx, fpy = fp.x, fp.y

            def move_function(ct, d):
                dx, dy = d.delta()
                nx, ny = my_pos.x + dx, my_pos.y + dy
                if max(abs(nx - fpx), abs(ny - fpy)) > 1:
                    DEBUG and print(f"[A*] FOLLOW constraint: blocked move {d}, would leave {fp}")
                    return False
                return _inner_move(ct, d)

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
            self._reopen(ct, map_manager, my_pos, target)

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
        if not self._found or path is None:
            # Compute budget here, after all preprocessing, so reconstruction
            # and re-seed cost doesn't eat into the expansion allowance.
            budget = max(0, (CPU_LIMIT - ct.get_cpu_time_elapsed()) // NODE_COST)
            DEBUG and print(f"[A*] expanding: found={self._found} path={path is not None} budget={budget}")
            _, n_expanded = self._expand(ct, map_manager, target, passability_function, budget, ctx)
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
        self._bug.track_stuck(my_pos, target, map_manager, has_astar_path)

        # Exit bug nav if A* found a complete usable path
        self._bug.exit_if_astar_ready(has_astar_path)

        # Detect oscillation → enter bug nav
        if self._bug.should_enter(my_pos, target, has_astar_path):
            self._bug.enter(ct, map_manager, my_pos, target)

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

                # Bot on next tile — sidestep if we can't just walk through it:
                #   - enemy bot (never yields)
                #   - stuck bot of either team (mid-build, can't yield)
                #   - lower-priority ally (we yield by convention)
                other_bot = map_manager.get_bot(nxt)
                if other_bot is not None:
                    is_ally = other_bot.team == ct.get_team()
                    must_sidestep = (not is_ally
                                     or _bot_is_stuck(other_bot)
                                     or ct.get_id() > other_bot.id)
                else:
                    must_sidestep = False

                if must_sidestep:
                    DEBUG and print(f"[A*] SIDESTEP around bot {other_bot.id} team={other_bot.team} stuck={_bot_is_stuck(other_bot)}")
                    result = self._sidestep(ct, map_manager, my_pos, target, path,
                                            passability_function, move_function)
                    if result is not None:
                        return result
                    DEBUG and print(f"[A*] sidestep failed, falling through")

                elif passability_function(nxt.x, nxt.y):
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

                # Expand explore Dijkstra (only if main A* didn't run).
                # Recompute budget against live CPU — everything since the
                # main-A* budget was taken has eaten into the turn.
                if not self._explore.found and not used_main:
                    explore_budget = max(0, (CPU_LIMIT - ct.get_cpu_time_elapsed()) // NODE_COST)
                    if explore_budget > 0:
                        self._explore.expand(ct, map_manager,
                                             passability_function, explore_budget)

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
                            if passability_function(nxt.x, nxt.y) and map_manager.get_bot(nxt) is None:
                                DEBUG and draw_move_direction(ct, my_pos, nxt, 0, 200, 255)
                                move_function(ct, d)
                                return d
                            else:
                                DEBUG and print(f"[A*] EXPLORE path[{idx}]={nxt} blocked, falling through")
                        elif idx + 1 < len(self._explore.path):
                            nxt = self._explore.path[idx + 1]
                            d = my_pos.direction_to(nxt)
                            # Yield to higher-priority ally bot
                            other = map_manager.get_bot(nxt)
                            if (other is not None and other.team == ct.get_team()
                                    and ct.get_id() > other.id):
                                DEBUG and print(f"[A*] EXPLORE YIELD to bot {other.id} at {nxt}")
                            elif passability_function(nxt.x, nxt.y):
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
                            self._reopen(ct, map_manager, my_pos, target)
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

    def idle_expand(self, ct, map_manager: MapManager) -> None:
        """Flood-fill _reachable into seen passable tiles.

        BFS outward from the persistent _idle_queue (seeded from
        frontier tiles adjacent to newly-seen terrain) through tiles
        that pass the lightweight is_reachable check, adding them to
        _reachable.

        Uses is_reachable instead of the full path_to pass_fn — path-
        time state (resources, launcher zones, target) is irrelevant
        for reachability, and skipping those checks makes each node
        cheaper.  path_to re-verifies under full rules before moving.

        Does not touch active A* search state (_open, _g, _from,
        _closed).
        """
        IDLE_CPU_LIMIT = 2000
        if not self._frontier:
            return
        if ct.get_cpu_time_elapsed() >= IDLE_CPU_LIMIT:
            return

        ctx = PassContext(ct, map_manager, self.launcher_tracker)
        w, h = map_manager.width, map_manager.height
        tile_grid = map_manager.tile_grid
        reachable = self._reachable
        frontier = self._frontier
        queue = self._idle_queue

        # One-shot initial seed: on the very first call, the persistent
        # queue is empty but the frontier already has tiles — dump them
        # all in once.  Subsequent calls rely on newly_seen to add work.
        if not self._idle_seeded:
            queue.extend(frontier)
            self._idle_seeded = True

        # Incremental seed: only frontier tiles adjacent to newly-seen
        # terrain can possibly make progress this turn.  Stalled frontier
        # tiles (all non-reachable neighbors still unseen) are skipped
        # entirely until vision reveals something new.
        newly_seen = map_manager.newly_seen
        if newly_seen:
            to_enqueue: set = set()
            for sx, sy in newly_seen:
                for _d, dx, dy in self._deltas:
                    nx, ny = sx + dx, sy + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    nb = (nx, ny)
                    if nb in frontier:
                        to_enqueue.add(nb)
            if to_enqueue:
                queue.extend(to_enqueue)

        # Compute budget *after* seeding work so preprocessing doesn't
        # eat into the BFS expansion allowance.
        budget = max(0, (IDLE_CPU_LIMIT - ct.get_cpu_time_elapsed()) // NODE_COST)

        head = self._idle_head
        retire: list = []
        reach_added = 0
        while head < len(queue) and budget > 0:
            cx, cy = queue[head]
            head += 1
            # Skip tiles already retired in a prior turn.
            if (cx, cy) not in frontier:
                continue
            budget -= 1
            has_open_neighbor = False
            for _d, dx, dy in self._deltas:
                nx, ny = cx + dx, cy + dy
                nb = (nx, ny)
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if nb in reachable:
                    continue
                has_open_neighbor = True
                if tile_grid[nx][ny] is None:
                    continue
                if not is_reachable(ctx, nx, ny):
                    continue
                reachable.add(nb)
                frontier.add(nb)
                queue.append(nb)
                reach_added += 1
            if not has_open_neighbor:
                retire.append((cx, cy))

        for k in retire:
            frontier.discard(k)

        DEBUG and print(f"[REACH] idle_expand: +{reach_added} tiles, retired={len(retire)} "
                        f"(total={len(reachable)}, frontier={len(frontier)}, "
                        f"queue={len(queue) - head})")

        # Compact queue: drop drained prefix.  Fully drained → clear;
        # otherwise slice off the head once it grows large enough that
        # the skip cost outweighs the copy.
        if head >= len(queue):
            queue.clear()
            self._idle_head = 0
        elif head > 512:
            del queue[:head]
            self._idle_head = 0
        else:
            self._idle_head = head

    # ── Movement helpers ─────────────────────────────────────────────────

    def _sidestep(self, ct, mm, my_pos, target, path, pass_fn, move_fn):
        """Step around an ally blocking path[1] while staying on route.

        Candidates are split into two classes per neighbor:
          CLEAN: empty, passable tile — always preferred.
          SOFT:  tile occupied by a non-stuck ally.  Speculative: the
                 ally is likely to vacate (higher-priority allies move
                 before us; lower-priority ones yield to us next turn),
                 so picking this direction is strictly better than
                 returning None when all clean tiles are taken.

        Stuck bots (any team) and enemy bots are hard-excluded — they
        will not vacate, so targeting them wastes the attempt.

        Within each class, we prefer a "shortcut" onto a later path
        tile (index >= 2); otherwise pick the best (g + h) neighbor.
        Priority: clean shortcut > clean score > soft shortcut > soft
        score.  Path[1] itself is treated as impassable even if
        bot_grid has cleared — the caller already decided to yield.
        """
        w, h = mm.width, mm.height
        tx, ty = target.x, target.y
        blocked = path[1]
        g_map = self._g
        my_team = ct.get_team()
        bot_grid = mm.bot_grid

        # Upcoming path tiles (after the blocked one) for shortcut lookup.
        path_idx: dict = {}
        for i in range(2, len(path)):
            path_idx[path[i]] = i

        # Clean (empty) candidates
        clean_shortcut_idx = -1
        clean_shortcut_d = None
        clean_score = float('inf')
        clean_score_d = None

        # Soft (ally-occupied, non-stuck) candidates
        soft_shortcut_idx = -1
        soft_shortcut_d = None
        soft_score = float('inf')
        soft_score_d = None

        for d, dx, dy in self._deltas:
            nx, ny = my_pos.x + dx, my_pos.y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            nb = (nx, ny)
            if nb == blocked:
                continue
            if not pass_fn(nx, ny):
                continue

            other = bot_grid[nx][ny]
            is_soft = False
            if other is not None:
                # Enemies and stuck bots will not vacate — skip.
                if other.team != my_team or _bot_is_stuck(other):
                    continue
                is_soft = True

            h_val = H_WEIGHT * max(abs(nx - tx), abs(ny - ty))
            score = (g_map[nb] + h_val) if nb in g_map else h_val
            idx = path_idx.get(nb, -1)

            if is_soft:
                score += BOT_PENALTY
                if idx > soft_shortcut_idx:
                    soft_shortcut_idx = idx
                    soft_shortcut_d = d
                if score < soft_score:
                    soft_score = score
                    soft_score_d = d
            else:
                if idx > clean_shortcut_idx:
                    clean_shortcut_idx = idx
                    clean_shortcut_d = d
                if score < clean_score:
                    clean_score = score
                    clean_score_d = d

        # Prefer clean shortcut > clean score > soft shortcut > soft score.
        chosen = clean_shortcut_d
        if chosen is None:
            chosen = clean_score_d
        if chosen is None:
            chosen = soft_shortcut_d
        if chosen is None:
            chosen = soft_score_d

        if chosen is not None:
            p = my_pos.add(chosen)
            DEBUG and draw_move_direction(ct, my_pos, p, 255, 150, 0)
            move_fn(ct, chosen)
            return chosen

        return None
