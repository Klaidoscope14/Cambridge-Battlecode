from cambc import EntityType, Environment, GameConstants, Position

from helpers.geometry import on_map
from states.builder_state import BuilderState
from helpers.directions import CARDINAL
from map.map_manager import MapManager
from sabotage.base_state import (
    BaseSabotageState,
    can_destroy_building,
    can_sabotage_given_nearby_enemies,
    is_enemy_sabotage_target,
    is_safe_to_sabotage,
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

        if not is_safe_to_sabotage(self.brain, pos):
            return False
        
        if ct.get_global_resources()[0] < GameConstants.HARVESTER_BASE_COST[0]:
            return False

        bot = mm.get_bot(pos)
        if bot is not None and bot.id != ct.get_id():
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
        """Find the closest valid sabotage target adjacent to any harvester on titanium.

        Iterates all nearby harvesters (ally and enemy), checks cardinal
        neighbors as candidates.
        Among all valid targets at the same best-priority level, pick the
        closest one.  A higher-priority type always wins regardless of distance.
        """
        best_pos: Position | None = None
        best_priority = len(self.TARGETS)
        best_dist = float("inf")

        all_harvester_ids = mm.nearby_ally_harvester_ids + mm.nearby_enemy_harvester_ids
        for eid in all_harvester_ids:
            harvester_pos = ct.get_position(eid)
            if mm.get_tile(harvester_pos) != Environment.ORE_TITANIUM:
                continue

            for d in CARDINAL:
                pos = harvester_pos.add(d)
                if not on_map(pos, mm.width, mm.height):
                    continue
                if not is_safe_to_sabotage(self.brain, pos):
                    continue
                if not self._is_valid_target(ct, mm, pos, current_round):
                    continue

                building = mm.get_building(pos)
                pri = target_priority(building.entity_type, self.TARGETS)
                dist = my_pos.distance_squared(pos)

                if pri < best_priority or (pri == best_priority and dist < best_dist):
                    best_priority = pri
                    best_dist = dist
                    best_pos = pos

        return best_pos

    def determine(self, ct, state_manager):
        print(f"Sabotage cooldowns: {self.cooldowns}")

        mm = self.brain.map_manager
        current_round = ct.get_current_round()

        # if not can_sabotage_given_nearby_enemies(ct, mm):
        #     return False

        if (
            state_manager.previous_state == BuilderState.SABOTAGE_SOURCE
            and self.target is not None
            and self._is_valid_target(ct, mm, self.target, current_round)
        ):
            state_manager.current_state = BuilderState.SABOTAGE_SOURCE
            return True

        my_pos = ct.get_position()
        if self._find_best_target(ct, mm, my_pos, current_round) is not None:
            state_manager.current_state = BuilderState.SABOTAGE_SOURCE
            return True

        return False