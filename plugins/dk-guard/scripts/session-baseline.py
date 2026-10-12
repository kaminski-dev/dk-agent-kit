#!/usr/bin/env python3
"""dk-guard SessionStart hook: where this session stands, in at most 15 lines.

Repo and branch, whether the session is in a linked worktree or the primary
checkout, uncommitted changes, the open PR for the branch, the labels of the
issue the branch names (`<type>/<issue>-<slug>`), and the dk-pg databases
running for that issue. Claude Code adds the output to the session's context.
Outside a git repo it prints nothing. gh and docker are asked with a short
timeout and left out when they fail; any other error prints nothing (fails open).
"""
import json
import os
import subprocess
import sys

MAX_LINES = 15
MAX_FILES = 5


def run(cmd, cwd, timeout=5):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def git(cwd, *args):
    return run(["git", "-C", cwd, *args], cwd)


def baseline(cwd):
    paths = git(cwd, "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-dir", "--git-common-dir")
    if not paths or len(paths.splitlines()) != 3:
        return []
    top, git_dir, common_dir = paths.splitlines()
    primary = os.path.dirname(common_dir)
    branch = (git(top, "branch", "--show-current") or "").strip()
    if not branch:
        branch = "detached at " + (git(top, "rev-parse", "--short", "HEAD") or "?").strip()
    if os.path.realpath(git_dir) == os.path.realpath(common_dir):
        where = "primary checkout"
    else:
        where = f"worktree {top} (primary: {primary})"
    lines = [f"{os.path.basename(primary)} · {branch} · {where}"]
    lines += changes(top)
    return lines


def changes(top):
    status = git(top, "status", "--porcelain")
    if status is None:
        return []
    entries = status.splitlines()
    if not entries:
        return ["uncommitted: none"]
    lines = [f"uncommitted: {len(entries)} file{'s' if len(entries) != 1 else ''}"]
    lines += ["  " + e for e in entries[:MAX_FILES]]
    if len(entries) > MAX_FILES:
        lines.append(f"  … {len(entries) - MAX_FILES} more")
    return lines


def main():
    try:
        data = json.load(sys.stdin)
        lines = baseline(data.get("cwd") or os.getcwd())
    except Exception:
        return  # fail open: say nothing rather than something wrong
    if lines:
        print("\n".join(lines[:MAX_LINES]))


if __name__ == "__main__":
    main()
