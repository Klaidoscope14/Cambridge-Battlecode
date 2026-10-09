from cambc import Controller, Position

from nav.common import save_path
from states.builder_state import BuilderState

# Distance squared within which an ally bot counts as "covering" an enemy
FOLLOW_ALLY_PROXIMITY_SQ = 8


class FollowState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.target_pos: Position | None = None

    def execute(self, ct: Controller):
        if self.target_pos is None:
            return
        save_path(ct, self.brain.map_manager, self.brain.pathing, self.target_pos)

    def determine_follow_state(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager

        if not mm.nearby_enemy_builder_bot_ids:
            return False

        my_pos = ct.get_position()

        # Collect ally bot positions, excluding ourselves
        ally_positions = []
        for aid in mm.nearby_ally_bot_ids:
            apos = ct.get_position(aid)
            if apos == my_pos:
                continue
            ally_positions.append(apos)

        # Find the closest uncontested enemy (no ally within FOLLOW_ALLY_PROXIMITY_SQ)
        best_pos = None
        best_dist = float('inf')
        for eid in mm.nearby_enemy_builder_bot_ids:
            epos = ct.get_position(eid)
            has_ally_nearby = any(
                apos.distance_squared(epos) <= FOLLOW_ALLY_PROXIMITY_SQ
                for apos in ally_positions
            )
            if has_ally_nearby:
                continue
            dist = my_pos.distance_squared(epos)
            if dist < best_dist:
                best_dist = dist
                best_pos = epos

        if best_pos is None:
            return False

        self.target_pos = best_pos
        state_manager.current_state = BuilderState.FOLLOW
        return True
