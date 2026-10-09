from __future__ import annotations


COOLDOWN_ROUNDS = 20


class DamageTracker:
    """Tracks tiles where we took damage and cools them down over time."""

    def __init__(self, ct) -> None:
        self._prev_hp: int = ct.get_hp()
        # (x, y) -> round damage was last taken
        self._damaged_tiles: dict[tuple[int, int], int] = {}

    def update(self, ct) -> None:
        current_hp = ct.get_hp()
        current_round = ct.get_current_round()

        if current_hp < self._prev_hp:
            pos = ct.get_position()
            self._damaged_tiles[(pos.x, pos.y)] = current_round

        self._prev_hp = current_hp

        # Evict expired entries
        expired = [
            k for k, r in self._damaged_tiles.items()
            if current_round - r >= COOLDOWN_ROUNDS
        ]
        for k in expired:
            del self._damaged_tiles[k]

    def is_dangerous(self, pos) -> bool:
        return (pos.x, pos.y) in self._damaged_tiles
