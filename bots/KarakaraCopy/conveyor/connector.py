from cambc import Controller, EntityType, Position

from conveyor.traverse import conveyor_bfs, ConveyorPlacement, placement_cost, _belt_outputs
from helpers.directions import CARDINAL
from nav.passability import passability_ally_conveyor
from roles.builder.helpers import build_conveyor, build_armoured_conveyor
from map.map_manager import MapManager


# Entity types considered "feeder belts" — these are what we look for when
# tracing which tile outputs into a given build pos.
_BELT_FEEDER_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
})


class Connector:
    def __init__(self, ct: Controller, map_manager: MapManager):
        self.ct = ct
        self.map_manager = map_manager
        self._cached_key: tuple | None = None
        self._cached_placements: list[ConveyorPlacement] | None = None

        # Most recently confirmed built position. Used to identify which tile
        # feeds into the current build pos so we can destroy it when rerouting
        # around an enemy road.
        self._last_built_pos: Position | None = None

        # True after an enemy-induced reroute. While active:
        #   - the BFS cache is bypassed so every turn re-plans from scratch
        #   - the Connector will prefer to bail on its current placement and
        #     let the new plan take any early path away from the contested tile
        # Cleared once the chain is fully connected (placement_cost == 0).
        self._avoid_enemy: bool = False

    def _get_placements(
        self,
        ct: Controller,
        sources: list[Position],
        destinations: list[Position],
    ) -> list[ConveyorPlacement] | None:
        key = (
            tuple(sorted((p.x, p.y) for p in sources)),
            tuple(sorted((p.x, p.y) for p in destinations)),
            ct.get_current_round(),
        )
        # Skip the cache while avoiding an enemy: we want the plan to react to
        # the latest observed map state every turn instead of re-using a stale
        # route that might still route through the contested area.
        if not self._avoid_enemy and key == self._cached_key:
            return self._cached_placements

        placements = conveyor_bfs(
            ct, self.map_manager, sources, destinations,
            passability_ally_conveyor,
        )
        self._cached_key = key
        self._cached_placements = placements
        return placements

    def check_connected(
        self,
        ct: Controller,
        sources: list[Position],
        destinations: list[Position],
    ) -> bool:
        placements = self._get_placements(ct, sources, destinations)
        if placements is None:
            return False
        return placement_cost(self.map_manager, placements) == 0

    # ── Enemy-reroute helpers ─────────────────────────────────────────────

    def _should_reroute(self, ct: Controller, build_pos: Position) -> bool:
        """Return True when build_pos is an enemy-owned ROAD with at least one
        enemy bot cardinally adjacent. This is the signal that the current
        build pos is contested and we should back off rather than push into it.
        """
        mm = self.map_manager
        w, h = mm.width, mm.height
        x, y = build_pos.x, build_pos.y
        if not (0 <= x < w and 0 <= y < h):
            return False

        building = mm.building_grid[x][y]
        if building is None:
            return False

        my_team = ct.get_team()
        if building.team == my_team:
            return False
        if building.entity_type != EntityType.ROAD:
            return False

        for d in CARDINAL:
            dx, dy = d.delta()
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            bot = mm.bot_grid[nx][ny]
            if bot is not None and bot.team != my_team:
                return True
        return False

    def _find_feeder_into(self, build_pos: Position) -> Position | None:
        """Locate the ally belt/bridge currently outputting INTO build_pos.

        Used as a fallback target for destruction when _last_built_pos is
        unset or already gone. Checks cardinal belts first, then scans the
        bridge-jump window for ally bridges targeting build_pos.
        """
        mm = self.map_manager
        w, h = mm.width, mm.height
        x, y = build_pos.x, build_pos.y
        my_team = self.ct.get_team()

        # Cardinal feeders: ally conveyor/splitter whose direction lands on build_pos.
        for d in CARDINAL:
            dx, dy = d.delta()
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            rec = mm.building_grid[nx][ny]
            if rec is None or rec.team != my_team:
                continue
            if rec.entity_type in _BELT_FEEDER_TYPES:
                rdx, rdy = rec.direction.delta()
                if (nx + rdx, ny + rdy) == (x, y):
                    return Position(nx, ny)

        # Bridge feeders: any ally bridge within jump range targeting build_pos.
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx == 0 and dy == 0:
                    continue
                if dx * dx + dy * dy > 9:
                    continue
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                rec = mm.building_grid[nx][ny]
                if rec is None or rec.team != my_team:
                    continue
                if rec.entity_type == EntityType.BRIDGE:
                    tgt = getattr(rec, 'output_target', None)
                    if tgt is not None and tgt.x == x and tgt.y == y:
                        return Position(nx, ny)
        return None

    def _trigger_reroute(self, ct: Controller, build_pos: Position) -> None:
        """Destroy the feeder tile leading into build_pos and flip the Connector
        into avoid-enemy mode so the next call computes a fresh path that will
        naturally grab any early connection away from the contested area.
        """
        mm = self.map_manager

        print(f"[Connector] ENEMY DETECTED at build_pos {build_pos} — rerouting")

        target = self._last_built_pos
        source_label = "last_built_pos"
        # Only trust the tracked last pos if a building still exists there.
        if target is None or mm.get_building(target) is None:
            target = self._find_feeder_into(build_pos)
            source_label = "feeder_into"

        if target is not None and ct.can_destroy(target):
            ct.destroy(target)
            print(f"[Connector] DESTROYED old build pos {target} ({source_label})")
            # Drop a road on the freshly cleared tile so the bot still has a
            # traversable surface while the new path is being planned. Without
            # this the tile is left bare — bots have to pay the road cost to
            # cross it again, and allies lose the shared walkway.
            if ct.can_build_road(target):
                ct.build_road(target)
                print(f"[Connector] ROAD placed on {target}")
        else:
            print(f"[Connector] no destroy target available (target={target})")

        self._last_built_pos = None
        # Invalidate the BFS cache so the next _get_placements call runs fresh.
        self._cached_key = None
        self._cached_placements = None
        self._avoid_enemy = True

    # ── Main entry ────────────────────────────────────────────────────────

    def connect(
        self,
        ct: Controller,
        sources: list[Position],
        destinations: list[Position],
        armoured: bool,
    ) -> bool:
        placements = self._get_placements(ct, sources, destinations)
        if placements is None:
            return False

        if placement_cost(self.map_manager, placements) == 0:
            # The chain is fully connected — reroute is over, resume normal cache.
            self._avoid_enemy = False
            return True

        for placement in placements:
            record = self.map_manager.get_building(placement.pos)
            if _belt_outputs(record, placement.direction):
                continue

            # Enemy-reroute check: if the next tile we were about to build on
            # is an enemy road with an enemy bot adjacent, abandon this
            # placement, destroy the feeder behind us, and force a fresh plan.
            if self._should_reroute(ct, placement.pos):
                self._trigger_reroute(ct, placement.pos)
                return True

            if record is not None and ct.can_destroy(placement.pos):
                ct.destroy(placement.pos)

            if armoured:
                built = build_armoured_conveyor(ct, placement.pos, placement.direction)
            else:
                built = build_conveyor(ct, placement.pos, placement.direction)

            if built:
                # Record the tile we just built on so a future reroute knows
                # which tile feeds into the next build pos.
                self._last_built_pos = placement.pos
            break

        return True
