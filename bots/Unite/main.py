from cambc import EntityType, GameError

from helpers import logging as core_logging
from roles.core.core_brain import CoreBrain
from roles.builder.builder_brain import BuilderBrain
from roles.artillery.gunner import Gunner
from roles.artillery.sentinel import Sentinel
from roles.artillery.breach import Breach
from roles.artillery.launcher import Launcher


class Player:
    def __init__(self) -> None:
        self.brain = None
        pass

    def run(self, ct) -> None:
        """Route by controller entity type; run the corresponding brain."""
        try:
            etype = ct.get_entity_type()

            if etype == EntityType.CORE:
                if (self.brain == None): self.brain = CoreBrain(ct)
                self.brain.run(ct)
            elif etype == EntityType.BUILDER_BOT:
                if (self.brain == None): self.brain = BuilderBrain(ct)
                self.brain.run(ct)
            elif etype == EntityType.GUNNER:
                gunner = Gunner(ct)
                gunner.run(ct)
            elif etype == EntityType.SENTINEL:
                sentinel = Sentinel(ct)
                sentinel.run(ct)
            elif etype == EntityType.BREACH:
                breach = Breach(ct)
                breach.run(ct)
            elif etype == EntityType.LAUNCHER:
                launcher = Launcher(ct)
                launcher.run(ct)
            # else: structure or unknown — no-op
        except GameError:
            if core_logging.DEBUG:
                raise
            pass


__all__ = ["Player"]
