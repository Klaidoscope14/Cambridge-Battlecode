from cambc import Environment, Position
from helpers.directions import CARDINAL
from helpers.geometry import on_map

AMMO_STARVATION_THRESHOLD = 40


def _adjacent_to_titanium(ct, pos: Position) -> bool:
    w, h = ct.get_map_width(), ct.get_map_height()
    for d in CARDINAL:
        n = pos.add(d)
        if not on_map(n, w, h):
            continue
        if ct.get_tile_env(n) == Environment.ORE_TITANIUM:
            return True
    return False


class AmmoStarvationTracker:
    """Self-destructs the turret if it hasn't held any ammo in the last
    AMMO_STARVATION_THRESHOLD rounds and isn't adjacent to a titanium ore tile."""

    def __init__(self) -> None:
        self._last_ammo_round: int | None = None

    def maybe_self_destruct(self, ct) -> bool:
        current_round = ct.get_current_round()

        if ct.get_ammo_amount() > 0:
            self._last_ammo_round = current_round
            return False

        if self._last_ammo_round is None:
            self._last_ammo_round = current_round
            return False

        if current_round - self._last_ammo_round <= AMMO_STARVATION_THRESHOLD:
            return False

        if _adjacent_to_titanium(ct, ct.get_position()):
            return False

        ct.self_destruct()
        return True
