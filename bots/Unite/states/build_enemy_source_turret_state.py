from cambc import EntityType, Environment, Position, Direction

from helpers.directions import CARDINAL
from helpers.geometry import on_map
from map.map_manager import MapManager
from build_turret.base_state import (
    BuildTurretBase,
    find_build_slot_cardinal,
)

# ── Tuning constants ────────────────────────────────────────────────

ENEMY_THRESHOLD = 1
MAX_TURRETS_PER_SOURCE = 2

SOURCE_TYPES = {EntityType.HARVESTER, EntityType.FOUNDRY}
OFFENSIVE_SOURCE_TYPES = {EntityType.SPLITTER}  # place near enemy splitters for now

ENEMY_CONVEYOR_TYPES = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
    EntityType.ARMOURED_CONVEYOR,
}

ENEMY_TURRET_TYPES = {
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
}


# ── Module-level helpers ────────────────────────────────────────────


def _is_turret_worthy_source(building, mm: MapManager, pos: Position) -> bool:
    if building is None:
        return False
    if building.entity_type in OFFENSIVE_SOURCE_TYPES:
        return True  # always worth targeting, skip axionite check
    if building.entity_type not in SOURCE_TYPES:
        return False
    if building.entity_type == EntityType.HARVESTER:
        tile = mm.get_tile(pos)
        if tile == Environment.ORE_AXIONITE:
            return False
    return True

def _count_nearby_enemies(mm: MapManager, source_pos: Position, team) -> int:
    count = 0
    for pos in mm.nearby_positions:
        if pos.distance_squared(source_pos) > 8:
            continue
        building = mm.get_building(pos)
        if building is not None and building.team != team and building.entity_type != EntityType.MARKER:
            count += 1
    return count


def _best_enemy_conveyor_facing(
    mm: MapManager, build_pos: Position, team
) -> Direction | None:
    """Count enemy conveyors by direction from build_pos.

    Returns the direction with the most enemy conveyors, or None if there are none.
    """
    counts: dict[Direction, int] = {}
    for pos in mm.nearby_positions:
        building = mm.get_building(pos)
        if building is None:
            continue
        if building.team == team:
            continue
        if building.entity_type not in ENEMY_CONVEYOR_TYPES:
            continue
        d = build_pos.direction_to(pos)
        counts[d] = counts.get(d, 0) + 1

    if not counts:
        return None
    return max(counts, key=counts.get)


def _best_enemy_turret_facing(
    mm: MapManager, build_pos: Position, team
) -> Direction | None:
    """Count enemy turrets (sentinel/gunner/breach) by direction from build_pos.

    Returns the direction with the most enemy turrets, or None if there are none.
    """
    counts: dict[Direction, int] = {}
    for pos in mm.nearby_positions:
        building = mm.get_building(pos)
        if building is None:
            continue
        if building.team == team:
            continue
        if building.entity_type not in ENEMY_TURRET_TYPES:
            continue
        d = build_pos.direction_to(pos)
        counts[d] = counts.get(d, 0) + 1

    if not counts:
        return None
    return max(counts, key=counts.get)


# ── Subclass ────────────────────────────────────────────────────────


class BuildEnemySourceTurretState(BuildTurretBase):
    """Build a sentinel adjacent to a source (allied or enemy).

    Allied sources: triggers when surrounded by many enemy buildings (defense).
    Enemy sources: always worth attacking; turret faces toward the source.
    Axionite harvesters are skipped.
    """

    def _find_best_source(
        self, ct, mm: MapManager, my_pos: Position, current_round: int
    ) -> Position | None:
        best_pos = None
        best_dist = float("inf")
        for pos in mm.nearby_positions:
            if not self._is_valid_source(ct, mm, pos, current_round):
                continue
            d = my_pos.distance_squared(pos)
            if d < best_dist:
                best_dist = d
                best_pos = pos
        return best_pos

    def _is_valid_source(
        self, ct, mm: MapManager, pos: Position, current_round: int
    ) -> bool:
        if self._is_source_on_cooldown(pos, current_round):
            return False
        team = ct.get_team()
        building = mm.get_building(pos)
        if not _is_turret_worthy_source(building, mm, pos):
            return False
        source_is_enemy = building.team != team
        offensive = building.entity_type in OFFENSIVE_SOURCE_TYPES

        # Skip splitters that haven't been receiving anything
        if offensive:
            tracker = self.brain.storage_tracker
            if not tracker.has_data(building.id):
                return False  # no data yet, don't place
            if tracker.is_empty(building.id):
                return False  # observed empty, don't place
        if not source_is_enemy and not offensive:
            if _count_nearby_enemies(mm, pos, team) < ENEMY_THRESHOLD:
                return False

        adjacent_sentinels = 0
        for d in CARDINAL:
            adj = pos.add(d)
            if not on_map(adj, mm.width, mm.height):
                continue
            adj_building = mm.get_building(adj)
            if (
                adj_building is not None
                and adj_building.team == team
                and adj_building.entity_type == EntityType.SENTINEL
            ):
                adjacent_sentinels += 1

        if adjacent_sentinels >= MAX_TURRETS_PER_SOURCE:
            return False

        if not any(
            on_map(pos.add(d), mm.width, mm.height)
            and any(ct.can_build_sentinel(pos.add(d), face) for face in CARDINAL)
            for d in CARDINAL
        ):
            return False
        return True

    def _find_build_slot(self, ct, mm, source_pos):
        building = mm.get_building(source_pos)
        source_is_enemy = building is not None and building.team != ct.get_team()

        enemy_core_pos = (
            mm.spotted_enemy_core_pos
            or self.brain.symmetry_manager.reflect(mm.ally_core_pos)
        )

        # For splitters, skip the back (input) side
        blocked_dir = None
        if building is not None and building.entity_type in OFFENSIVE_SOURCE_TYPES:
            facing = ct.get_direction(building.id)
            blocked_dir = facing.opposite()

        best_pos = None
        best_dist = float("inf")

        for d in CARDINAL:
            if d == blocked_dir:
                continue
            adj = source_pos.add(d)
            if not on_map(adj, mm.width, mm.height):
                continue
            if not any(ct.can_build_sentinel(adj, face) for face in CARDINAL):
                continue
            dist = adj.distance_squared(enemy_core_pos) if enemy_core_pos else 0
            if dist < best_dist:
                best_dist = dist
                best_pos = adj

        if best_pos is None:
            return None

        toward_source = best_pos.direction_to(source_pos)
        return (best_pos, toward_source)

    def _choose_facing(self, ct, mm: MapManager) -> Direction:
        pos = self.build_pos
        direction = self.build_dir
        team = ct.get_team()
        toward_source = pos.direction_to(self.source_pos)

        # Resolve enemy core position (known or reflected)
        enemy_core_pos = mm.spotted_enemy_core_pos or self.brain.symmetry_manager.reflect(mm.ally_core_pos)
        near_enemy_core = enemy_core_pos is not None and pos.distance_squared(enemy_core_pos) <= 25

        # print("enemy core", enemy_core_pos, "direction", enemy_core_pos.direction_to(enemy_core_pos))
        # Priority 1: face the direction with the most enemy turrets
        turret_facing = _best_enemy_turret_facing(mm, pos, team)
        if turret_facing is not None:
            if turret_facing == toward_source:
                return turret_facing.rotate_left()
            else:
                return turret_facing

        # Priority 2: face the direction with the most enemy conveyors
        # (skip near enemy core — face the core instead to pressure the base)
        if not near_enemy_core:
            conveyor_facing = _best_enemy_conveyor_facing(mm, pos, team)
            if conveyor_facing is not None and conveyor_facing != toward_source:
                return conveyor_facing

        # Priority 3: face toward enemy core
        if enemy_core_pos is not None:
            to_enemy_core = pos.direction_to(enemy_core_pos)
            if to_enemy_core != toward_source:
                return to_enemy_core

        # Fallback: build_dir (outward from source)
        if direction != toward_source:
            return direction
        return direction.rotate_left() if direction.rotate_left() != toward_source else direction.rotate_right()
