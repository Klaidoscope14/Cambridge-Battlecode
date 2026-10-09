from cambc import EntityType, Position

from map.map_manager import MapManager
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