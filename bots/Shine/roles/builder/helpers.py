from cambc import Controller, Direction, EntityType, Position
from helpers.directions import DIRECTIONS
import random

BABYSITTER_DIRECTION = Direction.CENTRE
GUARD_DIRECTION = Direction.EAST

# Harvester builders spawn on the four corners of the core.
HARVESTER_BUILDER_DIRECTIONS = [
    Direction.NORTHEAST,
    Direction.NORTHWEST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
]
# Rushers spawn on the four cardinal edges of the core.
RUSHER_DIRECTIONS = [
    Direction.NORTH,
    Direction.SOUTH,
    Direction.EAST,
    Direction.WEST,
]
# Centre-spawned explorers — free-form checker targeting, no follow.
CENTER_DIRECTIONS = [
    Direction.CENTRE,
]

# Legacy single-direction aliases (first choice in each list).
HARVESTER_BUILDER_DIRECTION = HARVESTER_BUILDER_DIRECTIONS[0]
RUSHER_DIRECTION = RUSHER_DIRECTIONS[0]

# Conveyors
def build_conveyor(ct: Controller, pos: Position, facing: Direction):
    if ct.can_build_conveyor(pos, facing):
        ct.build_conveyor(pos, facing)
        return True
    return False


def build_armoured_conveyor(ct: Controller, pos: Position, facing: Direction):
    if ct.can_build_armoured_conveyor(pos, facing):
        ct.build_armoured_conveyor(pos, facing)
        return True
    return False

def build_splitter(ct: Controller, pos: Position, facing: Direction):
    if ct.can_build_splitter(pos, facing):
        ct.build_splitter(pos, facing)
        return True
    return False


# Harvester / Foundry
def build_harvester(ct: Controller, pos: Position):
    # if we are adjacent to an ore tile, build a harvester on it
    if ct.can_build_harvester(pos):
        ct.build_harvester(pos)
        return True
    return False

def build_foundry(ct: Controller, pos: Position):
    if ct.can_build_foundry(pos):
        ct.build_foundry(pos)
        return True
    return False


# Turrets
def build_gunner(ct: Controller, pos: Position, facing: Direction):
    if ct.can_build_gunner(pos, facing):
        ct.build_gunner(pos, facing)
        return True
    return False

def build_breach(ct: Controller, pos: Position, facing: Direction):
    if ct.can_build_breach(pos, facing):
        ct.build_breach(pos, facing)
        return True
    return False

def build_launcher(ct: Controller, pos: Position, facing: Direction):
    if ct.can_build_launcher(pos):
        ct.build_launcher(pos)
        return True
    return False

def build_sentinel(ct: Controller, pos: Position, facing: Direction):
    if ct.can_build_gunner(pos, facing):
        ct.build_sentinel(pos, facing)
        return True
    return False


# Tiling
def build_road(ct: Controller, pos: Position):
    building = ct.get_tile_building_id(pos)
    if building is not None and ct.get_entity_type() == EntityType.MARKER:
        if ct.can_destroy(pos):
            ct.destroy(pos)
    if ct.can_build_road(pos):
        ct.build_road(pos)
        return True
    return False

def build_conveyor(ct: Controller, pos: Position):
    my_pos = ct.get_position()
    dir = my_pos.direction_to(pos)
    building = ct.get_tile_building_id(pos)
    if building is not None and ct.get_entity_type(building) != EntityType.CONVEYOR:
        if ct.can_destroy(pos):
            ct.destroy(pos)
    if ct.can_build_conveyor(pos, dir):
        ct.build_conveyor(pos, dir)
        return True
    return False

def build_barrier(ct: Controller, pos: Position):
    if ct.can_build_barrier(pos):
        ct.build_barrier(pos)
        return True
    return False


# Marker
def place_marker(ct: Controller):
    # place a marker on an adjacent tile with the current round number
    marker_pos = ct.get_position().add(random.choice(DIRECTIONS))
    if ct.can_place_marker(marker_pos):
        ct.place_marker(marker_pos, ct.get_current_round())
        return True
    return False



def in_bounds(ct: Controller, pos: Position):
    return (pos.x >= 0 and pos.x < ct.get_map_width() and 
        pos.y >= 0 and pos.y < ct.get_map_height())

def destroy_road(ct: Controller, pos: Position) -> bool:
    tile_id = ct.get_tile_building_id(pos)
    tile_type = ct.get_entity_type(tile_id)
    if tile_type == EntityType.ROAD:
        if ct.can_destroy(pos):
            ct.destroy(pos)
            return True
    return False
