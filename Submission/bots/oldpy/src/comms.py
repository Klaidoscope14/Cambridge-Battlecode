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
    # Spotted a loaded enemy? share its tile for allies to collapse on.
    best = belief.best_gank_target(wv)
    if best is not None:
        e, epos, egems, ehp = best
        if egems >= 10:
            # A message is a single intent.  Clear the other payload before
            # stamping it so a prior help request cannot be renewed forever.
            _w8(CFG.SM_HELP_X, 0)
            _w8(CFG.SM_HELP_Y, 0)
            _w8(CFG.SM_ENEMY_CARRIER_X, _enc(epos.x))
            _w8(CFG.SM_ENEMY_CARRIER_Y, _enc(epos.y))
            _w8(CFG.SM_FLAGS, 0)
            _w16(CFG.SM_ROUND, wv.round)
            return
    # Am I a carrier in danger? ask for help.
    if wv.gems >= 10 and (wv.enemies or belief.danger_at(wv.pos)):
        _w8(CFG.SM_ENEMY_CARRIER_X, 0)
        _w8(CFG.SM_ENEMY_CARRIER_Y, 0)
        _w8(CFG.SM_HELP_X, _enc(wv.pos.x))
        _w8(CFG.SM_HELP_Y, _enc(wv.pos.y))
        _w8(CFG.SM_FLAGS, 0)
        _w16(CFG.SM_ROUND, wv.round)
        return
    # Ordinary contact matters too.  A fresh rally point lets nearby farming
    # allies converge instead of each independently resuming an old camp.
    nearest, nearest_d = None, 1 << 30
    for enemy in wv.enemies:
        try:
            pos = enemy.position()
            d = wv.pos.chebyshev_distance(pos)
            if d < nearest_d:
                nearest, nearest_d = pos, d
        except Exception:
            continue
    if nearest is not None:
        _w8(CFG.SM_HELP_X, 0)
        _w8(CFG.SM_HELP_Y, 0)
        _w8(CFG.SM_ENEMY_CARRIER_X, _enc(nearest.x))
        _w8(CFG.SM_ENEMY_CARRIER_Y, _enc(nearest.y))
        _w8(CFG.SM_FLAGS, CFG.SM_FLAG_CONTACT)
        _w16(CFG.SM_ROUND, wv.round)


def read_hints(wv):
    """Return fresh enemy-carrier, contact, and help coordinates."""
    out = {"enemy_carrier": None, "enemy_contact": None, "help": None}
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
    if data[CFG.SM_FLAGS] & CFG.SM_FLAG_CONTACT:
        out["enemy_contact"] = ec
    else:
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
