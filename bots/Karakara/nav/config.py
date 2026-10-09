"""Navigation configuration constants."""

# ── General ─────────────────────────────────────────────────────────────────

DEBUG = False

# Estimated CPU cost per A* node expansion.
NODE_COST = 30
# Total CPU time available per turn for pathing work.
CPU_LIMIT = 1800

# Heuristic weight for weighted A*. W=1 is standard (optimal) A*.
H_WEIGHT = 4

# When the per-turn expansion budget falls at or below this many nodes
# AND the bot doesn't already have _g, we skip waiting for A* and fall
# back to Bug2. With a tiny budget, expansion can't catch up to the
# bot in any reasonable number of turns, so Bug2's local navigation
# is more useful than waiting.
TINY_BUDGET_THRESHOLD = 5

# Penalty added to g-cost for tiles with no building (empty ground).
# Encourages routing through built infrastructure when alternatives
# are similar length.
EMPTY_PENALTY = 3

# Penalty added to g-cost for tiles currently occupied by another
# builder bot. The chain still routes through bot tiles when it has
# to (bots are transient — they'll move soon), but biases toward
# unoccupied alternatives when one exists. Doesn't refuse the tile,
# just prefers detours.
BOT_PENALTY = 5
