"""Objective type shared by the three decision layers (point 2)."""
from __future__ import annotations

# kinds
BANK = "bank"
FARM = "farm"
CAPTURE = "capture"
GANK = "gank"
DEFEND = "defend"
RECALL = "recall"
FLEE = "flee"
SHOP = "shop"
WARD = "ward"
EXPLORE = "explore"
IDLE = "idle"


class Objective:
    __slots__ = ("kind", "target", "score", "emergency")

    def __init__(self, kind, target=None, score=0.0, emergency=False):
        self.kind = kind
        self.target = target       # Vec2, Unit, or None
        self.score = score
        self.emergency = emergency

    def key(self):
        """Identity for hysteresis: same kind + same coarse target."""
        t = self.target
        if t is None:
            return (self.kind,)
        try:
            return (self.kind, t.x, t.y)
        except Exception:
            try:
                return (self.kind, int(t.__hash__()))
            except Exception:
                return (self.kind, id(t))

    def __repr__(self):
        return f"Obj({self.kind}, score={self.score:.2f}, emg={self.emergency})"
