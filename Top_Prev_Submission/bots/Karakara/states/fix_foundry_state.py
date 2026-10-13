from cambc import Controller, Direction, EntityType, Position, ResourceType, Environment
from helpers.directions import CARDINAL, DIRECTIONS
from map.map_manager import MapManager
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from debug.profiling import cputimer

class FixFoundryState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.replace_pos = None
        self.is_standable = False
        self.next_to_harvester = False
        self.place_barrier = True
        self.pending_pos = None
        self.pending_timer = 0

    @cputimer
    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        print("clog pos: ", self.replace_pos)
        # Always stay adjacent (not on tile) and place barrier
        mm = self.brain.map_manager
        if abs(my_pos.x - self.replace_pos.x) <= 1 and abs(my_pos.y - self.replace_pos.y) <= 1:
            moved = False
            if ct.get_position() == self.replace_pos:
                print("STANDING")
                for d in DIRECTIONS:
                    if ct.can_move(d):
                        ct.move(d)
                        moved = True
                        break
                    print("FAILED MOVE ", d)
            if (
                (
                    mm.bot_grid[self.replace_pos.x][self.replace_pos.y] is None or
                    moved
                )
                and (not self.place_barrier or ct.get_global_resources()[0] > ct.get_barrier_cost()[0])
            ):
                if ct.can_destroy(self.replace_pos) and (self.place_barrier or ct.get_global_resources()[0] > ct.get_road_cost()[0]):
                    ct.destroy(self.replace_pos)
                    if self.place_barrier and ct.can_build_barrier(self.replace_pos):
                        ct.build_barrier(self.replace_pos)
                    elif not self.place_barrier and ct.can_build_road(self.replace_pos):
                        ct.build_road(self.replace_pos)
        elif my_pos.distance_squared(self.replace_pos) > 2:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.replace_pos)

    @cputimer
    def determine(self, ct, state_manager):
        replace_pos = self.find_clogging_conveyor(ct)
        if replace_pos is not None:
            self.is_standable = False
            self.place_barrier = False
        if replace_pos is None:
            replace_pos = self.find_clogging_path(ct)
            if replace_pos is not None:
                self.is_standable = True
                self.place_barrier = True
        if replace_pos is None:
            replace_pos = self.find_clogging_foundry(ct)
            self.is_standable = False
            self.place_barrier = True
        if replace_pos == None:
            self.pending_pos = None
            self.pending_timer = 0
            return False
        if replace_pos != self.pending_pos:
            self.pending_pos = replace_pos
            self.pending_timer = 0
        self.pending_timer += 1
        if self.pending_timer < 10:
            return False
        mm = self.brain.map_manager
        my_id = ct.get_id()
        my_team = ct.get_team()
        for d in [Direction.CENTRE] + DIRECTIONS:
            check_pos = replace_pos.add(d)
            if not in_bounds(ct, check_pos):
                continue
            bot_rec = mm.get_bot(check_pos)
            if bot_rec is None or bot_rec.id == my_id:
                continue
            if bot_rec.team == my_team:
                return False
        self.replace_pos = replace_pos
        state_manager.current_state = BuilderState.FIX_FOUNDRY_STATE
        return True

    def find_clogging_conveyor(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        best_pos = None
        best_dist = float('inf')
        for rec in mm.nearby_ally_clogged_conveyor_ids:
            pos = rec.position
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
        return best_pos

    def find_clogging_foundry(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        print("fix_foundry_pos_candidates:", mm.fix_foundry_pos_candidates)
        best_pos = None
        best_dist = float('inf')
        for pos in mm.fix_foundry_pos_candidates:
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
        return best_pos

    def _check_harvester_adjacent(self, ct: Controller, my_pos: Position, pos: Position):
        self.next_to_harvester = False
        for d in CARDINAL:
            adj_pos = pos.add(d)
            if not in_bounds(ct, adj_pos) or my_pos.distance_squared(adj_pos) > ct.get_vision_radius_sq():
                continue
            adj_id = ct.get_tile_building_id(adj_pos)
            if adj_id is not None and ct.get_entity_type(adj_id) == EntityType.HARVESTER:
                self.next_to_harvester = True
                return
    
    def find_clogging_path(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()

        best_pos = None
        best_dist = float('inf')
        for rec in mm.nearby_ally_clogged_bridge_ids:
            pos = rec.position
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
        if best_pos is not None:
            self._check_harvester_adjacent(ct, my_pos, best_pos)
        return best_pos

