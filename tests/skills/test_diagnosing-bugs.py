#!/usr/bin/env python3
"""Static checks on the dk:diagnosing-bugs skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, frontmatter, skills = lib.errors, lib.frontmatter, lib.skills

# dk:diagnosing-bugs must fire on its own, before dk:tdd and dk:verify, so it is model-invoked; its
# description then sits in the listing every turn (#27), so it stays short (#122).
diagnosing = skills.get("diagnosing-bugs")
if diagnosing is None:
    errors.append("skills/diagnosing-bugs: missing (#122)")
else:
    fm, text = frontmatter(diagnosing), diagnosing.read_text()
    if "disable-model-invocation" in fm:
        errors.append("skills/diagnosing-bugs: must be model-invoked (no disable-model-invocation)")
    if len(fm.get("description", "")) > 160:
        errors.append(f"skills/diagnosing-bugs: description is {len(fm.get('description', ''))} chars (> 160, #27)")
    if not re.search(r"<!-- Adapted from mattpocock/skills@[0-9a-f]+ skills/engineering/diagnosing-bugs, MIT", text):
        errors.append("skills/diagnosing-bugs: no `<!-- Adapted from mattpocock/skills@<commit> "
                      "skills/engineering/diagnosing-bugs, MIT` marker")
    for script in sorted(set(re.findall(r"`(scripts/[\w./-]+)`", text))):
        if not (diagnosing.parent / script).is_file():
            errors.append(f"skills/diagnosing-bugs: names {script}, which it does not ship")
    for what, pattern in (
        ("the issue's scratch folder for loops and the HITL copy", r"`\$SCRATCH/<N>/`"),
        ("the observability helper for captured artifacts", r"`docs/agents/observability\.md`"),
        ("the regression test through dk:tdd", r"Skill tool with `dk:tdd`"),
        ("the final proof through dk:verify", r"Skill tool with `dk:verify`"),
        ("a bug born on the branch, whose control is its last pre-fix commit", r"last pre-fix commit[^.]*`dk:verify` step 4"),
        ("the confirmed cause into the PR through dk:pr", r"Skill tool with `dk:pr`"),
        ("a missing seam routed to the user's /dk:improve-codebase-architecture", r"`/dk:improve-codebase-architecture`"),
        ("the fix going ahead without a seam, proven by the loop and dk:verify's control run",
         r"\*\*If no correct seam exists[^\n]*fix goes ahead without waiting[^\n]*Phase 1 loop[^\n]*`dk:verify`'s control run"
         r"[^\n]*in place of the regression test"),
        ("the same proof in Phase 6's checklist when there is no seam",
         r"- \[ \] Regression test passes[^\n]*no correct seam[^\n]*recorded in the report and the PR[^\n]*Phase 1 loop[^\n]*`dk:verify`'s control run"),
        # CodeRabbit local review on #136 (#112): the user runs the HITL copy, so their pasted run is the one Phase 1 needs.
        ("the user's pasted HITL run counting as Phase 1's run", r"HITL[^.]*the user's run counts"),
    ):
        if not re.search(pattern, text):
            errors.append(f"skills/diagnosing-bugs: does not name {what}")
    hitl = diagnosing.parent / "scripts/hitl-loop.template.sh"
    if hitl.is_file() and "<REDACTED>" not in hitl.read_text():
        errors.append("skills/diagnosing-bugs: the HITL template does not ask the user to replace secrets with <REDACTED> before pasting")

lib.finish("dk:diagnosing-bugs")
