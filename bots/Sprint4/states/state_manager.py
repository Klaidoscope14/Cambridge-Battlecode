from cambc import Controller

from debug.profiling import cputimer
from roles.builder.helpers import HARVESTER_BUILDER_DIRECTIONS, RUSHER_DIRECTIONS, GUARD_DIRECTION

from states.builder_state import BuilderState
from states.build_harvester_state import BuildHarvesterState
from states.explore_state import ExploreState
from states.sabotage_bridge_state import SabotageBridgeState
from states.sabotage_source_state import SabotageSourceState
from states.sabotage_conveyer_state import SabotageConveyorState
from states.destroy_ammo_source_state import DestroyAmmoSourceState
from states.build_sentinel_state import BuildSentinelState
from states.build_gunner_state import BuildGunnerState
from states.heal_connection_state import HealConnectionState
from states.heal_core_state import HealCoreState
from states.connect_conveyor_state import ConnectConveyorState
from states.follow_state import FollowState
from states.rush_state import RushState
from states.clean_turret_state import CleanTurretState
from states.connect_axionite_state import ConnectAxioniteState
from states.fix_foundry_state import FixFoundryState
from states.replace_with_foundry_state import ReplaceWithFoundryState
from states.heal_turret_state import HealTurretState
from states.guard_state import GuardState

class StateManager:
    def __init__(self, brain, ct: Controller, initial: BuilderState=BuilderState.EXPLORE) -> None:
        self.brain = brain
        self.previous_state = initial
        self.current_state = initial

        self.harvester_positions = {self.brain.map_manager.ally_core_pos.add(d) for d in HARVESTER_BUILDER_DIRECTIONS}
        self.rusher_positions = {self.brain.map_manager.ally_core_pos.add(d) for d in RUSHER_DIRECTIONS}

        self.state_map = {
            BuilderState.EXPLORE: ExploreState(ct, brain),
            BuilderState.BUILD_HARVESTER: BuildHarvesterState(ct, brain),
            BuilderState.SABOTAGE_BRIDGE: SabotageBridgeState(ct, brain),
            BuilderState.SABOTAGE_SOURCE: SabotageSourceState(ct, brain),
            BuilderState.SABOTAGE_CONVEYOR: SabotageConveyorState(ct, brain),
            BuilderState.BUILD_SENTINEL: BuildSentinelState(ct, brain),
            BuilderState.BUILD_GUNNER: BuildGunnerState(ct, brain),
            BuilderState.DESTROY_AMMO_SOURCE: DestroyAmmoSourceState(ct, brain),
            BuilderState.HEAL_CONNECTION: HealConnectionState(ct, brain),
            BuilderState.HEAL_CORE: HealCoreState(ct, brain),
            BuilderState.CONNECT_CONVEYOR: ConnectConveyorState(ct, brain),
            BuilderState.FOLLOW: FollowState(ct, brain),
            BuilderState.RUSH: RushState(ct, brain),
            BuilderState.CLEAN_TURRET: CleanTurretState(ct, brain),
            BuilderState.CONNECT_AXIONITE_STATE: ConnectAxioniteState(ct, brain),
            BuilderState.FIX_FOUNDRY_STATE: FixFoundryState(ct, brain),
            BuilderState.REPLACE_WITH_FOUNDRY_STATE: ReplaceWithFoundryState(ct, brain),
            BuilderState.HEAL_TURRET: HealTurretState(ct, brain),
            BuilderState.GUARD: GuardState(ct, brain)
        }

    # Determine state from spawn location
    def determine_state(self, ct):
        self.previous_state = self.current_state
        spawn_pos = self.brain.spawn_location

        # EXPLORER
        if spawn_pos in self.harvester_positions:
            self.current_state = BuilderState.EXPLORE
            # Priority order: highest priority first, short-circuit on first match
            (
                # DESTROY STATE
                self.state_map[BuilderState.DESTROY_AMMO_SOURCE].determine(ct, self)
                # HEAL STATES
                or self.state_map[BuilderState.HEAL_CORE].determine(ct, self)
                or self.state_map[BuilderState.HEAL_CONNECTION].determine(ct, self)
                # TURRET STATES
                or self.state_map[BuilderState.BUILD_GUNNER].determine(ct, self)
                or self.state_map[BuilderState.HEAL_TURRET].determine(ct, self)
                or self.state_map[BuilderState.BUILD_SENTINEL].determine(ct, self)
                # FOLLOW
                or self.state_map[BuilderState.FOLLOW].determine(ct, self)
                # AXIONITE
                or self.state_map[BuilderState.REPLACE_WITH_FOUNDRY_STATE].determine(ct, self)
                or self.state_map[BuilderState.FIX_FOUNDRY_STATE].determine(ct, self)
                or self.state_map[BuilderState.CONNECT_AXIONITE_STATE].determine(ct, self)
                # CONNECT CONVEYOR
                or self.state_map[BuilderState.CONNECT_CONVEYOR].determine(ct, self)
                # BUILD HARVESTER
                or self.state_map[BuilderState.BUILD_HARVESTER].determine(ct, self)
                # CLEAN TURRET STATE
                or self.state_map[BuilderState.CLEAN_TURRET].determine(ct, self)
            )

        # RUSHER
        elif spawn_pos in self.rusher_positions:
            self.current_state = BuilderState.RUSH
            (
                # DESTROY STATE
                self.state_map[BuilderState.DESTROY_AMMO_SOURCE].determine(ct, self)
                # HEAL STATES
                or self.state_map[BuilderState.HEAL_CORE].determine(ct, self)
                or self.state_map[BuilderState.HEAL_CONNECTION].determine(ct, self)
                # TURRET STATES
                or self.state_map[BuilderState.BUILD_GUNNER].determine(ct, self)
                or self.state_map[BuilderState.HEAL_TURRET].determine(ct, self)
                or self.state_map[BuilderState.BUILD_SENTINEL].determine(ct, self)
                # SABOTAGE STATES
                or self.state_map[BuilderState.SABOTAGE_SOURCE].determine(ct, self)
                or self.state_map[BuilderState.SABOTAGE_BRIDGE].determine(ct, self)
                or self.state_map[BuilderState.SABOTAGE_CONVEYOR].determine(ct, self)
            )

    @cputimer
    def execute_state(self, ct):
        print(f"State: {self.current_state}")
        self.state_map[self.current_state].execute(ct)
