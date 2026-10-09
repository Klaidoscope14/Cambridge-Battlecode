from cambc import Controller, Position
from nav.movement import move_road_if_empty
from nav.passability import passability_default

from fortify_core.helpers import (
    core_is_damaged,
    on_core,
)


class FortifyCoreState:
    """Walk to the allied core and heal it whenever it is damaged."""

    def __init__(self, ct: Controller, brain) -> None:
        self.ct = ct
        self.brain = brain

    # ── public interface expected by StateManager ────────────────────

    def execute(self, ct: Controller) -> None:
        mm = self.brain.map_manager
        core_pos = self.brain.ally_core_pos
        my_pos = ct.get_position()

        if core_is_damaged(ct, mm, core_pos):
            if on_core(my_pos, core_pos):
                if ct.can_heal(my_pos):
                    ct.heal(my_pos)
                return
            else:
                self.brain.pathing.path_to(
                    ct, mm,
                    my_pos, core_pos,
                    move_road_if_empty,
                    passability_default,
                    cardinal=False,
                )
                return

        # Core is healthy — idle at core center
        if my_pos.distance_squared(core_pos) > 0:
            self.brain.pathing.path_to(
                ct, mm,
                my_pos, core_pos,
                move_road_if_empty,
                passability_default,
                cardinal=False,
            )

    def has_target(self) -> bool:
        return False