from cambc import Controller, EntityType, Position
from map.map_manager import MapManager

TURRET_TYPES = {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH, EntityType.LAUNCHER}


class Sentinel:
    def __init__(self, ct) -> None:
        self.map_manager = MapManager(ct)

    def run(self, ct) -> None:
        self.shoot(ct)

    def shoot(self, ct) -> bool:
        team = ct.get_team()

        turrets = []
        cores = []
        bots = []       # (hp, pos)
        bridges = []
        conveyors = []
        splitters = []
        other = []

        for pos in ct.get_nearby_tiles():
            if not ct.can_fire(pos):
                continue

            bbid = ct.get_tile_builder_bot_id(pos)
            friendly_bot_present = bbid is not None and ct.get_team(bbid) == team
            if friendly_bot_present:
                continue
            if bbid is not None and ct.get_team(bbid) != team:
                bots.append((ct.get_hp(bbid), pos))

            tbid = ct.get_tile_building_id(pos)
            if tbid is not None and ct.get_team(tbid) != team:
                etype = ct.get_entity_type(tbid)
                if etype in TURRET_TYPES:
                    turrets.append(pos)
                elif etype == EntityType.CORE:
                    cores.append(pos)
                elif etype == EntityType.HARVESTER:
                    pass  # Skip harvesters — not worth shooting
                elif etype == EntityType.BRIDGE:
                    bridges.append(pos)
                elif etype == EntityType.SPLITTER:
                    splitters.append(pos)
                elif etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                    conveyors.append(pos)

        # Lowest HP bot first
        bots.sort(key=lambda t: t[0])
        bot_positions = [pos for _, pos in bots]

        for bucket in (turrets, bridges, conveyors, splitters, bot_positions, cores, other):
            for pos in bucket:
                if ct.can_fire(pos):
                    ct.fire(pos)
                    return True

        return False
