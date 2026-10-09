from __future__ import annotations

from helpers.directions import DIRECTIONS
from map.map_manager import MapManager


class LauncherTracker:
    """Tracks enemy launcher danger zones on a boolean grid.

    Each enemy launcher and its 8 adjacent cells are marked True.
    The grid is rebuilt every round from current vision data.
    """

    def __init__(self, ct) -> None:
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        self.grid: list[list[bool]] = [
            [False] * self.height for _ in range(self.width)
        ]

    def update(self, ct, map_manager: MapManager) -> None:
        grid = self.grid
        w = self.width
        h = self.height

        # Clear previous round
        for col in grid:
            for y in range(h):
                col[y] = False

        for rec in map_manager.nearby_enemy_launcher_ids:
            pos = rec.position
            px, py = pos.x, pos.y

            # Mark the launcher cell and all 8 neighbours
            for dx in (-1, 0, 1):
                nx = px + dx
                if nx < 0 or nx >= w:
                    continue
                col = grid[nx]
                for dy in (-1, 0, 1):
                    ny = py + dy
                    if 0 <= ny < h:
                        col[ny] = True

    def is_dangerous(self, pos) -> bool:
        return self.grid[pos.x][pos.y]
