"""
Connector: chains an existing bridge position back to the core.

No longer handles source-adjacent slot finding — that's CoreConnectState's job.
The Connector's only responsibility is: given a frontier bridge position,
build a chain of bridges from there to a core tile.
"""
from dataclasses import dataclass, field

from cambc import Controller, EntityType, Position

from vision.storage_tracker import StorageTracker
from helpers.directions import CARDINAL, DIRECTIONS
from helpers.geometry import step_distance
from roles.builder.helpers import in_bounds
from map.map_manager import MapManager
from vision.vision_manager import VisionManager


BRIDGE_REPLACEABLE_TYPES = [
    EntityType.MARKER,
    EntityType.ROAD,
    EntityType.CONVEYOR,
]

MAX_BRIDGE_RANGE_SQ = 9
MIN_BRIDGE_SPACING_SQ = 2


# ---------------------------------------------------------------------------
# Standalone helpers (usable without a Connector instance)
# ---------------------------------------------------------------------------

def find_baseline(
    ct: Controller,
    map_manager: MapManager,
    vision_manager: VisionManager,
    storage_tracker: StorageTracker | None,
    reference_pos: Position,
    chain: set[tuple[int, int]] | None = None,
) -> Position | None:
    """Find the nearest core tile or ally bridge to aim toward."""
    if chain is None:
        chain = set()
    core = map_manager.ally_core_pos
    candidates: list[Position] = []
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            tile = Position(core.x + dx, core.y + dy)
            if in_bounds(ct, tile):
                candidates.append(tile)

    # Also include visible ally bridges
    team = ct.get_team()
    for bridge_pos, bridge in vision_manager.get_bridges(ct):
        if bridge.team == team:
            if storage_tracker is not None and storage_tracker.is_full(bridge.id):
                continue
            candidates.append(bridge_pos)

    # Add core perimeter (non-wall)
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            pos = Position(core.x + dx, core.y + dy)
            if not in_bounds(ct, pos):
                continue
            if map_manager.has_wall(pos):
                continue
            candidates.append(pos)

    best = None
    for pos in candidates:
        if (pos.x, pos.y) in chain:
            continue
        if colliding_core_bridges(reference_pos, pos):
            continue
        if best is None or reference_pos.distance_squared(pos) < reference_pos.distance_squared(best):
            best = pos
    return best


def try_build_bridge(
    ct: Controller,
    map_manager: MapManager,
    bridge_pos: Position,
    target_pos: Position,
    replaceable_types=None,
) -> bool:
    """Attempt to build a bridge at bridge_pos pointing to target_pos.

    Destroys a replaceable building first if necessary.
    *replaceable_types* defaults to BRIDGE_REPLACEABLE_TYPES if not given.
    """
    if replaceable_types is None:
        replaceable_types = BRIDGE_REPLACEABLE_TYPES

    if ct.get_action_cooldown() != 0:
        return False
    if ct.get_global_resources()[0] < ct.get_bridge_cost()[0]:
        return False

    building = map_manager.get_building(bridge_pos)
    if building is not None:
        if building.entity_type in replaceable_types and ct.can_destroy(bridge_pos):
            ct.destroy(bridge_pos)

    if ct.can_build_bridge(bridge_pos, target_pos):
        ct.build_bridge(bridge_pos, target_pos)
        return True
    return False


# ---------------------------------------------------------------------------
# Bridge utilities
# ---------------------------------------------------------------------------

def colliding_core_bridges(a: Position, b: Position) -> bool:
    """True if two bridges at a and b would be adjacent (dist² <= 2)."""
    return a.distance_squared(b) <= 2


def is_bridge_replaceable(ct, map_manager, pos) -> bool:
    """True if pos has no building, a marker, or an ally building
    whose type is in BRIDGE_REPLACEABLE_TYPES."""
    building = map_manager.get_building(pos)
    if building is None:
        return True
    if building.entity_type == EntityType.MARKER:
        return True
    if building.team == ct.get_team():
        return building.entity_type in BRIDGE_REPLACEABLE_TYPES
    return False


def has_adjacent_ally_bridge(ct, pos, map_manager) -> bool:
    """True if an ally bridge exists in the 4 cardinal tiles around *pos*."""
    team = ct.get_team()
    for d in CARDINAL:
        neighbor = pos.add(d)
        if not in_bounds(ct, neighbor):
            continue
        building = map_manager.get_building(neighbor)
        if (
            building is not None
            and building.entity_type == EntityType.BRIDGE
            and building.team == team
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Bridge-position validators
# ---------------------------------------------------------------------------

def is_passable_terrain(ct, map_manager, pos) -> bool:
    return in_bounds(ct, pos) and not map_manager.has_wall(pos)


def is_far_from_core(map_manager, pos) -> bool:
    return step_distance(map_manager.ally_core_pos, pos) > 2


def _has_adjacent_source(ct, map_manager, pos) -> bool:
    """True if a harvester or foundry owned by our team is adjacent to pos."""
    team = ct.get_team()
    for d in CARDINAL:
        neighbor = pos.add(d)
        if not in_bounds(ct, neighbor):
            continue
        building = map_manager.get_building(neighbor)
        if (
            building is not None
            and building.team == team
            and building.entity_type in (EntityType.HARVESTER, EntityType.FOUNDRY)
        ):
            return True
    return False


def has_no_adjacent_ally_bridge(ct, map_manager, pos, allow_near_source=False) -> bool:
    if allow_near_source and _has_adjacent_source(ct, map_manager, pos):
        return True
    for d in DIRECTIONS:
        neighbor = pos.add(d)
        if not in_bounds(ct, neighbor):
            continue
        building = map_manager.get_building(neighbor)
        if (
            building is not None
            and building.entity_type == EntityType.BRIDGE
            and building.team == ct.get_team()
        ):
            return False
    return True


def has_no_ore(map_manager, pos) -> bool:
    return not map_manager.has_ore(pos)


def is_valid_bridge_pos(ct, map_manager, pos, allow_near_source=False) -> bool:
    return (
        is_passable_terrain(ct, map_manager, pos)
        and has_no_ore(map_manager, pos)
        and is_far_from_core(map_manager, pos)
        and has_no_adjacent_ally_bridge(ct, map_manager, pos, allow_near_source=allow_near_source)
        and is_bridge_replaceable(ct, map_manager, pos)
    )


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

@dataclass
class ChainProgress:
    frontier: Position
    baseline: Position | None = None
    connected: bool = False
    chain_positions: set[tuple[int, int]] = field(default_factory=set)
    last_placed: Position | None = None


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class Connector:
    def __init__(self, ct: Controller, map_manager: MapManager, vision_manager: VisionManager, storage_tracker: StorageTracker):
        self.ct = ct
        self.map_manager = map_manager
        self.vision_manager = vision_manager
        self.storage_tracker = storage_tracker
        self._progress: dict[tuple[int, int], ChainProgress] = {}

    # -- Public API ---------------------------------------------------------

    def connect(self, ct: Controller, frontier_pos: Position) -> bool:
        """Advance the bridge chain from *frontier_pos* toward core by one step.

        *frontier_pos* is the current head of the chain (an existing bridge or
        the position where the next bridge should be placed).

        Returns True when the chain reaches a core tile.
        """
        progress = self._get_or_create(frontier_pos)

        if progress.connected:
            return True

        frontier = progress.frontier

        # Check if an ally bridge appeared at frontier (placed externally)
        if not is_bridge_replaceable(ct, self.map_manager, frontier):
            building = self.map_manager.get_building(frontier)
            if (
                building is not None
                and building.entity_type == EntityType.BRIDGE
                and building.team == ct.get_team()
            ):
                progress.chain_positions.add((frontier.x, frontier.y))
                # Re-check: can we now reach core directly?
                progress.baseline = self._find_baseline(ct, frontier, progress.chain_positions)

        if progress.baseline is None:
            progress.baseline = self._find_baseline(ct, frontier, progress.chain_positions)
            if progress.baseline is None:
                return False

        chain = progress.chain_positions

        # Try to bridge directly to a core tile/existing bridge
        direct = self._find_direct_target(ct, frontier, progress.baseline, chain, progress.last_placed)
        if direct is not None:
            if self._try_build_bridge(ct, frontier, direct):
                chain.add((frontier.x, frontier.y))
                progress.last_placed = frontier
                progress.connected = True
            return progress.connected

        # Otherwise, place the next intermediate bridge
        next_slot = self._find_next_slot_toward(ct, frontier, progress.baseline, chain)
        if next_slot is None:
            return False

        if self._try_build_bridge(ct, frontier, next_slot):
            chain.add((frontier.x, frontier.y))
            progress.last_placed = frontier
            progress.frontier = next_slot

        return progress.connected

    def is_connected(self, pos: Position) -> bool:
        key = (pos.x, pos.y)
        progress = self._progress.get(key)
        return progress is not None and progress.connected

    def get_frontier(self, pos: Position) -> Position | None:
        key = (pos.x, pos.y)
        progress = self._progress.get(key)
        return progress.frontier if progress is not None else None

    def reset(self, pos: Position):
        key = (pos.x, pos.y)
        self._progress.pop(key, None)

    # -- Progress management ------------------------------------------------

    def _get_or_create(self, frontier_pos: Position) -> ChainProgress:
        key = (frontier_pos.x, frontier_pos.y)
        if key not in self._progress:
            self._progress[key] = ChainProgress(frontier=frontier_pos)
        return self._progress[key]

    # -- Target selection ---------------------------------------------------

    def _find_direct_target(
        self,
        ct: Controller,
        from_pos: Position,
        baseline: Position,
        chain: set[tuple[int, int]],
        last_placed: Position | None = None,
    ) -> Position | None:
        """Find the best target within bridge range of from_pos.

        Priority:
        1. Direct core tile (3×3 footprint) — nearest eligible.
        2. Non-full bridge — nearest eligible (excluding last_placed to
           prevent chaining back to the most recently built bridge).
        """
        core = self.map_manager.ally_core_pos

        best_core = None
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                core_tile = Position(core.x + dx, core.y + dy)
                if (core_tile.x, core_tile.y) in chain:
                    continue
                if not in_bounds(ct, core_tile):
                    continue
                if from_pos.distance_squared(core_tile) > MAX_BRIDGE_RANGE_SQ:
                    continue
                if colliding_core_bridges(from_pos, core_tile):
                    continue
                if best_core is None or from_pos.distance_squared(core_tile) < from_pos.distance_squared(best_core):
                    best_core = core_tile

        if best_core is not None:
            return best_core

        best_other = None
        for pos in self._gather_bridge_targets(ct):
            if (pos.x, pos.y) in chain:
                continue
            # Skip the most recently placed bridge to avoid chaining backward
            if last_placed is not None and pos.x == last_placed.x and pos.y == last_placed.y:
                continue
            if from_pos.distance_squared(pos) > MAX_BRIDGE_RANGE_SQ:
                continue
            if colliding_core_bridges(from_pos, pos):
                continue
            if best_other is None or from_pos.distance_squared(pos) < from_pos.distance_squared(best_other):
                best_other = pos

        return best_other

    def _find_baseline(
        self, ct: Controller, reference_pos: Position,
        chain: set[tuple[int, int]],
    ) -> Position | None:
        return find_baseline(
            ct, self.map_manager, self.vision_manager,
            self.storage_tracker, reference_pos, chain,
        )

    def _gather_bridge_targets(self, ct: Controller) -> list[Position]:
        """Collect all ally bridges + core perimeter positions (3×3 around core)."""
        core = self.map_manager.ally_core_pos
        targets: list[Position] = []

        for dx in range(-1, 2):
            for dy in range(-1, 2):
                pos = Position(core.x + dx, core.y + dy)
                if not in_bounds(ct, pos):
                    continue
                if self.map_manager.has_wall(pos):
                    continue
                targets.append(pos)

        team = ct.get_team()
        for bridge_pos, bridge in self.vision_manager.get_bridges(ct):
            if bridge.team == team:
                if self.storage_tracker is not None and self.storage_tracker.is_full(bridge.id):
                    continue
                targets.append(bridge_pos)
        return targets

    def _is_position_full(self, pos: Position) -> bool:
        if self.storage_tracker is None:
            return False
        building = self.map_manager.get_building(pos)
        if building is None or building.entity_type != EntityType.BRIDGE:
            return False
        return self.storage_tracker.is_full(building.id)

    def _is_position_empty(self, pos: Position) -> bool:
        if self.storage_tracker is None:
            return False
        building = self.map_manager.get_building(pos)
        if building is None or building.entity_type != EntityType.BRIDGE:
            return False
        return self.storage_tracker.is_empty(building.id)

    # -- Bridge placement ---------------------------------------------------

    def _find_next_slot_toward(
        self,
        ct: Controller,
        frontier: Position,
        baseline: Position,
        chain: set[tuple[int, int]],
    ) -> Position | None:
        """Pick the best next bridge position in the chain toward baseline."""
        candidates = []
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                dist_sq = dx * dx + dy * dy
                if dist_sq < MIN_BRIDGE_SPACING_SQ or dist_sq > MAX_BRIDGE_RANGE_SQ:
                    continue
                candidate = Position(frontier.x + dx, frontier.y + dy)
                if (candidate.x, candidate.y) in chain:
                    continue
                if not is_valid_bridge_pos(ct, self.map_manager, candidate):
                    continue
                candidates.append(candidate)

        if not candidates:
            return None

        frontier_to_baseline = frontier.distance_squared(baseline)
        forward = [
            c for c in candidates
            if c.distance_squared(baseline) < frontier_to_baseline
        ]
        pool = forward if forward else candidates

        pool.sort(key=lambda c: (
            c.distance_squared(baseline),
            -c.distance_squared(frontier),
        ))

        return pool[0]

    def _try_build_bridge(
        self,
        ct: Controller,
        bridge_pos: Position,
        target_pos: Position,
    ) -> bool:
        """Attempt to build a bridge at bridge_pos pointing to target_pos.
        Destroys a replaceable building first if necessary."""
        return try_build_bridge(ct, self.map_manager, bridge_pos, target_pos)