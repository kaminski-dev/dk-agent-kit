---
name: code-review
description: "Review the changes since a fixed point (default origin/pre-main) along four axes: Standards (does the code follow this repo's documented coding standards and the review baseline?), Spec (does the code match what the originating issue/spec asked for?), Correctness (what breaks at runtime?) and Comments (do the comments the change adds earn their place?). Runs the reviews in parallel read-only sub-agents and reports them side by side. Use when the user wants to review a branch, a PR, work-in-progress changes, or asks to \"review since X\"."
---

Four-axis review of the diff between `HEAD` and a fixed point the user supplies:

- **Standards**: does the code conform to this repo's documented coding standards?
- **Spec**: does the code faithfully implement the originating issue / spec?
- **Correctness**: what breaks at runtime: a crash between an effect and its commit, a failure shown as empty, an edge value, a test that cannot fail?
- **Comments**: does each comment the diff adds earn its place?

The axes run as **parallel sub-agents** so they don't pollute each other's context, then this skill aggregates their findings and, when you wrote the change, answers them.

Tracker commands are in `docs/agents/issue-tracker.md`. If it is missing, tell the user to run `/dk:setup`.

## Process

### 1. Pin the fixed point

Whatever the user said is the fixed point (a commit SHA, branch name, tag, `HEAD~5`, etc.). If they didn't specify one, use `origin/pre-main` after a `git fetch -q origin`: every branch here starts from it. When `git ls-remote --heads origin pre-main` prints nothing, the repo has no `pre-main` and the fixed point is `origin/main`.

Capture the diff command once: `git diff <fixed-point>...HEAD` (three-dot, so the comparison is against the merge-base). When `git status --porcelain` shows uncommitted work, review it too: add `git diff HEAD` (staged and unstaged changes) and the untracked files from `git ls-files --others --exclude-standard`, which the sub-agents read in full as new files.

Before going further, confirm the fixed point resolves (`git rev-parse <fixed-point>`) and there is something to review: a non-empty branch diff, a non-empty `git diff HEAD`, or untracked files. A bad ref or an empty change should fail here, not inside the parallel sub-agents.

**Tier.** Run `python3 -I <base directory>/tier <fixed-point>`, with `<base directory>` the one this skill's header names, written out literally. Its one line starts with the tier, `small`, `standard` or `risky`, and says why (its `--help` gives the thresholds). The tier sets which sub-agents run (step 3) and the round budget (step 5); keep the line for the report.

### 2. Identify the spec source

Look for the originating spec, in this order:

1. Issue references in the branch name, the commit messages or the open PR (`#123`, `Closes #45`).
2. A path the user passed as an argument.
3. A spec file under `docs/`, `specs/`, or `.scratch/` matching the branch name or feature.
4. If nothing is found, ask the user where the spec is. If they say there isn't one, the review runs without Spec (step 3).

The reference is enough: the Spec reviewer reads the spec, its comments and scope amendments itself.

### 3. Spawn the sub-agents in parallel

The tier from step 1 sets the calls:

- **Small**: one `dk:reviewer` call carrying the Spec and Correctness prompts below together, with both id prefixes, reporting under a heading per axis.
- **Standard** and **risky**: Standards, Spec and Correctness, each its own `dk:reviewer` call.
- **Comments**, in every tier: one `dk:comment-reviewer` call, only when the diff adds a comment line (an added line holding a comment or docstring).

Issue the calls together, in the foreground, and aggregate the reports they return. Both agent types are read-only, so the reviewers can share one worktree. Each agent carries its axis's brief, finds the repo's standards and comment policy, and gives each finding its id and severity; the prompt hands its axis the id prefix, so ids stay unique across the reports: `ST` for Standards, `SP` for Spec, `CO` for Correctness, `CM` for Comments.

**Prompt.** Each call's prompt is this template, filled in, and nothing more:

```text
Axis: <axis>, ids <prefix>.
Fixed point: <fixed-point>. Diff: `git diff <fixed-point>...HEAD`.
Uncommitted: `git diff HEAD`; untracked files: <paths>.
Tier: <tier line>.
Spec: <issue number or path>.
Ledger: <the rows step 5's Next round names>.
```

Drop the `Uncommitted` line when step 1 found none, the `Ledger` line in round 1, and the `Spec` line from every call that does not run Spec. The small tier's call names both axes: `Axis: Spec, ids SP; Correctness, ids CO.` Without a spec, no call runs Spec, and the final report says so.

### 4. Aggregate

Present the reports under `## Standards`, `## Spec`, `## Correctness` and `## Comments` headings, verbatim or lightly cleaned, with each report's `also:` and `PR must carry:` lines verbatim; an axis left out, by the tier or by a diff that adds no comment, keeps its heading, with one line on why. Do **not** merge or rerank findings, because the axes are deliberately separate (see _Why separate axes_).

End with the tier line and a one-line summary: findings per axis and severity, and the worst issue _within each axis_ (if any). Don't pick a single winner across axes: that's the reranking the separation exists to prevent.

### 5. Answer findings

When you wrote the change (`dk:implement` sends you here), or the user asks you to fix what the review found, answer every finding; otherwise step 4's report ends the review.

**Budget.** 2 rounds, steps 3 and 4 being round 1; 1 round in the small tier, plus one with Correctness alone when a fix for a blocker changed behaviour code. In the standard and risky tiers, extend to 5 only when the change touches security, permissions, auth, data loss or concurrency and a blocker or should stays open with evidence, or when the user asks.

**Also line.** Apply the nits in each report's closing "also" line without ledger rows, skipping any you judge wrong.

1. **Judge** each finding and its severity yourself, by impact and likelihood against the change's intent, whatever label it came with. A rare path or a small cost is a nit unless its impact (data loss, security, money, a customer-visible break) makes it a blocker or should.
2. **Answer** each id in the **ledger**, a table of id, severity and outcome, kept in the scratch directory and carried into the PR body when one follows:
   - `fixed: <commit>, <the check that shows it>`: the smallest fix. Prefer deleting or narrowing code over a new lock, cache, helper or option; add one focused test that fails without the fix when the intent needs it.
   - `disagree: <why, with file:line, a test or output>`.
   - `declined: <one line>`: out of scope, or a nit. One worth doing goes through scope intake (`dk:issue-flow` step 3), and its outcome carries the issue number.

   Agree on the evidence alone, never to end the loop.
3. **Measure.** Run `git diff --shortstat <fixed-point>` before the first fix and after each round's fixes, once the checks they touch pass and the fixes are committed. When review fixes grew the diff, cut first: undo or narrow what no blocker or should needs, before another round.
4. **Next round**, only while budget remains and a fix for a Correctness or Spec blocker or `should` changed behaviour code. Every other fix ends the loop: a nit, the "also" line, a Standards or Comments finding, a declined or disputed id, and a fix that touches only tests, comments, docs or formatting. The round runs step 3 for the axis that raised each such finding plus Correctness, on the fix diff (`git diff <last round's HEAD>`) as the prompt's `Diff`, and step 4 for those axes; each prompt adds its own axis's ledger rows, each open id's original claim and `file:line` from the report that raised it, and asks for only the open ids and the code changed since. An open id is a blocker or should whose fix opened a round, until that round's reviewer marks it `resolved`; every other id closes with its ledger outcome.

Done when every id has its ledger outcome and no round the stop condition opens is left to run. Stuck when an id stays disputed after two replies, or the budget ends with a blocker or should open: show both sides in 2-3 lines each, and the user decides. Budget end is not approval.

Report the tier line, the rounds run, the axes each round ran, the ledger, the diff's shortstat before and after, and the issue number of each declined finding that scope intake filed.

## Why separate axes

A change can pass one axis and fail another:

- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the issue asked but breaks the project's conventions → **Spec pass, Standards fail.**
- Code that follows the standards and does what the issue asked, but mails a customer twice when the process dies after the send → **Standards and Spec pass, Correctness fail.**
- Clean, correct code wrapped in comments that narrate how it was written → **Standards, Spec and Correctness pass, Comments fail.**

Reporting them separately stops one axis from masking another.
