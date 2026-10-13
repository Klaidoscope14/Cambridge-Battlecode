from cambc import EntityType, Environment, GameConstants, Position

from roles.builder.helpers import in_bounds
from comms.markers import place_harvester_claim, is_harvester_claimed_vm
from helpers.constants import HARVESTER_CLAIM_STALENESS
from map.map_manager import MapManager
from nav.common import common_path
from helpers.directions import DIRECTIONS

BUILD_COOLDOWN = 40
TOO_MANY_ENEMY_TILES = 100 # Don't use this anymore?
ACTION_RADIUS_SQ = 2

ORE_TYPES = {
    Environment.ORE_TITANIUM,
    Environment.ORE_AXIONITE,
}


class BuildHarvesterState:
    def __init__(self, ct, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self.cooldowns: dict[Position, int] = {}
        self.allow_titanium: bool = True
        self.allow_axionite: bool = False

    # ── Ore filtering ───────────────────────────────────────────────

    def _is_allowed_ore(self, env) -> bool:
        if env == Environment.ORE_TITANIUM:
            return self.allow_titanium
        if env == Environment.ORE_AXIONITE:
            return self.allow_axionite
        return False

    # ── Marker helpers ──────────────────────────────────────────────

    def _try_place_marker(self, ct) -> None:
        """Place a claim marker adjacent to the target ore every tick.

        Markers can get destroyed by other bots or expiry at any time,
        so we re-place unconditionally to keep the claim fresh.
        """
        if self.target is None:
            return
        if self.target.distance_squared(ct.get_position()) <= 2:
            place_harvester_claim(ct, self.target)

    # ── Validation / search ─────────────────────────────────────────

    def _is_valid_ore(self, ct, mm: MapManager, pos: Position, current_round: int, enemy_count: int = 0) -> bool:
        if pos in self.cooldowns:
            return False
        if enemy_count > TOO_MANY_ENEMY_TILES:
            return False
        tile = mm.get_tile(pos)
        if tile is None or not self._is_allowed_ore(tile):
            return False
        building = mm.get_building(pos)
        if building is not None and (
            building.entity_type == EntityType.HARVESTER
            or (
                building.team != ct.get_team()
                and building.entity_type != EntityType.MARKER
            )
        ):
            return False
        if is_harvester_claimed_vm(self.brain.vision_manager, pos, current_round, HARVESTER_CLAIM_STALENESS):
            return False
        return True

    def _find_best_ore(
        self, ct, mm: MapManager, my_pos: Position, current_round: int, enemy_count: int = 0
    ) -> Position | None:
        best_pos: Position | None = None
        best_dist = float("inf")

        for pos in mm.nearby_positions:
            if not self._is_valid_ore(ct, mm, pos, current_round, enemy_count):
                continue
            d = my_pos.distance_squared(pos)
            if d < best_dist:
                best_dist = d
                best_pos = pos

        return best_pos

    def _count_nearby_enemies(self, ct, mm: MapManager) -> int:
        count = 0
        team = ct.get_team()
        for pos in mm.nearby_positions:
            building = mm.get_building(pos)
            if building is not None and building.team != team:
                count += 1
        return count

    # ── Core tick ───────────────────────────────────────────────────

    def execute(self, ct) -> bool:
        print(f"Target is {self.target}")

        mm = self.brain.map_manager
        my_pos = ct.get_position()
        current_round = ct.get_current_round()

        # Expire old cooldowns
        expired = [p for p, r in self.cooldowns.items() if current_round - r > BUILD_COOLDOWN]
        for p in expired:
            del self.cooldowns[p]

        # Cooldown any ore that another bot has already claimed
        for pos in mm.nearby_positions:
            if pos in self.cooldowns:
                continue
            tile = mm.get_tile(pos)
            if tile is None or not self._is_allowed_ore(tile):
                continue
            if is_harvester_claimed_vm(self.brain.vision_manager, pos, current_round, HARVESTER_CLAIM_STALENESS):
                self.cooldowns[pos] = current_round
                # If we were chasing this exact target, drop it
                if self.target is not None and self.target.x == pos.x and self.target.y == pos.y:
                    self.target = None

        enemy_count = self._count_nearby_enemies(ct, mm)

        # Validate current target (skip enemy-count rejection if already in action range)
        if self.target is not None:
            ec = 0 if in_action_range(my_pos, self.target) else enemy_count
            if not self._is_valid_ore(ct, mm, self.target, current_round, ec):
                self.target = None

        # Pick new target only when needed
        if self.target is None:
            self.target = self._find_best_ore(ct, mm, my_pos, current_round, enemy_count)

        # Enemy territory — cooldown all visible ore so we don't keep coming back
        if self.target is None and enemy_count > TOO_MANY_ENEMY_TILES:
            for pos in mm.nearby_positions:
                tile = mm.get_tile(pos)
                if tile is not None and self._is_allowed_ore(tile):
                    self.cooldowns[pos] = current_round

        # Opportunistic switch: if we're walking to a distant target but
        # happen to be in action range of a different valid ore, grab it instead.
        if self.target is not None and not in_action_range(my_pos, self.target):
            for d in DIRECTIONS:
                pos = my_pos.add(d)
                if not in_bounds(ct, pos):
                    continue
                if pos == self.target:
                    continue
                if not self._is_valid_ore(ct, mm, pos, current_round, enemy_count):
                    continue
                self.target = pos
                break

        # Keep retrying marker placement every tick until one sticks
        self._try_place_marker(ct)

        if self.target is None:
            return False

        if in_action_range(my_pos, self.target):
            return self._try_build(ct, mm, current_round, enemy_count)
        else:
            common_path(ct, mm, self.brain.pathing, self.target)
            return False

    def _try_build(self, ct, mm: MapManager, current_round: int, enemy_count: int) -> bool:
        if in_theory_can_build_harvester(ct, self.target):
            if ct.can_destroy(self.target):
                ct.destroy(self.target)

        if ct.can_build_harvester(self.target):
            ct.build_harvester(self.target)
            self.target = None
            return True

        # Can't build — dangerous area: cooldown and leave
        if enemy_count > TOO_MANY_ENEMY_TILES:
            self.cooldowns[self.target] = current_round
            self.target = None
            return False

        return False

    # ── Interface for StateManager ──────────────────────────────────

    def has_target(self) -> bool:
        return self.target is not None

    def reset(self, ct=None) -> None:
        self.target = None


# ── Module-level helpers ────────────────────────────────────────────


def ore_is_available(pos: Position, map_manager: MapManager) -> bool:
    tile = map_manager.get_tile(pos)
    if tile is None or tile not in ORE_TYPES:
        return False
    return map_manager.get_building(pos) is None


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) <= ACTION_RADIUS_SQ


def in_theory_can_build_harvester(ct, pos: Position):
    if not in_action_range(ct.get_position(), pos):
        return False
    if ct.get_global_resources()[0] < ct.get_harvester_cost()[0]:
        return False
    return ct.get_action_cooldown() == 0