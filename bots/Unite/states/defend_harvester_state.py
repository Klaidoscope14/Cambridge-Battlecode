from cambc import Controller, Position, EntityType
from vision.vision_manager import VisionManager
from map.map_manager import MapManager
from nav.pathing import Pathing
from nav.movement import move_road_if_empty
from nav.passability import passability_default
class DefendState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.pathing: Pathing = brain.pathing
        self.ally_core_pos = brain.map_manager.ally_core_pos
        self.move_towards_core = True
        self.claim_harvester = False
        self.current_bridge_pos = None
        self.traverse_out = True
        self.idx = 0
    def _find_closest_bridge(self, ct: Controller) -> Position | None:
        my_pos = ct.get_position()
        mm: MapManager = self.brain.map_manager
        best_pos = None
        best_dist = float("inf")
        for id in mm.nearby_entity_ids:
            if ct.get_team(id) != ct.get_team():
                continue
            if ct.get_entity_type(id) != EntityType.BRIDGE:
                continue
            pos = ct.get_position(id)
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
        return best_pos
    
    def execute(self, ct: Controller):
        vm: VisionManager = self.brain.vision_manager
        harvester_pos = vm._harvesters
        print(harvester_pos)
        if not harvester_pos:
            return 
        cur_har_pos = harvester_pos[self.idx]
        my_pos = ct.get_position()
        if self.traverse_out:
            self.pathing.path_to(
                ct,
                self.brain.map_manager,
                my_pos,
                cur_har_pos,
                move_road_if_empty,
                passability_default
            )
            my_pos = ct.get_position()
            if abs(my_pos.x - cur_har_pos.x) <= 1 and abs(my_pos.y - cur_har_pos.y) <= 1:
                self.idx += 1
                if self.idx >= len(harvester_pos):
                    self.idx = 0
                self.traverse_out = False
        else:
            self.pathing.path_to(
                ct,
                self.brain.map_manager,
                my_pos,
                self.ally_core_pos,
                move_road_if_empty,
                passability_default
            )
            my_pos = ct.get_position()
            if abs(my_pos.x - self.ally_core_pos.x) <= 1 and abs(my_pos.y - self.ally_core_pos.y) <= 1:
                self.traverse_out = True

    # def ex_execute(self, ct: Controller):
    #     if self.ally_core_pos == None or self.current_bridge_pos == None:
    #         return
    #     my_pos = ct.get_position()
    #     mm: MapManager = self.brain.map_manager
    #     print(self.traverse_out)
    #     if self.traverse_out:
    #         if abs(my_pos.x - self.current_bridge_pos.x) <= 1 and abs(my_pos.y - self.current_bridge_pos.y) <= 1:
    #             is_end = True
    #             for id in mm.nearby_entity_ids:
    #                 if ct.get_team(id) != ct.get_team():
    #                     continue
    #                 unit_type = ct.get_entity_type(id)
    #                 if unit_type == EntityType.BRIDGE:
    #                     if ct.get_bridge_target(id) == self.current_bridge_pos:
    #                         is_end = False
    #                         self.current_bridge_pos = ct.get_position(id)
    #                         break
    #             if is_end:
    #                 self.traverse_out = False
    #                 return
    #         self.pathing.path_to(
    #             ct,
    #             self.brain.map_manager,
    #             my_pos,
    #             self.current_bridge_pos,
    #             move_road_if_empty,
    #             passability_default
    #         )
    #     else:
    #         self.pathing.path_to(
    #             ct,
    #             self.brain.map_manager,
    #             my_pos,
    #             self.ally_core_pos,
    #             move_road_if_empty,
    #             passability_default
    #         )
    #         my_pos = ct.get_position()
    #         if abs(my_pos.x - self.ally_core_pos.x) <= 1 and abs(my_pos.y - self.ally_core_pos.y) <= 1:
    #             self.traverse_out = True