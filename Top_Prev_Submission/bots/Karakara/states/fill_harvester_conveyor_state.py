from cambc import EntityType, Environment, Position, Direction

from debug.profiling import cputimer
from helpers.directions import CARDINAL
from helpers.geometry import on_map
from map.map_manager import MapManager
from nav.common import common_path
from states.builder_state import BuilderState

ACTION_RADIUS_SQ = 2
MAX_ATTEMPT_ROUNDS = 100
# After this many consecutive turns of trying to reach/fill the same
# target without succeeding, blacklist it so we don't keep re-picking
# the same tile.
FAIL_TIMEOUT_ROUNDS = 20
DESTROYABLE_OWN = {EntityType.ROAD, EntityType.MARKER}


class FillHarvesterConveyorState:
    """Place conveyors on empty cardinal-adjacent spots of ally harvesters,
    facing into the harvester.
    """

    def __init__(self, ct, brain) -> None:
        self.brain = brain
        self.target_pos: Position | None = None
        self.target_dir: Direction | None = None
        self.target_enemy: bool = False
        self.attempt_start: int | None = None
        # Tiles the bot has given up on — either confirmed unreachable
        # or the per-target attempt budget ran out. Skipped by both
        # validity check and fresh-pick. Per-bot, persistent for the
        # life of the state instance.
        self._blacklist: set[tuple[int, int]] = set()

    def _is_buildable(self, ct, mm: MapManager, pos: Position, is_enemy: bool = False) -> bool:
        if not on_map(pos, mm.width, mm.height):
            return False
        if pos in mm.gunner_danger_positions:
            return False
        if is_enemy:
            bot = mm.get_bot(pos)
            if bot is not None and bot.id != ct.get_id():
                return False
        building = mm.get_building(pos)
        if building is None:
            tile = mm.get_tile(pos)
            return tile != Environment.WALL
        if building.team != ct.get_team():
            return building.entity_type == EntityType.MARKER
        return building.entity_type in DESTROYABLE_OWN
    

    def _find_spot(self, ct, mm: MapManager, my_pos: Position):
        best = None
        best_key = (1, float("inf"))
        ally_pairs = [(h, a, False) for h, a in mm.nearby_harvester_card_pos]
        enemy_pairs = [(h, a, True) for h, a in mm.nearby_harvester_enemy_card_pos]
        for h_pos, t_pos, is_enemy in ally_pairs + enemy_pairs:
            if t_pos == my_pos:
                continue
            if (t_pos.x, t_pos.y) in self._blacklist:
                continue
            if self.brain.is_recently_filled(ct, t_pos):
                continue
            if not self._is_buildable(ct, mm, t_pos, is_enemy):
                continue
            # Skip provably unreachable spots — no point picking a
            # target we can't get to.
            if self.brain.pathing.is_tile_unreachable(mm, t_pos):
                self._blacklist.add((t_pos.x, t_pos.y))
                continue
            dist = my_pos.distance_squared(t_pos)
            rank = 0 if dist <= ACTION_RADIUS_SQ else 1
            key = (rank, dist)
            if key < best_key:
                best_key = key
                facing = t_pos.direction_to(h_pos)
                best = (t_pos, facing, is_enemy)
        return best

    def _is_target_valid(self, ct, mm: MapManager) -> bool:
        if self.target_pos is None or self.target_dir is None:
            return False

        # Cooldown timeout: if we've been on this target for
        # FAIL_TIMEOUT_ROUNDS consecutive turns without succeeding,
        # blacklist and drop it.
        if self.attempt_start is not None:
            elapsed = ct.get_current_round() - self.attempt_start
            if elapsed >= FAIL_TIMEOUT_ROUNDS:
                key = (self.target_pos.x, self.target_pos.y)
                self._blacklist.add(key)
                return False

        if self.brain.is_recently_filled(ct, self.target_pos):
            return False

        if not self._is_buildable(ct, mm, self.target_pos, self.target_enemy):
            return False

        if self.brain.pathing.is_tile_unreachable(mm, self.target_pos):
            key = (self.target_pos.x, self.target_pos.y)
            self._blacklist.add(key)
            return False
        h = self.target_pos.add(self.target_dir)
        if not on_map(h, mm.width, mm.height):
            return False
        building = mm.get_building(h)
        if building is None or building.entity_type != EntityType.HARVESTER:
            return False
        if self.target_enemy:
            return building.team != ct.get_team()
        return building.team == ct.get_team()
        

    @cputimer
    def determine(self, ct, state_manager):
        mm: MapManager = self.brain.map_manager
        min_cost = min(ct.get_conveyor_cost()[0], ct.get_barrier_cost()[0])
        resources = ct.get_global_resources()[0]
        if resources < min_cost * 2:
            self._clear()
            return False

        # Don't fill conveyors while enemy turrets are in vision.
        if mm.nearby_enemy_turret_pos:
            self._clear()
            return False

        if self._is_target_valid(ct, mm):
            state_manager.current_state = BuilderState.FILL_HARVESTER_CONVEYOR
            return True

        my_pos = ct.get_position()
        result = self._find_spot(ct, mm, my_pos)
        if result is not None:
            self.target_pos, self.target_dir, self.target_enemy = result
            self.attempt_start = ct.get_current_round()
            state_manager.current_state = BuilderState.FILL_HARVESTER_CONVEYOR
            return True

        self._clear()
        return False

    def execute(self, ct):
        mm: MapManager = self.brain.map_manager
        if self.target_pos is None:
            return

        if self.attempt_start is not None and ct.get_current_round() - self.attempt_start > MAX_ATTEMPT_ROUNDS:
            self._clear()
            return

        my_pos = ct.get_position()

        if my_pos.distance_squared(self.target_pos) <= ACTION_RADIUS_SQ:
            if my_pos != self.target_pos:
                building = mm.get_building(self.target_pos)
                if (
                    building is not None
                    and building.team == ct.get_team()
                    and building.entity_type in DESTROYABLE_OWN
                ):
                    if ct.can_destroy(self.target_pos):
                        ct.destroy(self.target_pos)
            if self.target_enemy:
                if my_pos != self.target_pos:
                    if ct.can_build_barrier(self.target_pos):
                        ct.build_barrier(self.target_pos)
                        self.brain.mark_filled(ct, self.target_pos)
                        self._clear()
                        return
            else:
                if ct.can_build_conveyor(self.target_pos, self.target_dir):
                    ct.build_conveyor(self.target_pos, self.target_dir)
                    self.brain.mark_filled(ct, self.target_pos)
                    self._clear()
                    return

        path_target = self.target_pos
        if self.target_enemy and my_pos == self.target_pos:
            for d in CARDINAL:
                step = my_pos.add(d)
                if (
                    on_map(step, mm.width, mm.height)
                    and mm.get_building(step) is None
                    and mm.get_tile(step) != Environment.WALL
                ):
                    path_target = step
                    break
        common_path(ct, mm, self.brain.pathing, path_target)

    def _clear(self):
        self.target_pos = None
        self.target_dir = None
        self.target_enemy = False
        self.attempt_start = None
