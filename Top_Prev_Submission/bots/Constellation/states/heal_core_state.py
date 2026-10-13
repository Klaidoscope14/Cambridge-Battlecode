from cambc import Controller, GameConstants

from states.builder_state import BuilderState
from nav.common import common_path


class HealCoreState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.map_manager = brain.map_manager

    # Can improve to avoid turret spots
    def execute(self, ct: Controller):
        common_path(ct, self.map_manager, self.brain.pathing, self.brain.ally_core_pos)
        if ct.can_heal(self.brain.ally_core_pos):
            ct.heal(self.brain.ally_core_pos)

    def determine_heal_core_state(self, ct, state_manager):
        core_building = self.map_manager.get_building(self.brain.ally_core_pos)
        if core_building.hp <= GameConstants.CORE_MAX_HP - 20:
            state_manager.current_state = BuilderState.HEAL_CORE
            return True
        return False
