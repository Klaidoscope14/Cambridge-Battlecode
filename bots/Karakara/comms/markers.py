from cambc import Controller, EntityType, Position

from helpers.directions import DIRECTIONS

# 6 bits per coordinate (0..63) — max map size is 50x50, so 6 bits covers
# it. Four coords pack into 24 bits, leaving the upper 8 bits free for a
# type tag if needed.
_COORD_BITS = 6
_COORD_MASK = (1 << _COORD_BITS) - 1


def encode_build_dest(build_x: int, build_y: int, dest_x: int, dest_y: int) -> int:
    """Pack a (build_pos, dest_pos) pair into a single int for marker
    placement. 9 bits per coord; supports map sizes up to 512.
    """
    return (
        (build_x & _COORD_MASK)
        | ((build_y & _COORD_MASK) << _COORD_BITS)
        | ((dest_x & _COORD_MASK) << (_COORD_BITS * 2))
        | ((dest_y & _COORD_MASK) << (_COORD_BITS * 3))
    )


def decode_build_dest(value: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """Unpack a value produced by encode_build_dest. Returns
    ((build_x, build_y), (dest_x, dest_y)).
    """
    return (
        (value & _COORD_MASK, (value >> _COORD_BITS) & _COORD_MASK),
        ((value >> (_COORD_BITS * 2)) & _COORD_MASK, (value >> (_COORD_BITS * 3)) & _COORD_MASK),
    )


def try_place_marker(ct: Controller, build_pos: Position, my_pos: Position, encoding: int) -> bool:
    """Place a marker encoding *encoding* at *build_pos*, falling back to
    tiles around *my_pos*. Ally markers blocking a candidate are destroyed
    inline. Returns True if placed.
    """
    my_team = ct.get_team()
    width, height = ct.get_map_width(), ct.get_map_height()
    adj = [my_pos.add(d) for d in DIRECTIONS]
    adj.sort(key=lambda p: p.distance_squared(build_pos))
    candidates = [build_pos] + adj

    for pos in candidates:
        if not (0 <= pos.x < width and 0 <= pos.y < height):
            continue
        if ct.can_place_marker(pos):
            ct.place_marker(pos, encoding)
            return True
        tile_id = ct.get_tile_building_id(pos)
        if tile_id is None or ct.get_team(tile_id) != my_team:
            continue
        if ct.get_entity_type(tile_id) == EntityType.MARKER and ct.can_destroy(pos):
            ct.destroy(pos)
            if ct.can_place_marker(pos):
                ct.place_marker(pos, encoding)
                return True

    return False
