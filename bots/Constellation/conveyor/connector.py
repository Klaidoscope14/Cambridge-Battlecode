from cambc import Controller, EntityType, Position

from conveyor.traverse import conveyor_bfs, ConveyorPlacement, placement_cost, _belt_outputs
from nav.passability import passability_ally_conveyor
from roles.builder.helpers import build_conveyor, build_armoured_conveyor
from map.map_manager import MapManager


class Connector:
    def __init__(self, ct: Controller, map_manager: MapManager):
        self.ct = ct
        self.map_manager = map_manager
        self._cached_key: tuple | None = None
        self._cached_placements: list[ConveyorPlacement] | None = None

    def _get_placements(
        self,
        ct: Controller,
        sources: list[Position],
        destinations: list[Position],
    ) -> list[ConveyorPlacement] | None:
        key = (
            tuple(sorted((p.x, p.y) for p in sources)),
            tuple(sorted((p.x, p.y) for p in destinations)),
            ct.get_current_round(),
        )
        if key == self._cached_key:
            return self._cached_placements

        placements = conveyor_bfs(
            ct, self.map_manager, sources, destinations,
            passability_ally_conveyor,
        )
        self._cached_key = key
        self._cached_placements = placements
        return placements

    def check_connected(
        self,
        ct: Controller,
        sources: list[Position],
        destinations: list[Position],
    ) -> bool:
        placements = self._get_placements(ct, sources, destinations)
        if placements is None:
            return False
        return placement_cost(self.map_manager, placements) == 0

    def connect(
        self,
        ct: Controller,
        sources: list[Position],
        destinations: list[Position],
        armoured: bool,
    ) -> bool:
        placements = self._get_placements(ct, sources, destinations)
        if placements is None:
            return False

        if placement_cost(self.map_manager, placements) == 0:
            return True

        for placement in placements:
            record = self.map_manager.get_building(placement.pos)
            if _belt_outputs(record, placement.direction):
                continue

            if record is not None and ct.can_destroy(placement.pos):
                ct.destroy(placement.pos)

            if armoured:
                build_armoured_conveyor(ct, placement.pos, placement.direction)
            else:
                build_conveyor(ct, placement.pos, placement.direction)
            break

        return True
