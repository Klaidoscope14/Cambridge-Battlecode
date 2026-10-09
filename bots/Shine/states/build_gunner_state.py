from cambc import EntityType, Environment, GameConstants, Position, Direction
from debug.profiling import cputimer
from helpers.directions import DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager
from turret.buildable import is_buildable_spot, is_destroyable_blocker
from turret.safe_path import path_to_build_spot
from turret.step_off import handle_on_build_tile
from states.builder_state import BuilderState

# ── Tuning constants ────────────────────────────────────────────────

DEBUG = False

ACTION_RADIUS_SQ = 2
MAX_ATTEMPT_ROUNDS = 2000
MAX_GUNNERS_PER_HARVESTER = 2
SKIP_AXIONITE_HARVESTERS = True


def _dbg(msg: str) -> None:
    if DEBUG:
        print(f"[BuildGunner] {msg}")

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


def _build_firing_offset_map() -> dict[tuple[int, int], Direction]:
    """Precompute (dx, dy) -> Direction for every tile a gunner can reach.
    Gunner range: 3 cardinal, 2 diagonal. Each offset maps to exactly one facing.
    """
    table: dict[tuple[int, int], Direction] = {}
    for d in DIRECTIONS:
        dx, dy = d.delta()
        max_range = 3 if (dx == 0 or dy == 0) else 2
        for step in range(1, max_range + 1):
            table.setdefault((dx * step, dy * step), d)
    return table


_FIRING_OFFSETS = _build_firing_offset_map()


def _firing_dir_to(gunner_pos: Position, target_pos: Position) -> Direction | None:
    """Return the unique facing that would make a gunner at gunner_pos hit target_pos,
    or None if target is out of range."""
    return _FIRING_OFFSETS.get((target_pos.x - gunner_pos.x, target_pos.y - gunner_pos.y))


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
    _dbg(f"LOS→core: from ({gunner_pos.x},{gunner_pos.y}) facing {facing}")
    for tile in _firing_line(gunner_pos, facing):
        if not on_map(tile, mm.width, mm.height):
            _dbg(f"  ({tile.x},{tile.y}) OFFMAP → block")
            return False

        env = mm.get_tile(tile)
        _dbg(f"  ({tile.x},{tile.y}) env={env}")
        if env == Environment.WALL:
            _dbg(f"  ({tile.x},{tile.y}) WALL → block")
            return False

        building = mm.get_building(tile)
        if building is not None:
            _dbg(f"  ({tile.x},{tile.y}) building={building.entity_type} team={building.team}")
            if building.entity_type == EntityType.CORE and building.team == enemy_team:
                _dbg(f"  ({tile.x},{tile.y}) ENEMY CORE → hit")
                return True
            # Our own building (except roads) blocks — we don't want to shoot our stuff
            if building.team == my_team and building.entity_type != EntityType.ROAD:
                _dbg(f"  ({tile.x},{tile.y}) own non-road → block")
                return False

    _dbg("  no core on ray")
    return False


def _has_clear_line_to_pos(
    mm: MapManager, gunner_pos: Position, facing: Direction, target_pos: Position, my_team
) -> bool:
    """Check if a gunner at gunner_pos facing direction can hit target_pos.
    Walks the firing line, ignoring builder bots. Only walls and non-road ally buildings block.
    """
    _dbg(f"LOS→pos: from ({gunner_pos.x},{gunner_pos.y}) facing {facing} target ({target_pos.x},{target_pos.y})")
    for tile in _firing_line(gunner_pos, facing):
        if not on_map(tile, mm.width, mm.height):
            _dbg(f"  ({tile.x},{tile.y}) OFFMAP → block")
            return False

        env = mm.get_tile(tile)
        _dbg(f"  ({tile.x},{tile.y}) env={env}")
        if env == Environment.WALL:
            _dbg(f"  ({tile.x},{tile.y}) WALL → block")
            return False

        if tile.x == target_pos.x and tile.y == target_pos.y:
            _dbg(f"  ({tile.x},{tile.y}) matches target → hit")
            return True

        building = mm.get_building(tile)
        if building is not None:
            _dbg(f"  ({tile.x},{tile.y}) building={building.entity_type} team={building.team}")
            if building.team == my_team and building.entity_type != EntityType.ROAD:
                _dbg(f"  ({tile.x},{tile.y}) own non-road → block")
                return False

    _dbg("  target not on ray")
    return False


# ── State class ─────────────────────────────────────────────────────


class BuildGunnerState:
    def __init__(self, ct, brain) -> None:
        self.brain = brain
        self.target_pos: Position | None = None
        self.target_dir: Direction | None = None
        self.attempt_start: int | None = None

    def _is_buildable(self, ct, mm: MapManager, pos: Position) -> bool:
        return is_buildable_spot(ct, mm, pos)

    def _resolve_enemy_team(self, mm: MapManager):
        """Resolve enemy team from visible core tiles."""
        for core_pos in mm.nearby_enemy_core_pos:
            b = mm.get_building(core_pos)
            if b is not None and b.entity_type == EntityType.CORE:
                return b.team
        return None

    def _enemy_infra_targets(self, ct, mm: MapManager) -> list[Position]:
        """Collect positions of any enemy building cardinally adjacent to a nearby harvester."""
        team = ct.get_team()
        targets: list[Position] = []
        for _, adj in mm.nearby_harvester_card_pos + mm.nearby_harvester_enemy_card_pos:
            building = mm.get_building(adj)
            if building is not None and building.team != team:
                targets.append(adj)
        return targets

    def _find_gunner_spot(self, ct, mm: MapManager, my_pos: Position):
        """Find the best spot to build a gunner next to a harvester.
        Priority 1: core pressure (line of sight to enemy core).
        Priority 2: turret sniping (line of sight to enemy turret).
        Priority 3: infra sniping (line of sight to any non-turret enemy building).
        """
        has_core = bool(mm.nearby_enemy_core_pos)
        has_turrets = bool(mm.nearby_enemy_turret_pos)

        enemy_team = self._resolve_enemy_team(mm) if has_core else None
        infra_targets = self._enemy_infra_targets(ct, mm)
        has_infra = bool(infra_targets)

        best_core = None
        best_core_dist = float("inf")
        best_turret = None
        best_turret_dist = float("inf")
        best_infra = None
        best_infra_dist = float("inf")


        _dbg(f"find_spot: my_pos=({my_pos.x},{my_pos.y}) has_core={has_core} has_turrets={has_turrets} has_infra={has_infra} enemy_team={enemy_team}")

        for harvester_pos, adj in mm.nearby_harvester_card_pos + mm.nearby_harvester_enemy_card_pos:
            _dbg(f"  harv=({harvester_pos.x},{harvester_pos.y}) adj=({adj.x},{adj.y})")
            if SKIP_AXIONITE_HARVESTERS and mm.get_tile(harvester_pos) == Environment.ORE_AXIONITE:
                _dbg("    skip: axionite")
                continue

            if mm.harvester_gunner_count.get((harvester_pos.x, harvester_pos.y), 0) >= MAX_GUNNERS_PER_HARVESTER:
                _dbg("    skip: saturated")
                continue

            if not self._is_buildable(ct, mm, adj):
                _dbg("    skip: not buildable")
                continue

            dist = my_pos.distance_squared(adj)

            # Priority 1: core pressure
            if has_core and enemy_team is not None and dist < best_core_dist:
                if any(adj.distance_squared(cp) <= 25 for cp in mm.nearby_enemy_core_pos):
                    _dbg(f"    core-range OK, picking facing for adj=({adj.x},{adj.y})")
                    facing = self._pick_facing_for_core(ct, mm, adj, enemy_team)
                    if facing is not None and adj.add(facing) != harvester_pos:
                        _dbg(f"    CORE candidate: adj=({adj.x},{adj.y}) facing={facing} dist={dist}")
                        best_core_dist = dist
                        best_core = (adj, facing)
                        continue
                    else:
                        _dbg(f"    core facing rejected (facing={facing})")

            # Priority 2: turret sniping
            if has_turrets and dist < best_turret_dist:
                _dbg(f"    picking turret facing for adj=({adj.x},{adj.y})")
                facing = self._pick_facing_for_turret(ct, mm, adj, harvester_pos)
                if facing is not None:
                    _dbg(f"    TURRET candidate: adj=({adj.x},{adj.y}) facing={facing} dist={dist}")
                    best_turret_dist = dist
                    best_turret = (adj, facing)
                    continue
                else:
                    _dbg("    turret facing rejected")

            # Priority 3: infra sniping
            if has_infra and dist < best_infra_dist:
                _dbg(f"    picking infra facing for adj=({adj.x},{adj.y})")
                facing = self._pick_facing_for_infra(ct, mm, adj, harvester_pos, infra_targets)
                if facing is not None:
                    _dbg(f"    INFRA candidate: adj=({adj.x},{adj.y}) facing={facing} dist={dist}")
                    best_infra_dist = dist
                    best_infra = (adj, facing)
                else:
                    _dbg("    infra facing rejected")

        # Core > turret > infra
        if best_core is not None:
            _dbg(f"find_spot result (CORE): {best_core}")
            return best_core
        if best_turret is not None:
            _dbg(f"find_spot result (TURRET): {best_turret}")
            return best_turret
        _dbg(f"find_spot result (INFRA): {best_infra}")
        return best_infra

    def _pick_facing_for_core(
        self, ct, mm: MapManager, gunner_pos: Position, enemy_team
    ) -> Direction | None:
        team = ct.get_team()
        ref_core = mm.spotted_enemy_core_pos or mm.nearby_enemy_core_pos[0]
        toward_core = gunner_pos.direction_to(ref_core)
        best_first = _snap_to_cardinal(toward_core)
        _dbg(f"pick_core: gunner=({gunner_pos.x},{gunner_pos.y}) ref_core=({ref_core.x},{ref_core.y}) toward={toward_core} first={best_first}")

        if _has_clear_line_to_core(mm, gunner_pos, best_first, enemy_team, team):
            _dbg(f"pick_core: picked {best_first}")
            return best_first
        for d in DIRECTIONS:
            if d == best_first or d == Direction.CENTRE:
                continue
            if _has_clear_line_to_core(mm, gunner_pos, d, enemy_team, team):
                _dbg(f"pick_core: picked fallback {d}")
                return d
        _dbg("pick_core: no direction works")
        return None

    def _pick_facing_for_turret(
        self, ct, mm: MapManager, gunner_pos: Position, harvester_pos: Position
    ) -> Direction | None:
        team = ct.get_team()
        _dbg(f"pick_turret: gunner=({gunner_pos.x},{gunner_pos.y}) turrets={[(p.x,p.y) for p in mm.nearby_enemy_turret_pos]}")
        for turret_pos in mm.nearby_enemy_turret_pos:
            building = mm.get_building(turret_pos)
            if building is None or building.entity_type not in TARGETABLE_TURRET_TYPES:
                _dbg(f"  skip turret ({turret_pos.x},{turret_pos.y}): not targetable ({building.entity_type if building else None})")
                continue
            d = _firing_dir_to(gunner_pos, turret_pos)
            _dbg(f"  turret=({turret_pos.x},{turret_pos.y}) firing_dir={d}")
            if d is None or gunner_pos.add(d) == harvester_pos:
                continue
            if not _has_clear_line_to_pos(mm, gunner_pos, d, turret_pos, team):
                _dbg(f"  turret=({turret_pos.x},{turret_pos.y}) LOS blocked")
                continue
            _dbg(f"pick_turret: picked {d}")
            return d
        _dbg("pick_turret: no direction works")
        return None

    def _pick_facing_for_infra(
        self, ct, mm: MapManager, gunner_pos: Position, harvester_pos: Position, targets: list[Position]
    ) -> Direction | None:
        team = ct.get_team()
        _dbg(f"pick_infra: gunner=({gunner_pos.x},{gunner_pos.y}) targets={[(p.x,p.y) for p in targets]}")
        for target_pos in targets:
            d = _firing_dir_to(gunner_pos, target_pos)
            _dbg(f"  target=({target_pos.x},{target_pos.y}) firing_dir={d}")
            if d is None or gunner_pos.add(d) == harvester_pos:
                continue
            if not _has_clear_line_to_pos(mm, gunner_pos, d, target_pos, team):
                _dbg(f"  target=({target_pos.x},{target_pos.y}) LOS blocked")
                continue
            _dbg(f"pick_infra: picked {d}")
            return d
        _dbg("pick_infra: no direction works")
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

        # Check if we still hit a targetable turret (with LOS)
        for turret_pos in mm.nearby_enemy_turret_pos:
            building = mm.get_building(turret_pos)
            if building is None or building.entity_type not in TARGETABLE_TURRET_TYPES:
                continue
            if _firing_dir_to(self.target_pos, turret_pos) != self.target_dir:
                continue
            if _has_clear_line_to_pos(mm, self.target_pos, self.target_dir, turret_pos, team):
                return True

        # Check if we still hit any non-turret enemy building (with LOS)
        for target_pos in self._enemy_infra_targets(ct, mm):
            if _firing_dir_to(self.target_pos, target_pos) != self.target_dir:
                continue
            if _has_clear_line_to_pos(mm, self.target_pos, self.target_dir, target_pos, team):
                return True

        return False

    @cputimer
    def determine(self, ct, state_manager):
        mm = self.brain.map_manager

        cost = ct.get_gunner_cost()[0] + ct.get_road_cost()[0]
        resources = ct.get_global_resources()[0]
        if resources < cost:
            self._clear()
            return False

        # Keep current target if still valid
        if self.target_pos is not None:
            if self._is_target_valid(ct, mm):
                state_manager.current_state = BuilderState.BUILD_GUNNER
                return True

        # Nothing to shoot at
        if (
            not mm.nearby_enemy_core_pos
            and not mm.nearby_enemy_turret_pos
            and not self._enemy_infra_targets(ct, mm)
        ):
            self._clear()
            return False

        my_pos = ct.get_position()

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
            target_dir = self.target_dir
            built = handle_on_build_tile(
                ct, mm, self.target_pos,
                lambda p: ct.can_build_gunner(p, target_dir),
                lambda p: ct.build_gunner(p, target_dir),
            )
            if built:
                self._clear()
            return

        # Adjacent — clear blocker and build
        if my_pos.distance_squared(self.target_pos) <= ACTION_RADIUS_SQ:
            building = mm.get_building(self.target_pos)
            if building is not None and building.team == ct.get_team() and is_destroyable_blocker(mm, self.target_pos, building):
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            if ct.can_build_gunner(self.target_pos, self.target_dir):
                ct.build_gunner(self.target_pos, self.target_dir)
                self._clear()
                return

        # Walk toward target
        path_to_build_spot(ct, mm, self.brain.pathing, self.target_pos)

    def _clear(self):
        self.target_pos = None
        self.target_dir = None
        self.attempt_start = None
