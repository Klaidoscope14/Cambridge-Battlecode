from cambc import Controller, EntityType, GameConstants
from debug.profiling import cputimer
from map.map_manager import MapManager
from nav.common import common_path
from states.builder_state import BuilderState

DEBUG = False

# Builder bots can heal any tile within king (Chebyshev) distance 1,
# i.e. the 3x3 footprint around the bot.
_HEAL_KING_RADIUS = 1
_ENEMY_BUILDER_DPR = 2   # enemy builder damage per round
_HEAL_PER_ROUND = 4      # ally builder heal per round


def _king_distance(a, b):
    """Chebyshev ("king move") distance — the true turn count on a grid
    with 8-directional movement."""
    dx = a.x - b.x
    dy = a.y - b.y
    if dx < 0: dx = -dx
    if dy < 0: dy = -dy
    return dx if dx > dy else dy


class HealConnectionState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.heal_pos = None

    def _pick_heal_target(self, ct: Controller):
        """Pick the best tile to heal, or None if nothing is worth doing.

        Selection runs in priority tiers:

        Pre-tier: damaged sentinel/breach turrets (losing a turret is
            strategically worse than losing any single connection tile).
        Tier 1: in-radius connection under attack. Sort by lowest hp first
            so alternation between two attacked tiles happens naturally.
            Applies a "defer" rule: if only one in-radius tile is under
            attack, it survives one more round, and the current heal would
            waste hp, skip it this round. Next round the tile will be at
            full heal efficiency. Produces the "heal every 2 rounds at
            full value" pattern for single-attacker scenarios.
        Tier 2: in-radius connection not under attack. Free buffer — any
            damaged tile is a valid top-off target. Prefer max heal_value.
        Tier 3: out-of-radius connection under attack, still savable
            (hp > 2 * turns_to_reach). Prefer lowest hp (most urgent).
        Tier 4: out-of-radius connection not under attack. Prefer nearest —
            everything in the network is critical, so walking to top off a
            distant tile is worth it when nothing closer is available.
        """
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        my_team = ct.get_team()

        # Pre-tier: sentinels and breaches (gunners are handled elsewhere).
        best_turret = None
        best_turret_d = float('inf')
        for id in mm.nearby_ally_turret_ids:
            if ct.get_entity_type(id) == EntityType.GUNNER:
                continue
            if ct.get_hp(id) >= ct.get_max_hp(id):
                continue
            tpos = ct.get_position(id)
            bbot_id = ct.get_tile_builder_bot_id(tpos)
            if bbot_id is not None and ct.get_team(bbot_id) == my_team:
                if DEBUG:
                    print(f"[HealConn] skipping turret at {tpos}: claimed by ally builder {bbot_id}")
                continue  # another ally builder already claims it
            d = _king_distance(my_pos, tpos)
            if DEBUG:
                print(f"[HealConn] damaged turret at {tpos}, hp={ct.get_hp(id)}/{ct.get_max_hp(id)}, dist={d}")
            if d < best_turret_d:
                best_turret_d = d
                best_turret = tpos
        if best_turret is not None:
            if DEBUG:
                print(f"[HealConn] pre-tier: picking turret at {best_turret}, dist={best_turret_d}")
            return best_turret

        # Connection tiles: roads, bridges, conveyors, splitters.
        connection_ids = (
            mm.nearby_ally_road_ids
            + mm.nearby_ally_bridge_ids
            + mm.nearby_ally_conveyor_ids
            + mm.nearby_ally_splitter_ids
        )

        # First pass: collect candidate info and count in-radius attacks so
        # the defer rule can tell single vs multi-target scenarios apart.
        candidates = []
        in_radius_attacked = 0
        for id in connection_ids:
            tpos = ct.get_position(id)
            hp = ct.get_hp(id)
            max_hp = ct.get_max_hp(id)
            if hp >= max_hp:
                continue
            bbot_id = ct.get_tile_builder_bot_id(tpos)
            if bbot_id is not None and ct.get_team(bbot_id) == my_team:
                if DEBUG:
                    print(f"[HealConn] skipping connection at {tpos}: claimed by ally builder {bbot_id}")
                continue  # another ally builder already claims it
            under_attack = bbot_id is not None and ct.get_team(bbot_id) != my_team
            heal_value = min(_HEAL_PER_ROUND, max_hp - hp)
            # turns_to_reach = king distance - 1 (we can heal from 1 step away),
            # clamped at 0 when already in the 3x3 heal footprint.
            king = _king_distance(my_pos, tpos)
            turns_to_reach = king - 1 if king > 1 else 0
            in_radius = (turns_to_reach == 0)
            candidates.append((tpos, hp, heal_value, under_attack, turns_to_reach, in_radius))
            if DEBUG:
                print(f"[HealConn] candidate at {tpos}: hp={hp}/{max_hp}, heal_val={heal_value}, attacked={under_attack}, dist={king}, in_radius={in_radius}")
            if in_radius and under_attack:
                in_radius_attacked += 1

        # Second pass: tier assignment. Include a monotonic index in the
        # sort key so Position objects are never compared directly.
        tier1 = []
        tier2 = []
        tier3 = []
        tier4 = []
        for i, (tpos, hp, heal_value, under_attack, turns_to_reach, in_radius) in enumerate(candidates):
            if in_radius:
                if under_attack:
                    # Defer iff we're the only in-radius tile under attack,
                    # the tile survives one more hit, and the current heal
                    # would waste hp. Otherwise commit to healing now so
                    # alternation between two attacked tiles works.
                    can_defer = (
                        in_radius_attacked == 1
                        and hp - _ENEMY_BUILDER_DPR >= 1
                        and heal_value < _HEAL_PER_ROUND
                    )
                    if can_defer:
                        if DEBUG:
                            print(f"[HealConn] deferring in-radius attacked tile at {tpos}: hp={hp}, heal_val={heal_value}, single attacker")
                    else:
                        # Sort by lowest hp first (urgency + alternation),
                        # tiebreak by higher heal_value.
                        tier1.append((hp, -heal_value, i, tpos))
                else:
                    # Sort by higher heal_value first.
                    tier2.append((-heal_value, i, tpos))
            else:
                if under_attack:
                    # Savable iff hp > 2 * turns_to_reach (we arrive before
                    # the tile dies). king distance gives exact moves.
                    if hp > _ENEMY_BUILDER_DPR * min(turns_to_reach - 1, 0):
                        # Sort by lowest hp first (most urgent), tiebreak nearest.
                        tier3.append((hp, turns_to_reach, i, tpos))
                    else:
                        if DEBUG:
                            print(f"[HealConn] lost cause at {tpos}: hp={hp}, turns_to_reach={turns_to_reach}, would die before arrival")
                else:
                    # Sort by nearest first, tiebreak by higher heal_value.
                    tier4.append((turns_to_reach, -heal_value, i, tpos))

        if DEBUG:
            print(f"[HealConn] tiers: t1={len(tier1)}, t2={len(tier2)}, t3={len(tier3)}, t4={len(tier4)}, in_radius_attacked={in_radius_attacked}")
        for tier_idx, tier in enumerate((tier1, tier2, tier3, tier4), 1):
            if tier:
                tier.sort()
                chosen = tier[0][-1]
                if DEBUG:
                    print(f"[HealConn] selected tier {tier_idx} target at {chosen}")
                return chosen
        if DEBUG:
            print("[HealConn] no heal target found")
        return None

    def execute(self, ct: Controller):
        if self.heal_pos is None:
            print("[HealConn] heal_pos is {heal_pos}")
            return

        mm: MapManager = self.brain.map_manager

        # Move toward the target if not already in heal range.
        dist = _king_distance(ct.get_position(), self.heal_pos)
        if dist > 1:
            if DEBUG:
                print(f"[HealConn] moving toward heal target {self.heal_pos}, dist={dist}")
            common_path(ct, mm, self.brain.pathing, self.heal_pos)

        # Heal the target if we can reach it this turn.
        print(f"[HealConn] Action cooldown is {ct.get_action_cooldown()}")
        print(f"[HealConn] Money is {ct.get_global_resources()[0]}")
        if ct.can_heal(self.heal_pos):
            if DEBUG:
                print(f"[HealConn] healing tile at {self.heal_pos}")
            ct.heal(self.heal_pos)
            self.heal_pos = None
            return
        else:
            if DEBUG:
                print(f"[HealConn] could not heal {self.heal_pos}")

        # Otherwise, if we're damaged and the heal cooldown is still
        # available (e.g. the target is out of range after moving), spend
        # it on ourselves rather than wasting the turn.
        my_pos = ct.get_position()
        if ct.get_hp() < GameConstants.BUILDER_BOT_MAX_HP and ct.can_heal(my_pos):
            if DEBUG:
                print(f"[HealConn] target out of range, self-healing at {my_pos} (hp={ct.get_hp()}/{GameConstants.BUILDER_BOT_MAX_HP})")
            ct.heal(my_pos)

    @cputimer
    def determine(self, ct, state_manager):
        heal_pos = self._pick_heal_target(ct)
        if heal_pos is None:
            return False
        self.heal_pos = heal_pos
        my_dist = _king_distance(ct.get_position(), heal_pos)
        for id in self.brain.map_manager.nearby_ally_bot_ids:
            other_dist = _king_distance(ct.get_position(id), heal_pos)
            if other_dist < my_dist:
                if DEBUG:
                    print(f"[HealConn] deferring to closer ally bot {id} (dist={other_dist} vs my {my_dist}) for {heal_pos}")
                return False
        if DEBUG:
            print(f"[HealConn] committed to HEAL_CONNECTION for {heal_pos}, dist={my_dist}")
        state_manager.current_state = BuilderState.HEAL_CONNECTION
        return True
