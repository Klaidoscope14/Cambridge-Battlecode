"""Launcher turret — standalone, no MapManager.

ENEMY-THROW: if an enemy bot is adjacent (any of the 8 directions), throw
it into an allied turret attack zone, or failing that, away from our core.
"""

from cambc import Controller, Position, EntityType, Direction
from debug.profiling import cputimer
from roles.builder.helpers import in_bounds

LAUNCH_RANGE_SQ = 26

# Turret attack ranges (from spec)
GUNNER_RANGE_SQ = 13
SENTINEL_RANGE_SQ = 32
BREACH_RANGE_SQ = 5

TURRET_TYPES = {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}

# Don't throw enemy bots onto ANY of our own stuff.
_PROTECTED_TYPES = {
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.HARVESTER,
    EntityType.CORE,
    EntityType.FOUNDRY,
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
    EntityType.BARRIER,
}

# All 8 king-move directions (for enemy scan)
DIRECTIONS = [
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
]

# Marker type tag for core position (must match helpers/marker_expiry.py)
_MARKER_TYPE_CORE_POSITION = 3
_TYPE_MASK = 0x3

# How long turret-zone cache is valid (in ticks). Nearby turrets rarely
# change, so rebuilding every tick is wasteful.
TURRET_ZONE_CACHE_TICKS = 5

# Same idea for ally-infra (belts/bridges/harvesters) used to bias throws
# away from our economy.
INFRA_CACHE_TICKS = 5

# Belts + bridges + harvesters define the "economy center of mass" we want
# to throw enemies AWAY from.
_INFRA_COM_TYPES = {
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.HARVESTER,
}

# Tiles within this squared distance of any ally harvester get a heavy
# penalty (we don't want enemies parked next to a harvester).
HARVESTER_AVOID_RADIUS_SQ = 4

# Landing-tile scoring weights. Tuned so:
#   enemy-building > harvester-proximity-penalty > away-from-COM
#   > away-from-core > turret-zone-bonus
W_ENEMY_BUILDING = 10000.0
W_NEAR_HARVESTER = -3000.0
W_AWAY_FROM_COM = 3.0
W_AWAY_FROM_CORE = 1.0
W_IN_TURRET_ZONE = 50.0


def _decode_core_pos_from_value(value: int) -> Position | None:
    if (value & _TYPE_MASK) != _MARKER_TYPE_CORE_POSITION:
        return None
    x = (value >> 14) & 0x1FF
    y = (value >> 23) & 0x1FF
    return Position(x, y)


# ------------------------------------------------------------------
# Turret attack zone computation
# ------------------------------------------------------------------

def _gunner_attack_tiles(turret_pos: Position, facing: Direction) -> set[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    dx, dy = facing.delta()
    for k in range(1, 6):
        tx = turret_pos.x + dx * k
        ty = turret_pos.y + dy * k
        if (tx - turret_pos.x) ** 2 + (ty - turret_pos.y) ** 2 > GUNNER_RANGE_SQ:
            break
        tiles.add((tx, ty))
    return tiles


def _sentinel_attack_tiles(turret_pos: Position, facing: Direction) -> set[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    dx, dy = facing.delta()
    for k in range(1, 7):
        cx = turret_pos.x + dx * k
        cy = turret_pos.y + dy * k
        for ox in range(-1, 2):
            for oy in range(-1, 2):
                tx, ty = cx + ox, cy + oy
                if (tx - turret_pos.x) ** 2 + (ty - turret_pos.y) ** 2 <= SENTINEL_RANGE_SQ:
                    tiles.add((tx, ty))
    return tiles


def _breach_attack_tiles(turret_pos: Position, facing: Direction) -> set[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    fdx, fdy = facing.delta()
    for ddx in range(-2, 3):
        for ddy in range(-2, 3):
            if ddx == 0 and ddy == 0:
                continue
            if ddx * fdx + ddy * fdy <= 0:
                continue
            if ddx * ddx + ddy * ddy > BREACH_RANGE_SQ:
                continue
            tiles.add((turret_pos.x + ddx, turret_pos.y + ddy))
    return tiles


def _compute_turret_zone(turret_pos: Position, turret_type: EntityType, facing: Direction) -> set[tuple[int, int]]:
    if turret_type == EntityType.GUNNER:
        return _gunner_attack_tiles(turret_pos, facing)
    elif turret_type == EntityType.SENTINEL:
        return _sentinel_attack_tiles(turret_pos, facing)
    elif turret_type == EntityType.BREACH:
        return _breach_attack_tiles(turret_pos, facing)
    return set()


# ------------------------------------------------------------------
# Launcher
# ------------------------------------------------------------------

class Launcher:
    def __init__(self, ct: Controller) -> None:
        self.ally_core_pos: Position | None = None
        # Turret-zone cache
        self._turret_zone_cache: set[tuple[int, int]] = set()
        self._turret_zone_cache_tick: int = -999
        # Ally-infra cache
        self._infra_com: tuple[float, float] | None = None
        self._harvester_positions: list[tuple[int, int]] = []
        self._infra_cache_tick: int = -999

    def run(self, ct: Controller) -> None:
        if self.ally_core_pos is None:
            self.ally_core_pos = self._find_core_marker(ct)
        self.try_launch_enemy_to_danger(ct)

    # ------------------------------------------------------------------
    # Small tile-query helpers (direct ct.*, no MapManager)
    # ------------------------------------------------------------------

    def _ally_builder_at(self, ct: Controller, pos: Position) -> bool:
        """True if an ally builder bot is standing on `pos`."""
        bid = ct.get_tile_builder_bot_id(pos)
        if bid is None:
            return False
        try:
            return ct.get_team(bid) == ct.get_team()
        except Exception:
            return False

    def _enemy_builder_at(self, ct: Controller, pos: Position) -> bool:
        """True if an enemy builder bot is standing on `pos`."""
        bid = ct.get_tile_builder_bot_id(pos)
        if bid is None:
            return False
        try:
            return ct.get_team(bid) != ct.get_team()
        except Exception:
            return False

    def _enemy_building_at(self, ct: Controller, pos: Position) -> bool:
        """True if `pos` has an enemy building on it."""
        bid = ct.get_tile_building_id(pos)
        if bid is None:
            return False
        try:
            return ct.get_team(bid) != ct.get_team()
        except Exception:
            return False

    def _ally_building_blocks(self, ct: Controller, pos: Position) -> bool:
        """True if `pos` has one of our own protected buildings on it."""
        bid = ct.get_tile_building_id(pos)
        if bid is None:
            return False
        try:
            if ct.get_team(bid) != ct.get_team():
                return False
            return ct.get_entity_type(bid) in _PROTECTED_TYPES
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core position discovery
    # ------------------------------------------------------------------

    def _find_core_marker(self, ct: Controller) -> Position | None:
        my_team = ct.get_team()
        for eid in ct.get_nearby_entities():
            try:
                if ct.get_entity_type(eid) != EntityType.MARKER:
                    continue
                if ct.get_team(eid) != my_team:
                    continue
                value = ct.get_marker_value(eid)
                core_pos = _decode_core_pos_from_value(value)
                if core_pos is not None:
                    print(f"Launcher: found core position marker -> {core_pos}")
                    return core_pos
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Enemy -> danger
    # ------------------------------------------------------------------

    def _get_ally_infra(
        self, ct: Controller
    ) -> tuple[tuple[float, float] | None, list[tuple[int, int]]]:
        """Cached (COM, harvester positions) for nearby ally infrastructure.

        COM is averaged over conveyors, bridges, armoured conveyors, and
        harvesters. Harvester positions are returned separately so we can
        apply a tighter proximity penalty around them.
        """
        current_tick = ct.get_current_round()
        if current_tick - self._infra_cache_tick < INFRA_CACHE_TICKS:
            return self._infra_com, self._harvester_positions

        my_team = ct.get_team()
        sx = sy = 0
        n = 0
        harvesters: list[tuple[int, int]] = []
        for eid in ct.get_nearby_entities():
            try:
                etype = ct.get_entity_type(eid)
                if etype not in _INFRA_COM_TYPES:
                    continue
                if ct.get_team(eid) != my_team:
                    continue
                p = ct.get_position(eid)
                sx += p.x
                sy += p.y
                n += 1
                if etype == EntityType.HARVESTER:
                    harvesters.append((p.x, p.y))
            except Exception:
                continue

        com = (sx / n, sy / n) if n > 0 else None
        self._infra_com = com
        self._harvester_positions = harvesters
        self._infra_cache_tick = current_tick
        return com, harvesters

    def _get_turret_zones(self, ct: Controller) -> set[tuple[int, int]]:
        """Cached turret-zone union. Rebuilt every TURRET_ZONE_CACHE_TICKS ticks."""
        current_tick = ct.get_current_round()
        if current_tick - self._turret_zone_cache_tick < TURRET_ZONE_CACHE_TICKS:
            return self._turret_zone_cache

        my_team = ct.get_team()
        zone: set[tuple[int, int]] = set()
        for eid in ct.get_nearby_entities():
            try:
                etype = ct.get_entity_type(eid)
                if etype not in TURRET_TYPES:
                    continue
                if ct.get_team(eid) != my_team:
                    continue
                turret_pos = ct.get_position(eid)
                facing = ct.get_direction(eid)
                zone.update(_compute_turret_zone(turret_pos, etype, facing))
            except Exception:
                continue

        self._turret_zone_cache = zone
        self._turret_zone_cache_tick = current_tick
        return zone

    @cputimer
    def try_launch_enemy_to_danger(self, ct: Controller) -> bool:
        my_pos = ct.get_position()
        core = self.ally_core_pos

        # Cheap check first: any adjacent enemy bot at all?
        enemy_bots: list[Position] = []
        for d in DIRECTIONS:
            adj = my_pos.add(d)
            if not in_bounds(ct, adj):
                continue
            if self._enemy_builder_at(ct, adj):
                enemy_bots.append(adj)

        if not enemy_bots:
            return False

        if core is not None:
            enemy_bots.sort(key=lambda p: p.distance_squared(core))
        else:
            enemy_bots.sort(key=lambda p: p.distance_squared(my_pos))

        turret_zone = self._get_turret_zones(ct)
        landing_tiles = self._get_landing_tiles(ct, my_pos, core, turret_zone)
        if not landing_tiles:
            return False

        for bot_pos in enemy_bots:
            for target in landing_tiles:
                if ct.can_launch(bot_pos, target):
                    in_zone = (target.x, target.y) in turret_zone
                    ct.draw_indicator_line(bot_pos, target, 0, 0, 255)
                    ct.launch(bot_pos, target)
                    print(f"Launcher: threw enemy {bot_pos} -> {target}"
                          f"{' (into turret zone!)' if in_zone else ''}")
                    return True
        return False

    def _get_landing_tiles(
        self,
        ct: Controller,
        my_pos: Position,
        core: Position | None,
        turret_zone: set[tuple[int, int]],
    ) -> list[Position]:
        """Passable tiles within launch range, ranked for enemy-throw targeting.

        Score (higher is better):
          + W_ENEMY_BUILDING   if tile has an enemy building (chip damage)
          + W_NEAR_HARVESTER   (negative) if close to one of our harvesters
          + W_AWAY_FROM_COM    * sq-dist from ally infra center of mass
          + W_AWAY_FROM_CORE   * sq-dist from our core (if known)
          + W_IN_TURRET_ZONE   if tile sits inside an allied turret kill-zone
        """
        w = ct.get_map_width()
        h = ct.get_map_height()
        com, harvesters = self._get_ally_infra(ct)

        scored: list[tuple[float, Position]] = []

        for dx in range(-5, 6):
            for dy in range(-5, 6):
                dist_sq = dx * dx + dy * dy
                if dist_sq == 0 or dist_sq > LAUNCH_RANGE_SQ:
                    continue
                tx, ty = my_pos.x + dx, my_pos.y + dy
                if tx < 0 or tx >= w or ty < 0 or ty >= h:
                    continue
                target = Position(tx, ty)
                if not ct.is_tile_passable(target):
                    continue
                if self._ally_building_blocks(ct, target):
                    continue
                if self._ally_builder_at(ct, target):
                    continue

                score = 0.0

                if self._enemy_building_at(ct, target):
                    score += W_ENEMY_BUILDING

                for hx, hy in harvesters:
                    if (tx - hx) * (tx - hx) + (ty - hy) * (ty - hy) <= HARVESTER_AVOID_RADIUS_SQ:
                        score += W_NEAR_HARVESTER
                        break

                if com is not None:
                    cx, cy = com
                    score += W_AWAY_FROM_COM * ((tx - cx) ** 2 + (ty - cy) ** 2)

                if core is not None:
                    score += W_AWAY_FROM_CORE * (
                        (tx - core.x) ** 2 + (ty - core.y) ** 2
                    )

                if (tx, ty) in turret_zone:
                    score += W_IN_TURRET_ZONE

                scored.append((score, target))

        scored.sort(key=lambda s: s[0], reverse=True)
        return [t for _, t in scored]
