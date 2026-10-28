// node observe2.js <replay> <team 0|1> <spawnA json> <spawnE json>
// Per-champion-type and per-phase behaviour, sampled every 3 rounds to r1200. JSON on stdout.
const R = require('./rp.js');
const [file, teamS, saj, sej] = process.argv.slice(2); const T = +teamS;
const E = R.load(__dirname + '/engine_v2_0_0.wasm');
const G = R.openReplay(E, require('child_process').execFileSync('unzip', ['-p', file, 'replay.repl26a'], { maxBuffer: 1 << 30 }));
const SA = JSON.parse(saj), SE = JSON.parse(sej);
const cen = t => [t.reduce((a, p) => a + p[0], 0) / t.length, t.reduce((a, p) => a + p[1], 0) / t.length];
const own = T === 0 ? cen(SA) : cen(SE), oth = T === 0 ? cen(SE) : cen(SA);
const cheb = (a, b) => Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y));
const dS = (c, s) => Math.max(Math.abs(c.x - s[0]), Math.abs(c.y - s[1]));
const NAMES = 'ryth vesper vendetta cassi issac stellar prism marcella willow ren varg tavi heart'.split(' ');
const at = r => { let lo = 0, hi = G.size - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (R.read(E, G, m).round < r) lo = m + 1; else hi = m; } return R.read(E, G, lo); };
const phaseOf = r => (r < 300 ? 'early' : r < 600 ? 'mid' : 'late');
const blank = () => ({ n: 0, dead: 0, spawn: 0, own: 0, mid: 0, away: 0, nearAlly: 0, alone8: 0, bag: 0, bagMax: 0, hp: 0,
  contact: 0, approach: 0, retreat: 0, hold: 0, adv: 0, even: 0, outnum: 0, appAdv: 0, appEven: 0, appOut: 0, retHp: 0, retN: 0,
  lowFight: 0, farm: 0 });
const per = {}, phase = {}, team = { early: { n: 0, comps: 0, spread: 0 }, mid: { n: 0, comps: 0, spread: 0 }, late: { n: 0, comps: 0, spread: 0 } };
let prev = null, lastRound = 0;
for (let r = 6; r <= 1200; r += 3) {
  const s = at(r); if (s.round < r - 3) break; lastRound = s.round;
  const ph = phaseOf(r);
  const ours = s.champs.filter(c => c.team === T && c.max > 0), alive = ours.filter(c => c.alive);
  const theirs = s.champs.filter(c => c.team !== T && c.max > 0 && c.alive);
  const seen = new Set(); let comps = 0;
  for (const c of alive) { if (seen.has(c.idx)) continue; comps++; const st = [c]; seen.add(c.idx);
    while (st.length) { const x = st.pop(); for (const y of alive) if (!seen.has(y.idx) && cheb(x, y) <= 4) { seen.add(y.idx); st.push(y); } } }
  if (alive.length > 1) { team[ph].n++; team[ph].comps += comps / alive.length;
    let mx = 0; for (const a of alive) for (const b of alive) mx = Math.max(mx, cheb(a, b)); team[ph].spread += mx; }
  for (const c of ours) {
    const key = NAMES[c.type] || 'x'; per[key] = per[key] || blank(); phase[ph] = phase[ph] || blank();
    for (const o of [per[key], phase[ph]]) {
      o.n++;
      if (!c.alive) { o.dead++; continue; }
      if (dS(c, own) <= 2) o.spawn++;
      const f = dS(c, own) / (dS(c, own) + dS(c, oth));
      if (f < 0.4) o.own++; else if (f <= 0.6) o.mid++; else o.away++;
      const na = Math.min(99, ...alive.filter(a => a !== c).map(a => cheb(a, c)));
      if (na <= 4) o.nearAlly++; if (na > 8) o.alone8++;
      o.bag += c.gems; o.bagMax = Math.max(o.bagMax, c.gems); o.hp += c.hp / c.max;
      if (s.camps.some(k => k.x >= 0 && k.hp > 0 && cheb(k, c) <= 2)) o.farm++;
      const ne = Math.min(99, ...theirs.map(e => cheb(e, c)));
      if (ne <= 5) {
        o.contact++;
        const a5 = alive.filter(a => cheb(a, c) <= 5).length, e5 = theirs.filter(e => cheb(e, c) <= 5).length;
        const side = a5 > e5 ? 'adv' : a5 === e5 ? 'even' : 'outnum'; o[side]++;
        if (c.hp / c.max < 0.35) o.lowFight++;
        if (prev) {
          const p = prev.champs.find(x => x.team === T && x.idx === c.idx), ens = prev.champs.filter(x => x.team !== T && x.alive && x.max > 0);
          if (p && p.alive && ens.length) {
            const e = ens.reduce((a, b) => (cheb(b, p) < cheb(a, p) ? b : a));
            const d0 = cheb(p, e), d1 = cheb(c, e);
            if (d1 < d0) { o.approach++; o[side === 'adv' ? 'appAdv' : side === 'even' ? 'appEven' : 'appOut']++; }
            else if (d1 > d0) { o.retreat++; o.retHp += p.hp / p.max; o.retN++; } else o.hold++;
          }
        }
      }
    }
  }
  prev = s;
}
console.log(JSON.stringify({ per, phase, team, lastRound }));
