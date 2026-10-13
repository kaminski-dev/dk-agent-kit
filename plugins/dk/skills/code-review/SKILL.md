---
name: code-review
description: "Review the changes since a fixed point (default origin/pre-main) along three axes: Standards (does the code follow this repo's documented coding standards and the review baseline?), Spec (does the code match what the originating issue/spec asked for?) and Comments (do the comments the change adds earn their place?). Runs the reviews in parallel read-only sub-agents and reports them side by side. Use when the user wants to review a branch, a PR, work-in-progress changes, or asks to \"review since X\"."
---

Three-axis review of the diff between `HEAD` and a fixed point the user supplies:

- **Standards**: does the code conform to this repo's documented coding standards?
- **Spec**: does the code faithfully implement the originating issue / spec?
- **Comments**: does each comment the diff adds earn its place?

The axes run as **parallel sub-agents** so they don't pollute each other's context, then this skill aggregates their findings.

Tracker commands are in `docs/agents/issue-tracker.md`. If it is missing, tell the user to run `/dk:setup`.

## Process

### 1. Pin the fixed point

Whatever the user said is the fixed point (a commit SHA, branch name, tag, `HEAD~5`, etc.). If they didn't specify one, use `origin/pre-main` after a `git fetch -q origin`: every branch here starts from it. When `git ls-remote --heads origin pre-main` prints nothing, the repo has no `pre-main` and the fixed point is `origin/main`.

Capture the diff command once: `git diff <fixed-point>...HEAD` (three-dot, so the comparison is against the merge-base). Also note the list of commits via `git log <fixed-point>..HEAD --oneline`. When `git status --porcelain` shows uncommitted work, review it too: add `git diff HEAD` (staged and unstaged changes) and the untracked files from `git ls-files --others --exclude-standard`, which the sub-agents read in full as new files.

Before going further, confirm the fixed point resolves (`git rev-parse <fixed-point>`) and there is something to review: a non-empty branch diff, a non-empty `git diff HEAD`, or untracked files. A bad ref or an empty change should fail here, not inside three parallel sub-agents.

### 2. Identify the spec source

Look for the originating spec, in this order:

1. Issue references in the branch name, the commit messages or the open PR (`#123`, `Closes #45`), fetched via the workflow in the tracker doc, comments included. Comments starting `Scope amendment:` and the PR body's "Also in this PR" list extend the spec: that work counts as requested.
2. A path the user passed as an argument.
3. A spec file under `docs/`, `specs/`, or `.scratch/` matching the branch name or feature.
4. If nothing is found, ask the user where the spec is. If they say there isn't one, the **Spec** sub-agent will skip and report "no spec available".

### 3. Identify the standards sources

Search the repo for every file that documents how code should be written. When `CODING_STANDARDS.md` or `CONTRIBUTING.md` exists, it must be on the list.

On top of whatever the repo documents, the Standards axis always carries the **smell baseline** below: a fixed set of Fowler code smells (_Refactoring_, ch.3) that applies even when a repo documents nothing. Two rules bind it:

- **The repo overrides.** A documented repo standard always wins; where it endorses something the baseline would flag, suppress the smell.
- **Always a judgement call.** Each smell is a labelled heuristic ("possible Feature Envy"), never a hard violation. Like any standard here, skip anything tooling already enforces.

Each smell reads *what it is* → *how to fix*; match it against the diff:

- **Mysterious Name**: a function, variable, or type whose name doesn't reveal what it does or holds. → rename it; if no honest name comes, the design's murky.
- **Duplicated Code**: the same logic shape appears in more than one hunk or file in the change. → extract the shared shape, call it from both.
- **Feature Envy**: a method that reaches into another object's data more than its own. → move the method onto the data it envies.
- **Data Clumps**: the same few fields or params keep travelling together (a type wanting to be born). → bundle them into one type, pass that.
- **Primitive Obsession**: a primitive or string standing in for a domain concept that deserves its own type. → give the concept its own small type.
- **Repeated Switches**: the same `switch`/`if`-cascade on the same type recurs across the change. → replace with polymorphism, or one map both sites share.
- **Shotgun Surgery**: one logical change forces scattered edits across many files in the diff. → gather what changes together into one module.
- **Divergent Change**: one file or module is edited for several unrelated reasons. → split so each module changes for one reason.
- **Speculative Generality**: abstraction, parameters, or hooks added for needs the spec doesn't have. → delete it; inline back until a real need shows.
- **Message Chains**: long `a.b().c().d()` navigation the caller shouldn't depend on. → hide the walk behind one method on the first object.
- **Middle Man**: a class or function that mostly just delegates onward. → cut it, call the real target direct.
- **Refused Bequest**: a subclass or implementer that ignores or overrides most of what it inherits. → drop the inheritance, use composition.

The baseline also covers what agents add that Fowler's list misses. Same two rules apply:

- **Defensive Interior**: `try/catch`, nil checks or re-validation deep inside internal code whose inputs a boundary (handler, CLI, config, external API) already validated. → handle errors at the boundary; let internal code trust its types.
- **Swallowed Error**: a catch or error branch that logs-and-continues, returns a default, or drops the error without a reason the caller can see. → propagate it, or name why it is safe to drop.
- **Dead Code**: unused functions, exports, parameters or branches the change leaves behind (commented-out code is the Comments axis's). → delete it; history keeps it.
- **Deprecated API**: a call the library or this repo marks deprecated, where the replacement is available. → use the replacement.
- **Empty Test**: a test that would still pass if every function it imports returned `undefined` or a wrong value, so it cannot fail for a defect: a loose or missing assertion (`toBeDefined`, `toBeTruthy`, `not.toThrow`); a call or an empty result as the only assertion (`toHaveBeenCalled` without its payload, `toEqual([])`), which a subject that does nothing also passes; an expected value computed by the code under test; a restated constant, config default or prompt string; assertions on data the test built, with no call to the subject. → call the subject with one concrete input and assert the literal output or effect (for a mock, the payload it received); delete the test when no such assertion exists. Cross-row relations between tables and compile-time type tests stay.

The **comment policy** is the part of `AGENTS.md` or `CODING_STANDARDS.md` (root or nearest to the changed files) that says which comments to write or keep. Note the file and heading when one exists; it goes to the Comments sub-agent, which applies it over its default keep list.

### 4. Spawn the sub-agents in parallel

Issue all three sub-agent calls together, in the foreground, and aggregate the reports they return: Standards and Spec with `subagent_type: "dk:reviewer"`, Comments with `subagent_type: "dk:comment-reviewer"`. Both types are read-only, so the reviewers can share one worktree.

**Standards sub-agent prompt** should include:

- The full diff command and commit list.
- The list of standards-source files you found in step 3, **plus the smell baseline from step 3** pasted in full (the sub-agent has no other access to it).
- The brief: "Report, per file/hunk where relevant, (a) every place the diff violates a documented standard: cite the standard (file + the rule); and (b) any baseline smell you spot: name it and quote the hunk. Distinguish hard violations from judgement calls: documented-standard breaches can be hard, but baseline smells are always judgement calls, and a documented repo standard overrides the baseline. Skip anything tooling enforces. Under 400 words."

**Spec sub-agent prompt** should include:

- The diff command and commit list.
- The path or fetched contents of the spec.
- The brief: "Report: (a) requirements the spec asked for that are missing or partial; (b) behaviour in the diff that wasn't asked for (scope creep), where recorded scope amendments count as asked for; (c) requirements that look implemented but where the implementation looks wrong. Quote the spec line for each finding. Under 400 words."

**Comments sub-agent prompt** should include:

- The diff command and commit list, plus the untracked files from step 1, which it reads in full.
- The comment policy from step 3 (file and heading), or "no comment policy: use your default keep list".

Its rules live in the agent, so the prompt carries nothing more.

If the spec is missing, skip the Spec sub-agent and note this in the final report.

### 5. Aggregate

Present the three reports under `## Standards`, `## Spec` and `## Comments` headings, verbatim or lightly cleaned. Do **not** merge or rerank findings, because the axes are deliberately separate (see _Why separate axes_).

End with a one-line summary: total findings per axis, and the worst issue _within each axis_ (if any). Don't pick a single winner across axes: that's the reranking the separation exists to prevent.

## Why separate axes

A change can pass one axis and fail another:

- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the issue asked but breaks the project's conventions → **Spec pass, Standards fail.**
- Clean, correct code wrapped in comments that narrate how it was written → **Standards and Spec pass, Comments fail.**

Reporting them separately stops one axis from masking another.
