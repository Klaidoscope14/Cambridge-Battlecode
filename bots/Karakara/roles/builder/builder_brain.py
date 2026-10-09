"""Builder brain: scan, state machine, opportunistic, debug."""
from cambc import EntityType, Environment, GameConstants, Position
from conveyor.connector import Connector
from helpers.directions import CARDINAL, OFFSET_TO_DIRECTION, DIRECTIONS

from roles.builder.helpers import build_barrier, build_conveyor, build_harvester, build_road, in_bounds

from map.map_manager import MapManager
from vision.storage_tracker import StorageTracker
from vision.damage_tracker import DamageTracker
from vision.launcher_tracker import LauncherTracker
from vision.gunner_blocked_tracker import GunnerBlockedTracker
from states.state_manager import BuilderState, StateManager

from nav.movement import *
from nav.pathing import Pathing
from nav.reachable_set import ReachableSet

from .symmetry_manager import SymmetryManager

from debug.indicators import draw_blocked_tile, draw_move_direction

FILL_COOLDOWN_ROUNDS = 20


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
        self.gunner_blocked_tracker = GunnerBlockedTracker(ct)
        self.symmetry_manager = SymmetryManager(ct)
        self.reachable = ReachableSet(self.launcher_tracker)
        self.pathing = Pathing(ct, self.launcher_tracker, self.reachable)
        self.connector = Connector(ct, self.map_manager)
        self.ally_core_pos = _ally_core_on_spawn(ct)
        self.spawn_location = ct.get_position()
        self.spawn_round = ct.get_current_round()
        self.harvesters_built = 0
        self.connections_built = 0

        self.last_pos: Position | None = None
        self.was_launched: bool = False

        # Per-tile cooldown: tile -> round we last placed a fill there.
        # Shared by FillHarvesterConveyorState and the lightweight
        # build_conveyor_next_to_harvester opportunistic action.
        self.recently_filled: dict[tuple[int, int], int] = {}

        # THIS IS LAST
        self.state_manager = StateManager(self, ct)

    def run(self, ct: Controller) -> None:
        print("TITANIUM: ", ct.get_global_resources()[0])
        print(f"[CPU] start: {ct.get_cpu_time_elapsed()}")

        self.map_manager.update(ct)
        print(f"[CPU] map_manager.update: {ct.get_cpu_time_elapsed()}")
        self.storage_tracker.update(ct, self.map_manager)
        print(f"[CPU] storage_tracker.update: {ct.get_cpu_time_elapsed()}")
        self.damage_tracker.update(ct)
        print(f"[CPU] damage_tracker.update: {ct.get_cpu_time_elapsed()}")
        self.launcher_tracker.update(ct, self.map_manager)
        print(f"[CPU] launcher_tracker.update: {ct.get_cpu_time_elapsed()}")
        self.gunner_blocked_tracker.update(ct, self.map_manager)
        print(f"[CPU] gunner_blocked_tracker.update: {ct.get_cpu_time_elapsed()}")
        self.reachable.update(ct, self.map_manager)
        print(f"[CPU] reachable.update: {ct.get_cpu_time_elapsed()}")
        self.pathing.update(ct, self.map_manager)
        print(f"[CPU] pathing.update: {ct.get_cpu_time_elapsed()}")

        self.heal_if_needed(ct)
        print(f"[CPU] heal_if_needed: {ct.get_cpu_time_elapsed()}")
        self.check_if_launched(ct)
        print(f"[CPU] check_if_launched: {ct.get_cpu_time_elapsed()}")

        self.state_manager.determine_state(ct)
        print(f"[CPU] determine_state: {ct.get_cpu_time_elapsed()}")
        self.state_manager.execute_state(ct)
        print(f"[CPU] execute_state: {ct.get_cpu_time_elapsed()}")

        self.build_conveyor_next_to_harvester(ct)
        print(f"[CPU] build_conveyor_next_to_harvester: {ct.get_cpu_time_elapsed()}")
        self.heal_gunner(ct)
        print(f"[CPU] heal_gunner: {ct.get_cpu_time_elapsed()}")
        self.build_road_near_belt(ct)
        self.heal_extra(ct)
        print(f"[CPU] build_road_near_belt: {ct.get_cpu_time_elapsed()}")
        self.build_road_near_ally_core(ct)
        print(f"[CPU] build_road_near_ally_core: {ct.get_cpu_time_elapsed()}")
        self.build_road_on_enemy_marker(ct)
        print(f"[CPU] build_road_on_enemy_marker: {ct.get_cpu_time_elapsed()}")
        self.symmetry_manager.update(self.map_manager)
        print(f"[CPU] symmetry_manager.update: {ct.get_cpu_time_elapsed()}")
        self.idle_expand(ct)
        print(f"[CPU] idle_expand: {ct.get_cpu_time_elapsed()}")

        # End-of-turn deferred follow move: if FollowState requested a
        # follow during determine(), all other action logic has fallen
        # through — now actually path toward the enemy.
        self.state_manager.state_map[BuilderState.FOLLOW].finalize(ct)
        print(f"[CPU] follow.finalize: {ct.get_cpu_time_elapsed()}")

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
    
    def is_recently_filled(self, ct: Controller, pos: Position) -> bool:
        last = self.recently_filled.get((pos.x, pos.y))
        if last is None:
            return False
        return ct.get_current_round() - last < FILL_COOLDOWN_ROUNDS

    def mark_filled(self, ct: Controller, pos: Position) -> None:
        self.recently_filled[(pos.x, pos.y)] = ct.get_current_round()

    def heal_if_needed(self, ct: Controller) -> bool:
        if ct.get_hp() <= GameConstants.SENTINEL_DAMAGE + 10:
            if ct.can_heal(ct.get_position()):
                ct.heal(ct.get_position())      

    def heal_extra(self, ct: Controller) -> bool:
        if ct.get_hp() <= GameConstants.BUILDER_BOT_MAX_HP - 4:
            if ct.can_heal(ct.get_position()):
                ct.heal(ct.get_position())               

    def idle_expand(self, ct: Controller) -> None:
        self.reachable.idle_expand(ct, self.map_manager)

    def heal_gunner(self, ct: Controller) -> None:
        if ct.get_action_cooldown() > 0:
            return
        my_team = ct.get_team()
        my_pos = ct.get_position()

        gunner_target: Position | None = None
        fallback_target: Position | None = None

        for d in DIRECTIONS:
            adj = my_pos.add(d)
            if not in_bounds(ct, adj):
                continue
            if not ct.can_heal(adj):
                continue

            bid = ct.get_tile_building_id(adj)
            if bid is not None and ct.get_team(bid) == my_team:
                if ct.get_hp(bid) < ct.get_max_hp(bid):
                    if ct.get_entity_type(bid) == EntityType.GUNNER:
                        gunner_target = adj
                        break
                    if fallback_target is None:
                        fallback_target = adj
                    continue

            rid = ct.get_tile_builder_bot_id(adj)
            if rid is not None and ct.get_team(rid) == my_team:
                if ct.get_hp(rid) < ct.get_max_hp(rid):
                    if fallback_target is None:
                        fallback_target = adj

        target = gunner_target if gunner_target is not None else fallback_target
        if target is not None:
            ct.heal(target)

    def build_conveyor_next_to_harvester(self, ct: Controller):
        if ct.get_action_cooldown() > 0:
            return
        titanium = ct.get_global_resources()[0]
        can_afford_conveyor = titanium > ct.get_conveyor_cost()[0] * 2
        can_afford_road = titanium > ct.get_road_cost()[0]
        if not can_afford_conveyor and not can_afford_road:
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
            is_enemy_harvester = ct.get_team(tbid) != ct.get_team()
            for cd in CARDINAL:
                t_pos = h_pos.add(cd)
                if not in_bounds(ct, t_pos):
                    continue
                dx = t_pos.x - my_pos.x
                dy = t_pos.y - my_pos.y
                if abs(dx) > 1 or abs(dy) > 1 or (dx == 0 and dy == 0):
                    continue
                if t_pos in self.map_manager.gunner_danger_positions:
                    continue
                if self.is_recently_filled(ct, t_pos):
                    continue
                t_tbid = ct.get_tile_building_id(t_pos)
                if t_tbid is not None:
                    t_etype = ct.get_entity_type(t_tbid)
                    is_ally = ct.get_team(t_tbid) == ct.get_team()
                    is_marker = t_etype == EntityType.MARKER
                    is_ally_road = t_etype == EntityType.ROAD and is_ally
                    is_ally_marker = is_marker and is_ally
                    is_enemy_marker = is_marker and not is_ally
                    if is_ally_road or is_ally_marker:
                        # Don't destroy our own road/marker if we'd just be
                        # dropping a road back on the cleared tile.
                        if not can_afford_conveyor:
                            continue
                        if not ct.can_destroy(t_pos):
                            continue
                        ct.destroy(t_pos)
                    elif not is_enemy_marker:
                        continue
                if is_enemy_harvester:
                    if build_barrier(ct, t_pos):
                        self.mark_filled(ct, t_pos)
                        return
                    continue
                facing = t_pos.direction_to(h_pos)
                if can_afford_conveyor and ct.can_build_conveyor(t_pos, facing):
                    ct.build_conveyor(t_pos, facing)
                    self.mark_filled(ct, t_pos)
                    return
                if not can_afford_conveyor and ct.can_build_road(t_pos):
                    ct.build_road(t_pos)
                    self.mark_filled(ct, t_pos)
                    return

    def build_road_near_belt(self, ct: Controller):
        if ct.get_action_cooldown() > 0:
            return
        if ct.get_global_resources()[0] <= ct.get_harvester_cost()[0] * 2:
            return
        my_pos = ct.get_position()
        marker_fallback: Position | None = None
        for d in DIRECTIONS:
            t_pos = my_pos.add(d)
            if not in_bounds(ct, t_pos):
                continue
            if not ct.can_build_road(t_pos):
                continue
            adjacent_to_belt = False
            for nd in DIRECTIONS:
                n_pos = t_pos.add(nd)
                if not in_bounds(ct, n_pos):
                    continue
                n_bid = ct.get_tile_building_id(n_pos)
                if n_bid is None:
                    continue
                n_etype = ct.get_entity_type(n_bid)
                if n_etype == EntityType.CONVEYOR or n_etype == EntityType.BRIDGE:
                    adjacent_to_belt = True
                    break
            if not adjacent_to_belt:
                continue
            t_bid = ct.get_tile_building_id(t_pos)
            if (
                t_bid is not None
                and ct.get_entity_type(t_bid) == EntityType.MARKER
                and ct.get_team(t_bid) == ct.get_team()
            ):
                if marker_fallback is None:
                    marker_fallback = t_pos
                continue
            ct.build_road(t_pos)
            return
        if marker_fallback is not None and ct.can_build_road(marker_fallback):
            ct.build_road(marker_fallback)

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

    def build_road_on_enemy_marker(self, ct: Controller):
        if ct.get_action_cooldown() > 0:
            return
        if ct.get_global_resources()[0] <= ct.get_harvester_cost()[0]:
            return
        my_pos = ct.get_position()
        for d in DIRECTIONS:
            t_pos = my_pos.add(d)
            if not in_bounds(ct, t_pos):
                continue
            t_bid = ct.get_tile_building_id(t_pos)
            if t_bid is None:
                continue
            if ct.get_entity_type(t_bid) != EntityType.MARKER:
                continue
            if ct.get_team(t_bid) == ct.get_team():
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
        if ct.get_entity_type(id) == EntityType.CORE and ct.get_team(id) == ct.get_team():
            return ct.get_position(id)
    raise Exception("Core not found on spawn")
