"""GunnerBlockedTracker: counts consecutive observed turns where an ally
gunner is facing directly into another ally turret/barrier (a wall it can
never shoot past). Once the count crosses the threshold, the gunner is a
candidate for cleanup-and-replace.

Only credits turns we actually see the gunner — out-of-vision turns
neither increment nor reset the counter (conservative).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cambc import EntityType

if TYPE_CHECKING:
    from map.map_manager import MapManager


BLOCKED_THRESHOLD = 16

_BLOCKING_ALLY_TYPES = frozenset((
    EntityType.BARRIER,
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.LAUNCHER,
))


@dataclass(slots=True)
class _GunnerState:
    consecutive_blocked_turns: int = 0
    last_seen_round: int | None = None


class GunnerBlockedTracker:
    def __init__(self, ct, blocked_threshold: int = BLOCKED_THRESHOLD) -> None:
        self._threshold = blocked_threshold
        self._states: dict[int, _GunnerState] = {}

    def update(self, ct, map_manager: MapManager) -> None:
        current_round = ct.get_current_round()
        my_team = ct.get_team()
        for record in map_manager.nearby_ally_turret_ids:
            if record.entity_type != EntityType.GUNNER:
                continue
            if record.team != my_team:
                continue
            self._observe(record, map_manager, current_round)

    def _observe(self, record, map_manager: MapManager, current_round: int) -> None:
        eid = record.id
        state = self._states.get(eid)
        if state is None:
            state = _GunnerState()
            self._states[eid] = state

        if state.last_seen_round == current_round:
            return
        state.last_seen_round = current_round

        front_pos = record.position.add(record.direction)
        front_building = map_manager.get_building(front_pos)
        my_team = record.team
        if (
            front_building is not None
            and front_building.team == my_team
            and front_building.entity_type in _BLOCKING_ALLY_TYPES
        ):
            state.consecutive_blocked_turns += 1
        else:
            state.consecutive_blocked_turns = 0

    def confirmed_blocked(self, eid: int) -> bool:
        state = self._states.get(eid)
        if state is None:
            return False
        return state.consecutive_blocked_turns >= self._threshold

    def blocked_turns(self, eid: int) -> int:
        state = self._states.get(eid)
        if state is None:
            return 0
        return state.consecutive_blocked_turns
