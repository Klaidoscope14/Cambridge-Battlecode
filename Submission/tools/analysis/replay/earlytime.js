// node earlytime.js <match zip> <team> <groups json> <ownSpawn json> <altars json> : time split of team T's champions, rounds 2-300.
const R = require('./rp.js');
const [file, teamS, gj, oj, aj] = process.argv.slice(2); const T = +teamS;
const groups = JSON.parse(gj), OWN = JSON.parse(oj), ALT = JSON.parse(aj);
const E = R.load(__dirname + '/engine_v2_0_0.wasm');
const G = R.openReplay(E, require('child_process').execFileSync('unzip', ['-p', file, 'replay.repl26a'], { maxBuffer: 1 << 30 }));
const MAXHP = [1350, 2400, 120, 120, 20000, 5000];
const cheb = (a, b) => Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y));
const near = (p, ts) => Math.min(99, ...ts.map(t => Math.max(Math.abs(p.x - t[0]), Math.abs(p.y - t[1]))));
const tileGroup = new Map(); groups.forEach((ts, gi) => ts.forEach(t => tileGroup.set(t[0] + ',' + t[1], gi)));
let pos = 0;
const at = r => { let lo = pos, hi = G.size - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (R.read(E, G, m).round < r) lo = m + 1; else hi = m; } pos = lo; return R.read(E, G, lo); };
let campGroup = null; const cnt = {}; let n = 0; const prev = {};
const add = k => { cnt[k] = (cnt[k] || 0) + 1; };
for (let r = 2; r <= 300; r += 2) {
  const s = at(r); if (s.round < r - 2) break;
  if (!campGroup) { campGroup = new Map(); for (const k of s.camps) if (k.x >= 0) campGroup.set(k.idx, tileGroup.get(k.x + ',' + k.y)); }
  const live = s.camps.filter(k => k.x >= 0);
  const deadGroup = gi => !live.some(k => campGroup.get(k.idx) === gi);
  for (const c of s.champs.filter(x => x.team === T && x.max > 0)) {
    n++;
    const p = prev[c.idx]; prev[c.idx] = { x: c.x, y: c.y, gems: c.gems };
    if (!c.alive) { add('dead'); continue; }
    const gi = tileGroup.get(c.x + ',' + c.y);
    const dCamp = Math.min(99, ...live.map(k => cheb(k, c)));
    const hurt = live.some(k => cheb(k, c) <= 4 && k.hp < MAXHP[k.type] - 1);
    const still = p && p.x === c.x && p.y === c.y;
    if (dCamp <= 2) add('within2_of_live_camp');  // Observations.md "farming" definition
    if (near(c, OWN) <= 1) add('spawn');
    else if (gi !== undefined && deadGroup(gi)) add('capture');
    else if (hurt) add('camp_fight');
    else if (near(c, ALT) <= 1 && (c.gems > 0 || (p && p.gems > c.gems))) add('altar');
    else if (dCamp <= 6 && still) add('idle_near_camp(wait)');
    else if (dCamp <= 2) add('next_to_sleeping_camp');
    else if (c.gems >= 20) add('walk_with_bag');
    else add('walk');
  }
}
const out = {}; for (const k in cnt) out[k] = cnt[k] / n; out.n = n;
console.log(JSON.stringify(out));
