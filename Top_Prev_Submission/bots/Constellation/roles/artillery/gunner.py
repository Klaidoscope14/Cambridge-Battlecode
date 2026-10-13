from cambc import Controller, EntityType, Environment, Position, Direction, GameConstants
from debug.profiling import cputimer
from helpers.geometry import on_map
from map.map_manager import MapManager
from helpers.directions import DIRECTIONS

IGNORE_TYPES = {EntityType.HARVESTER}
TURRET_TYPES = {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}

# testing buildings for now
DIRECTION_PRIORITY: list[tuple[EntityType, float]] = [
    (EntityType.CORE,       100),   # enemy core in line → huge pull
    (EntityType.SENTINEL,    40),   # enemy turrets are high-value
    (EntityType.GUNNER,      40),
    (EntityType.LAUNCHER,    30),
    (EntityType.CONVEYOR,    15),   # infrastructure disruption
    (EntityType.SPLITTER,    15),
    (EntityType.BRIDGE,      15),
    # (EntityType.HARVESTER,    5),   # low prio but still enemy stuff
    # (EntityType.BARRIER,      2)
]

_PRIORITY_SCORE: dict[EntityType, float] = {et: sc for et, sc in DIRECTION_PRIORITY}

# penalty when in firing lane
ALLY_BUILDING_BLOCK_PENALTY = -15

def firing_line(pos: Position, facing: Direction) -> list[Position]:
    dx, dy = facing.delta()
    max_range = 3 if (dx == 0 or dy == 0) else 2
    return [Position(pos.x + dx * s, pos.y + dy * s) for s in range(1, max_range + 1)]

# Check if an enemy core is anywhere along this firing line
def _core_in_line(ct, my_pos: Position, facing: Direction, my_team) -> bool:
    for tile in firing_line(my_pos, facing):
        if not on_map(tile, ct.get_map_width(), ct.get_map_height()):
            break
        bid = ct.get_tile_building_id(tile)
        if bid is not None:
            etype = ct.get_entity_type(bid)
            if etype == EntityType.CORE and ct.get_team(bid) != my_team:
                return True
    return False

# walk the firing line and score (only scores the first hit)
def scan_direction(ct, my_pos: Position, facing: Direction, my_team) -> tuple[float, bool, bool]:
    score = 0.0
    blocked = False

    for tile in firing_line(my_pos, facing):
        if not on_map(tile, ct.get_map_width(), ct.get_map_height()):
            break

        env = ct.get_tile_env(tile)
        if env == Environment.WALL:
            blocked = True
            break

        bbid = ct.get_tile_builder_bot_id(tile)
        if bbid is not None:
            if ct.get_team(bbid) == my_team:
                score += ALLY_BUILDING_BLOCK_PENALTY
            else:
                score += _PRIORITY_SCORE.get(EntityType.BUILDER_BOT, 0)
            break

        bid = ct.get_tile_building_id(tile)
        if bid is not None:
            etype = ct.get_entity_type(bid)
            if etype == EntityType.HARVESTER:
                score -= 1
            elif ct.get_team(bid) == my_team:
                score -= _PRIORITY_SCORE.get(etype, 0)
            else:
                score += _PRIORITY_SCORE.get(etype, 0)
            break

    # Separate check: is there a core anywhere along this line?
    has_core = _core_in_line(ct, my_pos, facing, my_team)
    if has_core:
        print("has core", facing)

    return score, blocked, has_core

def best_rotation_target(ct, my_pos: Position, current_facing: Direction, my_team) -> Direction | None:
    scores: dict[Direction, float] = {}
    has_core_current = False

    for d in DIRECTIONS:
        scores[d], _, has_core_flag = scan_direction(ct, my_pos, d, my_team)
        if d == current_facing:
            has_core_current = has_core_flag

    print("currently looking", current_facing)
    print("scores", len(scores))
    for score in scores.items():
        print(score)

    current_score = scores[current_facing]
    best_global = max(DIRECTIONS, key=lambda d: scores[d])

    if scores[best_global] <= current_score:
        return None

    # Don't rotate if no direction is beneficial
    if scores[best_global] <= 0 and current_score <= 0:
        return None

    # If we're aimed at a core, only rotate away to kill an enemy turret
    # that's threatening us — otherwise stay locked on core
    if has_core_current:
        has_threatening_turret = False
        for tile in firing_line(my_pos, best_global):
            if not on_map(tile, ct.get_map_width(), ct.get_map_height()):
                break
            env = ct.get_tile_env(tile)
            if env == Environment.WALL:
                break
            bid = ct.get_tile_building_id(tile)
            if bid is not None:
                etype = ct.get_entity_type(bid)
                if ct.get_team(bid) != my_team and etype in TURRET_TYPES:
                    has_threatening_turret = True
                break
        if not has_threatening_turret:
            return None

    left = current_facing.rotate_left()
    right = current_facing.rotate_right()

    def steps_to(start: Direction, target: Direction) -> int:
        d, count = start, 0
        for _ in range(8):
            if d == target:
                return count
            d = d.rotate_right()
            count += 1
        return count

    left_dist = min(steps_to(left, best_global), 8 - steps_to(left, best_global))
    right_dist = min(steps_to(right, best_global), 8 - steps_to(right, best_global))

    if left_dist < right_dist:
        return left
    if right_dist < left_dist:
        return right

    return left if scores[left] >= scores[right] else right

class Gunner:
    def __init__(self, ct) -> None:
        self.map_manager = MapManager(ct)

    def run(self, ct) -> None:
        (
            self.shoot(ct)
            or self.rotate(ct)
        )

    @cputimer
    def rotate(self, ct) -> bool:
        my_pos = ct.get_position()
        my_team = ct.get_team()
        current_facing = ct.get_direction()

        target_dir = best_rotation_target(ct, my_pos, current_facing, my_team)
        if target_dir is None:
            print("target dir is none")
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
        vision = ct.get_attackable_tiles()

        # Check if enemy core is anywhere along the firing line
        core_in_line = False
        for pos in vision:
            tbid = ct.get_tile_building_id(pos)
            if tbid is not None and ct.get_entity_type(tbid) == EntityType.CORE and ct.get_team(tbid) != team:
                core_in_line = True
                break

        for pos in vision:
            # Don't shoot through ally bots
            bbid = ct.get_tile_builder_bot_id(pos)
            if bbid is not None:
                if ct.get_team(bbid) == team:
                    break
                if ct.can_fire(pos):
                    ct.fire(pos)
                    return True
                break

            tbid = ct.get_tile_building_id(pos)
            if tbid is None:
                continue
            etype = ct.get_entity_type(tbid)
            if etype in IGNORE_TYPES and not core_in_line:
                continue

            # Don't shoot our own buildings (unless core is behind them)
            if ct.get_team(tbid) == team and not core_in_line:
                break

            if ct.can_fire(pos):
                ct.fire(pos)
                return True
            break
        return False
