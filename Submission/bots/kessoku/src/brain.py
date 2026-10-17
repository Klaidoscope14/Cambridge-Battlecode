"""Per-champion controller: wires Layer A -> B -> C each turn (point 2).

Owns persistent state (belief, current objective + commitment counter, role,
metrics). main.py creates one Bot per champion and calls play_turn() each
turn. Commitment/hysteresis lives here so objective selection doesn't thrash.
"""
from __future__ import annotations

import cambc

from config import CFG
import constraints
import objectives
import tactics
import comms
import champions
from belief import Belief
from world import WorldView
from metrics import Metrics
import objective as O


class Bot:
    def __init__(self):
        self.belief = Belief()
        self.metrics = Metrics()
        self.current = None          # committed Objective
        self.rounds_on = 0
        self.role = None

    def _ensure_role(self, wv):
        if self.role is None:
            try:
                self.role = champions.role_for_type(wv.me.champion_name())
            except Exception:
                self.role = champions.ROLE_CARRY

    def play_turn(self):
        # Low-fuel bail: don't start planning we can't finish.
        try:
            if cambc.fuel_remaining() < CFG.FUEL_HARD_FLOOR:
                return
        except Exception:
            pass

        wv = WorldView()
        self._ensure_role(wv)

        if not constraints.can_act(wv):
            # still track metrics (e.g., death) then yield
            self.metrics.observe(wv, self.current)
            return

        if CFG.USE_BELIEF:
            self.belief.update(wv)
        comms.publish(wv, self.belief)

        obj = self._choose(wv)
        tactics.execute(obj, wv, self.belief, self.role)
        self.metrics.observe(wv, obj)

        # Scheduling priority: carriers and low-HP act earlier next round.
        try:
            pr = 10 + wv.gems - int(wv.hp_frac() * 5)
            wv.me.set_priority(max(1, min(250, pr)))
        except Exception:
            pass

    # ---- objective selection with hysteresis ------------------------------
    def _choose(self, wv):
        emg = constraints.emergency(wv, self.belief)
        if emg is not None:
            self._commit(emg)
            return emg

        if not CFG.USE_LAYERED_DECISIONS:
            cands = objectives.enumerate_objectives(wv, self.belief, self.role)
            self._commit(cands[0])
            return cands[0]

        cands = objectives.enumerate_objectives(wv, self.belief, self.role)
        if not cands:
            idle = O.Objective(O.EXPLORE)
            self._commit(idle)
            return idle
        challenger = cands[0]

        if self.current is None:
            self._commit(challenger)
            return challenger

        # Is the incumbent kind still feasible?
        incumbent = None
        for c in cands:
            if c.kind == self.current.kind:
                incumbent = c
                break

        if incumbent is None:
            self._commit(challenger)   # incumbent infeasible -> switch
            return challenger

        if challenger.kind == incumbent.kind:
            self.rounds_on += 1        # same objective, maybe retargeted
            self.current = challenger
            return challenger

        # different challenger: respect min-commit and margin
        if self.rounds_on < CFG.COMMIT_MIN_ROUNDS and incumbent.score > 0.0:
            self.rounds_on += 1
            self.current = incumbent
            return incumbent

        if challenger.score > incumbent.score * (1.0 + CFG.COMMIT_MARGIN):
            self._commit(challenger)
            return challenger

        self.rounds_on += 1
        self.current = incumbent
        return incumbent

    def _commit(self, obj):
        if self.current is None or obj.kind != self.current.kind:
            self.rounds_on = 0
        self.current = obj
