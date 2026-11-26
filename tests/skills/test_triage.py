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

lib.finish("dk:triage")
