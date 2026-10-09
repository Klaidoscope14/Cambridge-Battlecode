"""VisionManager: pre-caches visible entities each round for O(1) access.

Pattern for adding a new entity type
-------------------------------------
1. Add a private list   ``_<type>s: list[tuple[Position, <Record>]]``
2. Add                  ``_<type>s_updated_round: int | None = None``
3. Implement            ``update_<type>s(map_manager, current_round) -> None``
4. Implement            ``get_<type>s(current_round) -> list[...]``
   - copy the stale-round guard from an existing get_* method
5. Call ``update_<type>s`` inside ``update()``
"""
from cambc import Controller, EntityType, Position

from map.map_manager import MapManager
from map.schema import BridgeRecord, MarkerRecord


class VisionManager:
    def __init__(self, ct: Controller):
        self._ct = ct

        # -- bridges -------------------------------------------------------
        self._bridges: list[tuple[Position, BridgeRecord]] = []
        self._bridges_updated_round: int | None = None

        # -- ally markers --------------------------------------------------
        self._ally_markers: list[tuple[Position, MarkerRecord]] = []
        self._ally_markers_updated_round: int | None = None

        self._harvesters: list[Position] = []
    # ----------------------------------------------------------------------
    # Bridges
    # ----------------------------------------------------------------------

    def update_bridges(self, ct, map_manager: MapManager) -> None:
        """Scan nearby entities and cache every visible bridge."""
        bridges: list[tuple[Position, BridgeRecord]] = []
        for eid in map_manager.nearby_entity_ids:
            try:
                if self._ct.get_entity_type(eid) != EntityType.BRIDGE:
                    continue
                pos = self._ct.get_position(eid)
                record = map_manager.get_building(pos)
                if not isinstance(record, BridgeRecord):
                    continue
                bridges.append((pos, record))
            except Exception:
                continue
        self._bridges = bridges
        self._bridges_updated_round = ct.get_current_round()

    def get_bridges(self, ct) -> list[tuple[Position, BridgeRecord]]:
        """Return cached bridges for the current round as ``(pos, BridgeRecord)`` pairs.

        Raises ``RuntimeError`` if ``update_bridges`` was not called this round.
        This check exists intentionally to catch call-order bugs during development.
        """
        current_round = ct.get_current_round()
        if self._bridges_updated_round != current_round:
            raise RuntimeError(
                f"get_bridges called in round {current_round} but "
                f"update_bridges was last called in round "
                f"{self._bridges_updated_round}. "
                "Call update_bridges (or update) before get_bridges."
            )
        return self._bridges

    # ----------------------------------------------------------------------
    # Ally markers
    # ----------------------------------------------------------------------

    def update_ally_markers(self, ct, map_manager: MapManager) -> None:
        """Scan nearby entities and cache every visible ally marker."""
        markers: list[tuple[Position, MarkerRecord]] = []
        my_team = ct.get_team()
        for eid in map_manager.nearby_entity_ids:
            try:
                if self._ct.get_entity_type(eid) != EntityType.MARKER:
                    continue
                if self._ct.get_team(eid) != my_team:
                    continue
                pos = self._ct.get_position(eid)
                record = map_manager.get_building(pos)
                if not isinstance(record, MarkerRecord):
                    continue
                markers.append((pos, record))
            except Exception:
                continue
        self._ally_markers = markers
        self._ally_markers_updated_round = ct.get_current_round()

    def get_ally_markers(self, current_round: int) -> list[tuple[Position, MarkerRecord]]:
        """Return cached ally markers for *current_round* as ``(pos, MarkerRecord)`` pairs.

        Raises ``RuntimeError`` if ``update_ally_markers`` was not called this round.
        """
        if self._ally_markers_updated_round != current_round:
            raise RuntimeError(
                f"get_ally_markers called in round {current_round} but "
                f"update_ally_markers was last called in round "
                f"{self._ally_markers_updated_round}. "
                "Call update_ally_markers (or update) before get_ally_markers."
            )
        return self._ally_markers

    # ----------------------------------------------------------------------
    # Ally Harvesters
    # ----------------------------------------------------------------------
    def update_harvesters(self, ct, map_manager: MapManager) -> None:
        """Scan nearby entities and cache every visible harvester."""

        for eid in map_manager.nearby_entity_ids:
            if self._ct.get_entity_type(eid) != EntityType.HARVESTER:
                continue
            pos = self._ct.get_position(eid)
            if pos not in self._harvesters:
                self._harvesters.append(pos)


    # ----------------------------------------------------------------------
    # Master update — call once per round before any get_* calls
    # ----------------------------------------------------------------------

    def update(self, ct, map_manager: MapManager) -> None:
        self.update_bridges(ct, map_manager)
        self.update_ally_markers(ct, map_manager)
        self.update_harvesters(ct, map_manager)
