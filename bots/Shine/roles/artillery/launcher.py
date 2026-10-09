"""Launcher turret — standalone, no MapManager.

Two jobs, checked in priority order each tick:

1. ALLY-CAPTURE: if a friendly builder bot is on one of our four CARDINAL
   neighbours AND an enemy harvester is within launch range, throw the
   builder onto a tile cardinal-adjacent to that harvester so it can
   claim/destroy it next tick.

   Diagonal ally builders are intentionally ignored — the caller controls
   builder movement and uses the cardinal/diagonal distinction as an
   opt-in signal.

2. ENEMY-THROW: if an enemy bot is adjacent (any of the 8 directions),
   throw it into an allied turret attack zone, or failing that, away
   from our core.
"""

from cambc import Controller, Position, EntityType, Direction
from debug.profiling import cputimer
from roles.builder.helpers import in_bounds

LAUNCH_RANGE_SQ = 26

# Enemy belt-like buildings that, if adjacent, suppress ally-builder launches.
_ENEMY_BELT_TYPES = {
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
}

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

# Cardinal only (for ally-builder pickup)
CARDINAL = [
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
]

# Marker type tag for core position (must match helpers/marker_expiry.py)
_MARKER_TYPE_CORE_POSITION = 3
_TYPE_MASK = 0x3

# How long turret-zone cache is valid (in ticks). Nearby turrets rarely
# change, so rebuilding every tick is wasteful.
TURRET_ZONE_CACHE_TICKS = 5


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

    def run(self, ct: Controller) -> None:
        if self.ally_core_pos is None:
            self.ally_core_pos = self._find_core_marker(ct)

        # Priority 1: throw an ally builder at an enemy harvester.
        # Skip if there's an enemy belt-like building adjacent to us —
        # launching an ally builder off a belt tile is unreliable.
        # Priority 2: throw an adjacent enemy into danger.
        if not self._adjacent_enemy_belt(ct):
            if self.try_launch_ally_to_harvester(ct):
                return
        self.try_launch_enemy_to_danger(ct)

    def _adjacent_enemy_belt(self, ct: Controller) -> bool:
        my_pos = ct.get_position()
        my_team = ct.get_team()
        for d in DIRECTIONS:
            adj = my_pos.add(d)
            if not in_bounds(ct, adj):
                continue
            bid = ct.get_tile_building_id(adj)
            if bid is None:
                continue
            try:
                if ct.get_team(bid) == my_team:
                    continue
                if ct.get_entity_type(bid) in _ENEMY_BELT_TYPES:
                    return True
            except Exception:
                continue
        return False

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
    # Priority 1: ally builder -> enemy harvester
    # ------------------------------------------------------------------


    def _find_near_ally_builders(self, ct: Controller) -> list[Position]:
        """Positions of ally builder bots on our 4 cardinal neighbours."""
        my_pos = ct.get_position()
        out: list[Position] = []
        for d in DIRECTIONS:
            adj = my_pos.add(d)
            if not in_bounds(ct, adj):
                continue
            if self._ally_builder_at(ct, adj):
                out.append(adj)
        print("nearby", out)
        return out

    def _find_cardinal_ally_builders(self, ct: Controller) -> list[Position]:
        """Positions of ally builder bots on our 4 cardinal neighbours."""
        my_pos = ct.get_position()
        out: list[Position] = []
        for d in CARDINAL:
            adj = my_pos.add(d)
            if not in_bounds(ct, adj):
                continue
            if self._ally_builder_at(ct, adj):
                out.append(adj)
        return out

    def _find_enemy_harvesters_in_range(self, ct: Controller) -> list[Position]:
        """Enemy harvester positions within LAUNCH_RANGE_SQ of us."""
        my_pos = ct.get_position()
        my_team = ct.get_team()
        out: list[Position] = []
        for eid in ct.get_nearby_entities():
            try:
                if ct.get_entity_type(eid) != EntityType.HARVESTER:
                    continue
                if ct.get_team(eid) == my_team:
                    continue
                hpos = ct.get_position(eid)
                if my_pos.distance_squared(hpos) <= LAUNCH_RANGE_SQ:
                    out.append(hpos)
            except Exception:
                continue
        return out

    def _pick_landing_near_harvester( self, ct: Controller, harvester_pos: Position) -> Position | None:
        """Best cardinal-adjacent tile next to the harvester to land a builder on.

        Priority (lower index = higher):
          0 — empty ground (builder can immediately build a turret here)
          1 — our own road (destroyable, then buildable)
          2 — any other passable tile (fallback)

        Within a bucket, prefer the tile farthest from our core (deepest push),
        or farthest from us if core unknown.
        """
        my_pos = ct.get_position()
        my_team = ct.get_team()

        empty: list[Position] = []
        ally_road: list[Position] = []
        other: list[Position] = []

        for d in CARDINAL:
            tile = harvester_pos.add(d)
            if not in_bounds(ct, tile):
                continue
            if my_pos.distance_squared(tile) > LAUNCH_RANGE_SQ:
                continue
            if not ct.is_tile_passable(tile):
                continue
            if ct.get_tile_builder_bot_id(tile) is not None:
                continue

            # Classify by what's on the tile
            bid = ct.get_tile_building_id(tile)
            if bid is None:
                empty.append(tile)
                continue

            try:
                if (ct.get_team(bid) == my_team
                        and ct.get_entity_type(bid) == EntityType.ROAD):
                    ally_road.append(tile)
                    continue
            except Exception:
                pass

            other.append(tile)

        # Pick from the highest-priority non-empty bucket
        bucket = empty or ally_road or other
        if not bucket:
            return None

        if self.ally_core_pos is not None:
            bucket.sort(key=lambda p: p.distance_squared(self.ally_core_pos), reverse=True)
        else:
            bucket.sort(key=lambda p: my_pos.distance_squared(p), reverse=True)

        return bucket[0]

    @cputimer
    def try_launch_ally_to_harvester(self, ct: Controller) -> bool:
        """Throw a cardinal-adjacent ally builder toward an enemy harvester."""
        # Cheap check first: do we even have a cardinal ally builder?
        builders = self._find_near_ally_builders(ct)
        if not builders:
            return False


        # More expensive: scan nearby entities for enemy harvesters
        harvesters = self._find_enemy_harvesters_in_range(ct)
        if not harvesters:
            return False

        # Harvester farthest from our core first (= deepest push)
        if self.ally_core_pos is not None:
            harvesters.sort(key=lambda h: h.distance_squared(self.ally_core_pos), reverse=True)
        else:
            my_pos = ct.get_position()
            harvesters.sort(key=lambda h: my_pos.distance_squared(h))

        # Cache landing tiles per harvester — reused across builders
        landing_cache: dict[tuple[int, int], Position | None] = {}

        for builder_pos in builders:
            for hpos in harvesters:
                key = (hpos.x, hpos.y)
                if key not in landing_cache:
                    landing_cache[key] = self._pick_landing_near_harvester(ct, hpos)
                landing = landing_cache[key]
                if landing is None:
                    continue
                if ct.can_launch(builder_pos, landing):
                    ct.draw_indicator_line(builder_pos, landing, 255, 0, 0)
                    ct.launch(builder_pos, landing)
                    print(f"Launcher: launched ally {builder_pos} -> {landing} "
                          f"(harvester @ {hpos})")
                    return True
        return False

    # ------------------------------------------------------------------
    # Priority 2: enemy -> danger
    # ------------------------------------------------------------------

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
        """Passable tiles within launch range, sorted for enemy-throw targeting.

        Priority:
          1. Tiles inside an allied turret attack zone (farthest from core)
          2. Remaining tiles (farthest from core / closest to center)
        """
        w = ct.get_map_width()
        h = ct.get_map_height()
        in_zone: list[Position] = []
        outside: list[Position] = []

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
                # Don't land on an ally bot
                if self._ally_builder_at(ct, target):
                    continue

                if (tx, ty) in turret_zone:
                    in_zone.append(target)
                else:
                    outside.append(target)

        if core is not None:
            in_zone.sort(key=lambda p: p.distance_squared(core), reverse=True)
            outside.sort(key=lambda p: p.distance_squared(core), reverse=True)
        else:
            cx, cy = w // 2, h // 2
            center = Position(cx, cy)
            in_zone.sort(key=lambda p: p.distance_squared(center))
            outside.sort(key=lambda p: p.distance_squared(center))

        return in_zone + outside
