#!/usr/bin/env python3
"""Real-opponent panel for the live submission (release loop, see Research.md section 0b).

usage (from Submission/, logged in):
  python3 tools/panel.py run "LABEL"   # queue the 4 pinned match groups for the LIVE bot, wait, fetch summaries, compare
  python3 tools/panel.py compare       # print the comparison of every recorded run

The panel (tools/data/panel.json) fixes the teams, their bot versions (--source-group), maps and sides, so every run
is comparable game for game. Summaries are cached in ~/.cache/kessoku_panel. Match groups always play the team's live
submission: upload/activate the candidate first (the user does that).
"""
import json, os, subprocess, sys, time

P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(P, 'tools', 'data', 'panel.json')
if '--panel' in sys.argv:  # e.g. --panel tools/data/panel_holdout.json
    i = sys.argv.index('--panel'); PANEL = os.path.abspath(sys.argv[i + 1]); del sys.argv[i:i + 2]
CACHE = os.path.expanduser('~/.cache/kessoku_panel'); os.makedirs(CACHE, exist_ok=True)
US = 'HighCortisol'


def cambc_json(*a):
    for k in range(6):
        out = subprocess.run(['cambc', *a], capture_output=True, text=True).stdout
        try:
            return json.loads(out[out.find('{'):out.rfind('}') + 1])
        except ValueError:
            time.sleep(5 + 5 * k)
    raise SystemExit('cambc ' + ' '.join(a) + ' failed')


def summary(match_id):
    j = f'{CACHE}/match-{match_id}.json'
    for k in range(8):
        if os.path.exists(j) and os.path.getsize(j) > 1000:
            return json.load(open(j))
        subprocess.run(['cambc', 'matches', 'summary', match_id], cwd=CACHE, capture_output=True)
        c = f'{CACHE}/match-{match_id}.camstat'
        if os.path.exists(c):
            subprocess.run(['cambc', 'summary', c, '-o', j], capture_output=True)
            continue
        time.sleep(4 + 4 * k)
    return None


def games(group):
    for k in range(60):
        d = cambc_json('match-groups', 'show', group, '--json')
        if all(m['status'] == 'finished' for m in d['matches']):
            return d['matches']
        time.sleep(15)
    raise SystemExit(f'group {group} did not finish')


def tl_at(runs, r):
    t = 0; v = 0.0
    for x in runs:
        if t > r: break
        v = float(x['value']); t += x['duration']
    return v


def row(m):
    us = [t for t in m['teams'] if t['name'] == US][0]; op = [t for t in m['teams'] if t['name'] != US][0]
    d = summary(m['matchId']); T = 'team' + us['side'].upper(); O = 'teamB' if T == 'teamA' else 'teamA'
    r = dict(opp=op['name'], map=m['map'], win=us['result'] == 'win')
    if d:
        M = lambda t, k: sum(float(c['metrics'][k]) for c in d['champions'] if c['team'] == t)
        deaths = [en for e in d['events'] if e['kind'] == 'death' and e['owner'].get('team') == T for en in e['entries']]
        lost = sum(int(en['value']) for e in d['events'] if e['kind'] == 'gemLoss' and e['owner'].get('team') == T for en in e['entries'])
        g300 = lambda t: sum(tl_at(c['runs'], 300) for c in d['championTimelines'] if c['metric'] == 'earnedGold' and c['owner']['team'] == t)
        r.update(rounds=d['match']['roundsCompleted'], deaths=len(deaths), odeaths=M(O, 'deaths'),
                 camp=sum(1 for en in deaths if en.get('context') != 'champion'), lost=lost,
                 coll=M(T, 'collectedGems'), ocoll=M(O, 'collectedGems'), sub=M(T, 'submittedGems'), osub=M(O, 'submittedGems'),
                 g300=g300(T), og300=g300(O))
    return r


def compare(panel):
    runs = [x for x in panel['runs'] if x.get('rows')]
    pairs = [(mp, t['name']) for t in panel['teams'] for mp in t.get('maps', panel.get('maps', '')).split(',')]
    print('game'.ljust(36) + ''.join(x['version'][:14].rjust(16) for x in runs))
    for mp, tm in sorted(pairs):
        if True:
            cells = []
            for x in runs:
                r = next((r for r in x['rows'] if r['opp'] == tm and r['map'] == mp), None)
                cells.append('-' if not r else f"{'W' if r['win'] else 'L'} {r.get('deaths', 0):2.0f}d {r.get('coll', 0):4.0f}g")
            print(f'{mp[2:]:12s} {tm[:22]:22s}  ' + ''.join(c.rjust(16) for c in cells))
    print()
    for x in runs:
        rs = x['rows']; n = len(rs); avg = lambda k: sum(r.get(k, 0) for r in rs) / n
        print(f"{x['version'][:22]:22s} wins {sum(r['win'] for r in rs)}/{n} | deaths {avg('deaths'):.1f} vs {avg('odeaths'):.1f} "
              f"(camp {avg('camp'):.1f}) | gems lost/death {sum(r.get('lost', 0) for r in rs) / max(1, sum(r.get('deaths', 0) for r in rs)):.1f} "
              f"| gold@300 {avg('g300'):.0f} vs {avg('og300'):.0f} | collected {avg('coll'):.0f} vs {avg('ocoll'):.0f}")


def main():
    panel = json.load(open(PANEL))
    if len(sys.argv) >= 3 and sys.argv[1] == 'run':
        groups = []
        for t in panel['teams']:
            pin = ['--source-group', t['source_group']] if t.get('source_group') else []
            d = cambc_json('match-groups', 'create', t['team_id'], *pin, '--maps', t.get('maps', panel.get('maps')),
                           '--sides', t.get('sides', panel.get('sides')), '--json')
            groups.append(d['groupId']); print('queued', t['name'], d['groupId'], flush=True)
            t.setdefault('source_group', d['groupId'])  # first run pins this opponent version for later runs
        rows = [row(m) for g in groups for m in games(g)]
        panel['runs'].append({'version': sys.argv[2], 'groups': groups, 'rows': rows})
        json.dump(panel, open(PANEL, 'w'), indent=2)
    elif len(sys.argv) >= 2 and sys.argv[1] == 'backfill':  # add rows to runs recorded without them
        for x in panel['runs']:
            if not x.get('rows'):
                x['rows'] = [row(m) for g in x['groups'] for m in games(g)]
        json.dump(panel, open(PANEL, 'w'), indent=2)
    elif len(sys.argv) < 2 or sys.argv[1] != 'compare':
        sys.exit(__doc__)
    compare(panel)


if __name__ == '__main__':
    main()
