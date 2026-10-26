#!/usr/bin/env python3
"""Early-stopping paired A/B: is VARIANT better than BASE against the same opponents on the same games?

usage (from Submission/): python3 tools/sprt.py VARIANT BASE OPP[,OPP...] [--maps m1,m2,...]
                          [--p1 0.65] [--alpha 0.05] [--beta 0.05] [--batch 16] [--max 400] [--seed 1]
Both bots play the same (map, side, opponent) games, in a fixed shuffled order, `--batch` games per round.
Matches are deterministic, so only games where exactly one of the two wins carry information: each is a
"+" (variant won, base lost) or a "-". Wald's SPRT on those discordant pairs tests H0: P(+) = 0.5 against
H1: P(+) = p1, and stops as soon as the log-likelihood ratio crosses log((1-beta)/alpha) (variant better)
or log(beta/(1-alpha)) (no evidence it is better), or when the game list or --max runs out.
Results are cached per bot source hash in $TMPDIR/kessoku_sprt, so a baseline is never replayed. Build
every bot (`cambc build X`) before running; concurrent first builds break games.
"""
import argparse, hashlib, json, math, os, random, subprocess, sys, tempfile

P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Submission/
POOL = set(open(os.path.join(P, 'tools', 'data', 'pool.txt')).read().split())  # the ladder map pool (cambc maps list)
ap = argparse.ArgumentParser()
ap.add_argument('variant'); ap.add_argument('base'); ap.add_argument('opps')
ap.add_argument('--maps', default=''); ap.add_argument('--p1', type=float, default=0.65)
ap.add_argument('--alpha', type=float, default=0.05); ap.add_argument('--beta', type=float, default=0.05)
ap.add_argument('--batch', type=int, default=16); ap.add_argument('--max', type=int, default=400)
ap.add_argument('--seed', type=int, default=1); ap.add_argument('--jobs', type=int, default=8)
a = ap.parse_args()

ENGINE = subprocess.run(['cambc', '--version'], capture_output=True, text=True).stdout.strip()  # results differ per engine


def src_hash(bot):
    h = hashlib.sha1(ENGINE.encode())
    root = f'{P}/bots/{bot}/src'
    for dp, _, fs in sorted(os.walk(root)):
        for f in sorted(fs):
            h.update(f.encode()); h.update(open(os.path.join(dp, f), 'rb').read())
    return h.hexdigest()[:12]

CACHE = os.path.join(tempfile.gettempdir(), 'kessoku_sprt')
maps = a.maps.split(',') if a.maps else sorted(f[:-7] for f in os.listdir(f'{P}/maps') if f.endswith('.map26a') and f[:-7] in POOL)
games = [(m, s, o) for m in maps for s in 'AB' for o in a.opps.split(',')]
random.Random(a.seed).shuffle(games)
games = games[:a.max]
dirs = {b: os.path.join(CACHE, f'{b}-{src_hash(b)}') for b in (a.variant, a.base)}
for d in dirs.values(): os.makedirs(d, exist_ok=True)

def path(bot, g): return os.path.join(dirs[bot], f'{g[2]}_{g[0]}_{g[1]}')
def result(bot, g):
    try:
        d = json.load(open(path(bot, g) + '.json'))
        return d['match']['outcome'] == 'team' + g[1]
    except Exception:
        return None

def run(pending):
    if not pending: return
    man = os.path.join(CACHE, f'manifest-{os.getpid()}.txt')
    with open(man, 'w') as f:
        for bot, (m, s, o) in pending:
            x, y = (bot, o) if s == 'A' else (o, bot)
            out = path(bot, (m, s, o))
            f.write(f'{P}/bots/{x} {P}/bots/{y} {P}/maps/{m}.map26a {out}.repl26a --statistics {out}.json --json\n')
    subprocess.run(['cambc', 'run-batch', '--jobs', str(a.jobs), '--release', man], cwd=P, capture_output=True)

lo, hi = math.log(a.beta / (1 - a.alpha)), math.log((1 - a.beta) / a.alpha)
up, down = math.log(a.p1 / 0.5), math.log((1 - a.p1) / 0.5)
plus = minus = wv = wb = n = 0
verdict = 'inconclusive (game list or --max ran out)'
for i in range(0, len(games), a.batch):
    chunk = games[i:i + a.batch]
    run([(b, g) for g in chunk for b in (a.variant, a.base) if result(b, g) is None])
    for g in chunk:
        rv, rb = result(a.variant, g), result(a.base, g)
        if rv is None or rb is None:
            print('missing result', g, file=sys.stderr); continue
        n += 1; wv += rv; wb += rb
        plus += rv and not rb; minus += rb and not rv
    llr = plus * up + minus * down
    print(f'{n:4d} games  variant {wv}  base {wb}  discordant +{plus} -{minus}  LLR {llr:+.2f} [{lo:.2f}, {hi:.2f}]', flush=True)
    if llr >= hi: verdict = 'ACCEPT: variant better'; break
    if llr <= lo: verdict = 'REJECT: no evidence variant is better'; break
print(f'SPRT {a.variant} vs {a.base} on {a.opps}: {verdict} | games {n}, variant wins {wv}, base wins {wb}, +{plus} -{minus}')
