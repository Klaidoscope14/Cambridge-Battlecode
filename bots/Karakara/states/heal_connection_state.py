from cambc import Controller, EntityType, GameConstants
from debug.profiling import cputimer
from map.map_manager import MapManager
from nav.common import common_path
from states.builder_state import BuilderState

DEBUG = False


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

        Pre-tier: damaged sentinel/breach turrets.
        Main: all damaged connection tiles sorted by lowest HP first.
            Roads get a large penalty so they sort last.
            Per-candidate: skip tiles where a closer ally (or same-distance
            lower-ID ally) exists, so multiple bots naturally spread across
            different tiles instead of all picking the same one.
        """
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        my_team = ct.get_team()
        my_id = ct.get_id()

        # Pre-tier: sentinels and breaches (gunners are handled elsewhere).
        best_turret = None
        best_turret_d = float('inf')
        for rec in mm.nearby_ally_turret_ids:
            if rec.entity_type == EntityType.GUNNER:
                continue
            if rec.hp >= rec.max_hp:
                continue
            tpos = rec.position
            bbot_id = ct.get_tile_builder_bot_id(tpos)
            if bbot_id is not None and ct.get_team(bbot_id) == my_team:
                if DEBUG:
                    print(f"[HealConn] skipping turret at {tpos}: claimed by ally builder {bbot_id}")
                continue
            d = _king_distance(my_pos, tpos)
            if DEBUG:
                print(f"[HealConn] damaged turret at {tpos}, hp={rec.hp}/{rec.max_hp}, dist={d}")
            if d < best_turret_d:
                best_turret_d = d
                best_turret = tpos
        if best_turret is not None:
            if DEBUG:
                print(f"[HealConn] pre-tier: picking turret at {best_turret}, dist={best_turret_d}")
            return best_turret

        # Connection tiles: conveyors, bridges, splitters, harvesters, roads.
        connection_recs = (
            mm.nearby_ally_conveyor_ids
            + mm.nearby_ally_bridge_ids
            + mm.nearby_ally_splitter_ids
            + mm.nearby_ally_harvester_ids
            + mm.nearby_ally_road_ids
            + mm.nearby_ally_launcher_ids
            + mm.nearby_ally_barrier_ids
        )

        _ROAD_PENALTY = 1000

        # Collect candidate damaged tiles with per-tile filters applied.
        candidates = []
        for rec in connection_recs:
            tpos = rec.position
            hp = rec.hp
            max_hp = rec.max_hp

            is_road = rec.entity_type == EntityType.ROAD

            # Wait for full heal value unless the tile is a road.
            if not is_road and max_hp - hp < 4:
                continue
            if hp >= max_hp:
                continue

            # Skip tiles claimed by an ally builder standing on them.
            bbot_id = ct.get_tile_builder_bot_id(tpos)
            if bbot_id is not None and ct.get_team(bbot_id) == my_team:
                if DEBUG:
                    print(f"[HealConn] skipping {tpos}: claimed by ally builder {bbot_id}")
                continue

            sort_hp = hp + _ROAD_PENALTY if is_road else hp
            candidates.append((sort_hp, tpos, hp, max_hp, is_road))

        if not candidates:
            if DEBUG:
                print("[HealConn] no heal target found")
            return None

        # Priority order: lowest HP first (roads last via penalty), deterministic
        # tiebreak by tile coords so every bot computes the same order.
        candidates.sort(key=lambda c: (c[0], c[1].x, c[1].y))

        # Distance-based claim: walk candidates in priority order and take the
        # first one where no other reachable ally builder is strictly closer
        # (ties broken by lower id). No global assignment table — each bot just
        # asks "is this mine?" per tile and stops at the first yes. Avoids the
        # ID-ordered clumping where low-id bots eat all the top-priority tiles
        # and higher-id bots either pile in or get phantom-assigned to tiles
        # they can't actually reach.
        reachable = self.brain.reachable
        other_allies = [
            (bot.position, bot.id) for bot in mm.nearby_ally_bot_ids
            if bot.id != my_id and (bot.position.x, bot.position.y) in reachable
        ]

        for sort_hp, tpos, hp, max_hp, is_road in candidates:
            my_d = _king_distance(my_pos, tpos)
            beaten = False
            for apos, aid in other_allies:
                d = _king_distance(apos, tpos)
                if d < my_d or (d == my_d and aid < my_id):
                    beaten = True
                    break
            if beaten:
                continue
            if DEBUG:
                print(f"[HealConn] claim {tpos} (hp={hp}/{max_hp}, road={is_road}) dist={my_d}")
            return tpos

        if DEBUG:
            print("[HealConn] no tile claimed by me")
        return None

    def execute(self, ct: Controller):
        if self.heal_pos is None:
            return

        mm: MapManager = self.brain.map_manager

        # Move toward the target if not already in heal range.
        dist = _king_distance(ct.get_position(), self.heal_pos)
        if dist > 1:
            if DEBUG:
                print(f"[HealConn] money={ct.get_global_resources()[0]} moving toward heal target {self.heal_pos}, dist={dist}")
            common_path(ct, mm, self.brain.pathing, self.heal_pos)

        # Heal the target if we can reach it this turn.
        if ct.can_heal(self.heal_pos):
            if DEBUG:
                print(f"[HealConn] money={ct.get_global_resources()[0]} healing tile at {self.heal_pos}")
            ct.heal(self.heal_pos)
            self.heal_pos = None
            return
        else:
            if DEBUG:
                print(f"[HealConn] money={ct.get_global_resources()[0]} could not heal {self.heal_pos}")

        # Otherwise, if we're damaged and the heal cooldown is still
        # available (e.g. the target is out of range after moving), spend
        # it on ourselves rather than wasting the turn.
        my_pos = ct.get_position()
        if ct.get_hp() < GameConstants.BUILDER_BOT_MAX_HP and ct.can_heal(my_pos):
            if DEBUG:
                print(f"[HealConn] money={ct.get_global_resources()[0]} target out of range, self-healing at {my_pos} (hp={ct.get_hp()}/{GameConstants.BUILDER_BOT_MAX_HP})")
            ct.heal(my_pos)

    @cputimer
    def determine(self, ct, state_manager):
        heal_pos = self._pick_heal_target(ct)
        if heal_pos is None:
            return False
        self.heal_pos = heal_pos
        if DEBUG:
            print(f"[HealConn] committed to HEAL_CONNECTION for {heal_pos}")
        state_manager.current_state = BuilderState.HEAL_CONNECTION
        return True
