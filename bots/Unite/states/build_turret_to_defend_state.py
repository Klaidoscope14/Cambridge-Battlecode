from cambc import Controller, Position, EntityType, Direction
from vision.vision_manager import VisionManager
from map.map_manager import MapManager
from nav.pathing import Pathing
from nav.movement import move_road_if_empty
from nav.passability import passability_default
from helpers.directions import DIRECTIONS, CARDINAL
from roles.builder.helpers import in_bounds
class BuildTurretDefendState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.enemy_turret_pos: Position | None = None
        self.harvester_pos: Position | None = None
        self.build_pos: Position | None = None
        self.build_dir: Direction | None = None
        self.pathing: Pathing = brain.pathing
    def identify_enemy_turret(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        nearby_entity_ids = mm.nearby_entity_ids
        closest_turret_pos = None
        best_har_pos = None
        my_pos = ct.get_position()
        best_dist = float('inf')
        har_pos = None
        turret_types = [EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER]
        for id in nearby_entity_ids:
            unit_type = ct.get_entity_type(id)
            if unit_type not in turret_types:
                continue
            if ct.get_team(id) == ct.get_team():
                continue
            pos = ct.get_position(id)
            adj = False
            for d in CARDINAL:
                if my_pos.distance_squared(pos.add(d)) > ct.get_vision_radius_sq():
                    continue
                adj_id = ct.get_tile_building_id(pos.add(d))
                if adj_id == None:
                    continue
                if ct.get_entity_type(adj_id) == EntityType.HARVESTER:
                    adj = True
                    har_pos = ct.get_position(adj_id)
                    break
            if not adj:
                continue
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                closest_turret_pos = pos
                best_har_pos = har_pos
        return closest_turret_pos, best_har_pos
    def identify_build_pos(self, ct: Controller):
        turret_pos, harvester_pos = self.identify_enemy_turret(ct)
        if turret_pos == None or harvester_pos == None:
            return None
        build_locs = [harvester_pos.add(d) for d in CARDINAL]
        enemy_turret_id = ct.get_tile_building_id(turret_pos)
        if enemy_turret_id == None:
            return None
        enemy_turret_dir = ct.get_direction(enemy_turret_id)
        for pos in build_locs:
            if ct.get_position().distance_squared(pos) > ct.get_vision_radius_sq():
                continue
            if not in_bounds(ct, pos):
                continue
            if turret_pos.direction_to(pos) == enemy_turret_dir:
                continue
            if abs(turret_pos.x - pos.x) > 1 or abs(turret_pos.y - pos.y) > 1:
                continue
            return pos, pos.direction_to(turret_pos)
        return None
    def execute(self, ct: Controller):
        if self.build_pos == None or self.build_dir == None:
            return
        my_pos = ct.get_position()
        if abs(my_pos.x - self.build_pos.x) <= 1 or abs(my_pos.y - self.build_pos.y) <= 1:
            if ct.can_build_gunner(self.build_pos, self.build_dir):
                ct.build_gunner(self.build_pos, self.build_dir)
        else:
            pass