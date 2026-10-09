from cambc import Controller, Position, EntityType
from roles.builder.helpers import in_bounds
from helpers.directions import CARDINAL, DIRECTIONS
from helpers.geometry import on_map
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
    EntityType.BARRIER,
]


class DestroyAmmoSourceState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.enemy_turret_pos: Position | None = None
        self.ammo_source_pos: Position | None = None
        self.pathing: Pathing = brain.pathing

    def identify_ammo_feeder(self, ct: Controller):
        """Find a conveyor/splitter/bridge that directly feeds any visible
        enemy turret (or barrier slot).

        For every visible enemy turret:
          * check the 4 cardinal neighbours — a conveyor whose direction
            points at the turret, or a splitter one of whose three output
            directions points at the turret, is a direct feeder.
        Then, for every visible bridge:
          * if the bridge's output tile holds an enemy turret, the bridge
            is a direct feeder (its "source" end is what we destroy).

        Ally feeders take priority: destroying an ally building is free
        and works from action range (dist_sq <= 2), whereas firing an
        enemy building requires the bot to stand on the tile.

        Returns (feeder_pos, turret_pos) or (None, None) if nothing found.
        """
        mm: MapManager = self.brain.map_manager
        my_team = ct.get_team()

        ally_feeder: Position | None = None
        ally_turret: Position | None = None
        enemy_feeder: Position | None = None
        enemy_turret: Position | None = None

        # --- collect visible enemy turret positions --------------------
        enemy_turret_positions: list[Position] = []
        for eid in mm.nearby_entity_ids:
            if ct.get_team(eid) == my_team:
                continue
            if ct.get_entity_type(eid) not in TURRET_TYPES:
                continue
            enemy_turret_positions.append(ct.get_position(eid))

        # --- per-turret: conveyor / splitter on cardinal neighbours ---
        my_pos = ct.get_position()
        vision_sq = ct.get_vision_radius_sq()
        for tur_pos in enemy_turret_positions:
            positions_to_check = [tur_pos] + [tur_pos.add(d) for d in DIRECTIONS]
            ally_present = False
            for check_pos in positions_to_check:
                if not in_bounds(ct, check_pos):
                    continue
                if my_pos.distance_squared(check_pos) > ct.get_vision_radius_sq():
                    continue
                bot_record = mm.bot_grid[check_pos.x][check_pos.y]
                if bot_record is None:
                    continue
                if bot_record.team == my_team and bot_record.id > ct.get_id():
                    ally_present = True
                    break
            if ally_present:
                continue

            for d in CARDINAL:
                adj_pos = tur_pos.add(d)
                if not on_map(adj_pos, mm.width, mm.height):
                    continue
                if my_pos.distance_squared(adj_pos) > vision_sq:
                    continue
                if (adj_pos.x, adj_pos.y) not in self.brain.pathing._reachable:
                    continue
                adj_id = ct.get_tile_building_id(adj_pos)
                if adj_id is None:
                    continue
                etype = ct.get_entity_type(adj_id)

                # d points from the turret out to adj_pos; the direction
                # FROM adj_pos back TO the turret is d.opposite().
                d_to_turret = d.opposite()

                feeds = False
                if etype == EntityType.CONVEYOR:
                    if ct.get_direction(adj_id) == d_to_turret:
                        feeds = True
                elif etype == EntityType.SPLITTER:
                    s_dir = ct.get_direction(adj_id)
                    # A splitter outputs in three directions: forward and
                    # both 90° perpendiculars (rotate_left twice / rotate_
                    # right twice, since each rotate_* is 45°).
                    outputs = (
                        s_dir,
                        s_dir.rotate_left().rotate_left(),
                        s_dir.rotate_right().rotate_right(),
                    )
                    if d_to_turret in outputs:
                        feeds = True

                if not feeds:
                    continue

                is_ally = ct.get_team(adj_id) == my_team
                if is_ally:
                    if ally_feeder is None:
                        ally_feeder = adj_pos
                        ally_turret = tur_pos
                else:
                    if enemy_feeder is None:
                        bot = mm.get_bot(adj_pos)
                        if bot is None or bot.id == ct.get_id():
                            enemy_feeder = adj_pos
                            enemy_turret = tur_pos

        # --- bridges: any bridge whose output tile holds an enemy turret
        for eid in mm.nearby_ally_bridge_ids + mm.nearby_enemy_bridge_ids:
            if ct.get_entity_type(eid) != EntityType.BRIDGE:
                continue
            target = ct.get_bridge_target(eid)
            target_building = mm.get_building(target)
            if target_building is None:
                continue
            if target_building.team == my_team:
                continue
            if target_building.entity_type not in TURRET_TYPES:
                continue
            pos = ct.get_position(eid)
            if (pos.x, pos.y) not in self.brain.pathing._reachable:
                continue

            positions_to_check = [pos] + [pos.add(d) for d in DIRECTIONS]
            ally_present = False
            for check_pos in positions_to_check:
                if not in_bounds(ct, check_pos):
                    continue
                if my_pos.distance_squared(check_pos) > ct.get_vision_radius_sq():
                    continue
                bot_record = mm.bot_grid[check_pos.x][check_pos.y]
                if bot_record is None:
                    continue
                if bot_record.team == my_team and bot_record.id > ct.get_id():
                    ally_present = True
                    break
            if ally_present:
                continue

            bridge_pos = ct.get_position(eid)
            is_ally = ct.get_team(eid) == my_team
            if is_ally:
                if ally_feeder is None:
                    ally_feeder = bridge_pos
                    ally_turret = target
            else:
                if enemy_feeder is None:
                    bot = mm.get_bot(bridge_pos)
                    if bot is None or bot.id == ct.get_id():
                        enemy_feeder = bridge_pos
                        enemy_turret = target

        if ally_feeder is not None:
            return ally_feeder, ally_turret
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
    
    def determine(self, ct, state_manager):
        feeder, turret = self.identify_ammo_feeder(ct)
        if feeder is None:
            return False
        self.ammo_source_pos = feeder
        self.enemy_turret_pos = turret
        state_manager.current_state = BuilderState.DESTROY_AMMO_SOURCE
        return True
        
        

