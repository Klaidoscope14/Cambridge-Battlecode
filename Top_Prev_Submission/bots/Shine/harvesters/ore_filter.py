"""Ore-tile validation: deciding whether a particular position is a legal target."""

from cambc import Controller, EntityType, Environment, Position

from helpers.directions import CARDINAL, CARDINAL_THEN_DIAGONAL
from helpers.geometry import on_map
from map.map_manager import MapManager

from harvesters.constants import (
    MIN_TURRET_AGE,
    SAFE_ROUNDS,
    TOO_MANY_ENEMY_TILES,
    TURRET_TYPES,
    UNREPLACEABLE_ALLY_TYPES,
)
from harvesters.helpers import is_on_position
from harvesters.resources import can_build_axionite


# ── Turret-on-ore safety ────────────────────────────────────────────


def is_safe(brain, current_round: int) -> bool:
    """No enemy builder seen recently — safe to dismantle ally turrets on ore."""
    last_seen = brain.map_manager.last_enemy_builder_seen_round
    return last_seen is None or current_round - last_seen > SAFE_ROUNDS


def turret_old_enough(
    turret_first_seen: dict[Position, int],
    pos: Position,
    current_round: int,
) -> bool:
    """Stamp first-seen round for a turret position; True once aged enough."""
    if pos not in turret_first_seen:
        turret_first_seen[pos] = current_round
    return current_round - turret_first_seen[pos] >= MIN_TURRET_AGE


def is_allowed_ore(env, allowed_ore: set) -> bool:
    return env in allowed_ore


def is_ore_type_buildable(env, allowed_ore: set, ct: Controller) -> bool:
    """Static `allowed_ore` set + dynamic axionite gate.

    Axionite is only buildable when ``can_build_axionite(ct)`` is True. Without
    this check, axionite ore is treated as a legal target and can be selected
    purely on distance — leading to expensive axionite harvesters going up
    before the economy supports them.
    """
    if env not in allowed_ore:
        return False
    if env == Environment.ORE_AXIONITE and not can_build_axionite(ct):
        return False
    return True


# ── Validation ──────────────────────────────────────────────────────


def is_valid_ore(
    state,
    ct: Controller,
    mm: MapManager,
    pos: Position,
    current_round: int,
    enemy_count: int = 0,
    my_pos: Position | None = None,
    _axionite_ok: bool | None = None,
) -> bool:
    """Full validation for ore tiles we can see.

    ``_axionite_ok`` is an optional pre-computed cache of ``can_build_axionite(ct)``
    so callers that invoke this function in a tight loop avoid re-querying the
    controller per ore tile. If omitted, computed lazily.
    """
    if pos in state.cooldowns:
        return False
    if enemy_count > TOO_MANY_ENEMY_TILES:
        return False

    px = pos.x
    py = pos.y
    tile = mm.tile_grid[px][py]
    if tile is None or tile not in state.allowed_ore:
        return False
    if tile == Environment.ORE_AXIONITE:
        if _axionite_ok is None:
            _axionite_ok = can_build_axionite(ct)
        if not _axionite_ok:
            return False

    team = ct.get_team()
    building = mm.building_grid[px][py]
    if building is not None:
        if building.entity_type == EntityType.HARVESTER:
            return False
        if building.team != team and building.entity_type != EntityType.MARKER:
            return False
        if building.team == team:
            if building.entity_type in UNREPLACEABLE_ALLY_TYPES:
                return False
            if building.entity_type in TURRET_TYPES:
                if not is_safe(state.brain, current_round):
                    return False
                if not turret_old_enough(state._turret_first_seen, pos, current_round):
                    return False

    # Never place an axionite harvester on a tile that already has a conveyor
    # on it — tearing up the belt just to drop a harvester costs more than any
    # intake we'd gain.
    if (
        tile == Environment.ORE_AXIONITE
        and building is not None
        and building.entity_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
    ):
        return False

    # Reject ore with enemy turrets on cardinal neighbours.
    # If a barrier sits on the ore, extend the check to all 8 directions.
    width = mm.width
    height = mm.height
    building_grid = mm.building_grid
    directions = (
        CARDINAL_THEN_DIAGONAL
        if building is not None and building.entity_type == EntityType.BARRIER
        else CARDINAL
    )
    for d in directions:
        adj = pos.add(d)
        ax = adj.x
        ay = adj.y
        if not (0 <= ax < width and 0 <= ay < height):
            continue
        adj_building = building_grid[ax][ay]
        if (
            adj_building is not None
            and adj_building.team != team
            and adj_building.entity_type in TURRET_TYPES
        ):
            return False

    # Another bot sitting on this ore means it is reserved.
    bot_on_ore = mm.bot_grid[px][py]
    if bot_on_ore is not None:
        if my_pos is None or not is_on_position(my_pos, pos):
            return False

    if not state.brain._is_closer_to_ally_core(pos):
        return False

    return True


def is_valid_ore_fast(
    state,
    ct: Controller,
    mm: MapManager,
    pos: Position,
    current_round: int,
    enemy_count: int = 0,
    my_pos: Position | None = None,
) -> bool:
    """Validation for positions already in ``mm.nearby_plausible_ore_positions``.

    Assumes the turn-static checks (tile is ore, axionite gate, no blocking
    building, no enemy turret cardinal-adjacent) have already been applied
    during ``MapManager.update()``. Runs only the per-call-variant checks:
    cooldowns, enemy-count threshold, ally-turret dismantling rules,
    bot-on-ore reservation, and closer-to-ally-core check.
    """
    if pos in state.cooldowns:
        return False
    if enemy_count > TOO_MANY_ENEMY_TILES:
        return False

    px = pos.x
    py = pos.y

    # Ally turret on the tile is conditionally valid (not pre-filtered in
    # MapManager because is_safe / turret_old_enough are state-dependent).
    building = mm.building_grid[px][py]
    if (
        building is not None
        and building.team == ct.get_team()
        and building.entity_type in TURRET_TYPES
    ):
        if not is_safe(state.brain, current_round):
            return False
        if not turret_old_enough(state._turret_first_seen, pos, current_round):
            return False

    # Barrier on the ore: MapManager's pre-filter only rejected cardinal-
    # adjacent enemy turrets. Extend the check to diagonals here.
    if building is not None and building.entity_type == EntityType.BARRIER:
        team = ct.get_team()
        width = mm.width
        height = mm.height
        building_grid = mm.building_grid
        for d in CARDINAL_THEN_DIAGONAL:
            adj = pos.add(d)
            ax = adj.x
            ay = adj.y
            if not (0 <= ax < width and 0 <= ay < height):
                continue
            adj_building = building_grid[ax][ay]
            if (
                adj_building is not None
                and adj_building.team != team
                and adj_building.entity_type in TURRET_TYPES
            ):
                return False

    # Never place an axionite harvester on a tile that already has a conveyor
    # on it (mirrors the same check in is_valid_ore).
    if (
        building is not None
        and building.entity_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
        and mm.tile_grid[px][py] == Environment.ORE_AXIONITE
    ):
        return False

    # Another bot sitting on this ore means it is reserved.
    bot_on_ore = mm.bot_grid[px][py]
    if bot_on_ore is not None:
        if my_pos is None or not is_on_position(my_pos, pos):
            return False

    if not state.brain._is_closer_to_ally_core(pos):
        return False

    return True


def is_valid_predicted_ore(
    state,
    ct: Controller,
    mm: MapManager,
    pos: Position,
    current_round: int,
    enemy_count: int = 0,
    my_pos: Position | None = None,
    _axionite_ok: bool | None = None,
) -> bool:
    """Lighter validation for symmetry-predicted ore we haven't seen yet.

    If the tile IS visible, falls back to full validation.
    """
    tile = mm.tile_grid[pos.x][pos.y]

    if tile is not None:
        return is_valid_ore(state, ct, mm, pos, current_round, enemy_count, my_pos, _axionite_ok)

    if pos in state.cooldowns:
        return False
    if enemy_count > TOO_MANY_ENEMY_TILES:
        return False
    if not state.brain._is_closer_to_ally_core(pos):
        return False

    return True
