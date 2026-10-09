from cambc import EntityType, Environment, GameConstants, Position, Direction, ResourceType
from debug.profiling import cputimer
from helpers.directions import DIRECTIONS
from map.map_manager import MapManager
from turret.buildable import is_buildable_spot, is_destroyable_blocker
from turret.safe_path import path_to_build_spot
from turret.step_off import handle_on_build_tile
from states.builder_state import BuilderState

ACTION_RADIUS_SQ = 2
MAX_ATTEMPT_ROUNDS = 15
SENTINEL_TRIGGER_RADIUS_SQ = 20
GUNNER_TRIGGER_RADIUS_SQ = 13

ENABLE_GUNNER_STEAL = True

# Placement kinds this state can produce. Only SENTINEL is wired up for now;
# GUNNER and BARRIER are stubbed so the shape is clear for later.
PLACEMENT_SENTINEL = "sentinel"
PLACEMENT_GUNNER = "gunner"
PLACEMENT_BARRIER = "barrier"

FACING_PRIORITY = [
    "nearby_enemy_turret_pos",
    "nearby_enemy_harvester_ids",
    "nearby_enemy_conveyor_ids",
    "nearby_enemy_launcher_ids",
    "nearby_enemy_builder_bot_ids",
]

TRIGGER_PRIORITY = [
    "nearby_enemy_turret_pos",
    "nearby_enemy_launcher_ids",
    "nearby_enemy_conveyor_ids",
    "nearby_enemy_bridge_ids",
    "nearby_enemy_harvester_ids"
]


class StealOpenSourceState:
    def __init__(self, ct, brain) -> None:
        self.brain = brain
        self.target_pos: Position | None = None
        self.target_dir: Direction | None = None
        self.target_kind: str | None = None  # PLACEMENT_SENTINEL / GUNNER / BARRIER
        self.attempt_start: int | None = None
        self.source_eid: int | None = None
        # Persisted alongside source_eid so we can re-fetch the record from
        # the building grid next turn (records are rebuilt fresh each round).
        self.source_pos: Position | None = None

    # ── shared helpers ──────────────────────────────────────────────

    def _is_buildable(self, ct, mm: MapManager, pos: Position) -> bool:
        return is_buildable_spot(ct, mm, pos)

    def _is_reachable(self, pos: Position) -> bool:
        reachable = self.brain.reachable
        if not reachable:
            return True  # set not yet seeded — don't reject
        return (pos.x, pos.y) in reachable

    def _has_enemy_nearby( self, ct, mm: MapManager, build_pos: Position, exclude_pos: Position | None = None, radius_sq: int | None = None) -> bool:
        if radius_sq == None:
            return True
        for attr in TRIGGER_PRIORITY:
            items = getattr(mm, attr, [])
            for item in items:
                # Items may be Positions (turret_pos lists) or EntityRecords
                # (everything else — pull rec.position).
                trigger_pos = item if isinstance(item, Position) else item.position
                if trigger_pos is None:
                    continue
                if exclude_pos is not None and trigger_pos == exclude_pos:
                    continue
                if build_pos.distance_squared(trigger_pos) <= radius_sq:
                    return True
        return False

    def _pick_facing( self, ct, mm: MapManager, pos: Position, away_from: Position | None = None,) -> Direction:
        toward_away = pos.direction_to(away_from) if away_from else None

        for attr in FACING_PRIORITY:
            items = getattr(mm, attr, [])
            if not items:
                continue
            first = items[0]
            target = first if isinstance(first, Position) else first.position
            facing = pos.direction_to(target)
            if facing != toward_away:
                return facing
            return facing.rotate_left()

        if mm.spotted_enemy_core_pos is not None:
            facing = pos.direction_to(mm.spotted_enemy_core_pos)
            if facing != toward_away:
                return facing
            return facing.rotate_left()

        if away_from is not None:
            return away_from.direction_to(pos)

        return Direction.NORTH

    # ── spot finder ─────────────────────────────────────────────────

    def _find_steal_spot(self, ct, mm: MapManager, my_pos: Position, radius_sq: int, allow_empty_conveyor: bool = True):
        """Find the closest stealable spot across all enemy source types.

        ``allow_empty_conveyor=False`` skips conveyors the storage tracker has
        confirmed empty — used by sentinel/gunner placements, which are wasted
        on a belt that isn't actually moving ore. Barriers still target them.
        """
        bridge_spot = self._find_bridge_steal_spot(ct, mm, my_pos, radius_sq)
        conveyor_spot = self._find_conveyor_steal_spot(ct, mm, my_pos, radius_sq, allow_empty_conveyor)
    
        if bridge_spot is None:
            return conveyor_spot
        if conveyor_spot is None:
            return bridge_spot
    
        # Both non-None — pick the closer target.
        bridge_dist = my_pos.distance_squared(bridge_spot[0])
        conveyor_dist = my_pos.distance_squared(conveyor_spot[0])
        return bridge_spot if bridge_dist <= conveyor_dist else conveyor_spot

    def _find_bridge_steal_spot(self, ct, mm: MapManager, my_pos: Position, radius_sq: int):
        best = None
        best_dist = float("inf")
        vision_sq = ct.get_vision_radius_sq()
    
        for rec in mm.nearby_enemy_bridge_ids:
            eid = rec.id
            bridge_pos = rec.position
            target = rec.output_target
    
            if my_pos.distance_squared(target) > vision_sq:
                continue
    
            # Skip tiles that already have one of our placements on them
            existing = mm.get_building(target)
            if existing is not None and existing.entity_type in (
                EntityType.SENTINEL,
                EntityType.GUNNER,
                EntityType.BARRIER,
            ):
                continue
    
            if not self._is_buildable(ct, mm, target):
                continue
            # Skip targets the bot has no confirmed walkable route to.
            if not self._is_reachable(target):
                continue
            if not self._has_enemy_nearby(ct, mm, target, exclude_pos=bridge_pos, radius_sq=radius_sq):
                continue
    
            facing = self._pick_facing(ct, mm, target, away_from=bridge_pos)
            dist = my_pos.distance_squared(target)
            if dist < best_dist:
                best_dist = dist
                best = (target, facing, eid, bridge_pos)

        return best

    def _find_conveyor_steal_spot(self, ct, mm: MapManager, my_pos: Position, radius_sq: int, allow_empty_conveyor: bool = True):
        best = None
        best_dist = float("inf")
        vision_sq = ct.get_vision_radius_sq()

        for rec in mm.nearby_enemy_open_conveyor_ids:
            eid = rec.id
            # Sentinel/gunner placements skip belts confirmed empty —
            # not worth a turret on inactive ore. Barriers still apply.
            if not allow_empty_conveyor and self.brain.storage_tracker.is_empty(eid):
                continue
            # Sentinel/gunner placements also skip belts carrying raw axionite —
            # we don't want to turret-block enemy axionite (we'd rather they keep
            # routing it where we can hit the refined output instead).
            if not allow_empty_conveyor and ResourceType.RAW_AXIONITE in self.brain.storage_tracker.get_recent_resources(eid):
                continue

            conv_pos = rec.position
            target = conv_pos.add(rec.direction)
    
            if my_pos.distance_squared(target) > vision_sq:
                continue
    
            # Skip tiles that already have one of our placements on them
            existing = mm.get_building(target)
            if existing is not None and existing.entity_type in (
                EntityType.SENTINEL,
                EntityType.GUNNER,
                EntityType.BARRIER,
            ):
                continue
    
            if not self._is_buildable(ct, mm, target):
                continue
            # Skip targets the bot has no confirmed walkable route to.
            if not self._is_reachable(target):
                continue
            if not self._has_enemy_nearby(ct, mm, target, exclude_pos=conv_pos, radius_sq=radius_sq):
                continue
    
            facing = self._pick_facing(ct, mm, target, away_from=conv_pos)
            dist = my_pos.distance_squared(target)
            if dist < best_dist:
                best_dist = dist
                best = (target, facing, eid, conv_pos)

        return best


    def _is_target_valid(self, ct, mm: MapManager) -> bool:
        if self.target_pos is None:
            return False
        if not self._is_reachable(self.target_pos):
            return False

        # If one of our placements (or anyone's) is already there, abandon.
        building = mm.get_building(self.target_pos)
        if building is not None and building.entity_type in (
            EntityType.SENTINEL,
            EntityType.GUNNER,
            EntityType.BARRIER,
        ):
            return False
    
        if not self._is_buildable(ct, mm, self.target_pos):
            return False
    
        # Revalidate the source we committed to. Look up the record via the
        # remembered position; if the eid no longer matches, the original
        # source was destroyed (and possibly replaced).
        if self.source_eid is None:
            return True

        if self.source_pos is None:
            return False
        rec = mm.get_building(self.source_pos)
        if rec is None or rec.id != self.source_eid:
            return False  # source destroyed (or replaced by a new entity)

        etype = rec.entity_type
        if etype == EntityType.BRIDGE:
            # Bridge output_target must still be our target tile.
            if rec.output_target != self.target_pos:
                return False
        elif etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            if self.source_pos.add(rec.direction) != self.target_pos:
                return False
            # Sentinel/gunner committed to a belt that's since gone empty —
            # bail so determine() can pick a barrier instead.
            if self.target_kind in (PLACEMENT_SENTINEL, PLACEMENT_GUNNER):
                if self.brain.storage_tracker.is_empty(self.source_eid):
                    return False
                if ResourceType.RAW_AXIONITE in self.brain.storage_tracker.get_recent_resources(self.source_eid):
                    return False
        else:
            return False

        return True

    # ── determine: three-way dispatch ────────

    @cputimer
    def determine(self, ct, state_manager):
        print("calc this")
        mm = self.brain.map_manager

        if ct.get_current_round() < 50:
            return False

        # Don't activate unless an enemy builder bot is nearby or we can see the enemy core.
        if not mm.nearby_enemy_builder_bot_ids and not mm.nearby_enemy_core_pos:
            return False

        # Keep current target if still valid.
        if self.target_pos is not None and self._is_target_valid(ct, mm):
            state_manager.current_state = BuilderState.STEAL_OPEN_SOURCE
            return True

        return (
            self._determine_sentinel(ct, state_manager)
            or self._determine_gunner(ct, state_manager)
            or self._determine_barrier(ct, state_manager)
        )

    def _determine_sentinel(self, ct, state_manager) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        cost = ct.get_sentinel_cost()[0] + ct.get_road_cost()[0]
        if ct.get_global_resources()[0] < cost:
            return False

        result = self._find_steal_spot(ct, mm, my_pos, radius_sq=SENTINEL_TRIGGER_RADIUS_SQ, allow_empty_conveyor=False)
        if result is None:
            return False

        self.target_pos, self.target_dir, self.source_eid, self.source_pos = result
        self.target_kind = PLACEMENT_SENTINEL
        self.attempt_start = ct.get_current_round()
        state_manager.current_state = BuilderState.STEAL_OPEN_SOURCE
        return True

    def _determine_gunner(self, ct, state_manager) -> bool:
        if not ENABLE_GUNNER_STEAL:
            return False

        mm = self.brain.map_manager
        my_pos = ct.get_position()

        cost = ct.get_gunner_cost()[0] + ct.get_road_cost()[0]
        if ct.get_global_resources()[0] < cost:
            return False

        result = self._find_steal_spot(ct, mm, my_pos, radius_sq=GUNNER_TRIGGER_RADIUS_SQ, allow_empty_conveyor=False)
        if result is None:
            return False

        self.target_pos, self.target_dir, self.source_eid, self.source_pos = result
        self.target_kind = PLACEMENT_GUNNER
        self.attempt_start = ct.get_current_round()
        state_manager.current_state = BuilderState.STEAL_OPEN_SOURCE
        return True

    def _determine_barrier(self, ct, state_manager) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()
    
        cost = ct.get_barrier_cost()[0] + ct.get_road_cost()[0]
        if ct.get_global_resources()[0] < cost:
            return False
    
        result = self._find_steal_spot(ct, mm, my_pos, radius_sq=None)
        if result is None:
            return False
    
        self.target_pos, _facing, self.source_eid, self.source_pos = result
        self.target_dir = None  # barriers have no facing
        self.target_kind = PLACEMENT_BARRIER
        self.attempt_start = ct.get_current_round()
        state_manager.current_state = BuilderState.STEAL_OPEN_SOURCE
        return True

    # ── execute ─────────────────────────────────────────────────────

    def execute(self, ct):
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        if self.target_pos is None:
            return

        if (
            self.attempt_start is not None
            and ct.get_current_round() - self.attempt_start > MAX_ATTEMPT_ROUNDS
        ):
            self._clear()
            return

        # Debug: show where we're headed and what we're placing
        if self.target_kind == PLACEMENT_SENTINEL:
            ct.draw_indicator_line(my_pos, self.target_pos, 0, 255, 255)  # cyan
        elif self.target_kind == PLACEMENT_GUNNER:
            ct.draw_indicator_line(my_pos, self.target_pos, 255, 0, 255)  # magenta
        elif self.target_kind == PLACEMENT_BARRIER:
            ct.draw_indicator_line(my_pos, self.target_pos, 255, 165, 0)  # orange


        if self.target_kind == PLACEMENT_SENTINEL:
            self._execute_sentinel(ct, mm, my_pos)
        elif self.target_kind == PLACEMENT_GUNNER:
            self._execute_gunner(ct, mm, my_pos)
        elif self.target_kind == PLACEMENT_BARRIER:
            self._execute_barrier(ct, mm, my_pos)

    def _execute_sentinel(self, ct, mm: MapManager, my_pos: Position):
        # Standing on build tile — destroy, step off, build.
        if my_pos == self.target_pos:
            target_dir = self.target_dir
            built = handle_on_build_tile(
                ct, mm, self.target_pos,
                lambda p: ct.can_build_sentinel(p, target_dir),
                lambda p: ct.build_sentinel(p, target_dir),
            )
            if built:
                self._clear()
            return

        # Adjacent — clear ally blocker and build.
        if my_pos.distance_squared(self.target_pos) <= ACTION_RADIUS_SQ:
            building = mm.get_building(self.target_pos)
            if (
                building is not None
                and building.team == ct.get_team()
                and is_destroyable_blocker(mm, self.target_pos, building)
            ):
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            if ct.can_build_sentinel(self.target_pos, self.target_dir):
                ct.build_sentinel(self.target_pos, self.target_dir)
                self._clear()
                return

        path_to_build_spot(ct, mm, self.brain.pathing, self.target_pos)

    def _execute_gunner(self, ct, mm: MapManager, my_pos: Position):
        # Standing on build tile — destroy, step off, build.
        if my_pos == self.target_pos:
            target_dir = self.target_dir
            built = handle_on_build_tile(
                ct, mm, self.target_pos,
                lambda p: ct.can_build_gunner(p, target_dir),
                lambda p: ct.build_gunner(p, target_dir),
            )
            if built:
                self._clear()
            return

        # Adjacent — clear ally blocker and build.
        if my_pos.distance_squared(self.target_pos) <= ACTION_RADIUS_SQ:
            building = mm.get_building(self.target_pos)
            if (
                building is not None
                and building.team == ct.get_team()
                and is_destroyable_blocker(mm, self.target_pos, building)
            ):
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            if ct.can_build_gunner(self.target_pos, self.target_dir):
                ct.build_gunner(self.target_pos, self.target_dir)
                self._clear()
                return

        path_to_build_spot(ct, mm, self.brain.pathing, self.target_pos)

    def _execute_barrier(self, ct, mm: MapManager, my_pos: Position):
        # Standing on build tile — destroy, step off, build.
        if my_pos == self.target_pos:
            built = handle_on_build_tile(
                ct, mm, self.target_pos,
                lambda p: ct.can_build_barrier(p),
                lambda p: ct.build_barrier(p),
            )
            if built:
                self._clear()
            return
    
        # Adjacent — clear ally blocker and build.
        if my_pos.distance_squared(self.target_pos) <= ACTION_RADIUS_SQ:
            building = mm.get_building(self.target_pos)
            if (
                building is not None
                and building.team == ct.get_team()
                and is_destroyable_blocker(mm, self.target_pos, building)
            ):
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            if ct.can_build_barrier(self.target_pos):
                ct.build_barrier(self.target_pos)
                self._clear()
                return
    
        path_to_build_spot(ct, mm, self.brain.pathing, self.target_pos)

    # ── utility ─────────────────────────────────────────────────────

    def _clear(self):
        self.target_pos = None
        self.target_dir = None
        self.target_kind = None
        self.attempt_start = None
        self.source_eid = None
        self.source_pos = None
