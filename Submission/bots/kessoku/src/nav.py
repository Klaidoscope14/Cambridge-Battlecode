"""Movement: cached static paths with live obstacle and danger handling.

The old code rebuilt a full DistanceField on every walking turn. That was
fuel-expensive and fragile when a planned destination was newly blocked. This
module caches fields for static terrain/goal masks, then chooses a legal live
step each turn and retries alternatives on a failed move.
"""
from __future__ import annotations

import cambc
from cambc import Bitboard, DistanceField

from config import CFG
from mapinfo import map_info


_FIELDS = {}
_FIELD_ORDER = []


def blocked_tiles(wv) -> Bitboard:
    mi = map_info()
    blocked = (mi.walls | mi.holes | mi.altars_bb | mi.enemy_spawn
               | cambc.vision.champion_tiles() | cambc.vision.camp_tiles()
               | cambc.vision.teleport_tiles())
    blocked.set(wv.pos, False)
    return blocked


def move_towards_goals(wv, goals: Bitboard, belief=None, avoid_danger=True,
                       avoid_camp_threats=True) -> bool:
    """Take a progressing legal step toward goals.

    Dynamic bodies are never put into a cached field. They are considered
    when choosing this turn's reachable tiles, which keeps the cache valid
    and lets us try a second move if hidden information invalidates the first.
    """
    me = wv.me
    origin = wv.pos
    if not me.can_move() or goals.is_empty() or goals.is_set(origin):
        return False

    blocked = blocked_tiles(wv)
    reachable_goals = goals & (~blocked | cambc.vision.camp_tiles())
    if reachable_goals.is_empty():
        reachable_goals = goals

    field = _field_for(reachable_goals)
    speed = me.base_stats().base_move_speed
    candidates = [origin, *blocked.reachable_tiles(origin, speed).positions()]

    if field is not None:
        def dist(p):
            try:
                return field.get(p)
            except Exception:
                return 1 << 30
    else:
        # Fuel-aware fallback: a small Chebyshev calculation is much cheaper
        # than constructing a new breadth-first field late in the turn.
        goal_positions = list(reachable_goals.positions())

        def dist(p):
            return min((p.chebyshev_distance(g) for g in goal_positions), default=1 << 30)

    here = dist(origin)
    progressing = [p for p in candidates if p != origin and dist(p) < here]
    if not progressing:
        return False

    progressing.sort(key=dist)
    safe = [p for p in progressing
            if not _dangerous(p, wv, belief, avoid_danger, avoid_camp_threats)]
    # If every forward move is unsafe, keep moving rather than idle next to a
    # camp/altar indefinitely; the shortest risky move is the least exposure.
    for step in (safe or progressing):
        try:
            if me.move_absolute(step):
                return True
        except Exception:
            # Failed moves do not consume movement. A hidden champion or
            # obstruction can make the best tile invalid; try the next one.
            continue
    return False


def _field_for(goals: Bitboard):
    try:
        key = bytes(goals.export_linear_buffer())
    except Exception:
        return None
    cached = _FIELDS.get(key)
    if cached is not None:
        _touch(key)
        return cached
    try:
        if cambc.fuel_remaining() < CFG.FUEL_PATH_COMPUTE_FLOOR:
            return None
    except Exception:
        pass
    try:
        static = map_info().blocked_static
        field = DistanceField()
        # Compute the complete static field once, then reuse it as champions
        # and camps move through the map.
        field.compute(static & ~goals, goals, Bitboard(), CFG.MAX_FIELD_DISTANCE)
    except Exception:
        return None
    _FIELDS[key] = field
    _FIELD_ORDER.append(key)
    while len(_FIELD_ORDER) > CFG.PATH_FIELD_CACHE_SIZE:
        old = _FIELD_ORDER.pop(0)
        _FIELDS.pop(old, None)
    return field


def _touch(key):
    try:
        _FIELD_ORDER.remove(key)
    except ValueError:
        pass
    _FIELD_ORDER.append(key)


def _dangerous(pos, wv, belief, avoid_danger, avoid_camp_threats):
    if avoid_danger and belief is not None:
        try:
            if belief.danger_at(pos):
                return True
        except Exception:
            pass
    if avoid_camp_threats:
        for camp in wv.camps:
            try:
                if (camp.strength() > 0
                        and pos.chebyshev_distance(camp.position()) <= camp.attack_range()):
                    return True
            except Exception:
                continue
    return False


def retreat(wv, threat_pos, belief) -> bool:
    """Step to the reachable tile furthest from threat and toward spawn."""
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
        return away * 3 + home + danger

    for step in sorted(reach, key=score, reverse=True):
        try:
            if me.move_absolute(step):
                return True
        except Exception:
            continue
    return move_towards_goals(wv, mi.ally_spawn, belief)

