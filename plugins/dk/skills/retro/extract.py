#!/usr/bin/env python3
"""Extract a retro's evidence from Claude Code transcripts in a date window.

Usage: python3 -I extract.py SINCE UNTIL OUT.jsonl [--projects-dir DIR]

SINCE and UNTIL are ISO dates, both inclusive, compared with each record's UTC
timestamp. Reads DIR/*/*.jsonl and their DIR/*/*/subagents/*.jsonl (default
~/.claude/projects) and writes one JSON line per event to OUT:

  {"ts", "session", "project", "kind", "text"}, plus "tool" ("Bash: <command>")
  on tool-result events and "bucket" on tool_error.

  kind  prompt      a human prompt after the session's first, typed or queued
                    mid-turn; subagent hand-backs, task notifications and
                    coordinator messages are not prompts
        interrupt   the user interrupted a turn
        rejected    the user rejected a tool call
        denied      a permission rule, safety check or the auto mode classifier
                    denied a tool call
        guard       a dk-guard hook denied a tool call
        stop_gate   Stop hook feedback (the dk-guard gate.sh failure)
        tool_error  any other errored tool result, with a coarse bucket

project is the record's cwd. Texts are cut to 400 characters (a tool error
keeps its head and tail). OUT holds raw prompt text: keep it in the session's
scratch directory. Prints a summary with counts by kind to stdout.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re

CUT = 400

NOT_A_PROMPT = re.compile(
    r"^\s*(<local-command|<bash-input>|<bash-std|<command-name>|<command-message>|<task-notification>|<agent-message|"
    r"\[SYSTEM NOTIFICATION|Another Claude session sent a message|<system-reminder>|Caveat:|"
    r"\[Request interrupted|Base directory for this skill|Stop hook feedback)")
GUARD = re.compile(r"^(\S+ hook error: )?dk-guard:")
REJECTED = re.compile(r"doesn't want to proceed|User rejected|rejected this")
DENIED = re.compile(r"Permission (for|to) .* denied|requires approval|classifier gave no verdict|"
                    r"denied by|blocked by a deny rule")
BUCKETS = [
    ("not-read-first", r"File has not been read yet"),
    ("modified-since-read", r"modified since read"),
    ("file-missing", r"File does not exist|No such file or directory"),
    ("too-large", r"exceeds maximum allowed tokens"),
    ("zsh-glob-nomatch", r"no matches found"),
    ("zsh-word-split", r"command not found: \S+ "),
    ("zsh-modifier", r"bad (math expression|substitution)|unmatched \""),
    ("cmd-not-found", r"command not found"),
    ("blocked-sleep", r"Blocked: sleep"),
    ("skill-unavailable", r"Skill .* cannot be used"),
    ("browser", r"^### Error"),
    ("not-git-repo", r"not a git repository"),
    ("push-rejected", r"\[rejected\]|failed to push some refs|protected branch"),
    ("traceback", r"Traceback"),
    ("test-or-build-fail", r"FAIL|✗|failed|error TS\d+|ERR!"),
    ("exit-nonzero", r"^Exit code \d+"),
]


def iso_date(value):
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date: {value!r}")


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def origin_kind(record):
    """human, peer (another agent), coordinator, task-notification, or None in older transcripts."""
    origin = record.get("origin")
    return origin.get("kind") if isinstance(origin, dict) else None


def tool_label(name, inp):
    if isinstance(inp, dict):
        for key in ("command", "file_path", "pattern", "skill", "url", "query", "description"):
            if key in inp:
                return f"{name}: {str(inp[key])[:200]}"
    return name


def bucket(text):
    for name, pattern in BUCKETS:
        if re.search(pattern, text[:600], re.M) or re.search(pattern, text[-600:], re.M):
            return name
    return "other"


def tool_event(body, denial, is_error):
    """The kind of a tool result, or None when it is not evidence."""
    head = body[:400]
    if not is_error:
        return None
    if GUARD.search(head):
        return "guard"
    # toolDenialKind says user-rejected also when a headless session had no user to ask
    if REJECTED.search(head):
        return "rejected"
    if denial is not None or DENIED.search(head):
        return "denied"
    return "tool_error"


def cut(text):
    return text if len(text) <= CUT else text[:CUT]


def events(path, since, until):
    """Yield the events of one transcript file in file order."""
    sidechain = os.sep + "subagents" + os.sep in path
    tool_uses, seen_prompt = {}, False
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            kind_of_record, ts = r.get("type"), str(r.get("timestamp", ""))
            if kind_of_record == "assistant":
                for x in (r.get("message") or {}).get("content") or []:
                    if isinstance(x, dict) and x.get("type") == "tool_use":
                        tool_uses[x.get("id")] = tool_label(x.get("name"), x.get("input"))
                continue
            in_window = since <= ts[:10] <= until
            base = {"ts": ts, "session": r.get("sessionId", ""), "project": r.get("cwd", "")}

            if kind_of_record == "attachment":
                a = r.get("attachment") or {}
                if not in_window:
                    continue
                if a.get("type") == "queued_command" and a.get("commandMode") == "prompt" \
                        and origin_kind(a) in ("human", None) and not NOT_A_PROMPT.match(str(a.get("prompt", ""))):
                    yield dict(base, kind="prompt", text=cut(str(a["prompt"])))
                elif a.get("hookEvent") == "Stop" and a.get("type") == "hook_blocking_error":
                    err = a.get("blockingError")
                    yield dict(base, kind="stop_gate", text=cut(str(err.get("blockingError") if isinstance(err, dict) else err)))
                elif a.get("hookEvent") == "Stop" and a.get("type") == "hook_system_message":
                    yield dict(base, kind="stop_gate", text=cut(str(a.get("content", ""))))
                continue

            if kind_of_record != "user":
                continue
            content = (r.get("message") or {}).get("content")
            results = [x for x in content if isinstance(x, dict) and x.get("type") == "tool_result"] \
                if isinstance(content, list) else []
            if results:
                if not in_window:
                    continue
                for x in results:
                    body = text_of(x.get("content"))
                    kind = tool_event(body, r.get("toolDenialKind"), x.get("is_error"))
                    if kind is None:
                        continue
                    event = dict(base, kind=kind, tool=tool_uses.get(x.get("tool_use_id"), "?"))
                    if kind == "tool_error":
                        short = body if len(body) <= 2 * CUT else body[:CUT // 2] + " [...] " + body[-CUT:]
                        yield dict(event, text=short, bucket=bucket(body))
                    else:
                        yield dict(event, text=cut(body))
                continue

            text = text_of(content)
            if sidechain or r.get("isMeta"):
                continue
            if text.startswith("[Request interrupted"):
                if in_window:
                    yield dict(base, kind="interrupt", text=cut(text))
                continue
            if origin_kind(r) not in ("human", None) or NOT_A_PROMPT.match(text) or not text.strip():
                continue
            if not seen_prompt:
                seen_prompt = True
                continue
            if in_window:
                yield dict(base, kind="prompt", text=cut(text))


def main():
    parser = argparse.ArgumentParser(description="Extract retro evidence from Claude Code transcripts.")
    parser.add_argument("since", metavar="SINCE", type=iso_date, help="first day, YYYY-MM-DD")
    parser.add_argument("until", metavar="UNTIL", type=iso_date, help="last day, YYYY-MM-DD")
    parser.add_argument("out", metavar="OUT.jsonl")
    parser.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    args = parser.parse_args()

    base = args.projects_dir
    files = sorted(glob.glob(os.path.join(base, "*", "*.jsonl"))
                   + glob.glob(os.path.join(base, "*", "*", "subagents", "*.jsonl")))
    by_kind, with_events = collections.Counter(), 0
    with open(args.out, "w") as out:
        for path in files:
            found = False
            for event in events(path, args.since, args.until):
                out.write(json.dumps(event, ensure_ascii=False) + "\n")
                by_kind[event["kind"]] += 1
                found = True
            with_events += found
    print(json.dumps({"files": len(files), "files_with_events": with_events, "events": sum(by_kind.values()),
                      "by_kind": dict(sorted(by_kind.items()))}))


if __name__ == "__main__":
    main()
