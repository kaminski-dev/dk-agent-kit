#!/usr/bin/env python3
"""Static checks on the dk:implement skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, skills = lib.errors, lib.skills

implement = skills["implement"].read_text()
if "fix what it finds" in implement or not re.search(r"\*\*Answer findings\*\*.*ledger", implement):
    errors.append("skills/implement: must answer review findings through dk:code-review's **Answer findings** "
                  "ledger, not fix what the review finds")

# The implementer settles the repeating small findings before the review sees them (#172: 588 restating comments,
# 239 renames, 178 drifted doc lines among 3,923 findings).
self_pass = re.search(r"\*\*[Ss]elf-pass\*\*.*?(?=call the Skill tool with `dk:code-review`)", implement, re.S)
self_pass = self_pass.group(0) if self_pass else ""
for what, pattern in (("removing comments that restate the code", r"comment[^.;]*restate"),
                      ("renaming in place of commenting", r"renam"),
                      ("updating doc lines that name a changed symbol", r"doc line[^.;]*name[^.;]*symbol")):
    if not re.search(pattern, self_pass):
        errors.append(f"skills/implement: its **Self-pass** before the dk:code-review call does not name {what}")

# An unattended run asks only for a closed list of reasons, through the question tool, and lists the rest as
# decisions it took (#126, tstack full-send's "Asking the user").
asking = re.search(r"^## Asking\n.*?(?=^## |\Z)", implement, re.M | re.S)
asking = asking.group(0) if asking else ""
if not asking:
    errors.append("skills/implement: has no ## Asking section")
for what, pattern in (
    ("no proof possible", r"^- [^\n]*no proof[^\n]*possible"),
    ("a ready gate that cannot pass", r"^- [^\n]*ready gate[^\n]*cannot pass"),
    ("a step outside the grant", r"^- [^\n]*outside the grant"),
    ("an ambiguous goal", r"^- [^\n]*goal is ambiguous"),
    ("another PR making this one obsolete", r"^- [^\n]*another PR makes this one obsolete"),
    ("AskUserQuestion with the recommendation first", r"AskUserQuestion.*recommendation first"),
    ("the final message opening with the question when there is no question tool",
     r"no question tool[^.]*open[^.]*final message with the question"),
    ("the Decisions taken list", r"\*\*Decisions taken\*\*"),
):
    if asking and not re.search(pattern, asking, re.M | re.S):
        errors.append(f"skills/implement: its ## Asking section does not name {what}")
report = re.search(r"^## Report\n.*?(?=^## |\Z)", implement, re.M | re.S)
report = report.group(0) if report else ""
if "**Decisions taken**" not in report or not re.search(r"ends with[^.]*verdict[^.]*`dk:issue-flow` step 6", report):
    errors.append("skills/implement: its ## Report must carry **Decisions taken** and end with the verdict "
                  "from `dk:issue-flow` step 6's **Ready gate.**")
# A run can stop before any PR exists, and the report carries the review's own report (#112, CodeRabbit on #136).
for what, pattern, text in (
    ("the PR link only when one exists, in the question", r"PR link when one exists", asking),
    ("a run stopped before any PR: where, the question, Decisions taken, no verdict",
     r"stopped before any PR[^.]*where it stopped[^.]*question[^.]*\*\*Decisions taken\*\*[^.]*no verdict", report),
    ("code-review's Answer findings report: rounds, shortstat, declined issue numbers",
     r"\*\*Answer findings\*\* report \(the rounds run[^)]*shortstat before and after[^)]*declined finding's issue number\)",
     report),
):
    if not re.search(pattern, text):
        errors.append(f"skills/implement: does not name {what}")

lib.finish("dk:implement")
