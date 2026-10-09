from cambc import Environment, Position, EntityType, Team, Controller, ResourceType

from map.schema import EntityCell, EnvironmentCell, MarkerCell, BotCell
from map.records import record_from_controller
from helpers.directions import DIRECTIONS, CARDINAL
from debug.profiling import cputimer
from helpers.encoder import encode_turret_details, decode_turret_details, get_marker_type
from roles.builder.helpers import in_bounds


ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER]#, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
ORE_INPUT_TYPES = [EntityType.FOUNDRY, EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.CORE, EntityType.SPLITTER, EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL]
TURRET_TYPES = [EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH]

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
        # specific types
        self.nearby_ally_harvester_ids: list[int] = []
        self.nearby_ally_conveyor_ids: list[int] = []
        self.nearby_ally_bridge_ids: list[int] = []
        self.nearby_ally_splitter_ids: list[int] = []
        self.nearby_ally_bot_ids: list[int] = []
        self.nearby_ally_turret_ids: list[int] = []
        self.nearby_ally_road_ids: list[int] = []
        self.nearby_ally_foundry_ids: list[int] = []
        # TITANIUM ONLY
        self.nearby_adjacent_harvester_conveyor_positions: list[int] = []

        # not connected
        self.nearby_ally_open_titanium_harvester_ids: list[int] = []
        self.nearby_ally_open_axionite_harvester_ids: list[int] = []
        self.nearby_ally_open_foundry_ids: list[int] = []
        self.nearby_ally_open_conveyor_ids: list[int] = []
        self.nearby_ally_open_raw_axionite_conveyor_ids: list[int] = []
        self.nearby_ally_open_raw_axionite_bridge_ids: list[int] = []

        self.nearby_ally_open_bridge_ids: list[int] = []
        self.nearby_ally_open_splitter_ids: list[int] = []

        self.nearby_enemy_builder_bot_ids: list[int] = []
        self.nearby_enemy_harvester_ids: list[int] = []
        self.nearby_enemy_conveyor_ids: list[int] = []
        self.nearby_enemy_bridge_ids: list[int] = []

        self.nearby_enemy_core_pos: list[Position] = []
        self.nearby_enemy_turret_pos: list[Position] = []
        self.nearby_harvester_pos: list[Position] = []
        self.nearby_harvester_card_pos = []
        self.nearby_harvester_enemy_card_pos = []
        self.harvester_sentinel_count: dict[tuple[int, int], int] = {}

        self.known_ore_positions: set[Position] = set()
        
        self.seen_no_axionite_foundry_positions: set[Position] = set()
        # TITANIUM ONLY
        self.seen_adjacent_harvester_conveyor_positions: set[Position] = set()
        self.seen_ally_no_foundry_harvester_positions: set[Position] = set()

        self.spotted_enemy_core_pos: Position | None = None
        self.ally_core_pos: Position = self.query_ally_core(ct)
        
        self._harvesters: set[Position] = set()
        self._last_enemy_builder_seen_round: int | None = None

        # Tiles revealed this turn (were None in tile_grid before update).
        # Consumed by pathing for incremental re-expansion.
        self.newly_seen: set[tuple[int, int]] = set()

    @cputimer
    def update(self, ct: Controller) -> None:
        self.nearby_entity_ids = ct.get_nearby_entities()
        self.nearby_positions = ct.get_nearby_tiles()
        # reset nearby
        self.nearby_ally_harvester_ids = []
        self.nearby_ally_bridge_ids = []
        self.nearby_ally_conveyor_ids = []

        self.nearby_ally_raw_axionite_bridge_ids = []
        self.nearby_ally_raw_axionite_conveyor_ids = []
        self.nearby_adjacent_harvester_conveyor_positions = []
        self.nearby_ally_splitter_ids = []
        self.nearby_ally_bot_ids = []
        self.nearby_ally_turret_ids = []
        self.nearby_ally_road_ids = []
        self.nearby_ally_foundry_ids = []

        self.nearby_ally_open_conveyor_ids = []
        self.nearby_ally_open_bridge_ids = []
        self.nearby_ally_open_titanium_harvester_ids = []
        self.nearby_ally_open_foundry_ids = []
        self.nearby_ally_open_axionite_harvester_ids = []
        self.nearby_ally_open_splitter_ids = []
        self.nearby_ally_open_raw_axionite_conveyor_ids = []
        self.nearby_ally_open_raw_axionite_bridge_ids = []

        self.nearby_enemy_builder_bot_ids = []
        self.nearby_enemy_harvester_ids = []
        self.nearby_enemy_conveyor_ids = []
        self.nearby_enemy_bridge_ids = []
        
        self.nearby_enemy_core_pos = []
        self.nearby_harvester_pos = []
        self.nearby_enemy_turret_pos = []
        self.nearby_harvester_card_pos = []
        self.nearby_harvester_enemy_card_pos = []
        self.harvester_sentinel_count = {}

        my_team = ct.get_team()
        my_pos = ct.get_position()
        for eid in self.nearby_entity_ids:
            unit_type = ct.get_entity_type(eid)
            if ct.get_team(eid) == my_team:

                if unit_type == EntityType.HARVESTER:
                    self.nearby_ally_harvester_ids.append(eid)
                    harvester_pos = ct.get_position(eid)
                    self._harvesters.add(harvester_pos)
                    if my_pos.distance_squared(harvester_pos) > 9:
                        continue
                    self.nearby_harvester_pos.append(harvester_pos)
                    is_connected = False
                    has_foundry = False
                    for d in CARDINAL:
                        adj_pos = harvester_pos.add(d)
                        if my_pos.distance_squared(adj_pos) > ct.get_vision_radius_sq() or not in_bounds(ct, adj_pos):
                            continue    
                        self.nearby_harvester_card_pos.append((harvester_pos, adj_pos))
                        adj_id = ct.get_tile_building_id(adj_pos)
                        if adj_id is not None:
                            adj_type = ct.get_entity_type(adj_id)
                            if adj_type == EntityType.SENTINEL:
                                key = (harvester_pos.x, harvester_pos.y)
                                self.harvester_sentinel_count[key] = self.harvester_sentinel_count.get(key, 0) + 1
                            if adj_type in [EntityType.CORE, EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER, EntityType.FOUNDRY]:
                                is_connected = True
                            if adj_type == EntityType.FOUNDRY:
                                has_foundry = True
                            if adj_type == EntityType.CONVEYOR and ct.get_tile_env(harvester_pos) == Environment.ORE_TITANIUM:
                                self.seen_adjacent_harvester_conveyor_positions.add(adj_pos)
                                self.nearby_adjacent_harvester_conveyor_positions.append(adj_id)
                        # clear
                        if adj_pos in self.seen_adjacent_harvester_conveyor_positions:
                            if adj_id == None or ct.get_entity_type(adj_id) != EntityType.CONVEYOR:
                                self.seen_adjacent_harvester_conveyor_positions.discard(adj_pos)

                    if not is_connected:
                        if ct.get_tile_env(harvester_pos) == Environment.ORE_TITANIUM:
                            self.nearby_ally_open_titanium_harvester_ids.append(eid)
                        if ct.get_tile_env(harvester_pos) == Environment.ORE_AXIONITE:
                            self.nearby_ally_open_axionite_harvester_ids.append(eid)

                    if not has_foundry and ct.get_tile_env(harvester_pos) == Environment.ORE_TITANIUM:
                        self.seen_ally_no_foundry_harvester_positions.add(harvester_pos)
                    if has_foundry and harvester_pos in self.seen_ally_no_foundry_harvester_positions:
                        self.seen_ally_no_foundry_harvester_positions.discard(harvester_pos)

                elif unit_type == EntityType.CONVEYOR:

                    self.nearby_ally_conveyor_ids.append(eid)
                    conveyor_pos = ct.get_position(eid)
                    # conveyors that aren't connected
                    next = ct.get_position(eid).add(ct.get_direction(eid))
                    if my_pos.distance_squared(next) > ct.get_vision_radius_sq() or not in_bounds(ct, next):
                        continue
                    next_id = ct.get_tile_building_id(next)
                    if next_id == None or ct.get_entity_type(next_id) not in ORE_INPUT_TYPES:
                        self.nearby_ally_open_conveyor_ids.append(eid)
                        if ct.get_stored_resource(eid) == ResourceType.RAW_AXIONITE:
                            self.nearby_ally_open_raw_axionite_conveyor_ids.append(eid)

                elif unit_type == EntityType.BRIDGE:

                    self.nearby_ally_bridge_ids.append(eid)
                    if ct.get_stored_resource(eid) == ResourceType.RAW_AXIONITE:
                        self.nearby_ally_raw_axionite_bridge_ids.append(eid)

                    target = ct.get_bridge_target(eid)
                    if my_pos.distance_squared(target) > ct.get_vision_radius_sq() or not in_bounds(ct, target):
                        continue
                    target_id = ct.get_tile_building_id(target)
                    if target_id == None or ct.get_entity_type(target_id) not in [EntityType.FOUNDRY, EntityType.CONVEYOR, EntityType.CORE, EntityType.BRIDGE, EntityType.SPLITTER]:
                        if ct.get_stored_resource(eid) == ResourceType.RAW_AXIONITE:
                            self.nearby_ally_open_raw_axionite_bridge_ids.append(eid)
                        elif ct.get_stored_resource(eid) in [ResourceType.REFINED_AXIONITE, ResourceType.TITANIUM]:
                            self.nearby_ally_open_bridge_ids.append(eid)

                elif unit_type == EntityType.SPLITTER:
                    self.nearby_ally_splitter_ids.append(eid)
                    next = ct.get_position(eid).add(ct.get_direction(eid))
                    if my_pos.distance_squared(next) > ct.get_vision_radius_sq() or not in_bounds(ct, next):
                        continue
                    next_id = ct.get_tile_building_id(next)
                    if next_id == None or ct.get_entity_type(next_id) not in ORE_INPUT_TYPES:
                        self.nearby_ally_open_splitter_ids.append(eid)
                
                elif unit_type == EntityType.BUILDER_BOT:
                    self.nearby_ally_bot_ids.append(eid)

                elif unit_type in TURRET_TYPES:
                    self.nearby_ally_turret_ids.append(eid)

                elif unit_type == EntityType.ROAD:
                    self.nearby_ally_road_ids.append(eid)
                
                elif unit_type == EntityType.FOUNDRY:
                    self.nearby_ally_foundry_ids.append(eid)

                    foundry_pos = ct.get_position(eid)
                    inputs = 0
                    is_connected = False
                    for d in CARDINAL:
                        adj_pos = foundry_pos.add(d)
                        if not in_bounds(ct, adj_pos) or ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq():
                            continue
                        adj_id = ct.get_tile_building_id(adj_pos)

                        if adj_id != None:
                            if ct.get_entity_type(adj_id) == EntityType.CONVEYOR:
                                if ct.get_direction(adj_id) == d.opposite():
                                    inputs += 1
                                if ct.get_direction(adj_id) != d.opposite():
                                    is_connected = True
                                print(is_connected)
                            if ct.get_entity_type(adj_id) == EntityType.BRIDGE:
                                is_connected = True
                            elif ct.get_entity_type(adj_id) == EntityType.SPLITTER:
                                inputs += 1

                    if not is_connected:
                        self.nearby_ally_open_foundry_ids.append(eid)

                    if inputs < 2 and foundry_pos not in self.seen_no_axionite_foundry_positions:
                        self.seen_no_axionite_foundry_positions.add(foundry_pos)
                    elif inputs >= 2 and foundry_pos in self.seen_no_axionite_foundry_positions:
                        self.seen_no_axionite_foundry_positions.discard(foundry_pos)


            else:
                if unit_type == EntityType.BUILDER_BOT:
                    self.nearby_enemy_builder_bot_ids.append(eid)
                    self._last_enemy_builder_seen_round = ct.get_current_round()
                elif unit_type == EntityType.HARVESTER:
                    self.nearby_enemy_harvester_ids.append(eid)
                    harvester_pos = ct.get_position(eid)
                    self._harvesters.add(harvester_pos)
                    if my_pos.distance_squared(harvester_pos) <= 9:
                        self.nearby_harvester_pos.append(harvester_pos)
                        for d in CARDINAL:
                            adj_pos = harvester_pos.add(d)
                            if my_pos.distance_squared(adj_pos) > ct.get_vision_radius_sq() or not in_bounds(ct, adj_pos):
                                continue
                            self.nearby_harvester_enemy_card_pos.append((harvester_pos, adj_pos))

                elif unit_type == EntityType.CONVEYOR:
                    self.nearby_enemy_conveyor_ids.append(eid)
                elif unit_type == EntityType.BRIDGE:
                    self.nearby_enemy_bridge_ids.append(eid)
                elif unit_type == EntityType.CORE:
                    self.nearby_enemy_core_pos.append(ct.get_position(eid))
                elif unit_type == EntityType.SENTINEL or unit_type == EntityType.GUNNER:
                    self.nearby_enemy_turret_pos.append(ct.get_position(eid))

        self.newly_seen = set()
        for pos in self.nearby_positions:
            env = ct.get_tile_env(pos)
            if self.tile_grid[pos.x][pos.y] is None:
                self.newly_seen.add((pos.x, pos.y))
            self.tile_grid[pos.x][pos.y] = env

            bbid = ct.get_tile_builder_bot_id(pos)
            if bbid is not None:
                record = record_from_controller(ct, bbid)
                self.bot_grid[pos.x][pos.y] = record
            else:
                self.bot_grid[pos.x][pos.y] = None
            if env in [Environment.ORE_TITANIUM, Environment.ORE_AXIONITE]:
                self.known_ore_positions.add(pos)

            # Clear empty buildings
            bid = ct.get_tile_building_id(pos)
            if bid is None:
                self.building_grid[pos.x][pos.y] = None
            else:
                record = record_from_controller(ct, bid)
                self.building_grid[pos.x][pos.y] = record
                if record.entity_type == EntityType.CORE and record.team != ct.get_team():
                    self.spotted_enemy_core_pos = pos
                if record.entity_type == EntityType.HARVESTER:
                    self.known_ore_positions.discard(pos)
        
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

    @property
    def last_enemy_builder_seen_round(self) -> int | None:
        """Last round an enemy builder bot was in vision range, or None if never."""
        return self._last_enemy_builder_seen_round

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