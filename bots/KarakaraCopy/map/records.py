"""
Functions that build or interpret grid/entity data using the map schema.
Use with three independent grids: tile_grid (terrain), entity_grid (entities), marker_grid (marker values).
"""
from typing import Optional
from cambc import EntityType, Direction

from map.schema import EntityRecord

# Local-bind EntityType members — avoids a dotted attribute lookup per comparison.
_BUILDER_BOT = EntityType.BUILDER_BOT
_CORE = EntityType.CORE
_GUNNER = EntityType.GUNNER
_SENTINEL = EntityType.SENTINEL
_BREACH = EntityType.BREACH
_LAUNCHER = EntityType.LAUNCHER
_CONVEYOR = EntityType.CONVEYOR
_SPLITTER = EntityType.SPLITTER
_ARMOURED_CONVEYOR = EntityType.ARMOURED_CONVEYOR
_BRIDGE = EntityType.BRIDGE
_MARKER = EntityType.MARKER
_DIRECTION_CENTRE = Direction.CENTRE


def record_from_controller(ct, entity_id: int) -> Optional[EntityRecord]:
    """
    Build an EntityRecord for the entity with the given id using Controller.
    Returns None if the entity is invalid or not visible.
    """
    try:
        etype = ct.get_entity_type(entity_id)
        team = ct.get_team(entity_id)
        hp = ct.get_hp(entity_id)
        max_hp = ct.get_max_hp(entity_id)
    except Exception:
        return None

    rec = EntityRecord(entity_id, etype, team, hp, max_hp)

    if etype is _CONVEYOR or etype is _SPLITTER or etype is _ARMOURED_CONVEYOR:
        try:
            rec.direction = ct.get_direction(entity_id)
            rec.stored_resource = ct.get_stored_resource(entity_id)
        except Exception:
            pass
        return rec

    if etype is _BRIDGE:
        try:
            rec.output_target = ct.get_bridge_target(entity_id)
            rec.stored_resource = ct.get_stored_resource(entity_id)
        except Exception:
            pass
        rec.direction = _DIRECTION_CENTRE
        return rec

    if etype is _BUILDER_BOT:
        try:
            rec.action_cooldown = ct.get_action_cooldown(entity_id)
            rec.move_cooldown = ct.get_move_cooldown(entity_id)
        except Exception:
            pass
        return rec

    if etype is _GUNNER:
        try:
            rec.direction = ct.get_direction(entity_id)
            rec.ammo = ct.get_ammo(entity_id)
            rec.ammo_resource = ct.get_ammo_resource(entity_id)
        except Exception:
            return rec
        try:
            rec.target_pos = ct.get_gunner_target_pos(entity_id)
        except Exception:
            pass
        return rec

    if etype is _SENTINEL or etype is _BREACH:
        try:
            rec.direction = ct.get_direction(entity_id)
            rec.ammo = ct.get_ammo(entity_id)
            rec.ammo_resource = ct.get_ammo_resource(entity_id)
        except Exception:
            pass
        return rec

    if etype is _LAUNCHER:
        try:
            rec.direction = ct.get_direction(entity_id)
        except Exception:
            pass
        return rec

    if etype is _MARKER:
        try:
            if team == ct.get_team():
                rec.marker_value = ct.get_marker_value(entity_id)
        except Exception:
            pass
        return rec

    # CORE and SimpleBuilding types (HARVESTER, ROAD, BARRIER, FOUNDRY, ...) need no extras.
    return rec
