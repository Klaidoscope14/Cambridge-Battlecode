"""
Functions that build or interpret grid/entity data using the map schema.
Use with three independent grids: tile_grid (terrain), entity_grid (entities), marker_grid (marker values).
"""
from typing import Optional
from cambc import EntityType, Direction

from map.schema import (
    GridEntityRecord,
    BaseEntityRecord,
    BuilderBotRecord,
    CoreRecord,
    TurretRecord,
    GunnerRecord,
    ConveyorRecord,
    BridgeRecord,
    MarkerRecord,
    SimpleBuildingRecord,
)

def _base_kw(entity_id: int, ct) -> Optional[dict]:
    try:
        return {
            "id": entity_id,
            "entity_type": ct.get_entity_type(entity_id),
            "team": ct.get_team(entity_id),
            "hp": ct.get_hp(entity_id),
            "max_hp": ct.get_max_hp(entity_id),
        }
    except Exception:
        return None


def record_from_controller(ct, entity_id: int) -> Optional[GridEntityRecord]:
    """
    Build a GridEntityRecord for the entity with the given id using Controller.
    Returns None if the entity is invalid or not visible.
    """
    kw = _base_kw(entity_id, ct)
    if kw is None:
        return None
    etype = kw["entity_type"]

    if etype == EntityType.BUILDER_BOT:
        try:
            kw["action_cooldown"] = ct.get_action_cooldown(entity_id)
            kw["move_cooldown"] = ct.get_move_cooldown(entity_id)
        except Exception:
            kw["action_cooldown"] = 0
            kw["move_cooldown"] = 0
        return BuilderBotRecord(**kw)

    if etype == EntityType.CORE:
        return CoreRecord(**kw)

    if etype in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH, EntityType.LAUNCHER):
        try:
            kw["direction"] = ct.get_direction(entity_id)
            kw["ammo"] = 0 if etype == EntityType.LAUNCHER else ct.get_ammo(entity_id)
            kw["ammo_resource"] = None if etype == EntityType.LAUNCHER else ct.get_ammo_resource(entity_id)
        except Exception:
            return BaseEntityRecord(**{k: kw[k] for k in ("id", "entity_type", "team", "hp", "max_hp")})
        if etype == EntityType.GUNNER:
            try:
                kw["target_pos"] = ct.get_gunner_target_pos(entity_id)
            except Exception:
                kw["target_pos"] = None
            return GunnerRecord(**kw)
        return TurretRecord(**kw)

    if etype in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR):
        try:
            kw["direction"] = ct.get_direction(entity_id)
            kw["stored_resource"] = ct.get_stored_resource(entity_id)
        except Exception:
            return BaseEntityRecord(**{k: kw[k] for k in ("id", "entity_type", "team", "hp", "max_hp")})
        return ConveyorRecord(**kw)

    if etype == EntityType.BRIDGE:
        try:
            kw["output_target"] = ct.get_bridge_target(entity_id)
            kw["stored_resource"] = ct.get_stored_resource(entity_id)
        except Exception:
            return BaseEntityRecord(**{k: kw[k] for k in ("id", "entity_type", "team", "hp", "max_hp")})
        kw["direction"] = Direction.CENTRE
        return BridgeRecord(**kw)

    if etype == EntityType.MARKER:
        try:
            kw["marker_value"] = ct.get_marker_value(entity_id) if ct.get_team(entity_id) == ct.get_team() else None
        except Exception:
            kw["marker_value"] = None
        return MarkerRecord(**kw)

    return SimpleBuildingRecord(**kw)
