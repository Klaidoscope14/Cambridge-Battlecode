from cambc import Controller, EntityType, Environment, Position, Direction, ResourceType
from helpers.directions import CARDINAL
from roles.builder.helpers import in_bounds
from vision.storage_tracker import StorageTracker

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.BARRIER]
BRIDGE_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.BARRIER]

# Armoured conveyors behave identically to regular conveyors for feeder/sink/
# receivable/path-type semantics. They are deliberately omitted from
# ENEMY_FIREABLE_TYPES because builder bots cannot fire on them.
CONVEYOR_LIKE = frozenset({EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR})

SPLITTER_OFFSET = 2

class PathBuilder:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.recent_connection = int | None
        self.splitter_offset_tracker = 1
        self.storage_tracker: StorageTracker = brain.storage_tracker

    def _find_early_goal(self, ct: Controller, build_pos: Position, dest: Position) -> Position | None:
        """Scan cardinal neighbors of build_pos for a receivable ally conveyor/bridge
        that is closer to dest than build_pos itself.  Mirrors the A* early-goal
        logic so the greedy fallback behaves consistently with the planner.

        Returns the best neighbour position, or None if not found.
        Only called when use_early_goals=True (never for isolated axionite paths).
        """
        build_dist = build_pos.distance_squared(dest)
        best_pos = None
        best_dist = float('inf')
        for d in CARDINAL:
            neighbor = build_pos.add(d)
            if not self.in_vision_and_bounds(ct, neighbor):
                continue
            # Must be closer to dest than build_pos (moving in the right direction)
            ndist = neighbor.distance_squared(dest)
            if ndist >= build_dist:
                continue
            tile_id = ct.get_tile_building_id(neighbor)
            if tile_id is None:
                continue
            if ct.get_team(tile_id) != ct.get_team():
                continue
            etype = ct.get_entity_type(tile_id)
            if etype not in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER):
                continue
            if self.storage_tracker.is_full(tile_id):
                continue
            if ct.get_stored_resource(tile_id) == ResourceType.RAW_AXIONITE:
                continue
            if ndist < best_dist:
                best_dist = ndist
                best_pos = neighbor
        return best_pos

    def connect_and_move(self, ct: Controller, prev_conv_dir: Direction, source_id,
                         build_pos: Position, dest: Position,
                         isolate=False, bridge_on_dest=False,
                         use_early_goals=True):
        my_pos = ct.get_position()
        move_dir = my_pos.direction_to(build_pos)

        # Early-goal shortcut: if there is already a receivable ally conveyor/bridge
        # cardinally adjacent to build_pos and closer to dest, point into it now
        # rather than continuing to build a fresh path.  Skipped when
        # use_early_goals=False (axionite paths must always reach their destination).
        if use_early_goals:
            early_goal = self._find_early_goal(ct, build_pos, dest)
            if early_goal is not None:
                print("path_builder early goal: ", early_goal)
                conv_dir = self.cardinal_direction_to(build_pos, early_goal)
            else:
                conv_dir = self.get_conveyor_dir(build_pos, dest, prev_conv_dir)
        else:
            conv_dir = self.get_conveyor_dir(build_pos, dest, prev_conv_dir)

        tile_id = ct.get_tile_building_id(build_pos)

        # if wall or non buildable block on the location
        if ct.get_tile_env(build_pos) in BLOCKING_ENVIRONMENT_TYPES:
            pass
        # if empty tile
        elif tile_id is None:
            path_type = self.get_path_type(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, isolate, bridge_on_dest)
            if self.build_conv_or_bridge(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, isolate, path_type) and ct.can_move(move_dir):
                ct.move(move_dir)

        # if we need to break an enemy tile on the building pos first
        elif ct.get_team(tile_id) != ct.get_team() and ct.get_entity_type(tile_id) in ENEMY_FIREABLE_TYPES:
            if my_pos != build_pos and ct.can_move(move_dir):
                ct.move(move_dir)
            if ct.can_fire(build_pos):
                ct.fire(build_pos)
            path_type = self.get_path_type(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, isolate, bridge_on_dest)
            self.build_conv_or_bridge(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, isolate, path_type)

        # if we need to destroy an ally tile on the building pos first
        elif ct.get_team(tile_id) == ct.get_team() and ct.get_entity_type(tile_id) in ALLY_DESTROYABLE_TYPES:
            path_type = self.get_path_type(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, isolate, bridge_on_dest)
            cost = ct.get_bridge_cost()[0] if path_type == EntityType.BRIDGE else ct.get_conveyor_cost()[0]
            if ct.get_global_resources()[0] >= cost:
                if ct.can_destroy(build_pos):
                    ct.destroy(build_pos)
                if self.build_conv_or_bridge(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, isolate, path_type) and ct.can_move(move_dir):
                    ct.move(move_dir)
        print("build pos: ", build_pos)

    def get_path_type(self, ct: Controller, source_id, build_pos: Position, dest: Position, conv_dir: Direction, prev_conv_dir: Direction, isolate: bool, bridge_on_dest: bool) -> EntityType:
        # if target of build position would end being a wall or an blocking entity, we should build a bridge instead of a conveyor
        target: Position = build_pos.add(conv_dir)
        add_block = []
        if dest != self.brain.map_manager.ally_core_pos:
            add_block = [EntityType.CORE]
        if not in_bounds(ct, target):
            return None
        target_id = ct.get_tile_building_id(target)
        if not self.in_vision_and_bounds(ct, target):
            return None

        if bridge_on_dest and build_pos.distance_squared(dest) <= 9:
            return EntityType.BRIDGE
        elif ct.get_tile_env(target) in BLOCKING_ENVIRONMENT_TYPES:
            return EntityType.BRIDGE
        elif build_pos.distance_squared(dest) == 1:
            return EntityType.CONVEYOR
        elif target_id != None and ct.get_team() == ct.get_team(target_id) and ct.get_entity_type(target_id) in ALLY_BLOCKING_TYPES + add_block:
            return EntityType.BRIDGE
        elif target_id != None and ct.get_team() != ct.get_team(target_id) and ct.get_entity_type(target_id) in ENEMY_BLOCKING_TYPES + add_block:
            return EntityType.BRIDGE
        elif target_id != None and ct.get_entity_type(target_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR) and self.storage_tracker.is_full(target_id):
            return EntityType.BRIDGE
        elif target_id != None and ct.get_entity_type(target_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR) and ct.get_stored_resource(target_id) == ResourceType.RAW_AXIONITE:
            return EntityType.BRIDGE
        elif target_id != None and isolate and ct.get_entity_type(target_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER):
            return EntityType.BRIDGE
        else:
            return EntityType.CONVEYOR

    def build_conv_or_bridge(self, ct: Controller, source_id, build_pos: Position, dest: Position, conv_dir: Direction, prev_conv_dir: Direction, isolate: bool, path_type: EntityType | None) -> bool:
        # if target of build position would end being a wall or an blocking entity, we should build a bridge instead of a conveyor
        if EntityType == None:
            return False
        target: Position = build_pos.add(conv_dir)

        if not in_bounds(ct, target):
            return False
        if not self.in_vision_and_bounds(ct, target):
            return False

        if path_type == EntityType.BRIDGE:
            target = self.get_bridge_target(ct, source_id, build_pos, dest, isolate)
            print("bridge target: ", target)
            if ct.can_build_bridge(build_pos, target):
                ct.build_bridge(build_pos, target)
                return True

        elif path_type == EntityType.CONVEYOR:
            if ct.can_build_conveyor(build_pos, conv_dir):
                ct.build_conveyor(build_pos, conv_dir)
                return True

        return False

    def get_conveyor_dir(self, build_pos, dest, prev_conv_dir):
        if build_pos.x == dest.x or build_pos.y == dest.y or prev_conv_dir == None:
            return self.cardinal_direction_to(build_pos, dest)
        return prev_conv_dir

    def get_bridge_target(self, ct: Controller, source_id, source: Position, dest: Position, isolate):
        nearby_pos = self.brain.map_manager.nearby_positions
        best_pos = None
        best_dist = float('inf')
        add_bridge_block = []
        if dest != self.brain.map_manager.ally_core_pos:
            add_bridge_block = [EntityType.CORE]
        for pos in nearby_pos:
            if source == pos:
                continue
            if ct.get_position().distance_squared(pos) > ct.get_vision_radius_sq():
                continue
            if source.distance_squared(pos) > 9:
                continue
            tile_id = ct.get_tile_building_id(pos)
            if ct.get_tile_env(pos) in BLOCKING_ENVIRONMENT_TYPES:
                continue
            if tile_id != None and ct.get_team(tile_id) != ct.get_team() and ct.get_entity_type(tile_id) in ENEMY_BLOCKING_TYPES + add_bridge_block:
                continue
            if tile_id != None and ct.get_team(tile_id) == ct.get_team() and ct.get_entity_type(tile_id) in ALLY_BLOCKING_TYPES + add_bridge_block:
                continue
            if pos == dest:
                return pos
            if tile_id != None and ct.get_entity_type(tile_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR) and self.storage_tracker.is_full(tile_id):
                continue
            if tile_id != None and isolate and ct.get_entity_type(tile_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                continue
            if tile_id != None and ct.get_entity_type(tile_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR) and ct.get_stored_resource(tile_id) == ResourceType.RAW_AXIONITE:
                continue
            if (pos.x, pos.y) not in self.brain.reachable:
                continue

            dist = pos.distance_squared(dest)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos

        if best_pos != None:
            return best_pos
        # second pass: attach to any other source that shares the same resource type
        for pos in nearby_pos:
            if source == pos:
                continue
            if ct.get_position().distance_squared(pos) > ct.get_vision_radius_sq():
                continue
            tile_id = ct.get_tile_building_id(pos)
            if ct.get_tile_env(pos) in BLOCKING_ENVIRONMENT_TYPES or (tile_id != None and ct.get_entity_type(tile_id) in BRIDGE_BLOCKING_TYPES + add_bridge_block):
                continue
            if source.distance_squared(pos) > 9:
                continue
            if pos == dest:
                return pos
            if tile_id != None:
                if ct.get_team() == ct.get_team(tile_id):
                    if ct.get_entity_type(tile_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR) and ct.get_entity_type(source_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                        if ct.get_stored_resource(source_id) == ct.get_stored_resource(tile_id):
                            return pos

        # third pass: if no available bridge target, build on ore
        for pos in nearby_pos:
            if source == pos:
                continue
            if ct.get_position().distance_squared(pos) > ct.get_vision_radius_sq():
                continue
            tile_id = ct.get_tile_building_id(pos)
            if ct.get_tile_env(pos) == Environment.WALL or (tile_id != None and ct.get_entity_type(tile_id) in BRIDGE_BLOCKING_TYPES + add_bridge_block):
                continue
            if source.distance_squared(pos) > 9:
                continue
            return pos
        return best_pos

    def in_vision_and_bounds(self, ct, pos):
        if ct.get_position().distance_squared(pos) > ct.get_vision_radius_sq() or not in_bounds(ct, pos):
            return False
        return True

    def cardinal_direction_to(self, my_pos, dest):
        x_dist = my_pos.x - dest.x
        y_dist = my_pos.y - dest.y
        if abs(x_dist) > abs(y_dist):
            if x_dist > 0:
                direction = Direction.WEST
            else:
                direction = Direction.EAST
        else:
            if y_dist < 0:
                direction = Direction.SOUTH
            else:
                direction = Direction.NORTH
        return direction
