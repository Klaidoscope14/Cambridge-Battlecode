"""Builder brain: scan, state machine, opportunistic, debug."""
from cambc import EntityType, Environment, Position
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
        # Share the same StorageTracker instance with MapManager so anything
        # that only has a MapManager (e.g. connectors, A*) can query storage
        # state without the brain passing it through explicitly.
        self.map_manager.storage_tracker = self.storage_tracker
        self.damage_tracker = DamageTracker(ct)
        self.launcher_tracker = LauncherTracker(ct)
        self.symmetry_manager = SymmetryManager(ct)
        self.pathing = Pathing(ct, self.launcher_tracker)
        self.connector = Connector(ct, self.map_manager)
        self.ally_core_pos = _ally_core_on_spawn(ct)
        self.spawn_location = ct.get_position()
        self.spawn_round = ct.get_current_round()
        self.harvesters_built = 0

        self.last_pos: Position | None = None
        self.was_launched: bool = False

        # THIS IS LAST
        self.state_manager = StateManager(self, ct)

    def run(self, ct: Controller) -> None:
        print("TITANIUM: ", ct.get_global_resources()[0])

        self.map_manager.update(ct)
        self.storage_tracker.update(ct, self.map_manager)
        self.damage_tracker.update(ct)
        self.launcher_tracker.update(ct, self.map_manager)
        self.pathing.update(ct, self.map_manager, passability_default)

        self.check_if_launched(ct)

        self.state_manager.determine_state(ct)
        self.state_manager.execute_state(ct)

        self.build_road_next_to_harvester(ct)
        self.heal_if_needed(ct)
        self.build_road_near_belt(ct)
        self.build_road_near_ally_core(ct)
        self.build_road_near_harvester(ct)
        self.symmetry_manager.update(self.map_manager)
        self.idle_expand(ct)

    def get_enemy_core_pos(self) -> Position | None:
        if self.ally_core_pos is None:
            return None
        if self.symmetry_manager.is_cracked():
            return self.symmetry_manager.reflect(self.ally_core_pos)
        return None

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

    def idle_expand(self, ct: Controller) -> None:
        """When not actively pathing, grow _reachable via flood-fill."""
        if self.pathing.current_target is not None:
            return
        self.pathing.idle_expand(ct, self.map_manager, passability_default)

    def build_road_next_to_harvester(self, ct: Controller):
        if ct.get_action_cooldown() > 0:
            return
        if ct.get_global_resources()[0] <= ct.get_conveyor_cost()[0] * 2:
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

    def build_road_near_belt(self, ct: Controller):
        if ct.get_action_cooldown() > 0:
            return
        if ct.get_global_resources()[0] <= ct.get_conveyor_cost()[0] * 2:
            return
        my_pos = ct.get_position()
        for d in DIRECTIONS:
            t_pos = my_pos.add(d)
            if not in_bounds(ct, t_pos):
                continue
            if not ct.can_build_road(t_pos):
                continue
            for nd in DIRECTIONS:
                n_pos = t_pos.add(nd)
                if not in_bounds(ct, n_pos):
                    continue
                n_bid = ct.get_tile_building_id(n_pos)
                if n_bid is None:
                    continue
                n_etype = ct.get_entity_type(n_bid)
                if n_etype == EntityType.CONVEYOR or n_etype == EntityType.BRIDGE:
                    ct.build_road(t_pos)
                    return

    def build_road_near_ally_core(self, ct: Controller):
        if ct.get_action_cooldown() > 0:
            return
        if ct.get_global_resources()[0] <= ct.get_conveyor_cost()[0] * 2:
            return
        if self.ally_core_pos is None:
            return
        my_pos = ct.get_position()
        dx = abs(my_pos.x - self.ally_core_pos.x)
        dy = abs(my_pos.y - self.ally_core_pos.y)
        if max(dx, dy) > 2:
            return
        for d in DIRECTIONS:
            t_pos = my_pos.add(d)
            if not in_bounds(ct, t_pos):
                continue
            if ct.can_build_road(t_pos):
                ct.build_road(t_pos)
                return

    def build_road_near_harvester(self, ct: Controller):
        if ct.get_action_cooldown() > 0:
            return
        if ct.get_global_resources()[0] <= ct.get_conveyor_cost()[0] * 2:
            return
        if not self.map_manager.nearby_ally_harvester_ids:
            return
        my_pos = ct.get_position()
        closest = None
        for hid in self.map_manager.nearby_ally_harvester_ids:
            h_pos = self.map_manager.id_to_pos.get(hid)
            if h_pos is None:
                continue
            dist = max(abs(my_pos.x - h_pos.x), abs(my_pos.y - h_pos.y))
            if closest is None or dist < closest:
                closest = dist
        if closest is None or closest > 1:
            return
        for d in DIRECTIONS:
            t_pos = my_pos.add(d)
            if not in_bounds(ct, t_pos):
                continue
            if ct.can_build_road(t_pos):
                ct.build_road(t_pos)
                return

    def check_if_launched(self, ct: Controller):
        if self.was_launched: return
        current_pos = ct.get_position()
        if self.last_pos is not None:
            dx = abs(current_pos.x - self.last_pos.x)
            dy = abs(current_pos.y - self.last_pos.y)
            if max(dx, dy) > 1:
                self.was_launched = True
                print(f"BuilderBrain: detected launch! {self.last_pos} -> {current_pos}")
        self.last_pos = current_pos

def _ally_core_on_spawn(ct) -> Position:
    ids = ct.get_nearby_entities()
    for id in ids:
        if ct.get_entity_type(id) == EntityType.CORE:
            return ct.get_position(id)
    raise Exception("Core not found on spawn")
