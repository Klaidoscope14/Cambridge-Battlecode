from abc import ABC, abstractmethod

from cambc import EntityType, Environment, Position, Direction

from helpers.directions import CARDINAL, DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager
from nav.common import common_path

# ── Shared constants ───────────────────────────────────────────────

ACTION_RADIUS_SQ = 2
SOURCE_COOLDOWN = 120
MAX_ATTEMPT_ROUNDS = 30

# ── Shared helpers ─────────────────────────────────────────────────


def is_slot_still_valid(ct, mm: MapManager, build_pos: Position) -> bool:
    """Return True if build_pos is still a tile we can build a sentinel on."""
    team = ct.get_team()
    if not on_map(build_pos, mm.width, mm.height):
        return False
    tile = mm.get_tile(build_pos)
    if tile is None:
        return False
    if tile in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
        return False
    building = mm.get_building(build_pos)
    if building is None:
        return True
    if building.team != team:
        return False
    return building.entity_type in (EntityType.ROAD, EntityType.MARKER)


def best_stand_tile(ct, mm: MapManager, target: Position, my_pos: Position) -> Position:
    """Return the best adjacent tile to stand on while building."""
    best = None
    best_dist = float("inf")
    for d in DIRECTIONS:
        adj = target.add(d)
        if not on_map(adj, mm.width, mm.height):
            continue
        tile = mm.get_tile(adj)
        if tile is None:
            continue
        if tile in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            continue
        dist = my_pos.distance_squared(adj)
        if dist < best_dist:
            best_dist = dist
            best = adj
    return best if best is not None else target


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) <= ACTION_RADIUS_SQ


def find_build_slot_cardinal(
    ct, mm: MapManager, source_pos: Position, face_toward_source: bool
) -> tuple[Position, Direction] | None:
    """Default build-slot finder: pick the closest cardinal-adjacent empty tile.

    If face_toward_source is True, the turret faces the source (offensive).
    Otherwise it faces outward (defensive).
    """
    team = ct.get_team()
    best = None
    best_dist = float("inf")
    my_pos = ct.get_position()

    for d in CARDINAL:
        candidate = source_pos.add(d)
        if not on_map(candidate, mm.width, mm.height):
            continue
        tile = mm.get_tile(candidate)
        if tile is None:
            continue
        if tile in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            continue
        building = mm.get_building(candidate)
        if building is not None:
            if building.team != team:
                continue
            if building.entity_type not in (EntityType.ROAD, EntityType.MARKER):
                continue

        if face_toward_source:
            facing = candidate.direction_to(source_pos)
        else:
            facing = source_pos.direction_to(candidate)

        dist = my_pos.distance_squared(candidate)
        if dist < best_dist:
            best_dist = dist
            best = (candidate, facing)

    return best


# ── Base class ─────────────────────────────────────────────────────


class BuildTurretBase(ABC):
    """Abstract base for all 'camp-then-build-turret' states.

    Subclasses must implement the four hook methods below.
    Everything else — movement, camping, step-off-and-build, cooldowns,
    timeout, slot revalidation — is handled here.
    """

    def __init__(self, ct, brain) -> None:
        self.ct = ct
        self.brain = brain

        self.source_pos: Position | None = None
        self.build_pos: Position | None = None
        self.build_dir: Direction | None = None
        self.stand_pos: Position | None = None
        self.attempt_start: int | None = None

        self.cooldowns: dict[tuple[int, int], int] = {}

    # ── Hook methods (override these) ──────────────────────────────

    @abstractmethod
    def _find_best_source(
        self, ct, mm: MapManager, my_pos: Position, current_round: int
    ) -> Position | None:
        """Scan visible tiles and return the best target position, or None."""
        ...

    @abstractmethod
    def _is_valid_source(
        self, ct, mm: MapManager, pos: Position, current_round: int
    ) -> bool:
        """Return True if pos is still a valid target to turret-up next to."""
        ...

    @abstractmethod
    def _choose_facing(self, ct, mm: MapManager) -> Direction:
        """Pick the sentinel's facing direction given self.build_pos / source_pos."""
        ...

    def _find_build_slot(
        self, ct, mm: MapManager, source_pos: Position
    ) -> tuple[Position, Direction] | None:
        """Find where to place the turret. Override for non-default logic.

        Default: cardinal-adjacent, turret faces outward.
        """
        return find_build_slot_cardinal(ct, mm, source_pos, face_toward_source=False)

    # ── Cooldown helpers ───────────────────────────────────────────

    def _is_source_on_cooldown(self, pos: Position, current_round: int) -> bool:
        key = (pos.x, pos.y)
        if key not in self.cooldowns:
            return False
        return current_round - self.cooldowns[key] <= SOURCE_COOLDOWN

    def _cooldown_source(self, pos: Position, current_round: int) -> None:
        self.cooldowns[(pos.x, pos.y)] = current_round

    # ── Core tick (not meant to be overridden) ─────────────────────

    def execute(self, ct) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        current_round = ct.get_current_round()

        # Expire old cooldowns
        expired = [k for k, r in self.cooldowns.items() if current_round - r > SOURCE_COOLDOWN]
        for k in expired:
            del self.cooldowns[k]

        # Check attempt timeout
        if (
            self.source_pos is not None
            and self.attempt_start is not None
            and current_round - self.attempt_start > MAX_ATTEMPT_ROUNDS
        ):
            self._cooldown_source(self.source_pos, current_round)
            self._clear_target()
            return False

        # Validate current target
        if self.source_pos is not None:
            if not self._is_valid_source(ct, mm, self.source_pos, current_round):
                self._clear_target()
            elif self.build_pos is not None and not is_slot_still_valid(ct, mm, self.build_pos):
                slot = self._find_build_slot(ct, mm, self.source_pos)
                if slot is None:
                    self._cooldown_source(self.source_pos, current_round)
                    self._clear_target()
                else:
                    self.build_pos, self.build_dir = slot
                    self.stand_pos = best_stand_tile(ct, mm, self.build_pos, my_pos)

        # Pick new target if needed
        if self.source_pos is None:
            source = self._find_best_source(ct, mm, my_pos, current_round)
            if source is None:
                return False
            slot = self._find_build_slot(ct, mm, source)
            if slot is None:
                return False
            self.source_pos = source
            self.build_pos, self.build_dir = slot
            self.stand_pos = best_stand_tile(ct, mm, self.build_pos, my_pos)
            self.attempt_start = current_round

        if self.build_pos is None:
            return False

        on_build_tile = (my_pos.x == self.build_pos.x and my_pos.y == self.build_pos.y)

        if on_build_tile:
            self.stand_pos = best_stand_tile(ct, mm, self.build_pos, my_pos)
            result = self._step_off_and_build(ct, mm, current_round)
            if result:
                return True
            if ct.can_build_road(self.build_pos):
                ct.build_road(self.build_pos)
            return False

        dist_sq = my_pos.distance_squared(self.build_pos)
        if 1 <= dist_sq <= ACTION_RADIUS_SQ:
            return self._try_build(ct, mm, current_round)

        common_path(ct, mm, self.brain.pathing, self.build_pos)
        return False

    # ── Build mechanics (shared) ───────────────────────────────────

    def _step_off_and_build(self, ct, mm: MapManager, current_round: int) -> bool:
        if ct.get_action_cooldown() > 0 or ct.get_move_cooldown() > 0:
            return False

        building = mm.get_building(self.build_pos)
        if building is not None and building.team == ct.get_team():
            if building.entity_type in (EntityType.ROAD, EntityType.MARKER):
                if ct.can_destroy(self.build_pos):
                    ct.destroy(self.build_pos)

        stand = self.stand_pos
        if stand is None:
            return False
        step_dir = self.build_pos.direction_to(stand)
        if not ct.can_move(step_dir):
            return False
        ct.move(step_dir)

        facing = self._choose_facing(ct, mm)
        if ct.can_build_sentinel(self.build_pos, facing):
            ct.build_sentinel(self.build_pos, facing)
            self._clear_target()
            return True
        return False

    def _try_build(self, ct, mm: MapManager, current_round: int) -> bool:
        pos = self.build_pos
        building = mm.get_building(pos)
        if building is not None and building.team == ct.get_team():
            if building.entity_type in (EntityType.ROAD, EntityType.MARKER):
                if ct.can_destroy(pos):
                    ct.destroy(pos)

        facing = self._choose_facing(ct, mm)
        if ct.can_build_sentinel(pos, facing):
            ct.build_sentinel(pos, facing)
            self._clear_target()
            return True
        return False

    # ── State management ───────────────────────────────────────────

    def _clear_target(self) -> None:
        self.source_pos = None
        self.build_pos = None
        self.build_dir = None
        self.stand_pos = None
        self.attempt_start = None

    def has_target(self) -> bool:
        return self.source_pos is not None

    def reset(self, ct=None) -> None:
        self._clear_target()