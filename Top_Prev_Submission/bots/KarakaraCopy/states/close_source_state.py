from cambc import Controller, EntityType
from map.map_manager import MapManager
from states.builder_state import BuilderState
from nav.common import common_path
from helpers.directions import DIRECTIONS

class CloseSourceState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        # Persisted across turns. enemy_pos is re-validated next turn via the
        # bot grid; if the enemy moved or died, we fall back to the stored
        # position (worst case the build still gets placed where we wanted).
        self.enemy_pos: Position | None = None
        self.build_pos = None

    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        build_id = ct.get_tile_building_id(self.build_pos)
        # Refresh enemy_pos from the bot grid if the enemy is still in vision.
        mm: MapManager = self.brain.map_manager
        if self.enemy_pos is not None:
            current = mm.get_bot(self.enemy_pos)
            if current is None:
                # Enemy moved or died — scan adjacent for the same bot, else
                # keep stale position so the sentinel still aims roughly right.
                pass
        enemy_pos = self.enemy_pos
        if build_id == None or ct.get_global_resources()[0] > ct.get_barrier_cost()[0]:
            if abs(my_pos.x - self.build_pos.x) <= 1 and abs(my_pos.y - self.build_pos.y) <= 1:
                # if right on top, we should move off so we can build
                if my_pos == self.build_pos:
                    for d in DIRECTIONS:
                        if ct.can_move(d):
                            ct.move(d)

                if ct.get_global_resources()[0] > ct.get_sentinel_cost()[0] * 10:
                    dir_to_enemy = self.build_pos.direction_to(enemy_pos)
                    if ct.can_build_sentinel(self.build_pos, dir_to_enemy):
                        ct.build_sentinel(self.build_pos, dir_to_enemy)
                else:
                    if ct.can_build_barrier(self.build_pos):
                        ct.build_barrier(self.build_pos)
            else:
                common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)
                if ct.get_global_resources()[0] > ct.get_sentinel_cost()[0] * 10:
                    dir_to_enemy = self.build_pos.direction_to(enemy_pos)
                    if ct.can_build_sentinel(self.build_pos, dir_to_enemy):
                        ct.build_sentinel(self.build_pos, dir_to_enemy)
                else:
                    if ct.can_build_barrier(self.build_pos):
                        ct.build_barrier(self.build_pos)
        else:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)

    def determine(self, ct: Controller, state_manager):
        enemy_pos = self.get_closest_enemy(ct)
        if enemy_pos is None:
            return False

        source = self.get_closest_open_source(ct)
        if source is None:
            return False

        build_pos = self.get_build_pos(ct, source)
        if build_pos == None:
            return False

        build_id = ct.get_tile_building_id(build_pos)
        if build_id != None and ct.get_team(build_id) == ct.get_team():
            return False

        self.enemy_pos = enemy_pos
        self.build_pos = build_pos
        state_manager.current_state = BuilderState.CLOSE_SOURCE
        return True


    def get_closest_open_source(self, ct: Controller):
        mm: MapManager = self.brain.map_manager

        best_dist = float('inf')
        best_rec = None

        my_pos = ct.get_position()
        for rec in mm.nearby_ally_open_bridge_ids + mm.nearby_ally_open_conveyor_ids + mm.nearby_ally_open_splitter_ids:
            dist = my_pos.distance_squared(rec.position)
            if dist < best_dist:
                best_rec = rec
                best_dist = dist

        return best_rec

    def get_closest_enemy(self, ct: Controller):
        mm: MapManager = self.brain.map_manager

        best_dist = float('inf')
        best_pos = None

        my_pos = ct.get_position()
        for rec in mm.nearby_enemy_builder_bot_ids:
            dist = my_pos.distance_squared(rec.position)
            if dist < best_dist:
                best_pos = rec.position
                best_dist = dist

        return best_pos

    def get_build_pos(self, ct: Controller, rec):
        e_type = rec.entity_type
        if e_type == EntityType.CONVEYOR or e_type == EntityType.ARMOURED_CONVEYOR:
            return rec.position.add(rec.direction)
        if e_type == EntityType.BRIDGE:
            return rec.output_target
        return None