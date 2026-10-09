from cambc import Controller, Position

from debug.profiling import cputimer
from helpers.directions import DIRECTIONS
from nav.common import common_path
from roles.builder.helpers import in_bounds
from states.builder_state import BuilderState


DEBUG = False

STUCK_TURN_LIMIT = 4
BLACKLIST_DURATION = 15

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

    def _pfx(self, ct: Controller) -> str:
        p = ct.get_position()
        return f"[FOLLOW r{ct.get_current_round()} id{ct.get_id()}@({p.x},{p.y})]"

    def _blacklist(self, eid: int, current_round: int):
        self.blacklisted_enemies[eid] = current_round + BLACKLIST_DURATION
        if DEBUG:
            print(f"[FOLLOW] blacklisting enemy {eid} until round {current_round + BLACKLIST_DURATION}")

    def execute(self, ct: Controller):
        pfx = self._pfx(ct) if DEBUG else ""
        if self.target_pos is None:
            if DEBUG:
                print(f"{pfx} execute: target_pos is None, returning")
            return

        my_pos = ct.get_position()
        dist_sq = my_pos.distance_squared(self.target_pos)
        if dist_sq <= 2:
            if DEBUG:
                print(f"{pfx} execute: adjacent to target_pos={self.target_pos} (dist_sq={dist_sq}), skipping stuck check")
            self.last_my_pos = my_pos
            self.stuck_turns = 0
        elif self.last_my_pos is not None and my_pos == self.last_my_pos:
            self.stuck_turns += 1
            if DEBUG:
                print(f"{pfx} execute: no movement (dist_sq={dist_sq} to target={self.target_pos}), stuck_turns={self.stuck_turns}/{STUCK_TURN_LIMIT}")
            if self.stuck_turns >= STUCK_TURN_LIMIT and self.last_enemy_id is not None:
                if DEBUG:
                    print(f"{pfx} execute: STUCK — blacklisting enemy {self.last_enemy_id} and exiting follow")
                self._blacklist(self.last_enemy_id, ct.get_current_round())
                self.last_enemy_id = None
                self.target_pos = None
                self.last_my_pos = None
                self.stuck_turns = 0
                return
        else:
            if DEBUG and self.last_my_pos is not None:
                print(f"{pfx} execute: progress made (was {self.last_my_pos}), stuck_turns reset")
            self.stuck_turns = 0
        self.last_my_pos = my_pos

        if DEBUG:
            print(f"{pfx} execute: pathing to target_pos={self.target_pos} (dist_sq={dist_sq})")
        common_path(ct, self.brain.map_manager, self.brain.pathing, self.target_pos)
        my_pos = ct.get_position()
        my_team = ct.get_team()

        for d in DIRECTIONS:
            adj = my_pos.add(d)
            if not in_bounds(ct, adj):
                continue
            building = self.brain.map_manager.get_building(adj)
            if building is not None and building.team == my_team and building.max_hp - building.hp >= 4:
                if ct.can_heal(adj):
                    if DEBUG:
                        print(f"{pfx} execute: healing building at {adj} hp={building.hp}/{building.max_hp}")
                    ct.heal(adj)
                    return


    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager
        pfx = self._pfx(ct) if DEBUG else ""

        current_round = ct.get_current_round()
        if current_round < 75 and self.brain.harvesters_built == 0:
            return False

        if self.blacklisted_enemies:
            before = len(self.blacklisted_enemies)
            self.blacklisted_enemies = {
                eid: exp for eid, exp in self.blacklisted_enemies.items() if exp > current_round
            }
            if DEBUG and len(self.blacklisted_enemies) != before:
                print(f"{pfx} determine: expired {before - len(self.blacklisted_enemies)} blacklist entries, remaining={list(self.blacklisted_enemies.keys())}")

        if not mm.nearby_enemy_builder_bot_ids:
            if DEBUG:
                print(f"{pfx} determine: REJECT — no nearby enemy builder bots")
            return False

        my_pos = ct.get_position()
        my_team = ct.get_team()

        # Only follow if we see ally buildings (other than roads) nearby.
        # if not (
        #     mm.nearby_ally_harvester_ids
        #     or mm.nearby_ally_conveyor_ids
        #     or mm.nearby_ally_bridge_ids
        #     or mm.nearby_ally_splitter_ids
        #     or mm.nearby_ally_turret_ids
        #     or mm.nearby_ally_foundry_ids
        # ):
        #     if DEBUG:
        #         print(f"{pfx} determine: REJECT — {len(mm.nearby_enemy_builder_bot_ids)} nearby enemy builders but no ally buildings to defend")
        #     return False

        reachable = self.brain.pathing._reachable

        # Collect enemies: confirm reachable if on a reachable tile,
        # but also allow previously confirmed bots even if they moved off.
        enemy_positions = {}  # eid -> Position
        skipped_blacklist = []
        skipped_unreachable = []
        for eid in mm.nearby_enemy_builder_bot_ids:
            if eid in self.blacklisted_enemies:
                skipped_blacklist.append(eid)
                continue
            epos = ct.get_position(eid)
            if (epos.x, epos.y) in reachable:
                self.confirmed_reachable_bots.add(eid)
                enemy_positions[eid] = epos
            elif eid in self.confirmed_reachable_bots:
                enemy_positions[eid] = epos
            else:
                skipped_unreachable.append((eid, (epos.x, epos.y)))

        if DEBUG and (skipped_blacklist or skipped_unreachable):
            print(f"{pfx} determine: filtered enemies — blacklisted={skipped_blacklist} unreachable={skipped_unreachable}")

        if not enemy_positions:
            if DEBUG:
                print(f"{pfx} determine: REJECT — no reachable enemies after filtering (raw={list(mm.nearby_enemy_builder_bot_ids)})")
            self.last_enemy_id = None
            return False

        if DEBUG:
            eposes = [(eid, (p.x, p.y), my_pos.distance_squared(p)) for eid, p in enemy_positions.items()]
            print(f"{pfx} determine: {len(enemy_positions)} candidate enemies (eid,pos,dist_sq): {eposes}")

        # Top priority: stick with the bot we were last following if no
        # other ally is adjacent to it (i.e. we're the only one covering it).
        if self.last_enemy_id in enemy_positions:
            lepos = enemy_positions[self.last_enemy_id]
            has_other_ally = False
            other_ally_pos = None
            for d in DIRECTIONS:
                adj = lepos.add(d)
                if not in_bounds(ct, adj) or adj == my_pos:
                    continue
                bot = mm.get_bot(adj)
                if bot is not None and bot.team == my_team:
                    has_other_ally = True
                    other_ally_pos = (adj.x, adj.y)
                    break
            if not has_other_ally:
                if my_pos.distance_squared(lepos) <= 2:
                    if DEBUG:
                        print(f"{pfx} determine: STICK — adjacent to last enemy {self.last_enemy_id} at ({lepos.x},{lepos.y}), setting follow_pos")
                    self.brain.pathing.follow_pos = lepos
                    self.last_my_pos = None
                    self.stuck_turns = 0
                    return False
                if DEBUG:
                    print(f"{pfx} determine: STICK — continuing to path toward last enemy {self.last_enemy_id} at ({lepos.x},{lepos.y}) dist_sq={my_pos.distance_squared(lepos)}")
                if self.target_pos != lepos:
                    self.last_my_pos = None
                    self.stuck_turns = 0
                self.target_pos = lepos
                state_manager.current_state = BuilderState.FOLLOW
                return True
            elif DEBUG:
                print(f"{pfx} determine: last enemy {self.last_enemy_id} at ({lepos.x},{lepos.y}) already covered by ally at {other_ally_pos}, falling through to matching")
        elif DEBUG and self.last_enemy_id is not None:
            print(f"{pfx} determine: last_enemy_id {self.last_enemy_id} no longer in candidate set")

        # Build bipartite graph: for each enemy, find adjacent ally bots
        # ally key = (x, y), edges[eid] = set of ally keys
        my_key = (my_pos.x, my_pos.y)
        edges = {}  # eid -> set of (x, y)
        for eid, epos in enemy_positions.items():
            adj_allies = set()
            for d in DIRECTIONS:
                adj = epos.add(d)
                if not in_bounds(ct, adj):
                    continue
                if adj == my_pos:
                    adj_allies.add(my_key)
                    continue
                bot = mm.get_bot(adj)
                if bot is not None and bot.team == my_team:
                    adj_allies.add((adj.x, adj.y))
            edges[eid] = adj_allies

        # Maximum bipartite matching via augmenting paths
        # match_ally[ally_key] = eid that this ally is matched to
        match_ally = {}

        def try_assign(eid, visited):
            for ally_key in edges[eid]:
                if ally_key in visited:
                    continue
                visited.add(ally_key)
                if ally_key not in match_ally or try_assign(match_ally[ally_key], visited):
                    match_ally[ally_key] = eid
                    return True
            return False

        # First pass: match all other allies, excluding ourselves
        for eid in enemy_positions:
            edges[eid].discard(my_key)
        for eid in enemy_positions:
            try_assign(eid, set())

        if DEBUG:
            print(f"{pfx} determine: bipartite edges (excl me): {[(eid, list(edges[eid])) for eid in enemy_positions]}")
            print(f"{pfx} determine: first-pass matching: {match_ally}")

        # Second pass: re-add ourselves and try to improve the matching
        for eid in enemy_positions:
            epos = enemy_positions[eid]
            for d in DIRECTIONS:
                adj = epos.add(d)
                if adj == my_pos:
                    edges[eid].add(my_key)
                    break
        for eid in enemy_positions:
            if eid not in set(match_ally.values()):
                try_assign(eid, set())

        if DEBUG:
            print(f"{pfx} determine: final matching: {match_ally}")

        # Check if we were needed in the matching
        matched_enemies = set(match_ally.values())
        if my_key not in match_ally:
            # We weren't matched, but there may be unmatched enemies
            # that no one is adjacent to — follow the closest one
            unmatched = [eid for eid in enemy_positions if eid not in matched_enemies]
            if not unmatched:
                if DEBUG:
                    print(f"{pfx} determine: REJECT — all {len(enemy_positions)} enemies covered by other allies, we're not needed")
                self.last_enemy_id = None
                return False
            core_pos = mm.ally_core_pos
            best_eid = min(
                unmatched,
                key=lambda eid: (
                    my_pos.distance_squared(enemy_positions[eid]),
                    core_pos.distance_squared(enemy_positions[eid]) if core_pos is not None else 0,
                ),
            )
            matched_eid = best_eid
            matched_epos = enemy_positions[best_eid]
            if DEBUG:
                print(f"{pfx} determine: not adjacent to any enemy, picking closest unmatched enemy {matched_eid} at ({matched_epos.x},{matched_epos.y}) from unmatched={unmatched}")
        else:
            matched_eid = match_ally[my_key]
            matched_epos = enemy_positions[matched_eid]
            if DEBUG:
                print(f"{pfx} determine: matched to enemy {matched_eid} at ({matched_epos.x},{matched_epos.y})")

        # If the enemy we're matched with is adjacent, set follow_pos and return False
        if my_pos.distance_squared(matched_epos) <= 2:
            if DEBUG:
                print(f"{pfx} determine: MATCHED-ADJACENT enemy {matched_eid} at ({matched_epos.x},{matched_epos.y}), setting follow_pos and returning False")
            self.brain.pathing.follow_pos = matched_epos
            self.last_enemy_id = None
            self.last_my_pos = None
            self.stuck_turns = 0
            return False

        # Enemy is not adjacent, enter follow state to path towards them
        if DEBUG:
            print(f"{pfx} determine: ENTER FOLLOW — pathing to enemy {matched_eid} at ({matched_epos.x},{matched_epos.y}) dist_sq={my_pos.distance_squared(matched_epos)}")
        if self.last_enemy_id != matched_eid:
            self.last_my_pos = None
            self.stuck_turns = 0
        self.last_enemy_id = matched_eid
        self.target_pos = matched_epos
        state_manager.current_state = BuilderState.FOLLOW
        return True
