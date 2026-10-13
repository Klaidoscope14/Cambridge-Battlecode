from cambc import Environment, Position, Direction
from debug.profiling import cputimer
from map.map_manager import MapManager
from turret.buildable import is_buildable_spot, is_destroyable_blocker
from turret.safe_path import path_to_build_spot
from turret.step_off import handle_on_build_tile
from states.builder_state import BuilderState

DEBUG = False

ACTION_RADIUS_SQ = 2
MAX_ATTEMPT_ROUNDS = 2000
MAX_SENTINELS_PER_HARVESTER = 1
SKIP_AXIONITE_HARVESTERS = True
TRIGGER_RADIUS_SQ = 32
"""A trigger entity must be within this squared distance of the build
spot for a sentinel to be placed there."""

PRIORITY = [
    "nearby_enemy_turret_pos",
    "nearby_enemy_launcher_ids",
    "nearby_enemy_conveyor_ids",
    "nearby_enemy_bridge_ids",
    "nearby_enemy_harvester_ids",
]

class BuildSentinelState:
    def __init__(self, ct, brain) -> None:
        self.brain = brain
        self.target_pos: Position | None = None
        self.target_harvester_pos: Position | None = None
        self.target_trigger_pos: Position | None = None
        self.attempt_start: int | None = None

    def _is_buildable(self, ct, mm: MapManager, pos: Position) -> bool:
        return is_buildable_spot(ct, mm, pos)

    def _in_enemy_gunner_danger(self, mm: MapManager, pos: Position) -> bool:
        return pos in mm.gunner_danger_positions

    def _facing_for(self, build_pos: Position, trigger_pos: Position) -> Direction:
        return build_pos.direction_to(trigger_pos)

    def _find_trigger(self, mm: MapManager, build_pos: Position, source_pos: Position) -> Position | None:
        """Return the highest-priority enemy within TRIGGER_RADIUS_SQ of
        build_pos whose facing from build_pos doesn't fire through source_pos.
        Returns None if no such enemy exists."""
        for attr in PRIORITY:
            items = getattr(mm, attr, [])
            for item in items:
                # Items are Positions for *_turret_pos lists, EntityRecords for *_ids lists.
                trigger_pos = item if isinstance(item, Position) else item.position
                if trigger_pos is None:
                    continue
                if trigger_pos == source_pos:
                    if DEBUG: print(f"[BuildSentinel] find_trigger SKIP: build=({build_pos.x},{build_pos.y}) attr={attr} trigger=({trigger_pos.x},{trigger_pos.y}) is source")
                    continue
                d = build_pos.distance_squared(trigger_pos)
                if d > TRIGGER_RADIUS_SQ:
                    continue
                facing = build_pos.direction_to(trigger_pos)
                if build_pos.add(facing) == source_pos:
                    if DEBUG: print(f"[BuildSentinel] find_trigger SKIP: build=({build_pos.x},{build_pos.y}) attr={attr} trigger=({trigger_pos.x},{trigger_pos.y}) facing={facing} fires through source ({source_pos.x},{source_pos.y})")
                    continue
                if DEBUG: print(f"[BuildSentinel] find_trigger HIT: build=({build_pos.x},{build_pos.y}) attr={attr} trigger=({trigger_pos.x},{trigger_pos.y}) dist²={d} facing={facing}")
                return trigger_pos
        if DEBUG: print(f"[BuildSentinel] find_trigger MISS: build=({build_pos.x},{build_pos.y}) — no valid trigger")
        return None

    def _trigger_pos_in_lists(self, mm: MapManager, trigger_pos: Position) -> bool:
        for attr in PRIORITY:
            items = getattr(mm, attr, [])
            for item in items:
                p = item if isinstance(item, Position) else item.position
                if p is not None and p == trigger_pos:
                    return True
        return False

    def _trigger_still_valid(self, ct, mm: MapManager, my_pos: Position, trigger_pos: Position) -> bool:
        """If the trigger is in our vision this turn, require it to still
        appear in the priority lists. If it's outside vision, assume it's
        still there (we have no ground truth)."""
        if my_pos.distance_squared(trigger_pos) <= ct.get_vision_radius_sq():
            return self._trigger_pos_in_lists(mm, trigger_pos)
        return True

    def _find_sentinel_spot(self, ct, mm: MapManager, my_pos: Position):
        best = None
        best_dist = float("inf")

        if DEBUG: print(f"[BuildSentinel] find_spot: my_pos=({my_pos.x},{my_pos.y}) ally_harv_slots={len(mm.nearby_harvester_card_pos)} enemy_harv_slots={len(mm.nearby_harvester_enemy_card_pos)}")

        # Find spot next to ally harvester and point at threats
        for harvester_pos, pos in mm.nearby_harvester_card_pos:
            key = (harvester_pos.x, harvester_pos.y)
            if DEBUG: print(f"[BuildSentinel] find_spot ALLY: harv=({harvester_pos.x},{harvester_pos.y}) adj=({pos.x},{pos.y})")
            if SKIP_AXIONITE_HARVESTERS and mm.get_tile(harvester_pos) == Environment.ORE_AXIONITE:
                if DEBUG: print("[BuildSentinel] find_spot ALLY: skip (axionite)")
                continue
            cnt = mm.harvester_sentinel_count.get(key, 0)
            if cnt >= MAX_SENTINELS_PER_HARVESTER:
                if DEBUG: print(f"[BuildSentinel] find_spot ALLY: skip (saturated, count={cnt}≥{MAX_SENTINELS_PER_HARVESTER})")
                continue
            if not self._is_buildable(ct, mm, pos):
                if DEBUG: print("[BuildSentinel] find_spot ALLY: skip (not buildable)")
                continue
            if self._in_enemy_gunner_danger(mm, pos):
                if DEBUG: print(f"[BuildSentinel] find_spot ALLY: skip (in enemy gunner danger) adj=({pos.x},{pos.y})")
                continue
            trigger = self._find_trigger(mm, pos, harvester_pos)
            if trigger is None:
                if DEBUG: print("[BuildSentinel] find_spot ALLY: skip (no valid trigger)")
                continue
            dist = my_pos.distance_squared(pos)
            if DEBUG: print(f"[BuildSentinel] find_spot ALLY: candidate adj=({pos.x},{pos.y}) trigger=({trigger.x},{trigger.y}) dist²={dist} best={best_dist}")
            if dist < best_dist:
                best_dist = dist
                best = (pos, harvester_pos, trigger)
                if DEBUG: print(f"[BuildSentinel] find_spot ALLY: NEW BEST adj=({pos.x},{pos.y}) trigger=({trigger.x},{trigger.y})")

        # Place next to enemy harvesters to disrupt their resource collection
        for harvester_pos, adj in mm.nearby_harvester_enemy_card_pos:
            key = (harvester_pos.x, harvester_pos.y)
            if DEBUG: print(f"[BuildSentinel] find_spot ENEMY: harv=({harvester_pos.x},{harvester_pos.y}) adj=({adj.x},{adj.y})")
            if SKIP_AXIONITE_HARVESTERS and mm.get_tile(harvester_pos) == Environment.ORE_AXIONITE:
                if DEBUG: print("[BuildSentinel] find_spot ENEMY: skip (axionite)")
                continue
            cnt = mm.harvester_sentinel_count.get(key, 0)
            if cnt >= MAX_SENTINELS_PER_HARVESTER:
                if DEBUG: print(f"[BuildSentinel] find_spot ENEMY: skip (saturated, count={cnt}≥{MAX_SENTINELS_PER_HARVESTER})")
                continue
            if not self._is_buildable(ct, mm, adj):
                if DEBUG: print("[BuildSentinel] find_spot ENEMY: skip (not buildable)")
                continue
            if self._in_enemy_gunner_danger(mm, adj):
                if DEBUG: print(f"[BuildSentinel] find_spot ENEMY: skip (in enemy gunner danger) adj=({adj.x},{adj.y})")
                continue
            trigger = self._find_trigger(mm, adj, harvester_pos)
            if trigger is None:
                if DEBUG: print("[BuildSentinel] find_spot ENEMY: skip (no valid trigger)")
                continue
            dist = my_pos.distance_squared(adj)
            if DEBUG: print(f"[BuildSentinel] find_spot ENEMY: candidate adj=({adj.x},{adj.y}) trigger=({trigger.x},{trigger.y}) dist²={dist} best={best_dist}")
            if dist < best_dist:
                best_dist = dist
                best = (adj, harvester_pos, trigger)
                if DEBUG: print(f"[BuildSentinel] find_spot ENEMY: NEW BEST adj=({adj.x},{adj.y}) trigger=({trigger.x},{trigger.y})")

        if DEBUG: print(f"[BuildSentinel] find_spot RESULT: {best}")
        return best

    def _is_target_valid(self, ct, mm: MapManager, my_pos: Position):
        if self.target_pos is None:
            if DEBUG: print("[BuildSentinel] is_target_valid: no target_pos → invalid")
            return False
        if not self._is_buildable(ct, mm, self.target_pos):
            if DEBUG: print(f"[BuildSentinel] is_target_valid: ({self.target_pos.x},{self.target_pos.y}) no longer buildable → invalid")
            return False
        if self._in_enemy_gunner_danger(mm, self.target_pos):
            if DEBUG: print(f"[BuildSentinel] is_target_valid: ({self.target_pos.x},{self.target_pos.y}) in enemy gunner danger → invalid")
            return False
        if self.target_trigger_pos is None:
            if DEBUG: print("[BuildSentinel] is_target_valid: no trigger_pos → invalid")
            return False
        if not self._trigger_still_valid(ct, mm, my_pos, self.target_trigger_pos):
            if DEBUG: print(f"[BuildSentinel] is_target_valid: trigger ({self.target_trigger_pos.x},{self.target_trigger_pos.y}) gone from vision → invalid")
            return False
        return True

    @cputimer
    def determine(self, ct, state_manager):
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        if DEBUG: print(f"[BuildSentinel] determine: my_pos=({my_pos.x},{my_pos.y}) target={self.target_pos} trigger={self.target_trigger_pos}")

        # Unit cap: max 50 units on the map
        units = ct.get_unit_count()
        if units >= 50:
            if DEBUG: print(f"[BuildSentinel] determine: unit cap ({units}≥50), clearing")
            self._clear()
            return False

        cost = ct.get_sentinel_cost()[0] + ct.get_harvester_cost()[0]
        resources = ct.get_global_resources()[0]
        if resources < cost:
            if DEBUG: print(f"[BuildSentinel] determine: insufficient resources (have {resources}, need {cost}), clearing")
            self._clear()
            return False

        if self.target_pos is not None and self._is_target_valid(ct, mm, my_pos):
            if DEBUG: print(f"[BuildSentinel] determine: keeping existing target ({self.target_pos.x},{self.target_pos.y}) trigger=({self.target_trigger_pos.x},{self.target_trigger_pos.y})")
            state_manager.current_state = BuilderState.BUILD_SENTINEL
            return True

        result = self._find_sentinel_spot(ct, mm, my_pos)
        if result is not None:
            self.target_pos, self.target_harvester_pos, self.target_trigger_pos = result
            self.attempt_start = ct.get_current_round()
            if DEBUG: print(f"[BuildSentinel] determine: NEW target=({self.target_pos.x},{self.target_pos.y}) trigger=({self.target_trigger_pos.x},{self.target_trigger_pos.y}) harv=({self.target_harvester_pos.x},{self.target_harvester_pos.y}) attempt_start={self.attempt_start}")
            state_manager.current_state = BuilderState.BUILD_SENTINEL
            return True

        if DEBUG: print("[BuildSentinel] determine: no valid sentinel spot found, clearing")
        self._clear()
        return False

    def execute(self, ct):
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        if DEBUG: print(f"[BuildSentinel] execute: my_pos=({my_pos.x},{my_pos.y}) target={self.target_pos} trigger={self.target_trigger_pos} attempt_start={self.attempt_start}")

        if self.target_pos is None or self.target_trigger_pos is None:
            if DEBUG: print("[BuildSentinel] execute: no target_pos/trigger, returning")
            return

        cost = ct.get_sentinel_cost()[0]
        resources = ct.get_global_resources()[0]
        if resources < cost:
            if DEBUG: print(f"[BuildSentinel] execute: insufficient resources (have {resources}, need {cost}), pathing toward target instead")
            path_to_build_spot(ct, mm, self.brain.pathing, self.target_pos)
            return

        if self.attempt_start is not None and ct.get_current_round() - self.attempt_start > MAX_ATTEMPT_ROUNDS:
            if DEBUG: print(f"[BuildSentinel] execute: timeout (round={ct.get_current_round()} start={self.attempt_start} max={MAX_ATTEMPT_ROUNDS}), clearing")
            self._clear()
            return

        target_dir = self._facing_for(self.target_pos, self.target_trigger_pos)
        if DEBUG: print(f"[BuildSentinel] execute: facing={target_dir} (from trigger ({self.target_trigger_pos.x},{self.target_trigger_pos.y}))")

        can_act = ct.get_action_cooldown() == 0

        # Standing on build tile — destroy, step off, build
        if my_pos == self.target_pos:
            if not can_act:
                if DEBUG: print(f"[BuildSentinel] execute: on build tile but action cooldown blocking, waiting")
                return
            if DEBUG: print(f"[BuildSentinel] execute: standing on build tile ({self.target_pos.x},{self.target_pos.y}), stepping off")
            built = handle_on_build_tile(
                ct, mm, self.target_pos,
                lambda p: ct.can_build_sentinel(p, target_dir),
                lambda p: ct.build_sentinel(p, target_dir),
            )
            if built:
                if DEBUG: print(f"[BuildSentinel] execute: built sentinel at ({self.target_pos.x},{self.target_pos.y}) facing {target_dir} via step-off, clearing")
                self._clear()
            else:
                if DEBUG: print("[BuildSentinel] execute: step-off did not build this turn")
            return

        # Adjacent — clear blocker and build
        dist = my_pos.distance_squared(self.target_pos)
        if dist <= ACTION_RADIUS_SQ:
            if DEBUG: print(f"[BuildSentinel] execute: adjacent to target (dist²={dist})")
            if can_act:
                building = mm.get_building(self.target_pos)
                if building is not None and building.team == ct.get_team() and is_destroyable_blocker(mm, self.target_pos, building):
                    if DEBUG: print(f"[BuildSentinel] execute: blocker present (type={building.entity_type}) at target, attempting destroy")
                    if ct.can_destroy(self.target_pos):
                        ct.destroy(self.target_pos)
                        if DEBUG: print(f"[BuildSentinel] execute: destroyed blocker at ({self.target_pos.x},{self.target_pos.y})")
                    else:
                        if DEBUG: print("[BuildSentinel] execute: can_destroy=False, skipping")
                can = ct.can_build_sentinel(self.target_pos, target_dir)
                if can:
                    ct.build_sentinel(self.target_pos, target_dir)
                    if DEBUG: print(f"[BuildSentinel] execute: built sentinel at ({self.target_pos.x},{self.target_pos.y}) facing {target_dir}, clearing")
                    self._clear()
                    return
                else:
                    if DEBUG: print(f"[BuildSentinel] execute: can_build_sentinel=False at ({self.target_pos.x},{self.target_pos.y}) facing {target_dir}")
            else:
                if DEBUG: print(f"[BuildSentinel] execute: adjacent but action cooldown blocking, deferring destroy/build")

        if DEBUG: print(f"[BuildSentinel] execute: pathing toward ({self.target_pos.x},{self.target_pos.y}) (dist²={dist})")
        path_to_build_spot(ct, mm, self.brain.pathing, self.target_pos)

    def _clear(self):
        self.target_pos = None
        self.target_harvester_pos = None
        self.target_trigger_pos = None
        self.attempt_start = None
