"""Core brain: spawn builders, maintain a babysitter. Direct ct calls."""

from cambc import Controller, Direction, GameConstants

from roles.builder.helpers import HARVESTER_BUILDER_DIRECTION, RUSHER_DIRECTION
from helpers.constants import scaled_constant

# ── Spawning constants ──────────────────────────────────────────────
HARVESTER_BUILDER_COUNT = 3
RUSHER_COUNT = 2
"""Max builders to spawn during the opening burst."""

OPENING_END_ROUND = 100
"""Last round of the opening burst phase."""

SPAWN_CADENCE_ROUNDS = 30
"""Minimum rounds between spawns in steady state."""


class CoreBrain:
    def __init__(self, ct) -> None:
        self.num_spawned = 0
        self.last_spawn_round = 0
        
        self.harvester_builder_count = 0
        self.rusher_count = 0

    
    def run(self, ct) -> None:
        current_round = ct.get_current_round()
        titanium, axionite = ct.get_global_resources()
        # Always keep the babysitter alive — takes priority over builders

        if self.rusher_count < RUSHER_COUNT:
            success = self.build_bot_direction(ct, RUSHER_DIRECTION)
            if success:
                self.rusher_count += 1
                return
            
        if self.harvester_builder_count < HARVESTER_BUILDER_COUNT:
            success = self.build_bot_direction(ct, HARVESTER_BUILDER_DIRECTION)
            if success:
                self.harvester_builder_count += 1
                return
            
            
        if current_round < OPENING_END_ROUND:
            return

        rounds_since_spawn = current_round - self.last_spawn_round
        should_build = False

        scale = ct.get_scale_percent()
        if rounds_since_spawn >= SPAWN_CADENCE_ROUNDS and titanium >= GameConstants.HARVESTER_BASE_COST[0] * pow((scale / 100), 1.5) * 2:
            should_build = True

        if should_build:
            # Maintain a 1:1 ratio of harvester builders to rushers
            if self.rusher_count * 1 < self.harvester_builder_count:
                success = self.build_bot_direction(ct, RUSHER_DIRECTION)
                if success:
                    self.rusher_count += 1
            else:
                success = self.build_bot_direction(ct, HARVESTER_BUILDER_DIRECTION)
                if success:
                    self.harvester_builder_count += 1

    # ── Helper ───────────────────────────────────────────────────
    def build_bot_direction(self, ct: Controller, d: Direction):
        if ct.can_spawn(ct.get_position().add(d)):
            bot_id = ct.spawn_builder(ct.get_position().add(d))
            return bot_id
        return None