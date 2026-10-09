
from cambc import Controller, Position

from nav.movement import move_road_if_empty, move_conveyor, move_no_road
from nav.fast_passability import (
    fast_passability_default
)
from map.map_manager import MapManager
from nav.pathing import Pathing


def common_path(ct: Controller, mm: MapManager, pathing: Pathing,
                target: Position):
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target,
        move_road_if_empty,
        fast_passability_default,
    )


def save_path(ct: Controller, mm: MapManager, pathing: Pathing,
              target: Position):
    move_fn = (
        move_no_road
        if ct.get_global_resources()[0] < ct.get_harvester_cost()[0] * 1.5
        else move_road_if_empty
    )
    return pathing.path_to(
        ct, mm,
        ct.get_position(),
        target,
        move_fn,
        fast_passability_default,
    )