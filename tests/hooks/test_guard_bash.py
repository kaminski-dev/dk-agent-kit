#!/usr/bin/env python3
"""Replays guard_bash_cases.json through guard-bash.py's decide(), in this process.

Each case runs in a throwaway git repo checked out on `main` or on a feature
branch, so implicit pushes resolve the way they would in a session (`"repo":
"verify"`: in a dk:verify run directory, `<scratch>/50/verify.Ab3dE9`; the `main` one holds `linked`, a link into the feature repo), and with a
throwaway HOME whose zsh alias list holds ALIASES (`"aliases": false`: a HOME
without the list). A case with `"process": true` or `max_seconds` runs as a real
hook call instead: the command hooks.json names for the Bash guard, through
`sh -c` as the harness starts it, JSON on stdin to the answer on stdout, so the
wiring stays covered; a `max_seconds` case fails when the hook takes longer, and
a case with `says` when the reason leaves out any of its phrases. The process
cases must hold an allow, a deny, an ask, a hint and a `max_seconds` case.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, "..", "..", "plugins", "dk-guard"))
GUARD = os.path.join(PLUGIN, "scripts", "guard-bash.py")
ALIASES = ["g", "gs", "gst", "ll"]
LEVELS = ("allow", "deny", "ask", "hint")
PATH = os.environ["PATH"]


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


def load_guard():
    spec = importlib.util.spec_from_file_location("guard_bash", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hook_command():
    """The command hooks.json runs before each Bash call and blocks on, with the plugin root filled in."""
    groups = json.load(open(os.path.join(PLUGIN, "hooks", "hooks.json")))["hooks"]["PreToolUse"]
    command, = [h["command"] for g in groups if g["matcher"] == "Bash" for h in g["hooks"]
                if h.get("onFailure") == "block"]
    return command.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN)


def by_process(case):
    return case.get("process", False) or "max_seconds" in case


def decide(guard, cmd, cwd, home, background=False):
    os.environ.clear()  # the environment a hook process gets in run(): the git calls inside decide() inherit it
    os.environ.update({"PATH": PATH, "HOME": home})
    try:
        return guard.decide(cmd, cwd, background)
    except Exception as e:  # what the hook process exits nonzero on
        return "crash", f"{type(e).__name__}: {e}"


def run(cmd, cwd, home, background=False, max_seconds=None):
    tool_input = {"command": cmd}
    if background:  # the harness sends the key only when the call sets it
        tool_input["run_in_background"] = True
    payload = {"session_id": "test", "cwd": cwd, "hook_event_name": "PreToolUse",
               "tool_name": "Bash", "tool_input": tool_input}
    try:
        out = subprocess.run(["sh", "-c", hook_command()], input=json.dumps(payload), timeout=max_seconds,
                             capture_output=True, text=True, env={"PATH": PATH, "HOME": home})
    except subprocess.TimeoutExpired:
        return "slow", f"took over {max_seconds} s"
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
    process = [c for c in cases if by_process(c)]
    missing = [l for l in LEVELS if not any(c["expect"] == l for c in process)] \
        + ["max_seconds"] * (not any("max_seconds" in c for c in process))
    guard = load_guard()
    failed = 0
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as root:
        repos = {"main": make_repo(root, "main-checkout", "main"),
                 "feature": make_repo(root, "feature", "feat/x"),
                 "none": root,
                 "verify": os.path.join(root, "50", "verify.Ab3dE9")}
        os.makedirs(os.path.join(repos["verify"], "shots"))
        os.symlink(os.path.join(repos["feature"], ".git"), os.path.join(repos["main"], "linked"))
        homes = {True: make_home(root, "home", ALIASES), False: make_home(root, "home-no-aliases", None)}
        for case in cases:
            cwd, home = repos[case.get("repo", "none")], homes[case.get("aliases", True)]
            background = case.get("background", False)
            if by_process(case):
                got, reason = run(case["cmd"], cwd, home, background, case.get("max_seconds"))
            else:
                got, reason = decide(guard, case["cmd"], cwd, home, background)
            ok = got == case["expect"] and all(phrase in reason for phrase in case.get("says", []))
            failed += not ok
            mark = "ok  " if ok else "FAIL"
            tags = (" [bg]" if background else "") + (" [process]" if by_process(case) else "")
            print(f"{mark} {case['expect']:5} got {got:5} | {case['cmd'].splitlines()[0][:90]}{tags}")
            if not ok and reason:
                print(f"       reason: {reason}")
    print(f"\n{len(cases) - failed}/{len(cases)} passed ({len(process)} as hook processes) "
          f"in {time.monotonic() - start:.1f} s")
    if missing:
        print("FAIL the process cases lack: " + ", ".join(missing) + " (mark one with \"process\": true)")
    sys.exit(1 if failed or missing else 0)


if __name__ == "__main__":
    main()
