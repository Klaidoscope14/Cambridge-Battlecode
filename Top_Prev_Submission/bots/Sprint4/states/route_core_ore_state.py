"""RouteCoreOreState – route to the titanium ore closest to ally core.

Paths toward the closest valid ore tile and sits on it (by building a
road underneath) to reserve it.  Returns True from execute() once the
bot is on the ore so the state manager can hand off to
BuildHarvesterState.
"""

from cambc import Controller, Environment, GameConstants, Position

from nav.common import common_path
from nav.movement import move_road_if_empty
from debug.profiling import cputimer
from states.builder_state import BuilderState
from ore.base_state import OreStateBase, in_action_range, is_on_position

# ── Tunable constants ───────────────────────────────────────────────

ROUTE_COOLDOWN = 120
RESOURCE_BUFFER_FRACTION = 0.5
BRIDGE_COST_RESERVE = 1


class RouteCoreOreState(OreStateBase):
    # Configure base-class behaviour
    allowed_ore = {Environment.ORE_TITANIUM}
    cooldown_duration = ROUTE_COOLDOWN
    route_timeout = 50
    enforce_ally_side = True
    reject_cardinal_turrets = True

    def __init__(self, ct, brain) -> None:
        super().__init__(ct, brain)
        self._core_cache_round: int = -1
        self._core_cache_result = None

    # ── Cached search ───────────────────────────────────────────────

    def _clear_target(self, current_round: int, *, cooldown: bool = False) -> None:
        super()._clear_target(current_round, cooldown=cooldown)
        # Bust the cache so the next lookup re-searches and skips the
        # now-cooled-down position instead of returning it again.
        self._core_cache_round = -1

    def _find_closest_cached(self, ct, mm, current_round, enemy_count=0, my_pos=None):
        """Return cached result if already searched this round."""
        if self._core_cache_round == current_round:
            return self._core_cache_result
        result = self._find_closest_to_core(ct, mm, current_round, enemy_count, my_pos)
        self._core_cache_round = current_round
        self._core_cache_result = result
        return result

    # ── Resource check ──────────────────────────────────────────────

    def _can_afford_soon(self, ct: Controller) -> bool:
        resources = ct.get_global_resources()[0]
        harvester_cost = ct.get_harvester_cost()[0]
        buffer = int(GameConstants.HARVESTER_BASE_COST[0] * RESOURCE_BUFFER_FRACTION)
        bridge_reserve = BRIDGE_COST_RESERVE * ct.get_bridge_cost()[0]
        return resources >= harvester_cost + buffer + bridge_reserve

    # ── Core tick ───────────────────────────────────────────────────

    @cputimer
    def execute(self, ct: Controller) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        current_round = ct.get_current_round()

        self._expire_cooldowns(current_round)

        # If BUILD abandoned the target, cooldown it so we don't loop back
        failed = self.brain.ore_build_failed
        if failed is not None:
            self.cooldowns[failed] = current_round
            if self.target is not None and is_on_position(self.target, failed):
                self._clear_target(current_round, cooldown=False)
            self.brain.ore_build_failed = None

        enemy_count = self._count_nearby_enemies(ct, mm)
        self._validate_target(ct, mm, my_pos, current_round, enemy_count)

        # Pick new target
        if self.target is None:
            self._assign_target(
                self._find_closest_cached(ct, mm, current_round, enemy_count, my_pos),
                current_round,
            )

        if self.target is None:
            return False

        # Sitting on the ore — hand off to BUILD_HARVESTER
        if is_on_position(my_pos, self.target):
            if not self._can_afford_soon(ct):
                return False
            self.brain.ore_build_target = self.target
            return True

        # Adjacent to ore — step onto it to reserve
        if in_action_range(my_pos, self.target):
            direction = my_pos.direction_to(self.target)
            move_road_if_empty(ct, direction)
            return False

        # Not in range yet — path to target
        common_path(ct, mm, self.brain.pathing, self.target)
        return False

    # ── State determination ─────────────────────────────────────────

    @cputimer
    def determine_route_core_ore_state(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager
        current_round = ct.get_current_round()
        my_pos = ct.get_position()

        # Sticky: if we were routing last round and still have a target,
        # stay in ROUTE.  execute() handles validation and BUILD handoff.
        if (
            state_manager.previous_state == BuilderState.ROUTE_CORE_ORE
            and self.target is not None
        ):
            state_manager.current_state = BuilderState.ROUTE_CORE_ORE
            return True

        # Keep current target if still valid to avoid oscillation
        if (
            self.target is not None
            and self._is_valid_ore(ct, mm, self.target, current_round, my_pos=my_pos)
        ):
            best = self.target
        else:
            best = self._find_closest_cached(ct, mm, current_round, my_pos=my_pos)

        if best is None:
            return False

        self._assign_target(best, current_round)
        state_manager.current_state = BuilderState.ROUTE_CORE_ORE
        return True