
from cambc import Controller, Position

from nav.movement import move_road_if_empty, move_conveyor
from nav.fast_passability import (
    fast_passability_default,
    fast_passability_save,
    fast_passability_no_build_road,
)
from map.map_manager import MapManager
from nav.pathing import Pathing


def common_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target,
        move_road_if_empty,
        fast_passability_default,
    )

def no_build_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target,
        move_road_if_empty,
        fast_passability_no_build_road,
    )

def cardinal_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target,
        move_conveyor,
        fast_passability_default,
    )

def save_path(ct: Controller, mm: MapManager, pathing: Pathing, target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target,
        move_road_if_empty,
        fast_passability_save,
    )