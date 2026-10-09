from cambc import Controller, EntityType, Position, ResourceType, Environment
from helpers.directions import CARDINAL, DIRECTIONS
from map.map_manager import MapManager
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from debug.profiling import cputimer

class ReplaceWithFoundryState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.replace_pos = None

    @cputimer
    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        print(self.replace_pos)
        # print("foundry cost: ", ct.get_foundry_cost()[0])
        # print("action cooldown: ", ct.get_action_cooldown())
        # print("builder bot id on replace pos: ", ct.get_tile_builder_bot_id(self.replace_pos))
        # print("adj: ", abs(my_pos.x - self.replace_pos.x) <= 1 and abs(my_pos.y - self.replace_pos.y) <= 1)
        if abs(my_pos.x - self.replace_pos.x) <= 1 and abs(my_pos.y - self.replace_pos.y) <= 1:
            
            # simple move off it if i'm standing on build pos
            if my_pos == self.replace_pos:
                for d in CARDINAL:
                    if ct.can_move(d):
                        ct.move(d)
            if ct.get_global_resources()[0] > ct.get_foundry_cost()[0] and ct.get_action_cooldown() == 0 and ct.get_tile_builder_bot_id(self.replace_pos) == None:
                print("can destroy: ", ct.can_destroy(self.replace_pos))
                if ct.can_destroy(self.replace_pos):
                    ct.destroy(self.replace_pos)
                if ct.can_build_foundry(self.replace_pos):
                    ct.build_foundry(self.replace_pos)
        else:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.replace_pos)

    @cputimer
    def determine(self, ct, state_manager):
        replace_pos = self.find_replace_location(ct)
        if replace_pos == None:
            return False

        # Don't crowd the target: if another builder is already on or adjacent to
        # replace_pos, only proceed if that bot is ourself.
        mm: MapManager = self.brain.map_manager
        my_id = ct.get_id()
        my_pos = ct.get_position()
        vision_sq = ct.get_vision_radius_sq()
        width = mm.width
        height = mm.height
        bot_grid = mm.bot_grid
        positions_to_check = [replace_pos] + [replace_pos.add(d) for d in DIRECTIONS]
        for check_pos in positions_to_check:
            cx = check_pos.x
            cy = check_pos.y
            if not (0 <= cx < width and 0 <= cy < height):
                continue
            if my_pos.distance_squared(check_pos) > vision_sq:
                continue
            occupant_rec = bot_grid[cx][cy]
            occupant = occupant_rec.id if occupant_rec is not None else None
            if occupant is not None and occupant != my_id:
                return False

        self.replace_pos = replace_pos
        state_manager.current_state = BuilderState.REPLACE_WITH_FOUNDRY_STATE
        return True

    def find_replace_location(self, ct: Controller):
        # Candidate detection runs in MapManager.update(); here we just pick
        # the closest precomputed candidate and drop any that are already
        # served by a foundry.
        #
        # Two skip rules (both use all 8 neighbours):
        #   1. The candidate tile itself has a foundry in any adjacent tile —
        #      dropping another foundry right next to it wastes the slot.
        #   2. Any harvester adjacent to the candidate already has a foundry
        #      adjacent on one of ITS other sides. In that case the axionite
        #      feed is already covered and we shouldn't pile a second foundry
        #      around the same harvester.
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        width = mm.width
        height = mm.height
        building_grid = mm.building_grid
        best_pos = None
        best_dist = float('inf')
        for cand_pos in mm.nearby_foundry_replacement_candidates:
            skip = False
            adj_harvester_positions: list[Position] = []
            for d in DIRECTIONS:
                adj = cand_pos.add(d)
                ax, ay = adj.x, adj.y
                if not (0 <= ax < width and 0 <= ay < height):
                    continue
                rec = building_grid[ax][ay]
                if rec is None:
                    continue
                if rec.entity_type == EntityType.FOUNDRY:
                    skip = True
                    break
                if rec.entity_type == EntityType.HARVESTER:
                    adj_harvester_positions.append(adj)
            if skip:
                continue
            # Rule 2: inspect each adjacent harvester for a foundry on any of
            # its own 8 neighbours.
            for h_pos in adj_harvester_positions:
                for d in DIRECTIONS:
                    adj = h_pos.add(d)
                    ax, ay = adj.x, adj.y
                    if not (0 <= ax < width and 0 <= ay < height):
                        continue
                    rec = building_grid[ax][ay]
                    if rec is not None and rec.entity_type == EntityType.FOUNDRY:
                        skip = True
                        break
                if skip:
                    break
            if skip:
                continue
            dist = my_pos.distance_squared(cand_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = cand_pos
        return best_pos
                        

