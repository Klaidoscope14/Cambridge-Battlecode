from cambc import Controller

from debug.profiling import cputimer
from roles.builder.helpers import HARVESTER_BUILDER_DIRECTIONS, RUSHER_DIRECTIONS, CENTER_DIRECTIONS, GUARD_DIRECTION

from states.builder_state import BuilderState
from states.build_harvester_state import BuildHarvesterState
from states.explore_state import ExploreState
from states.sabotage_state import SabotageState
from states.destroy_ammo_source_state import DestroyAmmoSourceState
from states.build_sentinel_state import BuildSentinelState
from states.build_gunner_state import BuildGunnerState
from states.build_launcher_state import BuildLauncherState
from states.steal_open_source_state import StealOpenSourceState
from states.heal_connection_state import HealConnectionState
from states.heal_core_state import HealCoreState
from states.connect_conveyor_state import ConnectConveyorState
from states.follow_state import FollowState
from states.rush_state import RushState
from states.trail_state import TrailState
from states.clean_turret_state import CleanTurretState
from states.connect_axionite_state import ConnectAxioniteState
from states.fix_foundry_state import FixFoundryState
from states.replace_with_foundry_state import ReplaceWithFoundryState
from states.replace_with_armoured_state import ReplaceWithArmouredState
from states.heal_turret_state import HealTurretState
from states.guard_state import GuardState
from states.center_state import CenterState
from states.fill_harvester_conveyor_state import FillHarvesterConveyorState
from states.rusher_build_harvester_state import RusherBuildHarvesterState

ROLE_LOCK_ROUNDS = 150
RUSHER_TITANIUM_THRESHOLD = 200
# Center bot demotes to explorer after seeing any higher-id ally bot
# for this many consecutive rounds.
CENTER_DEMOTION_ROUNDS = 200

class StateManager:
    def __init__(self, brain, ct: Controller, initial: BuilderState=BuilderState.EXPLORE) -> None:
        self.brain = brain
        self.previous_state = initial
        self.current_state = initial

        self.harvester_positions = {self.brain.map_manager.ally_core_pos.add(d) for d in HARVESTER_BUILDER_DIRECTIONS}
        self.center_positions = {self.brain.map_manager.ally_core_pos.add(d) for d in CENTER_DIRECTIONS}
        self.rusher_positions = {self.brain.map_manager.ally_core_pos.add(d) for d in RUSHER_DIRECTIONS}

        self.state_map = {
            BuilderState.EXPLORE: ExploreState(ct, brain),
            BuilderState.BUILD_HARVESTER: BuildHarvesterState(ct, brain),
            BuilderState.SABOTAGE: SabotageState(ct, brain),
            BuilderState.BUILD_SENTINEL: BuildSentinelState(ct, brain),
            BuilderState.BUILD_GUNNER: BuildGunnerState(ct, brain),
            BuilderState.BUILD_LAUNCHER: BuildLauncherState(ct, brain),
            BuilderState.STEAL_OPEN_SOURCE: StealOpenSourceState(ct, brain),
            BuilderState.DESTROY_AMMO_SOURCE: DestroyAmmoSourceState(ct, brain),
            BuilderState.HEAL_CONNECTION: HealConnectionState(ct, brain),
            BuilderState.HEAL_CORE: HealCoreState(ct, brain),
            BuilderState.CONNECT_CONVEYOR: ConnectConveyorState(ct, brain),
            BuilderState.FOLLOW: FollowState(ct, brain),
            BuilderState.RUSH: RushState(ct, brain),
            BuilderState.TRAIL: TrailState(ct, brain),
            BuilderState.CLEAN_TURRET: CleanTurretState(ct, brain),
            BuilderState.CONNECT_AXIONITE_STATE: ConnectAxioniteState(ct, brain),
            BuilderState.FIX_FOUNDRY_STATE: FixFoundryState(ct, brain),
            BuilderState.REPLACE_WITH_FOUNDRY_STATE: ReplaceWithFoundryState(ct, brain),
            BuilderState.REPLACE_WITH_ARMOURED_STATE: ReplaceWithArmouredState(ct, brain),
            BuilderState.HEAL_TURRET: HealTurretState(ct, brain),
            BuilderState.GUARD: GuardState(ct, brain),
            BuilderState.CENTER: CenterState(ct, brain),
            BuilderState.FILL_HARVESTER_CONVEYOR: FillHarvesterConveyorState(ct, brain),
            BuilderState.RUSHER_BUILD_HARVESTER: RusherBuildHarvesterState(ct, brain),
        }

        self._higher_id_streak: int = 0
        self._center_demoted: bool = False

    def _determine_explorer(self, ct):
        if self.brain.harvesters_built >= 4:
            self.current_state = BuilderState.GUARD
        else:
            self.current_state = BuilderState.EXPLORE
        (
            # DESTROY STATE
            self.state_map[BuilderState.DESTROY_AMMO_SOURCE].determine(ct, self)
            # CORE STATES
            or self.state_map[BuilderState.HEAL_CORE].determine(ct, self)
            or self.state_map[BuilderState.HEAL_CONNECTION].determine(ct, self)
            # TURRET STATES
            or self.state_map[BuilderState.BUILD_GUNNER].determine(ct, self)
            or self.state_map[BuilderState.FILL_HARVESTER_CONVEYOR].determine(ct, self)
            or self.state_map[BuilderState.HEAL_TURRET].determine(ct, self)
            or self.state_map[BuilderState.BUILD_SENTINEL].determine(ct, self)
            or self.state_map[BuilderState.CLEAN_TURRET].determine(ct, self)
            or self.state_map[BuilderState.FOLLOW].determine(ct, self)
            # CONNECT
            or self.state_map[BuilderState.FIX_FOUNDRY_STATE].determine(ct, self)
            or self.state_map[BuilderState.CONNECT_AXIONITE_STATE].determine(ct, self)
            or self.state_map[BuilderState.CONNECT_CONVEYOR].determine(ct, self)
            # BUILD
            or self.state_map[BuilderState.BUILD_LAUNCHER].determine(ct, self)
            or self.state_map[BuilderState.REPLACE_WITH_FOUNDRY_STATE].determine(ct, self)
            or self.state_map[BuilderState.BUILD_HARVESTER].determine(ct, self)
            # CLEAN TURRET STATE
            or self.state_map[BuilderState.GUARD].determine(ct, self)
            or self.state_map[BuilderState.REPLACE_WITH_ARMOURED_STATE].determine(ct, self)
        )

    def _determine_center(self, ct):
        self.current_state = BuilderState.CENTER
        (
            # DESTROY STATE
            self.state_map[BuilderState.DESTROY_AMMO_SOURCE].determine(ct, self)
            # CORE STATES
            or self.state_map[BuilderState.HEAL_CONNECTION].determine(ct, self)
            # TURRET STATES
            or self.state_map[BuilderState.BUILD_GUNNER].determine(ct, self)
            or self.state_map[BuilderState.FILL_HARVESTER_CONVEYOR].determine(ct, self)
            or self.state_map[BuilderState.HEAL_TURRET].determine(ct, self)
            or self.state_map[BuilderState.BUILD_SENTINEL].determine(ct, self)
            or self.state_map[BuilderState.HEAL_CORE].determine(ct, self)
            # BUILD LAUNCHER
            or self.state_map[BuilderState.BUILD_LAUNCHER].determine(ct, self)
            # CONNECT CONVEYOR
            or self.state_map[BuilderState.FOLLOW].determine(ct, self)
            or self.state_map[BuilderState.STEAL_OPEN_SOURCE].determine(ct, self)
            or self.state_map[BuilderState.CONNECT_CONVEYOR].determine(ct, self)
            or self.state_map[BuilderState.CLEAN_TURRET].determine(ct, self)
            or self.state_map[BuilderState.REPLACE_WITH_ARMOURED_STATE].determine(ct, self)
            # BUILD HARVESTER
            or self.state_map[BuilderState.BUILD_HARVESTER].determine(ct, self)
        )

    def _determine_rusher(self, ct):
        self.current_state = BuilderState.RUSH

        (
            # DESTROY STATE
            self.state_map[BuilderState.DESTROY_AMMO_SOURCE].determine(ct, self)
            # TURRET STATES
            or self.state_map[BuilderState.BUILD_GUNNER].determine(ct, self)
            or self.state_map[BuilderState.HEAL_TURRET].determine(ct, self)
            or self.state_map[BuilderState.FILL_HARVESTER_CONVEYOR].determine(ct, self)
            or self.state_map[BuilderState.BUILD_SENTINEL].determine(ct, self)
            or self.state_map[BuilderState.STEAL_OPEN_SOURCE].determine(ct, self)
            # HEAL STATES
            or self.state_map[BuilderState.HEAL_CORE].determine(ct, self)
            # SABOTAGE
            or self.state_map[BuilderState.BUILD_LAUNCHER].determine(ct, self)
            or self.state_map[BuilderState.RUSHER_BUILD_HARVESTER].determine(ct, self)
            or self.state_map[BuilderState.SABOTAGE].determine(ct, self)
            # TRAIL — lowest priority override above the RUSH default.
            or self.state_map[BuilderState.HEAL_CONNECTION].determine(ct, self)
            or self.state_map[BuilderState.CLEAN_TURRET].determine(ct, self)
            or (
                ct.get_global_resources()[0] < ct.get_harvester_cost()[0]
                and self.state_map[BuilderState.FOLLOW].determine(ct, self)
            )
            or self.state_map[BuilderState.TRAIL].determine(ct, self)
        )

    def _decide_role(self, ct):
        spawn_pos = self.brain.spawn_location
        if spawn_pos in self.harvester_positions:
            threshold = 1 if self.brain.spawn_round <= 2 else 2
            if self.brain.connections_built >= threshold:
                return False, True, False
            return True, False, False
        if spawn_pos in self.rusher_positions:
            return False, True, False
        if spawn_pos in self.center_positions:
            if self._center_demoted:
                return True, False, False
            return False, False, True
        return False, False, False

    def _has_open_ally_source_under_threat(self) -> bool:
        """True iff any nearby ally source/transport piece is open AND an
        enemy builder bot is in vision. Forces explorer mode regardless
        of role so the bot prioritises defending the open piece."""
        mm = self.brain.map_manager
        if not mm.nearby_enemy_builder_bot_ids:
            return False
        return bool(
            mm.nearby_ally_open_conveyor_ids
            or mm.nearby_ally_open_bridge_ids
            or mm.nearby_ally_open_empty_conveyor_ids
            or mm.nearby_ally_open_titanium_conveyor_ids
            or mm.nearby_ally_open_titanium_bridge_ids
            or mm.nearby_ally_open_raw_axionite_conveyor_ids
            or mm.nearby_ally_open_raw_axionite_bridge_ids
            or mm.nearby_ally_open_refined_axionite_conveyor_ids
            or mm.nearby_ally_open_refined_axionite_bridge_ids
        )

    def _tick_center_demotion(self, ct):
        if self._center_demoted:
            return
        my_id = ct.get_id()
        has_higher = any(
            rec.id > my_id for rec in self.brain.map_manager.nearby_ally_bot_ids
        )
        if has_higher:
            self._higher_id_streak += 1
            if self._higher_id_streak >= CENTER_DEMOTION_ROUNDS:
                self._center_demoted = True
                print("CENTER BOT DEMOTED TO EXPLORER")
        else:
            self._higher_id_streak = 0

    def _deep_in_enemy_territory(self) -> bool:
        """No ally conveyor/bridge visible but enemy conveyor AND bridge are."""
        mm = self.brain.map_manager
        if mm.nearby_ally_conveyor_ids or mm.nearby_ally_bridge_ids:
            return False
        return bool(mm.nearby_enemy_conveyor_ids and mm.nearby_enemy_bridge_ids)

    @cputimer
    def determine_state(self, ct):
        self.previous_state = self.current_state
        spawn_pos = self.brain.spawn_location
        if spawn_pos in self.center_positions:
            self._tick_center_demotion(ct)
        is_explorer, is_rusher, is_center = self._decide_role(ct)

        # Override: deep in enemy territory — behave as a rusher regardless of role.
        if self._deep_in_enemy_territory():
            is_explorer = False
            is_center = False
            is_rusher = True

        # EXPLORER
        if is_explorer:
            print("EXPLORER BOT")
            self._determine_explorer(ct)

        # RUSHER
        elif is_rusher:
            print("RUSHER BOT")
            self._determine_rusher(ct)

        # CENTER
        elif is_center:
            print("CENTER BOT")
            self._determine_center(ct)

    @cputimer
    def execute_state(self, ct):
        print(f"State: {self.current_state}")
        self.state_map[self.current_state].execute(ct)
