"""Phase implementations for the build-harvester pipeline.

Each ``execute_*`` function takes the state instance plus the round-local
context (``ct``, ``mm``, ``my_pos``) and runs one tick of that phase.
Phase transitions are made by mutating ``state._phase`` and calling the
sibling phase function directly.
"""

from cambc import Controller, EntityType, Environment, Position

from helpers.directions import CARDINAL, CARDINAL_THEN_DIAGONAL
from helpers.geometry import on_map
from nav.common import common_path
from nav.movement import move_road_if_empty

from harvesters.constants import (
    DEBUG,
    ENEMY_INFRA_TYPES,
    PHASE_BUILD,
    PHASE_ROUTE,
    PHASE_SABOTAGE,
    TURRET_TYPES,
)
from harvesters.helpers import in_action_range, is_on_position
from harvesters.resources import can_afford_build
from states.builder_state import BuilderState


# ── Movement helpers ────────────────────────────────────────────────


def try_step_off(ct: Controller, mm, ore_pos: Position) -> bool:
    """Move off the ore tile to any adjacent walkable, unoccupied tile.

    Prefer cardinals first — we laid conveyors on those tiles during the
    build ring, so moving onto them won't trigger ``build_road`` inside
    ``move_road_if_empty`` (which would consume the action and starve the
    harvester build). Diagonals are a fallback only.
    """
    width = mm.width
    height = mm.height
    tile_grid = mm.tile_grid
    bot_grid = mm.bot_grid
    for d in CARDINAL_THEN_DIAGONAL:
        adj = ore_pos.add(d)
        ax = adj.x
        ay = adj.y
        if not (0 <= ax < width and 0 <= ay < height):
            continue
        tile = tile_grid[ax][ay]
        if tile is None or tile == Environment.WALL:
            continue
        if bot_grid[ax][ay] is not None:
            continue
        if move_road_if_empty(ct, d):
            return True
    return False


def find_enemy_infra_cardinal(target: Position, mm, team):
    """Direction toward an enemy-infra tile cardinal-adjacent to target, or None."""
    width = mm.width
    height = mm.height
    building_grid = mm.building_grid
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
            return d
    return None


# ── Phase: ROUTE ────────────────────────────────────────────────────


def execute_route(state, ct: Controller, mm, my_pos: Position) -> bool:
    """Path to ore, step onto it, hand off to SABOTAGE."""
    if is_on_position(my_pos, state.target):
        state._phase = PHASE_SABOTAGE
        return execute_sabotage(state, ct, mm, my_pos)

    # Adjacent — step onto ore to reserve it. Ally turret on top must be
    # destroyed first.
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

        tx = state.target.x
        ty = state.target.y
        if mm.tile_grid[tx][ty] == Environment.ORE_TITANIUM:
            if _try_place_ring_conveyors(state, ct, mm, my_pos):
                return False

        direction = my_pos.direction_to(state.target)
        move_road_if_empty(ct, direction)
        return False

    common_path(ct, mm, state.brain.pathing, state.target)
    return False


# ── Phase: SABOTAGE ─────────────────────────────────────────────────


def execute_sabotage(state, ct: Controller, mm, my_pos: Position) -> bool:
    """Destroy enemy infra cardinal-adjacent to the ore before building.

    Builders can only ``fire`` while standing ON top of the target building,
    so we step off onto the enemy tile, fire it, then step back.
    """
    print(f"[BH sabotage] enter my_pos={my_pos} target={state.target}")
    team = ct.get_team()

    # Standing on the ore
    if is_on_position(my_pos, state.target):
        sab_dir = find_enemy_infra_cardinal(state.target, mm, team)
        if sab_dir is None:
            print("[BH sabotage] clear -> PHASE_BUILD")
            state._phase = PHASE_BUILD
            return execute_build(state, ct, mm, my_pos)

        enemy_pos = state.target.add(sab_dir)
        print(f"[BH sabotage] stepping off onto enemy infra at {enemy_pos}")
        if ct.can_move(sab_dir):
            ct.move(sab_dir)
            if ct.can_fire(enemy_pos):
                ct.fire(enemy_pos)
                print(f"[BH sabotage] moved + FIRED at {enemy_pos}")
            else:
                print("[BH sabotage] moved; fire next round")
        else:
            print("[BH sabotage] can_move=False — stuck this round")
        return False

    # Off the ore, inside action range
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
                print(f"[BH sabotage] FIRED at {my_pos}")
            else:
                print(f"[BH sabotage] on enemy infra {my_pos} but can_fire=False")
            return False

        other = mm.get_bot(state.target)
        if other is not None and not is_on_position(my_pos, state.target):
            print(f"[BH sabotage] ore {state.target} taken by another bot — abandoning")
            state._clear_target(ct.get_current_round(), cooldown=True)
            return False

        direction = my_pos.direction_to(state.target)
        print(f"[BH sabotage] stepping back onto ore via {direction}")
        move_road_if_empty(ct, direction)
        return False

    # Pushed far away
    print("[BH sabotage] far from target — reverting to ROUTE")
    state._phase = PHASE_ROUTE
    return execute_route(state, ct, mm, my_pos)


# ── Phase: BUILD ────────────────────────────────────────────────────


def _try_place_ring_conveyors(state, ct: Controller, mm, my_pos: Position) -> bool:
    """Place any cardinal-ring conveyors reachable from ``my_pos``.

    Returns True if an action was consumed (caller should return False for
    this tick). Skips tiles holding enemy infra — those are sabotage's job.
    """
    width = mm.width
    height = mm.height
    building_grid = mm.building_grid
    target = state.target
    team = ct.get_team()
    conveyor_cost = ct.get_conveyor_cost()[0]

    for d in CARDINAL:
        adj = target.add(d)
        ax = adj.x
        ay = adj.y
        if not (0 <= ax < width and 0 <= ay < height):
            continue
        if adj.distance_squared(my_pos) > 2:
            continue
        adj_rec = building_grid[ax][ay]
        if (
            adj_rec is not None
            and adj_rec.team != team
            and adj_rec.entity_type in ENEMY_INFRA_TYPES
        ):
            continue
        if adj_rec is not None and adj_rec.entity_type == EntityType.CONVEYOR:
            if DEBUG:
                print(f"[BH ring] {adj} already CONVEYOR, skipping")
            continue
        if (
            ct.get_global_resources()[0] > conveyor_cost
            and ct.get_action_cooldown() == 0
        ):
            if adj_rec is None or adj_rec.entity_type == EntityType.ROAD:
                if ct.can_destroy(adj):
                    if DEBUG:
                        print(f"[BH ring] destroying {adj_rec.entity_type if adj_rec else None} at {adj}")
                    ct.destroy(adj)
            d_opp = d.opposite()
            if ct.can_build_conveyor(adj, d_opp):
                if DEBUG:
                    print(f"[BH ring] building conveyor at {adj} facing {d_opp}")
                ct.build_conveyor(adj, d_opp)
                return True
            elif DEBUG:
                print(f"[BH ring] can_build_conveyor({adj}, {d_opp})=False; adj_rec={adj_rec}")
        elif DEBUG:
            print(f"[BH ring] gate fail at {adj}: res={ct.get_global_resources()[0]} cost={conveyor_cost} cd={ct.get_action_cooldown()}")
    return False


def _try_finalize_build(state, ct: Controller) -> bool:
    """Destroy whatever is on the target tile and place the harvester."""
    if ct.can_destroy(state.target):
        ct.destroy(state.target)
    if ct.can_build_harvester(state.target):
        ct.build_harvester(state.target)
        state.brain.harvesters_built += 1
        state._clear_target(ct.get_current_round(), cooldown=False)
        return True
    return False


def execute_build(state, ct: Controller, mm, my_pos: Position) -> bool:
    """Surround ore with conveyors, step off, build harvester."""
    titanium = ct.get_global_resources()[0]
    harvester_cost = ct.get_harvester_cost()[0]

    if titanium < harvester_cost:
        state.brain.state_manager.state_map[BuilderState.GUARD].execute(ct)
        return

    if not can_afford_build(ct, mm, state.target):
        return

    team = ct.get_team()
    # On the ore — re-check sabotage, lay surrounding conveyors, step off, build.
    width = mm.width
    height = mm.height
    building_grid = mm.building_grid
    tile_grid = mm.tile_grid
    target = state.target
    tx = target.x
    ty = target.y

    if is_on_position(my_pos, target):
        if DEBUG:
            print(f"[BH build] ON ORE {target} tile={tile_grid[tx][ty]} cd={ct.get_action_cooldown()}")
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
                return execute_sabotage(state, ct, mm, my_pos)

        if tile_grid[tx][ty] == Environment.ORE_TITANIUM:
            if _try_place_ring_conveyors(state, ct, mm, my_pos):
                return False  # used action; wait for next round
        elif DEBUG:
            print(f"[BH build] SKIP ring placement: tile={tile_grid[tx][ty]} != ORE_TITANIUM")

        # Don't step off until we can destroy + build on the same round
        if ct.get_action_cooldown() != 0:
            if DEBUG:
                print(f"[BH build] waiting on cooldown={ct.get_action_cooldown()}")
            return False

        if not try_step_off(ct, mm, target):
            state._clear_target(ct.get_current_round(), cooldown=True)
            return False

        return _try_finalize_build(state, ct)

    # Adjacent — place any reachable ring belts, then step toward ore.
    if in_action_range(my_pos, target):
        building = building_grid[tx][ty]
        if (
            building is not None
            and building.team == team
            and building.entity_type in TURRET_TYPES
        ):
            state._phase = PHASE_ROUTE
            return execute_route(state, ct, mm, my_pos)

        if DEBUG:
            print(f"[BH build] ADJ ore={target} tile={tile_grid[tx][ty]} my_pos={my_pos} cd={ct.get_action_cooldown()}")
        if tile_grid[tx][ty] == Environment.ORE_TITANIUM:
            if _try_place_ring_conveyors(state, ct, mm, my_pos):
                return False
        elif DEBUG:
            print(f"[BH build] ADJ skip ring: tile={tile_grid[tx][ty]} != ORE_TITANIUM")

        # Ring complete + bot adjacent + ore tile clear of friendly turret →
        # we can finalize without ever standing on the ore. Only CONVEYORs
        # count — plain ROADs need to be replaced.
        ring_complete = True
        for d in CARDINAL:
            adj = target.add(d)
            ax = adj.x
            ay = adj.y
            if not (0 <= ax < width and 0 <= ay < height):
                continue
            adj_building = building_grid[ax][ay]
            if adj_building is None or adj_building.entity_type != EntityType.CONVEYOR:
                if DEBUG:
                    print(f"[BH build] ring incomplete at {adj}: {adj_building}")
                ring_complete = False
                break

        if ring_complete:
            return _try_finalize_build(state, ct)

        # Ring incomplete and no more belts placeable from here → step onto ore.
        direction = my_pos.direction_to(target)
        move_road_if_empty(ct, direction)
        return False

    # Pushed away
    if ct.can_destroy(state.target):
        ct.destroy(state.target)
    common_path(ct, mm, state.brain.pathing, state.target)
    return False
