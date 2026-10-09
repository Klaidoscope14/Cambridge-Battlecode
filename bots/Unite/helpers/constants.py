"""Bot constants. Re-exports GameConstants when available; add bot-specific constants here."""

from cambc import GameConstants
MAX_TURNS = GameConstants.MAX_TURNS
BUILDER_VISION_RADIUS_SQ = getattr(GameConstants, "BUILDER_BOT_VISION_RADIUS_SQ", 20)
CORE_VISION_RADIUS_SQ = getattr(GameConstants, "CORE_VISION_RADIUS_SQ", 36)
ACTION_RADIUS_SQ = getattr(GameConstants, "ACTION_RADIUS_SQ", 2)

# Opening / strategy constants (extend as needed).
MAX_BUILDERS_OPENING = 6
"""Max builder bots to spawn in the opening phase."""

EARLY_GAME_ROUNDS = 200
"""Rounds considered early game for economy vs defense posture."""

# encoding for a marker so other bots know its for someone suiciding
SUICIDE_POS_CONSTANT = 9

BREACH = 1
GUNNER = 2
SENTINEL = 3
LAUNCHER = 4


REPAIR_MARKER_COOLDOWN = 30
"""Rounds before another bot can take over a stale bridge repair attempt."""

BRIDGE_WORK_STALENESS = 1
"""Rounds before a bridge-work marker is considered stale.  Markers are
placed once per bridge build (not refreshed), so this must cover the
travel + build time to the next bridge position."""

HARVESTER_CLAIM_STALENESS = 0
"""A harvester claim marker is valid for this many rounds beyond the round it was placed."""

DESTROY_BRIDGE_TIMEOUT = 50
"""Rounds before a destroy-bridge attempt is abandoned."""

DESTROY_BRIDGE_BLACKLIST_EXPIRY = 200
"""Rounds before a blacklisted destroy-bridge target becomes eligible again."""

def scaled_constant(ct, x: int): return x * ct.get_scale_percent() / 100