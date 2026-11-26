#!/usr/bin/env python3
"""Static checks for plugins/dk across skills: frontmatter, names, references, provenance.

The checks on one skill's prose are in tests/skills/test_<skill>.py.
"""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location(
    "_skills", pathlib.Path(__file__).resolve().parent / "skills" / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
ROOT, DK, FRESH, errors, skills, agents = lib.ROOT, lib.DK, lib.FRESH, lib.errors, lib.skills, lib.agents
frontmatter = lib.frontmatter

ORIGINAL = {"batch-pr", "issue-flow", "post-deploy-check", "verify"}  # written for the kit, no upstream row
CLIENT_REPOS = ("jetztbar", "clientdata", "kaminski-advies")  # their facts live in their own docs/agents/

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
    for client in CLIENT_REPOS:
        if client in text.lower():
            errors.append(f"{rel}: names the client repo {client}; skills stay repo-neutral")
    for stale in ("setup-matt-pocock-skills", "CONTEXT.md"):
        if stale in text and path.parent.name != "setup":  # setup renames and replaces them
            errors.append(f"{rel}: mentions {stale}")
    for bare in re.findall(r"Skill tool with [`\"]([a-z][a-z-]*)[`\"]", text):
        errors.append(f"{rel}: Skill tool call to bare {bare!r}; use dk:{bare}")

for name, file in (("research", "SKILL.md"), ("grilling", "SKILL.md"),
                   ("codebase-design", "DESIGN-IT-TWICE.md"), ("improve-codebase-architecture", "SKILL.md")):
    if FRESH not in (DK / "skills" / name / file).read_text():
        errors.append(f"skills/{name}/{file}: dispatches a subagent but does not start it with a {FRESH}")

for name in ("research", "improve-codebase-architecture"):
    if "never as a fork" not in (DK / "skills" / name / "SKILL.md").read_text():
        errors.append(f"skills/{name}: its subagent starts with a fresh context window, never as a fork")

readme = (ROOT / "README.md").read_text()
for block in re.findall(r"```mermaid\n(.*?)```", readme, re.S):
    planned = {i for ids in re.findall(r"^\s*class (\S+) planned$", block, re.M) for i in ids.split(",")}
    for node, label in re.findall(r"\b([A-Za-z_]\w*)[\[({]+\"([^\"]*)\"", block):
        for ref in re.findall(r"\bdk:([a-z][a-z-]*)", label):
            if node in planned and ref in skills:
                errors.append(f"README.md: dk:{ref} is built but its box '{node}' is still dashed (planned)")

upstream = (ROOT / "upstream" / "UPSTREAM.md").read_text()
for name in skills:
    if name not in ORIGINAL and not re.search(rf"^\| (skills/)?{re.escape(name)} \|", upstream, re.M):
        errors.append(f"skills/{name}: no row in upstream/UPSTREAM.md")

PIN = r"([0-9a-f]{7,40})(?:\.\.\w[\w./-]*)?"  # a section heading's end: its commit, then ..<branch> when it names one
dk_column_by_section_commit = {
    commit: " ".join(re.findall(r"^\| ([^|]+) \|", rows, re.M))
    for commit, rows in re.findall(rf"^## .*? @ {PIN}\n(.*?)(?=^## |\Z)", upstream, re.M | re.S)
}
marked = [("agents", n, p) for n, p in agents.items()] + [("skills", n, p) for n, p in skills.items()]
for kind, name, path in marked:
    for source, commit in re.findall(r"<!-- Adapted from (\S+(?: \S+)?)@([0-9a-f]+) ", path.read_text()):
        if not re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", dk_column_by_section_commit.get(commit, "")):
            errors.append(f"{kind}/{name}: adapted from {source}@{commit}, but upstream/UPSTREAM.md has no row for it in the section at that commit")

# A vendored script carries its marker as a comment; its row names it in the section at the marker's commit.
section_by_commit = dict(re.findall(rf"^## .*? @ {PIN}\n(.*?)(?=^## |\Z)", upstream, re.M | re.S))
for path in sorted(DK.glob("skills/*/**/*")):
    if not path.is_file() or path.suffix == ".md":
        continue
    dk_file = str(path.relative_to(DK))
    for source, commit, upstream_path in re.findall(r"^# Adapted from (\S+(?: \S+)?)@([0-9a-f]+) (\S+?), ",
                                                    path.read_text(errors="replace"), re.M):
        if not re.search(rf"^\| {re.escape(dk_file)} \| {re.escape(upstream_path)} \|", section_by_commit.get(commit, ""), re.M):
            errors.append(f"{dk_file}: adapted from {source}@{commit} {upstream_path}, but upstream/UPSTREAM.md has no "
                          "row for it in the section at that commit")

# The shape upstream/sync.sh parses (the format note at the top of UPSTREAM.md).
# sync.sh skips a section whose heading it cannot read and matches no file
# against a glob or a shorthand path, so either one hides upstream changes.
in_section, table_rows = False, 0
for n, line in enumerate(upstream.splitlines(), 1):
    where = f"upstream/UPSTREAM.md:{n}"
    if line.startswith("## "):
        in_section, table_rows = True, 0
        if not re.fullmatch(r"## [\w.-]+/[\w.-]+(?: [^()@]+)? \([^()]+\) @ " + PIN, line):
            errors.append(f"{where}: heading is not '## <owner>/<repo> [label] (<license>) @ <commit>[..<branch>]'")
        continue
    if not (in_section and line.startswith("|")):
        continue
    table_rows += 1
    if table_rows <= 2:  # header and separator
        continue
    paths = [p.strip().strip("`") for p in line.split("|")[2].split(",")]
    for i, path in enumerate(paths):
        if not path:
            errors.append(f"{where}: empty upstream path")
        elif re.search(r"[*?\[\]{}]", path):
            errors.append(f"{where}: glob in upstream path {path!r}; list each file")
        elif i and "/" in paths[0] and "/" not in path:
            errors.append(f"{where}: shorthand upstream path {path!r}; write it from the repo root")

# Each source in UPSTREAM.md keeps its license notice: a THIRD_PARTY row that links the repo and names
# the section's commit, its license and a license file that exists. A pin that moves takes the row along.
third_party = (ROOT / "THIRD_PARTY" / "README.md").read_text().splitlines()
for repo, license_name, commit in re.findall(rf"^## (\S+) .*?\(([^()]+)\) @ {PIN}$", upstream, re.M):
    row = next((r for r in third_party if re.search(rf"\(https://github\.com/{re.escape(repo)}[)/]", r)), None)
    if row is None:
        errors.append(f"THIRD_PARTY/README.md: no row links github.com/{repo}, a source in upstream/UPSTREAM.md")
        continue
    if f"`{commit}`" not in row:
        errors.append(f"THIRD_PARTY/README.md: the {repo} row does not name `{commit}`, its commit in upstream/UPSTREAM.md")
    if license_name not in row:
        errors.append(f"THIRD_PARTY/README.md: the {repo} row does not name its license, {license_name}")
    license_files = re.findall(r"\]\(([^()/]+\.LICENSE)\)", row)
    if not license_files or not all((ROOT / "THIRD_PARTY" / f).is_file() for f in license_files):
        errors.append(f"THIRD_PARTY/README.md: the {repo} row links no license file that exists")

# Each skill ships its own copy, since `python3 -I` keeps a script's folder off sys.path; the copies stay one.
copies = {}
for script in ("batch-pr/batch.py", "issue-flow/pr-wait", "implement-spec/preflight.py", "triage/ready.py",
               "../../dk-guard/bin/dk-comment-edit"):
    m = re.search(r"^def origin_repo\(\):\n(?:    .*\n)+", (DK / "skills" / script).read_text(), re.M)
    copies.setdefault(m.group(0) if m else None, []).append(script)
if len(copies) != 1 or None in copies:
    errors.append("skills: origin_repo() differs between " + " | ".join(", ".join(v) for v in copies.values()))
# The spec preflight reads blockers as dk:triage's ready list does, so the two blocker patterns stay one.
blocker_lines = {}
for script in ("implement-spec/preflight.py", "triage/ready.py"):
    lines = re.findall(r"^(?:BODY_BLOCKER|BLOCKER_REF) = .*$", (DK / "skills" / script).read_text(), re.M)
    blocker_lines.setdefault(tuple(lines) if len(lines) == 2 else None, []).append(script)
if len(blocker_lines) != 1 or None in blocker_lines:
    errors.append("skills: BODY_BLOCKER and BLOCKER_REF differ between " + " | ".join(", ".join(v) for v in blocker_lines.values()))
# dk-gc reads origin through its own git() helper, so only the pattern line is shared.
dkgc_pattern_line = re.search(r"^def slug_of\(root\):\n(?:    .*\n)*?(    m = re\.search\(.*\n)",
                      (ROOT / "plugins" / "dk-guard" / "bin" / "dk-gc").read_text(), re.M)
if not dkgc_pattern_line or not all(dkgc_pattern_line.group(1) in copy for copy in copies if copy):
    errors.append("dk-guard: dk-gc's slug_of() reads origin with another pattern than the skills' origin_repo()")

# On an already-closed issue, `gh issue close --comment` drops the comment and exits 0 (#117).
trackers = [ROOT / "docs/agents/issue-tracker.md", DK / "skills/setup/issue-tracker.md",
            DK / "evals/_fixture/app/docs/agents/issue-tracker.md", DK / "evals/_fixture/api/docs/agents/issue-tracker.md"]
for path in trackers:
    rel, text = path.relative_to(ROOT), path.read_text()
    close = re.search(r"^- \*\*Close\*\*: .*", text, re.M)
    close = close.group(0) if close else ""
    comment_at, close_at = close.find("`gh issue comment N"), close.find("`gh issue close N`")
    if re.search(r"`gh issue close [^`]*--comment", text) or not 0 <= comment_at < close_at:
        errors.append(f"{rel}: Close must comment with `gh issue comment N` first, then `gh issue close N`, "
                      "never `gh issue close --comment`")
    blocking = re.search(r"^- \*\*Blocking\*\*: .*", text, re.M)
    if blocking and not all(s in blocking.group(0) for s in (
            "`gh issue create --blocked-by", "`gh issue edit <child> --add-blocked-by <blocker>`", "2.94",
            "--method POST")):
        errors.append(f"{rel}: Blocking must use `gh issue create --blocked-by` and `gh issue edit <child> "
                      "--add-blocked-by <blocker>` (gh 2.94+), with the API POST as the older-gh fallback")

# The skills a subagent's brief names load on every implementer, so each main file keeps under its word cap, counted
# as `wc -w` counts; a branch only some readers reach moves to a reference file beside it (#179).
WORD_CAPS = {"issue-flow": 1500, "tdd": 650, "verify": 1700, "pr": 1350, "code-review": 3100}
for name, cap in WORD_CAPS.items():
    words = len(skills[name].read_text().split())
    if words > cap:
        errors.append(f"skills/{name}/SKILL.md: {words} words, over its cap of {cap}; move a branch only some "
                      "readers reach to a reference file behind a pointer")

lib.finish(f"{len(skills)} skills, {len(agents)} agents,")
