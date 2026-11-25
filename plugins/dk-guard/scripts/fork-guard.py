#!/usr/bin/env python3
"""dk-guard PreToolUse hook: no forked subagent for an implementer.

A fork (`subagent_type: "fork"`) inherits the orchestrator's whole context, so
an implementer should launch as a plain subagent that works from its brief.
A fork whose description or prompt asks it to commit, push or open a PR, to
implement a named issue, or to run `git worktree add` is denied with that
advice. An ask that is negated, or that someone other than the fork acts on,
asks nothing, and a branch, an existing worktree or a quoted mention of the
command decides nothing. Sweep forks, which work a slice of files and leave
committing to the parent, and every plain subagent are left alone, and so is
every call when the hook itself fails: it fails open.

It reads phrases, not meaning. An ask it misses falls back to the written rule
in `dk:issue-flow` step 2; `tests/hooks/replay_history.py --agent` replays it
over past calls.
"""
import json
import re
import sys

I = re.IGNORECASE
CLAUSE_END = re.compile(r"(?<!\be\.g)(?<!\bi\.e)[.;!?][)\"'*_`]*\s+|\n\s*\n\s*|\n\s*(?=[-*+]\s|\d+[.)]\s|[A-Z])|\s[—–]\s")
BULLET = re.compile(r"\s*(?:[-*+]|\d+[.)])\s")

# What stands right before a verb that instructs the fork.
LEAD = re.compile(
    r"(?:\A[\s*_>#+-]*|[,:(\n]|\b(?:and|then|also|please|finally|but|instead|so|done|green"
    r"|you(?:['’]ll|\s+(?:should|must|may|can|will|are\s+to|need\s+to|have\s+to))?"
    r"|(?:remember|sure|forget|fail|hesitate)\s+to))[\s*_]*\Z", I)
# Somebody else's step: "I will commit and push".
ELSEWHERE = re.compile(
    r"\b(?:I|we|parent|orchestrator|main\s+thread|maintainer)\b\)?(?:['’]ll|\s+(?:will|can|may|must|should))\b"
    r"(?!.*\b(?:you|then)\b)", I | re.DOTALL)

# "Don't forget to commit" and "don't wait for me, commit" negate the delay, not the commit.
NEGATOR = re.compile(
    r"\b(?:(?:do|must|should|may|shall)(?:\s+not|n['’]?t)|never|not\s+to)\b"
    r"(?!\s+(?:forget|fail|hesitate|wait|stop|only|just)\b)", I)
CONDITION = re.compile(r"\b(?:if|when|once|unless|while|since|because|although)\b", I)
TURN = re.compile(r"\b(?:then|but|instead)\b", I)
AND = re.compile(r"\band\b", I)
OR = re.compile(r"\b(?:or|nor)\b", I)
OR_LAST = re.compile(r"\b(?:or|nor)\s+(?:(?:run|use|execute)\s+`?)?\Z", I)
GIT_STEPS = re.compile(
    r"(?:[\s,/`:]|\b(?:run|git|stage|add|amend|rebase|merge|stash|commit|push|open|create|a|any|the|your|it|PR"
    r"|pull\s+request|branch|changes|anything|and|or)\b)*\Z", I)
NOT_HEADING = re.compile(NEGATOR.pattern + r"(?:\s+\w+){0,5}\s*:[\s*_]*\Z", I)

GIT = r"git\s+(?:-C\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s+)?"
ISSUE = r"(?:(?:issue|ticket)s?\s+#?\d+|#\d+|[^\s`]+/issues/\d+)\b"
IN_A_SWEEP = r"(?:\b(?:slice|part|share|group)\b|\bthe\s+#\d+\s+(?:[\w-]+\s+)?(?:sweep|cleanup)\b)"
TO_ISSUE = rf"\b(?:(?!{IN_A_SWEEP})[^,.;:`)\n]){{0,60}}?(?!{IN_A_SWEEP}){ISSUE}"
OBJECT = (r"\s+(?:per|after|each|every|the|your|it|them|this|all|everything|only|once|when|as|with|in|on|separately"
          r"|changes?|to(?!\s+(?:an?|one)\b)|(?:and|then)\s+(?:commit|push|open|report|rerun|run|return|post|hand))\b")

# (what the fork is asked, the pattern, whether it counts only as an instruction's verb, after LEAD)
ISSUE_ASK, GIT_ASK, WORKTREE_ASK = "an issue to implement", "a commit, push or PR to make", "a `git worktree add` to run"
ASKS = [(what, re.compile(rx, I), verb) for what, rx, verb in (
    (ISSUE_ASK, rf"\b(?:implement|fix|own|work\s+on){TO_ISSUE}|\btake\s+(?:on\s+)?{ISSUE}", True),
    (ISSUE_ASK, r"(?<!\banother\s)(?<!\bother\s)(?<!\bsibling\s)\b(?:you|fork|agent)"
                r"(?:\s+(?:are|is|that|who|which|the|a|an|fork|agent|to|will|must|should|now|one))*\s+"
                rf"(?:(?:implement|fix|work)(?:s|es|ing)?|owns?|responsible\s+for)(?:\s+on)?{TO_ISSUE}", False),
    (ISSUE_ASK, rf"\bfork\s+(?:for|that\s+owns)\s+{ISSUE}\s+only\b", False),
    (ISSUE_ASK, r"\b(?:follow(?:ing)?|run|call|invoke|load|use|execute|per|exactly\s+as|carry\s+out)\b"
                r"[^.;\n]{0,40}?dk:implement\b(?!-)", False),
    (GIT_ASK, rf"(?:\b(?:run|use|execute)\s+`?)?\b{GIT}(?:commit|push)\b|\b(?:run\s+`?)?gh\s+pr\s+create\b", True),
    (GIT_ASK, rf"\b(?:commit|push)\b[*_]*(?:{OBJECT}|\s*(?:[.;!](?=\s|\Z)|\Z))", True),
    (GIT_ASK, r"\b(?:open|create|raise)\s+(?:(?:the|a|an|one|your|its|draft)\s+)+(?:PR|pull\s+request)\b", True),
    (GIT_ASK, r"\b(?:an?|one)\s+commit\s+(?:per|after|for\s+each)\b|\bcommitting\s+(?:per|after|each)\b", False),
    (WORKTREE_ASK, rf"\b{GIT}worktree\s+add\b", False),
)]
QUOTES = ("`", '"', "'")
RUN = re.compile(r"\b(?:run|use|execute|call)\s+\Z", I)
MENTION = re.compile(r"\b(?:mention|document|describ|explain|say|quot|contain|reference|regex)\w*[^\w]{1,6}(?:the\s+)?\Z", I)


def clause_before(text, pos):
    """The part of pos's clause that stands before pos."""
    start = 0
    for m in CLAUSE_END.finditer(text):
        if m.end() > pos:
            break
        start = m.end()
    return text[start:pos]


def negated(text, pos, before):
    """Whether a "do not" or "never" in before governs pos: directly, along a list, or as the heading of pos's list."""
    rest = CLAUSE_END.split(text[pos:], maxsplit=1)[0]
    for m in NEGATOR.finditer(before):
        between = before[m.end():]
        if TURN.search(between):
            continue
        if GIT_STEPS.match(between) or not (re.search(r"[,:(]", between) or AND.search(between)):
            return True
        if CONDITION.search(before[:m.start()]):
            continue  # "if the tests do not pass, commit"
        if OR_LAST.search(between) or re.match(r"\s*,[^,]*,\s*\Z", between):
            return True
        if between.rstrip().endswith(",") and OR.search(rest) and not AND.search(between):
            return True
    lines = text[:pos].split("\n")
    if BULLET.match(lines[-1]):
        heading = next((line for line in reversed(lines[:-1]) if line.strip() and not BULLET.match(line)), "")
        return NOT_HEADING.search(heading) is not None
    return False


def mentioned(text, m, before):
    """Whether m's command is quoted as a mention rather than as the command to run."""
    quote = before[-1:]
    if quote not in QUOTES:
        return False
    bare = text[m.end():m.end() + 1] == quote
    return MENTION.search(before) is not None or bare and not RUN.search(before[:-1])


def asks(text):
    """What text asks the fork to do, out of ASKS, each once and in that order."""
    found = []
    for what, rx, verb in ASKS:
        for m in rx.finditer(text) if what not in found else ():
            before = clause_before(text, m.start())
            if verb and not LEAD.search(before) or what == WORKTREE_ASK and mentioned(text, m, before):
                continue
            if not ELSEWHERE.search(before) and not negated(text, m.start(), before):
                found.append(what)
                break
    return found


def handovers(tool_input):
    """What an Agent call's input asks a fork to do that belongs to an implementer; empty for a plain subagent."""
    if not isinstance(tool_input, dict) or tool_input.get("subagent_type") != "fork":
        return []
    return asks("\n\n".join(v for v in (tool_input.get("description"), tool_input.get("prompt")) if isinstance(v, str)))


def decide(tool_input):
    """The deny reason for an Agent call's input, or None to let it through."""
    matched = handovers(tool_input)
    if not matched:
        return None
    return (f"this fork is handed {' and '.join(matched)}, and a fork inherits this whole conversation. "
            "Relaunch it as a plain subagent (leave out subagent_type, or name an agent type) with the brief in "
            "its prompt: the issue, the worktree path and branch, the scratch directory, the skills to call and "
            "the report it owes (dk:issue-flow step 2, Fan-out). Forks stay for sweeps that work a slice of files "
            "and leave commits to you.")


def main():
    try:
        reason = decide(json.load(sys.stdin).get("tool_input"))
    except Exception:
        return  # fail open: a crash never blocks an Agent call
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": "dk-guard: " + reason}}))


if __name__ == "__main__":
    main()
