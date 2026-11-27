#!/usr/bin/env python3
"""Static checks on the dk:batch-pr skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, skills = lib.errors, lib.skills

pr_route = re.search(r"^\s*- `pr`: .*", skills["batch-pr"].read_text(), re.M)
if not pr_route or "Once it is merged, run step 1 again and write step 3's body from its new output, since the first " \
                   "collection predates the fix PR." not in pr_route.group(0):
    errors.append("skills/batch-pr: step 2's `pr` route does not run step 1 again after the fix PR merges")

# The latest run across all workflows can be a Dependabot run that tests nothing (#98).
evidence = re.search(r"^- \*\*Evidence\*\*: .*(?:\n  .*)*", skills["batch-pr"].read_text(), re.M)
evidence = evidence.group(0) if evidence else ""
runs = re.findall(r"gh run list [^`]*", evidence)
if not runs or any("--workflow" not in r for r in runs) or "workflow.md" not in evidence \
        or "batch PR's own checks" not in evidence or "origin/pre-main" not in evidence:
    errors.append("skills/batch-pr: step 3's Evidence must point at the batch PR's own checks, and read a pre-main "
                  "run per CI workflow workflow.md names (`gh run list --workflow`) that tested pre-main's head, "
                  "never the latest run of any")

# Step 5 finishes a merged batch with finish.py, which runs the setup line the Worktree slot writes (#181).
finish = re.search(r"^## 5\. Finish\n.*?(?=^## |\Z)", skills["batch-pr"].read_text(), re.M | re.S)
finish = finish.group(0) if finish else ""
if "finish.py" not in finish or not re.search(r"batch PR (?:has )?merged", finish):
    errors.append("skills/batch-pr: no step 5 that runs finish.py and says it runs once the batch PR merged")

lib.finish("dk:batch-pr")
