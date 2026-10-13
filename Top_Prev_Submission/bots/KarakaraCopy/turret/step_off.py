"""Shared on-build-tile step-off sequence for turret-style builders.

When a builder bot is standing on its build target, it must destroy any
blocker, step off to an adjacent tile, and then place the turret — all in
one turn. This module centralises that sequence and adds a guard: if no
adjacent tile is currently walkable (would require placing a road first),
we skip the destroy and instead drop a road nearby so we can step off
next turn.
"""

from cambc import Position
from helpers.directions import DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager


def has_walkable_adjacent(ct) -> bool:
    """True if any adjacent tile is walkable right now (no road build needed,
    no blocking bot/building, not a wall)."""
    return any(ct.can_move(d) for d in DIRECTIONS)


def place_road_around(ct, mm: MapManager, my_pos: Position) -> bool:
    """Place a road on any adjacent tile that accepts one. Pick arbitrarily."""
    for d in DIRECTIONS:
        adj = my_pos.add(d)
        if not on_map(adj, mm.width, mm.height):
            continue
        if ct.can_build_road(adj):
            ct.build_road(adj)
            return True
    return False


def _pos_in_danger(pos: Position, danger) -> bool:
    for dp in danger:
        if pos.x == dp.x and pos.y == dp.y:
            return True
    return False


def _step_off(ct, mm: MapManager | None = None) -> bool:
    danger = mm.gunner_danger_positions if mm is not None else []
    my_pos = ct.get_position()
    fallback = None
    for d in DIRECTIONS:
        if not ct.can_move(d):
            continue
        if danger and _pos_in_danger(my_pos.add(d), danger):
            if fallback is None:
                fallback = d
            continue
        ct.move(d)
        return True
    if fallback is not None:
        ct.move(fallback)
        return True
    return False


def handle_on_build_tile(ct, mm: MapManager, target_pos: Position,
                         can_build_fn, build_fn) -> bool:
    """Standing-on-target flow: step off this turn, build next turn from adjacent.

    Always returns False — destroy+build is handled by the caller's adjacent
    branch on the following turn. Doing it this way avoids the case where a
    destroyed blocker still occupies the tile in the same turn, causing the
    in-turn build to silently fail after we've already moved off.

    - If no adjacent tile is walkable, places a road nearby and waits a turn.
    - Otherwise steps off onto a walkable tile.
    """
    if ct.get_move_cooldown() > 0:
        return False

    if not has_walkable_adjacent(ct):
        place_road_around(ct, mm, target_pos)
        return False

    _step_off(ct, mm)
    return False
