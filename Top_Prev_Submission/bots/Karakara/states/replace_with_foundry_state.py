from cambc import Controller, EntityType, Position

from debug.profiling import cputimer
from helpers.directions import DIRECTIONS
from map.map_manager import MapManager
from ring import ring_build
from ring.constants import PHASE_BUILD, PHASE_ROUTE
from ring.helpers import manhattan
from states.builder_state import BuilderState


# Cooldown on abandoned foundry candidates, mirroring build_harvester_state.
COOLDOWN_DURATION = 0


class ReplaceWithFoundryState:
    def __init__(self, ct, brain):
        self.ct = ct
        self.brain = brain
        # ring pipeline contract: ``target``, ``_phase``, ``_clear_target``.
        self.target: Position | None = None
        self._phase: str = PHASE_ROUTE
        self._target_set_round: int = -1
        self.cooldowns: dict[Position, int] = {}
        # Candidates persist across turns so we can revisit ones that have
        # drifted out of vision. Only re-validated while in vision.
        self.remembered_candidates: set[Position] = set()

    # ── Cooldown / target bookkeeping ───────────────────────────────

    def _expire_cooldowns(self, current_round: int) -> None:
        expired = [
            p for p, r in self.cooldowns.items()
            if current_round - r > COOLDOWN_DURATION
        ]
        for p in expired:
            del self.cooldowns[p]

    def _assign_target(self, pos: Position | None, current_round: int) -> None:
        if pos != self.target:
            self._target_set_round = current_round if pos is not None else -1
            self._phase = PHASE_ROUTE
        self.target = pos

    def _clear_target(self, current_round: int, *, cooldown: bool = False) -> None:
        if self.target is not None and cooldown:
            self.cooldowns[self.target] = current_round
        self.target = None
        self._target_set_round = -1
        self._phase = PHASE_ROUTE

    # ── Main loop ───────────────────────────────────────────────────

    @cputimer
    def execute(self, ct: Controller):
        current_round = ct.get_current_round()
        self._expire_cooldowns(current_round)

        if self.target is None:
            return False

        # Resource gate (mirrors build_harvester_state): once we're in the
        # BUILD phase but can't afford the foundry, hand off to GUARD so the
        # bot does something useful instead of idling on the target.
        if self._phase == PHASE_BUILD:
            if ct.get_global_resources()[0] < ct.get_foundry_cost()[0] * 0.8:
                self.brain.state_manager.state_map[BuilderState.GUARD].execute(ct)
                return False

        return ring_build(
            self,
            ct,
            center=EntityType.FOUNDRY,
            ring=EntityType.BARRIER,
        )

    @cputimer
    def determine(self, ct, state_manager):
        mm: MapManager = self.brain.map_manager
        my_id = ct.get_id()
        my_pos = ct.get_position()
        vision_sq = ct.get_vision_radius_sq()
        ally_core = mm.ally_core_pos
        current_round = ct.get_current_round()

        # Merge freshly-seen candidates into the persistent set and prune any
        # remembered ones that visibly became invalid this turn.
        self.remembered_candidates.update(mm.nearby_foundry_replacement_candidates)
        self._prune_invalid_in_vision(mm, my_pos, vision_sq)
        # If the prune killed our active target, drop self.target too so we
        # don't carry a dead Position around. Resets _phase via _clear_target
        # so the next assign_target starts fresh in PHASE_ROUTE.
        if self.target is not None and self.target not in self.remembered_candidates:
            self._clear_target(current_round)

        def _rank(pos: Position) -> int:
            return -manhattan(pos, ally_core) if ally_core is not None else 0

        # Sticky: already locked onto a valid uncrowded target, keep it.
        if (
            state_manager.previous_state == BuilderState.REPLACE_WITH_FOUNDRY_STATE
            and self.target is not None
            and self.target in self.remembered_candidates
            and not self._is_crowded(self.target, mm, my_id, my_pos, vision_sq)
        ):
            if mm.newly_seen:
                candidate = self._pick_best(mm, my_id, my_pos, vision_sq, ally_core)
                if (
                    candidate is not None
                    and candidate != self.target
                    and _rank(candidate) < _rank(self.target)
                ):
                    self._assign_target(candidate, current_round)
            state_manager.current_state = BuilderState.REPLACE_WITH_FOUNDRY_STATE
            return True

        best = self._pick_best(mm, my_id, my_pos, vision_sq, ally_core)
        if best is None:
            return False

        self._assign_target(best, current_round)
        state_manager.current_state = BuilderState.REPLACE_WITH_FOUNDRY_STATE
        return True

    # ── Candidate management ────────────────────────────────────────

    def _pick_best(
        self,
        mm: MapManager,
        my_id: int,
        my_pos: Position,
        vision_sq: int,
        ally_core: Position,
    ) -> Position | None:
        """Choose the remembered candidate furthest from ally core that isn't
        crowded by another builder. Crowding is not a permanent disqualifier,
        just a per-turn skip."""
        best_pos = None
        best_score = None  # larger manhattan-to-core wins
        for cand_pos in self.remembered_candidates:
            if cand_pos in self.cooldowns:
                continue
            if self._is_crowded(cand_pos, mm, my_id, my_pos, vision_sq):
                continue
            score = manhattan(cand_pos, ally_core) if ally_core is not None else 0
            if best_score is None or score > best_score:
                best_score = score
                best_pos = cand_pos
        return best_pos

    def _prune_invalid_in_vision(
        self,
        mm: MapManager,
        my_pos: Position,
        vision_sq: int,
    ) -> None:
        """Drop remembered candidates that are now visibly invalid.

        Two prune triggers:
          1. ``_candidate_valid`` fails — there's a foundry on the tile or
             adjacent, or an adjacent harvester is already served.
          2. Staleness: if we have full local vision of ``cand_pos`` and
             every in-bounds 8-neighbour AND MapManager did NOT re-include
             the candidate in ``nearby_foundry_replacement_candidates`` this
             turn, drop it. By logic, a still-valid candidate would have been
             re-added — full local vision means MapManager had the same info
             we do, so its omission is authoritative. This catches the
             "raw-ax source disappeared since we first saw the candidate"
             case that ``_candidate_valid`` doesn't cover.

        Out-of-vision (or partially-in-vision) candidates stay untouched —
        we can't verify them, so the best guess is they're still good until
        we see otherwise.
        """
        width = mm.width
        height = mm.height
        building_grid = mm.building_grid
        current_candidates = set(mm.nearby_foundry_replacement_candidates)
        to_drop: list[Position] = []
        for cand_pos in self.remembered_candidates:
            if my_pos.distance_squared(cand_pos) > vision_sq:
                continue
            if not self._candidate_valid(cand_pos, mm, width, height, building_grid):
                to_drop.append(cand_pos)
                continue
            if cand_pos in current_candidates:
                continue
            # MapManager didn't re-validate this turn. Only treat that as
            # authoritative if every in-bounds 8-neighbour is also in vision —
            # otherwise an axionite source we can't see might still exist.
            full_local_vision = True
            for d in DIRECTIONS:
                adj = cand_pos.add(d)
                if not (0 <= adj.x < width and 0 <= adj.y < height):
                    continue
                if my_pos.distance_squared(adj) > vision_sq:
                    full_local_vision = False
                    break
            if full_local_vision:
                to_drop.append(cand_pos)
        for p in to_drop:
            self.remembered_candidates.discard(p)

    def _candidate_valid(
        self,
        cand_pos: Position,
        mm: MapManager,
        width: int,
        height: int,
        building_grid,
    ) -> bool:
        """Re-apply the two skip rules from the original find_replace_location
        (both over all 8 neighbours):
          1. No foundry cardinally/diagonally adjacent to the candidate.
          2. No adjacent harvester that already has a foundry on any of its
             own 8 neighbours.
        Also treat the candidate tile itself being a foundry as invalid."""
        cx, cy = cand_pos.x, cand_pos.y
        if 0 <= cx < width and 0 <= cy < height:
            rec = building_grid[cx][cy]
            if rec is not None and rec.entity_type == EntityType.FOUNDRY:
                return False
        adj_harvesters: list[Position] = []
        for d in DIRECTIONS:
            adj = cand_pos.add(d)
            ax, ay = adj.x, adj.y
            if not (0 <= ax < width and 0 <= ay < height):
                continue
            rec = building_grid[ax][ay]
            if rec is None:
                continue
            if rec.entity_type == EntityType.FOUNDRY:
                return False
            if rec.entity_type == EntityType.HARVESTER:
                adj_harvesters.append(adj)
        for h_pos in adj_harvesters:
            for d in DIRECTIONS:
                adj = h_pos.add(d)
                ax, ay = adj.x, adj.y
                if not (0 <= ax < width and 0 <= ay < height):
                    continue
                rec = building_grid[ax][ay]
                if rec is not None and rec.entity_type == EntityType.FOUNDRY:
                    return False
        return True

    def _is_crowded(
        self,
        cand_pos: Position,
        mm: MapManager,
        my_id: int,
        my_pos: Position,
        vision_sq: int,
    ) -> bool:
        """True if a non-self bot sits on or adjacent to cand_pos (within our
        vision). Out-of-vision tiles are treated as uncrowded — we can't see
        them, so best to try."""
        width = mm.width
        height = mm.height
        bot_grid = mm.bot_grid
        for check_pos in (cand_pos,) + tuple(cand_pos.add(d) for d in DIRECTIONS):
            cx, cy = check_pos.x, check_pos.y
            if not (0 <= cx < width and 0 <= cy < height):
                continue
            if my_pos.distance_squared(check_pos) > vision_sq:
                continue
            occupant_rec = bot_grid[cx][cy]
            occupant = occupant_rec.id if occupant_rec is not None else None
            if occupant is not None and occupant != my_id:
                return True
        return False
