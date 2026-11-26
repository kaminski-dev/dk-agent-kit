#!/usr/bin/env python3
"""Runs dk-gate against throwaway git repos whose gate records each run.

Each case builds a repo with a committed .claude/gate.sh that appends a line
to .gate-runs (ignored, so the record never changes the tree it gates), runs
`dk-gate` in it with the cache in a temp directory (DK_GATE_CACHE), and checks
the exit code, what it printed and how many times the gate ran.
"""
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DK_GATE = os.path.join(HERE, "..", "plugins", "dk-guard", "bin", "dk-gate")

PASS = "#!/bin/sh\necho 'lint ok'\necho run >> .gate-runs\n"
FAIL = "#!/bin/sh\necho run >> .gate-runs\necho 'src/a.ts(3,1): error TS2304: Cannot find name foo' >&2\nexit 1\n"


def git(path, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", path, *args],
                          check=True, capture_output=True, text=True).stdout


def write(repo, rel, text, executable=False):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def make_repo(root, name, gate=PASS):
    """A repo on main with a committed gate, a lockfile and a source file, and origin/main at its first commit."""
    repo = os.path.join(root, name)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    write(repo, ".gitignore", ".gate-runs\n")
    write(repo, ".claude/gate.sh", gate, executable=True)
    write(repo, "bun.lock", "lock 1\n")
    write(repo, "src/a.ts", "export const a = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "switch", "-q", "-c", f"feat/{name}")
    return repo


def run(cwd, *args, cache):
    out = subprocess.run([DK_GATE, *args], cwd=cwd, capture_output=True, text=True,
                         env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", cwd),
                              "DK_GATE_CACHE": cache})
    return out.returncode, out.stdout + out.stderr


def runs(repo):
    try:
        with open(os.path.join(repo, ".gate-runs")) as f:
            return len(f.read().splitlines())
    except FileNotFoundError:
        return 0


def case_unchanged_tree_returns_the_cached_pass_without_running_the_gate(root):
    repo, cache = make_repo(root, "unchanged"), os.path.join(root, "cache-unchanged")
    code, out = run(repo, cache=cache)
    assert code == 0 and "lint ok" in out and runs(repo) == 1, (code, out)
    code, out = run(repo, cache=cache)
    assert code == 0 and "cached" in out and runs(repo) == 1, (code, out)


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as root:
        root = os.path.realpath(root)
        for case in CASES:
            try:
                case(root)
                print(f"ok   {case.__name__[5:]}")
            except Exception as e:
                failed += 1
                print(f"FAIL {case.__name__[5:]}: {e!r}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
