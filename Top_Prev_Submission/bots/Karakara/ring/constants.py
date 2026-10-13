"""Constants for the generic ring-build pipeline."""

from cambc import EntityType

DEBUG: bool = True

# When False, conveyor ring slots will never auto-upgrade to BARRIER.
ALLOW_BARRIER_UPGRADE: bool = False

ACTION_RADIUS_SQ = 2

TURRET_TYPES = {
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
}

ENEMY_INFRA_TYPES = {
    EntityType.ROAD,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
}

PHASE_ROUTE = "route"
PHASE_SABOTAGE = "sabotage"
PHASE_BUILD = "build"

# try_step_off return values.
STEP_OFF_MOVED = "moved"      # bot left the target tile this tick
STEP_OFF_WAITING = "waiting"  # no exit ready, but progress was made (road laid) — retry next tick
STEP_OFF_STUCK = "stuck"      # no escape possible, caller should abandon
