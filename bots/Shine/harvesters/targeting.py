"""Closest-ore lookup with pluggable ore-type prioritisation.

The prioritisation policy lives in :func:`ore_type_priority`. Swap that single
function (or pass a different ``priority_fn`` to :func:`find_closest_to_core`)
to change the ore-selection strategy without touching the search itself.
"""

from cambc import Controller, Environment, Position

from helpers.geometry import on_map
from map.map_manager import MapManager

from harvesters.constants import (
    ORE_TIER_AXIONITE,
    ORE_TIER_EQUAL,
    ORE_TIER_TITANIUM,
    TURRET_TYPES,
)
from harvesters.helpers import manhattan
from harvesters.ore_filter import is_valid_ore, is_valid_ore_fast, is_valid_predicted_ore
from harvesters.resources import can_build_axionite


# ── Prioritisation policy ───────────────────────────────────────────


def ore_type_priority(tile_env, axionite_priority: bool) -> int:
    """Return ore-type tier (lower wins).

    With ``axionite_priority`` True, axionite strictly outranks titanium —
    a lone valid axionite anywhere on the map will be chosen over the
    closest titanium. Unseen (predicted) ore is treated as axionite-eligible
    since we can't tell from the tile yet.

    With ``axionite_priority`` False, all ore types tie on priority and
    fall through to reachability / distance ordering.
    """
    if not axionite_priority:
        return ORE_TIER_EQUAL
    if tile_env == Environment.ORE_AXIONITE:
        return ORE_TIER_AXIONITE
    if tile_env == Environment.ORE_TITANIUM:
        return ORE_TIER_TITANIUM
    return ORE_TIER_AXIONITE


# ── Reachability tier ───────────────────────────────────────────────


def _reach_tier_for(pos: Position, has_turret: bool, reachable: set) -> int:
    """0 reachable & clear, 1 ally turret on ore, 2 unreachable."""
    if has_turret:
        return 1
    if (pos.x, pos.y) in reachable:
        return 0
    return 2


# ── Search ──────────────────────────────────────────────────────────


def find_closest_to_core(
    state,
    ct: Controller,
    mm: MapManager,
    current_round: int,
    enemy_count: int = 0,
    my_pos: Position | None = None,
    priority_fn=ore_type_priority,
) -> Position | None:
    """Return the best valid ore.

    Ordering (lower wins, lexicographic):
      1. ore-type priority (from ``priority_fn``)
      2. reachability tier
      3. Manhattan distance to ally core
      4. Manhattan distance from caller
    """
    ally_core = mm.ally_core_pos
    reachable = state.brain.pathing._reachable
    team = ct.get_team()
    width = mm.width
    height = mm.height
    tile_grid = mm.tile_grid
    building_grid = mm.building_grid
    known_ore_positions = mm.known_ore_positions

    axionite_priority = can_build_axionite(ct)

    best_pos: Position | None = None
    best_key: tuple = (
        float("inf"),  # ore-type priority
        3,             # reach tier (worse than any valid)
        float("inf"),  # core distance
        float("inf"),  # self distance
    )

    def _consider(pos: Position, tile_env, has_turret: bool) -> None:
        nonlocal best_pos, best_key
        ore_pri = priority_fn(tile_env, axionite_priority)
        if ore_pri > best_key[0]:
            return
        reach = _reach_tier_for(pos, has_turret, reachable)
        dist = manhattan(pos, ally_core)
        self_dist = manhattan(pos, my_pos) if my_pos is not None else 0
        key = (ore_pri, reach, dist, self_dist)
        if key < best_key:
            best_key = key
            best_pos = pos

    # Known ore — iterate the pre-filtered plausible set from MapManager.
    # The static checks (tile is ore, axionite gate, blocking buildings,
    # enemy turret adjacency) were applied during update(); is_valid_ore_fast
    # runs only the state-dependent / caller-dependent checks.
    for pos in mm.nearby_plausible_ore_positions:
        if not is_valid_ore_fast(state, ct, mm, pos, current_round, enemy_count, my_pos):
            continue
        px = pos.x
        py = pos.y
        building = building_grid[px][py]
        has_turret = (
            building is not None
            and building.team == team
            and building.entity_type in TURRET_TYPES
        )
        _consider(pos, tile_grid[px][py], has_turret)

    # Symmetry-predicted ore (lighter validation)
    sym = state.brain.symmetry_manager
    if sym.is_cracked():
        for pos in known_ore_positions:
            reflected = sym.reflect(pos)
            if reflected is None:
                continue
            rx = reflected.x
            ry = reflected.y
            if not (0 <= rx < width and 0 <= ry < height):
                continue
            if reflected in known_ore_positions:
                continue
            if not is_valid_predicted_ore(
                state, ct, mm, reflected, current_round, enemy_count, my_pos,
                _axionite_ok=axionite_priority,
            ):
                continue
            building = building_grid[rx][ry]
            has_turret = (
                building is not None
                and building.team == team
                and building.entity_type in TURRET_TYPES
            )
            _consider(reflected, tile_grid[rx][ry], has_turret)

    return best_pos


def find_closest_cached(
    state,
    ct: Controller,
    mm: MapManager,
    current_round: int,
    enemy_count: int = 0,
    my_pos: Position | None = None,
) -> Position | None:
    if state._core_cache_round == current_round:
        return state._core_cache_result
    result = find_closest_to_core(state, ct, mm, current_round, enemy_count, my_pos)
    state._core_cache_round = current_round
    state._core_cache_result = result
    return result
