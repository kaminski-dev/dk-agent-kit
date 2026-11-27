#!/usr/bin/env python3
"""Static checks on the dk:handoff skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, skills = lib.errors, lib.skills

# The agent picking up a handoff never loads the skill, so the written document carries the pickup rules (#118).
handoff = skills["handoff"].read_text()
written = handoff[:handoff.find("## Picking up")]
pickup = re.search(r"^## Picking up a handoff\n.*?(?=^## |\Z)", handoff, re.M | re.S)
pickup = pickup.group(0) if pickup else ""
for what, pattern in (
    ("the handoff as context, not proof", r"context, not proof"),
    ("a check against the current head", r"current head"),
    ("a check for uncommitted work", r"uncommitted work.*git status"),
    ("a check against the code", r"the code each claim"),
    ("re-judging the earlier implementation", r"[Rr]e-judge the earlier implementation"),
    ("imported commits keeping their authorship and trailers", r"cherry-pick.*author.*trailers"),
    # CodeRabbit local review on #136 (#112): staged work hides from `git diff`, and a cherry-pick carries commits only.
    ("staged work in the check", r"`git diff --cached`"),
    ("uncommitted work carried over as a patch before the first edit", r"[Uu]ncommitted work[^.]*patch[^.]*`git apply"),
    # CodeRabbit on #136 (#112): without --binary a tracked binary change is "Binary files differ", which git apply rejects.
    ("the pickup's paths quoted and binary changes carried", r'`git -C "<old worktree>" diff --binary HEAD > "<patch file>"`'),
):
    if not re.search(pattern, pickup, re.S):
        errors.append(f"skills/handoff: its 'Picking up a handoff' section does not name {what}")
if not re.search(r"\"Picking up a handoff\" section.*verbatim", written):
    errors.append("skills/handoff: the written document must open with the 'Picking up a handoff' section, copied verbatim")
if not re.search(r"Right below that section, name the branch, its worktree path, the issue and the PR[^\n]*`none`",
                 written):
    errors.append("skills/handoff: the written document must name its branch, worktree path, issue and PR "
                  "(or `none`) right below that section")
if not re.search(r"\A---\n.*?\n---\n\n<!-- Adapted from t3dotgg/tstack@[0-9a-f]+ skills/takeover, MIT \(© 2026 Theo Browne\)\. ",
                 handoff, re.S):
    errors.append("skills/handoff: no `<!-- Adapted from t3dotgg/tstack@<commit> skills/takeover, MIT (© 2026 Theo Browne).` "
                  "marker right after the frontmatter")

lib.finish("dk:handoff")
