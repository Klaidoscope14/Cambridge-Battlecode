"""Resource gates: when can we afford / should we prioritise different harvesters."""

from collections import deque

from cambc import Controller, Position
from harvesters.constants import (
    AXIONITE_MIN_ROUND,
    AXIONITE_RESOURCE_MULTIPLIER,
    TITANIUM_MIN_RATE
)


# ──────────────────────────────────────────────────────────────────────────────
# Rolling-window titanium tracking (module-level state).
#
# Each Python bot process has its own module namespace, so these globals act as
# a per-bot persistent singleton. _sample_titanium() is guarded by
# _titanium_last_round so callers can invoke it freely across the turn without
# double-counting. This lives here (not in StorageTracker) so resource gates
# like can_build_axionite() are self-contained and don't need any external
# tracker passed in.
# ──────────────────────────────────────────────────────────────────────────────

# Window length (in rounds) for the rolling-average titanium total. 15 is the
# middle of the 10–20 range — long enough to smooth single-round spikes, short
# enough to react to sustained changes.
TITANIUM_AVG_WINDOW = 15

# Window length (in rounds) for the rolling-average titanium income per round.
# Kept separate from TITANIUM_AVG_WINDOW so the two can be tuned independently —
# income is noisier (bursts when harvesters cycle) so you may want a longer
# window here.
TITANIUM_INCOME_WINDOW = 15

# Stockpile (raw total) window + running sum.
_titanium_window: "deque[int]" = deque(maxlen=TITANIUM_AVG_WINDOW)
_titanium_sum: int = 0

# Per-round income delta window + running sum. Each entry is
# (this_round_total - last_round_total).
_titanium_income_window: "deque[int]" = deque(maxlen=TITANIUM_INCOME_WINDOW)
_titanium_income_sum: int = 0

# Previous round's total — needed to compute the per-round delta. None until
# the first sample is taken.
_titanium_prev_total: "int | None" = None

# Guards against double-counting inside a single round.
_titanium_last_round: "int | None" = None


def _sample_titanium(ct: Controller) -> None:
    """Push the current round's global titanium total onto the rolling
    windows. Guarded against double-counting: repeat calls within the same
    round are no-ops, so anywhere in resources.py can call this before reading
    the averages.
    """
    global _titanium_sum, _titanium_income_sum
    global _titanium_prev_total, _titanium_last_round

    current_round = ct.get_current_round()
    if _titanium_last_round == current_round:
        return
    _titanium_last_round = current_round

    titanium = ct.get_global_resources()[0]
    # Stockpile window: evict the oldest sample from the running sum just
    # before the deque evicts it on append.
    if len(_titanium_window) == TITANIUM_AVG_WINDOW:
        _titanium_sum -= _titanium_window[0]
    _titanium_window.append(titanium)
    _titanium_sum += titanium

    # Income delta: current - previous. On the very first sample we have no
    # previous value yet, so we only seed prev_total and skip. Every later
    # sample pushes a delta onto the income window.
    if _titanium_prev_total is not None:
        delta = titanium - _titanium_prev_total
        if len(_titanium_income_window) == TITANIUM_INCOME_WINDOW:
            _titanium_income_sum -= _titanium_income_window[0]
        _titanium_income_window.append(delta)
        _titanium_income_sum += delta
    _titanium_prev_total = titanium


def get_average_titanium(ct: Controller) -> float:
    """Rolling-average global titanium total over the last ``TITANIUM_AVG_WINDOW``
    rounds. Samples lazily — returns 0.0 before any samples exist.
    """
    _sample_titanium(ct)
    if not _titanium_window:
        return 0.0
    return _titanium_sum / len(_titanium_window)


def get_average_titanium_income(ct: Controller) -> float:
    """Rolling-average NET titanium income per round over the last
    ``TITANIUM_INCOME_WINDOW`` rounds — (titanium gained - titanium spent):

      - Positive when harvesters outpace our spending.
      - Negative when we're draining the stockpile faster than we mine.
      - Matches "harvesters × rate" in steady state only when nothing is
        being spent (e.g. 3 harvesters @ 10/4 rounds → 7.5/round).

    Samples lazily. Returns 0.0 before two rounds' worth of samples have been
    taken — we need at least one delta to produce a number.
    """
    _sample_titanium(ct)
    if not _titanium_income_window:
        return 0.0
    return _titanium_income_sum / len(_titanium_income_window)


def can_build_axionite(ct: Controller) -> bool:
    """True when economy supports prioritising axionite over titanium harvesters.

    Gates on both the rolling average of titanium income (>= TITANIUM_MIN_RATE)
    and round number (>= AXIONITE_MIN_ROUND) so we don't starve the early
    titanium pipeline.
    """

    # if ct.get_global_resources()[0] < ct.get_harvester_cost()[0] * AXIONITE_RESOURCE_MULTIPLIER:
    #     return False
    if get_average_titanium_income(ct) < TITANIUM_MIN_RATE:
        return False
    if ct.get_current_round() < AXIONITE_MIN_ROUND:
        return False
    return True


def required_titanium(ct: Controller, mm, target: Position) -> float | None:
    """Estimate titanium needed to build harvester + connect it to the belt.

    Returns None when there's no nearby ally belt; caller must decide whether
    to wait for a comfortable buffer.
    """
    target_x = target.x
    target_y = target.y

    harvester_cost = ct.get_harvester_cost()[0]
    conveyor_cost = ct.get_conveyor_cost()[0]

    # Early game: don't assume we can hop onto an existing belt — price the
    # run all the way back to the core.
    if ct.get_current_round() < 40:
        core = mm.ally_core_pos
        return harvester_cost + max(abs(target_x - core.x), abs(target_y - core.y)) * ct.get_conveyor_cost()[0]

    return harvester_cost + 4 * conveyor_cost


def can_afford_build(ct: Controller, mm, target: Position) -> bool:
    """True when titanium covers harvester + belt connection.

    Uses ``required_titanium`` when a belt is in vision; otherwise demands a
    comfortable 2.5x harvester-cost buffer before committing.
    """
    titanium = ct.get_global_resources()[0]
    required = required_titanium(ct, mm, target)
    if required is None:
        return titanium >= 2.5 * ct.get_harvester_cost()[0]
    return titanium >= required
