from cambc import Controller, EntityType, Position
from map.map_manager import MapManager

SENTINEL_DAMAGE = 18

# ── Priority order: lower index = shoot first ─────────────────────

TARGET_PRIORITY = [
    EntityType.BUILDER_BOT,
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
    EntityType.LAUNCHER,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.FOUNDRY,
    EntityType.CORE,
    EntityType.BARRIER,
    EntityType.ROAD,
]

_PRIORITY_INDEX = {et: i for i, et in enumerate(TARGET_PRIORITY)}


class Sentinel:
    def __init__(self, ct) -> None:
        self.map_manager = MapManager(ct)

    def run(self, ct) -> None:
        self.shoot(ct)

    def shoot(self, ct) -> bool:
        team = ct.get_team()

        # Collect all candidate targets: (priority_index, hp, pos)
        candidates = []
        attack_vision = ct.get_attackable_tiles()

        for pos in attack_vision:

            # Enemy bot on tile
            bbid = ct.get_tile_builder_bot_id(pos)
            if bbid is not None:
                if ct.get_team(bbid) != team:
                    pri = _PRIORITY_INDEX.get(EntityType.BUILDER_BOT)
                    hp = ct.get_hp(bbid)
                    candidates.append((pri, hp, pos))
                continue

            # Ignore same team
            tbid = ct.get_tile_building_id(pos)
            if tbid is None:
                continue
            if ct.get_team(tbid) == team:
                continue

            # Ignore harvesters
            etype = ct.get_entity_type(tbid)
            if etype == EntityType.HARVESTER:
                continue

            pri = _PRIORITY_INDEX.get(etype)
            if pri is None:
                continue

            hp = ct.get_hp(tbid)
            candidates.append((pri, hp, pos))

        if not candidates:
            return False

        # Sort by priority index first, then lowest HP within same type
        candidates.sort(key=lambda t: (t[0], t[1]))

        for _, _, pos in candidates:
            if ct.can_fire(pos):
                ct.fire(pos)
                return True

        return False
