"""Pure stateless helpers used across the harvester-build pipeline."""

from cambc import Controller, Position

from harvesters.constants import ACTION_RADIUS_SQ


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) <= ACTION_RADIUS_SQ


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def is_on_position(a: Position, b: Position) -> bool:
    return a.x == b.x and a.y == b.y


def in_theory_can_build_harvester(ct: Controller, pos: Position) -> bool:
    if not in_action_range(ct.get_position(), pos):
        return False
    if ct.get_global_resources()[0] < ct.get_harvester_cost()[0]:
        return False
    return ct.get_action_cooldown() == 0
