from cambc import Controller, Position, EntityType
from helpers.directions import DIRECTIONS, Direction
from vision.vision_manager import VisionManager

class Gunner:
    def __init__(self, ct) -> None:
        self.vision_manager = VisionManager(ct)
    def run(self, ct) -> None:
        self.map_manager.update(ct)
        # self.shoot(ct)

    def shoot(self, ct: Controller) -> bool:
        attack_vision = self.get_attack_vision(ct)
        for eid in self.vision_manager.nearby_enemy_bot_ids:
            if ct.get_position(eid) in attack_vision:
                return True
        return False

    def get_attack_vision(self, ct: Controller) -> list:
        facing = ct.get_direction()
        return [
            ct.get_position().add(facing),
            ct.get_position().add(facing).add(facing),
            ct.get_position().add(facing).add(facing).add(facing),
        ]

