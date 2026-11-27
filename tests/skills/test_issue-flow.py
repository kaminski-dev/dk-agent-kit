#!/usr/bin/env python3
"""Static checks on the dk:issue-flow skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
DK, FRESH, errors, skills = lib.DK, lib.FRESH, lib.errors, lib.skills

flow = skills["issue-flow"].read_text()
# The sections only some sessions reach live in reference files beside SKILL.md, each behind a pointer there (#179).
HERE = skills["issue-flow"].parent
REFS = ("fan-out", "comments", "watch", "review-bot", "ready-gate", "after-merge")
ref = {name: (HERE / f"{name}.md").read_text() if (HERE / f"{name}.md").is_file() else "" for name in REFS}
for name in REFS:
    if not ref[name]:
        errors.append(f"skills/issue-flow/{name}.md: missing, though SKILL.md's pointer reaches for it")
for path in sorted(HERE.glob("*.md")):
    if path.name != "SKILL.md" and path.stem not in REFS:
        errors.append(f"skills/issue-flow/{path.name}: no pointer in SKILL.md reaches it; add it to REFS and point at it")
# Each pointer names its reader and the branch that sends them there, so an implementer that never reaches the
# branch never loads the file.
for heading, name, reader in (
    (r"\*\*Fan-out\.\*\*", "fan-out", r"orchestrator running agents in parallel.*before its first `git worktree add`"),
    (r"\*\*Comments\.\*\*", "comments", r"before your first post, thread reply or correction"),
    (r"\*\*Watch the PR\.\*\*", "watch", r"session that opened the PR.*before it starts the watcher"),
    (r"\*\*Review bot\.\*\*", "review-bot", r"session watching the PR, once the watcher prints the review bot's verdict"),
    (r"\*\*Ready gate\.\*\*", "ready-gate", r"session that hands the PR to the maintainer"),
    (r"The session whose watch printed `merged`", "after-merge", r"batch PR's review findings, declines an issue or removes a worktree"),
):
    line = re.search(rf"^{heading}.*$", flow, re.M)
    line = line.group(0) if line else ""
    if f"[{name}.md]({name}.md)" not in line or not re.search(reader, line):
        errors.append(f"skills/issue-flow: the pointer to {name}.md must link it and name its reader and branch ({reader})")
    if ref[name] and not re.search(r"\A# .*\n\nFor ", ref[name]):
        errors.append(f"skills/issue-flow/{name}.md: must open with its heading, then a `For …` line naming its reader")
bot = ref["review-bot"]
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
watch = re.search(r"\A.*?(?=^\*\*Watch to the merge\.\*\*)", ref["watch"], re.M | re.S)
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
step6_waits = (step6_waits.group(0) if step6_waits else "") + ref["watch"] + ref["review-bot"] + ref["ready-gate"]
if re.search(r"--watch\b|\bsleep \d", step6_waits):
    errors.append("skills/issue-flow: step 6 waits through pr-wait alone; it has a `--watch` or `sleep` wait left")
step7 = ref["after-merge"]
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
if not re.search(r"done.*inline record is such a reply whose `in_reply_to_id`", route):
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
note = ref["comments"]
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
# CodeRabbit on #136, round 2 (#112): a record is the agent's only when it is the gh user's and carries the note.
if not re.search(r'is a record only when its author is the gh user.*attribution note.*'
                 r'inline record is such a reply[^)]*\.user\.login == "<login>"', route, re.S):
    errors.append("skills/issue-flow: step 7 must count a reply as your fix or skip record only when it is the gh "
                  "user's and opens with the attribution note, its inline query filtered on `.user.login`")
# CodeRabbit on #136, round 2 (#112): a watcher that ended on its own deadline or error is reported, not rerun.
if not re.search(r"[Ss]tart it again after each push, after an action of yours that changes what blocked it[^:]*"
                 r"monitor expired while the watch is still wanted", watch) or not re.search(
        r"`deadline passed` or `pr-wait stopped` line[^.]*goes to the user", watch):
    errors.append("skills/issue-flow: step 6 restarts the watcher after a push, an action that changes what blocked "
                  "it, or an expired monitor, and reports a `deadline passed` or `pr-wait stopped` line to the user")
# CodeRabbit on #136 (#112): the deadline report names the merge states pr-wait gates on, never "not CLEAN".
deadline = re.search(r"^- `deadline passed`:.*$", watch, re.M)
if not deadline or "`BEHIND`" not in deadline.group(0) or "`DIRTY`" not in deadline.group(0) or "CLEAN" in deadline.group(0):
    errors.append("skills/issue-flow: step 6's `deadline passed` report must name a `BEHIND`, `DIRTY` or unreadable "
                  "merge state, the ones pr-wait gates on")
# #148: a hand run of the gate goes through dk-gate, whose pass the push of the same tree reuses.
gate_runs = re.search(r"^The gate runs at the push and by hand.*$", step6, re.M)
if not gate_runs or "`dk-gate ~/workspace/<prefix>-<N>`" not in gate_runs.group(0) or "reuses" not in gate_runs.group(0):
    errors.append("skills/issue-flow: step 6 must say the gate runs at the push and by hand through dk-gate "
                  "(`dk-gate ~/workspace/<prefix>-<N>`), and that the push reuses a hand pass on the same tree")
# #149: a hand run may wait for one of the machine's two gate slots, longer than Bash's default 2 minutes, and a
# busy refusal means the gate did not run.
if not gate_runs or "600000 ms" not in gate_runs.group(0) or "Exit 3" not in gate_runs.group(0):
    errors.append("skills/issue-flow: step 6 must say a hand dk-gate run may wait for a gate slot (a 600000 ms Bash "
                  "timeout), and that exit 3 or a busy push denial means the gate did not run")
if re.search(r"Stop (hook|gate)", flow + "".join(ref.values())):
    errors.append("skills/issue-flow: the Stop gate is gone (#148); the gate runs at the push and through dk-gate")
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
# CodeRabbit on #136 (#112): a file path holds spaces, so it is quoted; a title can hold `$(...)` or backticks,
# which expand even inside double quotes, so the title reaches gh from a file, like the body.
if re.search(r'(?<![-"])body=@<|--body-file <|title=<', step6) or '-F "title=@<title file>"' not in opening \
        or '-F "body=@<body file>"' not in opening or "no trailing newline" not in opening:
    errors.append("skills/issue-flow: step 6 must pass the title from a file written with no trailing newline "
                  "(`-F \"title=@<title file>\"`) and quote each file path "
                  "(`-F \"body=@<file>\"`, `--body-file \"<file>\"`)")

# A PR reaches the maintainer through one gate, checked on the latest commit, and one verdict (#126, tstack
# full-send's merge gate and full-stop's handoff). Merging stays the maintainer's: no merge grant is taken.
gate = re.search(r"\A.*?(?=^\*\*Customer reply\.\*\*|\Z)", ref["ready-gate"], re.M | re.S)
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
    if line not in watcher or line not in watch:
        errors.append(f"skills/issue-flow: step 6's event list must name pr-wait's `{line}` line")
if "the merge state known" not in watch:
    errors.append("skills/issue-flow: step 6 must say `ready` waits for the merge state known")
if not re.search(r"6 hours[^.]*fresh baseline", watch):
    errors.append("skills/issue-flow: step 6 must say the watcher keeps its state 6 hours, past which a restart "
                  "starts a fresh baseline")
if re.search(r"gh pr merge|--admin|--auto\b|merge queue", gate) or "Merging is the maintainer's" not in step6:
    errors.append("skills/issue-flow: step 6 keeps merging the maintainer's; its gate grants no merge")

# After the handover the PR is watched until it merges, so no one relays a merge or a conflict by hand (#176).
merge_watch = re.search(r"^\*\*Watch to the merge\.\*\*.*?(?=^\*\*[A-Z]|^## |\Z)", ref["watch"], re.M | re.S)
merge_watch = merge_watch.group(0) if merge_watch else ""
for what, pattern in (
    ("the until-merged watcher", r"`python3 -I <base directory>/pr-wait <PR> --until merged`"),
    ("who starts it: the session that hands the PR over, the orchestrator for a subagent's PR",
     r"session that hands the PR over[^.]*orchestrator"),
    ("that it runs in the background only, re-armed when its monitor expires", r"background.*re-arm"),
    ("a rebase and push on a conflict", r"`merge state is DIRTY`[^.]*rebase onto `origin/<base>`[^.]*push"),
    ("step 7 and the waiting tickets on a merge", r"`merged`[^.]*step 7[^.]*tickets that waited"),
    ("its own deadline, exit 3, told to the user", r"`deadline passed: no merge after[^.]*exit 3[^.]*user"),
):
    if not re.search(pattern, merge_watch, re.S):
        errors.append(f"skills/issue-flow: step 6's **Watch to the merge.** paragraph does not name {what}")
# A subagent's watcher would hold the PR's lock past its run, so the orchestrator's could not start (#176).
if not re.search(r"watch to the merge \(\[watch\.md\]\(watch\.md\)\)[^.]*subagent leaves it to its orchestrator", ref["ready-gate"]):
    errors.append("skills/issue-flow/ready-gate.md: the gate's last line must leave a subagent's watch to the merge "
                  "to its orchestrator")
for line in ("deadline passed: no merge after", '"merged"'):
    if line not in watcher:
        errors.append(f"skills/issue-flow/pr-wait: the watcher lacks `{line}`, which step 6's **Watch to the merge.** names")

fan_out = re.search(r"\A.*", ref["fan-out"], re.S)
waits = re.search(r"^- \*\*Waits\*\*:.*$", fan_out.group(0) if fan_out else "", re.M)
if not waits or not re.search(r"every background wait", waits.group(0)) or not re.search(
        r"deadline.*20 minutes.*reports", waits.group(0)):
    errors.append("skills/issue-flow: step 2's fan-out rules need a **Waits** rule: every background wait has a "
                  "deadline (20 minutes unless the step says otherwise) and reports when it expires")

# A wave's width counts the reviewers each implementer starts, so their reviews find a free slot (#175).
wave = re.search(r"^- \*\*Waves\*\*:.*$", fan_out.group(0) if fan_out else "", re.M)
wave = wave.group(0) if wave else ""
if not re.search(r"counts[^.]*reviewers[^.]*`dk:code-review`[^.]*tier[^.]*two in the small tier[^.]*four in standard "
                 r"and risky", wave) or not re.search(r"counts as standard until its tier[^.]*four implementers", wave):
    errors.append("skills/issue-flow: step 2's **Waves** rule must count each implementer's `dk:code-review` "
                  "reviewers against the 20 by tier (two small, four standard and risky), counting one whose tier "
                  "is not known yet as standard, so a wave runs at most four implementers")

worktrees = re.search(r"^- \*\*Worktrees\*\*:.*$", fan_out.group(0) if fan_out else "", re.M)
worktrees = worktrees.group(0) if worktrees else ""
if FRESH not in worktrees or "`isolation`" not in worktrees or '`subagent_type: "fork"`' not in worktrees:
    errors.append(f"skills/issue-flow: step 2's **Worktrees** rule must launch each subagent with a {FRESH}, "
                  'ruling out both `isolation` and `subagent_type: "fork"`')

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

# issue-flow's worktree, rebase and PR commands name the base (step 2), which a repo's workflow.md can set,
# so a repo without pre-main gets its own branch and no needless ask to restore pre-main.
for name, text in (("SKILL", flow), *ref.items()):
    for n, line in enumerate(text.splitlines(), 1):
        if re.search(r"git ls-remote|git worktree add|gh pr create|^Rebase onto|is missing:", line) and "pre-main" in line:
            errors.append(f"skills/issue-flow/{name}.md:{n}: names pre-main where the base belongs")
# Steps 6 and 7 describe the pre-main batch; step 2 says which parts lapse when the base is main.
step2 = re.search(r"^## 2\..*?(?=^## 3\.)", skills["issue-flow"].read_text(), re.M | re.S)
if not step2 or not re.search(r"When the base is `main`, there is no batch PR: `Closes #N` closes the issue on merge, "
                              r"and step 6's batch-PR note and step 7's batch-review bullet do not apply\.", step2.group(0)):
    errors.append("skills/issue-flow/SKILL.md: step 2 does not say what lapses when the base is main")

# #177: a correction goes through dk-comment-edit, which the product repos' ask rules on `gh api` PATCH never reach.
if "`dk-comment-edit <comment id> <file>`" not in note or not re.search(r"dk-comment-edit[^.]*own[^.]*attribution note", note):
    errors.append("skills/issue-flow: step 6's **Comments.** paragraph must correct a posted comment with "
                  "`dk-comment-edit <comment id> <file>`, which edits only your own comment with the attribution note")
if re.search(r"(?:-X|--method)[ =]?['\"]?(?:PATCH|patch)", flow + "".join(ref.values())):
    errors.append("skills/issue-flow: a comment edit goes through dk-comment-edit, never a raw `gh api` PATCH")

# #177: the customer reply is posted once the review loop has ended and the PR passed the gate, so it is never
# reworded after it is posted.
reply = re.search(r"^\*\*Customer reply\.\*\*.*?(?=^\*\*[A-Z]|^## |\Z)", ref["ready-gate"], re.M | re.S)
gate_at = ref["ready-gate"].find("The PR goes to the maintainer")
after_gate = bool(reply) and reply.start() > gate_at >= 0
reply = reply.group(0) if reply else ""
before_gate = step6 + ref["ready-gate"][:gate_at]
if not after_gate:
    errors.append("skills/issue-flow/ready-gate.md: needs a **Customer reply.** paragraph after the **Ready gate.**")
elif not re.search(r"gate passes[^.]*review loop", reply) or "workflow.md" not in reply or "**Blocked**" not in reply:
    errors.append("skills/issue-flow: step 6's **Customer reply.** waits for the gate to pass and the review loop to "
                  "end, posts as `workflow.md` describes, and posts nothing on **Blocked**")
if re.search(r"customer reply on the issue", before_gate):
    errors.append("skills/issue-flow: step 6 writes the customer reply before the review loop; it belongs after the gate")

# #177: on a repo the maintainer does not own, nothing carries the kit's attribution, and each draft goes to the
# maintainer first. tests/test_repo_owner.py runs the check the paragraph names.
step1 = re.search(r"^## 1\..*?(?=^## 2\.)", flow, re.M | re.S)
owner = re.search(r"^\*\*Ownership\.\*\*.*?(?=^\*\*[A-Z]|^## |\Z)", step1.group(0) if step1 else "", re.M | re.S)
owner = owner.group(0) if owner else ""
for what, pattern in (
    ("the check it runs", r"`python3 -I <base directory>/repo-owner`"),
    ("the check for a comment that goes to another repo", r"`python3 -I <base directory>/repo-owner <owner>/<repo>`"),
    ("its two answers", r"`own: [^`]*`.*`not own: [^`]*`"),
    ("no attribution note on comments", r"no attribution note"),
    ("no attribution lines in commits", r"commit[^.;]*no `Co-Authored-By`"),
    ("no attribution line in the PR body", r"PR body[^.;]*no[^.;]*Generated with"),
    ("each draft shown to the maintainer before it is posted", r"draft[^.]*maintainer[^.]*their word"),
    ("an exit 2 read as not own", r"exit 2[^.]*`not own`"),
):
    if not re.search(pattern, owner, re.S):
        errors.append(f"skills/issue-flow: step 1 needs an **Ownership.** paragraph naming {what}")
if not re.search(r"\*\*Ownership\.\*\*", re.search(r"^## 4\..*?(?=^## 5\.)", flow, re.M | re.S).group(0)):
    errors.append("skills/issue-flow: step 4's commits point at step 1's **Ownership.** for their attribution lines")
if not re.search(r"\*\*Ownership\.\*\*", note):
    errors.append("skills/issue-flow: step 6's **Comments.** must leave the note out where step 1's **Ownership.** says")
if not re.search(r"\*\*Ownership\.\*\*[^.]*`comment from <login>`", watch):
    errors.append("skills/issue-flow: step 6's watch must say that on a repo not your own your comments carry no note, "
                  "so `comment from <login>` may be your own")

lib.finish("dk:issue-flow")
