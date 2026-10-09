from collections import deque
from cambc import Position


CARDINAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def bfs(ct, source: Position, passability_function, map_manager, cardinal: bool = True) -> list[list[int]]:
    width = map_manager.width
    height = map_manager.height
    dirs = CARDINAL if cardinal else DIRECTIONS

    dist = [[-1 for _ in range(width)] for _ in range(height)]
    dist[source.x][source.y] = 0

    queue = deque()
    queue.append(source)

    while queue:
        pos = queue.popleft()
        d = dist[pos.x][pos.y]

        for dx, dy in dirs:
            nx, ny = pos.x + dx, pos.y + dy
            if 0 <= nx < height and 0 <= ny < width and dist[nx][ny] == -1:
                npos = Position(nx, ny)
                if passability_function(ct, npos, map_manager):
                    dist[nx][ny] = d + 1
                    queue.append(npos)

    return dist


def trace_path(dist: list[list[int]], pos: Position, cardinal: bool = True) -> list[Position] | None:
    """Returns the full path from pos back to the source (distance 0), or None if unreachable."""
    if dist[pos.x][pos.y] == -1:
        return None

    height = len(dist)
    width = len(dist[0])
    dirs = CARDINAL if cardinal else DIRECTIONS

    path = [pos]
    while dist[pos.x][pos.y] != 0:
        d = dist[pos.x][pos.y]
        for dx, dy in dirs:
            nx, ny = pos.x + dx, pos.y + dy
            if 0 <= nx < height and 0 <= ny < width and dist[nx][ny] == d - 1:
                pos = Position(nx, ny)
                path.append(pos)
                break

    return path


def next_step(dist: list[list[int]], pos: Position, cardinal: bool = True) -> Position | None:
    """Returns the next position to move toward the source, or None if unreachable or already at source."""
    if dist[pos.x][pos.y] <= 0:
        return None

    height = len(dist)
    width = len(dist[0])
    dirs = CARDINAL if cardinal else DIRECTIONS

    d = dist[pos.x][pos.y]
    for dx, dy in dirs:
        nx, ny = pos.x + dx, pos.y + dy
        if 0 <= nx < height and 0 <= ny < width and dist[nx][ny] == d - 1:
            return Position(nx, ny)

    return None