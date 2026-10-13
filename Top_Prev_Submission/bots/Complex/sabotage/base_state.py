from cambc import EntityType, Position

from helpers.geometry import on_map
from map.map_manager import MapManager
from nav.common import common_path, avoid_launcher_path

SABOTAGE_COOLDOWN = 60
SABOTAGE_RETRY_TURNS = 30

# Priority order: lower index = higher priority
ENEMY_SABOTAGE_TARGETS = [
    EntityType.ROAD,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
]


# ── Shared helpers ──────────────────────────────────────────────────


def can_destroy_building(hp: int) -> bool:
    return True


def destroy_building(ct, pos: Position) -> bool:
    if ct.can_fire(pos):
        ct.fire(pos)
        return True
    return False


def is_enemy_sabotage_target(building, team, targets: list) -> bool:
    """Check if a building record is an enemy building we want to sabotage."""
    if building is None:
        return False
    if building.team == team:
        return False
    return building.entity_type in targets


def target_priority(entity_type: EntityType, targets: list) -> int:
    """Lower value = higher priority."""
    try:
        return targets.index(entity_type)
    except ValueError:
        return len(targets)


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) == 0


# ── Base class ──────────────────────────────────────────────────────


class BaseSabotageState:
    """Base class encapsulating the shared sabotage loop:
    cooldown management, pathing to target, and self-destruct execution.

    Subclasses must override ``TARGETS`` and implement ``_is_valid_target``
    and ``_find_best_target``.
    """

    TARGETS: list = ENEMY_SABOTAGE_TARGETS  # override in subclasses

    def __init__(self, ct, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self.cooldowns: dict[tuple[int, int], int] = {}
        self._attempts: int = 0

    # ── Cooldown management ─────────────────────────────────────────

    def _expire_cooldowns(self, current_round: int) -> None:
        expired = [
            k for k, r in self.cooldowns.items() if current_round - r > SABOTAGE_COOLDOWN
        ]
        for k in expired:
            del self.cooldowns[k]

    def _cooldown_target(self, pos: Position, current_round: int) -> None:
        self.cooldowns[(pos.x, pos.y)] = current_round

    # ── Template methods (override in subclasses) ───────────────────

    def _is_valid_target(self, ct, mm: MapManager, pos: Position, current_round: int) -> bool:
        raise NotImplementedError

    def _find_best_target(
        self, ct, mm: MapManager, my_pos: Position, current_round: int
    ) -> Position | None:
        raise NotImplementedError

    # ── Core tick ───────────────────────────────────────────────────

    def execute(self, ct) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        current_round = ct.get_current_round()

        self._expire_cooldowns(current_round)

        # Don't sabotage if resources are low and an enemy builder is nearby
        if ct.get_global_resources()[0] < ct.get_harvester_cost()[0] * 2:
            for eid in mm.nearby_enemy_builder_bot_ids:
                if my_pos.distance_squared(ct.get_position(eid)) <= 16:
                    return False

        # Validate current target (building may have been destroyed en route)
        if self.target is not None:
            if not self._is_valid_target(ct, mm, self.target, current_round):
                self.target = None

        # Pick new target if needed
        if self.target is None:
            self.target = self._find_best_target(ct, mm, my_pos, current_round)
            self._attempts = 0

        if self.target is None:
            return False

        if in_action_range(my_pos, self.target):
            return self._try_destroy(ct, mm, current_round)
        else:
            #avoid_launcher_path(ct, mm, self.brain.pathing, self.target)
            common_path(ct, mm, self.brain.pathing, self.target)
            my_pos = ct.get_position()
            print("in action range: ", in_action_range(my_pos, self.target))
            if in_action_range(my_pos, self.target):
                print("try to fire")
                return self._try_destroy(ct, mm, current_round)
            return False

    def _try_destroy(self, ct, mm: MapManager, current_round: int) -> bool:
        building = mm.get_building(self.target)
        if building is None or not can_destroy_building(building.hp):
            self._cooldown_target(self.target, current_round)
            self.target = None
            self._attempts = 0
            return False

        if destroy_building(ct, self.target):
            self.target = None
            self._attempts = 0
            return True

        # Couldn't destroy yet — retry up to SABOTAGE_RETRY_TURNS
        self._attempts += 1
        if self._attempts >= SABOTAGE_RETRY_TURNS:
            self._cooldown_target(self.target, current_round)
            self.target = None
            self._attempts = 0
        return False

    # ── Interface for StateManager ──────────────────────────────────

    def has_target(self) -> bool:
        return self.target is not None

    def reset(self, ct=None) -> None:
        self.target = None
        self._attempts = 0