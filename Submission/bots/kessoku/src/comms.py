"""Live team coordination over the 8-byte shared memory (point 6).

Deliberately tiny and unambiguous. Agents are mostly independent; this only
carries a couple of high-value, freshness-stamped hints (a spotted loaded
enemy to collapse on; an ally carrier needing help). Every read is validated
against SM_ROUND so stale intent is ignored. Last writer wins by design.
"""
from __future__ import annotations

import cambc
from config import CFG

_FRESH_ROUNDS = 6


def _read_all() -> bytes:
    try:
        buf = bytearray(cambc.shared_memory.size())
        cambc.shared_memory.read(0, buf)
        return bytes(buf)
    except Exception:
        return bytes(8)


def _w8(offset, value):
    try:
        cambc.shared_memory.write(offset, bytes([value & 0xFF]))
    except Exception:
        pass


def _w16(offset, value):
    try:
        cambc.shared_memory.write(offset, int(value & 0xFFFF).to_bytes(2, "little"))
    except Exception:
        pass


def publish(wv, belief):
    if not CFG.USE_COORDINATION:
        return
    _w16(CFG.SM_ROUND, wv.round)
    # Spotted a loaded enemy? share its tile for allies to collapse on.
    best = belief.best_gank_target(wv)
    if best is not None:
        e, epos, egems, ehp = best
        if egems >= 10:
            _w8(CFG.SM_ENEMY_CARRIER_X, _enc(epos.x))
            _w8(CFG.SM_ENEMY_CARRIER_Y, _enc(epos.y))
    # Am I a carrier in danger? ask for help.
    if wv.gems >= 10 and (wv.enemies or belief.danger_at(wv.pos)):
        _w8(CFG.SM_HELP_X, _enc(wv.pos.x))
        _w8(CFG.SM_HELP_Y, _enc(wv.pos.y))


def read_hints(wv):
    """Return {'enemy_carrier': Vec2|None, 'help': Vec2|None} if fresh."""
    out = {"enemy_carrier": None, "help": None}
    if not CFG.USE_COORDINATION:
        return out
    data = _read_all()
    if len(data) < 8:
        return out
    writer_round = int.from_bytes(data[CFG.SM_ROUND:CFG.SM_ROUND + 2], "little")
    if wv.round - writer_round > _FRESH_ROUNDS:
        return out
    ec = _decpt(data[CFG.SM_ENEMY_CARRIER_X], data[CFG.SM_ENEMY_CARRIER_Y])
    hp = _decpt(data[CFG.SM_HELP_X], data[CFG.SM_HELP_Y])
    out["enemy_carrier"] = ec
    out["help"] = hp
    return out


def _enc(coord):
    return (coord + 1) & 0xFF  # 0 means "none"


def _decpt(x, y):
    if x == 0 or y == 0:
        return None
    try:
        return cambc.Vec2(x - 1, y - 1)
    except Exception:
        return None
