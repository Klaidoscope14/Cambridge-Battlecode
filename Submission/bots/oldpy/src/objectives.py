"""Layer B — strategic objective arbitration (point 2).

Enumerate candidate objectives and score each by expected strategic value,
tilted by champion role. Returns a ranked list; the brain applies commitment
and hysteresis before handing the winner to Layer C.
"""
from __future__ import annotations

import math

import cambc
from cambc import game_map

from config import CFG
import objective as O
import economy
import champions
import comms
import plan
from mapinfo import map_info


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _role_mult(role, kind):
    # role affinity multipliers (priors)
    table = {
        champions.ROLE_CARRY:    {O.FARM: 1.2, O.BANK: 1.2, O.GANK: 0.8, O.DEFEND: 0.8, O.WARD: 0.7},
        champions.ROLE_ASSASSIN: {O.FARM: 0.9, O.BANK: 1.0, O.GANK: 1.5, O.DEFEND: 1.0, O.WARD: 1.1},
        champions.ROLE_BRUISER:  {O.FARM: 1.0, O.BANK: 1.0, O.GANK: 1.0, O.DEFEND: 1.3, O.WARD: 0.9},
        champions.ROLE_SUPPORT:  {O.FARM: 0.7, O.BANK: 1.0, O.GANK: 0.7, O.DEFEND: 1.4, O.WARD: 1.4},
    }
    return table.get(role, {}).get(kind, 1.0)


def _strategy_mult(strategy, kind):
    """Small, explicit use of the opening plan written during the draft."""
    table = {
        plan.STRAT_TEMPO: {
            O.FARM: 1.15, O.BANK: 1.15, O.GANK: 0.90, O.DEFEND: 0.85,
        },
        plan.STRAT_CONTROL: {
            O.FARM: 0.95, O.BANK: 1.12, O.GANK: 1.12, O.DEFEND: 1.30,
        },
        plan.STRAT_SKIRMISH: {
            O.FARM: 0.92, O.BANK: 1.00, O.GANK: 1.28, O.DEFEND: 1.24,
        },
    }
    return table.get(strategy, {}).get(kind, 1.0)


def _best_farm(wv, lane_slot=0, lane_count=1):
    """Choose a profitable camp while spreading the initial team over lanes.

    Camp ownership is static map information; camp state and nearby allies are
    live information.  The latter prevents three bodies walking to one capture
    tile, where extra bodies neither shorten the capture nor increase reward.
    """
    mi = map_info()
    best_score, best_target = 0.0, None
    lane_count = max(1, lane_count)
    for index, ci in enumerate(mi.camps):
        try:
            st = ci.group.state()
            if isinstance(st, game_map.CampGroupRespawning):
                continue
        except Exception:
            pass
        if ci.gem_value <= 0 and ci.gold_value <= 0:
            continue
        # Gem clusters yield the same strategic resource without retaliation.
        # Make them the default lane target; wolves/elk remain the fallback
        # after the safe map economy is exhausted.
        if ci.tanky:
            continue
        d = wv.pos.chebyshev_distance(ci.centroid)
        value = ci.gem_value * 1.0 + ci.gold_value * 0.12
        # Gems per clear-effort: low-HP gem clusters win over tanky wolves/elk.
        effort = ci.total_hp / 200.0 + d / 3.0 + 3.0
        own_bonus = 1.15 if ci.owner <= 0 else 0.9
        desired_lane = index % lane_count
        lane_mult = CFG.FARM_LANE_BONUS if desired_lane == lane_slot else CFG.FARM_LANE_OFF_PENALTY
        ally_crowd = 0
        for ally in wv.allies:
            try:
                if ally.position().chebyshev_distance(ci.centroid) <= 3:
                    ally_crowd += 1
            except Exception:
                continue
        crowd_mult = 1.0 / (1.0 + CFG.FARM_ALLY_CROWD_PENALTY * ally_crowd)
        safety_bonus = 1.9 if ci.harmless else 0.55
        score = own_bonus * lane_mult * crowd_mult * safety_bonus * value / effort
        if score > best_score:
            best_score, best_target = score, ci.centroid
    return best_score, best_target


def enumerate_objectives(wv, belief, role, strategy=plan.STRAT_BALANCED,
                         lane_slot=0, lane_count=1):
    out = []

    # Face-tank camps when EMPTY-handed (respawn heals full, camps don't
    # chase). But when CARRYING gems, don't fight hurt — a death loses the
    # whole bag, so disengage/bank well before dying.
    hp = wv.hp_frac()
    if wv.gems == 0 or hp > 0.40:
        hp_farm_mult = 1.0
    elif hp > 0.25:
        hp_farm_mult = 0.55
    else:
        hp_farm_mult = 0.2

    # FARM
    farm_score, farm_target = _best_farm(wv, lane_slot, lane_count)
    if farm_target is not None:
        s = (CFG.W_FARM * (0.2 + farm_score) * _role_mult(role, O.FARM)
             * _strategy_mult(strategy, O.FARM) * hp_farm_mult)
        out.append(O.Objective(O.FARM, farm_target, s))

    # Capture ticks do not speed up with extra champions. A body already on a
    # cleared camp must retain this job rather than being pulled to a nearby
    # farm target by ordinary objective arbitration.
    if _capture_here(wv):
        out.append(O.Objective(O.CAPTURE, wv.pos, CFG.W_CAPTURE))

    # BANK. Carried gems are only worth anything once tributed and are lost on
    # death, so banking urgency climbs with the bag. EV pressure fine-tunes on
    # top (how worth the detour is right now), but a non-trivial bag should
    # usually beat farming — hoarding loses games.
    if wv.gems > 0:
        # Bank the trip while still healthy: urgency grows with bag size so a
        # real bag (~18+) beats farming and we reach the altar alive, instead
        # of fighting on until a camp kills us carrying it (the far-altar maps
        # lose whole bags to this). Small bags keep farming; EV fine-tunes.
        bag_weight = min(1.3, wv.gems / 18.0)
        try:
            pressure = economy.bank_pressure(wv, belief) if CFG.USE_EV_BANKING else 0.0
        except Exception:
            pressure = 0.0
        s = (CFG.W_BANK * (bag_weight + 0.4 * _sigmoid(pressure))
             * _role_mult(role, O.BANK) * _strategy_mult(strategy, O.BANK))
        # A full camp payout should not lose to the capture/farm score while
        # the champion is still standing in danger.  This is below the hard
        # emergency ceiling but decisively wins normal arbitration.
        # Sparse-altar maps turn a 22+ gem bag into a long exposed return
        # trip.  Dense-altar maps can keep farming efficiently and bank on
        # ordinary EV pressure instead.
        if CFG.BANK_CONTINUOUS:
            s = max(s, CFG.W_BANK * 3.0)
        elif (wv.gems >= CFG.BANK_EARLY_BAG
                and len(map_info().altars) <= CFG.EARLY_BANK_ALTAR_LIMIT):
            s = max(s, CFG.W_BANK * 3.0)
        # Tactical execution ranks *all* altars with current locks/enemy
        # vision.  Keeping this target unset avoids committing to an altar
        # that became locked after static map analysis.
        out.append(O.Objective(O.BANK, None, s))

    # GANK
    if CFG.USE_GANKING:
        tgt = belief.best_gank_target(wv)
        if tgt is not None:
            e, epos, egems, ehp = tgt
            d = wv.pos.chebyshev_distance(epos)
            val = (egems + (1.0 - ehp) * 25.0) / (d + 2.0)
            s = (CFG.W_GANK * _sigmoid(val - 1.0) * _role_mult(role, O.GANK)
                 * _strategy_mult(strategy, O.GANK))
            out.append(O.Objective(O.GANK, epos, s))

    # DEFEND: an ally carrier with an enemy nearby
    dtar = _defend_target(wv, belief)
    if dtar is not None:
        s = CFG.W_DEFEND * _role_mult(role, O.DEFEND) * _strategy_mult(strategy, O.DEFEND)
        out.append(O.Objective(O.DEFEND, dtar, s))

    # A fresh shared-memory signal is more valuable than a vague inferred
    # target: it is a concrete place where a teammate has current vision.
    hints = comms.read_hints(wv)
    if hints["enemy_carrier"] is not None:
        out.append(O.Objective(
            O.GANK, hints["enemy_carrier"],
            CFG.W_GANK * 1.35 * _role_mult(role, O.GANK) * _strategy_mult(strategy, O.GANK),
        ))
    if hints["enemy_contact"] is not None:
        contact = hints["enemy_contact"]
        if wv.pos.chebyshev_distance(contact) <= CFG.RALLY_MAX_DISTANCE:
            out.append(O.Objective(
                O.GANK, contact,
                CFG.W_GANK * CFG.RALLY_SCORE_MULTIPLIER
                * _role_mult(role, O.GANK) * _strategy_mult(strategy, O.GANK),
            ))
    if hints["help"] is not None and hints["help"] != wv.pos:
        out.append(O.Objective(
            O.DEFEND, hints["help"],
            CFG.W_DEFEND * 1.30 * _role_mult(role, O.DEFEND) * _strategy_mult(strategy, O.DEFEND),
        ))

    # SHOP
    if economy.should_shop(wv, role):
        out.append(O.Objective(O.SHOP, None, CFG.W_SHOP))

    # WARD
    if CFG.USE_WARDS and _can_ward(wv):
        spot = _ward_spot(wv)
        if spot is not None:
            out.append(O.Objective(O.WARD, spot, CFG.W_WARD * _role_mult(role, O.WARD)))

    # EXPLORE (baseline)
    out.append(O.Objective(O.EXPLORE, _explore_target(wv), CFG.W_EXPLORE))

    out.sort(key=lambda o: o.score, reverse=True)
    return out


def _defend_target(wv, belief):
    for a in wv.allies:
        try:
            if a.gem_count() <= 0:
                continue
            apos = a.position()
        except Exception:
            continue
        if wv.pos.chebyshev_distance(apos) > 10:
            continue
        for e in wv.enemies:
            try:
                if apos.chebyshev_distance(e.position()) <= CFG.THREAT_RADIUS:
                    return apos
            except Exception:
                continue
    return None


def _capture_here(wv):
    from cambc import game_map
    for group in game_map.camp_groups():
        try:
            tiles = group.spawn_tiles()
            if not (tiles.is_set(wv.pos)
                    and isinstance(group.state(), game_map.CampGroupRewardAvailable)):
                continue
            occupants = [wv.me]
            for ally in wv.allies:
                try:
                    if tiles.is_set(ally.position()):
                        occupants.append(ally)
                except Exception:
                    continue
            return int(wv.me) == min(int(champion) for champion in occupants)
        except Exception:
            continue
    return False


def _can_ward(wv):
    me = wv.me
    try:
        return me.ward_cooldown() == 0 and not me.ward_placement_tiles().is_empty()
    except Exception:
        return False


def _ward_spot(wv):
    """Ward toward the midline / a contested altar for information."""
    me = wv.me
    try:
        tiles = me.ward_placement_tiles()
    except Exception:
        return None
    mi = map_info()
    # bias toward the nearest contested altar, else enemy direction
    focus = None
    best_d = 1 << 30
    for a in mi.altars:
        if a in mi.safe_altars:
            continue
        d = wv.pos.chebyshev_distance(a)
        if d < best_d:
            best_d, focus = d, a
    if focus is None:
        try:
            focus = mi.enemy_spawn.positions()[0]
        except Exception:
            return None
    best, bd = None, 1 << 30
    for t in tiles.positions():
        d = t.chebyshev_distance(focus)
        if d < bd:
            bd, best = d, t
    return best


def _explore_target(wv):
    mi = map_info()
    return cambc.Vec2(mi.width // 2, mi.height // 2)
