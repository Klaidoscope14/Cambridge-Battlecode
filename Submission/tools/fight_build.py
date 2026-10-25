"""R2 data: skirmish rows from a logging bot (v30 + an "FL ..." line per skirmish round, see MetaResearch 2026-10-25)
played with `cambc run-batch --log-limit 30000000` into DIR/g/*.repl26a + *.json; labels = died within 8 rounds.
usage: copy into DIR (the scratchpad r2 folder) and run there; writes DIR/data.json."""
import json, glob, os, zipfile, math, re
S = os.path.dirname(os.path.abspath(__file__))
NAMES = {'Ryth': 0, 'Vesper Vale': 1, 'Vendetta': 2, 'Cassi': 3, 'Issac': 4, 'Stellar': 5, 'Prism': 6, 'Marcella': 7, 'Willow': 8, 'Ren': 9, 'Varg': 10, 'Tavi': 11, 'Heart of Ruin': 12}
def tid(n):
    m = re.match(r'Unknown champion \((\d+)\)', n)
    return int(m.group(1)) if m else NAMES.get(n, -1)
rows = []
for f in glob.glob(S + '/g/*.json'):
    k = os.path.basename(f)[:-5]; side = k[-1]; us = 'team' + side
    d = json.load(open(f))
    deaths = {}
    for e in d['events']:
        if e['kind'] != 'kill': continue
        for en in e['entries']:
            tg = en['target']
            if tg.get('kind') == 'champion' and tg.get('team') == us:
                deaths.setdefault(tid(tg.get('name', '')), []).append(en['timestamp']['round'])
    try:
        txt = zipfile.ZipFile(f[:-5] + '.repl26a').read(f'team-{side.lower()}.stdout').decode('latin1').replace('\x00', '')
    except Exception:
        continue
    for line in txt.splitlines():
        if not line.startswith('FL '): continue
        p = line.split()
        if len(p) < 19: continue
        r, kind = int(p[1]), int(p[2])
        v = list(map(float, p[3:]))
        ohp, odps, on, ehp, edps, en, eshare, stun, dash, reset, ranged, share, burst, myhp, nearest, outm, gems = v[:17]
        died = any(r < t <= r + 8 for t in deaths.get(kind, []))
        rows.append(dict(game=k, r=r, kind=kind, ohp=ohp, odps=odps, on=on, ehp=ehp, edps=edps, en=en, eshare=eshare, stun=stun,
                         dash=dash, reset=reset, ranged=ranged, share=share, burst=burst, myhp=myhp, nearest=nearest, outm=outm, gems=gems, died=died))
json.dump(rows, open(S + '/data.json', 'w'))
print(len(rows), 'skirmish rows,', sum(r['died'] for r in rows), 'followed by a death within 8 rounds;', len({r['game'] for r in rows}), 'games')
