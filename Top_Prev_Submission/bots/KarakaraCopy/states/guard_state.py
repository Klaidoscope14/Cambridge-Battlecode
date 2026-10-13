from cambc import GameConstants, Position, Controller
from states.builder_state import BuilderState
from debug.profiling import cputimer
from map.map_manager import MapManager
from nav.common import save_path

import random


class GuardState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.vision_radius_sq = GameConstants.BUILDER_BOT_VISION_RADIUS_SQ

        self._target_harvester_pos: Position | None = None
        self._visited: set[Position] = set()

    @cputimer
    def determine(self, ct, state_manager) -> bool:
        if ct.get_global_resources()[0] < ct.get_harvester_cost()[0] * 2:
            if not self.brain.map_manager._ally_harvesters:
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

        if my_pos.distance_squared(self._target_harvester_pos) <= self.vision_radius_sq:
            self._visited.add(self._target_harvester_pos)
            self._target_harvester_pos = self._pick_harvester(map_manager)
            if self._target_harvester_pos is None:
                return

        save_path(ct, map_manager, self.brain.pathing, self._target_harvester_pos)

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
