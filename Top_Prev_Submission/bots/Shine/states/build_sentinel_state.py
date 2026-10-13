from cambc import EntityType, Environment, GameConstants, Position, Direction
from debug.profiling import cputimer
from helpers.directions import DIRECTIONS
from map.map_manager import MapManager
from turret.buildable import is_buildable_spot, is_destroyable_blocker
from turret.safe_path import path_to_build_spot
from turret.step_off import handle_on_build_tile
from states.builder_state import BuilderState

ACTION_RADIUS_SQ = 2
MAX_ATTEMPT_ROUNDS = 2000
MAX_SENTINELS_PER_HARVESTER = 1
SKIP_AXIONITE_HARVESTERS = True
TRIGGER_RADIUS_SQ = 20
"""A trigger entity must be within this squared distance of the build
spot for a sentinel to be placed there."""

FACING_PRIORITY = [
    "nearby_enemy_turret_pos",
    "nearby_enemy_harvester_ids",
    "nearby_enemy_conveyor_ids",
    "nearby_enemy_launcher_ids",
    "nearby_enemy_builder_bot_ids",
]

TRIGGER_PRIORITY = [
    "nearby_enemy_turret_pos",
    "nearby_enemy_launcher_ids",
    "nearby_enemy_conveyor_ids",
    "nearby_enemy_bridge_ids",
    "nearby_enemy_harvester_ids"
]

class BuildSentinelState:
    def __init__(self, ct, brain) -> None:
        self.brain = brain
        self.target_pos: Position | None = None
        self.target_dir: Direction | None = None
        self.attempt_start: int | None = None

    def _is_buildable(self, ct, mm: MapManager, pos: Position) -> bool:
        return is_buildable_spot(ct, mm, pos)

    def _has_enemy_nearby(self, ct, mm: MapManager, build_pos: Position) -> bool:
        for attr in TRIGGER_PRIORITY:
            items = getattr(mm, attr, [])
            for item in items:
                trigger_pos = item if isinstance(item, Position) else ct.get_position(item)
                if trigger_pos is None:
                    continue
                if build_pos.distance_squared(trigger_pos) <= TRIGGER_RADIUS_SQ:
                    return True
        return False

    def _pick_facing(self, ct, mm: MapManager, pos: Position, harvester_pos: Position | None = None):
        toward_harvester = pos.direction_to(harvester_pos) if harvester_pos else None

        for attr in FACING_PRIORITY:
            items = getattr(mm, attr, [])
            if not items:
                continue
            # Positions are stored directly, IDs need a lookup
            target = items[0] if isinstance(items[0], Position) else ct.get_position(items[0])
            facing = pos.direction_to(target)
            if facing != toward_harvester:
                return facing
            return facing.rotate_left()

        # Face enemy core
        if mm.spotted_enemy_core_pos is not None:
            facing = pos.direction_to(mm.spotted_enemy_core_pos)
            if facing != toward_harvester:
                return facing
            return facing.rotate_left()

        # Fallback: away from harvester
        if harvester_pos is not None:
            return harvester_pos.direction_to(pos)

        return Direction.NORTH

    def _find_sentinel_spot(self, ct, mm: MapManager, my_pos: Position):
        best = None
        best_dist = float("inf")

        # Find spot next to ally harvester and point at threats
        for harvester_pos, pos in mm.nearby_harvester_card_pos:
            key = (harvester_pos.x, harvester_pos.y)
            if SKIP_AXIONITE_HARVESTERS and mm.get_tile(harvester_pos) == Environment.ORE_AXIONITE:
                continue
            if mm.harvester_sentinel_count.get(key, 0) >= MAX_SENTINELS_PER_HARVESTER:
                continue
            if not self._is_buildable(ct, mm, pos):
                continue
            if not self._has_enemy_nearby(ct, mm, pos):
                continue
            facing = self._pick_facing(ct, mm, pos, harvester_pos)
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best = (pos, facing)

        # Place next to enemy harvesters to disrupt their resource collection
        for harvester_pos, adj in mm.nearby_harvester_enemy_card_pos:
            key = (harvester_pos.x, harvester_pos.y)
            if SKIP_AXIONITE_HARVESTERS and mm.get_tile(harvester_pos) == Environment.ORE_AXIONITE:
                continue
            if mm.harvester_sentinel_count.get(key, 0) >= MAX_SENTINELS_PER_HARVESTER:
                continue
            if not self._is_buildable(ct, mm, adj):
                continue
            facing = self._pick_facing(ct, mm, adj, harvester_pos)
            dist = my_pos.distance_squared(adj)
            if dist < best_dist:
                best_dist = dist
                best = (adj, facing)

        return best

    def _is_target_valid(self, ct, mm: MapManager):
        if self.target_pos is None:
            return False
        return self._is_buildable(ct, mm, self.target_pos)

    @cputimer
    def determine(self, ct, state_manager):
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        # Can't afford it — don't even try
        cost = ct.get_sentinel_cost()[0] + ct.get_road_cost()[0]
        if ct.get_global_resources()[0] < cost :
            self.target_pos = None
            self.target_dir = None
            self.attempt_start = None
            return False
        
        if ct.get_current_round() < 50:
            return False
    
        if self.target_pos is not None and self._is_target_valid(ct, mm):
            state_manager.current_state = BuilderState.BUILD_SENTINEL
            return True

        result = self._find_sentinel_spot(ct, mm, my_pos)
        if result is not None:
            self.target_pos, self.target_dir = result
            self.attempt_start = ct.get_current_round()
            state_manager.current_state = BuilderState.BUILD_SENTINEL
            return True

        self.target_pos = None
        self.target_dir = None
        self.attempt_start = None
        return False

    def execute(self, ct):
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        if self.target_pos is None:
            return

        if self.attempt_start is not None and ct.get_current_round() - self.attempt_start > MAX_ATTEMPT_ROUNDS:
            self.target_pos = None
            self.target_dir = None
            self.attempt_start = None
            return

        # Standing on build tile — destroy, step off, build
        if my_pos == self.target_pos:
            target_dir = self.target_dir
            built = handle_on_build_tile(
                ct, mm, self.target_pos,
                lambda p: ct.can_build_sentinel(p, target_dir),
                lambda p: ct.build_sentinel(p, target_dir),
            )
            if built:
                self.target_pos = None
                self.target_dir = None
                self.attempt_start = None
            return

        # Adjacent — clear blocker and build
        if my_pos.distance_squared(self.target_pos) <= ACTION_RADIUS_SQ:
            building = mm.get_building(self.target_pos)
            if building is not None and building.team == ct.get_team() and is_destroyable_blocker(mm, self.target_pos, building):
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            can = ct.can_build_sentinel(self.target_pos, self.target_dir)
            if can:
                ct.build_sentinel(self.target_pos, self.target_dir)
                self.target_pos = None
                self.target_dir = None
                self.attempt_start = None
                return

        path_to_build_spot(ct, mm, self.brain.pathing, self.target_pos)
