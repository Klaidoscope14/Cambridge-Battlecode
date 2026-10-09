"""Lightweight incremental weighted A* for exploration pathing."""

from __future__ import annotations

import heapq
from cambc import Position
from nav.config import DEBUG, H_WEIGHT, EMPTY_PENALTY, BOT_PENALTY
from debug.indicators import draw_blocked_tile
from map.map_manager import MapManager


class ExploreAStar:
    """Incremental weighted A* from the bot to a set of goal tiles.

    Used for exploration (pathing to vision-boundary tiles through
    obstacles).  Uses chebyshev heuristic toward the goal to focus
    expansion directionally.
    """

    def __init__(self, start: Position, goal_tiles: set[tuple[int, int]],
                 deltas: list) -> None:
        self._deltas = deltas
        self._goal_tiles = goal_tiles
        # Pick one goal tile for heuristic
        self._h_target = next(iter(goal_tiles))
        self._open: list = []
        self._cnt: int = 0
        self._g: dict = {}
        self._from: dict = {}
        self._closed: set = set()
        self._found: bool = False
        self._path: list[Position] = []
        self._pidx: int = 0

        s = (start.x, start.y)
        self._g[s] = 0
        tx, ty = self._h_target
        h = H_WEIGHT * max(abs(s[0] - tx), abs(s[1] - ty))
        heapq.heappush(self._open, (h, self._cnt, s))
        self._cnt += 1

    @property
    def found(self) -> bool:
        return self._found

    @property
    def path(self) -> list[Position]:
        return self._path

    @property
    def pidx(self) -> int:
        return self._pidx

    @pidx.setter
    def pidx(self, v: int) -> None:
        self._pidx = v

    def expand(self, ct, mm: MapManager, pass_fn,
               budget: int = 0) -> tuple[bool, int]:
        w, h = mm.width, mm.height
        tx, ty = self._h_target
        expanded = 0
        closed = self._closed
        g_map = self._g
        from_map = self._from
        goal_tiles = self._goal_tiles
        open_list = self._open
        bld_grid = mm.building_grid
        my_id = ct.get_id()
        my_team = ct.get_team()

        while open_list and budget > 0:
            _f, _c, cur = heapq.heappop(open_list)
            if cur in closed:
                continue
            closed.add(cur)
            budget -= 1
            expanded += 1

            DEBUG and draw_blocked_tile(ct, Position(cur[0], cur[1]), 0, 200, 255)

            if cur in goal_tiles:
                self._found = True
                self._build_path(cur)
                return True, expanded

            g = g_map[cur]
            cx, cy = cur
            bot_grid = mm.bot_grid
            for _d, dx, dy in self._deltas:
                nx, ny = cx + dx, cy + dy
                nb = (nx, ny)
                if nb in closed:
                    continue
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if not pass_fn(nx, ny):
                    continue

                ng = g + 1 + (EMPTY_PENALTY if bld_grid[nx][ny] is None else 0)
                other = bot_grid[nx][ny]
                if other is not None and (other.team != my_team or my_id > other.id):
                    ng += BOT_PENALTY
                if nb not in g_map or ng < g_map[nb]:
                    g_map[nb] = ng
                    from_map[nb] = cur
                    f = ng + H_WEIGHT * max(abs(nx - tx), abs(ny - ty))
                    heapq.heappush(open_list, (f, self._cnt, nb))
                    self._cnt += 1

        return False, expanded

    def _build_path(self, goal: tuple) -> None:
        path: list[Position] = []
        cur = goal
        while cur in self._from:
            path.append(Position(cur[0], cur[1]))
            cur = self._from[cur]
        path.append(Position(cur[0], cur[1]))
        path.reverse()
        self._path = path
        self._pidx = 0

    def best_partial_step(self, ct, mm: MapManager, my_pos: Position,
                          pass_fn) -> Position | None:
        """While computing, pick the best passable neighbor using _g data.

        Checks passability and bot_grid inline.
        """
        w, h = mm.width, mm.height
        tx, ty = self._h_target
        g_map = self._g
        best_pos = None
        best_score = float('inf')

        bot_grid = mm.bot_grid
        for _d, dx, dy in self._deltas:
            nx, ny = my_pos.x + dx, my_pos.y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if bot_grid[nx][ny] is not None:
                continue
            if not pass_fn(nx, ny):
                continue

            nb = (nx, ny)
            h_val = H_WEIGHT * max(abs(nx - tx), abs(ny - ty))

            if nb in g_map:
                score = g_map[nb] + h_val
            else:
                score = h_val

            if score < best_score:
                best_score = score
                best_pos = Position(nx, ny)

        return best_pos

    def sync(self, my_pos: Position) -> bool:
        """Sync bot to path. Checks exact match first, then adjacent tiles."""
        # Exact match
        for i in range(len(self._path)):
            if self._path[i] == my_pos:
                self._pidx = i
                return True

        # Adjacent match — find nearest path tile the bot is next to
        mx, my = my_pos.x, my_pos.y
        for i in range(len(self._path)):
            p = self._path[i]
            if max(abs(p.x - mx), abs(p.y - my)) <= 1:
                self._pidx = i
                return True

        return False
