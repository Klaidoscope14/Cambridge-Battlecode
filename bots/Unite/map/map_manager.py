from cambc import Environment, Position, EntityType, Team

from map.schema import EntityCell, EnvironmentCell, MarkerCell, BotCell
from map.records import record_from_controller
from helpers.directions import DIRECTIONS
from debug.profiling import cputimer
from helpers.encoder import encode_turret_details, decode_turret_details, get_marker_type


class MapManager:
    def __init__(self, ct) -> None:
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()

        self.tile_grid: list[list[EnvironmentCell]] = [
            [None for _ in range(self.height)] for _ in range(self.width)
        ]

        # Stores core even if cores aren't buildings
        self.building_grid: list[list[EntityCell]] = [
            [None for _ in range(self.height)] for _ in range(self.width)
        ]

        self.bot_grid: list[list[BotCell]] = [
            [None for _ in range(self.height)] for _ in range(self.width)
        ]

        self.nearby_entity_ids: list[int] = []
        self.nearby_positions: list[Position] = []

        self.spotted_enemy_core_pos: Position | None = None
        self.ally_core_pos: Position = self.query_ally_core(ct)

    @cputimer
    def update(self, ct) -> None:
        self.nearby_entity_ids = ct.get_nearby_entities()
        self.nearby_positions = ct.get_nearby_tiles()

        for pos in self.nearby_positions:
            env = ct.get_tile_env(pos)
            self.tile_grid[pos.x][pos.y] = env

            bbid = ct.get_tile_builder_bot_id(pos)
            if bbid is not None:
                record = record_from_controller(ct, bbid)
                self.bot_grid[pos.x][pos.y] = record
            else:
                self.bot_grid[pos.x][pos.y] = None

            # Clear empty buildings
            bid = ct.get_tile_building_id(pos)
            if bid is None:
                self.building_grid[pos.x][pos.y] = None
            else:
                record = record_from_controller(ct, bid)
                self.building_grid[pos.x][pos.y] = record
                if record.entity_type == EntityType.CORE and record.team != ct.get_team():
                    self.spotted_enemy_core_pos = pos
        
        if self.ally_core_pos:
            ally_core_record = self.building_grid[self.ally_core_pos.x][self.ally_core_pos.y]
            self.building_grid[self.ally_core_pos.x - 1][self.ally_core_pos.y - 1] = ally_core_record
            self.building_grid[self.ally_core_pos.x - 1][self.ally_core_pos.y] = ally_core_record
            self.building_grid[self.ally_core_pos.x - 1][self.ally_core_pos.y + 1] = ally_core_record
            self.building_grid[self.ally_core_pos.x][self.ally_core_pos.y - 1] = ally_core_record
            self.building_grid[self.ally_core_pos.x][self.ally_core_pos.y + 1] = ally_core_record
            self.building_grid[self.ally_core_pos.x + 1][self.ally_core_pos.y - 1] = ally_core_record
            self.building_grid[self.ally_core_pos.x + 1][self.ally_core_pos.y] = ally_core_record
            self.building_grid[self.ally_core_pos.x + 1][self.ally_core_pos.y + 1] = ally_core_record

        # Note that spotted enemy core pos is simply one of the 9 positions of the enemy core
        # If you want to find actual core, use learned reflection

    def query_ally_core(self, ct):
        ids = ct.get_nearby_entities()
        for id in ids:
            if ct.get_entity_type(id) == EntityType.CORE:
                return ct.get_position(id)
        return None

    def has_seen(self, pos) -> None:
        return self.tile_grid[pos.x][pos.y] != None
    
    def has_wall(self, pos) -> None:
        return self.tile_grid[pos.x][pos.y] == Environment.WALL

    def has_ore(self, pos):
        return (self.tile_grid[pos.x][pos.y] == Environment.ORE_TITANIUM or
                self.tile_grid[pos.x][pos.y] == Environment.ORE_AXIONITE)
    
    def get_tile(self, pos):
        return self.tile_grid[pos.x][pos.y]

    def get_building(self, pos):
        return self.building_grid[pos.x][pos.y]
    
    def get_bot(self, pos):
        return self.bot_grid[pos.x][pos.y]

    def update_danger_grid(self, turret_type, turret_pos, turret_direction):
        print("UPDATING DANGER GRID")