"""CleanTurretState – destroy ally turrets blocking a harvester's feed path.

Targets ally turrets sitting on a cardinal neighbour of a harvester that has
no ally feed infrastructure (conveyor or bridge) on any of its cardinal
neighbours — i.e. the turret is occupying the only spot a feed could be
hooked into.

(The "ally turret directly on an ore" case is handled by BuildHarvesterState
itself, which can now consider such ores as reclaimable targets.)

Only activates when it has been safe for SAFE_ROUNDS rounds (no enemy
builder spotted recently), so we don't tear down defences mid-fight.
"""

from cambc import Controller, EntityType, Environment, Position

from debug.profiling import cputimer
from helpers.directions import CARDINAL
from helpers.geometry import on_map
from map.map_manager import MapManager
from nav.common import common_path
from states.builder_state import BuilderState

# ── Constants ────────────────────────────────────────────────────────

ACTION_RADIUS_SQ = 2

ORE_TYPES = {
    Environment.ORE_TITANIUM,
    Environment.ORE_AXIONITE,
}

TURRET_TYPES = {
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
}

HARVESTER_FEED_TYPES = {
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
}

SAFE_ROUNDS = 30
MIN_TURRET_AGE = 30


# ── Helpers ──────────────────────────────────────────────────────────


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) <= ACTION_RADIUS_SQ


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


# ── State ─────────────────────────────────────────────────────────────


class CleanTurretState:
    """Find and destroy ally turrets blocking a harvester's feed path."""

    def __init__(self, ct: Controller, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None  # position of the turret to destroy
        self._turret_first_seen: dict[Position, int] = {}  # pos → round first observed

    # ── Safety ───────────────────────────────────────────────────────

    def _is_safe(self, current_round: int) -> bool:
        last_seen = self.brain.map_manager.last_enemy_builder_seen_round
        return last_seen is None or current_round - last_seen > SAFE_ROUNDS

    # ── Target search ────────────────────────────────────────────────

    def _harvester_has_feed(self, mm: MapManager, harvester_pos: Position, team) -> bool:
        """True if any cardinal neighbour of the harvester is an ally conveyor or bridge."""
        for d in CARDINAL:
            adj = harvester_pos.add(d)
            if not on_map(adj, mm.width, mm.height):
                continue
            b = mm.get_building(adj)
            if b is not None and b.team == team and b.entity_type in HARVESTER_FEED_TYPES:
                return True
        return False

    def _record_and_check_age(self, pos: Position, current_round: int) -> bool:
        """Record first time we see a turret at pos; return True if old enough."""
        if pos not in self._turret_first_seen:
            self._turret_first_seen[pos] = current_round
        return current_round - self._turret_first_seen[pos] >= MIN_TURRET_AGE

    def _find_target(self, ct: Controller, mm: MapManager, my_pos: Position, current_round: int) -> Position | None:
        """Return position of the closest qualifying ally turret."""
        team = ct.get_team()
        best_pos: Position | None = None
        best_dist = float("inf")

        for ore_pos in mm.known_ore_positions:
            tile = mm.get_tile(ore_pos)
            if tile is None or tile not in ORE_TYPES:
                continue

            # Look for an ally turret beside a harvester that has no feed
            # infrastructure on any of its cardinal neighbours.
            harvester = mm.get_building(ore_pos)
            if harvester is None or harvester.entity_type != EntityType.HARVESTER:
                continue
            if self._harvester_has_feed(mm, ore_pos, team):
                continue
            for d in CARDINAL:
                adj = ore_pos.add(d)
                if not on_map(adj, mm.width, mm.height):
                    continue
                adj_building = mm.get_building(adj)
                if (
                    adj_building is not None
                    and adj_building.team == team
                    and adj_building.entity_type in TURRET_TYPES
                    and self._record_and_check_age(adj, current_round)
                ):
                    dist = manhattan(adj, my_pos)
                    if dist < best_dist:
                        best_dist = dist
                        best_pos = adj

        return best_pos

    # ── Core tick ────────────────────────────────────────────────────

    @cputimer
    def execute(self, ct: Controller) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        # Validate target still exists
        if self.target is not None:
            building = mm.get_building(self.target)
            if building is None or building.entity_type not in TURRET_TYPES:
                self.target = None

        if self.target is None:
            return False

        if in_action_range(my_pos, self.target):
            if ct.can_destroy(self.target):
                ct.destroy(self.target)
            return False

        common_path(ct, mm, self.brain.pathing, self.target)
        return False

    # ── Determine ────────────────────────────────────────────────────

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        current_round = ct.get_current_round()
        if not self._is_safe(current_round):
            return False

        mm = self.brain.map_manager
        my_pos = ct.get_position()
        target = self._find_target(ct, mm, my_pos, current_round)
        if target is None:
            return False

        self.target = target
        state_manager.current_state = BuilderState.CLEAN_TURRET
        return True

    # ── Standard interface ───────────────────────────────────────────

    def reset(self, ct=None) -> None:
        self.target = None
