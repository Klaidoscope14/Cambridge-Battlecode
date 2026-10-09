"""BuildHarvesterState – find, route to, and build a harvester on ore.

Two internal phases drive the lifecycle:

PHASE_ROUTE     : pick best ore, path toward it, step on top to reserve.
PHASE_SABOTAGE  : on the ore, clear enemy infra adjacent to it, then wait
                  for resources before transitioning to BUILD.
PHASE_BUILD     : surround ore with conveyors, step off, place harvester.

Reservation is implicit — sitting on the ore tile makes other bots skip it.

Implementation logic lives in the ``harvesters`` package; this file is the
orchestrator that wires the per-instance state into those helpers.
"""

from cambc import Controller, Environment, Position

from debug.profiling import cputimer

from harvesters.constants import (
    COOLDOWN_DURATION,
    PHASE_BUILD,
    PHASE_ROUTE,
    PHASE_SABOTAGE,
    ROUTE_TIMEOUT,
)
from harvesters.helpers import in_action_range, is_on_position, manhattan
from harvesters.ore_filter import is_valid_ore, is_valid_predicted_ore
from harvesters.phases import execute_build, execute_route, execute_sabotage
from harvesters.resources import can_build_axionite
from harvesters.targeting import find_closest_cached
from states.builder_state import BuilderState


# If True, only ores confirmed reachable (in brain.pathing._reachable) are
# allowed as harvester build targets. If False, unreachable ores are also
# considered.
ONLY_REACHABLE_ORES: bool = True


class BuildHarvesterState:
    """Route to ore, reserve it, build harvester."""

    allowed_ore = {Environment.ORE_TITANIUM, Environment.ORE_AXIONITE}

    def __init__(self, ct: Controller, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self._target_set_round: int = -1
        self._phase: str = PHASE_ROUTE
        self._core_cache_round: int = -1
        self._core_cache_result: Position | None = None
        self.cooldowns: dict[Position, int] = {}
        self._turret_first_seen: dict[Position, int] = {}

    # ── Cooldown / target bookkeeping ───────────────────────────────

    def _expire_cooldowns(self, current_round: int) -> None:
        expired = [
            p for p, r in self.cooldowns.items()
            if current_round - r > COOLDOWN_DURATION
        ]
        for p in expired:
            del self.cooldowns[p]

    def _assign_target(self, pos: Position | None, current_round: int) -> None:
        if pos != self.target:
            self._target_set_round = current_round if pos is not None else -1
            self._phase = PHASE_ROUTE
        self.target = pos

    def _clear_target(self, current_round: int, *, cooldown: bool = False) -> None:
        if self.target is not None and cooldown:
            self.cooldowns[self.target] = current_round
        self.target = None
        self._target_set_round = -1
        self._phase = PHASE_ROUTE
        self._core_cache_round = -1

    # ── Per-tick context ────────────────────────────────────────────

    def _count_nearby_enemies(self, ct: Controller, mm) -> int:
        # MapManager counts enemy buildings in the same pass that populates
        # bot_grid / building_grid, so this is just a precomputed field read.
        return mm.nearby_enemy_building_count

    def _validate_target(
        self,
        ct: Controller,
        mm,
        my_pos: Position,
        current_round: int,
        enemy_count: int,
    ) -> None:
        if self.target is None:
            return

        on_target = is_on_position(my_pos, self.target)
        ec = 0 if on_target or in_action_range(my_pos, self.target) else enemy_count

        tx = self.target.x
        ty = self.target.y
        tile = mm.tile_grid[tx][ty]
        if tile is not None:
            valid = is_valid_ore(self, ct, mm, self.target, current_round, ec, my_pos)
        else:
            valid = is_valid_predicted_ore(self, ct, mm, self.target, current_round, ec, my_pos)

        if not valid:
            # Don't cooldown ore that's just temporarily reserved by another bot
            bot_on_ore = mm.bot_grid[tx][ty]
            self._clear_target(current_round, cooldown=(bot_on_ore is None))
            return

        if (
            ROUTE_TIMEOUT > 0
            and not on_target
            and self._target_set_round > 0
            and current_round - self._target_set_round >= ROUTE_TIMEOUT
        ):
            self._clear_target(current_round, cooldown=True)

    def _is_reachable(self, pos: Position) -> bool:
        return (pos.x, pos.y) in self.brain.pathing._reachable

    def _filter_reachable(self, pos: Position | None) -> Position | None:
        """Drop unreachable candidates when ONLY_REACHABLE_ORES is on."""
        if pos is None:
            return None
        if ONLY_REACHABLE_ORES and not self._is_reachable(pos):
            return None
        return pos

    # ── Resource gates (re-exported for state_manager / siblings) ───

    def can_build_axionite(self, ct: Controller) -> bool:
        return can_build_axionite(ct)

    # ── Main loop ───────────────────────────────────────────────────

    @cputimer
    def execute(self, ct: Controller) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        current_round = ct.get_current_round()

        self._expire_cooldowns(current_round)

        enemy_count = self._count_nearby_enemies(ct, mm)
        self._validate_target(ct, mm, my_pos, current_round, enemy_count)

        if self.target is None:
            self._phase = PHASE_ROUTE
            best = find_closest_cached(self, ct, mm, current_round, enemy_count, my_pos)
            best = self._filter_reachable(best)
            self._assign_target(best, current_round)

        if self.target is None:
            return False

        print(f"Target: {self.target}")

        if self._phase == PHASE_SABOTAGE:
            return execute_sabotage(self, ct, mm, my_pos)
        if self._phase == PHASE_BUILD:
            return execute_build(self, ct, mm, my_pos)
        return execute_route(self, ct, mm, my_pos)

    # ── State determination ─────────────────────────────────────────

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager
        current_round = ct.get_current_round()
        my_pos = ct.get_position()

        ally_core = mm.ally_core_pos

        def _rank(pos: Position) -> tuple[int, int]:
            """Lower is better: (reachability tier, manhattan-to-core)."""
            return (0 if self._is_reachable(pos) else 1, manhattan(pos, ally_core))

        # Sticky: already in BUILD_HARVESTER and still have a target —
        # keep going, but allow swap if the search returns something better.
        if (
            state_manager.previous_state == BuilderState.BUILD_HARVESTER
            and self.target is not None
        ):
            if self._phase == PHASE_ROUTE:
                # Skip the swap-check if no new tiles were revealed this turn:
                # the candidate set hasn't grown, so the search result can't
                # improve (cooldown expirations would be the only miss — rare).
                if mm.newly_seen:
                    candidate = find_closest_cached(self, ct, mm, current_round, my_pos=my_pos)
                    candidate = self._filter_reachable(candidate)
                    if (
                        candidate is not None
                        and candidate != self.target
                        and _rank(candidate) < _rank(self.target)
                    ):
                        self._assign_target(candidate, current_round)
            elif not self._is_reachable(self.target):
                # Past ROUTE phase but target became unreachable — try to swap
                best = find_closest_cached(self, ct, mm, current_round, my_pos=my_pos)
                if best is not None and self._is_reachable(best):
                    self._assign_target(best, current_round)
            state_manager.current_state = BuilderState.BUILD_HARVESTER
            return True

        # Keep current target if still valid, but re-evaluate every turn.
        if (
            self.target is not None
            and is_valid_ore(self, ct, mm, self.target, current_round, my_pos=my_pos)
        ):
            best = self.target
            # Same gate as above: only search for a swap when new tiles appeared.
            if mm.newly_seen:
                candidate = find_closest_cached(self, ct, mm, current_round, my_pos=my_pos)
                candidate = self._filter_reachable(candidate)
                if (
                    candidate is not None
                    and candidate != best
                    and _rank(candidate) < _rank(best)
                ):
                    best = candidate
        else:
            best = find_closest_cached(self, ct, mm, current_round, my_pos=my_pos)
            best = self._filter_reachable(best)

        if best is None:
            return False

        self._assign_target(best, current_round)
        state_manager.current_state = BuilderState.BUILD_HARVESTER
        return

    # ── Standard interface ──────────────────────────────────────────

    def has_target(self) -> bool:
        return self.target is not None

    def reset(self, ct=None) -> None:
        self.target = None
        s