#!/usr/bin/env python3
"""Finish a merged batch: bring pre-main level with main, set the checkouts up, list the cleanup.

Run from inside the repo once the batch PR from pre-main into main has merged. It fetches
origin's main and pre-main (a repo whose origin has no pre-main skips origin's), then:

  1. fast-forwards origin's pre-main to origin/main (a plain push, never forced), and the local
     main and pre-main to it: in the worktree that has one checked out, by git merge --ff-only;
  2. runs, in each worktree that has main or pre-main checked out, every backticked command on
     the **Fresh-worktree setup** line of origin/main's docs/agents/workflow.md, in order, through
     sh; a workflow.md without that line skips this part;
  3. runs dk-gc --dry-run in this checkout and prints its list.

Nothing moves unless every branch can: pre-main on origin and both local branches must be
ancestors of origin/main, and a worktree that has one checked out must hold no uncommitted
change to a tracked file and no untracked or ignored file in the way of a path the fast-forward
adds (git merge overwrites ignored files, so they are checked too). Nothing moves either
when the setup line holds anything but backticked commands and the words between them
(`, then`, `and`), since prose in backticks is no command.
Otherwise it names the branch or the line and exits 1, having changed nothing.

Exit 0: finished. Exit 1: a branch cannot fast-forward, the setup line is prose, git failed, or a
setup command failed (it names the command; the branches have moved by then). A missing dk-gc is
reported, not failed.
"""
import os
import re
import shutil
import subprocess
import sys

DEFAULT, BASE = "main", "pre-main"
SETUP_LINE = re.compile(r"^.*\*\*Fresh-worktree setup\*\*:?(.*)$", re.M)
SPAN = re.compile(r"`([^`]+)`")
BETWEEN = re.compile(r"[\s,;.]*(?:(?:then|and)\b[\s,;.]*)*")


def git(*args, cwd=None, ok=(0,)):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode not in ok:
        sys.exit(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip() or r.returncode}")
    return r


def rev(ref):
    r = git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}", ok=(0, 1))
    return r.stdout.strip() or None


def is_ancestor(old, new):
    return git("merge-base", "--is-ancestor", old, new, ok=(0, 1)).returncode == 0


def in_the_way(tree, old, new):
    """Why tree cannot move from old to new without losing a file: git's refusal, or the ignored paths in the way."""
    dry = git("read-tree", "-n", "-m", "-u", old, new, cwd=tree, ok=(0, 128))
    if dry.returncode:
        return (dry.stderr or dry.stdout).strip()
    # read-tree lets ignored files go. An added path counts if anything is there, a parent of it if a file is.
    present = set()
    added = git("diff", "-z", "--no-renames", "--name-only", "--diff-filter=A", old, new).stdout.split("\0")
    for path in filter(None, added):
        if os.path.lexists(os.path.join(tree, path)):
            present.add(path)
        while path := os.path.dirname(path):
            if os.path.islink(os.path.join(tree, path)) or os.path.isfile(os.path.join(tree, path)):
                present.add(path)
    if not present:
        return ""
    checked = git("check-ignore", "-z", "--", *sorted(present), cwd=tree, ok=(0, 1)).stdout
    ignored = [p for p in checked.split("\0") if p]
    return f"it would overwrite ignored {', '.join(ignored)}" if ignored else ""


def checked_out():
    """{branch: worktree path} for the worktrees that have a branch checked out."""
    out, path = {}, None
    for line in git("worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/"):
            out[line[len("branch refs/heads/"):]] = path
    return out


def setup_commands(commit):
    """The commands on the setup line of the commit's workflow.md, [] without one; exits on a prose line."""
    workflow = git("show", f"{commit}:docs/agents/workflow.md", ok=(0, 128)).stdout
    line = SETUP_LINE.search(workflow)
    if not line:
        return []
    if not all(BETWEEN.fullmatch(text) for text in SPAN.split(line.group(1))[::2]):
        sys.exit(f"The **Fresh-worktree setup** line of docs/agents/workflow.md holds more than its commands, so "
                 f"its backticked spans are not run: {line.group(0).strip()}\nWrite it as `cmd`, then `cmd`, and "
                 "rerun. Nothing was changed.")
    return SPAN.findall(line.group(1))


def main():
    if len(sys.argv) > 1:
        print(__doc__.strip())
        return 0 if sys.argv[1] in ("-h", "--help") else 1

    listed = git("ls-remote", "--heads", "origin", *(f"refs/heads/{b}" for b in (DEFAULT, BASE))).stdout
    heads = {line.split("\t")[-1] for line in listed.splitlines()}
    on_origin = [b for b in (DEFAULT, BASE) if f"refs/heads/{b}" in heads]
    if DEFAULT not in on_origin:
        sys.exit(f"origin has no {DEFAULT}, so there is nothing to fast-forward to.")
    git("fetch", "-q", "origin", *(f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in on_origin))
    target = rev(f"origin/{DEFAULT}")
    trees = checked_out()
    commands = setup_commands(target)

    # Every check before the first change, so a branch that cannot move leaves all of them where they were.
    moves = []  # (name, ref, old sha, the worktree that has it checked out or None)
    branches = [(f"origin/{BASE}", f"refs/remotes/origin/{BASE}")] if BASE in on_origin else []
    for name, ref in branches + [(DEFAULT, f"refs/heads/{DEFAULT}"), (BASE, f"refs/heads/{BASE}")]:
        old = rev(ref)
        if old is None or old == target:
            continue
        if not is_ancestor(old, target):
            ahead = git("rev-list", "--count", f"{target}..{old}").stdout.strip()
            sys.exit(f"{name} cannot fast-forward to origin/{DEFAULT}: it holds {ahead} commit(s) origin/{DEFAULT} "
                     f"lacks. Has the batch PR merged, and as a merge commit? Nothing was changed.")
        tree = trees.get(ref[len("refs/heads/"):]) if ref.startswith("refs/heads/") else None
        if tree:
            if git("status", "--porcelain", "--untracked-files=no", cwd=tree).stdout.strip():
                sys.exit(f"{name} is checked out in {tree} with uncommitted changes, so it cannot fast-forward. "
                         "Nothing was changed.")
            if blocked := in_the_way(tree, old, target):
                sys.exit(f"{name} is checked out in {tree}, where the fast-forward cannot run: {blocked}\n"
                         "Move them aside and rerun. Nothing was changed.")
        moves.append((name, ref, old, tree))

    for name, ref, old, tree in moves:
        if ref.startswith("refs/remotes/"):
            git("push", "-q", "origin", f"{target}:refs/heads/{BASE}")
        elif tree:
            git("merge", "-q", "--ff-only", "--no-overwrite-ignore", target, cwd=tree)
        else:
            git("update-ref", ref, target, old)
        print(f"{name}: {old[:12]} -> {target[:12]}")
    if not moves:
        print(f"{BASE} and {DEFAULT} are level with origin/{DEFAULT} at {target[:12]}.")

    setup_trees = [trees[branch] for branch in (DEFAULT, BASE) if branch in trees]
    if setup_trees and not commands:
        print(f"origin/{DEFAULT}'s workflow.md names no **Fresh-worktree setup** line; no setup run.")
    for tree in setup_trees:
        for command in commands:
            print(f"{tree}: {command}")
            r = subprocess.run(["sh", "-c", command], cwd=tree)
            if r.returncode:
                sys.exit(f"Setup failed in {tree}: `{command}` exited {r.returncode}. The branches have moved.")

    if not shutil.which("dk-gc"):
        print("No cleanup list: dk-gc is not on PATH.")
        return 0
    top = git("rev-parse", "--show-toplevel").stdout.strip()
    gc = subprocess.run(["dk-gc", "--dry-run"], cwd=top, capture_output=True, text=True)
    print("\n## Cleanup (dk-gc --dry-run)")
    print((gc.stdout + gc.stderr).rstrip())
    if gc.returncode:
        print(f"dk-gc --dry-run exited {gc.returncode}, so the list may be incomplete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
