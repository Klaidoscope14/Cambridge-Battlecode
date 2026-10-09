"""Lightweight timers/scopes for development. Stub when PROFILE is False."""

from helpers.logging import PROFILE, trace
from functools import wraps

# TODO: implement timer scope that records elapsed time when PROFILE is True.
# Use ct.get_cpu_time_elapsed() at start/end of scope.


def profile_scope(ct, name: str):
    """Context manager for profiling a block. Stub: no-op."""
    class _Scope:
        def __enter__(self):
            if PROFILE:
                self.start = ct.get_cpu_time_elapsed()
            return self
        def __exit__(self, *args):
            if PROFILE:
                elapsed = ct.get_cpu_time_elapsed() - self.start
                trace(f"DEBUG: {name} took {elapsed}s")
    return _Scope()

def cputimer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        ct = args[1]
        start = ct.get_cpu_time_elapsed()
        result = func(*args, **kwargs)
        elapsed = ct.get_cpu_time_elapsed() - start
        print(f"{func.__name__} took {elapsed}s")
        return result
    return wrapper

def cputimer0(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        ct = args[0]
        start = ct.get_cpu_time_elapsed()
        result = func(*args, **kwargs)
        elapsed = ct.get_cpu_time_elapsed() - start
        print(f"{func.__name__} took {elapsed}s")
        return result
    return wrapper
