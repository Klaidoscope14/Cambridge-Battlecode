"""RusherBuildHarvesterState — opportunistic titanium-ore claim for rushers.

The rusher walks past titanium ores while pushing toward the enemy. When one
of those ores sits inside an enemy build cluster (launcher / conveyor / bridge
/ harvester within 32 dist²), drop everything and barrier-ring a harvester on
it. The barrier ring is intentional — these tiles are deep in enemy territory,
so we use barriers instead of the usual conveyor ring to harden the claim.

Skipped entirely if any enemy turret is in vision — barriers don't help if a
gunner is shredding us mid-build.
"""

from cambc import Controller, Environment, EntityType, Position

from debug.profiling import cputimer
from harvesters.ore_filter import is_valid_ore
from ring import ring_build
from ring.constants import PHASE_BUILD, PHASE_ROUTE
from states.builder_state import BuilderState


TRIGGER_PRIORITY = (
    "nearby_enemy_harvester_ids",
    "nearby_enemy_launcher_ids",
    "nearby_enemy_conveyor_ids",
    "nearby_enemy_bridge_ids",
)

TRIGGER_RADIUS_SQ = 32

DEBUG: bool = False


class RusherBuildHarvesterState:
    """Rusher-side build-harvester: only triggers near enemy infra clusters."""

    # Required by is_valid_ore.
    allowed_ore = {Environment.ORE_TITANIUM}

    def __init__(self, ct: Controller, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self._phase: str = PHASE_ROUTE
        # is_valid_ore consults these.
        self.cooldowns: dict[Position, int] = {}
        self._turret_first_seen: dict[Position, int] = {}

    # ── Helpers ─────────────────────────────────────────────────────

    def _collect_trigger_positions(self, ct: Controller, mm) -> list[Position]:
        """Resolve the 4 trigger ID lists to positions once per determine."""
        out: list[Position] = []
        for attr in TRIGGER_PRIORITY:
            for item in getattr(mm, attr, ()):
                pos = item if isinstance(item, Position) else item.position
                if pos is not None:
                    out.append(pos)
        return out

    def _ore_has_trigger(self, ore: Position, triggers: list[Position]) -> bool:
        for t in triggers:
            if ore.distance_squared(t) <= TRIGGER_RADIUS_SQ:
                return True
        return False

    def _ally_builder_on_or_adjacent(self, ct: Controller, mm, pos: Position, my_pos: Position) -> bool:
        """True if any ally builder bot (other than me) sits on the ore or cardinal-adjacent."""
        team = ct.get_team()
        bot_grid = mm.bot_grid
        width = mm.width
        height = mm.height
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = pos.x + dx, pos.y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if nx == my_pos.x and ny == my_pos.y:
                continue
            b = bot_grid[nx][ny]
            if (
                b is not None
                and b.team == team
                and b.entity_type == EntityType.BUILDER_BOT
            ):
                return True
        return False

    def _is_valid_titanium_ore(
        self,
        ct: Controller,
        mm,
        pos: Position,
        current_round: int,
        my_pos: Position,
    ) -> bool:
        # Cheap pre-filter: titanium tile (most nearby_positions aren't ore).
        if mm.tile_grid[pos.x][pos.y] != Environment.ORE_TITANIUM:
            return False
        # Reject if the ore or any cardinal neighbor has an enemy building on
        # it (markers excepted). Fighting through a destructible blocker
        # mid-build — on the ore or on a ring tile — costs more than it's worth.
        team = ct.get_team()
        building_grid = mm.building_grid
        width = mm.width
        height = mm.height
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = pos.x + dx, pos.y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            b = building_grid[nx][ny]
            if (
                b is not None
                and b.team != team
                and b.entity_type != EntityType.MARKER
            ):
                return False
        if self._ally_builder_on_or_adjacent(ct, mm, pos, my_pos):
            return False
        return is_valid_ore(
            self,
            ct,
            mm,
            pos,
            current_round,
            my_pos=my_pos,
            require_closer_to_ally_core=False,
        )

    def _find_target(
        self,
        ct: Controller,
        mm,
        my_pos: Position,
        current_round: int,
        triggers: list[Position],
    ) -> Position | None:
        best: Position | None = None
        best_d = float("inf")
        for pos in mm.nearby_positions:
            # Cheap distance + trigger gate first — skip the heavy validator
            # for any ore that wouldn't qualify even if it were perfect.
            d = my_pos.distance_squared(pos)
            if d >= best_d:
                continue
            if not self._ore_has_trigger(pos, triggers):
                continue
            if not self._is_valid_titanium_ore(ct, mm, pos, current_round, my_pos):
                continue
            best_d = d
            best = pos
        return best

    def _clear(self) -> None:
        self.target = None
        self._phase = PHASE_ROUTE

    def _clear_target(self, current_round: int, *, cooldown: bool = False, reason: str = "") -> None:
        """Contract method called by the ring pipeline."""
        if cooldown and self.target is not None:
            self.cooldowns[self.target] = current_round
        if DEBUG and self.target is not None:
            print(f"[RusherBuildHarvester] _clear_target {self.target} cooldown={cooldown} reason={reason}")
        self._clear()

    # ── Standard interface ──────────────────────────────────────────

    def has_target(self) -> bool:
        return self.target is not None

    def reset(self, ct=None) -> None:
        self._clear()

    def on_center_built(self, ct: Controller) -> None:
        self.brain.harvesters_built += 1

    # ── Determine / execute ─────────────────────────────────────────

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        current_round = ct.get_current_round()

        # Hard veto: enemy turrets in vision.
        if mm.nearby_enemy_turret_pos:
            if DEBUG:
                print("[RusherBuildHarvester] veto: enemy turret nearby")
            self._clear()
            return False

        # Cost gate: only worth diverting if we can comfortably afford the
        # harvester with headroom. Deep-territory builds are speculative, so
        # require 2x the harvester cost before committing.
        if ct.get_global_resources()[0] < 2 * ct.get_harvester_cost()[0]:
            self._clear()
            return False

        triggers = self._collect_trigger_positions(ct, mm)
        if not triggers:
            self._clear()
            return False

        # Sticky: keep the current target if it's still a valid candidate.
        if self.target is not None:
            if (
                self._ore_has_trigger(self.target, triggers)
                and self._is_valid_titanium_ore(ct, mm, self.target, current_round, my_pos)
            ):
                state_manager.current_state = BuilderState.RUSHER_BUILD_HARVESTER
                return True
            if DEBUG:
                print(f"[RusherBuildHarvester] target {self.target} no longer valid")
            self._clear()

        target = self._find_target(ct, mm, my_pos, current_round, triggers)
        if target is None:
            return False

        if DEBUG:
            print(f"[RusherBuildHarvester] new target {target}")
        self.target = target
        self._phase = PHASE_ROUTE
        state_manager.current_state = BuilderState.RUSHER_BUILD_HARVESTER
        return True

    @cputimer
    def execute(self, ct: Controller) -> bool:
        if self.target is None:
            return False

        # Resource gate at PHASE_BUILD — match the existing harvester state.
        if self._phase == PHASE_BUILD:
            titanium = ct.get_global_resources()[0]
            if titanium < ct.get_harvester_cost()[0]:
                return False

        return ring_build(
            self,
            ct,
            center=EntityType.HARVESTER,
            ring=EntityType.BARRIER,
        )
