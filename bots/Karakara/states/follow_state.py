from cambc import Controller, EntityType, Position

from debug.profiling import cputimer
from helpers.directions import DIRECTIONS
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState


STUCK_TURN_LIMIT = 4
BLACKLIST_DURATION = 15
MAX_CONVEYOR_DIST_SQ = 30

# When (lower-id-allies + self) * enemies <= this, run a deterministic
# cross-bot assignment simulation instead of the cheap pairing heuristic
# below. Each bot computes the same result, so allies don't dogpile.
SIM_THRESHOLD = 20


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
        following = self._determine_inner(ct, state_manager)
        print(f"[Follow r{ct.get_current_round()} b{ct.get_id()}] following={following}")
        return False

    def _determine_inner(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager

        current_round = ct.get_current_round()
        if current_round < 30 and not mm._ally_harvesters:
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
        anchor_pos = cb_pos if cb_pos is not None else core_pos

        if anchor_pos is not None:
            vision_sq = ct.get_vision_radius_sq()
            reach_sq = vision_sq + MAX_CONVEYOR_DIST_SQ + 2 * (vision_sq * MAX_CONVEYOR_DIST_SQ) ** 0.5
            if my_pos.distance_squared(anchor_pos) > reach_sq:
                self.last_enemy_id = None
                return False

        my_team = ct.get_team()

        reachable = self.brain.reachable

        enemy_positions = {}  # eid -> Position
        for rec in mm.nearby_enemy_builder_bot_ids:
            eid = rec.id
            if eid in self.blacklisted_enemies:
                continue
            epos = rec.position
            if anchor_pos is not None and epos.distance_squared(anchor_pos) > MAX_CONVEYOR_DIST_SQ:
                continue
            if (epos.x, epos.y) in reachable:
                self.confirmed_reachable_bots.add(eid)
                enemy_positions[eid] = epos
            elif eid in self.confirmed_reachable_bots:
                enemy_positions[eid] = epos

        if not enemy_positions:
            self.last_enemy_id = None
            return False

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
            closer_to_anchor = False
            if anchor_pos is not None:
                cur_anchor_d = lepos.distance_squared(anchor_pos)
                for eid, epos in enemy_positions.items():
                    if eid == self.last_enemy_id:
                        continue
                    if epos.distance_squared(anchor_pos) + 4 < cur_anchor_d:
                        closer_to_anchor = True
                        break
            if not has_other_ally and not closer_to_anchor:
                if my_pos.distance_squared(lepos) <= 2:
                    print(f"[Follow] sticky-adjacent: prev enemy {self.last_enemy_id}@{lepos} adjacent (sole cover)")
                    self.brain.pathing.follow_pos = lepos
                    self.last_my_pos = None
                    self.stuck_turns = 0
                    return True
                if self.target_pos != lepos:
                    self.last_my_pos = None
                    self.stuck_turns = 0
                print(f"[Follow] sticky-chase: prev enemy {self.last_enemy_id}@{lepos} (sole cover, d²={my_pos.distance_squared(lepos)})")
                self.target_pos = lepos
                self._request_follow()
                return True

        # Deterministic cross-bot assignment when the search space is small.
        # Each bot considers self + lower-id allies and runs the same greedy
        # one-sided pairing; ties resolve to the higher id (i.e. self), so
        # all bots agree on who chases whom without re-running per-tile work.
        my_id = ct.get_id()
        sim_allies = [b for b in mm.nearby_ally_bot_ids if b.id != my_id]
        if (len(sim_allies) + 1) * len(enemy_positions) <= SIM_THRESHOLD:
            sim_bots = [(b.id, b.position) for b in sim_allies]
            sim_bots.append((my_id, my_pos))

            # Drop enemies that already have an ally adjacent (someone else
            # is covering them) so the sim doesn't dogpile.
            covered = set()
            for eid, epos in enemy_positions.items():
                for d in DIRECTIONS:
                    adj = epos.add(d)
                    if not in_bounds(ct, adj) or adj == my_pos:
                        continue
                    bot = mm.get_bot(adj)
                    if bot is not None and bot.team == my_team:
                        covered.add(eid)
                        break
            sim_enemies = {eid: epos for eid, epos in enemy_positions.items() if eid not in covered}

            if not sim_enemies:
                print(f"[Follow] sim-yield: all enemies already covered by adjacent allies")
                self.last_enemy_id = None
                return False

            # Iterate enemies in deterministic order so every bot computes
            # the same pairing.
            enemy_items = sorted(sim_enemies.items())
            assigned = set()
            my_match_eid = None
            my_match_epos = None
            for eid, epos in enemy_items:
                best_bid = None
                best_d = None
                for bid, bpos in sim_bots:
                    if bid in assigned:
                        continue
                    d = bpos.distance_squared(epos)
                    if best_d is None or d < best_d or (d == best_d and bid > best_bid):
                        best_d = d
                        best_bid = bid
                if best_bid is None:
                    break
                assigned.add(best_bid)
                if best_bid == my_id:
                    my_match_eid = eid
                    my_match_epos = epos
                    break

            if my_match_eid is None:
                print(f"[Follow] sim-yield: lower-id allies cover all enemies")
                self.last_enemy_id = None
                return False

            if my_pos.distance_squared(my_match_epos) <= 2:
                print(f"[Follow] sim-adjacent: enemy {my_match_eid}@{my_match_epos}")
                self.brain.pathing.follow_pos = my_match_epos
                self.last_enemy_id = None
                self.last_my_pos = None
                self.stuck_turns = 0
                return True

            if self.last_enemy_id != my_match_eid:
                self.last_my_pos = None
                self.stuck_turns = 0
            print(f"[Follow] sim-chase: enemy {my_match_eid}@{my_match_epos} from {my_pos} (d²={my_pos.distance_squared(my_match_epos)})")
            self.last_enemy_id = my_match_eid
            self.target_pos = my_match_epos
            self._request_follow()
            return True

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

        matched_enemies = set(match_ally.values())
        for eid in self_adj:
            if eid not in matched_enemies:
                match_ally[my_key] = eid
                matched_enemies.add(eid)
                break
        if my_key not in match_ally:
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

        if my_pos.distance_squared(matched_epos) <= 2:
            print(f"[Follow] adjacent-match: enemy {matched_eid}@{matched_epos} adjacent")
            self.brain.pathing.follow_pos = matched_epos
            self.last_enemy_id = None
            self.last_my_pos = None
            self.stuck_turns = 0
            return True

        if self.last_enemy_id != matched_eid:
            self.last_my_pos = None
            self.stuck_turns = 0
        print(f"[Follow] chase-match: enemy {matched_eid}@{matched_epos} from {my_pos} (d²={my_pos.distance_squared(matched_epos)})")
        self.last_enemy_id = matched_eid
        self.target_pos = matched_epos
        self._request_follow()
        return True
