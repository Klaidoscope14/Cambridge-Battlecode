"""Belief model (points 5 & 8): observed / inferred / unknown with decay.

Persistent across turns (owned by the brain). Tracks enemy champions with a
confidence that decays while unseen, infers likely positions from symmetry
when we have never seen them, and maintains a danger bitboard (tiles an enemy
could attack) used by banking, navigation and ganking. Nothing here treats an
inferred position as a current observation — callers read `.confidence`.
"""
from __future__ import annotations

import cambc
from cambc import Bitboard, Vec2

from config import CFG
from mapinfo import map_info
from util import reflect


class EnemyRecord:
    __slots__ = ("pos", "gems", "hp_frac", "last_seen", "confidence",
                 "attack_range", "observed")

    def __init__(self, pos, rnd, attack_range, observed):
        self.pos = pos
        self.gems = 0
        self.hp_frac = 1.0
        self.last_seen = rnd
        self.confidence = 1.0 if observed else 0.4
        self.attack_range = attack_range
        self.observed = observed


class Belief:
    def __init__(self):
        self.enemies = {}       # champion handle -> EnemyRecord
        self.danger = Bitboard()
        self.round = 0
        self._seeded = False

    def update(self, wv):
        self.round = wv.round
        mi = map_info()

        # Age existing records; drop stale ones.
        drop = []
        for h, rec in self.enemies.items():
            if rec.last_seen != wv.round:
                rec.confidence *= CFG.ENEMY_POSITION_DECAY
                if wv.round - rec.last_seen > CFG.ENEMY_FORGET_ROUNDS:
                    drop.append(h)
        for h in drop:
            del self.enemies[h]

        # Fold in fresh observations.
        for e in wv.enemies:
            try:
                h = int(e.__hash__())
            except Exception:
                h = id(e)
            try:
                pos = e.position()
                rng = e.attack_range()
                rec = EnemyRecord(pos, wv.round, rng, True)
                rec.gems = e.gem_count() if hasattr(e, "gem_count") else 0
                try:
                    rec.hp_frac = e.health() / e.max_health()
                except Exception:
                    rec.hp_frac = 1.0
                self.enemies[h] = rec
            except Exception:
                continue

        # One-time symmetry seed: if we have seen nothing, the enemy team
        # most plausibly mirrors our spawn. Low confidence, static only.
        if CFG.USE_BELIEF and not self._seeded and not self.enemies:
            self._seeded = True
            try:
                my_spawn = mi.ally_spawn.positions()[0]
                guess = reflect(my_spawn, mi.symmetry)
                self.enemies[-1] = EnemyRecord(guess, wv.round, 3, False)
            except Exception:
                pass

        self._rebuild_danger(wv)

    def _rebuild_danger(self, wv):
        self.danger.clear()
        if not CFG.USE_BELIEF:
            return
        for rec in self.enemies.values():
            if rec.confidence < 0.35:
                continue
            r = rec.attack_range + CFG.DANGER_ENEMY_RANGE_PAD
            tmp = Bitboard()
            tmp.draw_chebyshev(rec.pos, r)
            self.danger |= tmp

    # ---- queries ----------------------------------------------------------
    def danger_at(self, pos: Vec2) -> bool:
        try:
            return self.danger.is_set(pos)
        except Exception:
            return False

    def immediate_threat(self, wv, pad: int = 1) -> bool:
        """Anything that can hit us next turn: enemy champ or awake camp in
        range. Camps aren't in the danger field, so check them explicitly."""
        p = wv.pos
        for e in wv.enemies:
            try:
                if p.chebyshev_distance(e.position()) <= e.attack_range() + pad:
                    return True
            except Exception:
                continue
        for c in wv.camps:
            try:
                if p.chebyshev_distance(c.position()) <= c.attack_range() + pad:
                    return True
            except Exception:
                continue
        return False

    def champion_threat(self, wv, pad: int = 1) -> bool:
        """An ENEMY CHAMPION that can hit us next turn (gem-theft risk)."""
        p = wv.pos
        for e in wv.enemies:
            try:
                if p.chebyshev_distance(e.position()) <= e.attack_range() + pad:
                    return True
            except Exception:
                continue
        return False

    def nearest_enemy_pos(self, wv):
        best, best_d = None, 1 << 30
        for e in wv.enemies:
            try:
                d = wv.pos.chebyshev_distance(e.position())
                if d < best_d:
                    best_d, best = d, e.position()
            except Exception:
                continue
        return best

    def nearest_threat_pos(self, wv):
        best, best_d = None, 1 << 30
        for e in wv.enemies:
            try:
                d = wv.pos.chebyshev_distance(e.position())
                if d < best_d:
                    best_d, best = d, e.position()
            except Exception:
                continue
        for c in wv.camps:
            try:
                d = wv.pos.chebyshev_distance(c.position())
                if d < best_d:
                    best_d, best = d, c.position()
            except Exception:
                continue
        return best

    def enemies_within(self, pos: Vec2, radius: int):
        out = []
        for rec in self.enemies.values():
            if pos.chebyshev_distance(rec.pos) <= radius:
                out.append(rec)
        return out

    def best_gank_target(self, wv):
        """A visible, reachable-ish enemy worth killing: prefers loaded,
        low-HP, close targets. Returns (enemy_champion, record) or None."""
        best = None
        best_score = 0.0
        for e in wv.enemies:
            try:
                epos = e.position()
                egems = e.gem_count()
                ehp = e.health() / e.max_health()
            except Exception:
                continue
            dist = wv.pos.chebyshev_distance(epos)
            # value: stealing gems + finishing low targets, discounted by range
            score = (egems * 1.0 + (1.0 - ehp) * 20.0) / (1 + dist)
            if score > best_score:
                best_score, best = score, (e, epos, egems, ehp)
        return best if best_score > 0 else None
