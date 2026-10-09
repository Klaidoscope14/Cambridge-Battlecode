from cambc import Controller, Position, EntityType
from debug.profiling import cputimer
from helpers.directions import CARDINAL
from map.map_manager import MapManager
from nav.pathing import Pathing
from nav.movement import move_road_if_empty
from nav.passability import passability_default
from states.builder_state import BuilderState

# Treated as "turret slots" for feeder detection. BARRIER is intentionally
# included: enemies frequently self-destruct their own barriers to replace
# them with real turrets, so feeders pointing at a barrier tile are worth
# cutting off preemptively.
TURRET_TYPES = [
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.GUNNER,
]

BELT_TARGET_TYPES = (
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
)


class DestroyAmmoSourceState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.enemy_turret_pos: Position | None = None
        self.ammo_source_pos: Position | None = None
        self.pathing: Pathing = brain.pathing

    def identify_ammo_feeder(self, ct: Controller):
        """Find a conveyor/splitter/bridge that directly feeds any visible
        enemy turret.

        Priority: ally feeder pointing at turret > ally feeder pointing at
        enemy belt > enemy feeder pointing at turret. Destroying an ally
        building is free (action range, dist_sq <= 2); firing an enemy
        building requires standing on the tile.

        Returns (feeder_pos, turret_pos) or (None, None).
        """
        mm: MapManager = self.brain.map_manager
        my_team = ct.get_team()
        my_pos = ct.get_position()
        vision_sq = ct.get_vision_radius_sq()
        my_id = ct.get_id()
        building_grid = mm.building_grid
        id_to_pos = mm.id_to_pos
        id_to_record = mm.id_to_record
        reachable = self.brain.pathing._reachable
        width = mm.width
        height = mm.height
        get_bot = mm.get_bot
        get_building = mm.get_building

        ally_feeder: Position | None = None
        ally_turret: Position | None = None
        enemy_feeder: Position | None = None
        enemy_turret: Position | None = None
        ally_belt_feeder: Position | None = None
        ally_belt_target: Position | None = None

        # --- per-turret: conveyor / splitter on cardinal neighbours ---
        for tur_pos in mm.nearby_enemy_turret_pos:
            bot_record = get_bot(tur_pos)
            if bot_record is not None and bot_record.team == my_team:
                continue

            for d in CARDINAL:
                adj_pos = tur_pos.add(d)
                ax = adj_pos.x
                ay = adj_pos.y
                if not (0 <= ax < width and 0 <= ay < height):
                    continue
                if my_pos.distance_squared(adj_pos) > vision_sq:
                    continue
                if (ax, ay) not in reachable:
                    continue
                rec = building_grid[ax][ay]
                if rec is None:
                    continue
                etype = rec.entity_type
                d_to_turret = d.opposite()

                feeds = False
                if etype == EntityType.CONVEYOR:
                    if rec.direction == d_to_turret:
                        feeds = True
                elif etype == EntityType.SPLITTER:
                    s_dir = rec.direction
                    if (d_to_turret == s_dir
                        or d_to_turret == s_dir.rotate_left().rotate_left()
                        or d_to_turret == s_dir.rotate_right().rotate_right()):
                        feeds = True

                if not feeds:
                    continue

                if rec.team == my_team:
                    if ally_feeder is None:
                        ally_feeder = adj_pos
                        ally_turret = tur_pos
                else:
                    if enemy_feeder is None:
                        bot = get_bot(adj_pos)
                        if bot is None or bot.id == my_id:
                            enemy_feeder = adj_pos
                            enemy_turret = tur_pos

        if ally_feeder is not None:
            return ally_feeder, ally_turret

        # --- ally bridges whose output tile holds an enemy turret
        for eid in mm.nearby_ally_bridge_ids:
            rec = id_to_record.get(eid)
            if rec is None:
                continue
            target = rec.output_target
            target_building = get_building(target)
            if target_building is None:
                continue
            if target_building.team == my_team:
                continue
            if target_building.entity_type not in TURRET_TYPES:
                continue
            pos = id_to_pos[eid]
            if (pos.x, pos.y) not in reachable:
                continue
            bot_record = get_bot(pos)
            if bot_record is not None and bot_record.team == my_team:
                continue
            if ally_feeder is None:
                ally_feeder = pos
                ally_turret = target

        if ally_feeder is not None:
            return ally_feeder, ally_turret

        # --- enemy bridges whose output tile holds an enemy turret
        for eid in mm.nearby_enemy_bridge_ids:
            rec = id_to_record.get(eid)
            if rec is None:
                continue
            target = rec.output_target
            target_building = get_building(target)
            if target_building is None:
                continue
            if target_building.team == my_team:
                continue
            if target_building.entity_type not in TURRET_TYPES:
                continue
            pos = id_to_pos[eid]
            if (pos.x, pos.y) not in reachable:
                continue
            bot_record = get_bot(pos)
            if bot_record is not None and bot_record.team == my_team:
                continue
            if enemy_feeder is None:
                bot = get_bot(pos)
                if bot is None or bot.id == my_id:
                    enemy_feeder = pos
                    enemy_turret = target

        # --- ally conveyor/splitter feeding an enemy conveyor/bridge
        # (Enemy splitters are not individually cached by MapManager, so
        # they're omitted from the belt-target list.)
        enemy_belt_positions: list[Position] = []
        for eid in mm.nearby_enemy_conveyor_ids:
            p = id_to_pos.get(eid)
            if p is not None:
                enemy_belt_positions.append(p)
        for eid in mm.nearby_enemy_bridge_ids:
            p = id_to_pos.get(eid)
            if p is not None:
                enemy_belt_positions.append(p)

        for belt_pos in enemy_belt_positions:
            bot_record = get_bot(belt_pos)
            if bot_record is not None and bot_record.team == my_team:
                continue

            for d in CARDINAL:
                adj_pos = belt_pos.add(d)
                ax = adj_pos.x
                ay = adj_pos.y
                if not (0 <= ax < width and 0 <= ay < height):
                    continue
                if my_pos.distance_squared(adj_pos) > vision_sq:
                    continue
                if (ax, ay) not in reachable:
                    continue
                rec = building_grid[ax][ay]
                if rec is None:
                    continue
                if rec.team != my_team:
                    continue
                etype = rec.entity_type
                d_to_belt = d.opposite()

                feeds = False
                if etype == EntityType.CONVEYOR:
                    if rec.direction == d_to_belt:
                        feeds = True
                elif etype == EntityType.SPLITTER:
                    s_dir = rec.direction
                    if (d_to_belt == s_dir
                        or d_to_belt == s_dir.rotate_left().rotate_left()
                        or d_to_belt == s_dir.rotate_right().rotate_right()):
                        feeds = True

                if not feeds:
                    continue

                if ally_belt_feeder is None:
                    ally_belt_feeder = adj_pos
                    ally_belt_target = belt_pos

        # --- ally bridges whose output tile holds an enemy belt
        for eid in mm.nearby_ally_bridge_ids:
            rec = id_to_record.get(eid)
            if rec is None:
                continue
            target = rec.output_target
            target_building = get_building(target)
            if target_building is None:
                continue
            if target_building.team == my_team:
                continue
            if target_building.entity_type not in BELT_TARGET_TYPES:
                continue
            pos = id_to_pos[eid]
            if (pos.x, pos.y) not in reachable:
                continue
            bot_record = get_bot(pos)
            if bot_record is not None and bot_record.team == my_team:
                continue

            if ally_belt_feeder is None:
                ally_belt_feeder = pos
                ally_belt_target = target

        if ally_belt_feeder is not None:
            return ally_belt_feeder, ally_belt_target
        return enemy_feeder, enemy_turret

    def execute(self, ct: Controller):
        print("ammo_source: ", self.ammo_source_pos)
        print("turret: ", self.enemy_turret_pos)
        my_pos: Position = ct.get_position()
        mm: MapManager = self.brain.map_manager
        source_building = mm.get_building(self.ammo_source_pos)
        is_ally = source_building is not None and source_building.team == ct.get_team()

        if is_ally:
            # Ally building: destroy requires action range (distance_squared <= 2)
            if my_pos.distance_squared(self.ammo_source_pos) <= 2:
                if ct.can_destroy(self.ammo_source_pos):
                    ct.destroy(self.ammo_source_pos)
                    # Destroy is free (no action cost), so immediately tile
                    # the freed square over with a road in the same turn.
                    if ct.can_build_road(self.ammo_source_pos):
                        ct.build_road(self.ammo_source_pos)
            else:
                self.pathing.path_to(
                    ct, mm, my_pos, self.ammo_source_pos,
                    move_road_if_empty, passability_default
                )
        else:
            # Enemy building: fire requires standing on the tile
            if my_pos == self.ammo_source_pos:
                if ct.can_fire(self.ammo_source_pos):
                    ct.fire(self.ammo_source_pos)
            else:
                self.pathing.path_to(
                    ct, mm, my_pos, self.ammo_source_pos,
                    move_road_if_empty, passability_default
                )

    @cputimer
    def determine(self, ct, state_manager):
        feeder, turret = self.identify_ammo_feeder(ct)
        if feeder is None:
            return False
        self.ammo_source_pos = feeder
        self.enemy_turret_pos = turret
        state_manager.current_state = BuilderState.DESTROY_AMMO_SOURCE
        return True
