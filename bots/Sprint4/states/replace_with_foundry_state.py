from cambc import Controller, EntityType, Position, ResourceType, Environment
from helpers.directions import CARDINAL, DIRECTIONS
from map.map_manager import MapManager
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from debug.profiling import cputimer

class ReplaceWithFoundryState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.replace_pos = None

    @cputimer
    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        print(self.replace_pos)
        if abs(my_pos.x - self.replace_pos.x) <= 1 and abs(my_pos.y - self.replace_pos.y) <= 1:
            # simple move off it if i'm standing on build pos
            if my_pos == self.replace_pos:
                for d in CARDINAL:
                    if ct.can_move(d):
                        ct.move(d)
            if ct.get_global_resources()[0] > ct.get_foundry_cost()[0] and ct.get_action_cooldown() == 0 and ct.get_tile_builder_bot_id(self.replace_pos) == None:
                if ct.can_destroy(self.replace_pos):
                    ct.destroy(self.replace_pos)
                if ct.can_build_foundry(self.replace_pos):
                    ct.build_foundry(self.replace_pos)
        else:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.replace_pos)

    def determine(self, ct, state_manager):
        replace_pos = self.find_replace_location(ct)
        if replace_pos == None:
            return False
        self.replace_pos = replace_pos
        state_manager.current_state = BuilderState.REPLACE_WITH_FOUNDRY_STATE
        return True

    def find_replace_location(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        best_pos = None
        best_dist = float('inf')
        already_has_foundry = False

        for id in mm.nearby_ally_axionite_harvester_ids:
            pos = ct.get_position(id)
            for d in CARDINAL:
                adj_pos = pos.add(d)
                if not in_bounds(ct, adj_pos) or ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq():
                    continue
                adj_id = ct.get_tile_building_id(adj_pos)
                if adj_id != None and ct.get_entity_type(adj_id) == EntityType.FOUNDRY:
                    already_has_foundry = True
            if not already_has_foundry:
                for d in CARDINAL:
                    adj_pos = pos.add(d)
                    if not in_bounds(ct, adj_pos) or ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq():
                        continue
                    adj_id = ct.get_tile_building_id(adj_pos)
                    if adj_id != None and ct.get_entity_type(adj_id) in [EntityType.CONVEYOR]:
                        if ct.get_stored_resource(adj_id) == ResourceType.TITANIUM:
                            dist = ct.get_position().distance_squared(adj_pos)
                            if dist < best_dist:
                                best_dist = dist
                                best_pos = adj_pos

                if adj_id != None and ct.get_entity_type(adj_id) in [EntityType.BRIDGE]:
                    bridge_pos = ct.get_position(adj_id)
                    free = False
                    for d in CARDINAL:
                        adj_bridge_pos = bridge_pos.add(d)
                        if not in_bounds(ct, adj_bridge_pos) or ct.get_position().distance_squared(adj_bridge_pos) > ct.get_vision_radius_sq():
                            continue
                        adj_bridge_eid = ct.get_tile_building_id(adj_bridge_pos)
                        if ct.get_tile_env(adj_bridge_pos) in [Environment.ORE_TITANIUM, Environment.ORE_AXIONITE]:
                            free = True
                        if adj_bridge_eid == None:
                            free = True
                        elif ct.get_team() == ct.get_team(adj_bridge_eid) and ct.get_entity_type(adj_bridge_eid) in [EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.MARKER, EntityType.ROAD, EntityType.ARMOURED_CONVEYOR]:
                            free = True
                        elif ct.get_team() != ct.get_team(adj_bridge_eid) and ct.get_entity_type(adj_bridge_eid) in [EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.MARKER, EntityType.ROAD]:
                            free = True
                    if ct.get_stored_resource(adj_id) == ResourceType.TITANIUM and free:
                        dist = ct.get_position().distance_squared(adj_pos)
                        if dist < best_dist:
                            best_dist = dist
                            best_pos = adj_pos

        for id in mm.nearby_adjacent_harvester_conveyor_positions:
            titanium_input = False
            axionite_input = False
            pos = ct.get_position(id)

            for d in CARDINAL:

                adj_pos = pos.add(d)
                
                if not in_bounds(ct, adj_pos) or ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq():
                    continue
                adj_id = ct.get_tile_building_id(adj_pos)

                if adj_id != None:
                    if ct.get_entity_type(adj_id) == EntityType.HARVESTER:
                        if ct.get_tile_env(adj_pos) == Environment.ORE_TITANIUM:
                            titanium_input = True
                        elif ct.get_tile_env(adj_pos) == Environment.ORE_AXIONITE:
                            axionite_input = True
                    
                    if ct.get_entity_type(adj_id) in [EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR]:
                        if ct.get_direction(adj_id) == d.opposite():
                            # if ct.get_stored_resource(adj_id) == ResourceType.TITANIUM:
                            #     titanium_input = True
                            if ct.get_stored_resource(adj_id) == ResourceType.RAW_AXIONITE:
                                axionite_input = True

            for bridge_id in mm.nearby_ally_raw_axionite_bridge_ids:
                if ct.get_bridge_target(bridge_id) == pos:
                    axionite_input = True
            # maybe add a check for titanium bridge ids here too
            if titanium_input and axionite_input:
                dist = ct.get_position().distance_squared(pos)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = pos
        return best_pos
                        

