import subprocess
import time

# Teams to play against: (id, name)
OPPONENTS = [
    ("31724ff8-4f57-42fc-9271-0d0cb5832b70", "Pantheon"),
    ("023ce802-d72e-44f5-b99e-71a6f97db4b7", "Blue Dragon"),
    ("b4a784e9-1e15-4d0d-89d0-b673c53e686b", "something else"),
    ("05a96b0d-3ce5-4be8-921b-570dd973994a", "MFF1"),
    ("52f2b5ac-2f05-4bde-ab81-a5dc5edaa276", "muteki"),
    ("55d69169-9544-491a-a450-0d54d07e0c27", "PPP"),
    ("db64a383-a20a-4cf9-a57c-082e1dc9dfbf", "bwaaa"),
    ("bbde9d3c-7048-4e4c-b433-0ca13e387c3b", "Squishy"),
    ("64bb714f-4d8d-441f-b1e2-c9a047903430", "cheesynachos"),
    ("5b71b021-4fef-4bde-a7af-3469b4886c53", "Dear jump Give me a job plz"),
    ("9360446d-e598-439a-85fb-ada26caba6de", "okbro")
]

def run_cmd(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout, result.stderr

print(f"Playing each of {len(OPPONENTS)} opponents once.\n")

for tid, name in OPPONENTS:
    stdout, stderr = run_cmd(["cambc", "match", "unrated", tid])
    if stderr.strip():
        print(f"  ✗ vs {name}: {stderr.strip()}")
    else:
        print(f"  ✓ vs {name}")
    time.sleep(1)  # small delay between requests

print("Done.")
