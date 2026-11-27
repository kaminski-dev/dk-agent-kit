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

# The Worktree slot writes the **Fresh-worktree setup** line that batch-pr's finish.py runs (#181).
setup_slot = re.search(r"^- \*\*Worktree\*\*: .*", (DK / "skills/setup/workflow-parameters.md").read_text(), re.M)
if not setup_slot or "**Fresh-worktree setup**" not in setup_slot.group(0) or "finish.py" not in setup_slot.group(0):
    errors.append("skills/setup: the Worktree slot does not name the **Fresh-worktree setup** line batch-pr's finish.py runs")

lib.finish("dk:setup")
