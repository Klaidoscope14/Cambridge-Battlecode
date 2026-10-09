"""RepairBridgeState: chain a dangling bridge back to the core.

Detected by bridge_tracer (broken chain or first-link break), this state
uses the Connector to extend the chain from the break position back to
a core tile. One bridge per execute() call.

When a repair fails (timeout / no valid slot), the cooldown is keyed on
the *current frontier* (the last bridge placed), not the original break.
This prevents bridge_tracer from immediately re-detecting the frontier as
a new break and retrying the same stuck chain.
"""

from cambc import Controller, EntityType, Position

from comms.markers import place_bridge_work_marker
from core_supply.connector import Connector
from nav.common import common_path

REPAIR_TIMEOUT_ROUNDS = 120
REPAIR_COOLDOWN_ROUNDS = 30


class RepairBridgeState:

    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.map_manager = brain.map_manager
        self.connector = Connector(ct, brain.map_manager, brain.vision_manager, brain.storage_tracker)

        self.break_pos: Position | None = None
        self.source_pos: Position | None = None

        self._first_seen: dict[tuple[int, int], int] = {}
        self._repair_complete: bool = False
        self.cooldowns: dict[tuple[int, int], int] = {}
        self.repair_blacklist: set[tuple[int, int]] = set()

    @property
    def finished(self) -> bool:
        return self._repair_complete

    # -- Cooldown helpers -----------------------------------------------------

    def _is_on_cooldown(self, key: tuple[int, int], current_round: int) -> bool:
        if key not in self.cooldowns:
            return False
        if current_round - self.cooldowns[key] >= REPAIR_COOLDOWN_ROUNDS:
            del self.cooldowns[key]
            return False
        return True

    def _start_cooldown(self, key: tuple[int, int], current_round: int):
        """Cooldown both the original break and the current frontier.

        bridge_tracer will re-detect the frontier (last placed bridge) as a
        new break. Cooling down the frontier prevents immediate retries on
        the same stuck chain.
        """
        self.cooldowns[key] = current_round

        # Also cooldown the frontier if it differs from the break
        if self.source_pos is not None:
            frontier = self.connector.get_frontier(self.source_pos)
            if frontier is not None:
                frontier_key = (frontier.x, frontier.y)
                if frontier_key != key:
                    self.cooldowns[frontier_key] = current_round

        self._first_seen.pop(key, None)
        if self.source_pos is not None:
            self.connector.reset(self.source_pos)

    def reset(self):
        if self.source_pos is not None:
            self.connector.reset(self.source_pos)
        self.break_pos = None
        self.source_pos = None
        self._repair_complete = False

    # -- Marker helpers -------------------------------------------------------

    def _try_place_marker(self, ct: Controller) -> None:
        """Place a bridge-work marker next to the bot every tick.

        The marker encodes the break position in its value. It sits
        adjacent to the bot — not adjacent to the break — just like
        harvester-claim markers.

        Markers can get destroyed by other bots or expiry at any time,
        so we re-place unconditionally to keep the claim fresh.
        """
        if self.break_pos is None:
            return
        place_bridge_work_marker(ct, self.break_pos)

    # -- Execute --------------------------------------------------------------

    def execute(self, ct: Controller):
        if self.break_pos is None:
            return

        current_round = ct.get_current_round()
        key = (self.break_pos.x, self.break_pos.y)

        if self._is_on_cooldown(key, current_round):
            return

        # Timeout
        if key not in self._first_seen:
            self._first_seen[key] = current_round
        if current_round - self._first_seen[key] >= REPAIR_TIMEOUT_ROUNDS:
            print(f"RepairBridge: timed out on {self.break_pos}, cooling down")
            self._start_cooldown(key, current_round)
            return

        # Keep retrying marker placement every tick until one sticks
        self._try_place_marker(ct)

        print(f"RepairBridge: repairing break at {self.break_pos}")

        # Advance the chain by one step
        connected = self.connector.connect(ct, self.source_pos)
        if connected:
            print("RepairBridge: repair complete")
            self._repair_complete = True
            return

        # Not connected yet — walk toward the current frontier
        frontier = self.connector.get_frontier(self.source_pos)
        target = frontier if frontier is not None else self.source_pos
        my_pos = ct.get_position()
        if my_pos.x != target.x or my_pos.y != target.y:
            common_path(ct, self.map_manager, self.brain.pathing, target)

        # Check if frontier is stuck
        if frontier is None:
            print(f"RepairBridge: no valid slot for {self.break_pos}, cooling down")
            self._start_cooldown(key, current_round)
            return

        # Check if someone else already placed a bridge at frontier
        building = self.map_manager.get_building(frontier)
        if building is not None and building.entity_type == EntityType.BRIDGE:
            print(f"RepairBridge: frontier {frontier} already has a bridge, marking connected")
            self._repair_complete = True
            return