"""Layer A — hard constraints (point 2).

Legality and non-negotiable survival. Returns an emergency Objective that
overrides Layer B, or None if there is no hard constraint and normal objective
selection should run. Also reports whether we can act at all this turn.
"""
from __future__ import annotations

import objective as O
import economy
from config import CFG
from mapinfo import map_info

def can_act(wv) -> bool:
    me = wv.me
    try:
        if not me.is_alive():
            return False
        if me.is_recalling() or me.is_submitting_gems() or me.is_teleporting():
            return False
        if not me.can_move() and not me.can_attack() and not me.can_cast():
            return False
    except Exception:
        return False
    return True


def emergency(wv, belief):
    """Return an overriding Objective, or None."""
    # Forced banking (panic bag / endgame win) beats everything.
    if economy.force_bank(wv):
        return O.Objective(O.BANK, score=1e6, emergency=True)

    on_spawn = map_info().ally_spawn.is_set(wv.pos)
    # Recall only heals while we remain in the spawn region.  The old bot
    # immediately walked back out at low HP, throwing away the recall turn.
    if on_spawn and wv.hp_frac() < 0.99:
        return O.Objective(O.IDLE, score=1e5, emergency=True)

    # Shop as soon as it is legal.  This includes Tavi's field shop; can_buy
    # validates that special case instead of guessing from position.
    if economy.should_shop(wv):
        return O.Objective(O.SHOP, score=9.5e4, emergency=True)

    # Survival. Only CARRIED GEMS are worth protecting: dying empty-handed
    # just respawns us at full HP (a free heal) and camps don't chase, so
    # fleeing while empty is wasted farm uptime. Therefore:
    #   - carrying + hurt  -> go BANK (purposeful retreat to an altar), or
    #                          recall when there's no altar to reach.
    #   - empty + about to be killed by an enemy CHAMPION -> brief flee (a
    #                          pointless death also donates 50 gold), else tank.
    low = wv.hp_frac()
    carrying = wv.gems > 0
    champ_threat = belief.champion_threat(wv)
    threatened = champ_threat or belief.immediate_threat(wv)

    if not on_spawn:
        if carrying:
            if low <= CFG.RECALL_HP_FRACTION and threatened:
                altar = map_info().nearest_altar(wv.pos)
                if altar is not None:
                    return O.Objective(O.BANK, altar, score=1e5, emergency=True)
                return O.Objective(O.RECALL, score=1e5, emergency=True)
            if low <= CFG.RECALL_HP_FRACTION_SAFE:
                return O.Objective(O.RECALL, score=1e5, emergency=True)
        else:
            if champ_threat and low <= CFG.RECALL_HP_FRACTION_SAFE:
                return O.Objective(O.FLEE, belief.nearest_enemy_pos(wv),
                                   score=1e5, emergency=True)

    # Recall to spend a big gold stack when already safe at home-ish.
    if economy.should_recall(wv, belief):
        return O.Objective(O.RECALL, score=9e4, emergency=True)

    return None
