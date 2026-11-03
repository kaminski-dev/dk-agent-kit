#!/usr/bin/env python3
"""Runs the dk:batch-pr collection and review scripts against a fixture repo, the eval `gh` stand-in
and a `coderabbit` stand-in.

The workspace copies the shape plugins/dk/evals/_fixture/build.sh builds: .bin/gh
first on PATH, its state in .tracker/state.json, a bare origin beside the repo, which
origin's github.com URL is rewritten to. GH_REPO names another repo, as it does in a
session started from another checkout. Directories holding a real `coderabbit` are left
off PATH. Nothing reaches GitHub or CodeRabbit, and no case may open a PR.
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
REVIEW = ROOT / "plugins" / "dk" / "skills" / "batch-pr" / "review.py"
GH = ROOT / "plugins" / "dk" / "evals" / "_fixture" / "bin" / "gh"
ORIGIN = "https://github.com/acme/ledger.git"
INHERITED = "kaminski-dev/dk-agent-kit"

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
        path = [d for d in os.environ["PATH"].split(os.pathsep) if not (pathlib.Path(d) / "coderabbit").exists()]
        gitconfig = self.root / ".gitconfig"
        gitconfig.write_text(f'[url "file://{self.root / "origin.git"}"]\n\tinsteadOf = {ORIGIN}\n')
        self.env = {"PATH": os.pathsep.join([str(self.root / ".bin"), *path]), "HOME": str(self.root), "TERM": "dumb",
                    "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1", "GH_REPO": INHERITED}
        self.git_in(self.root, "init", "-q", "--bare", "origin.git")
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("remote", "add", "origin", ORIGIN)
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

    def run(self, cwd=None):
        r = subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=cwd or self.repo, env=self.env,
                           capture_output=True, text=True)
        log = self.root / ".tracker" / "calls.log"
        return r, log.read_text() if log.exists() else ""

    def repos_asked(self):
        log = self.root / ".tracker" / "repos.log"
        return [line.split("\t", 1)[0] for line in log.read_text().splitlines()] if log.exists() else []

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
asked = ws.repos_asked()
check("an inherited GH_REPO: every gh call asks for origin's acme/ledger",
      asked and set(asked) == {"acme/ledger"}, asked)
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

# GitHub reads a colon after the keyword as the plain form: `Closes: #N` keeps its line.
ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
colon, fixes = ws.commit("colon"), ws.commit("fixes")
ws.push()
ws.state([
    pr(24, "pre-main", "fix/12-colon", "MERGED", "Colon.\n\nCloses: #12\n", colon),
    pr(25, "pre-main", "fix/13-fixes", "MERGED", "Fixes:  #13", fixes),
])
r, _ = ws.run()
check("a colon after the keyword: the line is kept",
      r.returncode == 0 and "Closes #12\nCloses #13\n" in r.stdout and "Without a line" not in r.stdout,
      (r.returncode, r.stdout, r.stderr))
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

# A long pre-main history: 600 PRs from earlier batches, two in this one.
ws = Workspace()
earlier = ws.commit("earlier")
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
first, second = ws.commit("first"), ws.commit("second")
ws.push()
ws.state([pr(n, "pre-main", f"fix/{n}", "MERGED", f"Closes #{n}", earlier) for n in range(1000, 1600)]
         + [pr(1601, "pre-main", "fix/1601", "MERGED", "Closes #1601", first),
            pr(1602, "pre-main", "fix/1602", "MERGED", "Refs #1602", second)])
r, _ = ws.run()
check("600 earlier PRs: the batch is still collected",
      r.returncode == 0 and "Closes #1601\nRefs #1602\n" in r.stdout and "#1000" not in r.stdout,
      (r.returncode, r.stdout[-300:], r.stderr[-300:]))
ws.remove()

# A shallow checkout: the first PR's merge commit is below the clone's depth.
ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
first, second = ws.commit("first"), ws.commit("second")
ws.push()
ws.state([pr(41, "pre-main", "fix/401-first", "MERGED", "Closes #401", first),
          pr(42, "pre-main", "fix/402-second", "MERGED", "Closes #402", second)])
ws.git_in(ws.root, "clone", "-q", "--depth", "1", "--no-single-branch", ORIGIN, "shallow")
r, _ = ws.run(cwd=ws.root / "shallow")
check("shallow checkout: both PRs and both lines",
      r.returncode == 0 and "#41 PR 41" in r.stdout and "Closes #401\nCloses #402\n" in r.stdout,
      (r.returncode, r.stdout, r.stderr))
ws.remove()

# A single-branch shallow clone, the usual CI checkout: only main is in its fetch refspec.
ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
first, second = ws.commit("first"), ws.commit("second")
ws.push()
ws.state([pr(43, "pre-main", "fix/403-first", "MERGED", "Closes #403", first),
          pr(44, "pre-main", "fix/404-second", "MERGED", "Closes #404", second)])
ws.git_in(ws.root, "clone", "-q", "--depth", "1", "--branch", "main", ORIGIN, "single")
r, _ = ws.run(cwd=ws.root / "single")
check("single-branch shallow clone: both PRs and both lines",
      r.returncode == 0 and "#43 PR 43" in r.stdout and "Closes #403\nCloses #404\n" in r.stdout,
      (r.returncode, r.stdout, r.stderr))
ws.remove()

# A merged PR whose merge commit origin does not hold: stop and name it, rather than leave its line out.
ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
known = ws.commit("known")
ws.push()
ws.state([pr(51, "pre-main", "fix/501-known", "MERGED", "Closes #501", known),
          pr(52, "pre-main", "fix/502-lost", "MERGED", "Closes #502", "0123456789abcdef0123456789abcdef01234567")])
r, _ = ws.run()
check("unknown merge commit: exits 1 and names the PR",
      r.returncode == 1 and "#52" in r.stderr and "## Lines" not in r.stdout, (r.returncode, r.stdout, r.stderr))
ws.remove()

ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "-b", "fix/701-merged")
ws.commit("merged")
ws.git("checkout", "-q", "pre-main")
ws.git("merge", "-q", "--no-ff", "-m", "Merge pull request #71 from acme/fix/701-merged", "fix/701-merged")
ws.push()
ws.state([])
r, _ = ws.run()
check("merge commits but no merged PR: exits 1 and names the repo asked",
      r.returncode == 1 and "acme/ledger" in r.stderr and "## PRs" not in r.stdout, (r.returncode, r.stdout, r.stderr))
ws.remove()

ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
ws.commit("pushed")
ws.push()
ws.state([])
r, _ = ws.run()
check("a commit pushed onto pre-main (the push route) and no merged PR: an empty batch, exit 0", r.returncode == 0 and "## PRs" in r.stdout,
      (r.returncode, r.stdout, r.stderr))
ws.remove()

ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
ws.commit("pushed")
ws.git("checkout", "-q", "main")
ws.commit("hotfix")
ws.git("checkout", "-q", "pre-main")
ws.git("merge", "-q", "--no-ff", "-m", "Merge branch 'main' into pre-main", "main")
ws.push()
ws.state([])
r, _ = ws.run()
check("pre-main levelled by merging main, no merged PR: an empty batch, exit 0",
      r.returncode == 0 and "## PRs" in r.stdout, (r.returncode, r.stdout, r.stderr))
ws.remove()

ws = Workspace()
ws.git("branch", "pre-main")
ws.git("checkout", "-q", "pre-main")
first = ws.commit("first")
ws.push()
batch_prs = [pr(61, "pre-main", "fix/601-first", "MERGED", "Closes #601", first)]
ws.state(batch_prs)
before, _ = ws.run()
fix = ws.commit("fix")
ws.push()
ws.state(batch_prs + [pr(62, "pre-main", "fix/batch-review-1-period", "MERGED", "Review fix.\n\nCloses #602\n", fix)])
after, _ = ws.run()
check("fix PR merged after the first collection: the first run lacks it",
      before.returncode == 0 and "#62" not in before.stdout and "#602" not in before.stdout, before.stdout)
check("fix PR merged after the first collection: the second run lists it and its line",
      after.returncode == 0 and "- #62 PR 62" in after.stdout and "Closes #601\nCloses #602\n" in after.stdout,
      (after.returncode, after.stdout, after.stderr))
ws.remove()

# The local review. The stand-in logs its argv, its directory's HEAD and its branch, then
# reports one finding; CODERABBIT_FAIL makes it fail the way a rate limit does.
CODERABBIT = """#!/bin/sh
log="$(dirname "$0")/../.tracker/coderabbit.log"
printf '%s\\n' "$*" >> "$log"
git rev-parse HEAD >> "$log"
git rev-parse --abbrev-ref HEAD >> "$log"
if [ -n "$CODERABBIT_FAIL" ]; then echo "Rate limit exceeded, try again in 12 minutes" >&2; exit 1; fi
echo '{"type":"finding","file":"first","line":1,"severity":"minor","comment":"first is missing its trailing period"}'
"""


def review_ws():
    """A batch on pre-main, and a hotfix on main after pre-main branched: the merge base is not origin/main."""
    ws = Workspace()
    ws.git("branch", "pre-main")
    hotfix = ws.commit("hotfix")
    ws.git("checkout", "-q", "pre-main")
    ws.commit("first")
    ws.push()
    ws.git("checkout", "-q", "main")
    ws.git("fetch", "-q", "origin")
    ws.out = ws.root / "scratch" / "batch-review"
    ws.base = ws.git("merge-base", "origin/main", "origin/pre-main").strip()
    ws.head = ws.git("rev-parse", "origin/pre-main").strip()
    assert ws.base != hotfix
    return ws


def run_review(ws, env=None):
    r = subprocess.run([sys.executable, "-I", str(REVIEW), str(ws.out)], cwd=ws.repo, env={**ws.env, **(env or {})},
                       capture_output=True, text=True)
    log = ws.root / ".tracker" / "coderabbit.log"
    return r, log.read_text().splitlines() if log.exists() else []


def stub_coderabbit(ws):
    stub = ws.root / ".bin" / "coderabbit"
    stub.write_text(CODERABBIT)
    stub.chmod(0o755)


ws = review_ws()
r, calls = run_review(ws)
check("no coderabbit on PATH: exits 4 and says so",
      r.returncode == 4 and r.stdout == "No local review: coderabbit is not on PATH.\n",
      (r.returncode, r.stdout, r.stderr))
check("no coderabbit on PATH: writes nothing", not ws.out.exists() or not any(ws.out.iterdir()), r.stdout)
ws.remove()

ws = review_ws()
stub_coderabbit(ws)
r, calls = run_review(ws)
check("coderabbit on PATH: exits 0", r.returncode == 0, (r.returncode, r.stdout, r.stderr))
check("coderabbit on PATH: one agent review of the committed batch against the merge base, without --use-credits",
      calls[:1] == [f"review --agent --committed --base-commit {ws.base}"], calls)
check("coderabbit on PATH: reviews origin/pre-main's head", calls[1:2] == [ws.head], (calls, ws.head))
found = list(ws.out.glob("*")) if ws.out.exists() else []
check("coderabbit on PATH: the finding lands in the scratch directory, and its path is printed",
      len(found) == 1 and "first is missing its trailing period" in found[0].read_text() and str(found[0]) in r.stdout,
      (found, r.stdout))
check("coderabbit on PATH: the checkout keeps its branch and no worktree is left",
      ws.git("rev-parse", "--abbrev-ref", "HEAD").strip() == "main" and ws.git("worktree", "list").count("\n") == 1,
      ws.git("worktree", "list"))

# One review per batch: a fix pushed onto pre-main does not earn a second one.
ws.git("checkout", "-q", "pre-main")
ws.commit("fix")
ws.git("push", "-q", "origin", "pre-main")
ws.git("checkout", "-q", "main")
ws.git("fetch", "-q", "origin")
r, calls = run_review(ws)
check("second run for the batch: exits 3, names the first review and runs none",
      r.returncode == 3 and str(found[0] if found else "?") in r.stdout and len(calls) == 3,
      (r.returncode, r.stdout, r.stderr, calls))
ws.remove()

ws = review_ws()
stub_coderabbit(ws)
r, calls = run_review(ws, {"CODERABBIT_FAIL": "1"})
check("coderabbit fails: exits 1 with its message", r.returncode == 1 and "Rate limit exceeded" in r.stderr,
      (r.returncode, r.stdout, r.stderr))
r, calls = run_review(ws)
check("coderabbit fails: a failed run is no review, the next run reviews",
      r.returncode == 0 and len(calls) == 6, (r.returncode, r.stdout, r.stderr, calls))
check("coderabbit fails: no worktree is left", ws.git("worktree", "list").count("\n") == 1, ws.git("worktree", "list"))
ws.remove()

print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
