#!/usr/bin/env python3
"""dk-guard PreToolUse hook for Bash: runs the pushed checkout's .claude/gate.sh before a git push.

Sessions start in the main checkout and work in a linked worktree, and agents
commit before they stop, so the Stop gate, which gates uncommitted changes in
the session's cwd, rarely sees the work. This hook gates the push instead. For
each `git push` in the command it takes the directory the push runs in (the
`cd` or `git -C` target, resolved as guard-bash.py resolves it) and runs that
checkout's executable .claude/gate.sh from its root. A failing gate denies the
push with the gate's last lines; a passing gate is silent.

Pushes of verify-assets/*, branch deletes and pushes guard-bash.py denies
anyway run no gate. A directory known only at run time, a checkout without a
gate, or no checkout at all: nothing happens.

It fails open: a gate that outlives TIMEOUT is killed and the push goes through
with a message to the user. A crash, or the hook's own timeout in hooks.json,
lets the push through too.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Below the hook's 600 s timeout in hooks.json, so a hung gate is reported, not just killed. The slowest plain
# client gate run on record took 376 s.
TIMEOUT = int(os.environ.get("DK_PUSH_GATE_TIMEOUT", "540"))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_commands(cmd, cwd, guard):
    """(words from `git` on, the directory it runs in) for each git invocation in the command."""
    segs = guard.split(cmd)
    if segs is None:  # the guard's raw-string fallback, so an unsplittable command is still gated
        raw = guard.strip_heredocs(cmd)
        return [(tokens, guard.effective_cwd(raw, offset, cwd)) for offset, tokens in guard.segments(raw, "git")]
    return [(words, path) for _, words, path in guard.commands(segs, cwd)
            if words and os.path.basename(words[0]) == "git"]


def gated(rest, path, guard):
    """Whether `git push <rest>`, run in `path`, writes a branch the gate covers."""
    if any(level == "deny" for level, _ in guard.check_push(rest, path)):
        return False
    positional = []
    it = iter(rest)
    for a in it:
        if a in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
            next(it, None)
        elif a in ("--delete", "-d"):
            return False
        elif not a.startswith("-"):
            positional.append(a)
    branch = guard.current_branch(path)
    for spec in positional[1:] or ["HEAD"]:
        if spec.lstrip("+").startswith(":"):
            continue
        dst = guard.destination(spec)
        if not guard.FORCE_OK.match(guard.short_ref(branch if dst == "HEAD" and branch else dst)):
            return True
    return False


def push_roots(cmd, cwd, guard, stop):
    """The checkout roots of the command's gated pushes, in order, without repeats."""
    roots = []
    for tokens, path in git_commands(cmd, cwd, guard):
        args = tokens[1:]
        while args and args[0].startswith("-"):
            opt = args.pop(0)
            if opt == "-C" and args:
                path = guard.cd_into(path, args.pop(0))
            elif opt in ("-c", "--git-dir", "--work-tree", "--namespace") and args:
                args.pop(0)
        if path is None or args[:1] != ["push"] or not gated(args[1:], path, guard):
            continue
        root = (stop.git(path, "rev-parse", "--show-toplevel") or "").strip()
        if root and root not in roots:
            roots.append(root)
    return roots


def main():
    data = json.load(sys.stdin)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if "push" not in cmd:
        return
    guard = load("guard_bash", "guard-bash.py")
    stop = load("stop_gate", "stop-gate.py")
    cwd = data.get("cwd") or os.getcwd()
    notes = []
    for root in push_roots(cmd, cwd, guard, stop):
        gate = os.path.join(root, stop.GATE)
        if not os.access(gate, os.X_OK):
            continue
        failure, output = stop.run_gate(gate, root, TIMEOUT)
        tail = "\n".join(output.rstrip().splitlines()[-stop.TAIL_LINES:])[-stop.TAIL_CHARS:]
        head = f"dk-guard: {stop.GATE} in {root} {failure or 'passed'}"
        timed_out = bool(failure) and failure.startswith("timed out")
        guard.log({"session": data.get("session_id"), "cwd": cwd, "decision": "deny" if failure and not timed_out
                   else "allow", "reason": "push gate: " + head, "command": cmd[:500]})
        if timed_out:
            notes.append(f"{head}; the push goes through ungated. Last lines:\n{tail}")
        elif failure:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": f"{head}, so the push is blocked. Last lines:\n{tail}\n\n"
                                            "Fix the failure, commit, and push again."}}))
            return
    if notes:
        print(json.dumps({"systemMessage": "\n\n".join(notes)}))


if __name__ == "__main__":
    main()
