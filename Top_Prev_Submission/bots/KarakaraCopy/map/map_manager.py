from cambc import Environment, Position, EntityType, Team, Controller, ResourceType

from map.schema import EntityCell, EnvironmentCell, MarkerCell, BotCell
from map.records import record_from_controller
from helpers.directions import DIRECTIONS, CARDINAL
from debug.profiling import cputimer
from helpers.encoder import encode_turret_details, decode_turret_details, get_marker_type
from harvesters.constants import ENEMY_INFRA_TYPES, UNREPLACEABLE_ALLY_TYPES


ENEMY_FIREABLE_TYPES = frozenset({EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MARKER, EntityType.BRIDGE})
ALLY_DESTROYABLE_TYPES = frozenset({EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER})
BLOCKING_ENVIRONMENT_TYPES = frozenset({Environment.WALL, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM})
ALLY_BLOCKING_TYPES = frozenset({EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE, EntityType.FOUNDRY})
ENEMY_BLOCKING_TYPES = frozenset({EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.LAUNCHER, EntityType.GUNNER})
ORE_INPUT_TYPES = frozenset({EntityType.FOUNDRY, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE, EntityType.CORE, EntityType.SPLITTER, EntityType.HARVESTER, EntityType.BREACH, EntityType.SENTINEL, EntityType.GUNNER})
TURRET_TYPES = frozenset({EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH})
HARVESTER_CONNECTED_TYPES = frozenset({EntityType.CORE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER, EntityType.FOUNDRY})
CLOGGED_TYPES = frozenset({EntityType.HARVESTER})

# Armoured conveyors behave identically to regular conveyors for feeder/sink/
# resource-flow semantics. ENEMY_FIREABLE_TYPES intentionally excludes them —
# builder bots cannot fire on enemy armoured conveyors.
CONVEYOR_LIKE = frozenset({EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR})

MAX_HARVESTERS_PROCESSED = 5
MAX_ORES_PROCESSED = 10

class MapManager:
    def __init__(self, ct) -> None:
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()

        self.tile_grid: list[list[EnvironmentCell]] = [
            [None for _ in range(self.height)] for _ in range(self.width)
        ]

        # Stores core even if cores aren't buildings
        self.building_grid: list[list[EntityCell]] = [
            [None for _ in range(self.height)] for _ in range(self.width)
        ]

        self.bot_grid: list[list[BotCell]] = [
            [None for _ in range(self.height)] for _ in range(self.width)
        ]

        self.bot_seen_round: list[list[int | None]] = [
            [None for _ in range(self.height)] for _ in range(self.width)
        ]

        self.nearby_entity_ids: list[int] = []
        self.nearby_positions: list[Position] = []
        # NOTE: as of the records migration, all `nearby_*_ids` lists below
        # hold EntityRecord references, not int eids. The `_ids` suffix is
        # retained to minimize callsite churn — read each entry as a record
        # (e.g. `rec.position`, `rec.entity_type`, `rec.direction`). The one
        # exception is `nearby_entity_ids` above, which is the raw return from
        # ct.get_nearby_entities() and stays as ints.
        # specific types
        self.nearby_ally_harvester_ids: list[EntityCell] = []
        self.nearby_ally_conveyor_ids: list[EntityCell] = []
        self.nearby_ally_bridge_ids: list[EntityCell] = []
        self.nearby_ally_splitter_ids: list[EntityCell] = []
        self.nearby_ally_bot_ids: list[EntityCell] = []
        self.nearby_ally_turret_ids: list[EntityCell] = []
        self.nearby_ally_road_ids: list[EntityCell] = []
        self.nearby_ally_foundry_ids: list[EntityCell] = []
        self.nearby_ally_launcher_ids: list[EntityCell] = []
        self.nearby_ally_axionite_harvester_ids: list[EntityCell] = []
        self.nearby_ally_no_foundry_axionite_harvester_ids: list[EntityCell] = []
        # TITANIUM ONLY — positions of ally conveyors adjacent to titanium
        # harvesters, pointing away from the harvester.
        self.nearby_adjacent_harvester_conveyor_position_list: list[Position] = []
        # Cached output targets of raw-axionite bridges in vision.
        self.nearby_ally_raw_axionite_bridge_targets: list[Position] = []
        # Precomputed foundry-replacement candidate positions (closest-to-me consumed in find_replace_location)
        self.nearby_foundry_replacement_candidates: list[Position] = []
        # Total count of enemy buildings (all types) in vision this turn —
        # consumed by BuildHarvesterState._count_nearby_enemies.
        self.nearby_enemy_building_count: int = 0
        # Ore positions passing turn-static harvester-placement checks
        # (tile is ore, no blocking building, no enemy turret cardinal-adjacent).
        # Persistent across turns — only re-evaluated for tiles in vision this
        # turn; out-of-vision entries keep their last-known verdict, since we
        # have no fresh data on them. The axionite gate is dynamic and applied
        # at consumer time. Consumed by harvesters.targeting.find_closest_to_core.
        self.plausible_ore_positions: set[Position] = set()

        # not connected
        self.nearby_ally_open_conveyor_ids: list[EntityCell] = []
        self.nearby_ally_open_bridge_ids: list[EntityCell] = []

        self.nearby_ally_open_titanium_harvester_ids: list[EntityCell] = []
        self.nearby_ally_open_axionite_harvester_ids: list[EntityCell] = []
        self.nearby_ally_open_foundry_ids: list[EntityCell] = []
        self.nearby_ally_open_empty_conveyor_ids: list[EntityCell] = []
        self.nearby_ally_open_titanium_conveyor_ids: list[EntityCell] = []
        self.nearby_ally_open_raw_axionite_conveyor_ids: list[EntityCell] = []
        self.nearby_ally_open_raw_axionite_bridge_ids: list[EntityCell] = []

        self.nearby_ally_clogged_bridge_ids: list[EntityCell] = []
        self.nearby_ally_clogged_conveyor_ids: list[EntityCell] = []

        self.nearby_ally_open_refined_axionite_conveyor_ids: list[EntityCell] = []
        self.nearby_ally_open_refined_axionite_bridge_ids: list[EntityCell] = []

        self.nearby_ally_open_titanium_bridge_ids: list[EntityCell] = []
        self.nearby_ally_open_splitter_ids: list[EntityCell] = []

        # `nearby_ally_conveyor_ids` is a UNION list of EntityType.CONVEYOR
        # and EntityType.ARMOURED_CONVEYOR records. Consumers that need a
        # specific type filter inline by `rec.entity_type`.

        self.nearby_enemy_builder_bot_ids: list[EntityCell] = []
        self.nearby_enemy_harvester_ids: list[EntityCell] = []
        self.nearby_enemy_splitter_ids: list[EntityCell] = []
        self.nearby_enemy_conveyor_ids: list[EntityCell] = []
        self.nearby_enemy_bridge_ids: list[EntityCell] = []
        self.nearby_enemy_open_conveyor_ids: list[EntityCell] = []

        self.nearby_enemy_launcher_ids: list[EntityCell] = []

        self.nearby_enemy_core_pos: list[Position] = []
        self.nearby_enemy_turret_pos: list[Position] = []
        self.nearby_enemy_foundry_ids: list[EntityCell] = []
        self.nearby_harvester_card_pos = []
        self.nearby_harvester_enemy_card_pos = []
        self.nearby_foundry_card_pos = []
        self.nearby_foundry_enemy_card_pos = []
        self.harvester_sentinel_count: dict[tuple[int, int], int] = {}
        self.harvester_gunner_count: dict[tuple[int, int], int] = {}

        self.nearby_bridge_to_foundry_ids: list[int] = []

        self.known_ore_positions: set[Position] = set()
        
        # Sticky flag: flips True the first time we see any conveyor whose
        # stored_resource is axionite (raw or refined). Used by pathing to
        # switch from harvester-base cost to foundry cost as the road-build
        # affordability gate. Set inline in the conveyor branch of update().
        self.axionite_seen_on_conveyor: bool = False

        self.seen_no_axionite_foundry_positions: set[Position] = set()
        self.seen_launcher_positions: set[Position] = set()

        # TITANIUM ONLY
        self.seen_adjacent_harvester_conveyor_positions: set[Position] = set()

        self.spotted_enemy_core_pos: Position | None = None
        self.ally_core_pos: Position = self.query_ally_core(ct)
        
        self._harvesters: set[Position] = set()
        self._ally_harvesters: set[Position] = set()
        self._last_enemy_builder_seen_round: int | None = None
        self.gunner_danger_positions = []
        self.ally_gunner_danger_positions = []

        # Persistent closest-known ally conveyor/bridge. Carried across rounds;
        # re-evaluated each update by recomputing dist from new my_pos and
        # replacing if any in-vision ally conveyor/bridge is closer.
        self.closest_ally_conveyor_bridge_pos: Position | None = None

        # Tiles revealed this turn (were None in tile_grid before update).
        # Consumed by pathing for incremental re-expansion.
        self.newly_seen: set[tuple[int, int]] = set()

        # Positions that already have confirmed conveyor/bridge input this turn.
        # Built fresh in update() from all visible conveyors and bridges.
        # Used by ConveyorAStar to avoid connecting into tiles that are already
        # being fed — more reliable than is_full() which can be stale after
        # an enemy destroys part of the chain.
        self.confirmed_input_positions: set[tuple[int, int]] = set()

    @cputimer
    def update(self, ct: Controller) -> None:
        self.nearby_entity_ids = ct.get_nearby_entities()
        self.nearby_positions = ct.get_nearby_tiles()

        self.nearby_ally_harvester_ids = []
        self.nearby_ally_bridge_ids = []
        self.nearby_ally_conveyor_ids = []

        self.nearby_ally_open_bridge_ids = []
        self.nearby_ally_open_conveyor_ids = []

        self.nearby_ally_splitter_ids = []
        self.nearby_ally_bot_ids = []
        self.nearby_ally_turret_ids = []
        self.nearby_ally_road_ids = []
        self.nearby_ally_foundry_ids = []
        self.nearby_ally_launcher_ids = []
        self.nearby_bridge_to_foundry_ids = []
        
        self.nearby_ally_axionite_harvester_ids = []
        self.nearby_ally_no_foundry_axionite_harvester_ids = []
        self.nearby_adjacent_harvester_conveyor_position_list = []
        self.nearby_ally_raw_axionite_bridge_targets = []
        self.nearby_foundry_replacement_candidates = []
        self.nearby_enemy_building_count = 0

        self.nearby_ally_clogged_bridge_ids = []
        self.nearby_ally_clogged_conveyor_ids = []

        self.nearby_ally_open_empty_conveyor_ids = []
        self.nearby_ally_open_titanium_conveyor_ids = []
        self.nearby_ally_open_titanium_bridge_ids = []

        self.nearby_ally_open_titanium_harvester_ids = []
        self.nearby_ally_open_foundry_ids = []
        self.nearby_ally_open_axionite_harvester_ids = []

        self.nearby_ally_open_splitter_ids = []

        self.nearby_ally_open_raw_axionite_conveyor_ids = []
        self.nearby_ally_open_raw_axionite_bridge_ids = []

        self.nearby_ally_open_refined_axionite_conveyor_ids = []
        self.nearby_ally_open_refined_axionite_bridge_ids = []

        self.confirmed_input_positions = set()

        self.nearby_enemy_builder_bot_ids = []
        self.nearby_enemy_harvester_ids = []
        self.nearby_enemy_splitter_ids = []
        self.nearby_enemy_conveyor_ids = []
        self.nearby_enemy_bridge_ids = []
        self.nearby_enemy_launcher_ids = []
        self.nearby_enemy_open_conveyor_ids = []
        
        self.nearby_enemy_core_pos = []
        self.nearby_enemy_turret_pos = []
        self.gunner_danger_positions = []
        self.ally_gunner_danger_positions = []
        self.nearby_harvester_card_pos = []
        self.nearby_harvester_enemy_card_pos = []
        self.nearby_foundry_card_pos = []
        self.nearby_foundry_enemy_card_pos = []
        self.nearby_enemy_foundry_ids = []
        self.harvester_sentinel_count = {}
        self.harvester_gunner_count = {}

        my_team = ct.get_team()
        my_pos = ct.get_position()
        vision_sq = ct.get_vision_radius_sq()
        width = self.width
        height = self.height

        # Reseed local closest-dist for ally conveyor/bridge from carried-over
        # position. Inline checks below in the conveyor/bridge branches swap in
        # any in-vision tile that's closer this turn.
        if self.closest_ally_conveyor_bridge_pos is not None:
            closest_cb_dist_sq = my_pos.distance_squared(
                self.closest_ally_conveyor_bridge_pos
            )
        else:
            closest_cb_dist_sq = float('inf')

        current_round = ct.get_current_round()
        self.newly_seen = set()
        get_tile_env = ct.get_tile_env
        get_tile_builder_bot_id = ct.get_tile_builder_bot_id
        get_tile_building_id = ct.get_tile_building_id
        tile_grid = self.tile_grid
        building_grid = self.building_grid
        bot_grid = self.bot_grid
        newly_seen = self.newly_seen
        known_ore_positions = self.known_ore_positions
        plausible_ore_positions = self.plausible_ore_positions
        ORE_TI = Environment.ORE_TITANIUM
        ORE_AX = Environment.ORE_AXIONITE
        CORE_TYPE = EntityType.CORE
        HARVESTER_TYPE = EntityType.HARVESTER
        MARKER_TYPE = EntityType.MARKER
        WALL = Environment.WALL
        # StorageTracker shortcuts used by the bridge-target population in
        # the main building loop and by the foundry-candidate detection.
        # Pre-built single-element sets so equality checks are O(1) without
        # per-iter set construction. History is as of last turn since
        # storage_tracker.update() runs after this method.
        get_recent_resources = self.storage_tracker.get_recent_resources
        TITANIUM_ONLY = {ResourceType.TITANIUM}
        RAW_AXIONITE_ONLY = {ResourceType.RAW_AXIONITE}

        # In-vision ore tiles collected during pass 1; the closest
        # MAX_ORES_PROCESSED are revalidated after both passes complete.
        plausible_ore_to_validate: list[tuple[int, Position]] = []

        for pos in self.nearby_positions:
            px = pos.x
            py = pos.y
            env = get_tile_env(pos)
            tile_col = tile_grid[px]
            if tile_col[py] is None:
                newly_seen.add((px, py))
            tile_col[py] = env

            bbid = get_tile_builder_bot_id(pos)
            if bbid is not None:
                bot_rec = record_from_controller(ct, bbid)
                if bot_rec is not None:
                    bot_rec.position = pos
                bot_grid[px][py] = bot_rec
                self.bot_seen_round[px][py] = current_round
            else:
                bot_grid[px][py] = None
                self.bot_seen_round[px][py] = None
            is_ore = env is ORE_TI or env is ORE_AX
            if is_ore:
                known_ore_positions.add(pos)
            else:
                plausible_ore_positions.discard(pos)

            # Clear empty buildings
            bid = get_tile_building_id(pos)
            if bid is None:
                building_grid[px][py] = None
                record = None
            else:
                record = record_from_controller(ct, bid)
                # CORE has a 3x3 footprint and the same record is replicated
                # across 9 cells below — its `position` is intentionally left
                # None so consumers use ally_core_pos / spotted_enemy_core_pos.
                if record.entity_type is not CORE_TYPE:
                    record.position = pos
                building_grid[px][py] = record
                rtype = record.entity_type
                if rtype is CORE_TYPE and record.team != my_team:
                    self.spotted_enemy_core_pos = pos
                elif rtype is HARVESTER_TYPE:
                    known_ore_positions.discard(pos)
                    plausible_ore_positions.discard(pos)
                    is_ore = False

            # Defer plausibility revalidation to after both passes complete
            # (so building_grid is fully fresh for cardinal reads). Capped at
            # MAX_ORES_PROCESSED closest-to-me; non-top-N ore tiles keep their
            # prior verdict, same staleness contract as out-of-vision tiles.
            if is_ore:
                plausible_ore_to_validate.append((my_pos.distance_squared(pos), pos))

        if self.ally_core_pos:
            cx = self.ally_core_pos.x
            cy = self.ally_core_pos.y
            ally_core_record = building_grid[cx][cy]
            building_grid[cx - 1][cy - 1] = ally_core_record
            building_grid[cx - 1][cy] = ally_core_record
            building_grid[cx - 1][cy + 1] = ally_core_record
            building_grid[cx][cy - 1] = ally_core_record
            building_grid[cx][cy + 1] = ally_core_record
            building_grid[cx + 1][cy - 1] = ally_core_record
            building_grid[cx + 1][cy] = ally_core_record
            building_grid[cx + 1][cy + 1] = ally_core_record

        seen_ids = set()

        # Ally harvesters collected during the main pass; processed in a second
        # loop below so we can limit to the MAX_HARVESTERS_PROCESSED closest.
        ally_harvesters_to_process: list[tuple[int, Position, EntityCell]] = []

        for pos in self.nearby_positions:
            px = pos.x
            py = pos.y

            bot_rec = bot_grid[px][py]
            if bot_rec is not None:
                eid = bot_rec.id
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    if bot_rec.team == my_team:
                        self.nearby_ally_bot_ids.append(bot_rec)
                    else:
                        self.nearby_enemy_builder_bot_ids.append(bot_rec)
                        self._last_enemy_builder_seen_round = current_round

            rec = building_grid[px][py]
            if rec is None:
                continue
            eid = rec.id
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
            etype = rec.entity_type

            if rec.team == my_team:

                if etype is HARVESTER_TYPE:
                    ally_harvesters_to_process.append((my_pos.distance_squared(pos), pos, rec))

                elif etype in CONVEYOR_LIKE:
                    # `nearby_ally_conveyor_ids` is a UNION list of CONVEYOR
                    # and ARMOURED_CONVEYOR records. Consumers that need
                    # regular-only filter inline by `rec.entity_type`.
                    self.nearby_ally_conveyor_ids.append(rec)
                    d = my_pos.distance_squared(pos)
                    if d < closest_cb_dist_sq:
                        closest_cb_dist_sq = d
                        self.closest_ally_conveyor_bridge_pos = pos
                    if not self.axionite_seen_on_conveyor:
                        sr = rec.stored_resource
                        if sr == ResourceType.RAW_AXIONITE or sr == ResourceType.REFINED_AXIONITE:
                            self.axionite_seen_on_conveyor = True
                    next_pos = pos.add(rec.direction)
                    nx = next_pos.x
                    ny = next_pos.y
                    self.confirmed_input_positions.add((nx, ny))
                    if my_pos.distance_squared(next_pos) > vision_sq or not (0 <= nx < width and 0 <= ny < height):
                        continue
                    next_rec = building_grid[nx][ny]
                    if next_rec is None:
                        self.nearby_ally_open_conveyor_ids.append(rec)
                        stored = rec.stored_resource
                        if stored == ResourceType.TITANIUM:
                            self.nearby_ally_open_titanium_conveyor_ids.append(rec)
                        elif stored == ResourceType.RAW_AXIONITE:
                            self.nearby_ally_open_raw_axionite_conveyor_ids.append(rec)
                        elif stored == ResourceType.REFINED_AXIONITE:
                            self.nearby_ally_open_refined_axionite_conveyor_ids.append(rec)
                        elif stored == None:
                            if tile_grid[nx][ny] != Environment.ORE_TITANIUM:
                                self.nearby_ally_open_empty_conveyor_ids.append(rec)
                    else:
                        next_type = next_rec.entity_type
                        next_team = next_rec.team
                        if next_type in CONVEYOR_LIKE:
                            next_next_pos = next_pos.add(next_rec.direction)
                            nnx, nny = next_next_pos.x, next_next_pos.y

                            if tile_grid[nnx][nny] is not None and tile_grid[nnx][nny] == Environment.ORE_TITANIUM:
                            #if building_grid[nnx][nny] is not None and building_grid[nnx][nny].entity_type == EntityType.HARVESTER:
                                ore_b = building_grid[nnx][nny]
                                if ore_b is None:
                                    ore_open = True
                                elif ore_b.team == my_team:
                                    ore_open = ore_b.entity_type in (EntityType.ROAD, EntityType.HARVESTER)
                                else:
                                    ore_open = ore_b.entity_type in (EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.ROAD)
                                if ore_open:
                                    self.nearby_ally_open_conveyor_ids.append(rec)
                                    stored = rec.stored_resource
                                    if stored == ResourceType.TITANIUM:
                                        self.nearby_ally_open_titanium_conveyor_ids.append(rec)
                                    elif stored == ResourceType.RAW_AXIONITE:
                                        self.nearby_ally_open_raw_axionite_conveyor_ids.append(rec)
                                    elif stored == ResourceType.REFINED_AXIONITE:
                                        self.nearby_ally_open_refined_axionite_conveyor_ids.append(rec)

                        elif (next_type not in ORE_INPUT_TYPES and my_team == next_team) or (next_type in ENEMY_FIREABLE_TYPES and my_team != next_team):
                            self.nearby_ally_open_conveyor_ids.append(rec)
                            stored = rec.stored_resource
                            if stored == ResourceType.TITANIUM:
                                self.nearby_ally_open_titanium_conveyor_ids.append(rec)
                            elif stored == ResourceType.RAW_AXIONITE:
                                self.nearby_ally_open_raw_axionite_conveyor_ids.append(rec)
                            elif stored == ResourceType.REFINED_AXIONITE:
                                self.nearby_ally_open_refined_axionite_conveyor_ids.append(rec)

                        if next_type == EntityType.BARRIER and next_team != my_team:
                            self.nearby_ally_clogged_conveyor_ids.append(rec)

                elif etype == EntityType.BRIDGE:
                    self.nearby_ally_bridge_ids.append(rec)
                    d = my_pos.distance_squared(pos)
                    if d < closest_cb_dist_sq:
                        closest_cb_dist_sq = d
                        self.closest_ally_conveyor_bridge_pos = pos
                    # History-based: only list bridges whose last 15 rounds
                    # of observations are raw-axionite-only. Smooths over
                    # the tick-level flicker a snapshot `stored_resource`
                    # check suffered from.
                    if get_recent_resources(eid) == RAW_AXIONITE_ONLY:
                        self.nearby_ally_raw_axionite_bridge_targets.append(rec.output_target)

                    target = rec.output_target
                    tx = target.x
                    ty = target.y
                    self.confirmed_input_positions.add((tx, ty))
                    if my_pos.distance_squared(target) > vision_sq or not (0 <= tx < width and 0 <= ty < height):
                        continue
                    target_rec = building_grid[tx][ty]

                    if target_rec != None and target_rec.entity_type in CONVEYOR_LIKE:
                        next_next_pos = rec.output_target.add(target_rec.direction)
                        nnx, nny = next_next_pos.x, next_next_pos.y
                        if tile_grid[nnx][nny] is not None and tile_grid[nnx][nny] == Environment.ORE_TITANIUM:
                        #if building_grid[nnx][nny] is not None and building_grid[nnx][nny].entity_type == EntityType.HARVESTER:
                            #self.nearby_ally_open_bridge_ids.append(rec)
                            stored = rec.stored_resource
                            if stored == ResourceType.TITANIUM:
                                self.nearby_ally_open_titanium_bridge_ids.append(rec)
                            elif stored == ResourceType.RAW_AXIONITE:
                                self.nearby_ally_open_raw_axionite_bridge_ids.append(rec)
                            elif stored == ResourceType.REFINED_AXIONITE:
                                self.nearby_ally_open_refined_axionite_bridge_ids.append(rec)

                    elif target_rec is None or (target_rec.team == my_team and target_rec.entity_type in ALLY_DESTROYABLE_TYPES):
                        self.nearby_ally_open_bridge_ids.append(rec)
                        stored = rec.stored_resource
                        if stored == ResourceType.RAW_AXIONITE:
                            self.nearby_ally_open_raw_axionite_bridge_ids.append(rec)
                        elif stored == ResourceType.TITANIUM:
                            self.nearby_ally_open_titanium_bridge_ids.append(rec)
                        elif stored == ResourceType.REFINED_AXIONITE:
                            self.nearby_ally_open_refined_axionite_bridge_ids.append(rec)
                    else:
                        target_type = target_rec.entity_type
                        target_team = target_rec.team
                        if (target_type not in ORE_INPUT_TYPES and my_team == target_team) or (target_type in ENEMY_FIREABLE_TYPES and my_team != target_team):
                            #self.nearby_ally_open_bridge_ids.append(rec)
                            stored = rec.stored_resource
                            if stored == ResourceType.RAW_AXIONITE:
                                self.nearby_ally_open_raw_axionite_bridge_ids.append(rec)
                            elif stored == ResourceType.TITANIUM:
                                self.nearby_ally_open_titanium_bridge_ids.append(rec)
                            elif stored == ResourceType.REFINED_AXIONITE:
                                self.nearby_ally_open_refined_axionite_bridge_ids.append(rec)

                        if target_type == EntityType.FOUNDRY:
                            self.nearby_bridge_to_foundry_ids.append(rec)

                        if target_type in CLOGGED_TYPES:
                            self.nearby_ally_clogged_bridge_ids.append(rec)

                elif etype == EntityType.SPLITTER:
                    self.nearby_ally_splitter_ids.append(rec)
                    next_pos = pos.add(rec.direction)
                    nx = next_pos.x
                    ny = next_pos.y
                    if my_pos.distance_squared(next_pos) > vision_sq or not (0 <= nx < width and 0 <= ny < height):
                        continue
                    next_rec = building_grid[nx][ny]
                    if next_rec is None or next_rec.entity_type not in ORE_INPUT_TYPES:
                        self.nearby_ally_open_splitter_ids.append(rec)

                elif etype in TURRET_TYPES:
                    self.nearby_ally_turret_ids.append(rec)
                    if etype == EntityType.GUNNER:
                        gunner_dir = rec.direction
                        front1 = pos.add(gunner_dir)
                        front2 = front1.add(gunner_dir)
                        self.ally_gunner_danger_positions.append(front1)
                        self.ally_gunner_danger_positions.append(front2)

                elif etype == EntityType.ROAD:
                    self.nearby_ally_road_ids.append(rec)

                elif etype == EntityType.FOUNDRY:
                    self.nearby_ally_foundry_ids.append(rec)

                    # Skip open-foundry check if any cardinal neighbour is outside
                    # vision — we can't confirm those tiles are up to date.
                    foundry_on_rim = False
                    for d in CARDINAL:
                        ap = pos.add(d)
                        if my_pos.distance_squared(ap) > vision_sq:
                            foundry_on_rim = True
                            break

                    inputs = 0
                    is_connected = False
                    surrounded = 0
                    for d in CARDINAL:
                        adj_pos = pos.add(d)
                        ax = adj_pos.x
                        ay = adj_pos.y
                        if not (0 <= ax < width and 0 <= ay < height):
                            continue
                        if my_pos.distance_squared(adj_pos) <= vision_sq:
                            self.nearby_foundry_card_pos.append((pos, adj_pos))
                        adj_rec = building_grid[ax][ay]

                        if adj_rec is not None:
                            adj_type = adj_rec.entity_type
                            if adj_type in CONVEYOR_LIKE:
                                if adj_rec.direction == d.opposite():
                                    inputs += 1
                                else:
                                    is_connected = True
                            elif adj_type == EntityType.BRIDGE:
                                is_connected = True
                            elif adj_type == EntityType.SPLITTER:
                                inputs += 1
                            
                            if adj_type in ALLY_BLOCKING_TYPES:
                                surrounded += 1
                        if tile_grid[ax][ay] == Environment.WALL:
                            surrounded += 1
                        
                    if not foundry_on_rim and not is_connected and surrounded < 4:
                        self.nearby_ally_open_foundry_ids.append(rec)

                    if inputs < 2 and pos not in self.seen_no_axionite_foundry_positions:
                        self.seen_no_axionite_foundry_positions.add(pos)
                    elif inputs >= 2 and pos in self.seen_no_axionite_foundry_positions:
                        self.seen_no_axionite_foundry_positions.discard(pos)

                elif etype == EntityType.LAUNCHER:
                    self.seen_launcher_positions.add(pos)
                    self.nearby_ally_launcher_ids.append(rec)

            else:
                self.nearby_enemy_building_count += 1
                if etype is HARVESTER_TYPE:
                    self.nearby_enemy_harvester_ids.append(rec)
                    self._harvesters.add(pos)
                    harvester_key = (pos.x, pos.y)
                    for d in CARDINAL:
                        adj_pos = pos.add(d)
                        ax = adj_pos.x
                        ay = adj_pos.y
                        if my_pos.distance_squared(adj_pos) > vision_sq or not (0 <= ax < width and 0 <= ay < height):
                            continue
                        self.nearby_harvester_enemy_card_pos.append((pos, adj_pos))
                        adj_rec = building_grid[ax][ay]
                        if adj_rec is not None and adj_rec.team == my_team:
                            if adj_rec.entity_type == EntityType.SENTINEL:
                                self.harvester_sentinel_count[harvester_key] = self.harvester_sentinel_count.get(harvester_key, 0) + 1
                            elif adj_rec.entity_type == EntityType.GUNNER:
                                self.harvester_gunner_count[harvester_key] = self.harvester_gunner_count.get(harvester_key, 0) + 1
                elif etype is EntityType.SPLITTER:
                    self.nearby_enemy_splitter_ids.append(rec)
                elif etype in CONVEYOR_LIKE:
                    # UNION (regular + armoured). Fire-targeting consumers
                    # (e.g. sabotage_state) filter inline — builder bots
                    # cannot fire on enemy ARMOURED_CONVEYOR.
                    self.nearby_enemy_conveyor_ids.append(rec)
                    next_pos = pos.add(rec.direction)
                    nx = next_pos.x
                    ny = next_pos.y
                    if my_pos.distance_squared(next_pos) > vision_sq or not (0 <= nx < width and 0 <= ny < height):
                        continue
                    next_rec = building_grid[nx][ny]
                    if next_rec is None:
                        self.nearby_enemy_open_conveyor_ids.append(rec)
                    else:
                        next_type = next_rec.entity_type
                        next_team = next_rec.team
                        # Open from enemy POV: our stuff in the way, OR their own non-input dead-end
                        if (next_team == my_team) or (next_team != my_team and next_type not in ORE_INPUT_TYPES):
                            self.nearby_enemy_open_conveyor_ids.append(rec)
                elif etype == EntityType.BRIDGE:
                    self.nearby_enemy_bridge_ids.append(rec)
                elif etype == EntityType.FOUNDRY:
                    self.nearby_enemy_foundry_ids.append(rec)
                    for d in CARDINAL:
                        adj_pos = pos.add(d)
                        ax = adj_pos.x
                        ay = adj_pos.y
                        if my_pos.distance_squared(adj_pos) > vision_sq or not (0 <= ax < width and 0 <= ay < height):
                            continue
                        self.nearby_foundry_enemy_card_pos.append((pos, adj_pos))
                elif etype is CORE_TYPE:
                    self.nearby_enemy_core_pos.append(pos)
                elif etype == EntityType.LAUNCHER:
                    self.nearby_enemy_launcher_ids.append(rec)
                elif etype == EntityType.SENTINEL or etype == EntityType.GUNNER:
                    self.nearby_enemy_turret_pos.append(pos)
                    if etype == EntityType.GUNNER:
                        gunner_dir = rec.direction
                        front1 = pos.add(gunner_dir)
                        f1x = front1.x
                        f1y = front1.y
                        if 0 <= f1x < width and 0 <= f1y < height:
                            self.gunner_danger_positions.append(front1)
                            # Front1 blocks the shot iff it's a wall or holds a
                            # non-marker building. Unseen front1 → assume the
                            # shot passes through (conservative).
                            f1_blocks = tile_grid[f1x][f1y] is WALL
                            if not f1_blocks:
                                f1_rec = building_grid[f1x][f1y]
                                if f1_rec is not None and f1_rec.entity_type is not MARKER_TYPE:
                                    f1_blocks = True
                            if not f1_blocks:
                                front2 = front1.add(gunner_dir)
                                f2x = front2.x
                                f2y = front2.y
                                if 0 <= f2x < width and 0 <= f2y < height:
                                    self.gunner_danger_positions.append(front2)

        # Process ally harvesters — limit to MAX_HARVESTERS_PROCESSED closest
        # to us when we have more than that in vision.
        if len(ally_harvesters_to_process) > MAX_HARVESTERS_PROCESSED:
            ally_harvesters_to_process.sort(key=lambda x: x[0])
            harvesters_iter = ally_harvesters_to_process[:MAX_HARVESTERS_PROCESSED]
        else:
            harvesters_iter = ally_harvesters_to_process

        for _dist_sq, pos, rec in harvesters_iter:
            # `rec.position` was already set in the main pass above; assert
            # via re-assignment is unnecessary. Ally harvester records are
            # added to nearby_ally_harvester_ids here (deferred so the list
            # is bounded by MAX_HARVESTERS_PROCESSED).
            px = pos.x
            py = pos.y
            self.nearby_ally_harvester_ids.append(rec)
            self._harvesters.add(pos)
            self._ally_harvesters.add(pos)
            harvester_env = tile_grid[px][py]
            is_connected = False
            has_foundry = False
            blocked = 0
            enemy_turret_adjacent = False
            harvester_key = (px, py)
            for d in CARDINAL:
                adj_pos = pos.add(d)
                ax = adj_pos.x
                ay = adj_pos.y
                if not (0 <= ax < width and 0 <= ay < height):
                    continue
                in_vision = my_pos.distance_squared(adj_pos) <= vision_sq
                if in_vision:
                    self.nearby_harvester_card_pos.append((pos, adj_pos))
                adj_rec = building_grid[ax][ay]
                if tile_grid[ax][ay] is WALL:
                    blocked += 1
                if adj_rec is not None:
                    adj_type = adj_rec.entity_type
                    if adj_type in ALLY_BLOCKING_TYPES:
                        blocked += 1
                    if adj_rec.team != my_team and adj_type in TURRET_TYPES:
                        enemy_turret_adjacent = True
                    if in_vision and adj_rec.team == my_team:
                        if adj_type == EntityType.SENTINEL:
                            self.harvester_sentinel_count[harvester_key] = self.harvester_sentinel_count.get(harvester_key, 0) + 1
                        elif adj_type == EntityType.GUNNER:
                            self.harvester_gunner_count[harvester_key] = self.harvester_gunner_count.get(harvester_key, 0) + 1
                    if adj_type in HARVESTER_CONNECTED_TYPES and adj_rec.direction != d.opposite():
                        points_into_harvester = False
                        if adj_type in CONVEYOR_LIKE:
                            target_pos = adj_pos.add(adj_rec.direction)
                            tx = target_pos.x
                            ty = target_pos.y
                            if 0 <= tx < width and 0 <= ty < height:
                                target_rec = building_grid[tx][ty]
                                if target_rec is not None and target_rec.entity_type is HARVESTER_TYPE:
                                    points_into_harvester = True
                        if not points_into_harvester:
                            is_connected = True
                    if adj_type == EntityType.FOUNDRY:
                        has_foundry = True
                    if adj_type in CONVEYOR_LIKE and harvester_env is ORE_TI and adj_rec.direction != d.opposite():
                        if in_vision:
                            self.seen_adjacent_harvester_conveyor_positions.add(adj_pos)
                            self.nearby_adjacent_harvester_conveyor_position_list.append(adj_pos)
                # clear
                if adj_pos in self.seen_adjacent_harvester_conveyor_positions:
                    if adj_rec is None or adj_rec.entity_type not in CONVEYOR_LIKE:
                        if in_vision:
                            self.seen_adjacent_harvester_conveyor_positions.discard(adj_pos)

            if harvester_env is ORE_AX:
                self.nearby_ally_axionite_harvester_ids.append(rec)

            if not is_connected:
                if harvester_env is ORE_TI and not enemy_turret_adjacent:
                    self.nearby_ally_open_titanium_harvester_ids.append(rec)
                if harvester_env is ORE_AX:
                    self.nearby_ally_open_axionite_harvester_ids.append(rec)

            if not has_foundry and harvester_env is ORE_AX:
                self.nearby_ally_no_foundry_axionite_harvester_ids.append(rec)

        # Plausible-ore revalidation — limit to MAX_ORES_PROCESSED closest to
        # us. building_grid is fully fresh by this point, so cardinal reads
        # are consistent. Static checks: no blocking building on tile, no
        # enemy turret cardinal-adjacent. The axionite gate is dynamic and
        # applied at consumer time.
        if len(plausible_ore_to_validate) > MAX_ORES_PROCESSED:
            plausible_ore_to_validate.sort(key=lambda x: x[0])
            ores_iter = plausible_ore_to_validate[:MAX_ORES_PROCESSED]
        else:
            ores_iter = plausible_ore_to_validate

        for _dist_sq, pos in ores_iter:
            px = pos.x
            py = pos.y
            plausible = True
            rec = building_grid[px][py]
            if rec is not None:
                rteam = rec.team
                rtype = rec.entity_type
                if rteam != my_team and rtype is not MARKER_TYPE and rtype not in ENEMY_INFRA_TYPES:
                    plausible = False
                elif rteam == my_team and rtype in UNREPLACEABLE_ALLY_TYPES:
                    plausible = False
            if plausible:
                for d in CARDINAL:
                    adj = pos.add(d)
                    ax = adj.x
                    ay = adj.y
                    if not (0 <= ax < width and 0 <= ay < height):
                        continue
                    adj_rec = building_grid[ax][ay]
                    if (
                        adj_rec is not None
                        and adj_rec.team != my_team
                        and adj_rec.entity_type in TURRET_TYPES
                    ):
                        plausible = False
                        break
            if plausible:
                plausible_ore_positions.add(pos)
            else:
                plausible_ore_positions.discard(pos)

        # Foundry-replacement candidate detection. Uses only cached grid data
        # (no ct.* calls). Replaces the body of find_replace_location in
        # states/replace_with_foundry_state.py.
        foundry_candidates = self.nearby_foundry_replacement_candidates
        # `no_foundry_set` is a set of EntityRecord refs — same objects also
        # live in nearby_ally_axionite_harvester_ids, so identity membership
        # is correct. EntityRecord has no custom __eq__ so set() uses id().
        no_foundry_set = set(self.nearby_ally_no_foundry_axionite_harvester_ids)

        CONVEYOR_TYPE = EntityType.CONVEYOR
        BRIDGE_TYPE = EntityType.BRIDGE
        SPLITTER_TYPE = EntityType.SPLITTER
        ARMOURED_CONVEYOR_TYPE = EntityType.ARMOURED_CONVEYOR
        MARKER_TYPE = EntityType.MARKER
        ROAD_TYPE = EntityType.ROAD
        RAW_AXIONITE = ResourceType.RAW_AXIONITE

        # Part 1: axionite harvesters. Skip any harvester that already has a
        # foundry cardinally adjacent — we don't want to build a second foundry
        # next to a harvester that's already served. For each cardinal:
        #   - CONVEYOR with titanium-only history → candidate
        #   - BRIDGE with titanium-only history AND a "free" adjacent tile →
        #     candidate (bridge tile becomes the foundry slot)
        for h_rec in self.nearby_ally_axionite_harvester_ids:
            if h_rec not in no_foundry_set:
                continue
            h_pos = h_rec.position
            for d in CARDINAL:
                adj_pos = h_pos.add(d)
                ax = adj_pos.x
                ay = adj_pos.y
                if not (0 <= ax < width and 0 <= ay < height):
                    continue
                if my_pos.distance_squared(adj_pos) > vision_sq:
                    continue
                adj_rec = building_grid[ax][ay]
                if adj_rec is None:
                    continue
                adj_type = adj_rec.entity_type
                if adj_type is CONVEYOR_TYPE:
                    if get_recent_resources(adj_rec.id) == TITANIUM_ONLY:
                        foundry_candidates.append(adj_pos)
                elif adj_type is BRIDGE_TYPE:
                    if get_recent_resources(adj_rec.id) != TITANIUM_ONLY:
                        continue
                    free = False
                    for d2 in CARDINAL:
                        adj_bridge_pos = adj_pos.add(d2)
                        bx = adj_bridge_pos.x
                        by = adj_bridge_pos.y
                        if not (0 <= bx < width and 0 <= by < height):
                            continue
                        if my_pos.distance_squared(adj_bridge_pos) > vision_sq:
                            continue
                        adj_bridge_rec = building_grid[bx][by]
                        bridge_env = tile_grid[bx][by]
                        if bridge_env is ORE_TI or bridge_env is ORE_AX:
                            free = True
                        if adj_bridge_rec is None:
                            free = True
                        elif adj_bridge_rec.team == my_team and adj_bridge_rec.entity_type in (CONVEYOR_TYPE, BRIDGE_TYPE, MARKER_TYPE, ROAD_TYPE, ARMOURED_CONVEYOR_TYPE):
                            free = True
                        elif adj_bridge_rec.team != my_team and adj_bridge_rec.entity_type in (CONVEYOR_TYPE, BRIDGE_TYPE, MARKER_TYPE, ROAD_TYPE):
                            free = True
                    if free:
                        foundry_candidates.append(adj_pos)

        # Part 2: conveyors adjacent to titanium harvesters. A position is a
        # candidate when it has both a titanium input (adjacent titanium
        # harvester) and an axionite input (adjacent axionite harvester, a
        # conveyor/splitter/armoured-conveyor pointing toward it with raw
        # axionite, or a raw-axionite bridge targeting it).
        conveyor_like_types = (CONVEYOR_TYPE, SPLITTER_TYPE, ARMOURED_CONVEYOR_TYPE)
        raw_axionite_bridge_targets = self.nearby_ally_raw_axionite_bridge_targets
        for c_pos in self.nearby_adjacent_harvester_conveyor_position_list:
            titanium_input = False
            axionite_input = False
            for d in CARDINAL:
                adj_pos = c_pos.add(d)
                ax = adj_pos.x
                ay = adj_pos.y
                if not (0 <= ax < width and 0 <= ay < height):
                    continue
                if my_pos.distance_squared(adj_pos) > vision_sq:
                    continue
                adj_rec = building_grid[ax][ay]
                if adj_rec is not None:
                    adj_type = adj_rec.entity_type
                    if adj_type is HARVESTER_TYPE:
                        env = tile_grid[ax][ay]
                        if env is ORE_TI:
                            titanium_input = True
                        elif env is ORE_AX:
                            axionite_input = True
                    if adj_type in conveyor_like_types:
                        if adj_rec.direction == d.opposite():
                            if get_recent_resources(adj_rec.id) == RAW_AXIONITE_ONLY:
                                axionite_input = True
            if not axionite_input:
                for target in raw_axionite_bridge_targets:
                    if target == c_pos:
                        axionite_input = True
                        break
            if titanium_input and axionite_input:
                foundry_candidates.append(c_pos)

        print(f"MapManager time after update: {ct.get_cpu_time_elapsed()}")

        # Note that spotted enemy core pos is simply one of the 9 positions of the enemy core
        # If you want to find actual core, use learned reflection

    @property
    def last_enemy_builder_seen_round(self) -> int | None:
        """Last round an enemy builder bot was in vision range, or None if never."""
        return self._last_enemy_builder_seen_round

    def query_ally_core(self, ct):
        ids = ct.get_nearby_entities()
        for id in ids:
            if ct.get_entity_type(id) == EntityType.CORE:
                return ct.get_position(id)
        return None

    def has_seen(self, pos) -> None:
        return self.tile_grid[pos.x][pos.y] != None
    
    def has_wall(self, pos) -> None:
        return self.tile_grid[pos.x][pos.y] == Environment.WALL

    def has_ore(self, pos):
        return (self.tile_grid[pos.x][pos.y] == Environment.ORE_TITANIUM or
                self.tile_grid[pos.x][pos.y] == Environment.ORE_AXIONITE)
    
    def get_tile(self, pos):
        return self.tile_grid[pos.x][pos.y]

    def get_building(self, pos):
        return self.building_grid[pos.x][pos.y]
    
    def get_bot(self, pos, current_round=None):
        seen = self.bot_seen_round[pos.x][pos.y]
        if seen is not None and current_round is not None and current_round - seen > 2:
            return None
        return self.bot_grid[pos.x][pos.y]
