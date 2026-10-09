"""Utilities for detecting broken bridge chains and tracing them back to their source."""

from cambc import Controller, EntityType, Position

from helpers.directions import CARDINAL, DIRECTIONS
from map.map_manager import MapManager
from roles.builder.helpers import in_bounds
from vision.vision_manager import VisionManager

BRIDGE_CONNECTS_TO = [
    EntityType.BRIDGE,
]

def find_broken_bridges(
    ct: Controller,
    map_manager: MapManager,
    vision_manager: VisionManager,
) -> list[tuple[Position, Position]]:
    """Return ally bridges whose output_target tile is empty (chain break).

    Only reports a break when the output_target is currently visible (avoids
    false-positives on unseen tiles whose building_grid defaults to None).

    Each result is ``(bridge_pos, empty_target_pos)``.
    """
    broken: list[tuple[Position, Position]] = []
    team = ct.get_team()
    core = map_manager.ally_core_pos
    core_set = {
        (core.x + dx, core.y + dy) for dx in range(-1, 2) for dy in range(-1, 2)
    } if core is not None else set()

    for bridge_pos, bridge in vision_manager.get_bridges(ct):
        if bridge.team != team:
            continue
        output_target = bridge.output_target

        if not in_bounds(ct, output_target):
            continue

        if not in_bounds(ct, output_target):
            continue

        if (output_target.x, output_target.y) in core_set:
            continue

        target_building = map_manager.get_building(output_target)
        if target_building is None or (
            target_building.team == team and
            target_building.entity_type not in BRIDGE_CONNECTS_TO
        ):
            broken.append((bridge_pos, output_target))

    return broken


def find_hijacked_bridges(
    ct: Controller,
    map_manager: MapManager,
    vision_manager: VisionManager,
) -> list[tuple[Position, Position]]:
    """Return ally bridges whose output_target tile is an enemy building
    """
    hijacked: list[tuple[Position, Position]] = []
    team = ct.get_team()
    core = map_manager.ally_core_pos
    core_set = {
        (core.x + dx, core.y + dy) for dx in range(-1, 2) for dy in range(-1, 2)
    } if core is not None else set()

    for bridge_pos, bridge in vision_manager.get_bridges(ct):
        if bridge.team != team:
            continue
        output_target = bridge.output_target

        if not in_bounds(ct, output_target):
            continue

        if not in_bounds(ct, output_target):
            continue

        if (output_target.x, output_target.y) in core_set:
            continue

        target_building = map_manager.get_building(output_target)
        if target_building is not None and target_building.team != ct.get_team():
            hijacked.append((bridge_pos, output_target))

    return hijacked


def trace_upstream(
    ct: Controller,
    pos: Position,
    vision_manager: VisionManager,
) -> Position | None:
    """Find a visible ally bridge whose ``output_target`` equals *pos*.

    This is the next bridge "upstream" (toward the source).
    Returns the bridge position, or None if no such bridge is visible.
    """
    team = ct.get_team()

    for bridge_pos, bridge in vision_manager.get_bridges(ct):
        if bridge.team != team:
            continue
        output_target = bridge.output_target
        if output_target.x == pos.x and output_target.y == pos.y:
            return bridge_pos

    return None


def find_adjacent_source(
    ct: Controller,
    map_manager: MapManager,
    pos: Position,
) -> Position | None:
    """Return the position of a harvester or foundry adjacent to *pos*, or None."""
    team = ct.get_team()

    for d in DIRECTIONS:
        neighbor = pos.add(d)
        if not in_bounds(ct, neighbor):
            continue
        building = map_manager.get_building(neighbor)
        if building is None:
            continue
        if building.team != team:
            continue
        if building.entity_type in (EntityType.HARVESTER, EntityType.FOUNDRY):
            return neighbor

    return None