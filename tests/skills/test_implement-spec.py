#!/usr/bin/env python3
"""Checks on the dk:implement-spec skill: its prose, and its preflight against the eval `gh` stand-in (no call
reaches GitHub). The checks across skills are in tests/test_skills.py."""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, skills = lib.errors, lib.skills

spec_steps = skills["implement-spec"].read_text().replace("**", "")
for step in ("4", "7"):
    text = re.search(rf"^{step}\. .*$", spec_steps, re.M)
    if not text or "fresh implementer subagent" not in text.group(0):
        errors.append(f"skills/implement-spec: step {step} must use a fresh implementer subagent")
for step, what, pattern in (
    ("7", "answering the findings by dk:code-review's Answer findings step", r"`dk:code-review`'s Answer findings step"),
    ("8", "the hand-over through dk:issue-flow step 6's Ready gate", r"`dk:issue-flow` step 6's Ready gate"),
    ("7", "the review-fix implementer's own worktree off the integration branch, made by the orchestrator",
     r"its own worktree off the integration branch, made by you"),
    ("7", "a merger subagent bringing its branch back before step 8", r"merger subagent[^.]*before step 8"),
    ("1", "the preflight, run from the skill's base directory", r"python3 -I <base directory>/preflight\.py <spec>"),
    ("1", "the stop on an unfinishable spec before any worktree", r"exits 3[^.]*stop[^.]*no worktree"),
):
    text = re.search(rf"^{step}\. .*$", spec_steps, re.M)
    if not text or not re.search(pattern, text.group(0)):
        errors.append(f"skills/implement-spec: step {step} must name {what}")

# The preflight reads the spec's sub-issues and their blockers before any worktree exists.
PREFLIGHT = lib.DK / "skills" / "implement-spec" / "preflight.py"
GH = lib.DK / "evals" / "_fixture" / "bin" / "gh"


def ticket(title, labels=("ready-for-agent",), body="", state="open", blocked_by=()):
    return {"title": title, "body": body, "state": state, "labels": list(labels), "comments": [],
            "blocked_by": list(blocked_by)}


ISSUES = {
    "500": ticket("Spec that cannot finish", labels=("spec",)),
    "510": ticket("Spec that can finish", labels=("spec",)),
    "501": ticket("Free"),
    "502": ticket("After the free one", blocked_by=[501]),
    "503": ticket("Waits on another spec", body="Blocked by: #600"),
    "504": ticket("After the outside-blocked one", blocked_by=[503]),
    "505": ticket("Untriaged", labels=("needs-triage",)),
    "506": ticket("Already done", state="closed"),
    "507": ticket("Blocker closed", blocked_by=[599]),
    "508": ticket("Waits on another repo", body="Blocked by: acme/infra#7"),
    "599": ticket("Closed blocker", state="closed"),
    "600": ticket("Another spec's last ticket"),
}
ISSUES["500"]["sub_issues"] = [501, 502, 503, 504, 505, 506, 507, 508]
ISSUES["510"]["sub_issues"] = [501, 502, 506, 507]

ws = pathlib.Path(tempfile.mkdtemp(prefix="dk-preflight-"))
try:
    (ws / ".bin").mkdir()
    (ws / ".tracker").mkdir()
    shutil.copy(GH, ws / ".bin" / "gh")
    (ws / ".tracker" / "state.json").write_text(json.dumps(
        {"repo": "acme/ledger", "labels": [], "issues": ISSUES, "prs": [],
         "other_repos": {"acme/infra": {"7": "open"}}}))
    (ws / "repo").mkdir()
    env = {"PATH": os.pathsep.join([str(ws / ".bin"), os.environ["PATH"]]), "HOME": str(ws),
           "GIT_CONFIG_GLOBAL": "/dev/null", "GH_REPO": "kaminski-dev/dk-agent-kit"}
    for args in (["init", "-q", "-b", "main"], ["remote", "add", "origin", "https://github.com/acme/ledger.git"]):
        subprocess.run(["git", *args], cwd=ws / "repo", env=env, check=True, capture_output=True)

    def preflight(spec):
        """(exit status, {section: {number: rest of its line}}, stderr)."""
        r = subprocess.run([sys.executable, "-I", str(PREFLIGHT), spec], cwd=ws / "repo", env=env,
                           capture_output=True, text=True)
        sections, section = {}, None
        for line in r.stdout.splitlines():
            if line.startswith("## "):
                section = sections.setdefault(line[3:], {})
            elif line.startswith("- #") and section is not None:
                number, _, rest = line[3:].partition(" ")
                section[int(number)] = rest
        return r.returncode, sections, r.stderr

    code, got, err = preflight("500")
    blocked = got.get("Cannot finish", {})
    for n, what, pattern in (
        (503, "an open blocker outside the spec", r"#600.*outside the spec"),
        (504, "a wait on a ticket that cannot finish", r"#503.*cannot finish"),
        (505, "a ticket that is not ready-for-agent", r"not ready-for-agent"),
        (508, "another repo's open blocker", r"acme/infra#7.*outside the spec"),
    ):
        if not re.search(pattern, blocked.get(n, "")):
            lib.errors.append(f"implement-spec preflight: #{n} ({what}) is not listed under Cannot finish: {got}")
    if code != 3 or "#500 cannot finish" not in err:
        lib.errors.append(f"implement-spec preflight: an unfinishable spec must exit 3 and say so, got {code}: {err}")
    if sorted(got.get("Can finish now", {})) != [501, 507] or sorted(got.get("Waits inside the spec", {})) != [502]:
        lib.errors.append(f"implement-spec preflight: spec 500's frontier and inside waits are wrong: {got}")

    code, got, err = preflight("510")
    if code != 0 or got.get("Cannot finish"):
        lib.errors.append(f"implement-spec preflight: a finishable spec must exit 0, got {code}: {got} {err}")
    if sorted(got.get("Can finish now", {})) != [501, 507]:
        lib.errors.append(f"implement-spec preflight: spec 510's frontier must be #501 and #507: {got}")
    if not re.search(r"#501", got.get("Waits inside the spec", {}).get(502, "")):
        lib.errors.append(f"implement-spec preflight: #502 must wait on #501 inside the spec: {got}")
    log = ws / ".tracker" / "repos.log"
    asked = {line.split("\t", 1)[0] for line in log.read_text().splitlines()} if log.exists() else set()
    if not asked or not asked <= {"acme/ledger", "acme/infra"}:
        lib.errors.append(f"implement-spec preflight: asked gh about {asked}, not origin's acme/ledger")
finally:
    shutil.rmtree(ws, ignore_errors=True)

lib.finish("dk:implement-spec")
