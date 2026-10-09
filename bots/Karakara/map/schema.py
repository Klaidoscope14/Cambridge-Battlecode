"""
Schema for entities and tiles (two independent grids).
Entity grid: entity record or None per cell.
Tile grid: terrain per cell — wall, empty, titanium_ore, ore_axionite.
See https://docs.battlecode.cam for entity types and Controller API.
"""
from cambc import Environment, EntityType

# Marker grid cell type: u32 marker value when present, else None (builders can stand on markers)
MarkerCell = int | None

_CONVEYOR_LIKE = frozenset({EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR})
_GUNNER = EntityType.GUNNER
_SENTINEL = EntityType.SENTINEL
_BREACH = EntityType.BREACH
_BRIDGE = EntityType.BRIDGE
_MARKER = EntityType.MARKER
_FOUNDRY = EntityType.FOUNDRY


class EntityRecord:
    """Single record class for every entity on the grid.

    Replaces the prior frozen-dataclass hierarchy. All fields live as
    ``__slots__`` to keep instantiation cheap (no ``object.__setattr__``
    indirection, no MRO walk, no per-class ``__dict__``).

    ``__init__`` only takes the 5 fields every entity has; specialised
    fields default to None / 0 and are written directly by
    ``record_from_controller`` for the entity types that use them.

    Discriminate on ``entity_type``, NOT ``isinstance``. There is only
    one underlying class — every legacy ``*Record`` name in this module
    is an alias for ``EntityRecord``.
    """

    __slots__ = (
        "id",
        "entity_type",
        "team",
        "hp",
        "max_hp",
        # Anchor position on the grid this turn. Written by MapManager.update
        # when the record is paired with its grid cell. None for CORE (3x3
        # footprint — use mm.ally_core_pos / mm.spotted_enemy_core_pos instead).
        "position",
        # turret / directional fields
        "direction",
        "ammo",
        "ammo_resource",
        # storage fields
        "stored_resource",
        "output_target",
        # gunner-only
        "target_pos",
        # marker-only
        "marker_value",
        # builder-bot-only
        "action_cooldown",
        "move_cooldown",
    )

    def __init__(self, id, entity_type, team, hp, max_hp):
        self.id = id
        self.entity_type = entity_type
        self.team = team
        self.hp = hp
        self.max_hp = max_hp
        self.position = None
        self.direction = None
        self.ammo = 0
        self.ammo_resource = None
        self.stored_resource = None
        self.output_target = None
        self.target_pos = None
        self.marker_value = None
        self.action_cooldown = 0
        self.move_cooldown = 0

    def refresh(self, ct, entity_id: int) -> None:
        """Update only dynamic fields in-place. Skips static fields (entity_type,
        team, max_hp, direction for non-gunners, output_target, ammo_resource)."""
        self.hp = ct.get_hp(entity_id)
        etype = self.entity_type
        if etype in _CONVEYOR_LIKE or etype is _BRIDGE or etype is _FOUNDRY:
            self.stored_resource = ct.get_stored_resource(entity_id)
        elif etype is _GUNNER:
            self.direction = ct.get_direction(entity_id)
            #self.target_pos = ct.get_gunner_target_pos(entity_id)
        elif etype is _MARKER:
            if self.team == ct.get_team():
                self.marker_value = ct.get_marker_value(entity_id)


# --- Backwards-compatible aliases ---
# All prior record classes collapse to one. Existing imports and type
# annotations remain valid. The single isinstance check that depended on
# the hierarchy (vision/storage_tracker.py) was migrated to an
# entity_type check.

BaseEntityRecord = EntityRecord
TurretRecord = EntityRecord
GunnerRecord = EntityRecord
ConveyorRecord = EntityRecord
BridgeRecord = EntityRecord
SimpleBuildingRecord = EntityRecord
MarkerRecord = EntityRecord
BuilderBotRecord = EntityRecord
CoreRecord = EntityRecord

GridEntityRecord = EntityRecord

BotCell = EntityRecord | None

EntityCell = EntityRecord | None

EnvironmentCell = Environment | None
