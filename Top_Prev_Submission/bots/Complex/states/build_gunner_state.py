from cambc import EntityType, Environment, GameConstants, Position, Direction
from debug.profiling import cputimer
from helpers.directions import CARDINAL, DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager
from nav.common import common_path
from states.builder_state import BuilderState

# ── Tuning constants ────────────────────────────────────────────────

ACTION_RADIUS_SQ = 2
MAX_ATTEMPT_ROUNDS = 10
MAX_GUNNERS_PER_HARVESTER = 2
SKIP_AXIONITE_HARVESTERS = True
DESTROYABLE = {EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER}

# Turret types on enemy harvesters that we'd want to snipe (expandable later)
TARGETABLE_TURRET_TYPES = {EntityType.SENTINEL, EntityType.GUNNER}


# ── Line-of-sight helpers ──────────────────────────────────────────

def _firing_line(pos: Position, facing: Direction) -> list[Position]:
    """Return the tiles a gunner at pos facing direction would shoot through.
    Gunner range: 2 diagonally, 3 cardinally.
    """
    dx, dy = facing.delta()
    if dx == 0 or dy == 0:
        max_range = 3  # cardinal
    else:
        max_range = 2  # diagonal

    tiles = []
    for step in range(1, max_range + 1):
        tiles.append(Position(pos.x + dx * step, pos.y + dy * step))
    return tiles


def _snap_to_cardinal(d: Direction) -> Direction:
    """Snap a direction to the nearest cardinal. Arbitrary tie-break."""
    dx, dy = d.delta()
    if abs(dx) >= abs(dy):
        return Direction.EAST if dx > 0 else Direction.WEST
    return Direction.SOUTH if dy > 0 else Direction.NORTH


def _has_clear_line_to_core( mm: MapManager, gunner_pos: Position, facing: Direction, enemy_team, my_team
) -> bool:
    """Check if a gunner at gunner_pos facing direction can hit an enemy core tile.
    Walks the firing line, ignoring builder bots. Only walls and non-road ally buildings block.
    """
    for tile in _firing_line(gunner_pos, facing):
        if not on_map(tile, mm.width, mm.height):
            return False

        env = mm.get_tile(tile)
        if env == Environment.WALL:
            return False

        building = mm.get_building(tile)
        if building is not None:
            if building.entity_type == EntityType.CORE and building.team == enemy_team:
                return True
            # Our own building (except roads) blocks — we don't want to shoot our stuff
            if building.team == my_team and building.entity_type != EntityType.ROAD:
                return False

    return False


def _has_clear_line_to_pos(
    mm: MapManager, gunner_pos: Position, facing: Direction, target_pos: Position, my_team
) -> bool:
    """Check if a gunner at gunner_pos facing direction can hit target_pos.
    Walks the firing line, ignoring builder bots. Only walls and non-road ally buildings block.
    """
    for tile in _firing_line(gunner_pos, facing):
        if not on_map(tile, mm.width, mm.height):
            return False

        env = mm.get_tile(tile)
        if env == Environment.WALL:
            return False

        if tile.x == target_pos.x and tile.y == target_pos.y:
            return True

        building = mm.get_building(tile)
        if building is not None:
            if building.team == my_team and building.entity_type != EntityType.ROAD:
                return False

    return False


# ── State class ─────────────────────────────────────────────────────


class BuildGunnerState:
    def __init__(self, ct, brain) -> None:
        self.brain = brain
        self.target_pos: Position | None = None
        self.target_dir: Direction | None = None
        self.attempt_start: int | None = None

    def _is_buildable(self, ct, mm: MapManager, pos: Position) -> bool:
        building = mm.get_building(pos)
        bot = mm.get_bot(pos)
        if bot is not None and bot.id != ct.get_id():
            return False
        if building is None:
            tile = mm.get_tile(pos)
            return tile is not None and tile == Environment.EMPTY
        if building.team == ct.get_team() and building.entity_type in DESTROYABLE:
            return True
        return False

    def _count_adjacent_gunners(self, ct, mm: MapManager, harvester_pos: Position) -> int:
        """Count allied gunners already adjacent to this harvester."""
        team = ct.get_team()
        count = 0
        for d in CARDINAL:
            adj = harvester_pos.add(d)
            if not on_map(adj, mm.width, mm.height):
                continue
            building = mm.get_building(adj)
            if (
                building is not None
                and building.team == team
                and building.entity_type == EntityType.GUNNER
            ):
                count += 1
        return count

    def _resolve_enemy_team(self, mm: MapManager):
        """Resolve enemy team from visible core tiles."""
        for core_pos in mm.nearby_enemy_core_pos:
            b = mm.get_building(core_pos)
            if b is not None and b.entity_type == EntityType.CORE:
                return b.team
        return None

    def _find_gunner_spot(self, ct, mm: MapManager, my_pos: Position):
        """Find the best spot to build a gunner next to a harvester.
        Priority 1: core pressure (line of sight to enemy core).
        Priority 2: turret sniping (line of sight to enemy turret).
        """
        has_core = bool(mm.nearby_enemy_core_pos)
        has_turrets = bool(mm.nearby_enemy_turret_pos)

        if not has_core and not has_turrets:
            return None

        enemy_team = self._resolve_enemy_team(mm) if has_core else None

        best_core = None
        best_core_dist = float("inf")
        best_turret = None
        best_turret_dist = float("inf")

        skip_harvesters = set()
        checked_harvesters = set()

        for harvester_pos, adj in mm.nearby_harvester_card_pos + mm.nearby_harvester_enemy_card_pos:
            hkey = (harvester_pos.x, harvester_pos.y)
            if SKIP_AXIONITE_HARVESTERS and mm.get_tile(harvester_pos) == Environment.ORE_AXIONITE:
                continue
            if hkey in skip_harvesters:
                continue
            if hkey not in checked_harvesters:
                checked_harvesters.add(hkey)
                if self._count_adjacent_gunners(ct, mm, harvester_pos) >= MAX_GUNNERS_PER_HARVESTER:
                    skip_harvesters.add(hkey)
                    continue

            if not self._is_buildable(ct, mm, adj):
                continue

            dist = my_pos.distance_squared(adj)

            # Priority 1: core pressure
            if has_core and enemy_team is not None and dist < best_core_dist:
                if any(adj.distance_squared(cp) <= 25 for cp in mm.nearby_enemy_core_pos):
                    facing = self._pick_facing_for_core(ct, mm, adj, enemy_team)
                    if facing is not None and adj.add(facing) != harvester_pos:
                        best_core_dist = dist
                        best_core = (adj, facing)
                        continue

            # Priority 2: turret sniping
            if has_turrets and dist < best_turret_dist:
                facing = self._pick_facing_for_turret(ct, mm, adj)
                if facing is not None and adj.add(facing) != harvester_pos:
                    best_turret_dist = dist
                    best_turret = (adj, facing)

        # Core pressure takes priority
        return best_core if best_core is not None else best_turret

    def _pick_facing_for_core(
        self, ct, mm: MapManager, gunner_pos: Position, enemy_team
    ) -> Direction | None:
        team = ct.get_team()
        toward_core = gunner_pos.direction_to(mm.spotted_enemy_core_pos or mm.nearby_enemy_core_pos[0])
        best_first = _snap_to_cardinal(toward_core)

        if _has_clear_line_to_core(mm, gunner_pos, best_first, enemy_team, team):
            return best_first
        for d in DIRECTIONS:
            if d == best_first or d == Direction.CENTRE:
                continue
            if _has_clear_line_to_core(mm, gunner_pos, d, enemy_team, team):
                return d
        return None

    def _pick_facing_for_turret(
        self, ct, mm: MapManager, gunner_pos: Position
    ) -> Direction | None:
        team = ct.get_team()
        for turret_pos in mm.nearby_enemy_turret_pos:
            building = mm.get_building(turret_pos)
            if building is None or building.entity_type not in TARGETABLE_TURRET_TYPES:
                continue

            toward_turret = gunner_pos.direction_to(turret_pos)

            if _has_clear_line_to_pos(mm, gunner_pos, toward_turret, turret_pos, team):
                return toward_turret
            for d in DIRECTIONS:
                if d == toward_turret or d == Direction.CENTRE:
                    continue
                if _has_clear_line_to_pos(mm, gunner_pos, d, turret_pos, team):
                    return d

        return None

    def _is_target_valid(self, ct, mm: MapManager) -> bool:
        if self.target_pos is None:
            return False
        if not self._is_buildable(ct, mm, self.target_pos):
            return False
        if self.target_dir is None:
            return False

        team = ct.get_team()
        # Check if we still have core LOS
        if mm.nearby_enemy_core_pos:
            enemy_team = self._resolve_enemy_team(mm)
            if enemy_team is not None:
                if _has_clear_line_to_core(mm, self.target_pos, self.target_dir, enemy_team, team):
                    return True

        # Check if we still have turret LOS
        for turret_pos in mm.nearby_enemy_turret_pos:
            building = mm.get_building(turret_pos)
            if building is None or building.entity_type not in TARGETABLE_TURRET_TYPES:
                continue
            if _has_clear_line_to_pos(mm, self.target_pos, self.target_dir, turret_pos, team):
                return True

        return False

    @cputimer
    def determine(self, ct, state_manager):
        mm = self.brain.map_manager

        # Nothing to shoot at
        if not mm.nearby_enemy_core_pos and not mm.nearby_enemy_turret_pos:
            self._clear()
            return False

        # Can't afford it
        cost = ct.get_gunner_cost()
        resources = ct.get_global_resources()
        if resources[0] < cost[0]:
            self._clear()
            return False

        my_pos = ct.get_position()

        # Keep current target if still valid
        if self.target_pos is not None:
            if self._is_target_valid(ct, mm):
                state_manager.current_state = BuilderState.BUILD_GUNNER
                return True

        # Find new spot
        result = self._find_gunner_spot(ct, mm, my_pos)
        if result is not None:
            self.target_pos, self.target_dir = result
            self.attempt_start = ct.get_current_round()
            state_manager.current_state = BuilderState.BUILD_GUNNER
            return True

        self._clear()
        return False

    def execute(self, ct):
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        if self.target_pos is None:
            return

        # Timeout
        if self.attempt_start is not None and ct.get_current_round() - self.attempt_start > MAX_ATTEMPT_ROUNDS:
            self._clear()
            return

        # Standing on build tile — destroy, step off, build
        if my_pos == self.target_pos:
            if ct.get_action_cooldown() > 0 or ct.get_move_cooldown() > 0:
                return
            building = mm.get_building(self.target_pos)
            if building is not None and building.team == ct.get_team() and building.entity_type in DESTROYABLE:
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            for d in DIRECTIONS:
                if ct.can_move(d):
                    ct.move(d)
                    break
            if ct.can_build_gunner(self.target_pos, self.target_dir):
                ct.build_gunner(self.target_pos, self.target_dir)
                self._clear()
            return

        # Adjacent — clear blocker and build
        if my_pos.distance_squared(self.target_pos) <= ACTION_RADIUS_SQ:
            building = mm.get_building(self.target_pos)
            if building is not None and building.team == ct.get_team() and building.entity_type in DESTROYABLE:
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            if ct.can_build_gunner(self.target_pos, self.target_dir):
                ct.build_gunner(self.target_pos, self.target_dir)
                self._clear()
                return

        # Walk toward target
        common_path(ct, mm, self.brain.pathing, self.target_pos)

    def _clear(self):
        self.target_pos = None
        self.target_dir = None
        self.attempt_start = None
