"""Draw debug lines and dots using ct.draw_indicator_*. No wrapper API."""

from cambc import Controller, Position

from helpers.logging import DRAW_INDICATORS


def draw_state_target(ct: Controller, from_pos: Position, to_pos: Position, r: int = 255, g: int = 100, b: int = 100) -> None:
    """Draw line from current position to state target when DRAW_INDICATORS is True."""
    if not DRAW_INDICATORS:
        return
    ct.draw_indicator_line(from_pos, to_pos, r, g, b)


def draw_move_direction(ct: Controller, from_pos: Position, to_pos: Position, r: int = 100, g: int = 255, b: int = 100) -> None:
    """Draw line indicating chosen move direction."""
    if not DRAW_INDICATORS:
        return
    ct.draw_indicator_line(from_pos, to_pos, r, g, b)


def draw_blocked_tile(ct: Controller, pos: Position, r: int = 255, g: int = 0, b: int = 0) -> None:
    """Draw dot on blocked tile."""
    if not DRAW_INDICATORS:
        return
    ct.draw_indicator_dot(pos, r, g, b)


def draw_reservation(ct: Controller, pos: Position, r: int = 200, g: int = 200, b: int = 0) -> None:
    """Draw dot on reserved build site."""
    if not DRAW_INDICATORS:
        return
    ct.draw_indicator_dot(pos, r, g, b)
