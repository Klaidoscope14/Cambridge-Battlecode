"""Central tunable configuration.

Every weight the strategy depends on lives here so experiments can flip one
knob at a time (point 7: testing as an optimisation engine). Nothing else in
the codebase should hard-code a magic number that affects a decision; import
it from CFG instead. Feature flags let ablation tests disable a whole
subsystem without touching its code.
"""
from __future__ import annotations


class _Config:
    __slots__ = ()

    # ---- feature flags (ablation switches) --------------------------------
    USE_EV_BANKING = True          # point 1: risk-aware banking
    USE_LAYERED_DECISIONS = True   # point 2: A/B/C with hysteresis
    USE_GEOMETRY = True            # point 3: geometric map reasoning
    USE_BELIEF = True              # point 5/8: observed/inferred/unknown
    USE_COORDINATION = True        # point 6: lanes + 8-byte live memory
    USE_GANKING = True             # hunt loaded enemies
    USE_WARDS = True               # vision placement
    USE_METRICS = True             # point 7: per-turn instrumentation logging

    # ---- fuel budget ------------------------------------------------------
    FUEL_SOFT_FLOOR = 8000         # below this, skip optional planning
    FUEL_HARD_FLOOR = 2500         # below this, bail out of the turn

    # ---- banking EV policy (point 1) --------------------------------------
    # Expected value of continuing to farm vs banking now. Values are in
    # "gems" units unless noted. Tuned priors; refine with self-play.
    GEMS_PER_FARM_WINDOW = 6.0     # expected gems gained per safe farming window
    FARM_WINDOW_ROUNDS = 12        # how many rounds a "window" is
    BANK_BASE_URGENCY = 0.0        # constant push toward banking
    # Risk of losing the bag scales with carried gems, enemy proximity and HP.
    RISK_PER_ENEMY_IN_VISION = 0.06
    RISK_PER_ENEMY_NEAR = 0.22     # enemy within THREAT_RADIUS of me
    THREAT_RADIUS = 6
    RISK_LOW_HP_FACTOR = 0.9       # extra risk multiplier when at low HP
    LOW_HP_FRACTION = 0.40
    # Travel/channel cost: banking isn't free; each round away from farming
    # costs expected farm value.
    BANK_TRAVEL_PENALTY_PER_TILE = 0.02
    # Hard bag ceiling: above this always try to bank regardless of EV.
    BAG_PANIC_CEILING = 60
    # Endgame: if tributing this bag would win (reach WINNING_GEMS), always go.
    ENDGAME_FORCE_BANK = True

    # ---- recall policy ----------------------------------------------------
    RECALL_HP_FRACTION = 0.30      # recall when below this and unsafe
    RECALL_HP_FRACTION_SAFE = 0.15 # recall even if nominally safe below this
    RECALL_IF_RICH_GOLD = 150      # recall to spend a big gold stack

    # ---- objective arbitration (point 2) ----------------------------------
    # Hysteresis: keep the current objective unless a challenger beats it by
    # this margin (fraction of the incumbent's score), or the incumbent is
    # infeasible, or an emergency overrides.
    COMMIT_MARGIN = 0.25
    COMMIT_MIN_ROUNDS = 4          # don't switch away from an objective this
    #                                fresh unless infeasible/emergency.
    # Objective base weights (priors for Layer B scoring).
    W_CAPTURE = 10.0               # finishing a capture we started
    W_FARM = 6.0
    W_BANK = 7.0
    W_GANK = 8.0
    W_DEFEND = 7.5
    W_WARD = 2.0
    W_SHOP = 3.0
    W_EXPLORE = 1.0

    # ---- combat / micro (point 6) -----------------------------------------
    KITE_WHEN_RANGED = True
    # Only kite if we can still contribute damage soon; kiting a melee-range
    # camp as a ranged champ trades an attack for safety.
    KITE_HP_FRACTION = 0.6         # kite (reposition) below this HP vs camps
    STUN_SAVE_FOR_PVP = True       # prefer saving CC for champions over camps
    FOCUS_TARGET_LOWEST_HP = True  # last-hit / focus fire

    # ---- draft scoring (point 4) ------------------------------------------
    # Weights on champion scoring features; priors, meant to be learned.
    DW_CLEAR = 1.0                 # camp-clear speed
    DW_ECON = 0.6                  # gold economy
    DW_MOBILITY = 0.5
    DW_SUSTAIN = 0.5
    DW_CONTROL = 0.8               # stuns / PvP disruption
    DW_SURVIVE = 0.6
    DW_TEAM_FIT = 0.7              # role coverage / anti-overlap
    # Map-feature multipliers applied on top (set in draftbrain).
    DRAFT_COUNTER_WEIGHT = 0.5     # how much enemy picks shift our scores

    # ---- geometry (point 3) -----------------------------------------------
    MAX_FIELD_DISTANCE = 255       # DistanceField cap
    SAFE_ALTAR_MAX_ENEMY_ACCESS = 1  # altars with <= this enemy reach are "safe"

    # ---- belief / fog (point 5,8) -----------------------------------------
    ENEMY_POSITION_DECAY = 0.85    # confidence multiplier per round unseen
    ENEMY_FORGET_ROUNDS = 25       # drop an inferred enemy after this many
    DANGER_ENEMY_RANGE_PAD = 1     # treat enemy threat range as atk_range+this

    # ---- coordination (point 6) -------------------------------------------
    # 8-byte shared memory layout (byte offsets). Keep tiny and unambiguous.
    SM_ROUND = 0                   # u16: round of last writer (freshness)
    SM_HELP_X = 2                  # u8: ally-needs-help tile x (+1, 0=none)
    SM_HELP_Y = 3                  # u8: ally-needs-help tile y (+1, 0=none)
    SM_ENEMY_CARRIER_X = 4         # u8: spotted loaded enemy x (+1, 0=none)
    SM_ENEMY_CARRIER_Y = 5         # u8
    SM_FLAGS = 6                   # u8 bitfield: bit0 = racing-to-win
    SM_RESERVED = 7


CFG = _Config()
