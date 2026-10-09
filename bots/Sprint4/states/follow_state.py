from cambc import Controller, Position

from helpers.directions import DIRECTIONS
from nav.common import save_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState


class FollowState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.target_pos: Position | None = None

    def execute(self, ct: Controller):
        if self.target_pos is None:
            return
        save_path(ct, self.brain.map_manager, self.brain.pathing, self.target_pos)

    def determine(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager

        if not mm.nearby_enemy_builder_bot_ids:
            return False

        # Only follow if we see ally buildings (other than roads) nearby.
        if not (
            mm.nearby_ally_harvester_ids
            or mm.nearby_ally_conveyor_ids
            or mm.nearby_ally_bridge_ids
            or mm.nearby_ally_splitter_ids
            or mm.nearby_ally_turret_ids
            or mm.nearby_ally_foundry_ids
        ):
            return False

        my_pos = ct.get_position()
        my_team = ct.get_team()

        # Find the closest uncontested enemy (no ally bot in any of the 8
        # directions around the enemy).
        reachable = self.brain.pathing._reachable
        best_pos = None
        best_dist = float('inf')
        for eid in mm.nearby_enemy_builder_bot_ids:
            epos = ct.get_position(eid)
            if (epos.x, epos.y) not in reachable:
                continue
            has_ally_nearby = False
            for d in DIRECTIONS:
                adj = epos.add(d)
                if not in_bounds(ct, adj):
                    continue
                if adj == my_pos:
                    continue
                bot = mm.get_bot(adj)
                if bot is not None and bot.team == my_team:
                    has_ally_nearby = True
                    break
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
