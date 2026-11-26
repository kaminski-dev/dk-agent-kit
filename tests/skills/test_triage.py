#!/usr/bin/env python3
"""Static checks on the dk:triage skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, skills = lib.errors, lib.skills

# Triage's verify step runs the check the issue names and ends on a checkable criterion.
verify = re.search(r"^3\. \*\*Verify the claim\.\*\*.*?(?=^4\. )", skills["triage"].read_text(), re.M | re.S)
if not verify:
    errors.append("skills/triage: no step 3 'Verify the claim' followed by a step 4")
else:
    done = re.search(r"Done when .*", verify.group(0))
    done = done.group(0) if done else ""
    if "failing check the issue names" not in verify.group(0):
        errors.append("skills/triage: step 3 does not run the failing check the issue names")
    for what, pattern in (
        ("each command quoted with its exit status or key output line", r"quotes each command .*exit status or key output line"),
        ("needs-info for a bug whose check could not run", r"a bug whose .*could not run goes to `needs-info`"),
    ):
        if not re.search(pattern, done):
            errors.append(f"skills/triage: step 3's Done when line does not name {what}")

triage = skills["triage"].read_text()

# Code is read at the fetched remote base, in the detached worktree the ready listing hands out (#178).
if not re.search(r"python3 -I <base directory>/ready\.py --base <base> --worktree \S+", triage):
    errors.append("skills/triage: the ready listing must run ready.py with --base <base> and --worktree")
gather = re.search(r"^1\. \*\*Gather context\.\*\*.*$", triage, re.M)
gather = gather.group(0) if gather else ""
if not re.search(r"worktree at `origin/<base>`[^.]*not the main checkout", gather):
    errors.append("skills/triage: step 1 must read code in the worktree at origin/<base>, not the main checkout")
if "origin/pre-main" in gather:
    errors.append("skills/triage: step 1 names origin/pre-main; the base is origin/<base>")

# A guard issue is admitted with a past command that hit it, else parked with its shape (#178).
guard = re.search(r"^## Guard issues\n(.*?)(?=^## )", triage, re.M | re.S)
guard = guard.group(1) if guard else ""
for what, pattern in (
    ("admission only with a past command that hit it", r"`ready-for-agent` only with a past command that hit"),
    ("the replay tool or a transcript as the source", r"replay_history\.py.*transcript"),
    ("where an unhit shape is recorded", r"`\.out-of-scope/unhit-guard-shapes\.md`"),
):
    if not re.search(pattern, guard, re.S):
        errors.append(f"skills/triage: the Guard issues section must name {what}")

# The disclaimer tells the reader an AI wrote the post, on any repo: dropping it with the attribution note on a repo
# read as not your own cost the triage evals their brief (#168 review, SP5 declined).
if not re.search(r"during triage \*\*must\*\* start with this disclaimer:\n", skills["triage"].read_text()):
    errors.append("skills/triage: every triage comment or issue must start with the disclaimer, on any repo")

lib.finish("dk:triage")
