"""Pathing: reverse A* anchored at target (or frontier sub-goal).

Algorithm
---------
On every turn:

  1. Determine effective target:
       - target ∈ reachable.tiles → effective = target
       - else → effective = frontier tile (in reachable.tiles,
         bordering unseen) closest to target by Chebyshev distance
       - else → mark unreachable, wait
  2. If effective target changed since last turn, re-seed reverse
     A* at the new effective target.
  3. Expand reverse A* with the per-turn budget. _g grows from the
     effective target outward toward the bot. Static_pass includes
     terrain + walkable structure + flavour, so every tile in _g
     is currently walkable.
  4. If the bot's tile has _g, descend: pick the neighbour with
     the smallest _g. If the lowest-g neighbour is blocked by a
     bot or danger zone, slide down the ranked candidate list to
     the next unblocked one.
  5. If the bot's tile doesn't have _g yet (expansion hasn't
     reached us), Bug2 takes over and walks toward the effective
     target greedily, wall-following around obstacles. Once
     expansion catches up (or vision grows), the dispatch flips
     back to gradient descent automatically. The only times we
     return None without moving are: cooldown, or no effective
     target at all.

Indicators:
  Pink   (255,100,255) — bot → target marker
  Green  (0,255,0)     — gradient-descent step toward effective target
  Purple (200,0,200)   — Bug2 step (greedy or wall-follow)
"""
from __future__ import annotations

from cambc import Direction, Position
from debug.indicators import draw_move_direction
from debug.profiling import cputimer
from map.map_manager import MapManager
from vision.launcher_tracker import LauncherTracker

from nav.bug_nav import BugNav
from nav.config import DEBUG, NODE_COST, CPU_LIMIT

# One-line-per-step diagnostic for the cardinal-vs-diagonal pattern.
# Independent of DEBUG. Flip to False once root cause is identified.
STAIR_DEBUG = False


def _is_diag(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0
from nav.pass_context import PassContext
from nav.reachability import is_reachable
from nav.reachable_set import ReachableSet
from nav.reverse_astar import ReverseAStar


class Pathing:
    # Early-exploration phase. For the first WARMUP_MOVES turns the bot
    # can move, skip A*/frontier logic and let Bug2 walk toward the real
    # target. Spawn-time vision is tiny — frontier choice is dominated by
    # whichever direction happened to be revealed first, often pulling
    # the bot the wrong way. A few raw Bug2 steps grow reachable.tiles
    # enough that the frontier picker has a meaningful choice space when
    # it takes over.
    WARMUP_MOVES = 10

    def __init__(self, ct, launcher_tracker: LauncherTracker,
                 reachable: ReachableSet) -> None:
        self.launcher_tracker = launcher_tracker
        self.reachable = reachable

        self.current_target: Position | None = None
        self.follow_pos: Position | None = None
        self.disable_moves: bool = False

        self._deltas = self._build_deltas(ct)
        self._astar = ReverseAStar(self._deltas)
        self._bug = BugNav(self._deltas)

        # Currently anchored target (real target or a frontier).
        # When this changes, A* re-seeds.
        self._effective_target: tuple[int, int] | None = None

        # Frontier tiles we've reached without lifting fog. Cleared on
        # any vision update.
        self._frontier_blacklist: set[tuple[int, int]] = set()

        # Real targets the caller set that have no reachable path AND
        # no frontier left to explore.
        self._unreachable_targets: set[tuple[int, int]] = set()

        # Anchor we've already retried with a fresh re-seed after an
        # exhaustion-without-bot. Used to distinguish "stale _g, just
        # try once more" from "genuinely disconnected, escalate". Reset
        # when the effective target changes or on newly_seen.
        self._reseeded_for: tuple[int, int] | None = None

        # Diagnostics: how many consecutive turns we've been stuck
        # waiting for expansion to reach the bot under the *current*
        # effective target. Resets when the anchor changes or descent
        # succeeds. Useful for spotting re-seed churn vs. slow expand.
        self._wait_anchor: tuple[int, int] | None = None
        self._wait_turns: int = 0

        # Warmup counter — increments each turn path_to runs with the
        # bot off cooldown. While < WARMUP_MOVES, we skip A* and let
        # Bug2 carry navigation so vision can grow naturally.
        self._move_count: int = 0

    # ── Per-turn lifecycle ──────────────────────────────────────────────

    def update(self, ct, mm: MapManager) -> None:
        self.disable_moves = False
        self.follow_pos = None
        if mm.newly_seen:
            self._unreachable_targets.clear()
            self._frontier_blacklist.clear()
            self._reseeded_for = None

    # ── Public queries ──────────────────────────────────────────────────

    def is_target_unreachable(self, target: Position) -> bool:
        return (target.x, target.y) in self._unreachable_targets

    def is_tile_unreachable(self, mm: MapManager, p: Position) -> bool:
        """Conservative: True iff *p* is provably unreachable from the
        bot under current vision.

        All three must hold:
          1. The tile is seen.
          2. It's not in reachable.tiles.
          3. No unseen tile borders reachable — so reachable can't
             grow without the bot moving first.

        If any is false, returns False (no guarantee). The tile *might*
        still be reachable once vision grows. Call again after the
        bot moves and reveals more terrain.

        Uses the lightweight reachability notion (terrain + walkable
        structure). A flavour-poor bot may be even more restricted.
        """
        x, y = p.x, p.y
        if mm.tile_grid[x][y] is None:
            return False
        if (x, y) in self.reachable.tiles:
            return False
        # Boundary scan: any fog-bordering frontier tile means
        # reachable might still grow — no guarantee yet.
        w, h = mm.width, mm.height
        tile_grid = mm.tile_grid
        for tx_, ty_ in self.reachable.frontier:
            for _d, dx, dy in self._deltas:
                nx, ny = tx_ + dx, ty_ + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if tile_grid[nx][ny] is None:
                    return False
        return True

    # ── Construction helpers ────────────────────────────────────────────

    def _build_deltas(self, ct) -> list:
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
        dirs.append(left.rotate_left())
        return [(d, *d.delta()) for d in dirs]

    def _wrap_move_fn(self, base, my_pos: Position):
        if self.disable_moves:
            def vetoed(_ct, _d):
                return False
            return vetoed
        fp = self.follow_pos
        if fp is None:
            return base
        fpx, fpy = fp.x, fp.y

        def follow_bound(ct_, d_):
            dx, dy = d_.delta()
            nx, ny = my_pos.x + dx, my_pos.y + dy
            if max(abs(nx - fpx), abs(ny - fpy)) > 1:
                return False
            return base(ct_, d_)

        return follow_bound

    # ── Frontier picking ───────────────────────────────────────────────

    def _pick_frontier(
        self, mm: MapManager, target: Position, bot: Position,
        current: tuple[int, int] | None = None,
    ) -> tuple[int, int] | None:
        """Frontier = a tile in reachable.tiles with at least one
        unseen neighbour.

        Score is a tuple (cheby_sum, manhattan_sum):
            cheby_sum     = chebyshev(bot, f) + chebyshev(f, target)
            manhattan_sum = manhattan(bot, f) + manhattan(f, target)

        Chebyshev is the tight lower bound on actual 8-conn path cost,
        but it under-penalises backtracking on the dominant axis (a
        frontier west of the bot when target is east scores the same
        as a frontier directly toward target whenever the y-delta
        dominates). Manhattan as a tiebreaker punishes backtracking
        on either axis — frontiers that lie *along* the route win
        ties over frontiers that detour.

        Excludes the blacklist.

        Hysteresis (when *current* is provided): if the current
        effective frontier is still valid (in reachable, not
        blacklisted, still bordering fog) and its score is within
        a slack of the best, prefer current. Without this, two
        frontiers straddling the bot can flip turn-to-turn as a
        single bot step tips Chebyshev/Manhattan by 1 — every flip
        re-seeds A* and the bot oscillates without ever reaching
        either frontier.
        """
        tx, ty = target.x, target.y
        bx, by = bot.x, bot.y
        w, h = mm.width, mm.height
        tile_grid = mm.tile_grid
        deltas = self._deltas
        blacklist = self._frontier_blacklist

        best: tuple[tuple[int, int], tuple[int, int]] | None = None
        current_score: tuple[int, int] | None = None
        # Diagnostic: how the *previous* current frontier fared this turn.
        #   None       → current was None coming in (no previous frontier)
        #   "blacklist"→ current is in blacklist (we stood on it)
        #   "unreach"  → current no longer in reachable.tiles
        #   "no_fog"   → still reachable but no neighbour is None anymore
        #   "ok"       → still a valid candidate; current_score is set
        current_status: str | None = None if current is None else "unreach"
        scored: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for tile in self.reachable.tiles:
            is_current = tile == current
            if tile in blacklist:
                if is_current:
                    current_status = "blacklist"
                continue
            x, y = tile
            has_unseen = False
            for _d, dx, dy in deltas:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if tile_grid[nx][ny] is None:
                    has_unseen = True
                    break
            if not has_unseen:
                if is_current:
                    current_status = "no_fog"
                continue
            dx_b = abs(x - bx)
            dy_b = abs(y - by)
            dx_t = abs(x - tx)
            dy_t = abs(y - ty)
            cheby_sum = max(dx_b, dy_b) + max(dx_t, dy_t)
            manhattan_sum = dx_b + dy_b + dx_t + dy_t
            score = (cheby_sum, manhattan_sum)
            if DEBUG:
                scored.append((score, tile))
            if is_current:
                current_score = score
                current_status = "ok"
            if best is None or score < best[0]:
                best = (score, tile)
        if DEBUG:
            scored.sort()
            top = " ".join(
                f"{t}c{s[0]}m{s[1]}" for s, t in scored[:6]
            )
            print(
                f"[PATH:FRONT] target={target} bot={bot} "
                f"n_cands={len(scored)} bl={len(blacklist)} "
                f"current={current} status={current_status} "
                f"current_score={current_score} top: {top}"
            )
        if best is None:
            DEBUG and print(f"[PATH:FRONT] no frontier candidates")
            return None
        # Hysteresis: stick with current if still valid & close enough
        # in score. Slack on cheby_sum scales with the best score so
        # short paths get small slack, long paths get more.
        if (current is not None and current_score is not None
                and current != best[1]):
            slack = max(2, best[0][0] // 8)
            if current_score[0] <= best[0][0] + slack:
                DEBUG and print(
                    f"[PATH] frontier hysteresis: keep current {current} "
                    f"score={current_score} (best={best[1]} "
                    f"score={best[0]} slack={slack})"
                )
                return current
        return best[1]

    # ── Approach picking (target unreachable, get adjacent) ────────────

    def _pick_approach_tile(
        self, target: Position, bot: Position,
    ) -> tuple[int, int] | None:
        """Return a reachable tile within Chebyshev 1 of *target*,
        choosing the one closest to the bot.

        Used when *target* itself isn't in reachable.tiles (typically
        a seen-impassable structure: enemy turret, harvester, core).
        The caller's actual goal is to be *adjacent* to the target so
        it can attack/replace/interact — getting there is what this
        function plans for.

        Returns None if no target-adjacent reachable tile exists at
        all, OR if the bot is already adjacent to the target (in
        which case the caller's job is to act, not to keep walking).
        """
        tx, ty = target.x, target.y
        bx, by = bot.x, bot.y
        # Bot already adjacent — caller's turn.
        if max(abs(bx - tx), abs(by - ty)) <= 1:
            return None
        best: tuple[int, tuple[int, int]] | None = None
        for _d, dx, dy in self._deltas:
            ax, ay = tx + dx, ty + dy
            if (ax, ay) not in self.reachable.tiles:
                continue
            cheby_bot = max(abs(ax - bx), abs(ay - by))
            cand = (cheby_bot, (ax, ay))
            if best is None or cand < best:
                best = cand
        return best[1] if best else None

    # ── Main entry point ────────────────────────────────────────────────

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
        if my_pos == target:
            return None

        DEBUG and draw_move_direction(ct, my_pos, target, 255, 100, 255)

        ctx = PassContext(ct, map_manager, self.launcher_tracker, target)
        move_fn = self._wrap_move_fn(move_function, my_pos)
        tx, ty = target.x, target.y
        bk = (my_pos.x, my_pos.y)

        def flavour_pass(x: int, y: int) -> bool:
            return passability_function(ctx, x, y)

        launcher_grid = ctx.launcher_grid
        gunner_danger = ctx.gunner_danger

        def static_pass(x: int, y: int) -> bool:
            # A* expansion uses terrain + walkable structure + flavour
            # AND avoids launcher zones unconditionally. Launcher
            # tiles are never walkable — not even the target tile.
            if not is_reachable(ctx, x, y):
                return False
            if not flavour_pass(x, y):
                return False
            if launcher_grid[x][y]:
                return False
            return True

        # Move-time danger check: launcher OR gunner. Gunners move
        # too quickly to bake into _g without thrashing, so they're
        # only checked at step time. Launcher zones are hard-blocked
        # even for the target tile.
        def in_danger(x: int, y: int) -> bool:
            return launcher_grid[x][y] or (x, y) in gunner_danger

        cd = ct.get_move_cooldown()
        can_move = cd == 0
        cheby = max(abs(my_pos.x - tx), abs(my_pos.y - ty))
        target_in_reachable = (tx, ty) in self.reachable.tiles

        if DEBUG:
            print(
                f"[PATH:HDR] pos={my_pos} target={target} cheby={cheby} "
                f"cd={cd} reachable={target_in_reachable}"
            )

        # Adjacent-step bypass.
        if can_move and cheby <= 1:
            why = None
            if not is_reachable(ctx, tx, ty):
                why = "static"
            elif in_danger(tx, ty):
                why = "danger"
            elif not flavour_pass(tx, ty):
                why = "flavour"
            elif map_manager.bot_grid[tx][ty] is not None:
                why = "bot"
            if why is None:
                d = my_pos.direction_to(target)
                DEBUG and print(f"[PATH:HDR] ADJACENT step {d}")
                DEBUG and draw_move_direction(ct, my_pos, target, 0, 255, 0)
                if move_fn(ct, d):
                    return d
            else:
                DEBUG and print(
                    f"[PATH:HDR] adjacent target blocked by {why}"
                )

        # Warmup phase: first WARMUP_MOVES turns the bot can move, skip
        # A*/frontier and let Bug2 walk toward the real target. Spawn
        # vision is too small for the frontier picker to make a sane
        # choice — Bug2 makes local progress and grows reachable.tiles
        # at the same time. Once warmup elapses, the normal A* dispatch
        # takes over with a meaningful candidate set.
        if can_move:
            self._move_count += 1
            if self._move_count <= self.WARMUP_MOVES:
                DEBUG and print(
                    f"[PATH:WARMUP] move {self._move_count}/"
                    f"{self.WARMUP_MOVES} — Bug2 to {target}"
                )
                return self._bug.step(
                    ct, map_manager, my_pos, target,
                    static_pass, in_danger, move_fn,
                )

        # Track real-target changes (clears state and forces re-pick).
        if self.current_target is None or target != self.current_target:
            DEBUG and print(f"[PATH] target change -> {target}")
            self.current_target = target
            self._effective_target = None
            # blacklist is cleared on newly_seen, not on target change

        # If we reached our previous effective target, decide whether
        # to blacklist it.
        #   Approach tile (cheby ≤ 1 to real target) — don't blacklist;
        #     this is exactly where we wanted the bot. Just clear
        #     effective so next-turn re-pick can stick.
        #   Frontier tile (cheby > 1 to real target) — blacklist.
        #     We got there but the visit didn't lift fog; revisiting
        #     would be pointless until vision changes (blacklist
        #     clears on newly_seen).
        if (self._effective_target is not None
                and bk == self._effective_target
                and self._effective_target != (tx, ty)):
            etx, ety = self._effective_target
            adjacent_to_real = max(abs(etx - tx), abs(ety - ty)) <= 1
            if adjacent_to_real:
                DEBUG and print(
                    f"[PATH] reached approach tile "
                    f"{self._effective_target} — clear (no blacklist)"
                )
            else:
                DEBUG and print(
                    f"[PATH:EXPL] reached frontier "
                    f"{self._effective_target} — blacklist"
                )
                self._frontier_blacklist.add(self._effective_target)
            self._effective_target = None

        # Decide effective target.
        #   Target reachable        → effective = target.
        #   Target unreachable      → effective = the best tile
        #                              adjacent to target (getting
        #                              the bot next to a turret /
        #                              enemy structure / etc.).
        #   No adjacent reachable   → fall back to fog frontier so
        #                              vision can grow toward target.
        #   Nothing left            → mark unreachable, wait.
        if target_in_reachable:
            new_effective: tuple[int, int] | None = (tx, ty)
        else:
            # Bot already adjacent to an unreachable target → caller's
            # job to act (attack/replace/etc.). Don't even try to plan.
            if cheby <= 1:
                DEBUG and print(
                    f"[PATH] target {target} unreachable but bot "
                    f"already adjacent — done, caller's turn"
                )
                return None
            new_effective = self._pick_approach_tile(target, my_pos)
            if new_effective is not None:
                DEBUG and print(
                    f"[PATH] approach tile {new_effective} "
                    f"(adjacent to unreachable target {target})"
                )
            else:
                # No reachable adjacent tile (target is in/behind
                # fog). Fall back to fog frontier so vision can grow.
                new_effective = self._pick_frontier(
                    map_manager, target, my_pos, self._effective_target,
                )

        if new_effective != self._effective_target:
            discarded = len(self._astar.g_map)
            waited = (
                self._wait_turns
                if self._wait_anchor == self._effective_target else 0
            )
            DEBUG and print(
                f"[PATH] effective target: {self._effective_target} -> "
                f"{new_effective} (discarding |g|={discarded} "
                f"after {waited} wait-turns)"
            )
            self._effective_target = new_effective
            self._reseeded_for = None
            self._wait_anchor = None
            self._wait_turns = 0
            # Bug2 state is per-goal — reset when the goal we're
            # navigating to changes.
            self._bug.reset()
            if new_effective is not None:
                self._astar.seed(
                    Position(new_effective[0], new_effective[1]), my_pos,
                )

        if self._effective_target is None:
            # Target unreachable and no frontier — Bug2 toward the real
            # target anyway. It'll wall-follow until cycle detection
            # bails, but that's better than standing still and may
            # uncover new terrain along the way. Mark unreachable so
            # the caller knows to pick a different target.
            DEBUG and print(
                f"[PATH] UNREACHABLE: no frontier — Bug2 toward {target}"
            )
            self._unreachable_targets.add((tx, ty))
            return self._bug.step(
                ct, map_manager, my_pos, target,
                static_pass, in_danger, move_fn,
            )

        # Expand toward bot.
        cpu_before = ct.get_cpu_time_elapsed()
        budget = max(0, (CPU_LIMIT - cpu_before) // NODE_COST)
        n_exp = self._astar.expand(
            ct, map_manager, my_pos, static_pass, self.reachable, budget,
        )
        DEBUG and print(
            f"[PATH:A*] expand b={budget} n={n_exp} "
            f"|g|={len(self._astar.g_map)} exh={self._astar.exhausted} "
            f"cpu_before={cpu_before} eff={self._effective_target}"
        )

        if not can_move:
            DEBUG and print("[PATH] cooldown — expansion only")
            return None

        # Step: descend g.
        bot_g = self._astar.g_at(my_pos.x, my_pos.y)
        if bot_g is None:
            # Reverse A* can't help — bot isn't in _g. Reasons:
            #   1. Expansion mid-flight, will reach us soon.
            #   2. Effective target is in a flavour-disconnected
            #      component (reachable.tiles ignores flavour but
            #      static_pass doesn't, so they can disagree).
            #   3. Tiny CPU budget — expansion will never catch up.
            #
            # In every case, Bug2 makes local progress toward the
            # effective target while A* keeps trying. It stays in
            # flavour-passable terrain (same static_pass as A*) and
            # provably escapes any single connected obstacle. Once
            # expansion reaches the bot (or vision opens new terrain),
            # gradient descent takes over automatically.
            eff = self._effective_target

            if self._astar.exhausted:
                # A* exhausted, bot still not in _g — the effective
                # target appears disconnected under flavour-aware
                # static_pass. Two causes:
                #   (a) Stale _g — seeded under different static
                #       conditions; a fresh re-seed may find a path.
                #   (b) Genuine disconnection — re-seed will exhaust
                #       again.
                # One-shot retry to distinguish; meanwhile Bug2 walks.
                if eff is not None and self._reseeded_for != eff:
                    DEBUG and print(
                        f"[PATH:A*] exhausted, bot not in _g — "
                        f"re-seed retry at {eff} + Bug2"
                    )
                    self._reseeded_for = eff
                    self._astar.seed(Position(eff[0], eff[1]), my_pos)
                elif eff != (tx, ty):
                    # Genuine disconnection on a frontier sub-goal:
                    # blacklist so we re-pick next turn. Bug2 still
                    # tries to make progress this turn (the frontier
                    # is the best heading we have).
                    DEBUG and print(
                        f"[PATH:EXPL] frontier {eff} disconnected — "
                        "blacklist + Bug2 this turn"
                    )
                    if eff is not None:
                        self._frontier_blacklist.add(eff)
                    self._effective_target = None
                    self._reseeded_for = None

            # Wait-turn counter (diagnostic only — we don't actually
            # wait, but it tracks how long Bug2's been carrying us).
            if self._wait_anchor == self._effective_target:
                self._wait_turns += 1
            else:
                self._wait_anchor = self._effective_target
                self._wait_turns = 1

            bug_target = Position(eff[0], eff[1]) if eff is not None else target
            DEBUG and print(
                f"[PATH:BUG] bot not in _g — Bug2 to {bug_target} "
                f"(anchor={self._effective_target} wait_turn={self._wait_turns} "
                f"|g|={len(self._astar.g_map)} budget={budget} n_exp={n_exp} "
                f"exh={self._astar.exhausted})"
            )
            return self._bug.step(
                ct, map_manager, my_pos, bug_target,
                static_pass, in_danger, move_fn,
            )

        # Descent reachable — clear wait counter so future stalls show
        # a fresh count.
        self._wait_anchor = None
        self._wait_turns = 0

        return self._descend(
            ct, map_manager, my_pos, target, bot_g,
            static_pass, in_danger, move_fn,
        )

    # ── Gradient descent step ──────────────────────────────────────────

    def _descend(
        self,
        ct,
        mm: MapManager,
        my_pos: Position,
        target: Position,
        bot_g: int,
        static_pass,
        in_danger,
        move_fn,
    ) -> Direction | None:
        """Pick the bot's neighbour with the smallest _g.

        Strict-progress: only consider neighbours with g < bot_g —
        never lateral or regressing.

        If every g-decreasing neighbour is blocked (by ally, enemy, or
        danger), Bug2 takes over to route around.
        """
        candidates: list[tuple[int, int, tuple[int, int], Direction]] = []
        cand_dbg: list[str] = []
        my_team = ct.get_team()
        # When a neighbour has _g but now fails static_pass, the search
        # graph is stale w.r.t. dangers (launcher zone activated, etc.)
        # — _g still routes through tiles that are no longer walkable.
        # Track this so we can re-seed instead of waiting on a chain
        # that's silently broken.
        stale_g_static = False
        from cambc import Environment as _Env
        for d, dx, dy in self._deltas:
            nx, ny = my_pos.x + dx, my_pos.y + dy
            if not (0 <= nx < mm.width and 0 <= ny < mm.height):
                if DEBUG:
                    cand_dbg.append(f"({nx},{ny})!oob")
                continue

            if DEBUG:
                tile_v = mm.tile_grid[nx][ny]
                if tile_v is None:
                    tdesc = "fog"
                elif tile_v is _Env.WALL:
                    tdesc = "wall"
                else:
                    tdesc = "ok"
                bld = mm.building_grid[nx][ny]
                bdesc = "" if bld is None else f",{bld.entity_type.name}"
                bot_here = mm.bot_grid[nx][ny]
                bothere = (
                    "" if bot_here is None
                    else f",bot{bot_here.team}/{bot_here.id}"
                )

            g = self._astar.g_at(nx, ny)
            if g is None:
                if DEBUG:
                    # Distinguish why a tile isn't in _g.
                    if not static_pass(nx, ny):
                        cand_dbg.append(f"({nx},{ny})!static[{tdesc}{bdesc}{bothere}]")
                    else:
                        cand_dbg.append(f"({nx},{ny})!g[{tdesc}{bdesc}{bothere}]")
                continue
            if not static_pass(nx, ny):
                # Tile is in _g but static_pass now rejects → stale.
                # Most likely: launcher zone activated since expansion.
                stale_g_static = True
                if DEBUG:
                    cand_dbg.append(
                        f"({nx},{ny})!static[{tdesc}{bdesc}{bothere}](stale_g)"
                    )
                continue
            block_reason = None
            blocker_bot = mm.bot_grid[nx][ny]
            if blocker_bot is not None:
                block_reason = "B" if blocker_bot.team == my_team else "E"
            elif in_danger(nx, ny):
                block_reason = "D"
            blocked = block_reason is not None
            # Tiebreak: diagonals win pure g-ties (is_card=0 < 1). On
            # uniform-cost open ground, diagonal and cardinal-toward-axis
            # always tie on g; without this, the (nx,ny) coord tiebreak
            # would systematically pick cardinal and produce staircases.
            is_card = 0 if (dx != 0 and dy != 0) else 1
            candidates.append((1 if blocked else 0, g, is_card, (nx, ny), d))
            if DEBUG:
                tag = f"/X{block_reason}" if blocked else ""
                cand_dbg.append(f"({nx},{ny})g{g}{tag}[{tdesc}{bdesc}{bothere}]")

        DEBUG and print(
            f"[PATH:A*] bot_g={bot_g} cands: {' '.join(cand_dbg)}"
        )

        if not candidates:
            eff = self._effective_target
            bug_target = Position(eff[0], eff[1]) if eff is not None else target
            DEBUG and print(
                f"[PATH:BUG] no g-known passable neighbour — Bug2 to {bug_target}"
            )
            return self._bug.step(
                ct, mm, my_pos, bug_target,
                static_pass, in_danger, move_fn,
            )

        candidates.sort()

        progress = [c for c in candidates if c[1] < bot_g]

        # Staircase diagnostic: dump the full progress ranking so we can
        # see if a diagonal lost a tie to a cardinal, or if diagonal
        # candidates exist but are blocked, etc.
        if STAIR_DEBUG and progress:
            top = progress[:4]
            ranked = " ".join(
                f"{'D' if _is_diag(c[4]) else 'C'}:{c[4].name[:2]}"
                f"{'X' if c[0] else ''}g{c[1]}"
                for c in top
            )
            best_diag_g = min(
                (c[1] for c in progress if _is_diag(c[4]) and not c[0]),
                default=None,
            )
            best_card_g = min(
                (c[1] for c in progress if not _is_diag(c[4]) and not c[0]),
                default=None,
            )
            tag = ""
            if (best_diag_g is not None and best_card_g is not None
                    and best_diag_g == best_card_g):
                tag = " [TIE]"
            elif best_diag_g is not None and (
                    best_card_g is None or best_diag_g < best_card_g):
                tag = " [DIAG-WINS]"
            elif best_card_g is not None and (
                    best_diag_g is None or best_card_g < best_diag_g):
                tag = " [CARD-WINS]"
            print(
                f"[STAIR] pos={my_pos} bot_g={bot_g} "
                f"diag={best_diag_g} card={best_card_g}{tag} | {ranked}"
            )
        if not progress:
            # Stale-_g detection: at least one neighbour has _g but
            # currently fails static_pass (launcher zone activated
            # since expansion, terrain changed, etc.). The chain is
            # broken — re-seed reverse A* with current dangers so a
            # new path can route around them.
            if stale_g_static and self._effective_target is not None:
                DEBUG and print(
                    f"[PATH:A*] stale _g detected — RE-SEED + Bug2"
                )
                self._astar.seed(
                    Position(self._effective_target[0],
                             self._effective_target[1]),
                    my_pos,
                )
            eff = self._effective_target
            bug_target = Position(eff[0], eff[1]) if eff is not None else target
            DEBUG and print(
                f"[PATH:BUG] no g-decreasing neighbour "
                f"(bot_g={bot_g}) — Bug2 to {bug_target}"
            )
            return self._bug.step(
                ct, mm, my_pos, bug_target,
                static_pass, in_danger, move_fn,
            )

        for blocked, g_val, _is_card, nb, d in progress:
            if blocked:
                continue
            DEBUG and print(
                f"[PATH:A*] step -> {nb} g={g_val} (bot_g={bot_g})"
            )
            # Diagonal squeeze diagnostic: when we step diagonally,
            # also print the two cardinal "squeeze" tiles. Many grid
            # engines refuse a diagonal move if either cardinal is
            # impassable — knowing those tiles' state tells us if
            # the engine is rejecting for that reason.
            if DEBUG:
                ddx, ddy = d.delta()
                if ddx != 0 and ddy != 0:
                    c1x, c1y = my_pos.x + ddx, my_pos.y
                    c2x, c2y = my_pos.x, my_pos.y + ddy

                    def _desc(x, y):
                        if not (0 <= x < mm.width and 0 <= y < mm.height):
                            return "oob"
                        from cambc import Environment as _Env
                        t = mm.tile_grid[x][y]
                        if t is None:
                            tag = "fog"
                        elif t is _Env.WALL:
                            tag = "wall"
                        else:
                            tag = "ok"
                        b = mm.building_grid[x][y]
                        bt = "" if b is None else f",{b.entity_type.name}"
                        return f"{tag}{bt}"

                    print(
                        f"[PATH:A*] diagonal step squeeze check: "
                        f"({c1x},{c1y})=[{_desc(c1x, c1y)}] "
                        f"({c2x},{c2y})=[{_desc(c2x, c2y)}]"
                    )
            DEBUG and draw_move_direction(
                ct, my_pos, Position(nb[0], nb[1]), 0, 255, 0,
            )
            if move_fn(ct, d):
                DEBUG and print(f"[PATH:A*] MOVE OK {d}")
                if STAIR_DEBUG:
                    print(
                        f"[STAIR] MOVED {'DIAG' if _is_diag(d) else 'CARD'} "
                        f"{d.name} -> {nb} g={g_val}"
                    )
                return d
            # move_fn rejected. Pull out everything we can about *why*
            # so we can diagnose: ct.can_move result, tile contents,
            # building, bot occupant, resources vs road_cost, cooldown.
            if DEBUG or STAIR_DEBUG:
                cm = False
                try:
                    cm = ct.can_move(d)
                except Exception as e:
                    cm = f"err({e})"
                tile = mm.tile_grid[nb[0]][nb[1]]
                bld = mm.building_grid[nb[0]][nb[1]]
                bot = mm.bot_grid[nb[0]][nb[1]]
                resources = ct.get_global_resources()[0]
                road_cost = ct.get_road_cost()[0]
                cd_now = ct.get_move_cooldown()
                kind = 'DIAG' if _is_diag(d) else 'CARD'
                squeeze = ""
                if _is_diag(d):
                    ddx, ddy = d.delta()
                    c1x, c1y = my_pos.x + ddx, my_pos.y
                    c2x, c2y = my_pos.x, my_pos.y + ddy
                    from cambc import Environment as _Env
                    def _sq(x, y):
                        if not (0 <= x < mm.width and 0 <= y < mm.height):
                            return "oob"
                        t = mm.tile_grid[x][y]
                        if t is None: tag = "fog"
                        elif t is _Env.WALL: tag = "wall"
                        else: tag = "ok"
                        b = mm.building_grid[x][y]
                        bt = "" if b is None else f",{b.entity_type.name}"
                        bh = mm.bot_grid[x][y]
                        bo = "" if bh is None else f",bot"
                        return f"{tag}{bt}{bo}"
                    squeeze = (
                        f" squeeze=({c1x},{c1y})[{_sq(c1x,c1y)}] "
                        f"({c2x},{c2y})[{_sq(c2x,c2y)}]"
                    )
                print(
                    f"[STAIR] REJECT {kind} {d.name} -> {nb} | "
                    f"can_move={cm} tile={tile} "
                    f"bld={None if bld is None else bld.entity_type} "
                    f"bot={None if bot is None else f'{bot.team}/{bot.id}'} "
                    f"res={resources} road_cost={road_cost} cd={cd_now}"
                    f"{squeeze}"
                )
            # move_fn rejected this candidate (engine squeeze, can't
            # afford road, etc.). Try the next g-decreasing candidate
            # instead of waiting — staircase fix #1.
            continue

        # Every g-decreasing candidate is blocked or move_fn-rejected.
        eff = self._effective_target
        bug_target = Position(eff[0], eff[1]) if eff is not None else target
        DEBUG and print(
            f"[PATH:BUG] all g-decreasing neighbours blocked — "
            f"Bug2 to {bug_target}"
        )
        return self._bug.step(
            ct, mm, my_pos, bug_target,
            static_pass, in_danger, move_fn,
        )

