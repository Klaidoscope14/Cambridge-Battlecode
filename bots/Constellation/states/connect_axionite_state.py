from cambc import Controller, EntityType, Position, ResourceType, Environment
from helpers.directions import CARDINAL
from map.map_manager import MapManager
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from conveyor.bridge_builder import BridgeBuilder
from debug.profiling import cputimer

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL]#, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
BRIDGE_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]


class ConnectAxioniteState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.prev_source = None
        self.build_pos = None
        self.dest = None
        self.prev_dir = None
        self.path_builder = PathBuilder(ct, brain)
        self.bridge_builder = BridgeBuilder(ct, brain)
    @cputimer
    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        if abs(my_pos.x - self.build_pos.x) <= 1 and abs(my_pos.y - self.build_pos.y) <= 1:
            print("connect and move")
            self.path_builder.connect_and_move(ct, self.prev_dir, self.build_pos, self.dest, False)
            self.build_pos = None
        else:
            print("moving to build pos")
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)

    def determine_connect_axionite_state(self, ct: Controller, state_manager):
        if self.build_pos != None:
            state_manager.current_state = BuilderState.CONNECT_AXIONITE_STATE
            return True

        dest = self.find_destination(ct)
        source = self.find_source(ct)
        if dest == None:
            return False
        
        if source == None: #and (self.prev_source == None or ct.get_stored_resource(self.prev_source) != ResourceType.RAW_AXIONITE):
            return False
        build_pos = self.get_build_pos(ct, source)
        if build_pos == None:
            return False
        self.build_pos = build_pos
        self.dest = dest
        print("build pos: ", self.build_pos)
        print("dest pos: ", self.dest)
        if ct.get_entity_type(source) in [EntityType.CONVEYOR, EntityType.SPLITTER]:
            self.prev_dir = ct.get_direction(source)
        else:
            self.prev_dir = None
        state_manager.current_state = BuilderState.CONNECT_AXIONITE_STATE
        self.prev_source = source
        return True

    def find_destination(self, ct):
        mm: MapManager = self.brain.map_manager
        potential_destinations = list(mm.seen_adjacent_harvester_conveyor_positions) + list(mm.seen_no_axionite_foundry_positions)
        best_pos = None
        best_dist = float('inf')
        for pos in potential_destinations:
            dist = ct.get_position().distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
        return best_pos
    
    def find_source(self, ct):
        mm: MapManager = self.brain.map_manager
        best_id = None
        best_pos = None
        best_dist = float('inf')
        for id in mm.nearby_ally_open_axionite_harvester_ids + mm.nearby_ally_open_raw_axionite_conveyor_ids + mm.nearby_ally_open_raw_axionite_bridge_ids:
            pos = ct.get_position(id)
            dist = ct.get_position().distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
                best_id = id
        return best_id
    
    def get_build_pos(self, ct: Controller, eid):
        unit_type = ct.get_entity_type(eid)
        if unit_type == EntityType.HARVESTER:
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
    