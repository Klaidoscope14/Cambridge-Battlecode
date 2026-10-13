"""Core brain: spawn builders, maintain a babysitter. Direct ct calls."""

import random

from cambc import Controller, Direction, GameConstants, EntityType, ResourceType

from roles.builder.helpers import (
    HARVESTER_BUILDER_DIRECTIONS,
    RUSHER_DIRECTIONS,
    RUSHER_NO_BUILD_DIRECTIONS,
    RUSHER_SAVE_DIRECTIONS,
    CENTER_DIRECTIONS,
)
from helpers.constants import scaled_constant

# ── Spawning constants ──────────────────────────────────────────────
HARVESTER_BUILDER_COUNT_SMALL = 3
HARVESTER_BUILDER_COUNT_LARGE = 3
LARGE_MAP_AREA_THRESHOLD = 43 * 43
"""Maps with area strictly greater than this are considered large."""
RUSHER_COUNT = 1
CENTER_COUNT = 0
OPENING_GUARD_COUNT = 0
"""Max builders to spawn during the opening burst."""

OPENING_END_ROUND = 100
"""Last round of the opening burst phase."""

SPAWN_CADENCE_ROUNDS = 40
"""Minimum rounds between spawns in steady state."""

AXIONITE_MEMORY_ROUNDS = 20
"""How long (rounds) a raw-axionite sighting keeps the higher titanium threshold active."""

THREAT_SPAWN_COOLDOWN = 100
"""Minimum rounds between threat-response spawns."""

ALLOW_SEND_TO_CENTER: bool = True
"""If True, sending a spawned builder toward the map center is an option.
If False, center-targeting is disabled and other destinations are used."""


class CoreBrain:
    def __init__(self, ct) -> None:
        self.num_spawned = 0
        self.last_spawn_round = 0

        map_area = ct.get_map_width() * ct.get_map_height()
        self.harvester_builder_target = (
            HARVESTER_BUILDER_COUNT_LARGE
            if map_area > LARGE_MAP_AREA_THRESHOLD
            else HARVESTER_BUILDER_COUNT_SMALL
        )

        self.harvester_builder_count = 0
        self.rusher_count = 0
        self.center_count = 0
        # Steady-state rotation starts at explorer because the opening
        # burst already ends with a guard spawn.
        self.steady_spawn_index = 1

        self.last_threat_spawn_round = -THREAT_SPAWN_COOLDOWN
        self.last_axionite_seen_round = -AXIONITE_MEMORY_ROUNDS
        self.last_refined_axionite_seen_round = -AXIONITE_MEMORY_ROUNDS

        # Shuffle so the first 3 explorers are assigned to different areas.
        self._opening_harvest_order = list(HARVESTER_BUILDER_DIRECTIONS)
        random.shuffle(self._opening_harvest_order)

    
    def run(self, ct) -> None:
        current_round = ct.get_current_round()
        titanium, axionite = ct.get_global_resources()

        if self.rusher_count < RUSHER_COUNT:
            ordered = self._rusher_directions_for_next_spawn()
            success = self.build_bot_directions(ct, ordered)
            if success:
                self.rusher_count += 1
                return

        if self.harvester_builder_count < self.harvester_builder_target:
            # First two opening explorers get distinct directions from
            # the pre-shuffled list. The third doubles up on one of those
            # two areas instead of fanning out into a third.
            idx = self.harvester_builder_count
            if idx < 2:
                ordered = (
                    self._opening_harvest_order[idx:]
                    + self._opening_harvest_order[:idx]
                )
            else:
                primary = self._opening_harvest_order[random.randint(0, 1)]
                rest = [d for d in self._opening_harvest_order if d != primary]
                ordered = [primary] + rest
            success = self.build_bot_directions(ct, ordered)
            if success:
                self.harvester_builder_count += 1
                return

        if self.center_count < CENTER_COUNT:
            if self.build_center_bot(ct):
                self.center_count += 1
                return

        if current_round < OPENING_END_ROUND:
            return

        # ── Threat-response spawn ──────────────────────────────────
        # If the core sees more enemy units than ally units, spawn a
        # harvester builder to reinforce.  A cooldown prevents rapid
        # oscillation when bots enter and leave vision.
        if current_round - self.last_threat_spawn_round >= THREAT_SPAWN_COOLDOWN:
            my_team = ct.get_team()
            nearby_units = ct.get_nearby_units()
            ally_count = 0
            enemy_count = 0
            for uid in nearby_units:
                if ct.get_entity_type(uid) != EntityType.BUILDER_BOT:
                    continue
                if ct.get_team(uid) == my_team:
                    ally_count += 1
                else:
                    enemy_count += 1
            if enemy_count > ally_count:
                idx = self.harvester_builder_count
                ordered = (
                    self._opening_harvest_order[idx:]
                    + self._opening_harvest_order[:idx]
                )
                success = self.build_bot_directions(ct, ordered)
                if success:
                    self.harvester_builder_count += 1
                    self.last_threat_spawn_round = current_round
                    return

        rounds_since_spawn = current_round - self.last_spawn_round
        should_build = False

        saw_raw, saw_refined = self._sees_axionite_on_conveyor(ct)
        if saw_raw:
            self.last_axionite_seen_round = current_round
        if saw_refined:
            self.last_refined_axionite_seen_round = current_round

        power_threshold = ct.get_harvester_cost()[0] + ct.get_builder_bot_cost()[0] * 1.5
        saw_raw_recently = current_round - self.last_axionite_seen_round < AXIONITE_MEMORY_ROUNDS
        saw_refined_recently = current_round - self.last_refined_axionite_seen_round < AXIONITE_MEMORY_ROUNDS
        if saw_raw_recently and not saw_refined_recently:
            threshold = max(power_threshold, ct.get_foundry_cost()[0] + ct.get_builder_bot_cost()[0])
        else:
            threshold = power_threshold
        if rounds_since_spawn >= SPAWN_CADENCE_ROUNDS and titanium >= threshold:
            should_build = True

        if should_build:
            # Rotate through guard → explorer → rusher in a fixed pattern.
            # On success, advance the cycle; on failure, leave it alone so
            # the same slot is retried next tick.
            pattern = (
                (HARVESTER_BUILDER_DIRECTIONS, "harvester"),
                (RUSHER_DIRECTIONS, "rusher"),
                (HARVESTER_BUILDER_DIRECTIONS, "harvester"),
                (CENTER_DIRECTIONS, "center"),
                (RUSHER_DIRECTIONS, "rusher"),
                (HARVESTER_BUILDER_DIRECTIONS, "harvester"),
                (RUSHER_DIRECTIONS, "rusher"),
            )
            base_dirs, kind = pattern[self.steady_spawn_index % len(pattern)]
            if kind == "center":
                success = self.build_center_bot(ct)
                if success:
                    self.center_count += 1
                    self.steady_spawn_index += 1
                return
            if kind == "harvester":
                idx = self.harvester_builder_count
                dirs = (
                    self._opening_harvest_order[idx:]
                    + self._opening_harvest_order[:idx]
                )
            elif kind == "rusher":
                dirs = self._rusher_directions_for_next_spawn()
            else:
                dirs = list(base_dirs)
                random.shuffle(dirs)
            success = self.build_bot_directions(ct, dirs)
            if success:
                if kind == "harvester":
                    self.harvester_builder_count += 1
                else:
                    self.rusher_count += 1
                self.steady_spawn_index += 1

    def build_center_bot(self, ct: Controller) -> bool:
        """Spawn a builder on the core centre tile (Direction.CENTRE).
        Centre-spawned bots are routed to StateManager._determine_center,
        which mirrors the explorer path minus FOLLOW."""
        target = ct.get_position().add(Direction.CENTRE)
        if ct.can_spawn(target):
            return bool(ct.spawn_builder(target))
        return False

    # ── Helpers ──────────────────────────────────────────────────
    def _sees_axionite_on_conveyor(self, ct: Controller) -> tuple[bool, bool]:
        saw_raw = False
        saw_refined = False
        for eid in ct.get_nearby_entities():
            etype = ct.get_entity_type(eid)
            if etype != EntityType.CONVEYOR and etype != EntityType.BRIDGE:
                continue
            stored = ct.get_stored_resource(eid)
            if stored == ResourceType.RAW_AXIONITE:
                saw_raw = True
            elif stored == ResourceType.REFINED_AXIONITE:
                saw_refined = True
            if saw_raw and saw_refined:
                break
        return saw_raw, saw_refined

    def _rusher_directions_for_next_spawn(self) -> list[Direction]:
        """Alternate the preferred rusher spawn group.

        Even rusher_count → prefer no-build (N/S); odd → prefer save (E/W).
        The other group is appended as fallback so a spawn still happens
        when the preferred tiles are blocked."""
        primary = list(RUSHER_NO_BUILD_DIRECTIONS)
        secondary = list(RUSHER_SAVE_DIRECTIONS)
        random.shuffle(primary)
        random.shuffle(secondary)
        if self.rusher_count % 2 == 0:
            return primary + secondary
        return secondary + primary

    def build_bot_directions(self, ct: Controller, dirs: list[Direction]):
        """Try each direction in *dirs* until a spawn succeeds."""
        pos = ct.get_position()
        for d in dirs:
            if not ALLOW_SEND_TO_CENTER and d == Direction.CENTRE:
                continue
            target = pos.add(d)
            if ct.can_spawn(target):
                return ct.spawn_builder(target)
        return None