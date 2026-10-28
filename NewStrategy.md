# New bot strategy ("nova") — draft

Basis: `Observations.md` (2,469 top-10 games, 60 top-10 replays, compared with 175 / 30 of ours). The bot is written
from scratch in C++ in `Submission/bots/nova`; the current submission (`bots/kessoku` = v65) is untouched.

## Lessons that constrain the design

1. Copying the top draft onto our old play logic lost clearly (META_DRAFT 600 vs 674, with melee tweaks 603 vs 674).
   The draft only works if farming, fighting and banking are built for it from the start.
2. Their edge is not position (same own/middle/away split as us) but **tempo**: first clear r19, ~5 clears per 100
   rounds from the start (we do ~3 for 600 rounds), 26% of time on camps early (we 17%), shop/heal 5% of the time.
3. Fights are taken when ahead (57% of contacts) and avoided when behind (~10%); they step away early (median 77% HP)
   and come back. Deaths decide games.
4. Every drafted champion is a farmer (1.2-2.2k gold each for Marcella, Vesper, Vendetta; ~0.9k Heart).
5. Bags are small (median tribute 21-26) and the first tribute comes by r77.
6. Our local test bots are forks of our ranged bot, so local results are a safety check; the panels and the ladder decide.

## 1. Draft

| Team size | Picks, in order |
|---|---|
| 3 | Vesper, Heart of Ruin, Vendetta |
| 4 | + Marcella |
| 5 | + Cassi & Issac (Fish's fifth; adds a body, measured +13 for us vs zci) |

Mirror picks are allowed, so the order only matters for our own team. Fallback if a pick fails: Ryth, Tavi.

## 2. Roles

| Champion | Role | Notes |
|---|---|---|
| Vesper | Gold carrier, ranged damage | +20% gold: designated capturer of gold-rich groups; first clears on clusters |
| Marcella | Bruiser, gem banker | 2 gold per gem tributed: designated capturer of gem-rich groups, banks the most |
| Vendetta | Camp clearer, skirmisher | Cooldown reset on camp kills: takes multi-camp groups; follows up kills |
| Heart of Ruin | Frontline | Up to +50% damage at low HP: stays in winning fights down to 20% HP |
| Cassi & Issac | Paired farmers | Stay together; Cassi ranged focus, Issac melee; retreat as a pair |

## 3. Farming

- **Score** for a camp group: value / time.
  - value = gems + 0.5 x gold, times the champion's role bonus (Vesper +20% of gold, Marcella +2 per gem when she will
    bank it), times a side factor (own 1.2, middle 1.0, enemy half 0.6; enemy half 1.0 while 2+ enemies are dead).
  - time = path distance + kill time (group HP / our camp damage, counting allies already there) + 5-turn capture.
  - Claimed groups (shared memory) are skipped unless the group is big and the claimant needs help.
- **Solo feasibility:** take a fighting group only if `camp damage x kill time <= HP - 25% of max`; otherwise only if an
  ally is already on it. Never wait more than 4 rounds for help (the old bot lost tempo waiting for squads).
- **Opening:** the score naturally favours clusters and wolf camps on the own half; no special opening script.
- **Monoliths:** never targeted; tiles within the monolith's reach + 1 are avoided while it is awake.

## 4. Banking

- Bank when the bag reaches 25 (Marcella 20) and an altar is within 12 steps, or 40 anywhere.
- Take an altar detour of up to 6 extra steps for a bag of 12+.
- Threat banking: an enemy within 8 and a bag of 12+ -> bank if an altar is nearer than the enemy, else retreat home.
- Endgame: if our tributed gems + bag would reach 1,000, bank now.
- Altars with an enemy within 4 (seen in the last 8 rounds) are skipped.

## 5. Shopping and items

- Shop whenever standing on spawn; go home to shop when gold >= 300 and spawn is within 15, or when HP < 55% and no
  fight is going on (heal + shop). Target ~5% of time at spawn.
- Builds (first three emblems from the top teams, then stacking):

| Champion | 1st | 2nd | 3rd | Then stack |
|---|---|---|---|---|
| Vesper | Treasure Strength | Jungle Strength | Bruiser Health | Bruiser Strength (1 Health per 2 Strength) |
| Marcella | Treasure Health | Jungle Strength | Bruiser Health | Bruiser Strength / Health 1:1 |
| Vendetta | Treasure Health | Jungle Strength | Bruiser Health | Bruiser Strength (1 Health per 2) |
| Heart | Treasure Health | Jungle Focus | Bruiser Health | Bruiser Focus / Health 1:1 |
| Cassi | Power Focus | Durability Focus | Bruiser Health | Bruiser Focus |
| Issac | Treasure Strength | Power Strength | Home Health | Bruiser Strength |
| Others | Treasure (main stat) | Jungle | Bruiser Health | Bruiser main stat |

- One altar lock is kept once the first three emblems are bought (used to deny enemy tributes).

## 6. Fights

Every turn, around me (radius 6): our side = me + allies, their side = visible enemies.
Power = total HP x total damage per round (Lanchester), damage including ready spells.

| Situation | Action |
|---|---|
| ratio >= 1.25 and an enemy within 5 | **Engage**: move into range, focus the enemy we can kill this turn, else the lowest HP share |
| 0.8 <= ratio < 1.25 and an enemy already in range | **Trade**: attack, do not chase |
| ratio < 0.8, or my HP < 40% (Heart: 20% while ratio >= 1) | **Disengage**: bank if an altar is in reach, else step away from threats toward allies/spawn |
| an ally within 8 is in contact, I am healthy (>= 60%) and the joint ratio >= 1 | **Join** the fight |
| enemy HP <= my burst within 3 and the tile is safe | **Finish** it |

- Spells: damage spells on champions first (kills, then low HP), area spells where they hit 2+; stun the
  highest-damage enemy in range; shields when taking damage below 70% HP; Vendetta reset after a kill; Marcella's
  enhanced attack reset when adjacent; dashes only to finish a kill or to escape.
- Unseen enemies are remembered 10 rounds (position + 1 tile per round of slack) and count at half weight.

## 7. Vision and denial

- Every 8 rounds place a ward on the tile in placement range that is nearest the enemy spawn and within 6 of my target
  group or altar (own half and middle, matching the top teams' 94%).
- Altar lock: use on an altar within 2 tiles where an enemy is tributing.

## 8. Game state adjustments

- Behind by 200+ tributed gems: engage at ratio >= 1.0 and score enemy-half groups at 1.0 (comebacks come from
  fights and gems).
- Ahead by 200+: bank at 15, engage only at >= 1.5.

## 9. Shared memory (8 bytes)

| Byte | Use |
|---|---|
| 0-5 | Claimed group id + 1 for each body |
| 6 | Fight call: map sector + 1 of an ally in a winning fight (rewritten every round, round parity in the top bit) |
| 7 | Last round an enemy was seen on our half (in 8s) |

## 10. Code layout

| File | Contents |
|---|---|
| `config.h` | Every parameter above (one place to tune) |
| `world.h/.cpp` | Per-turn snapshot: me, allies, enemies, memory of unseen enemies, camp groups, distance fields |
| `draft.cpp` | Draft order |
| `farm.cpp` | Group scoring, targeting, claims, capture |
| `fight.cpp` | Skirmish evaluation, engage / trade / disengage / join, spells |
| `econ.cpp` | Banking, shopping, wards, altar locks |
| `main.cpp` | Turn order: observe -> retreat check -> fight -> bank -> shop -> farm -> ward |

## 11. Testing

Protocol as before: focused (fight maps and always-lost maps vs zmarc / zgank / zmeta / zci) and full pool vs v65
on AWS; then the panels and the ladder. Expect a tuning round after the first full pool, since this is a new bot.

## 12. Status (2026-10-27, nova v0)

Implemented from scratch in `Submission/bots/nova/src` (config.h, bot.h, world.cpp, farm.cpp, econ.cpp, fight.cpp,
turn.cpp, draft.cpp, main.cpp; ~900 lines). Builds cleanly, 0 faults, 0 turn errors.

| Test | Result |
|---|---|
| vs starter-cpp (3 maps x 2 sides) | 6/8 after fixes (stuck-target and claim ping-pong bugs fixed) |
| vs v65 (00eight, 02fields, 01shortcut, 00lanes x 2 sides) | **0/8**: gold 700-2,400 vs 3,500-10,300; deaths 4-40 vs 0-8 |

Bugs found and fixed during the first runs: camp groups with no living camps and no reward kept as targets
(champions stood still for hundreds of rounds); two champions yielding the same cluster to each other every re-score
(target ping-pong); targets switched mid-walk (switch margin 1.25 -> 1.5); early all-in fights into the enemy's
spawn (no engagement before r150, never chase within 3 of their spawn).

Main gaps vs v65, in order:
1. Farming throughput: 4-5x less gold even in low-death games. Needs per-group distance fields (path distance, not
   a re-computed field from us), multi-camp attack order, capture without idle turns, and an opening route.
2. Fights: on fight maps nova still loses 30-40 champions a game to v65's focus fire.
3. Banking at a fixed bag size without altar-distance planning.

## 13. Iteration 2 (2026-10-27): fuel and farming fixes

Measured on 6 maps x 2 sides vs starter-cpp (`~/.cache/kessoku_rep/thr.py`), v65 = 1,658 gold@300, 22.2 clears<300.

| Change | gold@300 | clears<300 | deaths | wins vs starter |
|---|---|---|---|---|
| start (no squad starts) | 559 | 10.3 | 6.3 | 8/12 |
| idle champions lead squads; helpers counted on the wait ring | 618 | 10.8 | 7.5 | 8/12 |
| partial-sight group HP; claim tie-break by body; no re-score mid-fight | 666 | 10.8 | 7.4 | 10/12 |
| **no `state()` on out-of-sight groups** (each threw, ~2K fuel; up to 6,000 lost turns a game) | 856 | 15.6 | 3.5 | 11/12 |
| long walks step down cached static fields | 933 | 15.5 | 4.3 | 12/12 |
| camps read from `camp_tiles` / `awake_camp_tiles` bitboards, one group field per turn, altar locks only in sight | 991 | 15.8 | 3.5 | 10/12 |

Fuel lessons: fuel counts our own code as well as engine calls (bitboard loops and prints cost thousands); every
thrown engine error costs ~2K; `vision::camps()` alone ~10K with 40+ camps in sight; a `distance_field` ~11K.
Exhausted turns abort with no action. The_pack still loses ~360 turns a game (was ~3,000).

nova vs v65 (same 6 maps x 2): **0/12**, deaths 178 vs 37 (00eight: 34-36 vs 0), gold 26k vs 90k.
Next: fights (focus fire, disengage before low HP, no feeding on fight maps), then the farming tempo gap
(first clear r22 vs r12; v65 takes the 22-44 gem wolf groups early).

## 14. Code-review items 1-4 (2026-10-28)

From the nova-vs-v65 review (CAMBC_Nova_vs_v65_Claude_Context.txt). Each change behind a switch in `config.h`, identity
check first (switches off reproduced the previous build exactly), then one switch at a time against the current
baseline: 20 maps x 2 sides head-to-head (`~/.cache/kessoku_rep/flagtest.sh`) plus 6 maps x 2 vs starter-cpp.

| Switch | Head-to-head vs baseline | Tributed gems | Deaths | vs starter-cpp | Decision |
|---|---|---|---|---|---|
| `ALIVE_STATE` (visible group the engine reports alive is alive, not "away 10 rounds") | 22/40 | 24,233 vs 22,055 | 777 vs 809 | 10/12, gold@300 983 vs 991 | **on** |
| `DEAD_SHOP` (shop while dead; claim byte kept, as v65) | 21/40 | 22,854 vs 22,779 | 790 vs 748 | 10/12, gold@600 2,252 vs 2,146 | **on** |
| `MOVE_RESET` (attack after moving: melee always, ranged via attack reset; reset re-picks after a kill) | 22/40 | 21,838 vs 21,263 | 697 vs 722 | **12/12**, tributed 9,005 vs 7,549 | **on** |
| `MONO_AVOID` (no step within reach + 1 of an awake monolith we are not farming) | 21/44 on the 22 monolith maps (never fired); vs zmono2 2/44 both on and off | 17,556 vs 17,576 | 691 vs 685 | identical | off (no effect) |

nova vs zmono2 on the 22 monolith maps: 2/44 - nova is still far behind our older bots; fights remain the gap.

## 15. Code-review items 5-7 (2026-10-28)

Same method as section 14 (baseline = nova with ALIVE_STATE, DEAD_SHOP, MOVE_RESET on). The identity check first
failed: computing the map mode at startup (unused while off) cost a little fuel, shifted when group fields were
built, and moved gold@300 955 -> 915 on its own. That is the size of pure timing noise; the code now runs only when
the switch is on, and switches-off then matched exactly.

| Switch | Head-to-head vs baseline | Tributed gems | Deaths | vs starter-cpp | Decision |
|---|---|---|---|---|---|
| `NEAR_SWEEP` (group within 4 steps scores x2, v65) | 18/40 | 23,308 vs 23,024 | 764 vs 697 | 12/12; clears<300 16.3 vs 15.2, <600 33.2 vs 29.2 | off (fewer wins, more deaths) |
| `MAP_MODES` (side weights by spawn walk, v65) | 20/40 | 22,372 vs 22,785 | 743 vs 777 | 12/12; gold@300 898 vs 955 | off (no gain over nova's fixed side weights) |
| `SQUAD_WAIT` (v65 LESS_WAIT: regroup after 4, give up after 12, +10 time per missing helper) | 22/40 | 22,735 vs 24,944 | 825 vs 658 | 11/12; tributed 8,263 vs 9,005 | off (economy -9%, deaths +25%) |

None of the three v65 farming features carries over to nova on its own. NEAR_SWEEP raises clears but also deaths,
so it may pay once nova's fights are safer; worth re-testing after the fight work.
