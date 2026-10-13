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
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.SPLITTER, EntityType.BRIDGE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
BRIDGE_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]


class ConnectAxioniteState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.source = None
        self.build_pos = None
        self.dest = None
        self.prev_dir = None
        self.path_builder = PathBuilder(ct, brain)
        #self.bridge_builder = BridgeBuilder(ct, brain)
    @cputimer
    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        print("build pos: ", self.build_pos)
        print("dest: ", self.dest)
        if self.build_pos == self.dest:
            self.prep_and_build_foundry(ct, self.build_pos)
        elif abs(my_pos.x - self.build_pos.x) <= 1 and abs(my_pos.y - self.build_pos.y) <= 1:
            #self.bridge_builder.connect_and_move(ct, self.build_pos, self.dest, False)
            self.path_builder.connect_and_move(ct, self.prev_dir, self.source, self.build_pos, self.dest, False, True)
            self.build_pos = None
            self.source = None
        else:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)
    
    def determine(self, ct: Controller, state_manager):
        dest = self.find_destination(ct)
        source = self.find_source(ct)
        if dest == None:
            return False
        
        if source == None: #and (self.prev_source == None or ct.get_stored_resource(self.prev_source) != ResourceType.RAW_AXIONITE):
            return False
        
        build_pos = self.get_build_pos(ct, source)
        if build_pos == None:
            return False
        
        self.source = source
        self.build_pos = build_pos
        self.dest = dest
        if ct.get_position().distance_squared(dest) < ct.get_vision_radius_sq() - 8:
            if ct.get_entity_type(ct.get_tile_building_id(dest)) == EntityType.HARVESTER:
                new_dest = self.find_foundry_build_pos(ct, ct.get_tile_building_id(dest))
            else:
                new_dest = self.get_build_pos(ct, ct.get_tile_building_id(dest))
            if new_dest is not None:
                self.dest = new_dest

        print("build pos: ", self.build_pos)
        print("dest pos: ", self.dest)
        if ct.get_entity_type(source) in [EntityType.CONVEYOR, EntityType.SPLITTER]:
            self.prev_dir = ct.get_direction(source)
        else:
            self.prev_dir = None
        state_manager.current_state = BuilderState.CONNECT_AXIONITE_STATE
        return True

    def find_destination(self, ct):
        mm: MapManager = self.brain.map_manager
        potential_destinations = list(mm.seen_ally_no_foundry_harvester_positions) + list(mm.seen_no_axionite_foundry_positions)
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
        elif unit_type == EntityType.FOUNDRY:
            return self.get_foundry_build_pos(ct, eid)
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
        my_pos = ct.get_position()
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
            dist = adj_pos.distance_squared(my_pos)
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
    
    def get_foundry_build_pos(self, ct, eid):
        return ct.get_position(eid)

    def prep_and_build_foundry(self, ct: Controller, build_pos):
        my_pos = ct.get_position()
        tile_id = ct.get_tile_building_id(build_pos)
        
        if tile_id is None:
            if ct.can_build_foundry(build_pos):
                ct.build_foundry(build_pos)
            return
        
        entity_type = ct.get_entity_type(tile_id)
        team = ct.get_team(tile_id)
        
        # enemy tile - move toward and fire
        if team != ct.get_team():
            move_dir = my_pos.direction_to(build_pos)
            if my_pos != build_pos and ct.can_move(move_dir):
                ct.move(move_dir)
            if ct.can_fire(build_pos):
                ct.fire(build_pos)
            return
        
        # ally destroyable tile - destroy then build
        if entity_type in ALLY_DESTROYABLE_TYPES:
            if ct.can_destroy(build_pos):
                ct.destroy(build_pos)
            if ct.can_build_foundry(build_pos):
                ct.build_foundry(build_pos)

    def find_foundry_build_pos(self, ct: Controller, eid):
        harv_pos = ct.get_position(eid)
        best_pos = None
        best_dist = float('inf')
        my_pos = ct.get_position()
        conveyor_pos = None

        for d in CARDINAL:
            adj_pos = harv_pos.add(d)
            if ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq() or not in_bounds(ct, adj_pos):
                continue
            adj_eid = ct.get_tile_building_id(adj_pos)
            adj_env = ct.get_tile_env(adj_pos)
            if adj_env == Environment.WALL:
                continue
            if adj_eid is not None:
                if ct.get_entity_type(adj_eid) == EntityType.CONVEYOR:
                    conveyor_pos = adj_pos
                    continue
                if ct.get_entity_type(adj_eid) in ALLY_BLOCKING_TYPES:
                    continue
            dist = adj_pos.distance_squared(my_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = adj_pos

        return conveyor_pos if conveyor_pos is not None else best_pos
    
    def is_card_adj(self, pos_a: Position, pos_b: Position) -> bool:
        return pos_a.distance_squared(pos_b) == 1