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

shutil.rmtree(ws.parent.parent, ignore_errors=True)
print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
