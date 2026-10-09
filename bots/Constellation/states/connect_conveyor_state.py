from cambc import Controller, EntityType, Direction, Position, Environment, ResourceType
from helpers.directions import CARDINAL, DIRECTIONS
from roles.builder.helpers import in_bounds
from nav.common import common_path
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from map.map_manager import MapManager

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
BRIDGE_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]

class ConnectConveyorState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.SOURCE_TYPES = [EntityType.HARVESTER, EntityType.BRIDGE, EntityType.CONVEYOR]
        self.prev_dir = None
        self.build_pos = None
        self.dest = None
        self.path_builder = PathBuilder(ct, brain)

    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        # adj to build pos, we can do our connect and move stuff, otherwise we need to move to the build pos
        if abs(my_pos.x - self.build_pos.x) <= 1 and abs(my_pos.y - self.build_pos.y) <= 1:
            print("connect and move")
            self.path_builder.connect_and_move(ct, self.prev_dir, self.build_pos, self.dest, False)
            self.build_pos = None
        else:
            print("moving to build pos")
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)

    def determine_connect_conveyor_state(self, ct: Controller, state_manager):
        if self.build_pos != None:
            state_manager.current_state = BuilderState.CONNECT_CONVEYOR
            return True
        
        source = self.get_closest_source(ct)
        if source != None:
            build_pos = self.get_build_pos(ct, source)
            if build_pos == None:
                return False
            if ct.get_entity_type(source) in [EntityType.CONVEYOR, EntityType.SPLITTER]:
                self.prev_dir = ct.get_direction(source)
            else:
                self.prev_dir = None
            self.build_pos = build_pos
            self.dest = self.brain.map_manager.ally_core_pos
            state_manager.current_state = BuilderState.CONNECT_CONVEYOR
            return True
        return False
    
    def get_build_pos(self, ct: Controller, eid):
        unit_type = ct.get_entity_type(eid)
        if unit_type == EntityType.HARVESTER:
            return self.get_harvester_build_pos(ct, eid)
        if unit_type == EntityType.FOUNDRY:
            return self.get_harvester_build_pos(ct, eid)
        elif unit_type == EntityType.CONVEYOR:
            return self.get_conv_build_pos(ct, eid)
        elif unit_type == EntityType.BRIDGE:
            return self.get_bridge_build_pos(ct, eid)
        elif unit_type == EntityType.SPLITTER:
            return self.get_splitter_build_pos(ct, eid)

    def get_harvester_build_pos(self, ct: Controller, eid):
        harv_pos = ct.get_position(eid)
        best_pos = None
        best_dist = float('inf')
        core_pos = self.brain.map_manager.ally_core_pos
        
        for d in CARDINAL:
            adj_pos = harv_pos.add(d)
            if ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq() or not in_bounds(ct, adj_pos):
                continue
            adj_eid = ct.get_tile_building_id(adj_pos)
            adj_env = ct.get_tile_env(adj_pos)
            if adj_env in BLOCKING_ENVIRONMENT_TYPES:
                continue
            if adj_eid is not None and ct.get_entity_type(adj_eid) in ALLY_BLOCKING_TYPES:
                continue
            dist = adj_pos.distance_squared(core_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = adj_pos
        
        return best_pos
        
    def get_conv_build_pos(self, ct: Controller, eid):
        pos = ct.get_position(eid).add(ct.get_direction(eid))
        return pos
        
    def get_bridge_build_pos(self, ct: Controller, eid):
        pos = ct.get_bridge_target(eid)
        return pos
    
    def get_splitter_build_pos(self, ct, eid):
        pos = ct.get_position(eid).add(ct.get_direction(eid))
        return pos
    
    def get_closest_source(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        all_nearby_sources = mm.nearby_ally_open_bridge_ids + mm.nearby_ally_open_conveyor_ids + mm.nearby_ally_open_titanium_harvester_ids + mm.nearby_ally_open_splitter_ids + mm.nearby_ally_open_foundry_ids
        best_id = None
        best_dist = float('inf')
        for eid in all_nearby_sources:
            dist = ct.get_position().distance_squared(ct.get_position(eid))
            if ct.get_entity_type(eid) == EntityType.BRIDGE and ct.get_stored_resource(eid) == ResourceType.RAW_AXIONITE:
                continue
            if dist < best_dist:
                best_dist = dist
                best_id = eid
        return best_id if best_id is not None else None