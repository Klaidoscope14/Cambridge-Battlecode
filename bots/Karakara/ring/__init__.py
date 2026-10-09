"""Generic route→sabotage→ring→center build pipeline.

Callers pick a target, track ``_phase`` across turns, and invoke
``ring_build(state, ct, center=..., ring=...)`` to advance the pipeline one
tick. The ``center`` and ``ring`` kwargs are cambc ``EntityType`` values —
see ``ring.actions`` for the dispatch table.
"""

from ring.pipeline import ring_build

__all__ = ["ring_build"]
