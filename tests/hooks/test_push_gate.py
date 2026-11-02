#!/usr/bin/env python3
"""Runs push-gate.py as a real PreToolUse hook against throwaway git repos.

Each case builds a main checkout with a linked worktree, the way sessions run:
the session's cwd is the clean main checkout and the agent pushes from the
worktree (`cd <worktree> && git push`). The case checks what the hook prints
(a deny with the gate's last lines, a user-only message, or nothing) and
whether the worktree's gate ran.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "push-gate.py")

PASS = "#!/bin/sh\necho 'lint ok'\ntouch .gate-ran\n"
FAIL = ("#!/bin/sh\ntouch .gate-ran\necho 'first line, scrolled away'\n"
        "for i in $(seq 1 60); do echo \"noise $i\"; done\n"
        "echo 'src/a.ts(3,1): error TS2304: Cannot find name foo' >&2\nexit 1\n")


def git(path, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", path, *args],
                   check=True, capture_output=True)


def write_gate(repo, gate):
    path = os.path.join(repo, ".claude", "gate.sh")
    with open(path, "w") as f:
        f.write(gate)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def make_checkout(root, name, worktree_gate=None):
    """A main checkout on main, whose committed gate passes, and a linked worktree on feat/<name>, whose gate is
    `worktree_gate` (None: the worktree has no gate). Returns (main checkout, worktree)."""
    main = os.path.join(root, name)
    subprocess.run(["git", "init", "-q", "-b", "main", main], check=True)
    os.makedirs(os.path.join(main, ".claude"))
    with open(os.path.join(main, ".gitignore"), "w") as f:
        f.write(".gate-ran\n")
    write_gate(main, PASS)
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "init")
    wt = os.path.join(root, name + "-1")
    git(main, "worktree", "add", "-q", wt, "-b", f"feat/{name}")
    if worktree_gate is None:
        git(wt, "rm", "-q", ".claude/gate.sh")
    else:
        write_gate(wt, worktree_gate)
        git(wt, "add", "-A")
    git(wt, "commit", "-q", "--allow-empty", "-m", "work")
    return main, wt


def run(cwd, command, env=None):
    payload = {"session_id": "test", "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}}
    out = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(payload),
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"], **(env or {})})
    return out.returncode, json.loads(out.stdout) if out.stdout.strip() else None, out.stderr


def gate_ran(repo):
    return os.path.exists(os.path.join(repo, ".gate-ran"))


def denial(out):
    spec = (out or {}).get("hookSpecificOutput") or {}
    return spec.get("permissionDecisionReason") if spec.get("permissionDecision") == "deny" else None


def case_failing_gate_in_the_pushed_worktree_denies_with_last_lines(root):
    main, wt = make_checkout(root, "failing", FAIL)
    code, out, err = run(main, f"cd {wt} && git push -u origin feat/failing")
    reason = denial(out)
    assert code == 0 and reason, (code, out, err)
    assert "error TS2304: Cannot find name foo" in reason and "noise 60" in reason, reason
    assert "first line, scrolled away" not in reason, "reason should hold only the last lines"
    assert gate_ran(wt) and not gate_ran(main)


def case_passing_gate_in_the_pushed_worktree_allows(root):
    main, wt = make_checkout(root, "passing", PASS)
    assert run(main, f"cd {wt} && git push -u origin feat/passing") == (0, None, "")
    assert gate_ran(wt)


def case_git_dash_c_push_runs_the_worktree_gate(root):
    main, wt = make_checkout(root, "dash-c", FAIL)
    assert denial(run(main, f"git -C {wt} push")[1])


def case_bare_push_from_the_session_cwd_runs_its_gate(root):
    _, wt = make_checkout(root, "bare", FAIL)
    assert denial(run(wt, "git add -A && git commit -qm x; git push")[1])


def case_command_the_splitter_cannot_read_still_runs_the_gate(root):
    main, wt = make_checkout(root, "unsplittable", FAIL)
    assert denial(run(main, f'cd {wt} && git push; echo "unterminated')[1])


def case_command_without_a_push_runs_no_gate(root):
    main, wt = make_checkout(root, "no-push", FAIL)
    assert run(main, f"cd {wt} && git status && echo push") == (0, None, "")
    assert not gate_ran(wt)


def case_verify_assets_push_runs_no_gate(root):
    main, wt = make_checkout(root, "assets", FAIL)
    for cmd in (f"cd {wt} && git push origin HEAD:verify-assets/47",
                f"cd {wt} && git push --force-with-lease origin verify-assets/47"):
        assert run(main, cmd) == (0, None, ""), cmd
    git(wt, "switch", "-q", "-c", "verify-assets/49")
    assert run(main, f"cd {wt} && git push -u origin HEAD") == (0, None, "")
    assert not gate_ran(wt)


def case_branch_delete_runs_no_gate(root):
    main, wt = make_checkout(root, "delete", FAIL)
    for cmd in (f"cd {wt} && git push origin --delete feat/old", f"cd {wt} && git push origin :feat/old",
                f"cd {wt} && git push -d origin feat/old"):
        assert run(main, cmd) == (0, None, ""), cmd
    assert not gate_ran(wt)


def case_push_the_guard_denies_runs_no_gate(root):
    main, wt = make_checkout(root, "to-main", FAIL)
    assert run(main, f"cd {wt} && git push origin HEAD:main") == (0, None, "")
    assert not gate_ran(wt)


def case_worktree_without_a_gate_does_nothing(root):
    main, wt = make_checkout(root, "no-gate")
    assert run(main, f"cd {wt} && git push") == (0, None, "")
    assert not gate_ran(main), "the main checkout's gate must not stand in for the pushed worktree's"


def case_push_outside_a_repo_does_nothing(root):
    plain = os.path.join(root, "plain")
    os.makedirs(plain)
    assert run(root, f"cd {plain} && git push origin feat/x") == (0, None, "")


def case_directory_known_only_at_run_time_runs_no_gate_and_says_so(root):
    main, wt = make_checkout(root, "runtime", FAIL)
    code, out, err = run(main, f'WT={wt}; cd "$WT" && git push origin feat/runtime')
    context = ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
    assert code == 0 and not denial(out) and "did not run" in context, (code, out, err)
    assert not gate_ran(wt)


def case_gate_that_hangs_lets_the_push_through_and_says_so(root):
    main, wt = make_checkout(root, "hangs", "#!/bin/sh\necho 'starting tests'\nsleep 30\n")
    code, out, err = run(main, f"cd {wt} && git push", env={"DK_PUSH_GATE_TIMEOUT": "1"})
    assert code == 0 and out and not denial(out), (code, out, err)
    assert "timed out after 1 s" in out.get("systemMessage", "") and "starting tests" in out["systemMessage"], out


def case_decisions_go_to_the_guard_log(root):
    main, wt = make_checkout(root, "logged", FAIL)
    data = os.path.join(root, "plugin-data")
    os.makedirs(data)
    cmd = f"cd {wt} && git push"
    run(main, cmd, env={"CLAUDE_PLUGIN_DATA": data})
    with open(os.path.join(data, "guard-bash.jsonl")) as f:
        event = json.loads(f.read().splitlines()[-1])
    assert event["decision"] == "deny" and event["command"] == cmd and event["cwd"] == main, event
    assert event["session"] == "test" and "push gate" in event["reason"], event


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as root:
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
