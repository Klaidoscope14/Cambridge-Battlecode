from cambc import Controller, EntityType, Position, ResourceType, Environment
from helpers.directions import CARDINAL
from map.map_manager import MapManager
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from debug.profiling import cputimer

class FixFoundryState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.replace_pos = None
        self.is_standable = False

    @cputimer
    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        print("clog pos: ", self.replace_pos)
        if abs(my_pos.x - self.replace_pos.x) <= 1 and abs(my_pos.y - self.replace_pos.y) <= 1 and self.is_standable == False:
            #if ct.get_global_resources()[0] > ct.get_foundry_cost()[0] and ct.get_action_cooldown() == 0:
                if ct.can_destroy(self.replace_pos):
                    ct.destroy(self.replace_pos)
                    if ct.can_build_road(self.replace_pos):
                        ct.build_road(self.replace_pos)
        elif my_pos == self.replace_pos and self.is_standable == True:
                if ct.can_destroy(self.replace_pos):
                    ct.destroy(self.replace_pos)
                    if ct.can_build_road(self.replace_pos):
                        ct.build_road(self.replace_pos)
        
        common_path(ct, self.brain.map_manager, self.brain.pathing, self.replace_pos)

    def determine(self, ct, state_manager):
        replace_pos = self.find_clogging_path(ct)
        if replace_pos is not None:
            self.is_standable = True
        if replace_pos == None:
            replace_pos = self.find_clogging_foundry(ct)
            self.is_standable = False
        if replace_pos == None:
            return False
        self.replace_pos = replace_pos
        state_manager.current_state = BuilderState.FIX_FOUNDRY_STATE
        return True

    def find_clogging_foundry(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        for id in mm.nearby_ally_foundry_ids:
            pos = ct.get_position(id)
            for d in CARDINAL:
                adj_pos = pos.add(d)
                if not in_bounds(ct, adj_pos) or my_pos.distance_squared(adj_pos) > ct.get_vision_radius_sq():
                    continue
                adj_id = ct.get_tile_building_id(adj_pos)
                if adj_id is not None and ct.get_entity_type(adj_id) == EntityType.CONVEYOR:
                    if ct.get_direction(adj_id) == d.opposite() and ct.get_stored_resource(adj_id) == ResourceType.REFINED_AXIONITE:
                        return pos
        
        for tile_id in mm.nearby_bridge_to_foundry_ids:
            target = ct.get_bridge_target(tile_id)
            target_id = ct.get_tile_building_id(target)
            if target_id != None and ct.get_entity_type(target_id) == EntityType.FOUNDRY and ct.get_stored_resource(tile_id) == ResourceType.REFINED_AXIONITE:
                return ct.get_position(tile_id)
        return None
    
    def find_clogging_path(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()

        best_pos = None
        best_dist = float('inf')
        for id in mm.nearby_ally_clogged_bridge_ids + mm.nearby_ally_clogged_conveyor_ids:
            dist = my_pos.distance_squared(ct.get_position(id))
            if dist < best_dist:
                best_dist = dist
                best_pos = ct.get_position(id)
        return best_pos

