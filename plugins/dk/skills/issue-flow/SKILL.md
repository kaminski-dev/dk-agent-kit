---
name: issue-flow
description: "How an issue travels from GitHub issue to merged PR in repos that batch through pre-main. Use when starting work on an issue (worktree, branch), reading or labelling an issue with gh, deciding whether newly found work joins the current issue, committing, attaching screenshots, opening the PR, or cleaning up after a merge."
---

# Issue flow

The shared sequence for every repo that works issue → branch → PR into `pre-main` → batch merge to `main` → deploy. The repo supplies its parameters in `docs/agents/workflow.md`: worktree prefix, branch types, fresh-worktree setup, CI names, customer-reply language, production-data policy. Read it before the first git step. Tracker commands live in `docs/agents/issue-tracker.md`, labels in `docs/agents/triage-labels.md`.

## 1. Read the issue

`gh issue view N --json title,body,labels,comments`. The issue and its comments are the record; a recalled note is background to check against them. Plain `--comments` drops the body when piped, so the `--json` form is the one that works in an agent shell. An issue labelled `spec` is an epic: its sub-issues are the work, the spec is their context.

## 2. Worktree before the first edit

One issue, one branch, one worktree, based on the remote `pre-main`:

```sh
git ls-remote --heads origin pre-main     # the local origin/pre-main ref can outlive the branch
git fetch -q origin
git worktree add ~/workspace/<prefix>-<N> -b <type>/<N>-<slug> origin/pre-main
```

When `ls-remote` prints nothing, `pre-main` is missing: ask the maintainer to restore it, branching from `main` only on their word. Run the fresh-worktree setup from `workflow.md` before any gate means anything.

Scratch files live in `$SCRATCH/<N>/` (`$SCRATCH` = the session's scratchpad directory), one directory per agent, never in the tree. Parallel agents each get their own worktree and their own scratch directory; a shared one is how two agents overwrote each other's `network-failure.ts`. `git stash` is one list across all worktrees, so set work aside with a WIP commit or a patch file in `$SCRATCH`.

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

Call the Skill tool with `dk:verify`; the proof it asks for lands here. Evidence goes into the PR, never into the tree. `dk:verify` leaves the screenshots in `$RUN/shots/`, its run directory under the session scratch (`$RUN` stands for the path it printed, written literally); push them with one command:

```sh
dk-assets push <N> "$RUN"/shots/*.png
```

It force-pushes an orphan commit with the files to `verify-assets/<N>` and prints the commit SHA, then one embeddable URL per file: paste those URLs into the PR as printed. A rerun replaces the branch. It takes files only from the session's scratch directory, and a non-zero exit (missing file, rejected push) means nothing new was pushed. The branch stays after the merge: it is the only ref that keeps the embedded commit, so deleting it would eventually break the images in the merged PR.

## 6. Open the PR

Rebase onto the current `origin/pre-main`, push the branch, and open the PR against `pre-main` (`gh pr create --base pre-main --body-file …`), body written with the `dk:pr` skill. The body carries:

- `Closes #N` when no post-deploy acceptance criterion remains, `Refs #N` when one does (a 24 h, 48 h or 7 d window on production logs or errors).
  GitHub acts on these keywords only in a PR into the default branch, so on this PR they do nothing. The batch PR into `main` repeats the line: its merge closes a `Closes #N` issue, and a `Refs #N` issue stays open for the post-deploy check (step 7).
- Every deviation from the issue, named for the maintainer's OK, and the "Also in this PR" list from scope intake.

When the change is one the customer sees, write the customer reply on the issue as `workflow.md` describes; for a change they never see (toolchain, CI, internal refactor), the PR says so instead. Merging is the maintainer's.

Wait for CI with `gh pr checks <PR> --watch --fail-fast`: it returns once every check has finished, non-zero when one failed. Right after a push it can answer "no checks reported" before CI has registered; run it again. A failed check is fixed on the branch and watched again before you report.

## 7. After the merge

- Batch PR review findings are fixed in a new PR against `pre-main`, so they ride the same batch. A skipped finding gets its reason on the review thread.
- `Refs #N` issues: once the batch reaches `main`, swap `ready-for-agent` for `awaiting-verification` and comment the exact query, the deploy time and the due date. When the window has passed, call the Skill tool with `dk:post-deploy-check`: it runs the query and posts the verdict.
- Declining an issue: comment the reason, add `wontfix`, close.
- Clean up: `git worktree remove ~/workspace/<prefix>-<N>`, `git branch -D <branch>`. Keep `verify-assets/<N>` (step 5).

## `pre-main`

`pre-main` is shared by every open PR. The maintainer moves it and brings it level with `main` after each batch; agents reach it only through PRs. The batch PR into `main` carries every merged PR's `Closes #N` or `Refs #N` line (step 6). A push that rewrites or deletes it makes the guard ask the user first.
