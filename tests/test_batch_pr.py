#!/usr/bin/env python3
"""Runs the dk:batch-pr collection script against a fixture repo and the eval `gh` stand-in.

The workspace copies the shape plugins/dk/evals/_fixture/build.sh builds: .bin/gh
first on PATH, its state in .tracker/state.json, a bare origin beside the repo.
Nothing reaches GitHub, and no case may open a PR.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "dk" / "skills" / "batch-pr" / "batch.py"
GH = ROOT / "plugins" / "dk" / "evals" / "_fixture" / "bin" / "gh"

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(name)


def pr(number, base, head, state, body, merge_commit=None):
    return {"number": number, "title": f"PR {number}", "body": body, "base": base, "head": head, "state": state,
            "mergeCommit": {"oid": merge_commit} if merge_commit else None}


class Workspace:
    def __init__(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="dk-batch-"))
        (self.root / ".bin").mkdir()
        (self.root / ".tracker").mkdir()
        shutil.copy(GH, self.root / ".bin" / "gh")
        self.repo = self.root / "repo"
        self.env = {"PATH": f"{self.root / '.bin'}:{os.environ['PATH']}", "HOME": str(self.root), "TERM": "dumb",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.git_in(self.root, "init", "-q", "--bare", "origin.git")
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("remote", "add", "origin", "../origin.git")
        self.commit("base")

    def git_in(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True).stdout

    def git(self, *args):
        return self.git_in(self.repo, *args)

    def commit(self, name):
        (self.repo / name).write_text(name + "\n")
        self.git("add", name)
        self.git("commit", "-qm", name)
        return self.git("rev-parse", "HEAD").strip()

    def push(self):
        self.git("push", "-q", "--force", "origin", "main", "pre-main")

    def state(self, prs):
        (self.root / ".tracker" / "state.json").write_text(json.dumps(
            {"repo": "acme/ledger", "labels": [], "issues": {}, "prs": prs}))

    def run(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=self.repo, env=self.env, capture_output=True,
                           text=True)
        log = self.root / ".tracker" / "calls.log"
        return r, log.read_text() if log.exists() else ""

    def remove(self):
        shutil.rmtree(self.root, ignore_errors=True)


# Two PRs merged into pre-main since the last batch, one from an earlier batch already in main,
# and one still open against pre-main.
ws = Workspace()
earlier = ws.commit("earlier")
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
first, second = ws.commit("first"), ws.commit("second")
ws.push()
ws.state([
    pr(10, "pre-main", "fix/100-earlier", "MERGED", "Earlier batch.\n\nCloses #100\n", earlier),
    pr(11, "pre-main", "fix/101-first", "MERGED", "First.\n\nCloses #101\n", first),
    pr(12, "pre-main", "feat/102-second", "MERGED", "Second.\n\nRefs #102\n", second),
    pr(13, "pre-main", "fix/103-open", "OPEN", "Still open.\n\nCloses #103\n"),
])
r, calls = ws.run()
check("two merged PRs: exits 0", r.returncode == 0, r.stdout + r.stderr)
check("two merged PRs: both PRs listed", "#11 PR 11" in r.stdout and "#12 PR 12" in r.stdout, r.stdout)
check("two merged PRs: both lines, each once", r.stdout.count("Closes #101\n") == 1 and r.stdout.count("Refs #102\n") == 1,
      r.stdout)
check("two merged PRs: the earlier batch's and the open PR's lines left out",
      "#100" not in r.stdout and "#103" not in r.stdout and "#10 " not in r.stdout, r.stdout)
check("two merged PRs: opens no PR", "pr create" not in calls, calls)
ws.remove()

# A merged PR whose body carries no Closes or Refs line is named, so the batch body can say so;
# an issue one PR closes and a later one only refers to keeps its Refs line for the post-deploy check.
ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
lined, bare, follow_up = ws.commit("lined"), ws.commit("bare"), ws.commit("follow-up")
ws.push()
ws.state([
    pr(21, "pre-main", "fix/201-lined", "MERGED", "Closes #201", lined),
    pr(22, "pre-main", "chore/ci", "MERGED", "CI bump, no issue.", bare),
    pr(23, "pre-main", "fix/201-follow-up", "MERGED", "refs #201", follow_up),
])
r, _ = ws.run()
check("a PR without a line: named under its own heading",
      r.returncode == 0 and "## Without a line\n- #22 PR 22" in r.stdout, r.stdout)
check("Closes and Refs for one issue: Refs alone",
      "Refs #201\n" in r.stdout and "Closes #201" not in r.stdout, r.stdout)
ws.remove()

ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
merged = ws.commit("merged")
ws.push()
ws.state([
    pr(31, "pre-main", "fix/301-merged", "MERGED", "Closes #301", merged),
    pr(32, "main", "pre-main", "OPEN", "Batch.\n\nCloses #301\n"),
])
r, calls = ws.run()
check("open batch PR: exits 3", r.returncode == 3, (r.returncode, r.stdout, r.stderr))
check("open batch PR: prints its URL", "https://github.com/acme/ledger/pull/32" in r.stdout, r.stdout)
check("open batch PR: opens no PR", "pr create" not in calls, calls)
ws.remove()

ws = Workspace()
ws.git("branch", "pre-main")
ws.push()
ws.state([])
r, calls = ws.run()
check("pre-main level with main: exits 4", r.returncode == 4, (r.returncode, r.stdout, r.stderr))
check("pre-main level with main: says so", "not ahead of main" in r.stdout, r.stdout)
check("pre-main level with main: opens no PR", "pr create" not in calls, calls)
ws.remove()

print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
