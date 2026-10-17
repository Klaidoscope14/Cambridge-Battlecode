"""Champion priors (point 4).

Kit knowledge from the handbook, encoded as *tagged priors* — initial
feature estimates and role tags, NOT proven facts. Draft scoring combines
these with map features and enemy picks; self-play is meant to re-weight
them. Keyed by ChampionDraft index (0..10). CASSI_AND_ISSAC is one pick that
yields two bodies.

Feature axes (0..1): clear (camp-clear speed), econ (gold generation),
mobility, sustain (self/ally healing or shields), control (stuns/CC),
survive (effective tankiness / un-killability).
"""
from __future__ import annotations

import cambc

CD = cambc.ChampionDraft

# role tags steer in-match Layer-B weighting
ROLE_CARRY = "carry"      # farm + bank focus
ROLE_BRUISER = "bruiser"  # frontline + control
ROLE_ASSASSIN = "assassin"  # gank loaded enemies
ROLE_SUPPORT = "support"  # heal / peel / ward

# name, {features}, role, flags
_PRIORS = {
    CD.RYTH:            (dict(clear=.55, econ=.3, mobility=.3, sustain=.3, control=.85, survive=.8),
                         ROLE_BRUISER, dict(ranged=False, stun=True, aoe=True, heal=False, gold=False, immune=False)),
    CD.VESPER_VALE:     (dict(clear=.8, econ=.9, mobility=.75, sustain=.2, control=.2, survive=.5),
                         ROLE_CARRY, dict(ranged=True, stun=False, aoe=False, heal=False, gold=True, immune=False)),
    CD.VENDETTA:        (dict(clear=.95, econ=.5, mobility=.75, sustain=.2, control=.2, survive=.55),
                         ROLE_CARRY, dict(ranged=False, stun=False, aoe=False, heal=False, gold=False, immune=False)),
    CD.CASSI_AND_ISSAC: (dict(clear=.8, econ=.5, mobility=.7, sustain=.2, control=.75, survive=.35),
                         ROLE_ASSASSIN, dict(ranged=True, stun=True, aoe=False, heal=False, gold=False, immune=False)),
    CD.STELLAR:         (dict(clear=.95, econ=.4, mobility=.3, sustain=.1, control=.2, survive=.35),
                         ROLE_CARRY, dict(ranged=True, stun=False, aoe=True, heal=False, gold=False, immune=False)),
    CD.PRISM:           (dict(clear=.75, econ=.4, mobility=.3, sustain=.1, control=.8, survive=.3),
                         ROLE_ASSASSIN, dict(ranged=True, stun=True, aoe=True, heal=False, gold=False, immune=False)),
    CD.MARCELLA:        (dict(clear=.6, econ=.3, mobility=.3, sustain=.3, control=.8, survive=.9),
                         ROLE_BRUISER, dict(ranged=False, stun=True, aoe=False, heal=False, gold=False, immune=True)),
    CD.WILLOW:          (dict(clear=.45, econ=.4, mobility=.3, sustain=.95, control=.1, survive=.4),
                         ROLE_SUPPORT, dict(ranged=True, stun=False, aoe=False, heal=True, gold=False, immune=False)),
    CD.REN:             (dict(clear=.55, econ=.3, mobility=.7, sustain=.4, control=.75, survive=.7),
                         ROLE_BRUISER, dict(ranged=False, stun=True, aoe=False, heal=False, gold=False, immune=False)),
    CD.VARG:            (dict(clear=.85, econ=.4, mobility=.3, sustain=.6, control=.2, survive=.8),
                         ROLE_BRUISER, dict(ranged=False, stun=False, aoe=True, heal=False, gold=False, immune=False)),
    CD.TAVI:            (dict(clear=.6, econ=.85, mobility=.4, sustain=.2, control=.8, survive=.4),
                         ROLE_CARRY, dict(ranged=True, stun=True, aoe=False, heal=False, gold=True, immune=False)),
}

# Map ChampionDraft -> the ChampionType(s) its bodies use (for stat lookups).
DRAFT_TO_TYPES = {
    CD.RYTH: (cambc.ChampionType.RYTH,),
    CD.VESPER_VALE: (cambc.ChampionType.VESPER_VALE,),
    CD.VENDETTA: (cambc.ChampionType.VENDETTA,),
    CD.CASSI_AND_ISSAC: (cambc.ChampionType.CASSI, cambc.ChampionType.ISSAC),
    CD.STELLAR: (cambc.ChampionType.STELLAR,),
    CD.PRISM: (cambc.ChampionType.PRISM,),
    CD.MARCELLA: (cambc.ChampionType.MARCELLA,),
    CD.WILLOW: (cambc.ChampionType.WILLOW,),
    CD.REN: (cambc.ChampionType.REN,),
    CD.VARG: (cambc.ChampionType.VARG,),
    CD.TAVI: (cambc.ChampionType.TAVI,),
}

ALL_PICKS = list(_PRIORS.keys())


def features(pick) -> dict:
    return _PRIORS[pick][0]


def role_of(pick) -> str:
    return _PRIORS[pick][1]


def flags(pick) -> dict:
    return _PRIORS[pick][2]


def role_for_type(champ_type) -> str:
    """Role for an in-match champion given its ChampionType (reverse map)."""
    for pick, types in DRAFT_TO_TYPES.items():
        if champ_type in types:
            return role_of(pick)
    return ROLE_CARRY
