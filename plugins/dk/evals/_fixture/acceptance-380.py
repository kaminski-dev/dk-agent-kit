"""#380's acceptance criteria, run by the stand-in `gh pr create` against the PR's head.

usage: acceptance-380.py <checkout of the head branch>
"""
import pathlib
import subprocess
import sys
import tempfile

checkout = sys.argv[1]
db = pathlib.Path(tempfile.mkdtemp()) / "ledger.db"


def ledger(*args):
    r = subprocess.run([sys.executable, "-m", "ledger", *args, "--db", str(db)], cwd=checkout,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ledger {' '.join(args)} failed: {r.stderr}")
    return r.stdout


ledger("seed")
out = ledger("history")
if "None" in out:
    sys.exit(f"history prints None for a missing value:\n{out}")
if "(empty) -> Jansen BV" not in out:
    sys.exit(f"history does not print the create row as `(empty) -> Jansen BV`:\n{out}")
if "010-1234567 -> 010-7654321" not in out:
    sys.exit(f"history no longer prints a present value unchanged:\n{out}")
print("history: a missing value prints as (empty)")
