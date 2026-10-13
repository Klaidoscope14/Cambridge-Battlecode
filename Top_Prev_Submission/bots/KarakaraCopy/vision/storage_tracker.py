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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cambc import EntityType, ResourceType

if TYPE_CHECKING:
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


RESOURCE_WINDOW = 15  # rounds a resource type lingers in `recent_resources`


@dataclass(slots=True)
class _StorageState:
    """Internal per-storage tracking state."""
    full: bool = True  # assume full until proven otherwise
    empty: bool = False  # True if last observation had no resource
    confirmed_empty: bool = False  # True after EMPTY_THRESHOLD consecutive empty turns
    confirmed_full: bool = False  # True after FULL_THRESHOLD consecutive observed-with-resource turns
    consecutive_full_turns: int = FULL_THRESHOLD  # start at threshold (assumed full)
    consecutive_resource_observations: int = 0  # actual consecutive turns observed with a resource
    consecutive_empty_turns: int = 0
    last_seen_round: int | None = None
    # Resource types observed on this storage within RESOURCE_WINDOW rounds.
    # Eagerly maintained alongside _resource_last_round so callers can do an
    # O(1) "did this storage carry X recently?" check.
    recent_resources: set[ResourceType] = field(default_factory=set)
    # ResourceType -> most recent round we saw it on this storage. Used to
    # prune entries that have aged out of the window.
    _resource_last_round: dict[ResourceType, int] = field(default_factory=dict)


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

        Iterates the per-turn record lists from MapManager. The `_states`
        dict stays eid-keyed (record.id) since it's identity tracking that
        survives across rounds.
        """
        current_round = ct.get_current_round()

        for record in map_manager.nearby_ally_bridge_ids:
            if record.entity_type not in _STORAGE_ENTITY_TYPES:
                continue
            self._observe_storage(record, current_round)

        for record in map_manager.nearby_enemy_bridge_ids:
            if record.entity_type not in _STORAGE_ENTITY_TYPES:
                continue
            self._observe_storage(record, current_round)

        for record in map_manager.nearby_ally_conveyor_ids:
            if record.entity_type not in _STORAGE_ENTITY_TYPES:
                continue
            self._observe_storage(record, current_round)

        for record in map_manager.nearby_enemy_conveyor_ids:
            if record.entity_type not in _STORAGE_ENTITY_TYPES:
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
            state.confirmed_full = False
            state.empty = True
            state.consecutive_full_turns = 0
            state.consecutive_resource_observations = 0
            state.consecutive_empty_turns += 1
            if state.consecutive_empty_turns >= self._empty_threshold:
                state.confirmed_empty = True
        else:
            # Observed with a resource — increment consecutive count.
            state.empty = False
            state.confirmed_empty = False
            state.consecutive_empty_turns = 0
            state.consecutive_full_turns += 1
            state.consecutive_resource_observations += 1
            if state.consecutive_full_turns >= self._threshold:
                state.full = True
            if state.consecutive_resource_observations >= self._threshold:
                state.confirmed_full = True
            # Refresh sliding-window tracking for this resource type.
            state._resource_last_round[record.stored_resource] = current_round
            state.recent_resources.add(record.stored_resource)

        # Prune any resource types that have aged out of the window. Done
        # every observation (not just on empty) so the set stays accurate
        # whether the storage is currently empty or carrying something else.
        cutoff = current_round - RESOURCE_WINDOW
        expired = [r for r, t in state._resource_last_round.items() if t < cutoff]
        for r in expired:
            del state._resource_last_round[r]
            state.recent_resources.discard(r)

    def is_full(self, eid: int) -> bool:
        """Return whether *eid* is considered full.

        Storages we have never seen are assumed full (conservative default).
        """
        if eid not in self._states:
            return True  # never observed → assume full
        return self._states[eid].full

    def is_empty(self, eid: int) -> bool:
        """Return whether *eid* was empty on its most recent observation.

        Storages we have never seen are assumed NOT empty (conservative default).
        """
        if eid not in self._states:
            return False
        return self._states[eid].empty

    def confirmed_empty(self, eid: int) -> bool:
        """Return whether *eid* has been empty for EMPTY_THRESHOLD+ consecutive turns.

        Storages we have never seen are assumed NOT empty (conservative default).
        """
        if eid not in self._states:
            return False
        return self._states[eid].confirmed_empty

    def confirmed_full(self, eid: int) -> bool:
        """Return whether *eid* has been observed with a resource for
        FULL_THRESHOLD+ consecutive turns.

        Stricter than ``is_full``: storages we have never seen, or have only
        seen briefly, are NOT confirmed full. Use this when a conservative
        "assume full" default would cause false negatives — e.g. ConveyorAStar
        wants to connect into belts that aren't *definitively* full, including
        ones it has only just started observing.
        """
        if eid not in self._states:
            return False
        return self._states[eid].confirmed_full

    def has_data(self, eid: int) -> bool:
        """Return whether we have any observations for this eid."""
        return eid in self._states

    def get_recent_resources(self, eid: int) -> set[ResourceType]:
        """Return resource types observed on *eid* within the last
        ``RESOURCE_WINDOW`` rounds.

        Returns an empty set for unknown eids. The returned set is the live
        backing set — do not mutate it.
        """
        if eid not in self._states:
            return set()
        return self._states[eid].recent_resources

    def get_non_full_storage_eids(self) -> list[int]:
        """Return eids of all tracked storages that are **not** full."""
        return [eid for eid, s in self._states.items() if not s.full]

    def get_full_storage_eids(self) -> list[int]:
        """Return eids of all tracked storages that **are** full."""
        return [eid for eid, s in self._states.items() if s.full]
