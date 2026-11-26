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
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "push-gate.py")
DK_GATE = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "bin", "dk-gate")
# The gate cache of every run, so no case reads or writes the real one under ~/.claude. Cases differ in their
# worktree paths, and the cache keys a pass on its worktree, so one directory serves them all.
CACHE = tempfile.mkdtemp(prefix="dk-gate-cache-")

PASS = "#!/bin/sh\necho 'lint ok'\ntouch .gate-ran\n"
FAIL = ("#!/bin/sh\ntouch .gate-ran\necho 'first line, scrolled away'\n"
        "for i in $(seq 1 60); do echo \"noise $i\"; done\n"
        "echo 'src/a.ts(3,1): error TS2304: Cannot find name foo' >&2\nexit 1\n")
# The timeout case gives the gate each budget in turn. A loaded machine can start a gate too late to print its
# first line inside 1 s, so the fixture touches .started after that line: a run without it says the machine
# was slow and moves to the next budget; a run with it checks the hook in full.
BUDGETS = (1, 5, 15)


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
                         capture_output=True, text=True,
                         env={"PATH": os.environ["PATH"], "DK_GATE_CACHE": CACHE, **(env or {})})
    return out.returncode, json.loads(out.stdout) if out.stdout.strip() else None, out.stderr


def gate_ran(repo, forget=False):
    """Whether the repo's gate ran; with forget, clears the record so the next check sees only later runs."""
    marker = os.path.join(repo, ".gate-ran")
    ran = os.path.exists(marker)
    if ran and forget:
        os.remove(marker)
    return ran


def within_a_budget(attempt):
    for budget in BUDGETS:
        if attempt(budget):
            return
    raise AssertionError(f"the fixture gate never printed its first line inside {BUDGETS[-1]} s")


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


def case_second_push_of_an_unchanged_tree_reuses_the_pass(root):
    main, wt = make_checkout(root, "unchanged", PASS)
    assert run(main, f"cd {wt} && git push") == (0, None, "") and gate_ran(wt, forget=True)
    assert run(main, f"cd {wt} && git push") == (0, None, "")
    assert not gate_ran(wt), "the second push ran the gate again on the same tree"
    with open(os.path.join(wt, "src.txt"), "w") as f:
        f.write("new\n")
    assert run(main, f"cd {wt} && git push") == (0, None, "") and gate_ran(wt), "a changed tree must be gated"


def case_push_after_a_hand_run_of_dk_gate_reuses_its_pass(root):
    main, wt = make_checkout(root, "by-hand", PASS)
    hand = subprocess.run([DK_GATE], cwd=wt, capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], "DK_GATE_CACHE": CACHE})
    assert hand.returncode == 0 and gate_ran(wt, forget=True), hand
    assert run(main, f"cd {wt} && git push") == (0, None, "")
    assert not gate_ran(wt), "the push ran the gate again after a hand pass on the same tree"


def case_failing_gate_runs_again_on_the_next_push(root):
    main, wt = make_checkout(root, "fails-twice", FAIL)
    assert denial(run(main, f"cd {wt} && git push")[1]) and gate_ran(wt, forget=True)
    assert denial(run(main, f"cd {wt} && git push")[1]) and gate_ran(wt)


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


def case_directory_in_a_variable_the_call_sets_runs_its_gate(root):
    main, wt = make_checkout(root, "same-call", FAIL)
    for push in ('cd "$WT" && git push origin feat/same-call', 'git -C "$WT" push origin feat/same-call'):
        _, out, _ = run(main, f"WT={wt}; {push}")
        assert denial(out) and gate_ran(wt), (push, out)
        os.remove(os.path.join(wt, ".gate-ran"))


def case_directory_known_only_at_run_time_runs_no_gate_and_says_so(root):
    main, wt = make_checkout(root, "runtime", FAIL)
    code, out, err = run(main, f'WT=$(echo {wt}); cd "$WT" && git push origin feat/runtime')
    context = ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
    assert code == 0 and not denial(out) and "did not run" in context, (code, out, err)
    assert not gate_ran(wt)


def case_directory_the_call_creates_runs_no_gate_and_says_so(root):
    main, wt = make_checkout(root, "created", FAIL)
    code, out, err = run(main, f'WT={wt}-new; git worktree add "$WT" -b feat/new && cd "$WT" && git push origin feat/new')
    context = ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
    assert code == 0 and not denial(out) and "did not run" in context, (code, out, err)


def case_gate_that_hangs_lets_the_push_through_and_says_so(root):
    def attempt(budget):
        gate = "#!/bin/sh\necho 'starting tests'\ntouch .started\nsleep 30\n"
        main, wt = make_checkout(root, f"hangs-{budget}", gate)
        code, out, err = run(main, f"cd {wt} && git push", env={"DK_PUSH_GATE_TIMEOUT": str(budget)})
        assert code == 0 and out and not denial(out), (code, out, err)
        message = out.get("systemMessage", "")
        assert f"timed out after {budget} s" in message, out
        if not os.path.exists(os.path.join(wt, ".started")):
            return False
        assert "starting tests" in message, out
        return True
    within_a_budget(attempt)


def case_push_that_gets_no_gate_slot_is_denied_as_busy(root):
    flag = os.path.join(root, "busy-holder.started")
    _, holder = make_checkout(root, "busy-holder", f"#!/bin/sh\necho $$ > {flag}\nexec sleep 30\n")
    env = {"DK_GATE_SLOTS": "1", "DK_GATE_WAIT": "1"}
    hand = subprocess.Popen([DK_GATE], cwd=holder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={"PATH": os.environ["PATH"], "DK_GATE_CACHE": CACHE, **env})
    try:
        deadline = time.monotonic() + 20
        while not os.path.exists(flag):
            assert time.monotonic() < deadline, "the holding gate never started"
            time.sleep(0.05)
        main, wt = make_checkout(root, "busy", PASS)
        code, out, err = run(main, f"cd {wt} && git push", env=env)
        reason = denial(out)
        assert code == 0 and reason, (code, out, err)
        assert "gates are busy" in reason and holder in reason and "push again" in reason, reason
        assert "Fix the failure" not in reason and not gate_ran(wt), reason
    finally:
        hand.kill()
        with open(flag) as f:
            os.kill(int(f.read()), 9)
        hand.wait()


def case_a_slot_that_frees_too_late_for_the_gate_denies_the_push_as_busy(root):
    # The gate's last pass took 3 s and the push has 6 s: the wait for a slot ends after 3, before the holder's
    # gate (6 s) frees it, so the gate is never started with too little time left and killed.
    main, wt = make_checkout(root, "late-slot", "#!/bin/sh\nsleep 3\ntouch .gate-ran\n")
    env = {"DK_GATE_SLOTS": "1", "DK_GATE_WAIT": "30", "DK_PUSH_GATE_TIMEOUT": "6"}
    assert run(main, f"cd {wt} && git push", env=env) == (0, None, "") and gate_ran(wt, forget=True)
    with open(os.path.join(wt, "src.txt"), "w") as f:
        f.write("new\n")
    flag = os.path.join(root, "late-holder.started")
    _, holder = make_checkout(root, "late-holder", f"#!/bin/sh\necho $$ > {flag}\nexec sleep 6\n")
    hand = subprocess.Popen([DK_GATE], cwd=holder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={"PATH": os.environ["PATH"], "DK_GATE_CACHE": CACHE, **env})
    try:
        deadline = time.monotonic() + 20
        while not os.path.exists(flag):
            assert time.monotonic() < deadline, "the holding gate never started"
            time.sleep(0.05)
        code, out, err = run(main, f"cd {wt} && git push", env=env)
        reason = denial(out)
        assert code == 0 and reason and "gates are busy" in reason, (code, out, err)
        assert not gate_ran(wt), "the gate started with less time left than its last pass took"
    finally:
        hand.kill()
        try:
            with open(flag) as f:
                os.kill(int(f.read()), 9)
        except ProcessLookupError:
            pass  # its sleep already ended
        hand.wait()


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
    shutil.rmtree(CACHE, ignore_errors=True)
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
