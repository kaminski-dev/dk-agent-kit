#!/usr/bin/env python3
"""dk-guard PreToolUse hook for Bash: runs the pushed checkout's .claude/gate.sh before a git push.

Agents work in a linked worktree and commit as they go, so the push is where
the gate runs. For each `git push` in the command it takes the directory the
push runs in (the `cd` or `git -C` target, resolved as guard-bash.py resolves
it) and runs that checkout's executable .claude/gate.sh from its root through
gate.py, the code behind `dk-gate`: when the gate already passed on the same
tree, by hand or at an earlier push, the pass is reused and the gate does not
run. A failing gate denies the push with the gate's last lines; a passing or
cached gate is silent.

Pushes of verify-assets/*, branch deletes and pushes guard-bash.py denies
anyway run no gate. A checkout without a gate, or no checkout at all: nothing
happens. A directory known only at run time (`cd "$(…)" && git push`, or `$WT`
when the call does not set it or may have switched the checkout's branch), or
missing before the call, runs no gate either, and the agent is told so.

The gate waits for any other run on the same checkout, then takes one of the
machine's gate slots (gate.py); a hand run in flight on the checkout is waited
for and its pass on the same tree reused. The waits count against TIMEOUT.
When they outlast DK_GATE_WAIT, or leave the gate less than the seconds its
last pass took once the tree is hashed, the gate does not run and the push is
denied with a message that says which of the three happened and to push
again.

It fails open otherwise: a gate that outlives TIMEOUT is killed and the push
goes through with a message to the user. A crash, or the hook's own timeout in
hooks.json, lets the push through too.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Below the hook's 600 s timeout in hooks.json, so a hung gate is reported, not just killed.
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
        return list(guard.raw_git(raw, cwd))
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


def push_roots(cmd, cwd, guard, gate):
    """(the checkout roots of the command's gated pushes, in order, without repeats; whether a gated push runs in a
    directory known only at run time, or one that does not exist yet)."""
    roots, unknown = [], False
    for tokens, path in git_commands(cmd, cwd, guard):
        args, path = guard.git_subcommand(tokens, path)
        if args[:1] != ["push"] or not gated(args[1:], path, guard):
            continue
        if path is None or not os.path.isdir(path):
            unknown = True
            continue
        root = gate.toplevel(path)
        if root and root not in roots:
            roots.append(root)
    return roots, unknown


def main():
    data = json.load(sys.stdin)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if "push" not in cmd:
        return
    guard = load("guard_bash", "guard-bash.py")
    gate = load("gate", "gate.py")
    cwd = data.get("cwd") or os.getcwd()
    notes = []
    roots, unknown = push_roots(cmd, cwd, guard, gate)
    for root in roots:
        if not os.access(os.path.join(root, gate.GATE), os.X_OK):
            continue
        status, output, entry = gate.check(root, TIMEOUT)
        if status == gate.BUSY:
            head = f"dk-guard: {gate.why_busy(root, entry)}"
            again = {gate.SLOTS: "push again in a minute, or run dk-gate there first, which waits for a slot.",
                     gate.CHECKOUT: "push again when that run ends; its pass on this same tree is reused.",
                     gate.LATE: "push again, or run dk-gate there first, which has no deadline, and push on its "
                                "pass."}[entry["cause"]]
            guard.log({"session": data.get("session_id"), "cwd": cwd, "decision": "deny",
                       "reason": "push gate: " + head, "command": cmd[:500]})
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": f"{head} and the push is blocked. Nothing is wrong with the change: "
                                            + again}}))
            return
        failure = None if status.startswith("passed") or status == "cached" else status
        tail = gate.tail(output)
        head = f"dk-guard: {gate.GATE} in {root} " + ("passed on this tree before (cached)" if status == "cached"
                                                        else status)
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
    out = {}
    if notes:
        out["systemMessage"] = "\n\n".join(notes)
    if unknown:
        out["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "additionalContext": f"dk-guard: {gate.GATE} did not run for this push: its directory is known only at "
                                 "run time, or does not exist before the call. Push in a call of its own with the "
                                 "worktree path written literally (`cd <worktree> && git push`), or run the gate "
                                 "there by hand."}
    if out:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
