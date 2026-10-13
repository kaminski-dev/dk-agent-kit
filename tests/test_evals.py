#!/usr/bin/env python3
"""Checks the fixtures behind plugins/dk/evals without running a model.

Each case's scaffold builds its workspace into a temp HOME the way
`claude plugin eval --scaffold` does (workspace = $HOME/cwd), and the checks
drive the stand-in `gh` and the fixture repo from there. A fixture that is
not red before the fix would let an eval pass without the skill doing its job.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVALS = ROOT / "plugins" / "dk" / "evals"
REFERENCE = pathlib.Path(__file__).resolve().parent / "evals"

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(name)


def scaffold(case):
    """Run a case's scaffold_script in a fresh HOME/cwd and return the workspace."""
    home = pathlib.Path(tempfile.mkdtemp(prefix="dk-eval-")) / "home"
    ws = home / "cwd"
    ws.mkdir(parents=True)
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": tempfile.gettempdir(), "TERM": "dumb"}
    script = EVALS / case / "scaffold.sh"
    r = subprocess.run(["bash", str(script)], cwd=ws, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAIL scaffold {case}: {r.stderr}")
    return ws


def run(ws, cmd, cwd=None, stdin=None):
    """Run cmd in a login-less shell that reads the workspace's rc, like the eval's Bash tool."""
    env = {"PATH": os.environ["PATH"], "HOME": str(ws.parent), "TERM": "dumb"}
    full = f'. "$HOME/.bashrc"; {cmd}'
    return subprocess.run(["bash", "-c", full], cwd=cwd or ws, env=env, input=stdin, capture_output=True, text=True)


def git(ws, repo, *args):
    return run(ws, "git " + " ".join(args), cwd=ws / repo)


def acceptance_on(ws, ref):
    """Push ref as a branch and open a PR through the stand-in, which runs the acceptance check."""
    git(ws, "app", "push", "-q", "origin", f"{ref}:refs/heads/fix/353-check")
    r = run(ws, "gh pr create --base pre-main --head fix/353-check --title t --body 'Closes #353'", cwd=ws / "app")
    return r, (ws / ".tracker" / "pr.md").read_text() if (ws / ".tracker" / "pr.md").exists() else ""


# --- #353 fixture: Customer History order -------------------------------------------------------

ws = scaffold("implement-353")
heads = git(ws, "app", "ls-remote", "--heads", "origin").stdout
check("353: origin has main and pre-main", "refs/heads/main" in heads and "refs/heads/pre-main" in heads, heads)
tests = run(ws, "python3 -m unittest discover -s tests -q", cwd=ws / "app")
check("353: fixture's own tests pass", tests.returncode == 0, tests.stderr[-500:])

r, pr = acceptance_on(ws, "origin/pre-main")
check("353: acceptance fails on the pre-fix state", "acceptance: fail" in pr, pr or r.stderr)

git(ws, "app", "checkout", "-q", "-b", "reference", "origin/pre-main")
patch = run(ws, f"git apply '{REFERENCE / 'reference-353.patch'}'", cwd=ws / "app")
check("353: reference fix applies", patch.returncode == 0, patch.stderr)
git(ws, "app", "commit", "-qam", "reference")
r, pr = acceptance_on(ws, "reference")
check("353: acceptance passes on the reference fix", "acceptance: pass" in pr and "unit tests: pass" in pr, pr or r.stderr)

# A head that cannot be extracted still gets a PR and an acceptance line, and leaves no checkout behind.
broken = ws.parent / "broken-tar"
broken.mkdir()
(broken / "tar").write_text("#!/bin/sh\nexit 2\n")
(broken / "tar").chmod(0o755)
(ws / ".tracker" / "pr.md").unlink()
r = run(ws, f"PATH='{broken}':$PATH gh pr create --base pre-main --head fix/353-check --title t --body b", cwd=ws / "app")
pr = (ws / ".tracker" / "pr.md").read_text() if (ws / ".tracker" / "pr.md").exists() else ""
check("353: a failed extraction reports acceptance: fail", r.returncode == 0 and "acceptance: fail" in pr, pr or r.stderr)
left = sorted(p.name for p in (ws / ".tracker").glob("pr-*"))
check("353: a failed extraction leaves no checkout in .tracker", left == [], left)

shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The review fixture: a branch that fixes #353 correctly but breaks one documented standard.
ws = scaffold("code-review-353")
branch = git(ws, "app", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
check("353 review: the fix branch is checked out", branch == "fix/353-history-order", branch)
diff = git(ws, "app", "diff", "origin/pre-main...HEAD").stdout
check("353 review: the diff seeds a value interpolated into SQL", "entity_type = '{entity_type}'" in diff, diff[:300])
r, pr = acceptance_on(ws, "HEAD")
check("353 review: the seeded branch still meets #353's acceptance", "acceptance: pass" in pr and "unit tests: pass" in pr, pr or r.stderr)
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The review fixture with work in progress: the same branch, plus an uncommitted edit and an untracked
# file, each breaking a documented standard that a review of the commits alone cannot see.
ws = scaffold("code-review-wip")
branch = git(ws, "app", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
check("wip review: the fix branch is checked out", branch == "fix/353-history-order", branch)
status = git(ws, "app", "status", "--porcelain").stdout
check("wip review: one uncommitted edit and one untracked file",
      status == " M tests/test_audit_store.py\n?? ledger/export.py\n", status)
committed = git(ws, "app", "diff", "--name-only", "origin/pre-main...HEAD").stdout.split()
check("wip review: the commits touch neither", "ledger/export.py" not in committed
      and "test_one_row_per_changed_field" not in git(ws, "app", "diff", "origin/pre-main...HEAD").stdout, committed)
wip = git(ws, "app", "diff", "HEAD").stdout
check("wip review: the uncommitted test reads the table directly",
      'conn.execute("SELECT field_name FROM audit_logs WHERE' in wip, wip[:400])
export = (ws / "app" / "ledger" / "export.py").read_text()
check("wip review: the untracked file formats a value into SQL", "entity_type = '%s'\" % entity_type" in export, export)
tests = run(ws, "python3 -m unittest discover -s tests -q", cwd=ws / "app")
check("wip review: the tests still pass with the work in progress", tests.returncode == 0, tests.stderr[-500:])
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The triage fixture: #353 as filed, on the pre-fix code.
ws = scaffold("triage-353")
issue = json.loads(run(ws, "gh issue view 353 --json labels,comments").stdout)
check("353 triage: the tracker holds the untriaged issue", issue == {"labels": [{"name": "needs-triage"}], "comments": []}, issue)
store = (ws / "app" / "ledger" / "audit_store.py").read_text()
check("353 triage: list_by_entity still orders by changed_at alone", '" ORDER BY changed_at DESC"' in store, store[-600:])
r = run(ws, "gh issue edit 353 --add-label bug --add-label ready-for-agent --remove-label needs-triage")
md = (ws / ".tracker" / "issue-353.md").read_text() if (ws / ".tracker" / "issue-353.md").exists() else ""
check("353 triage: a label edit reaches the file the graders read", "labels: bug, ready-for-agent\n" in md, md or r.stderr)
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# --- #1091 fixture: govulncheck red on go1.27.1 and x/net v0.59.0 --------------------------------

ws = scaffold("triage-1091")
vuln = run(ws, "govulncheck ./...", cwd=ws / "api")
ids = sorted(set(l.split()[2] for l in vuln.stdout.splitlines() if l.startswith("Vulnerability #")))
check("1091: govulncheck exits 3 on the pinned toolchain", vuln.returncode == 3, vuln.stdout[-300:])
check("1091: it reports the issue's 12 IDs", len(ids) == 12 and "GO-2026-6617" in ids, ids)
scans = (ws / ".tracker" / "govulncheck.log").read_text()
check("1091: the scan is logged for the graders", scans == "./... exit=3\n", scans)
mod = ws / "api" / "go.mod"
mod.write_text(mod.read_text().replace("go 1.27.1", "go 1.27.2").replace("x/net v0.59.0", "x/net v0.60.0"))
vuln = run(ws, "govulncheck ./...", cwd=ws / "api")
check("1091: govulncheck exits 0 after the bump", vuln.returncode == 0, vuln.stdout[-300:])
issue = json.loads(run(ws, "gh issue view 1091 --json title,labels").stdout)
check("1091: the tracker holds the untriaged issue", issue["labels"] == [{"name": "needs-triage"}], issue)
shutil.rmtree(ws.parent.parent, ignore_errors=True)

print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
