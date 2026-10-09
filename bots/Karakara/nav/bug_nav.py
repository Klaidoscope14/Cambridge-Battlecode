"""Bug2-style local planner.

Used as a *fallback* when the global planner (reverse A*) can't help
the bot — typically because the effective target is in a flavour-
disconnected component, or because expansion is mid-flight and the
bot's tile isn't in _g yet. The bot moves greedily toward the goal;
when blocked by an obstacle it follows the wall under a fixed
rotation rule until it has made strict h-progress past the obstacle,
then resumes greedy.

Two layers of entry/exit:

  Layer 1 — Bug2 vs reverse A* (decided in Pathing each turn):
    Active when bot has no _g AND caller opted in via local_fallback.
    Auto-exits when reverse A* expansion reaches the bot.

  Layer 2 — wall-follow inside Bug2 (this module):
    Enters when a greedy direct step toward the goal is blocked.
    Exits when current h-to-goal drops strictly below the h at which
    wall-follow started (entry_h). This is what gives Bug2 its
    termination guarantee on any single connected obstacle.

State:
    _entry_h     None when not wall-following; stored at entry.
    _rotate_right rotation rule (right-hand by default). Persistent
                 across goals — keeps the bot's preferred direction
                 stable. Flips only on full 8-rotation failure.
    _last_dir    last direction taken; used as the rotation start so
                 the bot continues hugging the wall consistently.
    _target_key  current goal; resets entry/last_dir on change.

Tile predicates:
    static_pass — terrain + walkable structure + flavour. The same
                  predicate the global planner uses, so Bug2 doesn't
                  walk into fog or unaffordable empty tiles.
    in_danger   — launcher/gunner zones (target tile exempt).
    bot_grid    — builder bots block.
"""
from __future__ import annotations

from cambc import Direction, Position
from debug.indicators import draw_move_direction
from map.map_manager import MapManager

from nav.config import DEBUG


class BugNav:
    def __init__(self, deltas: list) -> None:
        self._deltas = deltas
        self._entry_h: int | None = None
        self._rotate_right: bool = True
        self._last_dir: Direction | None = None
        self._target_key: tuple[int, int] | None = None
        # Cycle detection. h-progress alone (cur_h < entry_h) doesn't
        # guarantee termination under Chebyshev — wall-follow can orbit
        # an obstacle on tiles whose h never drops below entry_h. We
        # track (pos, last_dir) pairs visited during the current
        # wall-follow; revisiting one means we're looping.
        self._wf_seen: set = set()

    def reset(self) -> None:
        """Full reset (rotation preference preserved)."""
        self._entry_h = None
        self._last_dir = None
        self._target_key = None
        self._wf_seen = set()

    def step(
        self,
        ct,
        mm: MapManager,
        bot: Position,
        goal: Position,
        static_pass,
        in_danger,
        move_fn,
    ) -> Direction | None:
        # Reset wall-follow state if goal changed since last call.
        gk = (goal.x, goal.y)
        if self._target_key != gk:
            DEBUG and print(f"[BUG] new goal {goal} — reset wall-follow state")
            self._entry_h = None
            self._last_dir = None
            self._wf_seen = set()
            self._target_key = gk

        cur_h = max(abs(bot.x - goal.x), abs(bot.y - goal.y))

        # Wall-follow exit check BEFORE attempting anything. The exit
        # condition is the *only* thing that gives Bug2 its termination
        # guarantee — never weaken it.
        if self._entry_h is not None and cur_h < self._entry_h:
            DEBUG and print(
                f"[BUG] exit wall-follow (h={cur_h} < entry_h={self._entry_h})"
            )
            self._entry_h = None
            self._last_dir = None
            self._wf_seen = set()

        # Cycle detection. If we're wall-following and have already
        # visited this (pos, last_dir) state before, the wall-follow is
        # orbiting without making h-progress — bail. Caller will see
        # None and either wait, blacklist the goal, or pick a new one.
        if self._entry_h is not None:
            key = (bot.x, bot.y, self._last_dir)
            if key in self._wf_seen:
                DEBUG and print(
                    f"[BUG] cycle detected at {bot} last_dir={self._last_dir} "
                    f"(h={cur_h} entry_h={self._entry_h}) — abort wall-follow"
                )
                self._entry_h = None
                self._last_dir = None
                self._wf_seen = set()
                return None
            self._wf_seen.add(key)

        w, h_dim = mm.width, mm.height
        bot_grid = mm.bot_grid

        def passable(d: Direction) -> bool:
            if d == Direction.CENTRE:
                return False
            dx, dy = d.delta()
            nx, ny = bot.x + dx, bot.y + dy
            if not (0 <= nx < w and 0 <= ny < h_dim):
                return False
            if not static_pass(nx, ny):
                return False
            if bot_grid[nx][ny] is not None:
                return False
            if in_danger(nx, ny):
                return False
            return True

        direct = bot.direction_to(goal)

        # Greedy attempt — only when NOT currently wall-following.
        # If we're wall-following, we keep doing it until exit
        # condition fires (entry_h cleared above).
        if self._entry_h is None:
            if direct != Direction.CENTRE and passable(direct):
                DEBUG and print(f"[BUG] direct {direct} h={cur_h}")
                DEBUG and draw_move_direction(
                    ct, bot, bot.add(direct), 200, 0, 200,
                )
                if move_fn(ct, direct):
                    self._last_dir = direct
                    return direct
                DEBUG and print(f"[BUG] direct {direct} move_fn rejected")
                return None
            # Greedy blocked — enter wall-follow.
            self._entry_h = cur_h
            self._last_dir = direct if direct != Direction.CENTRE else Direction.NORTH
            DEBUG and print(
                f"[BUG] enter wall-follow at h={cur_h} "
                f"(direct {direct} blocked)"
            )

        # Wall-follow rotation. Start from last_dir and rotate in the
        # active direction (right-hand or left-hand) until we find a
        # passable direction. The rotation rule is what makes Bug2
        # actually *follow* a wall instead of jittering.
        chosen = self._scan_rotation(self._last_dir, passable)
        if chosen is None:
            # Full rotation blocked. Flip rotation direction and retry
            # — handles dead-end pockets and map-boundary corner cases.
            self._rotate_right = not self._rotate_right
            DEBUG and print(
                f"[BUG] full rotation blocked — flipped to "
                f"right={self._rotate_right}"
            )
            chosen = self._scan_rotation(self._last_dir, passable)

        if chosen is None:
            DEBUG and print("[BUG] all 8 directions blocked — wait")
            return None

        DEBUG and print(
            f"[BUG] wall-follow {chosen} (rot={'R' if self._rotate_right else 'L'} "
            f"h={cur_h} entry_h={self._entry_h})"
        )
        DEBUG and draw_move_direction(ct, bot, bot.add(chosen), 200, 0, 200)
        if move_fn(ct, chosen):
            self._last_dir = chosen
            return chosen
        DEBUG and print(f"[BUG] wall-follow {chosen} move_fn rejected")
        return None

    def _scan_rotation(
        self, start: Direction | None, passable,
    ) -> Direction | None:
        """Wall-hugging scan from *start* (the last direction taken).

        Right-hand rule: keep the wall on the bot's right. After moving
        in direction ``start``, the wall that blocked greedy lies
        roughly to the right, so the first candidate must turn *into*
        the wall (90° right of start), then sweep counter-clockwise
        back through forward and around. Left-hand rule mirrors.

        Starting the scan one tick *past* start (the previous bug) made
        the bot drift away from the wall in open terrain — once the
        wall ended, every step rotated 45° in the same direction,
        tracing a circle instead of returning to greedy.
        """
        if start is None or start == Direction.CENTRE:
            start = Direction.NORTH
        if self._rotate_right:
            # 90° right of start, then sweep counter-clockwise.
            d = start.rotate_right().rotate_right()
        else:
            d = start.rotate_left().rotate_left()
        for _ in range(8):
            if passable(d):
                return d
            d = d.rotate_left() if self._rotate_right else d.rotate_right()
        return None
