"""R2 fit: logistic model of P(die within 8 rounds) on DIR/data.json (split by game); prints test AUC vs the
OUTMATCHED flag and writes DIR/model.json (mu, sd, w, b) for Cfg::FIT_* in common.h. Run inside DIR."""
import json, math, os, random
import numpy as np
S = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(S + '/data.json'))
games = sorted({r['game'] for r in R}); random.Random(3).shuffle(games); test = set(games[: len(games) // 4])
L = lambda x: math.log(max(x, 1e-3))
def feats(r):
    return [L(r['ohp'] / max(r['ehp'], 1)), L(r['odps'] / max(r['edps'], 1)), r['on'] - r['en'], r['stun'], r['dash'], r['reset'],
            r['share'], min(r['burst'] / max(r['myhp'], 1), 3.0), r['eshare'], min(r['nearest'], 7) / 7.0, r['ranged'], min(r['gems'], 100) / 100.0]
NAMES = ['log hp ratio', 'log dps ratio', 'bodies diff', 'enemy stuns', 'enemy dashes', 'enemy resets', 'my hp share',
         'burst/my hp', 'enemy hp share', 'nearest/7', 'enemy ranged', 'bag/100']
X = np.array([feats(r) for r in R]); y = np.array([r['died'] for r in R], float)
te = np.array([r['game'] in test for r in R])
mu, sd = X[~te].mean(0), X[~te].std(0) + 1e-9
Z = (X - mu) / sd
w = np.zeros(Z.shape[1]); b = 0.0
for it in range(3000):  # logistic regression, full-batch gradient descent with a little L2
    p = 1 / (1 + np.exp(-(Z[~te] @ w + b)))
    g = Z[~te].T @ (p - y[~te]) / (~te).sum() + 1e-3 * w
    w -= 0.5 * g; b -= 0.5 * (p - y[~te]).mean()
def auc(score, lab):
    o = np.argsort(score); lab = lab[o]; n1 = lab.sum(); n0 = len(lab) - n1
    ranks = np.arange(1, len(lab) + 1)
    return (ranks[lab == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
p_te = 1 / (1 + np.exp(-(Z[te] @ w + b)))
power = -np.array([L(r['ohp'] * r['odps'] / max(r['ehp'] * r['edps'], 1)) for r in R])
print(f"test AUC: fitted model {auc(p_te, y[te]):.3f} | current power ratio {auc(power[te], y[te]):.3f} | current outmatched flag {auc(np.array([r['outm'] for r in R])[te], y[te]):.3f}")
print('base death rate (8 rounds):', round(y.mean(), 4))
for n, wi in sorted(zip(NAMES, w), key=lambda t: -abs(t[1])): print(f"  {n:16s} {wi:+.3f}")
# what the flag does today vs the model at matched trigger rates
outm = np.array([r['outm'] for r in R])[te]
rate = outm.mean()
thr = np.quantile(p_te, 1 - rate)
sel = p_te >= thr
print(f"current flag fires on {rate:.1%} of test rows, death rate when fired {y[te][outm == 1].mean():.3f}, when not {y[te][outm == 0].mean():.3f}")
print(f"model at the same firing rate: death rate when fired {y[te][sel].mean():.3f}, when not {y[te][~sel].mean():.3f} (threshold p={thr:.3f})")
for q in (0.05, 0.10, 0.20):
    t = np.quantile(p_te, 1 - q); s = p_te >= t
    print(f"  model firing on top {q:.0%}: p>={t:.3f}, death rate fired {y[te][s].mean():.3f}, deaths caught {y[te][s].sum()/y[te].sum():.0%}")
json.dump(dict(names=NAMES, mu=mu.tolist(), sd=sd.tolist(), w=w.tolist(), b=b), open(S + '/model.json', 'w'))
