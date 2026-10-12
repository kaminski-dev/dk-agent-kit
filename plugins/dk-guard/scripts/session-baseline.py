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
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

MAX_LINES = 15
MAX_FILES = 5
MAX_DBS = 3
MAX_CHARS = 200
ISSUE = re.compile(r"^[^/]+/(\d+)(?:-|$)")
DEFAULT_TIMEOUT = 5.0


def timeout():
    """Seconds each gh or docker call gets; the three calls run side by side, inside the hook's timeout."""
    try:
        value = float(os.environ.get("DK_BASELINE_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if 0 < value < float("inf") else DEFAULT_TIMEOUT


def run(cmd, cwd):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout(),
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
    head = f"{os.path.basename(primary)} · {branch} · {where}"
    lines = changes(top)
    match = ISSUE.match(branch)
    issue = match.group(1) if match else None
    with ThreadPoolExecutor(3) as pool:
        pr_lines = pool.submit(pull_request, top, branch)
        issue_lines = pool.submit(issue_labels, top, issue)
        db_lines = pool.submit(databases, top, primary, issue)
        lines += pr_lines.result() + issue_lines.result() + db_lines.result()
    # The head keeps its paths whole; titles, labels and file names are cut.
    return [head] + [line if len(line) <= MAX_CHARS else line[:MAX_CHARS - 1] + "…" for line in lines]


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


def gh_json(top, *args):
    out = run(["gh", *args], top)
    if out is None:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def pull_request(top, branch):
    prs = gh_json(top, "pr", "list", "--head", branch, "--state", "open", "--json", "number,title,url", "--limit", "1")
    if not isinstance(prs, list):
        return []
    if not prs:
        return ["PR: none open for this branch"]
    pr = prs[0]
    return [f"PR #{pr.get('number')} open: {pr.get('title')} {pr.get('url')}"]


def issue_labels(top, issue):
    if not issue:
        return []
    data = gh_json(top, "issue", "view", issue, "--json", "number,title,state,labels")
    if not isinstance(data, dict):
        return []
    labels = ", ".join(label.get("name", "") for label in data.get("labels") or []) or "none"
    return [f"issue #{issue} ({str(data.get('state', '')).lower()}) {data.get('title')}: labels {labels}"]


def databases(top, primary, issue):
    """The dk-pg containers for this issue: dk-pg labels them with the primary checkout's path."""
    if not issue:
        return []
    out = run(["docker", "ps", "--filter", f"label=dk.root={primary}", "--filter", f"label=dk.issue={issue}",
               "--format", "{{.Names}}\t{{.Ports}}"], top)
    if out is None:
        return []
    rows = [row.replace("\t", " ") for row in out.splitlines() if row.strip()]
    if not rows:
        return [f"dk-pg: none running for #{issue}"]
    lines = [f"dk-pg #{issue}: {row}" for row in rows[:MAX_DBS]]
    if len(rows) > MAX_DBS:
        lines.append(f"dk-pg #{issue}: … {len(rows) - MAX_DBS} more")
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
