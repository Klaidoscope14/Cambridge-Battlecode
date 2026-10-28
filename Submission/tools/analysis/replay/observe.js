// node observe.js <replay> <team 0|1> <spawnA json> <spawnE json>
// Samples every 3 rounds up to r900 and prints per-team behaviour stats as JSON.
const R = require('./rp.js');
const [file, teamS, saj, sej] = process.argv.slice(2); const T = +teamS;
const E = R.load(__dirname + '/engine_v2_0_0.wasm');
const G = R.openReplay(E, require('child_process').execFileSync('unzip', ['-p', file, 'replay.repl26a'], { maxBuffer: 1 << 30 }));
const SA = JSON.parse(saj), SE = JSON.parse(sej);
const cen = t => [t.reduce((a, p) => a + p[0], 0) / t.length, t.reduce((a, p) => a + p[1], 0) / t.length];
const own = T === 0 ? cen(SA) : cen(SE), oth = T === 0 ? cen(SE) : cen(SA);
const cheb = (a, b) => Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y));
const dS = (c, s) => Math.max(Math.abs(c.x - s[0]), Math.abs(c.y - s[1]));
const at = r => { let lo = 0, hi = G.size - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (R.read(E, G, m).round < r) lo = m + 1; else hi = m; } return R.read(E, G, lo); };
const out = { samples: 0, nearAlly: 0, alone8: 0, groups: 0, halfOwn: 0, halfMid: 0, halfAway: 0, bag: 0, atSpawn: 0, dead: 0,
  contact: 0, approach: 0, retreat: 0, hold: 0, contactOutnum: 0, contactAdv: 0, lowHpFight: 0, lowHp: 0,
  retreatHp: [], phase: {} };
let prev = null;
for (let r = 6; r <= 900; r += 3) {
  const s = at(r); if (s.round < r - 3) break;
  const ours = s.champs.filter(c => c.team === T && c.max > 0), theirs = s.champs.filter(c => c.team !== T && c.max > 0 && c.alive);
  const ph = r < 300 ? 'early' : r < 600 ? 'mid' : 'late';
  out.phase[ph] = out.phase[ph] || { samples: 0, nearAlly: 0, away: 0, contact: 0 };
  // connected components of allies within 4 (how many "groups" the team is split into)
  const alive = ours.filter(c => c.alive);
  const seen = new Set(); let comps = 0;
  for (const c of alive) { if (seen.has(c.idx)) continue; comps++; const st = [c]; seen.add(c.idx);
    while (st.length) { const x = st.pop(); for (const y of alive) if (!seen.has(y.idx) && cheb(x, y) <= 4) { seen.add(y.idx); st.push(y); } } }
  if (alive.length) out.groups += comps / alive.length;
  for (const c of ours) {
    out.samples++; out.phase[ph].samples++;
    if (!c.alive) { out.dead++; continue; }
    const na = Math.min(99, ...alive.filter(a => a !== c).map(a => cheb(a, c)));
    if (na <= 4) { out.nearAlly++; out.phase[ph].nearAlly++; }
    if (na > 8) out.alone8++;
    const f = dS(c, own) / (dS(c, own) + dS(c, oth));
    if (f < 0.4) out.halfOwn++; else if (f <= 0.6) out.halfMid++; else { out.halfAway++; out.phase[ph].away++; }
    out.bag += c.gems; if (dS(c, own) <= 2) out.atSpawn++;
    const hpf = c.hp / c.max; if (hpf < 0.35) out.lowHp++;
    const ne = Math.min(99, ...theirs.map(e => cheb(e, c)));
    if (ne <= 5) {
      out.contact++; out.phase[ph].contact++;
      if (hpf < 0.35) out.lowHpFight++;
      const allies5 = alive.filter(a => cheb(a, c) <= 5).length, en5 = theirs.filter(e => cheb(e, c) <= 5).length;
      if (en5 > allies5) out.contactOutnum++; else if (allies5 > en5) out.contactAdv++;
      if (prev) {
        const p = prev.champs.find(x => x.team === T && x.idx === c.idx), ens = prev.champs.filter(x => x.team !== T && x.alive);
        if (p && p.alive && ens.length) {
          const e = ens.reduce((a, b) => (cheb(b, p) < cheb(a, p) ? b : a));
          const d0 = cheb(p, e), d1 = cheb(c, e);
          if (d1 < d0) out.approach++; else if (d1 > d0) { out.retreat++; out.retreatHp.push(Math.round(100 * p.hp / p.max)); } else out.hold++;
        }
      }
    }
  }
  prev = s;
}
console.log(JSON.stringify(out));
