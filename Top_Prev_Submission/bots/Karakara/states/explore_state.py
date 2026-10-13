import math
import random

from cambc import Position

from debug.profiling import cputimer
from map.map_manager import MapManager
from nav.common import save_path

# Toggle to draw a line from the bot to its current explore target each turn.
DEBUG_DRAW_EXPLORE_TARGET = False


# Half-angle (radians) of the wedge we sample inside on the first pick when
# we have a spawn-offset hint. Narrower = stricter initial bearing.
_SEED_HALF_ANGLE = math.pi / 4


class ExploreState:
    # Candidate directions to sample at a given R before shrinking.
    _DIR_TRIES = 12
    # Multiplicative shrink applied when every sampled direction fell off-map.
    _R_SHRINK = 0.7
    # Minimum R before we reset and accept any unseen tile as a fallback.
    _R_MIN = 2
    # Squared distance at which we treat the target as "reached" even if
    # pathing hasn't walked onto it — prevents getting pinned near a wall
    # or bot blocking the last tile.
    _REACHED_DIST_SQ = 8

    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        self.w = ct.get_map_width()
        self.h = ct.get_map_height()
        # Start R near the map diagonal so early targets are far-flung.
        self._initial_R: float = float(max(self.w, self.h))
        self.R: float = self._initial_R
        self.explore_loc: Position | None = None
        # Bearing bias (radians) used only for the very first pick, so the
        # explorer heads out along the offset between its spawn tile and
        # the core. Cleared after the first pick.
        self._seed_angle: float | None = self._compute_seed_angle()

    @cputimer
    def determine(self, ct, state_manager) -> bool:
        return False

    def execute(self, ct):
        mm = self.brain.map_manager
        target = self._get_explore_target(mm)
        if DEBUG_DRAW_EXPLORE_TARGET:
            ct.draw_indicator_line(ct.get_position(), target, 255, 180, 0)
            ct.draw_indicator_dot(target, 255, 180, 0)
        save_path(ct, mm, self.brain.pathing, target)

    def _get_explore_target(self, mm: MapManager) -> Position:
        # Expire on intrinsic signals so the target survives across state
        # swaps: target unset, already seen, or we're close enough that
        # pathing-stuck-near-the-goal should count as reached.
        my_pos = self.ct.get_position()
        if (
            self.explore_loc is None
            or mm.has_seen(self.explore_loc)
            or my_pos.distance_squared(self.explore_loc) <= self._REACHED_DIST_SQ
        ):
            self._pick_new_target(mm)
        if self.explore_loc is None:
            self.explore_loc = Position(
                random.randrange(self.w), random.randrange(self.h)
            )
        return self.explore_loc

    def _compute_seed_angle(self) -> float | None:
        ally_core = self.brain.map_manager.ally_core_pos
        spawn_pos = self.brain.spawn_location
        if ally_core is None or spawn_pos is None:
            return None
        dx = spawn_pos.x - ally_core.x
        dy = spawn_pos.y - ally_core.y
        if dx == 0 and dy == 0:
            return None
        return math.atan2(dy, dx)

    def _sample_angle(self) -> float:
        if self._seed_angle is None:
            return random.uniform(0.0, 2.0 * math.pi)
        lo = self._seed_angle - _SEED_HALF_ANGLE
        hi = self._seed_angle + _SEED_HALF_ANGLE
        return random.uniform(lo, hi)

    def _pick_new_target(self, mm: MapManager) -> None:
        my_pos = self.ct.get_position()
        while self.R >= self._R_MIN:
            for _ in range(self._DIR_TRIES):
                angle = self._sample_angle()
                dx = int(round(self.R * math.cos(angle)))
                dy = int(round(self.R * math.sin(angle)))
                cand = Position(my_pos.x + dx, my_pos.y + dy)
                if not (0 <= cand.x < self.w and 0 <= cand.y < self.h):
                    continue
                if mm.has_seen(cand):
                    continue
                self.explore_loc = cand
                self.R = self._initial_R
                self._seed_angle = None
                return
            # Every sampled direction was off-map or already seen — shrink.
            self.R *= self._R_SHRINK

        # R collapsed: fall back to any unseen tile on the map, then reset R.
        for _ in range(self._DIR_TRIES):
            cand = Position(
                random.randrange(self.w), random.randrange(self.h)
            )
            if mm.has_seen(cand):
                continue
            self.explore_loc = cand
            self.R = self._initial_R
            self._seed_angle = None
            return

        self.explore_loc = Position(
            random.randrange(self.w), random.randrange(self.h)
        )
        self.R = self._initial_R
        self._seed_angle = None
