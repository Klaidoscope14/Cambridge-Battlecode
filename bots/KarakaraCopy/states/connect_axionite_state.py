from cambc import Controller, EntityType, Direction, Position, Environment, ResourceType
from debug.profiling import cputimer
from helpers.directions import CARDINAL, DIRECTIONS
from map.map_manager import MapManager
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from conveyor.conveyor_astar import ConveyorAStar, _tile_buildable

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.SPLITTER, EntityType.BRIDGE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]

# ENEMY_FIREABLE_TYPES intentionally excludes ARMOURED_CONVEYOR — builder bots
# cannot fire on enemy armoured conveyors. Everywhere else, armoured behaves
# identically to regular conveyor.
CONVEYOR_LIKE = frozenset({EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR})

# How many destinations the bot will exhaust on (with the strict planner)
# before falling back to an early-connect reroute. The first N attempts pick
# the closest unseen-yet harvester/foundry candidate; only after N have all
# exhausted do we accept a possibly-distant early-goal connection.
MAX_DESTS_BEFORE_EARLY_CONNECT = 3


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
        # True after we've already retried an exhausted plan with
        # use_early_goals=True. Reset whenever determine() commits a fresh
        # (source, build_pos, dest) triple so each new plan gets one retry.
        self._exhaust_rerouted = False
        # Destinations the bot has already attempted and exhausted on the
        # strict planner. Used by find_destination to skip them so the next
        # determine() picks the next-closest candidate. Reset only on a
        # successful path completion — once we give up on a destination,
        # we don't want to immediately retry it next turn.
        self._tried_dests: list[Position] = []

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
            needs_replan = not self.conveyor_astar.validate_next_step(ct)
            replan_reason = "next step invalid" if needs_replan else None

            # Axionite-specific two-step lookahead: validate_next_step peeks
            # +1 but its truncation logic will silently splice into an
            # existing ally conveyor at the next planned tile, bypassing the
            # early_goal_only_titanium resource filter. Manually inspect +1
            # and +2 here and force a replan if any ally CONVEYOR has
            # appeared on the path — the new plan can route around it.
            if not needs_replan:
                path = getattr(self.conveyor_astar, '_path', None)
                path_index = getattr(self.conveyor_astar, '_path_index', 0)
                if path is not None:
                    my_team = ct.get_team()
                    for offset in (1, 2):
                        i = path_index + offset
                        if i >= len(path):
                            break
                        peek_pos = path[i].pos
                        px, py = peek_pos.x, peek_pos.y
                        if not (0 <= px < mm.width and 0 <= py < mm.height):
                            continue
                        rec = mm.building_grid[px][py]
                        if rec is None:
                            continue
                        if rec.team == my_team and rec.entity_type in CONVEYOR_LIKE:
                            needs_replan = True
                            replan_reason = f"unexpected ally conveyor at +{offset} ({px},{py})"
                            break

            if needs_replan:
                print(f"[ConvAStar/axionite] {replan_reason} — re-planning")
                saved_source_pos = self.source_pos
                saved_build_pos = self.build_pos
                saved_dest = self.dest
                self.conveyor_astar.invalidate()
                self.source = None
                self.source_pos = None
                self.build_pos = None
                if saved_build_pos is not None and saved_dest is not None:
                    # If the build_pos itself is no longer buildable (e.g. another
                    # bot placed a bridge there), replanning to the same tile loops
                    # forever — clear state and let determine() pick a new source.
                    if not _tile_buildable(saved_build_pos.x, saved_build_pos.y, mm,
                                          self.conveyor_astar.storage_tracker,
                                          ct.get_team(), mm.ally_core_pos,
                                          saved_dest, False):
                        bx, by = saved_build_pos.x, saved_build_pos.y
                        rec = mm.building_grid[bx][by]
                        exempt = False
                        if rec is not None and rec.entity_type in CONVEYOR_LIKE:
                            ddx, ddy = rec.direction.delta()
                            nx, ny = bx + ddx, by + ddy
                            points_to_source = (saved_source_pos is not None and nx == saved_source_pos.x and ny == saved_source_pos.y)
                            points_to_ore = (0 <= nx < mm.width and 0 <= ny < mm.height and
                                             mm.tile_grid[nx][ny] in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE))
                            if points_to_source or points_to_ore:
                                exempt = True
                        if not exempt:
                            print(f"[ConvAStar/axionite] build_pos {saved_build_pos} no longer buildable — clearing state")
                            self.dest = None
                            self.astar_turns_attempted = 0
                            return
                    src = saved_source_pos if saved_source_pos is not None else my_pos
                    self.conveyor_astar.plan_path(
                        ct, src, saved_build_pos, saved_dest,
                        use_early_goals=False,
                        use_core_exclusion=False,
                        avoid_harvester_adjacent=True,
                        avoid_harvester_ore=Environment.ORE_TITANIUM,
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
                # Path successfully built end-to-end — clear the tried-dest
                # memory so the next plan can target any candidate fresh.
                self._tried_dests = []
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

        # Exhaust handling. Two-phase fallback:
        #   1. Add the current dest to _tried_dests and clear the plan so
        #      determine() picks a different (next-closest, not-yet-tried)
        #      dest next turn. Repeat until MAX_DESTS_BEFORE_EARLY_CONNECT
        #      candidates have exhausted.
        #   2. Once the threshold is hit, retry the *current* dest with
        #      use_early_goals=True so allow_early is True from turn 1 and
        #      any titanium-only / raw-axionite-only conveyor in vision can
        #      land in the early-goal cache. early_goal_only_titanium=True
        #      keeps the resource filter on.
        # Bail-out: if the early-connect reroute itself exhausts, abandon
        # the plan (clear state) so the bot stops looping. _tried_dests is
        # NOT reset here — we don't want to immediately rediscover the same
        # dead candidates next turn.
        if self.conveyor_astar._exhausted:
            if not self._exhaust_rerouted:
                if self.dest is not None and self.dest not in self._tried_dests:
                    self._tried_dests.append(self.dest)

                if len(self._tried_dests) < MAX_DESTS_BEFORE_EARLY_CONNECT:
                    print(f"[ConvAStar/axionite] EXHAUSTED on {self.dest} ({len(self._tried_dests)}/{MAX_DESTS_BEFORE_EARLY_CONNECT}) — trying next dest")
                    self.build_pos = None
                    self.source = None
                    self.source_pos = None
                    self.dest = None
                    self.conveyor_astar.invalidate()
                    return

                if self.build_pos is not None and self.dest is not None:
                    print(f"[ConvAStar/axionite] {len(self._tried_dests)} dests tried — rerouting with use_early_goals=True on {self.dest}")
                    src = self.source_pos if self.source_pos is not None else my_pos
                    self.conveyor_astar.invalidate()
                    self.conveyor_astar.plan_path(
                        ct, src, self.build_pos, self.dest,
                        use_early_goals=True,
                        use_core_exclusion=False,
                        avoid_harvester_adjacent=True,
                        avoid_harvester_ore=Environment.ORE_TITANIUM,
                        early_goal_only_titanium=True,
                    )
                    self.source_pos = src
                    self._exhaust_rerouted = True
                    self.astar_turns_attempted = 0
                    return
            print("[ConvAStar/axionite] exhausted after reroute — abandoning plan")
            self.build_pos = None
            self.source = None
            self.source_pos = None
            self.dest = None
            self.conveyor_astar.invalidate()
            self._exhaust_rerouted = False
            return

        # Search still in progress (budget spent this turn, not exhausted) —
        # walk toward build_pos while the planner keeps expanding.
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
        for rec in mm.nearby_ally_foundry_ids:
            if rec.position == self.dest:
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
            # Once build_pos is in vision, revalidate it — another bot may have
            # built something here while we were walking toward it. Same exempt
            # logic as _execute_astar's validate_next_step branch: conveyors
            # pointing into our source or into ore are still buildable-over,
            # so we don't want to abandon the plan in those cases.
            if my_pos.distance_squared(self.build_pos) <= ct.get_vision_radius_sq():
                if not _tile_buildable(self.build_pos.x, self.build_pos.y, mm,
                                       self.conveyor_astar.storage_tracker,
                                       ct.get_team(), mm.ally_core_pos,
                                       self.dest, False):
                    bx, by = self.build_pos.x, self.build_pos.y
                    rec = mm.building_grid[bx][by]
                    exempt = False
                    if rec is not None and rec.entity_type in CONVEYOR_LIKE:
                        ddx, ddy = rec.direction.delta()
                        nx, ny = bx + ddx, by + ddy
                        points_to_source = (self.source_pos is not None
                                            and nx == self.source_pos.x
                                            and ny == self.source_pos.y)
                        points_to_ore = (0 <= nx < mm.width and 0 <= ny < mm.height and
                                         mm.tile_grid[nx][ny] in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE))
                        if points_to_source or points_to_ore:
                            exempt = True
                    if not exempt:
                        print(f"[axionite] build_pos {self.build_pos} no longer buildable — clearing state")
                        self.build_pos = None
                        self.source = None
                        self.source_pos = None
                        self.dest = None
                        self.conveyor_astar.invalidate()
                        return False
            if my_pos.distance_squared(self.source_pos) <= 9 and my_pos.distance_squared(self.build_pos) <= 9:
                # Membership by eid — record objects are rebuilt fresh each
                # turn so identity won't match last turn's reference.
                valid_source_ids = {
                    rec.id for rec in (
                        mm.nearby_ally_open_axionite_harvester_ids
                        + mm.nearby_ally_open_raw_axionite_conveyor_ids
                        + mm.nearby_ally_open_raw_axionite_bridge_ids
                    )
                }
                if self.source not in valid_source_ids:
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

        source_pos = source.position
        allies, enemies = self._count_nearby_builders(ct, mm, source_pos)
        if allies > enemies + 1:
            return False

        build_pos = self.get_build_pos(ct, source)
        if build_pos is None:
            return False
        if not _tile_buildable(build_pos.x, build_pos.y, mm,
                               self.conveyor_astar.storage_tracker,
                               ct.get_team(), mm.ally_core_pos,
                               dest, False):
            bx, by = build_pos.x, build_pos.y
            rec = mm.building_grid[bx][by]
            exempt = False
            if rec is not None and rec.entity_type in CONVEYOR_LIKE:
                ddx, ddy = rec.direction.delta()
                nx, ny = bx + ddx, by + ddy
                points_to_source = (nx == source_pos.x and ny == source_pos.y)
                points_to_ore = (0 <= nx < mm.width and 0 <= ny < mm.height and
                                 mm.tile_grid[nx][ny] in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE))
                if points_to_source or points_to_ore:
                    exempt = True
            if not exempt:
                return False

        # `self.source` stores eid for cross-turn membership checks.
        self.source = source.id
        self.source_pos = source_pos
        self.build_pos = build_pos
        self.dest = dest
        # Fresh plan committed — allow one exhaust-reroute retry on this triple.
        self._exhaust_rerouted = False

        print("dist to dest: ", ct.get_position().distance_squared(dest))
        print("build pos: ", self.build_pos)
        print("dest pos: ", self.dest)

        if source.entity_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER):
            self.prev_dir = source.direction
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
                avoid_harvester_ore=Environment.ORE_TITANIUM,
                early_goal_only_titanium=True,
            )

        state_manager.current_state = BuilderState.CONNECT_AXIONITE_STATE
        return True

    # ── Destination / source finding (unchanged from original) ───────────────

    def find_destination(self, ct):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        bridge_targets = mm.nearby_ally_raw_axionite_bridge_targets
        storage_tracker = self.brain.storage_tracker
        tried = self._tried_dests
        best_pos = None
        best_dist = float('inf')
        for pos in mm.seen_adjacent_harvester_conveyor_positions:
            if pos in tried:
                continue
            already_connected = False
            for t in bridge_targets:
                if t == pos:
                    already_connected = True
                    break
            if already_connected:
                continue
            # Same rule as conveyor_astar early-connect: only accept
            # conveyors whose recent_resources is a subset of {TITANIUM}
            # or {RAW_AXIONITE}. A mixed belt or one with refined axionite
            # in its history is not a valid splice target. Skipped when
            # the building isn't a conveyor (likely stale set entry).
            b = mm.building_grid[pos.x][pos.y]
            if b is not None and b.entity_type in CONVEYOR_LIKE:
                recent = storage_tracker.get_recent_resources(b.id)
                ti_only = recent <= {ResourceType.TITANIUM}
                raw_ax_only = recent <= {ResourceType.RAW_AXIONITE}
                if not (ti_only or raw_ax_only):
                    continue
            dist = my_pos.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos

        for pos in mm.seen_no_axionite_foundry_positions:
            if pos in tried:
                continue
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
            for rec in mm.nearby_ally_foundry_ids:
                pos = rec.position
                if pos in tried:
                    continue
                dist = my_pos.distance_squared(pos)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = pos

        return best_pos

    def find_source(self, ct):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        best_rec = None
        best_dist = float('inf')
        for rec in (mm.nearby_ally_open_axionite_harvester_ids
                    + mm.nearby_ally_open_raw_axionite_conveyor_ids
                    + mm.nearby_ally_open_raw_axionite_bridge_ids):
            dist = my_pos.distance_squared(rec.position)
            if dist < best_dist:
                best_dist = dist
                best_rec = rec
        return best_rec

    def get_build_pos(self, ct: Controller, rec):
        unit_type = rec.entity_type
        if unit_type == EntityType.HARVESTER:
            return self.get_harvester_build_pos(ct, rec)
        elif unit_type == EntityType.FOUNDRY:
            return self.get_foundry_build_pos(ct, rec)
        elif unit_type == EntityType.CONVEYOR:
            return self.get_conv_build_pos(ct, rec)
        elif unit_type == EntityType.ARMOURED_CONVEYOR:
            return self.get_conv_build_pos(ct, rec)
        elif unit_type == EntityType.BRIDGE:
            return self.get_bridge_build_pos(ct, rec)
        elif unit_type == EntityType.SPLITTER:
            return self.get_splitter_build_pos(ct, rec)

    def get_harvester_build_pos(self, ct: Controller, rec):
        mm: MapManager = self.brain.map_manager
        harv_pos = rec.position
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

    def get_conv_build_pos(self, ct: Controller, rec):
        return rec.position.add(rec.direction)

    def get_bridge_build_pos(self, ct: Controller, rec):
        return rec.output_target

    def get_splitter_build_pos(self, ct, rec):
        return rec.position.add(rec.direction)

    def get_foundry_build_pos(self, ct, rec):
        return rec.position