"""Trail state: follow enemy conveyor/bridge trails to guide rusher bots
toward enemy harvesters.

Lower priority than every specialized action state — its job is to get the
bot into a useful area, where states like BUILD_HARVESTER, SABOTAGE, or
the turret builds take over. Higher priority than RUSH (the default), so
once we have ever seen an enemy conveyor, we stop guessing at the core
and start following real trails.

Behavior:
- Track every enemy conveyor/bridge position seen across turns.
- Mark a trail tile visited once we've passed within sq-dist 4 of it.
- Target the closest unvisited known trail tile.
- When all known trail is visited, fall back to the enemy core — the bot
  re-enters the network and picks up fresh branches on the next pass.
"""

from cambc import Position, Controller
from debug.profiling import cputimer
from nav.common import common_path
from states.builder_state import BuilderState

# Passing within this sq distance of a trail tile counts as visiting it.
VISIT_THRESHOLD_SQ = 4

# Once the full trail is visited, we only reset `visited_trail` once the bot
# has moved beyond this sq distance from every visited tile. Prevents
# thrashing where clearing immediately re-targets the tile we just marked.
RESET_CLEARANCE_SQ = 25


class TrailState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.seen_trail: set[tuple[int, int]] = set()
        self.visited_trail: set[tuple[int, int]] = set()
        self.target: Position | None = None
        self._enemy_core_center: Position | None = None
        self._last_symmetry_guess: str | None = None

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        self._ingest_visible_trail()
        self._mark_visited(ct.get_position())

        if not self.seen_trail:
            return False

        state_manager.current_state = BuilderState.TRAIL
        return True

    def execute(self, ct: Controller) -> None:
        my_pos = ct.get_position()
        self._ingest_visible_trail()
        self._mark_visited(my_pos)

        if (
            self.seen_trail
            and not (self.seen_trail - self.visited_trail)
            and self._far_from_visited(my_pos)
        ):
            self.visited_trail.clear()

        target = self._pick_target(my_pos)
        if target is None:
            return
        self.target = target
        common_path(ct, self.brain.map_manager, self.brain.pathing, target)

    def _far_from_visited(self, my_pos: Position) -> bool:
        if not self.visited_trail:
            return True
        mx = my_pos.x
        my = my_pos.y
        for key in self.visited_trail:
            dx = key[0] - mx
            dy = key[1] - my
            if dx * dx + dy * dy <= RESET_CLEARANCE_SQ:
                return False
        return True

    def _ingest_visible_trail(self) -> None:
        mm = self.brain.map_manager
        seen = self.seen_trail
        for rec in mm.nearby_enemy_conveyor_ids:
            pos = rec.position
            if pos is not None:
                seen.add((pos.x, pos.y))
        for rec in mm.nearby_enemy_bridge_ids:
            pos = rec.position
            if pos is not None:
                seen.add((pos.x, pos.y))

    def _mark_visited(self, my_pos: Position) -> None:
        if not self.seen_trail:
            return
        mx = my_pos.x
        my = my_pos.y
        visited = self.visited_trail
        for key in self.seen_trail:
            if key in visited:
                continue
            dx = key[0] - mx
            dy = key[1] - my
            if dx * dx + dy * dy <= VISIT_THRESHOLD_SQ:
                visited.add(key)

    def _pick_target(self, my_pos: Position) -> Position | None:
        unvisited = self.seen_trail - self.visited_trail

        if self.target is not None:
            key = (self.target.x, self.target.y)
            if key in unvisited:
                return self.target
            self.target = None

        if unvisited:
            mx = my_pos.x
            my = my_pos.y
            best = None
            best_dist = float("inf")
            for key in unvisited:
                dx = key[0] - mx
                dy = key[1] - my
                d = dx * dx + dy * dy
                if d < best_dist:
                    best_dist = d
                    best = key
            if best is not None:
                return Position(best[0], best[1])

        return self._enemy_core_pos()

    def _enemy_core_pos(self) -> Position | None:
        sm = self.brain.symmetry_manager
        guess = sm.guess_symmetry()
        if guess is None:
            return None
        if guess == self._last_symmetry_guess and self._enemy_core_center is not None:
            return self._enemy_core_center

        ally_core = getattr(self.brain, "ally_core_pos", None)
        if ally_core is None:
            ally_core = self.brain.map_manager.ally_core_pos
        if ally_core is None:
            return None

        reflected = sm.reflect(ally_core, guess)
        if reflected is not None:
            self._enemy_core_center = reflected
            self._last_symmetry_guess = guess
        return reflected
