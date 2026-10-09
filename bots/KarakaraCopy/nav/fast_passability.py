"""Fast (ctx, x, y) -> bool passability variants.

Mirror the semantics of nav.passability.passability_* but avoid the slow
parts: direct grid indexing instead of MapManager methods, a snapshot
PassContext instead of per-call controller queries, and exactly one
building lookup per call (the old functions looked it up twice).

Launcher avoidance is NOT baked in here — Pathing wraps the chosen
fast_pass_fn with a launcher/target check in its caching layer.
"""
from __future__ import annotations

from cambc import Environment, EntityType
from nav.pass_context import PassContext

_WALL = Environment.WALL
_CORE = EntityType.CORE
_MARKER = EntityType.MARKER
_WALKABLE = frozenset({
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
    EntityType.MARKER,
})


def fast_passability_default(ctx: PassContext, x: int, y: int) -> bool:
    if x == ctx.my_x and y == ctx.my_y:
        return True
    tile = ctx.tile_grid[x][y]
    if tile is None or tile is _WALL:
        return False
    b = ctx.building_grid[x][y]
    if b is None:
        # Empty tile: need to build a road to pass.
        return ctx.resources > ctx.road_cost
    et = b.entity_type
    if et is _CORE:
        return b.team == ctx.my_team
    if et not in _WALKABLE:
        return False
    if et is _MARKER:
        return ctx.resources > ctx.road_cost
    return True


def fast_passability_save(ctx: PassContext, x: int, y: int) -> bool:
    if x == ctx.my_x and y == ctx.my_y:
        return True
    tile = ctx.tile_grid[x][y]
    if tile is None or tile is _WALL:
        return False
    b = ctx.building_grid[x][y]
    if b is None:
        return ctx.resources > ctx.save_cost
    et = b.entity_type
    if et is _CORE:
        return b.team == ctx.my_team
    if et not in _WALKABLE:
        return False
    if et is _MARKER:
        return ctx.resources > ctx.save_cost
    return True


def fast_passability_no_build_road(ctx: PassContext, x: int, y: int) -> bool:
    if x == ctx.my_x and y == ctx.my_y:
        return True
    tile = ctx.tile_grid[x][y]
    if tile is None or tile is _WALL:
        return False
    b = ctx.building_grid[x][y]
    if b is None:
        return False
    et = b.entity_type
    if et is _CORE:
        return b.team == ctx.my_team
    if et not in _WALKABLE:
        return False
    # Reject MARKER — it would need a road build.
    return et is not _MARKER
