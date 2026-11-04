#!/usr/bin/env python3
"""dk-guard PreToolUse hook: no forked subagent for an implementer.

A fork (`subagent_type: "fork"`) inherits the orchestrator's whole context, so
an implementer should launch as a plain subagent that works from its brief.
A fork whose description or prompt hands over an issue to implement, a
worktree with its branch (or one that already exists, with a branch, commit,
push or open-PR cue), or a `git worktree add` to run is denied with that
advice. Sweep forks, which work a slice of files and leave committing to the
parent, and every plain subagent are left alone, and so is every call when the
hook itself fails: it fails open.

The terms below are the shapes of the implementer forks in past sessions;
`tests/hooks/replay_history.py --agent` replays them.
"""
import json
import re
import sys

I = re.IGNORECASE
PATH = r"[~/$][\w./~${}-]*"
UNSAID = r"(?<!\bnot\s)(?<!n't\s)(?<!\bnever\s)"  # "do not commit" hands nothing over
OPEN_PR = rf"{UNSAID}\bopen\s+(?:the|a)\s+PR\b"
HANDOVER_CUE = rf"\bbranch\b|{UNSAID}\b(?:commit|push)\s+(?:per|after|each|every|the|your|it|to)\b|{OPEN_PR}"
HANDOVERS = [
    ("an issue to implement", re.compile(
        r"\bdk:implement"
        r"|\bimplement(?:s|ing)?\s+(?:issue\s+|ticket\s+)?#\d+"
        r"|\b(?:owns?|takes?|fix(?:es)?|responsible\s+for)\s+(?:issue|ticket)\s+#\d+"
        rf"|(?s:\A(?=.*?#\d+).*?){OPEN_PR}"
        r"|\bfork\s+(?:for|that\s+owns)\s+(?:issue\s+|ticket\s+)?#\d+\s+only\b", I)),
    ("a worktree with its branch", re.compile(
        rf"(?s:\A(?=.*?(?:{HANDOVER_CUE})).*?)\bworktree\b[\s(:]*(?:already\s+)?(?:exists|created)\b"
        rf"|\bworktree\b[^.\n]{{0,40}}?{PATH}`?\s*(?:,|\bon\b)\s*(?:on\s+)?branch\b", I)),
    ("a `git worktree add` to run", re.compile(
        r"\bgit\s+(?:-C\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s+)?worktree\s+add\b", I)),
]


def handovers(tool_input):
    """What an Agent call's input hands a fork, from HANDOVERS; empty for a plain subagent."""
    if not isinstance(tool_input, dict) or tool_input.get("subagent_type") != "fork":
        return []
    text = "\n".join(v for v in (tool_input.get("description"), tool_input.get("prompt")) if isinstance(v, str))
    return [what for what, rx in HANDOVERS if rx.search(text)]


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
