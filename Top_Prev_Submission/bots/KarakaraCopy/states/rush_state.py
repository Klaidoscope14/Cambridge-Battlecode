"""Rush state: guess enemy core via symmetry, path to it, then orbit."""

from cambc import Position, Controller, Environment
from debug.profiling import cputimer
from map.map_manager import MapManager
from nav.common import save_path, no_build_path

import math

# Orbit radius (tiles away from core center)
ORBIT_RADIUS = 6
# How close to an orbit waypoint before advancing to the next one
WAYPOINT_THRESHOLD_SQ = 4
# Number of candidate angles to sample around the circle
NUM_WAYPOINTS = 8
# Max turns spent in rush state trying to reach a single orbit waypoint
# before giving up and advancing to the next one
MAX_WAYPOINT_ATTEMPTS = 20

class RushState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self.orbiting: bool = False
        self.orbit_waypoints: list[Position] = []
        self.orbit_index: int = 0
        self._waypoint_attempts: int = 0
        self.enemy_core_center: Position | None = None
        self._last_symmetry_guess: str | None = None
        self._path_fn = self._select_path_fn()

    def _select_path_fn(self):
        # """Rushers spawned N/S of the core walk only existing roads
        # (no_build_path); E/W rushers can build roads as they go (save_path)."""
        # spawn = self.brain.spawn_location
        # core = self.brain.ally_core_pos
        # if spawn is not None and core is not None and spawn.x == core.x:
        #     return no_build_path
        return save_path

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        return False

    def execute(self, ct: Controller) -> None:
        sm = self.brain.symmetry_manager

        # Re-evaluate enemy core center whenever the symmetry guess changes
        guess = sm.guess_symmetry()
        if guess != self._last_symmetry_guess or self.enemy_core_center is None:
            new_center = self._find_enemy_core_center(guess)
            if new_center is not None:
                self.enemy_core_center = new_center
                self._last_symmetry_guess = guess
                # Target moved — regenerate orbit
                if self.orbiting:
                    self.orbiting = False

        # Start / restart orbiting once we have a center
        if self.enemy_core_center is not None and not self.orbiting:
            self._start_orbit(ct, self.enemy_core_center)

        if self.orbiting:
            self._do_orbit(ct)
        else:
            # Symmetry not resolved yet — rush toward best guess
            self.target = self._pick_rush_target(guess)
            if self.target is not None:
                self._path_fn(ct, self.brain.map_manager, self.brain.pathing, self.target)

    # ------------------------------------------------------------------
    # Enemy core center — reflect our ally core through current guess
    # ------------------------------------------------------------------

    def _find_enemy_core_center(self, guess: str | None) -> Position | None:
        if guess is None:
            return None

        sm = self.brain.symmetry_manager
        ally_core = self.brain.ally_core_pos
        if ally_core is None:
            ally_core = self.brain.map_manager.ally_core_pos
        if ally_core is None:
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
        self._waypoint_attempts = 0

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

        # End the orbit loop with the map center if it's reachable
        waypoints.append(self.brain.ally_core_pos)

        return waypoints

    def _do_orbit(self, ct: Controller) -> None:
        """Path toward the current orbit waypoint; advance when close enough."""
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

        self._path_fn(ct, self.brain.map_manager, self.brain.pathing, wp)

    # ------------------------------------------------------------------
    # Rush target selection (before orbiting begins)
    # ------------------------------------------------------------------

    def _pick_rush_target(self, guess: str | None) -> Position:
        mm = self.brain.map_manager
        sm = self.brain.symmetry_manager

        ally_core = self.brain.ally_core_pos
        if ally_core is None:
            ally_core = mm.ally_core_pos
        if ally_core is None:
            return Position(mm.width // 2, mm.height // 2)

        if guess is not None:
            reflected = sm.reflect(ally_core, guess)
            if reflected is not None:
                return reflected

        return Position(mm.width // 2, mm.height // 2)