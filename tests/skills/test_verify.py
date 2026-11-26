#!/usr/bin/env python3
"""Static checks on the dk:verify skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, skills = lib.errors, lib.skills

# A bug born on the branch passes at the base, so its control is the branch's last pre-fix commit (#112, CodeRabbit on #136).
control = re.search(r"^1\. \*\*Control\*\*.*$", skills["verify"].read_text(), re.M)
if not control or "the branch's last pre-fix commit when the bug came in on this branch" not in control.group(0):
    errors.append("skills/verify: step 4's control must be the branch's last pre-fix commit when the bug came in on this branch")
# CodeRabbit on #136, round 4 (#112): the parent of the commit that brought the bug in has no bug yet, so it would pass.
if control and not re.search(r"parent \(`<fix sha>\^`\) of the fix's first commit[^.]*still has the bug", control.group(0)):
    errors.append("skills/verify: step 4's control for a bug born on the branch must be the parent of the fix's "
                  "first commit, which still has the bug")

# A performance claim owes its spread, so "faster" inside the noise reads as inconclusive (#119).
owe = re.search(r"^## 1\..*?(?=^## 2\.)", skills["verify"].read_text(), re.M | re.S)
perf = re.search(r"^\| Performance claim .*$", owe.group(0) if owe else "", re.M)
perf = perf.group(0) if perf else ""
if not perf:
    errors.append("skills/verify: step 1's proof table has no Performance claim row")
for what, pattern in (
    ("the limiter", r"\blimiter\b"),
    ("the decision rule written before the first run", r"decision rule.*before the first run"),
    ("both sides run tuned", r"\btuned\b"),
    ("errors counted", r"errors.*counted"),
    # CodeRabbit on #136 (#112): a faster run with wrong outputs must still fail the claim.
    ("an error threshold in the decision rule that rejects the claim", r"error threshold[^.]*rejects the claim"),
    ("at least 5 alternating runs per side", r"at least 5 runs per side, alternating"),
    ("the range reported", r"median and range"),
    # CodeRabbit on #136 (#112): the threshold is judged on errors both sides report.
    ("each side's error count reported beside the threshold", r"median and range, with each side's error count"),
    ("the work confirmed to have happened", r"work confirmed to have happened"),
    ("what spread and effect are, in one unit",
     r"[Ss]pread is the wider of the two sides' ranges \(max minus min\)[^|]*effect the absolute difference of the medians"
     r"[^|]*the metric's own unit"),
    ("the inconclusive verdict when the spread is larger than the effect",
     r"spread larger than the effect.*\*\*inconclusive\*\*"),
):
    if perf and not re.search(pattern, perf):
        errors.append(f"skills/verify: step 1's Performance claim row does not name {what}")

# Verify was 25% of a small PR's time; a small change owes a red/green test or one phone-width screenshot (#173).
tier = re.search(r"^\*\*Tier\.\*\*.*$", owe.group(0) if owe else "", re.M)
tier = tier.group(0) if tier else ""
for what, pattern in (
    ("the tier script, run from dk:code-review", r"`python3 -I <base directory>/\.\./code-review/tier <base>`"),
    ("the small tier's red/green test", r"`small` tier[^\n]*regression test seen red, then green"),
    ("the small tier's one phone-width screenshot for a visible change", r"visible change[^\n]*one screenshot at 390 × 844"),
    ("the small tier skipping the stack and the control run", r"no stack \(steps 2 and 3\) and no control run \(step 4\)"),
    ("the other tiers owing the table in full", r"`standard` and `risky` tiers owe[^\n]*in full"),
):
    if not re.search(pattern, tier):
        errors.append(f"skills/verify: step 1's **Tier.** paragraph does not name {what}")

lib.finish("dk:verify")
