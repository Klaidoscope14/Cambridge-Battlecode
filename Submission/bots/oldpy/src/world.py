"""Per-turn perception snapshot.

Gathered fresh each turn from vision; cheap, read-only facts (OBSERVED). The
persistent belief model (belief.py) consumes this to maintain INFERRED state
across turns. Keeping observed vs inferred separate is point 5/8.
"""
from __future__ import annotations

import cambc
from cambc import Team


class WorldView:
    __slots__ = ("round", "me", "pos", "hp", "max_hp", "gems", "gold",
                 "allies", "enemies", "camps", "visible",
                 "enemy_locks")

    def __init__(self):
        self.round = cambc.round_number()
        me = cambc.me()
        self.me = me
        self.pos = me.position()
        self.hp = me.health()
        self.max_hp = me.max_health()
        self.gems = me.gem_count()
        self.gold = me.gold_count()

        self.visible = cambc.vision.visible_tiles()

        self.allies = []
        for c in cambc.vision.champions(Team.ALLY):
            if c == me:
                continue
            self.allies.append(c)
        self.enemies = list(cambc.vision.champions(Team.ENEMY))
        self.camps = list(cambc.vision.camps())

        self.enemy_locks = cambc.vision.altar_locks(Team.ENEMY)

    def hp_frac(self) -> float:
        return self.hp / self.max_hp if self.max_hp else 1.0
