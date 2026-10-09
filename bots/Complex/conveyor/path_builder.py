from cambc import Controller, EntityType, Environment, Position, Direction, ResourceType
from roles.builder.helpers import in_bounds
from vision.storage_tracker import StorageTracker

ENEMY_FIREABLE_TYPES = [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE]
ALLY_DESTROYABLE_TYPES = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER]
BLOCKING_ENVIRONMENT_TYPES = [Environment.WALL, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]
ALLY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER]
ENEMY_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.BARRIER, EntityType.ARMOURED_CONVEYOR]
BRIDGE_BLOCKING_TYPES = [EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.BARRIER]

SPLITTER_OFFSET = 2
class PathBuilder:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.recent_connection = int | None
        self.splitter_offset_tracker = 1
        self.storage_tracker: StorageTracker = brain.storage_tracker
    def connect_and_move(self, ct: Controller, prev_conv_dir: Direction, source_id, build_pos: Position, dest: Position, use_splitters: bool = False, isolate=False):
        my_pos = ct.get_position()
        move_dir = my_pos.direction_to(build_pos)
        conv_dir = self.get_conveyor_dir(build_pos, dest, prev_conv_dir)
        tile_id = ct.get_tile_building_id(build_pos)
        # if wall or non buildable block on the location
        if ct.get_tile_env(build_pos) in BLOCKING_ENVIRONMENT_TYPES:
            # pass
            pass
        # if empty tile
        elif tile_id == None:
            if self.build_conv_or_bridge(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, use_splitters, isolate) and ct.can_move(move_dir):
                ct.move(move_dir)

        # if we need to break an enemy tile on the building pos first
        elif ct.get_team(tile_id) != ct.get_team() and ct.get_entity_type(tile_id) in ENEMY_FIREABLE_TYPES:
            if my_pos != build_pos and ct.can_move(move_dir):
                ct.move(move_dir)
            if ct.can_fire(build_pos):
                ct.fire(build_pos)
            self.build_conv_or_bridge(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, use_splitters, isolate)

        # if we need to destroy an ally tile on the building post first
        elif ct.get_team(tile_id) == ct.get_team() and ct.get_entity_type(tile_id) in ALLY_DESTROYABLE_TYPES:
            if ct.can_destroy(build_pos):
                if my_pos != build_pos and ct.can_move(move_dir):
                    ct.move(move_dir)
                ct.destroy(build_pos)
            self.build_conv_or_bridge(ct, source_id, build_pos, dest, conv_dir, prev_conv_dir, use_splitters, isolate)
        print("build pos: ", build_pos)

    def build_conv_or_bridge(self, ct: Controller, source_id, build_pos: Position, dest: Position, conv_dir: Direction, prev_conv_dir: Direction, use_splitters, isolate: bool) -> bool:
        # if target of build position would end being a wall or an blocking entity, we should build a bridge instead of a conveyor
        target: Position = build_pos.add(conv_dir)
        add_block = []
        if dest != self.brain.map_manager.ally_core_pos:
            add_block = [EntityType.CORE]
        if not in_bounds(ct, target):
            return False
        target_id = ct.get_tile_building_id(target)
        if not self.in_vision_and_bounds(ct, target):
            return False
        if ct.get_tile_env(target) in BLOCKING_ENVIRONMENT_TYPES:
            bridge_target = self.get_bridge_target(ct, source_id, build_pos, dest, isolate)
            if ct.can_build_bridge(build_pos, bridge_target):
                ct.build_bridge(build_pos, bridge_target)
                return True
        elif target_id != None and ct.get_team() == ct.get_team(target_id) and ct.get_entity_type(target_id) in ALLY_BLOCKING_TYPES + add_block:
            bridge_target = self.get_bridge_target(ct, source_id, build_pos, dest, isolate)
            if ct.can_build_bridge(build_pos, bridge_target):
                ct.build_bridge(build_pos, bridge_target)
                return True
        elif target_id != None and ct.get_team() != ct.get_team(target_id) and ct.get_entity_type(target_id) in ENEMY_BLOCKING_TYPES:
            bridge_target = self.get_bridge_target(ct, source_id, build_pos, dest, isolate)
            if ct.can_build_bridge(build_pos, bridge_target):
                ct.build_bridge(build_pos, bridge_target)
                return True        
        elif target_id != None and ct.get_entity_type(target_id) in [EntityType.BRIDGE, EntityType.CONVEYOR] and self.storage_tracker.is_full(target_id):
            bridge_target = self.get_bridge_target(ct, source_id, build_pos, dest, isolate)
            if ct.can_build_bridge(build_pos, bridge_target):
                ct.build_bridge(build_pos, bridge_target)
                return True
        elif target_id != None and ct.get_entity_type(target_id) in [EntityType.BRIDGE, EntityType.CONVEYOR] and ct.get_entity_type(source_id) in [EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER] and ct.get_stored_resource(target_id) != ct.get_stored_resource(source_id):
            bridge_target = self.get_bridge_target(ct, source_id, build_pos, dest, isolate)
            if ct.can_build_bridge(build_pos, bridge_target):
                ct.build_bridge(build_pos, bridge_target)
                return True
        elif target_id != None and isolate and ct.get_entity_type(target_id) in [EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.SPLITTER]:
            bridge_target = self.get_bridge_target(ct, source_id, build_pos, dest, isolate)
            if ct.can_build_bridge(build_pos, bridge_target):
                ct.build_bridge(build_pos, bridge_target)
                return True
        else:
            if use_splitters and prev_conv_dir == conv_dir and self.splitter_offset_tracker % SPLITTER_OFFSET == 0:
                if ct.can_build_splitter(build_pos, conv_dir):
                    ct.build_splitter(build_pos, conv_dir)
                    self.splitter_offset_tracker += 1
                    return True
            elif ct.can_build_conveyor(build_pos, conv_dir):
                ct.build_conveyor(build_pos, conv_dir)
                self.splitter_offset_tracker += 1
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
            if tile_id != None and ct.get_team(tile_id) != ct.get_team() and ct.get_entity_type(tile_id) in [EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR]:
                continue
            if tile_id != None and ct.get_entity_type(tile_id) in [EntityType.BRIDGE, EntityType.CONVEYOR] and self.storage_tracker.is_full(tile_id):
                continue
            if tile_id != None and isolate and ct.get_entity_type(tile_id) in [EntityType.BRIDGE, EntityType.CONVEYOR]:
                continue
            if tile_id != None and ct.get_entity_type(tile_id) in [EntityType.BRIDGE, EntityType.CONVEYOR] and ct.get_stored_resource(tile_id) == ResourceType.RAW_AXIONITE:
                continue

            dist = pos.distance_squared(dest)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos

        if best_pos != None:
            return best_pos
        # second pass for if best pos is None, we want to try just attaching to any other source that shares a the resource of our source
        for pos in nearby_pos:
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
                    if ct.get_entity_type(tile_id) in [EntityType.BRIDGE, EntityType.CONVEYOR] and ct.get_entity_type(source_id) in [EntityType.BRIDGE, EntityType.CONVEYOR]:
                        if ct.get_stored_resource(source_id) == ct.get_stored_resource(tile_id):
                            return pos
                        
        # third pass for if there are no available bridges, we should just build on ore
        for pos in nearby_pos:
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
        