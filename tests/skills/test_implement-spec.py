#!/usr/bin/env python3
"""Static checks on the dk:implement-spec skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

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
):
    text = re.search(rf"^{step}\. .*$", spec_steps, re.M)
    if not text or not re.search(pattern, text.group(0)):
        errors.append(f"skills/implement-spec: step {step} must name {what}")

lib.finish("dk:implement-spec")
