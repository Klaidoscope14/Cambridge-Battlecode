// node deathctx.js <match zip> <team 0|1> : context of every death of team T, sampled every 2 rounds.
// For each death: the dead champion's hp/gems/ally distance and nearby enemies 2, 6 and 12 rounds before.
const R = require('./rp.js');
const [file, teamS] = process.argv.slice(2); const T = +teamS;
const E = R.load(__dirname + '/engine_v2_0_0.wasm');
const G = R.openReplay(E, require('child_process').execFileSync('unzip', ['-p', file, 'replay.repl26a'], { maxBuffer: 1 << 30 }));
const NAMES = 'ryth vesper vendetta cassi issac stellar prism marcella willow ren varg tavi heart'.split(' ');
const cheb = (a, b) => Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y));
let pos = 0; const hist = []; const out = [];
const last = R.read(E, G, G.size - 1).round;
const at = r => { let lo = pos, hi = G.size - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (R.read(E, G, m).round < r) lo = m + 1; else hi = m; } pos = lo; return R.read(E, G, lo); };
const snap = (s, idx) => {
  const c = s.champs.find(x => x.idx === idx); if (!c || !c.alive) return null;
  const al = s.champs.filter(x => x.team === T && x.alive && x.idx !== idx && !(NAMES[x.type] === 'cassi' && NAMES[c.type] === 'issac') && !(NAMES[x.type] === 'issac' && NAMES[c.type] === 'cassi'));
  const en = s.champs.filter(x => x.team !== T && x.alive && x.max > 0);
  return { r: s.round, hp: +(c.hp / c.max).toFixed(2), gems: c.gems, x: c.x, y: c.y,
    ally: Math.min(99, ...al.map(a => cheb(a, c))), allies6: al.filter(a => cheb(a, c) <= 6).length,
    enemies6: en.filter(e => cheb(e, c) <= 6).map(e => NAMES[e.type]), enemyHp6: +en.filter(e => cheb(e, c) <= 6).reduce((a, e) => a + e.hp / e.max, 0).toFixed(2) };
};
let prevAlive = {};
for (let r = 2; r <= last; r += 2) {
  const s = at(r); hist.push(s); if (hist.length > 8) hist.shift();
  for (const c of s.champs.filter(x => x.team === T && x.max > 0)) {
    if (prevAlive[c.idx] && !c.alive) {
      const back = k => { const h = hist[hist.length - 1 - k]; return h ? snap(h, c.idx) : null; };
      out.push({ round: s.round, who: NAMES[c.type], b2: back(1), b6: back(3), b12: back(6) });
    }
    prevAlive[c.idx] = c.alive;
  }
}
console.log(JSON.stringify(out));
