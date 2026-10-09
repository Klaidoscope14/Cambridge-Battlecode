from cambc import GameConstants, Position, Controller
from states.builder_state import BuilderState
from debug.profiling import cputimer
from map.map_manager import MapManager
from nav.common import common_path

import random

NEAR_DISTANCE_SQUARED = 10

class GuardState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self._target_harvester_pos: Position | None = None
        self._visited: set[Position] = set()

    @cputimer
    def determine(self, ct, state_manager) -> bool:
        if ct.get_global_resources()[0] < ct.get_harvester_cost()[0] * 3:
            if not self.brain.map_manager._ally_harvesters:
                return False
            if len(self.brain.map_manager.nearby_ally_bot_ids) > 2:
                return False
            state_manager.current_state = BuilderState.GUARD
            return True

    def execute(self, ct):
        my_pos = ct.get_position()
        map_manager = self.brain.map_manager

        if self._target_harvester_pos is None:
            self._target_harvester_pos = self._pick_harvester(map_manager)

        if self._target_harvester_pos is None:
            return

        if my_pos.distance_squared(self._target_harvester_pos) <= NEAR_DISTANCE_SQUARED:
            self._visited.add(self._target_harvester_pos)
            self._target_harvester_pos = self._pick_harvester(map_manager)
            if self._target_harvester_pos is None:
                return

        common_path(ct, map_manager, self.brain.pathing, self._target_harvester_pos)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pick_harvester(self, map_manager: MapManager) -> Position | None:
        """Choose a random waypoint (ally harvester or ally core) this guard
        has not yet visited.

        Resets the visited set once every known waypoint has been seen so
        the guard keeps cycling instead of stalling."""
        waypoints = list(map_manager._ally_harvesters)
        if map_manager.ally_core_pos is not None:
            waypoints.append(map_manager.ally_core_pos)
        if not waypoints:
            return None
        candidates = tuple(w for w in waypoints if w not in self._visited)
        if not candidates:
            self._visited.clear()
            candidates = tuple(waypoints)
        return random.choice(candidates)
