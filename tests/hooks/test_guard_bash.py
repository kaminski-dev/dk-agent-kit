#!/usr/bin/env python3
"""Replays guard_bash_cases.json through guard-bash.py as real hook calls.

Each case runs in a throwaway git repo checked out on `main` or on a feature
branch, so implicit pushes resolve the way they would in a session, and with a
throwaway HOME whose zsh alias list holds ALIASES (`"aliases": false`: a HOME
without the list).
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "guard-bash.py")
ALIASES = ["g", "gs", "gst", "ll"]


def make_home(root, name, aliases):
    home = os.path.join(root, name)
    os.makedirs(os.path.join(home, ".config", "dk-agent-kit"))
    if aliases is not None:
        with open(os.path.join(home, ".config", "dk-agent-kit", "zsh-aliases"), "w") as f:
            f.write("# zsh alias names, written by bootstrap.sh\n" + "\n".join(aliases) + "\n")
    return home


def make_repo(root, name, branch):
    path = os.path.join(root, name)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", "-C"]
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", path], check=True)
    subprocess.run(git + [path, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    if branch != "main":
        subprocess.run(git + [path, "checkout", "-q", "-b", branch], check=True)
    return path


def run(cmd, cwd, home, background=False):
    tool_input = {"command": cmd}
    if background:  # the harness sends the key only when the call sets it
        tool_input["run_in_background"] = True
    payload = {"session_id": "test", "cwd": cwd, "hook_event_name": "PreToolUse",
               "tool_name": "Bash", "tool_input": tool_input}
    out = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(payload),
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": home})
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
        homes = {True: make_home(root, "home", ALIASES), False: make_home(root, "home-no-aliases", None)}
        for case in cases:
            cwd = repos[case.get("repo", "none")]
            got, reason = run(case["cmd"], cwd, homes[case.get("aliases", True)], case.get("background", False))
            ok = got == case["expect"]
            failed += not ok
            mark = "ok  " if ok else "FAIL"
            bg = " [bg]" if case.get("background") else ""
            print(f"{mark} {case['expect']:5} got {got:5} | {case['cmd'].splitlines()[0][:90]}{bg}")
            if not ok and reason:
                print(f"       reason: {reason}")
    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
