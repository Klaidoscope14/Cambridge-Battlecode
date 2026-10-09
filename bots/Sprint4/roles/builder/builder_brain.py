"""Builder brain: scan, state machine, opportunistic, debug."""
from cambc import EntityType, Environment, Position
from helpers.marker_expiry import remove_expired_markers
from conveyor.connector import Connector
from helpers.directions import CARDINAL, OFFSET_TO_DIRECTION, DIRECTIONS

from roles.builder.helpers import build_conveyor, build_harvester, build_road, in_bounds

from map.map_manager import MapManager
from vision.storage_tracker import StorageTracker
from vision.damage_tracker import DamageTracker
from vision.launcher_tracker import LauncherTracker
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
        self.damage_tracker = DamageTracker(ct)
        self.launcher_tracker = LauncherTracker(ct)
        self.symmetry_manager = SymmetryManager(ct)
        self.pathing = Pathing(ct, self.launcher_tracker)
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
        self.damage_tracker.update(ct)
        self.launcher_tracker.update(ct, self.map_manager)

        self.state_manager.determine_state(ct)
        self.state_manager.execute_state(ct)

        self.build_road_next_to_harvester(ct)
        self.heal_if_needed(ct)
        self.symmetry_manager.update(self.map_manager)
        self.idle_expand_toward_core(ct)

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

    def idle_expand_toward_core(self, ct: Controller) -> None:
        """When not actively pathing, expand A* toward our core to build reachable."""
        if self.pathing.current_target is not None:
            return
        if self.ally_core_pos is None:
            return
        self.pathing.idle_expand(
            ct, self.map_manager, ct.get_position(),
            self.ally_core_pos, passability_default,
        )

    def build_road_next_to_harvester(self, ct: Controller):
        if ct.get_action_cooldown() > 0:
            return
        my_pos = ct.get_position()
        for d in DIRECTIONS:
            h_pos = my_pos.add(d)
            if not in_bounds(ct, h_pos):
                continue
            tbid = ct.get_tile_building_id(h_pos)
            if tbid is None:
                continue
            etype = ct.get_entity_type(tbid)
            if etype != EntityType.HARVESTER:
                continue
            for cd in CARDINAL:
                t_pos = h_pos.add(cd)
                if not in_bounds(ct, t_pos):
                    continue
                dx = t_pos.x - my_pos.x
                dy = t_pos.y - my_pos.y
                if abs(dx) > 1 or abs(dy) > 1 or (dx == 0 and dy == 0):
                    continue
                t_tbid = ct.get_tile_building_id(t_pos)
                if t_tbid is not None:
                    continue
                if build_road(ct, t_pos):
                    return


def _ally_core_on_spawn(ct) -> Position:
    ids = ct.get_nearby_entities()
    for id in ids:
        if ct.get_entity_type(id) == EntityType.CORE:
            return ct.get_position(id)
    raise Exception("Core not found on spawn")