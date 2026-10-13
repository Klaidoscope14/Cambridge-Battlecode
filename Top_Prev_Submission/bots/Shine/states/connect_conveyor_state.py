from cambc import Controller, EntityType, Direction, Position, Environment, ResourceType, GameConstants

from debug.profiling import cputimer
from helpers.directions import CARDINAL, DIRECTIONS
from roles.builder.helpers import in_bounds
from nav.common import common_path
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from conveyor.conveyor_astar import ConveyorAStar
from map.map_manager import MapManager
from harvesters.constants import AXIONITE_MIN_ROUND

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER, EntityType.CONVEYOR]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.SPLITTER, EntityType.BRIDGE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
BRIDGE_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]

# Ally belt types that can feed into a build pos (used by the enemy-reroute
# logic to locate the tile to destroy behind the current build pos).
_BELT_FEEDER_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
})

class ConnectConveyorState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.SOURCE_TYPES = [EntityType.HARVESTER, EntityType.BRIDGE, EntityType.CONVEYOR]
        self.prev_dir = None
        self.source = None
        self.source_pos = None
        self.source_resource = None
        self.build_pos = None
        self.dest = None
        self.path_builder = PathBuilder(ct, brain)
        self.conveyor_astar = ConveyorAStar(ct, brain)

        self.astar_turns_attempted = 0

        # Most recently confirmed built position — survives replans so the
        # enemy-reroute logic can destroy the tile feeding into the current
        # build pos. Updated each time a build step succeeds; cleared after
        # it gets consumed by a reroute.
        self._last_built_pos: Position | None = None

        # Enemy-reroute mode: when True, plan_path is called with
        # avoid_enemy=True so the planner steers clear of enemy tiles and
        # grabs any early-goal connection it can find. Cleared when the
        # resulting path completes.
        self._avoid_enemy: bool = False

    # ── Enemy-reroute helpers ────────────────────────────────────────────

    def _is_enemy_contested(self, mm: MapManager, build_pos: Position) -> bool:
        """True when build_pos is an enemy-owned ROAD with an enemy bot
        cardinally adjacent. Signal to bail on the current build pos and
        reroute around the contested tile.
        """
        w, h = mm.width, mm.height
        x, y = build_pos.x, build_pos.y
        if not (0 <= x < w and 0 <= y < h):
            return False
        building = mm.building_grid[x][y]
        if building is None:
            return False
        my_team = self.ct.get_team()
        if building.team == my_team:
            return False
        if building.entity_type != EntityType.ROAD:
            return False
        for d in CARDINAL:
            dx, dy = d.delta()
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            bot = mm.bot_grid[nx][ny]
            if bot is not None and bot.team != my_team:
                return True
        return False

    def _find_feeder_into(self, mm: MapManager, build_pos: Position) -> Position | None:
        """Locate the ally belt/bridge currently outputting INTO build_pos.

        Used as a destruction target when _last_built_pos has been lost or
        never set (e.g. the very first step of a fresh plan).
        """
        w, h = mm.width, mm.height
        x, y = build_pos.x, build_pos.y
        my_team = self.ct.get_team()

        for d in CARDINAL:
            dx, dy = d.delta()
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            rec = mm.building_grid[nx][ny]
            if rec is None or rec.team != my_team:
                continue
            if rec.entity_type in _BELT_FEEDER_TYPES:
                rdx, rdy = rec.direction.delta()
                if (nx + rdx, ny + rdy) == (x, y):
                    return Position(nx, ny)

        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx == 0 and dy == 0 or dx * dx + dy * dy > 9:
                    continue
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                rec = mm.building_grid[nx][ny]
                if rec is None or rec.team != my_team:
                    continue
                if rec.entity_type == EntityType.BRIDGE:
                    tgt = getattr(rec, 'output_target', None)
                    if tgt is not None and tgt.x == x and tgt.y == y:
                        return Position(nx, ny)
        return None

    def _trigger_reroute(self, ct: Controller, mm: MapManager, build_pos: Position) -> None:
        """Destroy the feeder tile behind the contested build pos, invalidate
        the current A* plan, and flip avoid-enemy mode on so the next plan_path
        call routes around the enemy and grabs any early-goal connection.
        """
        print(f"[ConvAStar] ENEMY DETECTED at build_pos {build_pos} — rerouting")

        target = self._last_built_pos
        source_label = "last_built_pos"
        if target is None or mm.get_building(target) is None:
            target = self._find_feeder_into(mm, build_pos)
            source_label = "feeder_into"

        if target is not None and ct.can_destroy(target):
            ct.destroy(target)
            print(f"[ConvAStar] DESTROYED old build pos {target} ({source_label})")
            # Drop a road on the freshly cleared tile so the bot still has a
            # traversable surface while the new path is being planned. Without
            # this the tile is left bare — bots have to pay the road cost to
            # cross it again, and allies lose the shared walkway.
            if ct.can_build_road(target):
                ct.build_road(target)
                print(f"[ConvAStar] ROAD placed on {target}")
        else:
            print(f"[ConvAStar] no destroy target available (target={target})")

        self._last_built_pos = None
        self._avoid_enemy = True
        self.conveyor_astar.invalidate()
        # Clear the local source/build tracking so determine() picks a fresh
        # source on the next call — the current build pos is contested and
        # pushing the same source again would just loop.
        self.source = None
        self.source_pos = None
        self.build_pos = None

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

    def execute(self, ct: Controller):
        print("build pos: ", self.build_pos)
        print("dest: ", self.dest)
        my_pos = ct.get_position()

        # After round 100, use the old greedy PathBuilder (proven reliable)
        # if ct.get_current_round() >= 100:
        #     return self._execute_old(ct, my_pos)

        print("source id: ", self.source)
        return self._execute_astar(ct, my_pos)

    def _execute_astar(self, ct: Controller, my_pos: Position):
        """A* path planner — used in early game (< round 100)."""
        mm: MapManager = self.brain.map_manager

        if mm.newly_seen:
            self.conveyor_astar.handle_newly_seen(mm)

        # If A* has a complete path, follow it
        if self.conveyor_astar.is_complete():
            print("ASTAR PATH BUILDER")
            self.astar_turns_attempted = 0
            if not self.conveyor_astar.validate_next_step(ct):
                print("[ConvAStar] next step invalid, re-planning")
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
                        avoid_enemy=self._avoid_enemy,
                        source_resource=self.source_resource,
                    )
                    self.build_pos = saved_build_pos
                    self.source_pos = src
                    self.dest = saved_dest
                self.astar_turns_attempted = 0
                return

            step = self.conveyor_astar.get_next_build_step()
            if step is None:
                # Path fully built — reroute (if any) has succeeded, clear mode.
                self._avoid_enemy = False
                self.build_pos = None
                self.source = None
                self.source_pos = None
                self.conveyor_astar.invalidate()
                return

            # Enemy-reroute check: if the upcoming build pos is an enemy road
            # with an adjacent enemy bot, destroy the feeder behind us and
            # replan with avoid_enemy=True so the next path steers clear.
            if self._is_enemy_contested(mm, step.pos):
                print(f"[ConvAStar] REROUTE: build_pos {step.pos} is enemy road with adj enemy bot")
                self._trigger_reroute(ct, mm, step.pos)
                return

            build_pos = step.pos
            if abs(my_pos.x - build_pos.x) <= 1 and abs(my_pos.y - build_pos.y) <= 1:
                #print(f"[ConvAStar] building step: {step}")
                built = self._execute_build_step(ct, step)
                if built:
                    self.conveyor_astar.advance()
                    # Record the tile we just confirmed built. The next reroute
                    # will destroy this as the feeder into whatever comes next.
                    self._last_built_pos = build_pos
                    self.build_pos = None
                    self.source = None
                    self.source_pos = None
                else:
                    pass
                    #print(f"[ConvAStar] build FAILED at {build_pos}, will retry")
            else:
                #print(f"[ConvAStar] moving to build pos {build_pos}")
                common_path(ct, mm, self.brain.pathing, build_pos)
            return
        else:
            self.astar_turns_attempted += 1
        # A* still computing — expand this turn
        found = self.conveyor_astar.expand_turn(ct)
        if found:
            #print("[ConvAStar] path found this turn!")
            return

        # Fallback while A* computes
        if self.astar_turns_attempted > 10:
            # self.build_pos = None
            # self.source = None
            # self.source_pos = None
            pass
            
        else:
            pass
            #common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)

    def _execute_old(self, ct: Controller, my_pos: Position):
        """Old greedy PathBuilder — used after round 100 and as A* fallback."""
        if abs(my_pos.x - self.build_pos.x) <= 1 and abs(my_pos.y - self.build_pos.y) <= 1:
            self.path_builder.connect_and_move(ct, self.prev_dir, self.source, self.build_pos, self.dest, False, False)
            self.build_pos = None
            self.source = None
            self.source_pos = None
            self.conveyor_astar.invalidate()
        else:
            common_path(ct, self.brain.map_manager, self.brain.pathing, self.build_pos)

    def _execute_build_step(self, ct: Controller, step) -> bool:
        """Execute a single build step, handling obstacles. Returns True if built.

        Reuses the same obstacle-handling logic from PathBuilder.connect_and_move():
        - Empty tile: build then move
        - Enemy fireable: move, fire, build
        - Ally destroyable: destroy, build, move
        """
        build_pos = step.pos
        my_pos = ct.get_position()
        move_dir = my_pos.direction_to(build_pos)
        tile_id = ct.get_tile_building_id(build_pos)

        # Wall (shouldn't happen, A* avoids walls)
        if ct.get_tile_env(build_pos) == Environment.WALL:
            return False

        # Empty tile
        if tile_id is None:
            built = self._build_step(ct, step)
            if built and ct.can_move(move_dir):
                ct.move(move_dir)
            return built

        # Enemy fireable — clear then build
        if ct.get_team(tile_id) != ct.get_team() and ct.get_entity_type(tile_id) in ENEMY_FIREABLE_TYPES:
            if my_pos != build_pos and ct.can_move(move_dir):
                ct.move(move_dir)
            if ct.can_fire(build_pos):
                ct.fire(build_pos)
            return self._build_step(ct, step)

        # Ally destroyable — destroy then build
        if ct.get_team(tile_id) == ct.get_team() and ct.get_entity_type(tile_id) in ALLY_DESTROYABLE_TYPES:
            cost = ct.get_bridge_cost()[0] if step.build_type == EntityType.BRIDGE else ct.get_conveyor_cost()[0]
            if ct.get_global_resources()[0] >= cost:
                if ct.can_destroy(build_pos):
                    ct.destroy(build_pos)
                built = self._build_step(ct, step)
                if built and ct.can_move(move_dir):
                    ct.move(move_dir)
                return built
            return False  # Not enough resources

        # Ally unit is standing on the tile (bot, not a building) — the tile
        # itself may be empty underneath. Try to build; the ally will move away
        # next turn. If the building is ours and destroyable, destroy first.
        if ct.get_team(tile_id) == ct.get_team():
            if ct.can_destroy(build_pos):
                ct.destroy(build_pos)
            built = self._build_step(ct, step)
            if built and ct.can_move(move_dir):
                ct.move(move_dir)
            return built

        # Something unexpected at build_pos
        print("BUILD STEP RETURN FALSE")
        return False

    def _build_step(self, ct: Controller, step) -> bool:
        """Build a conveyor or bridge from a BuildStep. Returns True if built."""
        if step.build_type == EntityType.CONVEYOR:
            if ct.can_build_conveyor(step.pos, step.direction):
                ct.build_conveyor(step.pos, step.direction)
                return True
        elif step.build_type == EntityType.BRIDGE:
            if ct.can_build_bridge(step.pos, step.bridge_target):
                ct.build_bridge(step.pos, step.bridge_target)
                return True
        return False

    @cputimer
    def determine(self, ct: Controller, state_manager):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()

        print(f"Build pos is currently {self.build_pos}")

        if self.build_pos != None:
            if my_pos.distance_squared(self.source_pos) <= GameConstants.BUILDER_BOT_VISION_RADIUS_SQ and my_pos.distance_squared(self.build_pos) <= GameConstants.BUILDER_BOT_VISION_RADIUS_SQ:
                if self.source not in self._get_all_open_sources(ct, mm):
                    self.build_pos = None
                    self.source = None
                    self.source_pos = None
                    self.conveyor_astar.invalidate()
                    return False

                allies, enemies = self._count_nearby_builders(ct, mm, self.build_pos)
                if allies <= enemies + 1:
                    if not self.conveyor_astar.is_planned_for_dest(self.dest):
                        self.conveyor_astar.plan_path(
                            ct, self.source_pos, self.build_pos, self.dest,
                            avoid_enemy=self._avoid_enemy,
                            source_resource=self.source_resource,
                        )
                    state_manager.current_state = BuilderState.CONNECT_CONVEYOR
                    return True
                else:
                    self.build_pos = None
                    self.source = None
                    self.source_pos = None
                    self.conveyor_astar.invalidate()
                    return False
            else:
                if not self.conveyor_astar.is_planned_for_dest(self.dest):
                    self.conveyor_astar.plan_path(
                        ct, self.source_pos, self.build_pos, self.dest,
                        avoid_enemy=self._avoid_enemy,
                        source_resource=self.source_resource,
                    )
                state_manager.current_state = BuilderState.CONNECT_CONVEYOR
                return True

        source = self.get_closest_source(ct)
        self.source = source

        if source != None:
            source_pos = mm.id_to_pos[source]
            self.source_pos = source_pos
            allies, enemies = self._count_nearby_builders(ct, mm, source_pos)

            if allies > enemies + 1:
                return False

            build_pos = self.get_build_pos(ct, source)
            if build_pos == None:
                return False
            source_rec = mm.id_to_record[source]
            if source_rec.entity_type in [EntityType.CONVEYOR, EntityType.SPLITTER]:
                self.prev_dir = source_rec.direction
            else:
                self.prev_dir = None
            # Stash the source's carried resource so plan_path can apply the
            # "titanium chains never merge into raw axionite" rule.
            self.source_resource = getattr(source_rec, 'stored_resource', None)
            self.build_pos = build_pos
            self.dest = self.brain.map_manager.ally_core_pos
            # Seed the reroute destroy target for fresh chains. If the very
            # first build pos turns out to be enemy-contested we need something
            # to tear down behind us — the source itself is the feeder.
            if self._last_built_pos is None:
                self._last_built_pos = source_pos

            if not self.conveyor_astar.is_planned_for_dest(self.dest):
                self.conveyor_astar.plan_path(
                    ct, self.source_pos, self.build_pos, self.dest,
                    avoid_enemy=self._avoid_enemy,
                    source_resource=self.source_resource,
                )

            state_manager.current_state = BuilderState.CONNECT_CONVEYOR
            return True
        return False
    
    def get_build_pos(self, ct: Controller, eid):
        unit_type = self.brain.map_manager.id_to_record[eid].entity_type
        if unit_type == EntityType.HARVESTER:
            return self.get_harvester_build_pos(ct, eid)
        if unit_type == EntityType.FOUNDRY:
            return self.get_harvester_build_pos(ct, eid)
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
        core_pos = mm.ally_core_pos
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
            dist = adj_pos.distance_squared(core_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = adj_pos

        if best_pos != None:
            return best_pos

        for d in CARDINAL:
            adj_pos = harv_pos.add(d)
            ax = adj_pos.x
            ay = adj_pos.y
            if not (0 <= ax < width and 0 <= ay < height):
                continue
            if my_pos.distance_squared(adj_pos) > vision_sq:
                continue
            adj_env = tile_grid[ax][ay]
            if adj_env == Environment.WALL:
                continue
            adj_rec = building_grid[ax][ay]
            if adj_rec is not None and adj_rec.entity_type in ALLY_BLOCKING_TYPES:
                continue
            dist = adj_pos.distance_squared(core_pos)
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
    
    def _get_all_open_sources(self, ct: Controller, mm: MapManager):
        if ct.get_current_round() > AXIONITE_MIN_ROUND:
            return mm.nearby_ally_open_refined_axionite_conveyor_ids + mm.nearby_ally_open_refined_axionite_bridge_ids + mm.nearby_ally_open_titanium_bridge_ids + mm.nearby_ally_open_titanium_conveyor_ids + mm.nearby_ally_open_titanium_harvester_ids + mm.nearby_ally_open_splitter_ids + mm.nearby_ally_open_foundry_ids
        else:
            return mm.nearby_ally_open_titanium_conveyor_ids + mm.nearby_ally_open_bridge_ids + mm.nearby_ally_open_titanium_harvester_ids + mm.nearby_ally_open_splitter_ids + mm.nearby_ally_open_foundry_ids + mm.nearby_ally_open_empty_conveyor_ids + mm.nearby_ally_open_titanium_harvester_ids

    def get_closest_source(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        all_nearby_sources = self._get_all_open_sources(ct, mm)
        my_pos = ct.get_position()
        id_to_pos = mm.id_to_pos
        id_to_record = mm.id_to_record
        best_id = None
        best_dist = float('inf')
        for eid in all_nearby_sources:
            rec = id_to_record[eid]
            if rec.entity_type == EntityType.BRIDGE and rec.stored_resource == ResourceType.RAW_AXIONITE:
                continue
            dist = my_pos.distance_squared(id_to_pos[eid])
            if dist < best_dist:
                best_dist = dist
                best_id = eid
        return best_id