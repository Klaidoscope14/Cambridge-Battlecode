"""Combat targeting and micro (point 6).

Decisions here are value-based, not reflexive: CC is saved for champions when
a PvP target exists, kiting is a tradeoff (only when hurt / out of melee
value), and camp focus uses last-hit-friendly lowest-HP targeting. All casts
are guarded; use() may return False (newly revealed obstruction) or raise.
"""
from __future__ import annotations

from cambc import Vec2

from config import CFG


def _in_attack_range(me, target) -> bool:
    try:
        return me.attack_tiles().is_set(target.position())
    except Exception:
        return False


def basic_attack(wv, target) -> bool:
    me = wv.me
    try:
        if (me.can_attack() and target.is_visible() and target.health() > 0
                and _in_attack_range(me, target)):
            me.attack(target)
            return True
    except Exception:
        pass
    return False


def _ability_in_range(me, ab, pos: Vec2) -> bool:
    try:
        return ab.valid_tiles().is_set(pos)
    except Exception:
        return False


def _cast(ab, target) -> bool:
    try:
        return bool(ab.use(target))
    except Exception:
        return False


def _smart_cast(me, ab, unit, pos) -> bool:
    """Cast on a unit or a ground tile depending on what the ability accepts.
    Some 'damage'/'cc' abilities are ground-targeted (e.g. area stuns) and
    reject a unit; others take the unit directly."""
    try:
        takes_unit = (ab.can_target_enemies() or ab.can_target_camps()
                      or ab.can_target_allies())
    except Exception:
        takes_unit = True
    try:
        takes_ground = ab.can_target_ground()
    except Exception:
        takes_ground = False
    if takes_unit:
        if _cast(ab, unit):
            return True
    if takes_ground:
        tile = _ground_tile_near(ab, pos)
        if tile is not None and _cast(ab, tile):
            return True
    return False


def _ground_tile_near(ab, pos: Vec2):
    """Pick a castable tile on/closest to pos for a ground ability."""
    try:
        tiles = ab.valid_tiles()
    except Exception:
        return None
    if tiles.is_set(pos):
        return pos
    best, best_d = None, 1 << 30
    for t in tiles.positions():
        d = t.chebyshev_distance(pos)
        if d < best_d:
            best_d, best = d, t
    return best


def cast_on_enemy(wv, enemy) -> bool:
    """Burst/CC an enemy champion in range. Prefers damage; will CC too."""
    me = wv.me
    try:
        epos = enemy.position()
    except Exception:
        return False
    for ab in me.abilities():
        if not ab.is_ready():
            continue
        if (ab.is_damage() or ab.is_cc() or ab.is_aoe_damage()) and _ability_in_range(me, ab, epos):
            if _smart_cast(me, ab, enemy, epos):
                return True
    return False


def attack_best_enemy(wv, aggressive=False) -> bool:
    """Engage an in-range enemy only when the objective warrants the trade."""
    targets = []
    for e in wv.enemies:
        try:
            if e.health() <= 0:
                continue
            targets.append((e, e.gem_count(), e.health() / e.max_health()))
        except Exception:
            continue
    if not targets:
        return False
    if not aggressive:
        # A farming champion should not abandon gem throughput for an even
        # poke. Only take a field fight that threatens a valuable bag or has
        # a likely finish, and do not solo-engage it while already hurt.
        valuable = any(gems >= 10 or hp <= 0.35 for _enemy, gems, hp in targets)
        nearby_allies = 0
        for ally in wv.allies:
            try:
                if ally.position().chebyshev_distance(wv.pos) <= CFG.THREAT_RADIUS:
                    nearby_allies += 1
            except Exception:
                continue
        if not valuable or (wv.hp_frac() < 0.50 and nearby_allies == 0):
            return False
    # Prefer loaded, then low HP.
    targets.sort(key=lambda t: (-t[1], t[2]))
    for e, _gems, _hp in targets:
        if cast_on_enemy(wv, e):
            return True
        if basic_attack(wv, e):
            return True
    return False


def winnable_camp(wv, camp) -> bool:
    """Feasibility check: can we kill this camp without dying? Clusters never
    fight back; tanky camps (elk/monolith) are only winnable with enough
    allied DPS sharing the fight. This both stops solo-suicide into elk and
    produces emergent grouping — champions wait near an elk until enough are
    present, then commit together."""
    try:
        chp = camp.health()
        cstr = camp.strength()
        mystr = wv.me.strength()
    except Exception:
        return True
    if chp <= 0 or cstr <= 0:   # gem/gold clusters are harmless
        return True
    if mystr <= 0:
        return False
    attackers = [(wv.me, mystr)]
    try:
        cpos = camp.position()
        for a in wv.allies:
            try:
                if a.position().chebyshev_distance(cpos) <= a.attack_range():
                    attackers.append((a, a.strength()))
            except Exception:
                pass
    except Exception:
        pass
    dps = sum(max(0.0, strength) for _champion, strength in attackers)
    if dps <= 0:
        return False
    turns = chp / dps
    # A hostile camp attacks the nearest champion; damage is not evenly split
    # across every ally merely standing nearby. Helpers shorten time-to-kill,
    # but only the nearest body must be able to absorb the full retaliation.
    try:
        my_distance = wv.pos.chebyshev_distance(cpos)
        nearest_distance = min(champ.position().chebyshev_distance(cpos)
                               for champ, _strength in attackers)
    except Exception:
        my_distance = nearest_distance = 0
    incoming = cstr * turns if my_distance <= nearest_distance else cstr * turns * 0.25
    return wv.hp > incoming * CFG.CAMP_FIGHT_SAFETY_MARGIN


def kite_threat(wv):
    """Return a dangerous camp to back away from before a ranged trade."""
    if not CFG.KITE_WHEN_RANGED or wv.hp_frac() > CFG.KITE_HP_FRACTION:
        return None
    try:
        if wv.me.attack_range() <= 1:
            return None
    except Exception:
        return None
    for camp in wv.camps:
        try:
            if (camp.strength() > 0
                    and wv.pos.chebyshev_distance(camp.position()) <= camp.attack_range()):
                return camp.position()
        except Exception:
            continue
    return None


def best_camp_in_range(wv, require_winnable=True):
    me = wv.me
    best, best_key = None, (2, 0, 1 << 30)
    for c in wv.camps:
        try:
            if not _in_attack_range(me, c):
                continue
            hp = c.health()
            if hp <= 0:
                continue
            if require_winnable and not winnable_camp(wv, c):
                continue
        except Exception:
            continue
        # Clear harmless sources before trading HP into hostile camps. Among
        # camps we can already hit, take the group with the largest gem payout
        # first; this is live camp metadata, not a stale map guess.
        try:
            danger = 0 if c.strength() <= 0 else 1
        except Exception:
            danger = 1
        try:
            gems = c.camp_group().gem_value()
        except Exception:
            gems = 0
        key = (danger, -gems, hp)
        if key < best_key:
            best_key, best = key, c
    return best


def fight_camp(wv) -> bool:
    """Attack/burst the best camp in range. Saves CC for PvP when enabled."""
    me = wv.me
    camp = best_camp_in_range(wv)
    if camp is None:
        return False
    try:
        cpos = camp.position()
    except Exception:
        return basic_attack(wv, camp)

    # Offensive abilities that target camps (skip CC if saving it for PvP).
    for ab in me.abilities():
        if not ab.is_ready():
            continue
        if ab.is_cc() and CFG.STUN_SAVE_FOR_PVP and _has_enemy_soon(wv):
            continue
        if (ab.is_damage() or ab.is_aoe_damage()) and _ability_in_range(me, ab, cpos):
            if _smart_cast(me, ab, camp, cpos):
                return True
    # Attack-reset: ranged double-tap or melee extra swing.
    for ab in me.abilities():
        if ab.is_ready() and ab.is_attack_reset() and not me.can_attack():
            _cast(ab, None)
            break
    return basic_attack(wv, camp)


def maybe_support(wv) -> bool:
    """Opportunistic heal of the lowest ally / self-shield when threatened."""
    me = wv.me
    for ab in me.abilities():
        if not ab.is_ready():
            continue
        if ab.is_heal() and ab.can_target_allies():
            target = _lowest_hurt_ally(wv, ab)
            if target is not None and _cast(ab, target):
                return True
        if ab.is_shield() and wv.hp_frac() < 0.75 and (wv.enemies or best_camp_in_range(wv)):
            if _cast(ab, None):
                return True
    return False


def _lowest_hurt_ally(wv, ab):
    best, best_frac = None, 0.85
    for a in wv.allies:
        try:
            frac = a.health() / a.max_health()
            if frac < best_frac and _ability_in_range(wv.me, ab, a.position()):
                best_frac, best = frac, a
        except Exception:
            continue
    return best


def _has_enemy_soon(wv) -> bool:
    return bool(wv.enemies)
