from cambc import Controller

from debug.profiling import cputimer
from roles.builder.helpers import HARVESTER_BUILDER_DIRECTION, RUSHER_DIRECTION

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
from states.guard_state import GuardState
from states.rush_state import RushState
from states.connect_axionite_state import ConnectAxioniteState
from states.replace_with_foundry_state import ReplaceWithFoundry
from states.fix_foundry_state import FixFoundry

class StateManager:
    def __init__(self, brain, ct: Controller, initial: BuilderState=BuilderState.EXPLORE) -> None:
        self.brain = brain
        self.previous_state = initial
        self.current_state = initial

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
            BuilderState.GUARD: GuardState(ct, brain),
            BuilderState.RUSH: RushState(ct, brain),
            BuilderState.CONNECT_AXIONITE_STATE: ConnectAxioniteState(ct, brain),
            BuilderState.REPLACE_WITH_FOUNDRY_STATE: ReplaceWithFoundry(ct, brain),
            BuilderState.FIX_FOUNDRY_STATE: FixFoundry(ct, brain)
        }

    # Determine state from spawn location
    def determine_state(self, ct):
        self.previous_state = self.current_state
        ally_core = self.brain.map_manager.ally_core_pos
        spawn_pos = self.brain.spawn_location

        # EXPLORER
        if spawn_pos == ally_core.add(HARVESTER_BUILDER_DIRECTION):
            if self.brain.harvester_built:
                self.current_state = BuilderState.GUARD
            else:
                self.current_state = BuilderState.EXPLORE
            # Priority order: highest priority first, short-circuit on first match
            (
                # DESTROY STATE
                self.determine_destroy_ammo_source_state(ct)

                # HEAL STATES
                or self.determine_heal_core_state(ct)
                or self.determine_heal_connection_state(ct)

                # TURRET STATES
                or self.determine_build_gunner_state(ct)
                or self.determine_build_sentinel_state(ct)

                # BRIDGING STATES
                # or self.determine_fix_foundry_state(ct)
                # or self.determine_replace_with_foundry_state(ct)
                # or self.determine_connect_axionite_state(ct)
                or self.determine_connect_conveyor_state(ct)

                # FOLLOW ENEMY
                or self.determine_follow_state(ct)

                # BUILD HARVESTER
                or self.determine_build_harvester_state(ct)
            )
        
        # RUSHER
        elif spawn_pos == ally_core.add(RUSHER_DIRECTION):
            self.current_state = BuilderState.RUSH

            (
                # DESTROY STATE
                self.determine_destroy_ammo_source_state(ct)

                # HEAL STATES
                or self.determine_heal_core_state(ct)
                or self.determine_heal_connection_state(ct)

                # TURRET STATES
                or self.determine_build_gunner_state(ct)
                or self.determine_build_sentinel_state(ct)

                # SABOTAGE STATES
                or self.determine_sabotage_source_state(ct)
                or self.determine_sabotage_bridge_state(ct)
                or self.determine_sabotage_conveyor_state(ct)
            )

    @cputimer
    def execute_state(self, ct):
        print(f"State: {self.current_state}")
        self.state_map[self.current_state].execute(ct)

    def determine_follow_state(self, ct):
        return self.state_map[BuilderState.FOLLOW].determine_follow_state(ct, self)

    def determine_build_harvester_state(self, ct):
        return self.state_map[BuilderState.BUILD_HARVESTER].determine_build_harvester_state(ct, self)

    def determine_core_connect_state(self, ct):
        return self.state_map[BuilderState.CORE_CONNECT].determine_core_connect_state(ct, self)

    def determine_repair_bridge_state(self, ct):
        return self.state_map[BuilderState.REPAIR_BRIDGE].determine_repair_bridge_state(ct, self)

    def determine_sabotage_source_state(self, ct):
        return self.state_map[BuilderState.SABOTAGE_SOURCE].determine_sabotage_source_state(ct, self)

    def determine_sabotage_bridge_state(self, ct):
        return self.state_map[BuilderState.SABOTAGE_BRIDGE].determine_sabotage_bridge_state(ct, self)
    
    def determine_sabotage_conveyor_state(self, ct):
        return self.state_map[BuilderState.SABOTAGE_CONVEYOR].determine_sabotage_conveyor_state(ct, self)

    def determine_fortify_bridge_state(self, ct: Controller):
        return self.state_map[BuilderState.FORTIFY_BRIDGE].determine_fortify_bridge_state(ct, self)

    def determine_heal_connection_state(self, ct):
        return self.state_map[BuilderState.HEAL_CONNECTION].determine_heal_connection_state(ct, self)
    
    def determine_heal_core_state(self, ct):
        return self.state_map[BuilderState.HEAL_CORE].determine_heal_core_state(ct, self)
    
    def determine_destroy_ammo_source_state(self, ct):
        return self.state_map[BuilderState.DESTROY_AMMO_SOURCE].determine_destroy_ammo_source_state(ct, self)
    
    def determine_connect_conveyor_state(self, ct):
        return self.state_map[BuilderState.CONNECT_CONVEYOR].determine_connect_conveyor_state(ct, self)

    def determine_build_sentinel_state(self, ct):
        return self.state_map[BuilderState.BUILD_SENTINEL].determine_build_sentinel_state(ct, self)
    
    def determine_build_gunner_state(self, ct):
        return self.state_map[BuilderState.BUILD_GUNNER].determine_build_gunner_state(ct, self)
    
    def determine_connect_axionite_state(self, ct):
        return self.state_map[BuilderState.CONNECT_AXIONITE_STATE].determine_connect_axionite_state(ct, self)
    
    def determine_replace_with_foundry_state(self, ct):
        return self.state_map[BuilderState.REPLACE_WITH_FOUNDRY_STATE].determine_replace_with_foundry_state(ct, self)
    
    def determine_fix_foundry_state(self, ct):
        return self.state_map[BuilderState.FIX_FOUNDRY_STATE].determine_fix_foundry_state(ct, self)
