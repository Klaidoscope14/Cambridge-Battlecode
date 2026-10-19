"""Tactical execution for strategic objectives.

This layer owns the live decisions that static scoring cannot know: which
altar is currently lockable, whether a camp is already occupied, and whether
the immediate combat state calls for a safe attack, peel, or reposition.
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

    if kind == O.IDLE:
        # Usually means a recalled champion is standing in spawn and healing.
        return

    if kind == O.CAPTURE:
        _capture_in_place(wv)
        return

    if kind == O.RECALL:
        _safe(lambda: wv.me.recall())
        return

    if kind == O.FLEE:
        nav.retreat(wv, obj.target, belief)
        if not belief.immediate_threat(wv):
            _safe(lambda: wv.me.recall())
        return

    if kind == O.SHOP:
        economy.buy_items(wv, role)
        _default_move(wv, belief)
        return

    if kind == O.WARD:
        if obj.target is not None and _safe(lambda: wv.me.place_ward(obj.target)):
            return

    # A lock cancels an enemy's bank channel. It is more valuable than a
    # speculative camp hit when we can see the attempted tribute.
    if kind in (O.FARM, O.GANK, O.DEFEND, O.EXPLORE) and _try_lock_enemy_tribute(wv):
        return

    # Passive field combat should only take an unusually good trade. Gank and
    # defend explicitly opt into an aggressive engage below.
    if kind in (O.FARM, O.EXPLORE) and CFG.USE_GANKING:
        if combat.attack_best_enemy(wv, aggressive=False):
            return
    combat.maybe_support(wv)

    if kind == O.BANK:
        _do_bank(wv, belief, obj.target)
        return

    if kind in (O.GANK, O.DEFEND):
        if combat.attack_best_enemy(wv, aggressive=True):
            return
        if obj.target is not None:
            nav.move_towards_goals(wv, _single(obj.target), belief)
            return

    # FARM / EXPLORE / fallback.
    camp_threat = combat.kite_threat(wv)
    if camp_threat is not None:
        nav.retreat(wv, camp_threat, belief)
        return
    if combat.fight_camp(wv):
        return
    if _capture_in_place(wv):
        return
    _do_farm(wv, belief, obj.target)


def _try_lock_enemy_tribute(wv) -> bool:
    """Spend an altar lock only to interrupt a visible enemy channel."""
    try:
        lock = wv.me.consumables()[int(cambc.ConsumableType.ALTAR_LOCK)]
        if lock.count() <= 0:
            return False
    except Exception:
        return False
    for enemy in wv.enemies:
        try:
            if not enemy.is_submitting_gems():
                continue
            epos = enemy.position()
        except Exception:
            continue
        for altar in map_info().altars:
            try:
                if (epos.chebyshev_distance(altar) <= _submit_range()
                        and wv.pos.chebyshev_distance(altar) <= CFG.ALTAR_LOCK_RANGE):
                    return _safe(lambda altar=altar: lock.use(altar))
            except Exception:
                continue
    return False


# ---- banking -------------------------------------------------------------
def _do_bank(wv, belief, preferred_altar):
    me = wv.me
    rng = _submit_range()
    altars = list(map_info().altars)
    if not altars:
        return

    def rank(altar):
        locked = _enemy_locked(wv, altar)
        dangerous = False
        try:
            dangerous = belief.danger_at(altar)
        except Exception:
            pass
        preferred_bonus = -2.0 if altar == preferred_altar else 0.0
        return (wv.pos.chebyshev_distance(altar)
                + (CFG.BANK_LOCKED_ALTAR_PENALTY if locked else 0.0)
                + (CFG.BANK_ALTAR_DANGER_PENALTY if dangerous else 0.0)
                + preferred_bonus)

    ranked = sorted(altars, key=rank)
    # Any altar lock blocks a submission.  An enemy lock can be attacked when
    # it is in range; an allied lock must simply be avoided until it expires.
    for altar in ranked:
        if wv.pos.chebyshev_distance(altar) <= rng:
            if _has_altar_lock(altar):
                if _enemy_locked(wv, altar):
                    if _clear_enemy_lock(me, altar):
                        return
                continue
            elif _safe(lambda altar=altar: me.submit_gems(altar)):
                return

    unlocked = [altar for altar in ranked if not _has_altar_lock(altar)]
    # Walking toward an altar which is currently locked only creates a
    # stationary, vulnerable carrier.  Wait safely if every visible altar is
    # unavailable; the next turn refreshes the dynamic lock snapshot.
    if not unlocked:
        return
    goals = Bitboard()
    for altar in unlocked:
        goals |= tiles_around(altar, rng)
    if not goals.is_empty() and nav.move_towards_goals(wv, goals, belief):
        return
    _default_move(wv, belief)


def _enemy_locked(wv, altar):
    try:
        return any(lock.position() == altar for lock in wv.enemy_locks)
    except Exception:
        return False


def _has_altar_lock(altar):
    try:
        return cambc.vision.has_altar_lock(altar)
    except Exception:
        return False


def _clear_enemy_lock(me, altar):
    try:
        lock = cambc.vision.altar_lock_at(altar)
        if me.attack_tiles().is_set(altar):
            me.attack(lock)
            return True
    except Exception:
        pass
    return False


# ---- farming and capture -------------------------------------------------
def _do_farm(wv, belief, target):
    # A broad set lets the distance field choose the nearest viable camp.  It
    # is deliberately preferable to walking across the map to a stale lane
    # assignment when another gem camp has just become available nearby.
    goals = _farm_goals(wv)
    if goals.is_empty():
        goals = _farm_goals(wv, strict=False)
    if not goals.is_empty():
        if nav.move_towards_goals(wv, goals, belief):
            combat.fight_camp(wv)


def _capture_in_place(wv) -> bool:
    """Keep a champion on a cleared group's capture tile."""
    from cambc import game_map
    for group in game_map.camp_groups():
        try:
            if not isinstance(group.state(), game_map.CampGroupRewardAvailable):
                continue
            tiles = group.spawn_tiles()
            if not tiles.is_set(wv.pos):
                continue
            return True
        except Exception:
            continue
    return False


def _farm_goals(wv, strict=True, target=None) -> Bitboard:
    """Spawn tiles of farmable, unoccupied groups.

    Strict goals are gem camps without tanky elk/monolith groups. The fallback
    permits those groups when the easy economy is exhausted.
    """
    from cambc import game_map
    goals = Bitboard()
    groups = None
    if target is not None:
        info = map_info().camp_for_centroid(target)
        if info is not None:
            groups = [info.group]
    for group in groups if groups is not None else game_map.camp_groups():
        try:
            spawn_tiles = group.spawn_tiles()
            # Camp state is only readable when at least one spawn tile is in
            # vision. Unseen groups must remain navigation goals; treating an
            # API visibility error as "skip" made the old bot wander once it
            # lost sight of its current camps.
            if not (spawn_tiles & wv.visible).is_empty():
                if isinstance(group.state(), game_map.CampGroupRespawning):
                    continue
            if _occupied_by_ally(wv, group):
                continue
            if strict:
                if group.gem_value() <= 0:
                    continue
                if any(camp.is_monolith() or camp.is_elk() for camp in group.camps()):
                    continue
            goals |= spawn_tiles
        except Exception:
            continue
    return goals


def _occupied_by_ally(wv, group) -> bool:
    """Do not funnel into a farm group a visible teammate already covers."""
    try:
        tiles = group.spawn_tiles()
        positions = list(tiles.positions())
        centroid = positions[0] if positions else None
        try:
            spread_out = cambc.draft.team_size() <= CFG.FARM_DECONFLICT_MAX_TEAM_SIZE
        except Exception:
            spread_out = False
        for ally in wv.allies:
            apos = ally.position()
            if tiles.is_set(apos):
                return True
            if (spread_out and centroid is not None
                    and apos.chebyshev_distance(centroid) <= CFG.FARM_ALLY_EXCLUSION_RADIUS):
                return True
    except Exception:
        pass
    return False


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
        return fn() is not False
    except Exception:
        return False
