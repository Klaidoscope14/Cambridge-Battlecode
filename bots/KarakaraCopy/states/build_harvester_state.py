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

from cambc import Controller, Environment, EntityType, Position

from debug.profiling import cputimer

from harvesters.constants import (
    COOLDOWN_DURATION,
    ROUTE_TIMEOUT,
)
from harvesters.ore_filter import is_valid_ore, is_valid_predicted_ore
from harvesters.resources import can_afford_build, can_build_axionite
from harvesters.targeting import (
    _ENEMY_TIER_CONTESTED,
    _enemy_proximity_tier,
    find_closest_cached,
)
from ring import ring_build
from ring.constants import PHASE_BUILD, PHASE_ROUTE, PHASE_SABOTAGE
from ring.helpers import in_action_range, is_on_position, manhattan
from states.builder_state import BuilderState


# If True, only ores confirmed reachable (in brain.pathing._reachable) are
# allowed as harvester build targets. If False, unreachable ores are also
# considered.
ONLY_REACHABLE_ORES: bool = True

# Toggle verbose target-selection logging. Prints every assign/clear/swap
# along with the reason so target churn is visible in-game.
DEBUG: bool = True


def _dbg(ct: Controller, msg: str) -> None:
    if DEBUG:
        print(f"[harv r{ct.get_current_round()} b{ct.get_id()}] {msg}")


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

    def _assign_target(self, pos: Position | None, current_round: int, reason: str = "") -> None:
        if pos != self.target:
            if DEBUG:
                tag = f" ({reason})" if reason else ""
                _dbg(self.ct, f"assign {self.target} -> {pos} phase={self._phase}{tag}")
            self._target_set_round = current_round if pos is not None else -1
            self._phase = PHASE_ROUTE
        self.target = pos

    def _clear_target(self, current_round: int, *, cooldown: bool = False, reason: str = "") -> None:
        if DEBUG and self.target is not None:
            tag = f" ({reason})" if reason else ""
            _dbg(self.ct, f"clear {self.target} cooldown={cooldown} phase={self._phase}{tag}")
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
            # Cooldown when an ally is reserving on/cardinal-adjacent to the
            # ore — treat their presence as a structural "this area is taken"
            # signal and bounce away rather than re-considering every tick.
            my_team = ct.get_team()
            bot_grid = mm.bot_grid
            width = len(bot_grid)
            height = len(bot_grid[0]) if width else 0
            ally_reserving = False
            for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = tx + dx, ty + dy
                if 0 <= nx < width and 0 <= ny < height:
                    b = bot_grid[nx][ny]
                    if b is not None and b.team == my_team:
                        ally_reserving = True
                        break
            if DEBUG:
                bot_tag = f"ally_reserving={ally_reserving}"
                _dbg(
                    ct,
                    f"validate reject {self.target} tile={tile} on_target={on_target} "
                    f"ec={ec} {bot_tag} my_pos={my_pos}",
                )
            self._clear_target(
                current_round,
                cooldown=ally_reserving,
                reason="invalidated",
            )
            return

        if (
            ROUTE_TIMEOUT > 0
            and not on_target
            and self._target_set_round > 0
            and current_round - self._target_set_round >= ROUTE_TIMEOUT
        ):
            if DEBUG:
                _dbg(ct, f"ROUTE_TIMEOUT on {self.target} (set r{self._target_set_round})")
            self._clear_target(current_round, cooldown=True, reason="route_timeout")

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

    def on_center_built(self, ct: Controller) -> None:
        """Called by ring pipeline after a successful harvester placement."""
        self.brain.harvesters_built += 1

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
            self._assign_target(best, current_round, reason="execute.pick_new")

        if self.target is None:
            return False

        if DEBUG:
            _dbg(ct, f"execute phase={self._phase} target={self.target} my_pos={my_pos}")

        # Resource gate (harvester-specific; foundry state has its own logic).
        # Only enforced once we're actually trying to finalise the build —
        # route/sabotage don't spend titanium.
        if self._phase == PHASE_BUILD:
            titanium = ct.get_global_resources()[0]
            if titanium < ct.get_harvester_cost()[0]:
                if mm._harvesters:
                    print("Can't afford harvester; waiting for resources")
                    self.brain.state_manager.state_map[BuilderState.GUARD].execute(ct)
                return False

        # Titanium ore wants a 4-cardinal conveyor ring; axionite ore does
        # not (a foundry will land on one of those slots later).
        tile = mm.tile_grid[self.target.x][self.target.y]
        ring = EntityType.CONVEYOR if tile == Environment.ORE_TITANIUM else None

        return ring_build(self, ct, center=EntityType.HARVESTER, ring=ring)

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
                        if DEBUG:
                            _dbg(
                                ct,
                                f"sticky route swap {self.target}{_rank(self.target)} -> "
                                f"{candidate}{_rank(candidate)}",
                            )
                        self._assign_target(candidate, current_round, reason="sticky.route_swap")
            elif not self._is_reachable(self.target):
                # Past ROUTE phase but target became unreachable — try to swap
                best = find_closest_cached(self, ct, mm, current_round, my_pos=my_pos)
                if best is not None and self._is_reachable(best):
                    if DEBUG:
                        _dbg(ct, f"sticky post-route unreachable swap {self.target} -> {best}")
                    self._assign_target(best, current_round, reason="sticky.unreachable_swap")

            # Contested-target override (any phase): if an enemy builder is in
            # the area and our current target has an enemy building on it or
            # cardinal-adjacent, swap to a strictly cleaner candidate.
            if mm.nearby_enemy_builder_bot_ids and self.target is not None:
                team = ct.get_team()
                target_tile = mm.tile_grid[self.target.x][self.target.y]
                target_tier = _enemy_proximity_tier(self.target, target_tile, mm, team)
                if target_tier == _ENEMY_TIER_CONTESTED:
                    candidate = find_closest_cached(self, ct, mm, current_round, my_pos=my_pos)
                    candidate = self._filter_reachable(candidate)
                    if candidate is not None and candidate != self.target:
                        cand_tile = mm.tile_grid[candidate.x][candidate.y]
                        cand_tier = _enemy_proximity_tier(candidate, cand_tile, mm, team)
                        if cand_tier < target_tier:
                            if DEBUG:
                                _dbg(
                                    ct,
                                    f"sticky contested swap {self.target}(tier={target_tier}) -> "
                                    f"{candidate}(tier={cand_tier})",
                                )
                            self._assign_target(candidate, current_round, reason="sticky.contested_swap")

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
                    if DEBUG:
                        _dbg(
                            ct,
                            f"nonsticky swap {best}{_rank(best)} -> "
                            f"{candidate}{_rank(candidate)}",
                        )
                    best = candidate
        else:
            if DEBUG and self.target is not None:
                _dbg(ct, f"nonsticky reject current {self.target} — searching fresh")
            best = find_closest_cached(self, ct, mm, current_round, my_pos=my_pos)
            best = self._filter_reachable(best)

        if best is None:
            if DEBUG:
                _dbg(ct, "determine: no candidate")
            return False

        self._assign_target(best, current_round, reason="determine.pick")
        state_manager.current_state = BuilderState.BUILD_HARVESTER
        return

    # ── Standard interface ──────────────────────────────────────────

    def has_target(self) -> bool:
        return self.target is not None

    def reset(self, ct=None) -> None:
        self.target = None
        