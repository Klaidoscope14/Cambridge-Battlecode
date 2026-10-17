"""Static map analysis (point 3): geometry, not labels.

Computed once (terrain is static), then queried cheaply. Turns raw masks
into strategic features: travel distances from each spawn to every altar and
camp group, which altars are ally-safe vs enemy-contested, camp-group farm
ordering and ownership, and a terrain-content fingerprint that survives pool
changes. Everything keys off DistanceField BFS around walls/holes, so
"distance" means real reachable path length, never Chebyshev-through-walls.
"""
from __future__ import annotations

import hashlib

import cambc
from cambc import Bitboard, DistanceField, game_map

from config import CFG


class CampInfo:
    __slots__ = ("group", "spawn_tiles", "centroid", "gem_value", "gold_value",
                 "ally_dist", "enemy_dist", "owner", "total_hp")

    def __init__(self, group):
        self.group = group
        self.spawn_tiles = group.spawn_tiles()
        ps = self.spawn_tiles.positions()
        # integer centroid of the group's spawn tiles
        cx = sum(p.x for p in ps) // max(1, len(ps))
        cy = sum(p.y for p in ps) // max(1, len(ps))
        self.centroid = cambc.Vec2(cx, cy)
        self.gem_value = group.gem_value()
        self.gold_value = group.gold_value()
        # Clear effort ~ total group health (gem clusters are low-HP + safe,
        # wolves/elk/monoliths are tanky and dangerous).
        self.total_hp = 0.0
        try:
            for c in group.camps():
                try:
                    self.total_hp += c.base_stats().base_health
                except Exception:
                    self.total_hp += 500.0
        except Exception:
            self.total_hp = 500.0
        self.ally_dist = CFG.MAX_FIELD_DISTANCE
        self.enemy_dist = CFG.MAX_FIELD_DISTANCE
        self.owner = 0   # -1 ours, +1 theirs, 0 contested/neutral


class MapInfo:
    def __init__(self):
        gm = game_map
        self.width = gm.width()
        self.height = gm.height()
        self.symmetry = gm.symmetry()
        self.team_size = cambc.draft.team_size()

        self.walls = gm.walls()
        self.holes = gm.holes()
        self.altars_bb = gm.altars()
        self.bushes = gm.bushes()
        self.ally_spawn = gm.spawn_region(cambc.Team.ALLY)
        self.enemy_spawn = gm.spawn_region(cambc.Team.ENEMY)

        # Terrain impassable for path-length estimates.
        self._terrain = self.walls | self.holes
        # Tiles a champion may never stand on (for goal masking).
        self.blocked_static = self.walls | self.holes | self.altars_bb | self.enemy_spawn

        # Distance fields from each spawn, around terrain.
        self.ally_field = self._field_from(self.ally_spawn)
        self.enemy_field = self._field_from(self.enemy_spawn)

        self.altars = list(self.altars_bb.positions())
        # Altar safety: enemy path distance to the altar. Lower = more
        # contested. We treat an altar as "ally-safe" when we clearly reach
        # it first.
        self.altar_ally_dist = {}
        self.altar_enemy_dist = {}
        self.safe_altars = []
        for a in self.altars:
            da = self._reach(self.ally_field, a)
            de = self._reach(self.enemy_field, a)
            self.altar_ally_dist[(a.x, a.y)] = da
            self.altar_enemy_dist[(a.x, a.y)] = de
            if da <= de:
                self.safe_altars.append(a)
        if not self.safe_altars:
            self.safe_altars = list(self.altars)

        # Camp groups (available at draft time too).
        self.camps = []
        for g in game_map.camp_groups():
            ci = CampInfo(g)
            ci.ally_dist = self._reach_mask(self.ally_field, ci.spawn_tiles)
            ci.enemy_dist = self._reach_mask(self.enemy_field, ci.spawn_tiles)
            if ci.ally_dist + 2 < ci.enemy_dist:
                ci.owner = -1
            elif ci.enemy_dist + 2 < ci.ally_dist:
                ci.owner = 1
            self.camps.append(ci)
        self.camps.sort(key=lambda c: c.ally_dist)

        # Aggregate geometry features (0..1-ish) for draft/strategy tilt.
        area = self.width * self.height
        self.bush_frac = self.bushes.count() / area
        self.wall_frac = self.walls.count() / area
        self.open_frac = 1.0 - self.wall_frac - self.holes.count() / area
        self.altar_scarcity = 1.0 / max(1, len(self.altars))
        self.total_gem_supply = sum(c.gem_value for c in self.camps)
        self.our_gem_supply = sum(c.gem_value for c in self.camps if c.owner <= 0)

        self.fingerprint = self._fingerprint()

    # ---- helpers ----------------------------------------------------------
    def _field_from(self, roots: Bitboard) -> DistanceField:
        field = DistanceField()
        field.compute(self._terrain, roots, Bitboard(), CFG.MAX_FIELD_DISTANCE)
        return field

    def _reach(self, field: DistanceField, pos) -> int:
        """Shortest distance to a tile, approximated by the min over its
        free neighbours (the tile itself may be an altar/wall = unreached)."""
        best = CFG.MAX_FIELD_DISTANCE
        try:
            v = field.get(pos)
            if 0 < v < best:
                best = v
        except Exception:
            pass
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                n = cambc.Vec2(pos.x + dx, pos.y + dy)
                if not game_map.is_in_bounds(n):
                    continue
                try:
                    v = field.get(n)
                except Exception:
                    continue
                if 0 < v < best:
                    best = v
        return best

    def _reach_mask(self, field: DistanceField, mask: Bitboard) -> int:
        best = CFG.MAX_FIELD_DISTANCE
        for p in mask.positions():
            v = self._reach(field, p)
            if v < best:
                best = v
        return best

    def _fingerprint(self) -> str:
        h = hashlib.sha1()
        for bb in (self.walls, self.holes, self.altars_bb, self.bushes,
                   self.ally_spawn, self.enemy_spawn):
            h.update(bb.export_linear_buffer())
        h.update(bytes([self.team_size, int(self.symmetry)]))
        return h.hexdigest()[:12]

    def nearest_altar(self, origin):
        best, best_d = None, 1 << 30
        for a in self.altars:
            d = origin.chebyshev_distance(a)
            if d < best_d:
                best_d, best = d, a
        return best

    def nearest_safe_altar(self, origin):
        best, best_d = None, 1 << 30
        for a in self.safe_altars:
            d = origin.chebyshev_distance(a)
            if d < best_d:
                best_d, best = d, a
        return best


_MAP = None


def map_info() -> MapInfo:
    global _MAP
    if _MAP is None:
        _MAP = MapInfo()
    return _MAP
