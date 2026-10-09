from cambc import Controller, Environment, EntityType, Position, Direction
from vision.vision_manager import VisionManager
from map.map_manager import MapManager
from roles.builder.helpers import in_bounds
from helpers.directions import DIRECTIONS


def core_is_damaged(ct: Controller, mm: MapManager, core_pos: Position) -> bool:
    """Return True if the allied core is missing any HP."""
    core_record = mm.get_building(core_pos)
    if core_record is None:
        return False
    return core_record.hp < core_record.max_hp


def on_core(my_pos: Position, core_pos: Position) -> bool:
    """Return True if my_pos is within the 3×3 core footprint."""
    return abs(my_pos.x - core_pos.x) <= 1 and abs(my_pos.y - core_pos.y) <= 1