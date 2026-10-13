"""
Architecture:
  1. greedy() — try to move the simulated position toward the target by picking
     the neighbor that minimises distance (with scoring tie-breaks).  If stuck,
     switch to bug mode.
  2. bug()   — wall-follow (clockwise or counterclockwise) until the simulated
     position improves on its best-known distance to the target.
  3. BFS flood — from the simulated position, flood-fill over the local vision
     grid to compute the BFS distance from each of the 8+1 neighbors of the
     real unit to the simulated position.  Pick the best movable direction
     using (penalty, bfs_dist, bug_dist) as the sort key.
  4. Move the real unit in that direction — building a road first if the
     destination tile is empty ground.

The simulation goal is to reach a tile *adjacent* to the target, not the
target itself.  The target may be impassable (e.g. an enemy core, a
harvester we want to interact with).  _is_passable checks only whether a
tile is structurally walkable — it knows nothing about the target.
"""

from __future__ import annotations
import random
from cambc import Direction, Position
from debug.indicators import draw_move_direction
from debug.profiling import cputimer
from helpers.geometry import average_locations, on_map, in_vision
from helpers.directions import DIRECTIONS, CARDINAL
from map.map_manager import MapManager
from nav.validator import validator_on_direction


# ── Helpers ──────────────────────────────────────────────────────────────────

CENTRE = Direction.CENTRE


def _adjacent(a: Position, b: Position) -> bool:
    """True if a and b are the same tile or within chebyshev distance 1."""
    return a.distance_squared(b) <= 2

def _card_rotate_left(d: Direction, cardinal: bool):
    if cardinal: return d.rotate_left().rotate_left()
    return d.rotate_left()

def _card_rotate_right(d: Direction, cardinal: bool):
    if cardinal: return d.rotate_right().rotate_right()
    return d.rotate_right()

def _rotate(d: Direction, clockwise: bool, cardinal: bool) -> Direction:
    return _card_rotate_right(d, cardinal) if clockwise else _card_rotate_left(d, cardinal)

def _rotate_opposite(d: Direction, clockwise: bool, cardinal: bool) -> Direction:
    return _card_rotate_left(d, cardinal) if clockwise else _card_rotate_right(d, cardinal)

# ── Scoring (placeholder) ───────────────────────────────────────────────────

def score_tile(ct, pos: Position) -> int:
    """
    Return a penalty score for standing on *pos*.

    Lower is better.  This is the hook for paint / enemy territory / etc.
    Currently returns 0 for every tile (placeholder).
    """
    return 0

# ── Pathing class ────────────────────────────────────────────────────────────

# Maximum number of positions we remember in the bug path trail
_MAX_PATH_BACKUP = 50
# Number of greedy/bug simulation steps per path_to call
_SIM_STEPS = 7


class Pathing:
    def __init__(self, ct) -> None:
        self.current_target: Position | None = None
        self.current_bug_position: Position | None = None
        self.current_bug_direction: Direction | None = None
        self.clockwise: bool = False
        self.should_guess_rotation: bool = True
        self.best_bug_dist: int = 100_000_000
        self.should_bug: bool = False
        self.done_simulating: bool = False
        self.bug_path: list[Position] = []
        self.prev_cardinality = False

    # ── Reset ────────────────────────────────────────────────────────────

    def reset(self, ct, my_pos: Position, target: Position | None) -> None:
        self.best_bug_dist = 100_000_000
        self.should_bug = False
        self.current_target = target
        self.current_bug_direction = None
        self.current_bug_position = my_pos
        self.should_guess_rotation = True
        self.clockwise = False
        self.bug_path = []
        self.prev_cardinality = False

    # ── Trail management ─────────────────────────────────────────────────

    def _append_position(self) -> None:
        """Append the current bug position to the trail (skip duplicates)."""
        if len(self.bug_path) >= _MAX_PATH_BACKUP:
            return
        if self.bug_path and self.bug_path[-1] == self.current_bug_position:
            return
        self.bug_path.append(self.current_bug_position)

    def _set_current_position(self, ct, my_pos: Position) -> None:
        """
        Walk the trail backwards and find the most-recently-appended position
        that is still within vision.  If none is visible, reset.
        """
        vision_r_sq = ct.get_vision_radius_sq()
        for i in range(len(self.bug_path) - 1, -1, -1):
            if self.bug_path[i].distance_squared(my_pos) <= vision_r_sq:
                self.current_bug_position = self.bug_path[i]
                return
        # Nothing visible — full reset
        self.reset(ct, ct.get_position(), self.current_target)

    # ── Greedy step ──────────────────────────────────────────────────────

    def _greedy(self, ct, map_manager: MapManager, my_pos: Position, passability_function, cardinal: bool) -> None:
        """
        From the simulated bug position, try every neighbor and pick the one
        closest to the target (with score tie-break).  If none improves, enter
        bug mode.

        We only consider tiles that are actually passable — we never try to
        step onto the target itself.
        """
        dirs = CARDINAL if cardinal else DIRECTIONS

        target = self.current_target
        vision_r_sq = ct.get_vision_radius_sq()
        map_w = map_manager.width
        map_h = map_manager.height

        best_dist = self.current_bug_position.distance_squared(target)
        best_penalty = score_tile(ct, self.current_bug_position)
        best_loc = self.current_bug_position

        for d in dirs:
            new_loc = self.current_bug_position.add(d)
            if not on_map(new_loc, map_w, map_h):
                continue
            if not in_vision(my_pos, new_loc, vision_r_sq):
                # Reached edge of vision — stop simulating
                self.done_simulating = True
                return
            if not passability_function(ct, new_loc, map_manager):
                continue

            nd = new_loc.distance_squared(target)
            penalty = score_tile(ct, new_loc)

            # Prefer lower distance first, then lower penalty
            should_update = False
            if nd != best_dist:
                should_update = nd < best_dist
            else:
                should_update = penalty < best_penalty

            if should_update:
                best_dist = nd
                best_penalty = penalty
                best_loc = new_loc

        if best_loc != self.current_bug_position:
            self.current_bug_position = best_loc
        else:
            # Greedy is stuck — switch to bug mode
            self.best_bug_dist = self.current_bug_position.distance_squared(target)
            self.current_bug_direction = self.current_bug_position.direction_to(target)
            if cardinal and self.current_bug_direction not in CARDINAL:
                clamps = [self.current_bug_direction.rotate_left(), self.current_bug_direction.rotate_right()]
                self.current_bug_direction = random.choice(clamps)
            if self.current_bug_direction == CENTRE:
                return  # already there
            self.should_bug = True

    # ── Bug step ─────────────────────────────────────────────────────────

    def _bug(self, ct, map_manager: MapManager, my_pos: Position, passability_function, cardinal: bool) -> None:
        """
        Wall-following step.  Attempts to move along the current bug direction;
        if blocked, rotates (CW or CCW) until a passable neighbor is found.
        """
        target = self.current_target
        vision_r_sq = ct.get_vision_radius_sq()
        map_w = map_manager.width
        map_h = map_manager.height

        # First time entering bug: guess the better rotation direction
        if self.should_guess_rotation:
            self.should_guess_rotation = False

            dir_l = self.current_bug_direction
            for _ in range(8):
                test = self.current_bug_position.add(dir_l)
                if (on_map(test, map_w, map_h)
                        and passability_function(ct, test, map_manager)):
                    break
                dir_l = _card_rotate_left(dir_l, cardinal)

            dir_r = self.current_bug_direction
            for _ in range(8):
                test = self.current_bug_position.add(dir_r)
                if (on_map(test, map_w, map_h)
                        and passability_function(ct, test, map_manager)):
                    break
                dir_r = _card_rotate_right(dir_r, cardinal)

            loc_l = self.current_bug_position.add(dir_l)
            loc_r = self.current_bug_position.add(dir_r)
            self.clockwise = loc_r.distance_squared(target) < loc_l.distance_squared(target)

        # Try to move in the current bug direction
        new_loc = self.current_bug_position.add(self.current_bug_direction)
        if not in_vision(my_pos, new_loc, vision_r_sq):
            self.done_simulating = True
            return

        current_loc: Position | None = None
        if (on_map(new_loc, map_w, map_h)
                and passability_function(ct, new_loc, map_manager)):
            current_loc = new_loc

        # If direct path blocked, rotate until we find a passable neighbor
        if current_loc is None:
            for _ in range(8):
                self.current_bug_direction = _rotate(
                    self.current_bug_direction, self.clockwise, cardinal
                )
                new_loc = self.current_bug_position.add(self.current_bug_direction)
                if not in_vision(my_pos, new_loc, vision_r_sq):
                    self.done_simulating = True
                    return
                if not on_map(new_loc, map_w, map_h):
                    # Hit map edge — flip rotation
                    self.clockwise = not self.clockwise
                    return
                if passability_function(ct, new_loc, map_manager):
                    current_loc = new_loc
                    break

        if current_loc is not None and current_loc != self.current_bug_position:
            self.current_bug_position = current_loc
            self.current_bug_direction = _rotate_opposite(
                self.current_bug_direction, self.clockwise, cardinal
            )
            d = self.current_bug_position.distance_squared(target)
            if d < self.best_bug_dist:
                # We've improved — leave bug mode
                self.should_bug = False

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
        cardinal=False
    ) -> None:
        print(f"Pathing from {my_pos} to {target}")

        """
        Compute and execute one movement step toward *target*.

        The goal is to reach a tile *adjacent* to the target, not the target
        itself — the target may be impassable (an enemy core, a building we
        want to interact with, etc.).

        Steps:
          1. Bail early if we can't move, are on the target, or the target is
             adjacent and directly reachable.
          2. If the target changed, reset; otherwise, restore the simulated
             position from the trail.
          3. Run up to SIM_STEPS iterations of greedy/bug simulation.
             Simulation terminates when the simulated position is adjacent
             to the target.
          4. BFS flood from the simulated position over the vision grid to get
             distances to each of the 8 neighbors.
          5. Pick the best direction by (penalty, bfs_dist, bug_dist) and move.
          6. If no direction improves, use a backup direction.

        Before each actual move, we attempt to build a road on the destination
        tile if it is empty ground and we have action cooldown available.
        """
        dirs = CARDINAL if cardinal else DIRECTIONS

        # Can't move — bail
        if ct.get_move_cooldown() > 0:
            return

        # Already at target
        if my_pos == target:
            return

        # Adjacent
        if _adjacent(my_pos, target):
            d = my_pos.direction_to(target)
            move_function(ct, d)
            return

        # Target changed — reset
        if self.current_target is None or target != self.current_target:
            self.reset(ct, my_pos, target)
        else:
            self._set_current_position(ct, my_pos)

        # Change cardinality
        if self.prev_cardinality != cardinal:
            self.reset(ct, my_pos, target)

        # Full bug path
        if len(self.bug_path) >= _MAX_PATH_BACKUP:
            self.reset(ct, my_pos, target)

        # ── Simulation loop ──────────────────────────────────────────────
        # Terminate when the simulated position is adjacent to the target.
        self.done_simulating = _adjacent(self.current_bug_position, target)
        for _ in range(_SIM_STEPS):
            if self.done_simulating or _adjacent(self.current_bug_position, target):
                break
            if self.should_bug:
                self._bug(ct, map_manager, my_pos, passability_function, cardinal)
            else:
                self._greedy(ct, map_manager, my_pos, passability_function, cardinal)
            self._append_position()

        for i in range(len(self.bug_path) - 2, -1, -1):
            draw_move_direction(ct, self.bug_path[i], self.bug_path[i + 1], 200, 200, 200)

        # ── BFS flood from simulated bug position ────────────────────────
        vision_r_sq = ct.get_vision_radius_sq()
        bfs_dists = validator_on_direction(
            ct,
            map_manager,
            my_pos, 
            self.current_bug_position,
            passability_function,
            cardinal
        )

        # ── Pick the best movement direction ─────────────────────────────
        center_bfs = bfs_dists.get(CENTRE, 100000)
        center_bug_dist = my_pos.distance_squared(self.current_bug_position)

        best_dir: Direction | None = None
        backup_dir: Direction | None = None
        best_penalty = 100_000_000
        best_dist = 100_000_000
        best_bug_d = 100_000_000

        for d in dirs:
            n_pos = my_pos.add(d)
            if not passability_function(ct, n_pos, map_manager):
                continue

            backup_dir = d  # any movable direction works as fallback

            dist_val = bfs_dists.get(d, 100000)
            penalty = score_tile(ct, n_pos)
            bug_d = n_pos.distance_squared(self.current_bug_position)

            # Only consider directions that don't worsen BFS distance vs centre
            if dist_val >= center_bfs:
                continue
            if dist_val == center_bfs and bug_d >= center_bug_dist:
                continue

            # Tie-break: penalty → bfs distance → bug distance
            should_update = False
            if penalty != best_penalty:
                should_update = penalty < best_penalty
            elif dist_val != best_dist:
                should_update = dist_val < best_dist
            elif bug_d != best_bug_d:
                should_update = bug_d < best_bug_d

            if should_update:
                best_dir = d
                best_dist = dist_val
                best_bug_d = bug_d
                best_penalty = penalty

        chosen_dir = best_dir

        if chosen_dir is None:
            bug_path_backup_dir: Direction | None = None
            for i in range(len(self.bug_path) - 2, -1, -1):
                if self.bug_path[i] != my_pos:
                    continue
                next_pos = self.bug_path[i + 1]
                candidate = my_pos.direction_to(next_pos)
                if candidate == CENTRE:
                    continue
                if cardinal and candidate not in CARDINAL:
                    continue
                if my_pos.add(candidate) != next_pos:
                    continue
                if not passability_function(ct, next_pos, map_manager):
                    continue
                bug_path_backup_dir = candidate
                draw_move_direction(ct, my_pos, my_pos.add(bug_path_backup_dir), 200, 0, 200)
                break
            chosen_dir = bug_path_backup_dir

        if best_dir is not None:
            draw_move_direction(ct, my_pos, my_pos.add(best_dir), 0, 200, 0)

        if chosen_dir is None:
            buggy_dir = my_pos.direction_to(average_locations(self.bug_path[(len(self.bug_path)//2):]))
            buggy_loc = my_pos.add(buggy_dir)
            if passability_function(ct, buggy_loc, map_manager):
                chosen_dir = buggy_dir
            self.reset(ct, my_pos, self.current_target)

        if chosen_dir is None:
            chosen_dir = backup_dir

        if chosen_dir is not None:
            move_function(ct, chosen_dir)
            # After moving, check if the simulated position is still visible
            new_pos = ct.get_position()
            if new_pos.distance_squared(self.current_bug_position) > vision_r_sq:
                self._set_current_position(ct, my_pos)

        self.prev_cardinality = cardinal
        return chosen_dir
