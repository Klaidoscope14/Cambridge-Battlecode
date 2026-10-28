#!/usr/bin/env python3
"""Per-champion, per-phase detail from summaries: top-10 (rows.json) vs ours (v41+v43). Writes summ_detail.json."""
import os as _os
SUB = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../..'))  # Submission/
import json, os, sys, collections, statistics as st
sys.path.insert(0, SUB + '/tools')
import panel
SUB = SUB
geo = json.load(open(f'{SUB}/tools/data/geo.json')); sp = json.load(open(f'{SUB}/tools/data/spawns.json'))
cen = lambda t: (sum(p[0] for p in t) / len(t), sum(p[1] for p in t) / len(t))
cheb = lambda a, b: max(abs(a[0] - b[0]), abs(a[1] - b[1]))
ph = lambda r: 'early' if r < 300 else 'mid' if r < 600 else 'late'


def kind(g):
    if 'mono' in g['kinds']: return 'mono'
    if g['str'] <= 0: return 'cluster'
    return 'small' if g['str'] <= 40 else 'big'


def mode(m):
    if m not in sp: return 'normal'
    a, e = cen(sp[m]['SPAWN_A']), cen(sp[m]['SPAWN_E']); d = cheb(a, e)
    return 'fight' if d <= 35 else 'race' if d >= 70 else 'normal'


def analyse(rows):
    C = collections.defaultdict(collections.Counter)      # per champion counters
    P = collections.defaultdict(collections.Counter)      # per phase (team level)
    routes = collections.defaultdict(collections.Counter) # first three clears per champion: kind/side
    deaths = collections.Counter(); games = collections.Counter(); M = collections.defaultdict(collections.Counter)
    for r in rows:
        d = panel.summary(r['id'])
        if not d or r['map'] not in geo or r['map'] not in sp: continue
        T = 'team' + r['side'].upper(); O = 'teamB' if T == 'teamA' else 'teamA'
        G = geo[r['map']]['groups']; A = cen(sp[r['map']]['SPAWN_A']); E = cen(sp[r['map']]['SPAWN_E'])
        own, oth = (A, E) if r['side'] == 'a' else (E, A)
        side = lambda x, y: 'own' if cheb((x, y), own) < cheb((x, y), oth) * 0.8 else 'away' if cheb((x, y), oth) < cheb((x, y), own) * 0.8 else 'mid'
        names = [c['name'] for c in d['champions'] if c['team'] == T]
        for nm in set(names): games[nm] += 1
        md = mode(r['map']); M[md]['games'] += 1; M[md]['wins'] += r['win']
        first = collections.defaultdict(list)
        for e in d['events']:
            if e['owner'].get('team') != T: continue
            nm = e['owner'].get('name', '?')
            for en in e['entries']:
                rd = en['timestamp']['round']; p = ph(rd)
                if e['kind'] == 'campClear':
                    i = en['target'].get('id', -1)
                    if 0 <= i < len(G):
                        k = kind(G[i]); s2 = side(*cen(G[i]['tiles']))
                        C[nm][f'clear_{k}'] += 1; C[nm][f'side_{s2}'] += 1; C[nm][f'phase_{p}'] += 1; P[p]['clears'] += 1
                        if len(first[nm]) < 3: first[nm].append(f'{k}/{s2}')
                elif e['kind'] == 'gemSubmission':
                    C[nm]['tributes'] += 1; C[nm]['tributed'] += int(en['value']); P[p]['tributes'] += 1; P[p]['tributed'] += int(en['value'])
                elif e['kind'] == 'kill':
                    C[nm]['kills'] += 1; C[nm][f'kill_{p}'] += 1; P[p]['kills'] += 1
                elif e['kind'] == 'assist':
                    C[nm]['assists'] += 1
                elif e['kind'] == 'death':
                    C[nm]['deaths'] += 1; C[nm][f'death_{p}'] += 1; P[p]['deaths'] += 1
                    deaths[('champ' if en.get('context') == 'champion' else 'camp', side(en['x'], en['y']), p)] += 1
                elif e['kind'] == 'wardPlacement':
                    C[nm]['wards'] += 1
                elif e['kind'] == 'buyConsumable':
                    C[nm]['cons_' + en['target'].get('name', '?')] += 1
                elif e['kind'] == 'gemLoss':
                    C[nm]['lost'] += int(en['value'])
        for nm, f in first.items(): routes[nm][' > '.join(f)] += 1
        for c in d['champions']:
            if c['team'] != T: continue
            C[c['name']]['gold'] += float(c['metrics']['earnedGold']); C[c['name']]['collected'] += float(c['metrics']['collectedGems'])
            C[c['name']]['dmg'] += float(c['metrics']['championDamageDone']); C[c['name']]['taken'] += float(c['metrics']['championDamageTaken'])
            C[c['name']]['mdmg'] += float(c['metrics']['monsterDamageDone'])
        for c in d['championTimelines']:
            if c['owner']['team'] == T and c['metric'] == 'earnedGold':
                for rr in (100, 300, 600): C[c['owner']['name']][f'g{rr}'] += panel.tl_at(c['runs'], rr)
    n = sum(M[m]['games'] for m in M)
    out = {'n': n, 'modes': {m: dict(v) for m, v in M.items()}, 'phase': {p: {k: v / n for k, v in c.items()} for p, c in P.items()},
           'champ': {nm: {k: v / games[nm] for k, v in c.items()} | {'games': games[nm]} for nm, c in C.items() if games[nm] >= 20},
           'routes': {nm: c.most_common(4) for nm, c in routes.items() if games[nm] >= 20},
           'deaths': {'|'.join(k): v / n for k, v in deaths.items()}}
    return out


top = [r for r in json.load(open(os.path.expanduser('~/.cache/kessoku_top/rows.json'))) if 'rounds' in r]
ours = []
for k in ['v41', 'v43']: ours += [r for r in json.load(open(os.path.expanduser(f'~/.cache/kessoku_ladder/{k}.json'))) if 'g300' in r]
res = {'top': analyse(top), 'ours': analyse(ours)}
json.dump(res, open(os.path.expanduser('~/.cache/kessoku_rep/summ_detail.json'), 'w'), indent=1)
print('top games', res['top']['n'], 'ours', res['ours']['n'])
