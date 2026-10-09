"""Center state: orbit our own ally core forever at a fixed radius."""

from cambc import Position, Controller
from debug.profiling import cputimer
from nav.common import common_path

import math

# Orbit radius (tiles away from ally core center)
ORBIT_RADIUS = 5
# How close to an orbit waypoint before advancing to the next one
WAYPOINT_THRESHOLD_SQ = 4
# Number of candidate angles to sample around the circle
NUM_WAYPOINTS = 8
# Max turns spent trying to reach a single orbit waypoint before giving up
MAX_WAYPOINT_ATTEMPTS = 20


class CenterState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.orbit_waypoints: list[Position] = []
        self.orbit_index: int = 0
        self._waypoint_attempts: int = 0
        self._initialized: bool = False

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        return False

    def execute(self, ct: Controller) -> None:
        core = self.brain.ally_core_pos
        if core is None:
            core = self.brain.map_manager.ally_core_pos
        if core is None:
            return

        if not self._initialized:
            self._start_orbit(ct, core)
            self._initialized = True

        if not self.orbit_waypoints:
            return

        wp = self.orbit_waypoints[self.orbit_index]
        my_pos = ct.get_position()

        advanced = False
        if my_pos.distance_squared(wp) <= WAYPOINT_THRESHOLD_SQ:
            advanced = True
        elif self._waypoint_attempts >= MAX_WAYPOINT_ATTEMPTS:
            advanced = True

        if advanced:
            self.orbit_index = (self.orbit_index + 1) % len(self.orbit_waypoints)
            wp = self.orbit_waypoints[self.orbit_index]
            self._waypoint_attempts = 0
        else:
            self._waypoint_attempts += 1

        common_path(ct, self.brain.map_manager, self.brain.pathing, wp)

    def _start_orbit(self, ct: Controller, core_center: Position) -> None:
        self.orbit_waypoints = self._generate_orbit_waypoints(core_center)
        if not self.orbit_waypoints:
            return

        my_pos = ct.get_position()
        best_idx = 0
        best_dist = float("inf")
        for i, wp in enumerate(self.orbit_waypoints):
            d = my_pos.distance_squared(wp)
            if d < best_dist:
                best_dist = d
                best_idx = i
        self.orbit_index = best_idx
        self._waypoint_attempts = 0

    def _generate_orbit_waypoints(self, center: Position) -> list[Position]:
        mm = self.brain.map_manager
        waypoints: list[Position] = []
        seen: set[tuple[int, int]] = set()

        for i in range(NUM_WAYPOINTS):
            angle = 2 * math.pi * i / NUM_WAYPOINTS
            wx = center.x + round(ORBIT_RADIUS * math.cos(angle))
            wy = center.y + round(ORBIT_RADIUS * math.sin(angle))

            if not (0 <= wx < mm.width and 0 <= wy < mm.height):
                continue

            key = (wx, wy)
            if key in seen:
                continue
            seen.add(key)

            pos = Position(wx, wy)
            if mm.has_seen(pos) and mm.has_wall(pos):
                continue

            waypoints.append(pos)

        return waypoints
