from cambc import EntityType, Environment, Position
from debug.profiling import cputimer
from helpers.directions import CARDINAL, DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager
from turret.safe_path import path_to_build_spot
from states.builder_state import BuilderState

# ── Tuning constants ────────────────────────────────────────────────

ACTION_RADIUS_SQ = 2
MAX_ATTEMPT_ROUNDS = 2000
LAUNCH_RANGE_SQ = 26
MIN_LAUNCH_DIST_SQ = 16
MAX_VISIBLE_LAUNCHERS = 2
BUILD_COOLDOWN_ROUNDS = 75
EARLY_ROUNDS = 200
DESTROYABLE = {EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER}

# Buildings that count as "ally road" for the top-priority bucket.
# Only ROAD is destroyable, so only ROAD can be a bucket-0 hit (we destroy
# the road then build the launcher on top).
_ON_ROAD_TYPES = {EntityType.ROAD}

# Buildings that count as "ally road/conveyor network" for the adjacency check.
# A tile cardinally next to any of these is bucket-1 (one step off the path).
_ROAD_NETWORK_TYPES = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
}

_ALLY_TURRET_TYPES = {EntityType.GUNNER, EntityType.SENTINEL}
_ENEMY_CONVEYOR_TYPES = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE
}

# Enemy tiles we're willing to destroy to build a launcher on top of
# (used by the emergency trigger when we're standing on one).
_ENEMY_DESTROYABLE_UNDERFOOT = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}

_LAUNCH_OFFSETS = [
    (dx, dy) for dx in range(-5, 6) for dy in range(-5, 6)
    if MIN_LAUNCH_DIST_SQ <= dx*dx + dy*dy <= LAUNCH_RANGE_SQ
]


class BuildLauncherState:
    def __init__(self, ct, brain) -> None:
        self.brain = brain
        self.target_pos: Position | None = None
        self.target_harvester_pos: Position | None = None
        self.target_enemy_launcher_pos: Position | None = None
        self.attempt_start: int | None = None
        self.wait_one_turn: bool | None = None
        # Round we last placed a launcher; used to throttle spend.
        self.last_build_round: int | None = None

    # ── Buildability ────────────────────────────────────────────────

    def _is_buildable(self, ct, mm: MapManager, pos: Position) -> bool:
        bot = mm.get_bot(pos)
        if bot is not None and bot.id != ct.get_id():
            return False
        building = mm.get_building(pos)
        if building is None:
            tile = mm.get_tile(pos)
            return tile is not None and tile == Environment.EMPTY
        if building.team == ct.get_team() and building.entity_type in DESTROYABLE:
            return True
        return False

    # ── Priority bucket helpers ─────────────────────────────────────

    def _is_on_ally_road(self, ct, mm: MapManager, tile: Position) -> bool:
        b = mm.get_building(tile)
        return (
            b is not None
            and b.team == ct.get_team()
            and b.entity_type in _ON_ROAD_TYPES
        )

    def _is_adjacent_to_ally_road(self, ct, mm: MapManager, tile: Position) -> bool:
        team = ct.get_team()
        for d in CARDINAL:
            n = tile.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            b = mm.get_building(n)
            if b is not None and b.team == team and b.entity_type in _ROAD_NETWORK_TYPES:
                return True
        return False

    def _harvester_feeds_enemy_conveyor(self, ct, mm: MapManager, harvester_pos: Position) -> bool:
        """True if the harvester has at least one enemy conveyor cardinally adjacent."""
        team = ct.get_team()
        for d in CARDINAL:
            n = harvester_pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            b = mm.get_building(n)
            if b is None:
                continue
            if b.team == team:
                continue
            if b.entity_type in _ENEMY_CONVEYOR_TYPES:
                return True
        return False

    def _has_ally_turret_adjacent(self, ct, mm: MapManager, harvester_pos: Position) -> bool:
        """True if any ally gunner/sentinel is already cardinally adjacent to the harvester."""
        team = ct.get_team()
        for d in CARDINAL:
            n = harvester_pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            b = mm.get_building(n)
            if b is None:
                continue
            if b.team != team:
                continue
            if b.entity_type in _ALLY_TURRET_TYPES:
                return True
        return False

    # ── Coverage check ──────────────────────────────────────────────

    def _cheb(self, a: Position, b: Position) -> int:
        return max(abs(a.x - b.x), abs(a.y - b.y))

    def _already_covered(self, mm: MapManager, harvester_pos: Position) -> bool:
        """True if a known friendly launcher sits within launch range of this harvester."""
        for lpos in mm.seen_launcher_positions:
            if lpos.distance_squared(harvester_pos) <= LAUNCH_RANGE_SQ:
                return True
        return False

    def _too_close_to_existing_launcher(self, mm: MapManager, tile: Position) -> bool:
        """True if any known friendly launcher is within LAUNCH_RANGE_SQ of this tile."""
        for lpos in mm.seen_launcher_positions:
            if lpos.distance_squared(tile) <= LAUNCH_RANGE_SQ:
                return True
        return False

    def _has_adjacent_launcher(self, mm: MapManager, tile: Position) -> bool:
        """True if any known launcher sits in one of the 8 tiles around `tile`.
        Enforces the no-two-adjacent-launchers invariant."""
        for lpos in mm.seen_launcher_positions:
            if lpos.distance_squared(tile) <= 2 and lpos != tile:
                return True
        return False

    def _has_ally_launcher_adjacent(self, mm: MapManager, tile: Position) -> bool:
        """True if any known ally launcher sits in one of the 8 tiles around `tile`."""
        for lpos in mm.seen_launcher_positions:
            if lpos.distance_squared(tile) <= 2 and lpos != tile:
                return True
        return False

    # ── Emergency trigger ───────────────────────────────────────────

    def _find_emergency_launch_spot(self, ct, mm: MapManager, my_pos: Position):
        """If enemy harvesters outnumber ours and we're sitting on an enemy
        conveyor/bridge, return a buildable tile in one of the 8 neighbours.
        Returns a Position or None."""
        if len(mm.nearby_enemy_harvester_ids) <= len(mm.nearby_ally_harvester_ids):
            return None
        building = mm.get_building(my_pos)
        if building is None or building.team == ct.get_team():
            return None
        if building.entity_type not in _ENEMY_DESTROYABLE_UNDERFOOT:
            return None
        for d in DIRECTIONS:
            n = my_pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            if self._is_buildable(ct, mm, n) and not self._has_adjacent_launcher(mm, n):
                return n
        return None

    # ── Spot search ─────────────────────────────────────────────────

    def _find_launcher_spot(self, ct, mm: MapManager, my_pos: Position):
        """Priority-list search. Lower index = higher priority:
          0 — tile is on an ally road (max traffic)
          1 — tile is cardinally adjacent to ally road/conveyor network
          2 — any other buildable tile within launch range
        Tie-break within a bucket: nearest to us.
        Returns (spot, harvester_pos) or None.
        """
        enemy_core = self.brain.get_enemy_core_pos()
        if enemy_core is None:
            return None
        ecx, ecy = enemy_core.x, enemy_core.y
    
        # Precompute forbidden tiles (within LAUNCH_RANGE_SQ of any known launcher).
        forbidden_tiles: set[tuple[int, int]] = set()
        for lpos in mm.seen_launcher_positions:
            lx, ly = lpos.x, lpos.y
            for dx in range(-5, 6):
                for dy in range(-5, 6):
                    if dx * dx + dy * dy <= LAUNCH_RANGE_SQ:
                        forbidden_tiles.add((lx + dx, ly + dy))
    
        mpx, mpy = my_pos.x, my_pos.y
        map_w, map_h = mm.width, mm.height
    
        best_on_road: tuple[Position, Position, str] | None = None
        best_adj_road: tuple[Position, Position, str] | None = None
        best_other: tuple[Position, Position, str] | None = None
        best_on_road_dist = float("inf")
        best_adj_road_dist = float("inf")
        best_other_dist = float("inf")
    
        # Build target list: enemy harvesters (existing) + enemy launchers
        # that have no ally launcher adjacent to them (new).
        # Each entry: (pos, kind) where kind is "harvester" or "launcher".
        targets: list[tuple[Position, str]] = []
        for eid in mm.nearby_enemy_harvester_ids:
            hpos = ct.get_position(eid)
            if self._already_covered(mm, hpos):
                continue
            if not self._harvester_feeds_enemy_conveyor(ct, mm, hpos):
                continue
            if self._has_ally_turret_adjacent(ct, mm, hpos):
                continue
            targets.append((hpos, "harvester"))
        for eid in mm.nearby_enemy_launcher_ids:
            elpos = ct.get_position(eid)
            if self._has_ally_launcher_adjacent(mm, elpos):
                continue
            targets.append((elpos, "launcher"))

        for harvester_pos, target_kind in targets:
    
            hx, hy = harvester_pos.x, harvester_pos.y
            # Chebyshev from me to the harvester — used as the "backwards" gate.
            my_to_harv_cheb = max(abs(mpx - hx), abs(mpy - hy))
    
            for dx, dy in _LAUNCH_OFFSETS:
                tx_pos = hx + dx
                ty_pos = hy + dy
    
                # Bounds (cheap)
                if tx_pos < 0 or tx_pos >= map_w or ty_pos < 0 or ty_pos >= map_h:
                    continue
    
                # "Not backwards" check (cheap arithmetic, rejects a lot)
                if max(abs(mpx - tx_pos), abs(mpy - ty_pos)) >= my_to_harv_cheb:
                    continue
    
                # Forbidden by existing launcher coverage (O(1) set lookup)
                if (tx_pos, ty_pos) in forbidden_tiles:
                    continue

                # Invariant: no two launchers may be adjacent (8-neighbour).
                if self._has_adjacent_launcher(mm, Position(tx_pos, ty_pos)):
                    continue
    
                # Cone check — tile must launch the builder roughly toward enemy core.
                # tx, ty = harvester - tile = -dx, -dy (reuse loop vars).
                fx = ecx - tx_pos
                fy = ecy - ty_pos
                ndx = -dx
                ndy = -dy
                dot = fx * ndx + fy * ndy
                if dot <= 0 or 2 * dot * dot < (fx * fx + fy * fy) * (ndx * ndx + ndy * ndy):
                    continue
    
                # Buildability is the most expensive check — do it last.
                tile = Position(tx_pos, ty_pos)
                if not self._is_buildable(ct, mm, tile):
                    continue
    
                d_me = (mpx - tx_pos) * (mpx - tx_pos) + (mpy - ty_pos) * (mpy - ty_pos)
    
                if self._is_on_ally_road(ct, mm, tile):
                    if d_me < best_on_road_dist:
                        best_on_road_dist = d_me
                        best_on_road = (tile, harvester_pos, target_kind)
                elif self._is_adjacent_to_ally_road(ct, mm, tile):
                    if d_me < best_adj_road_dist:
                        best_adj_road_dist = d_me
                        best_adj_road = (tile, harvester_pos, target_kind)
                else:
                    if d_me < best_other_dist:
                        best_other_dist = d_me
                        best_other = (tile, harvester_pos, target_kind)
    
        return best_on_road or best_adj_road or best_other

    # ── Validity ────────────────────────────────────────────────────

    def _is_target_valid(self, ct, mm: MapManager) -> bool:
        if self.target_pos is None:
            return False
        if not self._is_buildable(ct, mm, self.target_pos):
            return False
        # Reject if an existing launcher now covers this spot (clump prevention)
        if self._too_close_to_existing_launcher(mm, self.target_pos):
            return False
        # Reject if a launcher has since been built adjacent to our target
        if self._has_adjacent_launcher(mm, self.target_pos):
            return False
        # Reject if the specific harvester we were targeting is now covered,
        # or no longer exists / no longer feeds a conveyor / is now ally-turret'd
        if self.target_harvester_pos is not None:
            if self._already_covered(mm, self.target_harvester_pos):
                return False
            if not self._harvester_feeds_enemy_conveyor(ct, mm, self.target_harvester_pos):
                return False
            if self._has_ally_turret_adjacent(ct, mm, self.target_harvester_pos):
                return False
        # Target harvester must still be within launch range of the spot
        if self.target_harvester_pos is not None:
            if self.target_pos.distance_squared(self.target_harvester_pos) > LAUNCH_RANGE_SQ:
                return False
        # Enemy-launcher target: revalidate ally-launcher-adjacency and range.
        if self.target_enemy_launcher_pos is not None:
            if self._has_ally_launcher_adjacent(mm, self.target_enemy_launcher_pos):
                return False
            if self.target_pos.distance_squared(self.target_enemy_launcher_pos) > LAUNCH_RANGE_SQ:
                return False
        return True

    # ── State interface ─────────────────────────────────────────────

    @cputimer
    def determine(self, ct, state_manager) -> bool:
        if self.wait_one_turn:
            state_manager.current_state = BuilderState.BUILD_LAUNCHER
            return True
        mm = self.brain.map_manager

        # Nothing to launch toward
        if not mm.nearby_enemy_harvester_ids:
            self._clear()
            return False

        # Cooldown: don't spam launcher builds back-to-back
        if (
            self.last_build_round is not None
            and ct.get_current_round() - self.last_build_round < BUILD_COOLDOWN_ROUNDS
        ):
            self._clear()
            return False

        # Cap: if we already see enough launchers in vision, don't enter state
        my_pos = ct.get_position()
        vision_sq = ct.get_vision_radius_sq()
        visible_launchers = sum(
            1 for lpos in mm.seen_launcher_positions
            if my_pos.distance_squared(lpos) <= vision_sq
        )
        if visible_launchers >= MAX_VISIBLE_LAUNCHERS:
            self._clear()
            return False

        # Can't afford it
        cost = ct.get_launcher_cost()[0] * 2.5
        if ct.get_global_resources()[0] < cost or ct.get_current_round() < EARLY_ROUNDS:
            self._clear()
            return False

        # Emergency: enemy harvesters outnumber allies and we're parked on an
        # enemy conveyor/bridge — build on an adjacent buildable tile.
        emergency_spot = self._find_emergency_launch_spot(ct, mm, my_pos)
        if emergency_spot is not None:
            self.target_pos = emergency_spot
            self.target_harvester_pos = None
            self.target_enemy_launcher_pos = None
            self.attempt_start = ct.get_current_round()
            state_manager.current_state = BuilderState.BUILD_LAUNCHER
            return True

        # Keep current target if still valid
        if self.target_pos is not None and self._is_target_valid(ct, mm):
            state_manager.current_state = BuilderState.BUILD_LAUNCHER
            return True

        result = self._find_launcher_spot(ct, mm, my_pos)
        if result is not None:
            tile, paired_pos, kind = result
            self.target_pos = tile
            if kind == "harvester":
                self.target_harvester_pos = paired_pos
                self.target_enemy_launcher_pos = None
            else:
                self.target_harvester_pos = None
                self.target_enemy_launcher_pos = paired_pos
            self.attempt_start = ct.get_current_round()
            state_manager.current_state = BuilderState.BUILD_LAUNCHER
            return True

        self._clear()
        return False

    def execute(self, ct):
        if self.wait_one_turn:
            self.wait_one_turn = False
            return
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        if self.target_pos is None:
            return

        # Debug: show which harvester this launcher spot is paired with
        if self.target_harvester_pos is not None:
            ct.draw_indicator_line(self.target_pos, self.target_harvester_pos, 0, 255, 0)
        elif self.target_enemy_launcher_pos is not None:
            ct.draw_indicator_line(self.target_pos, self.target_enemy_launcher_pos, 255, 0, 0)

        # Timeout
        if self.attempt_start is not None and ct.get_current_round() - self.attempt_start > MAX_ATTEMPT_ROUNDS:
            self._clear()
            return

        # Standing on build tile — destroy blocker, step off, build
        if my_pos == self.target_pos:
            if ct.get_action_cooldown() > 0 or ct.get_move_cooldown() > 0:
                return
            building = mm.get_building(self.target_pos)
            if building is not None and building.team == ct.get_team() and building.entity_type in DESTROYABLE:
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            for d in DIRECTIONS:
                if ct.can_move(d):
                    ct.move(d)
                    break
            if ct.can_build_launcher(self.target_pos):
                ct.build_launcher(self.target_pos)
                self.wait_one_turn = True
                self.last_build_round = ct.get_current_round()
                self._clear()
            return

        # Adjacent — clear blocker and build
        if my_pos.distance_squared(self.target_pos) <= ACTION_RADIUS_SQ:
            building = mm.get_building(self.target_pos)
            if building is not None and building.team == ct.get_team() and building.entity_type in DESTROYABLE:
                if ct.can_destroy(self.target_pos):
                    ct.destroy(self.target_pos)
            if ct.can_build_launcher(self.target_pos):
                ct.build_launcher(self.target_pos)
                self.wait_one_turn = True
                self.last_build_round = ct.get_current_round()
                self._clear()
                return

        # Walk toward target
        path_to_build_spot(ct, mm, self.brain.pathing, self.target_pos)

    def _clear(self):
        self.target_pos = None
        self.target_harvester_pos = None
        self.target_enemy_launcher_pos = None
        self.attempt_start = None
