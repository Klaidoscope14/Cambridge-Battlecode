"""Geometry: in_bounds, distance, adjacent, radius."""

from cambc import Direction, Position

def in_vision(unit_pos: Position, pos: Position, vision_r_sq: int) -> bool:
    return unit_pos.distance_squared(pos) <= vision_r_sq


def on_map(pos: Position, w: int, h: int) -> bool:
    """Return True if pos is within map bounds [0, width) x [0, height)."""
    return 0 <= pos.x < w and 0 <= pos.y < h


def chebyshev_distance(a: Position, b: Position) -> int:
    """Return Chebyshev (max of dx, dy) distance between a and b."""
    return max(abs(a.x - b.x), abs(a.y - b.y))


def manhattan_distance(a: Position, b: Position) -> int:
    """Return Manhattan distance between a and b."""
    return abs(a.x - b.x) + abs(a.y - b.y)

def step_distance(a: Position, b: Position) -> int:
    """Return squared distance between a and b."""
    return max(abs(a.x - b.x), abs(a.y - b.y))


def adjacent_tiles(pos: Position, width: int, height: int) -> list[Position]:
    """Return in-bounds positions adjacent to pos (all 8 neighbours)."""
    result = []
    for d in Direction:
        if d == Direction.CENTRE:
            continue
        dx, dy = d.delta()
        nx, ny = pos.x + dx, pos.y + dy
        if 0 <= nx < width and 0 <= ny < height:
            result.append(Position(nx, ny))
    return result


def tiles_in_radius(pos: Position, radius_sq: int, width: int, height: int) -> list[Position]:
    """Return all in-bounds tiles within squared Euclidean distance radius_sq."""
    result = []
    r = int(radius_sq ** 0.5) + 1
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if dx * dx + dy * dy > radius_sq:
                continue
            nx, ny = pos.x + dx, pos.y + dy
            if 0 <= nx < width and 0 <= ny < height:
                result.append(Position(nx, ny))
    return result

def average_locations(locs):
    total_x = 0
    total_y = 0
    for loc in locs:
        total_x += loc.x
        total_y += loc.y
    return Position(
        total_x / len(locs),
        total_y / len(locs)
    )

def nearest_manhattan_location(ct, locs):
    if len(locs) == 0:
        return None
    best = locs[0]
    my_pos = ct.get_position()
    for loc in locs:
        if manhattan_distance(my_pos, loc) < manhattan_distance(my_pos, best):
            best = loc
    return best
