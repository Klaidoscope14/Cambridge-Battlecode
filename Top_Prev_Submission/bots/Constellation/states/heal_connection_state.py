from cambc import Controller, EntityType
from debug.profiling import cputimer
from map.map_manager import MapManager
from nav.common import common_path
from states.builder_state import BuilderState
class HealConnectionState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.heal_pos = None
    def get_nearest_damaged_connection(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        dist = float('inf')
        best_bridge = None
        my_pos = ct.get_position()
        # find nearest damaged ally path that doesn't have an ally builderbot on it already
        nearby_connection_ids = mm.nearby_ally_bridge_ids + mm.nearby_ally_conveyor_ids + mm.nearby_ally_splitter_ids + mm.nearby_ally_turret_ids
        for id in nearby_connection_ids:
            bbot_id = ct.get_tile_builder_bot_id(ct.get_position(id))
            if bbot_id != None:
                if ct.get_team(bbot_id) == ct.get_team():
                    continue

            if ct.get_hp(id) <= ct.get_max_hp(id) - 4:
                d = my_pos.distance_squared(ct.get_position(id))
                if d < dist:
                    dist = d
                    best_bridge = ct.get_position(id)

        if best_bridge is not None:
            return best_bridge

        # secondary: roads — any damage warrants healing
        for id in mm.nearby_ally_road_ids:
            bbot_id = ct.get_tile_builder_bot_id(ct.get_position(id))
            if bbot_id != None:
                if ct.get_team(bbot_id) == ct.get_team():
                    continue

            if ct.get_hp(id) < ct.get_max_hp(id):
                d = my_pos.distance_squared(ct.get_position(id))
                if d < dist:
                    dist = d
                    best_bridge = ct.get_position(id)

        return best_bridge
    def execute(self, ct: Controller):
        if self.heal_pos == None:
            return
        # if not on the healing pos, move to it
        if ct.get_position() != self.heal_pos:
            mm: MapManager = self.brain.map_manager
            common_path(ct, mm, self.brain.pathing, self.heal_pos)
        # if can heal the bridge, heal
        if ct.can_heal(self.heal_pos):
            ct.heal(self.heal_pos)
            self.heal_pos = None

    @cputimer
    def determine_heal_connection_state(self, ct, state_manager):
        heal_pos = self.get_nearest_damaged_connection(ct)
        if heal_pos == None:
            return False
        self.heal_pos = heal_pos
        my_dist = ct.get_position().distance_squared(heal_pos)
        for id in self.brain.map_manager.nearby_ally_bot_ids:
            if ct.get_position(id).distance_squared(heal_pos) < my_dist:
                return False
        state_manager.current_state = BuilderState.HEAL_CONNECTION
        return True