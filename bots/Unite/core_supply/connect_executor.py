"""Shared connect-and-path logic used by CoreConnectState and RepairBridgeState."""

from cambc import Controller, Position
from typing import Callable

from core_supply.connector import Connector
from conveyor.traverse import surround_4
from nav.common import common_path


def connect_and_approach(
    ct: Controller,
    brain,
    connector: Connector,
    source_pos: Position,
    slot_fn: Callable[[Position], list[Position]] = surround_4,
) -> bool:
    """Try to advance the bridge chain for *source_pos* by one step.

    If the chain is not yet complete, path the builder toward the current
    frontier (or toward the source itself when no frontier exists yet).

    Returns True when the source is fully connected.
    """
    connected = connector.connect(ct, source_pos, slot_fn)
    if not connected:
        frontier = connector.get_frontier(source_pos)
        target = frontier if frontier is not None else source_pos
        my_pos = ct.get_position()
        if my_pos.x != target.x or my_pos.y != target.y:
            common_path(ct, brain.map_manager, brain.pathing, target)
    return connected