"""Expiry checks for ally markers placed adjacent to the builder."""

from cambc import Controller, EntityType

from helpers.constants import (
    HARVESTER_CLAIM_STALENESS,
    BRIDGE_WORK_STALENESS,
)
from helpers.directions import DIRECTIONS
from helpers.geometry import on_map

MARKER_TYPE_HARVESTER_CLAIM = 1
MARKER_TYPE_BRIDGE_WORK = 2
MARKER_TYPE_CORE_POSITION = 3

_TYPE_MASK = 0x3

CORE_POSITION_STALENESS = 2000

MARKER_EXPIRY: dict[int, int] = {
    MARKER_TYPE_HARVESTER_CLAIM: HARVESTER_CLAIM_STALENESS,
    MARKER_TYPE_BRIDGE_WORK: BRIDGE_WORK_STALENESS,
    MARKER_TYPE_CORE_POSITION: CORE_POSITION_STALENESS,
}


def get_marker_type(value: int) -> int:
    return value & _TYPE_MASK


def _decode_round_xy(value: int) -> tuple[int, int, int]:
    round_num = (value >> 2) & 0xFFF
    x = (value >> 14) & 0x1FF
    y = (value >> 23) & 0x1FF
    return round_num, x, y


def get_marker_round(value: int) -> int:
    marker_type = get_marker_type(value)
    if marker_type in (
        MARKER_TYPE_HARVESTER_CLAIM,
        MARKER_TYPE_BRIDGE_WORK,
        MARKER_TYPE_CORE_POSITION,
    ):
        return _decode_round_xy(value)[0]
    return 0


def is_marker_expired(value: int, current_round: int) -> bool:
    marker_round = get_marker_round(value)
    expiry = MARKER_EXPIRY.get(get_marker_type(value), 0)
    return current_round - marker_round > expiry


def remove_expired_markers(ct: Controller) -> int:
    """Destroy every adjacent marker that has exceeded its type's expiry.

    Returns the number of markers removed.
    """
    current_round = ct.get_current_round()
    bot_pos = ct.get_position()
    w, h = ct.get_map_width(), ct.get_map_height()
    removed = 0
    for d in DIRECTIONS:
        pos = bot_pos.add(d)
        if not on_map(pos, w, h):
            continue
        bid = ct.get_tile_building_id(pos)
        if bid is None or ct.get_entity_type(bid) != EntityType.MARKER:
            continue
        if ct.get_team(bid) != ct.get_team():
            continue
        mv = ct.get_marker_value(bid)
        if is_marker_expired(mv, current_round) and ct.can_destroy(pos):
            ct.destroy(pos)
            removed += 1
    return removed
