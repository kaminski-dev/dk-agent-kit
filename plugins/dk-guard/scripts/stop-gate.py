#!/usr/bin/env python3
"""dk-guard Stop hook: runs the repo's .claude/gate.sh before a turn ends.

When the tree has uncommitted changes and the repo ships an executable
.claude/gate.sh (the fast static gate: lint, typecheck, unit tests on what
changed), the hook runs it from the repo root. A failing gate blocks the stop
and hands the agent the last lines of its output. A passing gate is silent.

A stop that follows a block (stop_hook_active) is never blocked again: a gate
the agent cannot fix would loop it, so the user gets the failure instead.
Runtime proof is not this hook's job; that stays with the repo's verify recipe.
"""
import json
import os
import signal
import subprocess
import sys

GATE = os.path.join(".claude", "gate.sh")
TAIL_LINES, TAIL_CHARS = 40, 4000
# Below the hook's 300 s timeout in hooks.json, so a hung gate is reported, not just killed.
TIMEOUT = int(os.environ.get("DK_GATE_TIMEOUT", "240"))


def git(cwd, *args):
    try:
        out = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def run_gate(gate, root):
    """Run the gate in its own process group; return (failure or None, combined output)."""
    try:
        proc = subprocess.Popen([gate], cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        return f"could not run: {e.strerror}", ""
    try:
        out, _ = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # the gate's test runners go with it
        out, _ = proc.communicate()
        failure = f"timed out after {TIMEOUT} s"
    else:
        failure = f"failed (exit {proc.returncode})" if proc.returncode else None
    return failure, out.decode("utf-8", errors="replace")


def main():
    data = json.load(sys.stdin)
    cwd = data.get("cwd") or os.getcwd()
    root = (git(cwd, "rev-parse", "--show-toplevel") or "").strip()
    gate = os.path.join(root, GATE)
    if not root or not os.access(gate, os.X_OK) or not git(root, "status", "--porcelain"):
        return
    failure, output = run_gate(gate, root)
    if not failure:
        return
    tail = "\n".join(output.rstrip().splitlines()[-TAIL_LINES:])[-TAIL_CHARS:]
    head = f"dk-guard: {GATE} {failure}"
    if data.get("stop_hook_active"):
        # The agent already had one try after a block; a second block could loop.
        print(json.dumps({"systemMessage": f"{head}; the turn ends anyway. Last lines:\n{tail}"}))
    else:
        print(json.dumps({"decision": "block",
                          "reason": f"{head}. Last lines:\n{tail}\n\nFix the failure before you finish."}))


if __name__ == "__main__":
    main()
