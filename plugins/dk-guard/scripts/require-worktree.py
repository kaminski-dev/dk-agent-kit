#!/usr/bin/env python3
"""dk-guard PreToolUse hook: no Edit or Write in an opted-in repo's primary checkout.

Several sessions share each primary checkout and only the branch pointer moves,
so parallel sessions collide there. A repo opts in with
`"env": {"DK_REQUIRE_WORKTREE": "1"}` in its committed .claude/settings.json;
an edit to a file in its primary checkout is then denied with the worktree
command from the repo's docs/agents/workflow.md. Linked worktrees, repos that
have not opted in and paths outside a repo are left alone, and so is every
edit when the hook itself fails: it fails open.
"""
import json
import os
import re
import subprocess
import sys

SETTINGS = os.path.join(".claude", "settings.json")
WORKFLOW = os.path.join("docs", "agents", "workflow.md")
COMMAND = re.compile(r"`(git worktree add [^`]+)`")


def git(cwd, *args):
    try:
        out = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def existing_dir(path):
    """The nearest directory that exists: Write may create the file's parents."""
    path = os.path.dirname(path)
    while path and not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return path or None


def opted_in(root):
    try:
        with open(os.path.join(root, SETTINGS)) as f:
            env = json.load(f).get("env") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return str(env.get("DK_REQUIRE_WORKTREE", "")).strip() not in ("", "0", "false")


def worktree_command(root):
    try:
        with open(os.path.join(root, WORKFLOW)) as f:
            match = COMMAND.search(f.read())
    except (OSError, UnicodeDecodeError):
        match = None
    return match.group(1) if match else "git worktree add ../<repo>-<issue> -b <type>/<issue>-<slug>"


def decide(data):
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path")
    if not isinstance(path, str) or not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(data.get("cwd") or os.getcwd(), path)
    where = existing_dir(path)
    if not where:
        return None
    paths = git(where, "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-dir", "--git-common-dir")
    if not paths or len(paths.splitlines()) != 3:
        return None
    root, git_dir, common_dir = paths.splitlines()
    if os.path.realpath(git_dir) != os.path.realpath(common_dir) or not opted_in(root):
        return None  # a linked worktree, or a repo that has not opted in
    return (f"{root} is a primary checkout that several sessions share, and this repo requires a worktree "
            f"for edits. Create one and edit there: {worktree_command(root)} (see {WORKFLOW}).")


def main():
    try:
        reason = decide(json.load(sys.stdin))
    except Exception:
        return  # fail open: a crash never blocks an edit
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": "dk-guard: " + reason}}))


if __name__ == "__main__":
    main()
