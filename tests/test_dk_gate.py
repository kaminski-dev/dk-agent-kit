#!/usr/bin/env python3
"""Runs dk-gate against throwaway git repos whose gate records each run.

Each case builds a repo with a committed .claude/gate.sh that appends a line
to .gate-runs (ignored, so the record never changes the tree it gates), runs
`dk-gate` in it with the cache in a temp directory (DK_GATE_CACHE), and checks
the exit code, what it printed and how many times the gate ran.
"""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DK_GATE = os.path.join(HERE, "..", "plugins", "dk-guard", "bin", "dk-gate")
GATE_PY = os.path.join(HERE, "..", "plugins", "dk-guard", "scripts", "gate.py")
# What the push hook does with gate.py: load it and call check() under a timeout. Prints [status, entry].
CHECK = ("import importlib.util, json, sys\n"
         "spec = importlib.util.spec_from_file_location('gate', sys.argv[1])\n"
         "gate = importlib.util.module_from_spec(spec)\n"
         "spec.loader.exec_module(gate)\n"
         "status, _, entry = gate.check(sys.argv[2], timeout=float(sys.argv[3]))\n"
         "print(json.dumps([status, entry]))\n")

PASS = "#!/bin/sh\necho 'lint ok'\necho run >> .gate-runs\n"
CACHED = "did not run again (cached)"
FAIL = "#!/bin/sh\necho run >> .gate-runs\necho 'src/a.ts(3,1): error TS2304: Cannot find name foo' >&2\nexit 1\n"


def git(path, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", path, *args],
                          check=True, capture_output=True, text=True).stdout


def write(repo, rel, text, executable=False):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def make_repo(root, name, gate=PASS):
    """A repo on main with a committed gate, a lockfile and a source file, and origin/main at its first commit."""
    repo = os.path.join(root, name)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    write(repo, ".gitignore", ".gate-runs\n")
    write(repo, ".claude/gate.sh", gate, executable=True)
    write(repo, "bun.lock", "lock 1\n")
    write(repo, "src/a.ts", "export const a = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "switch", "-q", "-c", f"feat/{name}")
    return repo


def gate_env(cwd, cache, env=None):
    return {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", cwd), "DK_GATE_CACHE": cache, **(env or {})}


def run(cwd, *args, cache, env=None):
    out = subprocess.run([DK_GATE, *args], cwd=cwd, capture_output=True, text=True, env=gate_env(cwd, cache, env))
    return out.returncode, out.stdout + out.stderr


def check(repo, timeout, cache, env=None):
    """gate.check(repo, timeout) in a process of its own, as the push hook calls it: (status, entry)."""
    out = subprocess.run([sys.executable, "-I", "-c", CHECK, GATE_PY, repo, str(timeout)], capture_output=True,
                         text=True, env=gate_env(repo, cache, env))
    assert out.returncode == 0, out
    return tuple(json.loads(out.stdout))


def slow_hash(root, name, seconds):
    """A PATH whose git takes `seconds` longer over `git diff` once the returned flag file exists: the tree hash
    of a big checkout on a loaded machine."""
    bin_dir, flag = os.path.join(root, name + "-bin"), os.path.join(root, name + ".slow")
    os.makedirs(bin_dir)
    write(bin_dir, "git", f"#!/bin/sh\ncase \" $* \" in *\" diff \"*) test -e {flag} && sleep {seconds};; esac\n"
                         f"exec {shutil.which('git')} \"$@\"\n", executable=True)
    return bin_dir + os.pathsep + os.environ["PATH"], flag


def start(cwd, *args, cache, env=None):
    """dk-gate started in the background; its pid is the gate command's own (bin/dk-gate execs it)."""
    return subprocess.Popen([DK_GATE, *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env=gate_env(cwd, cache, env))


def wait_for(path, seconds=20):
    deadline = time.monotonic() + seconds
    while not os.path.exists(path):
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def runs(repo):
    try:
        with open(os.path.join(repo, ".gate-runs")) as f:
            return len(f.read().splitlines())
    except FileNotFoundError:
        return 0


def case_unchanged_tree_returns_the_cached_pass_without_running_the_gate(root):
    repo, cache = make_repo(root, "unchanged"), os.path.join(root, "cache-unchanged")
    code, out = run(repo, cache=cache)
    assert code == 0 and "lint ok" in out and runs(repo) == 1, (code, out)
    code, out = run(repo, cache=cache)
    assert code == 0 and CACHED in out and runs(repo) == 1, (code, out)


def tracked_edit(repo):
    write(repo, "src/a.ts", "export const a = 2\n")


def new_untracked_file(repo):
    write(repo, "src/b.ts", "export const b = 1\n")


def changed_lockfile(repo):
    write(repo, "bun.lock", "lock 2\n")


def changed_gate_script(repo):
    write(repo, ".claude/gate.sh", PASS + "echo 'one more check'\n", executable=True)


def new_base_commit_that_moves_the_merge_base(repo):
    """main gets the branch's own change as a commit of its own and the branch resets onto it: the tree stays the
    same, only the merge base with origin/main moves."""
    git(repo, "switch", "-q", "main")
    write(repo, "src/c.ts", "export const c = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "main moves")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "switch", "-q", "-")
    git(repo, "reset", "-q", "--hard", "main")


def edited_untracked_file(repo):
    write(repo, "src/b.ts", "export const b = 2\n")


def changed_ignored_lockfile(repo):
    write(repo, "bun.lockb", "binary lock 2\n")


def changed_ignored_gate_script(repo):
    write(repo, ".claude/gate.sh", PASS + "echo 'one more check'\n", executable=True)


def commit_the_change_the_base_repeats(repo):
    write(repo, "src/c.ts", "export const c = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "work")


def ignore(*paths):
    def setup(repo):
        with open(os.path.join(repo, ".gitignore"), "a") as f:
            f.write("".join(p + "\n" for p in paths))
        for p in paths:
            if p == "bun.lockb":
                write(repo, p, "binary lock 1\n")
            else:
                git(repo, "rm", "-q", "--cached", p)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "ignore " + " ".join(paths))
    return setup


INVALIDATIONS = (
    (None, tracked_edit),
    (None, new_untracked_file),
    (new_untracked_file, edited_untracked_file),
    (None, changed_lockfile),
    (ignore("bun.lockb"), changed_ignored_lockfile),
    (None, changed_gate_script),
    (ignore(".claude/gate.sh"), changed_ignored_gate_script),
    (commit_the_change_the_base_repeats, new_base_commit_that_moves_the_merge_base),
)


def case_each_input_of_the_pass_invalidates_it(root):
    wrong = []
    for setup, change in INVALIDATIONS:
        name = change.__name__.replace("_", "-")
        repo, cache = make_repo(root, name), os.path.join(root, "cache-" + name)
        if setup:
            setup(repo)
        tree = git(repo, "rev-parse", "HEAD^{tree}")
        assert run(repo, cache=cache)[0] == 0 and runs(repo) == 1, name
        change(repo)
        if change is new_base_commit_that_moves_the_merge_base:
            assert git(repo, "rev-parse", "HEAD^{tree}") == tree, "the fixture must leave the tree as it was"
        code, out = run(repo, cache=cache)
        if code != 0 or CACHED in out or runs(repo) != 2:
            wrong.append(f"{name}: the gate did not run again ({code}, {out!r})")
            continue
        code, out = run(repo, cache=cache)
        if code != 0 or CACHED not in out or runs(repo) != 2:
            wrong.append(f"{name}: the new pass was not cached ({code}, {out!r})")
    assert not wrong, wrong


def case_a_failing_gate_is_never_cached(root):
    repo, cache = make_repo(root, "failing", FAIL), os.path.join(root, "cache-failing")
    for attempt in (1, 2):
        code, out = run(repo, cache=cache)
        assert code == 1 and "TS2304" in out and "failed (exit 1)" in out and runs(repo) == attempt, (code, out)


def case_fresh_runs_the_gate_whatever_the_cache_holds(root):
    repo, cache = make_repo(root, "fresh"), os.path.join(root, "cache-fresh")
    run(repo, cache=cache)
    code, out = run(repo, "--fresh", cache=cache)
    assert code == 0 and CACHED not in out and runs(repo) == 2, (code, out)


def case_a_gate_linked_to_an_ignored_script_is_keyed_on_the_script(root):
    repo, cache = make_repo(root, "linked"), os.path.join(root, "cache-linked")
    with open(os.path.join(repo, ".gitignore"), "a") as f:
        f.write("gate.local\n")
    write(repo, "gate.local", PASS, executable=True)
    git(repo, "rm", "-q", ".claude/gate.sh")
    os.makedirs(os.path.join(repo, ".claude"), exist_ok=True)
    os.symlink("../gate.local", os.path.join(repo, ".claude/gate.sh"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "link the gate")
    assert run(repo, cache=cache)[0] == 0 and runs(repo) == 1
    write(repo, "gate.local", PASS + "echo 'one more check'\n", executable=True)
    code, out = run(repo, cache=cache)
    assert code == 0 and CACHED not in out and runs(repo) == 2, (code, out)


def case_a_fresh_run_that_fails_drops_the_older_pass(root):
    repo, cache = make_repo(root, "fresh-fails"), os.path.join(root, "cache-fresh-fails")
    assert run(repo, cache=cache)[0] == 0 and runs(repo) == 1
    with open(os.path.join(repo, ".gitignore"), "a") as f:
        f.write("gate.conf\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "ignore the gate's config")
    assert run(repo, cache=cache)[0] == 0 and runs(repo) == 2
    write(repo, ".claude/gate.sh", PASS + "test -e gate.conf || exit 1\n", executable=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "gate reads an ignored config")
    write(repo, "gate.conf", "ok\n")
    assert run(repo, cache=cache)[0] == 0 and runs(repo) == 3
    os.remove(os.path.join(repo, "gate.conf"))  # an input the key cannot see
    code, out = run(repo, "--fresh", cache=cache)
    assert code == 1 and runs(repo) == 4, (code, out)
    code, out = run(repo, cache=cache)
    assert code == 1 and CACHED not in out and runs(repo) == 5, (code, out)


def case_a_failed_run_on_another_tree_drops_the_older_pass(root):
    repo, cache = make_repo(root, "fails-elsewhere"), os.path.join(root, "cache-fails-elsewhere")
    with open(os.path.join(repo, ".gitignore"), "a") as f:
        f.write("gate.conf\n")
    write(repo, ".claude/gate.sh", PASS + "test -e gate.conf || exit 1\n", executable=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "gate reads an ignored config")
    write(repo, "gate.conf", "ok\n")
    assert run(repo, cache=cache)[0] == 0 and runs(repo) == 1
    os.remove(os.path.join(repo, "gate.conf"))  # an input the key cannot see
    write(repo, "src/a.ts", "export const a = 2\n")
    assert run(repo, cache=cache)[0] == 1 and runs(repo) == 2
    write(repo, "src/a.ts", "export const a = 1\n")  # back on the tree of the older pass
    code, out = run(repo, cache=cache)
    assert code == 1 and CACHED not in out and runs(repo) == 3, (code, out)


def case_a_tree_that_changes_while_the_gate_runs_is_not_cached(root):
    repo, cache = make_repo(root, "racing", PASS + "echo x > src/generated.ts\n"), os.path.join(root, "cache-racing")
    code, out = run(repo, cache=cache)
    assert code == 0 and "the pass is not cached" in out, (code, out)
    os.remove(os.path.join(repo, "src", "generated.ts"))
    assert CACHED not in run(repo, cache=cache)[1] and runs(repo) == 2


def case_a_subdirectory_gates_its_checkout(root):
    repo, cache = make_repo(root, "subdir"), os.path.join(root, "cache-subdir")
    run(repo, cache=cache)
    code, out = run(os.path.join(repo, "src"), cache=cache)
    assert code == 0 and CACHED in out and runs(repo) == 1, (code, out)
    code, out = run(root, repo, cache=cache)
    assert code == 0 and CACHED in out and runs(repo) == 1, (code, out)


def case_a_pass_drops_the_entries_of_worktrees_that_are_gone(root):
    cache = os.path.join(root, "cache-gone")
    gone, kept = make_repo(root, "gone"), make_repo(root, "kept")
    run(gone, cache=cache)
    run(kept, cache=cache)
    subprocess.run(["rm", "-rf", gone], check=True)
    run(make_repo(root, "later"), cache=cache)
    entries = [n for n in os.listdir(cache) if n.endswith(".json")]
    assert len(entries) == 2, os.listdir(cache)
    assert CACHED in run(kept, cache=cache)[1]


def case_a_checkout_without_a_gate_says_so(root):
    repo, cache = make_repo(root, "no-gate"), os.path.join(root, "cache-no-gate")
    git(repo, "rm", "-q", ".claude/gate.sh")
    code, out = run(repo, cache=cache)
    assert code == 0 and "no executable .claude/gate.sh" in out, (code, out)


def case_outside_a_checkout_is_an_error(root):
    plain = os.path.join(root, "plain")
    os.makedirs(plain)
    code, out = run(plain, cache=os.path.join(root, "cache-plain"))
    assert code == 2 and "not in a git checkout" in out, (code, out)


def case_three_gates_started_together_run_at_most_two_at_once(root):
    shared, cache = os.path.join(root, "overlap"), os.path.join(root, "cache-overlap")
    os.makedirs(os.path.join(shared, "running"))
    # Each run counts the runs under way as it starts; the last to start at the peak sees all of them.
    gate = (f"#!/bin/sh\ntouch {shared}/running/$$\nls {shared}/running | wc -l >> {shared}/peaks\n"
            f"sleep 2\nrm {shared}/running/$$\necho run >> .gate-runs\n")
    repos = [make_repo(root, f"overlap-{i}", gate) for i in range(3)]
    procs = [start(repo, cache=cache) for repo in repos]
    outs = [p.communicate(timeout=60)[0] for p in procs]
    assert all(p.returncode == 0 for p in procs) and all(runs(r) == 1 for r in repos), outs
    with open(os.path.join(shared, "peaks")) as f:
        peaks = [int(line) for line in f.read().split()]
    assert max(peaks) == 2, (peaks, outs)


def holding_gate(root, name):
    """A repo whose gate says it started, then sleeps with its own pid on record."""
    flag = os.path.join(root, name + ".started")
    return make_repo(root, name, f"#!/bin/sh\necho $$ > {flag}\nexec sleep 30\n"), flag


def stop(flag, *procs):
    """Kill the dk-gate runs and the sleep of the holding gate whose pid `flag` holds."""
    for proc in procs:
        if proc:
            proc.kill()
    try:
        with open(flag) as f:
            os.kill(int(f.read()), signal.SIGKILL)
    except ProcessLookupError:
        pass  # the sleep already ended
    for proc in procs:
        if proc:
            proc.communicate()


def case_a_gate_that_gets_no_slot_in_its_wait_is_refused_as_busy(root):
    cache, env = os.path.join(root, "cache-busy"), {"DK_GATE_SLOTS": "1", "DK_GATE_WAIT": "1"}
    holder, flag = holding_gate(root, "busy-holder")
    proc = start(holder, cache=cache, env=env)
    try:
        wait_for(flag)
        repo = make_repo(root, "busy")
        code, out = run(repo, cache=cache, env=env)
        assert code == 3 and "gates are busy" in out and holder in out and runs(repo) == 0, (code, out)
    finally:
        proc.kill()
        with open(flag) as f:
            os.kill(int(f.read()), signal.SIGKILL)
        proc.communicate()


def case_a_slot_that_comes_late_and_a_slow_hash_start_no_gate_the_timeout_would_kill(root):
    # The gate's last pass took 2 s and the check has 4 s. The slot frees after 1 s, inside the wait, but the hash
    # of the tree after it takes 2.5 s, so under 1.5 s are left: the gate must not start.
    cache, env = os.path.join(root, "cache-late"), {"DK_GATE_SLOTS": "1"}
    started = os.path.join(root, "late.starts")
    repo = make_repo(root, "late", f"#!/bin/sh\necho start >> {started}\nsleep 2\necho run >> .gate-runs\n")
    assert run(repo, cache=cache, env=env)[0] == 0 and runs(repo) == 1
    os.remove(started)
    tracked_edit(repo)
    path, slow = slow_hash(root, "late", 2.5)
    flag = os.path.join(root, "late-holder.started")
    holder = make_repo(root, "late-holder", f"#!/bin/sh\necho $$ > {flag}\nsleep 1\ntouch {slow}\n")
    proc = start(holder, cache=cache, env=env)
    try:
        wait_for(flag)
        status, entry = check(repo, 4, cache, {**env, "PATH": path})
        assert status == "busy" and not os.path.exists(started), (status, entry)
        assert entry["cause"] == "late" and entry["left"] < 2 <= entry["needs"], entry
    finally:
        proc.communicate()


def counting_gate(root, name, then="echo run >> .gate-runs\n"):
    """A gate that says it started, records how many runs of it are under way, and takes 2 s. Returns (the gate
    script, the flag its start makes, peaks(): the count each run saw as it started)."""
    shared = os.path.join(root, name + "-shared")
    os.makedirs(os.path.join(shared, "running"))
    flag = os.path.join(shared, "started")

    def peaks():
        with open(os.path.join(shared, "peaks")) as f:
            return [int(line) for line in f.read().split()]
    return (f"#!/bin/sh\ntouch {shared}/running/$$ {flag}\nls {shared}/running | wc -l >> {shared}/peaks\n"
            f"sleep 2\nrm {shared}/running/$$\n" + then), flag, peaks


def case_a_second_run_on_a_checkout_waits_for_the_first_and_reuses_its_pass(root):
    gate, flag, peaks = counting_gate(root, "same")
    repo, cache = make_repo(root, "same", gate), os.path.join(root, "cache-same")
    first = start(repo, cache=cache)
    wait_for(flag)
    code, out = run(repo, cache=cache)
    assert first.wait(timeout=20) == 0, first.stdout.read()
    assert code == 0 and CACHED in out and runs(repo) == 1 and peaks() == [1], (code, out, peaks())
    assert f"another run of .claude/gate.sh in {repo}" in out and "waiting for it to end" in out, out


def case_a_second_run_on_a_checkout_runs_the_gate_when_the_first_fails(root):
    gate, flag, peaks = counting_gate(root, "same-fails", "echo run >> .gate-runs\ntest $(wc -l < .gate-runs) -gt 1\n")
    repo, cache = make_repo(root, "same-fails", gate), os.path.join(root, "cache-same-fails")
    first = start(repo, cache=cache)
    wait_for(flag)
    code, out = run(repo, cache=cache)
    assert first.wait(timeout=20) == 1, first.stdout.read()
    assert code == 0 and CACHED not in out and runs(repo) == 2 and peaks() == [1, 1], (code, out, peaks())


def case_a_fresh_run_that_fails_behind_a_run_in_flight_leaves_no_cached_pass(root):
    # The gate reads an ignored config as it starts. Run A starts with it in place and passes 2 s later; meanwhile
    # the config goes, an input the key cannot see, and run B (--fresh) fails on it. B is the later run, so no pass
    # may stay cached.
    gate, flag, _ = counting_gate(root, "stale-pass")
    repo, cache = make_repo(root, "stale-pass"), os.path.join(root, "cache-stale-pass")
    with open(os.path.join(repo, ".gitignore"), "a") as f:
        f.write("gate.conf\n")
    write(repo, ".claude/gate.sh", gate.replace("\n", "\ntest -e gate.conf || exit 1\n", 1), executable=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "gate reads an ignored config")
    write(repo, "gate.conf", "ok\n")
    first = start(repo, cache=cache)
    wait_for(flag)
    os.remove(os.path.join(repo, "gate.conf"))
    code, out = run(repo, "--fresh", cache=cache)
    assert first.wait(timeout=20) == 0, first.stdout.read()
    assert code == 1, (code, out)
    code, out = run(repo, cache=cache)
    assert code == 1 and CACHED not in out, (code, out)


def case_a_run_waiting_for_its_own_checkout_holds_no_slot(root):
    # Two slots: the run in flight holds one. A waiter that held the other would keep it from the third run.
    cache, env = os.path.join(root, "cache-own-wait"), {"DK_GATE_SLOTS": "2", "DK_GATE_WAIT": "30"}
    holder, flag = holding_gate(root, "own-wait-holder")
    first = start(holder, cache=cache, env=env)
    waiter = None
    try:
        wait_for(flag)
        waiter = start(holder, cache=cache, env=env)
        line = waiter.stdout.readline()
        assert "waiting for it to end" in line, line
        other = make_repo(root, "own-wait-other")
        code, out = run(other, cache=cache, env={**env, "DK_GATE_WAIT": "1"})
        assert code == 0 and runs(other) == 1, (code, out)
    finally:
        stop(flag, first, waiter)


def case_a_run_whose_checkout_stays_busy_is_refused_and_names_that_run(root):
    cache, env = os.path.join(root, "cache-own-busy"), {"DK_GATE_WAIT": "1"}
    repo, flag = holding_gate(root, "own-busy")
    first = start(repo, cache=cache, env=env)
    try:
        wait_for(flag)
        code, out = run(repo, cache=cache, env=env)
        assert code == 3 and f"another run of .claude/gate.sh in {repo} is still going" in out, (code, out)
        assert "did not run" in out and "held every slot" not in out, out
    finally:
        stop(flag, first)


def case_a_run_killed_mid_gate_leaves_its_checkout_free(root):
    cache, env = os.path.join(root, "cache-own-killed"), {"DK_GATE_WAIT": "1"}
    flag = os.path.join(root, "own-killed.started")
    repo = make_repo(root, "own-killed", f"#!/bin/sh\ntest -e {flag} && echo run >> .gate-runs && exit\n"
                                         f"echo $$ > {flag}\nexec sleep 30\n")
    first = start(repo, cache=cache, env=env)
    wait_for(flag)
    first.send_signal(signal.SIGKILL)
    with open(flag) as f:
        os.kill(int(f.read()), signal.SIGKILL)
    first.communicate()
    code, out = run(repo, cache=cache, env=env)
    assert code == 0 and runs(repo) == 1 and "waiting" not in out, (code, out)


def case_gates_under_two_claude_config_dirs_share_the_slots(root):
    home = os.path.join(root, "home-shared")
    env = {"DK_GATE_CACHE": "", "HOME": home, "DK_GATE_SLOTS": "1", "DK_GATE_WAIT": "1"}
    holder, flag = holding_gate(root, "config-holder")
    proc = start(holder, cache="", env={**env, "CLAUDE_CONFIG_DIR": os.path.join(root, "config-a")})
    try:
        wait_for(flag)
        repo = make_repo(root, "config-other")
        code, out = run(repo, cache="", env={**env, "CLAUDE_CONFIG_DIR": os.path.join(root, "config-b")})
        assert code == 3 and "gates are busy" in out and runs(repo) == 0, (code, out)
    finally:
        proc.kill()
        with open(flag) as f:
            os.kill(int(f.read()), signal.SIGKILL)
        proc.communicate()


def case_a_slot_held_by_a_killed_process_is_reclaimed(root):
    cache, env = os.path.join(root, "cache-stale"), {"DK_GATE_SLOTS": "1", "DK_GATE_WAIT": "2"}
    holder, flag = holding_gate(root, "stale-holder")
    proc = start(holder, cache=cache, env=env)
    wait_for(flag)
    proc.send_signal(signal.SIGKILL)  # the gate command dies without releasing anything
    with open(flag) as f:
        os.kill(int(f.read()), signal.SIGKILL)  # its gate's sleep holds the pipe until it goes too
    proc.communicate()
    repo = make_repo(root, "stale")
    code, out = run(repo, cache=cache, env=env)
    assert code == 0 and runs(repo) == 1, (code, out)


def case_the_gate_gets_the_worker_limit(root):
    gate = "#!/bin/sh\necho \"workers=$DK_GATE_WORKERS\"\n"
    for name, env, want in (("workers-default", None, "workers=4"), ("workers-set", {"DK_GATE_WORKERS": "3"},
                                                                      "workers=3")):
        repo = make_repo(root, name, gate)
        code, out = run(repo, cache=os.path.join(root, "cache-" + name), env=env)
        assert code == 0 and want in out.splitlines(), (name, code, out)


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
