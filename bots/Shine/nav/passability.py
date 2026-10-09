from cambc import Controller, Position, EntityType, GameConstants, Direction

from helpers.geometry import on_map
from helpers.directions import DIRECTIONS
from map.map_manager import MapManager

# Entity types a builder bot can walk on top of.
_WALKABLE_ENTITY_TYPES = frozenset({
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
    EntityType.MARKER
})

_conveyor_REPLACEABLE_ENTITY_TYPES = frozenset({
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.MARKER
})

BOT_IS_BLOCK_RADIUS = GameConstants.BUILDER_BOT_VISION_RADIUS_SQ

def can_pass_environment(ct: Controller, pos: Position, map_manager: MapManager) -> bool:
    # 1. Terrain check — walls are never passable.
    if not on_map(pos, map_manager.width, map_manager.height):
        return False

    if not map_manager.has_seen(pos):
        return False

    if map_manager.has_wall(pos):
        return False
    
    return True


def can_pass_entity(ct, pos: Position, map_manager: MapManager) -> bool:
    # Builder bots are ignored for pathing -- they move and we dodge them.
    # if ct.get_position().distance_squared(pos) <= BOT_IS_BLOCK_RADIUS:
    #     bot = map_manager.get_bot(pos)
    #     if bot is not None: return False

    building = map_manager.get_building(pos)
    if building is not None:
        if building.entity_type == EntityType.CORE:
            return building.team == ct.get_team()
        return building.entity_type in _WALKABLE_ENTITY_TYPES
    
    return True

def in_launcher_zone(ct: Controller, pos: Position, map_manager: MapManager) -> bool:
    my_pos = ct.get_position()
    vision_r_sq = ct.get_vision_radius_sq()
    for d in DIRECTIONS:
        adj_pos = pos.add(d)
        if not on_map(adj_pos, ct.get_map_width(), ct.get_map_height()):
            continue
        if adj_pos.distance_squared(my_pos) > vision_r_sq:
            continue
        building_id = ct.get_tile_building_id(adj_pos)
        if building_id == None:
            continue
        if ct.get_team(building_id) == ct.get_team():
            continue
        if ct.get_entity_type(building_id) == EntityType.LAUNCHER:
            return True
    return False

def need_road(ct, pos: Position, map_manager: MapManager) -> bool:
    building = map_manager.get_building(pos)
    return building is None or building.entity_type == EntityType.MARKER


def passability_save(ct, pos: Position, map_manager: MapManager) -> bool:
    if pos == ct.get_position(): return True

    if not can_pass_environment(ct, pos, map_manager): return False
    if not can_pass_entity(ct, pos, map_manager): return False
    if need_road(ct, pos, map_manager):
        return ct.get_global_resources()[0] > GameConstants.HARVESTER_BASE_COST[0]
    return True

def passability_default(ct, pos: Position, map_manager: MapManager) -> bool:
    if pos == ct.get_position(): return True

    if not can_pass_environment(ct, pos, map_manager): return False
    if not can_pass_entity(ct, pos, map_manager): return False
    if need_road(ct, pos, map_manager):
        return ct.get_global_resources()[0] > ct.get_road_cost()[0]
    return True

def passability_no_build_road(ct, pos: Position, map_manager: MapManager) -> bool:
    if pos == ct.get_position(): return True
    if not can_pass_environment(ct, pos, map_manager): return False
    if not can_pass_entity(ct, pos, map_manager): return False
    return not need_road(ct, pos, map_manager)


def passability_ally_conveyor(ct, pos: Position, map_manager: MapManager) -> bool:
    if not on_map(pos, map_manager.width, map_manager.height):
        return False

    if not map_manager.has_seen(pos):
        return False
    
    if map_manager.has_wall(pos):
        return False

    building = map_manager.get_building(pos)
    if building is not None:
        if building.entity_type != EntityType.MARKER and building.team != ct.get_team():
            return False
        return building.entity_type in _conveyor_REPLACEABLE_ENTITY_TYPES
    
    return True

def passability_avoid_launcher(ct, pos: Position, map_manager: MapManager, target_pos: Position) -> bool:
    if pos == ct.get_position(): return True
    if not can_pass_environment(ct, pos, map_manager): return False
    if not can_pass_entity(ct, pos, map_manager): return False
    if pos != target_pos:
        if in_launcher_zone(ct, pos, map_manager): return False
    if need_road(ct, pos, map_manager):
        return ct.get_global_resources()[0] > ct.get_road_cost()[0]
    return True
    
