"""Lightweight terrain reachability check for idle_expand.

A tile is reachable if it's seen, not a wall, and either empty or
covered by a walkable building.  Does NOT depend on transient state
(resources, launcher zones, target) — Pathing.path_to re-verifies
under full passability rules before actually moving onto the tile,
so being optimistic here is safe and much cheaper than the A*
passability check.
"""
from __future__ import annotations

from cambc import Environment, EntityType
from nav.pass_context import PassContext

_WALL = Environment.WALL
_CORE = EntityType.CORE
_WALKABLE = frozenset({
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
    EntityType.MARKER,
})


def is_reachable(ctx: PassContext, x: int, y: int) -> bool:
    tile = ctx.tile_grid[x][y]
    if tile is None or tile is _WALL:
        return False
    b = ctx.building_grid[x][y]
    if b is None:
        return True
    et = b.entity_type
    if et is _CORE:
        return b.team == ctx.my_team
    return et in _WALKABLE
