"""Constants shared across the harvester-build pipeline."""

from cambc import EntityType, Environment

# Toggle verbose per-tick logging from harvester phases.
DEBUG: bool = False

# ── Action / vision ─────────────────────────────────────────────────

ACTION_RADIUS_SQ = 2

# ── Tile / building categories ──────────────────────────────────────

ORE_TYPES = {
    Environment.ORE_TITANIUM,
    Environment.ORE_AXIONITE,
}

TURRET_TYPES = {
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
}

# Ally buildings the harvester is NOT allowed to destroy/replace.
UNREPLACEABLE_ALLY_TYPES = {
    EntityType.BRIDGE,
}

ENEMY_INFRA_TYPES = {
    EntityType.ROAD,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
}

# ── Numeric thresholds ──────────────────────────────────────────────

TOO_MANY_ENEMY_TILES = 100
COOLDOWN_DURATION = 100
ROUTE_TIMEOUT = 2000
RESOURCE_BUFFER_FRACTION = 0.5
BRIDGE_COST_RESERVE = 1

# Ally turret on an ore tile may be destroyed only when no enemy builder
# has been seen for SAFE_ROUNDS and the turret has stood put for at least
# MIN_TURRET_AGE rounds.
SAFE_ROUNDS = 30
MIN_TURRET_AGE = 30

# Axionite-build gate
AXIONITE_RESOURCE_MULTIPLIER = 2.5
AXIONITE_MIN_ROUND = 250
TITANIUM_MIN_RATE = 4

# ── Phases ──────────────────────────────────────────────────────────

PHASE_ROUTE = "route"
PHASE_SABOTAGE = "sabotage"
PHASE_BUILD = "build"

# ── Ore-type priority tiers (lower = higher priority) ───────────────

ORE_TIER_AXIONITE = 0
ORE_TIER_TITANIUM = 1
ORE_TIER_EQUAL = 0
