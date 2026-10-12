#!/usr/bin/env python3
"""Runs session-baseline.py as a real SessionStart hook against throwaway git repos.

`gh` and `docker` are stub scripts first on PATH: each answers from a canned
file in the stub directory, or fails when there is none, so no case reaches
GitHub or a Docker daemon. The checks read the hook's stdout, which Claude
Code adds to the session's context.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "session-baseline.py")

# A stub answers from <tool>.<arg1>-<arg2>.out, else <tool>.<arg1>.out, else exits 1;
# a matching .sleep file makes it sleep that many seconds first. Calls are logged.
STUB = """#!/bin/sh
dir=$(dirname "$0")
echo "$*" >> "$dir/{name}.calls"
for key in "$1-$2" "$1"; do
  [ -f "$dir/{name}.$key.sleep" ] && sleep "$(cat "$dir/{name}.$key.sleep")"
  if [ -f "$dir/{name}.$key.out" ]; then cat "$dir/{name}.$key.out"; exit 0; fi
done
exit 1
"""


def make_stubs(root, name, answers=None):
    """answers maps keys like 'gh pr-list' or 'docker ps' to stdout; a key ending ' sleep' to seconds."""
    path = os.path.join(root, name + "-bin")
    os.makedirs(path)
    for tool in ("gh", "docker"):
        script = os.path.join(path, tool)
        with open(script, "w") as f:
            f.write(STUB.format(name=tool))
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
    for key, out in (answers or {}).items():
        tool, args = key.split(" ", 1)
        suffix = "sleep" if args.endswith(" sleep") else "out"
        with open(os.path.join(path, f"{tool}.{args.removesuffix(' sleep')}.{suffix}"), "w") as f:
            f.write(out)
    return path


def calls(stubs, tool):
    try:
        with open(os.path.join(stubs, f"{tool}.calls")) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def make_repo(root, name, branch="main"):
    path = os.path.join(root, name)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", path]
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", path], check=True)
    with open(os.path.join(path, "README.md"), "w") as f:
        f.write("hi\n")
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
    if branch != "main":
        subprocess.run(git + ["checkout", "-q", "-b", branch], check=True)
    return path


def run(cwd, stubs, raw=None, env=None):
    payload = {"session_id": "test", "cwd": cwd, "hook_event_name": "SessionStart", "source": "startup"}
    out = subprocess.run([sys.executable, "-I", HOOK], input=raw if raw is not None else json.dumps(payload),
                         capture_output=True, text=True,
                         env={"PATH": stubs + os.pathsep + os.environ["PATH"], "HOME": os.environ["HOME"],
                              **(env or {})})
    return out.returncode, out.stdout, out.stderr


def case_primary_checkout_names_repo_and_branch(root):
    repo = make_repo(root, "acme")
    code, out, err = run(repo, make_stubs(root, "primary"))
    assert code == 0, (code, err)
    first = out.splitlines()[0]
    assert "acme" in first and "main" in first and "primary checkout" in first, out


def case_linked_worktree_with_uncommitted_changes(root):
    repo = make_repo(root, "wt-main")
    wt = os.path.join(root, "wt-main-19")
    subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b", "feat/19-session-hooks", wt], check=True)
    with open(os.path.join(wt, "README.md"), "a") as f:
        f.write("more\n")
    with open(os.path.join(wt, "new.py"), "w") as f:
        f.write("x = 1\n")
    code, out, err = run(wt, make_stubs(root, "wt"))
    assert code == 0, (code, err)
    assert "feat/19-session-hooks" in out and f"worktree {wt}" in out and repo in out, out
    assert "uncommitted: 2 files" in out and "README.md" in out and "new.py" in out, out


def case_long_worktree_paths_are_kept_whole(root):
    deep = os.path.join(root, "a-rather-long-directory-name-" * 4)
    os.makedirs(deep)
    repo = make_repo(deep, "deep-main")
    wt = os.path.join(deep, "deep-main-19")
    subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b", "feat/19-deep", wt], check=True)
    _, out, _ = run(wt, make_stubs(root, "deep"))
    assert f"worktree {wt}" in out and f"primary: {repo}" in out, out


def case_clean_tree_says_so(root):
    repo = make_repo(root, "clean")
    _, out, _ = run(repo, make_stubs(root, "clean"))
    assert "uncommitted: none" in out, out


def case_many_changes_stay_within_15_lines(root):
    repo = make_repo(root, "busy", "feat/7-busy")
    for i in range(40):
        with open(os.path.join(repo, f"f{i:02}.txt"), "w") as f:
            f.write("x\n")
    stubs = make_stubs(root, "busy", {
        "gh pr-list": json.dumps([{"number": 3, "title": "Busy", "url": "https://x/pull/3"}]),
        "gh issue-view": json.dumps({"number": 7, "title": "Busy", "state": "OPEN",
                                "labels": [{"name": f"label-{i}"} for i in range(30)]}),
        "docker ps": "".join(f"dk-pg-busy-{i}\t127.0.0.1:{5000 + i}->5432/tcp\n" for i in range(20)),
    })
    code, out, err = run(repo, stubs)
    assert code == 0, (code, err)
    assert 0 < len(out.splitlines()) <= 15, out
    assert "uncommitted: 40 files" in out, out


def case_branch_issue_shows_pr_labels_and_its_databases(root):
    repo = make_repo(root, "linked", "feat/19-session-hooks")
    stubs = make_stubs(root, "linked", {
        "gh pr-list": json.dumps([{"number": 23, "title": "Session hooks", "url": "https://gh/pull/23"}]),
        "gh issue-view": json.dumps({"number": 19, "title": "Session hooks", "state": "OPEN",
                                     "labels": [{"name": "ready-for-agent"}, {"name": "enhancement"}]}),
        "docker ps": "dk-pg-linked-123-19\t127.0.0.1:55001->5432/tcp\n",
    })
    code, out, err = run(repo, stubs)
    assert code == 0, (code, err)
    assert "PR #23" in out and "https://gh/pull/23" in out, out
    assert "#19" in out and "ready-for-agent" in out and "enhancement" in out, out
    assert "dk-pg-linked-123-19" in out and "127.0.0.1:55001" in out, out
    assert "--head feat/19-session-hooks" in calls(stubs, "gh"), calls(stubs, "gh")
    docker = calls(stubs, "docker")
    assert f"label=dk.root={repo}" in docker and "label=dk.issue=19" in docker, docker


def case_no_pr_and_no_database_say_so(root):
    repo = make_repo(root, "quiet", "fix/4-typo")
    stubs = make_stubs(root, "quiet", {"gh pr-list": "[]", "docker ps": "",
                                       "gh issue-view": json.dumps({"number": 4, "title": "Typo", "state": "OPEN",
                                                                    "labels": []})})
    _, out, _ = run(repo, stubs)
    assert "PR: none open" in out and "dk-pg: none running for #4" in out and "#4" in out, out


def case_failing_gh_and_docker_are_left_out(root):
    repo = make_repo(root, "offline", "feat/5-offline")
    code, out, err = run(repo, make_stubs(root, "offline"))
    assert code == 0 and err == "", (code, err)
    assert "PR" not in out and "dk-pg" not in out and "#5" not in out, out
    assert out.startswith("offline · feat/5-offline"), out


def case_branch_without_issue_skips_issue_and_databases(root):
    repo = make_repo(root, "no-issue")
    stubs = make_stubs(root, "no-issue", {"gh pr-list": "[]"})
    _, out, _ = run(repo, stubs)
    assert "issue" not in calls(stubs, "gh") and calls(stubs, "docker") == "", (calls(stubs, "gh"), out)


def case_slow_gh_is_cut_off(root):
    repo = make_repo(root, "slow", "feat/6-slow")
    stubs = make_stubs(root, "slow", {"gh pr-list sleep": "10", "gh pr-list": "[]"})
    start = time.monotonic()
    code, out, _ = run(repo, stubs, env={"DK_BASELINE_TIMEOUT": "1"})
    assert time.monotonic() - start < 5, f"hook waited {time.monotonic() - start:.0f} s for gh"
    assert code == 0 and out.startswith("slow · feat/6-slow") and "PR" not in out, out


def case_unexpected_payload_is_silent(root):
    repo = make_repo(root, "payload")
    stubs = make_stubs(root, "payload")
    assert run(repo, stubs, raw="not json") == (0, "", "")
    assert run(repo, stubs, raw='["a list"]') == (0, "", "")


def case_outside_a_repo_is_silent(root):
    plain = os.path.join(root, "plain")
    os.makedirs(plain)
    assert run(plain, make_stubs(root, "plain")) == (0, "", "")


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
