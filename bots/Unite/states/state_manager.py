from enum import Enum
from cambc import Controller, Environment, EntityType, GameConstants, Position

from debug.profiling import cputimer
from roles.builder.helpers import BABYSITTER_DIRECTION, RUSHER_DIRECTION
from core_supply.connector import has_adjacent_ally_bridge
from states.fortify_core_state import FortifyCoreState

from states.build_harvester_state import BuildHarvesterState
from states.build_enemy_source_turret_state import BuildEnemySourceTurretState
from states.explore_state import ExploreState
from states.core_connect_state import CoreConnectState, has_adjacent_enemy_bridge
from states.repair_bridge_state import RepairBridgeState
from states.sabotage_bridge_state import SabotageBridgeState
from states.sabotage_source_state import SabotageSourceState
<<<<<<< HEAD
from states.sabotage_defend_state import SabotageDefendState
from states.connect_harvester_to_bridge import ConnectHarvesterToBridgeState

from comms.markers import is_repair_stale_near, is_gap_being_worked
from core_supply.bridge_tracer import find_broken_bridges, find_first_link_breaks, trace_downstream
from helpers.constants import REPAIR_MARKER_COOLDOWN, HARVESTER_CLAIM_STALENESS, BRIDGE_WORK_STALENESS
from map.map_manager import MapManager
=======
from states.rush_state import RushState
from states.destroy_ammo_source_state import DestroyAmmoSourceState
from states.defend_harvester_state import DefendState
from states.build_turret_to_defend_state import BuildTurretDefendState
from core_supply.bridge_tracer import find_broken_bridges
from comms.markers import is_bridge_work_claimed_vm

>>>>>>> a12edd4ba89e00e139a5290528a15f8044537009

class BuilderState(Enum):
    EXPLORE = "explore"
    BUILD_HARVESTER = "build_harvester"
    UNDERMINE = "steal_conveyor_space"
    BUILD_GUNNER = "build_gunner"
    CORE_CONNECT = "core_connect"
    REPAIR_BRIDGE = "repair_bridge"
    FORTIFY_CORE = "fortify_core"
    SABOTAGE_SOURCE = "sabotage_source"
    SABOTAGE_BRIDGE = "sabotage_bridge"
    BUILD_SOURCE_TURRET = "build_source_turret"
<<<<<<< HEAD
    CONNECT_HARVESTER_TO_BRIDGE = "connect_harvester_to_bridge"

=======
    RUSH_STATE = "rush_state"
    DESTROY_AMMO_SOURCE = "destroy the ammo source!"
    DEFEND_HARVESTER = "defebd"
    BUILD_DEFENSIVE_TURRET = "defent"
>>>>>>> a12edd4ba89e00e139a5290528a15f8044537009

class StateManager:
    def __init__(self, brain, ct: Controller, initial: BuilderState=BuilderState.EXPLORE) -> None:
        self.brain = brain
        self.previous_state = initial
        self.current_state = initial

        self.state_map = {
            BuilderState.EXPLORE: ExploreState(ct, brain),
            BuilderState.BUILD_HARVESTER: BuildHarvesterState(ct, brain),
            BuilderState.CORE_CONNECT: CoreConnectState(ct, brain),
            BuilderState.REPAIR_BRIDGE: RepairBridgeState(ct, brain),
            BuilderState.FORTIFY_CORE: FortifyCoreState(ct, brain),
            BuilderState.SABOTAGE_BRIDGE: SabotageBridgeState(ct, brain),
            BuilderState.SABOTAGE_SOURCE: SabotageSourceState(ct, brain),
<<<<<<< HEAD
            BuilderState.SABOTAGE_DEFEND: SabotageDefendState(ct, brain),
            BuilderState.BUILD_SOURCE_TURRET: BuildSourceTurretState(ct, brain),
            BuilderState.CONNECT_HARVESTER_TO_BRIDGE: ConnectHarvesterToBridgeState(ct, brain)
=======
            BuilderState.BUILD_SOURCE_TURRET: BuildEnemySourceTurretState(ct, brain),
            BuilderState.RUSH_STATE: RushState(ct, brain),
            BuilderState.DESTROY_AMMO_SOURCE: DestroyAmmoSourceState(ct, brain),
            BuilderState.DEFEND_HARVESTER: DefendState(ct, brain),
            BuilderState.BUILD_DEFENSIVE_TURRET: BuildTurretDefendState(ct, brain)
>>>>>>> a12edd4ba89e00e139a5290528a15f8044537009
        }

    # Determine state from spawn location
    def determine_state(self, ct):
        self.previous_state = self.current_state
        ally_core = self.brain.map_manager.ally_core_pos
        spawn_pos = self.brain.spawn_location

        # BABYSITTER
        if spawn_pos == ally_core.add(BABYSITTER_DIRECTION):
            self.current_state = BuilderState.FORTIFY_CORE
            return
        
        # RUSHER
        elif spawn_pos == self.brain.map_manager.ally_core_pos.add(RUSHER_DIRECTION):
            self.current_state = BuilderState.RUSH_STATE
            (
                # TURRET STATES
                self.determine_build_source_turret_state(ct)

                # # SABOTAGE STATES
                or self.determine_sabotage_source_state(ct)
                or self.determine_sabotage_bridge_state(ct)
            )

        # Priority order: highest priority first, short-circuit on first match
        (
            # TURRET STATES
            #self.determine_build_source_turret_state(ct)

            # # SABOTAGE STATES
            # or self.determine_sabotage_defend_state(ct)
            # or self.determine_sabotage_source_state(ct)
            # or self.determine_sabotage_bridge_state(ct)

            # BRIDGING STATES
            self.determine_repair_bridge_state(ct)
            or self.determine_core_connect_state(ct)

                # BUILD STATES
                or self.determine_build_harvester_state(ct)
                or self.determine_defend_state(ct)
            )

    @cputimer
    def execute_state(self, ct):
        self.state_map[self.current_state].execute(ct)

    def determine_build_harvester_state(self, ct):
        build_state = self.state_map[BuilderState.BUILD_HARVESTER]
        mm = self.brain.map_manager
        current_round = ct.get_current_round()

        print(f"Harvestor cost is {ct.get_harvester_cost()}")
        if ct.get_global_resources()[0] < ct.get_harvester_cost()[0] + (GameConstants.HARVESTER_BASE_COST[0]) / 2 + 2 * ct.get_bridge_cost()[0]:
            return False

        if (
            self.previous_state == BuilderState.BUILD_HARVESTER
            and build_state.target is not None
            and build_state._is_valid_ore(ct, mm, build_state.target, current_round)
            and self.brain._is_closer_to_ally_core(build_state.target)
        ):
            self.current_state = BuilderState.BUILD_HARVESTER
            return True

        my_pos = ct.get_position()
        candidate = build_state._find_best_ore(ct, mm, my_pos, current_round)
        if candidate is not None and self.brain._is_closer_to_ally_core(candidate):
            self.current_state = BuilderState.BUILD_HARVESTER
            return True

        return False
    
    def determine_build_source_turret_state(self, ct):
        turret_state = self.state_map[BuilderState.BUILD_SOURCE_TURRET]
        mm = self.brain.map_manager
        current_round = ct.get_current_round()

        if (
            self.previous_state == BuilderState.BUILD_SOURCE_TURRET
            and turret_state.source_pos is not None
            and turret_state._is_valid_source(ct, mm, turret_state.source_pos, current_round)
        ):
            self.current_state = BuilderState.BUILD_SOURCE_TURRET
            return True

        my_pos = ct.get_position()
        if turret_state._find_best_source(ct, mm, my_pos, current_round) is not None:
            self.current_state = BuilderState.BUILD_SOURCE_TURRET
            return True

        return False

    def determine_core_connect_state(self, ct):
        """Find sources (harvesters/foundries) with no adjacent ally bridge."""
        core_state = self.state_map[BuilderState.CORE_CONNECT]
        current_round = ct.get_current_round()
        mm = self.brain.map_manager

        # Continue in-progress connection
        if (
            self.previous_state == BuilderState.CORE_CONNECT
            and core_state.source_pos is not None
            and not core_state.is_connected(core_state.source_pos)
            and not core_state._is_on_cooldown((core_state.source_pos.x, core_state.source_pos.y), current_round)
            and not has_adjacent_enemy_bridge(ct, core_state.source_pos, mm)
            and self.brain._is_closer_to_ally_core(core_state.source_pos)
        ):
            self.current_state = BuilderState.CORE_CONNECT
            return True

        # Scan for new unconnected sources
        for pos in mm.nearby_positions:
            building = mm.get_building(pos)
            if building is None:
                continue
            if not (
                (building.entity_type == EntityType.HARVESTER and mm.get_tile(pos) == Environment.ORE_TITANIUM) or
                building.entity_type == EntityType.FOUNDRY
            ):
                continue
            key = (pos.x, pos.y)
            if core_state._is_on_cooldown(key, current_round):
                continue
            if core_state.is_connected(pos):
                continue
            if has_adjacent_ally_bridge(ct, pos, mm):
                continue
            if has_adjacent_enemy_bridge(ct, pos, mm):
                continue
            if not self.brain._is_closer_to_ally_core(pos):
                continue
            self.current_state = BuilderState.CORE_CONNECT
            core_state.source_pos = pos
            return True

        return False

    def determine_repair_bridge_state(self, ct):
        repair_state = self.state_map[BuilderState.REPAIR_BRIDGE]
        current_round = ct.get_current_round()

        # Continue in-progress repair
        if (
            self.previous_state == BuilderState.REPAIR_BRIDGE
            and repair_state.break_pos is not None
            and not repair_state.finished
            and not repair_state._is_on_cooldown((repair_state.break_pos.x, repair_state.break_pos.y), current_round)
        ):
            self.current_state = BuilderState.REPAIR_BRIDGE
            return True

        mm = self.brain.map_manager
        vm = self.brain.vision_manager

        # Broken chains: a bridge whose output_target has no bridge
        broken_bridges = find_broken_bridges(ct, mm, vm)
        print(f"Broken bridges found: {broken_bridges}")
        for bridge_pos, empty_pos in broken_bridges:
            key = (empty_pos.x, empty_pos.y)
            if repair_state._is_on_cooldown(key, current_round):
                continue
            if is_bridge_work_claimed_vm(vm, empty_pos, current_round):
                repair_state.cooldowns[key] = current_round
                continue
            self.current_state = BuilderState.REPAIR_BRIDGE
            repair_state.reset()
            repair_state.break_pos = empty_pos
            repair_state.source_pos = empty_pos
            return True

        return False

    def determine_sabotage_source_state(self, ct):
        sabotage_state = self.state_map[BuilderState.SABOTAGE_SOURCE]
        print(f"Sabotage cooldowns: {sabotage_state.cooldowns}")

        mm = self.brain.map_manager
        current_round = ct.get_current_round()
    
        if (
            self.previous_state == BuilderState.SABOTAGE_SOURCE
            and sabotage_state.target is not None
            and sabotage_state._is_valid_target(ct, mm, sabotage_state.target, current_round)
        ):
            self.current_state = BuilderState.SABOTAGE_SOURCE
            return True
    
        my_pos = ct.get_position()
        if sabotage_state._find_best_target(ct, mm, my_pos, current_round) is not None:
            self.current_state = BuilderState.SABOTAGE_SOURCE
            return True

        return False

    def determine_sabotage_bridge_state(self, ct):
        sabotage_state = self.state_map[BuilderState.SABOTAGE_BRIDGE]

        mm = self.brain.map_manager
        current_round = ct.get_current_round()

        if (
            self.previous_state == BuilderState.SABOTAGE_BRIDGE
            and sabotage_state.target is not None
            and sabotage_state._is_valid_target(ct, mm, sabotage_state.target, current_round)
        ):
            self.current_state = BuilderState.SABOTAGE_BRIDGE
            return True

        my_pos = ct.get_position()
        if sabotage_state._find_best_target(ct, mm, my_pos, current_round) is not None:
            self.current_state = BuilderState.SABOTAGE_BRIDGE
            return True

        return False

    def determine_destroy_ammo_source_state(self, ct):
        destroy_state:DestroyAmmoSourceState = self.state_map[BuilderState.DESTROY_AMMO_SOURCE]
        enemy_turret: Position | None = destroy_state.identify_enemy_turret(ct)
        if enemy_turret == None:
            return False
<<<<<<< HEAD

        if (
            self.previous_state == BuilderState.SABOTAGE_DEFEND
            and sabotage_state.target is not None
            and sabotage_state._is_valid_target(ct, mm, sabotage_state.target, current_round)
        ):
            self.current_state = BuilderState.SABOTAGE_DEFEND
            return True

        my_pos = ct.get_position()
        if sabotage_state._find_best_target(ct, mm, my_pos, current_round) is not None:
            self.current_state = BuilderState.SABOTAGE_DEFEND
            return True

        return False
    def determine_connect_harvester_to_bridge_state(self, ct: Controller):
        connect_state: ConnectHarvesterToBridgeState = self.state_map[BuilderState.CONNECT_HARVESTER_TO_BRIDGE]
        mm: MapManager = self.brain.map_manager

        my_pos = ct.get_position()
        my_team = ct.get_team()

        harvester_positions = []
        bridge_positions = []

        for eid in mm.nearby_entity_ids:
            if ct.get_team(eid) != my_team:
                continue
            unit_type = ct.get_entity_type(eid)
            position = ct.get_position(eid)

            if unit_type == EntityType.HARVESTER:
                harvester_positions.append(position)
            elif unit_type == EntityType.BRIDGE:
                bridge_positions.append(position)

        if not harvester_positions or not bridge_positions:
            return False

        def is_adjacent(a, b):
            return abs(a.x - b.x) <= 1 and abs(a.y - b.y) <= 1

        filtered_bridges = [
            b for b in bridge_positions
            if not any(is_adjacent(b, h) for h in harvester_positions)
        ]

        if not filtered_bridges:
            return False

        closest_harvester = min(harvester_positions, key=lambda h: my_pos.distance_squared(h))
        closest_bridge = min(filtered_bridges, key=lambda b: my_pos.distance_squared(b))

        connect_state.source_pos = closest_harvester
        connect_state.dest_pos = closest_bridge
        self.current_state = BuilderState.CONNECT_HARVESTER_TO_BRIDGE
        return True
=======
        ammo_source: Position | None = destroy_state.identify_source_destroy(ct, enemy_turret)
        if ammo_source == None:
            return False
        destroy_state.ammo_source_pos = ammo_source
        destroy_state.enemy_turret_pos = enemy_turret
        self.current_state = BuilderState.DESTROY_AMMO_SOURCE
        return True
    def determine_defend_state(self, ct: Controller):
        defend_state: DefendState = self.state_map[BuilderState.DEFEND_HARVESTER]
        if ct.get_global_resources() > ct.get_harvester_cost() * 2:
            return False
        self.current_state = BuilderState.DEFEND_HARVESTER
        return True
    def determine_build_defensive_turret_state(self, ct: Controller):
        if ct.get_global_resources() > ct.get_gunner_cost() * 2:
            return False
        state: BuildTurretDefendState = self.state_map[BuilderState.BUILD_DEFENSIVE_TURRET]
        build = state.identify_build_pos(ct)
        if build == None:
            return False
        build_pos, build_dir = build
        if build_pos == None or build_dir == None:
            return False
        state.build_pos = build_pos
        state.build_dir = build_dir
        self.current_state = BuilderState.BUILD_DEFENSIVE_TURRET
        return True
        
>>>>>>> a12edd4ba89e00e139a5290528a15f8044537009
