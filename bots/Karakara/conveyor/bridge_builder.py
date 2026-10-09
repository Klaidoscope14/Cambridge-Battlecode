from cambc import Controller, EntityType, Environment, Position, Direction, ResourceType
from roles.builder.helpers import in_bounds
from helpers.directions import CARDINAL
from vision.storage_tracker import StorageTracker
from map.map_manager import MapManager

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL]#, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.CORE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
BRIDGE_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]

class BridgeBuilder:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain

    def connect_and_move(self, ct: Controller, source: Position, dest: Position, isolate=False):
        my_pos = ct.get_position()
        build_pos = source
        move_dir = my_pos.direction_to(build_pos)
        tile_id = ct.get_tile_building_id(build_pos)
        # if wall or non buildable block on the location
        if ct.get_tile_env(build_pos) in BLOCKING_ENVIRONMENT_TYPES:
            # pass
            pass
        # if empty tile
        elif tile_id == None:
            if self.build_avoid_harvesters_bridge(ct, build_pos, dest, isolate) and ct.can_move(move_dir):
                ct.move(move_dir)

        # if we need to break an enemy tile on the building pos first
        elif ct.get_team(tile_id) != ct.get_team() and ct.get_entity_type(tile_id) in ENEMY_FIREABLE_TYPES:
            if my_pos != build_pos and ct.can_move(move_dir):
                ct.move(move_dir)
            if ct.can_fire(build_pos):
                ct.fire(build_pos)
            self.build_avoid_harvesters_bridge(ct, build_pos, dest, isolate)

        # if we need to destroy an ally tile on the building post first
        elif ct.get_team(tile_id) == ct.get_team() and ct.get_entity_type(tile_id) in ALLY_DESTROYABLE_TYPES:
            if ct.can_destroy(build_pos):
                ct.destroy(build_pos)
            if self.build_avoid_harvesters_bridge(ct, build_pos, dest, isolate) and ct.can_move(move_dir):
                ct.move(move_dir)
        print("build pos: ", build_pos)

    def build_avoid_harvesters_bridge(self, ct: Controller, build_pos, dest, isolate):
        target = self.get_bridge_target(ct, build_pos, dest, isolate)
        if ct.can_build_bridge(build_pos, target):
            ct.build_bridge(build_pos, target)
            return True
        return False

    def get_bridge_target(self, ct: Controller, build_pos, dest, isolate):
        mm: MapManager = self.brain.map_manager
        best_pos = None
        best_dist = float('inf')
        my_pos = ct.get_position()
        for pos in mm.nearby_positions:
            if my_pos.distance_squared(pos) > ct.get_vision_radius_sq():
                continue
            id = ct.get_tile_building_id(pos)

            if build_pos.distance_squared(pos) > 9:
                continue
            if ct.get_tile_env(pos) in BLOCKING_ENVIRONMENT_TYPES:
                continue
            
            if pos == dest:
                return pos
            
            if id != None:
                if ct.get_entity_type(id) in ALLY_BLOCKING_TYPES:
                    continue
                if isolate and ct.get_entity_type(id) in [EntityType.CONVEYOR, EntityType.BRIDGE]:
                    continue
                if ct.get_entity_type(id) in [EntityType.BRIDGE, EntityType.CONVEYOR]:
                    if ct.get_stored_resource(id) != ResourceType.RAW_AXIONITE:
                        continue
                if self.is_adj_to_harvester_or_foundry(ct, pos):
                    continue
            else:
                if self.is_adj_to_harvester_or_foundry(ct, pos):
                    continue
            
            dist = dest.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
        return best_pos
            
    def is_adj_to_harvester_or_foundry(self, ct: Controller, pos):
        for d in CARDINAL:
            adj_pos = pos.add(d)
            #if can't see adj tiles, we should assume is adj to harvester or foundry
            if not in_bounds(ct, adj_pos) or ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq():
                return True
            
            adj_id = ct.get_tile_building_id(adj_pos)
            if adj_id is not None and ct.get_entity_type(adj_id) in [EntityType.HARVESTER, EntityType.FOUNDRY]:
                return True
        return False
            
