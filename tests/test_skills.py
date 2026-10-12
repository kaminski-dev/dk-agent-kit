#!/usr/bin/env python3
"""Static checks for plugins/dk: frontmatter, names, references, provenance.

Stdlib only, so CI needs no PyYAML; the frontmatter here is flat key: value.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DK = ROOT / "plugins" / "dk"
ORIGINAL = {"issue-flow", "post-deploy-check"}  # written for the kit, no upstream row

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

for name, path in skills.items():
    fm = frontmatter(path)
    if fm.get("name") != name:
        errors.append(f"skills/{name}: frontmatter name {fm.get('name')!r} != folder")
    desc = fm.get("description", "")
    if not desc:
        errors.append(f"skills/{name}: missing description")
    if len(desc) > 1024:
        errors.append(f"skills/{name}: description is {len(desc)} chars (> 1024)")
    if fm.get("disable-model-invocation") not in (None, "true"):
        errors.append(f"skills/{name}: disable-model-invocation must be true or absent")

for name, path in agents.items():
    fm = frontmatter(path)
    if fm.get("name") != name:
        errors.append(f"agents/{name}: frontmatter name {fm.get('name')!r} != file name")
    if not fm.get("description"):
        errors.append(f"agents/{name}: missing description")

user_invoked = {n for n, p in skills.items() if frontmatter(p).get("disable-model-invocation") == "true"}
for path in sorted(DK.rglob("*.md")):
    text = path.read_text()
    rel = path.relative_to(ROOT)
    for ref in sorted(set(re.findall(r"\bdk:([a-z][a-z-]*)", text))):
        if ref not in skills and ref not in agents:
            errors.append(f"{rel}: dk:{ref} names no skill or agent")
    for ref in re.findall(r"Skill tool with [`\"]dk:([a-z-]+)", text):
        if ref in user_invoked:
            errors.append(f"{rel}: calls user-invoked dk:{ref} through the Skill tool, which cannot reach it")
    for stale in ("setup-matt-pocock-skills", "CONTEXT.md"):
        if stale in text and path.parent.name != "setup":  # setup renames and replaces them
            errors.append(f"{rel}: mentions {stale}")
    for bare in re.findall(r"Skill tool with [`\"]([a-z][a-z-]*)[`\"]", text):
        errors.append(f"{rel}: Skill tool call to bare {bare!r}; use dk:{bare}")

upstream = (ROOT / "upstream" / "UPSTREAM.md").read_text()
for name in skills:
    if name not in ORIGINAL and not re.search(rf"^\| (skills/)?{re.escape(name)} \|", upstream, re.M):
        errors.append(f"skills/{name}: no row in upstream/UPSTREAM.md")

for e in errors:
    print("FAIL", e)
print(f"{len(skills)} skills, {len(agents)} agents, {len(errors)} problems")
sys.exit(1 if errors else 0)
