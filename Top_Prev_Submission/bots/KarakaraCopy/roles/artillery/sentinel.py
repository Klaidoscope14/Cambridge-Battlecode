from cambc import Controller, EntityType, GameConstants, Position, Direction
from map.map_manager import MapManager
from helpers.geometry import on_map
from helpers.directions import CARDINAL
from roles.artillery.ammo_starvation import AmmoStarvationTracker

# # of sentinels paired together
MIN_SENTINELS_FOR_SYNC = 2

# Entity types worth coordinating burst fire on.
SYNC_WORTHY_TYPES = {
    EntityType.BUILDER_BOT,
    # EntityType.SENTINEL,
    # EntityType.GUNNER,
    # EntityType.BREACH,
    # EntityType.LAUNCHER,
}

# ── Priority order: lower index = shoot first ─────────────────────

TARGET_PRIORITY = [
    EntityType.LAUNCHER,
    EntityType.HARVESTER,   # unconnected enemy harvesters only
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
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

def _get_ally_sentinels(ct) -> list[int]:
    """Return IDs of allied sentinels visible to this unit (excluding self)."""
    my_id = ct.get_id()
    team = ct.get_team()
    sentinels = []
    for eid in ct.get_nearby_units():
        if eid == my_id:
            continue
        if ct.get_team(eid) != team:
            continue
        if ct.get_entity_type(eid) == EntityType.SENTINEL:
            sentinels.append(eid)
    return sentinels


def _get_attackable_set(ct, sentinel_id: int) -> set[tuple[int, int]]:
    """Get the raw attackable tile set for another sentinel by ID."""
    pos = ct.get_position(sentinel_id)
    direction = ct.get_direction(sentinel_id)
    tiles = ct.get_attackable_tiles_from(pos, direction, EntityType.SENTINEL)
    return {(t.x, t.y) for t in tiles}

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
            continue

        etype = ct.get_entity_type(tbid)
        if etype == EntityType.ROAD:
            if _is_road_near_harvester(ct, pos, team):
                pri = _PRIORITY_INDEX.get(EntityType.ROAD)
                hp = ct.get_hp(tbid)
                targets.append((pri, hp, EntityType.ROAD, pos))
            continue  # not near enemy harvester — skip

        if etype == EntityType.HARVESTER:
            if ct.get_team(tbid) == team:
                continue  # ally harvester, never shoot
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
        if self._ammo_tracker.maybe_self_destruct(ct):
            return
        self.shoot(ct)

    def shoot(self, ct) -> bool:
        current_round = ct.get_current_round()
        is_sync_round = current_round % 2 == 0

        # ── 1. My own attackable tiles & targets ───────────────────
        my_attack_tiles = ct.get_attackable_tiles()
        my_attack_set = {(t.x, t.y) for t in my_attack_tiles}

        all_my_targets = _collect_targets(ct, my_attack_tiles)
        if not all_my_targets: # exit because we have no target
            return False

        # ── 2. Find allied sentinels and compute intersection ──────
        ally_sentinel_ids = _get_ally_sentinels(ct)

        # Build the intersection: tiles that I AND at least
        # (MIN_SENTINELS_FOR_SYNC - 1) allies can all attack.
        # We count per-tile how many sentinels (including me) cover it.
        if ally_sentinel_ids:
            tile_coverage: dict[tuple[int, int], int] = {}
            # Start with my tiles, each covered by 1 (me)
            for t in my_attack_set:
                tile_coverage[t] = 1

            for sid in ally_sentinel_ids:
                ally_tiles = _get_attackable_set(ct, sid)
                for t in ally_tiles:
                    if t in tile_coverage:
                        tile_coverage[t] += 1

            # Intersection = tiles with enough coverage
            intersection_set = {
                t for t, count in tile_coverage.items()
                if count >= MIN_SENTINELS_FOR_SYNC
            }
        else:
            intersection_set = set()

        # ── 3. Find sync-worthy targets in the intersection ────────
        sync_target = None
        if intersection_set:
            intersection_positions = [Position(x, y) for x, y in intersection_set]
            sync_candidates = _collect_targets(ct, intersection_positions)

            # Filter to only sync-worthy entity types
            sync_candidates = [
                c for c in sync_candidates if c[2] in SYNC_WORTHY_TYPES
            ]

            if sync_candidates:
                sync_candidates.sort(key=lambda t: (t[0], t[1]))
                sync_target = sync_candidates[0]  # (pri, hp, etype, pos)


        # this is just debugging so ignore
        if sync_target is not None:
            my_pos = ct.get_position()
            # Red dot = the target we're bursting
            ct.draw_indicator_dot(sync_target[3], 255, 0, 0)
            # Green lines to each ally that shares the sync target
            target_key = (sync_target[3].x, sync_target[3].y)
            for sid in ally_sentinel_ids:
                ally_tiles = _get_attackable_set(ct, sid)
                if target_key in ally_tiles:
                    ct.draw_indicator_line(my_pos, ct.get_position(sid), 0, 255, 0)

        # ── 4. Decide whether to sync or fire freely ───────────────
        if sync_target is not None:
            # We have a sync-worthy target in the intersection.
            # Only fire on sync rounds.
            if is_sync_round:
                pos = sync_target[3]
                if ct.can_fire(pos):
                    ct.fire(pos)
                    return True
            else:
                # off round
                if ct.get_ammo_amount() >= GameConstants.SENTINEL_AMMO_COST:
                    return False

        # ── 5. Free fire: best target from my own tiles ────────────
        all_my_targets.sort(key=lambda t: (t[0], t[1]))
        for _, _, _, pos in all_my_targets:
            if ct.can_fire(pos):
                ct.fire(pos)
                return True

        return False
