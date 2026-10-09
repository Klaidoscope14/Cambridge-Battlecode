from cambc import Controller, EntityType, Position

from debug.profiling import cputimer
from helpers.directions import DIRECTIONS
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState


STUCK_TURN_LIMIT = 4
BLACKLIST_DURATION = 15
MAX_CONVEYOR_DIST_SQ = 30

class FollowState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.target_pos: Position | None = None
        self.last_enemy_id: int | None = None
        self.confirmed_reachable_bots: set = set()  # enemy bot IDs ever seen on a reachable tile
        self.last_my_pos: Position | None = None
        self.stuck_turns: int = 0
        self.blacklisted_enemies: dict[int, int] = {}  # eid -> round when blacklist expires
        self.pending_move: bool = False

    def _blacklist(self, eid: int, current_round: int):
        self.blacklisted_enemies[eid] = current_round + BLACKLIST_DURATION

    def _move_toward_target(self, ct: Controller):
        if self.target_pos is None:
            return

        my_pos = ct.get_position()
        dist_sq = my_pos.distance_squared(self.target_pos)
        if dist_sq <= 2:
            self.last_my_pos = my_pos
            self.stuck_turns = 0
        elif self.last_my_pos is not None and my_pos == self.last_my_pos:
            self.stuck_turns += 1
            if self.stuck_turns >= STUCK_TURN_LIMIT and self.last_enemy_id is not None:
                self._blacklist(self.last_enemy_id, ct.get_current_round())
                self.last_enemy_id = None
                self.target_pos = None
                self.last_my_pos = None
                self.stuck_turns = 0
                return
        else:
            self.stuck_turns = 0
        self.last_my_pos = my_pos

        common_path(ct, self.brain.map_manager, self.brain.pathing, self.target_pos)

    def execute(self, ct: Controller):
        pass

    def _request_follow(self):
        self.pending_move = True
        self.brain.pathing.disable_moves = True

    def finalize(self, ct: Controller):
        if not self.pending_move:
            return
        self.pending_move = False
        self.brain.pathing.disable_moves = False
        self._move_toward_target(ct)

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager

        current_round = ct.get_current_round()
        if current_round < 30 and self.brain.harvesters_built == 0:
            return False

        if state_manager.previous_state == BuilderState.CONNECT_CONVEYOR:
            cc_state = state_manager.state_map[BuilderState.CONNECT_CONVEYOR]
            bp = cc_state.last_built_pos
            cc_state.last_built_pos = None
            if bp is not None and 0 <= bp.x < mm.width and 0 <= bp.y < mm.height:
                building = mm.building_grid[bp.x][bp.y]
                if building is not None:
                    my_team = ct.get_team()
                    bdir = building.direction
                    if bdir is not None:
                        tgt = bp.add(bdir)
                        if 0 <= tgt.x < mm.width and 0 <= tgt.y < mm.height:
                            tgt_b = mm.building_grid[tgt.x][tgt.y]
                            if tgt_b is not None and tgt_b.team != my_team:
                                return False
                            if tgt_b is not None and (tgt_b.entity_type == EntityType.ROAD or tgt_b.entity_type == EntityType.MARKER):
                                return False

        if self.blacklisted_enemies:
            self.blacklisted_enemies = {
                eid: exp for eid, exp in self.blacklisted_enemies.items() if exp > current_round
            }

        if not mm.nearby_enemy_builder_bot_ids:
            return False

        my_pos = ct.get_position()

        core_pos = mm.ally_core_pos
        cb_pos = mm.closest_ally_conveyor_bridge_pos

        # Triangle-inequality early-out: if we're so far from our base that
        # no enemy in vision could possibly be within MAX_CONVEYOR_DIST_SQ of
        # cb_pos, skip the whole matching pass.
        # Threshold: (sqrt(vision_sq) + sqrt(MAX_CONVEYOR_DIST_SQ))^2
        if cb_pos is not None:
            vision_sq = ct.get_vision_radius_sq()
            reach_sq = vision_sq + MAX_CONVEYOR_DIST_SQ + 2 * (vision_sq * MAX_CONVEYOR_DIST_SQ) ** 0.5
            if my_pos.distance_squared(cb_pos) > reach_sq:
                self.last_enemy_id = None
                return False

        my_team = ct.get_team()

        reachable = self.brain.pathing._reachable

        # Collect enemies: confirm reachable if on a reachable tile,
        # but also allow previously confirmed bots even if they moved off.
        enemy_positions = {}  # eid -> Position
        for rec in mm.nearby_enemy_builder_bot_ids:
            eid = rec.id
            if eid in self.blacklisted_enemies:
                continue
            epos = rec.position
            if (epos.x, epos.y) in reachable:
                self.confirmed_reachable_bots.add(eid)
                enemy_positions[eid] = epos
            elif eid in self.confirmed_reachable_bots:
                enemy_positions[eid] = epos

        if not enemy_positions:
            self.last_enemy_id = None
            return False

        # Top priority: stick with the bot we were last following if no
        # other ally is adjacent to it (i.e. we're the only one covering it).
        if self.last_enemy_id in enemy_positions:
            lepos = enemy_positions[self.last_enemy_id]
            has_other_ally = False
            for d in DIRECTIONS:
                adj = lepos.add(d)
                if not in_bounds(ct, adj) or adj == my_pos:
                    continue
                bot = mm.get_bot(adj)
                if bot is not None and bot.team == my_team:
                    has_other_ally = True
                    break
            if not has_other_ally:
                if cb_pos is not None and lepos.distance_squared(cb_pos) > MAX_CONVEYOR_DIST_SQ:
                    pass  # assigned bot too far from our base — fall through
                else:
                    if my_pos.distance_squared(lepos) <= 2:
                        self.brain.pathing.follow_pos = lepos
                        self.last_my_pos = None
                        self.stuck_turns = 0
                        return False
                    if self.target_pos != lepos:
                        self.last_my_pos = None
                        self.stuck_turns = 0
                    self.target_pos = lepos
                    self._request_follow()
                    return False

        # Greedy assignment: for each enemy, find adjacent ally bots and
        # claim the first unclaimed one. Sub-optimal vs. bipartite matching
        # in rare overlap cases, but ~O(E) instead of O(V*E).
        my_key = (my_pos.x, my_pos.y)
        match_ally = {}  # ally_key -> eid
        self_adj = []    # eids we are adjacent to

        for eid, epos in enemy_positions.items():
            assigned = False
            self_adjacent = False
            for d in DIRECTIONS:
                adj = epos.add(d)
                if not in_bounds(ct, adj):
                    continue
                if adj == my_pos:
                    self_adjacent = True
                    continue
                ally_key = (adj.x, adj.y)
                if ally_key in match_ally:
                    continue
                bot = mm.get_bot(adj)
                if bot is not None and bot.team == my_team:
                    match_ally[ally_key] = eid
                    assigned = True
                    break
            if not assigned and self_adjacent:
                self_adj.append(eid)

        # Take any enemy still unmatched that we're adjacent to
        matched_enemies = set(match_ally.values())
        for eid in self_adj:
            if eid not in matched_enemies:
                match_ally[my_key] = eid
                matched_enemies.add(eid)
                break
        if my_key not in match_ally:
            # We weren't matched, but there may be unmatched enemies
            # that no one is adjacent to — follow the closest one
            unmatched = [eid for eid in enemy_positions if eid not in matched_enemies]
            if not unmatched:
                self.last_enemy_id = None
                return False
            best_eid = min(
                unmatched,
                key=lambda eid: (
                    my_pos.distance_squared(enemy_positions[eid]),
                    core_pos.distance_squared(enemy_positions[eid]) if core_pos is not None else 0,
                ),
            )
            matched_eid = best_eid
            matched_epos = enemy_positions[best_eid]
        else:
            matched_eid = match_ally[my_key]
            matched_epos = enemy_positions[matched_eid]

        # Gate: only follow this assignment if it's near our base (closest
        # ally conveyor/bridge). If cb_pos is None (none ever seen) allow it.
        if cb_pos is not None and matched_epos.distance_squared(cb_pos) > MAX_CONVEYOR_DIST_SQ:
            self.last_enemy_id = None
            return False

        # If the enemy we're matched with is adjacent, set follow_pos and return False
        if my_pos.distance_squared(matched_epos) <= 2:
            self.brain.pathing.follow_pos = matched_epos
            self.last_enemy_id = None
            self.last_my_pos = None
            self.stuck_turns = 0
            return False

        # Enemy is not adjacent — request end-of-turn follow and fall through
        if self.last_enemy_id != matched_eid:
            self.last_my_pos = None
            self.stuck_turns = 0
        self.last_enemy_id = matched_eid
        self.target_pos = matched_epos
        self._request_follow()
        return False
