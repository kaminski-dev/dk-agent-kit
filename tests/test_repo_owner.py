#!/usr/bin/env python3
"""Runs dk:issue-flow's repo-owner against the eval `gh` stand-in and fixture checkouts: a repo counts as the
maintainer's own only when the gh user owns origin, origin is no fork of another owner's repo, and no upstream
remote names another owner. Anything else gets no agent marker and no `Co-Authored-By` trailer (dk:issue-flow's
**Ownership.**). Nothing reaches GitHub.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "dk" / "skills" / "issue-flow" / "repo-owner"
GH = ROOT / "plugins" / "dk" / "evals" / "_fixture" / "bin" / "gh"

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(name)


def run(viewer, remotes, repos=None, args=()):
    """repo-owner in a checkout with these {name: owner/repo} remotes, origin first, as the gh user viewer."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="dk-repo-owner-"))
    try:
        (root / ".bin").mkdir()
        (root / ".tracker").mkdir()
        shutil.copy(GH, root / ".bin" / "gh")
        (root / ".tracker" / "state.json").write_text(json.dumps(
            {"repo": remotes["origin"], "viewer": viewer, "labels": [], "issues": {}, "prs": [], "repos": repos or {}}))
        env = {"PATH": os.pathsep.join([str(root / ".bin"), os.environ["PATH"]]), "HOME": str(root), "TERM": "dumb",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(root / ".gitconfig")}
        repo = root / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], env=env, check=True)
        for name, slug in remotes.items():
            url = f"git@github.com:{slug}.git" if name == "origin" else f"https://github.com/{slug}.git"
            subprocess.run(["git", "-C", str(repo), "remote", "add", name, url], env=env, check=True)
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=repo, env=env, capture_output=True,
                              text=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


r = run("kaminski-dev", {"origin": "kaminski-dev/jetztbar-platform"})
check("the gh user's own repo: own", r.returncode == 0 and r.stdout.startswith("own: "), (r.returncode, r.stdout, r.stderr))
r = run("Kaminski-Dev", {"origin": "kaminski-dev/jetztbar-platform"})
check("logins compare without case", r.stdout.startswith("own: "), (r.stdout, r.stderr))

r = run("kaminski-dev", {"origin": "acme/app"})
check("another owner's origin: not own, naming the owner",
      r.returncode == 0 and r.stdout.startswith("not own: ") and "acme/app" in r.stdout and "acme" in r.stdout,
      (r.returncode, r.stdout, r.stderr))
r = run("kaminski-dev", {"origin": "kaminski-dev/lexical"}, {"kaminski-dev/lexical": {"parent": "facebook/lexical"}})
check("a fork of another owner's repo as origin: not own, naming its parent",
      r.stdout.startswith("not own: ") and "facebook/lexical" in r.stdout, (r.stdout, r.stderr))
r = run("kaminski-dev", {"origin": "kaminski-dev/pulsar", "upstream": "apache/pulsar"})
check("an upstream remote of another owner: not own, naming it",
      r.stdout.startswith("not own: ") and "apache/pulsar" in r.stdout, (r.stdout, r.stderr))
r = run("kaminski-dev", {"origin": "datastax/kaap", "fork": "kaminski-dev/kaap"})
check("origin upstream, the maintainer's fork under another name: not own",
      r.stdout.startswith("not own: ") and "datastax/kaap" in r.stdout, (r.stdout, r.stderr))
r = run("kaminski-dev", {"origin": "kaminski-dev/app"}, args=["facebook/lexical"])
check("a repo named on the command line, which a comment with --repo goes to: that repo is read",
      r.stdout.startswith("not own: ") and "facebook/lexical" in r.stdout, (r.stdout, r.stderr))

r = run("kaminski-dev", {"origin": "kaminski-dev/gone"}, args=["kaminski-dev/gone-too"])
check("a repo gh cannot read: fails, never a guess",
      r.returncode == 2 and "kaminski-dev/gone-too" in r.stderr and not r.stdout, (r.returncode, r.stdout, r.stderr))

print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
