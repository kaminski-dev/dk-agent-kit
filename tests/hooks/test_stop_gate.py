#!/usr/bin/env python3
"""Runs stop-gate.py as a real Stop hook against throwaway git repos.

Each case builds a repo with or without an executable .claude/gate.sh, with a
clean or dirty tree, and checks what the hook prints: a block with the gate's
last lines, a user-only message, or nothing.
"""
import json
import os
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "stop-gate.py")

PASS = "#!/bin/sh\necho 'lint ok'\ntouch .gate-ran\n"
FAIL = ("#!/bin/sh\ntouch .gate-ran\necho 'first line, scrolled away'\n"
        "for i in $(seq 1 60); do echo \"noise $i\"; done\n"
        "echo 'src/a.ts(3,1): error TS2304: Cannot find name foo' >&2\nexit 1\n")
# Leaves the gate's process group, keeping the gate's stdout open, and says so once it is out.
ESCAPE = """import os, time
os.setsid()
open(".escaped", "w").close()
time.sleep(60)
"""

# The timeout cases give the gate each budget in turn. A loaded machine can start a gate too late to print its
# first line inside 1 s, so the fixture touches .started after that line: a run without it says the machine
# was slow and moves to the next budget; a run with it checks the hook in full.
BUDGETS = (1, 5, 15)
GRACE = 2  # s stop-gate.py waits for the gate's pipe after it kills the group
SLACK = 10  # s a loaded machine may add to a hook run beyond its budget and grace


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


def run(cwd, active=False, env=None, timeout=None):
    payload = {"session_id": "test", "cwd": cwd, "hook_event_name": "Stop",
               "stop_hook_active": active, "last_assistant_message": "Done."}
    out = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(payload), timeout=timeout,
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"], **(env or {})})
    return out.returncode, json.loads(out.stdout) if out.stdout.strip() else None, out.stderr


def gate_ran(repo):
    return os.path.exists(os.path.join(repo, ".gate-ran"))


def within_a_budget(attempt):
    for budget in BUDGETS:
        if attempt(budget):
            return
    raise AssertionError(f"the fixture gate never printed its first line inside {BUDGETS[-1]} s")


def started(repo):
    return os.path.exists(os.path.join(repo, ".started"))


def child_pid(repo):
    try:
        with open(os.path.join(repo, ".child")) as f:
            return int(f.read())
    except (FileNotFoundError, ValueError):  # ValueError: the gate was cut off while it wrote the pid
        return None


def reaped_within_slack(pid):
    deadline = time.monotonic() + SLACK
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):  # PermissionError: the pid now belongs to another user
            return True
        time.sleep(0.05)
    return False


def case_failing_gate_blocks_with_last_lines(root):
    repo = make_repo(root, "failing", FAIL)
    code, out, _ = run(repo)
    assert code == 0, code
    assert out and out.get("decision") == "block", out
    assert "error TS2304: Cannot find name foo" in out["reason"], out["reason"]
    assert "noise 60" in out["reason"], out["reason"]
    assert "first line, scrolled away" not in out["reason"], "reason should hold only the last lines"


def case_still_failing_after_a_block_lets_the_turn_end(root):
    repo = make_repo(root, "retry", FAIL)
    code, out, _ = run(repo, active=True)
    assert code == 0, code
    assert out and "decision" not in out, out
    assert "error TS2304" in out.get("systemMessage", ""), out


def case_passing_after_a_block_is_silent(root):
    repo = make_repo(root, "retry-pass", PASS)
    assert run(repo, active=True) == (0, None, "")
    assert gate_ran(repo)


def case_gate_output_that_is_not_utf8_still_blocks(root):
    repo = make_repo(root, "binary", "#!/bin/sh\nprintf 'bad \\377\\376 bytes\\nerror: lint failed\\n'\nexit 1\n")
    code, out, err = run(repo)
    assert out and out.get("decision") == "block", (code, out, err)
    assert "error: lint failed" in out["reason"], out["reason"]


def case_gate_that_cannot_execute_blocks_with_the_reason(root):
    repo = make_repo(root, "no-shebang", "echo hi\n")
    code, out, err = run(repo)
    assert out and out.get("decision") == "block", (code, out, err)
    assert "could not run" in out["reason"], out["reason"]


def case_gate_that_hangs_is_cut_off_with_its_children(root):
    def attempt(budget):
        repo = make_repo(root, f"hangs-{budget}", "#!/bin/sh\nsleep 30 &\necho $! > .child\n"
                                                  "echo 'starting tests'\ntouch .started\nsleep 30\n")
        code, out, err = run(repo, env={"DK_GATE_TIMEOUT": str(budget)})
        assert out and out.get("decision") == "block", (code, out, err)
        assert f"timed out after {budget} s" in out["reason"], out["reason"]
        if not started(repo):
            return False
        assert "starting tests" in out["reason"], out["reason"]
        assert reaped_within_slack(child_pid(repo)), "a child of the gate outlived the timeout"
        return True
    within_a_budget(attempt)


def case_child_that_escapes_the_group_does_not_hang_the_hook(root):
    escape = os.path.join(root, "escape.py")
    with open(escape, "w") as f:
        f.write(ESCAPE)

    def attempt(budget):
        repo = make_repo(root, f"escapes-{budget}",
                         f"#!/bin/sh\n{shlex.quote(sys.executable)} -I {shlex.quote(escape)} &\necho $! > .child\n"
                         "while [ ! -f .escaped ]; do sleep 0.1; done\n"
                         "echo 'starting tests'\ntouch .started\nsleep 30\n")
        limit = budget + GRACE + SLACK
        try:
            code, out, err = run(repo, env={"DK_GATE_TIMEOUT": str(budget)}, timeout=limit)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"hook waited over {limit} s for the escaped child") from None
        finally:
            pid = child_pid(repo)
            if pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        assert out and out.get("decision") == "block", (code, out, err)
        assert f"timed out after {budget} s" in out["reason"], out["reason"]
        if not started(repo):
            return False
        assert "starting tests" in out["reason"], out["reason"]
        return True
    within_a_budget(attempt)


def case_one_huge_line_is_capped(root):
    repo = make_repo(root, "huge", "#!/bin/sh\nhead -c 200000 /dev/zero | tr '\\0' x\necho\necho 'error: at the end'\nexit 1\n")
    code, out, err = run(repo)
    assert out and len(out["reason"]) < 5000, len(out["reason"]) if out else (code, err)
    assert "error: at the end" in out["reason"], out["reason"][-200:]


def case_failing_gate_found_from_a_subdirectory(root):
    repo = make_repo(root, "subdir", FAIL)
    code, out, _ = run(os.path.join(repo, "src"))
    assert code == 0 and out and out.get("decision") == "block", (code, out)


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
