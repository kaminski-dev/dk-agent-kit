#!/usr/bin/env python3
"""Static checks on the dk:setup skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
DK, errors = lib.DK, lib.errors

# Evidence's pre-main run needs a workflow.md that names the workflow and the commit its runs tested (#106).
ci_slot = re.search(r"^- \*\*CI and deploy\*\*: .*(?:\n  .*)*", (DK / "skills/setup/workflow-parameters.md").read_text(), re.M)
ci_slot = ci_slot.group(0) if ci_slot else ""
for what, pattern in (
    ("the workflow that runs the CI against `pre-main`", r"which workflow, if any, runs that CI against `pre-main`"),
    ("that workflow by the name `gh run list --workflow` takes", r"by the name `gh run list --workflow` takes"),
    ("how a run shows the commit it tested", r"how one of its runs shows the commit it tested"),
):
    if not re.search(pattern, ci_slot):
        errors.append(f"skills/setup: workflow-parameters.md's **CI and deploy** does not ask for {what}")

# A base with no CI skips pr-wait's wait for checks to register, read from workflow.md's **No CI** line (#176).
params = (DK / "skills/setup/workflow-parameters.md").read_text()
no_ci = re.search(r"^- \*\*No CI\*\*: .*$", params, re.M)
if not no_ci or "backticks" not in no_ci.group(0) or "watcher" not in no_ci.group(0):
    errors.append("skills/setup: workflow-parameters.md needs a **No CI** item: the bases with no CI, in backticks, "
                  "which dk:issue-flow's watcher reads")
if r"\*\*No CI\*\*" not in (DK / "skills/issue-flow/pr-wait").read_text():
    errors.append("skills/issue-flow/pr-wait: the watcher does not read workflow.md's **No CI** line")

# The tier script reads the repo's risk paths; a repo without them never gets the small tier (#173).
setup = (DK / "skills/setup/SKILL.md").read_text()
if not re.search(r"^- \*\*Risk paths\*\*: [^\n]*`tier`[^\n]*never gets the small tier", params, re.M):
    errors.append("skills/setup: workflow-parameters.md has no **Risk paths** slot naming the tier script")
if not re.search(r"^## Risk paths\n", params, re.M):
    errors.append("skills/setup: workflow-parameters.md carries no ## Risk paths template with the default globs")
if not re.search(r"Add its `## Risk paths` section when the repo has none", setup):
    errors.append("skills/setup: its Workflow step does not add the ## Risk paths section")

lib.finish("dk:setup")
