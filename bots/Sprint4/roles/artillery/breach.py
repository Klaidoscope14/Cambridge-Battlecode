from cambc import Controller, EntityType
from map.map_manager import MapManager
from helpers.directions import DIRECTIONS, Direction

class Breach:
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

    def get_attack_vision(self, ct: Controller) -> list:
        facing = ct.get_direction()
        left45 = facing.rotate_left()
        left90 = facing.rotate_left()
        right45 = facing.rotate_right()
        right90 = facing.rotate_right()

        pos = ct.get_position()
        return [
            pos.add(left90),
            pos.add(left90).add(left90),

            pos.add(left45),
            pos.add(left45).add(left90),
            pos.add(left45).add(facing),

            pos.add(facing),
            pos.add(facing).add(facing),

            pos.add(right45),
            pos.add(right45).add(right90),
            pos.add(right45).add(facing),

            pos.add(right90),
            pos.add(right90).add(right90),
        ]
        
