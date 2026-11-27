#!/usr/bin/env python3
"""Static checks on the dk:code-review skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
FRESH, errors, frontmatter, skills, agents = lib.FRESH, lib.errors, lib.frontmatter, lib.skills, lib.agents

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
review = skills["code-review"].read_text()
for ref in sorted(set(re.findall(r'subagent_type: "dk:([a-z][a-z-]*)"', review))):
    if ref not in agents:
        continue  # the reference check above reports it
    tools = frontmatter(agents[ref]).get("tools")
    if tools is None:
        errors.append(f"agents/{ref}: code-review spawns it, so it needs a tools list (absent inherits Edit and Write)")
    elif WRITE_TOOLS & {t.strip() for t in tools.split(",")}:
        errors.append(f"agents/{ref}: code-review spawns it, so its tools must exclude {sorted(WRITE_TOOLS)}")

baseline = re.search(r"\*\*smell baseline\*\*.*?(?=^The \*\*comment policy\*\*)", review, re.M | re.S)
if baseline is None or re.search(r"empty test", baseline.group(0), re.I):
    errors.append("skills/code-review: the Standards smell baseline lists Empty Test; the Correctness brief owns it")
# pstack principle-fix-root-causes: a guard is right only when the state it handles is legitimate.
for entry in ("Defensive Interior", "Swallowed Error"):
    line = re.search(rf"^- \*\*{entry}\*\*:.*$", baseline.group(0) if baseline else "", re.M)
    if not line or not re.search(r"state it handles is legitimate", line.group(0)):
        errors.append(f"skills/code-review: the baseline's {entry} entry does not ask whether the state it handles is legitimate")
standards_brief = re.search(r"^\*\*Standards sub-agent prompt\*\*.*?(?=^\*\*Spec sub-agent prompt\*\*)", review, re.M | re.S)
if not re.search(r"Whether a test can fail is the Correctness axis's question unless a documented standard rules on it",
                 standards_brief.group(0) if standards_brief else ""):
    errors.append("skills/code-review: the Standards brief must hand whether a test can fail to the Correctness axis, "
                  "keeping documented test rules")
test_question = re.search(r"^  - \*\*Test\*\*:.*$", review, re.M)
test_question = test_question.group(0) if test_question else ""
for what, pattern in (
    ("a loose assertion", r"toBeDefined"),
    ("a call as the only assertion", r"toHaveBeenCalled"),
    ("an empty result as the only assertion", r"toEqual\(\[\]\)"),
    ("an expected value computed by the code under test", r"computed by the code under test"),
    ("a restated constant, config default or prompt string", r"constant, config default or prompt string"),
    ("assertions on data the test built", r"data the test built"),
    ("the fix", r"literal output or effect"),
    ("the cross-row exemption", r"[Cc]ross-row relations between tables"),
    ("the type-test exemption", r"compile-time type tests"),
):
    if not re.search(pattern, test_question):
        errors.append(f"skills/code-review: the Correctness brief's **Test** question does not name {what}")
# pstack e5136d8: the two imagined edits, and two cases a list of assertion shapes misjudges.
for what, pattern in (
    ("the break-the-behaviour edit (does the test still pass?)", r"\*\*[Bb]reak the behaviour\*\*[^*]*still pass"),
    ("the change-the-internals edit (does it now fail?)", r"\*\*[Cc]hange the internals\*\*[^*]*now fail"),
    ("an absence assertion counting when paired with a presence case", r"absence assertion[^;]*paired with a presence case"),
    ("the error type as the contract", r"error type[^.]*\bcontract\b"),
    ("an exact error message as implementation", r"error message"),
):
    if not re.search(pattern, test_question):
        errors.append(f"skills/code-review: the Correctness brief's **Test** question does not name {what}")
empty_result = re.search(r"`toEqual\(\[\]\)`[^;]*", test_question)
empty_result = empty_result.group(0) if empty_result else ""
if not re.search(r"\bwhen a subject that does nothing\b.*\breturns\b", empty_result) or not re.search(
        r"`undefined`.*`None`", empty_result):
    errors.append("skills/code-review: the Correctness brief's **Test** question must flag an empty-result-only assertion "
                  "(`toEqual([])`) only when a subject that does nothing still returns that result, and say in the same "
                  "clause that a no-op returns `undefined` or `None` (#87: reviewers took a no-op to return [])")

# Each finding carries a stable id and a severity judged against the change's intent, and the change's author
# answers every id in a ledger over a bounded number of rounds (#125, tstack sol-loop).
reviewer = agents["reviewer"].read_text()
# The same sentence in the reviewer and in code-review's Judge step (#112, CodeRabbit on #136).
IMPACT = re.escape("A rare path or a small cost is a nit unless its impact (data loss, security, money, a customer-visible "
                   "break) makes it a blocker or should.")
for what, pattern in (
    ("the finding line", r"`<id> \[blocker\|should\|nit\] <file>:<line> <claim>\. Fix: <fix>`"),
    ("the severity judged against the change's intent", r"against the change's intent"),
    ("a floor the brief sets overriding that scale", r"unless the brief sets a floor"),
    ("blocker as the intended case wrong", r"\*\*blocker\*\*[^\n]*intended case is wrong"),
    ("should as a real bug callers will hit", r"\*\*should\*\*[^\n]*real bug callers will hit"),
    ("nit as everything else", r"\*\*nit\*\*[^\n]*everything else"),
    ("ids prefixed as the brief says", r"prefix the brief"),
    ("old ids kept and marked in a later round", r"`resolved`[^\n]*`still open: <reason>`"),
    ("a Correctness finding citing its trigger and consequence, not a rule", r"Correctness finding[^.]*trigger[^.]*observable consequence"),
    ("severity by impact and likelihood", r"impact and likelihood"),
    ("a rare path or small cost kept a nit only when its impact is small", IMPACT),
):
    if not re.search(pattern, reviewer):
        errors.append(f"agents/reviewer: does not name {what}")
comment_reviewer = agents["comment-reviewer"].read_text()
if "<!-- Adapted from cursor/plugins pstack@" not in comment_reviewer:
    errors.append("agents/comment-reviewer: lost its pstack provenance marker")
for what, pattern in (
    ("the finding line", r"`<id> \[should\|nit\] <file>:<line> "),
    ("findings as nits unless the comment states something false", r"`nit` unless the comment states something false"),
    ("Stale as a should", r"^- \*\*Stale\*\*:[^\n]*`should`"),
):
    if not re.search(pattern, comment_reviewer, re.M):
        errors.append(f"agents/comment-reviewer: does not name {what}")
for name, text in (("agents/reviewer", reviewer), ("agents/comment-reviewer", comment_reviewer),
                   ("skills/code-review", review)):
    if re.search(r"hard violation|judgement call|\bHard\.|hard or judgement", text, re.I):
        errors.append(f"{name}: still marks findings hard or judgement call; the blocker, should or nit severity replaces it")
spawn = re.search(r"^### 4\..*?(?=^### 5\.)", review, re.M | re.S)
if not re.search(r"`ST`.*Standards.*`SP`.*Spec.*`CO`.*Correctness.*`CM`.*Comments", spawn.group(0) if spawn else "", re.S):
    errors.append("skills/code-review: step 4 must hand each axis its id prefix (`ST`, `SP`, `CO`, `CM`), "
                  "so ids stay unique across the four reports")
steps = re.findall(r"^### (\d+)\. (.*)$", review, re.M)
answer = re.search(r"^### \d+\. Answer findings\n.*?(?=^## |\Z)", review, re.M | re.S)
answer = answer.group(0) if answer else ""
if not steps or steps[-1][1] != "Answer findings":
    errors.append("skills/code-review: its last step must be 'Answer findings'")
for what, pattern in (
    ("a ledger of id, severity and outcome", r"ledger.*id.*severity.*outcome"),
    ("the fixed outcome with evidence", r"`fixed: [^`]+`"),
    ("the disagree outcome with evidence", r"`disagree: [^`]+`"),
    ("the declined outcome", r"`declined: [^`]+`"),
    ("later rounds on the open ids and the code changed since", r"only the open ids and the code changed since"),
    ("3 rounds by default", r"\b3 rounds\b"),
    ("5 rounds for the named risk classes", r"\b5\b[^.]*security, permissions, auth, data loss or concurrency"),
    ("stopping early on a round that brings only nits", r"round brings only nits"),
    ("the diff size after each round", r"`git diff --shortstat <fixed-point>`"),
    ("growth cut first", r"cut first"),
    ("declined findings worth doing through scope intake", r"`dk:issue-flow` step 3"),
    ("severity by impact and likelihood", r"impact and likelihood"),
    ("a rare path or small cost kept a nit only when its impact is small", IMPACT),
    ("each next-round prompt carrying its own axis's ledger rows", r"its own axis's ledger rows"),
    ("each open id reaching the next round with its claim and location",
     r"\*\*Next round\*\*[^\n]*each open id's original claim and `file:line` from the report that raised it"),
    ("the nits-only stop only when no nit's fix changed behaviour code", r"round brings only nits[^.]*no behaviour code"),
    # CodeRabbit on #136, round 2 (#112): a declined nit has no issue, so the report names one only when filed.
    ("an issue number reported only for a declined finding scope intake filed",
     r"issue number of each declined finding that scope intake filed"),
):
    if not re.search(pattern, answer, re.S):
        errors.append(f"skills/code-review: its Answer findings step does not name {what}")

if FRESH in review:
    errors.append(f"skills/code-review: launches named agent types, which never fork; it skips the {FRESH} line")

lib.finish("dk:code-review")
