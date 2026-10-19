"""Small helpers over the cambc primitives (Vec2 / Bitboard)."""
from __future__ import annotations

import cambc
from cambc import Vec2, Bitboard


def tiles_around(center: Vec2, radius: int) -> Bitboard:
    bb = Bitboard()
    bb.draw_chebyshev(center, radius)
    return bb


def reflect(p: Vec2, symmetry: int) -> Vec2:
    """Mirror a tile under the map symmetry (static terrain is symmetric)."""
    gm = cambc.game_map
    if symmetry == cambc.Symmetry.HORIZONTAL:
        return gm.reflect_horizontal(p)
    if symmetry == cambc.Symmetry.VERTICAL:
        return gm.reflect_vertical(p)
    return gm.rotate_180(p)
