# Meta research for `bots/kessoku` (internal v25 = ladder v24), 2026-10-22

Goal: counterintuitive but rule-valid strategies, each derived from `GameRules.md` and checked
against what the bot can actually observe. Nothing here relies on knowing the map in advance
(everything is computed at runtime from the visible map, which the draft and every champion can
read), on hidden information, or on illegal actions.

**Evidence labels.** RULE = stated in `GameRules.md` (line numbers given). PROBE = confirmed by a
local probe bot for this report. LADDER = measured on the **395 ranked games played by v25**
(21 Oct 08:00-21:10 UTC, record **202-193**). THEORY = reasoning only. **No proposal below has
been shown to raise win rate.** Each has a test plan; the gate for shipping is the existing
protocol: sum of wins over the fixed opponent set (`zmeta`, `zpoke`, `zhor`, `zrush`, plus any new
adversary), 35 maps x 2 sides, no opponent down by more than 4, targeted maps checked separately,
the mirror reported but never used to accept.

---

## 1. Facts established for this report

| # | Fact | Label |
|---|---|---|
| F1 | **Turns interleave champion by champion**, not team by team. A probe logged, at each of our turns, which visible enemies had already acted: 153 of 1,329 observations saw some enemies done and others not, and both round parities showed "all done", "none done" and "mixed". So there is no team "double turn"; order is per champion (priority, then draft order) and the starting team swaps each round (RULE l.122-128). | PROBE |
| F2 | At our turn we can tell exactly which visible enemies have **already acted this round**: `champion::has_completed_turn()`. An enemy that has acted cannot act again until the next round. | PROBE + SDK |
| F3 | `set_priority` reorders our champions within the interleave from the next round on; the bot never calls it. | RULE l.127-128 |
| F4 | Visible enemies expose `remaining_channel_time()` and `is_submitting_gems()`. | SDK |
| F5 | Geometry (27 of 35 maps probed; the 8 largest did not report on turn 2): a camp group with a capture tile adjacent to an altar exists on 5 maps (hooks, starfish, shortcut, broken_curve, boss_battle); a fighting camp group within 3 tiles of a tribute tile exists on about 18 maps (usually one per side); all maps are mirror-symmetric (nearest altar equidistant from both spawns). | PROBE |
| F6 | **Capture theft is real and runs against us**: after a clear, the other team made the first capture of that group within 40 rounds 728 times on our clears (1.84 per game, 14,282 gems = 36 per game) and 440 times on theirs (1.11 per game, 22 per game). Net about **-14.6 gems per game**. | LADDER |
| F7 | Enemy tributes: 26.5 per game, median bag 22; tributes of >= 50 gems 3.3 per game, mean channel 8.1 turns. Ours: 18.4 per game, median 33. | LADDER |
| F8 | **Gem-dead games**: 13 games ended 0-0 at round 2000 (7-6, decided on lifetime gold). In the losses on `contest` and `stampede` we died 90/62/59/39 times against their 4/2/1/0, and each kill pays the killer gold (RULE l.361; 100 in patch 3.0). All boss_battle 0-0 games were won or lost on farming gold. | LADDER |
| F9 | Score reactivity: our deaths per 100 rounds are 0.54 before and 0.59 after we pass 700 tributed (222 windows): **no evidence opponents react to our score**. Their deaths rise 0.19 -> 0.38 after *they* pass 700, consistent with our own `ENDGAME_DENIAL`. | LADDER |
| F10 | Carried gems lost on death: ours to enemy champions 69 per game, theirs to ours 51; ours to camps 15 per game (destroyed). | LADDER |
| F11 | Enemy ward count does not track our results (>= 100 wards: 119-121; < 100: 56-47; none: 27-25). | LADDER |

Things already measured and rejected in earlier memos are not repeated as proposals: tour planner,
arrival-time opening, close-out at 800/900, lock-on-bank, wards on capture/bank, Durability, squad
convergence, Vendetta/Willow drafts, cluster down-weighting, capture assignment off, re-score
every 8/12, fight-sim outmatched.

---

## A. Five relatively safe improvements

### A1. First-strike gate: engage only enemies that have already acted

- **Mechanism (F1, F2).** Within a round, an enemy whose turn is done cannot respond until the next
  round. If we step into its range now, we land our hit this round; it answers next round at the
  earliest. If we step into range of an enemy that has *not* acted, it may hit first, this round.
- **Why positive (THEORY).** Our chase rules (melee kill-step, `MELEE_CHASE_POKERS`, ranged chase,
  deny chase) ignore turn state. Restricting new engagements to "already acted" enemies converts
  some even trades into first-strike trades and costs at most one turn of delay.
- **Assumptions.** `has_completed_turn()` is true exactly when that enemy has finished its turn this
  round (the probe's mixed states support it). Next-round order does not reverse the gain often.
- **Counter.** An opponent can read our flag the same way and only step in after we act; then both
  wait and the gate reduces our aggression with no gain (neutral, not negative).
- **Pseudocode.**
  ```cpp
  bool acted(const Foe& f) { try { return enemies[f.index].has_completed_turn(); } catch (...) { return false; } }
  // in fight_enemies() before any chase move (melee kill-step, poker chase, deny chase):
  if (Cfg::FIRST_STRIKE_GATE && !acted(*f) && !reach.is_set(f->pos)) continue;   // wait for it to act
  ```
- **Complexity.** O(F) flag reads per turn (F <= 6). Negligible fuel.
- **Failure modes.** Chases start one turn later and some targets escape; kiters that never act
  near us leave the gate permanently closed (melee loses its poker answer: watch `zpoke`).
- **Test plan.** A/B with the switch on vs v25 on the full set; extra metric: champion damage dealt
  minus taken per skirmish; check `zpoke` separately (melee chase is what fixed it in v22).

### A2. Contested-capture discipline: fight or fold, never sit

- **Mechanism (RULE l.193, 205).** "Leaving the region empty or admitting an enemy resets progress."
  The `hold` step in `play_turn` keeps a capturer on the tile while any enemy stands on the region,
  so the timer never runs; the enemy either kills it or captures after it leaves.
- **Why positive (THEORY + LADDER F6).** We lose 1.84 groups per game to the other team after our
  clears (36 gems). Holding a contested tile is a war of attrition with zero income; the right play
  is to win the fight decisively or leave at once and farm elsewhere.
- **Assumptions.** Enemy presence on the region is visible (region tiles inside our 8-tile vision;
  bushes can hide it, handled by the move-probe in C2).
- **Counter.** An opponent can bait us off rewards by standing on regions; folding hands them the
  reward. Mitigation: fold only when the local fight evaluation is unfavourable.
- **Pseudocode.**
  ```cpp
  // in the hold step, before attack_camp(capture_group):
  bool contested = false;
  for (const auto& f : foes) if (cg.spawn.is_set(f.pos)) contested = true;
  if (Cfg::CAPTURE_CONTEST && contested) {
      if (!outmatched) { fight_enemies(); return; }          // clear the region
      cg.skip_until = round + 20; capture_group = -1; target = -1;   // fold, farm elsewhere
  }
  ```
- **Complexity.** O(F) per turn. Negligible.
- **Failure modes.** Folding too eagerly gifts rewards; fighting on a region next to awake camps.
- **Test plan.** Full-set A/B. Specific metric from summaries: per-game count of our clears captured
  by the other team (ladder baseline 1.84, local baseline measured first on the same set).

### A3. Last-tick altar lock

- **Mechanism (RULE l.223, 235-241; F4).** Placing a lock cancels enemy tribute channels at that
  altar; the enemy then has to land 3 hits on the lock and restart the channel from zero. The
  channel length is fixed at its start (`ceil(bag/10)`). `try_lock_altar()` locks immediately.
- **Why positive (THEORY).** Locking on the last tick instead of the first wastes the whole channel
  (on average 8 turns for >= 50-gem bags, F7) instead of zero turns: the same 10-gold lock costs the
  enemy about twice the tempo. Pure timing change of an existing action.
- **Assumptions.** We can keep our position within 2 tiles for the waiting turns; the completion
  rule "completes at the owner's next turn start after reaching zero" (RULE l.229) means we must
  lock while `remaining_channel_time() >= 1` and before its next turn. With interleaved order this
  is safest when `remaining_channel_time() == 1` (lock now) or `== 2` and the enemy has already
  acted this round.
- **Counter.** The enemy cancels and re-tributes elsewhere; an opponent that guards altars kills the
  locker while it waits. Opportunity is small: an enemy tribute of >= 50 gems with one of our bodies
  dying within 6 tiles in the previous 30 rounds (a proxy for being there) happens 0.30 per game.
- **Pseudocode.**
  ```cpp
  // in try_lock_altar(), per tributing visible enemy f with bag >= 10:
  const int left = enemies[f.index].remaining_channel_time();
  const bool last = left <= 1 || (left == 2 && enemies[f.index].has_completed_turn());
  if (Cfg::LOCK_LAST_TICK && !last && !outmatched && burst_here * 2 < my_hp) { hold_position(); return true; }
  lock.use(a);
  ```
- **Complexity.** O(F x A). Negligible.
- **Failure modes.** Misreading the timer by one turn lets the tribute complete (the enemy banks;
  we would have cancelled it with the old rule); waiting next to enemies gets us killed.
- **Test plan.** First a probe: one enemy tributing 60 gems, our body within 2; log the turn the
  lock lands vs the tribute event to calibrate the off-by-one. Then full-set A/B; metric: enemy
  tribute events cancelled (no direct event: measure enemy tributes completed per game).

### A4. Primed tribute at capture-adjacent altars

- **Mechanism (RULE l.223, 230-231).** "Completion tributes your whole bag, including gems gained
  since" and "captures resolve before channels". A champion standing on a capture tile within 1 of
  an altar can start a 1-tick tribute (bag 1-10) so that it completes at the turn start right after
  the capture phase that pays the reward: the whole reward is banked with no walk and no
  `ceil(bag/10)`-turn exposure. Confirmed in a ladder event log by the earlier strategy memo
  (Willow, `01hooks`, round 1035).
- **Why positive (THEORY).** Removes the most dangerous part of a trip on the 5 maps of F5 (on
  `shortcut` 470 of 990 gems and on `starfish` 118 of 334 sit in adjacent groups). A mistimed
  primer only tributes the primer gems early: no gems can be lost by mistiming.
- **Assumptions.** The capture-phase count is predictable (5 phases from the first uncontested
  phase); we can keep 1-10 gems in the bag ("dust") before the capture.
- **Counter.** An enemy on the region resets the capture; an enemy lock on that altar converts our
  tribute into lock attacks (check `has_altar_lock` first).
- **Pseudocode.**
  ```cpp
  // static, lazily: adj[g] = any spawn tile of g within cheb 1 of an altar
  if (Cfg::PRIME_TRIBUTE && capture_group >= 0 && adj[capture_group] && me.gem_count() >= 1
      && !me.is_submitting_gems() && phases_held(capture_group) == 4 /* reward next phase */
      && !bc::vision::has_altar_lock(adj_altar[capture_group]))
      me.submit_gems(adj_altar[capture_group]);
  // keep dust: in bank(), when the next target is an adjacent group, stop at bag <= 10 (one tick).
  ```
- **Complexity.** O(groups x tiles x altars) once; O(1) per turn.
- **Failure modes.** Off-by-one phase counting (harmless), leaving the region to tribute (the
  tribute must be started from the capture tile, which is within 1 of the altar).
- **Test plan.** Probe on `hooks`: event log must show one tribute event equal to primer + reward in
  the capture round. A/B restricted to the 5 maps, both sides, all opponents; metric: our tribute
  events per capture and carrier deaths within 6 of those altars.

### A5. Gem-dead zero-feed mode (protect the gold tiebreak)

- **Mechanism (RULE l.27, 33, 361).** At round 2000 ties on tributed gems go to lifetime gold
  earned; kills pay the killer gold, assists pay nothing. When neither team can tribute (boss
  altar blocked, monolith-only gems the bot will not fight), every death is a pure transfer of
  tiebreak points.
- **Why positive (LADDER F8).** 13 v25 games ended 0-0: in the `contest`/`stampede` losses we died
  39-90 times against 0-4 and lost the gold count by 9,000-17,000. Not dying there would remove
  most of the enemy's gold lead (each death is 100 gold to them and 60 rounds of no farming for us).
- **Assumptions.** "Gem-dead" can be detected at runtime: both tributed totals are 0 at round >= 400
  and either `bank()` has hit the blocked-altar rule or all reachable gem groups are monoliths.
- **Counter.** An opponent that kills monoliths turns the game gem-live and we lose on gems; the mode
  must switch off the moment either team's tributed score moves.
- **Pseudocode.**
  ```cpp
  const bool gem_dead = round >= 400 && bc::global_submitted_gems(team::ally) == 0
      && bc::global_submitted_gems(team::enemy) == 0 && (round < bank_blocked_until || only_monolith_gems);
  if (Cfg::ZERO_FEED && gem_dead) {
      // farm only groups with no enemy seen within 8 in the last 40 rounds; retreat at 60% HP;
      // treat any visible enemy within SKIRMISH_RANGE as outmatched unless we can kill it this turn.
  }
  ```
- **Complexity.** O(G) per re-score for the extra filter.
- **Failure modes.** Over-passivity on gem-live maps if detection misfires; giving up central gold
  groups to a squad that farms them.
- **Test plan.** `contest`, `stampede`, `boss_battle` both sides vs all opponents; metrics: deaths and
  gold difference at 2000, win count on those maps; plus a full-set run to prove no effect elsewhere
  (the mode must never trigger on gem-live maps).

---

## B. Five high-upside experimental strategies

### B1. Capture theft ("reset raid")

- **Mechanism (RULE l.193, 205).** After the other team clears a group, any of our bodies standing on
  the region resets their 5-phase timer. If they leave or die, we hold 5 phases and take the full
  reward without fighting a single monster. Theft already happens incidentally: 1.11 per game by us,
  1.84 per game against us (F6).
- **Why positive (THEORY).** A full group reward (22-50 gems) for a few rounds of standing, against a
  farming income of about 0.12 gems per body-round: positive whenever the region is reachable within
  about 10 tiles and the local fight is in our favour.
- **Assumptions.** We see the enemy capturer on a region whose camps are all dead (`camps` dead +
  enemy on spawn tile); the enemy does not out-fight us there.
- **Counter.** Escort the capturer (two bodies); fight the raider; the counter is the same as A2 on
  their side.
- **Pseudocode.**
  ```cpp
  for (int g : visible_groups) {
      if (!all_camps_dead(g) || g.reward_taken) continue;
      const Foe* holder = enemy_on_region(g);
      if (!holder || cheb(pos, g.centre) > Cfg::RAID_RANGE) continue;
      if (simulate_fight(g.centre, 4, false).me_dies_at >= 0 || outmatched) continue;
      target = g; raid = true;      // move onto a free spawn tile of g, attack the holder if in range
  }
  ```
- **Complexity.** O(G x F) per re-score.
- **Failure modes.** Walking into an escort; region tiles all occupied; raids pull bodies off safe
  farms. Measures local strength only by visible units (fog).
- **Test plan.** Needs an opponent that captures alone (all kessoku copies do). Full-set A/B; metric:
  our thefts per game (local baseline first), deaths per game, wins.

### B2. Camp trap: monsters as weapons against stationary tributers

- **Mechanism (RULE l.189, 206-207, 223, 361-365).** Camps wake when hit, attack the **nearest**
  champion within range 3, never chase, and a camp kill **destroys** carried gems. A tribute channel
  holds the carrier in place (it can only cancel). On about 18 maps a fighting group sits within 3 of
  an altar's tribute tiles (F5). A ranged body can wake that group with one hit from range 3 and step
  back so that the tributing enemy is the nearest champion in range: elks hit for 60, wolves 20 each,
  every round, and damage does not stop the channel.
- **Why positive (THEORY).** It denies the enemy's whole bag (or forces a cancel) for one basic attack
  and no lock, and it keeps working while our body stays out of range.
- **Assumptions.** The trap group is alive and asleep; the enemy is nearer to it than we are; the camp
  stays awake while the enemy stands in range (it sleeps only after 2 rounds without an in-range
  champion, RULE l.207).
- **Counter.** Clear trap groups before tributing at that altar, cancel the channel, or use the other
  altar. Many bots will not model it at all.
- **Pseudocode.**
  ```cpp
  // static: trap[a] = fighting groups with a camp within 3 of altar a's tribute tiles
  for (const Foe& f : foes) if (f.channel == TRIBUTE)
      for (int g : trap[altar_of(f.pos)]) if (group_alive_asleep(g)) {
          const vec2 c = nearest_camp(g, f.pos);
          if (cheb(c, f.pos) > 3) continue;
          // wake from a tile within our range of c, then stand where cheb(us, c) > cheb(f, c)
          if (attack_tile_exists(c) && safe_after_wake()) { me.attack(camp_at(c)); step_away_from(c); }
      }
  ```
- **Complexity.** O(F x |trap|) per turn; trap sets built once.
- **Failure modes.** We are the nearest champion after waking and eat the group; the enemy finishes a
  short channel before the camps act (bags <= 10 complete next turn start).
- **Test plan.** Probe on a map with a trap group: scripted enemy tributing 80 gems, scripted waker;
  confirm camps target the tributer and its bag is destroyed on death (gemLoss context camp). Then
  A/B on the ~18 trap maps, both sides, all opponents.

### B3. Respawn denial by standing on a spawn tile (when ahead)

- **Mechanism (RULE l.193).** "Any occupied spawn tile delays the entire group." We already hit this
  by accident (v17 boss_battle deadlock).
- **Why positive (THEORY).** On supply-bound maps (earlier memo: 11 maps below 2,500 gems per 1,000
  rounds of perfect duty), a team that is ahead wins by cutting the other team's income. A body that
  sits on the spawn tile of an enemy-side group after capturing it removes that group's whole flow.
- **Assumptions.** We are ahead by a real margin (ladder: a tributed lead of >= 100 at round 700 wins
  88%, earlier memo); the sitter can hold the tile safely (spawn tiles of camps are ordinary tiles,
  so the sitter can be attacked).
- **Counter.** Kill the sitter (then the group respawns); farm elsewhere; sit on *our* groups in turn.
- **Pseudocode.**
  ```cpp
  if (Cfg::STARVE && lead() >= 100 && round >= 600 && just_captured(g) && enemy_share(g) >= 0.4
      && !outmatched && blockers_on_team() < 1)
      { stay(); }   // do not move; leave if hp < 40%, a foe can kill us next turn, or the lead drops
  ```
  `enemy_share` from captures we saw them make, or inferred from which spawn is nearer.
- **Complexity.** O(1) per turn plus the existing outmatched test.
- **Failure modes.** The sitter dies (100 gold and its bag to them); our own farming loses one body;
  self-trap (reuse `EMPTY_GROUP_SKIP` logic so allies never wait on that group).
- **Test plan.** Probe first (group stays respawning while occupied, 300 rounds). New adversary that
  attacks sitters. A/B on the supply-bound maps and the full set.

### B4. Altar ownership on <= 2-altar maps (lock and hold, when ahead)

- **Mechanism (RULE l.235-241).** A lock blocks only the opposing team, our team still tributes there,
  a locked altar cannot be locked again, and 3 basic attacks clear it. On a map with one or two
  altars, owning the lock owns the scoring.
- **Why positive (THEORY).** When ahead, a lock plus a guard turns every enemy tribute into a fight at
  a place we chose; when the enemy must break the lock, it stands still for 3 attack turns.
- **Assumptions.** Locks are cheap (10 gold) and the bot already buys them; guards win local fights.
- **Counter.** Brute-force the lock with a squad; out-trade the guards; tribute at the other altar.
- **Pseudocode.**
  ```cpp
  if (Cfg::SIEGE && altar_tiles.size() <= 2 && lead() >= 100 && have_lock())
      for (auto a : altars_by(their_dist - our_dist)) if (!bc::vision::has_altar_lock(a)) { walk_within(a, 2); lock.use(a); }
  // up to two ranged guards stay within 3 of our locked altar while lead() >= 100; focus enemies hitting the lock
  ```
- **Complexity.** O(A) per re-score.
- **Failure modes.** Guards die; we stop farming; the enemy simply uses the other altar.
- **Test plan.** Needs a lock-breaking adversary (extend `zlock2` to also clear locks with a squad).
  A/B on the <= 2-altar maps; pass only with no loss on the rest.

### B5. Adaptive opponent model with state-dependent plan switching

- **Mechanism.** Everything the bot sees about the opponent is legal information: visible bags, deaths
  and kills with positions, `global_submitted_gems(enemy)`, enemy positions near our groups and
  altars. Their tendencies show within about 300 rounds.
- **Why positive (THEORY).** Our five test opponents beat different presets: v22's melee chase helped
  vs pokers, health shards vs bruisers, ranged draft vs Heart of Ruin. A fixed policy is a compromise;
  a classifier can pick a preset per opponent: HUNTER (many of our deaths to champions, enemies seen
  near our altars) -> bank at 20, escort, A2 fold rule; FARMER (few fights, high enemy tribute rate) ->
  B1 raids, B3/B4 when ahead; CAMPER (enemies idle on altars) -> lock clearing and the other altar.
  Mixed play: choose between equal-value altars/targets with a seed from the opponent's revealed draft
  so the same opponent does not see the same choice every game (no RNG needed, and nothing hidden is
  used).
- **Assumptions.** Tendencies are stable within a game; 8 bytes of team memory can carry the class (2
  bits) so every body switches together.
- **Counter.** An opponent that changes behaviour mid-game; misclassification early.
- **Pseudocode.**
  ```cpp
  struct OppStats { int our_deaths_champ, enemy_near_altar, enemy_tribs; };   // updated in observe()
  if (round == 300 && body == 0) mem[7] = classify(stats);   // 2 bits, broadcast
  preset = mem[7] & 3;   // switches Cfg-like runtime parameters: BANK_BAG, fold rule, raid on/off
  ```
- **Complexity.** O(F) per turn for stats; O(1) classification.
- **Failure modes.** Byte 7 is the help-call byte (unused now); classification noise early.
- **Test plan.** Needs each preset A/B'd separately first; then the switcher vs each opponent must be
  >= the best fixed preset minus 1 on every opponent and > v25 in total.

---

## C. Three unconventional strategies with a plausible path

### C1. Map banking: deliberately leave a cleared group uncaptured

- **Mechanism (RULE l.193, 199).** A group respawns only "after rewards are claimed"; until someone
  captures it, the reward stays on the map. Carried gems are lost on death (RULE l.217) but an
  uncaptured reward is not carried by anyone.
- **Why it could pay (THEORY).** Near the end, or when an altar is far, killing a group and capturing
  it later (right before a bank trip, or with a primed tribute, A4) keeps gems out of our bags while
  the enemy is hunting, and freezes that group's respawn for the enemy too.
- **Assumptions.** The enemy does not capture it first (5 uncontested phases); we can return.
- **Counter.** Capture it (exactly what B1 does to them); the cost is our throughput (no respawn).
- **Pseudocode.** `if (Cfg::MAP_BANK && enemy_hunting && altar_far && capture_risky) { g.parked = true; skip capture; } ... if (parked && about_to_bank) capture(g)`.
- **Complexity.** O(1) per decision.
- **Failure modes.** Lost respawn cycles; the enemy steals parked rewards (F6 shows theft happens).
- **Test plan.** Only against a carrier-hunting adversary; metric: gems lost on death per game vs
  gems lost to theft of parked groups.

### C2. Bush shadow economy: stealth routing and free bush probes

- **Mechanism (RULE l.149, 163-167, 340-341).** Nobody sees into a bush from outside; enemies cannot
  target what they cannot see. A move into a bush tile that hides an enemy returns false, reveals the
  tile and **does not consume the move**: a free probe.
- **Why it could pay (THEORY).** Carriers that path through bushes cannot be targeted by spells or
  attacks from outside the bush; probing suspicious bush tiles before tributing finds ambushers at no
  cost. Our bot never prefers bushes.
- **Assumptions.** Enough bush tiles near routes (F5: bushes 2-456 per map; plenty on stampede,
  concentrated_wealth, collision).
- **Counter.** Enemies wait in the same bushes (they see the whole bush they stand in); wards (radius
  6) do not see into bushes either, so the counter is presence.
- **Pseudocode.** In `move_to` for carriers with bag >= 20: compute the field twice (with and without
  non-bush tiles penalised by forbidding them) and take the bush route if it is at most `k` steps
  longer; before `submit_gems`, try `move_absolute` into adjacent bush tiles that are reachable and
  unseen and log false results as enemies.
- **Complexity.** One extra BFS per carrier move (about 1.5 fuel per tile measured on big_world).
- **Failure modes.** Longer trips; meeting an enemy inside the bush at point-blank range.
- **Test plan.** Bush-heavy maps first; metric: carrier deaths with bag >= 20 per game; then full set.

### C3. Draft-time contingency planner (use the 10x draft turn and the unused 1,024 bytes)

- **Mechanism (RULE l.72-79, 389, 399).** The draft sees the whole map with 10x fuel and writes up to
  1,024 bytes that every champion can read. The bot writes an opening plan that nobody reads.
- **Why it could pay (THEORY).** A2-A5 and B1-B4 each need static map facts (adjacent altars, trap
  groups, supply-bound flag, <= 2 altars, gem-dead flag, enemy-side groups). Computing them once in
  the draft removes per-champion fuel spikes and lets every body agree on the same plan (no shared
  vision needed). The draft can also fix the mixed-strategy seed for B5.
- **Assumptions.** The draft bot can compute camp groups and distance fields within 1M fuel (one
  100x100 BFS is about 33K fuel).
- **Counter.** None directly; it is infrastructure.
- **Pseudocode.** `draft: plan = {flags(map), adj[], trap[], enemy_side[], seed}; bc::draft_memory = serialize(plan);` champions: `if (draft_memory valid) load(plan) else compute lazily as now.`
- **Complexity.** O(G x W x H) once in the draft; O(1) reads during play.
- **Failure modes.** Stale or partial plan if the draft runs out of fuel (fall back to lazy compute);
  the earlier performance audit showed extra first-turn work can change games, so measure.
- **Test plan.** Equivalence first (same decisions with the plan loaded vs computed), then it simply
  carries the other proposals.

---

## Rejected in this round (with the evidence)

| Idea | Why rejected |
|---|---|
| Team "double turn" tempo | PROBE F1: turns interleave per champion; replaced by A1 |
| Score sandbagging (keep our score low to avoid triggering opponents' denial) | LADDER F9: our death rate does not change after we pass 700 |
| Ward-based scouting as a win driver | LADDER F11: no relation; earlier mirror tests neutral or negative |
| Dedicated carrier hunter | earlier memo arithmetic: needs about 3 carrier kills per game to repay the farming it gives up; ladder take from enemy carriers is 51 gems per game for the whole team |

## Suggested order

1. Probes (no bot change): lock timing (A3), primer timing (A4), spawn-tile blocking (B3), camp trap
   targeting (B2). Each turns one THEORY into an engine fact or kills it.
2. A2 and A5 (most direct ladder evidence: -14.6 gems per game to theft; 0-0 losses by kill feeding).
3. A1 and A4, then B1 (needs no new adversary).
4. New adversaries (carrier hunter, lock breaker, sitter-killer) before B2-B5 and C1-C2.

---

## Results log

### 2026-10-22: A2 and A5 measured, both rejected

35 maps x 2 sides, 70 games per pairing. v26 baselines: zmeta 59, zpoke 52, zhor 66, zrush 58.

| Variant | vs v26 | zmeta | zpoke | zhor | zrush | sum of four |
|---|---|---|---|---|---|---|
| v26 | 35 | 59 | 52 | 66 | 58 | 235 |
| A2 contested-capture fold | 35 | 57 | 48 | 67 | 59 | 231 |
| A5 gem-dead zero-feed | 34 | 56 | 49 | 64 | 56 | 225 |
| both | 34 | 54 | 47 | 65 | 57 | 223 |

- **A2** did not change its own target metric: our clears captured by the opponent stayed at 1.6-2.3
  per game (1.84 vs 1.70 for v26 against `zmeta`). Locally, theft is roughly balanced (we also take
  about 2 per game), unlike the ladder (1.84 vs 1.11), so the ladder imbalance is caused by how ladder
  opponents capture or escort, not by our capturers sitting on contested tiles.
- **A5** is harmful on the very maps it targets: on `contest` vs `zmeta` v26 wins 2/2 (deaths 13 vs
  114, gold +25K); with the mode on it loses 0/2 (deaths 61 vs 12, gold -32K), and similarly against
  every opponent. Refusing fights does not avoid deaths; it removes the retaliation that kept the
  enemy honest. The ladder `contest` losses came from opponents that out-fight us, so the fix there
  is fighting better, not fighting less.
- Both stay in the code behind switches set to off; `kessoku.zip` is unchanged (v26).

### 2026-10-22: engine probes (scripted copies of kessoku; opponent `zidle` = kessoku that never acts, or `zmeta`)

| Probe | Result | Verdict for the strategy |
|---|---|---|
| **Spawn-tile blocking** (B3) | Our champion sat on the spawn tile of a captured group on `00fragment` and `00elkring`: the respawn timer counted 60 -> 0 and then stayed at `respawning:0` for ~230 rounds while the tile was occupied; the group was alive again within ~9 rounds of leaving. | **CONFIRMED**: one body freezes a group indefinitely. B3 is mechanically sound. Side note: any of our own bodies idling on a spawn tile also freezes that group. |
| **Lock timing** (A3) | 22 sightings of enemy tributes vs `zmeta` (70 games x 2 variants): the tribute event lands `remaining + 1` rounds after our observation if that enemy has already acted this round, `remaining` rounds if not. Deadline for a last-tick lock is therefore exact. | Mechanism **CONFIRMED**, opportunity **too rare**: we held a lock within 2 tiles of an altar during an enemy tribute only 6 times in 70 games (and the lock rule needs that enemy at the same altar). A3 parked. |
| **Primed tribute** (A4) | Capturer steered onto an altar-adjacent region tile; with 4 dust gems, a tribute started 3 rounds into the hold completed in the same round as the capture and banked 18 = 4 + 14 (two games, `broken_curve` both sides). Offsets 1-2 complete too early; offsets >= 4 come after the capture. General rule: start `4 - ceil(bag/10)` rounds into the hold (bags up to 30). | Mechanism **CONFIRMED**. Practical limit: 70 of 72 attempts had an empty bag (the bot banks whole bags), so A4 needs carried gems to fire; value is limited to the 5 adjacent-altar maps. |
| **Camp trap** (B2) | 396 enemy-tribute sightings in 28 games on the 14 trap maps; 96 had a live fighting camp within 3 of the tributer, 40 inside our attack range. After fixing the trigger to "end strictly farther from the camp than the enemy" (camps hit the nearest champion), 9 wakes: the camp hit the tributer every round (Cassi 531 -> 405 -> 279 vs elks; Varg 231 -> 76); 4 tributers died (kills credited to our champions, so their bags came to us), 5 tributes completed (short channels, 20-strength wolves). | **CONFIRMED**: monsters can be aimed at a channelling enemy. Worth building with a filter: elk-strength camps and >= 2 channel turns left. |

### 2026-10-22: B2 camp trap measured, neutral

Built in `bots/kessoku` behind `CAMP_TRAP` (camp strength >= 60, >= 2 rounds of channel left, bag >= 10,
no visible ally as close to the camp as the enemy, we end strictly farther from the camp than the enemy).
vs v26, 70 games each: mirror 35, zmeta 59 (v26 59), zpoke 51 (52), zhor 66 (66), zrush 58 (58).
It fired 3 times in 350 games (starfish 2, hooks 1): the probe's 40 in-range chances per 28 games
mostly fail the strength/channel/ally filters, and those filters are what made the probe wakes work.
Mechanism confirmed, opportunity too rare with our current positioning; making it matter needs
deliberate trap positioning near altars when enemy carriers approach (a larger, riskier change).
Switch left off; zip unchanged (v26).

### 2026-10-22: B3 respawn denial measured, neutral (slower wins)

Built behind `STARVE` (lead >= 100 at round >= 600, enemy-side gem group just captured, bag <= 30,
even-numbered bodies only; leave on HP < 40%, outmatched, lead < 50, 300 rounds, or round 1950).
vs v26, 70 games each: mirror 35, zmeta 59 (v26 59), zpoke 51 (52), zhor 66 (66), zrush 58 (58).
It ran a lot (279 sits in 94 games, median 70-240 rounds; about a third ended outmatched), but only
in games we already led, where it cannot add wins: it made those wins 35-65 rounds slower
(average win round zmeta 1362 -> 1429, zpoke 1420 -> 1459, zhor 1354 -> 1388, zrush 1421 -> 1464).
No loss was turned into a win. Switch left off; zip unchanged (v26).

Takeaway across A2, A3, A4, A5, B2, B3: every mechanism the probes confirmed is real, but none
moves results against the current opponent set, because each either triggers rarely (A3, A4, B2)
or only in games already decided (B3), and the passive ones (A5) invite punishment. The losses
that remain are decided earlier (round 300-700 collection lead and fights), which is where the
next experiments should aim.

### 2026-10-22: focus stickiness and Willow capture yield measured, neutral

Code-review follow-ups, both behind switches (off). vs v26 baselines zmeta 59, zpoke 52, zhor 66, zrush 58 (sum 235):
- `FOCUS_STICKY` (+bonus in fight_enemies for the enemy hit within the last 2 rounds): bonus 0.3 ->
  58/49/67/57 = 231, mirror 34/70; bonus 1.0 -> 58/49/67/61 = 235, mirror 36/70. Neutral.
- `WILLOW_YIELDS` (non-Vesper gem rewards go to a non-Willow ally near; ladder v25: Willow lost 17% of
  collected gems to champions vs Vesper 4%): 57/49/64/61 = 231, mirror 36/70. Willow collected
  116 -> 65 gems/game locally but our gems lost to champions barely moved; slightly negative.
Second review: altar flip-flop already handled by any_safe; spawn-heal loop impossible (spawn heals
to full at that turn's end); Prism never drafted on the ladder; ZERO_FEED is off. Zip unchanged (v26).

### 2026-10-23: review archetypes built as adversaries, neither exploit lands

Forks of zmeta with one draft (Vendetta, Ren, Varg, Stellar, Ryth), switch ADV_ROLE: zven control,
zdip altar dipper (Ren/Vendetta walk within 3 of an altar every ~40 rounds, our-side altars first,
alternating on 2-altar maps), zamb bush ambusher (from r120 Vendetta, plus Ren on >3-champion maps,
lurks in the bush nearest our approach to our main altar, hunts bags >= 10 or tribute channels).
v26 (kbase), 70 games each: zven 60, zdip 68, zamb 68. Our gems lost to champions per game 18.4 /
25.8 / 14.3; tributes per game 25.2 / 25.2 / 24.5. The dipper costs us ~7 gems a game but no
tributes (no banking deadlock); the ambush posts feed kills. Both behaviours weaken the attacker
more than they hurt us. No bot change.

### 2026-10-23: red-team review 1 measured; v27 = 3-champion draft fix

Switches on the current source (base 226 on zmeta/zpoke/zhor/zrush; 70 games each):
DASH_THREAT 225 (zhor 63=63), LOCK_FIX 229 but zlock2 59 vs 65 (rejected), WARD_ALTAR 224,
FIGHT_SIM_OUTMATCHED + stun-timing fix 228 (mirror 38/70, marginal). DRAFT3=2 (3-champion maps force
only Vesper+Tavi, scoring then picks Varg; ladder v25 won 43% on 3-champion maps vs 55% on 5):
125/132 vs 121/132 over 11 opponents on the 6 local 3-champion maps, mirror 8/12. DRAFT3=1 worse.
Also fixed a read of a destroyed temporary in break_channels (`const auto& ab = me.abilities()[i]`).
v27 = v26 source + DRAFT3=2 + that fix: zmeta 62 (59), zpoke 52 (52), zhor 67 (66), zrush 60 (58)
= 241 vs 235; all 232 games off 3-champion maps identical to v26; 3-champion games 44/48 vs 38/48;
mirror 37/70. kessoku.zip rebuilt from bots/v27 (v26 kept as bots/kbase).

### 2026-10-23: red-team review 2 (decision-logic A-F) measured on v27, none ship

v27 base: zmeta 62, zpoke 52, zhor 67, zrush 60 = 241. Variants (sum, mirror vs v27):
A xwin (winning bag ignores embargo and the mid-camp gate) 237, 35; F xesc (escape marks nearby
altars hot instead of a global embargo) 236, 34; B xcast (camp spells before walking when nothing is
in basic reach) 226, 38 (zpoke 44, zhor 59); C xhold (drop a capture held >12 rounds with an enemy
adjacent) 238, 35; D xmarg (camp-fight reserve = retreat floor + 5%) 220, 27; E xpart (unseen group
members at static share) 223, 39. A and C are within re-roll noise; B, D, E clearly worse. Zip stays v27.
v28 = v27 + fix A (winning bag banks first, ignores the embargo and the mid-camp gate), shipped on the
user's call as a correctness fix: identical to the measured xwin (237 vs 241, mirror 35/70). Of 280 games,
243 identical and 37 changed; most changed wins just end a few rounds earlier. The 3 games lost (01the_farm,
01big_world, 00eight vs zpoke) diverged at rounds 104-1839 with no bag able to win, i.e. fuel re-roll noise,
not the fix. kessoku.zip = v28 (v27 zip kept in scratchpad).

### 2026-10-24: v28 on the ladder (uploaded as "v27") and why we lose

1220 ranked games 2026-10-22 19:40 -> 2026-10-24 13:00 UTC (v26 period before: 680 games).
Overall 50% (v26 48%); 3-champion maps 44% (37%), 4: 66% (53%), 5: 46% (48%). Rank 232, rating 1632;
49% vs the 1600-1750 band where nearly all games are. Worst maps: monolith 2/30, lost_world 3/33,
lanes 4/36, collision 3/25, starfish 3/22, contest 6/33, elkring 7/37, great_wall 9/42; locally v28
wins most of these, and 41/50 on the 5 newly pulled maps (now in maps/, 40 total).
469 summaries (scratchpad lad28/): losses are fights. Collected equal at r300 (median gap 0), behind
at r600 in 61% and r1000 in 80% of losses. Our deaths 17.5/game in losses vs 6.3 in wins, from the
start (2.1 before r250 vs 0.8); 97% untraded (no enemy death within 6 rounds), 78% isolated. Killers:
Vesper, Heart of Ruin, Marcella, Vendetta, Ryth; most common enemy draft is exactly those (59 games,
46%). Our Varg, Tavi, Willow die 3.7-3.8 times a game each in losses.
Ladder-meta adversary on our own engine (bots/zdive: that draft, Heart+Vendetta hunt anything in
sight; zdive0 draft only): v28 wins 67/80 and 58/80 with only 2.5-3.7 deaths a game -> our engine
playing their draft does not reproduce ladder pressure; local tests cannot measure anti-pick-off fixes.

### 2026-10-24: ladder loss replays read death by death

Tooling: scratchpad lad28/rep/rp.js drives the visualiser engine wasm (engine_v1_0_3.wasm, taken
from the cambc 3.0.5 wheel run with HOME in the scratchpad; the installed 3.0.4 only ships 1.0.2,
which rejects ladder replays with error 11) from Node: Game_FromReplayFileBytes, Timeline_Seek,
ReadTimelineState (40152-byte snapshot: champions at 196 + 252*k with team/type/x/y/hp/max/alive/
gold/gems/kills, camps at 4228 + 28*k). deaths.js binary-searches each death round from the
summary's kill events and reads the state 10/5/2/0 rounds before.
1065 of our deaths in 35 lost v28 games: 10 rounds before death the victim is at 95% HP (median),
86% already have an enemy within 8; HP then drains to 66% at -5 and 41% at -2 (only 20% die from
>= 80% HP two rounds out). Only 7% carry 20+ gems, 15% stand by a camp, 30% die within 6 tiles of
our spawn. Local numbers at -10: we outnumber 42%, even 30%, outnumbered 28% -> we lose fights we
should not take, slowly. OUTMATCHED = 1.25 keeps us in fights we narrowly lose, and side_power counts
enemy dps as strength + spell/8 (no stuns, dash landings, Heart's missing-health bonus).
Items: winners against us buy Power Strength (66/game) and Bruiser shards/emblems (52 Str, 25 HP, 17
Focus; Bruiser emblem = 5 + 1 of each other stat = 7 shards for 150 gold, Power = 6); we never buy
Bruiser. With our 1:1 health/strength build the stat totals are nearly equal; the real item gap is
gold volume (their 8.9k vs our 4.8k in losses), largely a consequence of the kills.
Draft ideas tested on 40 maps (80 games/opponent, v28 327/400): golems as hostile 328 (mirror 41/80),
Heart of Ruin as 4th pick 309 (mirror 44/80) -> neither ships.
Anti-pick-off variants on v28, 40 maps x 2 sides (v28 327/400 on zmeta/zpoke/zhor/zrush/zdive0):
ptrend (lost >= 20% max HP in 5 rounds and below every nearby enemy's HP share -> outmatched) 319,
mirror 41/80; OUTMATCHED 0.9 305, mirror 37; OUTMATCHED 0.7 278, mirror 37. Retreating earlier gives
up farming and does not even cut deaths (pk07 vs zpoke 720 deaths vs 668): fleeing champions get run
down. Replays again: 61% of victims have an ally within 8 two rounds before death but only 37% within
4, and 97% of deaths are untraded -> allies are near but do not join the fight. Local opponents never
punish the current behaviour, so none of this is measurable locally; the ladder is the only test.

### 2026-10-24: cambc 3.0.5 (engine 1.0.3) and a ladder-faithful adversary (bots/zgank)

Upgraded cambc 3.0.4 -> 3.0.5 (SDK refreshed; API unchanged; 3.0.4 SDK backed up in scratchpad).
v28 on engine 1.0.3 scores identically to 1.0.2 vs every bot, so the local/ladder gap is opponent behaviour.
Stun scan (222 ladder deaths, every step of the last 12 rounds): victims keep moving (median 10 moves in
12 rounds), stunned at some point in 57% but a small share of the time, 0-1 enemies adjacent, losing ~10%
max HP per round: they flee and are run down; ranged champions cannot move and shoot in one turn, so the
fleeing deal no damage back.
bots/zgank = v28 engine + ladder dive draft (Heart, Vesper, Marcella, Ryth, Vendetta / Ren) + Bruiser and
Power Strength items, no passive emblems + chase: pursue any visible enemy within 6 whose HP share is
below ours when not outmatched. (v1 hunted anything within 9 and collapsed its own economy.)
v28 vs zgank: 44/80 (ladder 50%); our deaths 8.3 in wins / 18.8 in losses (ladder 7.6 / 18.3); 92% of our
deaths untraded (ladder 97%); per-map win-rate correlation with the ladder 0.37; the worst ladder maps
(monolith, lanes, lost_world, collision, starfish, contest) are 4/12 locally. zgank is the test bed for
fight fixes from now on.

### 2026-10-24: fight fixes measured against zgank -> v29

On v28, 40 maps x 2 sides (80 games each; v28: zgank 44, field zmeta/zpoke/zhor/zrush/zdive0 327/400):
- STAND_SHOOT (escape(): when a step away leaves us inside some chaser's next-turn reach - melee 2
  (+2 dash), ranged 3 (+1 reset) - and home is over 2 tiles off, fight back instead): zgank 45,
  field 311, mirror 40 -> worse alone.
- CONVERGE (before farming: a visible enemy within 9 that is within 4 of a teammate, our side_power
  there >= theirs, us above 50% HP with < 30 gems -> walk in and attack): zgank 52, field 330, mirror 48.
- Both: zgank 51, field 338 (zmeta 70 =, zpoke 62 +6, zhor 74 -1, zrush 71 +3, zdive0 61 +3), mirror 49/80.
  vs zgank 12 games flipped to wins, 5 to losses; lanes 0/2 -> 2/2, collision 1/2 -> 2/2.
v29 = v28 + both; kessoku.zip rebuilt (v28 zip kept in scratchpad). Ladder baseline to beat: v28 50%.

### 2026-10-25: Plan_v29 C1-C5 implemented and measured (focused tests), nothing ships

All in bots/v30 as Cfg switches, OFF = v29 (80/80 identical games vs zmeta). New adversaries: bots/zmono2
(v29 + MONOLITH_FIGHTS + MONOLITH_WHEN_DOMINANT; v29 beats it only 43/80) and bots/zspawn (zgank + Heart
and Vendetta camping the enemy spawn exit on maps with >= 80% of gems in monoliths, from round 150).
Focused A/B (variant vs v29 on the targeted maps only; v29 baselines from its full-pool runs):
- C1 CAMP_DANGER (awake camps of other groups are no-go tiles): full field 364 vs 389, mirror 37/80, and
  starfish side-B deaths unchanged (48 -> 46, 44 -> 58). Real cause: ~half the side-B deaths are camp kills
  at the two altars inside the centre elk herd's reach (tiles 24-27,19-21).
- C1b ALTAR_CAMP_WAIT (altars inside an awake herd's reach are threatened; all hot -> wait outside):
  29 vs 33 on starfish/hooks/shortcut/broken_curve/boss_battle. Old BURST_RETREAT_MULT 1.0: 31 vs 33.
- C2 TEAM_CLOSEOUT (visible allies' bags) 48 vs 48; CLOSEOUT_MARGIN 150: 48 vs 48 (12 close maps).
- C3 BOSS_ALTAR_OPEN 10 vs 10 on boss_battle; never fires locally (traced: nobody kills the boss, not even
  zmono2). C3 + BOSS_RUSH_BAG 100: 0 vs 10 (idle carriers lose the gold tiebreak).
- C4 on 9 monolith maps vs zmono2/zgank/zmeta: MONOLITH_FIGHTS 34, WHEN_DOMINANT 33, mono-only (share 0.99)
  33, mono vulture (VULTURE, MIN_HP 1e9) 34, MONO_QUIET 36 vs v29 34; but MONO_QUIET mirror 20/44.
- C5 SPAWN_REGROUP 6 vs 7 on contest/stampede vs zspawn/zgank/zmeta. Old HELP_CALLS 16 vs 17 (invasion maps).
- Combined TEAM_CLOSEOUT + BOSS_ALTAR_OPEN + MONO_QUIET on 22 maps: zgank 25/27, zmeta 36/38, zmono2 23/24
  (v30c vs v29), mirror 19/44 -> not shipped. kessoku.zip stays v29.
C6 not built (plan: measure v29 on the ladder first).

### 2026-10-25: first v29 ladder read (95 games, 18:10-21:10 UTC 24 Oct)

v29 45% (43/95) vs v28 50% over 1220; v28's per-map rates re-weighted to v29's map mix predict 52%, and
v29's opponents are slightly weaker (mean current rating 1631 vs 1658). Rank 232 -> 254, rating 1632 -> 1618.
Deaths per loss 18.5 (v28 16.4), per win 7.6 (6.1); traded 7% (5%); isolated 81% (82%). C6: our deaths
on our own half 7.9/game (6.6), enemy deaths on our half 2.5 (2.0); gems stolen from our clears 35.5/game
(34.5), we steal 27.3 (21.9). About 1.4 standard errors below expectation: leaning negative, not conclusive.
Prime suspect STAND_SHOOT (alone it was worse locally: field 311, mirror 40/80); CONVERGE alone was zgank
52, field 330, mirror 48/80. Spawn geometry for all 40 maps: scratchpad lad29/geo.json (from bots/zgeo).

### 2026-10-25: C8 turn priority measured, dropped; tools/sprt.py

tools/sprt.py: paired early-stopping A/B (same shuffled map/side/opponent games for variant and base, Wald
SPRT on discordant games, H1 P(+) = 0.65, alpha = beta = 0.05, results cached per source hash).
C8 PRIORITY_ORDER (set_priority verified working: tiers read back a round later) on 12 PvP maps vs
zgank/zdive0/zpoke, 72 games each, base v30: fighters first 43 vs 47 (+8 -12), fighters last 48 vs 47
(+14 -13). Turn order within the team does not help -> dropped.

### 2026-10-25: R1 (isolation) and R3 (assignment) measured with tools/sprt.py, none ship

Dev source bots/v32 = v30 + switches ISO_PATH, ISO_TARGET, R3_ASSIGN (all OFF = v30).
- R1 ISO_PATH (while an enemy seen/remembered is within 10, route only through tiles within 4 of an ally,
  else normal routing): 12 PvP maps vs zgank/zdive0/zpoke, 72 games: 48 vs 47 (+7 -6) -> neutral.
- R1 ISO_TARGET (score x0.5 for a group with an enemy near and no ally within 6): 38 vs 44 (+9 -15), SPRT reject.
- R3_ASSIGN (match us + 3 nearest visible allies to our top 8 groups, squads take req+1 bodies), 12 theft
  maps vs zgank/zmeta/zpoke: exhaustive search + second scoring pass ran out of fuel 1535 turns a game
  (v30: 14) -> 9 vs 22; greedy matching with value/time estimates (fuel 35/game) still 26 vs 34 (+3 -11),
  SPRT reject. Without shared vision each body solves a different assignment; claims coordinate better.

### 2026-10-25: R2 fitted fight model -> v31 candidate (FIT_FIGHT, threshold 0.20)

Data: v30 + a per-skirmish-round feature log vs zgank/zdive0/zpoke, 40 maps x 2 sides (240 games, 223K rows,
4.4% followed by our death within 8 rounds). Logistic model (tools/fight_build.py, tools/fight_fit.py; split by
game): test AUC 0.889 vs 0.816 for the power ratio and 0.705 for the OUTMATCHED flag. Strongest terms: nearest
enemy distance, log dps ratio, our hp share, enemy hp share.
FIT_FIGHT (outmatched = P(die) >= threshold) vs v30 with tools/sprt.py: 0.025 and 0.043 24-32 (reject),
0.09 46-47, 0.20 50-47 on 12 PvP maps and 67-63 on 12 other maps vs zmeta/zhor/zrush, mirror 23/40 (more
deaths, 553 vs 421, but more wins), 0.35 37-44. Lesson again: better prediction used to flee more loses; used
to stay in fights unless death is likely, it gains a little everywhere. v31 = v30 + FIT_FIGHT 0.20 (bots/v31).
Part 2 of R2 (policy search) not built.

### 2026-10-25: v30 matches from MFF1 on (40 games, 22:23-22:41 UTC 24 Oct)

20 unranked vs MFF1 (Cassi&Issac, Varg, Vesper, Ryth, Stellar): 8/20. gemfight 4/4, great_wall 2/4,
monolith 1/4, starvation 1/4, gold_rush (3 champions) 0/4 with our deaths 23-30 vs their 1-2.
Deaths per loss 26.7, our deaths on our own half 8.2/game, traded 2%.
20 after MFF1 (ranked slop 3/5, Ascendance 2/5; unranked Tozo's Disciples 2/5, Milk and Potatoes 1/5): 8/20,
deaths/loss 10.2, collected 824 vs 796 -> mostly close races, not pick-offs.
New failure: 00reverse_spiral spawn standoff (2 of 3 games): the two spawns are adjacent in the centre, our
champions see enemies 2-4 tiles away from round 2, the outmatched/lethal branch calls escape(), which returns
"done" while we stand on our spawn (heal), so all four sit on the spawn for 2000 rounds (0 gems, 0 gold, no
faults); the opponent idles too after 2 clears and the full tie goes to side B ("tiebreak_second_team").
Earlier: one such game in 21 v28 games (we were side B and won it). Fix candidate: when no enemy can enter
our spawn and we have taken no damage for N rounds, ignore outmatched/escape on the spawn and farm.
Standoff follow-up (same day): my first diagnosis was wrong - v31's escape() has no "stay on spawn" return (only
the low-HP retreat does, and the champions were at full HP). The freeze cause is still unknown; the speculative
SPAWN_STANDOFF patch was discarded untested and kessoku.zip stays v31. Next: reproduce on 00reverse_spiral with a
trace of g_stage per turn for a champion standing on the spawn.

### 2026-10-25: user's 7 bugs + 7 ideas checked (code, SDK, rules, probe, ladder)

Probe (v31 copy printing ability flags and failed casts, 6 games vs zgank):
- Ren's, Tavi's and Prism's damage-and-stun spells are is_cc() only (not is_damage), so assess_threat never adds
  their damage (Ren 75-82, Tavi 154) to f.spell; damage_amount() returns it for any kind (also Heart's dash 150-200).
- Failed casts all came after moving in the same turn ("Excludes walking": Tavi slot 1, Stellar both slots, also
  Prism/Ren/Marcella/Ryth/Cassi): Stellar 47, Tavi 25 over 6 games (~12 lost spells a game).
Rules: Varg's basic attacks splash Strength onto everything within 1 of the target; Vendetta's kills (camps too)
reset her cooldowns; tributing a locked altar auto-attacks the lock; placing a lock cancels enemy channels; any
spawn tile heals to full at turn end; shared memory is 8 bytes.
Ladder v28 (1220 games): fuel-outs 10.5/game, almost all after round 100 (rounds 0-5: 0.7/game); 00lanes 101.6/game,
01big_world 81.5, 01yellow_brick_road 33.5, 01elk_arena 29.7, 01boss_battle 27.9. Our deaths: 6.8% standing in a
bush, 30% within 1 tile of one.
Verdicts: true and cheap to test - CC spell damage in threat, cast exclusive spells before moving in fights, Varg
splash targeting, multi-camp factor 0.75 vs 0.65; worth a test - escape into bushes; already in v31 - emergency
lock (try_lock_altar), dash fields; false or measured - ability_dash fields (exist), lock-attack turn waste
(identical cost), dead claims (DEAD_CLEARS_CLAIM measured worse), set_priority (C8 neutral), altar ward (neutral),
Tavi sell/rebuy heal (spawn already heals to full), draft precompute for turn 1 (early fuel-outs negligible).
Biggest new lead: fuel exhaustion on lanes / big_world.

### 2026-10-25: fuel profile + the four cheap fixes, nothing ships (zip stays v31)

Fuel profile (tools/fuel_profile harness on v31 vs zgank/zmeta): fuel-outs 78-186 a game on 00lanes/01big_world
(ladder: 102/82). Per turn observe() costs ~13-16K; the overruns come from spikes in choose_target (to 57-83K),
farm (75-83K), move_to (45-60K), bank (to 61K). The existing exact-optimisation switches halve fuel-outs on the
6 worst fuel maps (FUEL_GUARD: lanes 119 -> 61, big_world 76 -> 45; with OBS_SKIP_FAR + BANK_CACHE + MOVE_SCRATCH:
46 / 57) but win slightly less vs zgank/zmeta/zpoke (24 and 23 vs 27 of 36): a fuel-out only delays the turn's
decision (the engine resumes it), while skipping a re-score makes a worse one. Fuel is not why lanes is lost.
Cheap fixes (bots/v34, switches OFF = v31), tools/sprt.py vs v31: CC_THREAT 27-35 (reject: more threat = more
retreat); CAST_FIRST 52-50; VARG_SPLASH 59-57; MULTI_CAMP_TAKEN 0.75 60-57; the last three together 41-48 on PvP
maps (reject), 57-57 on camp maps, mirror 21/40 -> individual gains were noise.

### 2026-10-25: 00reverse_spiral standoff traced and fixed -> v35

Reproduced in the v31 mirror; per-turn trace of champions on the spawn (stage, can_move, attacked):
1. converge() picked enemies standing on their own (adjacent) spawn - unreachable, healed to full every turn - and
   returned "done" although it could not act, ending the turn;
2. with that fixed, ranged champions (Tavi, Willow) shot those spawn-sitters every turn; ranged champions share one
   allowance for moving and attacking, so can_move() was false and move_to() failed every turn.
v35 = v31 + CONVERGE_FIX (converge ignores enemies on their spawn) + SPAWN_TARGET_SKIP (fights ignore enemies on their
spawn unless killable this turn). Each alone keeps the standoff. CONVERGE_ACT_ONLY (end converge's turn only if it
acted) fixed it too but cost 113-122 elsewhere, so it is OFF. Results: reverse_spiral games all real again; vs v31 on
all 40 maps x zgank/zmeta/zpoke/zdive0 243-243 (+5 -5); mirror 43/80. kessoku.zip = v35.

### 2026-10-25: why 00lanes is lost (v28 ladder: 4/36)

Map: 90x30, three horizontal lanes (y~4, 13, 25) split by bush walls; spawns at the far ends of the middle lane;
altars along every lane near both ends; every camp in the centre (x 35-54). The bottom lane is the gem lane (11-gem
cluster+wolf groups and a 22-gem elk herd); the top lane's centre groups are 0-gem, 40-gold clusters.
36 ladder games: collected 157-141 at r300 (ahead), 328-368 at r600, 748-1062 final; our deaths 17.8 vs 3.1 a game,
15.4 of them in the bottom lane, mostly at x 30-39 (the approach to and the camps on our side); none to camps.
Not fuel: only 6% of those deaths follow a fuel-out of the victim within 3 rounds (fuel-outs ~100/game there).
Not bush ambushes: 5% of bottom-lane deaths have an enemy within 6 in a bush; 8% are next to an altar; 20% carry 10+.
Repeats: 21% die within 8 tiles of their own previous bottom-lane death, median gap 167 rounds (DEATH_AVOID lasts
150). DEATH_AVOID_REPEAT (avoid range 8 for 400 rounds after a repeat death; dev bots/v36, OFF) was neutral locally
(244-243 over 320 games, deaths 8.2 -> 7.9) and did not help the one local game with the pattern -> not shipped.
Cause (10 replays, champions on the lanes every 50 rounds, r300-1100): enemies stack the gem lane, 3.38 bodies vs
our 2.37; we have fewer there in 63% of samples (more in 21%); we keep ~0.62 bodies in the gold-only top lane
(they 0.15) and have ~1 fewer body on the lanes overall (more of ours dead or at spawn). group_score values a group
at gems + 0.12 x gold (CLUSTER_VALUE 1.0), so a 0-gem, 40-gold, 240-HP cluster is worth 4.8 for a near-instant kill.
Next experiment: concentrate on contested gem groups (lower value for 0-gem groups while enemies hold a gem lane,
or a CONVERGE-style pull to the lane where enemies are seen); local bots do not stack lanes, so it needs a stacking
adversary or a ladder trial.
Lanes follow-up (same day): bots/zstack (zgank valuing only gem groups) reproduces the lanes losses - v35 loses
00lanes from both sides (16 and 19 bottom-lane deaths); zgank only from side B. But zstack does not outnumber us much
in the gem lane locally (2.6 vs our 2.3-2.8 bodies; fewer in 4 and 8 of 17 samples) and still wins those fights.
ZERO_GEM_DISCOUNT (0-gem groups x0.3 while an enemy was seen in the last 100 rounds) vs v35 on all 40 maps x
zstack/zgank/zmeta/zpoke: 143-150 (+5 -12), SPRT reject; on lanes still lost to zstack-A (11 bottom deaths, was 16)
and zgank-B (21, was 15). Conclusion: lanes is lost on fight quality in the gem lane, the same root as the other
ladder losses, not on lane allocation. Not shipped; zip stays v35. zstack kept as an adversary for lanes.
