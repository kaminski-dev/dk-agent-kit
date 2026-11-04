#!/usr/bin/env python3
"""Replays past tool calls through a dk-guard hook to spot false positives.

Usage: replay_history.py <commands.jsonl>   (lines of {"cwd": ..., "cmd": ..., "background": true|false})
       replay_history.py --agent <agent_calls.jsonl>   (lines of {"tool_input": {...}} from Agent tool_use blocks)
The first replays Bash commands through guard-bash's decide(); the second replays Agent calls through
fork-guard and lists each denial's description with what the fork was handed.
Extract the file from ~/.claude/projects transcripts; it stays out of this repo.
Implicit pushes resolve against each checkout's branch today, not at the time.
"""
import collections
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(script):
    spec = importlib.util.spec_from_file_location(
        script.replace("-", "_"), os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", script + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay_bash(path):
    guard = load("guard-bash")
    counts, samples = collections.Counter(), collections.defaultdict(collections.Counter)
    for line in open(path):
        row = json.loads(line)
        level, reason = guard.decide(row["cmd"], row.get("cwd") or os.getcwd(), row.get("background", False))
        counts[level] += 1
        if level != "allow":
            samples[(level, reason[:60])][row["cmd"].splitlines()[0][:150]] += 1

    print(dict(counts))
    for (level, reason), cmds in sorted(samples.items()):
        print(f"\n[{level}] {reason}… ({sum(cmds.values())})")
        for cmd, n in cmds.most_common(int(os.environ.get("SAMPLES", "6"))):
            print(f"  {n:4} {cmd}")


def replay_agent(path):
    guard = load("fork-guard")
    counts, denials = collections.Counter(), []
    for line in open(path):
        tool_input = json.loads(line).get("tool_input")
        kind = "fork" if isinstance(tool_input, dict) and tool_input.get("subagent_type") == "fork" else "other"
        denied = guard.decide(tool_input) is not None
        counts[f"{kind} {'deny' if denied else 'allow'}"] += 1
        if denied:
            denials.append((str(tool_input.get("description")), " and ".join(guard.handovers(tool_input))))

    print(dict(sorted(counts.items())))
    for description, handed in denials:
        print(f"  deny  {description[:80]}  ({handed})")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--agent"]:
        replay_agent(sys.argv[2])
    else:
        replay_bash(sys.argv[1])
