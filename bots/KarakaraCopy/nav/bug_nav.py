"""Bug navigation — Xsquare-style wall-following fallback for large obstacles.

Based on Ivan Geffner's (Xsquare) BugNav from his Battlecode 2025 code.
Adapted for Cambridge Battlecode's 8-directional grid with passability
functions and Chebyshev distance.

Key features over a basic wall-follow:
  - Greedy-first: every step tries direct movement before wall-following.
  - Obstacle tracking: records the actual blocked tile, not just a direction.
  - Min-distance exit: resets wall-follow whenever a new closest distance
    to target is achieved (not just beating the entry distance).
  - Loop detection: encodes (path_index, rotation, obstacle_dir) at each
    cell — if the same state is seen twice, resets to avoid infinite loops.
  - Boundary flip: reverses rotation when hitting the map edge.
  - Dynamic obstacle handling: resets after 2 consecutive turns moving
    toward the same obstacle (it may have moved or we're stuck).

Indicator colour:
  Purple  (200,0,200) — bug nav wall following
"""

from __future__ import annotations

from cambc import Direction, Position
from nav.config import (
    DEBUG, BUG_OSCILLATION_WINDOW, BUG_OSCILLATION_THRESHOLD, BUG_MAX_TURNS,
)
from debug.indicators import draw_move_direction
from map.map_manager import MapManager

# Directions in rotation order for index encoding.
_DIR_ORDINALS = {
    Direction.NORTH: 0, Direction.NORTHEAST: 1, Direction.EAST: 2,
    Direction.SOUTHEAST: 3, Direction.SOUTH: 4, Direction.SOUTHWEST: 5,
    Direction.WEST: 6, Direction.NORTHWEST: 7, Direction.CENTRE: 8,
}

_MAX_TURNS_TOWARD_OBSTACLE = 2

# Enter bug nav after this many consecutive turns blocked behind a bot
# (no positional progress, blocker on direct line to target, no A* path).
_STUCK_BEHIND_BOT_THRESHOLD = 2


class BugNav:
    """Xsquare-style bug navigation state machine."""

    def __init__(self) -> None:
        self.active: bool = False

        # Wall-follow state
        self._obstacle: tuple[int, int] | None = None  # (x,y) of last obstacle
        self._rotate_right: bool | None = None          # None = undecided
        self._min_dist: int = 100_000_000               # best distance achieved
        self._min_location: tuple[int, int] | None = None
        self._bug_path_index: int = 0                   # incremented per reset
        self._turns_toward_obstacle: int = 0
        self._turns: int = 0

        # Loop detection: (x, y) -> encoded state
        self._states: dict[tuple[int, int], int] = {}

        # Oscillation detection (unchanged — detects WHEN to enter bug nav)
        self._pos_history: list[tuple[int, int]] = []

        # Stuck-behind-bot detection: counts consecutive turns the bot
        # didn't move while a bot sat on the tile toward the target.
        self._stuck_turns: int = 0
        self._stuck_last_pos: tuple[int, int] | None = None

    # ── Public API (signatures unchanged for pathing.py) ────────────────

    def reset(self) -> None:
        """Full reset — call when target changes."""
        self.active = False
        self._obstacle = None
        self._rotate_right = None
        self._min_dist = 100_000_000
        self._min_location = None
        self._bug_path_index = 0
        self._turns_toward_obstacle = 0
        self._turns = 0
        self._states.clear()
        self._pos_history.clear()
        self._stuck_turns = 0
        self._stuck_last_pos = None

    def track_position(self, my_pos: Position) -> None:
        """Record position for oscillation detection (only if changed)."""
        pos_xy = (my_pos.x, my_pos.y)
        if not self._pos_history or self._pos_history[-1] != pos_xy:
            self._pos_history.append(pos_xy)
            if len(self._pos_history) > BUG_OSCILLATION_WINDOW:
                self._pos_history.pop(0)

    def track_stuck(self, my_pos: Position, target: Position,
                    mm: MapManager, has_astar_path: bool) -> None:
        """Track consecutive turns blocked behind a bot toward the target.

        Increments when: same position as last turn, no A* path, and the
        tile in `direction_to(target)` is bot-occupied. Otherwise resets.
        """
        pos_xy = (my_pos.x, my_pos.y)
        if has_astar_path or pos_xy != self._stuck_last_pos:
            self._stuck_turns = 0
            self._stuck_last_pos = pos_xy
            return

        d = my_pos.direction_to(target)
        if d == Direction.CENTRE:
            self._stuck_turns = 0
            return
        nxt = my_pos.add(d)
        if not (0 <= nxt.x < mm.width and 0 <= nxt.y < mm.height):
            self._stuck_turns = 0
            return
        if mm.bot_grid[nxt.x][nxt.y] is not None:
            self._stuck_turns += 1
            DEBUG and print(
                f"[BUG] STUCK behind bot at {nxt}, count={self._stuck_turns}"
            )
        else:
            self._stuck_turns = 0

    def should_enter(self, my_pos: Position, target: Position,
                     has_astar_path: bool) -> bool:
        """Return True if oscillation or stuck-behind-bot is detected."""
        if self.active:
            return False
        if has_astar_path:
            return False

        if self._stuck_turns >= _STUCK_BEHIND_BOT_THRESHOLD:
            DEBUG and print(
                f"[BUG] enter via stuck-behind-bot ({self._stuck_turns} turns)"
            )
            return True

        if len(self._pos_history) < BUG_OSCILLATION_WINDOW:
            return False

        old_x, old_y = self._pos_history[0]
        old_dist = max(abs(old_x - target.x), abs(old_y - target.y))
        cur_dist = max(abs(my_pos.x - target.x), abs(my_pos.y - target.y))
        unique_pos = len(set(self._pos_history))

        return (cur_dist >= old_dist - BUG_OSCILLATION_THRESHOLD
                and unique_pos >= 3)

    def enter(self, ct, mm: MapManager, my_pos: Position,
              target: Position) -> None:
        """Activate bug nav.  Rotation direction is deferred to first hit."""
        self.active = True
        self._obstacle = None
        self._rotate_right = None
        self._min_dist = max(abs(my_pos.x - target.x),
                             abs(my_pos.y - target.y))
        self._min_location = (my_pos.x, my_pos.y)
        self._bug_path_index += 1
        self._turns_toward_obstacle = 0
        self._turns = 0
        self._states.clear()
        self._pos_history.clear()
        self._stuck_turns = 0
        self._stuck_last_pos = None

        DEBUG and print(
            f"[BUG] ENTER: pos={my_pos} target={target} "
            f"min_dist={self._min_dist}"
        )

    def step(self, ct, mm: MapManager, my_pos: Position,
             target: Position, pass_fn, move_fn,
             reachable: set | None = None) -> Direction | None:
        """Execute one turn of Xsquare-style bug nav.

        Returns the move direction, or None if bug nav exited / stuck.
        If *reachable* is provided and the bot has reached a tile A*
        never expanded, we've broken past the wall — exit immediately
        so A* can re-expand from this new territory.
        """
        w, h = mm.width, mm.height
        cur_dist = max(abs(my_pos.x - target.x), abs(my_pos.y - target.y))

        self._turns += 1

        # Timeout
        if self._turns > BUG_MAX_TURNS:
            DEBUG and print(f"[BUG] EXIT: timeout after {self._turns} turns")
            self._exit()
            return None

        # Reached unexplored territory — A* can take over from here
        if (reachable is not None
                and (my_pos.x, my_pos.y) not in reachable
                and self._turns > 1):
            DEBUG and print(
                f"[BUG] EXIT: reached unexplored tile {my_pos} "
                f"(not in {len(reachable)} reachable)"
            )
            self._exit()
            return None

        # ── Loop detection ──────────────────────────────────────────
        if self._obstacle is not None:
            obs_dir = my_pos.direction_to(Position(self._obstacle[0],
                                                   self._obstacle[1]))
            state = (self._bug_path_index << 6)
            if self._rotate_right is not None:
                state |= (1 if self._rotate_right else 2)
            state |= (_DIR_ORDINALS.get(obs_dir, 8) << 2)

            pos_key = (my_pos.x, my_pos.y)
            if self._states.get(pos_key) == state:
                DEBUG and print(f"[BUG] LOOP detected at {my_pos}, resetting wall-follow")
                self._reset_wall_follow()
                return None
            self._states[pos_key] = state

        # ── Min distance check — free if closer than ever ───────────
        if cur_dist < self._min_dist:
            DEBUG and print(
                f"[BUG] PROGRESS: dist={cur_dist} < min={self._min_dist}, "
                f"resetting wall-follow"
            )
            self._reset_wall_follow()
            self._min_dist = cur_dist
            self._min_location = (my_pos.x, my_pos.y)

        # ── Greedy attempt (when not wall-following) ────────────────
        if self._obstacle is None:
            result = self._try_greedy(ct, mm, my_pos, target, pass_fn,
                                      move_fn, w, h)
            if result is not None:
                self._reset_wall_follow()
                return result
            # Greedy failed — we've hit an obstacle

        # ── Determine direction toward obstacle or target ───────────
        if self._obstacle is not None:
            d = my_pos.direction_to(Position(self._obstacle[0],
                                            self._obstacle[1]))
        else:
            d = my_pos.direction_to(target)

        # ── Try moving toward obstacle (it might have cleared) ──────
        if self._can_move(ct, mm, my_pos, d, pass_fn, w, h):
            nxt = my_pos.add(d)
            DEBUG and draw_move_direction(ct, my_pos, nxt, 200, 0, 200)
            move_fn(ct, d)

            if self._obstacle is not None:
                self._turns_toward_obstacle += 1
                # Update obstacle to the tile beyond where we moved
                beyond = nxt.add(d)
                self._obstacle = (beyond.x, beyond.y)

                if self._turns_toward_obstacle >= _MAX_TURNS_TOWARD_OBSTACLE:
                    DEBUG and print(f"[BUG] Reset: {self._turns_toward_obstacle} turns toward obstacle")
                    self._reset_wall_follow()
                elif not (0 <= beyond.x < w and 0 <= beyond.y < h):
                    self._reset_wall_follow()
            return d

        self._turns_toward_obstacle = 0

        # ── Choose rotation direction (first time hitting obstacle) ─
        if self._rotate_right is None:
            self._choose_rotation(ct, mm, my_pos, target, pass_fn, d, w, h)

        # ── Wall-follow rotation loop ───────────────────────────────
        # Up to 16 iterations (can flip direction mid-loop)
        for _ in range(16):
            if self._can_move(ct, mm, my_pos, d, pass_fn, w, h):
                nxt = my_pos.add(d)
                DEBUG and print(
                    f"[BUG] WALL-FOLLOW: {my_pos} -> {nxt} dir={d} "
                    f"rotate_right={self._rotate_right} turn={self._turns}"
                )
                DEBUG and draw_move_direction(ct, my_pos, nxt, 200, 0, 200)
                move_fn(ct, d)
                return d

            nxt_pos = my_pos.add(d)
            if not (0 <= nxt_pos.x < w and 0 <= nxt_pos.y < h):
                # Hit map boundary — flip rotation
                self._rotate_right = not self._rotate_right
            else:
                # This tile is the obstacle
                self._obstacle = (nxt_pos.x, nxt_pos.y)

            if self._rotate_right:
                d = d.rotate_right()
            else:
                d = d.rotate_left()

        # Exhausted all directions
        DEBUG and print(f"[BUG] EXIT: stuck at {my_pos}")
        self._exit()
        return None

    def exit_if_astar_ready(self, has_path: bool) -> None:
        """Exit bug nav if A* found a complete usable path."""
        if self.active and has_path:
            DEBUG and print("[BUG] EXIT: A* found path")
            self._exit()

    # ── Internal helpers ────────────────────────────────────────────

    def _can_move(self, ct, mm: MapManager, my_pos: Position,
                  d: Direction, pass_fn, w: int, h: int) -> bool:
        """Check if moving in direction d is valid.

        pass_fn is the bound (x, y) -> bool closure from Pathing.
        """
        if d == Direction.CENTRE:
            return False
        nxt = my_pos.add(d)
        nx, ny = nxt.x, nxt.y
        if not (0 <= nx < w and 0 <= ny < h):
            return False
        if mm.bot_grid[nx][ny] is not None:
            return False
        return pass_fn(nx, ny)

    def _try_greedy(self, ct, mm: MapManager, my_pos: Position,
                    target: Position, pass_fn, move_fn,
                    w: int, h: int) -> Direction | None:
        """Try direct move toward target, then ±45 degrees.

        Returns direction if moved, None if all blocked.
        """
        direct = my_pos.direction_to(target)
        cur_dist = max(abs(my_pos.x - target.x), abs(my_pos.y - target.y))

        # Try direct
        if self._can_move(ct, mm, my_pos, direct, pass_fn, w, h):
            nxt = my_pos.add(direct)
            DEBUG and draw_move_direction(ct, my_pos, nxt, 200, 0, 200)
            move_fn(ct, direct)
            return direct

        # Try ±45 degrees — pick whichever gets closer
        d_right = direct.rotate_right()
        d_left = direct.rotate_left()

        can_right = self._can_move(ct, mm, my_pos, d_right, pass_fn, w, h)
        can_left = self._can_move(ct, mm, my_pos, d_left, pass_fn, w, h)

        if can_right or can_left:
            dist_right = 100_000_000
            dist_left = 100_000_000
            if can_right:
                nr = my_pos.add(d_right)
                dist_right = max(abs(nr.x - target.x), abs(nr.y - target.y))
            if can_left:
                nl = my_pos.add(d_left)
                dist_left = max(abs(nl.x - target.x), abs(nl.y - target.y))

            if dist_right < cur_dist and dist_right <= dist_left:
                nxt = my_pos.add(d_right)
                DEBUG and draw_move_direction(ct, my_pos, nxt, 200, 0, 200)
                move_fn(ct, d_right)
                return d_right
            if dist_left < cur_dist and dist_left < dist_right:
                nxt = my_pos.add(d_left)
                DEBUG and draw_move_direction(ct, my_pos, nxt, 200, 0, 200)
                move_fn(ct, d_left)
                return d_left

        # Greedy failed — record the obstacle (blocked tile in direct dir)
        blocked = my_pos.add(direct)
        if 0 <= blocked.x < w and 0 <= blocked.y < h:
            self._obstacle = (blocked.x, blocked.y)
        return None

    def _choose_rotation(self, ct, mm: MapManager, my_pos: Position,
                         target: Position, pass_fn, d: Direction,
                         w: int, h: int) -> None:
        """Choose CW vs CCW by scanning both ways from blocked direction."""
        d_left = d
        d_right = d

        for _ in range(8):
            if not self._can_move(ct, mm, my_pos, d_left, pass_fn, w, h):
                d_left = d_left.rotate_left()
            else:
                break

        for _ in range(8):
            if not self._can_move(ct, mm, my_pos, d_right, pass_fn, w, h):
                d_right = d_right.rotate_right()
            else:
                break

        left_pos = my_pos.add(d_left)
        right_pos = my_pos.add(d_right)
        dist_left = max(abs(left_pos.x - target.x),
                        abs(left_pos.y - target.y))
        dist_right = max(abs(right_pos.x - target.x),
                         abs(right_pos.y - target.y))

        self._rotate_right = dist_right < dist_left
        DEBUG and print(
            f"[BUG] CHOOSE ROTATION: right={self._rotate_right} "
            f"dist_left={dist_left} dist_right={dist_right}"
        )

    def _reset_wall_follow(self) -> None:
        """Reset wall-following state but stay in bug nav mode."""
        self._obstacle = None
        self._rotate_right = None
        self._bug_path_index += 1
        self._turns_toward_obstacle = 0

    def _exit(self) -> None:
        """Fully exit bug nav mode."""
        self.active = False
        self._obstacle = None
        self._rotate_right = None
        self._min_dist = 100_000_000
        self._min_location = None
        self._turns_toward_obstacle = 0
        self._turns = 0
        self._states.clear()
        self._pos_history.clear()
        self._stuck_turns = 0
        self._stuck_last_pos = None
