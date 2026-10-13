from cambc import Controller, Position, EntityType
from debug.profiling import cputimer
from map.map_manager import MapManager
from helpers.directions import DIRECTIONS, Direction

class Launcher:
    def __init__(self, ct) -> None:
        self.map_manager = MapManager(ct)

    def run(self, ct) -> None:
        self.map_manager.update(ct)
        self.shoot(ct)

    def shoot(self, ct):
        attack_vision = self.get_attack_vision(ct)
        for pos in attack_vision:
            ct.draw_indicator_dot(pos, 1, 1, 1)
            if self.map_manager.get_bot(pos) is not None:
                ct.fire(pos)
                ct.draw_indicator_dot(pos, 1, 0, 0)
                return True
        return False

    @cputimer
    def get_attack_vision(self, ct: Controller) -> list:
        pos = ct.get_position()
        attack_vision = []

        for d in DIRECTIONS:
            attack_vision.append(pos.add(d))

        return attack_vision

