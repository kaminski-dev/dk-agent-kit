#!/usr/bin/env python3
"""Static checks for plugins/dk: frontmatter, names, references, provenance.

Stdlib only, so CI needs no PyYAML; the frontmatter here is flat key: value.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DK = ROOT / "plugins" / "dk"
ORIGINAL = {"batch-pr", "issue-flow", "post-deploy-check", "verify"}  # written for the kit, no upstream row
CLIENT_REPOS = ("jetztbar", "clientdata", "kaminski-advies")  # their facts live in their own docs/agents/

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
    for client in CLIENT_REPOS:
        if client in text.lower():
            errors.append(f"{rel}: names the client repo {client}; skills stay repo-neutral")
    for stale in ("setup-matt-pocock-skills", "CONTEXT.md"):
        if stale in text and path.parent.name != "setup":  # setup renames and replaces them
            errors.append(f"{rel}: mentions {stale}")
    for bare in re.findall(r"Skill tool with [`\"]([a-z][a-z-]*)[`\"]", text):
        errors.append(f"{rel}: Skill tool call to bare {bare!r}; use dk:{bare}")

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
review = skills["code-review"].read_text()
for ref in sorted(set(re.findall(r'subagent_type: "dk:([a-z][a-z-]*)"', review))):
    if ref not in agents:
        continue  # the reference check above reports it
    tools = frontmatter(agents[ref]).get("tools")
    if tools is None:
        errors.append(f"agents/{ref}: code-review spawns it, so it needs a tools list (absent inherits Edit and Write)")
    elif WRITE_TOOLS & {t.strip() for t in tools.split(",")}:
        errors.append(f"agents/{ref}: code-review spawns it, so its tools must exclude {sorted(WRITE_TOOLS)}")

flow = skills["issue-flow"].read_text()
bot = re.search(r"^\*\*Review bot\.\*\*.*?(?=^## )", flow, re.M | re.S)
bot = bot.group(0) if bot else ""
for what, pattern in (
    ("the background wait", r"run_in_background"),
    ("the 20-minute give-up", r"20 minutes"),
    ("the head-SHA filter", r"headRefOid.*commit_id|commit_id.*headRefOid"),
    ("the inline-comment endpoint", r"repos/\S+/pulls/\S+/comments"),
    ("the review-body endpoint", r"repos/\S+/pulls/\S+/reviews/\S+"),
):
    if not re.search(pattern, bot, re.S):
        errors.append(f"skills/issue-flow: its **Review bot.** paragraph in step 6 does not name {what}")
if not re.search(r"pulls/\S+/comments\" --jq '[^']*in_reply_to_id == null", bot):
    errors.append("skills/issue-flow: item 2's inline query must keep the bot's thread starters only (in_reply_to_id == null)")
if "wait-review.py" not in bot:
    errors.append("skills/issue-flow: its **Review bot.** paragraph must start wait-review.py, whose cases tests/test_wait_review.py runs")
step7 = re.search(r"^## 7\..*?(?=^## )", flow, re.M | re.S)
step7 = step7.group(0) if step7 else ""
if not re.search(r"<PR>-<review>-<\w+>", step7) or "one at a time" not in step7:
    errors.append("skills/issue-flow: step 7's push route needs a worktree key unique per finding, "
                  "body findings of one review included, and works findings one at a time")

if "PR comment" not in step7:
    errors.append("skills/issue-flow: step 7's push route must record a review-body finding's fix in a PR comment; it has no thread")
skipped = re.search(r"^ *Either way, a skipped .*$", step7, re.M)
skipped = skipped.group(0) if skipped else ""
if not re.search(r"skipped inline finding.*thread", skipped) or not re.search(
        r"skipped review-body finding.*PR comment.*file.*lines", skipped):
    errors.append("skills/issue-flow: step 7 must send a skipped inline finding's reason to its thread, "
                  "and a skipped review-body finding's to a PR comment naming its file and lines")

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

dk_column_by_section_commit = {
    commit: " ".join(re.findall(r"^\| ([^|]+) \|", rows, re.M))
    for commit, rows in re.findall(r"^## .*? @ ([0-9a-f]+)\n(.*?)(?=^## |\Z)", upstream, re.M | re.S)
}
marked = [("agents", n, p) for n, p in agents.items()] + [("skills", n, p) for n, p in skills.items()]
for kind, name, path in marked:
    for source, commit in re.findall(r"<!-- Adapted from (\S+(?: \S+)?)@([0-9a-f]+) ", path.read_text()):
        if not re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", dk_column_by_section_commit.get(commit, "")):
            errors.append(f"{kind}/{name}: adapted from {source}@{commit}, but upstream/UPSTREAM.md has no row for it in the section at that commit")

# The shape upstream/sync.sh parses (the format note at the top of UPSTREAM.md).
# sync.sh skips a section whose heading it cannot read and matches no file
# against a glob or a shorthand path, so either one hides upstream changes.
in_section, table_rows = False, 0
for n, line in enumerate(upstream.splitlines(), 1):
    where = f"upstream/UPSTREAM.md:{n}"
    if line.startswith("## "):
        in_section, table_rows = True, 0
        if not re.fullmatch(r"## [\w.-]+/[\w.-]+(?: [^()@]+)? \([^()]+\) @ [0-9a-f]{7,40}", line):
            errors.append(f"{where}: heading is not '## <owner>/<repo> [label] (<license>) @ <commit>'")
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

# issue-flow's worktree, rebase and PR commands name the base (step 2), which a repo's workflow.md can set,
# so a repo without pre-main gets its own branch and no needless ask to restore pre-main.
for n, line in enumerate(skills["issue-flow"].read_text().splitlines(), 1):
    if re.search(r"git ls-remote|git worktree add|gh pr create|^Rebase onto|is missing:", line) and "pre-main" in line:
        errors.append(f"skills/issue-flow/SKILL.md:{n}: names pre-main where the base belongs")
# Steps 6 and 7 describe the pre-main batch; step 2 says which parts lapse when the base is main.
step2 = re.search(r"^## 2\..*?(?=^## 3\.)", skills["issue-flow"].read_text(), re.M | re.S)
if not step2 or not re.search(r"When the base is `main`, there is no batch PR: `Closes #N` closes the issue on merge, "
                              r"and step 6's batch-PR note and step 7's batch-review bullet do not apply\.", step2.group(0)):
    errors.append("skills/issue-flow/SKILL.md: step 2 does not say what lapses when the base is main")

for e in errors:
    print("FAIL", e)
print(f"{len(skills)} skills, {len(agents)} agents, {len(errors)} problems")
sys.exit(1 if errors else 0)
