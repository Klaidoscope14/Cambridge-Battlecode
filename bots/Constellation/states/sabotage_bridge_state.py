from cambc import EntityType, Position

from map.map_manager import MapManager
from states.builder_state import BuilderState
from sabotage.base_state import (
    BaseSabotageState,
    can_destroy_building,
)


# ── State class ─────────────────────────────────────────────────────


class SabotageBridgeState(BaseSabotageState):
    """Sabotage any visible enemy bridge."""

    TARGETS = [EntityType.BRIDGE]

    def _is_valid_target(self, ct, mm: MapManager, pos: Position, current_round: int) -> bool:
        key = (pos.x, pos.y)
        if key in self.cooldowns:
            return False

        team = ct.get_team()
        building = mm.get_building(pos)
        if building is None:
            return False
        if building.team == team:
            return False
        if building.entity_type != EntityType.BRIDGE:
            return False
        if not can_destroy_building(building.hp):
            return False
        
        bot = mm.get_bot(pos)
        if bot is not None and bot.id != ct.get_id():
            return False

        return True

    def _find_best_target(
        self, ct, mm: MapManager, my_pos: Position, current_round: int
    ) -> Position | None:
        """Find the closest visible enemy bridge."""
        best_pos: Position | None = None
        best_dist = float("inf")

        for pos in mm.nearby_positions:
            if not self._is_valid_target(ct, mm, pos, current_round):
                continue

            d = my_pos.distance_squared(pos)
            if d < best_dist:
                best_dist = d
                best_pos = pos

        return best_pos

    def determine_sabotage_bridge_state(self, ct, state_manager):
        mm = self.brain.map_manager
        current_round = ct.get_current_round()

        if (
            state_manager.previous_state == BuilderState.SABOTAGE_BRIDGE
            and self.target is not None
            and self._is_valid_target(ct, mm, self.target, current_round)
        ):
            state_manager.current_state = BuilderState.SABOTAGE_BRIDGE
            return True

        my_pos = ct.get_position()
        if self._find_best_target(ct, mm, my_pos, current_round) is not None:
            state_manager.current_state = BuilderState.SABOTAGE_BRIDGE
            return True

        return False