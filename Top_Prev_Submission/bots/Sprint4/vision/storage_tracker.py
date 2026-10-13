"""StorageTracker: tracks which storages are "full" (blocked).

A storage is considered full if it has held a stored resource for 4+
consecutive observed turns.  All storages are assumed full until we
*observe* them empty, at which point they become not-full.  They return
to full status only after 4 consecutive observed turns with a resource.

Usage
-----
Call ``update(ct, map_manager)`` once per round after
MapManager has been updated.  Then query ``is_full(eid)`` or
``get_non_full_storage_eids()`` as needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from cambc import EntityType

from map.map_manager import MapManager
from map.schema import EntityRecord

# Storage entities the tracker observes. Replaces the prior
# isinstance(record, (BridgeRecord, ConveyorRecord)) check now that the
# record hierarchy collapsed to a single EntityRecord class. Matches the
# original semantics: anything that the old ConveyorRecord covered
# (CONVEYOR / SPLITTER / ARMOURED_CONVEYOR) plus BRIDGE.
_STORAGE_ENTITY_TYPES = frozenset((
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
))

FULL_THRESHOLD = 4  # consecutive turns with a resource to be considered full


EMPTY_THRESHOLD = 4  # consecutive turns without a resource to be considered empty


@dataclass
class _StorageState:
    """Internal per-storage tracking state."""
    full: bool = True  # assume full until proven otherwise
    empty: bool = False  # True after EMPTY_THRESHOLD consecutive empty turns
    consecutive_full_turns: int = FULL_THRESHOLD  # start at threshold (assumed full)
    consecutive_empty_turns: int = 0
    last_seen_round: int | None = None


class StorageTracker:
    """Tracks storage fullness across rounds.

    Parameters
    ----------
    full_threshold : int
        Number of consecutive turns a storage must hold a resource before
        it is considered full again after being cleared.  Default is 4.
    """

    def __init__(self, ct, full_threshold: int = FULL_THRESHOLD, empty_threshold: int = EMPTY_THRESHOLD) -> None:
        self._threshold = full_threshold
        self._empty_threshold = empty_threshold
        self._states: dict[int, _StorageState] = {}  # eid -> state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, ct, map_manager: MapManager) -> None:
        """Update storage states from this round's observations.

        Uses MapManager's nearby ally/enemy bridge and conveyor id lists; one pass
        per visible storage entity.
        """
        current_round = ct.get_current_round()

        storage_eids = (
            map_manager.nearby_ally_bridge_ids
            + map_manager.nearby_enemy_bridge_ids
            + map_manager.nearby_ally_conveyor_ids
            + map_manager.nearby_enemy_conveyor_ids
        )
        for eid in storage_eids:
            try:
                pos = ct.get_position(eid)
                record = map_manager.get_building(pos)
            except Exception:
                continue
            if record is None or record.entity_type not in _STORAGE_ENTITY_TYPES:
                continue
            self._observe_storage(record, current_round)

    def _observe_storage(
        self, record: EntityRecord, current_round: int
    ) -> None:
        eid = record.id
        has_resource = record.stored_resource is not None

        if eid not in self._states:
            # First time seeing this storage — assume full per spec.
            self._states[eid] = _StorageState(
                full=True,
                consecutive_full_turns=self._threshold,
                last_seen_round=current_round,
            )

        state = self._states[eid]

        # Guard against double-updates in the same round.
        if state.last_seen_round == current_round:
            return

        state.last_seen_round = current_round

        if not has_resource:
            # Observed empty — storage is definitively not full.
            state.full = False
            state.consecutive_full_turns = 0
            state.consecutive_empty_turns += 1
            if state.consecutive_empty_turns >= self._empty_threshold:
                state.empty = True
        else:
            # Observed with a resource — increment consecutive count.
            state.empty = False
            state.consecutive_empty_turns = 0
            state.consecutive_full_turns += 1
            if state.consecutive_full_turns >= self._threshold:
                state.full = True

    def is_full(self, eid: int) -> bool:
        """Return whether *eid* is considered full.

        Storages we have never seen are assumed full (conservative default).
        """
        if eid not in self._states:
            return True  # never observed → assume full
        return self._states[eid].full

    def is_empty(self, eid: int) -> bool:
        """Return whether *eid* has been empty for EMPTY_THRESHOLD+ consecutive turns.

        Storages we have never seen are assumed NOT empty (conservative default).
        """
        if eid not in self._states:
            return False
        return self._states[eid].empty

    def has_data(self, eid: int) -> bool:
        """Return whether we have any observations for this eid."""
        return eid in self._states

    def get_non_full_storage_eids(self) -> list[int]:
        """Return eids of all tracked storages that are **not** full."""
        return [eid for eid, s in self._states.items() if not s.full]

    def get_full_storage_eids(self) -> list[int]:
        """Return eids of all tracked storages that **are** full."""
        return [eid for eid, s in self._states.items() if s.full]
