#!/usr/bin/env python3
"""Checks tests/run.py: its path map against fixture diffs, its diff read in a fixture repo, its runs with
stand-in checks, and that the map knows every check file on disk."""
import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run", ROOT / "tests" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(name)


every = {c.name for c in run.CHECKS}
fast = {c.name for c in run.CHECKS if c.fast}
SLOW = {"tests/hooks/test_stop_gate.py", "tests/test_evals.py", "tests/test_batch_pr.py", "tests/test_dk_gc.sh"}
check("map: the slow checks are not always-on", every >= SLOW and not fast & SLOW, sorted(fast & SLOW))
check("map: the skill and runner checks are always-on", {"tests/test_skills.py", "tests/test_run.py"} <= fast,
      sorted(fast))


def selected(*paths):
    return {c.name for c in run.select(list(paths))}


got = selected("plugins/dk-guard/scripts/stop-gate.py")
check("one hook: its tests and the always-on set", got - fast == {"tests/hooks/test_stop_gate.py"} and fast <= got,
      sorted(got - fast))
got = selected("plugins/dk-guard/scripts/session-baseline.py")
check("another hook: its tests and the always-on set", got - fast == {"tests/hooks/test_session_baseline.py"},
      sorted(got - fast))
got = selected("plugins/dk-guard/scripts/guard-bash.py")
check("guard-bash: its matrix and the push gate that loads it",
      "tests/hooks/test_guard_bash.py" in got and got - fast == {"tests/hooks/test_push_gate.py"}, sorted(got - fast))
got = selected("plugins/dk/skills/verify/SKILL.md")
check("one skill's prose: its test file and the always-on set",
      "tests/skills/test_verify.py" in got and got <= fast and fast <= got, sorted(got - fast))
got = selected("plugins/dk/skills/issue-flow/SKILL.md")
check("issue-flow's prose: its test file, and the evals that read it",
      "tests/skills/test_issue-flow.py" in got and got - fast == {"tests/test_evals.py"}, sorted(got - fast))
got = selected("plugins/dk/skills/tdd/tests.md")
check("a skill with no test file of its own: the always-on set", got == fast, sorted(got ^ fast))
check("a path with no mapping: every check", selected("plugins/dk/skills/tdd/SKILL.md", "brand-new/thing.txt") == every)
check("no change: the always-on set", selected() == fast)

# The map fails closed: a check file it does not name is a failure here.
on_disk = {str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("**/test_*") if p.suffix in (".py", ".sh")}
check("map: every check file on disk is a check", not on_disk - every, sorted(on_disk - every))
named = {c.name for c in run.CHECKS if c.name.startswith("tests/")}
check("map: every check it names exists", named <= on_disk, sorted(named - on_disk))
skills = {p.parent.name for p in ROOT.glob("plugins/dk/skills/*/SKILL.md")}
own = {re.fullmatch(r"tests/skills/test_(.+)\.py", n).group(1) for n in on_disk if n.startswith("tests/skills/")}
check("map: each tests/skills file is named for a skill", own and own <= skills, sorted(own - skills))

# The diff read: committed, staged, unstaged and untracked paths since the merge base, and nothing the base gained.
with tempfile.TemporaryDirectory() as tmp:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp, env=env, check=True, capture_output=True)

    def write(path, text="x\n"):
        os.makedirs(os.path.dirname(os.path.join(tmp, path)) or tmp, exist_ok=True)
        pathlib.Path(tmp, path).write_text(text)

    git("init", "-q", "-b", "main")
    for path in ("a.txt", "b.txt", "c.txt"):
        write(path)
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "topic")
    write("committed/one.txt")
    git("add", ".")
    git("commit", "-qm", "topic")
    git("checkout", "-q", "main")
    write("on-main.txt")
    git("add", ".")
    git("commit", "-qm", "main moves on")
    git("checkout", "-q", "topic")
    write("a.txt", "staged\n")
    git("add", "a.txt")
    write("b.txt", "unstaged\n")
    write("new dir/untracked.txt")
    got = run.changed("main", tmp)
    check("diff read: committed, staged, unstaged and untracked paths since the merge base",
          sorted(got) == ["a.txt", "b.txt", "committed/one.txt", "new dir/untracked.txt"], got)

# The run: each check's seconds, a failure's output, and the exit status.
with tempfile.TemporaryDirectory() as tmp:
    ok = run.Check("stand-in pass", cmd=[sys.executable, "-c", "print('fine')"])
    bad = run.Check("stand-in fail", cmd=[sys.executable, "-c", "print('broke here'); raise SystemExit(3)"])
    log = pathlib.Path(tmp, "out")
    with log.open("w") as out:
        status = run.run([ok, bad], out=out, cwd=tmp)
    text = log.read_text()
    check("run: a failing check makes the run fail", status != 0, status)
    check("run: each check's seconds", re.search(r"^PASS +\d+\.\d+s +stand-in pass$", text, re.M) is not None
          and re.search(r"^FAIL +\d+\.\d+s +stand-in fail$", text, re.M) is not None, text)
    check("run: a failing check's output", "broke here" in text and "fine" not in text, text)
    with log.open("w") as out:
        status = run.run([ok], out=out, cwd=tmp)
    check("run: all passing exits 0", status == 0, status)

# One command from zsh or bash, no loop: the CLI with --list prints what a base ref selects.
cli = subprocess.run([sys.executable, "-I", str(ROOT / "tests" / "run.py"), "--list", "HEAD"], cwd=ROOT,
                     capture_output=True, text=True)
listed = set(cli.stdout.splitlines())
check("cli: --list HEAD prints at least the always-on set", cli.returncode == 0 and fast <= listed,
      (cli.returncode, cli.stderr[-300:]))
cli = subprocess.run([sys.executable, "-I", str(ROOT / "tests" / "run.py"), "--list", "no-such-ref"], cwd=ROOT,
                     capture_output=True, text=True)
check("cli: an unknown base ref fails loud", cli.returncode != 0 and "no-such-ref" in cli.stderr, cli.stderr[-300:])

# AGENTS.md names the runner in place of the command list, and the README, workflow.md and CI agree.
RUNNER = "python3 -I tests/run.py"
test_cmd = r"(?:python3 -I|bash) tests/(?:[\w-]+/)*test_[\w-]+\.(?:py|sh)"
checks_section = re.search(r"^## Checks\n(.*?)(?=^## |\Z)", (ROOT / "AGENTS.md").read_text(), re.M | re.S)
checks_section = checks_section.group(1) if checks_section else ""
check("AGENTS.md: its Checks section names the runner", RUNNER in checks_section, checks_section[:200])
check("AGENTS.md: its Checks section lists no check command", not re.search(test_cmd, checks_section),
      re.findall(test_cmd, checks_section))
readme = (ROOT / "README.md").read_text()
test_block = re.search(r"^## Test\n\n```sh\n(.*?)```", readme, re.M | re.S)
test_block = test_block.group(1) if test_block else ""
check("README.md: its Test block names the runner", RUNNER in test_block, test_block)
check("README.md: its Test block lists no check command", not re.search(test_cmd, test_block), test_block)
check("docs/agents/workflow.md: names the runner", RUNNER in (ROOT / "docs/agents/workflow.md").read_text())
ci = (ROOT / ".github/workflows/test.yml").read_text()
check("CI: runs the runner once, with no base", re.findall(r"^\s*run: (.*tests/run\.py.*)$", ci, re.M) == [RUNNER],
      re.findall(r"run: .*", ci))
check("CI: no check command outside the runner", not re.search(test_cmd, ci), re.findall(test_cmd, ci))
trigger = re.search(r"^on:\n((?:  .*\n)+)", ci, re.M)
trigger = trigger.group(1) if trigger else ""
check("CI: one run per push to a PR branch (pull_request, and push only on main)",
      "  pull_request:" in trigger and re.search(r"^  push:\n    branches: \[main\]$", trigger, re.M) is not None, trigger)

print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
