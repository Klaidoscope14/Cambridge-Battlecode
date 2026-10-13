"""Stateless geometry + movement helpers for the ring-build pipeline."""

from cambc import Controller, Environment, EntityType, Position

from helpers.directions import CARDINAL, DIAGONAL
from nav.movement import move_road_if_empty

from ring.constants import (
    ACTION_RADIUS_SQ,
    ENEMY_INFRA_TYPES,
    STEP_OFF_MOVED,
    STEP_OFF_STUCK,
    STEP_OFF_WAITING,
)


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) <= ACTION_RADIUS_SQ


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def is_on_position(a: Position, b: Position) -> bool:
    return a.x == b.x and a.y == b.y


def try_step_off(ct: Controller, mm, target: Position) -> str:
    """Move off the target tile so the center can be built next.

    Cardinals (the freshly-placed ring slots) are tried first via a plain
    move — never build_road, since that would consume the action cooldown
    we need for the follow-up center build/destroy. Otherwise we exit
    diagonally only through tiles that *already* have a road; moving onto
    bare ground would also burn the action. If no diagonal road exit is
    free, lay a road on a buildable diagonal and return WAITING so the
    caller retries next tick. STUCK is reserved for the case where no
    cardinal/diagonal exit could ever exist (all blocked terrain/buildings,
    nothing road-buildable).
    """
    width = mm.width
    height = mm.height
    tile_grid = mm.tile_grid
    bot_grid = mm.bot_grid
    building_grid = mm.building_grid

    cardinal_exit_possible = False
    for d in CARDINAL:
        adj = target.add(d)
        ax = adj.x
        ay = adj.y
        if not (0 <= ax < width and 0 <= ay < height):
            continue
        tile = tile_grid[ax][ay]
        if tile is None or tile == Environment.WALL:
            continue
        # An empty/passable cardinal that's just transiently blocked by a
        # bot still counts as a possible future exit — don't declare STUCK.
        building = building_grid[ax][ay]
        if building is None or ct.is_tile_passable(adj):
            cardinal_exit_possible = True
        if bot_grid[ax][ay] is not None:
            continue
        if ct.can_move(d):
            ct.move(d)
            return STEP_OFF_MOVED

    road_build_dir = None
    road_build_pos = None
    diagonal_exit_possible = False
    for d in DIAGONAL:
        adj = target.add(d)
        ax = adj.x
        ay = adj.y
        if not (0 <= ax < width and 0 <= ay < height):
            continue
        tile = tile_grid[ax][ay]
        if tile is None or tile == Environment.WALL:
            continue
        building = building_grid[ax][ay]
        has_road = building is not None and building.entity_type == EntityType.ROAD
        if has_road:
            diagonal_exit_possible = True
            if bot_grid[ax][ay] is not None:
                continue
            if ct.can_move(d):
                ct.move(d)
                return STEP_OFF_MOVED
        elif (
            road_build_pos is None
            and building is None
            and bot_grid[ax][ay] is None
            and ct.can_build_road(adj)
        ):
            road_build_dir = d
            road_build_pos = adj
            diagonal_exit_possible = True

    if road_build_pos is not None:
        ct.build_road(road_build_pos)
        return STEP_OFF_WAITING

    if cardinal_exit_possible or diagonal_exit_possible:
        return STEP_OFF_WAITING
    return STEP_OFF_STUCK


def find_enemy_infra_cardinal(target: Position, mm, team):
    """Direction toward an enemy-infra tile cardinal-adjacent to target, or None."""
    width = mm.width
    height = mm.height
    building_grid = mm.building_grid
    for d in CARDINAL:
        adj = target.add(d)
        ax = adj.x
        ay = adj.y
        if not (0 <= ax < width and 0 <= ay < height):
            continue
        building = building_grid[ax][ay]
        if (
            building is not None
            and building.team != team
            and building.entity_type in ENEMY_INFRA_TYPES
        ):
            return d
    return None
