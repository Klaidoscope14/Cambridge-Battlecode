"""Vision-safe entity reads for tiles.

Map grids store entity ids that can go stale when tiles leave vision. The engine
raises GameError when querying an id that is not currently sensible.

Always prefer **position** + `is_in_vision` + `get_tile_building_id` / `get_tile_builder_bot_id`
when you need what is on a tile now. Only query by id after resolving from the tile.
"""
from __future__ import annotations

from typing import Any

from cambc import Controller, EntityType, GameError, Position, Team

from helpers.directions import CARDINAL
from helpers.geometry import on_map


def _tile_visible(ct: Controller, mm: Any, pos: Position) -> bool:
    return mm.has_seen(pos) and ct.is_in_vision(pos)


def entity_type_at_tile(ct: Controller, mm: Any, pos: Position) -> EntityType | None:
    """Building entity type at *pos*, or None if empty / not visible / unknown."""
    if not _tile_visible(ct, mm, pos):
        return None
    bid = ct.get_tile_building_id(pos)
    if bid is None:
        return None
    try:
        return ct.get_entity_type(bid)
    except GameError:
        return None


def team_at_tile(ct: Controller, mm: Any, pos: Position) -> Team | None:
    """Team of building at *pos*, or None if empty / not visible / unknown."""
    if not _tile_visible(ct, mm, pos):
        return None
    bid = ct.get_tile_building_id(pos)
    if bid is None:
        return None
    try:
        return ct.get_team(bid)
    except GameError:
        return None


def hp_at_tile(ct: Controller, mm: Any, pos: Position) -> int | None:
    """HP of building at *pos*, or None if empty / not visible / unknown."""
    if not _tile_visible(ct, mm, pos):
        return None
    bid = ct.get_tile_building_id(pos)
    if bid is None:
        return None
    try:
        return ct.get_hp(bid)
    except GameError:
        return None


def builder_bot_id_at_tile(ct: Controller, mm: Any, pos: Position) -> int | None:
    """Builder bot id on *pos*, or None if none / not visible / error."""
    if not _tile_visible(ct, mm, pos):
        return None
    try:
        return ct.get_tile_builder_bot_id(pos)
    except GameError:
        return None


def try_entity_type(ct: Controller, entity_id: int) -> EntityType | None:
    """Resolve entity type by id when the id is known to be sensible (e.g. nearby list)."""
    try:
        return ct.get_entity_type(entity_id)
    except GameError:
        return None


def try_team(ct: Controller, entity_id: int) -> Team | None:
    try:
        return ct.get_team(entity_id)
    except GameError:
        return None


def try_hp(ct: Controller, entity_id: int) -> int | None:
    try:
        return ct.get_hp(entity_id)
    except GameError:
        return None


def try_direction(ct: Controller, entity_id: int):
    try:
        return ct.get_direction(entity_id)
    except GameError:
        return None


def try_stored_resource(ct: Controller, entity_id: int):
    try:
        return ct.get_stored_resource(entity_id)
    except GameError:
        return None


_TURRET_TYPES = frozenset(
    {EntityType.SENTINEL, EntityType.GUNNER, EntityType.BREACH}
)


def _resolve_tile_building_et_team(
    ct: Controller, mm: Any, pos: Position
) -> tuple[EntityType | None, Team | None] | None:
    """Known (et, team) for a building on pos, or None if tile is empty or unknown (fog, no snapshot)."""
    if not mm.has_seen(pos):
        return None
    if ct.is_in_vision(pos):
        bid = ct.get_tile_building_id(pos)
        if bid is None:
            return None
        et = entity_type_at_tile(ct, mm, pos)
        team = team_at_tile(ct, mm, pos)
        if et is None:
            bid2 = mm.get_building_id(pos)
            if bid2 is not None:
                et = try_entity_type(ct, bid2)
                team = try_team(ct, bid2)
        return (et, team)
    detail = mm.get_cell_building_detail(pos)
    if detail is not None:
        return detail
    if mm.get_building_id(pos) is None:
        return None
    return None


def ore_center_building_valid(
    ct: Controller,
    mm: Any,
    pos: Position,
    my_team: Team,
    *,
    safe_replace_ally_turret: bool,
) -> bool:
    """Match Constellation building-on-ore checks; True if ore is not blocked by a building."""
    pair = _resolve_tile_building_et_team(ct, mm, pos)
    if pair is None:
        return True
    et, team = pair
    if et is None:
        return True
    if et == EntityType.HARVESTER:
        return False
    if team is not None and team != my_team and et != EntityType.MARKER:
        return False
    if team == my_team and et in _TURRET_TYPES and not safe_replace_ally_turret:
        return False
    return True


def ore_cardinal_turrets_ok(
    ct: Controller, mm: Any, pos: Position, my_team: Team, width: int, height: int
) -> bool:
    """False if a cardinal neighbour has a known enemy turret (Constellation cardinal check)."""
    for d in CARDINAL:
        adj = pos.add(d)
        if not on_map(adj, width, height):
            continue
        pair = _resolve_tile_building_et_team(ct, mm, adj)
        if pair is None:
            continue
        adj_et, adj_team = pair
        if adj_et is None:
            continue
        if (
            adj_team is not None
            and adj_team != my_team
            and adj_et in _TURRET_TYPES
        ):
            return False
    return True
