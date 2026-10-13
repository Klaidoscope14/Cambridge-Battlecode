from cambc import Controller, EntityType, Position, ResourceType, Environment
from helpers.directions import CARDINAL
from map.map_manager import MapManager
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from debug.profiling import cputimer

class FixFoundry:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.replace_pos = None

    @cputimer
    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        print("clog pos: ", self.replace_pos)
        if abs(my_pos.x - self.replace_pos.x) <= 1 and abs(my_pos.y - self.replace_pos.y) <= 1:
            if ct.get_global_resources()[0] > ct.get_foundry_cost()[0] and ct.get_action_cooldown() == 0:
                if ct.can_destroy(self.replace_pos):
                    ct.destroy(self.replace_pos)
        else:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.replace_pos)

    def determine_fix_foundry_state(self, ct, state_manager):
        replace_pos = self.find_clogging_foundry(ct)
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
        return None