"""TitaniumTracker: detect whether the first harvester has been built.

Detection logic (checked each round):
1. Titanium *increased* since last round → a harvester is producing, so one
   exists.  Mark built immediately.
2. Titanium *decreased* by at least HARVESTER_BASE_COST → someone just spent
   enough to build one.  Mark built immediately.
3. Neither condition met yet → first harvester has not been confirmed.
"""

from cambc import Controller, GameConstants


class TitaniumTracker:
    def __init__(self, ct: Controller) -> None:
        self._first_harvester_built: bool = False
        self._prev_titanium: int = ct.get_global_resources()[0]

    @property
    def first_harvester_built(self) -> bool:
        return self._first_harvester_built

    def update(self, ct: Controller) -> None:
        if self._first_harvester_built:
            return

        current_titanium = ct.get_global_resources()[0]
        delta = current_titanium - self._prev_titanium

        if delta > 0:
            # Titanium went up — a harvester is producing
            self._first_harvester_built = True
            print("TitaniumTracker: titanium increased, first harvester confirmed")

        elif -delta >= GameConstants.HARVESTER_BASE_COST[0]:
            # Titanium dropped by at least a harvester's base cost
            self._first_harvester_built = True
            print("TitaniumTracker: large titanium spend detected, first harvester confirmed")

        self._prev_titanium = current_titanium