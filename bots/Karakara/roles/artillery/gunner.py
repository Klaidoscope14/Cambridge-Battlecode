from cambc import Controller, EntityType, Environment, Position, Direction, GameConstants
from debug.profiling import cputimer
from helpers.geometry import on_map
from map.map_manager import MapManager
from helpers.directions import DIRECTIONS, CARDINAL
from roles.artillery.ammo_starvation import AmmoStarvationTracker


# testing buildings for now
DIRECTION_PRIORITY: list[tuple[EntityType, float]] = [
    (EntityType.LAUNCHER,    100),
    (EntityType.GUNNER,      55),
    (EntityType.SENTINEL,    50),   # enemy turrets are high-value
    (EntityType.FOUNDRY,     25),   # economic chokepoint
    (EntityType.CONVEYOR,    15),   # infrastructure disruption
    (EntityType.SPLITTER,    15),
    (EntityType.BRIDGE,      15),
    (EntityType.BARRIER,     10),
    (EntityType.CORE,         5),
]

_PRIORITY_SCORE: dict[EntityType, float] = {et: sc for et, sc in DIRECTION_PRIORITY}

UNCONNECTED_HARVESTER_SCORE = 12  # worth shooting but lower than turrets/launchers
ALLY_BUILDING_BLOCK_PENALTY = -15 # penalty when in firing lane
AIMED_AT_ME_BONUS = 40 # bonus when an enemy turret in our firing line is aimed at us

TURRET_TYPES = {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}
_BELT_TYPES = {EntityType.CONVEYOR, EntityType.BRIDGE}
_HARVESTER_PROTECT_TYPES = _BELT_TYPES | TURRET_TYPES

def _turret_aims_at(ct, turret_pos: Position, turret_facing: Direction, target_pos: Position) -> bool:
    """Does the turret's firing line include target_pos?"""
    for tile in firing_line(turret_pos, turret_facing):
        if tile == target_pos:
            return True
    return False

def firing_line(pos: Position, facing: Direction) -> list[Position]:
    dx, dy = facing.delta()
    max_range = 3 if (dx == 0 or dy == 0) else 2
    return [Position(pos.x + dx * s, pos.y + dy * s) for s in range(1, max_range + 1)]

def _road_next_to_ally_harvester(ct, road_pos: Position, my_team) -> bool:
    """True if any cardinal neighbour of road_pos is an ally harvester."""
    w, h = ct.get_map_width(), ct.get_map_height()
    for d in CARDINAL:
        n = road_pos.add(d)
        if not on_map(n, w, h):
            continue
        if not ct.is_in_vision(n):
            continue
        bid = ct.get_tile_building_id(n)
        if bid is None:
            continue
        if ct.get_entity_type(bid) == EntityType.HARVESTER and ct.get_team(bid) == my_team:
            return True
    return False

def _find_source_harvester(ct, gunner_pos: Position, my_team) -> Position | None:
    """Find the harvester feeding this gunner by checking cardinal neighbors.
    When multiple candidates exist, pick the one blocking the least valuable
    firing line so the gunner can shoot in more useful directions.
    Ally harvesters always win ties (we'd never shoot those anyway).
    """
    w, h = ct.get_map_width(), ct.get_map_height()
    ally_candidates: list[tuple[Position, Direction]] = []
    enemy_candidates: list[tuple[Position, Direction]] = []
    for d in CARDINAL:
        n = gunner_pos.add(d)
        if not on_map(n, w, h):
            continue
        bid = ct.get_tile_building_id(n)
        if bid is None:
            continue
        if ct.get_entity_type(bid) != EntityType.HARVESTER:
            continue
        if ct.get_team(bid) == my_team:
            ally_candidates.append((n, d))
        else:
            enemy_candidates.append((n, d))

    # Pick from ally candidates first, then enemy
    candidates = ally_candidates if ally_candidates else enemy_candidates
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    # Multiple candidates — score each direction and pick the lowest
    best_pos = candidates[0][0]
    best_score = float('inf')
    for pos, d in candidates:
        score, _ = scan_direction(ct, gunner_pos, d, my_team)
        if score < best_score:
            best_score = score
            best_pos = pos
    return best_pos

def _is_unconnected_enemy_harvester(ct, harvester_pos: Position, my_team) -> bool:
    """True if an enemy harvester has no ally conveyor/bridge on any cardinal side.
    Returns False if any cardinal neighbour is out of vision (can't confirm it's
    unconnected, so leave it alone).
    """
    w, h = ct.get_map_width(), ct.get_map_height()
    for d in CARDINAL:
        n = harvester_pos.add(d)
        if not on_map(n, w, h):
            continue  # off-map = no belt there, that side is fine
        if not ct.is_in_vision(n):
            return False  # can't see this side, assume it might be connected
        bid = ct.get_tile_building_id(n)
        if bid is None:
            continue
        if ct.get_team(bid) == my_team and ct.get_entity_type(bid) in _HARVESTER_PROTECT_TYPES:
            return False  # ally belt or turret found, don't break this harvester
    return True

# walk the firing line and score (only scores the first hit)
def scan_direction(ct, my_pos: Position, facing: Direction, my_team, source_harvester: Position | None = None, ignore_ally_bots: bool = False) -> tuple[float, bool]:
    score = 0.0
    blocked = False
    found_real_target = False
    trace: list[str] = []  # what we saw on each tile

    for tile in firing_line(my_pos, facing):
        if not on_map(tile, ct.get_map_width(), ct.get_map_height()):
            trace.append("oob")
            break

        env = ct.get_tile_env(tile)
        if env == Environment.WALL:
            trace.append("wall")
            blocked = True
            break

        bbid = ct.get_tile_builder_bot_id(tile)
        if bbid is not None:
            if ct.get_team(bbid) == my_team:
                if ignore_ally_bots:
                    # second pass — pretend the ally bot isn't there
                    trace.append("ally_bot(ignored)")
                    continue
                trace.append("ally_bot")
                score += ALLY_BUILDING_BLOCK_PENALTY
                found_real_target = True
                break
            # enemy bot — transient, look past it
            trace.append("enemy_bot")
            continue

        bid = ct.get_tile_building_id(tile)
        if bid is None:
            trace.append("empty")
            continue

        etype = ct.get_entity_type(bid)

        if etype == EntityType.MARKER:
            trace.append("marker")
            continue
        if etype == EntityType.ROAD and ct.get_team(bid) == my_team:
            if _road_next_to_ally_harvester(ct, tile, my_team):
                trace.append("ally_road(protected)")
                blocked = True
                break
            trace.append("ally_road")
            continue
        if etype == EntityType.ROAD:
            # enemy road — not a real target, look past it
            trace.append("enemy_road")
            continue
        if etype == EntityType.HARVESTER:
            if ct.get_team(bid) == my_team:
                # ally harvester — never shoot, slight penalty
                trace.append("ally_harvester")
                score -= 1
            elif tile == source_harvester:
                # this is our ammo source — don't rotate toward breaking it
                trace.append("enemy_harvester(source)")
                score -= 1
            elif _is_unconnected_enemy_harvester(ct, tile, my_team):
                # enemy harvester with no ally belts — shoot it
                trace.append("enemy_harvester(unconnected)")
                score += UNCONNECTED_HARVESTER_SCORE
            else:
                # enemy harvester that feeds us or we can't fully see — skip
                trace.append("enemy_harvester(connected/unknown)")
                score -= 1
        elif ct.get_team(bid) == my_team:
            trace.append(f"ally_{etype.name.lower()}")
            score -= _PRIORITY_SCORE.get(etype, 0)
        else:
            trace.append(f"enemy_{etype.name.lower()}")
            score += _PRIORITY_SCORE.get(etype, 0)
            if etype in TURRET_TYPES:
                turret_facing = ct.get_direction(bid)
                if turret_facing is not None and _turret_aims_at(ct, tile, turret_facing, my_pos):
                    trace.append("aimed_at_me")
                    score += AIMED_AT_ME_BONUS
        found_real_target = True
        break

    if not found_real_target:
        score = 0.0

    print(f"  {facing}: score={score:+.0f} blocked={blocked} [{', '.join(trace)}]")
    return score, blocked

def best_rotation_target(ct, my_pos: Position, current_facing: Direction, my_team, source_harvester: Position | None = None, ignore_ally_bots: bool = False) -> Direction | None:
    """Pick the single best direction to face. Since we can rotate instantly to
    any direction, just return the global best (or None if rotation isn't worthwhile)."""
    scores: dict[Direction, float] = {}

    for d in DIRECTIONS:
        scores[d], _ = scan_direction(ct, my_pos, d, my_team, source_harvester, ignore_ally_bots)

    print("currently looking", current_facing)

    current_score = scores[current_facing]
    best_global = max(DIRECTIONS, key=lambda d: scores[d])

    # Already facing the best — nothing to do
    if best_global == current_facing:
        return None

    if scores[best_global] <= current_score:
        return None

    # Don't rotate if no direction is beneficial
    if scores[best_global] <= 0 and current_score <= 0:
        return None

    return best_global

def _pick_belt_dir(ct, my_pos: Position, current_facing: Direction, my_team) -> Direction | None:
    """Pick an adjacent ally conveyor/bridge direction to commit to."""
    w, h = ct.get_map_width(), ct.get_map_height()
    for d in DIRECTIONS:
        if d == current_facing:
            continue
        adj = my_pos.add(d)
        if not on_map(adj, w, h):
            continue
        bid = ct.get_tile_building_id(adj)
        if bid is None:
            continue
        if ct.get_team(bid) == my_team and ct.get_entity_type(bid) in _BELT_TYPES:
            return d
    return None

def _belt_still_valid(ct, my_pos: Position, d: Direction, my_team) -> bool:
    """Check the committed belt direction still has an ally belt."""
    adj = my_pos.add(d)
    if not on_map(adj, ct.get_map_width(), ct.get_map_height()):
        return False
    bid = ct.get_tile_building_id(adj)
    if bid is None:
        return False
    return ct.get_team(bid) == my_team and ct.get_entity_type(bid) in _BELT_TYPES

class Gunner:
    def __init__(self, ct) -> None:
        self.map_manager = MapManager(ct)
        self._belt_target_dir: Direction | None = None
        self._ammo_tracker = AmmoStarvationTracker()

    def run(self, ct) -> None:
        if self._ammo_tracker.maybe_self_destruct(ct):
            return

        if ct.get_ammo_amount() == 0:
            return

        (
            self.shoot(ct)
            or self.rotate(ct)
        )

    @cputimer
    def rotate(self, ct) -> bool:
        my_pos = ct.get_position()
        my_team = ct.get_team()
        current_facing = ct.get_direction()

        source_harvester = _find_source_harvester(ct, my_pos, my_team)

        current_score, _ = scan_direction(ct, my_pos, current_facing, my_team, source_harvester)
        target_dir = best_rotation_target(ct, my_pos, current_facing, my_team, source_harvester)
        if target_dir is not None:
            self._belt_target_dir = None  # real target found, drop belt commitment
        elif current_score > 0:
            return False  # already facing something worth shooting, don't rotate to belt
        else:
            target_dir = best_rotation_target(ct, my_pos, current_facing, my_team, source_harvester, ignore_ally_bots=True)
            if target_dir is not None:
                self._belt_target_dir = None

        if target_dir is None:
            # Stick with committed belt direction, or pick a new one
            if self._belt_target_dir is not None:
                if current_facing == self._belt_target_dir:
                    return False  # reached it, stay aimed at this belt
                elif not _belt_still_valid(ct, my_pos, self._belt_target_dir, my_team):
                    self._belt_target_dir = None  # belt gone
            if self._belt_target_dir is None:
                self._belt_target_dir = _pick_belt_dir(ct, my_pos, current_facing, my_team)
            if self._belt_target_dir is not None:
                target_dir = self._belt_target_dir

        if target_dir is None:
            return False

        if target_dir == current_facing:
            return False

        if ct.can_rotate(target_dir):
            ct.rotate(target_dir)
            return True
        else:
            print("cannot rotate")

        return False

    @cputimer
    def shoot(self, ct) -> bool:
        team = ct.get_team()
        my_pos = ct.get_position()
        vision = ct.get_attackable_tiles()

        # Find the harvester feeding this gunner — never shoot it
        source_harvester = _find_source_harvester(ct, my_pos, team)

        first_ally_road: Position | None = None

        for pos in vision:
            # Don't shoot through ally bots
            bbid = ct.get_tile_builder_bot_id(pos)
            if bbid is not None:
                if ct.get_team(bbid) == team:
                    return False
                target = first_ally_road if first_ally_road is not None else pos
                if ct.can_fire(target):
                    ct.fire(target)
                    return True
                return False

            tbid = ct.get_tile_building_id(pos)
            if tbid is None:
                continue

            etype = ct.get_entity_type(tbid)
            if etype == EntityType.MARKER:
                continue  # markers are non-blocking, shoot through them

            if etype == EntityType.HARVESTER:
                if ct.get_team(tbid) == team:
                    continue  # ally harvester, never shoot
                if pos == source_harvester:
                    continue  # this one feeds us, don't break it
                if _is_unconnected_enemy_harvester(ct, pos, team):
                    # enemy harvester with no ally belts — treat as real target
                    target = first_ally_road if first_ally_road is not None else pos
                    if ct.can_fire(target):
                        ct.fire(target)
                        return True
                    return False
                else:
                    continue  # connected or can't fully see, skip it

            # Ally roads: remember the first one and keep scanning
            if etype == EntityType.ROAD and ct.get_team(tbid) == team:
                if _road_next_to_ally_harvester(ct, pos, team):
                    return False  # protective road, don't break it
                if first_ally_road is None:
                    first_ally_road = pos
                continue

            # Don't shoot our own buildings
            if ct.get_team(tbid) == team:
                return False

            # Real target found — shoot the road in front of it if there is one,
            # otherwise shoot the target directly
            target = first_ally_road if first_ally_road is not None else pos
            if ct.can_fire(target):
                ct.fire(target)
                return True
            return False

        return False
