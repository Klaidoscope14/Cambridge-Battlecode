from cambc import Controller, EntityType, GameConstants, Position, Direction
from map.map_manager import MapManager
from helpers.geometry import on_map
from helpers.directions import CARDINAL
from roles.artillery.ammo_starvation import AmmoStarvationTracker

DEBUG = True

# ── Priority order: lower index = shoot first ─────────────────────

TARGET_PRIORITY = [
    EntityType.LAUNCHER,
    EntityType.HARVESTER,   # unconnected enemy harvesters only
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BARRIER,
    EntityType.BUILDER_BOT,
    EntityType.ROAD,        # only roads cardinal-adjacent to enemy harvesters
    EntityType.ARMOURED_CONVEYOR,
    EntityType.FOUNDRY,
    EntityType.CORE,
]

_PRIORITY_INDEX = {et: i for i, et in enumerate(TARGET_PRIORITY)}

TURRET_TYPES = {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}
_BELT_TYPES = {EntityType.CONVEYOR, EntityType.BRIDGE}
_HARVESTER_PROTECT_TYPES = _BELT_TYPES | TURRET_TYPES
_SURROUND_TYPES = {EntityType.GUNNER, EntityType.SENTINEL, EntityType.CONVEYOR,
                   EntityType.ARMOURED_CONVEYOR, EntityType.FOUNDRY, EntityType.SPLITTER}

def _get_builder_bot_positions(ct) -> tuple[list[Position], list[Position]]:
    """Return (ally_positions, enemy_positions) of all visible builder bots.
    Excludes self from the ally list. Single pass over nearby units.
    """
    team = ct.get_team()
    my_id = ct.get_id()
    ally_positions: list[Position] = []
    enemy_positions: list[Position] = []
    for eid in ct.get_nearby_units():
        if ct.get_entity_type(eid) != EntityType.BUILDER_BOT:
            continue
        if ct.get_team(eid) == team:
            if eid == my_id:
                continue
            ally_positions.append(ct.get_position(eid))
        else:
            enemy_positions.append(ct.get_position(eid))
    return ally_positions, enemy_positions


def _min_sq_dist_to_positions(pos: Position, others: list[Position]) -> int:
    """Min squared distance from pos to any position in others. 0 if empty."""
    if not others:
        return 0
    best = None
    for o in others:
        dx = pos.x - o.x
        dy = pos.y - o.y
        d = dx * dx + dy * dy
        if best is None or d < best:
            best = d
    return best


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

def _is_ally_harvester_surrounded_by_turrets(ct, harvester_pos: Position, my_team) -> bool:
    """True if an ally harvester is boxed in on all 4 cardinal sides by ENEMY """
    w, h = ct.get_map_width(), ct.get_map_height()
    for d in CARDINAL:
        n = harvester_pos.add(d)
        if not on_map(n, w, h):
            continue  # off-map = map edge acts as a wall, counts as blocked
        if not ct.is_in_vision(n):
            return False  # can't confirm — don't assume surrounded
        bid = ct.get_tile_building_id(n)
        if bid is None:
            return False  # empty side — not surrounded
        if ct.get_team(bid) == my_team:
            return False  # ally on a side — not an enemy cage
        if ct.get_entity_type(bid) not in _SURROUND_TYPES:
            return False  # enemy building, but not a gunner/sentinel
    return True

def _is_road_near_harvester(ct, road_pos: Position, my_team) -> bool:
    """True if a harvester is cardinal-adjacent to this road."""
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
        if ct.get_entity_type(bid) == EntityType.HARVESTER:
            return True
    return False

def _collect_targets(ct, positions) -> list[tuple[int, int, EntityType, Position]]:
    """Scan a set of positions for enemy targets.
    Returns list of (priority_index, hp, entity_type, position) for each
    enemy target found.  Shoots unconnected enemy harvesters (no ally
    belts/turrets adjacent), skips connected ones.
    """
    team = ct.get_team()
    targets = []

    for pos in positions:
        # Check for enemy builder bot first
        bbid = ct.get_tile_builder_bot_id(pos)
        if bbid is not None:
            if ct.get_team(bbid) != team:
                pri = _PRIORITY_INDEX.get(EntityType.BUILDER_BOT)
                hp = ct.get_hp(bbid)
                targets.append((pri, hp, EntityType.BUILDER_BOT, pos))
            continue

        tbid = ct.get_tile_building_id(pos)
        if tbid is None:
            continue
        if ct.get_team(tbid) == team:
            if (ct.get_entity_type(tbid) == EntityType.HARVESTER
                    and _is_ally_harvester_surrounded_by_turrets(ct, pos, team)):
                pri = _PRIORITY_INDEX.get(EntityType.HARVESTER)
                hp = ct.get_hp(tbid)
                targets.append((pri, hp, EntityType.HARVESTER, pos))
            continue

        etype = ct.get_entity_type(tbid)
        if etype == EntityType.ROAD:
            if _is_road_near_harvester(ct, pos, team):
                pri = _PRIORITY_INDEX.get(EntityType.ROAD)
                hp = ct.get_hp(tbid)
                targets.append((pri, hp, EntityType.ROAD, pos))
            continue  # not near enemy harvester — skip

        if etype == EntityType.HARVESTER:
            if _is_unconnected_enemy_harvester(ct, pos, team):
                # enemy harvester with no ally belts/turrets — shoot it
                pri = _PRIORITY_INDEX.get(EntityType.HARVESTER)
                hp = ct.get_hp(tbid)
                targets.append((pri, hp, EntityType.HARVESTER, pos))
            continue  # connected or can't fully see — skip

        pri = _PRIORITY_INDEX.get(etype)
        if pri is None:
            continue

        hp = ct.get_hp(tbid)
        targets.append((pri, hp, etype, pos))

    return targets


# ── Sentinel class ─────────────────────────────────────────────────


class Sentinel:
    def __init__(self, ct) -> None:
        self.map_manager = MapManager(ct)
        self._ammo_tracker = AmmoStarvationTracker()

    def run(self, ct) -> None:
        if DEBUG:
            pos = ct.get_position()
            print(f"[SENTINEL {ct.get_id()}] run() round={ct.get_current_round()} pos=({pos.x},{pos.y}) dir={ct.get_direction()} ammo={ct.get_ammo_amount()}")
        if self._ammo_tracker.maybe_self_destruct(ct):
            if DEBUG:
                print(f"[SENTINEL {ct.get_id()}] ammo_tracker.maybe_self_destruct ate the turn")
            return
        self.shoot(ct)

    def shoot(self, ct) -> bool:
        my_attack_tiles = ct.get_attackable_tiles()

        if DEBUG:
            print(f"[SENTINEL {ct.get_id()}] attack_tiles={len(my_attack_tiles)}")

        all_my_targets = _collect_targets(ct, my_attack_tiles)
        if DEBUG:
            print(f"[SENTINEL {ct.get_id()}] collected {len(all_my_targets)} targets: {[(t[2].name if hasattr(t[2],'name') else t[2], t[3].x, t[3].y) for t in all_my_targets]}")
        if not all_my_targets:
            if DEBUG:
                print(f"[SENTINEL {ct.get_id()}] EXIT: no targets in attackable tiles")
            return False

        # Tiebreakers (within same priority class):
        #   1. prefer targets farthest from enemy builder bots (deny repair)
        #   2. prefer targets closest to our builder bots (offensive)
        #   3. prefer lower-HP targets (finish them off)
        ally_bb_positions, enemy_bb_positions = _get_builder_bot_positions(ct)
        def _sort_key(t):
            pri, hp, _etype, pos = t
            ally_dist = _min_sq_dist_to_positions(pos, ally_bb_positions)
            enemy_dist = _min_sq_dist_to_positions(pos, enemy_bb_positions)
            return (pri, -enemy_dist, ally_dist, hp)

        all_my_targets.sort(key=_sort_key)
        if DEBUG:
            print(f"[SENTINEL {ct.get_id()}] FREE FIRE: trying {len(all_my_targets)} targets")
        for _, _, etype, pos in all_my_targets:
            can = ct.can_fire(pos)
            if DEBUG:
                print(f"[SENTINEL {ct.get_id()}]   try {etype} at ({pos.x},{pos.y}) can_fire={can}")
            if can:
                ct.fire(pos)
                if DEBUG:
                    print(f"[SENTINEL {ct.get_id()}] FIRED {etype} at ({pos.x},{pos.y})")
                return True

        if DEBUG:
            print(f"[SENTINEL {ct.get_id()}] EXIT: no can_fire target found")
        return False
