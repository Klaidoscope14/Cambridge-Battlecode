"""Extract the embedded .map26a from a downloaded ladder replay bundle.

usage: python3 extract_map.py BUNDLE.repl26a OUT.map26a
The replay starts with a 14-byte header, then the map verbatim; the map ends just
before a u32 followed by the first event record (04 01 .. 00 00 00 ff 03). Each
candidate cut is checked by loading it in a 2-round local match.
"""
import re, subprocess, sys, tempfile, zipfile, os
bundle, out = sys.argv[1], sys.argv[2]
L = zipfile.ZipFile(bundle).read("replay.repl26a")
assert L[14:20] == b"w62pam", "no embedded map"
tmp = tempfile.mkdtemp()
for m in re.finditer(rb"\x04\x01.\x00\x00\x00\xff\x03", L):
    end = m.start() - 4
    if end < 100: continue
    path = os.path.join(tmp, "try.map26a"); open(path, "wb").write(L[14:end])
    r = subprocess.run(["cambc", "run", "starter-cpp", "starter-python", "--map", path, "--rounds", "2", "-o", tmp],
                       capture_output=True, text=True, cwd=os.getcwd())
    if "engine error" not in r.stdout + r.stderr:
        open(out, "wb").write(L[14:end]); print("ok", out, end - 14); sys.exit(0)
print("no valid cut found"); sys.exit(1)
