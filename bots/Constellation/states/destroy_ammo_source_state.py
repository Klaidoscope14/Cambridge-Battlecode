from cambc import Controller, Position, EntityType
from vision.vision_manager import VisionManager
from map.map_manager import MapManager
from nav.pathing import Pathing
from nav.movement import move_road_if_empty
from nav.passability import passability_default
from states.builder_state import BuilderState

class DestroyAmmoSourceState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.enemy_turret_pos: Position | None = None
        self.ammo_source_pos: Position | None = None
        self.pathing: Pathing = brain.pathing

    def identify_enemy_turret(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        nearby_entity_ids = mm.nearby_entity_ids
        closest_turret_pos = None
        my_pos = ct.get_position()
        best_dist = float('inf')
        turret_types = [EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER]
        for id in nearby_entity_ids:
            unit_type = ct.get_entity_type(id)
            if unit_type not in turret_types:
                continue
            if ct.get_team(id) == ct.get_team():
                continue
            pos = ct.get_position(id)
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                closest_turret_pos = pos
        return closest_turret_pos
    
    # CALL THIS AND SET AMMO SOURCE TO DESTROY POS BEFORE CALLING EXECUTE IN STATE_MANAGER
    def identify_source_destroy(self, ct: Controller, en_tur_pos: Position):
        mm: MapManager = self.brain.map_manager
        nearby_entity_ids = mm.nearby_entity_ids
        ally_pos = None
        enemy_pos = None
        for id in nearby_entity_ids:
            unit_type = ct.get_entity_type(id)
            pos = ct.get_position(id)
            is_match = False
            if unit_type == EntityType.BRIDGE:
                if ct.get_bridge_target(id) == en_tur_pos:
                    is_match = True
            elif unit_type == EntityType.CONVEYOR:
                # if conveyor is next to turret and points towards it
                if abs(pos.x - en_tur_pos.x) <= 1 and abs(pos.y - en_tur_pos.y) <= 1:
                    if ct.get_direction(id) == pos.direction_to(en_tur_pos):
                        is_match = True
            if is_match:
                if ct.get_team(ct.get_tile_building_id(pos)) == ct.get_team():
                    ally_pos = pos
                    break  # ally destroy is cheapest, take it immediately
                elif enemy_pos is None:
                    enemy_pos = pos
        return ally_pos if ally_pos is not None else enemy_pos

    def execute(self, ct: Controller):
        print("ammo_source: ", self.ammo_source_pos)
        print("turret: ", self.enemy_turret_pos)
        my_pos: Position = ct.get_position()
        if abs(my_pos.x - self.ammo_source_pos.x) <= 1 and abs(my_pos.y - self.ammo_source_pos.y) <= 1:
            if ct.get_team(ct.get_tile_building_id(self.ammo_source_pos)) == ct.get_team():
                if ct.can_destroy(self.ammo_source_pos):
                    ct.destroy(self.ammo_source_pos)
            else:
                if ct.can_fire(self.ammo_source_pos):
                    ct.fire(self.ammo_source_pos)
        else:
            self.pathing.path_to(
                ct,
                self.brain.map_manager,
                my_pos,
                self.ammo_source_pos,
                move_road_if_empty,
                passability_default
            )
    
    def determine_destroy_ammo_source_state(self, ct, state_manager):
        enemy_turret: Position | None = self.identify_enemy_turret(ct)
        if enemy_turret == None:
            return False
        ammo_source: Position | None = self.identify_source_destroy(ct, enemy_turret)
        if ammo_source == None:
            return False
        self.ammo_source_pos = ammo_source
        self.enemy_turret_pos = enemy_turret
        state_manager.current_state = BuilderState.DESTROY_AMMO_SOURCE
        return True
        
        
