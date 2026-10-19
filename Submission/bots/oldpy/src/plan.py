"""Draft-memory plan (point 6): static opening strategy, written once.

The draft turn has full vision and 10x fuel, so it bakes the team composition
and a small strategy code into the 1024-byte draft memory. Gameplay bots read
it once; dynamic coordination uses the 8-byte live memory instead. Lifetimes
are kept separate (point 6): this is immutable opening context, not live state.
"""
from __future__ import annotations

import cambc

_MAGIC = 0xBC

# strategy codes (map archetype → opening posture)
STRAT_BALANCED = 0
STRAT_TEMPO = 1      # altar-rich / open: race to farm+bank
STRAT_CONTROL = 2    # altar-scarce: contest/deny altars
STRAT_SKIRMISH = 3   # small/crowded: fight early


def encode(picks, strategy, symmetry) -> bytes:
    body = bytearray()
    body.append(_MAGIC)
    body.append(strategy & 0xFF)
    body.append(int(symmetry) & 0xFF)
    body.append(len(picks) & 0xFF)
    for p in picks:
        body.append(int(p) & 0xFF)
    return bytes(body)


def write(picks, strategy, symmetry):
    try:
        cambc.draft_memory.submit(encode(picks, strategy, symmetry))
    except Exception:
        pass


def read():
    """Return (picks, strategy, symmetry) or (None, STRAT_BALANCED, None)."""
    try:
        data = bytes(cambc.DraftMemoryBuffer())
    except Exception:
        return [], STRAT_BALANCED, None
    if len(data) < 4 or data[0] != _MAGIC:
        return [], STRAT_BALANCED, None
    strategy = data[1]
    symmetry = data[2]
    n = data[3]
    picks = list(data[4:4 + n]) if len(data) >= 4 + n else []
    return picks, strategy, symmetry
