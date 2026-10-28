// node deathctx2.js <match zip> <team 0|1> <groups json: [[ [x,y],... ], ...]> <ownSpawn json> <oppSpawn json>
// Per death of team T: victim/ally/enemy state at t-8, t-6, t-4, t-2 (sampled every 2 rounds).
const R = require('./rp.js');
const [file, teamS, gj, oj, ej] = process.argv.slice(2); const T = +teamS;
const groups = JSON.parse(gj), OWN = JSON.parse(oj), OPP = JSON.parse(ej);
const E = R.load(__dirname + '/engine_v2_0_0.wasm');
const G = R.openReplay(E, require('child_process').execFileSync('unzip', ['-p', file, 'replay.repl26a'], { maxBuffer: 1 << 30 }));
const NAMES = 'ryth vesper vendetta cassi issac stellar prism marcella willow ren varg tavi heart'.split(' ');
const MAXHP = [1350, 2400, 120, 120, 20000, 5000];
const cheb = (a, b) => Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y));
const near = (p, ts) => Math.min(...ts.map(t => Math.max(Math.abs(p.x - t[0]), Math.abs(p.y - t[1]))));
const tileGroup = new Map(); groups.forEach((ts, gi) => ts.forEach(t => tileGroup.set(t[0] + ',' + t[1], gi)));
let pos = 0; const last = R.read(E, G, G.size - 1).round;
const at = r => { let lo = pos, hi = G.size - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (R.read(E, G, m).round < r) lo = m + 1; else hi = m; } pos = lo; return R.read(E, G, lo); };
let campGroup = null;
const pair = (a, b) => (NAMES[a] === 'cassi' && NAMES[b] === 'issac') || (NAMES[a] === 'issac' && NAMES[b] === 'cassi');
function activity(s, c) {  // what a champion is doing in snapshot s
  const live = s.camps.filter(k => k.x >= 0);
  const groupDead = gi => !live.some(k => campGroup.get(k.idx) === gi);
  const gi = tileGroup.get(c.x + ',' + c.y);
  const en = s.champs.filter(x => x.team !== T && x.alive && x.max > 0);
  const ne = Math.min(99, ...en.map(e => cheb(e, c)));
  const hurtCamp = live.filter(k => k.hp < MAXHP[k.type] - 1 && cheb(k, c) <= 4 && MAXHP[k.type] > 120 && k.type !== 2 && k.type !== 3);
  const nearCamp = Math.min(99, ...live.map(k => cheb(k, c)));
  let act = 'walk';
  if (near(c, OWN) <= 1) act = 'spawn';
  else if (gi !== undefined && groupDead(gi)) act = 'capture';
  else if (hurtCamp.length) act = 'campfight';
  else if (nearCamp <= 3) act = 'atcamp';
  return { act, ne, half: near(c, OWN) < 0.8 * near(c, OPP) ? 'own' : near(c, OPP) < 0.8 * near(c, OWN) ? 'away' : 'mid' };
}
const hist = []; const out = []; const prevAlive = {};
for (let r = 2; r <= last; r += 2) {
  const s = at(r);
  if (!campGroup) { campGroup = new Map(); for (const k of s.camps) if (k.x >= 0) campGroup.set(k.idx, tileGroup.get(k.x + ',' + k.y)); }
  hist.push(s); if (hist.length > 6) hist.shift();
  for (const c of s.champs.filter(x => x.team === T && x.max > 0)) {
    if (prevAlive[c.idx] && !c.alive) {
      const rec = { round: s.round, who: NAMES[c.type], steps: {} };
      for (const [lab, k] of [['t8', 4], ['t6', 3], ['t4', 2], ['t2', 1]]) {
        const h = hist[hist.length - 1 - k]; if (!h) continue;
        const v = h.champs.find(x => x.idx === c.idx); if (!v || !v.alive) continue;
        const a = activity(h, v);
        const allies = h.champs.filter(x => x.team === T && x.alive && x.idx !== c.idx && !pair(x.type, c.type));
        let na = null, nd = 99; for (const x of allies) if (cheb(x, v) < nd) nd = cheb(x, v), na = x;
        const en = h.champs.filter(x => x.team !== T && x.alive && x.max > 0);
        rec.steps[lab] = { hp: +(v.hp / v.max).toFixed(2), gems: v.gems, x: v.x, y: v.y, act: a.act, half: a.half, ne: a.ne,
          en6: en.filter(e => cheb(e, v) <= 6).map(e => NAMES[e.type]),
          ally: na ? { d: nd, who: NAMES[na.type], hp: +(na.hp / na.max).toFixed(2), act: activity(h, na).act, ne: activity(h, na).ne } : null };
      }
      out.push(rec);
    }
    prevAlive[c.idx] = c.alive;
  }
}
console.log(JSON.stringify(out));
