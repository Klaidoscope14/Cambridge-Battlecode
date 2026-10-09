from cambc import EntityType, Environment, Position
from debug.profiling import cputimer
from helpers.directions import CARDINAL, DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager
from states.builder_state import BuilderState

# ── Tuning constants ────────────────────────────────────────────────

DEBUG = False

MAX_DEFENSIVE_LAUNCHERS = 2
MAX_OFFENSIVE_LAUNCHERS = 4
BUILD_COOLDOWN_ROUNDS = 30
DESTROYABLE = {EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER}

# Belt-like buildings — used for both the enemy-belt trigger and the
# ally-belt requirement that pairs with an adjacent enemy builder.
_BELT_TYPES = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
}


class BuildLauncherState:
    def __init__(self, ct, brain) -> None:
        self.brain = brain
        # Spot found in determine(), consumed by execute() this same tick.
        self.spot: Position | None = None
        self.last_build_round: int | None = None

    # ── Buildability ────────────────────────────────────────────────

    def _is_buildable(self, ct, mm: MapManager, pos: Position) -> bool:
        bot = mm.get_bot(pos)
        if bot is not None and bot.id != ct.get_id():
            return False
        tile = mm.get_tile(pos)
        if tile is None:
            return False
        if tile == Environment.ORE_TITANIUM or tile == Environment.ORE_AXIONITE:
            return False
        building = mm.get_building(pos)
        if building is None:
            return tile == Environment.EMPTY
        if building.team == ct.get_team() and building.entity_type in DESTROYABLE:
            return True
        return False

    def _has_adjacent_enemy_belt(self, ct, mm: MapManager, pos: Position) -> bool:
        team = ct.get_team()
        for d in CARDINAL:
            n = pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            b = mm.get_building(n)
            if b is None:
                continue
            if b.team == team:
                continue
            if b.entity_type in _BELT_TYPES:
                return True
        return False

    def _has_adjacent_ally_belt(self, ct, mm: MapManager, pos: Position) -> bool:
        team = ct.get_team()
        for d in CARDINAL:
            n = pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            b = mm.get_building(n)
            if b is None:
                continue
            if b.team != team:
                continue
            if b.entity_type in _BELT_TYPES:
                return True
        return False

    def _has_adjacent_enemy_builder(self, ct, mm: MapManager, pos: Position) -> bool:
        team = ct.get_team()
        for d in CARDINAL:
            n = pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            bot = mm.get_bot(n)
            if bot is None:
                continue
            if bot.team != team:
                return True
        return False

    def _has_adjacent_enemy_gunner(self, ct, mm: MapManager, pos: Position) -> bool:
        team = ct.get_team()
        for d in CARDINAL:
            n = pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            b = mm.get_building(n)
            if b is None:
                continue
            if b.team == team:
                continue
            if b.entity_type == EntityType.GUNNER:
                return True
        return False

    def _in_gunner_danger(self, mm: MapManager, pos: Position) -> bool:
        return pos in mm.gunner_danger_positions or pos in mm.ally_gunner_danger_positions

    def _has_adjacent_launcher(self, mm: MapManager, pos: Position) -> bool:
        """True if any known launcher sits in one of the 8 tiles around `pos`.
        Enforces the no-two-adjacent-launchers invariant."""
        for lpos in mm.seen_launcher_positions:
            if lpos.distance_squared(pos) <= 2 and lpos != pos:
                return True
        return False

    def _qualifies(self, ct, mm: MapManager, pos: Position) -> bool:
        """A tile is a valid launcher spot if it's buildable, has no launcher
        8-adjacent to it, AND triggers via either:
          - cardinally-adjacent enemy belt, OR
          - cardinally-adjacent enemy builder AND cardinally-adjacent ally belt."""
        if not self._is_buildable(ct, mm, pos):
            return False
        if self._has_adjacent_launcher(mm, pos):
            return False
        if self._has_adjacent_enemy_gunner(ct, mm, pos):
            return False
        if self._in_gunner_danger(mm, pos):
            return False
        if self._has_adjacent_enemy_belt(ct, mm, pos):
            return True
        if (
            self._has_adjacent_enemy_builder(ct, mm, pos)
            and self._has_adjacent_ally_belt(ct, mm, pos)
        ):
            return True
        return False

    def _find_spot(self, ct, mm: MapManager, my_pos: Position) -> tuple[Position | None, bool]:
        """Scan the bot's own tile + 8 neighbours; return (tile, is_offensive).
        is_offensive is True when the trigger is an adjacent enemy belt,
        False when it's the ally-belt + adjacent-enemy-builder fallback."""
        if self._qualifies(ct, mm, my_pos):
            return my_pos, self._has_adjacent_enemy_belt(ct, mm, my_pos)
        for d in DIRECTIONS:
            n = my_pos.add(d)
            if not on_map(n, mm.width, mm.height):
                continue
            if self._qualifies(ct, mm, n):
                return n, self._has_adjacent_enemy_belt(ct, mm, n)
        return None, False

    # ── State interface ─────────────────────────────────────────────

    @cputimer
    def determine(self, ct, state_manager) -> bool:
        mm = self.brain.map_manager
        my_pos = ct.get_position()

        # Unit cap: max 50 units on the map
        if ct.get_unit_count() >= 50:
            return False

        if self.last_build_round is not None:
            since = ct.get_current_round() - self.last_build_round
            if since < BUILD_COOLDOWN_ROUNDS:
                if DEBUG:
                    print(
                        f"[BuildLauncher] skip: cooldown "
                        f"({since}/{BUILD_COOLDOWN_ROUNDS} rounds since last build)"
                    )
                return False

        cost = ct.get_launcher_cost()[0] * 2
        have = ct.get_global_resources()[0]
        if have < cost:
            if DEBUG:
                print(f"[BuildLauncher] skip: can't afford (have={have}, need={cost})")
            return False

        # Need the action cooldown to actually do anything this tick.
        action_cd = ct.get_action_cooldown()
        if action_cd > 0:
            if DEBUG:
                print(f"[BuildLauncher] skip: action cooldown={action_cd}")
            return False

        spot, is_offensive = self._find_spot(ct, mm, my_pos)
        if spot is None:
            if DEBUG:
                self._explain_no_spot(ct, mm, my_pos)
            return False

        # Cap: don't pile up launchers in a tight region. Offensive spots
        # (adjacent enemy belt) get a higher cap than defensive ones.
        cap = MAX_OFFENSIVE_LAUNCHERS if is_offensive else MAX_DEFENSIVE_LAUNCHERS
        vision_sq = ct.get_vision_radius_sq()
        visible = sum(
            1 for lpos in mm.seen_launcher_positions
            if my_pos.distance_squared(lpos) <= vision_sq
        )
        if visible >= cap:
            if DEBUG:
                kind = "offensive" if is_offensive else "defensive"
                print(
                    f"[BuildLauncher] skip: {kind} cap hit "
                    f"({visible} visible >= {cap})"
                )
            return False

        if DEBUG:
            print(f"[BuildLauncher] found spot {spot} from my_pos={my_pos}")
        self.spot = spot
        state_manager.current_state = BuilderState.BUILD_LAUNCHER
        return True

    def _explain_no_spot(self, ct, mm: MapManager, my_pos: Position) -> None:
        """Walk the 9-tile region and print why each tile failed."""
        belt_count = 0
        builder_count = 0
        ally_belt_count = 0
        buildable_count = 0
        clean_count = 0  # tiles with no adjacent launcher
        for d in [None] + list(DIRECTIONS):
            tile = my_pos if d is None else my_pos.add(d)
            label = "self" if d is None else str(d)
            if d is not None and not on_map(tile, mm.width, mm.height):
                print(f"[BuildLauncher]   {label} {tile}: off-map")
                continue
            buildable = self._is_buildable(ct, mm, tile)
            adj_belt = self._has_adjacent_enemy_belt(ct, mm, tile)
            adj_builder = self._has_adjacent_enemy_builder(ct, mm, tile)
            adj_ally_belt = self._has_adjacent_ally_belt(ct, mm, tile)
            adj_launcher = self._has_adjacent_launcher(mm, tile)
            adj_enemy_gunner = self._has_adjacent_enemy_gunner(ct, mm, tile)
            in_danger = self._in_gunner_danger(mm, tile)
            triggers = adj_belt or (adj_builder and adj_ally_belt)
            if buildable:
                buildable_count += 1
            if adj_belt:
                belt_count += 1
            if adj_builder:
                builder_count += 1
            if adj_ally_belt:
                ally_belt_count += 1
            if not adj_launcher:
                clean_count += 1
            if not buildable or adj_launcher or adj_enemy_gunner or in_danger or not triggers:
                # Show what's blocking: building? bot? launcher nearby? no trigger?
                if adj_launcher:
                    blocker = "launcher 8-adjacent"
                elif adj_enemy_gunner:
                    blocker = "enemy gunner adjacent"
                elif in_danger:
                    blocker = "in gunner danger zone"
                elif not buildable:
                    bot = mm.get_bot(tile)
                    bldg = mm.get_building(tile)
                    if bot is not None and bot.id != ct.get_id():
                        blocker = f"bot id={bot.id}"
                    elif bldg is not None:
                        team_tag = "ally" if bldg.team == ct.get_team() else "enemy"
                        blocker = f"{team_tag} {bldg.entity_type}"
                    else:
                        t = mm.get_tile(tile)
                        blocker = f"tile={t}"
                elif adj_builder and not adj_ally_belt:
                    blocker = "enemy builder adjacent but no ally belt"
                else:
                    blocker = "no trigger (no enemy belt, no enemy builder)"
                print(
                    f"[BuildLauncher]   {label} {tile}: "
                    f"buildable={buildable} adj_enemy_belt={adj_belt} "
                    f"adj_enemy_builder={adj_builder} adj_ally_belt={adj_ally_belt} "
                    f"adj_launcher={adj_launcher} ({blocker})"
                )
        print(
            f"[BuildLauncher] no spot: scanned 9 tiles, "
            f"{buildable_count} buildable, {clean_count} launcher-free, "
            f"{belt_count} adj-to-enemy-belt, {builder_count} adj-to-enemy-builder, "
            f"{ally_belt_count} adj-to-ally-belt"
        )

    def execute(self, ct):
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        spot = self.spot
        self.spot = None
        if spot is None:
            return

        # Standing on the spot — destroy blocker, step off.
        # The build itself will happen next tick when we're adjacent.
        if my_pos == spot:
            building = mm.get_building(spot)
            if building is not None and building.team == ct.get_team() and building.entity_type in DESTROYABLE:
                if ct.can_destroy(spot):
                    ct.destroy(spot)
                elif DEBUG:
                    print(f"[BuildLauncher] on-spot {spot}: can_destroy=False on {building.entity_type}")
            stepped = False
            for d in DIRECTIONS:
                if ct.can_move(d):
                    ct.move(d)
                    stepped = True
                    break
            if not stepped and DEBUG:
                print(f"[BuildLauncher] on-spot {spot}: no movable direction, stuck")
            return

        # Adjacent — destroy blocker (if any), then build.
        building = mm.get_building(spot)
        if building is not None and building.team == ct.get_team() and building.entity_type in DESTROYABLE:
            if ct.can_destroy(spot):
                ct.destroy(spot)
            elif DEBUG:
                print(f"[BuildLauncher] adj {spot}: can_destroy=False on {building.entity_type}")
        if ct.can_build_launcher(spot):
            ct.build_launcher(spot)
            self.last_build_round = ct.get_current_round()
        elif DEBUG:
            print(f"[BuildLauncher] adj {spot}: can_build_launcher=False")
