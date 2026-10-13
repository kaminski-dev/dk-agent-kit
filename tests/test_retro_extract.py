#!/usr/bin/env python3
"""Runs the dk:retro extraction script against a fixture transcript tree.

The fixture records copy the shape of Claude Code 2.1.29x transcripts, so a
failure here after a Claude Code update means the transcript format moved and
the script's matching needs to follow it.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "plugins", "dk", "skills", "retro", "extract.py")

CWD = "/work/repo"
SESSION = "s-1"


def user(ts, content, **extra):
    return {"type": "user", "timestamp": ts, "cwd": CWD, "sessionId": SESSION,
            "message": {"role": "user", "content": content}, **extra}


def human(ts, text):
    return user(ts, text, origin={"kind": "human"})


def tool_use(ts, tid, name, inp):
    return {"type": "assistant", "timestamp": ts, "cwd": CWD, "sessionId": SESSION,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def tool_result(ts, tid, body, is_error=True, denial=None):
    extra = {"toolDenialKind": denial} if denial else {}
    return user(ts, [{"type": "tool_result", "tool_use_id": tid, "content": body, "is_error": is_error}], **extra)


def attachment(ts, att):
    return {"type": "attachment", "timestamp": ts, "cwd": CWD, "sessionId": SESSION, "attachment": att}


GUARD = "PreToolUse:Bash hook error: dk-guard: Pushing to main deploys to production."
SAFETY = "Permission for this command was denied by a built-in Claude Code safety check, not by the user."
APPROVAL = "This command requires approval"
REJECTED = "The user doesn't want to proceed with this tool use. The tool use was rejected."
GATE = "dk-guard: .claude/gate.sh failed (exit 1). Last lines:\nlint failed\n\nFix the failure before you finish."
GATE_AGAIN = "dk-guard: .claude/gate.sh failed (exit 1) again; the turn ends anyway. Last lines:\nlint failed"
TAIL = "\nFAILED test_a.py::test_x"  # 25 characters
LONG_FAILURE = "Exit code 1\n" + "." * 900 + TAIL  # head 200 and tail 400 survive
HAND_BACK = ("Another Claude session sent a message:\n<agent-message from=\"a1\">\n[Subagent hand-back] "
             "The text below is the final report of a subagent this session delegated to.")
NOTIFICATION = "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n</task-notification>"

MAIN = [
    human("2026-10-01T09:00:00Z", "Implement #1"),
    tool_use("2026-10-01T09:01:00Z", "t1", "Bash", {"command": "git push origin main"}),
    tool_result("2026-10-01T09:01:01Z", "t1", GUARD, denial="permission-rule"),
    tool_use("2026-10-01T09:02:00Z", "t2", "Bash", {"command": "rm -rf ~/workspace"}),
    tool_result("2026-10-01T09:02:01Z", "t2", SAFETY, denial="permission-rule"),
    tool_use("2026-10-01T09:03:00Z", "t3", "Edit", {"file_path": "/work/repo/a.py", "old_string": "x"}),
    tool_result("2026-10-01T09:03:01Z", "t3", REJECTED, denial="user-rejected"),
    tool_use("2026-10-01T09:03:30Z", "t6", "Bash", {"command": "sh .claude/gate.sh"}),
    tool_result("2026-10-01T09:03:31Z", "t6", APPROVAL, denial="user-rejected"),  # headless: no user to ask
    tool_use("2026-10-01T09:04:00Z", "t4", "Bash", {"command": "pytest"}),
    tool_result("2026-10-01T09:04:01Z", "t4", [{"type": "text", "text": LONG_FAILURE}]),
    tool_use("2026-10-01T09:05:00Z", "t5", "Read", {"file_path": "/work/repo/a.py"}),
    tool_result("2026-10-01T09:05:01Z", "t5", "1\tx = 1", is_error=False),
    user("2026-10-01T09:06:00Z", [{"type": "text", "text": "[Request interrupted by user for tool use]"}]),
    human("2026-10-01T09:07:00Z", "No, work in the worktree instead"),
    human("2026-10-01T09:07:10Z", "<bash-input>git status</bash-input>"),  # the user's own ! command
    human("2026-10-01T09:07:11Z", "<bash-stdout>On branch main</bash-stdout><bash-stderr></bash-stderr>"),
    attachment("2026-10-01T09:07:59Z", {"type": "queued_command", "prompt": HAND_BACK.split("\n", 1)[1],
                                        "commandMode": "prompt", "origin": {"kind": "peer", "from": "a1"}}),
    user("2026-10-01T09:08:00Z", HAND_BACK, isMeta=True, origin={"kind": "peer", "from": "a1"}),
    attachment("2026-10-01T09:08:01Z", {"type": "queued_command", "prompt": NOTIFICATION,
                                        "commandMode": "task-notification", "origin": {"kind": "task-notification"}}),
    user("2026-10-01T09:08:02Z", "[SYSTEM NOTIFICATION - NOT USER INPUT]\nA background task finished.",
         isMeta=True, origin={"kind": "task-notification"}),
    user("2026-10-01T09:08:03Z", NOTIFICATION),  # the same before transcripts carried origin
    attachment("2026-10-01T09:09:00Z", {"type": "queued_command", "prompt": "why does it take so long",
                                        "commandMode": "prompt", "origin": {"kind": "human"}}),
    attachment("2026-10-01T09:10:00Z", {"type": "hook_blocking_error", "hookName": "Stop", "hookEvent": "Stop",
                                        "blockingError": {"blockingError": GATE}}),
    user("2026-10-01T09:10:01Z", "Stop hook feedback:\n" + GATE, isMeta=True),
    attachment("2026-10-01T09:11:00Z", {"type": "hook_system_message", "hookName": "Stop", "hookEvent": "Stop",
                                        "content": GATE_AGAIN}),
    human("2026-10-02T23:59:59Z", "Last prompt of the window"),
    human("2026-10-03T00:00:00Z", "After the window"),
]

SUBAGENT = [
    user("2026-10-01T09:20:00Z", "You are reviewing the diff for #1."),
    tool_use("2026-10-01T09:20:01Z", "s1", "Edit", {"file_path": "/work/repo/b.py"}),
    tool_result("2026-10-01T09:20:02Z", "s1", "<tool_use_error>File has not been read yet. Read it first "
                "before writing to it.</tool_use_error>"),
]

BEFORE = [
    dict(human("2026-09-30T23:59:59Z", "Start"), sessionId="s-0"),
    dict(human("2026-09-30T23:59:59Z", "Before the window"), sessionId="s-0"),
]


def ev(ts, kind, text, **extra):
    return {"ts": ts, "session": SESSION, "project": CWD, "kind": kind, "text": text, **extra}


EXPECTED = [
    ev("2026-10-01T09:01:01Z", "guard", GUARD, tool="Bash: git push origin main"),
    ev("2026-10-01T09:02:01Z", "denied", SAFETY, tool="Bash: rm -rf ~/workspace"),
    ev("2026-10-01T09:03:01Z", "rejected", REJECTED, tool="Edit: /work/repo/a.py"),
    ev("2026-10-01T09:03:31Z", "denied", APPROVAL, tool="Bash: sh .claude/gate.sh"),
    ev("2026-10-01T09:04:01Z", "tool_error", "Exit code 1\n" + "." * 188 + " [...] " + "." * 375 + TAIL,
       tool="Bash: pytest",
       bucket="test-or-build-fail"),
    ev("2026-10-01T09:06:00Z", "interrupt", "[Request interrupted by user for tool use]"),
    ev("2026-10-01T09:07:00Z", "prompt", "No, work in the worktree instead"),
    ev("2026-10-01T09:09:00Z", "prompt", "why does it take so long"),
    ev("2026-10-01T09:10:00Z", "stop_gate", GATE),
    ev("2026-10-01T09:11:00Z", "stop_gate", GATE_AGAIN),
    ev("2026-10-02T23:59:59Z", "prompt", "Last prompt of the window"),
    ev("2026-10-01T09:20:02Z", "tool_error", "<tool_use_error>File has not been read yet. Read it first before "
       "writing to it.</tool_use_error>", tool="Edit: /work/repo/b.py", bucket="not-read-first"),
]


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
        f.write("{not json\n")  # a torn last line, as a killed session leaves


def build_tree(root):
    projects = os.path.join(root, "projects")
    write_jsonl(os.path.join(projects, "-work-repo", SESSION + ".jsonl"), MAIN)
    write_jsonl(os.path.join(projects, "-work-repo", SESSION, "subagents", "agent-a1.jsonl"), SUBAGENT)
    write_jsonl(os.path.join(projects, "-work", "s-0.jsonl"), BEFORE)
    return projects


def extract(root, since, until):
    out = os.path.join(root, f"out-{since}-{until}.jsonl")
    proc = subprocess.run([sys.executable, "-I", SCRIPT, since, until, out, "--projects-dir", build_tree(root)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    with open(out, encoding="utf-8") as f:
        return [json.loads(line) for line in f], json.loads(proc.stdout)


def case_one_record_per_event_in_the_window(root):
    records, _ = extract(root, "2026-10-01", "2026-10-02")
    for want, got in zip(EXPECTED, records):
        assert got == want, f"\n got  {got}\n want {want}"
    assert len(records) == len(EXPECTED), f"{len(records)} records, want {len(EXPECTED)}"


def case_hand_backs_and_task_notifications_are_not_prompts(root):
    records, _ = extract(root, "2026-10-01", "2026-10-02")
    texts = " ".join(r["text"] for r in records)
    for marker in ("Subagent hand-back", "task-notification", "SYSTEM NOTIFICATION", "You are reviewing"):
        assert marker not in texts, marker


def case_records_outside_the_window_are_not_emitted(root):
    records, _ = extract(root, "2026-10-02", "2026-10-02")
    assert records == [ev("2026-10-02T23:59:59Z", "prompt", "Last prompt of the window")], records


def case_summary_counts_events_by_kind(root):
    _, summary = extract(root, "2026-10-01", "2026-10-02")
    assert summary["files"] == 3, summary
    assert summary["by_kind"] == {"denied": 2, "guard": 1, "interrupt": 1, "prompt": 3, "rejected": 1,
                                  "stop_gate": 2, "tool_error": 2}, summary


def case_a_bad_date_fails_with_usage(root):
    proc = subprocess.run([sys.executable, "-I", SCRIPT, "last-month", "2026-10-02", os.path.join(root, "x.jsonl")],
                          capture_output=True, text=True)
    assert proc.returncode == 2, proc
    assert "SINCE" in proc.stderr, proc.stderr


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as root:
        for case in CASES:
            try:
                case(root)
                print(f"ok   {case.__name__[5:]}")
            except Exception as e:
                failed += 1
                print(f"FAIL {case.__name__[5:]}: {e!r}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
