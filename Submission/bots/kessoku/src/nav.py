"""Movement (points 3 & 5): shortest-path stepping with danger awareness.

Built on the engine's DistanceField/move_towards (no hand-rolled A*). Goals
are a Bitboard; we BFS outward from the goals around blocked tiles and take
the reachable step that reduces distance most, preferring steps that stay out
of the belief danger field when a safe step of equal progress exists.
"""
from __future__ import annotations

import cambc
from cambc import Bitboard, DistanceField

from mapinfo import map_info


def blocked_tiles(wv) -> Bitboard:
    mi = map_info()
    blocked = (mi.walls | mi.holes | mi.altars_bb | mi.enemy_spawn
               | cambc.vision.champion_tiles() | cambc.vision.camp_tiles()
               | cambc.vision.teleport_tiles())
    blocked.set(wv.pos, False)
    return blocked


def move_towards_goals(wv, goals: Bitboard, belief=None, avoid_danger=True) -> bool:
    """BFS outward from the goals around blocked tiles and take the reachable
    step that reduces distance most, preferring non-danger steps. The field
    stops us ADJACENT to occupied goal tiles (e.g. camps on their spawn),
    which me.move_towards() cannot do (it refuses occupied destinations)."""
    me = wv.me
    origin = wv.pos
    if not me.can_move() or goals.is_empty() or goals.is_set(origin):
        return False

    blocked = blocked_tiles(wv)
    reachable_goals = goals & (~blocked | cambc.vision.camp_tiles())
    if reachable_goals.is_empty():
        reachable_goals = goals

    field = DistanceField()
    field.compute_to(blocked & ~reachable_goals, reachable_goals,
                     _around(origin, 0), Bitboard())

    speed = me.base_stats().base_move_speed
    reach = blocked.reachable_tiles(origin, speed)
    candidates = [origin, *reach.positions()]

    def dist(p):
        try:
            return field.get(p)
        except Exception:
            return 1 << 30

    here = dist(origin)
    best = min(candidates, key=dist)
    best_d = dist(best)
    if best_d >= here:
        return False

    if avoid_danger and belief is not None:
        safe = [p for p in candidates
                if dist(p) <= best_d and not belief.danger_at(p)]
        if safe:
            best = min(safe, key=dist)

    if best == origin:
        return False
    try:
        return bool(me.move_absolute(best))
    except Exception:
        # destination became occupied; let the engine path there instead
        try:
            return bool(me.move_towards(best))
        except Exception:
            return False


def retreat(wv, threat_pos, belief) -> bool:
    """Step to the reachable tile that maximises distance from the threat,
    breaking ties toward our spawn and away from the danger field."""
    me = wv.me
    if not me.can_move():
        return False
    mi = map_info()
    blocked = blocked_tiles(wv)
    speed = me.base_stats().base_move_speed
    reach = [p for p in blocked.reachable_tiles(wv.pos, speed).positions()]
    if not reach:
        return False
    try:
        spawn = mi.ally_spawn.positions()[0]
    except Exception:
        spawn = wv.pos

    def score(p):
        away = p.chebyshev_distance(threat_pos) if threat_pos is not None else 0
        home = -p.chebyshev_distance(spawn)
        danger = -5 if (belief is not None and belief.danger_at(p)) else 0
        return (away * 3 + home + danger)

    best = max(reach, key=score)
    if threat_pos is not None and score(best) <= score(wv.pos):
        # can't get further; head home instead
        return move_towards_goals(wv, mi.ally_spawn, belief)
    try:
        return bool(me.move_absolute(best))
    except Exception:
        return move_towards_goals(wv, mi.ally_spawn, belief)


def flee(wv, belief) -> bool:
    """Step to the reachable tile furthest from danger / nearest spawn."""
    me = wv.me
    if not me.can_move():
        return False
    mi = map_info()
    # Retreat toward our spawn, away from danger.
    return move_towards_goals(wv, mi.ally_spawn, belief, avoid_danger=True)


def _around(center, radius) -> Bitboard:
    bb = Bitboard()
    bb.draw_chebyshev(center, radius)
    return bb
