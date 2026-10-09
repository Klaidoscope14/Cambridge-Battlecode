"""BuildHarvesterState – find, route to, and build a harvester on ore.

Handles the full lifecycle in two internal phases:

Phase ROUTE:
  1. Find closest valid ore to ally core (including symmetry-predicted).
  2. Path toward it.
  3. Step onto ore (road underneath) to reserve it.
  4. Wait until affordable, then transition to BUILD.

Phase BUILD:
  5. Step off the ore to an adjacent walkable tile.
  6. Destroy the road left on the ore.
  7. Build the harvester.

Ore reservation is signalled by the bot sitting on the ore tile.
Other bots see the occupied tile and skip it automatically — no
markers required.
"""

from cambc import Controller, Direction, EntityType, Environment, GameConstants, Position

from helpers.directions import CARDINAL, DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager
from nav.common import common_path
from nav.movement import move_road_if_empty
from debug.profiling import cputimer
from states.builder_state import BuilderState

# ── Constants ───────────────────────────────────────────────────────

ACTION_RADIUS_SQ = 2

ORE_TYPES = {
    Environment.ORE_TITANIUM,
    Environment.ORE_AXIONITE,
}

TURRET_TYPES = {
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
}

# Ally buildings the harvester is NOT allowed to destroy/replace.
# Ore tiles with one of these on top are skipped during candidate search.
UNREPLACEABLE_ALLY_TYPES = {
    EntityType.BRIDGE,
}

ENEMY_INFRA_TYPES = {
    EntityType.ROAD,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
}

TOO_MANY_ENEMY_TILES = 100

COOLDOWN_DURATION = 100
ROUTE_TIMEOUT = 40
RESOURCE_BUFFER_FRACTION = 0.5
BRIDGE_COST_RESERVE = 1

# Ally turret on an ore tile may be destroyed to free the ore, but only when
# no enemy builder has been seen for SAFE_ROUNDS and the turret has stood at
# its current position for at least MIN_TURRET_AGE rounds.
SAFE_ROUNDS = 30
MIN_TURRET_AGE = 30

# ── Phases ──────────────────────────────────────────────────────────

PHASE_ROUTE = "route"
PHASE_SABOTAGE = "sabotage"
PHASE_BUILD = "build"


# ── Pure helpers (module-level) ─────────────────────────────────────


def in_action_range(a: Position, b: Position) -> bool:
    return a.distance_squared(b) <= ACTION_RADIUS_SQ


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def ore_is_available(pos: Position, map_manager: MapManager) -> bool:
    tile = map_manager.get_tile(pos)
    if tile is None or tile not in ORE_TYPES:
        return False
    return map_manager.get_building(pos) is None


def is_on_position(a: Position, b: Position) -> bool:
    return a.x == b.x and a.y == b.y


def in_theory_can_build_harvester(ct, pos: Position):
    if not in_action_range(ct.get_position(), pos):
        return False
    if ct.get_global_resources()[0] < ct.get_harvester_cost()[0]:
        return False
    return ct.get_action_cooldown() == 0


# ── State ───────────────────────────────────────────────────────────


class BuildHarvesterState:
    """Route to ore → reserve it → build harvester.  Single cooldown dict."""

    allowed_ore = {Environment.ORE_TITANIUM, Environment.ORE_AXIONITE}

    def __init__(self, ct: Controller, brain) -> None:
        self.ct = ct
        self.brain = brain
        self.target: Position | None = None
        self._target_set_round: int = -1
        self._phase: str = PHASE_ROUTE
        self._core_cache_round: int = -1
        self._core_cache_result = None
        self.cooldowns: dict[Position, int] = {}
        self._turret_first_seen: dict[Position, int] = {}

    # ── Turret-on-ore safety ────────────────────────────────────────

    def _is_safe(self, current_round: int) -> bool:
        """No enemy builder seen recently — safe to dismantle ally turrets."""
        last_seen = self.brain.map_manager.last_enemy_builder_seen_round
        return last_seen is None or current_round - last_seen > SAFE_ROUNDS

    def _turret_old_enough(self, pos: Position, current_round: int) -> bool:
        """Stamp first-seen round for a turret position; True once aged enough."""
        if pos not in self._turret_first_seen:
            self._turret_first_seen[pos] = current_round
        return current_round - self._turret_first_seen[pos] >= MIN_TURRET_AGE

    # ── Ore filtering ───────────────────────────────────────────────

    def _is_allowed_ore(self, env: Environment) -> bool:
        return env in self.allowed_ore

    def _is_valid_ore(
        self,
        ct: Controller,
        mm: MapManager,
        pos: Position,
        current_round: int,
        enemy_count: int = 0,
        my_pos: Position | None = None,
    ) -> bool:
        """Full validation for ore tiles we can see."""
        if pos in self.cooldowns:
            return False
        if enemy_count > TOO_MANY_ENEMY_TILES:
            return False

        tile = mm.get_tile(pos)
        if tile is None or not self._is_allowed_ore(tile):
            return False
        
        if tile == Environment.ORE_AXIONITE and (ct.get_global_resources()[0] < ct.get_harvester_cost()[0] * 2 or ct.get_current_round() < 700):
            return False

        building = mm.get_building(pos)
        if building is not None:
            if building.entity_type == EntityType.HARVESTER:
                return False
            if building.team != ct.get_team() and building.entity_type != EntityType.MARKER:
                return False
            if building.team == ct.get_team():
                if building.entity_type in UNREPLACEABLE_ALLY_TYPES:
                    return False
                if building.entity_type in TURRET_TYPES:
                    if not self._is_safe(current_round):
                        return False
                    if not self._turret_old_enough(pos, current_round):
                        return False
                    # Fall through to remaining checks below

        # Reject ore with enemy turrets on cardinal neighbours
        team = ct.get_team()
        for d in CARDINAL:
            adj = pos.add(d)
            if not on_map(adj, mm.width, mm.height):
                continue
            adj_building = mm.get_building(adj)
            if (
                adj_building is not None
                and adj_building.team != team
                and adj_building.entity_type in TURRET_TYPES
            ):
                return False

        # Another bot sitting on this ore means it is reserved.
        # Skip the check when *we* are the bot on the tile.
        bot_on_ore = mm.get_bot(pos)
        if bot_on_ore is not None:
            if my_pos is None or not is_on_position(my_pos, pos):
                return False

        if not self.brain._is_closer_to_ally_core(pos):
            return False

        return True

    def _is_valid_predicted_ore(
        self,
        ct: Controller,
        mm: MapManager,
        pos: Position,
        current_round: int,
        enemy_count: int = 0,
        my_pos: Position | None = None,
    ) -> bool:
        """Lighter validation for symmetry-predicted ore we haven't seen yet.

        If the tile IS visible, falls back to full validation.
        If unseen, only checks cooldown, enemy count, and ally-side.
        """
        tile = mm.get_tile(pos)

        # Visible — use full validation
        if tile is not None:
            return self._is_valid_ore(ct, mm, pos, current_round, enemy_count, my_pos)

        # Unseen — lightweight checks only
        if pos in self.cooldowns:
            return False
        if enemy_count > TOO_MANY_ENEMY_TILES:
            return False
        if not self.brain._is_closer_to_ally_core(pos):
            return False

        return True

    # ── Closest ore lookup ──────────────────────────────────────────

    def _find_closest_to_core(
        self,
        ct: Controller,
        mm: MapManager,
        current_round: int,
        enemy_count: int = 0,
        my_pos: Position | None = None,
    ) -> Position | None:
        """Return the valid ore closest (Manhattan) to ally core.

        Prioritises ore on tiles already in the pathing reachable set
        (known-walkable).  Falls back to all ore if none are reachable.

        Considers both directly observed ore and symmetry-predicted ore
        (reflected positions of known ore when symmetry is cracked).
        """
        ally_core = mm.ally_core_pos
        reachable = self.brain.pathing._reachable
        team = ct.get_team()

        # Tiers: 0 = reachable & clear, 1 = ally turret on ore, 2 = unreachable
        best_pos: Position | None = None
        best_dist = float("inf")
        best_self_dist = float("inf")
        best_tier = 3  # worse than any valid tier

        def _tier_for(pos: Position, has_turret: bool) -> int:
            if has_turret:
                return 1
            if (pos.x, pos.y) in reachable:
                return 0
            return 2

        def _consider(pos, dist, self_dist, has_turret):
            nonlocal best_pos, best_dist, best_self_dist, best_tier
            tier = _tier_for(pos, has_turret)
            if tier > best_tier:
                return
            if tier < best_tier:
                best_tier = tier
                best_dist = dist
                best_self_dist = self_dist
                best_pos = pos
                return
            if dist < best_dist or (dist == best_dist and self_dist < best_self_dist):
                best_dist = dist
                best_self_dist = self_dist
                best_pos = pos

        # ── Known ore (full validation) ─────────────────────────────
        for pos in mm.known_ore_positions:
            if not self._is_valid_ore(ct, mm, pos, current_round, enemy_count, my_pos):
                continue
            building = mm.get_building(pos)
            has_turret = (
                building is not None
                and building.team == team
                and building.entity_type in TURRET_TYPES
            )
            dist = manhattan(pos, ally_core)
            self_dist = manhattan(pos, my_pos) if my_pos is not None else 0
            _consider(pos, dist, self_dist, has_turret)

        # ── Symmetry-predicted ore (lighter validation) ─────────────
        sym = self.brain.symmetry_manager
        if sym.is_cracked():
            for pos in list(mm.known_ore_positions):
                reflected = sym.reflect(pos)
                if reflected is None or not on_map(reflected, mm.width, mm.height):
                    continue
                if reflected in mm.known_ore_positions:
                    continue  # already checked above
                if not self._is_valid_predicted_ore(
                    ct, mm, reflected, current_round, enemy_count, my_pos
                ):
                    continue
                building = mm.get_building(reflected)
                has_turret = (
                    building is not None
                    and building.team == team
                    and building.entity_type in TURRET_TYPES
                )
                dist = manhattan(reflected, ally_core)
                self_dist = manhattan(reflected, my_pos) if my_pos is not None else 0
                _consider(reflected, dist, self_dist, has_turret)

        return best_pos

    def _find_closest_cached(self, ct, mm, current_round, enemy_count=0, my_pos=None):
        if self._core_cache_round == current_round:
            return self._core_cache_result
        result = self._find_closest_to_core(ct, mm, current_round, enemy_count, my_pos)
        self._core_cache_round = current_round
        self._core_cache_result = result
        return result

    # ── Enemy counting ──────────────────────────────────────────────

    def _count_nearby_enemies(self, ct: Controller, mm: MapManager) -> int:
        count = 0
        team = ct.get_team()
        for pos in mm.nearby_positions:
            building = mm.get_building(pos)
            if building is not None and building.team != team:
                count += 1
        return count

    # ── Cooldown management ─────────────────────────────────────────

    def _expire_cooldowns(self, current_round: int) -> None:
        expired = [p for p, r in self.cooldowns.items()
                   if current_round - r > COOLDOWN_DURATION]
        for p in expired:
            del self.cooldowns[p]

    # ── Target bookkeeping ──────────────────────────────────────────

    def _assign_target(self, pos: Position | None, current_round: int) -> None:
        if pos != self.target:
            self._target_set_round = current_round if pos is not None else -1
            self._phase = PHASE_ROUTE
        self.target = pos

    def _clear_target(self, current_round: int, *, cooldown: bool = False) -> None:
        if self.target is not None and cooldown:
            self.cooldowns[self.target] = current_round
        self.target = None
        self._target_set_round = -1
        self._phase = PHASE_ROUTE
        # Bust cache so next search re-evaluates
        self._core_cache_round = -1

    # ── Target validation ───────────────────────────────────────────

    def _validate_target(
        self,
        ct: Controller,
        mm: MapManager,
        my_pos: Position,
        current_round: int,
        enemy_count: int,
    ) -> None:
        """Drop current target if no longer valid or timed out."""
        if self.target is None:
            return

        on_target = is_on_position(my_pos, self.target)
        ec = 0 if on_target or in_action_range(my_pos, self.target) else enemy_count

        # Visible tiles get full validation; unseen predicted tiles get light
        tile = mm.get_tile(self.target)
        if tile is not None:
            valid = self._is_valid_ore(ct, mm, self.target, current_round, ec, my_pos)
        else:
            valid = self._is_valid_predicted_ore(ct, mm, self.target, current_round, ec, my_pos)

        if not valid:
            # Don't cooldown ore that's just temporarily reserved by another bot
            bot_on_ore = mm.get_bot(self.target)
            self._clear_target(current_round, cooldown=(bot_on_ore is None))
            return

        # Timed out — routing too long without reaching the ore
        if (
            ROUTE_TIMEOUT > 0
            and not on_target
            and self._target_set_round > 0
            and current_round - self._target_set_round >= ROUTE_TIMEOUT
        ):
            self._clear_target(current_round, cooldown=True)

    # ── Resource check ──────────────────────────────────────────────

    def _can_afford_soon(self, ct: Controller) -> bool:
        resources = ct.get_global_resources()[0]
        harvester_cost = ct.get_harvester_cost()[0]
        buffer = int(GameConstants.HARVESTER_BASE_COST[0] * RESOURCE_BUFFER_FRACTION)
        return resources >= harvester_cost + buffer

    # ── Step-off helper ─────────────────────────────────────────────

    def _try_step_off(self, ct: Controller, mm, ore_pos: Position) -> bool:
        """Move off the ore tile to any adjacent walkable tile."""
        for d in DIRECTIONS:
            adj = ore_pos.add(d)
            if not on_map(adj, mm.width, mm.height):
                continue
            tile = mm.get_tile(adj)
            if tile is None or tile == Environment.WALL:
                continue
            if mm.get_bot(adj) is not None:
                continue
            if move_road_if_empty(ct, d):
                return True
        return False

    # ── Core round ──────────────────────────────────────────────────

    @cputimer
    def execute(self, ct: Controller) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        current_round = ct.get_current_round()

        self._expire_cooldowns(current_round)

        enemy_count = self._count_nearby_enemies(ct, mm)
        self._validate_target(ct, mm, my_pos, current_round, enemy_count)

        # Target lost — reset to route phase and pick a new one
        if self.target is None:
            self._phase = PHASE_ROUTE
            best = self._find_closest_cached(ct, mm, current_round, enemy_count, my_pos)
            self._assign_target(best, current_round)

        if self.target is None:
            return False
        
        print(f"Target: {self.target}")

        if self._phase == PHASE_SABOTAGE:
            return self._execute_sabotage(ct, mm, my_pos)
        if self._phase == PHASE_BUILD:
            return self._execute_build(ct, mm, my_pos)
        return self._execute_route(ct, mm, my_pos)

    # ── Route phase ─────────────────────────────────────────────────

    def _execute_route(self, ct: Controller, mm, my_pos: Position) -> bool:
        """Path to ore, step onto it, wait for resources, then transition."""

        # Sitting on the ore — start clearing enemy infra immediately.
        # Affordability is checked at the SABOTAGE → BUILD transition.
        if is_on_position(my_pos, self.target):
            self._phase = PHASE_SABOTAGE
            return self._execute_sabotage(ct, mm, my_pos)

        # Adjacent — step onto ore to reserve it.
        # Exception: an ally turret may be sitting on the ore. Destroy it
        # first, then step on next round.
        if in_action_range(my_pos, self.target):
            building = mm.get_building(self.target)
            if (
                building is not None
                and building.team == ct.get_team()
                and building.entity_type in TURRET_TYPES
            ):
                if ct.can_destroy(self.target):
                    ct.destroy(self.target)
                return False

            direction = my_pos.direction_to(self.target)
            move_road_if_empty(ct, direction)
            return False

        # Far away — path toward target
        common_path(ct, mm, self.brain.pathing, self.target)
        return False

    # ── Sabotage phase ───────────────────────────────────────────────

    def _find_enemy_infra_cardinal(self, mm, team) -> Direction | None:
        """Return a direction whose cardinal neighbour of target has enemy infra."""
        for d in CARDINAL:
            adj = self.target.add(d)
            if not on_map(adj, mm.width, mm.height):
                continue
            building = mm.get_building(adj)
            if (
                building is not None
                and building.team != team
                and building.entity_type in ENEMY_INFRA_TYPES
            ):
                return d
        return None

    def _execute_sabotage(self, ct: Controller, mm, my_pos: Position) -> bool:
        """Destroy enemy infra on cardinal neighbours before building roads.

        Builders can only ``fire`` at enemy buildings while standing on top of
        them (distance² == 0), so to clear an enemy road adjacent to the ore
        we must step off onto it, fire, then step back.
        """
        print(f"[BH sabotage] enter my_pos={my_pos} target={self.target}")
        team = ct.get_team()

        # ── Case A: Standing on the ore ─────────────────────────────
        if is_on_position(my_pos, self.target):
            sab_dir = self._find_enemy_infra_cardinal(mm, team)
            if sab_dir is None:
                # Cardinals clean — wait for resources then hand off to BUILD
                if not self._can_afford_soon(ct):
                    print(f"[BH sabotage] clear; waiting on resources")
                    return False
                print(f"[BH sabotage] clear + affordable → PHASE_BUILD")
                self._phase = PHASE_BUILD
                return self._execute_build(ct, mm, my_pos)

            # Step off onto the enemy tile so we can fire it next
            enemy_pos = self.target.add(sab_dir)
            print(f"[BH sabotage] stepping off onto enemy infra at {enemy_pos}")
            if ct.can_move(sab_dir):
                ct.move(sab_dir)
                # Try to fire it in the same round if cooldowns allow
                if ct.can_fire(enemy_pos):
                    ct.fire(enemy_pos)
                    print(f"[BH sabotage] moved + FIRED at {enemy_pos}")
                else:
                    print(f"[BH sabotage] moved; fire next round")
            else:
                print(f"[BH sabotage] can_move={False} — stuck this round")
            return False

        # ── Case B: Off the ore, inside action range ─────────────────
        if in_action_range(my_pos, self.target):
            building_here = mm.get_building(my_pos)
            on_enemy_infra = (
                building_here is not None
                and building_here.team != team
                and building_here.entity_type in ENEMY_INFRA_TYPES
            )

            if on_enemy_infra:
                if ct.can_fire(my_pos):
                    ct.fire(my_pos)
                    print(f"[BH sabotage] FIRED at {my_pos}")
                else:
                    print(f"[BH sabotage] on enemy infra {my_pos} but can_fire=False")
                return False

            # Empty (or ally) tile adjacent to ore — step back onto ore.
            # Abort if another bot has taken the ore while we were off.
            other = mm.get_bot(self.target)
            if other is not None and not is_on_position(my_pos, self.target):
                print(f"[BH sabotage] ore {self.target} taken by another bot — abandoning")
                self._clear_target(ct.get_current_round(), cooldown=True)
                return False

            direction = my_pos.direction_to(self.target)
            print(f"[BH sabotage] stepping back onto ore via {direction}")
            move_road_if_empty(ct, direction)
            return False

        # ── Case C: Pushed far away — fall back to ROUTE ────────────
        print(f"[BH sabotage] far from target — reverting to ROUTE")
        self._phase = PHASE_ROUTE
        return self._execute_route(ct, mm, my_pos)

    # ── Build phase ─────────────────────────────────────────────────

    def _execute_build(self, ct: Controller, mm, my_pos: Position) -> bool:
        """Surround ore with roads (while on it), step off, destroy road, build harvester."""

        # On the ore — build surrounding roads first (all 4 neighbours at distance²=1),
        # then step off once every eligible neighbour is covered.
        if is_on_position(my_pos, self.target):
            # Re-check for enemy infra that may have appeared during BUILD phase
            team = ct.get_team()
            for d in CARDINAL:
                adj = self.target.add(d)
                if not on_map(adj, mm.width, mm.height):
                    continue
                building = mm.get_building(adj)
                if (
                    building is not None
                    and building.team != team
                    and building.entity_type in ENEMY_INFRA_TYPES
                ):
                    self._phase = PHASE_SABOTAGE
                    return self._execute_sabotage(ct, mm, my_pos)

            for d in CARDINAL:
                adj = self.target.add(d)
                if not on_map(adj, mm.width, mm.height):
                    continue
                if ct.can_build_road(adj):
                    ct.build_road(adj)
                    return False  # used action; wait for next round

            # Don't step off until we can destroy + build on the same round
            if ct.get_action_cooldown() != 0:
                return False
            if ct.get_global_resources()[0] < ct.get_harvester_cost()[0]:
                return False

            # Step off, then immediately destroy road and build harvester
            if not self._try_step_off(ct, mm, self.target):
                self._clear_target(ct.get_current_round(), cooldown=True)
                return False

            if ct.can_destroy(self.target):
                ct.destroy(self.target)
            if ct.can_build_harvester(self.target):
                ct.build_harvester(self.target)
                self.brain.harvester_built = True
                self._clear_target(ct.get_current_round(), cooldown=False)
                return True
            return False

        # Adjacent — check that cardinal roads are all built before placing.
        # If any are missing, step back onto the ore to resume road-building.
        if in_action_range(my_pos, self.target):
            building = mm.get_building(self.target)
            if (
                building is not None
                and building.team == ct.get_team()
                and building.entity_type in TURRET_TYPES
            ):
                # Ally turret still here — fall back to route phase to handle properly
                self._phase = PHASE_ROUTE
                return self._execute_route(ct, mm, my_pos)

            # Verify all cardinal neighbours have roads; if not, step back on
            for d in CARDINAL:
                adj = self.target.add(d)
                if not on_map(adj, mm.width, mm.height):
                    continue
                adj_building = mm.get_building(adj)
                if adj_building is None or adj_building.entity_type != EntityType.ROAD:
                    direction = my_pos.direction_to(self.target)
                    move_road_if_empty(ct, direction)
                    return False

            if ct.can_destroy(self.target):
                ct.destroy(self.target)
            if ct.can_build_harvester(self.target):
                ct.build_harvester(self.target)
                self.brain.harvester_built = True
                self._clear_target(ct.get_current_round(), cooldown=False)
                return True
            return False

        # Not adjacent (rare — pushed away?) — path back
        if ct.can_destroy(self.target):
            ct.destroy(self.target)
        common_path(ct, mm, self.brain.pathing, self.target)
        return False

    # ── Reachability helper ──────────────────────────────────────────

    def _is_reachable(self, pos: Position) -> bool:
        return (pos.x, pos.y) in self.brain.pathing._reachable

    # ── State determination ─────────────────────────────────────────

    @cputimer
    def determine(self, ct: Controller, state_manager) -> bool:
        mm = self.brain.map_manager
        current_round = ct.get_current_round()
        my_pos = ct.get_position()

        # Sticky: already building and still have a target — keep going,
        # but allow a reachable ore to override an unreachable target.
        if (
            state_manager.previous_state == BuilderState.BUILD_HARVESTER
            and self.target is not None
        ):
            if self._is_reachable(self.target):
                state_manager.current_state = BuilderState.BUILD_HARVESTER
                return True
            # Current target unreachable — check if a reachable one exists
            best = self._find_closest_cached(ct, mm, current_round, my_pos=my_pos)
            if best is not None and self._is_reachable(best):
                self._assign_target(best, current_round)
            state_manager.current_state = BuilderState.BUILD_HARVESTER
            return True

        # Keep current target if still valid, but prefer reachable ore
        if (
            self.target is not None
            and self._is_valid_ore(ct, mm, self.target, current_round, my_pos=my_pos)
        ):
            best = self.target
            if not self._is_reachable(best):
                reachable_best = self._find_closest_cached(ct, mm, current_round, my_pos=my_pos)
                if reachable_best is not None and self._is_reachable(reachable_best):
                    best = reachable_best
        else:
            best = self._find_closest_cached(ct, mm, current_round, my_pos=my_pos)

        if best is None:
            return False

        if self.brain.harvester_built:
            if ct.get_global_resources()[0] < ct.get_harvester_cost()[0] + 2 * ct.get_conveyor_cost()[0]:
                return False

        self._assign_target(best, current_round)
        state_manager.current_state = BuilderState.BUILD_HARVESTER
        return True

    # ── Standard interface ──────────────────────────────────────────

    def has_target(self) -> bool:
        return self.target is not None

    def reset(self, ct=None) -> None:
        self.target = None
        self._target_set_round = -1