"""CoreConnectState: place the first bridge adjacent to an unconnected source.

Walks to the source, finds the best cardinal slot toward core, and uses the
Connector to place one bridge with the correct target (same chain logic that
RepairBridge uses). The dangling bridge is then picked up by RepairBridgeState
(via bridge_tracer) to chain back to core.
"""

from cambc import Controller, EntityType, Position

from helpers.directions import DIRECTIONS
from roles.builder.helpers import in_bounds
from core_supply.connector import (
    Connector,
    is_valid_bridge_pos,
    has_adjacent_ally_bridge,
)
from nav.common import common_path
from conveyor.traverse import surround_4

CONNECT_TIMEOUT_ROUNDS = 10
COOLDOWN_ROUNDS = 30


def has_adjacent_enemy_bridge(ct, pos, map_manager) -> bool:
    team = ct.get_team()
    for d in DIRECTIONS:
        neighbor = pos.add(d)
        if not in_bounds(ct, neighbor):
            continue
        building = map_manager.get_building(neighbor)
        if (
            building is not None
            and building.entity_type == EntityType.BRIDGE
            and building.team != team
        ):
            return True
    return False


def _find_best_slot(ct, connector, map_manager, source_pos):
    """Pick the best cardinal slot adjacent to source_pos for the first bridge.

    Uses the Connector's baseline logic to prefer the slot that makes the
    most progress toward core.
    """
    candidates = [
        s for s in surround_4(source_pos)
        if is_valid_bridge_pos(ct, map_manager, s, allow_near_source=True)
    ]
    if not candidates:
        return None

    # Use Connector's baseline to pick direction
    baseline = connector._find_baseline(ct, source_pos, set())
    if baseline is not None:
        candidates.sort(key=lambda c: c.distance_squared(baseline))

    return candidates[0]


class CoreConnectState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.map_manager = brain.map_manager
        self.connector = Connector(ct, brain.map_manager, brain.vision_manager, brain.storage_tracker)
        self.source_pos = None
        self._first_seen: dict[tuple[int, int], int] = {}
        self.cooldowns: dict[tuple[int, int], int] = {}
        self._connected_sources: set[tuple[int, int]] = set()

    def _is_on_cooldown(self, key: tuple[int, int], current_round: int) -> bool:
        if key not in self.cooldowns:
            return False
        if current_round - self.cooldowns[key] >= COOLDOWN_ROUNDS:
            del self.cooldowns[key]
            return False
        return True

    def _start_cooldown(self, key: tuple[int, int], current_round: int):
        self.cooldowns[key] = current_round
        self._first_seen.pop(key, None)
        self.connector.reset(self.source_pos)

    def is_connected(self, pos: Position) -> bool:
        return (pos.x, pos.y) in self._connected_sources

    def execute(self, ct):
        if self.source_pos is None:
            return

        current_round = ct.get_current_round()
        key = (self.source_pos.x, self.source_pos.y)

        if self._is_on_cooldown(key, current_round):
            return

        if has_adjacent_enemy_bridge(ct, self.source_pos, self.map_manager):
            print(f"CoreConnect: enemy bridge adjacent to {self.source_pos}, cooling down")
            self._start_cooldown(key, current_round)
            return

        # Timeout
        if key not in self._first_seen:
            self._first_seen[key] = current_round
        if current_round - self._first_seen[key] >= CONNECT_TIMEOUT_ROUNDS:
            print(f"CoreConnect: timed out on {self.source_pos}, cooling down")
            self._start_cooldown(key, current_round)
            return

        # Check if a bridge already appeared (someone else built it)
        if has_adjacent_ally_bridge(ct, self.source_pos, self.map_manager):
            print(f"CoreConnect: source {self.source_pos} already has adjacent bridge, done")
            self._connected_sources.add(key)
            self._first_seen.pop(key, None)
            return

        # Find where to place the bridge
        slot = _find_best_slot(ct, self.connector, self.map_manager, self.source_pos)

        if slot is None:
            print(f"CoreConnect: no valid slot around {self.source_pos}, cooling down")
            self._start_cooldown(key, current_round)
            return

        # Walk toward the slot first — skip expensive connector work until adjacent
        my_pos = ct.get_position()
        dist = abs(my_pos.x - slot.x) + abs(my_pos.y - slot.y)
        if dist > 1:
            common_path(ct, self.map_manager, self.brain.pathing, slot)
            return

        print(f"CoreConnect: placing first bridge at {slot} for source {self.source_pos}")

        # Seed the Connector with this slot as the frontier, then let it
        # pick the correct target using the same chain logic as RepairBridge
        progress = self.connector._get_or_create(slot)
        if progress.frontier is None:
            progress.frontier = slot

        # Try to advance — this places one bridge from slot toward core
        connected = self.connector.connect(ct, slot)

        if connected:
            print(f"CoreConnect: bridge placed and fully connected for {self.source_pos}")
            self._connected_sources.add(key)
            self._first_seen.pop(key, None)
            return

        # Bridge placed (or attempted) — check if frontier moved (meaning bridge was built)
        new_frontier = self.connector.get_frontier(slot)
        if new_frontier is not None and (new_frontier.x != slot.x or new_frontier.y != slot.y):
            print(f"CoreConnect: first bridge built at {slot}, repair will continue chain")
            self._connected_sources.add(key)
            self._first_seen.pop(key, None)
            return