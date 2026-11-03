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

Capture the diff command once: `git diff <fixed-point>...HEAD` (three-dot, so the comparison is against the merge-base). Also note the list of commits via `git log <fixed-point>..HEAD --oneline`. When `git status --porcelain` shows uncommitted work, review it too: add `git diff HEAD` (staged and unstaged changes) and the untracked files from `git ls-files --others --exclude-standard`, which the sub-agents read in full as new files.

Before going further, confirm the fixed point resolves (`git rev-parse <fixed-point>`) and there is something to review: a non-empty branch diff, a non-empty `git diff HEAD`, or untracked files. A bad ref or an empty change should fail here, not inside four parallel sub-agents.

### 2. Identify the spec source

Look for the originating spec, in this order:

1. Issue references in the branch name, the commit messages or the open PR (`#123`, `Closes #45`), fetched via the workflow in the tracker doc, comments included. Comments starting `Scope amendment:` and the PR body's "Also in this PR" list extend the spec: that work counts as requested.
2. A path the user passed as an argument.
3. A spec file under `docs/`, `specs/`, or `.scratch/` matching the branch name or feature.
4. If nothing is found, ask the user where the spec is. If they say there isn't one, the **Spec** sub-agent will skip and report "no spec available".

### 3. Identify the standards sources

Read `CODING_STANDARDS.md` first (at the root and nearest to the changed files), then every doc it links or names. Then add `CONTRIBUTING.md`, the `AGENTS.md` sections that set rules for code, and any other doc in the repo on how code should be written, such as a skill `AGENTS.md` requires for edits. Those paths are the list the Standards sub-agent gets, so it reads them instead of guessing where standards live.

On top of whatever the repo documents, the Standards axis always carries the **smell baseline** below: a fixed set of Fowler code smells (_Refactoring_, ch.3) that applies even when a repo documents nothing. Two rules bind it:

- **The repo overrides.** A documented repo standard always wins; where it endorses something the baseline would flag, suppress the smell.
- **Always a nit.** Each smell is a labelled heuristic ("possible Feature Envy"), never a `should` or a `blocker`. Like any standard here, skip anything tooling already enforces.

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

- **Defensive Interior**: `try/catch`, nil checks, retries or re-validation deep inside internal code whose inputs a boundary (handler, CLI, config, external API) already validated. A guard is right only when the state it handles is legitimate, one the system may really be in; a guard against a state that should never exist hides the bug where it surfaced. → find what produced the state and fix it there; handle errors at the boundary; let internal code trust its types.
- **Swallowed Error**: a catch or error branch that logs-and-continues, returns a default, clamps a value, or drops the error without a reason the caller can see. → when the state it handles is legitimate, handle it there and name why; otherwise propagate it and fix what produced it.
- **Dead Code**: unused functions, exports, parameters or branches the change leaves behind (commented-out code is the Comments axis's). → delete it; history keeps it.
- **Deprecated API**: a call the library or this repo marks deprecated, where the replacement is available. → use the replacement.

The **comment policy** is the part of `AGENTS.md` or `CODING_STANDARDS.md` (root or nearest to the changed files) that says which comments to write or keep. Note the file and heading when one exists; it goes to the Comments sub-agent, which applies it over its default keep list.

### 4. Spawn the sub-agents in parallel

Issue all four sub-agent calls together, in the foreground, and aggregate the reports they return: Standards, Spec and Correctness with `subagent_type: "dk:reviewer"`, Comments with `subagent_type: "dk:comment-reviewer"`. Both types are read-only, so the reviewers can share one worktree. They give each finding its id and severity; each prompt hands its axis the id prefix, so ids stay unique across the four reports: `ST` for Standards, `SP` for Spec, `CO` for Correctness, `CM` for Comments.

**Standards sub-agent prompt** should include:

- The full diff command and commit list.
- The list of standards-source files you found in step 3, **plus the smell baseline from step 3** pasted in full (the sub-agent has no other access to it).
- The brief: "Report, per file/hunk where relevant, (a) every place the diff violates a documented standard: cite the standard (file + the rule); and (b) any baseline smell you spot: name it and quote the hunk. A clear breach of a documented standard is at least a `should`, one whose rule needs judgement to apply is a `nit`, and a baseline smell is always a `nit`; a documented repo standard overrides the baseline. Skip anything tooling enforces. Whether a test can fail is the Correctness axis's question unless a documented standard rules on it. Under 400 words."

**Spec sub-agent prompt** should include:

- The diff command and commit list.
- The path or fetched contents of the spec.
- The brief: "Report: (a) requirements the spec asked for that are missing or partial; (b) behaviour in the diff that wasn't asked for (scope creep), where recorded scope amendments count as asked for; (c) requirements that look implemented but where the implementation looks wrong. Quote the spec line for each finding. Under 400 words."

**Correctness sub-agent prompt** should include:

- The diff command and commit list, plus the untracked files from step 1, which it reads in full.
- The brief: "Report what breaks at runtime. Walk every item of these kinds the diff adds or changes, and answer each question for it:
  - **Side effect** (provider call, mail, webhook): what happens if the process dies between the effect and its commit? Does a retry past the lease repeat it? Does one tenant's or runner's failure block the others? Can a reader run before the lock?
  - **Query a UI renders**: does a failed load look different from an empty one? Does a failed refresh still report success?
  - **Form**: does Enter submit it before it is ready? Does a disabled control show why? Does the unsaved-changes check compare values, so an edit undone by hand reads as clean?
  - **Boundary value**: does it hold at zero, empty and nil? Are protocol tokens compared case-insensitively where the protocol says so? Does each `ORDER BY … LIMIT` have a tie-breaker? Does the server repeat the client's validation? Do a write and its audit row share a transaction?
  - **Test**: does it run the mechanism its name claims? Judge it by two imagined edits. **Break the behaviour** (the code under test returns nothing or a wrong value, skips an effect or does it twice): if the test still passes, it proves nothing. **Change the internals** (every observable result kept, the code underneath restructured): if the test now fails, it is pinned to the implementation, such as a call to an internal helper or an exact error message no caller reads; the error type callers branch on is the contract. An empty test passes the first edit: it asserts loosely or not at all (`toBeDefined`, `toBeTruthy`, `not.toThrow`); asserts only a call (`toHaveBeenCalled` without its payload), or only an empty result (`toEqual([])`) when a subject that does nothing still returns it, such as a default or initial value (a function that does nothing returns `undefined` or `None`, which fails `toEqual([])`); expects a value computed by the code under test; restates a constant, config default or prompt string; or asserts on data the test built, with no call to the subject. An absence assertion (`not.toHaveBeenCalled`, an empty result) counts when the contract promises the absence and it is paired with a presence case on another input. Fix: call the subject with one concrete input and assert the literal output or effect (for a mock, the payload it received); delete the test when no such assertion exists. Cross-row relations between tables and compile-time type tests stay.
  - **Changed doc line** (ADR, glossary, AGENTS.md): does the code it describes back it?
  For each finding, name the trigger (the crash point, the value, the order of events) and what the user or the data ends up with. Under 400 words."

**Comments sub-agent prompt** should include:

- The diff command and commit list, plus the untracked files from step 1, which it reads in full.
- The comment policy from step 3 (file and heading), or "no comment policy: use your default keep list".

Its rules live in the agent, so the prompt carries nothing more than its id prefix.

If the spec is missing, skip the Spec sub-agent and note this in the final report.

### 5. Aggregate

Present the four reports under `## Standards`, `## Spec`, `## Correctness` and `## Comments` headings, verbatim or lightly cleaned. Do **not** merge or rerank findings, because the axes are deliberately separate (see _Why separate axes_).

End with a one-line summary: findings per axis and severity, and the worst issue _within each axis_ (if any). Don't pick a single winner across axes: that's the reranking the separation exists to prevent.

### 6. Answer findings

When you wrote the change (`dk:implement` sends you here), or the user asks you to fix what the review found, answer every finding; otherwise step 5's report ends the review.

**Budget.** 3 rounds, steps 4 and 5 being round 1. Extend to 5 only when the change touches security, permissions, auth, data loss or concurrency and a blocker or should stays open with evidence, or when the user asks. When a round brings only nits and their fixes change no behaviour code, the loop ends: declined nits and comment-, doc- or format-only fixes need no new round.

1. **Judge** each finding and its severity yourself, by impact and likelihood against the change's intent, whatever label it came with. A rare path or a small cost is a nit unless its impact (data loss, security, money, a customer-visible break) makes it a blocker or should.
2. **Answer** each id in the **ledger**, a table of id, severity and outcome, kept in the scratch directory and carried into the PR body when one follows:
   - `fixed: <commit>, <the check that shows it>`: the smallest fix. Prefer deleting or narrowing code over a new lock, cache, helper or option; add one focused test that fails without the fix when the intent needs it.
   - `disagree: <why, with file:line, a test or output>`.
   - `declined: <one line>`: out of scope, or a nit. One worth doing goes through scope intake (`dk:issue-flow` step 3), and its outcome carries the issue number.

   Agree on the evidence alone, never to end the loop.
3. **Measure.** Run `git diff --shortstat <fixed-point>` before the first fix and after each round's fixes, once the checks they touch pass and the fixes are committed. When review fixes grew the diff, cut first: undo or narrow what no blocker or should needs, before another round.
4. **Next round**, only while budget remains and a blocker or should is open, or behaviour code changed since the last round. Run steps 4 and 5 again with the same diff command; each prompt adds its own axis's ledger rows and the change since the last round (`git diff <last round's HEAD>`), and asks for only the open ids and the code changed since. An open id is one no reviewer has marked `resolved` yet.

Done when no blocker or should is open on the current diff. Stuck when an id stays disputed after two replies, or the budget ends with a blocker or should open: show both sides in 2-3 lines each, and the user decides. Budget end is not approval.

Report the rounds run, the ledger, the diff's shortstat before and after, and each declined finding's issue number.

## Why separate axes

A change can pass one axis and fail another:

- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the issue asked but breaks the project's conventions → **Spec pass, Standards fail.**
- Code that follows the standards and does what the issue asked, but mails a customer twice when the process dies after the send → **Standards and Spec pass, Correctness fail.**
- Clean, correct code wrapped in comments that narrate how it was written → **Standards, Spec and Correctness pass, Comments fail.**

Reporting them separately stops one axis from masking another.
