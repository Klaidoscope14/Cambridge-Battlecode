from cambc import Controller, Position, EntityType
from map.map_manager import MapManager
from nav.pathing import Pathing
from nav.movement import move_road_if_empty
from nav.passability import passability_default
from states.builder_state import BuilderState

ENEMY_CHAIN_TYPES = [EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER]

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
        my_team = ct.get_team()
        ally_direct = None   # ally belt feeding directly into the enemy turret (highest priority)
        ally_chain = None    # ally belt feeding into enemy chain infrastructure
        enemy_direct = None  # enemy belt feeding directly into the enemy turret

        for id in mm.nearby_entity_ids:
            unit_type = ct.get_entity_type(id)
            if unit_type not in [EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.SPLITTER]:
                continue
            pos = ct.get_position(id)
            is_ally = ct.get_team(id) == my_team
            is_turret_feeder = False
            is_chain_feeder = False

            if unit_type == EntityType.BRIDGE:
                target = ct.get_bridge_target(id)
                if target == en_tur_pos:
                    is_turret_feeder = True
                elif is_ally:
                    target_building = mm.get_building(target)
                    if target_building is not None and target_building.team != my_team:
                        if target_building.entity_type in ENEMY_CHAIN_TYPES:
                            is_chain_feeder = True

            elif unit_type == EntityType.CONVEYOR:
                if abs(pos.x - en_tur_pos.x) <= 1 and abs(pos.y - en_tur_pos.y) <= 1:
                    if ct.get_direction(id) == pos.direction_to(en_tur_pos):
                        is_turret_feeder = True
                elif is_ally:
                    next_pos = pos.add(ct.get_direction(id))
                    if 0 <= next_pos.x < mm.width and 0 <= next_pos.y < mm.height:
                        next_building = mm.get_building(next_pos)
                        if next_building is not None and next_building.team != my_team:
                            if next_building.entity_type in ENEMY_CHAIN_TYPES:
                                is_chain_feeder = True

            elif unit_type == EntityType.SPLITTER:
                if is_ally:
                    next_pos = pos.add(ct.get_direction(id))
                    if 0 <= next_pos.x < mm.width and 0 <= next_pos.y < mm.height:
                        next_building = mm.get_building(next_pos)
                        if next_building is not None and next_building.team != my_team:
                            if next_building.entity_type in ENEMY_CHAIN_TYPES:
                                is_chain_feeder = True

            if is_turret_feeder:
                if is_ally:
                    ally_direct = pos
                    break  # ally destroy is cheapest, take it immediately
                elif enemy_direct is None:
                    bot = mm.get_bot(pos)
                    if bot is None or bot.id == ct.get_id():
                        enemy_direct = pos
            elif is_chain_feeder and ally_chain is None:
                ally_chain = pos

        return ally_direct or ally_chain or enemy_direct

    def execute(self, ct: Controller):
        print("ammo_source: ", self.ammo_source_pos)
        print("turret: ", self.enemy_turret_pos)
        my_pos: Position = ct.get_position()
        if abs(my_pos.x - self.ammo_source_pos.x) <= 1 and abs(my_pos.y - self.ammo_source_pos.y) <= 1:
            mm: MapManager = self.brain.map_manager
            source_building = mm.get_building(self.ammo_source_pos)
            if source_building is not None and source_building.team == ct.get_team():
                if ct.can_destroy(self.ammo_source_pos):
                    ct.destroy(self.ammo_source_pos)
        else:
            self.pathing.path_to(
                ct,
                self.brain.map_manager,
                my_pos,
                self.ammo_source_pos,
                move_road_if_empty,
                passability_default
            )
            if ct.can_fire(self.ammo_source_pos):
                ct.fire(self.ammo_source_pos)
    
    def determine(self, ct, state_manager):
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
        
        

