"""Core brain: spawn builders, maintain a babysitter. Direct ct calls."""

from helpers.constants import scaled_constant
from roles.core.helpers import build_builder, build_babysitter, build_rusher

# ── Spawning constants ──────────────────────────────────────────────
OPENING_MAX_BUILDERS = 1
"""Max builders to spawn during the opening burst."""

OPENING_END_ROUND = 300
"""Last round of the opening burst phase."""

SPAWN_CADENCE_ROUNDS = 30
"""Minimum rounds between spawns in steady state."""

BABYSITTER_SPAWN_ROUND = 5
"""Earliest round to attempt spawning the babysitter."""

RUSHER_COUNT = 2

class CoreBrain:
    def __init__(self, ct) -> None:
        self.num_spawned = 0
        self.last_spawn_round = 0
        self.babysitter_id = None
        self.rushers = 0

    # ── Babysitter management ───────────────────────────────────────
    def _ensure_babysitter(self, ct, current_round: int) -> None:
        """Guarantee exactly one babysitter is alive.

        The babysitter never leaves vision range, so if we can no
        longer sense it the bot is dead and must be replaced.
        """
        if current_round < BABYSITTER_SPAWN_ROUND:
            return

        # Still alive — nothing to do
        if self.babysitter_id is not None:
            if self.babysitter_id in ct.get_nearby_entities():
                return

        print("WTF")

        # Dead or never spawned — try to create a new one
        new_id = build_babysitter(ct)
        if new_id is not None:
            self.babysitter_id = new_id

    # ── Main loop ───────────────────────────────────────────────────
    def run(self, ct) -> None:
        current_round = ct.get_current_round()
        titanium, axionite = ct.get_global_resources()
        # Always keep the babysitter alive — takes priority over builders

        # Build rushers
        if self.rushers < RUSHER_COUNT:
            success = build_rusher(ct)
            if success:
                self.rushers += 1
                return
        
        if ct.get_scale_percent() > 200:
            self._ensure_babysitter(ct, current_round)

        if current_round <= OPENING_END_ROUND:
            if self.num_spawned < OPENING_MAX_BUILDERS:
                if build_builder(ct):
                    self.num_spawned += 1
                    self.last_spawn_round = current_round
            return

        rounds_since_spawn = current_round - self.last_spawn_round
        should_build = False

        if rounds_since_spawn >= SPAWN_CADENCE_ROUNDS and titanium >= ct.get_harvester_cost()[0] * 2.5:
            should_build = True

        if should_build:
            if build_builder(ct):
                self.num_spawned += 1
                self.last_spawn_round = current_round
