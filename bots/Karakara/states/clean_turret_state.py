"""CleanTurretState – replace useless ally turrets with barriers.

Two cleanup rules:

* **Sentinel**: if we're standing on the tile directly in front of an
  ally sentinel (i.e. the sentinel is facing us) AND no enemy triggers
  are within ``TRIGGER_RADIUS_SQ`` of the sentinel, the sentinel isn't
  doing useful work — destroy it and drop a barrier in its place.
* **Gunner**: if an ally gunner has been observed facing directly into
  another ally barrier/gunner/sentinel/launcher for the last
  ``BLOCKED_THRESHOLD`` observed turns (tracked by
  ``vision.gunner_blocked_tracker``), it can't shoot past the wall —
  destroy and replace.
"""

from cambc import Controller, EntityType, Position

from debug.profiling import cputimer
from nav.common import common_path
from states.build_sentinel_state import PRIORITY as SENTINEL_TRIGGER_PRIORITY
from states.build_sentinel_state import TRIGGER_RADIUS_SQ as SENTINEL_TRIGGER_RADIUS_SQ
from states.builder_state import BuilderState

# ── Constants ────────────────────────────────────────────────────────

ACTION_RADIUS_SQ = 2


# ── Helpers ──────────────────────────────────────────────────────────


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) <= ACTION_RADIUS_SQ


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


# ── State ─────────────────────────────────────────────────────────────


class CleanTurretState:
    def __init__(self, ct: Controller, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None

    # ── Sentinel rule ────────────────────────────────────────────────

    def _has_sentinel_trigger_nearby(self, sentinel_pos: Position) -> bool:
        mm = self.brain.map_manager
        for attr in SENTINEL_TRIGGER_PRIORITY:
            for item in getattr(mm, attr, []):
                trigger_pos = item if isinstance(item, Position) else item.position
                if trigger_pos is None:
                    continue
                if sentinel_pos.distance_squared(trigger_pos) <= SENTINEL_TRIGGER_RADIUS_SQ:
                    return True
        return False

    def _find_useless_sentinel(self, my_pos: Position, team) -> Position | None:
        """Sentinel directly facing us with no triggers in range."""
        mm = self.brain.map_manager
        for rec in mm.nearby_ally_turret_ids:
            if rec.team != team or rec.entity_type != EntityType.SENTINEL:
                continue
            pos = rec.position
            if pos is None or rec.direction is None:
                continue
            # We must be on the tile the sentinel is facing.
            if pos.add(rec.direction) != my_pos:
                continue
            if self._has_sentinel_trigger_nearby(pos):
                continue
            return pos
        return None

    # ── Gunner rule ──────────────────────────────────────────────────

    def _find_blocked_gunner(self, my_pos: Position, team) -> Position | None:
        mm = self.brain.map_manager
        tracker = self.brain.gunner_blocked_tracker
        best_pos: Position | None = None
        best_dist = float("inf")
        for rec in mm.nearby_ally_turret_ids:
            if rec.team != team or rec.entity_type != EntityType.GUNNER:
                continue
            if not tracker.confirmed_blocked(rec.id):
                continue
            pos = rec.position
            if pos is None:
                continue
            dist = manhattan(pos, my_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
        return best_pos

    # ── Core tick ────────────────────────────────────────────────────

    @cputimer
    def execute(self, ct: Controller) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        if self.target is None:
            return False

        building = mm.get_building(self.target)
        target_is_turret = (
            building is not None
            and building.team == ct.get_team()
            and building.entity_type in (
                EntityType.SENTINEL,
                EntityType.GUNNER,
                EntityType.BREACH,
            )
        )

        # Turret already gone — drop a barrier on the now-empty tile.
        if not target_is_turret:
            if (
                in_action_range(my_pos, self.target)
                and my_pos != self.target
                and ct.can_build_barrier(self.target)
            ):
                ct.build_barrier(self.target)
            self.target = None
            return False

        if in_action_range(my_pos, self.target) and my_pos != self.target:
            if ct.get_action_cooldown() > 0:
                return False
            if ct.get_global_resources()[0] < ct.get_barrier_cost()[0]:
                return False
            if ct.can_destroy(self.target):
                ct.destroy(self.target)
                if ct.can_build_barrier(self.target):
                    ct.build_barrier(self.target)
                    self.target = None
            return False

        common_path(ct, mm, self.brain.pathing, self.target)
        return False

    # ── Determine ────────────────────────────────────────────────────

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        my_pos = ct.get_position()
        team = ct.get_team()

        target = self._find_useless_sentinel(my_pos, team)
        if target is None:
            target = self._find_blocked_gunner(my_pos, team)
        if target is None:
            return False

        self.target = target
        state_manager.current_state = BuilderState.CLEAN_TURRET
        return True

    # ── Standard interface ───────────────────────────────────────────

    def reset(self, ct=None) -> None:
        self.target = None
