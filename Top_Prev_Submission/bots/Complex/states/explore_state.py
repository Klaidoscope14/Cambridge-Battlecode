from cambc import GameConstants, Position, Controller
from debug.indicators import draw_move_direction
from map.map_manager import MapManager
from nav.common import no_build_path, save_path

import random

class ExploreState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.w = ct.get_map_width()
        self.h = ct.get_map_height()
        self.vision_radius_sq = GameConstants.BUILDER_BOT_VISION_RADIUS_SQ
        self.target_round: int = -100
        self.explore_loc: Position | None = None
        self.check_locs: list[Position] = []
        self.generate_locs()

    def determine(self, ct, state_manager) -> bool:
        return False

    def execute(self, ct):
        explorePos = self.get_explore_target(self.brain.map_manager)
        save_path(ct, self.brain.map_manager, self.brain.pathing, explorePos)

        # if self.brain.spawn_round == 5:
        #     no_build_path(ct, self.brain.map_manager, self.brain.pathing, explorePos)
        # else:
        #     save_path(ct, self.brain.map_manager, self.brain.pathing, explorePos)

    def get_explore_target(self, map_manager: MapManager) -> Position:
        current_round = self.ct.get_current_round()
        # Expire the target if it's stale or already seen
        if current_round - self.target_round > 40 or (
            self.explore_loc is not None
            and map_manager.has_seen(self.explore_loc)
        ):
            self.explore_loc = None

        if self.explore_loc is None:
            # rct.getID() % 2 >= 0 is always true for non-negative IDs, so
            # all bots use checker targets — preserving the original behaviour.
            self.get_checker_target(map_manager, 15)

        # Final safety net — should never happen, but guarantees non-None.
        if self.explore_loc is None:
            self.explore_loc = Position(
                random.randrange(self.w), random.randrange(self.h)
            )
            self.target_round = self.ct.get_current_round()

        return self.explore_loc

    def generate_locs(self) -> None:
        w, h = self.w, self.h
        self.check_locs = [
            Position(w // 2, h // 2),
            Position(2, 2),
            Position(w - 3, 0),
            Position(0, h - 3),
            Position(w - 3, h - 3),
        ]
        self.explore_loc = self.check_locs[self.ct.get_current_round() % 5]
        self.target_round = self.ct.get_current_round()

    def get_emergency_target(self, map_manager: MapManager, tries: int) -> None:
        max_x = self.ct.get_map_width()
        max_y = self.ct.get_map_height()
        my_pos = self.ct.get_position()
        while tries > 0:
            tries -= 1
            new_loc = Position(random.randrange(max_x), random.randrange(max_y))
            # Skip tiles we've already seen
            if map_manager.has_seen(new_loc):
                continue
            # Only update if new loc is farther away than current target
            if (
                self.explore_loc is not None
                and my_pos.distance_squared(self.explore_loc)
                < my_pos.distance_squared(new_loc)
            ):
                continue
            self.explore_loc = new_loc
            self.target_round = self.ct.get_current_round()
        if self.explore_loc is None:
            self.explore_loc = Position(
                random.randrange(max_x), random.randrange(max_y)
            )
            self.target_round = self.ct.get_current_round()

    def get_checker_target(self, map_manager: MapManager, tries: int) -> None:
        my_pos = self.ct.get_position()
        found = False
        for _ in range(tries):
            new_loc = random.choice(self.check_locs)
            if map_manager.has_seen(new_loc):
                continue
            if (
                self.explore_loc is not None
                and my_pos.distance_squared(self.explore_loc)
                < my_pos.distance_squared(new_loc)
            ):
                continue
            self.explore_loc = new_loc
            self.target_round = self.ct.get_current_round()
            found = True
            break
        if not found:
            # All checker locations seen — fall back with a fresh budget.
            self.get_emergency_target(map_manager, tries)
