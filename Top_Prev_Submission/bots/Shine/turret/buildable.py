from cambc import EntityType, Environment, Position
from map.map_manager import MapManager

DESTROYABLE = {EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER}


def is_destroyable_blocker(mm: MapManager, pos: Position, building) -> bool:
    if building.entity_type in DESTROYABLE:
        return True
    if building.entity_type == EntityType.CONVEYOR:
        target = pos.add(building.direction)
        if 0 <= target.x < mm.width and 0 <= target.y < mm.height:
            target_building = mm.get_building(target)
            if target_building is not None and target_building.entity_type == EntityType.HARVESTER:
                return True
    return False


def is_buildable_spot(ct, mm: MapManager, pos: Position) -> bool:
    bot = mm.get_bot(pos)
    if bot is not None and bot.id != ct.get_id():
        return False
    building = mm.get_building(pos)
    if building is None:
        tile = mm.get_tile(pos)
        return tile is not None and tile == Environment.EMPTY
    if building.team != ct.get_team():
        return False
    return is_destroyable_blocker(mm, pos, building)
