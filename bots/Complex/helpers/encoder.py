from helpers.constants import SUICIDE_POS_CONSTANT
from cambc import Position, EntityType
from helpers.constants import GUNNER, BREACH, SENTINEL, LAUNCHER
from helpers.directions import DIRECTIONS
def get_marker_type(encoded_val: int):
    return encoded_val % 10
def encode_turret_details(turret_type, dir, pos: Position):
    #xxyydt
    dir_idx = DIRECTIONS.index(dir) + 1
    turret_types = [EntityType.GUNNER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER]
    turret_idx = turret_types.index(turret_type) + 1
    encoding = pos.x * 10000 + pos.y * 100 + dir_idx * 10 + turret_idx
    return encoding
def decode_turret_details(encoding: int):
    turret_type, encoding = encoding % 10, encoding // 10
    dir, encoding = encoding % 10, encoding // 10
    y, encoding = encoding % 100, encoding // 100
    x = encoding
    turret_types = [EntityType.GUNNER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER]
    return (turret_types[turret_type - 1], DIRECTIONS[dir - 1], Position(x, y))
def encode_suicide_details(target_pos: Position):
    encoding = target_pos.x * 1000 + target_pos.y * 10 + SUICIDE_POS_CONSTANT
    return encoding
def decode_suicide_details(encoding: int):
    encoding = encoding // 10
    y, encoding = encoding % 100, encoding // 100
    x = encoding
    return Position(x, y)