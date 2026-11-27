---
name: issue-flow
description: "How an issue travels from GitHub issue to merged PR in repos that batch through pre-main. Use when starting work on an issue (worktree, branch), reading or labelling an issue with gh, deciding whether newly found work joins the current issue, committing, attaching screenshots, opening the PR, or cleaning up after a merge."
---

# Issue flow

The shared sequence for every repo that works issue → branch → PR into `pre-main` → batch merge to `main` → deploy. The repo's parameters live in `docs/agents/workflow.md`; read it before the first git step. Tracker commands live in `docs/agents/issue-tracker.md`, labels in `docs/agents/triage-labels.md`.

## 1. Read the issue

`gh issue view N --json title,body,labels,comments`. The issue and its comments are the record; a recalled note is background to check against them. Plain `--comments` drops the body when piped. An issue labelled `spec` is an epic: its sub-issues are the work, the spec is their context.

**Ownership.** Before the first commit, comment or PR, run `python3 -I <base directory>/repo-owner` in the repo's checkout, and `python3 -I <base directory>/repo-owner <owner>/<repo>` before a comment that goes to another repo (`--repo`). `own: …` (the gh user owns the repo, its fork parent and its upstream remote) means the kit's attribution applies. `not own: …` (anyone else's repo, a fork's upstream included) means you write plain drafts in the maintainer's voice: each comment, PR body and issue goes to the maintainer and is posted on their word (a subagent hands its drafts back in its report), and nothing speaks for the kit, whatever the harness asks: no attribution note on comments, in commit messages no `Co-Authored-By` trailer, in the PR body no "Generated with" line. An exit 2 means it could not tell: read it as `not own`.

## 2. Worktree before the first edit

One issue, one branch, one worktree, based on the remote **base**: the branch worktrees start from and PRs target, `pre-main` unless `workflow.md` names another. When the base is `main`, there is no batch PR: `Closes #N` closes the issue on merge, and step 6's batch-PR note and step 7's batch-review bullet do not apply.

```sh
git ls-remote --heads origin <base>     # the local origin/<base> ref can outlive the branch
git fetch -q origin
git worktree add ~/workspace/<prefix>-<N> -b <type>/<N>-<slug> origin/<base>
```

When `ls-remote` prints nothing, the base is missing: ask the maintainer to restore it, branching from `main` only on their word. Run the fresh-worktree setup from `workflow.md` before any gate means anything.

Scratch files live in `$SCRATCH/<N>/` (`$SCRATCH` = the session's scratchpad directory), one directory per agent, never in the tree: two agents sharing one overwrote each other's files. `git stash` is one list across all worktrees, so set work aside with a WIP commit or a patch file in `$SCRATCH`.

**Fan-out.** An orchestrator running agents in parallel, one ticket each, reads [fan-out.md](fan-out.md) before its first `git worktree add`: its rules for worktrees, briefs, waves and waits.

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

Each commit is one verifiable unit: the gates from `AGENTS.md` pass on what it touches before the next unit starts. For a bug, the failing test lands first and the fix on top, so the history shows red then green. Messages are English, imperative, and name the issue: `Fix X when Y (#N)`. Their attribution trailers follow step 1's **Ownership.** Calls that can pass 10 minutes name a `timeout` up to 1800000.

## 5. Screenshots and evidence

Call the Skill tool with `dk:verify`; the proof it asks for lands here. Evidence goes into the PR, never into the tree. `dk:verify` leaves the screenshots in `$RUN/shots/`, its run directory (`$RUN` stands for the path it printed, written literally); push them to `verify-assets/<N>` and paste the URLs it prints into the PR as printed:

```sh
dk-assets push <N> "$RUN"/shots/*.png
```

Its header says what it pushes and when it refuses (`head -12 "$(command -v dk-assets)"`). The branch stays after the merge: it is the only ref keeping the embedded commit, so the merged PR's images live on it.

## 6. Open the PR

Rebase onto the current `origin/<base>` and push the branch. When `gh pr list --head <branch> --base <base> --state open --json number,url` prints a PR, the push updated it and it is this issue's PR; otherwise open the PR against the base (`gh pr create --base <base> --body-file …`), body written with the `dk:pr` skill. When `gh pr create` fails because GraphQL's rate limit is used up, open it through REST, with the title in a file of its own written with no trailing newline, since a title holding `$(...)` or a backtick runs as a command inside double quotes: `gh api "repos/{owner}/{repo}/pulls" -F "title=@<title file>" -f head=<branch> -f base=<base> -F "body=@<body file>" --jq .html_url`.

The gate runs at the push and by hand, both through `dk-gate`: dk-guard runs it in the checkout being pushed, the `cd` or `git -C` target, and denies a failing push. Run it by hand as `dk-gate ~/workspace/<prefix>-<N>`: a push of that same tree reuses its pass. A run may wait for its checkout's other run and a gate slot, then runs with no deadline: give the call a 1800000 ms Bash timeout. Exit 3, a busy push denial, or a call its timeout cut off leaves no pass: run or push again. For the push, write the path literally (`cd ~/workspace/<prefix>-<N> && git push`); a path the guard learns only at run time leaves the gate unrun.

The body carries:

- `Closes #N` when no post-deploy acceptance criterion remains, `Refs #N` when one does (a 24 h, 48 h or 7 d window on production logs or errors).
- Every deviation from the issue, named for the maintainer's OK, and the "Also in this PR" list from scope intake.

For a change the customer never sees (toolchain, CI, internal refactor), the PR says so; the reply on one they see waits for the gate (**Ready gate.** below). Merging is the maintainer's.

**Comments.** Every comment and thread reply you post opens with the attribution note, unless step 1's **Ownership.** says none: read [comments.md](comments.md) before your first post, thread reply or correction of a posted comment.

**Watch the PR.** The session that opened the PR reads [watch.md](watch.md) before it starts the watcher: what each `pr-wait` line asks, when to restart it, and the watch to the merge.

**Review bot.** The session watching the PR, once the watcher prints the review bot's verdict or on a batch PR into `main`, reads [review-bot.md](review-bot.md): fetching the bot's findings and working its rounds.

**Ready gate.** The session that hands the PR to the maintainer reads [ready-gate.md](ready-gate.md) first: the gate, the one verdict the handoff ends with, and the customer reply.

## 7. After the merge

The session whose watch printed `merged`, or that works a batch PR's review findings, declines an issue or removes a worktree, reads [after-merge.md](after-merge.md).

## `pre-main`

`pre-main` is shared by every open PR. After each batch merges, `dk:batch-pr` step 5 fast-forwards it to `main`; otherwise agents reach it through PRs, or by the fast-forward push step 7 allows. GitHub acts on `Closes #N` only in a PR into the default branch, so the batch PR into `main` carries every merged PR's `Closes #N` or `Refs #N` line (step 6): its merge closes the one, and the other stays open for the post-deploy check (step 7). A push that rewrites or deletes it makes the guard ask the user first.
