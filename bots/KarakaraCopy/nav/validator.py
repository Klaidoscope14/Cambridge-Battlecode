from cambc import Position, Direction

from map.map_manager import MapManager
from helpers.geometry import on_map

from helpers.directions import DIRECTIONS, CARDINAL

from typing import Callable

_DIR_DELTAS: dict[Direction, tuple[int, int]] = {d: d.delta() for d in DIRECTIONS}
_DIR_DELTAS[Direction.CENTRE] = (0, 0)

# ── BFS flood on the local vision grid ──────────────────────────────────────
CARINDAL_ITERS = 4
ALL_DIRECTIONS_ITERS = 3

TIME_REQUIRED = 400


def validator_on_direction(
    ct,
    map_manager: MapManager,
    my_pos: Position,
    bug_pos: Position,
    passability_function: Callable[[Position], bool],
    cardinal = False,
) -> dict[Direction, int]:
    # The positions we care about: the neighbours of my_pos + my_pos itself.
    max_iters = CARINDAL_ITERS if cardinal else ALL_DIRECTIONS_ITERS
    dirs = CARDINAL if cardinal else DIRECTIONS
    dirs_with_centre = dirs + [Direction.CENTRE]

    result: dict[Direction, int] = {d: 100000 for d in dirs_with_centre}
    
    time_available = 2000 - ct.get_cpu_time_elapsed()
    if time_available < 400:
        return result

    map_w = map_manager.width
    map_h = map_manager.height

    neighbor_positions: dict[Direction, Position] = {}
    for d in dirs_with_centre:
        p = my_pos.add(d)
        if on_map(p, map_w, map_h):
            neighbor_positions[d] = p

    # BFS state
    visited: set[tuple[int, int]] = set()

    start = (bug_pos.x, bug_pos.y)
    visited.add(start)
    frontier: list[tuple[int, int]] = [start]


    # Check if the start itself is one of the target neighbors
    for d, p in neighbor_positions.items():
        if (p.x, p.y) == start:
            result[d] = 0

    for iteration in range(1, max_iters + 1):
        next_frontier: list[tuple[int, int]] = []
        for (cx, cy) in frontier:
            for dd in dirs:
                dx, dy = _DIR_DELTAS[dd]
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in visited:
                    continue
                npos = Position(nx, ny)
                # Removing wall checks and vision checks here hurt speed?
                # BFS is now doing 20 real iterations
                if not passability_function(ct, npos, map_manager):
                    continue
                visited.add((nx, ny))
                next_frontier.append((nx, ny))

                # Check if this newly reached cell is one of the neighbor positions
                for d, p in neighbor_positions.items():
                    if p.x == nx and p.y == ny and iteration < result[d]:
                        result[d] = iteration

        frontier = next_frontier
        if not frontier:
            break

        # Early exit: if all neighbor positions have been reached
        if all(result[d] < 100000 for d in neighbor_positions):
            break

    return result
