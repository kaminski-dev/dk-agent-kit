#!/usr/bin/env python3
"""Runs stop-gate.py as a real Stop hook against throwaway git repos.

Each case builds a repo with or without an executable .claude/gate.sh, with a
clean or dirty tree, and checks what the hook prints: a block with the gate's
last lines, a user-only message, or nothing.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "stop-gate.py")

PASS = "#!/bin/sh\necho 'lint ok'\ntouch .gate-ran\n"
FAIL = ("#!/bin/sh\ntouch .gate-ran\necho 'first line, scrolled away'\n"
        "for i in $(seq 1 60); do echo \"noise $i\"; done\n"
        "echo 'src/a.ts(3,1): error TS2304: Cannot find name foo' >&2\nexit 1\n")


def make_repo(root, name, gate=None, executable=True, dirty=True):
    path = os.path.join(root, name)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", path]
    subprocess.run(["git", "init", "-q", path], check=True)
    os.makedirs(os.path.join(path, ".claude"))
    with open(os.path.join(path, ".gitignore"), "w") as f:
        f.write(".gate-ran\n")
    if gate is not None:
        gate_path = os.path.join(path, ".claude", "gate.sh")
        with open(gate_path, "w") as f:
            f.write(gate)
        if executable:
            os.chmod(gate_path, os.stat(gate_path).st_mode | stat.S_IXUSR)
    os.makedirs(os.path.join(path, "src"))
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
    if dirty:
        with open(os.path.join(path, "src", "a.ts"), "w") as f:
            f.write("foo\n")
    return path


def run(cwd, active=False):
    payload = {"session_id": "test", "cwd": cwd, "hook_event_name": "Stop",
               "stop_hook_active": active, "last_assistant_message": "Done."}
    out = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(payload),
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    return out.returncode, json.loads(out.stdout) if out.stdout.strip() else None, out.stderr


def gate_ran(repo):
    return os.path.exists(os.path.join(repo, ".gate-ran"))


def case_failing_gate_blocks_with_last_lines(root):
    repo = make_repo(root, "failing", FAIL)
    code, out, _ = run(repo)
    assert code == 0, code
    assert out and out.get("decision") == "block", out
    assert "error TS2304: Cannot find name foo" in out["reason"], out["reason"]
    assert "noise 60" in out["reason"], out["reason"]
    assert "first line, scrolled away" not in out["reason"], "reason should hold only the last lines"


def case_failing_gate_found_from_a_subdirectory(root):
    repo = make_repo(root, "subdir", FAIL)
    code, out, _ = run(os.path.join(repo, "src"))
    assert out and out.get("decision") == "block", out


def case_passing_gate_is_silent(root):
    repo = make_repo(root, "passing", PASS)
    code, out, err = run(repo)
    assert (code, out, err) == (0, None, ""), (code, out, err)
    assert gate_ran(repo)


def case_no_gate_does_nothing(root):
    repo = make_repo(root, "no-gate")
    assert run(repo) == (0, None, "")


def case_gate_not_executable_does_nothing(root):
    repo = make_repo(root, "not-executable", FAIL, executable=False)
    assert run(repo) == (0, None, "")
    assert not gate_ran(repo)


def case_clean_tree_skips_the_gate(root):
    repo = make_repo(root, "clean", FAIL, dirty=False)
    assert run(repo) == (0, None, "")
    assert not gate_ran(repo)


def case_outside_a_repo_does_nothing(root):
    plain = os.path.join(root, "plain")
    os.makedirs(plain)
    assert run(plain) == (0, None, "")


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
