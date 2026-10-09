"""Reverse A* anchored at an effective target.

The search expands outward from a goal tile (the real target if it's
in the bot's reachable set, else a frontier sub-goal). The bot
navigates by descending the _g surface — every turn it picks its
neighbour with the smallest cost-from-target and steps there.

Properties:
- The anchor is the effective target, not the bot. Bot movement
  doesn't reseed the search; only effective-target change does.
- The bot is *always* on the gradient when its tile has been
  reached by expansion — there's no chain to wander off of.
- Heuristic h(n) = chebyshev(n, bot). The bot moves so h drifts
  ≤1 per turn, but A* stays admissible (Chebyshev is the true min
  cost on an 8-connected grid). Slight heap-staleness, no
  correctness loss.
- Static_pass is provided by the caller; it must include both
  terrain (is_reachable) and flavour (resources / no_build_road).
  Tiles the bot can't currently traverse don't enter _g — so the
  gradient is always walkable.
"""
from __future__ import annotations

import heapq

from cambc import Position
from map.map_manager import MapManager

from nav.config import H_WEIGHT, EMPTY_PENALTY, BOT_PENALTY


class ReverseAStar:
    def __init__(self, deltas: list) -> None:
        self._deltas = deltas
        self.reset()

    def reset(self) -> None:
        self._open: list = []
        self._cnt: int = 0
        self._g: dict[tuple[int, int], int] = {}
        self._closed: set[tuple[int, int]] = set()
        self._target: tuple[int, int] | None = None
        self.exhausted: bool = False

    def seed(self, target_pos: Position, bot_pos: Position) -> None:
        self.reset()
        t = (target_pos.x, target_pos.y)
        self._target = t
        self._g[t] = 0
        h = H_WEIGHT * max(abs(t[0] - bot_pos.x), abs(t[1] - bot_pos.y))
        heapq.heappush(self._open, (h, self._cnt, t))
        self._cnt += 1

    @property
    def g_map(self) -> dict[tuple[int, int], int]:
        return self._g

    @property
    def target_key(self) -> tuple[int, int] | None:
        return self._target

    def g_at(self, x: int, y: int) -> int | None:
        return self._g.get((x, y))

    def expand(
        self,
        ct,
        mm: MapManager,
        bot_pos: Position,
        static_pass,
        reachable_set,
        budget: int,
    ) -> int:
        if budget <= 0 or self._target is None:
            return 0

        w, h_dim = mm.width, mm.height
        bx, by = bot_pos.x, bot_pos.y
        g_map = self._g
        closed = self._closed
        open_list = self._open
        bld_grid = mm.building_grid
        bot_grid = mm.bot_grid
        reachable_tiles = reachable_set.tiles
        frontier = reachable_set.frontier
        expanded = 0

        while open_list and budget > 0:
            _f, _c, cur = heapq.heappop(open_list)
            if cur in closed:
                continue
            closed.add(cur)
            budget -= 1
            expanded += 1

            if cur not in reachable_tiles:
                reachable_tiles.add(cur)
            frontier.add(cur)

            cx, cy = cur
            g = g_map[cur]
            for _d, dx, dy in self._deltas:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < w and 0 <= ny < h_dim):
                    continue
                nb = (nx, ny)
                if nb in closed:
                    continue
                if not static_pass(nx, ny):
                    continue
                ng = g + 1 + (
                    EMPTY_PENALTY if bld_grid[nx][ny] is None else 0
                )
                # Penalise tiles currently occupied by another bot.
                # The chain will still route through them when there's
                # no alternative, but prefers detours when there is.
                if bot_grid[nx][ny] is not None:
                    ng += BOT_PENALTY
                if nb not in g_map or ng < g_map[nb]:
                    g_map[nb] = ng
                    f = ng + H_WEIGHT * max(abs(nx - bx), abs(ny - by))
                    heapq.heappush(open_list, (f, self._cnt, nb))
                    self._cnt += 1

        if not open_list:
            self.exhausted = True
        return expanded
