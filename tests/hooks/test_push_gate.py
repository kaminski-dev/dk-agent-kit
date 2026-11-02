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
