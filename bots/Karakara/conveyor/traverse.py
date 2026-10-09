from collections import deque
from dataclasses import dataclass
from cambc import Position, EntityType, Direction

from map.schema import ConveyorRecord
from debug.indicators import draw_blocked_tile

from helpers.directions import DIRECTIONS, CARDINAL as _CARDINAL_DIRS, OFFSET_TO_DIRECTION

CARDINAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
MAX_BFS_ITERS = 30

BELT_TYPES = {EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR}

SPLITTER_OUTPUTS = {
    Direction.NORTH: {Direction.NORTH, Direction.EAST, Direction.WEST},
    Direction.SOUTH: {Direction.SOUTH, Direction.EAST, Direction.WEST},
    Direction.EAST:  {Direction.EAST, Direction.NORTH, Direction.SOUTH},
    Direction.WEST:  {Direction.WEST, Direction.NORTH, Direction.SOUTH},
}


@dataclass(frozen=True)
class ConveyorPlacement:
    pos: Position
    direction: Direction


def _is_belt(record) -> bool:
    return record is not None and record.entity_type in BELT_TYPES


def _belt_outputs(record, direction_needed: Direction) -> bool:
    if not _is_belt(record):
        return False
    if record.entity_type == EntityType.SPLITTER:
        return direction_needed in SPLITTER_OUTPUTS.get(record.direction, set())
    return record.direction == direction_needed


def conveyor_bfs(
    ct,
    map_manager,
    sources: list[Position],
    ends: list[Position],
    passability_function
) -> list[ConveyorPlacement] | None:
    height = map_manager.height
    width = map_manager.width

    end_set = {(e.x, e.y) for e in ends}

    dist = [[-1 for _ in range(width)] for _ in range(height)]
    prev = [[None for _ in range(width)] for _ in range(height)]

    dq = deque()
    for src in sources:
        if 0 <= src.x < height and 0 <= src.y < width:
            if passability_function(ct, src, map_manager):
                dist[src.x][src.y] = 0
                dq.append(src)

    reached_end = None

    iters = 0
    while dq:
        if iters >= MAX_BFS_ITERS:
            return None
        iters += 1

        pos = dq.popleft()
        d = dist[pos.x][pos.y]

        if (pos.x, pos.y) in end_set:
            reached_end = pos
            break

        for dx, dy in CARDINAL:
            nx, ny = pos.x + dx, pos.y + dy
            if not (0 <= nx < height and 0 <= ny < width):
                continue

            npos = Position(nx, ny)
            is_end = (nx, ny) in end_set

            if not is_end and not passability_function(ct, npos, map_manager):
                continue

            draw_blocked_tile(ct, npos, 255, 255, 0)

            dest_record = map_manager.get_building(npos)
            if dest_record is not None and not _is_belt(dest_record):
                if not is_end:
                    continue

            direction_needed = OFFSET_TO_DIRECTION[(dx, dy)]
            src_record = map_manager.get_building(pos)

            cost = 0 if _belt_outputs(src_record, direction_needed) else 1

            new_dist = d + cost
            if dist[nx][ny] == -1 or new_dist < dist[nx][ny]:
                dist[nx][ny] = new_dist
                prev[nx][ny] = pos
                if cost == 0:
                    dq.appendleft(npos)
                else:
                    dq.append(npos)

    if reached_end is None:
        return None

    positions = []
    cur = reached_end
    while cur is not None:
        positions.append(cur)
        cur = prev[cur.x][cur.y]
    positions.reverse()

    placements = []
    for i in range(len(positions) - 1):
        pos = positions[i]
        nxt = positions[i + 1]
        dx, dy = nxt.x - pos.x, nxt.y - pos.y
        direction = OFFSET_TO_DIRECTION[(dx, dy)]
        placements.append(ConveyorPlacement(pos=pos, direction=direction))

    return placements

def placement_cost(map_manager, placements: list[ConveyorPlacement]) -> int:
    count = 0
    for p in placements:
        record = map_manager.get_building(p.pos)
        if not _belt_outputs(record, p.direction):
            count += 1
    return count

def surround_4(pos: Position):
    return [pos.add(d) for d in _CARDINAL_DIRS]

def surround_9(pos: Position):
    return [pos.add(d) for d in DIRECTIONS]

def surround_12(pos: Position) -> list[Position]:
    cx, cy = pos.x, pos.y
    return [
        # Top row (y - 2)
        Position(cx - 1, cy - 2),
        Position(cx,     cy - 2),
        Position(cx + 1, cy - 2),
        # Bottom row (y + 2)
        Position(cx - 1, cy + 2),
        Position(cx,     cy + 2),
        Position(cx + 1, cy + 2),
        # Left column (x - 2)
        Position(cx - 2, cy - 1),
        Position(cx - 2, cy),
        Position(cx - 2, cy + 1),
        # Right column (x + 2)
        Position(cx + 2, cy - 1),
        Position(cx + 2, cy),
        Position(cx + 2, cy + 1),
    ]