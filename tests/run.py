#!/usr/bin/env python3
"""Runs the kit's checks: every one, or those a change since a base ref needs.

    python3 -I tests/run.py                  every check
    python3 -I tests/run.py origin/main      the checks mapped to the paths changed since origin/main, plus the
                                             always-on ones (each under two seconds)
    python3 -I tests/run.py --list <base>    print what <base> selects, run nothing

The changed paths are those committed since the merge base with <base>, plus staged, unstaged and untracked ones.
A changed path no check maps runs every check, so the map fails closed; tests/test_run.py fails on a check file
the map does not name. Each check prints its seconds, a failing one its output, and the run exits 1 when any fails.
"""
import fnmatch
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Check:
    """A check: its name (the test file, which runs it), the paths it reads (fnmatch patterns, where `*` also crosses
    `/`), and whether it is always-on because it takes under two seconds."""

    def __init__(self, name, reads=(), fast=False, cmd=None):
        self.name, self.fast = name, fast
        self.reads = [name, *reads]
        if cmd is None:
            cmd = [sys.executable, "-I", name] if name.endswith(".py") else ["bash", name]
        self.cmd = cmd

    def maps(self, path):
        return any(fnmatch.fnmatchcase(path, pattern) for pattern in self.reads)


HOOKS = "plugins/dk-guard/scripts/"
BIN = "plugins/dk-guard/bin/"
SKILLS = "plugins/dk/skills/"
SKILL_LIB = "tests/skills/_skills.py"


def skill(name, *reads):
    """The prose checks of one skill, in tests/skills/test_<name>.py."""
    return Check(f"tests/skills/test_{name}.py", [SKILL_LIB, f"{SKILLS}{name}/*", *reads], fast=True)


CHECKS = [
    Check("tests/hooks/test_guard_bash.py", [HOOKS + "guard-bash.py", "tests/hooks/guard_bash_cases.json"], fast=True),
    # It loads the guard, and runs dk-gate.
    Check("tests/hooks/test_push_gate.py", [HOOKS + "push-gate.py", HOOKS + "guard-bash.py", HOOKS + "gate.py",
                                            BIN + "dk-gate"]),
    Check("tests/hooks/test_require_worktree.py", [HOOKS + "require-worktree.py"], fast=True),
    Check("tests/hooks/test_session_baseline.py", [HOOKS + "session-baseline.py"]),
    Check("tests/hooks/test_fork_guard.py", [HOOKS + "fork-guard.py"]),
    Check("tests/test_skills.py", [SKILL_LIB, "plugins/dk/*.md", SKILLS + "*", "README.md", "upstream/UPSTREAM.md",
                                   "THIRD_PARTY/*", BIN + "dk-gc", "docs/agents/issue-tracker.md"], fast=True),
    skill("batch-pr"),
    skill("code-review", "plugins/dk/agents/*"),
    skill("diagnosing-bugs"),
    skill("handoff"),
    skill("implement"),
    skill("implement-spec"),
    skill("issue-flow"),
    skill("modernize"),
    skill("pr", SKILLS + "to-spec/*", SKILLS + "research-codebase/*"),
    skill("retro"),
    skill("setup"),
    skill("triage"),
    skill("verify"),
    # It also reads every SKILL.md's disable-model-invocation line; a skill that changes that line alone
    # runs it in CI only.
    Check("tests/test_evals.py", ["tests/evals/*", "plugins/dk/evals/*", SKILLS + "issue-flow/*",
                                  SKILLS + "triage/ready.py", SKILLS + "setup/issue-tracker.md",
                                  "docs/agents/issue-tracker.md"]),
    Check("tests/test_retro_extract.py", [SKILLS + "retro/extract.py"], fast=True),
    Check("tests/test_pr_wait.py", [SKILLS + "issue-flow/pr-wait"]),
    Check("tests/test_batch_pr.py", [SKILLS + "batch-pr/*.py", "plugins/dk/evals/_fixture/bin/gh"]),
    Check("tests/test_run.py", ["tests/run.py", "AGENTS.md", "README.md", "docs/agents/workflow.md",
                                ".github/workflows/test.yml"], fast=True),
    Check("tests/test_bootstrap.sh", ["bootstrap.sh", "settings/*"], fast=True),
    Check("tests/test_dk_gate.py", [HOOKS + "gate.py", BIN + "dk-gate", HOOKS + "push-gate.py"]),
    Check("tests/test_dk_pg.sh", [BIN + "dk-pg"]),
    Check("tests/test_dk_gc.sh", [BIN + "dk-gc"]),
    Check("tests/test_dk_assets.sh", [BIN + "dk-assets"], fast=True),
    Check("tests/test_sync.sh", ["upstream/sync.sh"]),
    # The only expected warning is the missing `version`, once per plugin, left out so installs track commits.
    Check("claude plugin validate .", [".claude-plugin/*", "plugins/*/.claude-plugin/*", "plugins/*/hooks/*",
                                       SKILLS + "*/SKILL.md", "plugins/dk/agents/*"],
          fast=True, cmd=["claude", "plugin", "validate", "."]),
]

# Paths no check reads; they still run the always-on set.
UNCHECKED = ["tests/hooks/replay_history.py", "CLAUDE.md", "LICENSE", ".out-of-scope/*", "docs/agents/*"]


def unmapped(paths):
    return [p for p in paths
            if not any(c.maps(p) for c in CHECKS) and not any(fnmatch.fnmatchcase(p, u) for u in UNCHECKED)]


def select(paths):
    """The checks the changed paths need: every check when one path maps to none, else the always-on ones and
    those that read a changed path."""
    if unmapped(paths):
        return list(CHECKS)
    return [c for c in CHECKS if c.fast or any(c.maps(p) for p in paths)]


def git(cwd, *args):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"run.py: git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout


def changed(base, cwd=ROOT):
    """Repo-relative paths changed since the merge base of base and HEAD: committed, staged, unstaged, untracked."""
    merge_base = git(cwd, "merge-base", base, "HEAD").strip()
    diff = git(cwd, "diff", "--name-only", "--no-renames", "-z", merge_base, "--")
    untracked = git(cwd, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted({p for p in (diff + untracked).split("\0") if p})


def run(checks, out=sys.stdout, cwd=ROOT):
    """Run each check in turn; print its seconds and, when it fails, its output. Returns the exit status."""
    failed, start = [], time.monotonic()
    for c in checks:
        began = time.monotonic()
        try:
            proc = subprocess.run(c.cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  errors="replace")
            ok, output = proc.returncode == 0, proc.stdout
        except OSError as e:
            ok, output = False, f"{c.cmd[0]}: {e}\n"
        print(f"{'PASS' if ok else 'FAIL'} {time.monotonic() - began:6.1f}s  {c.name}", file=out, flush=True)
        if not ok:
            failed.append(c.name)
            print("".join(f"    {line}\n" for line in output.splitlines()[-80:]), end="", file=out, flush=True)
    print(f"{len(checks) - len(failed)}/{len(checks)} passed in {time.monotonic() - start:.1f}s"
          + (f"; failed: {', '.join(failed)}" if failed else ""), file=out, flush=True)
    return 1 if failed else 0


def main(argv):
    listing = "--list" in argv
    args = [a for a in argv if a != "--list"]
    if len(args) > 1 or any(a.startswith("-") for a in args):
        sys.exit(__doc__)
    if not args:
        checks = list(CHECKS)
    else:
        paths = changed(args[0])
        missing = unmapped(paths)
        checks = select(paths)
        note = (f"no check maps {', '.join(missing)}, so every check runs" if missing
                else f"{len(checks)} of {len(CHECKS)} checks for {len(paths)} paths changed since {args[0]}")
        print(note, file=sys.stderr, flush=True)
    if listing:
        print("\n".join(c.name for c in checks))
        return 0
    os.chdir(ROOT)
    return run(checks)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
