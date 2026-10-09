from cambc import Direction, EntityType, Environment, Position
from debug.profiling import cputimer
from helpers.directions import CARDINAL, CARDINAL_THEN_DIAGONAL, DIRECTIONS
from helpers.geometry import on_map
from map.map_manager import MapManager
from states.builder_state import BuilderState

# Direction → (dx, dy) offset, with y growing south.
_DIR_OFFSET: dict[Direction, tuple[int, int]] = {
    Direction.NORTH:     (0, -1),
    Direction.SOUTH:     (0, 1),
    Direction.EAST:      (1, 0),
    Direction.WEST:      (-1, 0),
    Direction.NORTHEAST: (1, -1),
    Direction.NORTHWEST: (-1, -1),
    Direction.SOUTHEAST: (1, 1),
    Direction.SOUTHWEST: (-1, 1),
}
_OFFSET_DIR: dict[tuple[int, int], Direction] = {v: k for k, v in _DIR_OFFSET.items()}

# For an existing launcher at this offset (relative to my_pos), prioritize
# placing the new launcher at these offsets:
#  - Diagonal launcher → the two corners "beside" it (sharing a 3x3 edge).
#  - Cardinal launcher → the opposite cardinal.
_LAUNCHER_PRIORITY: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {
    (-1, -1): ((1, -1), (-1, 1)),   # NW → NE, SW
    (1, -1):  ((-1, -1), (1, 1)),   # NE → NW, SE
    (1, 1):   ((1, -1), (-1, 1)),   # SE → NE, SW
    (-1, 1):  ((-1, -1), (1, 1)),   # SW → NW, SE
    (0, -1):  ((0, 1),),            # N  → S
    (1, 0):   ((-1, 0),),           # E  → W
    (0, 1):   ((0, -1),),           # S  → N
    (-1, 0):  ((1, 0),),            # W  → E
}

# ── Tuning constants ────────────────────────────────────────────────

DEBUG = False

MAX_DEFENSIVE_LAUNCHERS = 1
MAX_OFFENSIVE_LAUNCHERS = 3
BUILD_COOLDOWN_ROUNDS = 0
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
        if tile == Environment.ORE_TITANIUM or tile == Environment.ORE_AXIONITE or tile == Environment.WALL:
            return False
        building = mm.get_building(pos)
        if building is None:
            return True
        if building.team != ct.get_team():
            # Engine permits building directly on top of enemy markers.
            return building.entity_type == EntityType.MARKER
        return building.entity_type in DESTROYABLE

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
                if self.brain.storage_tracker.is_empty(b.id):
                    continue
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
        8-adjacent to it, and has a cardinally-adjacent enemy belt."""
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
        return False

    def _priority_directions(self, mm: MapManager, my_pos: Position) -> list[Direction]:
        """Return CARDINAL_THEN_DIAGONAL reordered so spots that pair well with
        an existing launcher in our 8-neighborhood come first."""
        priority: list[Direction] = []
        seen: set[Direction] = set()
        for lpos in mm.seen_launcher_positions:
            if lpos == my_pos:
                continue
            if my_pos.distance_squared(lpos) > 2:
                continue
            offset = (lpos.x - my_pos.x, lpos.y - my_pos.y)
            for poff in _LAUNCHER_PRIORITY.get(offset, ()):
                d = _OFFSET_DIR.get(poff)
                if d is not None and d not in seen:
                    seen.add(d)
                    priority.append(d)
        if not priority:
            return CARDINAL_THEN_DIAGONAL
        return priority + [d for d in CARDINAL_THEN_DIAGONAL if d not in seen]

    def _find_spot(self, ct, mm: MapManager, my_pos: Position) -> tuple[Position | None, bool]:
        """Scan the bot's own tile + 8 neighbours; return (tile, is_offensive).
        is_offensive is True when the trigger is an adjacent enemy belt,
        False when it's the ally-belt + adjacent-enemy-builder fallback."""
        if self._qualifies(ct, mm, my_pos):
            return my_pos, self._has_adjacent_enemy_belt(ct, mm, my_pos)
        for d in self._priority_directions(mm, my_pos):
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

        # No enemy bots in sight → no need to build a launcher.
        if not mm.nearby_enemy_builder_bot_ids:
            if DEBUG:
                print("[BuildLauncher] skip: no enemy bots nearby")
            return False

        # 2+ enemy sentinels staring at us → likely to die mid-build.
        if mm.alert_sentinels >= 1.5:
            if DEBUG:
                print(f"[BuildLauncher] skip: {mm.alert_sentinels} sentinels facing us")
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

        cost = ct.get_launcher_cost()[0] * 1.5
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

    def _describe_tile(self, ct, mm: MapManager, tile: Position) -> str:
        """Dump raw map_manager state for a tile: env, building, bot."""
        env = mm.get_tile(tile)
        bldg = mm.get_building(tile)
        bot = mm.get_bot(tile)
        if bldg is None:
            bldg_str = "None"
        else:
            team_tag = "ally" if bldg.team == ct.get_team() else "enemy"
            bldg_str = f"{team_tag} {bldg.entity_type}"
        if bot is None:
            bot_str = "None"
        else:
            team_tag = "ally" if bot.team == ct.get_team() else "enemy"
            self_tag = " (self)" if bot.id == ct.get_id() else ""
            bot_str = f"{team_tag} id={bot.id} {bot.entity_type}{self_tag}"
        return f"env={env} building={bldg_str} bot={bot_str}"

    def _explain_no_spot(self, ct, mm: MapManager, my_pos: Position) -> None:
        """Walk the 9-tile region and print why each tile failed."""
        print(f"[BuildLauncher] no spot: round={ct.get_current_round()} my_pos={my_pos} vision_sq={ct.get_vision_radius_sq()}")
        belt_count = 0
        buildable_count = 0
        clean_count = 0  # tiles with no adjacent launcher
        for d in [None] + list(DIRECTIONS):
            tile = my_pos if d is None else my_pos.add(d)
            label = "self" if d is None else str(d)
            if d is not None and not on_map(tile, mm.width, mm.height):
                print(f"[BuildLauncher]   {label} {tile}: off-map")
                continue
            # Raw mm state dump first — useful when reality disagrees with mm.
            print(f"[BuildLauncher]   {label} {tile}: {self._describe_tile(ct, mm, tile)}")
            # Per-cardinal-neighbor dump — shows which adjacent tile fed each adj_* flag.
            for nd in CARDINAL:
                n = tile.add(nd)
                if not on_map(n, mm.width, mm.height):
                    continue
                nb = mm.get_building(n)
                nbot = mm.get_bot(n)
                if nb is None and nbot is None:
                    continue
                parts = []
                if nb is not None:
                    tt = "ally" if nb.team == ct.get_team() else "enemy"
                    parts.append(f"bldg={tt} {nb.entity_type}")
                if nbot is not None:
                    tt = "ally" if nbot.team == ct.get_team() else "enemy"
                    parts.append(f"bot={tt} id={nbot.id}")
                print(f"[BuildLauncher]     neighbor {nd} {n}: {', '.join(parts)}")
            buildable = self._is_buildable(ct, mm, tile)
            adj_belt = self._has_adjacent_enemy_belt(ct, mm, tile)
            adj_launcher = self._has_adjacent_launcher(mm, tile)
            adj_enemy_gunner = self._has_adjacent_enemy_gunner(ct, mm, tile)
            in_danger = self._in_gunner_danger(mm, tile)
            triggers = adj_belt
            # Note: trigger rule is adj_enemy_belt.
            if buildable:
                buildable_count += 1
            if adj_belt:
                belt_count += 1
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
                else:
                    blocker = "no trigger (no enemy belt)"
                print(
                    f"[BuildLauncher]   {label} {tile}: "
                    f"buildable={buildable} adj_enemy_belt={adj_belt} "
                    f"adj_launcher={adj_launcher} ({blocker})"
                )
        print(
            f"[BuildLauncher] no spot: scanned 9 tiles, "
            f"{buildable_count} buildable, {clean_count} launcher-free, "
            f"{belt_count} adj-to-enemy-belt"
        )

    def execute(self, ct):
        mm = self.brain.map_manager
        my_pos = ct.get_position()
        spot = self.spot
        self.spot = None
        if spot is None:
            return

        # Standing on the spot — destroy blocker, step off.
        if my_pos == spot:
            building = mm.get_building(spot)
            if building is not None and building.team == ct.get_team() and building.entity_type in DESTROYABLE:
                if ct.can_destroy(spot):
                    ct.destroy(spot)
                elif DEBUG:
                    print(f"[BuildLauncher] on-spot {spot}: can_destroy=False on {building.entity_type}")
            stepped = False
            for d in CARDINAL_THEN_DIAGONAL:
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
