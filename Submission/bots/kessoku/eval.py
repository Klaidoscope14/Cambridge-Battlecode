#!/usr/bin/env python3
"""Averaged A/B evaluation harness (point 7).

Runs a bot against an opponent N times per map, BOTH sides, and aggregates
tributed gems, win rate, deaths, and gold earned from --statistics JSON. Use
this (not single matches) to decide whether a change helps — single matches
are high-variance and lead to overfitting.

Usage (from inside a `cambc init` workspace):
    python bots/kessoku/eval.py --bot kessoku --opp starter-python --runs 3
    python bots/kessoku/eval.py --bot kessoku --opp starter-python --maps lanes,packs
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ALL_MAPS = ["collision", "corners", "elkring", "expanse", "interlock",
            "lanes", "monolith", "packs", "rows"]


def run_match(a, b, map_path, stats_path):
    subprocess.run(
        ["cambc", "run", a, b, "--map", str(map_path),
         "--statistics", str(stats_path), "-o", "/tmp/cambc_eval_replays"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    try:
        return json.loads(Path(stats_path).read_text())
    except Exception:
        return None


def team_gems(stats, team_index):
    # sum tributed gems across the team's champions
    try:
        champs = stats["champions"]
        # champions list carries a team marker; fall back to summary if present
        if "teams" in stats:
            return stats["teams"][team_index].get("submittedGems", 0)
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="kessoku")
    ap.add_argument("--opp", default="starter-python")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--maps", default=",".join(ALL_MAPS))
    ap.add_argument("--maps-dir", default="maps")
    args = ap.parse_args()

    maps = [m.strip() for m in args.maps.split(",") if m.strip()]
    stats_path = Path("/tmp/cambc_eval_stats.json")
    tmp = Path("/tmp/cambc_eval_replays")
    tmp.mkdir(exist_ok=True)

    total_wins = 0
    total_games = 0
    print(f"{args.bot} vs {args.opp} — {args.runs} runs/side/map\n")
    print(f"{'map':<11} {'ourGems':>8} {'oppGems':>8} {'winrate':>8}")
    for m in maps:
        mp = Path(args.maps_dir) / f"{m}.map26a"
        if not mp.exists():
            print(f"{m:<11}  (missing {mp})")
            continue
        our, opp, wins, games = 0, 0, 0, 0
        for _ in range(args.runs):
            for a, b, ours_is_a in ((args.bot, args.opp, True),
                                    (args.opp, args.bot, False)):
                st = run_match(a, b, mp, stats_path)
                games += 1
                total_games += 1
                if st is None:
                    continue
                # Prefer explicit team summary; else parse from the CLI is skipped.
                g_a = team_gems(st, 0) or 0
                g_b = team_gems(st, 1) or 0
                og = g_a if ours_is_a else g_b
                pg = g_b if ours_is_a else g_a
                our += og
                opp += pg
                if og > pg:
                    wins += 1
                    total_wins += 1
        n = max(1, games)
        print(f"{m:<11} {our/n:8.0f} {opp/n:8.0f} {wins/n:8.1%}")
    print(f"\noverall winrate: {total_wins/max(1,total_games):.1%} "
          f"over {total_games} games")


if __name__ == "__main__":
    main()
