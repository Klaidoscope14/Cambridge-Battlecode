"""Core brain: spawn builders, maintain a babysitter. Direct ct calls."""

import random

from cambc import Controller, Direction, GameConstants

from roles.builder.helpers import (
    HARVESTER_BUILDER_DIRECTIONS,
    RUSHER_DIRECTIONS,
)
from helpers.constants import scaled_constant

# ── Spawning constants ──────────────────────────────────────────────
HARVESTER_BUILDER_COUNT = 3
RUSHER_COUNT = 2
OPENING_GUARD_COUNT = 0
"""Max builders to spawn during the opening burst."""

OPENING_END_ROUND = 100
"""Last round of the opening burst phase."""

SPAWN_CADENCE_ROUNDS = 30
"""Minimum rounds between spawns in steady state."""

THREAT_SPAWN_COOLDOWN = 5
"""Minimum rounds between threat-response spawns."""


class CoreBrain:
    def __init__(self, ct) -> None:
        self.num_spawned = 0
        self.last_spawn_round = 0

        self.harvester_builder_count = 0
        self.rusher_count = 0
        self.guard_count = 0
        # Steady-state rotation starts at explorer because the opening
        # burst already ends with a guard spawn.
        self.steady_spawn_index = 1

        self.last_threat_spawn_round = -THREAT_SPAWN_COOLDOWN

        # Shuffle so the first 3 explorers are assigned to different areas.
        self._opening_harvest_order = list(HARVESTER_BUILDER_DIRECTIONS)
        random.shuffle(self._opening_harvest_order)

    
    def run(self, ct) -> None:
        current_round = ct.get_current_round()
        titanium, axionite = ct.get_global_resources()
        # Always keep the babysitter alive — takes priority over builders

        if self.rusher_count < RUSHER_COUNT:
            success = self.build_bot_directions(ct, RUSHER_DIRECTIONS)
            if success:
                self.rusher_count += 1
                return

        if self.harvester_builder_count < HARVESTER_BUILDER_COUNT:
            # Each opening explorer gets the next direction from the
            # pre-shuffled list, guaranteeing they cover different areas.
            idx = self.harvester_builder_count
            ordered = (
                self._opening_harvest_order[idx:]
                + self._opening_harvest_order[:idx]
            )
            success = self.build_bot_directions(ct, ordered)
            if success:
                self.harvester_builder_count += 1
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

        scale = ct.get_scale_percent()
        if rounds_since_spawn >= SPAWN_CADENCE_ROUNDS and titanium >= GameConstants.HARVESTER_BASE_COST[0] * pow((scale / 100), 1.2) * 2:
            should_build = True

        if should_build:
            # Rotate through guard → explorer → rusher in a fixed pattern.
            # On success, advance the cycle; on failure, leave it alone so
            # the same slot is retried next tick.
            pattern = (
                (HARVESTER_BUILDER_DIRECTIONS, "harvester"),
                (RUSHER_DIRECTIONS, "rusher"),
            )
            base_dirs, kind = pattern[self.steady_spawn_index % 2]
            if kind == "harvester":
                idx = self.harvester_builder_count
                dirs = (
                    self._opening_harvest_order[idx:]
                    + self._opening_harvest_order[:idx]
                )
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

    # ── Helpers ──────────────────────────────────────────────────
    def build_bot_directions(self, ct: Controller, dirs: list[Direction]):
        """Try each direction in *dirs* until a spawn succeeds."""
        pos = ct.get_position()
        for d in dirs:
            target = pos.add(d)
            if ct.can_spawn(target):
                return ct.spawn_builder(target)
        return None