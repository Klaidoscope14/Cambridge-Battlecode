"""Refresh maps/ with the exact ladder versions, extracted from our own ranked replays.

`cambc maps pull` can fail (HTTP 303) for new maps; every replay embeds its map, so
this downloads one recent ranked match per map and extracts it with extract_map.py.
usage (from Submission/, after `cambc login`): python3 tools/refresh_maps.py TEAM_ID
"""
import json, os, subprocess, sys, tempfile, time
team = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
out = subprocess.run(["cambc", "matches", "list", "--team", team, "--kind", "ranked", "--limit", "50", "--json"],
                     capture_output=True, text=True).stdout
seen = {}
for m in json.loads(out)["matches"]:
    seen.setdefault(m["map"], m["matchId"])
for name, mid in sorted(seen.items()):
    dst = os.path.join(tmp, name + ".repl26a")
    for _ in range(8):  # the download queue rate-limits (HTTP 429)
        subprocess.run(["cambc", "matches", "download", mid, "-o", dst], capture_output=True, text=True)
        if os.path.exists(dst): break
        time.sleep(6)
    if os.path.exists(dst):
        subprocess.run([sys.executable, os.path.join(here, "extract_map.py"), dst, f"maps/{name}.map26a"])
    else:
        print(name, "download failed")
