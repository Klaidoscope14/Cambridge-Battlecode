"""Dispatchers from cambc ``EntityType`` to the matching Controller calls.

The ring pipeline is parameterised by two EntityType values — ``center``
(what sits on the target tile: HARVESTER, FOUNDRY, …) and ``ring`` (what
fills the 4 cardinal slots: CONVEYOR, ARMOURED_CONVEYOR, BARRIER). Every
``ct.build_X`` / ``ct.can_build_X`` / ``ct.get_X_cost`` call in the pipeline
goes through one of the functions below so that swapping a kind is a single
kwarg change at the callsite.
"""

from cambc import Controller, Direction, EntityType, Position


# ── Ring (4 cardinal slots around the target) ───────────────────────

def ring_cost(ct: Controller, kind: EntityType) -> int:
    if kind == EntityType.CONVEYOR:
        return ct.get_conveyor_cost()[0]
    if kind == EntityType.ARMOURED_CONVEYOR:
        return ct.get_armoured_conveyor_cost()[0]
    if kind == EntityType.BARRIER:
        return ct.get_barrier_cost()[0]
    raise ValueError(f"Unsupported ring kind: {kind}")


def can_place_ring(ct: Controller, pos: Position, facing: Direction, kind: EntityType) -> bool:
    if kind == EntityType.CONVEYOR:
        return ct.can_build_conveyor(pos, facing)
    if kind == EntityType.ARMOURED_CONVEYOR:
        return ct.can_build_armoured_conveyor(pos, facing)
    if kind == EntityType.BARRIER:
        return ct.can_build_barrier(pos)
    raise ValueError(f"Unsupported ring kind: {kind}")


def place_ring(ct: Controller, pos: Position, facing: Direction, kind: EntityType) -> None:
    if kind == EntityType.CONVEYOR:
        ct.build_conveyor(pos, facing)
        return
    if kind == EntityType.ARMOURED_CONVEYOR:
        ct.build_armoured_conveyor(pos, facing)
        return
    if kind == EntityType.BARRIER:
        ct.build_barrier(pos)
        return
    raise ValueError(f"Unsupported ring kind: {kind}")


def is_ring_entry(entry, kind: EntityType) -> bool:
    """True when a building_grid entry already matches the requested ring kind."""
    return entry is not None and entry.entity_type == kind


# ── Center (the target tile itself) ─────────────────────────────────

def center_cost(ct: Controller, kind: EntityType) -> int:
    if kind == EntityType.HARVESTER:
        return ct.get_harvester_cost()[0]
    if kind == EntityType.FOUNDRY:
        return ct.get_foundry_cost()[0]
    raise ValueError(f"Unsupported center kind: {kind}")


def can_build_center(ct: Controller, pos: Position, kind: EntityType) -> bool:
    if kind == EntityType.HARVESTER:
        return ct.can_build_harvester(pos)
    if kind == EntityType.FOUNDRY:
        return ct.can_build_foundry(pos)
    raise ValueError(f"Unsupported center kind: {kind}")


def build_center(ct: Controller, pos: Position, kind: EntityType) -> None:
    if kind == EntityType.HARVESTER:
        ct.build_harvester(pos)
        return
    if kind == EntityType.FOUNDRY:
        ct.build_foundry(pos)
        return
    raise ValueError(f"Unsupported center kind: {kind}")
