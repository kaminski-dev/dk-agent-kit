---
name: issue-flow
description: "How an issue travels from GitHub issue to merged PR in repos that batch through pre-main. Use when starting work on an issue (worktree, branch), reading or labelling an issue with gh, deciding whether newly found work joins the current issue, committing, attaching screenshots, opening the PR, or cleaning up after a merge."
---

# Issue flow

The shared sequence for every repo that works issue → branch → PR into `pre-main` → batch merge to `main` → deploy. The repo supplies its parameters in `docs/agents/workflow.md`: worktree prefix, branch types, fresh-worktree setup, CI names, review bot, batch-review fixes, customer-reply language, production-data policy. Read it before the first git step. Tracker commands live in `docs/agents/issue-tracker.md`, labels in `docs/agents/triage-labels.md`.

## 1. Read the issue

`gh issue view N --json title,body,labels,comments`. The issue and its comments are the record; a recalled note is background to check against them. Plain `--comments` drops the body when piped, so the `--json` form is the one that works in an agent shell. An issue labelled `spec` is an epic: its sub-issues are the work, the spec is their context.

## 2. Worktree before the first edit

One issue, one branch, one worktree, based on the remote **base**: the branch worktrees start from and PRs target, `pre-main` unless `workflow.md` names another. When the base is `main`, there is no batch PR: `Closes #N` closes the issue on merge, and step 6's batch-PR note and step 7's batch-review bullet do not apply.

```sh
git ls-remote --heads origin <base>     # the local origin/<base> ref can outlive the branch
git fetch -q origin
git worktree add ~/workspace/<prefix>-<N> -b <type>/<N>-<slug> origin/<base>
```

When `ls-remote` prints nothing, the base is missing: ask the maintainer to restore it, branching from `main` only on their word. Run the fresh-worktree setup from `workflow.md` before any gate means anything.

Scratch files live in `$SCRATCH/<N>/` (`$SCRATCH` = the session's scratchpad directory), one directory per agent, never in the tree. Parallel agents each get their own worktree and their own scratch directory; a shared one is how two agents overwrote each other's `network-failure.ts`. `git stash` is one list across all worktrees, so set work aside with a WIP commit or a patch file in `$SCRATCH`.

**Fan-out.** An orchestrator that runs agents in parallel, one ticket each, keeps three rules:

- **Worktrees**: it creates every worktree itself, one `git worktree add` after another (parallel adds collide on the `.git/config` lock), and hands each subagent its path. The subagent launches as a plain one, with no `isolation` parameter: harness isolation gives it a worktree of its own, branched from the default branch rather than the base, and blocks its edits in the one it was handed.
- **Briefs**: a brief names only skills a subagent can call: `dk:issue-flow`, `dk:tdd`, `dk:verify`, `dk:code-review`, `dk:pr`. A skill with `disable-model-invocation: true`, such as `dk:implement`, answers a subagent with an error, so the brief spells out the sequence through those five.
- **Waves**: at most 20 subagents run at once, the harness's limit; the remaining tickets start as slots free up.

## 3. Scope intake

Something new turns up mid-work: a bug next door, a missing case, a cleanup. Decide once, then move on.

**Fold it in** when all four hold:

- **Same place**: it touches files already in this branch's diff, or the same issue or acceptance area.
- **Small**: about 50 changed lines or fewer, with no migration, no new route or public API, no new dependency.
- **Context fits**: no new subsystem to read, and the session is far from compaction.
- **Two-way door**: nothing the customer sees changes beyond what the issue already changes.

Then record it, so review counts it as requested work: comment `Scope amendment: <what and why>` on the issue, and list it under "Also in this PR" in the PR body.

**Otherwise file it**: a new issue labelled `needs-triage`, opening with `Found while working on #N` and the evidence. Before creating it, search open issues touching the same files (`gh issue list --state open --search "<file or term>" --json number,title`) and add it there as a comment when one fits. When it blocks the current issue, link it as a blocker (tracker doc) and say so on the issue.

**Name each item by number and content.** Every follow-up, side finding or deferred item in your report, the PR body or an issue comment is its issue number plus one line of what it is: `#123: login answers 500 on an empty password`. An item without a number is filed first; a folded-in one carries the number of the issue whose scope amendment records it.

## 4. Commit per green step

Each commit is one verifiable unit: the gates from `AGENTS.md` pass on what it touches before the next unit starts. For a bug, the failing test lands first and the fix on top, so the history shows red then green. Messages are English, imperative, and name the issue: `Fix X when Y (#N)`.

## 5. Screenshots and evidence

Call the Skill tool with `dk:verify`; the proof it asks for lands here. Evidence goes into the PR, never into the tree. `dk:verify` leaves the screenshots in `$RUN/shots/`, its run directory under the session scratch (`$RUN` stands for the path it printed, written literally); push them to `verify-assets/<N>` with one command and paste the URLs it prints into the PR as printed:

```sh
dk-assets push <N> "$RUN"/shots/*.png
```

What it pushes and when it refuses is in its header (`head -12 "$(command -v dk-assets)"`). The branch stays after the merge: it is the only ref that keeps the embedded commit, so deleting it would eventually break the images in the merged PR.

## 6. Open the PR

Rebase onto the current `origin/<base>`, push the branch, and open the PR against the base (`gh pr create --base <base> --body-file …`), body written with the `dk:pr` skill.

The push is where the gate runs: dk-guard runs `.claude/gate.sh` in the checkout being pushed, the `cd` or `git -C` target, and denies the push when the gate fails. Write that path literally (`cd ~/workspace/<prefix>-<N> && git push`); a path held in a variable leaves the gate unrun.

The body carries:

- `Closes #N` when no post-deploy acceptance criterion remains, `Refs #N` when one does (a 24 h, 48 h or 7 d window on production logs or errors).
  GitHub acts on these keywords only in a PR into the default branch, so on this PR they do nothing. The batch PR into `main` repeats the line: its merge closes a `Closes #N` issue, and a `Refs #N` issue stays open for the post-deploy check (step 7).
- Every deviation from the issue, named for the maintainer's OK, and the "Also in this PR" list from scope intake.

When the change is one the customer sees, write the customer reply on the issue as `workflow.md` describes; for a change they never see (toolchain, CI, internal refactor), the PR says so instead. Merging is the maintainer's.

CI waits run in the background, so the user gets answers while CI runs:

1. Read the checks once: `gh pr checks <PR>`. When every check has finished, the read is the result.
2. Otherwise (a check pending, or "no checks reported" because CI has not registered the push yet) start `gh pr checks <PR> --watch --fail-fast` with `run_in_background` and keep answering. It ends non-zero at the first failed check, or zero once every check has passed, and its end wakes you. When it ends on "no checks reported", which it does at once, give CI time to register: start `sleep 20 && gh pr checks <PR> --watch --fail-fast` the same way, in the background, at most three times; still no checks after that, tell the user CI has not picked up the push.

A failed check is fixed on the branch and watched again before you report.

**Review bot.** A PR into a base that `workflow.md` lists under **Review bot** gets a review from the bot it names; with no such line, that is `coderabbitai[bot]` on PRs into `main`, the batch PR. You fetch its findings yourself, so the maintainer never pastes them:

1. Wait in the background for the bot's review of the head SHA: start this with `run_in_background` (or run its check as a Monitor until-loop) and keep answering. A review counts when its `commit_id` is the `headRefOid` and it has a body or inline comments of its own; a bot review holding only replies to threads (`in_reply_to_id` set) is not one. A round with no findings leaves no review, only the bot's summary comment, whose recent-review block now ends its range at the SHA (`between <old> and <sha>`) once no review is in progress. A rate-limit notice in that comment names the SHA too, but means no review ran. A match counts only while the head is still that SHA; a push meanwhile starts the wait on the new head.

   ```sh
   export bot='coderabbitai[bot]'   # or the login workflow.md names
   head=$(gh pr view <PR> --json headRefOid,commits --jq '"\(.headRefOid) \(.commits[-1].committedDate)"') || exit 2
   read -r sha since <<<"$head"; export sha since
   for i in $(seq 40); do
     reviews=$(gh api --paginate "repos/{owner}/{repo}/pulls/<PR>/reviews" --jq '.[] | select(.user.login == env.bot and .commit_id == env.sha) | "\(.id) \(.body | length > 0)"') || exit 2
     own=$(gh api --paginate "repos/{owner}/{repo}/pulls/<PR>/comments" --jq '.[] | select(.user.login == env.bot and .in_reply_to_id == null) | .pull_request_review_id') || exit 2
     hit=$(while read -r id body; do [ "$body" = true ] || grep -qx "$id" <<<"$own" && echo "$id"; done <<<"$reviews")
     if [ -z "$hit" ]; then
       hit=$(gh api --paginate "repos/{owner}/{repo}/issues/<PR>/comments" --jq '.[] | select(.user.login == env.bot) | .body as $b | ($b | split("<!-- recent_review_start -->")[1] // "" | split("<!-- recent_review_end -->")[0] // "") as $recent | if ($b | contains("review in progress")) then empty elif ($recent | contains("and " + env.sha)) then "clean round: and \(env.sha)" elif ($b | contains("rate limited")) and ($b | contains("and " + env.sha)) then "rate limited" elif ($b | contains("Reviews paused")) and .updated_at > env.since then "Reviews paused" else empty end') || exit 2
     fi
     if [ -n "$hit" ]; then
       now=$(gh pr view <PR> --json headRefOid,commits --jq '"\(.headRefOid) \(.commits[-1].committedDate)"') || exit 2
       [ "$now" = "$head" ] && { echo "$hit"; exit 0; }
       head=$now; read -r sha since <<<"$head"; export sha since   # the head moved: wait for its round
     fi
     sleep 30
   done
   echo "no review by $bot on $sha after 20 minutes"; exit 1
   ```

   It prints the review ids, or `clean round`, or `rate limited` or `Reviews paused` (paused after the head commit), which you tell the user: asking the bot to review again is theirs. A failed `gh` call stops it with exit 2 and the API error: tell the user that error. After 20 minutes it gives up; tell the user no review arrived, since the bot skips drafts and can be rate-limited.
2. After a clean round, run the block once more: a review can land just after the summary. Then read both sources of each review id it printed and list every finding before fixing any. Inline comments: `gh api --paginate "repos/{owner}/{repo}/pulls/<PR>/comments" --jq '.[] | select(.pull_request_review_id == <id>) | {id, path, line, body}'`. The review body: `gh api "repos/{owner}/{repo}/pulls/<PR>/reviews/<id>" --jq .body`. The body holds findings no inline comment carries (outside diff range, nitpick, follow-up), each headed by its lines: `` `path:12-20` ``, or `` `12-20`: `` under a file name.
3. Work them: on a per-issue PR, fix on its branch and push; on the batch PR, step 7 routes them. A skipped finding gets its reason on its thread. A body finding has no thread, so its reply is a PR comment naming its file and lines. Each push starts a new round: wait and read again until a round brings no new finding.

## 7. After the merge

- Batch PR review findings, fetched as step 6's **Review bot** says, take the route `workflow.md` sets as **Batch-review fixes**, `pr` when it sets none:
  - `pr`: fix them in a new PR against `pre-main`, so they ride the same batch.
  - `push`: a finding that passes the four fold-in tests of scope intake (step 3) is fixed in a worktree on `origin/pre-main` (step 2, with `<N>` the batch PR's number and the finding's key: `<PR>-<thread>` for an inline finding, `<PR>-<review>-<k>` for the k-th finding in a review body). Work the findings one at a time, removing each worktree (clean-up below) before the next. Rebase onto `origin/pre-main` if it moved, then push the fix as a fast-forward, never forced: `git push origin HEAD:pre-main`; the push runs the gate first (step 6). When the push is refused because `pre-main` moved meanwhile, `git fetch -q origin`, rebase and push once more, until the push lands. Then reply on the review thread with the pushed commit's SHA; that reply is the fix's record. A finding that fails a fold-in test becomes its own issue (step 3).

  Either way, a skipped finding gets its reason on the review thread.
- `Refs #N` issues: once the batch reaches `main`, swap `ready-for-agent` for `awaiting-verification` and comment the exact query, the deploy time and the due date. When the window has passed, call the Skill tool with `dk:post-deploy-check`: it runs the query and posts the verdict.
- Declining an issue: comment the reason, add `wontfix`, close.
- Clean up: `git worktree remove ~/workspace/<prefix>-<N>`, `git branch -D <branch>`. Keep `verify-assets/<N>` (step 5).

## `pre-main`

`pre-main` is shared by every open PR. The maintainer moves it and brings it level with `main` after each batch; agents reach it through PRs, or by the fast-forward push step 7 allows. The batch PR into `main` carries every merged PR's `Closes #N` or `Refs #N` line (step 6). A push that rewrites or deletes it makes the guard ask the user first.
