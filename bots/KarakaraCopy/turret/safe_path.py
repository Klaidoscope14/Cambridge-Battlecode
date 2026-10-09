from cambc import Environment, Position
from helpers.directions import DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager
from nav.common import common_path

ACTION_RADIUS_SQ = 2


def _is_in_danger(pos: Position, danger: list[Position]) -> bool:
    for dp in danger:
        if pos.x == dp.x and pos.y == dp.y:
            return True
    return False


def _is_passable_safe_spot(ct, mm: MapManager, pos: Position, danger: list[Position]) -> bool:
    if not on_map(pos, mm.width, mm.height):
        return False
    if _is_in_danger(pos, danger):
        return False
    tile = mm.get_tile(pos)
    if tile is None or tile == Environment.WALL:
        return False
    bot = mm.get_bot(pos)
    if bot is not None and bot.id != ct.get_id():
        return False
    return True


def path_to_build_spot(ct, mm: MapManager, pathing, target_pos: Position):
    """Path toward target_pos to build a turret. If target_pos is in a gunner
    danger zone, path to a safe adjacent tile instead (within action radius)."""
    danger = mm.gunner_danger_positions
    if not _is_in_danger(target_pos, danger):
        common_path(ct, mm, pathing, target_pos)
        return

    my_pos = ct.get_position()
    best = None
    best_dist = float("inf")
    for d in DIRECTIONS:
        adj = target_pos.add(d)
        if not _is_passable_safe_spot(ct, mm, adj, danger):
            continue
        dist = my_pos.distance_squared(adj)
        if dist < best_dist:
            best_dist = dist
            best = adj

    if best is not None:
        common_path(ct, mm, pathing, best)
