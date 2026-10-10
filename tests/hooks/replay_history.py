#!/usr/bin/env python3
"""Replays past Bash commands through guard-bash's decide() to spot false positives.

Usage: replay_history.py <commands.jsonl>   (lines of {"cwd": ..., "cmd": ...})
Extract the file from ~/.claude/projects transcripts; it stays out of this repo.
Implicit pushes resolve against each checkout's branch today, not at the time.
"""
import collections
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "guard", os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "guard-bash.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

counts, samples = collections.Counter(), collections.defaultdict(collections.Counter)
for line in open(sys.argv[1]):
    row = json.loads(line)
    level, reason = guard.decide(row["cmd"], row.get("cwd") or os.getcwd())
    counts[level] += 1
    if level != "allow":
        samples[(level, reason[:60])][row["cmd"].splitlines()[0][:150]] += 1

print(dict(counts))
for (level, reason), cmds in sorted(samples.items()):
    print(f"\n[{level}] {reason}… ({sum(cmds.values())})")
    for cmd, n in cmds.most_common(int(os.environ.get("SAMPLES", "6"))):
        print(f"  {n:4} {cmd}")
