from cambc import EntityType, Environment, Position

from debug.profiling import cputimer
from helpers.directions import CARDINAL, DIRECTIONS
from helpers.geometry import chebyshev_distance, on_map
from map.map_manager import MapManager
from nav.common import common_path
from states.builder_state import BuilderState


DEBUG = False

SABOTAGE_COOLDOWN = 60
SABOTAGE_RETRY_TURNS = 2000

OVERRIDE_MIN_ENEMY_KING_DIST = 2
LOW_HP_OVERRIDE = 8

# Priority 1: anything worth tearing down adjacent to an undefended titanium
# harvester or foundry (ally or enemy).
ADJACENT_ANCHOR_SABOTAGE_TYPES = (
    EntityType.ROAD,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
)

# Priority 2: generic enemy logistics
GENERAL_SABOTAGE_TYPES = (
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
)


def _is_safe_to_sabotage(brain, pos: Position) -> bool:
    mm = brain.map_manager
    if pos in mm.gunner_danger_positions or pos in mm.ally_gunner_danger_positions:
        return False
    return True


def _fire_on(ct, pos: Position) -> bool:
    if ct.can_fire(pos):
        ct.fire(pos)
        return True
    return False


def _in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) == 0


def _weakness_count(mm: MapManager, my_team, pos: Position) -> float:
    """Cardinal neighbors that are empty or ally-building.
    Ally launcher counts 1.5 because it actively burns the tile down.
    A lone wall contributes 0, but a full 3-tile wall line on a cardinal
    side contributes 1.5 (it caps off that whole approach).
    Off-map neighbors are ignored."""
    WALL = Environment.WALL
    w = 0.0
    for d in CARDINAL:
        n = pos.add(d)
        if not on_map(n, mm.width, mm.height):
            continue

        # If the cardinal neighbor is a wall, it only contributes when the
        # full 3-tile perpendicular line is also wall (caps off the approach).
        if mm.get_tile(n) == WALL:
            px, py = n.y - pos.y, n.x - pos.x
            full_line = True
            for k in (-1, 1):
                t = Position(n.x + px * k, n.y + py * k)
                if not on_map(t, mm.width, mm.height) or mm.get_tile(t) != WALL:
                    full_line = False
                    break
            if full_line:
                w += 1.5
            continue

        nb = mm.get_building(n)
        if nb is None:
            w += 1
        elif nb.team == my_team:
            w += 1.5 if nb.entity_type == EntityType.LAUNCHER else 1
    return w


def _pos_has_ally_gunner(mm: MapManager, my_team, hpos: Position) -> bool:
    for d in CARDINAL:
        adj = hpos.add(d)
        if not on_map(adj, mm.width, mm.height):
            continue
        b = mm.get_building(adj)
        if b is not None and b.team == my_team and b.entity_type == EntityType.GUNNER:
            return True
    return False


class SabotageState:
    """Unified sabotage state.

    Target priority:
      1. Lowest-HP enemy tile cardinally adjacent to an undefended
         titanium harvester or foundry (ally or enemy anchor).
      2. Lowest-HP enemy conveyor / bridge / splitter anywhere in vision,
         biased away from other ally builder bots so we spread out.

    Determine gates:
      * no enemy bot in any of the 8 tiles adjacent to us

    Fire gates (applied at firing time only, not while pathing):
      * no enemy builder is king-adjacent to us
    """

    def __init__(self, ct, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self.cooldowns: dict[tuple[int, int], int] = {}
        self._attempts: int = 0
        self._fire_unconditional: bool = False

    # ── cooldowns ─────────────────────────────────────────────────
    def _expire_cooldowns(self, current_round: int) -> None:
        expired = [
            k for k, r in self.cooldowns.items() if current_round - r > SABOTAGE_COOLDOWN
        ]
        for k in expired:
            del self.cooldowns[k]

    def _cooldown_target(self, pos: Position, current_round: int) -> None:
        self.cooldowns[(pos.x, pos.y)] = current_round

    # ── validation ────────────────────────────────────────────────
    def _valid_enemy_building(
        self, ct, mm: MapManager, pos: Position, allowed_types
    ) -> bool:
        if (pos.x, pos.y) in self.cooldowns:
            return False
        if not _is_safe_to_sabotage(self.brain, pos):
            return False

        building = mm.get_building(pos)
        if building is None:
            return False
        if building.team == ct.get_team():
            return False
        if building.entity_type not in allowed_types:
            return False

        bot = mm.get_bot(pos)
        if bot is not None and bot.id != ct.get_id():
            return False

        return True

    def _adjacent_undefended_titanium_harvester(
        self, ct, mm: MapManager, pos: Position
    ) -> bool:
        """Any team — we sabotage enemy logistics next to *any* titanium harvester."""
        my_team = ct.get_team()
        for d in CARDINAL:
            n = pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            b = mm.get_building(n)
            if (
                b is not None
                and b.entity_type == EntityType.HARVESTER
                and mm.get_tile(n) == Environment.ORE_TITANIUM
                and not _pos_has_ally_gunner(mm, my_team, n)
            ):
                return True
        return False

    def _adjacent_undefended_foundry(self, ct, mm: MapManager, pos: Position) -> bool:
        """Any team — sabotage enemy logistics next to *any* foundry."""
        my_team = ct.get_team()
        for d in CARDINAL:
            n = pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            b = mm.get_building(n)
            if (
                b is not None
                and b.entity_type == EntityType.FOUNDRY
                and not _pos_has_ally_gunner(mm, my_team, n)
            ):
                return True
        return False

    def _is_road_receiving(self, mm: MapManager, pos: Position) -> bool:
        """True if `pos` is the output tile of any visible enemy conveyor or bridge."""
        for rec in mm.nearby_enemy_conveyor_ids:
            if rec.direction is None:
                continue
            if rec.position.add(rec.direction) == pos:
                return True
        for rec in mm.nearby_enemy_bridge_ids:
            if rec.output_target is None:
                continue
            if rec.output_target == pos:
                return True
        return False

    def _is_valid_target(self, ct, mm: MapManager, pos: Position) -> bool:
        """Accept a position if it still matches any priority tier."""
        if self._valid_enemy_building(
            ct, mm, pos, ADJACENT_ANCHOR_SABOTAGE_TYPES
        ) and (
            self._adjacent_undefended_titanium_harvester(ct, mm, pos)
            or self._adjacent_undefended_foundry(ct, mm, pos)
        ):
            return True

        # Road-receiving: enemy ROAD being fed by an enemy conveyor/bridge.
        if self._valid_enemy_building(
            ct, mm, pos, (EntityType.ROAD,)
        ) and self._is_road_receiving(mm, pos):
            return True

        if self._valid_enemy_building(ct, mm, pos, GENERAL_SABOTAGE_TYPES):
            building = mm.get_building(pos)
            if not self.brain.storage_tracker.confirmed_empty(building.id):
                return True

        return False

    # ── target search ────────────────────────────────────────────
    def _search_anchor_adjacent(
        self,
        ct,
        mm: MapManager,
        my_pos: Position,
        card_pos_iter,
        allowed_types,
        anchor_predicate,
    ) -> Position | None:
        """Iterate (anchor_pos, adj_pos) pairs and pick the lowest-HP valid adj tile.

        Key: (is_empty, hp, distance²) — non-empty storage first, then low HP,
        then closest.
        """
        my_team = ct.get_team()
        best_pos: Position | None = None
        best_key: tuple | None = None
        anchor_ok: dict[Position, bool] = {}

        for apos, p in card_pos_iter:
            ok = anchor_ok.get(apos)
            if ok is None:
                ok = anchor_predicate(apos) and not _pos_has_ally_gunner(mm, my_team, apos)
                anchor_ok[apos] = ok
            if not ok:
                continue
            if not self._valid_enemy_building(ct, mm, p, allowed_types):
                continue
            b = mm.get_building(p)
            is_empty = self.brain.storage_tracker.confirmed_empty(b.id)
            key = (is_empty, b.hp, my_pos.distance_squared(p))
            if best_key is None or key < best_key:
                best_key = key
                best_pos = p

        return best_pos

    def _find_priority_1(self, ct, mm: MapManager, my_pos: Position) -> Position | None:
        """Sabotage adjacent to undefended titanium harvesters + foundries (any team)."""
        ORE_TI = Environment.ORE_TITANIUM

        harv_best = self._search_anchor_adjacent(
            ct,
            mm,
            my_pos,
            (*mm.nearby_harvester_enemy_card_pos, *mm.nearby_harvester_card_pos),
            ADJACENT_ANCHOR_SABOTAGE_TYPES,
            lambda apos: mm.get_tile(apos) is ORE_TI,
        )
        foundry_best = self._search_anchor_adjacent(
            ct,
            mm,
            my_pos,
            (*mm.nearby_foundry_enemy_card_pos, *mm.nearby_foundry_card_pos),
            ADJACENT_ANCHOR_SABOTAGE_TYPES,
            lambda apos: True,
        )

        if harv_best is None:
            return foundry_best
        if foundry_best is None:
            return harv_best
        # Pick the one with lower (is_empty, hp, dist²) among the two.
        hb = mm.get_building(harv_best)
        fb = mm.get_building(foundry_best)
        hk = (
            self.brain.storage_tracker.confirmed_empty(hb.id),
            hb.hp,
            my_pos.distance_squared(harv_best),
        )
        fk = (
            self.brain.storage_tracker.confirmed_empty(fb.id),
            fb.hp,
            my_pos.distance_squared(foundry_best),
        )
        return harv_best if hk <= fk else foundry_best

    def _find_priority_2(self, ct, mm: MapManager, my_pos: Position) -> Position | None:
        my_id = ct.get_id()

        ally_bot_positions = [
            rec.position for rec in mm.nearby_ally_bot_ids if rec.id != my_id
        ]

        candidates: list[Position] = []
        # Regular-only — builder bots cannot fire on enemy ARMOURED_CONVEYOR,
        # so filter inline by entity_type.
        for rec in mm.nearby_enemy_conveyor_ids:
            if rec.entity_type != EntityType.CONVEYOR:
                continue
            candidates.append(rec.position)
        for rec in mm.nearby_enemy_bridge_ids:
            candidates.append(rec.position)

        best_pos: Position | None = None
        best_key: tuple | None = None
        seen: set[tuple[int, int]] = set()

        for p in candidates:
            k = (p.x, p.y)
            if k in seen:
                continue
            seen.add(k)

            if not self._valid_enemy_building(ct, mm, p, GENERAL_SABOTAGE_TYPES):
                continue
            b = mm.get_building(p)
            if self.brain.storage_tracker.confirmed_empty(b.id):
                continue

            my_team = ct.get_team()
            weaknesses = _weakness_count(mm, my_team, p)

            nearest_ally_sq = None
            for ap in ally_bot_positions:
                d = p.distance_squared(ap)
                if nearest_ally_sq is None or d < nearest_ally_sq:
                    nearest_ally_sq = d
            if nearest_ally_sq is None:
                nearest_ally_sq = 10_000_000

            # more weaknesses first, then lower hp, then farther from allies, then closer to us
            key = (-weaknesses, b.hp, -nearest_ally_sq, my_pos.distance_squared(p))
            if best_key is None or key < best_key:
                best_key = key
                best_pos = p

        return best_pos

    def _find_best_target(
        self, ct, mm: MapManager, my_pos: Position
    ) -> Position | None:
        return (
            self._find_priority_1(ct, mm, my_pos)
            or self._find_priority_2(ct, mm, my_pos)
        )

    def _find_road_near_anchor(
        self, ct, mm: MapManager, my_pos: Position
    ) -> Position | None:
        """Lowest-HP enemy ROAD cardinally adjacent to an undefended
        titanium harvester or foundry (any team)."""
        ORE_TI = Environment.ORE_TITANIUM

        harv_best = self._search_anchor_adjacent_road(
            ct,
            mm,
            my_pos,
            (*mm.nearby_harvester_enemy_card_pos, *mm.nearby_harvester_card_pos),
            lambda apos: mm.get_tile(apos) is ORE_TI,
        )
        foundry_best = self._search_anchor_adjacent_road(
            ct,
            mm,
            my_pos,
            (*mm.nearby_foundry_enemy_card_pos, *mm.nearby_foundry_card_pos),
            lambda apos: True,
        )

        if harv_best is None:
            return foundry_best
        if foundry_best is None:
            return harv_best
        hb = mm.get_building(harv_best)
        fb = mm.get_building(foundry_best)
        hk = (hb.hp, my_pos.distance_squared(harv_best))
        fk = (fb.hp, my_pos.distance_squared(foundry_best))
        return harv_best if hk <= fk else foundry_best

    def _search_anchor_adjacent_road(
        self,
        ct,
        mm: MapManager,
        my_pos: Position,
        card_pos_iter,
        anchor_predicate,
    ) -> Position | None:
        my_team = ct.get_team()
        best_pos: Position | None = None
        best_key: tuple | None = None
        anchor_ok: dict[Position, bool] = {}

        for apos, p in card_pos_iter:
            ok = anchor_ok.get(apos)
            if ok is None:
                ok = anchor_predicate(apos) and not _pos_has_ally_gunner(mm, my_team, apos)
                anchor_ok[apos] = ok
            if not ok:
                continue
            if not self._valid_enemy_building(ct, mm, p, (EntityType.ROAD,)):
                continue
            b = mm.get_building(p)
            key = (b.hp, my_pos.distance_squared(p))
            if best_key is None or key < best_key:
                best_key = key
                best_pos = p

        return best_pos

    def _find_road_receiving(
        self, ct, mm: MapManager, my_pos: Position
    ) -> Position | None:
        """Lowest-HP enemy ROAD fed by an enemy conveyor, or enemy BRIDGE
        fed by an enemy bridge."""
        best_pos: Position | None = None
        best_key: tuple | None = None

        for rec in mm.nearby_enemy_conveyor_ids:
            d = rec.direction
            if d is None:
                continue
            p = rec.position.add(d)
            if not on_map(p, mm.width, mm.height):
                continue
            if not self._valid_enemy_building(ct, mm, p, (EntityType.ROAD,)):
                continue
            b = mm.get_building(p)
            key = (b.hp, my_pos.distance_squared(p))
            if best_key is None or key < best_key:
                best_key = key
                best_pos = p

        for rec in mm.nearby_enemy_bridge_ids:
            p = rec.output_target
            if p is None:
                continue
            if not on_map(p, mm.width, mm.height):
                continue
            if not self._valid_enemy_building(ct, mm, p, (EntityType.ROAD,)):
                continue
            b = mm.get_building(p)
            key = (b.hp, my_pos.distance_squared(p))
            if best_key is None or key < best_key:
                best_key = key
                best_pos = p

        return best_pos

    def _nearest_enemy_builder_king_distance(self, ct, mm: MapManager) -> float:
        my_pos = ct.get_position()
        best: float = float("inf")
        for rec in mm.nearby_enemy_builder_bot_ids:
            d = chebyshev_distance(my_pos, rec.position)
            if d < best:
                best = d
        return best

    # ── determine ────────────────────────────────────────────────
    @cputimer
    def determine(self, ct, state_manager):
        mm = self.brain.map_manager
        current_round = ct.get_current_round()

        self._expire_cooldowns(current_round)
        self._fire_unconditional = False
        my_pos = ct.get_position()

        if DEBUG:
            print(f"[SABOTAGE.determine] bot={ct.get_id()} pos=({my_pos.x},{my_pos.y}) round={current_round}")

        if (
            state_manager.previous_state == BuilderState.SABOTAGE
            and self.target is not None
            and self._is_valid_target(ct, mm, self.target)
        ):
            target_b = mm.get_building(self.target)
            enemy_builder_adj = self._nearest_enemy_builder_king_distance(ct, mm) <= 1

            if not enemy_builder_adj:
                if DEBUG:
                    print(f"[SABOTAGE.determine] STICKY (no enemy builder adjacent) target=({self.target.x},{self.target.y})")
                state_manager.current_state = BuilderState.SABOTAGE
                return True

            # Enemy builder is adjacent — only commit if the tile is worth it:
            # a road (cheap, always worth finishing) or a high-weakness target
            # (>= 2 means ≥2 sides exposed / supported by allies).
            is_road = target_b is not None and target_b.entity_type == EntityType.ROAD
            weakness = _weakness_count(mm, ct.get_team(), self.target)
            if is_road or weakness >= 2:
                if DEBUG:
                    reason = "road" if is_road else f"weakness={weakness}"
                    print(f"[SABOTAGE.determine] STICKY (enemy adj, {reason}) target=({self.target.x},{self.target.y})")
                state_manager.current_state = BuilderState.SABOTAGE
                return True

            if DEBUG:
                print(f"[SABOTAGE.determine] DROP (enemy adj, weakness={weakness}, not road) target=({self.target.x},{self.target.y})")
            self.target = None

        # Road override — always worth busting a cheap road next to a
        # titanium harvester or foundry (any team) when undefended.
        road_target = self._find_road_near_anchor(ct, mm, my_pos)
        if road_target is not None:
            if DEBUG:
                print(f"[SABOTAGE.determine] ROAD-NEAR-ANCHOR override -> ({road_target.x},{road_target.y})")
            self.target = road_target
            self._fire_unconditional = True
            state_manager.current_state = BuilderState.SABOTAGE
            return True

        # Road-receiving override — break the road/bridge being fed by an
        # enemy conveyor or bridge.
        road_target = self._find_road_receiving(ct, mm, my_pos)
        if road_target is not None:
            if DEBUG:
                print(f"[SABOTAGE.determine] ROAD-RECEIVING override -> ({road_target.x},{road_target.y})")
            self.target = road_target
            self._fire_unconditional = True
            state_manager.current_state = BuilderState.SABOTAGE
            return True

        # Standing-on-target override — if we're already on a valid sabotage
        # tile and no enemy builder is king-adjacent, fire for free. The
        # moment an enemy builder steps adjacent we fall through to the
        # normal search and may abandon for a higher-priority target.
        if self._is_valid_target(ct, mm, my_pos):
            if self._nearest_enemy_builder_king_distance(ct, mm) > 1:
                if DEBUG:
                    print(f"[SABOTAGE.determine] STANDING-ON override at ({my_pos.x},{my_pos.y})")
                self.target = my_pos
                state_manager.current_state = BuilderState.SABOTAGE
                return True

        enemy_n = len(mm.nearby_enemy_builder_bot_ids)
        nearest_king = self._nearest_enemy_builder_king_distance(ct, mm) if enemy_n > 0 else float("inf")
        no_enemy_builders_near = (
            enemy_n == 0
            or nearest_king > OVERRIDE_MIN_ENEMY_KING_DIST
        )
        if DEBUG:
            print(f"[SABOTAGE.determine] enemy_builders_nearby={enemy_n} nearest_king_dist={nearest_king} no_enemy_builders_near={no_enemy_builders_near}")

        best_target = self._find_best_target(ct, mm, my_pos)
        if DEBUG:
            if best_target is None:
                print(f"[SABOTAGE.determine] best_target=None")
            else:
                bb = mm.get_building(best_target)
                hp = bb.hp if bb is not None else "?"
                etype = bb.entity_type if bb is not None else "?"
                print(f"[SABOTAGE.determine] best_target=({best_target.x},{best_target.y}) hp={hp} type={etype}")

        # Low-HP override — a tile at or below LOW_HP_OVERRIDE is cheap enough
        # to finish that we skip the enemy-proximity gate.
        if best_target is not None:
            b = mm.get_building(best_target)
            if b is not None and b.hp <= LOW_HP_OVERRIDE:
                if DEBUG:
                    print(f"[SABOTAGE.determine] LOW-HP override (hp={b.hp} <= {LOW_HP_OVERRIDE})")
                self._fire_unconditional = True
                state_manager.current_state = BuilderState.SABOTAGE
                return True

        # No enemies around — follow the priority list.
        if no_enemy_builders_near:
            if best_target is not None:
                if DEBUG:
                    print(f"[SABOTAGE.determine] NO-ENEMY path -> sabotage")
                state_manager.current_state = BuilderState.SABOTAGE
                return True
            if DEBUG:
                print(f"[SABOTAGE.determine] NO-ENEMY but no target, returning False")
            return False

        my_team = ct.get_team()
        for d in DIRECTIONS:
            adj = my_pos.add(d)
            if not on_map(adj, mm.width, mm.height):
                continue
            bot = mm.get_bot(adj)
            if bot is not None and bot.team != my_team:
                if DEBUG:
                    print(f"[SABOTAGE.determine] adjacency gate FAILED: enemy bot at ({adj.x},{adj.y})")
                return False

        if self._find_best_target(ct, mm, my_pos) is not None:
            if DEBUG:
                print(f"[SABOTAGE.determine] all gates passed -> sabotage")
            state_manager.current_state = BuilderState.SABOTAGE
            return True

        if DEBUG:
            print(f"[SABOTAGE.determine] no target after all gates -> False")
        return False

    # ── execute ──────────────────────────────────────────────────
    def execute(self, ct) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        current_round = ct.get_current_round()

        self._expire_cooldowns(current_round)

        if DEBUG:
            tstr = f"({self.target.x},{self.target.y})" if self.target else "None"
            print(f"[SABOTAGE.execute] bot={ct.get_id()} pos=({my_pos.x},{my_pos.y}) target={tstr}")

        if self.target is not None and not self._is_valid_target(ct, mm, self.target):
            if DEBUG:
                print(f"[SABOTAGE.execute] target ({self.target.x},{self.target.y}) no longer valid, dropping")
            self.target = None

        if self.target is None:
            self.target = self._find_best_target(ct, mm, my_pos)
            self._attempts = 0
            if DEBUG:
                tstr = f"({self.target.x},{self.target.y})" if self.target else "None"
                print(f"[SABOTAGE.execute] re-acquired target={tstr}")

        if self.target is None:
            if DEBUG:
                print(f"[SABOTAGE.execute] no target -> False")
            return False

        if _in_action_range(my_pos, self.target):
            if DEBUG:
                print(f"[SABOTAGE.execute] in action range, firing")
            return self._try_destroy(ct, mm, current_round)

        if DEBUG:
            print(f"[SABOTAGE.execute] pathing toward ({self.target.x},{self.target.y})")
        common_path(ct, mm, self.brain.pathing, self.target)
        my_pos = ct.get_position()
        if _in_action_range(my_pos, self.target):
            if DEBUG:
                print(f"[SABOTAGE.execute] arrived in range after path, firing")
            return self._try_destroy(ct, mm, current_round)
        if DEBUG:
            print(f"[SABOTAGE.execute] not in range after pathing, pos=({my_pos.x},{my_pos.y})")
        return False

    def _try_destroy(self, ct, mm: MapManager, current_round: int) -> bool:
        building = mm.get_building(self.target)
        if building is None:
            if DEBUG:
                print(f"[SABOTAGE._try_destroy] building gone at ({self.target.x},{self.target.y}), cooldown")
            self._cooldown_target(self.target, current_round)
            self.target = None
            self._attempts = 0
            return False

        # Only gate: don't fire if an enemy builder is king-adjacent.
        # Overrides (road-near-anchor, road-receiving, low-hp) bypass this.
        if not self._fire_unconditional and self._nearest_enemy_builder_king_distance(ct, mm) <= 1:
            if DEBUG:
                print(f"[SABOTAGE._try_destroy] enemy builder adjacent, holding fire at ({self.target.x},{self.target.y})")
            return False

        if DEBUG:
            print(f"[SABOTAGE._try_destroy] firing at ({self.target.x},{self.target.y}) hp={building.hp} type={building.entity_type}")
        if _fire_on(ct, self.target):
            if DEBUG:
                print(f"[SABOTAGE._try_destroy] FIRED successfully")
            self.target = None
            self._attempts = 0
            return True

        self._attempts += 1
        if DEBUG:
            print(f"[SABOTAGE._try_destroy] can_fire=False, attempts={self._attempts}")
        if self._attempts >= SABOTAGE_RETRY_TURNS:
            if DEBUG:
                print(f"[SABOTAGE._try_destroy] retries exhausted, cooldown target")
            self._cooldown_target(self.target, current_round)
            self.target = None
            self._attempts = 0
        return False

    # ── interface ────────────────────────────────────────────────
    def has_target(self) -> bool:
        return self.target is not None

    def reset(self, ct=None) -> None:
        self.target = None
        self._attempts = 0
