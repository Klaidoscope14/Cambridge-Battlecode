"""Layer C — tactical execution (point 2).

Turns the chosen Objective into concrete, legal SDK actions. Opportunistic
value (attacking a loaded/low enemy already in range) is taken before moving
on most objectives. Each action is guarded; a False/raise falls through to a
movement fallback so the turn is never wasted.
"""
from __future__ import annotations

import cambc
from cambc import Bitboard

from config import CFG
import objective as O
import combat
import economy
import nav
from mapinfo import map_info
from util import tiles_around


def execute(obj, wv, belief, role) -> None:
    kind = obj.kind

    if kind == O.RECALL:
        _safe(lambda: wv.me.recall())
        return

    if kind == O.FLEE:
        # disengage; recall opportunistically if we got clear this step
        nav.retreat(wv, obj.target, belief)
        if not belief.immediate_threat(wv):
            _safe(lambda: wv.me.recall())
        return

    if kind == O.SHOP:
        economy.buy_items(wv, role)
        # after shopping we may still want to act; fall through to farm
        _default_move(wv, belief)
        return

    if kind == O.WARD:
        if obj.target is not None and _safe(lambda: wv.me.place_ward(obj.target)):
            return
        # couldn't ward; fall through

    # Opportunistic combat (steal/last-hit) for field objectives.
    if kind in (O.FARM, O.GANK, O.DEFEND, O.EXPLORE):
        if CFG.USE_GANKING and combat.attack_best_enemy(wv):
            return
    combat.maybe_support(wv)

    if kind == O.BANK:
        _do_bank(wv, belief, obj.target)
        return

    if kind == O.GANK or kind == O.DEFEND:
        if combat.attack_best_enemy(wv):
            return
        if obj.target is not None:
            nav.move_towards_goals(wv, _single(obj.target), belief)
            return

    # FARM / EXPLORE / fallback
    if combat.fight_camp(wv):
        return
    if _capture_in_place(wv):
        return
    _do_farm(wv, belief, obj.target)


# ---- sub-executors --------------------------------------------------------
def _do_bank(wv, belief, altar):
    me = wv.me
    rng = _submit_range()
    mi = map_info()
    # Which altars to consider: the specific emergency target, else safe ones,
    # else any altar (contested maps may have no "safe" altar reachable).
    candidates = [altar] if altar is not None else list(mi.safe_altars)
    if not candidates:
        candidates = list(mi.altars)
    # tribute if already in range of a usable altar
    for a in candidates:
        if wv.pos.chebyshev_distance(a) <= rng and not cambc.vision.has_altar_lock(a):
            if _safe(lambda: me.submit_gems(a)):
                return
    # otherwise approach
    goals = Bitboard()
    for a in candidates:
        if cambc.vision.has_altar_lock(a):
            continue
        goals |= tiles_around(a, rng)
    if not goals.is_empty():
        nav.move_towards_goals(wv, goals, belief)
    else:
        _default_move(wv, belief)


def _do_farm(wv, belief, target):
    # Head to the nearest worthwhile camp (gem-bearing, non-tanky). NOTE: a
    # greedy champion->camp assignment (bipartite matching) was tried here to
    # spread champions and avoid dogpiling, but measured WORSE — overflow
    # champions got sent on long treks that cost more than crowding saved,
    # losing both map wins. Nearest-camp routing is better for this bot's
    # bottlenecks (carry-death + travel), so it was reverted.
    goals = _farm_goals(wv)
    if goals.is_empty():
        goals = _farm_goals(wv, strict=False)
    if not goals.is_empty():
        if nav.move_towards_goals(wv, goals, belief):
            combat.fight_camp(wv)
            return
    if target is not None:
        nav.move_towards_goals(wv, _single(target), belief)


def _capture_in_place(wv) -> bool:
    """If we're standing on a cleared group's spawn tile, stay to capture."""
    from cambc import game_map
    for g in game_map.camp_groups():
        try:
            if not isinstance(g.state(), game_map.CampGroupRewardAvailable):
                continue
            if g.spawn_tiles().is_set(wv.pos):
                return True  # occupy and wait (do nothing this turn)
        except Exception:
            continue
    return False


def _farm_goals(wv, strict=True) -> Bitboard:
    """Spawn tiles of farmable groups. strict => gem-bearing, non-tanky
    (best gem-race targets); non-strict => any non-respawning group (fallback,
    where tanky elk/monoliths get cleared with grouped allies)."""
    from cambc import game_map
    goals = Bitboard()
    for g in game_map.camp_groups():
        try:
            if isinstance(g.state(), game_map.CampGroupRespawning):
                continue
            if strict:
                if g.gem_value() <= 0:
                    continue
                # skip tanky camps (monolith, elk) as primary routing targets:
                # poor gems-per-effort and deadly to solo. They are still
                # cleared via the non-strict fallback (with the winnable-fight
                # gate forcing champions to group up first). Flip this to
                # `is_monolith` only if A/B vs real ladder opponents prefers it.
                if any(c.is_monolith() or c.is_elk() for c in g.camps()):
                    continue
            goals |= g.spawn_tiles()
        except Exception:
            continue
    return goals


def _default_move(wv, belief):
    goals = _farm_goals(wv)
    if not goals.is_empty():
        nav.move_towards_goals(wv, goals, belief)


def _single(pos) -> Bitboard:
    bb = Bitboard()
    try:
        bb.set(pos, True)
    except Exception:
        pass
    return bb


def _submit_range() -> int:
    try:
        return cambc.constants.SUBMIT_GEMS_RANGE
    except Exception:
        return 1


def _safe(fn) -> bool:
    try:
        r = fn()
        return r is not False
    except Exception:
        return False
