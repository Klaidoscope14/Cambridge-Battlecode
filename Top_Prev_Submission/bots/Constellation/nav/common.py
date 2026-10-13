
from cambc import Controller, Position

from nav.movement import move_road_if_empty, move_conveyor
from nav.passability import passability_no_build_road, passability_default, passability_save, passability_avoid_launcher
from map.map_manager import MapManager
from nav.pathing import Pathing
from functools import partial

def common_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target, 
        move_road_if_empty,
        passability_default,
        cardinal=False
    )

def no_build_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target, 
        move_road_if_empty,
        passability_no_build_road,
        cardinal=False
    )

def cardinal_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target, 
        move_conveyor,
        passability_default,
        cardinal=True
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
# avoids launcher until its adj to target, for the edge case that the target is on a launcher zone, we want to go there anyways
def avoid_launcher_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    my_pos = ct.get_position()
    if abs(my_pos.x - target.x) <= 1 and abs(my_pos.y - target.y) <= 1:
        print("common_pathing")
        return common_path(ct, mm, pathing, target)
    else:
        print("avoid_launcher_pathing")
        return pathing.path_to(
            ct, mm,
            my_pos,
            target,
            move_road_if_empty,
            partial(passability_avoid_launcher, target_pos=target),
            cardinal = False
        )