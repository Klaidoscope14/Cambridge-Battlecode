"""Rush state: guess enemy core via symmetry, path to it, then orbit once spotted."""

from cambc import Position, Controller, Environment
from map.map_manager import MapManager
from nav.common import common_path, save_path

import math

# Orbit radius (tiles away from core center)
ORBIT_RADIUS = 4
# How close to an orbit waypoint before advancing to the next one
WAYPOINT_THRESHOLD_SQ = 4
# Number of candidate angles to sample around the circle
NUM_WAYPOINTS = 8

# This is AI generated I got lazy

class RushState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self.orbiting: bool = False
        self.orbit_waypoints: list[Position] = []
        self.orbit_index: int = 0
        self.enemy_core_center: Position | None = None

    def execute(self, ct: Controller) -> None:
        mm = self.brain.map_manager

        # Once we spot the enemy core, lock in its true center via symmetry
        if mm.spotted_enemy_core_pos is not None and self.enemy_core_center is None:
            self.enemy_core_center = self._find_enemy_core_center()

        if self.enemy_core_center is not None and not self.orbiting:
            self._start_orbit(ct, self.enemy_core_center)

        if self.orbiting:
            self._do_orbit(ct)
        else:
            self.target = self._pick_rush_target(ct)
            if self.target is not None:
                common_path(ct, self.brain.map_manager, self.brain.pathing, self.target)

    # ------------------------------------------------------------------
    # Enemy core center — reflect our ally core through known symmetry
    # ------------------------------------------------------------------

    def _find_enemy_core_center(self) -> Position | None:
        sm = self.brain.symmetry_manager
        ally_core = self.brain.ally_core_pos
        if ally_core is None:
            ally_core = self.brain.map_manager.ally_core_pos
        if ally_core is None:
            return None

        guess = sm.guess_symmetry()
        if guess is None:
            return None
        return sm.reflect(ally_core, guess)

    # ------------------------------------------------------------------
    # Orbit logic
    # ------------------------------------------------------------------

    def _start_orbit(self, ct: Controller, core_center: Position) -> None:
        """Generate circular waypoints around the enemy core and begin orbiting."""
        self.orbit_waypoints = self._generate_orbit_waypoints(core_center)
        if not self.orbit_waypoints:
            return

        self.orbiting = True

        # Start at the closest waypoint to our current position
        my_pos = ct.get_position()
        best_idx = 0
        best_dist = float("inf")
        for i, wp in enumerate(self.orbit_waypoints):
            d = my_pos.distance_squared(wp)
            if d < best_dist:
                best_dist = d
                best_idx = i
        self.orbit_index = best_idx

    def _generate_orbit_waypoints(self, center: Position) -> list[Position]:
        """Create waypoints in a circle around center, skipping any that are
        out of bounds or land on a wall."""
        mm = self.brain.map_manager
        waypoints: list[Position] = []
        seen: set[tuple[int, int]] = set()

        for i in range(NUM_WAYPOINTS):
            angle = 2 * math.pi * i / NUM_WAYPOINTS
            wx = center.x + round(ORBIT_RADIUS * math.cos(angle))
            wy = center.y + round(ORBIT_RADIUS * math.sin(angle))

            # Skip out-of-bounds
            if not (0 <= wx < mm.width and 0 <= wy < mm.height):
                continue

            # Skip duplicates (can happen near edges)
            key = (wx, wy)
            if key in seen:
                continue
            seen.add(key)

            # Skip walls if we've seen the tile
            pos = Position(wx, wy)
            if mm.has_seen(pos) and mm.has_wall(pos):
                continue

            waypoints.append(pos)

        return waypoints

    def _do_orbit(self, ct: Controller) -> None:
        """Path toward the current orbit waypoint; advance when close enough."""
        if not self.orbit_waypoints:
            return

        wp = self.orbit_waypoints[self.orbit_index]
        my_pos = ct.get_position()

        if my_pos.distance_squared(wp) <= WAYPOINT_THRESHOLD_SQ:
            self.orbit_index = (self.orbit_index + 1) % len(self.orbit_waypoints)
            wp = self.orbit_waypoints[self.orbit_index]

        save_path(ct, self.brain.map_manager, self.brain.pathing, wp)

    # ------------------------------------------------------------------
    # Rush target selection (before core is spotted)
    # ------------------------------------------------------------------

    def _pick_rush_target(self, ct: Controller) -> Position:
        mm = self.brain.map_manager
        sm = self.brain.symmetry_manager

        if mm.spotted_enemy_core_pos is not None:
            return mm.spotted_enemy_core_pos

        ally_core = self.brain.ally_core_pos
        if ally_core is None:
            ally_core = mm.ally_core_pos
        if ally_core is None:
            return Position(mm.width // 2, mm.height // 2)

        guess = sm.guess_symmetry()
        if guess is not None:
            reflected = sm.reflect(ally_core, guess)
            if reflected is not None:
                return reflected

        return Position(mm.width // 2, mm.height // 2)