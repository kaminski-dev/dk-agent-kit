"""What tests/test_skills.py and tests/skills/test_*.py share: the dk plugin's skills and agents, their
frontmatter, and the list each file's checks append their problems to.

Stdlib only, so CI needs no PyYAML; the frontmatter here is flat key: value. Each test file loads this one
by path, since `python3 -I` keeps a script's folder off sys.path.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DK = ROOT / "plugins" / "dk"
# A dispatched subagent starts with a fresh context window; a fork carries the orchestrator's whole context (#114).
FRESH = "fresh context window"

errors = []


def frontmatter(path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        errors.append(f"{path.relative_to(ROOT)}: no frontmatter")
        return {}
    fields = {}
    for line in m.group(1).splitlines():
        if re.match(r"^[a-z][a-z-]*:", line):
            key, _, value = line.partition(":")
            fields[key] = value.strip().strip('"')
    return fields


skills = {p.parent.name: p for p in DK.glob("skills/*/SKILL.md")}
agents = {p.stem: p for p in DK.glob("agents/*.md")}
if not skills or not agents:
    sys.exit(f"FAIL no skills or agents found under {DK}")


def finish(label):
    for e in errors:
        print("FAIL", e)
    print(f"{label} {len(errors)} problems")
    sys.exit(1 if errors else 0)
