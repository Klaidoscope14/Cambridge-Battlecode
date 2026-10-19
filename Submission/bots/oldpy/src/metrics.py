"""Instrumentation (point 7): make testing an optimisation engine.

Emits compact, parseable lines to stdout (captured in the replay bundle) so
A/B and ablation runs can extract per-champion outcomes: gems banked, gems
lost on death, deaths, fuel headroom, and the objective mix. Cheap; never
affects decisions.
"""
from __future__ import annotations

import cambc
from config import CFG


class Metrics:
    __slots__ = ("prev_gems", "prev_alive", "banked", "lost_on_death",
                 "deaths", "obj_counts", "min_fuel", "last_log",
                 "team_banked", "enemy_banked")

    def __init__(self):
        self.prev_gems = 0
        self.prev_alive = True
        self.banked = 0
        self.lost_on_death = 0
        self.deaths = 0
        self.obj_counts = {}
        self.min_fuel = 1 << 30
        self.last_log = 0
        self.team_banked = 0
        self.enemy_banked = 0

    def observe(self, wv, obj):
        if not CFG.USE_METRICS:
            return
        try:
            alive = wv.me.is_alive()
        except Exception:
            alive = True
        # A gem drop while continuously alive is a successful tribute. A
        # dead body has no bag, so record the loss exactly once on the alive
        # -> dead transition instead of mistaking it for a bank.
        if not alive:
            if self.prev_alive:
                self.on_death(self.prev_gems)
            self.prev_alive = False
            self.prev_gems = 0
        else:
            if self.prev_alive and wv.gems < self.prev_gems:
                self.banked += self.prev_gems - wv.gems
            self.prev_alive = True
            self.prev_gems = wv.gems
        if obj is not None:
            self.obj_counts[obj.kind] = self.obj_counts.get(obj.kind, 0) + 1
        try:
            f = cambc.fuel_remaining()
            if f < self.min_fuel:
                self.min_fuel = f
        except Exception:
            pass
        try:
            self.team_banked = cambc.global_submitted_gems(cambc.Team.ALLY)
            self.enemy_banked = cambc.global_submitted_gems(cambc.Team.ENEMY)
        except Exception:
            pass
        if wv.round - self.last_log >= 50:
            self.last_log = wv.round
            self._flush(wv)

    def on_death(self, carried):
        self.deaths += 1
        self.lost_on_death += carried

    def _flush(self, wv):
        try:
            mix = ",".join(f"{k}:{v}" for k, v in sorted(self.obj_counts.items()))
            print(f"METRIC r={wv.round} personal_banked={self.banked} "
                  f"team_banked={self.team_banked} enemy_banked={self.enemy_banked} "
                  f"lost={self.lost_on_death} deaths={self.deaths} "
                  f"minfuel={self.min_fuel} mix={mix}", flush=True)
        except Exception:
            pass
