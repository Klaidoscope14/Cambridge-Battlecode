"""Economy: risk-aware banking + gold spend (point 1).

Banking is an expected-value decision, not a fixed threshold: we compare the
gems we'd secure now against the farm we forgo and the expected-loss of
carrying, centred on the probability the bag actually gets deposited. Shopping
buys toward a role-appropriate emblem, endgame-aware.
"""
from __future__ import annotations

import math

import cambc

from config import CFG
from mapinfo import map_info
import champions


def carry_risk(wv, belief) -> float:
    """Probability-ish [0,1] that the carried bag is lost if we keep it."""
    n_vis = len(wv.enemies)
    n_near = 0
    for e in wv.enemies:
        try:
            if _safe_dist(wv.pos, e.position()) <= CFG.THREAT_RADIUS:
                n_near += 1
        except Exception:
            continue
    # inferred enemies add a little latent risk
    if CFG.USE_BELIEF:
        n_near += 0.5 * len(belief.enemies_within(wv.pos, CFG.THREAT_RADIUS))
    risk = CFG.RISK_PER_ENEMY_IN_VISION * n_vis + CFG.RISK_PER_ENEMY_NEAR * n_near
    if wv.hp_frac() < CFG.LOW_HP_FRACTION:
        risk *= (1.0 + CFG.RISK_LOW_HP_FACTOR)
    return max(0.0, min(1.0, risk))


def bank_pressure(wv, belief) -> float:
    """Net gems favouring banking now vs continuing to farm. >0 => bank."""
    carried = wv.gems
    if carried <= 0:
        return -1.0
    mi = map_info()
    altar = mi.nearest_safe_altar(wv.pos)
    if altar is None:
        return -1.0
    travel = _safe_dist(wv.pos, altar)
    channel = max(1, math.ceil(carried / 10.0))
    horizon = travel + channel

    rate = CFG.GEMS_PER_FARM_WINDOW / CFG.FARM_WINDOW_ROUNDS  # gems/round
    expected_loss = carried * carry_risk(wv, belief)
    forgone_farm = rate * horizon + CFG.BANK_TRAVEL_PENALTY_PER_TILE * travel

    # Securing the bag is worth `carried` only probabilistically vs loss; the
    # pressure is how much loss we avoid minus the farm we skip.
    return expected_loss - forgone_farm + CFG.BANK_BASE_URGENCY


def force_bank(wv) -> bool:
    if wv.gems >= CFG.BAG_PANIC_CEILING:
        return True
    if CFG.ENDGAME_FORCE_BANK and wv.gems > 0:
        try:
            have = cambc.global_submitted_gems(cambc.Team.ALLY)
            if have + wv.gems >= cambc.constants.WINNING_GEMS:
                return True
        except Exception:
            pass
    return False


def should_recall(wv, belief) -> bool:
    mi = map_info()
    if mi.ally_spawn.is_set(wv.pos):
        return False
    if wv.hp_frac() <= CFG.RECALL_HP_FRACTION_SAFE:
        return True
    unsafe = len(wv.enemies) > 0 or belief.danger_at(wv.pos)
    if wv.hp_frac() <= CFG.RECALL_HP_FRACTION and unsafe and wv.gems == 0:
        return True
    return False


# ---- shopping -------------------------------------------------------------
_STAT_BY_TYPE = {
    cambc.ChampionType.RYTH: "HEALTH",      # HP->STR passive
    cambc.ChampionType.VESPER_VALE: "STRENGTH",
    cambc.ChampionType.VENDETTA: "STRENGTH",
    cambc.ChampionType.CASSI: "FOCUS",
    cambc.ChampionType.ISSAC: "STRENGTH",
    cambc.ChampionType.STELLAR: "FOCUS",
    cambc.ChampionType.PRISM: "FOCUS",
    cambc.ChampionType.MARCELLA: "STRENGTH",
    cambc.ChampionType.WILLOW: "FOCUS",
    cambc.ChampionType.REN: "STRENGTH",
    cambc.ChampionType.VARG: "STRENGTH",
    cambc.ChampionType.TAVI: "FOCUS",
}


def _family_for(role, ctype) -> str:
    if ctype in (cambc.ChampionType.VESPER_VALE, cambc.ChampionType.TAVI):
        return "TREASURE"
    if role == champions.ROLE_BRUISER:
        return "DURABILITY"
    if role == champions.ROLE_SUPPORT:
        return "POWER"
    return "POWER"


def buy_items(wv, role) -> bool:
    me = wv.me
    try:
        ctype = me.champion_name()
    except Exception:
        return False
    stat = _STAT_BY_TYPE.get(ctype, "STRENGTH")
    family = _family_for(role, ctype)
    name = f"{family}_SHARD_OF_{stat}"
    try:
        item = getattr(cambc.ItemType, name)
    except Exception:
        item = cambc.ItemType.POWER_SHARD_OF_STRENGTH
    cost = item.cost()
    if cost <= 0:
        return False
    count = me.gold_count() // cost
    if count >= 1 and me.can_buy(item, count):
        try:
            me.buy(item, count)
            return True
        except Exception:
            return False
    return False


def _safe_dist(a, b) -> int:
    return a.chebyshev_distance(b)
