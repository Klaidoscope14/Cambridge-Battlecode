from cambc import EntityType, Position
from map.map_manager import MapManager


# Symmetry type constants
HORIZONTAL  = "horizontal"   # reflected across horizontal axis: (x, y) -> (x, H-1-y)
VERTICAL    = "vertical"     # reflected across vertical axis:   (x, y) -> (W-1-x, y)
ROTATIONAL  = "rotational"   # 180 rotation:                     (x, y) -> (W-1-x, H-1-y)

ALL_SYMMETRIES = {HORIZONTAL, VERTICAL, ROTATIONAL}


class SymmetryManager:
    def __init__(self, ct) -> None:
        self.width  = ct.get_map_width()
        self.height = ct.get_map_height()
        self._candidates: set[str] = set(ALL_SYMMETRIES)
        self._checked_positions: set[tuple[int, int]] = set()

    def update(self, map_manager: MapManager) -> None:
        if len(self._candidates) <= 1:
            return  # already cracked, nothing to do

        self._check_core_symmetry(map_manager)
        if len(self._candidates) <= 1:
            return

        self._eliminate_by_ally_core(map_manager)
        if len(self._candidates) <= 1:
            return

        for pos in map_manager.nearby_positions:
            key = (pos.x, pos.y)
            if key in self._checked_positions:
                continue
            self._checked_positions.add(key)

            tile = map_manager.tile_grid[pos.x][pos.y]
            if tile is None:
                continue

            # For each surviving symmetry, check if the mirror cell is known
            # and whether it matches.
            to_eliminate = set()
            for sym in self._candidates:
                mirror = self._mirror_pos(pos.x, pos.y, sym)
                if mirror is None:
                    continue
                mx, my = mirror
                mirror_tile = map_manager.tile_grid[mx][my]
                if mirror_tile is None:
                    continue  # mirror not yet seen -- can't rule anything out
                if not self._tiles_match(tile, mirror_tile):
                    to_eliminate.add(sym)

            self._candidates -= to_eliminate

            if len(self._candidates) <= 1:
                break  # cracked -- stop early

    def _check_core_symmetry(self, map_manager: MapManager) -> None:
        ally_core = map_manager.ally_core_pos
        spotted = map_manager.spotted_enemy_core_pos
        if ally_core is None or spotted is None:
            return

        to_eliminate = set()
        for sym in self._candidates:
            mirror = self._mirror_pos(ally_core.x, ally_core.y, sym)
            if mirror is None:
                to_eliminate.add(sym)
                continue
            mx, my = mirror
            if abs(mx - spotted.x) > 1 or abs(my - spotted.y) > 1:
                to_eliminate.add(sym)

        self._candidates -= to_eliminate

    def _eliminate_by_ally_core(self, map_manager: MapManager) -> None:
        """Eliminate symmetries where the predicted enemy core center has a visible
        non-core building.

        Reflects ally core center under each candidate. If the building_grid at
        that single tile is seen and is not a core, that symmetry is impossible.
        """
        ally_core = map_manager.ally_core_pos
        if ally_core is None:
            return

        to_eliminate = set()

        for sym in self._candidates:
            mirror = self._mirror_pos(ally_core.x, ally_core.y, sym)
            if mirror is None:
                to_eliminate.add(sym)
                continue
            building = map_manager.get_building(Position(mirror[0], mirror[1]))
            if building is not None and building.entity_type != EntityType.CORE and map_manager.has_seen(Position(mirror[0], mirror[1])):
                to_eliminate.add(sym)

        self._candidates -= to_eliminate

    def is_cracked(self) -> bool:
        return len(self._candidates) == 1

    def get_symmetry(self) -> str | None:
        if len(self._candidates) == 1:
            return next(iter(self._candidates))
        return None

    def get_candidates(self) -> set[str]:
        return set(self._candidates)

    def guess_symmetry(self) -> str | None:
        """Return the best symmetry guess. Prefers the cracked answer, then
        rotational (as it eliminates others fastest), then any remaining."""
        if len(self._candidates) == 1:
            return next(iter(self._candidates))
        if not self._candidates:
            return None
        if ROTATIONAL in self._candidates:
            return ROTATIONAL
        return next(iter(self._candidates))

    def reflect(self, pos: Position, sym: str | None = None) -> Position | None:
        if sym is None:
            sym = self.get_symmetry()
        if sym is None:
            return None
        mirror = self._mirror_pos(pos.x, pos.y, sym)
        if mirror is None:
            return None
        mx, my = mirror
        return Position(mx, my)

    def reflect_all(self, pos: Position) -> dict[str, Position]:
        result = {}
        for sym in self._candidates:
            mirror = self._mirror_pos(pos.x, pos.y, sym)
            if mirror is not None:
                result[sym] = Position(mirror[0], mirror[1])
        return result

    def _mirror_pos(self, x: int, y: int, sym: str) -> tuple[int, int] | None:
        W, H = self.width, self.height
        if sym == HORIZONTAL:
            mx, my = x, H - 1 - y
        elif sym == VERTICAL:
            mx, my = W - 1 - x, y
        elif sym == ROTATIONAL:
            mx, my = W - 1 - x, H - 1 - y
        else:
            return None

        if 0 <= mx < W and 0 <= my < H:
            return mx, my
        return None

    @staticmethod
    def _tiles_match(a, b) -> bool:
        return a == b