"""Launcher: picks up adjacent enemy bots and throws them into danger.

Priority: throw into allied turret attack zones when possible, otherwise
throw away from core (or toward map center if core is unknown).

Reads ally core position from a CORE_POSITION marker placed by the builder
that constructed this launcher.
"""

from cambc import Controller, Position, EntityType, Direction
from debug.profiling import cputimer
from map.map_manager import MapManager
from roles.builder.helpers import in_bounds

LAUNCH_RANGE_SQ = 26

# Turret attack ranges (from spec)
GUNNER_RANGE_SQ = 13
SENTINEL_RANGE_SQ = 32
BREACH_RANGE_SQ = 5

TURRET_TYPES = {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}

# Don't throw enemies onto these allied buildings
_PROTECTED_TYPES = {
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
}

# All 8 king-move directions for scanning adjacent tiles
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

# Marker type tag for core position (must match comms/markers.py)
_MARKER_TYPE_CORE_POSITION = 3
_TYPE_MASK = 0x3


def _decode_core_pos_from_value(value: int) -> Position | None:
    """Decode a core-position marker value, returning Position or None if wrong type."""
    if (value & _TYPE_MASK) != _MARKER_TYPE_CORE_POSITION:
        return None
    x = (value >> 14) & 0x1FF
    y = (value >> 23) & 0x1FF
    return Position(x, y)


# ------------------------------------------------------------------
# Turret attack zone computation
# ------------------------------------------------------------------

def _gunner_attack_tiles(turret_pos: Position, facing: Direction) -> set[tuple[int, int]]:
    """Tiles along the gunner's firing line within r²=13.

    Gunners fire at the CLOSEST non-empty tile in their facing direction.
    We return the full line — if the enemy lands there, it becomes the target.
    """
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
    """Tiles within 1 king move (Chebyshev) of the sentinel's firing line, within r²=32.

    The sentinel's line extends in the facing direction; any tile within
    Chebyshev distance 1 of a tile on that line is hittable.
    """
    tiles: set[tuple[int, int]] = set()
    dx, dy = facing.delta()
    for k in range(1, 7):
        cx = turret_pos.x + dx * k
        cy = turret_pos.y + dy * k
        # Expand by 1 Chebyshev distance around each line tile
        for ox in range(-1, 2):
            for oy in range(-1, 2):
                tx, ty = cx + ox, cy + oy
                if (tx - turret_pos.x) ** 2 + (ty - turret_pos.y) ** 2 <= SENTINEL_RANGE_SQ:
                    tiles.add((tx, ty))
    return tiles


def _breach_attack_tiles(turret_pos: Position, facing: Direction) -> set[tuple[int, int]]:
    """Tiles in the breach's 180° forward cone within r²=5.

    A tile is in the cone if the dot product of its displacement with the
    facing direction is positive (forward half-plane).
    """
    tiles: set[tuple[int, int]] = set()
    fdx, fdy = facing.delta()
    for ddx in range(-2, 3):
        for ddy in range(-2, 3):
            if ddx == 0 and ddy == 0:
                continue
            # Dot product with facing direction — must be positive (forward)
            if ddx * fdx + ddy * fdy <= 0:
                continue
            if ddx * ddx + ddy * ddy > BREACH_RANGE_SQ:
                continue
            tiles.add((turret_pos.x + ddx, turret_pos.y + ddy))
    return tiles


def _compute_turret_zone(turret_pos: Position, turret_type: EntityType, facing: Direction) -> set[tuple[int, int]]:
    """Return the set of (x, y) tiles this turret can attack."""
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
        self.map_manager = MapManager(ct)
        self.ally_core_pos: Position | None = None

    def run(self, ct: Controller) -> None:
        self.map_manager.update(ct)

        # Try to learn core position from nearby markers (once is enough,
        # but keep scanning in case the marker wasn't visible on round 1)
        if self.ally_core_pos is None:
            self.ally_core_pos = self._find_core_marker(ct)

        self.try_launch(ct)

    # ------------------------------------------------------------------
    # Core position discovery
    # ------------------------------------------------------------------

    def _find_core_marker(self, ct: Controller) -> Position | None:
        """Scan nearby entities for a CORE_POSITION marker and decode it."""
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
    # Turret zone scanning
    # ------------------------------------------------------------------

    def _collect_turret_zones(self, ct: Controller) -> set[tuple[int, int]]:
        """Scan nearby allied turrets and union all their attack tiles."""
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

        return zone

    # ------------------------------------------------------------------
    # Launch logic
    # ------------------------------------------------------------------

    @cputimer
    def try_launch(self, ct: Controller) -> bool:
        """Find the highest-priority adjacent enemy bot and throw it into danger."""
        my_pos = ct.get_position()
        my_team = ct.get_team()
        core = self.ally_core_pos

        # ── 1. Collect adjacent enemy bots ────────────────────────────
        enemy_bots: list[Position] = []
        for d in DIRECTIONS:
            adj = my_pos.add(d)
            if not in_bounds(ct, adj):
                continue
            bot = self.map_manager.get_bot(adj)
            if bot is not None and bot.team != my_team:
                enemy_bots.append(adj)

        if not enemy_bots:
            return False

        # ── 2. Prioritise: enemy closest to our core is biggest threat ─
        if core is not None:
            enemy_bots.sort(key=lambda p: p.distance_squared(core))
        else:
            enemy_bots.sort(key=lambda p: p.distance_squared(my_pos))

        # ── 3. Collect allied turret attack zones ─────────────────────
        turret_zone = self._collect_turret_zones(ct)

        # ── 4. Build candidate landing tiles ──────────────────────────
        landing_tiles = self._get_landing_tiles(ct, my_pos, core, turret_zone)
        if not landing_tiles:
            return False

        # ── 5. Try each enemy in priority order ───────────────────────
        for bot_pos in enemy_bots:
            for target in landing_tiles:
                if ct.can_launch(bot_pos, target):
                    in_zone = (target.x, target.y) in turret_zone
                    ct.launch(bot_pos, target)
                    print(f"Launcher: threw {bot_pos} -> {target}"
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
        """Return passable tiles within launch range, sorted by best throw target.

        Sorting priority:
        1. Tiles in allied turret attack zones (sorted farthest from core)
        2. Remaining tiles (sorted farthest from core / closest to center)
        """
        w = ct.get_map_width()
        h = ct.get_map_height()
        my_team = ct.get_team()
        in_zone: list[Position] = []
        outside: list[Position] = []

        # Scan the bounding box of launch range (radius ~5.1)
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
                # Don't throw enemies onto our own supply chain
                building = self.map_manager.get_building(target)
                if (building is not None
                        and building.team == my_team
                        and building.entity_type in _PROTECTED_TYPES):
                    continue
                if (tx, ty) in turret_zone:
                    in_zone.append(target)
                else:
                    outside.append(target)

        # Sort turret-zone tiles: farthest from core (max damage + max travel)
        # Sort outside tiles: same fallback logic as before
        if core is not None:
            in_zone.sort(key=lambda p: p.distance_squared(core), reverse=True)
            outside.sort(key=lambda p: p.distance_squared(core), reverse=True)
        else:
            cx, cy = w // 2, h // 2
            center = Position(cx, cy)
            in_zone.sort(key=lambda p: p.distance_squared(center))
            outside.sort(key=lambda p: p.distance_squared(center))

        # Turret-zone tiles first, then fallback
        return in_zone + outside