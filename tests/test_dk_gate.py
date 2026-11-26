#!/usr/bin/env python3
"""Runs dk-gate against throwaway git repos whose gate records each run.

Each case builds a repo with a committed .claude/gate.sh that appends a line
to .gate-runs (ignored, so the record never changes the tree it gates), runs
`dk-gate` in it with the cache in a temp directory (DK_GATE_CACHE), and checks
the exit code, what it printed and how many times the gate ran.
"""
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DK_GATE = os.path.join(HERE, "..", "plugins", "dk-guard", "bin", "dk-gate")

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


def run(cwd, *args, cache):
    out = subprocess.run([DK_GATE, *args], cwd=cwd, capture_output=True, text=True,
                         env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", cwd),
                              "DK_GATE_CACHE": cache})
    return out.returncode, out.stdout + out.stderr


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
    assert len(os.listdir(cache)) == 2, os.listdir(cache)
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
