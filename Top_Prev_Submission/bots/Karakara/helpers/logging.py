"""Single place for debug/profiling/indicator flags. No side effects on import."""

DEBUG = True
"""When True, trace() may print; optional stack traces on GameError."""

PROFILE = True
"""When True, profiling timers may record (see debug/profiling.py)."""

DRAW_INDICATORS = True
"""When True, debug/indicators.py draws lines and dots (saved to replay)."""


def trace(msg: str) -> None:
    """Optional string trace; no-op when DEBUG is False."""
    if DEBUG:
        print(msg)
