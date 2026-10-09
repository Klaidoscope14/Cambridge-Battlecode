"""Single entrypoint for the ring-build pipeline.

Callsite example:

    from cambc import EntityType
    from ring import ring_build

    ring_build(self, ct, center=EntityType.HARVESTER, ring=EntityType.CONVEYOR)

The state is responsible for target selection, validation, cooldown
bookkeeping, and phase initialisation (``self._phase = PHASE_ROUTE``). See
``ring.phases`` for the contract on the ``state`` object.
"""

from cambc import Controller, EntityType

from ring.constants import PHASE_BUILD, PHASE_SABOTAGE
from ring.phases import execute_build, execute_route, execute_sabotage


def ring_build(
    state,
    ct: Controller,
    *,
    center: EntityType,
    ring: EntityType | None,
) -> bool:
    """Advance the ring-build pipeline one tick for ``state.target``."""
    mm = state.brain.map_manager
    my_pos = ct.get_position()

    if state._phase == PHASE_SABOTAGE:
        return execute_sabotage(state, ct, mm, my_pos, center=center, ring=ring)
    if state._phase == PHASE_BUILD:
        return execute_build(state, ct, mm, my_pos, center=center, ring=ring)
    return execute_route(state, ct, mm, my_pos, center=center, ring=ring)
