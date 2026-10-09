"""Phase implementations for the generic ring-build pipeline.

The three phases form a linear state machine driven by ``state._phase``:

    PHASE_ROUTE    — path to the target and step onto it (reserves the tile).
    PHASE_SABOTAGE — on the target, clear enemy infra cardinal-adjacent.
    PHASE_BUILD    — lay the 4-cardinal ring, step off, place the center.

Both the ring-slot entity and the center entity are parameterised by cambc
``EntityType`` values (``ring`` and ``center`` kwargs) and resolved through
``ring.actions``. Nothing in this file knows about harvesters or foundries
specifically — the state layer is responsible for deciding when this pipeline
should run for a given target.

The pipeline expects the following on ``state``:
  - ``state.target: Position``               — current build target.
  - ``state._phase: str``                    — mutated across phases.
  - ``state.brain``                          — carries ``pathing``.
  - ``state._clear_target(current_round, *, cooldown: bool)``
                                             — called when sabotage abandons.
"""

from cambc import Controller, Environment, EntityType, Position

from helpers.directions import CARDINAL
from nav.common import common_path
from nav.movement import move_road_if_empty

from ring.actions import (
    build_center,
    can_build_center,
    can_place_ring,
    center_cost,
    is_ring_entry,
    place_ring,
    ring_cost,
)
from ring.constants import (
    ALLOW_BARRIER_UPGRADE,
    DEBUG,
    ENEMY_INFRA_TYPES,
    PHASE_BUILD,
    PHASE_ROUTE,
    PHASE_SABOTAGE,
    STEP_OFF_MOVED,
    STEP_OFF_STUCK,
    STEP_OFF_WAITING,
    TURRET_TYPES,
)
from ring.helpers import (
    find_enemy_infra_cardinal,
    in_action_range,
    is_on_position,
    try_step_off,
)


# ── Ring placement ──────────────────────────────────────────────────


def _slot_kind(
    ct: Controller,
    mm,
    target: Position,
    adj: Position,
    ring: EntityType,
) -> EntityType:
    """Pick what to actually build in a ring slot.

    For ``CONVEYOR``, default to ``BARRIER`` only when *every* "keep
    conveyor" reason is false. Reasons OR'd together:
      - the slot tile itself is on ore (we want a belt feeding off it);
      - any non-center cardinal neighbor of the slot is OOB or impassable
        (slot isn't fully exposed → conveyor still earns its keep).
    Otherwise the slot is fully exposed on a non-ore tile → ``BARRIER``.
    """
    if ring != EntityType.CONVEYOR:
        return ring
    if not ALLOW_BARRIER_UPGRADE:
        return ring
    width = mm.width
    height = mm.height
    building_grid = mm.building_grid
    tile_grid = mm.tile_grid

    slot_tile = tile_grid[adj.x][adj.y]
    on_ore = (
        slot_tile == Environment.ORE_TITANIUM
        or slot_tile == Environment.ORE_AXIONITE
    )

    any_neighbor_impassable = False
    any_neighbor_ore = False
    for nd in CARDINAL:
        nb = adj.add(nd)
        if nb.x == target.x and nb.y == target.y:
            continue
        if not (0 <= nb.x < width and 0 <= nb.y < height):
            if DEBUG:
                print(f"[slot_kind] {adj}: nb={nb} OOB")
            any_neighbor_impassable = True
            break
        nb_tile = tile_grid[nb.x][nb.y]
        if nb_tile is None or nb_tile is Environment.WALL:
            if DEBUG:
                print(f"[slot_kind] {adj}: nb={nb} terrain={nb_tile} not passable")
            any_neighbor_impassable = True
            break
        if (
            nb_tile == Environment.ORE_TITANIUM
            or nb_tile == Environment.ORE_AXIONITE
        ):
            # Ore neighbor will likely become a harvester (impassable).
            # Treat it like a soft-impassable so we keep this slot a
            # conveyor — barriering here risks trapping the future builder.
            if DEBUG:
                print(f"[slot_kind] {adj}: nb={nb} is ore — keep CONVEYOR")
            any_neighbor_ore = True
            break
        empty = building_grid[nb.x][nb.y] is None
        passable = empty or ct.is_tile_passable(nb)
        if not passable:
            bot = mm.get_bot(nb)
            if bot is not None and bot.entity_type == EntityType.BUILDER_BOT:
                passable = True
        if DEBUG:
            print(f"[slot_kind] {adj}: nb={nb} empty={empty} passable={passable}")
        if not passable:
            any_neighbor_impassable = True
            break

    if on_ore or any_neighbor_impassable or any_neighbor_ore:
        if DEBUG:
            print(
                f"[slot_kind] {adj}: on_ore={on_ore} "
                f"impassable_nb={any_neighbor_impassable} ore_nb={any_neighbor_ore} → CONVEYOR"
            )
        return ring

    if DEBUG:
        print(f"[slot_kind] {adj}: fully exposed, non-ore → BARRIER")
    return EntityType.BARRIER


def _try_place_ring(
    state,
    ct: Controller,
    mm,
    my_pos: Position,
    ring: EntityType | None,
) -> bool:
    """Place any cardinal-ring tile of kind ``ring`` reachable from ``my_pos``.

    Returns True if an action was consumed (caller returns False for this
    tick). Skips slots occupied by enemy infra — sabotage handles those.
    ``ring=None`` means no ring is wanted (degenerate pipeline: route →
    sabotage → step off → build center).
    """
    if ring is None:
        return False
    width = mm.width
    height = mm.height
    building_grid = mm.building_grid
    target = state.target
    team = ct.get_team()

    # Two passes: prefer empty slots so we don't waste a destroy on an
    # existing tile when a None slot is also available.
    for empty_only in (True, False):
        for d in CARDINAL:
            adj = target.add(d)
            ax = adj.x
            ay = adj.y
            if not (0 <= ax < width and 0 <= ay < height):
                continue
            if adj.distance_squared(my_pos) > 2:
                continue
            adj_rec = building_grid[ax][ay]
            if empty_only and adj_rec is not None:
                continue
            if (
                adj_rec is not None
                and adj_rec.team != team
                and adj_rec.entity_type in ENEMY_INFRA_TYPES
            ):
                continue
            kind = _slot_kind(ct, mm, target, adj, ring)
            slot_cost = ring_cost(ct, kind)
            if is_ring_entry(adj_rec, kind):
                if DEBUG:
                    print(f"[ring] {adj} already {kind}, skipping")
                continue
            if (
                ct.get_global_resources()[0] > slot_cost
                and ct.get_action_cooldown() == 0
            ):
                if adj_rec is None or adj_rec.entity_type == EntityType.ROAD:
                    if ct.can_destroy(adj):
                        if DEBUG:
                            print(f"[ring] destroying {adj_rec.entity_type if adj_rec else None} at {adj}")
                        ct.destroy(adj)
                facing = d.opposite()
                if can_place_ring(ct, adj, facing, kind):
                    if DEBUG:
                        print(f"[ring] building {kind} at {adj} facing {facing}")
                    place_ring(ct, adj, facing, kind)
                    return True
                elif DEBUG:
                    print(f"[ring] can_place({adj}, {facing}, {kind})=False; adj_rec={adj_rec}")
            elif DEBUG:
                print(f"[ring] gate fail at {adj}: res={ct.get_global_resources()[0]} cost={slot_cost} cd={ct.get_action_cooldown()}")
    return False


def _can_finalize_build(
    state,
    ct: Controller,
    mm,
    center: EntityType,
) -> bool:
    """True iff destroying the target tile would leave us able to build the center.

    Destroying is free but wastes the existing tile if the follow-up build
    fails. Gate on the build preconditions (cooldown, cost, no bot sitting on
    the target) before committing to the destroy.
    """
    if ct.get_action_cooldown() != 0:
        return False
    if ct.get_global_resources()[0] < center_cost(ct, center):
        return False
    bot_on_target = mm.get_bot(state.target)
    if bot_on_target is not None and bot_on_target.id != ct.get_id():
        return False
    return True


def _try_finalize_build(
    state,
    ct: Controller,
    mm,
    center: EntityType,
) -> bool:
    """Destroy whatever sits on the target and place the center entity."""
    if not _can_finalize_build(state, ct, mm, center):
        return False
    if ct.can_destroy(state.target):
        ct.destroy(state.target)
    if can_build_center(ct, state.target, center):
        build_center(ct, state.target, center)
        on_built = getattr(state, "on_center_built", None)
        if on_built is not None:
            on_built(ct)
        state._clear_target(ct.get_current_round(), cooldown=False)
        return True
    return False


# ── PHASE_ROUTE ─────────────────────────────────────────────────────


def execute_route(
    state,
    ct: Controller,
    mm,
    my_pos: Position,
    *,
    center: EntityType,
    ring: EntityType | None,
) -> bool:
    """Path to the target, step on, hand off to SABOTAGE."""
    if is_on_position(my_pos, state.target):
        state._phase = PHASE_SABOTAGE
        return execute_sabotage(state, ct, mm, my_pos, center=center, ring=ring)

    if in_action_range(my_pos, state.target):
        building = mm.get_building(state.target)
        if (
            building is not None
            and building.team == ct.get_team()
            and building.entity_type in TURRET_TYPES
        ):
            if ct.can_destroy(state.target):
                ct.destroy(state.target)
            return False

        # Fire off any ring placements we can make from here — saves a tick.
        if _try_place_ring(state, ct, mm, my_pos, ring):
            return False

        direction = my_pos.direction_to(state.target)
        move_road_if_empty(ct, direction)
        return False

    common_path(ct, mm, state.brain.pathing, state.target)
    return False


# ── PHASE_SABOTAGE ──────────────────────────────────────────────────


def execute_sabotage(
    state,
    ct: Controller,
    mm,
    my_pos: Position,
    *,
    center: EntityType,
    ring: EntityType | None,
) -> bool:
    """Clear enemy infra cardinal-adjacent to the target before building.

    Builders only ``fire`` while standing ON the target building, so the
    pattern is: step off onto the enemy tile, fire it, step back.
    """
    if DEBUG:
        print(f"[sabotage] enter my_pos={my_pos} target={state.target}")
    team = ct.get_team()

    if is_on_position(my_pos, state.target):
        target_building = mm.get_building(state.target)
        if (
            target_building is not None
            and target_building.team != team
            and target_building.entity_type in ENEMY_INFRA_TYPES
        ):
            if ct.can_fire(my_pos):
                if DEBUG:
                    print(f"[sabotage] firing enemy {target_building.entity_type} on target {my_pos}")
                ct.fire(my_pos)
            return False

        sab_dir = find_enemy_infra_cardinal(state.target, mm, team)
        if sab_dir is None:
            if DEBUG:
                print("[sabotage] clear -> PHASE_BUILD")
            state._phase = PHASE_BUILD
            return execute_build(state, ct, mm, my_pos, center=center, ring=ring)

        enemy_pos = state.target.add(sab_dir)
        if ct.can_move(sab_dir):
            ct.move(sab_dir)
            if ct.can_fire(enemy_pos):
                ct.fire(enemy_pos)
        return False

    if in_action_range(my_pos, state.target):
        building_here = mm.get_building(my_pos)
        on_enemy_infra = (
            building_here is not None
            and building_here.team != team
            and building_here.entity_type in ENEMY_INFRA_TYPES
        )

        if on_enemy_infra:
            if ct.can_fire(my_pos):
                ct.fire(my_pos)
            return False

        other = mm.get_bot(state.target)
        if other is not None and not is_on_position(my_pos, state.target):
            if DEBUG:
                print(f"[sabotage] target {state.target} taken — abandoning")
            state._clear_target(ct.get_current_round(), cooldown=True)
            return False

        direction = my_pos.direction_to(state.target)
        move_road_if_empty(ct, direction)
        return False

    # Pushed far away — fall back to ROUTE.
    state._phase = PHASE_ROUTE
    return execute_route(state, ct, mm, my_pos, center=center, ring=ring)


# ── PHASE_BUILD ─────────────────────────────────────────────────────


def execute_build(
    state,
    ct: Controller,
    mm,
    my_pos: Position,
    *,
    center: EntityType,
    ring: EntityType | None,
) -> bool:
    """Surround the target with the ring, step off, place the center."""
    width = mm.width
    height = mm.height
    building_grid = mm.building_grid
    target = state.target
    tx = target.x
    ty = target.y
    team = ct.get_team()

    if is_on_position(my_pos, target):
        if DEBUG:
            print(f"[build] ON TARGET {target} cd={ct.get_action_cooldown()}")
        # Re-check sabotage — new enemy infra may have crept in.
        for d in CARDINAL:
            adj = target.add(d)
            ax = adj.x
            ay = adj.y
            if not (0 <= ax < width and 0 <= ay < height):
                continue
            building = building_grid[ax][ay]
            if (
                building is not None
                and building.team != team
                and building.entity_type in ENEMY_INFRA_TYPES
            ):
                state._phase = PHASE_SABOTAGE
                return execute_sabotage(state, ct, mm, my_pos, center=center, ring=ring)

        if _try_place_ring(state, ct, mm, my_pos, ring):
            return False

        # Don't step off until we can destroy + build on the same round.
        if not _can_finalize_build(state, ct, mm, center):
            if DEBUG:
                print(f"[build] finalize gate fail cd={ct.get_action_cooldown()}")
            return False

        step_result = try_step_off(ct, mm, target)
        if step_result == STEP_OFF_STUCK:
            if DEBUG:
                print(f"[build] step_off STUCK at {target} — abandoning")
            state._clear_target(ct.get_current_round(), cooldown=True)
            return False
        if step_result == STEP_OFF_WAITING:
            if DEBUG:
                print(f"[build] step_off WAITING at {target} — retry next tick")
            return False

        return _try_finalize_build(state, ct, mm, center)

    if in_action_range(my_pos, target):
        building = building_grid[tx][ty]
        if (
            building is not None
            and building.team == team
            and building.entity_type in TURRET_TYPES
        ):
            state._phase = PHASE_ROUTE
            return execute_route(state, ct, mm, my_pos, center=center, ring=ring)

        if DEBUG:
            print(f"[build] ADJ target={target} my_pos={my_pos} cd={ct.get_action_cooldown()}")
        if _try_place_ring(state, ct, mm, my_pos, ring):
            return False

        # Ring complete + adjacent + tile clear → finalise without stepping on.
        # With ring=None there are no slots to check — treat as complete.
        ring_complete = True
        if ring is not None:
            for d in CARDINAL:
                adj = target.add(d)
                ax = adj.x
                ay = adj.y
                if not (0 <= ax < width and 0 <= ay < height):
                    continue
                adj_rec = building_grid[ax][ay]
                expected = _slot_kind(ct, mm, target, adj, ring)
                if not is_ring_entry(adj_rec, expected):
                    if DEBUG:
                        print(f"[build] ring incomplete at {adj}: {adj_rec} (want {expected})")
                    ring_complete = False
                    break

        if ring_complete:
            return _try_finalize_build(state, ct, mm, center)

        # Ring incomplete and no more slots placeable from here → step on.
        direction = my_pos.direction_to(target)
        move_road_if_empty(ct, direction)
        return False

    # Pushed away from the target.
    common_path(ct, mm, state.brain.pathing, state.target)
    return False
