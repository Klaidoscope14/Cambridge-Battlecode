from cambc import EntityType, Environment, Position

from helpers.geometry import on_map
from helpers.directions import CARDINAL
from map.map_manager import MapManager
from sabotage.base_state import (
    BaseSabotageState,
    can_destroy_building,
    is_enemy_sabotage_target,
    target_priority,
)

ACTION_RADIUS_SQ = 2


# ── Module-level helpers ────────────────────────────────────────────


def _has_adjacent_titanium_harvester(mm: MapManager, pos: Position) -> bool:
    """Return True if *pos* is cardinally adjacent to an harvester."""
    for d in CARDINAL:
        neighbour = pos.add(d)
        if not on_map(neighbour, mm.width, mm.height):
            continue
        building = mm.get_building(neighbour)
        if (
            building is not None
            and mm.get_tile(neighbour) == Environment.ORE_TITANIUM
            and building.entity_type == EntityType.HARVESTER
        ):
            return True
    return False


# ── State class ─────────────────────────────────────────────────────


class SabotageSourceState(BaseSabotageState):
    """Sabotage enemy conveyor-chain buildings that are adjacent to an enemy harvester."""

    def _is_valid_target(self, ct, mm: MapManager, pos: Position, current_round: int) -> bool:
        key = (pos.x, pos.y)
        if key in self.cooldowns:
            return False

        team = ct.get_team()
        building = mm.get_building(pos)
        if not is_enemy_sabotage_target(building, team, self.TARGETS):
            return False

        if not can_destroy_building(building.hp):
            return False

        # Only sabotage enemy tiles that are adjacent to an harvester
        if not _has_adjacent_titanium_harvester(mm, pos):
            return False

        return True

    def _find_best_target(
        self, ct, mm: MapManager, my_pos: Position, current_round: int
    ) -> Position | None:
        """Find the closest valid sabotage target, respecting priority ordering.

        Among all valid targets at the same best-priority level, pick the
        closest one.  A higher-priority type always wins regardless of distance.
        """
        best_pos: Position | None = None
        best_priority = len(self.TARGETS)
        best_dist = float("inf")

        for pos in mm.nearby_positions:
            if not self._is_valid_target(ct, mm, pos, current_round):
                continue

            building = mm.get_building(pos)
            pri = target_priority(building.entity_type, self.TARGETS)
            d = my_pos.distance_squared(pos)

            if pri < best_priority or (pri == best_priority and d < best_dist):
                best_priority = pri
                best_dist = d
                best_pos = pos

        return best_pos