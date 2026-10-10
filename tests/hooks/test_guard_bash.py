#!/usr/bin/env python3
"""Replays guard_bash_cases.json through guard-bash.py as real hook calls.

Each case runs in a throwaway git repo checked out on `main` or on a feature
branch, so implicit pushes resolve the way they would in a session.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "guard-bash.py")


def make_repo(root, name, branch):
    path = os.path.join(root, name)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", "-C"]
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", path], check=True)
    subprocess.run(git + [path, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    if branch != "main":
        subprocess.run(git + [path, "checkout", "-q", "-b", branch], check=True)
    return path


def run(cmd, cwd):
    payload = {"session_id": "test", "cwd": cwd, "hook_event_name": "PreToolUse",
               "tool_name": "Bash", "tool_input": {"command": cmd}}
    out = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(payload),
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    if out.returncode != 0:
        return "crash", out.stderr.strip()
    if not out.stdout.strip():
        return "allow", ""
    spec = json.loads(out.stdout)["hookSpecificOutput"]
    if "permissionDecision" in spec:
        return spec["permissionDecision"], spec.get("permissionDecisionReason", "")
    return "hint", spec.get("additionalContext", "")


def main():
    cases = json.load(open(os.path.join(HERE, "guard_bash_cases.json")))
    failed = 0
    with tempfile.TemporaryDirectory() as root:
        repos = {"main": make_repo(root, "main-checkout", "main"),
                 "feature": make_repo(root, "feature", "feat/x"),
                 "none": root}
        for case in cases:
            cwd = repos[case.get("repo", "none")]
            got, reason = run(case["cmd"], cwd)
            ok = got == case["expect"]
            failed += not ok
            mark = "ok  " if ok else "FAIL"
            print(f"{mark} {case['expect']:5} got {got:5} | {case['cmd'].splitlines()[0][:90]}")
            if not ok and reason:
                print(f"       reason: {reason}")
    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
