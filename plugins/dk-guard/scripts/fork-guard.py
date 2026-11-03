#!/usr/bin/env python3
"""dk-guard PreToolUse hook: no forked subagent for an implementer.

A fork (`subagent_type: "fork"`) inherits the orchestrator's whole context, so
an implementer should launch as a plain subagent that works from its brief.
A fork whose description or prompt hands over an issue to implement, a
worktree with its branch, or a `git worktree add` to run is denied with that
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
HANDOVERS = [
    ("an issue to implement", re.compile(
        r"\bdk:implement"
        r"|\bimplement(?:s|ing)?\s+(?:issue\s+|ticket\s+)?#\d+"
        r"|\bowns?\s+(?:issue|ticket)\s+#\d+"
        r"|\bfork\s+(?:for|that\s+owns)\s+(?:issue\s+|ticket\s+)?#\d+\s+only\b", I)),
    ("a worktree with its branch", re.compile(
        r"\bworktree\b[\s(:]*(?:already\s+)?(?:exists|created)\b"
        rf"|\bworktree\b[^.\n]{{0,40}}?{PATH}`?\s*(?:,|\bon\b)\s*(?:on\s+)?branch\b", I)),
    ("a `git worktree add` to run", re.compile(rf"\bgit\s+(?:-C\s+{PATH}\s+)?worktree\s+add\b", I)),
]


def decide(tool_input):
    """The deny reason for an Agent call's input, or None to let it through."""
    if not isinstance(tool_input, dict) or tool_input.get("subagent_type") != "fork":
        return None
    text = "\n".join(v for v in (tool_input.get("description"), tool_input.get("prompt")) if isinstance(v, str))
    matched = [what for what, rx in HANDOVERS if rx.search(text)]
    if not matched:
        return None
    return (f"this fork is handed {' and '.join(matched)}, and a fork inherits this whole conversation. "
            "Relaunch it as a plain subagent (leave out subagent_type, or name an agent type) with the brief in "
            "its prompt: the issue, the worktree path and branch, the scratch directory, the skills to call and "
            "the report it owes. Forks stay for sweeps that work a slice of files and leave commits to you.")


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
