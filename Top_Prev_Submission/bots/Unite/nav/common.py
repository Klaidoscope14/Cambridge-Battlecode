
from cambc import Controller, Position

from nav.movement import move_road_if_empty
from nav.passability import passability_default, passability_save
from map.map_manager import MapManager
from nav.pathing import Pathing


def common_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target, 
        move_road_if_empty,
        passability_default,
        cardinal=False
    )

def save_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target, 
        move_road_if_empty,
        passability_save,
        cardinal=False
    )