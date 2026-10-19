"""Draft brain (point 4): explainable, hypothesis-driven champion scoring.

Runs once per draft round (10x fuel, full vision). Scores each available pick
from champion priors, tilted by map geometry (point 3) and the enemy's
revealed picks (counter-draft), with team-fit to avoid role overlap. Picks the
best and records the comp + a map strategy code into draft memory (point 6).
All weights are priors in config, meant to be re-weighted by self-play.
"""
from __future__ import annotations

import cambc

from config import CFG
import champions
import plan
CD = cambc.ChampionDraft


def _strategy(mi):
    n_altars = len(mi.altars)
    area = mi.width * mi.height
    if n_altars <= 2:
        return plan.STRAT_CONTROL
    if area <= 1100 and mi.team_size >= 5:
        return plan.STRAT_SKIRMISH
    if n_altars >= 10 or mi.open_frac > 0.9:
        return plan.STRAT_TEMPO
    return plan.STRAT_BALANCED


def _feature_mult(strategy):
    base = dict(clear=1.0, econ=1.0, mobility=1.0, sustain=1.0, control=1.0, survive=1.0)
    if strategy == plan.STRAT_TEMPO:
        base.update(clear=1.3, econ=1.3, mobility=1.25)
    elif strategy == plan.STRAT_CONTROL:
        base.update(control=1.4, survive=1.3, sustain=1.15)
    elif strategy == plan.STRAT_SKIRMISH:
        base.update(control=1.3, clear=1.2, survive=1.25)
    return base


def _geometry_mult(mi, mult):
    # large / walled maps reward mobility; bushy maps reward control (ambush)
    area = mi.width * mi.height
    if area >= 4000:
        mult["mobility"] *= 1.2
    if mi.wall_frac > 0.06:
        mult["mobility"] *= 1.15
    if mi.bush_frac > 0.08:
        mult["control"] *= 1.15
    if mi.open_frac > 0.95:
        mult["clear"] *= 1.1   # open sightlines favour ranged clear
    return mult


_DW = {
    "clear": CFG.DW_CLEAR, "econ": CFG.DW_ECON, "mobility": CFG.DW_MOBILITY,
    "sustain": CFG.DW_SUSTAIN, "control": CFG.DW_CONTROL, "survive": CFG.DW_SURVIVE,
}


def _base_score(pick, mult):
    f = champions.features(pick)
    return sum(_DW[k] * f[k] * mult[k] for k in f)


def _team_fit(pick, our_roles):
    role = champions.role_of(pick)
    same = our_roles.count(role)
    fit = 0.0
    # cover missing essential roles
    if role == champions.ROLE_SUPPORT and champions.ROLE_SUPPORT not in our_roles:
        fit += 0.6
    if role == champions.ROLE_BRUISER and champions.ROLE_BRUISER not in our_roles:
        fit += 0.4
    # penalise 3rd+ of a role
    if same >= 2:
        fit -= 0.7 * (same - 1)
    # C&I adds two fragile bodies under one draft slot. It is powerful with a
    # frontline/peel plan, but a brittle blind first pick in the old scorer.
    if pick == CD.CASSI_AND_ISSAC:
        if champions.ROLE_BRUISER not in our_roles:
            fit -= 0.30
        if champions.ROLE_SUPPORT not in our_roles:
            fit -= 0.25
    return CFG.DW_TEAM_FIT * fit


def _counter(pick, enemy_picks):
    fl = champions.flags(pick)
    bonus = 0.0
    enemy_stuns = sum(1 for e in enemy_picks if champions.flags(_as_cd(e)).get("stun"))
    if enemy_stuns >= 2 and fl.get("immune"):
        bonus += 0.8
    if enemy_stuns >= 2:
        bonus += 0.1 * champions.features(pick)["survive"]
    if any(_as_cd(enemy) == CD.CASSI_AND_ISSAC for enemy in enemy_picks):
        # Two squishy linked champions reward splash and reliable control.
        if fl.get("aoe"):
            bonus += 0.35
        if fl.get("stun"):
            bonus += 0.20
    return CFG.DRAFT_COUNTER_WEIGHT * bonus


def _as_cd(v):
    return v  # ChampionDraft ints


def play():
    # Draft fuel is shared across the complete drafting sequence.  Constructing
    # two whole-map distance fields here caused the bot to time out on larger
    # maps, leaving random picks.  Gameplay performs geometry analysis once
    # per champion where it has a normal turn budget; drafting must be cheap
    # and deterministic so it always completes.
    mi = None
    strategy = plan.STRAT_BALANCED

    try:
        ours = list(cambc.draft.current_draft(cambc.Team.ALLY))
    except Exception:
        ours = []
    try:
        theirs = list(cambc.draft.current_draft(cambc.Team.ENEMY))
    except Exception:
        theirs = []

    taken = {int(pick) for pick in [*ours, *theirs]}
    available = [pick for pick in champions.ALL_PICKS if int(pick) not in taken]
    if not available:
        return

    mult = _feature_mult(strategy)

    our_roles = [champions.role_of(_as_cd(p)) for p in ours]

    best, best_score = available[0], -1e9
    for pick in available:
        s = _base_score(pick, mult) + _team_fit(pick, our_roles) + _counter(pick, theirs)
        if s > best_score:
            best_score, best = s, pick

    try:
        cambc.draft.pick(best)
    except Exception:
        return

    # Record the (growing) comp + strategy for gameplay bots.
    try:
        final = [int(x) for x in cambc.draft.current_draft(cambc.Team.ALLY)]
    except Exception:
        final = [int(best)]
    plan.write(final, strategy, 2)
