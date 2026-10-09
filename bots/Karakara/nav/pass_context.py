"""Turn-scoped snapshot used by fast passability functions.

Captures controller + map state that's invariant across a single turn
so the A* hot loop doesn't have to re-query the controller on every
neighbor check.  A fresh PassContext is built at the start of each
Pathing.path_to / idle_expand call.

Grid references are shared (not copied) — the underlying MapManager
grids are only mutated in MapManager.update, which runs before pathing.
"""
from __future__ import annotations

from cambc import Position
from map.map_manager import MapManager
from vision.launcher_tracker import LauncherTracker


class PassContext:
    __slots__ = (
        'width', 'height',
        'my_x', 'my_y', 'my_team',
        'resources', 'road_cost', 'save_cost',
        'tile_grid', 'building_grid', 'bot_grid',
        'launcher_grid', 'gunner_danger',
        'target_x', 'target_y',
    )

    def __init__(self, ct, mm: MapManager, lt: LauncherTracker,
                 target: Position | None = None) -> None:
        self.width = mm.width
        self.height = mm.height
        my_pos = ct.get_position()
        self.my_x = my_pos.x
        self.my_y = my_pos.y
        self.my_team = ct.get_team()
        self.resources = ct.get_global_resources()[0]
        self.road_cost = ct.get_road_cost()[0]
        # "Save" mode reserves enough for a foundry once any ally conveyor
        # has been seen carrying axionite; before then, just enough for a
        # harvester (the next thing we'd build).
        self.save_cost = (
            ct.get_foundry_cost()[0]
            if mm.axionite_seen_on_conveyor
            else ct.get_harvester_cost()[0]
        )
        self.tile_grid = mm.tile_grid
        self.building_grid = mm.building_grid
        self.bot_grid = mm.bot_grid
        self.launcher_grid = lt.grid
        # Sparse per-turn snapshot of enemy gunner fire tiles. Rebuilt each
        # turn from MapManager — gunners move, so persistence isn't useful.
        self.gunner_danger = {(p.x, p.y) for p in mm.gunner_danger_positions}
        if target is not None:
            self.target_x = target.x
            self.target_y = target.y
        else:
            self.target_x = -1
            self.target_y = -1
