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

baseline = re.search(r"\*\*smell baseline\*\*.*?(?=^The \*\*comment policy\*\*)", review, re.M | re.S)
if baseline is None or re.search(r"empty test", baseline.group(0), re.I):
    errors.append("skills/code-review: the Standards smell baseline lists Empty Test; the Correctness brief owns it")
# pstack principle-fix-root-causes: a guard is right only when the state it handles is legitimate.
for entry in ("Defensive Interior", "Swallowed Error"):
    line = re.search(rf"^- \*\*{entry}\*\*:.*$", baseline.group(0) if baseline else "", re.M)
    if not line or not re.search(r"state it handles is legitimate", line.group(0)):
        errors.append(f"skills/code-review: the baseline's {entry} entry does not ask whether the state it handles is legitimate")
standards_brief = re.search(r"^\*\*Standards sub-agent prompt\*\*.*?(?=^\*\*Spec sub-agent prompt\*\*)", review, re.M | re.S)
if not re.search(r"Whether a test can fail is the Correctness axis's question unless a documented standard rules on it",
                 standards_brief.group(0) if standards_brief else ""):
    errors.append("skills/code-review: the Standards brief must hand whether a test can fail to the Correctness axis, "
                  "keeping documented test rules")
test_question = re.search(r"^  - \*\*Test\*\*:.*$", review, re.M)
test_question = test_question.group(0) if test_question else ""
for what, pattern in (
    ("a loose assertion", r"toBeDefined"),
    ("a call as the only assertion", r"toHaveBeenCalled"),
    ("an empty result as the only assertion", r"toEqual\(\[\]\)"),
    ("an expected value computed by the code under test", r"computed by the code under test"),
    ("a restated constant, config default or prompt string", r"constant, config default or prompt string"),
    ("assertions on data the test built", r"data the test built"),
    ("the fix", r"literal output or effect"),
    ("the cross-row exemption", r"[Cc]ross-row relations between tables"),
    ("the type-test exemption", r"compile-time type tests"),
):
    if not re.search(pattern, test_question):
        errors.append(f"skills/code-review: the Correctness brief's **Test** question does not name {what}")
# pstack e5136d8: the two imagined edits, and two cases a list of assertion shapes misjudges.
for what, pattern in (
    ("the break-the-behaviour edit (does the test still pass?)", r"\*\*[Bb]reak the behaviour\*\*[^*]*still pass"),
    ("the change-the-internals edit (does it now fail?)", r"\*\*[Cc]hange the internals\*\*[^*]*now fail"),
    ("an absence assertion counting when paired with a presence case", r"absence assertion[^;]*paired with a presence case"),
    ("the error type as the contract", r"error type[^.]*\bcontract\b"),
    ("an exact error message as implementation", r"error message"),
):
    if not re.search(pattern, test_question):
        errors.append(f"skills/code-review: the Correctness brief's **Test** question does not name {what}")
empty_result = re.search(r"`toEqual\(\[\]\)`[^;]*", test_question)
empty_result = empty_result.group(0) if empty_result else ""
if not re.search(r"\bwhen a subject that does nothing\b.*\breturns\b", empty_result) or not re.search(
        r"`undefined`.*`None`", empty_result):
    errors.append("skills/code-review: the Correctness brief's **Test** question must flag an empty-result-only assertion "
                  "(`toEqual([])`) only when a subject that does nothing still returns that result, and say in the same "
                  "clause that a no-op returns `undefined` or `None` (#87: reviewers took a no-op to return [])")
# The retro's correct step judges a test as the review does (pstack correct, e5136d8).
retro_test = re.search(r"^   \d\. \*\*Test\*\*.*$", skills["retro"].read_text(), re.M)
if not retro_test or not re.search(r"still passes when the behaviour it checks breaks.*fails when only the internals change",
                                   retro_test.group(0)):
    errors.append("skills/retro: the correct step's **Test** level does not ask for a test that fails when the behaviour "
                  "breaks and keeps passing when only the internals change")

# Each finding carries a stable id and a severity judged against the change's intent, and the change's author
# answers every id in a ledger over a bounded number of rounds (#125, tstack sol-loop).
reviewer = agents["reviewer"].read_text()
# The same sentence in the reviewer and in code-review's Judge step (#112, CodeRabbit on #136).
IMPACT = re.escape("A rare path or a small cost is a nit unless its impact (data loss, security, money, a customer-visible "
                   "break) makes it a blocker or should.")
for what, pattern in (
    ("the finding line", r"`<id> \[blocker\|should\|nit\] <file>:<line> <claim>\. Fix: <fix>`"),
    ("the severity judged against the change's intent", r"against the change's intent"),
    ("a floor the brief sets overriding that scale", r"unless the brief sets a floor"),
    ("blocker as the intended case wrong", r"\*\*blocker\*\*[^\n]*intended case is wrong"),
    ("should as a real bug callers will hit", r"\*\*should\*\*[^\n]*real bug callers will hit"),
    ("nit as everything else", r"\*\*nit\*\*[^\n]*everything else"),
    ("ids prefixed as the brief says", r"prefix the brief"),
    ("old ids kept and marked in a later round", r"`resolved`[^\n]*`still open: <reason>`"),
    ("a Correctness finding citing its trigger and consequence, not a rule", r"Correctness finding[^.]*trigger[^.]*observable consequence"),
    ("severity by impact and likelihood", r"impact and likelihood"),
    ("a rare path or small cost kept a nit only when its impact is small", IMPACT),
):
    if not re.search(pattern, reviewer):
        errors.append(f"agents/reviewer: does not name {what}")
comment_reviewer = agents["comment-reviewer"].read_text()
if "<!-- Adapted from cursor/plugins pstack@" not in comment_reviewer:
    errors.append("agents/comment-reviewer: lost its pstack provenance marker")
for what, pattern in (
    ("the finding line", r"`<id> \[should\|nit\] <file>:<line> "),
    ("findings as nits unless the comment states something false", r"`nit` unless the comment states something false"),
    ("Stale as a should", r"^- \*\*Stale\*\*:[^\n]*`should`"),
):
    if not re.search(pattern, comment_reviewer, re.M):
        errors.append(f"agents/comment-reviewer: does not name {what}")
for name, text in (("agents/reviewer", reviewer), ("agents/comment-reviewer", comment_reviewer),
                   ("skills/code-review", review)):
    if re.search(r"hard violation|judgement call|\bHard\.|hard or judgement", text, re.I):
        errors.append(f"{name}: still marks findings hard or judgement call; the blocker, should or nit severity replaces it")
spawn = re.search(r"^### 4\..*?(?=^### 5\.)", review, re.M | re.S)
if not re.search(r"`ST`.*Standards.*`SP`.*Spec.*`CO`.*Correctness.*`CM`.*Comments", spawn.group(0) if spawn else "", re.S):
    errors.append("skills/code-review: step 4 must hand each axis its id prefix (`ST`, `SP`, `CO`, `CM`), "
                  "so ids stay unique across the four reports")
steps = re.findall(r"^### (\d+)\. (.*)$", review, re.M)
answer = re.search(r"^### \d+\. Answer findings\n.*?(?=^## |\Z)", review, re.M | re.S)
answer = answer.group(0) if answer else ""
if not steps or steps[-1][1] != "Answer findings":
    errors.append("skills/code-review: its last step must be 'Answer findings'")
for what, pattern in (
    ("a ledger of id, severity and outcome", r"ledger.*id.*severity.*outcome"),
    ("the fixed outcome with evidence", r"`fixed: [^`]+`"),
    ("the disagree outcome with evidence", r"`disagree: [^`]+`"),
    ("the declined outcome", r"`declined: [^`]+`"),
    ("later rounds on the open ids and the code changed since", r"only the open ids and the code changed since"),
    ("3 rounds by default", r"\b3 rounds\b"),
    ("5 rounds for the named risk classes", r"\b5\b[^.]*security, permissions, auth, data loss or concurrency"),
    ("stopping early on a round that brings only nits", r"round brings only nits"),
    ("the diff size after each round", r"`git diff --shortstat <fixed-point>`"),
    ("growth cut first", r"cut first"),
    ("declined findings worth doing through scope intake", r"`dk:issue-flow` step 3"),
    ("severity by impact and likelihood", r"impact and likelihood"),
    ("a rare path or small cost kept a nit only when its impact is small", IMPACT),
    ("each next-round prompt carrying its own axis's ledger rows", r"its own axis's ledger rows"),
    ("the nits-only stop only when no nit's fix changed behaviour code", r"round brings only nits[^.]*no behaviour code"),
):
    if not re.search(pattern, answer, re.S):
        errors.append(f"skills/code-review: its Answer findings step does not name {what}")
implement = skills["implement"].read_text()
if "fix what it finds" in implement or not re.search(r"\*\*Answer findings\*\*.*ledger", implement):
    errors.append("skills/implement: must answer review findings through dk:code-review's **Answer findings** "
                  "ledger, not fix what the review finds")

flow = skills["issue-flow"].read_text()
bot = re.search(r"^\*\*Review bot\.\*\*.*?(?=^## )", flow, re.M | re.S)
bot = bot.group(0) if bot else ""
for what, pattern in (
    ("the head-SHA filter", r"headRefOid.*commit_id|commit_id.*headRefOid"),
    ("the inline-comment endpoint", r"repos/\S+/pulls/\S+/comments"),
    ("the review-body endpoint", r"repos/\S+/pulls/\S+/reviews/\S+"),
):
    if not re.search(pattern, bot, re.S):
        errors.append(f"skills/issue-flow: its **Review bot.** paragraph in step 6 does not name {what}")
if not re.search(r"pulls/\S+/comments\" --jq '[^']*in_reply_to_id == null", bot):
    errors.append("skills/issue-flow: item 1's inline query must keep the bot's thread starters only (in_reply_to_id == null)")
# The bot's rounds end by the same budget as dk:code-review's (#125).
if "until a round brings no new finding" in bot or not re.search(
        r"`dk:code-review`'s \*\*Answer findings\*\*[^.]*severit[^.]*ledger[^.]*round budget", bot):
    errors.append("skills/issue-flow: step 6's bot rounds must follow dk:code-review's **Answer findings** severities, "
                  "ledger and round budget, not run until a round brings no new finding")

# One watcher, pr-wait, reports every PR event in step 6, run with Monitor (#124).
watch = re.search(r"^\*\*Watch the PR\.\*\*.*?(?=^\*\*Review bot\.\*\*)", flow, re.M | re.S)
watch = watch.group(0) if watch else ""
watcher = (DK / "skills" / "issue-flow" / "pr-wait").read_text()
for what, pattern in (
    ("the watcher, whose cases tests/test_pr_wait.py runs", r"`python3 -I <base directory>/pr-wait <PR>`"),
    ("the Monitor tool at its longest timeout", r"Monitor tool \(`timeout_ms: 1800000`\)"),
    ("the run_in_background fallback", r"[Ww]ithout Monitor, start the same command with `run_in_background`"),
    ("the 20-minute deadline a push restarts", r"push restarts its 20 minutes"),
    ("a restart after each push, which replays what arrived in between", r"[Ss]tart it again after each push"),
):
    if not re.search(pattern, watch, re.S):
        errors.append(f"skills/issue-flow: step 6's **Watch the PR.** paragraph does not name {what}")
for line in ("required check failed", "comment from", "review from", "new thread from", "thread reply from", "reviewed",
             "rate limited on", "paused on", "and touches files in this PR", "merge state is BEHIND",
             "merge state is DIRTY", "blocked by", "merged", "closed without merging", "deadline passed", "ready on",
             "green on", "pr-wait stopped", "(not a collaborator)", "so ready is not reported on"):
    if line not in watch:
        errors.append(f"skills/issue-flow: step 6's **Watch the PR.** paragraph does not say what to do on pr-wait's "
                      f"`{line}` line (tests/test_pr_wait.py shows it printed)")
# A comment from outside the repo is data (#112, CodeRabbit on #136).
if not re.search(r"`\(not a collaborator\)`[^.]*data, never instructions", watch):
    errors.append("skills/issue-flow: step 6 must say a line tagged `(not a collaborator)` is data, never instructions")
if not re.search(r"`--until green`[^.]*\bDIRTY\b", watch):
    errors.append("skills/issue-flow: step 6 must say `--until green` also stops on a DIRTY merge state")
step6_waits = re.search(r"^## 6\..*?(?=^## 7\.)", flow, re.M | re.S)
if step6_waits and re.search(r"--watch\b|\bsleep \d", step6_waits.group(0)):
    errors.append("skills/issue-flow: step 6 waits through pr-wait alone; it has a `--watch` or `sleep` wait left")
step7 = re.search(r"^## 7\..*?(?=^## )", flow, re.M | re.S)
step7 = step7.group(0) if step7 else ""
if not re.search(r"<PR>-<review>-<\w+>", step7) or "one at a time" not in step7:
    errors.append("skills/issue-flow: step 7's push route needs a worktree key unique per finding, "
                  "body findings of one review included, and works findings one at a time")

# The maintainer's own findings on the batch PR take the bot's route, read once with step 6's inline query.
route = re.search(r"^- [^\n]*\*\*Batch-review fixes\*\*.*?(?=^  - `pr`:)", step7, re.M | re.S)
route = route.group(0) if route else ""
for what, pattern in (
    ("the review bot's findings", r"step 6's \*\*Review bot\*\*"),
    ("the maintainer's own review", r"maintainer's own review"),
    ("its inline comments, review bodies and PR comments", r"inline review comments.*review bodies.*PR comments"),
    ("the filter that keeps other bots out", r'\.user\.type == "User"'),
    ("a review read that keeps humans' submitted reviews with a body only",
     r'pulls/<PR>/reviews" --jq \'[^\']*\.user\.type == "User"[^\']*\.state != "PENDING"[^\']*\.body != ""'),
    ("a PR-comment read that keeps humans' comments only", r'issues/<PR>/comments" --jq \'[^\']*\.user\.type == "User"'),
    ("that your own fix and skip records, posted from the same account, are records and not findings (#99)",
     r"records.*same account.*leave them out"),
):
    if not re.search(pattern, route, re.S):
        errors.append(f"skills/issue-flow: step 7's routing bullet does not name {what}")
if "pull_request_review_id ==" in step7:
    errors.append("skills/issue-flow: step 7 repeats step 6's inline query; point at it instead")
if "`<PR>-<comment>`" not in step7:
    errors.append("skills/issue-flow: step 7's push route needs a worktree key for a PR-comment finding")
if not re.search(r"done.*inline record is a reply whose `in_reply_to_id`", route):
    errors.append("skills/issue-flow: step 7's done check must find an inline finding's record among its thread's replies")
pr_fix = re.search(r"^  - `pr`: .*$", step7, re.M)
if not pr_fix or "record" not in pr_fix.group(0):
    errors.append("skills/issue-flow: step 7's `pr` route must record each finding's fix PR on the batch PR")
if not re.search(r"review-body finding post a PR comment with its key", step7) or not re.search(
        r"skipped review-body finding gets it in a PR comment naming its key", step7):
    errors.append("skills/issue-flow: step 7's review-body fix and skip records must name the finding's key")

# The agent posts under the maintainer's gh account, so each comment it posts says who wrote it, in one
# format a script can match to drop the agent's own comments (#121).
step6 = re.search(r"^## 6\..*?(?=^## 7\.)", flow, re.M | re.S)
step6 = step6.group(0) if step6 else ""
note = re.search(r"^\*\*Comments\.\*\*.*?(?=^\*\*[A-Z]|\Z)", step6, re.M | re.S)
note = note.group(0) if note else ""
template = re.search(r"```md\n(.*?)```", note, re.S)
template = template.group(1) if template else ""
pattern = re.search(r"Python `re` pattern `([^`]+)`", note)
try:
    pattern = re.compile(pattern.group(1)) if pattern else None
except re.error:
    pattern = None
if not template.startswith("> [!NOTE]\n") or "<model>" not in template or "<login>" not in template:
    errors.append("skills/issue-flow: step 6 needs a **Comments.** paragraph whose ```md template opens with a "
                  "`> [!NOTE]` line and names the model (`<model>`) acting for the maintainer (`<login>`)")
elif not pattern:
    errors.append("skills/issue-flow: step 6's **Comments.** paragraph must give the note as a Python `re` pattern")
else:
    ours = template.replace("<model>", "Claude Opus 5.5").replace("<login>", "kaminski-dev")
    for body, own in ((ours, True), (ours.replace("\n", "\r\n"), True),
                      ("> [!NOTE]\n> The deploy window is 48 h.\n\nPlease check.", False),
                      ("Quoting it:\n\n" + ours, False)):
        if bool(pattern.match(body)) != own:
            errors.append(f"skills/issue-flow: step 6's attribution pattern {'misses' if own else 'matches'} {body!r}")
own = re.search(r'^ATTRIBUTION = re\.compile\(r"([^"\n]+)"\)$', watcher, re.M)
if not pattern or not own or own.group(1) != pattern.pattern:
    errors.append("skills/issue-flow/pr-wait: its ATTRIBUTION pattern must equal step 6's **Comments.** pattern, "
                  "or it reports the agent's own comments or drops the maintainer's")
for what, rule in (
    ("every comment and thread reply, in steps 6 and 7", r"every comment and thread reply.*step 7"),
    ("the model name the harness reports", r"model name the harness reports"),
    ("resolving a review thread only once its reply posted and GitHub returned the reply's URL",
     r"[Rr]esolve a review thread only once its reply posted and GitHub returned (?:its|the reply's) URL"),
):
    if not re.search(rule, note, re.S):
        errors.append(f"skills/issue-flow: step 6's **Comments.** paragraph does not name {what}")
if not re.search(r"own fix and skip records.*attribution note", step7, re.S):
    errors.append("skills/issue-flow: step 7 must tell your own records apart by the attribution note")
# Before `gh pr create`: the branch's open PR, and the REST create when GraphQL is rate-limited.
opening = re.search(r"^Rebase onto .*$", step6, re.M)
opening = opening.group(0) if opening else ""
# CodeRabbit on #136, round 2 (#112): an open PR from the branch into another base is not this issue's PR.
if "`gh pr list --head <branch> --base <base> --state open --json number,url`" not in opening:
    errors.append("skills/issue-flow: step 6's existing-PR check must filter on the base too (`--base <base>`)")
if not 0 <= opening.find("gh pr list --head") < opening.find("gh pr create"):
    errors.append("skills/issue-flow: step 6 must look for the branch's open PR (`gh pr list --head`) before `gh pr create`")
rest = re.search(r"GraphQL.*rate limit.*`gh api \"repos/\{owner\}/\{repo\}/pulls\"[^`]*`", opening)
if not rest or "-f base=<base>" not in rest.group(0) or "pre-main" in rest.group(0):
    errors.append("skills/issue-flow: step 6 must open the PR through REST (`gh api \"repos/{owner}/{repo}/pulls\"`, "
                  "`-f base=<base>`, never pre-main) when `gh pr create` hits GraphQL's rate limit")

# A PR reaches the maintainer through one gate, checked on the latest commit, and one verdict (#126, tstack
# full-send's merge gate and full-stop's handoff). Merging stays the maintainer's: no merge grant is taken.
gate = re.search(r"^\*\*Ready gate\.\*\*.*?(?=^\*\*[A-Z]|\Z)", step6, re.M | re.S)
gate = gate.group(0) if gate else ""
if not gate:
    errors.append("skills/issue-flow: step 6 has no **Ready gate.** paragraph")
for what, pattern in (
    ("the latest commit it is checked on", r"latest commit"),
    ("proof that covers every change in the diff", r"proof[^.;]*covers every change in the diff"),
    ("required checks green", r"[Rr]equired checks are green"),
    ("every bot finding fixed or answered on its thread", r"[Ee]very bot finding is fixed or answered on its thread"),
    ("no human review requesting changes", r"[Nn]o human review requests changes"),
    ("a branch up to date and mergeable", r"up to date[^.;]*mergeable"),
    ("pr-wait --until ready for the mechanical part", r"`[^`]*pr-wait[^`]*--until ready`[^.]*mechanical"),
    ("exactly one verdict ending the handoff", r"handoff[^.]*ends with exactly one"),
    ("the Ready to merge verdict", r"\*\*Ready to merge\*\*"),
    ("the Waiting for required approval verdict", r"\*\*Waiting for required approval\*\*"),
    ("the Blocked verdict", r"\*\*Blocked\*\*"),
    ("the mergeable fields in its gh pr view read", r"`gh pr view <PR> --json [^`]*\bmergeable,mergeStateStatus\b"),
    ("a condition that cannot be read as not passed, so Blocked",
     r"condition you cannot read[^.]*has not passed[^.]*\*\*Blocked\*\*"),
):
    if gate and not re.search(pattern, gate, re.S):
        errors.append(f"skills/issue-flow: step 6's **Ready gate.** paragraph does not name {what}")
for line in ("could not read whether it touches files in this PR", "required checks could not be read (HTTP 403"):
    if line not in watcher or line not in step6:
        errors.append(f"skills/issue-flow: step 6's event list must name pr-wait's `{line}` line")
if "the merge state known" not in step6:
    errors.append("skills/issue-flow: step 6 must say `ready` waits for the merge state known")
if not re.search(r"6 hours[^.]*fresh baseline", step6):
    errors.append("skills/issue-flow: step 6 must say the watcher keeps its state 6 hours, past which a restart "
                  "starts a fresh baseline")
if re.search(r"gh pr merge|--admin|--auto\b|merge queue", gate) or "Merging is the maintainer's" not in step6:
    errors.append("skills/issue-flow: step 6 keeps merging the maintainer's; its gate grants no merge")

# An unattended run asks only for a closed list of reasons, through the question tool, and lists the rest as
# decisions it took (#126, tstack full-send's "Asking the user").
asking = re.search(r"^## Asking\n.*?(?=^## |\Z)", implement, re.M | re.S)
asking = asking.group(0) if asking else ""
if not asking:
    errors.append("skills/implement: has no ## Asking section")
for what, pattern in (
    ("no proof possible", r"^- [^\n]*no proof[^\n]*possible"),
    ("a ready gate that cannot pass", r"^- [^\n]*ready gate[^\n]*cannot pass"),
    ("a step outside the grant", r"^- [^\n]*outside the grant"),
    ("an ambiguous goal", r"^- [^\n]*goal is ambiguous"),
    ("another PR making this one obsolete", r"^- [^\n]*another PR makes this one obsolete"),
    ("AskUserQuestion with the recommendation first", r"AskUserQuestion.*recommendation first"),
    ("the final message opening with the question when there is no question tool",
     r"no question tool[^.]*open[^.]*final message with the question"),
    ("the Decisions taken list", r"\*\*Decisions taken\*\*"),
):
    if asking and not re.search(pattern, asking, re.M | re.S):
        errors.append(f"skills/implement: its ## Asking section does not name {what}")
report = re.search(r"^## Report\n.*?(?=^## |\Z)", implement, re.M | re.S)
report = report.group(0) if report else ""
if "**Decisions taken**" not in report or not re.search(r"ends with[^.]*verdict[^.]*`dk:issue-flow` step 6", report):
    errors.append("skills/implement: its ## Report must carry **Decisions taken** and end with the verdict "
                  "from `dk:issue-flow` step 6's **Ready gate.**")
# A run can stop before any PR exists, and the report carries the review's own report (#112, CodeRabbit on #136).
for what, pattern, text in (
    ("the PR link only when one exists, in the question", r"PR link when one exists", asking),
    ("a run stopped before any PR: where, the question, Decisions taken, no verdict",
     r"stopped before any PR[^.]*where it stopped[^.]*question[^.]*\*\*Decisions taken\*\*[^.]*no verdict", report),
    ("code-review's Answer findings report: rounds, shortstat, declined issue numbers",
     r"\*\*Answer findings\*\* report \(the rounds run[^)]*shortstat before and after[^)]*declined finding's issue number\)",
     report),
):
    if not re.search(pattern, text):
        errors.append(f"skills/implement: does not name {what}")

fan_out = re.search(r"^\*\*Fan-out\.\*\*.*?(?=^## )", flow, re.M | re.S)
waits = re.search(r"^- \*\*Waits\*\*:.*$", fan_out.group(0) if fan_out else "", re.M)
if not waits or not re.search(r"every background wait", waits.group(0)) or not re.search(
        r"deadline.*20 minutes.*reports", waits.group(0)):
    errors.append("skills/issue-flow: step 2's fan-out rules need a **Waits** rule: every background wait has a "
                  "deadline (20 minutes unless the step says otherwise) and reports when it expires")
# A dispatched subagent starts with a fresh context window; a fork carries the orchestrator's whole context (#114).
FRESH = "fresh context window"
worktrees = re.search(r"^- \*\*Worktrees\*\*:.*$", fan_out.group(0) if fan_out else "", re.M)
worktrees = worktrees.group(0) if worktrees else ""
if FRESH not in worktrees or "`isolation`" not in worktrees or '`subagent_type: "fork"`' not in worktrees:
    errors.append(f"skills/issue-flow: step 2's **Worktrees** rule must launch each subagent with a {FRESH}, "
                  'ruling out both `isolation` and `subagent_type: "fork"`')
for name, file in (("research", "SKILL.md"), ("grilling", "SKILL.md"),
                   ("codebase-design", "DESIGN-IT-TWICE.md"), ("improve-codebase-architecture", "SKILL.md")):
    if FRESH not in (DK / "skills" / name / file).read_text():
        errors.append(f"skills/{name}/{file}: dispatches a subagent but does not start it with a {FRESH}")
if FRESH in review:
    errors.append(f"skills/code-review: launches named agent types, which never fork; it skips the {FRESH} line")
spec_steps = skills["implement-spec"].read_text().replace("**", "")
for step in ("4", "7"):
    text = re.search(rf"^{step}\. .*$", spec_steps, re.M)
    if not text or "fresh implementer subagent" not in text.group(0):
        errors.append(f"skills/implement-spec: step {step} must use a fresh implementer subagent")
for step, what, pattern in (
    ("7", "answering the findings by dk:code-review's Answer findings step", r"`dk:code-review`'s Answer findings step"),
    ("8", "the hand-over through dk:issue-flow step 6's Ready gate", r"`dk:issue-flow` step 6's Ready gate"),
    ("7", "the review-fix implementer's own worktree off the integration branch, made by the orchestrator",
     r"its own worktree off the integration branch, made by you"),
    ("7", "a merger subagent bringing its branch back before step 8", r"merger subagent[^.]*before step 8"),
):
    text = re.search(rf"^{step}\. .*$", spec_steps, re.M)
    if not text or not re.search(pattern, text.group(0)):
        errors.append(f"skills/implement-spec: step {step} must name {what}")
for name in ("research", "improve-codebase-architecture"):
    if "never as a fork" not in (DK / "skills" / name / "SKILL.md").read_text():
        errors.append(f"skills/{name}: its subagent starts with a fresh context window, never as a fork")

manual = re.search(r"A worktree with no merged PR.*$", step7, re.M)
if not manual or not re.search(r"dk-gc --in-use <worktree>.*git worktree remove", manual.group(0)):
    errors.append("skills/issue-flow: step 7's removal by hand must run `dk-gc --in-use <worktree>` before "
                  "`git worktree remove`")

if "PR comment" not in step7:
    errors.append("skills/issue-flow: step 7's push route must record a review-body finding's fix in a PR comment; it has no thread")
skipped = re.search(r"^ *Either way, a skipped .*$", step7, re.M)
skipped = skipped.group(0) if skipped else ""
if not re.search(r"skipped inline finding.*thread", skipped) or not re.search(
        r"skipped review-body finding.*PR comment.*file.*lines", skipped):
    errors.append("skills/issue-flow: step 7 must send a skipped inline finding's reason to its thread, "
                  "and a skipped review-body finding's to a PR comment naming its file and lines")

# The agent picking up a handoff never loads the skill, so the written document carries the pickup rules (#118).
handoff = skills["handoff"].read_text()
pickup = re.search(r"^## Picking up a handoff\n.*?(?=^## |\Z)", handoff, re.M | re.S)
pickup = pickup.group(0) if pickup else ""
for what, pattern in (
    ("the handoff as context, not proof", r"context, not proof"),
    ("a check against the current head", r"current head"),
    ("a check for uncommitted work", r"uncommitted work.*git status"),
    ("a check against the code", r"the code each claim"),
    ("re-judging the earlier implementation", r"[Rr]e-judge the earlier implementation"),
    ("imported commits keeping their authorship and trailers", r"cherry-pick.*author.*trailers"),
):
    if not re.search(pattern, pickup, re.S):
        errors.append(f"skills/handoff: its 'Picking up a handoff' section does not name {what}")
if not re.search(r"\"Picking up a handoff\" section.*verbatim", handoff[:handoff.find("## Picking up")]):
    errors.append("skills/handoff: the written document must open with the 'Picking up a handoff' section, copied verbatim")
if not re.search(r"\A---\n.*?\n---\n\n<!-- Adapted from t3dotgg/tstack@[0-9a-f]+ skills/takeover, MIT \(© 2026 Theo Browne\)\. ",
                 handoff, re.S):
    errors.append("skills/handoff: no `<!-- Adapted from t3dotgg/tstack@<commit> skills/takeover, MIT (© 2026 Theo Browne).` "
                  "marker right after the frontmatter")

# A bug born on the branch passes at the base, so its control is the branch's last pre-fix commit (#112, CodeRabbit on #136).
control = re.search(r"^1\. \*\*Control\*\*.*$", skills["verify"].read_text(), re.M)
if not control or "the branch's last pre-fix commit when the bug came in on this branch" not in control.group(0):
    errors.append("skills/verify: step 4's control must be the branch's last pre-fix commit when the bug came in on this branch")
# CodeRabbit on #136, round 2 (#112): that commit is found, not guessed.
if control and not re.search(r"parent \(`<sha>\^`\) of the commit that brought the bug in.*`git log`.*`git bisect`", control.group(0)):
    errors.append("skills/verify: step 4's control does not say how to find the last pre-fix commit "
                  "(the parent of the commit that brought the bug in, by git log or git bisect)")

# A performance claim owes its spread, so "faster" inside the noise reads as inconclusive (#119).
owe = re.search(r"^## 1\..*?(?=^## 2\.)", skills["verify"].read_text(), re.M | re.S)
perf = re.search(r"^\| Performance claim .*$", owe.group(0) if owe else "", re.M)
perf = perf.group(0) if perf else ""
if not perf:
    errors.append("skills/verify: step 1's proof table has no Performance claim row")
for what, pattern in (
    ("the limiter", r"\blimiter\b"),
    ("the decision rule written before the first run", r"decision rule.*before the first run"),
    ("both sides run tuned", r"\btuned\b"),
    ("errors counted", r"errors.*counted"),
    ("at least 5 alternating runs per side", r"at least 5 runs per side, alternating"),
    ("the range reported", r"median and range"),
    ("the work confirmed to have happened", r"work confirmed to have happened"),
    ("the inconclusive verdict when the spread is larger than the effect",
     r"spread larger than the effect.*\*\*inconclusive\*\*"),
):
    if perf and not re.search(pattern, perf):
        errors.append(f"skills/verify: step 1's Performance claim row does not name {what}")

# A stale PR is judged as an idea before its branch is rebased, and only a leased push updates it (#123).
modernize = skills.get("modernize")
modernize_text = modernize.read_text() if modernize else ""
if not modernize:
    errors.append("skills/modernize: missing; a stale PR has no procedure")
elif frontmatter(modernize).get("disable-model-invocation") != "true":
    errors.append("skills/modernize: must be user-invoked (disable-model-invocation: true)")
for what, pattern in (
    ("its tstack provenance marker", r"<!-- Adapted from t3dotgg/tstack@1085050 skills/modernize, MIT \(© 2026 Theo Browne\)\. "
                                     r"Changed for dk-agent-kit: "),
    ("the three dispositions", r"MODERNIZE.*REWORK.*CLOSE"),
    ("that age alone is not evidence", r"Age alone is not evidence"),
    ("the base read from workflow.md", r"base.*`docs/agents/workflow\.md`"),
    ("the worktree from dk:issue-flow step 2", r"`dk:issue-flow` step 2"),
    ("the base's new commits checked for conceptual conflicts", r"conceptual conflict"),
    ("the series compared with git range-diff", r"git range-diff"),
    ("the push leased to the observed remote head, every ref quoted",
     r'git push --force-with-lease="refs/heads/<branch>:<observed sha>" origin "HEAD:refs/heads/<branch>"'),
    # CodeRabbit on #136, round 2 (#112): headRefName reaches the shell only once Git accepts it as a branch name.
    ("the branch checked before any shell use, stopping when it fails",
     r'`git check-ref-format --branch "<branch>"`[^.]*stop[^`]*`git ls-remote origin "refs/heads/<branch>"`'),
    # CodeRabbit on #136 (#112): a wrong base stops first, a fork's head comes from refs/pull, the work stays in the worktree.
    ("a base mismatch stopping before any change to the branch, until the user's word",
     r"`baseRefName` differs stops here, before any change to its branch[^.]*only on the user's word"),
    ("a fork PR's head fetched read-only from refs/pull", r"`git fetch -q origin pull/<PR>/head`"),
    ("items 2 to 5 run inside the chosen worktree", r"Items 2 to 5 run inside that worktree"),
    ("the push from the path item 1 chose, -modernize included", r"`~/workspace/<prefix>-<N>-modernize`, written literally"
                                                                  r".*cd <that path> && git push"),
):
    if modernize and not re.search(pattern, modernize_text, re.S):
        errors.append(f"skills/modernize: does not name {what}")
if re.search(r"--force-with-lease(?!=)", modernize_text):
    errors.append("skills/modernize: a bare --force-with-lease leases against whatever the last fetch saw; "
                  "name the branch and the observed sha")

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

# A vendored script carries its marker as a comment; its row names it in the section at the marker's commit.
section_by_commit = dict(re.findall(r"^## .*? @ ([0-9a-f]+)\n(.*?)(?=^## |\Z)", upstream, re.M | re.S))
for path in sorted(DK.glob("skills/*/**/*")):
    if not path.is_file() or path.suffix == ".md":
        continue
    dk_file = str(path.relative_to(DK))
    for source, commit, upstream_path in re.findall(r"^# Adapted from (\S+(?: \S+)?)@([0-9a-f]+) (\S+?), ",
                                                    path.read_text(errors="replace"), re.M):
        if not re.search(rf"^\| {re.escape(dk_file)} \| {re.escape(upstream_path)} \|", section_by_commit.get(commit, ""), re.M):
            errors.append(f"{dk_file}: adapted from {source}@{commit} {upstream_path}, but upstream/UPSTREAM.md has no "
                          "row for it in the section at that commit")

# dk:diagnosing-bugs must fire on its own, before dk:tdd and dk:verify, so it is model-invoked; its
# description then sits in the listing every turn (#27), so it stays short (#122).
diagnosing = skills.get("diagnosing-bugs")
if diagnosing is None:
    errors.append("skills/diagnosing-bugs: missing (#122)")
else:
    fm, text = frontmatter(diagnosing), diagnosing.read_text()
    if "disable-model-invocation" in fm:
        errors.append("skills/diagnosing-bugs: must be model-invoked (no disable-model-invocation)")
    if len(fm.get("description", "")) > 160:
        errors.append(f"skills/diagnosing-bugs: description is {len(fm.get('description', ''))} chars (> 160, #27)")
    if not re.search(r"<!-- Adapted from mattpocock/skills@[0-9a-f]+ skills/engineering/diagnosing-bugs, MIT", text):
        errors.append("skills/diagnosing-bugs: no `<!-- Adapted from mattpocock/skills@<commit> "
                      "skills/engineering/diagnosing-bugs, MIT` marker")
    for script in sorted(set(re.findall(r"`(scripts/[\w./-]+)`", text))):
        if not (diagnosing.parent / script).is_file():
            errors.append(f"skills/diagnosing-bugs: names {script}, which it does not ship")
    for what, pattern in (
        ("the issue's scratch folder for loops and the HITL copy", r"`\$SCRATCH/<N>/`"),
        ("the observability helper for captured artifacts", r"`docs/agents/observability\.md`"),
        ("the regression test through dk:tdd", r"Skill tool with `dk:tdd`"),
        ("the final proof through dk:verify", r"Skill tool with `dk:verify`"),
        ("a bug born on the branch, whose control is its last pre-fix commit", r"last pre-fix commit[^.]*`dk:verify` step 4"),
        ("the confirmed cause into the PR through dk:pr", r"Skill tool with `dk:pr`"),
        ("a missing seam routed to the user's /dk:improve-codebase-architecture", r"`/dk:improve-codebase-architecture`"),
    ):
        if not re.search(pattern, text):
            errors.append(f"skills/diagnosing-bugs: does not name {what}")

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

# Each source in UPSTREAM.md keeps its license notice: a THIRD_PARTY row that links the repo and names
# the section's commit, its license and a license file that exists. A pin that moves takes the row along.
third_party = (ROOT / "THIRD_PARTY" / "README.md").read_text().splitlines()
for repo, license_name, commit in re.findall(r"^## (\S+) .*?\(([^()]+)\) @ ([0-9a-f]+)$", upstream, re.M):
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

# Triage's verify step runs the check the issue names and ends on a checkable criterion.
verify = re.search(r"^3\. \*\*Verify the claim\.\*\*.*?(?=^4\. )", skills["triage"].read_text(), re.M | re.S)
if not verify:
    errors.append("skills/triage: no step 3 'Verify the claim' followed by a step 4")
else:
    done = re.search(r"Done when .*", verify.group(0))
    done = done.group(0) if done else ""
    if "failing check the issue names" not in verify.group(0):
        errors.append("skills/triage: step 3 does not run the failing check the issue names")
    for what, pattern in (
        ("each command quoted with its exit status or key output line", r"quotes each command .*exit status or key output line"),
        ("needs-info for a bug whose check could not run", r"a bug whose .*could not run goes to `needs-info`"),
    ):
        if not re.search(pattern, done):
            errors.append(f"skills/triage: step 3's Done when line does not name {what}")

pr_route = re.search(r"^\s*- `pr`: .*", skills["batch-pr"].read_text(), re.M)
if not pr_route or "Once it is merged, run step 1 again and write step 3's body from its new output, since the first " \
                   "collection predates the fix PR." not in pr_route.group(0):
    errors.append("skills/batch-pr: step 2's `pr` route does not run step 1 again after the fix PR merges")

# The latest run across all workflows can be a Dependabot run that tests nothing (#98).
evidence = re.search(r"^- \*\*Evidence\*\*: .*(?:\n  .*)*", skills["batch-pr"].read_text(), re.M)
evidence = evidence.group(0) if evidence else ""
runs = re.findall(r"gh run list [^`]*", evidence)
if not runs or any("--workflow" not in r for r in runs) or "workflow.md" not in evidence \
        or "batch PR's own checks" not in evidence or "origin/pre-main" not in evidence:
    errors.append("skills/batch-pr: step 3's Evidence must point at the batch PR's own checks, and read a pre-main "
                  "run per CI workflow workflow.md names (`gh run list --workflow`) that tested pre-main's head, "
                  "never the latest run of any")

# PR, spec and research diagrams follow one set of rules, kept in dk:pr (#116): labels and arrows from pstack
# statechart, the box and word limits from pstack ketchup, the build-up series from teach.
pr_skill = skills["pr"].read_text()
diagram_rules = re.search(r"^#### Diagram rules\n.*?(?=^#{1,4} )", pr_skill, re.M | re.S)
diagram_rules = diagram_rules.group(0) if diagram_rules else ""
for what, pattern in (
    ("states and boxes named by what the reader sees", r"what the reader sees"),
    ("arrows that say what happens", r"[Aa]rrow.*says? what happens"),
    ("about 20 arrows at most", r"about 20 arrows"),
    ("at most 6 boxes of at most 8 words", r"six boxes.*eight words"),
    ("status lists kept out of diagrams", r"status list"),
    ("every box connected", r"[Ee]very box connects"),
    ("each fact given once", r"[Ee]ach fact.*once"),
    ("plain-word labels", r"plain words"),
    ("a short build-up series for 3 or more parts", r"short build-up series.*three or more parts"),
):
    if not re.search(pattern, diagram_rules, re.S):
        errors.append(f"skills/pr: its **Diagram rules** under Summary do not name {what}")
for name in ("to-spec", "research-codebase"):
    if not re.search(r"\*\*Diagram rules\*\*[^\n]*`dk:pr`", skills[name].read_text()):
        errors.append(f"skills/{name}: does not point its diagrams at the **Diagram rules** in `dk:pr`")
# The PR opens with the problem, and its title says why the change matters (tstack file-pr).
if not re.search(r"^## Summary\n\n<[^>\n]*problem[^>\n]*>\n\n<diagram", pr_skill, re.M):
    errors.append("skills/pr: the template's Summary does not open with the problem sentence, before the visual")
summary = re.search(r"^### Summary\n.*?(?=^#{1,4} )", pr_skill, re.M | re.S)
if not summary or not re.search(r"one plain sentence on the problem.*before any visual", summary.group(0), re.S):
    errors.append("skills/pr: its Summary section does not open with one plain sentence on the problem, before any visual")
if not re.search(r"^### Title\n\n[^\n]*why the change matters", pr_skill, re.M):
    errors.append("skills/pr: no ### Title section saying the title tells why the change matters")

# Each skill ships its own copy, since `python3 -I` keeps a script's folder off sys.path; the copies stay one.
copies = {}
for script in ("batch-pr/batch.py", "issue-flow/pr-wait", "triage/ready.py"):
    m = re.search(r"^def origin_repo\(\):\n(?:    .*\n)+", (DK / "skills" / script).read_text(), re.M)
    copies.setdefault(m.group(0) if m else None, []).append(script)
if len(copies) != 1 or None in copies:
    errors.append("skills: origin_repo() differs between " + " | ".join(", ".join(v) for v in copies.values()))
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

# The AGENTS.md checks line, the README Test block and CI run the same test files, and every one exists (#127).
test_cmd = r"(?:python3 -I|bash) (tests/[\w/]+\.(?:py|sh))"
checks_line = re.search(r"^## Checks\n\n(.*)", (ROOT / "AGENTS.md").read_text(), re.M)
test_block = re.search(r"^## Test\n\n```sh\n(.*?)```", readme, re.M | re.S)
lists = {
    "AGENTS.md checks line": set(re.findall(test_cmd, checks_line.group(1) if checks_line else "")),
    "README.md Test block": set(re.findall(test_cmd, test_block.group(1) if test_block else "")),
    ".github/workflows/test.yml": set(re.findall(rf"^\s*run: {test_cmd}$",
                                                 (ROOT / ".github/workflows/test.yml").read_text(), re.M)),
}
on_disk = {str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("**/test_*") if p.suffix in (".py", ".sh")}
for where, listed in lists.items():
    for path in sorted(listed - on_disk):
        errors.append(f"{where}: runs {path}, which does not exist")
    for path in sorted(on_disk - listed):
        errors.append(f"{where}: does not run {path}")

for e in errors:
    print("FAIL", e)
print(f"{len(skills)} skills, {len(agents)} agents, {len(errors)} problems")
sys.exit(1 if errors else 0)
