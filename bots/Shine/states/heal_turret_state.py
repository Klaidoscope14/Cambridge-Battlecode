from cambc import Controller, EntityType, GameConstants
from helpers.directions import DIRECTIONS
from helpers.geometry import in_vision
from debug.profiling import cputimer
from map.map_manager import MapManager
from nav.common import common_path
from nav.passability import can_pass_environment, can_pass_entity
from states.builder_state import BuilderState
from roles.builder.helpers import in_bounds


ACCOMPANY_TURNS = 9


class HealTurretState:
    def __init__(self, ct: Controller, brain):
        self.ct = ct
        self.brain = brain
        self.heal_pos = None
        self.turret_pos = None
        self.accompany_counter = 0

    def _find_heal_spot(self, ct: Controller, turret_pos):
        """Find the best adjacent spot to heal from, avoiding gunner danger zones."""
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()
        danger = mm.gunner_danger_positions
        dt = self.brain.damage_tracker

        # Start from direction of turret toward us, then alternate left/right
        toward_us = turret_pos.direction_to(my_pos)
        candidates = [toward_us]
        left = toward_us
        right = toward_us
        for _ in range(3):
            left = left.rotate_left()
            right = right.rotate_right()
            candidates.append(left)
            candidates.append(right)
        # opposite direction last
        candidates.append(toward_us.opposite())

        for d in candidates:
            spot = turret_pos.add(d)
            if not in_bounds(ct, spot):
                continue
            if spot in danger:
                continue
            # Skip tiles where we previously took damage, unless it's our
            # current tile — abandoning the current tile is usually worse
            # than staying put under fire.
            if spot != my_pos and dt.is_dangerous(spot):
                continue
            if not can_pass_environment(ct, spot, mm):
                continue
            if not can_pass_entity(ct, spot, mm):
                continue
            # no ally builder bot already there (unless it's us)
            if spot != my_pos:
                if not in_vision(ct.get_position(), spot, GameConstants.BUILDER_BOT_VISION_RADIUS_SQ):
                    continue
                bot = mm.get_bot(spot)
                bbot_id = bot.id if bot else None
                if bbot_id is not None and ct.get_team(bbot_id) == ct.get_team():
                    continue
            return spot
        return None

    def _count_nearby_ally_builders(self, ct: Controller, turret_pos):
        """Count ally builder bots on the 8 tiles adjacent to the turret,
        excluding self. Reads directly from the map manager's bot grid."""
        mm: MapManager = self.brain.map_manager
        my_team = ct.get_team()
        my_id = ct.get_id()
        count = 0
        for d in DIRECTIONS:
            pos = turret_pos.add(d)
            if not in_bounds(ct, pos):
                continue
            bot = mm.get_bot(pos)
            if bot is None:
                continue
            if bot.team != my_team:
                continue
            if bot.id == my_id:
                continue
            count += 1
        return count

    def _is_heal_spot_valid(self, ct: Controller, spot, turret_pos):
        """Lightweight re-validation of a previously chosen heal spot.
        Used by the sticky branch so we don't re-run the full search
        (and lose our spot to a transient danger marker) every turn.
        """
        mm: MapManager = self.brain.map_manager
        # Must be Chebyshev-1 adjacent to the turret (heal reach).
        dx = abs(spot.x - turret_pos.x)
        dy = abs(spot.y - turret_pos.y)
        if max(dx, dy) != 1:
            return False
        if not in_bounds(ct, spot):
            return False
        if not can_pass_environment(ct, spot, mm):
            return False
        if not can_pass_entity(ct, spot, mm):
            return False
        # Another ally builder sitting on it blocks us.
        my_pos = ct.get_position()
        if spot != my_pos:
            bot = mm.get_bot(spot)
            bbot_id = bot.id if bot else None
            if bbot_id is not None and ct.get_team(bbot_id) == ct.get_team():
                return False
        return True

    def execute(self, ct: Controller):
        if self.heal_pos is None:
            return
        if ct.get_position() != self.heal_pos:
            mm: MapManager = self.brain.map_manager
            common_path(ct, mm, self.brain.pathing, self.heal_pos)
        if self.turret_pos is not None and ct.can_heal(self.turret_pos):
            ct.heal(self.turret_pos)
            # Re-arm sticky accompany; keep heal_pos so we stay put next
            # turn instead of re-searching from scratch.
            self.accompany_counter = ACCOMPANY_TURNS

    @cputimer
    def determine(self, ct, state_manager):
        mm: MapManager = self.brain.map_manager
        my_pos = ct.get_position()

        # Sticky accompany: stay near a recently-healed turret for ACCOMPANY_TURNS
        # turns even if it's currently at full HP, in case it takes damage again.
        if (
            state_manager.previous_state == BuilderState.HEAL_TURRET
            and self.accompany_counter > 0
            and self.turret_pos is not None
        ):
            # Verify the gunner still exists and is ours; if it's been
            # destroyed or captured, drop sticky.
            building = mm.get_building(self.turret_pos)
            if (
                building is not None
                and building.team == ct.get_team()
                and building.entity_type == EntityType.GUNNER
                and self._count_nearby_ally_builders(ct, self.turret_pos) <= 1
            ):
                # Prefer keeping our current heal_pos if it's still usable
                # — this is what keeps us from drifting off the spot.
                if self.heal_pos is not None and self._is_heal_spot_valid(
                    ct, self.heal_pos, self.turret_pos
                ):
                    self.accompany_counter -= 1
                    state_manager.current_state = BuilderState.HEAL_TURRET
                    return True
                # Current spot no longer valid; try to find a new one.
                spot = self._find_heal_spot(ct, self.turret_pos)
                if spot is not None:
                    self.accompany_counter -= 1
                    self.heal_pos = spot
                    state_manager.current_state = BuilderState.HEAL_TURRET
                    return True

        # Accompany expired or no longer viable — clear sticky state.
        self.accompany_counter = 0
        self.turret_pos = None
        self.heal_pos = None

        best_dist = float('inf')
        best_turret_pos = None

        for tid in mm.nearby_ally_turret_ids:
            if ct.get_entity_type(tid) != EntityType.GUNNER:
                continue
            if ct.get_hp(tid) >= ct.get_max_hp(tid):
                continue
            tpos = ct.get_position(tid)
            # Skip turrets that already have enough ally builders adjacent
            # to heal them — no need to crowd.
            if self._count_nearby_ally_builders(ct, tpos) > 2:
                continue
            d = my_pos.distance_squared(tpos)
            if d < best_dist:
                best_dist = d
                best_turret_pos = tpos

        if best_turret_pos is None:
            return False

        spot = self._find_heal_spot(ct, best_turret_pos)
        if spot is None:
            return False

        # only take the state if we're the closest ally bot
        my_dist = my_pos.distance_squared(best_turret_pos)
        for bid in mm.nearby_ally_bot_ids:
            if ct.get_position(bid).distance_squared(best_turret_pos) < my_dist:
                return False

        self.turret_pos = best_turret_pos
        self.heal_pos = spot
        state_manager.current_state = BuilderState.HEAL_TURRET
        return True
