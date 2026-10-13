"""Direction helpers: non-centre list, ordering, optional direction_from_to."""

from cambc import Direction, Position

# All directions except CENTRE, for iteration.
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

# Cardinal then diagonal ordering (for consistent tie-breaking).
CARDINAL = [
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
]
DIAGONAL = [
    Direction.NORTHEAST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
    Direction.NORTHWEST,
]

CARDINAL_THEN_DIAGONAL = CARDINAL + DIAGONAL
OFFSET_TO_DIRECTION = {
    (1, 0): Direction.EAST,
    (-1, 0): Direction.WEST,
    (0, 1): Direction.SOUTH,
    (0, -1): Direction.NORTH,
}


def directions_toward(pos: Position, target: Position) -> list[Direction]:
    """Return directions from pos to target, best first (closest alignment)."""
    if pos == target:
        return []
    return [pos.direction_to(target)] + [
        d for d in CARDINAL_THEN_DIAGONAL if d != pos.direction_to(target)
    ]


def is_cardinal(d: Direction) -> bool:
    """Return True if d is north/east/south/west."""
    return d in CARDINAL


def is_cardinal_or_diagonal(d: Direction) -> bool:
    """Return True if d is not CENTRE."""
    return d != Direction.CENTRE
