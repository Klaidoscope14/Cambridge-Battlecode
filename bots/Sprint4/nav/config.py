"""Navigation configuration constants."""

from cambc import EntityType

# ── General ─────────────────────────────────────────────────────────────────

DEBUG = False

# Estimated CPU cost per A* node expansion.
NODE_COST = 40
# CPU cost for conveyor A* (more neighbors per node due to bridge offsets).
CONVEYOR_NODE_COST = 50
# Total CPU time available per turn.
CPU_LIMIT = 1800

# Heuristic weight for weighted A*.  W > 1 makes the search greedier,
# strongly preferring tiles closer to the target and reducing backward
# expansion.  W=1 is standard A*.  Path quality degrades but speed
# improves — a good trade-off under TLE.
H_WEIGHT = 4

# Penalty added to g-cost for tiles with no building (empty ground).
EMPTY_PENALTY = 1

# Penalty added to g-cost for tiles occupied by a bot.  Heavy enough
# that A* routes around bots when possible, but they remain passable
# so the path doesn't break when bots move.
BOT_PENALTY = 10

# Building types whose presence on the computed path triggers a re-path.
BLOCKING_BUILDING_TYPES = frozenset({
    EntityType.HARVESTER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.GUNNER,
    EntityType.LAUNCHER,
    EntityType.BARRIER,
})

# ── Bug navigation ──────────────────────────────────────────────────────────

# Number of unique positions to track for oscillation detection.
BUG_OSCILLATION_WINDOW = 30
# Minimum Chebyshev distance improvement required over the window.
BUG_OSCILLATION_THRESHOLD = 3
# Maximum turns in bug nav before giving up and returning to A*.
BUG_MAX_TURNS = 100
