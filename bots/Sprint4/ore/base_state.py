"""ore_base.py – Shared logic for ore-targeting states.

Both RouteCoreOreState and BuildHarvesterState need to:
  • filter ore by type, cooldown, buildings, and claims
  • find the closest valid ore to ally core
  • count nearby enemy buildings
  • manage per-position cooldowns
  • check action range

Ore reservation is signalled by an ally bot sitting on the ore tile.
Other bots see the occupied tile and skip it automatically — no
markers required.

This base class provides all of that so the subclasses only contain
their unique behaviour (routing vs. build).
"""

from cambc import Controller, EntityType, Environment, Position

from helpers.directions import CARDINAL
from helpers.geometry import on_map
from map.map_manager import MapManager

# ── Shared constants ────────────────────────────────────────────────

ACTION_RADIUS_SQ = 2

ORE_TYPES = {
    Environment.ORE_TITANIUM,
    Environment.ORE_AXIONITE,
}

TOO_MANY_ENEMY_TILES = 100

TURRET_TYPES = {
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
}


# ── Pure helpers (module-level) ─────────────────────────────────────


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) <= ACTION_RADIUS_SQ


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def ore_is_available(pos: Position, map_manager: MapManager) -> bool:
    tile = map_manager.get_tile(pos)
    if tile is None or tile not in ORE_TYPES:
        return False
    return map_manager.get_building(pos) is None


def is_on_position(a: Position, b: Position) -> bool:
    return a.x == b.x and a.y == b.y


# ── Base class ──────────────────────────────────────────────────────


class OreStateBase:
    """Common infrastructure shared by RouteCoreOreState and BuildHarvesterState."""

    # Subclasses can override these to change filtering behaviour.
    allowed_ore: set = {Environment.ORE_TITANIUM}
    cooldown_duration: int = 40          # rounds before a position is retried
    route_timeout: int = 0               # rounds before giving up on a target (0 = disabled)
    max_enemy_tiles: int = TOO_MANY_ENEMY_TILES
    enforce_ally_side: bool = False
    reject_cardinal_turrets: bool = False

    def __init__(self, ct: Controller, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self._target_set_round: int = -1
        self.cooldowns: dict[Position, int] = {}

    # ── Ore filtering ───────────────────────────────────────────────

    def _is_allowed_ore(self, env: Environment) -> bool:
        return env in self.allowed_ore

    def _is_valid_ore(
        self,
        ct: Controller,
        mm: MapManager,
        pos: Position,
        current_round: int,
        enemy_count: int = 0,
        my_pos: Position | None = None,
    ) -> bool:
        if pos in self.cooldowns:
            return False
        if enemy_count > self.max_enemy_tiles:
            return False

        tile = mm.get_tile(pos)
        if tile is None or not self._is_allowed_ore(tile):
            return False

        building = mm.get_building(pos)
        if building is not None:
            if building.entity_type == EntityType.HARVESTER:
                return False
            if building.team != ct.get_team() and building.entity_type != EntityType.MARKER:
                return False

        # Optional: reject ore with enemy turrets on cardinal neighbours
        if self.reject_cardinal_turrets:
            team = ct.get_team()
            for d in CARDINAL:
                adj = pos.add(d)
                if not on_map(adj, mm.width, mm.height):
                    continue
                adj_building = mm.get_building(adj)
                if (
                    adj_building is not None
                    and adj_building.team != team
                    and adj_building.entity_type in TURRET_TYPES
                ):
                    return False

        # Another bot sitting on this ore means it is reserved.
        # Skip the check when *we* are the bot on the tile.
        bot_on_ore = mm.get_bot(pos)
        if bot_on_ore is not None:
            if my_pos is None or not is_on_position(my_pos, pos):
                return False

        if self.enforce_ally_side and not self.brain._is_closer_to_ally_core(pos):
            return False

        return True

    # ── Closest ore lookup ─────────────────────────────────────────

    def _find_closest_to_core(
        self,
        ct: Controller,
        mm: MapManager,
        current_round: int,
        enemy_count: int = 0,
        my_pos: Position | None = None,
    ) -> Position | None:
        """Return the valid ore position closest (Manhattan) to ally core, or None."""
        ally_core = self.brain.map_manager.ally_core_pos
        best_pos: Position | None = None
        best_dist = float("inf")
        best_self_dist = float("inf")

        for pos in mm.known_ore_positions:
            if not self._is_valid_ore(ct, mm, pos, current_round, enemy_count, my_pos):
                continue
            dist = manhattan(pos, ally_core)
            self_dist = manhattan(pos, my_pos) if my_pos is not None else 0
            if dist < best_dist or (dist == best_dist and self_dist < best_self_dist):
                best_dist = dist
                best_self_dist = self_dist
                best_pos = pos

        return best_pos

    # ── Enemy counting ──────────────────────────────────────────────

    def _count_nearby_enemies(self, ct: Controller, mm: MapManager) -> int:
        count = 0
        team = ct.get_team()
        for pos in mm.nearby_positions:
            building = mm.get_building(pos)
            if building is not None and building.team != team:
                count += 1
        return count

    # ── Cooldown management ─────────────────────────────────────────

    def _expire_cooldowns(self, current_round: int) -> None:
        expired = [p for p, r in self.cooldowns.items()
                   if current_round - r > self.cooldown_duration]
        for p in expired:
            del self.cooldowns[p]

    # ── Target bookkeeping ─────────────────────────────────────────

    def _assign_target(self, pos: Position | None, current_round: int) -> None:
        """Set a new target and record when routing began."""
        if pos != self.target:
            self._target_set_round = current_round if pos is not None else -1
        self.target = pos

    def _clear_target(self, current_round: int, *, cooldown: bool = False) -> None:
        """Drop the current target, optionally placing it on cooldown."""
        if self.target is not None and cooldown:
            self.cooldowns[self.target] = current_round
        self.target = None
        self._target_set_round = -1

    # ── Target validation ───────────────────────────────────────────

    def _validate_target(
        self,
        ct: Controller,
        mm: MapManager,
        my_pos: Position,
        current_round: int,
        enemy_count: int,
    ) -> None:
        """Drop current target if it's no longer valid or we've timed out."""
        if self.target is None:
            return
        on_target = is_on_position(my_pos, self.target)
        ec = 0 if on_target or in_action_range(my_pos, self.target) else enemy_count
        if not self._is_valid_ore(ct, mm, self.target, current_round, ec, my_pos):
            self._clear_target(current_round, cooldown=True)
            return

        # Timed out — been routing too long without reaching the ore
        if (
            self.route_timeout > 0
            and not on_target
            and self._target_set_round > 0
            and current_round - self._target_set_round >= self.route_timeout
        ):
            self._clear_target(current_round, cooldown=True)

    # ── Standard interface ──────────────────────────────────────────

    def has_target(self) -> bool:
        return self.target is not None

    def reset(self, ct=None) -> None:
        self.target = None
        self._target_set_round = -1