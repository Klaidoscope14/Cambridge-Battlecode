from cambc import Controller, EntityType, Direction, Position, Environment, ResourceType
from debug.profiling import cputimer
from helpers.directions import CARDINAL, DIRECTIONS
from map.map_manager import MapManager
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from conveyor.conveyor_astar import ConveyorAStar

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER, EntityType.CONVEYOR]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.SPLITTER, EntityType.BRIDGE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]


class ConnectAxioniteState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.prev_dir = None
        self.source = None
        self.source_pos = None
        self.build_pos = None
        self.dest = None
        self.path_builder = PathBuilder(ct, brain)
        self.conveyor_astar = ConveyorAStar(ct, brain)
        self.astar_turns_attempted = 0

    def _count_nearby_builders(self, ct: Controller, mm: MapManager, center: Position) -> tuple[int, int]:
        """Count ally and enemy builders in the 9 tiles around *center*.
        Returns (ally_count, enemy_count).

        Hard cap: if 4+ raw allies already surround *center* (ignoring the id /
        cooldown / on-ore filters), the returned ally count is forced to 8. The
        caller's `allies > enemies + 1` check then rejects the square, keeping
        further builders from piling onto an already crowded cluster.
        """
        my_pos = ct.get_position()
        my_team = ct.get_team()
        my_id = ct.get_id()
        vision_sq = ct.get_vision_radius_sq()
        width = mm.width
        height = mm.height
        bot_grid = mm.bot_grid
        tile_grid = mm.tile_grid
        inactive_allies = 0
        allies = 0
        enemies = 0
        raw_allies = 0
        positions_to_check = [center] + [center.add(d) for d in DIRECTIONS]
        for check_pos in positions_to_check:
            cx = check_pos.x
            cy = check_pos.y
            if not (0 <= cx < width and 0 <= cy < height):
                continue
            if my_pos.distance_squared(check_pos) > vision_sq:
                continue
            bot_record = bot_grid[cx][cy]
            if bot_record is None:
                continue
            if bot_record.team == my_team:
                raw_allies += 1
                if tile_grid[cx][cy] in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                    continue
                if bot_record.id >= my_id:
                    continue
                if bot_record.action_cooldown > 0:
                    inactive_allies += 1
                else:
                    allies += 1
            else:
                enemies += 1
        if not mm.nearby_enemy_builder_bot_ids: allies += inactive_allies
        if raw_allies >= 4:
            return 8, enemies
        return allies, enemies

    @cputimer
    def execute(self, ct: Controller):
        my_pos = ct.get_position()
        print("build pos: ", self.build_pos)
        print("dest: ", self.dest)
        return self._execute_astar(ct, my_pos)

    def _execute_astar(self, ct: Controller, my_pos: Position):
        """A* planner with use_early_goals=False — path always runs to destination."""
        mm: MapManager = self.brain.map_manager

        if mm.newly_seen:
            self.conveyor_astar.handle_newly_seen(mm)

        if self.conveyor_astar.is_complete():
            print("ASTAR PATH BUILDER (axionite)")
            self.astar_turns_attempted = 0
            if not self.conveyor_astar.validate_next_step(ct):
                print("[ConvAStar/axionite] next step invalid, re-planning")
                saved_source_pos = self.source_pos
                saved_build_pos = self.build_pos
                saved_dest = self.dest
                self.conveyor_astar.invalidate()
                self.source = None
                self.source_pos = None
                self.build_pos = None
                if saved_build_pos is not None and saved_dest is not None:
                    src = saved_source_pos if saved_source_pos is not None else my_pos
                    self.conveyor_astar.plan_path(
                        ct, src, saved_build_pos, saved_dest,
                        use_early_goals=False,
                        use_core_exclusion=False,
                        avoid_harvester_adjacent=True,
                        early_goal_only_titanium=True,
                    )
                    self.build_pos = saved_build_pos
                    self.source_pos = src
                    self.dest = saved_dest
                self.astar_turns_attempted = 0
                return

            step = self.conveyor_astar.get_next_build_step()
            if step is None:
                self.build_pos = None
                self.source = None
                self.source_pos = None
                self.conveyor_astar.invalidate()
                return

            build_pos = step.pos
            if abs(my_pos.x - build_pos.x) <= 1 and abs(my_pos.y - build_pos.y) <= 1:
                built = self._execute_build_step(ct, step)
                if built:
                    self.conveyor_astar.advance()
                    self.build_pos = None
                    self.source = None
                    self.source_pos = None
            else:
                common_path(ct, mm, self.brain.pathing, build_pos)
            return
        else:
            self.astar_turns_attempted += 1

        found = self.conveyor_astar.expand_turn(ct)
        if found:
            return

        # Fallback while A* is still computing
        if self.astar_turns_attempted > 10:
            print("OLD PATH BUILDER (axionite)")
            self._execute_old(ct, my_pos)
        else:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)

    def _execute_old(self, ct: Controller, my_pos: Position):
        """Greedy PathBuilder fallback. isolate=True keeps axionite paths independent."""
        if abs(my_pos.x - self.build_pos.x) <= 1 and abs(my_pos.y - self.build_pos.y) <= 1:
            self.path_builder.connect_and_move(
                ct, self.prev_dir, self.source,
                self.build_pos, self.dest,
                isolate=True, bridge_on_dest=True,
                use_early_goals=False
            )
            self.build_pos = None
            self.source = None
            self.source_pos = None
        else:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)

    def _execute_build_step(self, ct: Controller, step) -> bool:
        """Execute one A* build step, handling obstacles. Returns True if built."""
        build_pos = step.pos
        my_pos = ct.get_position()
        move_dir = my_pos.direction_to(build_pos)
        tile_id = ct.get_tile_building_id(build_pos)

        if ct.get_tile_env(build_pos) == Environment.WALL:
            return False

        if tile_id is None:
            built = self._build_step(ct, step)
            if built and ct.can_move(move_dir):
                ct.move(move_dir)
            return built

        if ct.get_team(tile_id) != ct.get_team() and ct.get_entity_type(tile_id) in ENEMY_FIREABLE_TYPES:
            if my_pos != build_pos and ct.can_move(move_dir):
                ct.move(move_dir)
            if ct.can_fire(build_pos):
                ct.fire(build_pos)
            return self._build_step(ct, step)

        if ct.get_team(tile_id) == ct.get_team() and ct.get_entity_type(tile_id) in ALLY_DESTROYABLE_TYPES:
            cost = ct.get_bridge_cost()[0] if step.build_type == EntityType.BRIDGE else ct.get_conveyor_cost()[0]
            if ct.get_global_resources()[0] >= cost:
                if ct.can_destroy(build_pos):
                    ct.destroy(build_pos)
                built = self._build_step(ct, step)
                if built and ct.can_move(move_dir):
                    ct.move(move_dir)
                return built
            return False

        print("BUILD STEP RETURN FALSE (axionite)")
        return False

    def _build_step(self, ct: Controller, step) -> bool:
        if step.build_type == EntityType.CONVEYOR:
            if ct.can_build_conveyor(step.pos, step.direction):
                ct.build_conveyor(step.pos, step.direction)
                return True
        elif step.build_type == EntityType.BRIDGE:
            if ct.can_build_bridge(step.pos, step.bridge_target):
                ct.build_bridge(step.pos, step.bridge_target)
                return True
        return False

    def _dest_still_valid(self, mm: MapManager) -> bool:
        """Is self.dest still an acceptable axionite destination?

        A dest is valid when it's (still) listed as a harvester-adjacent conveyor
        or a no-axionite foundry position (or an ally foundry's own tile as a
        last resort), AND hasn't already been connected into by another bot's
        raw-axionite bridge.
        """
        if self.dest is None:
            return False

        for t in mm.nearby_ally_raw_axionite_bridge_targets:
            if t == self.dest:
                return False

        for pos in mm.seen_adjacent_harvester_conveyor_positions:
            if pos == self.dest:
                return True
        for pos in mm.seen_no_axionite_foundry_positions:
            if pos == self.dest:
                return True
        id_to_pos = mm.id_to_pos
        for id in mm.nearby_ally_foundry_ids:
            if id_to_pos[id] == self.dest:
                return True
        return False

    @cputimer
    def determine(self, ct: Controller, state_manager):
        mm: MapManager = self.brain.map_manager

        # Resume an existing plan if we still have one
        if self.build_pos is not None:
            my_pos = ct.get_position()
            # Once the dest is in vision range, revalidate — another bot may have
            # already connected to it, or it may no longer be a candidate. Replan
            # if so rather than building a chain into a dead target.
            if self.dest is not None and my_pos.distance_squared(self.dest) <= ct.get_vision_radius_sq():
                if not self._dest_still_valid(mm):
                    print("[axionite] dest no longer valid, replanning")
                    self.build_pos = None
                    self.source = None
                    self.source_pos = None
                    self.dest = None
                    self.conveyor_astar.invalidate()
                    return False
            if my_pos.distance_squared(self.source_pos) <= 9 and my_pos.distance_squared(self.build_pos) <= 9:
                valid_sources = (mm.nearby_ally_open_axionite_harvester_ids
                                 + mm.nearby_ally_open_raw_axionite_conveyor_ids
                                 + mm.nearby_ally_open_raw_axionite_bridge_ids)
                if self.source not in valid_sources:
                    self.build_pos = None
                    self.source = None
                    self.source_pos = None
                    self.conveyor_astar.invalidate()
                    return False

                allies, enemies = self._count_nearby_builders(ct, mm, self.build_pos)
                if allies > enemies + 1:
                    self.build_pos = None
                    self.source = None
                    self.source_pos = None
                    self.conveyor_astar.invalidate()
                    return False

                state_manager.current_state = BuilderState.CONNECT_AXIONITE_STATE
                return True
            else:
                state_manager.current_state = BuilderState.CONNECT_AXIONITE_STATE
                return True

        dest = self.find_destination(ct)
        if dest is None:
            return False

        source = self.find_source(ct)
        if source is None:
            return False

        source_pos = mm.id_to_pos[source]
        allies, enemies = self._count_nearby_builders(ct, mm, source_pos)
        if allies > enemies + 1:
            return False

        build_pos = self.get_build_pos(ct, source)
        if build_pos is None:
            return False

        self.source = source
        self.source_pos = source_pos
        self.build_pos = build_pos
        self.dest = dest

        print("dist to dest: ", ct.get_position().distance_squared(dest))
        print("build pos: ", self.build_pos)
        print("dest pos: ", self.dest)

        source_rec = mm.id_to_record[source]
        if source_rec.entity_type in [EntityType.CONVEYOR, EntityType.SPLITTER]:
            self.prev_dir = source_rec.direction
        else:
            self.prev_dir = None

        # Axionite pathing differs from the titanium conveyor planner:
        #   - use_early_goals=False         : never shortcut during normal search,
        #                                     only fall back to a hop when the path
        #                                     to dest truly exhausts
        #   - use_core_exclusion=False      : axionite never cares about proximity
        #                                     to the ally core
        #   - avoid_harvester_adjacent=True : don't build on tiles cardinally
        #                                     adjacent to any harvester (bridge
        #                                     over them instead); dest is exempt
        #   - early_goal_only_titanium=True : the exhaust-mode fallback can only
        #                                     hook into titanium conveyors
        if not self.conveyor_astar.is_planned_for_dest(self.dest):
            self.conveyor_astar.plan_path(
                ct, self.source_pos, self.build_pos, self.dest,
                use_early_goals=False,
                use_core_exclusion=False,
                avoid_harvester_adjacent=True,
                early_goal_only_titanium=True,
            )

        state_manager.current_state = BuilderState.CONNECT_AXIONITE_STATE
        return True

    # ── Destination / source finding (unchanged from original) ───────────────

    def find_destination(self, ct):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        bridge_targets = mm.nearby_ally_raw_axionite_bridge_targets
        best_pos = None
        best_dist = float('inf')
        for pos in mm.seen_adjacent_harvester_conveyor_positions:
            already_connected = False
            for t in bridge_targets:
                if t == pos:
                    already_connected = True
                    break
            if already_connected:
                continue
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos

        for pos in mm.seen_no_axionite_foundry_positions:
            already_connected = False
            for t in bridge_targets:
                if t == pos:
                    already_connected = True
                    break
            if already_connected:
                continue
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos

        if best_pos is None:
            id_to_pos = mm.id_to_pos
            for id in mm.nearby_ally_foundry_ids:
                pos = id_to_pos[id]
                dist = my_pos.distance_squared(pos)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = pos

        return best_pos

    def find_source(self, ct):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        id_to_pos = mm.id_to_pos
        best_id = None
        best_dist = float('inf')
        for id in (mm.nearby_ally_open_axionite_harvester_ids
                   + mm.nearby_ally_open_raw_axionite_conveyor_ids
                   + mm.nearby_ally_open_raw_axionite_bridge_ids):
            pos = id_to_pos[id]
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_id = id
        return best_id

    def get_build_pos(self, ct: Controller, eid):
        unit_type = self.brain.map_manager.id_to_record[eid].entity_type
        if unit_type == EntityType.HARVESTER:
            return self.get_harvester_build_pos(ct, eid)
        elif unit_type == EntityType.FOUNDRY:
            return self.get_foundry_build_pos(ct, eid)
        elif unit_type == EntityType.CONVEYOR:
            return self.get_conv_build_pos(ct, eid)
        elif unit_type == EntityType.BRIDGE:
            return self.get_bridge_build_pos(ct, eid)
        elif unit_type == EntityType.SPLITTER:
            return self.get_splitter_build_pos(ct, eid)

    def get_harvester_build_pos(self, ct: Controller, eid):
        mm: MapManager = self.brain.map_manager
        harv_pos = mm.id_to_pos[eid]
        best_pos = None
        best_dist = float('inf')
        my_pos = ct.get_position()
        vision_sq = ct.get_vision_radius_sq()
        width = mm.width
        height = mm.height
        tile_grid = mm.tile_grid
        building_grid = mm.building_grid
        for d in CARDINAL:
            adj_pos = harv_pos.add(d)
            ax = adj_pos.x
            ay = adj_pos.y
            if not (0 <= ax < width and 0 <= ay < height):
                continue
            if my_pos.distance_squared(adj_pos) > vision_sq:
                continue
            adj_env = tile_grid[ax][ay]
            if adj_env in BLOCKING_ENVIRONMENT_TYPES:
                continue
            adj_rec = building_grid[ax][ay]
            if adj_rec is not None and adj_rec.entity_type in ALLY_BLOCKING_TYPES:
                continue
            dist = adj_pos.distance_squared(my_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = adj_pos
        return best_pos

    def get_conv_build_pos(self, ct: Controller, eid):
        mm = self.brain.map_manager
        return mm.id_to_pos[eid].add(mm.id_to_record[eid].direction)

    def get_bridge_build_pos(self, ct: Controller, eid):
        return self.brain.map_manager.id_to_record[eid].output_target

    def get_splitter_build_pos(self, ct, eid):
        mm = self.brain.map_manager
        return mm.id_to_pos[eid].add(mm.id_to_record[eid].direction)

    def get_foundry_build_pos(self, ct, eid):
        return self.brain.map_manager.id_to_pos[eid]