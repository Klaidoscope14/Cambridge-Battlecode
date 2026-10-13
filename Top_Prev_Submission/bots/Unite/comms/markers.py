"""Marker API for inter-bot coordination.

All marker values carry a 2-bit type tag in the lowest bits:
  Type 0 (REPAIR)          : [round 30b][type 2b]
  Type 1 (HARVESTER_CLAIM) : [y 9b][x 9b][round 12b][type 2b]
  Type 2 (BRIDGE_WORK)     : [y 9b][x 9b][round 12b][type 2b]
"""

from cambc import Controller, EntityType, Position

from helpers.constants import (
    REPAIR_MARKER_COOLDOWN,
    HARVESTER_CLAIM_STALENESS,
    BRIDGE_WORK_STALENESS,
)
from helpers.geometry import on_map
from helpers.directions import DIRECTIONS
from map.map_manager import MapManager

# ---------------------------------------------------------------------------
# Marker type tags (2 bits)
# ---------------------------------------------------------------------------
MARKER_TYPE_HARVESTER_CLAIM = 1
MARKER_TYPE_BRIDGE_WORK = 2

_TYPE_MASK = 0x3


def get_marker_type(value: int) -> int:
    return value & _TYPE_MASK


# ---------------------------------------------------------------------------
# Harvester-claim marker encoding
# ---------------------------------------------------------------------------

def encode_harvester_claim(round_num: int, pos: Position) -> int:
    return (
        MARKER_TYPE_HARVESTER_CLAIM
        | ((round_num & 0xFFF) << 2)
        | ((pos.x & 0x1FF) << 14)
        | ((pos.y & 0x1FF) << 23)
    )


def decode_harvester_claim(value: int) -> tuple[int, int, int]:
    """Returns (round, x, y)."""
    round_num = (value >> 2) & 0xFFF
    x = (value >> 14) & 0x1FF
    y = (value >> 23) & 0x1FF
    return round_num, x, y


# ---------------------------------------------------------------------------
# Bridge-work marker encoding
# ---------------------------------------------------------------------------

def encode_bridge_work(round_num: int, pos: Position) -> int:
    """Encode a bridge-work claim for the break at *pos*.

    Layout matches harvester-claim: [y 9b][x 9b][round 12b][type 2b]
    """
    return (
        MARKER_TYPE_BRIDGE_WORK
        | ((round_num & 0xFFF) << 2)
        | ((pos.x & 0x1FF) << 14)
        | ((pos.y & 0x1FF) << 23)
    )


def decode_bridge_work(value: int) -> tuple[int, int, int]:
    """Returns (round, x, y)."""
    round_num = (value >> 2) & 0xFFF
    x = (value >> 14) & 0x1FF
    y = (value >> 23) & 0x1FF
    return round_num, x, y


# ---------------------------------------------------------------------------
# Placement primitive
# ---------------------------------------------------------------------------

def _try_place_marker_at(ct: Controller, pos: Position, value: int) -> bool:
    """Place a marker at *pos*, destroying a road there if necessary.

    Returns True when the marker is successfully placed.
    Only roads are destroyed — any other occupant blocks placement.
    """
    if ct.can_place_marker(pos):
        ct.place_marker(pos, value)
        return True
    if not ct.can_destroy(pos):
        return False
    bid = ct.get_tile_building_id(pos)
    if bid is not None and ct.get_entity_type(bid) == EntityType.ROAD:
        ct.destroy(pos)
        if ct.can_place_marker(pos):
            ct.place_marker(pos, value)
            return True
    return False


def _place_marker_nearby(
    ct: Controller,
    center: Position,
    value: int,
    exclude: Position | None = None,
) -> Position | None:
    """Try each in-bounds direction around *center*, returning the first position
    where the marker was successfully placed, or None.

    Pass *exclude* to skip one specific neighbour (e.g. the bridge tile in repair markers).
    """
    w, h = ct.get_map_width(), ct.get_map_height()
    for d in DIRECTIONS:
        pos = center.add(d)
        if not on_map(pos, w, h):
            continue
        if exclude is not None and pos.x == exclude.x and pos.y == exclude.y:
            continue
        if _try_place_marker_at(ct, pos, value):
            return pos
    return None


def _ally_markers_of_type(vision_manager, current_round: int, marker_type: int):
    """Yield ``(pos, MarkerRecord)`` for every ally marker of *marker_type* visible this round."""
    for pos, record in vision_manager.get_ally_markers(current_round):
        if get_marker_type(record.marker_value) == marker_type:
            yield pos, record


# ---------------------------------------------------------------------------
# High-level harvester-claim helpers
# ---------------------------------------------------------------------------

def place_harvester_claim(ct: Controller, harvester_pos: Position) -> Position | None:
    """Place a claim marker on a free tile around us.

    Returns the position where the marker was placed, or None if no
    adjacent tile was available.
    """
    value = encode_harvester_claim(ct.get_current_round(), harvester_pos)
    return _place_marker_nearby(ct, ct.get_position(), value)


def is_harvester_claimed_vm(
    vision_manager,
    harvester_pos: Position,
    current_round: int,
    staleness: int = 1,
) -> bool:
    """True when an active claim marker for *harvester_pos* exists nearby.

    Uses the VisionManager's cached ally markers instead of scanning map_manager.
    """
    for _, record in _ally_markers_of_type(vision_manager, current_round, MARKER_TYPE_HARVESTER_CLAIM):
        claim_round, cx, cy = decode_harvester_claim(record.marker_value)
        if cx == harvester_pos.x and cy == harvester_pos.y:
            if current_round - claim_round <= staleness:
                return True
    return False


# ---------------------------------------------------------------------------
# High-level bridge-work helpers
# ---------------------------------------------------------------------------

def place_bridge_work_marker(ct: Controller, break_pos: Position) -> Position | None:
    """Place a bridge-work claim marker on a free tile around us.

    Returns the position where the marker was placed, or None if no
    adjacent tile was available.
    """
    value = encode_bridge_work(ct.get_current_round(), break_pos)
    return _place_marker_nearby(ct, ct.get_position(), value)


def is_bridge_work_claimed_vm(
    vision_manager,
    break_pos: Position,
    current_round: int,
    staleness: int = BRIDGE_WORK_STALENESS,
) -> bool:
    """True when an active bridge-work marker for *break_pos* exists.

    Uses the VisionManager's cached ally markers instead of scanning map_manager.
    """
    for _, record in _ally_markers_of_type(vision_manager, current_round, MARKER_TYPE_BRIDGE_WORK):
        claim_round, cx, cy = decode_bridge_work(record.marker_value)
        if cx == break_pos.x and cy == break_pos.y:
            if current_round - claim_round <= staleness:
                return True
    return False


# ---------------------------------------------------------------------------
# Marker expiry — all expiry defaults and helpers in one place
# ---------------------------------------------------------------------------

MARKER_EXPIRY: dict[int, int] = {
    MARKER_TYPE_HARVESTER_CLAIM: HARVESTER_CLAIM_STALENESS,
    MARKER_TYPE_BRIDGE_WORK: BRIDGE_WORK_STALENESS,
}
"""Map each marker type tag to its default expiry duration (rounds)."""


def get_marker_round(value: int) -> int:
    """Extract the round number from any encoded marker value."""
    marker_type = get_marker_type(value)
    if marker_type == MARKER_TYPE_HARVESTER_CLAIM:
        return decode_harvester_claim(value)[0]
    if marker_type == MARKER_TYPE_BRIDGE_WORK:
        return decode_bridge_work(value)[0]
    return 0


def is_marker_expired(value: int, current_round: int) -> bool:
    """True when the marker encoded in *value* has exceeded its type's expiry."""
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