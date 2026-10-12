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

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "session-baseline.py")

# A stub prints <name>.out for its arguments' key and exits 0, or exits 1 when no answer is canned.
STUB = """#!/bin/sh
dir=$(dirname "$0")
echo "$*" >> "$dir/{name}.calls"
key=$(printf %s "$1-$2")
[ -f "$dir/{name}.$key.sleep" ] && sleep "$(cat "$dir/{name}.$key.sleep")"
[ -f "$dir/{name}.$key.out" ] || exit 1
cat "$dir/{name}.$key.out"
"""


def make_stubs(root, name, answers=None):
    """answers maps 'gh pr-list' style keys (tool, first two args) to stdout."""
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


def run(cwd, stubs, raw=None):
    payload = {"session_id": "test", "cwd": cwd, "hook_event_name": "SessionStart", "source": "startup"}
    out = subprocess.run([sys.executable, "-I", HOOK], input=raw if raw is not None else json.dumps(payload),
                         capture_output=True, text=True,
                         env={"PATH": stubs + os.pathsep + os.environ["PATH"], "HOME": os.environ["HOME"]})
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
        "gh pr": json.dumps([{"number": 3, "title": "Busy", "url": "https://x/pull/3"}]),
        "gh issue": json.dumps({"number": 7, "title": "Busy", "state": "OPEN",
                                "labels": [{"name": f"label-{i}"} for i in range(30)]}),
        "docker ps": "".join(f"dk-pg-busy-{i}\t127.0.0.1:{5000 + i}->5432/tcp\n" for i in range(20)),
    })
    code, out, err = run(repo, stubs)
    assert code == 0, (code, err)
    assert 0 < len(out.splitlines()) <= 15, out
    assert "uncommitted: 40 files" in out, out


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
