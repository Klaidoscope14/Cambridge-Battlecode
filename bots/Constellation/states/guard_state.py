from cambc import GameConstants, Position, Controller
from map.map_manager import MapManager
from nav.common import save_path

import random


class GuardState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.vision_radius_sq = GameConstants.BUILDER_BOT_VISION_RADIUS_SQ

        # True  → heading toward a harvester
        # False → heading back to core
        self._outbound = True
        self._target_harvester_pos: Position | None = None

    def execute(self, ct):
        my_pos = ct.get_position()
        map_manager = self.brain.map_manager
        vision_manager = self.brain.vision_manager

        if self._outbound:
            # Pick a harvester target if we don't have one yet
            if self._target_harvester_pos is None:
                self._target_harvester_pos = self._pick_harvester(vision_manager)

            # If there are no known harvesters at all, fall back to core
            if self._target_harvester_pos is None:
                save_path(ct, map_manager, self.brain.pathing, map_manager.ally_core_pos)
                return

            # Check if the harvester is already within vision range
            if my_pos.distance_squared(self._target_harvester_pos) <= self.vision_radius_sq:
                # Arrived — switch to inbound leg
                self._outbound = False
                self._target_harvester_pos = None
            else:
                save_path(ct, map_manager, self.brain.pathing, self._target_harvester_pos)
                return

        # Inbound: head back to core
        if not self._outbound:
            core_pos = map_manager.ally_core_pos
            if my_pos.distance_squared(core_pos) <= self.vision_radius_sq:
                # Back at core — pick a new harvester and go outbound
                self._outbound = True
                self._target_harvester_pos = self._pick_harvester(vision_manager)
            save_path(ct, map_manager, self.brain.pathing,
                      self._target_harvester_pos if self._outbound and self._target_harvester_pos is not None
                      else core_pos)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_harvester(vision_manager) -> Position | None:
        """Choose a random harvester from the vision manager's cache."""
        harvesters = vision_manager._harvesters
        if not harvesters:
            return None
        return random.choice(harvesters)