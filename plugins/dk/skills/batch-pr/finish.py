#!/usr/bin/env python3
"""Finish a merged batch: bring pre-main level with main, set the checkouts up, list the cleanup.

Run from inside the repo once the batch PR from pre-main into main has merged. It fetches
origin's main and pre-main, then:

  1. fast-forwards origin's pre-main to origin/main (a plain push, never forced), and the local
     main and pre-main to it: in the worktree that has one checked out, by git merge --ff-only;
  2. runs, in each worktree that has main or pre-main checked out, every backticked command on
     the **Fresh-worktree setup** line of its docs/agents/workflow.md, in order, through sh;
     a workflow.md without that line skips this part;
  3. runs dk-gc --dry-run in this checkout and prints its list.

Nothing moves unless every branch can: pre-main on origin and both local branches must be
ancestors of origin/main, and a worktree that has one checked out must hold no uncommitted
change to a tracked file. Otherwise it names the branch and exits 1, having changed nothing.

Exit 0: finished. Exit 1: a branch cannot fast-forward, git failed, or a setup command failed
(it names the command; the branches have moved by then). A missing dk-gc is reported, not failed.
"""
import pathlib
import re
import shutil
import subprocess
import sys

DEFAULT, BASE = "main", "pre-main"
SETUP_LINE = re.compile(r"^.*\*\*Fresh-worktree setup\*\*.*$", re.M)


def sh(*cmd, cwd=None, ok=(0,)):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode not in ok:
        sys.exit(f"{' '.join(cmd)}: {(r.stderr or r.stdout).strip() or r.returncode}")
    return r


def rev(ref):
    r = sh("git", "rev-parse", "-q", "--verify", f"{ref}^{{commit}}", ok=(0, 1))
    return r.stdout.strip() or None


def is_ancestor(old, new):
    return sh("git", "merge-base", "--is-ancestor", old, new, ok=(0, 1)).returncode == 0


def checked_out():
    """{branch: worktree path} for the worktrees that have a branch checked out."""
    out, path = {}, None
    for line in sh("git", "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/"):
            out[line[len("branch refs/heads/"):]] = path
    return out


def setup_commands(tree):
    workflow = pathlib.Path(tree) / "docs" / "agents" / "workflow.md"
    line = SETUP_LINE.search(workflow.read_text()) if workflow.exists() else None
    return re.findall(r"`([^`]+)`", line.group(0).split("**Fresh-worktree setup**", 1)[1]) if line else []


def main():
    if len(sys.argv) > 1:
        print(__doc__.strip())
        return 0 if sys.argv[1] in ("-h", "--help") else 1

    sh("git", "fetch", "-q", "origin", *(f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in (DEFAULT, BASE)))
    target = rev(f"origin/{DEFAULT}")
    if not target:
        sys.exit(f"origin has no {DEFAULT}, so there is nothing to fast-forward to.")
    trees = checked_out()

    # Every check before the first change, so a branch that cannot move leaves all of them where they were.
    moves = []  # (name, ref, old sha)
    for name, ref in ((f"origin/{BASE}", f"refs/remotes/origin/{BASE}"), (DEFAULT, f"refs/heads/{DEFAULT}"),
                      (BASE, f"refs/heads/{BASE}")):
        old = rev(ref)
        if old is None or old == target:
            continue
        if not is_ancestor(old, target):
            ahead = sh("git", "rev-list", "--count", f"{target}..{old}").stdout.strip()
            sys.exit(f"{name} cannot fast-forward to origin/{DEFAULT}: it holds {ahead} commit(s) origin/{DEFAULT} "
                     f"lacks. Has the batch PR merged, and as a merge commit? Nothing was changed.")
        tree = trees.get(ref[len("refs/heads/"):]) if ref.startswith("refs/heads/") else None
        if tree and sh("git", "status", "--porcelain", "--untracked-files=no", cwd=tree).stdout.strip():
            sys.exit(f"{name} is checked out in {tree} with uncommitted changes, so it cannot fast-forward. "
                     "Nothing was changed.")
        moves.append((name, ref, old, tree))

    for name, ref, old, tree in moves:
        if ref.startswith("refs/remotes/"):
            sh("git", "push", "-q", "origin", f"{target}:refs/heads/{BASE}")
        elif tree:
            sh("git", "merge", "-q", "--ff-only", target, cwd=tree)
        else:
            sh("git", "update-ref", ref, target, old)
        print(f"{name}: {old[:12]} -> {target[:12]}")
    if not moves:
        print(f"{BASE} and {DEFAULT} are level with origin/{DEFAULT} at {target[:12]}.")

    for branch in (DEFAULT, BASE):
        tree = trees.get(branch)
        if not tree:
            continue
        commands = setup_commands(tree)
        if not commands:
            print(f"{tree}: its workflow.md names no **Fresh-worktree setup** line; no setup run.")
        for command in commands:
            print(f"{tree}: {command}")
            r = subprocess.run(["sh", "-c", command], cwd=tree)
            if r.returncode:
                sys.exit(f"Setup failed in {tree}: `{command}` exited {r.returncode}. The branches have moved.")

    if not shutil.which("dk-gc"):
        print("No cleanup list: dk-gc is not on PATH.")
        return 0
    top = sh("git", "rev-parse", "--show-toplevel").stdout.strip()
    gc = subprocess.run(["dk-gc", "--dry-run"], cwd=top, capture_output=True, text=True)
    print("\n## Cleanup (dk-gc --dry-run)")
    print((gc.stdout + gc.stderr).rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
