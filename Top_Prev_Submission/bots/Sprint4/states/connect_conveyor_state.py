from cambc import Controller, EntityType, Direction, Position, Environment, ResourceType
from helpers.directions import CARDINAL, DIRECTIONS
from roles.builder.helpers import in_bounds
from nav.common import common_path
from states.builder_state import BuilderState
from conveyor.path_builder import PathBuilder
from conveyor.conveyor_astar import ConveyorAStar
from map.map_manager import MapManager

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
BRIDGE_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]

class ConnectConveyorState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.SOURCE_TYPES = [EntityType.HARVESTER, EntityType.BRIDGE, EntityType.CONVEYOR]
        self.prev_dir = None
        self.source = None
        self.build_pos = None
        self.dest = None
        self.path_builder = PathBuilder(ct, brain)
        self.conveyor_astar = ConveyorAStar(ct, brain)

    def execute(self, ct: Controller):
        print("build pos: ", self.build_pos)
        print("dest: ", self.dest)
        my_pos = ct.get_position()

        # After round 100, use the old greedy PathBuilder (proven reliable)
        if ct.get_current_round() >= 100:
            return self._execute_old(ct, my_pos)

        # Before round 100, use A* planner
        return self._execute_astar(ct, my_pos)

    def _execute_astar(self, ct: Controller, my_pos: Position):
        """A* path planner — used in early game (< round 100)."""
        mm: MapManager = self.brain.map_manager

        if mm.newly_seen:
            self.conveyor_astar.handle_newly_seen(mm)

        # If A* has a complete path, follow it
        if self.conveyor_astar.is_complete():
            if not self.conveyor_astar.validate_next_step(ct):
                print("[ConvAStar] next step invalid, re-planning")
                self.conveyor_astar.invalidate()
                self.build_pos = None
                self.source = None
                return

            step = self.conveyor_astar.get_next_build_step()
            if step is None:
                self.build_pos = None
                self.source = None
                self.conveyor_astar.invalidate()
                return

            build_pos = step.pos
            if abs(my_pos.x - build_pos.x) <= 1 and abs(my_pos.y - build_pos.y) <= 1:
                print(f"[ConvAStar] building step: {step}")
                built = self._execute_build_step(ct, step)
                if built:
                    self.conveyor_astar.advance()
                    self.build_pos = None
                    self.source = None
                else:
                    print(f"[ConvAStar] build FAILED at {build_pos}, will retry")
            else:
                print(f"[ConvAStar] moving to build pos {build_pos}")
                common_path(ct, mm, self.brain.pathing, build_pos)
            return

        # A* still computing — expand this turn
        found = self.conveyor_astar.expand_turn(ct)
        if found:
            print("[ConvAStar] path found this turn!")
            return

        # Fallback while A* computes
        self._execute_old(ct, my_pos)

    def _execute_old(self, ct: Controller, my_pos: Position):
        """Old greedy PathBuilder — used after round 100 and as A* fallback."""
        if abs(my_pos.x - self.build_pos.x) <= 1 and abs(my_pos.y - self.build_pos.y) <= 1:
            self.path_builder.connect_and_move(ct, self.prev_dir, self.source, self.build_pos, self.dest, False, False)
            self.build_pos = None
            self.source = None
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

        # Something unexpected at build_pos
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

    def determine(self, ct: Controller, state_manager):
        if self.build_pos != None:
            state_manager.current_state = BuilderState.CONNECT_CONVEYOR
            return True
        
        source = self.get_closest_source(ct)
        self.source = source

        if source != None:
            mm: MapManager = self.brain.map_manager
            my_pos = ct.get_position()
            my_team = ct.get_team()
            source_pos = ct.get_position(source)
            ally_builder_nearby = False
            enemy_builder_nearby = False
            positions_to_check = [source_pos] + [source_pos.add(d) for d in DIRECTIONS]
            
            for check_pos in positions_to_check:
                if not in_bounds(ct, check_pos):
                    continue
                if my_pos.distance_squared(check_pos) > ct.get_vision_radius_sq():
                    continue
                bot_record = mm.bot_grid[check_pos.x][check_pos.y]
                if bot_record is None:
                    continue
                if bot_record.team == my_team and bot_record.id > ct.get_id():
                    ally_builder_nearby = True
                else:
                    enemy_builder_nearby = True

            if ally_builder_nearby and not enemy_builder_nearby:
                return False

            build_pos = self.get_build_pos(ct, source)
            if build_pos == None:
                return False
            if ct.get_entity_type(source) in [EntityType.CONVEYOR, EntityType.SPLITTER]:
                self.prev_dir = ct.get_direction(source)
            else:
                self.prev_dir = None
            self.build_pos = build_pos
            self.dest = self.brain.map_manager.ally_core_pos
            print(f"ALLY CORE POS IS {self.brain.map_manager.ally_core_pos}")

            # Use A* planner only before round 100
            if ct.get_current_round() < 100:
                if not self.conveyor_astar.is_planned_for_dest(self.dest):
                    self.conveyor_astar.plan_path(ct, self.build_pos, self.dest)

            state_manager.current_state = BuilderState.CONNECT_CONVEYOR
            return True
        return False
    
    def get_build_pos(self, ct: Controller, eid):
        unit_type = ct.get_entity_type(eid)
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
        harv_pos = ct.get_position(eid)
        best_pos = None
        best_dist = float('inf')
        core_pos = self.brain.map_manager.ally_core_pos
        
        for d in CARDINAL:
            adj_pos = harv_pos.add(d)
            if ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq() or not in_bounds(ct, adj_pos):
                continue
            adj_eid = ct.get_tile_building_id(adj_pos)
            adj_env = ct.get_tile_env(adj_pos)
            if adj_env in BLOCKING_ENVIRONMENT_TYPES:
                continue
            if adj_eid is not None and ct.get_entity_type(adj_eid) in ALLY_BLOCKING_TYPES:
                continue
            dist = adj_pos.distance_squared(core_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = adj_pos
        
        if best_pos != None:
            return best_pos
        
        for d in CARDINAL:
            adj_pos = harv_pos.add(d)
            if ct.get_position().distance_squared(adj_pos) > ct.get_vision_radius_sq() or not in_bounds(ct, adj_pos):
                continue
            adj_eid = ct.get_tile_building_id(adj_pos)
            adj_env = ct.get_tile_env(adj_pos)
            if adj_env == Environment.WALL:
                continue
            if adj_eid is not None and ct.get_entity_type(adj_eid) in ALLY_BLOCKING_TYPES:
                continue
            dist = adj_pos.distance_squared(core_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = adj_pos
        
        return best_pos
        
    def get_conv_build_pos(self, ct: Controller, eid):
        pos = ct.get_position(eid).add(ct.get_direction(eid))
        return pos
        
    def get_bridge_build_pos(self, ct: Controller, eid):
        pos = ct.get_bridge_target(eid)
        return pos
    
    def get_splitter_build_pos(self, ct, eid):
        pos = ct.get_position(eid).add(ct.get_direction(eid))
        return pos
    
    def get_closest_source(self, ct: Controller):
        mm: MapManager = self.brain.map_manager
        if ct.get_current_round() > 700:
            all_nearby_sources = mm.nearby_ally_open_refined_axionite_conveyor_ids + mm.nearby_ally_open_refined_axionite_bridge_ids + mm.nearby_ally_open_titanium_bridge_ids + mm.nearby_ally_open_titanium_conveyor_ids + mm.nearby_ally_open_titanium_harvester_ids + mm.nearby_ally_open_splitter_ids + mm.nearby_ally_open_foundry_ids
        else:
            all_nearby_sources = mm.nearby_ally_open_conveyor_ids + mm.nearby_ally_open_bridge_ids + mm.nearby_ally_open_titanium_harvester_ids + mm.nearby_ally_open_splitter_ids + mm.nearby_ally_open_foundry_ids
        
        best_id = None
        best_dist = float('inf')
        for eid in all_nearby_sources:
            dist = ct.get_position().distance_squared(ct.get_position(eid))
            if ct.get_entity_type(eid) == EntityType.BRIDGE and ct.get_stored_resource(eid) == ResourceType.RAW_AXIONITE:
                continue
            if dist < best_dist:
                best_dist = dist
                best_id = eid
        return best_id if best_id is not None else None