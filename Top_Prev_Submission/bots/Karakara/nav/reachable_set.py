"""Persistent reachable-tile tracker.

Owns the set of tiles confirmed reachable under the lightweight
is_reachable check, plus the BFS bookkeeping used to grow that set
across turns.  Decoupled from path search itself — the Pathing class
contributes new tiles during A* expansion, and any other module can
read membership through the set-like API.

State:
  tiles    — every (x, y) ever confirmed reachable
  frontier — subset of tiles with at least one in-bounds non-reachable
             neighbor.  Used to seed idle_expand without scanning
             the full reachable set; pruned lazily.

Persistent BFS state for idle_expand survives across turns: the queue
is grown only when newly_seen fires (or once at startup), the head
advances as tiles are processed, and the queue is compacted lazily.
"""
from __future__ import annotations

from map.map_manager import MapManager
from vision.launcher_tracker import LauncherTracker

from nav.config import DEBUG, NODE_COST
from nav.pass_context import PassContext
from nav.reachability import is_reachable


_DELTAS: list[tuple[int, int]] = [
    (dx, dy)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    if not (dx == 0 and dy == 0)
]


class ReachableSet:
    def __init__(self, launcher_tracker: LauncherTracker) -> None:
        self.launcher_tracker: LauncherTracker = launcher_tracker
        self.tiles: set[tuple[int, int]] = set()
        self.frontier: set[tuple[int, int]] = set()

        # Persistent BFS state for idle_expand.
        self._idle_queue: list = []
        self._idle_head: int = 0
        self._idle_seeded: bool = False

    # ── Set-like passthrough so callsites can treat the wrapper as a set ──

    def __contains__(self, key) -> bool:
        return key in self.tiles

    def __iter__(self):
        return iter(self.tiles)

    def __len__(self) -> int:
        return len(self.tiles)

    # ── Local seeding ────────────────────────────────────────────────────

    def update(self, ct, mm: MapManager) -> None:
        """Seed the 3x3 around the bot into the reachable set.

        Uses the lightweight reachability check (terrain + walkable
        building) rather than full passability — resource-gated tiles
        still belong in the reachable set; path_to re-verifies under
        full rules before stepping onto them.
        """
        ctx = PassContext(ct, mm, self.launcher_tracker)
        w, h = mm.width, mm.height
        mx, my = ctx.my_x, ctx.my_y
        before = len(self.tiles)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = mx + dx, my + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if is_reachable(ctx, nx, ny):
                        self.tiles.add((nx, ny))
                        self.frontier.add((nx, ny))
        DEBUG and print(f"[REACH] update: +{len(self.tiles) - before} tiles "
                        f"(total={len(self.tiles)}, frontier={len(self.frontier)})")

    # ── Idle expansion ──────────────────────────────────────────────────

    def idle_expand(self, ct, mm: MapManager) -> None:
        """Flood-fill the reachable set into seen passable tiles.

        BFS outward from the persistent _idle_queue (seeded from
        frontier tiles adjacent to newly-seen terrain) through tiles
        that pass the lightweight is_reachable check, adding them to
        the reachable set.

        Uses is_reachable instead of the full path_to pass_fn — path-
        time state (resources, launcher zones, target) is irrelevant
        for reachability, and skipping those checks makes each node
        cheaper.  path_to re-verifies under full rules before moving.
        """
        IDLE_CPU_LIMIT = 2000
        if not self.frontier:
            return
        if ct.get_cpu_time_elapsed() >= IDLE_CPU_LIMIT:
            return

        ctx = PassContext(ct, mm, self.launcher_tracker)
        w, h = mm.width, mm.height
        tile_grid = mm.tile_grid
        tiles = self.tiles
        frontier = self.frontier
        queue = self._idle_queue

        # One-shot initial seed: on the very first call, the persistent
        # queue is empty but the frontier already has tiles — dump them
        # all in once.  Subsequent calls rely on newly_seen to add work.
        if not self._idle_seeded:
            queue.extend(frontier)
            self._idle_seeded = True

        # Incremental seed: only frontier tiles adjacent to newly-seen
        # terrain can possibly make progress this turn.  Stalled frontier
        # tiles (all non-reachable neighbors still unseen) are skipped
        # entirely until vision reveals something new.
        newly_seen = mm.newly_seen
        if newly_seen:
            to_enqueue: set = set()
            for sx, sy in newly_seen:
                for dx, dy in _DELTAS:
                    nx, ny = sx + dx, sy + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    nb = (nx, ny)
                    if nb in frontier:
                        to_enqueue.add(nb)
            if to_enqueue:
                queue.extend(to_enqueue)

        # Compute budget *after* seeding work so preprocessing doesn't
        # eat into the BFS expansion allowance.
        budget = max(0, (IDLE_CPU_LIMIT - ct.get_cpu_time_elapsed()) // NODE_COST)

        head = self._idle_head
        retire: list = []
        reach_added = 0
        while head < len(queue) and budget > 0:
            cx, cy = queue[head]
            head += 1
            # Skip tiles already retired in a prior turn.
            if (cx, cy) not in frontier:
                continue
            budget -= 1
            has_open_neighbor = False
            for dx, dy in _DELTAS:
                nx, ny = cx + dx, cy + dy
                nb = (nx, ny)
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if nb in tiles:
                    continue
                has_open_neighbor = True
                if tile_grid[nx][ny] is None:
                    continue
                if not is_reachable(ctx, nx, ny):
                    continue
                tiles.add(nb)
                frontier.add(nb)
                queue.append(nb)
                reach_added += 1
            if not has_open_neighbor:
                retire.append((cx, cy))

        for k in retire:
            frontier.discard(k)

        DEBUG and print(f"[REACH] idle_expand: +{reach_added} tiles, retired={len(retire)} "
                        f"(total={len(tiles)}, frontier={len(frontier)}, "
                        f"queue={len(queue) - head})")

        # Compact queue: drop drained prefix.  Fully drained → clear;
        # otherwise slice off the head once it grows large enough that
        # the skip cost outweighs the copy.
        if head >= len(queue):
            queue.clear()
            self._idle_head = 0
        elif head > 512:
            del queue[:head]
            self._idle_head = 0
        else:
            self._idle_head = head
