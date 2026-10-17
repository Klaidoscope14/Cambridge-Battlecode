"""Small helpers over the cambc primitives (Vec2 / Bitboard)."""
from __future__ import annotations

import cambc
from cambc import Vec2, Bitboard


def cheb(a: Vec2, b: Vec2) -> int:
    return a.chebyshev_distance(b)


def tiles_around(center: Vec2, radius: int) -> Bitboard:
    bb = Bitboard()
    bb.draw_chebyshev(center, radius)
    return bb


def bb_of(positions) -> Bitboard:
    bb = Bitboard()
    for p in positions:
        bb.set(p, True)
    return bb


def nearest(origin: Vec2, positions):
    """Nearest position by Chebyshev distance, or None."""
    best = None
    best_d = 1 << 30
    for p in positions:
        d = origin.chebyshev_distance(p)
        if d < best_d:
            best_d, best = d, p
    return best


def in_bounds(p: Vec2) -> bool:
    return cambc.game_map.is_in_bounds(p)


def reflect(p: Vec2, symmetry: int) -> Vec2:
    """Mirror a tile under the map symmetry (static terrain is symmetric)."""
    gm = cambc.game_map
    if symmetry == cambc.Symmetry.HORIZONTAL:
        return gm.reflect_horizontal(p)
    if symmetry == cambc.Symmetry.VERTICAL:
        return gm.reflect_vertical(p)
    return gm.rotate_180(p)
