"""
Schema for entities and tiles (two independent grids).
Entity grid: entity record or None per cell.
Tile grid: terrain per cell — wall, empty, titanium_ore, ore_axionite.
See https://docs.battlecode.cam for entity types and Controller API.
"""
from dataclasses import dataclass
from typing import Optional

from cambc import EntityType, Team, Direction, ResourceType, Position, Environment

# Marker grid cell type: u32 marker value when present, else None (builders can stand on markers)
MarkerCell = int | None


# --- Base / common ---

@dataclass(frozen=True)
class BaseEntityRecord:
    """Common fields for every entity on the grid."""
    id: int
    entity_type: EntityType
    team: Team
    hp: int
    max_hp: int


# --- Turrets (have direction, ammo, etc.) ---

@dataclass(frozen=True)
class TurretRecord(BaseEntityRecord):
    """Gunner, Sentinel, Breach, Launcher — directional turrets with ammo (except launcher)."""
    direction: Direction
    ammo: int = 0
    ammo_resource: Optional[ResourceType] = None


@dataclass(frozen=True)
class GunnerRecord(TurretRecord):
    """Gunner: get_gunner_target_pos() for closest non-empty tile in facing direction."""
    target_pos: Optional[Position] = None


# --- Conveyors / directional buildings ---

@dataclass(frozen=True)
class ConveyorRecord(BaseEntityRecord):
    """Conveyor, Splitter, Armoured conveyor — direction + optional stored resource."""
    direction: Direction
    stored_resource: Optional[ResourceType] = None


@dataclass(frozen=True)
class BridgeRecord(BaseEntityRecord):
    """Bridge — has output target position."""
    direction: Direction  # implied by pos -> target
    output_target: Position
    stored_resource: Optional[ResourceType] = None


# --- Non-directional buildings ---

@dataclass(frozen=True)
class SimpleBuildingRecord(BaseEntityRecord):
    """Harvester, Road, Barrier, Foundry, Launcher (building). No extra per-type data in schema."""
    pass


@dataclass(frozen=True)
class MarkerRecord(BaseEntityRecord):
    """Marker — stores a u32 value (read via get_marker_value)."""
    marker_value: Optional[int] = None


# --- Mobile unit ---

@dataclass(frozen=True)
class BuilderBotRecord(BaseEntityRecord):
    """Builder bot — mobile unit; has action_cooldown, move_cooldown."""
    action_cooldown: int = 0
    move_cooldown: int = 0


# --- Core (3×3) ---

@dataclass(frozen=True)
class CoreRecord(BaseEntityRecord):
    """Core — 3×3; spawns builders. No extra data needed for grid cell."""
    pass


# --- Union type for entity records ---

GridEntityRecord = (
    BaseEntityRecord
    | TurretRecord
    | GunnerRecord
    | ConveyorRecord
    | BridgeRecord
    | SimpleBuildingRecord
    | MarkerRecord
    | BuilderBotRecord
    | CoreRecord
)

BotCell = BuilderBotRecord | None

EntityCell = GridEntityRecord | None

EnvironmentCell = Environment | None
