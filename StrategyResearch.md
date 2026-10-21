# Strategy research memo for `bots/kessoku` (internal v25 / ladder v24), 2026-10-22

Sources: `GameRules.md`, `BotAPICpp.md`, the full bot source, **370 ranked games played by this build since the Ad Astra series** (06:50 to 19:10 UTC, 21 Oct; record **190-180**), 180 games of the previous builds, and about 70 local 35-map x 2-side sweeps run for this memo.

Labels: **RULE** = stated in `GameRules.md`; **LOG** = seen in ladder event logs; **MEASURED** = deterministic local A/B (`tools/ab.py`, 70 games, parity 35); **COMPUTED** = derived from logs/geometry; **HYPOTHESIS** = untested. I did not assume undocumented mechanics; where a strategy depends on one, the first experiment confirms it.

## 0. Read this first

1. **None of the quick ideas I tested beats the current build across a diverse set of opponents.** Eighteen variants (opening-arrival rules, close-out banking, altar locks, wards, Durability emblem, squad convergence, two drafts) either lost in total against the five-opponent set or won only the mirror. Section 3 has every number. The lesson is also a method warning: **a mirror win is not evidence**; several variants gained 4-8 mirror wins and lost 10+ games against the other opponents.
2. The ideas worth building are therefore not parameter changes but **new capabilities that no tuning test can see**, grounded in mechanics that the logs show exist.
3. **Three highest-upside strategies** (details in section 5):
   1. **Resource-control suite: lock-and-guard the chokepoints and sit on spawn tiles** (altar ownership + respawn-tile control). Highest ceiling, highest risk, 18 of 35 maps have <= 2 altars and 11 have a combined supply flow that a perfect team could only just turn into 1,000 gems in 1,000 rounds.
   2. **Channel economy: prime the tribute before the loot lands, plus team-wide parallel close-out.** Smallest upside but near-certain: the engine behaviour is confirmed in a real log, and the situations are countable.
   3. **Score-state controller from the exact opponent score** (`global_submitted_gems(enemy)` is readable): risk-off when ahead, siege/denial when behind. Moderate ceiling, cheap, and it uses the only opponent information that is exact and free.

## 1. Model of the game (what is actually there)

- **Players and bodies.** Two teams, 3-6 bodies each (3-5 draft picks; Cassi & Issac is one pick, two bodies). Each body is its own program instance with 100k fuel per turn, no shared memory except 8 bytes of team memory (1,024 bytes of draft memory is read-only during play). Vision is 8 tiles per body (+ one persistent ward, radius 6, replaceable once per round within 2 tiles); vision is not shared.
- **Timing.** Rounds alternate which team moves first; within a team, higher priority first, then draft order (`set_priority` persists). Round start: camp respawns, effects, **camp captures**, camp attacks; then champion turns, where channels that reached zero execute at the owner's turn start.
- **Actions per body per turn.** One move (1 tile, 8 directions), one basic attack (ranged: move OR attack unless a reset ability), one ability cast (8-turn-end cooldown per slot), ward, consumables (altar lock, teleport crystal, 10 gold each, one of each at a time), recall (5 turn-ends, 3 with Home), tribute, shop on spawn tiles (Tavi: shards anywhere).
- **Supply.** Camp groups (cardinally connected camps) hold gems and gold and **respawn together** after a timer (40-150 rounds, set by the longest member) once rewards are claimed. Camps are asleep until hit, attack the nearest champion in range while awake, never chase, and sleep after 2 rounds without a champion in range. Total gem supply per map ranges 68 to 1,180 per cycle; the per-1,000-round ceiling at perfect duty is **COMPUTED** below.
- **Conversion pipeline.** Kill every camp in a group -> stand on a spawn tile of the group uncontested for 5 capture phases (more bodies do not speed it; an enemy on the region resets it; rewards split among allies present) -> carry -> tribute: stand within Chebyshev 1 of an altar, channel `ceil(bag/10)` turn-ends (min 1), completion tributes **the whole bag at completion, including gems that arrived during the channel** (RULE and LOG, section 2). Interrupts: stun, death, enemy altar lock; damage does not interrupt a tribute.
- **Shared, contestable objects.** Altars are shared by both teams. A lock (10 gold, 3 basic attacks to remove) blocks only the opponent's tributes and cancels their channel at that altar; the owner's team can still tribute; an already-locked altar cannot be locked again. Group spawn tiles are shared; **any occupied spawn tile delays the whole group's respawn** (RULE; also observed in our own bot: the v17 boss_battle deadlock).
- **Violence.** Death costs 60 rounds, drops the bag to the killer, pays the killer 50 base gold (100 in the 3.0 patch notes), and a camp kill destroys the bag. Spawn tiles heal fully each turn end and cannot be entered by opponents.
- **Scoring.** First team to 1,000 **tributed** gems wins at once. At round 2,000: tributed gems, then lifetime gold earned, then kills, then Team B. Carried gems and spent gold do not count.
- **Observable opponent state.** Positions, HP, bag, ability cooldowns of visible enemies; `global_submitted_gems(enemy)` exactly, at any time; enemy spawn region and altars from the map.

## 2. What decides matches (from the logs)

| Fact | Evidence | Label |
|---|---|---|
| The collected-gem lead at round 300 predicts the result (67% win with a lead, 31% without; at round 900, 83% vs 15%) | 370 games | LOG |
| A tributed lead of >= 100 at round 700 wins 88%; behind by >= 100 wins 10% | 370 games | LOG |
| Losses are blowouts, not close races: median margin at the end 364 gems; only 23 of 152 gem-decided losses were within 100 | 370 games | LOG |
| 15% of games run to round 2000 (54 of 370); record 26-28, mostly decided on tributed gems | 370 games | LOG |
| Eight maps carry 41% of the losses (74 of 180: `elkring` 0-7, `monolith` 1-11, `rushbait_v2` 1-10, `broken_curve` 2-11, `reverse_spiral` 2-9, `lanes` 4-12, `rows` 2-6, `collision` 3-8). Their camp-type mix does not explain it (correlation of win rate with wolf/elk/monolith/cluster share: -0.01 / +0.24 / -0.16 / -0.16) | 370 games, geometry | LOG, COMPUTED |
| Supply binds on many maps. Perfect-duty ceiling of **all** gem groups together per 1,000 rounds: `fragment` 778, `elk_arena` 800, `hooks` 978, then `packs` 1,767, `stampede` 1,778, `gold_rush` 1,936 ... 11 maps below 2,500 | probe of all 35 maps | COMPUTED |
| 18 of 35 maps have 1 or 2 altars | probe | COMPUTED |
| On `elkring` (10 identical elk groups, 22 gems each) clear counts are equal (45/44, 44/46, 41/47) and we lose by 130-180 gems: the opponent's extra gems are **loot from our dead carriers** (we died 6-13 times, they 0-7) | 7 games | LOG |
| A tribute that completes in the same round as a capture it contains is real: Willow, `01hooks`, round 1035: captured 22 gems at round 1028, another 11 at the capture phase of round 1035, tribute event of 33 at that round's turn start | event log | LOG |
| Gems sit next to altars on a few maps: group spawn tiles within Chebyshev 1 of an altar on `hooks`, `starfish`, `yellow_brick_road`, `broken_curve`, `islands`, `fracture`, `shortcut`, `boss_battle`; share of all captured gems at such tiles: `starfish` 25%, `hooks` 25%, `yellow_brick_road` 10%, `broken_curve` 6% | probe + logs | COMPUTED |
| Team close-out: in 6 of 152 gem-decided losses (4%) our submitted + carried gems already reached 1,000 twenty rounds before the opponent finished (10 = 7% at the finish); in wins the median gap between "1,000 in hand" and the real finish is 30 rounds | 370 games | COMPUTED |
| Dedicated carrier hunting is expected to lose: a body farms about 0.12 gems per round (180 per game); the whole team's current take from enemy carriers is about 50 gems per game | 370 games | COMPUTED |

## 3. Experiments run for this memo (35 maps x 2 sides = 70 games each; wins out of 70)

Baseline (current build): vs `zmeta` (Stellar/Ren/Varg/Ryth/Cassi-Issac comp) **59**, vs `zpoke` (ranged kiter) **52**, vs `zhor` **66**, vs `zrush` **58**, mirror vs itself 35 (parity).

| Variant (all behind switches, patch in `kessoku_strategy_experiments.diff`) | zmeta | zpoke | zhor | zrush | mirror |
|---|---|---|---|---|---|
| Opening: value x0.7 for groups both spawns reach within 3 tiles, first 300 rounds | 63 | - | 61 | 62 | 39 |
| same, x0.5 within 4, first 400 | 60 | - | - | - | 37 |
| Opening: value x0.6 for groups the enemy reaches first | 60 | - | - | - | 42 |
| both rules (0.7 and 0.6) | 62 | 52 | 59 | 59 | 37 |
| both rules, tie 2, 450 rounds | 61 | 51 | - | - | 38 |
| both rules, milder (0.85 / 0.7) | 59 | 50 | - | - | 38 |
| both rules + keep applying them while far ahead | 62 | 51 | 59 | 59 | 41 |
| Close-out: every body banks any bag >= 5 once team tributed >= 800 | 59 | - | - | - | 34 |
| same at 900 | 60 | - | - | - | 34 |
| Place our altar lock before tributing | 61 | - | - | - | 33 |
| Leave the ward on the group just captured | 61 | - | - | - | 30 |
| Leave the ward at the altar tributed at | 59 | - | - | - | 36 |
| Durability emblem after Monster + Jungle | 57 | **40** | - | - | 36 |
| Squad convergence x2 (`SQUAD_CLAIM_BONUS` 1.0) | 56 | 48 | 59 | - | 39 |
| Squad convergence x4 (2.0) | 55 | 38 | 59 | - | 29 |
| Squad convergence 1.0 + up to 4 helpers | 58 | 43 | 64 | - | 43 |
| Draft: Vendetta always the 4th pick | 60 | 45 | 61 | - | - |
| Draft: drop Willow, Vendetta first | 59 | 40 | 64 | - | - |

Reading:
- The arrival-aware opening (the idea I expected to win) is net zero over opponents: +4 vs `zmeta`, -7 vs `zhor`, +4 vs `zrush`; the mirror gain (37-42) does not generalise. **Do not ship it.**
- Close-out, lock-on-bank and wards change nothing measurable locally. That does not refute them: the test opponents are kessoku copies that do not exploit what these ideas protect against (their carriers behave like ours), and the close-out situation is rare (4-7% of losses).
- Durability, the stronger squad and both drafts lose in total (-11 to -14 wins over `zmeta`+`zpoke`+`zhor`).
- Ladder shows Vendetta teams winning 40-18 vs 71-76 for Stellar teams, but each map always gets the same draft, so this is map-confounded (Vendetta is drafted only on 5 maps, including `expanse` 12-0); the local test removes the confound and finds no gain.

## 4. Strategy catalog (14 distinct approaches)

Ranking columns: impact = expected change in win rate if it works as designed; complexity and compute are relative; risk = chance of a net loss.

| # | Strategy | Mechanic exploited | Impact | Complexity | Compute | Risk | Status |
|---|---|---|---|---|---|---|---|
| 1 | Respawn-tile control (starve supply) | an occupied spawn tile blocks the whole group's respawn | high on ~11 supply-bound maps, 0 elsewhere | medium | low | medium-high | RULE + observed once; **HYPOTHESIS** as a strategy |
| 2 | Altar ownership: lock and guard | lock blocks only the opponent; owner tributes freely; no double lock | high on <= 2-altar maps, 0 elsewhere | medium-high | low | high | RULE; untested vs real opponents |
| 3 | Channel economy: prime tribute before loot | completion tributes the whole bag, captures resolve before channels | small, near-certain; large on `hooks`/`starfish` | low-medium | none | low | **mechanic confirmed in LOG** |
| 4 | Team close-out (parallel tribute at the finish) | tribute channels run in parallel per body | +1.5-3% win | low | none | low | COMPUTED opportunity; local test neutral (rare) |
| 5 | Score-state controller (exact enemy score) | `global_submitted_gems(enemy)` is readable | moderate | low | none | low-medium | COMPUTED value of lead; policy untested |
| 6 | Capture-reset raids | an enemy on the region resets the 5-phase timer | small-moderate | medium | low | medium | RULE; **HYPOTHESIS** |
| 7 | Sentinel wards (respawn timers, altar sightings) | persistent vision of 6 tiles | small | low | low | low | MEASURED neutral/negative in the mirror |
| 8 | Arrival-time opening | known spawns, equal speed | small | low | one BFS | low | **MEASURED net zero** |
| 9 | Dedicated carrier hunter | carriers drop their bag to the killer | negative expected value | medium | low | high | COMPUTED: needs >= 3 kills per game to break even |
| 10 | Escorted banking | carriers die near altars; two bodies halve exposure | moderate on altar-distant maps (`elkring`, `rushbait_v2`) | medium | low | medium | HYPOTHESIS; motivated by net loot -50 to -90 on 6 of the 8 weak maps |
| 11 | Tribute-window punish | a tributing enemy cannot act for `ceil(bag/10)` turns | small | low | low | low | partly in the bot (`BREAK_CHANNELS`) |
| 12 | Stun sequencing for fights | stun skips the target's next turn; burst has an 8-turn cooldown | moderate | medium | medium | medium | HYPOTHESIS |
| 13 | Teleport-crystal shortcuts | crystal ignores terrain within 3 tiles | small, a few maps | medium | low | low | HYPOTHESIS |
| 14 | Draft re-fit by map shape | pick count and camp types differ by map | none found | low | none | low | MEASURED no gain (two variants) |

## 5. The strategies that deserve implementation, in detail

### 5.1 Resource-control suite (strategies 1 and 2)

**Mechanics.** RULE: "Any occupied spawn tile delays the entire group"; our own v17 `boss_battle` deadlock showed it (a capturer boxed in on the spawn tile while the group could not respawn). RULE: an altar lock blocks the opponent's tributes, cancels their channel, allows our tributes, takes 3 basic attacks to clear, costs 10 gold, and a locked altar cannot be locked again.

**Insight.** The game is a shared-resource race, not two separate farms. Supply is bound on about a third of the maps and the altar is a single point of failure on half of them. Whoever controls the chokepoint owns the tiebreak: at round 2000 only tributed gems count, and a team that is ahead and denies the other team's income wins without more farming. Both levers are cheap per body; neither is something the current bot does outside a late-game denial rule.

**Decision procedure (supply starvation, strategy 1).**

```
every re-score:
  flow_enemy_access = sum over gem groups g not blocked by us of gems[g] / (resp[g] + kill_time[g] + 5)
  if tributed_us - tributed_them >= M(t) and eta_them(under flow_enemy_access) > rounds_left:
      mode = STARVE
on capture completion of group g (we hold a region tile, all camps dead, reward paid):
  if mode == STARVE and g in top_k(groups by enemy_share[g] * flow[g] / holders_needed) and blockers < cap:
      stay on the region tile (no move); mark g as blocked_by_us
  leave if hp < 40% or outmatched(near) or mode != STARVE or round > 1990
farm elsewhere with the other bodies; bank as usual
```

`enemy_share[g]` is the fraction of g's last captures made by the enemy, observed by us (or inferred from distance to the enemy spawn).

**Decision procedure (altar ownership, strategy 2).**

```
candidates = altars sorted by (enemy_distance - our_distance) descending     // closest to us first
if altar_count <= 2 and we hold a lock and altar a is unlocked:
    walk within 2 of a, lock.use(a)
guards = 2 bodies (ranged preferred) kept within 3 tiles of every locked altar while mode in {SIEGE, STARVE}
clearers (enemies within attack range of the lock and in the lock's tile range): focus fire first
bank only at our locked altars; if the enemy has the lock, clear it only with allies within 6 tiles
release guards after 120 rounds without enemy contact or if guards die twice
```

**State and computation.** Per group: spawn tiles, resp time, last-capture team (from vision/events only if seen). Per altar: lock state (`has_altar_lock`, `altar_lock_at`), distance to both spawns (static BFS). Cost: one BFS from the enemy spawn at init (about 30k fuel on 100 x 100; do it lazily), plus O(G) per re-score.

**Failure cases and counters.** (a) The blocker or guards die: you lose bodies and the denial; counter: only commit when `side_power` near the target is in our favour and the lead is real (M >= 100 at round >= 600 where the lead predicted 88% wins). (b) The opponent brute-forces the lock with 3+ bodies: counter: fall back, lose 10 gold. (c) Blocking our own farms: use only groups the enemy took >= 40% of, never our home groups. (d) Self-trapping (the v17 deadlock): the blocker must never be boxed in; reuse the `EMPTY_GROUP_SKIP` guard. (e) A smart opponent can also do this to us: protect against it with the existing lock-clearing logic and by not leaving our captured groups unattended when supply is scarce.

**Controlled experiments.**
1. *Engine probe (1 hour):* scripted bots on `elk_arena` (one gem group): one body kills the group, captures, then stays on a spawn tile; log `group.state()` for 300 rounds; confirm the group stays "respawning/blocked". A second probe on a 2-altar map: lock one altar; confirm the enemy's `submit_gems` turns into a lock attack and that our tribute proceeds. These confirm or kill the strategy before any behaviour code is written.
2. *Behavioural A/B:* implement `STARVE` and `SIEGE` behind two switches. Opponents needed: the current five plus **a new adversary that actually contests chokepoints** (squad of 3 that walks to the lock and the blocker). Metrics: win rate on the 18 <= 2-altar maps and the 11 supply-bound maps separately, tributed gems at round 2000, deaths of guards/blockers. Pass: >= +6 wins out of 70 on the targeted maps with no loss elsewhere, in every opponent.

**Why it can beat a conventional strong bot.** A conventional bot optimises farming and fights. This changes who owns the game's finite throughput. It targets opponents that bank at a fixed place without escorts and supply-bound maps where being ahead is enough.

### 5.2 Channel economy (strategies 3 and 4)

**Mechanics.** RULE and LOG: the tribute channel length is fixed by the bag at the start; the completion tributes the entire bag then, including gems that landed in a capture phase in between ("Captures resolve before channels"). Round-1035 Willow log shows it.

**Insight (priming).** If a capture region tile is within Chebyshev 1 of an altar, a body that stands there can start a **short** tribute (small bag, 1-2 ticks) timed to complete at the turn start after the capture phase that pays the reward. The whole reward is tributed with no walk and no `ceil(bag/10)`-turn exposure. The opportunity is real only on a few maps (computed above: 25% of captured gems on `starfish` and `hooks`), but there it removes the single most dangerous part of a trip.

```
static: adj[g] = exists spawn tile t of g, altar a with cheb(t, a) <= 1
while holding region tile t of g with adj[g], capture phase count c in 0..4 observed:
    T = round when the reward will land (first uncontested capture phase + 4; calibrate by the probe)
    D = max(1, ceil(bag / 10))
    if bag >= 1 and not channeling and round == T - D: submit_gems(altar)
    if reward lands earlier than expected (bag grew): do nothing special (normal path)
```
A failed timing costs only the primer gems (they are tributed, not lost). A dust gem is needed: keep one gem back from earlier tributes when the next capture is adjacent (`escape()` and `bank()` already tribute whole bags; add `keep_one`).

**Close-out (strategy 4).** `should_bank` currently banks a body only when its own bag completes 1,000. Team-wide: once `tributed_us + sum(known bags) >= 1000`, every body drops everything and banks in parallel; finish time is the longest `ceil(bag/10)`, not the sum. Bags of allies are not shared (8 bytes): each body can store its bag in a quantised 4-bit slot after shrinking the claim bytes to 6 bits (6 x 6 + 6 x 4 = 60 bits), or simply bank everything >= 5 gems once `tributed_us >= 850`.

**Controlled experiments.** (1) Probe on `hooks`: place a body on the region tile next to the altar with 1 gem; verify with the event log that a 1-tick tribute started one round before the reward tributes the whole reward. (2) A/B only on the four maps (`hooks`, `starfish`, `yellow_brick_road`, `broken_curve`), both sides; metric: tribute events per capture, deaths with bag >= 20 near the altar, win rate. (3) Close-out on the full pool; metric: rounds from "1,000 in hand" to finish (median 30 now). Local test of the simple close-out (800/900): no effect, as expected for a rare case.

**Failure cases.** Timing off by one (primer wasted, 1-10 gems); contested capture resets the timer (channel completes with dust, nothing lost); stun on the channel (existing risk); the region tile is adjacent to an altar that the enemy has locked (check `has_altar_lock` first).

### 5.3 Score-state controller (strategy 5)

**Mechanic.** `global_submitted_gems(enemy)` is exact and free. The data show a sharp value structure: tributed lead >= 100 at round 700 wins 88%, deficit >= 100 wins 10%.

```
eta_us   = (1000 - (tributed_us + safe_carried_us)) / max(rate_us(300), eps)
eta_them = (1000 -  tributed_them) / max(rate_them(300), eps)
if eta_us + margin < eta_them:  mode = LEAD     // bank at 20, avoid contested groups, no new squads, keep bodies near spawn heal
elif eta_them + margin < eta_us: mode = BEHIND  // deny: lock altars, hunt visible bags >= 20, no farming in contested zone
else mode = EVEN
```
The existing bot has pieces (ahead-banking at 150, denial at 700); this unifies them with rate-based ETAs and a behaviour switch for the contested-zone rule. A first local version (rules from the opening experiment applied while 150 ahead) gave mirror 41, others 62/51/59/59 vs 62/52/59/58 without it: neutral. The case for it rests on the ladder statistic (88% vs 10%), not on local tests; the experiment must therefore use a **hunting/siege opponent** that punishes a passive leader and a farming opponent that rewards a passive leader.

**Failure cases.** Passive leaders get out-farmed when supply respawns (the controller must keep farming home groups); estimating rates early is noisy (require >= 300 rounds of data); the denial mode feeds kills when behind.

### 5.4 Other approaches in brief (all with a defined first experiment)

- **Capture-reset raids (6).** When an enemy body has stood on a group region for >= 3 capture phases and our nearest body is within 6 tiles with `side_power` > theirs, step onto the region (resets their timer) instead of farming. First experiment: a scripted two-body scenario on `00fragment` checking the reset; A/B against the five opponents on 70 games.
- **Sentinel wards (7).** Measured: leaving the ward on a captured group gave mirror 30 (worse), at the altar 36 (neutral), vs `zmeta` 61/59. Not worth more effort until an opponent that stalls near altars exists.
- **Escorted banking (10).** Motivation: net gems looted through kills are -71, -66, -46, -70, -93 on `elkring`, `monolith`, `rushbait_v2`, `lanes`, `collision`. Rule: if two bodies with bags >= 15 are within 4 tiles, bank together and take the other altar when the enemy was seen near the first. Experiment: against `zhor` and a carrier-hunting adversary on those five maps, metric = gems lost per game.
- **Tribute-window punish (11).** An enemy in a tribute channel is stationary for `ceil(bag/10)` turns; a ranged body within 4 tiles that is not outmatched gets free hits. The bot already prioritises tributing carriers (`fight_enemies`, `BREAK_CHANNELS`); extend to detours of <= 6 tiles. Experiment as above.
- **Stun sequencing (12).** Use stuns (Tavi S2, Ren, Cassi, Prism, Ryth, Marcella) on the enemy body with the largest next-turn burst before their turn, not only on tributers. Experiment: scripted duels with fixed seeds; metric = deaths per skirmish.
- **Teleport-crystal shortcuts (13).** Use a crystal when the walking path to a target exceeds the straight 3-tile jump by >= 6 and no enemy stunner is visible. Only a few maps benefit.
- **Dedicated hunter (9).** Rejected on arithmetic: it must make about 3 carrier kills per game to repay the 180 gems it stops farming.
- **Arrival-aware opening (8) and draft re-fit (14).** Measured, no gain.

## 6. Implementation priority and why

1. **Probes first (half a day, no bot changes):** the spawn-tile blocking probe, the lock probe, and the priming probe. They are the cheapest way to turn three HYPOTHESES into engine facts and decide the order.
2. **Channel economy (low risk, a few hours of code):** the priming and team close-out, because it cannot lose games when it mistimes and the opportunity is countable in logs.
3. **Score-state controller:** reuse existing banking/denial code; the value is in the lead statistics.
4. **Resource-control suite:** highest ceiling, so build it behind two switches after the probes confirm the engine behaviour, and gate promotion on the multi-opponent set (including a new chokepoint-contesting adversary), never on the mirror.

## 7. Evaluation protocol (to avoid the mistakes in section 3)

- Gate every change on the **sum over a fixed opponent set** (`zmeta`, `zpoke`, `zhor`, `zrush`, plus any new adversary), both sides of all 35 maps, and require no opponent to drop by more than 4 wins; the mirror is reported but never used to accept.
- Check the targeted maps separately (the effect of a map-specific mechanic is invisible in a 70-game total).
- Re-pull ladder games (>= 150) before and after a release and compare lead-at-300, deaths per game, and win rate on the eight weak maps.
