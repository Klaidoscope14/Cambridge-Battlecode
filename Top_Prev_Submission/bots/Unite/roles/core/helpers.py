from cambc import Controller, Direction
from roles.builder.helpers import RUSHER_DIRECTION, BABYSITTER_DIRECTION

def build_builder(ct: Controller) -> bool:
    for d in Direction:
        if d == BABYSITTER_DIRECTION or d == RUSHER_DIRECTION:
            continue
        spawn_pos = ct.get_position().add(d)
        if ct.can_spawn(spawn_pos):
            ct.spawn_builder(spawn_pos)
            return True
    return False


def build_babysitter(ct: Controller):
    if ct.can_spawn(ct.get_position().add(BABYSITTER_DIRECTION)):
        bot_id = ct.spawn_builder(ct.get_position().add(BABYSITTER_DIRECTION))
        return bot_id
    return None

def build_rusher(ct: Controller):
    if (ct.can_spawn(ct.get_position().add(RUSHER_DIRECTION))):
        ct.spawn_builder(ct.get_position().add(RUSHER_DIRECTION))
        return True
    return False