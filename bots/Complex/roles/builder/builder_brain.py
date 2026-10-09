"""Builder brain: scan, state machine, opportunistic, debug."""
from cambc import EntityType, Environment, Position
from helpers.marker_expiry import remove_expired_markers
from conveyor.connector import Connector
from helpers.directions import CARDINAL, OFFSET_TO_DIRECTION, DIRECTIONS

from roles.builder.helpers import build_conveyor, build_harvester, in_bounds

from map.map_manager import MapManager
from vision.storage_tracker import StorageTracker
from states.state_manager import BuilderState, StateManager

from nav.movement import *
from nav.pathing import Pathing
from nav.passability import passability_default

from .symmetry_manager import SymmetryManager



from debug.indicators import draw_blocked_tile, draw_move_direction


class BuilderBrain:
    def __init__(self, ct: Controller) -> None:
        self.map_manager = MapManager(ct)
        self.storage_tracker = StorageTracker(ct)
        self.symmetry_manager = SymmetryManager(ct)
        self.pathing = Pathing(ct)
        self.connector = Connector(ct, self.map_manager)
        self.ally_core_pos = _ally_core_on_spawn(ct)
        self.spawn_location = ct.get_position()
        self.spawn_round = ct.get_current_round()
        self.harvester_built = False

        # THIS IS LAST
        self.state_manager = StateManager(self, ct)

    def run(self, ct: Controller) -> None:
        remove_expired_markers(ct)
        self.map_manager.update(ct)
        self.storage_tracker.update(ct, self.map_manager)

        self.state_manager.determine_state(ct)
        self.state_manager.execute_state(ct)

        self.heal_if_needed(ct)
        self.fill_enemy_markers_with_roads(ct)
        self.symmetry_manager.update(self.map_manager)

        print(f"Symmetry is cracked: {self.symmetry_manager.is_cracked()}")
        print(f"Symmetry: {self.symmetry_manager.get_symmetry()}")

    def _is_closer_to_ally_core(self, pos: Position) -> bool:
        if self.ally_core_pos is None:
            return True

        enemy_core = self.symmetry_manager.reflect(self.ally_core_pos)
        if enemy_core is None:
            return True

        dist_ally  = abs(pos.x - self.ally_core_pos.x) + abs(pos.y - self.ally_core_pos.y)
        dist_enemy = abs(pos.x - enemy_core.x) + abs(pos.y - enemy_core.y)
        return dist_ally <= dist_enemy
    
    def heal_if_needed(self, ct: Controller) -> bool:
        if ct.get_hp() <= ct.get_max_hp() - 4:
            if ct.can_heal(ct.get_position()):
                ct.heal(ct.get_position()) 

    def fill_enemy_markers_with_roads(self, ct):
        if ct.get_road_cost() >= (2,0): return
        if ct.get_action_cooldown() > 0: return
        my_pos = ct.get_position()
        for d in DIRECTIONS:
            new_pos = my_pos.add(d)
            if not in_bounds(ct, new_pos): continue
            if ct.get_tile_building_id(new_pos) is None and ct.get_tile_env(new_pos) is Environment.EMPTY:
                build_road(ct, new_pos)
                return
            

def _ally_core_on_spawn(ct) -> Position:
    ids = ct.get_nearby_entities()
    for id in ids:
        if ct.get_entity_type(id) == EntityType.CORE:
            return ct.get_position(id)
    raise Exception("Core not found on spawn")