from cambc import Controller, EntityType, Position
from debug.profiling import cputimer
from helpers.directions import CARDINAL
from map.map_manager import MapManager
from states.builder_state import BuilderState

TITANIUM_BUFFER = 5
AXIONITE_BUFFER = 5

class ReplaceWithArmouredState:
    def __init__(self, ct: Controller, brain) -> None:
        self.brain = brain
        self.target_pos: Position | None = None
        self.target_dir = None

    # ── Helpers ───────────────────────────────────────────────────────────

    def _clear(self) -> None:
        self.target_pos = None
        self.target_dir = None

    def _can_afford(self, ct: Controller) -> bool:
        ti, ax = ct.get_global_resources()
        cost_ti, cost_ax = ct.get_armoured_conveyor_cost()
        return ti >= cost_ti + TITANIUM_BUFFER and ax >= cost_ax + AXIONITE_BUFFER

    def _is_frontier_seed(self, mm: MapManager, pos: Position) -> bool:
        """True if pos is cardinally adjacent to the core or to an existing
        ally armoured conveyor. The core itself is a valid seed, so the very
        first upgrade is a conveyor touching the core."""
        for d in CARDINAL:
            nx = pos.x + d.delta()[0]
            ny = pos.y + d.delta()[1]
            if not (0 <= nx < mm.width and 0 <= ny < mm.height):
                continue
            rec = mm.building_grid[nx][ny]
            if rec is None:
                continue
            # Same-team check via record.team — matches the pattern in
            # connect_conveyor_state._find_feeder_into.
            if rec.entity_type == EntityType.CORE:
                return True
            if rec.entity_type == EntityType.ARMOURED_CONVEYOR:
                return True
        return False

    def _find_target(self, ct: Controller, mm: MapManager, my_pos: Position):
        """Scan nearby ally conveyors via map_manager. Of the ones in action
        range that satisfy the frontier rule, pick the one closest to the
        core so the armoured shell genuinely grows outward.
        """
        core_pos = mm.ally_core_pos
        best_pos = None
        best_dir = None
        best_dist = float("inf")

        for rec in mm.nearby_ally_conveyor_ids:
            # Filter out armoured — this state only upgrades regular conveyors.
            if rec.entity_type != EntityType.CONVEYOR:
                continue
            pos = rec.position
            if abs(pos.x - my_pos.x) > 1 or abs(pos.y - my_pos.y) > 1:
                continue
            if pos.x == my_pos.x and pos.y == my_pos.y:
                continue
            if not self._is_frontier_seed(mm, pos):
                continue
            dist = pos.distance_squared(core_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
                best_dir = rec.direction

        if best_pos is None:
            return None
        return best_pos, best_dir

    # ── State interface ──────────────────────────────────────────────────

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        if not self._can_afford(ct):
            self._clear()
            return False

        ti, _ = ct.get_global_resources()
        if ti < ct.get_harvester_cost()[0] * 3:
            self._clear()
            return False

        print("Determining axionite state")

        mm = self.brain.map_manager
        my_pos = ct.get_position()

        result = self._find_target(ct, mm, my_pos)
        if result is None:
            self._clear()
            return False

        self.target_pos, self.target_dir = result
        state_manager.current_state = BuilderState.REPLACE_WITH_ARMOURED_STATE
        return True

    def execute(self, ct: Controller) -> None:
        if self.target_pos is None or self.target_dir is None:
            return

        mm = self.brain.map_manager

        # Re-validate: tile must still be an ally plain conveyor, and we
        # must still be able to afford the swap.
        rec = mm.get_building(self.target_pos)
        if rec is None or rec.team != ct.get_team() or rec.entity_type != EntityType.CONVEYOR:
            self._clear()
            return

        if not self._can_afford(ct):
            self._clear()
            return

        if not ct.can_destroy(self.target_pos):
            self._clear()
            return

        ct.destroy(self.target_pos)

        if ct.can_build_armoured_conveyor(self.target_pos, self.target_dir):
            ct.build_armoured_conveyor(self.target_pos, self.target_dir)

        self._clear()
