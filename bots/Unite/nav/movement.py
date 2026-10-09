"""Direction ordering, greedy step, build-road-then-move. All ct calls direct."""
from cambc import Controller, Direction, EntityType, Position
from helpers.directions import CARDINAL_THEN_DIAGONAL, directions_toward
from roles.builder.helpers import build_road
from debug.indicators import draw_move_direction


def greedy_step(ct: Controller, pos: Position, target: Position) -> Direction | None:
    """Return best legal move direction toward target, or None if no move."""
    if pos == target:
        return None
    ordered = directions_toward(pos, target)
    for d in ordered:
        if ct.can_move(d):
            return d
        # Check if we can build road then move
        target_pos = pos.add(d)
        if ct.can_build_road(target_pos):
            return d  # Caller can use build_road_then_move(ct, d)
    return None


def directions_away_from(pos: Position, danger: Position) -> list[Direction]:
    """Return directions ordered by increasing distance to danger (flee)."""
    def dist(d: Direction) -> int:
        p = pos.add(d)
        return p.distance_squared(danger)
    return sorted(CARDINAL_THEN_DIAGONAL, key=dist)


def move_road_if_empty(ct: Controller, direction: Direction) -> bool:
    move_pos = ct.get_position().add(direction)
    build_road(ct, move_pos)
    if ct.can_move(direction):
        ct.move(direction)
        return True
    return False


def move_away_from(ct: Controller, danger: Position) -> bool:
    """Take one step away from danger. Return True if moved."""
    pos = ct.get_position()
    for d in directions_away_from(pos, danger):
        if ct.can_move(d):
            ct.move(d)
            return True
        target_pos = pos.add(d)
        if ct.can_build_road(target_pos):
            ct.build_road(target_pos)
            if ct.can_move(d):
                ct.move(d)
                return True
    return False

def move_fake(ct: Controller, danger: Position) -> bool:
    pass
