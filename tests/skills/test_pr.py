#!/usr/bin/env python3
"""Static checks on the dk:pr skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, skills = lib.errors, lib.skills

# PR, spec and research diagrams follow one set of rules, kept in dk:pr (#116): labels and arrows from pstack
# statechart, the box and word limits from pstack ketchup, the build-up series from teach.
pr_skill = skills["pr"].read_text()
diagram_rules = re.search(r"^#### Diagram rules\n.*?(?=^#{1,4} )", pr_skill, re.M | re.S)
diagram_rules = diagram_rules.group(0) if diagram_rules else ""
for what, pattern in (
    ("states and boxes named by what the reader sees", r"what the reader sees"),
    ("arrows that say what happens", r"[Aa]rrow.*says? what happens"),
    ("about 20 arrows at most", r"about 20 arrows"),
    ("at most 6 boxes of at most 8 words", r"six boxes.*eight words"),
    ("status lists kept out of diagrams", r"status list"),
    ("every box connected", r"[Ee]very box connects"),
    ("each fact given once", r"[Ee]ach fact.*once"),
    ("plain-word labels", r"plain words"),
    ("a short build-up series for 3 or more parts", r"short build-up series.*three or more parts"),
):
    if not re.search(pattern, diagram_rules, re.S):
        errors.append(f"skills/pr: its **Diagram rules** under Summary do not name {what}")
for name in ("to-spec", "research-codebase"):
    if not re.search(r"\*\*Diagram rules\*\*[^\n]*`dk:pr`", skills[name].read_text()):
        errors.append(f"skills/{name}: does not point its diagrams at the **Diagram rules** in `dk:pr`")
# The PR opens with the problem, and its title says why the change matters (tstack file-pr).
if not re.search(r"^## Summary\n\n<[^>\n]*problem[^>\n]*>\n\n<diagram", pr_skill, re.M):
    errors.append("skills/pr: the template's Summary does not open with the problem sentence, before the visual")
summary = re.search(r"^### Summary\n.*?(?=^#{1,4} )", pr_skill, re.M | re.S)
if not summary or not re.search(r"one plain sentence on the problem.*before any visual", summary.group(0), re.S):
    errors.append("skills/pr: its Summary section does not open with one plain sentence on the problem, before any visual")
if not re.search(r"^### Title\n\n[^\n]*why the change matters", pr_skill, re.M):
    errors.append("skills/pr: no ### Title section saying the title tells why the change matters")

lib.finish("dk:pr")
