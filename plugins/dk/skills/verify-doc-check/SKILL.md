---
name: verify-doc-check
description: "Monthly check that this repo's docs/agents/verify.md still starts the stack: read every claim against the source, run the recipe in a fresh worktree, fix or file each drifted step."
disable-model-invocation: true
---

<!-- Adapted from cursor/plugins pstack@d73344b skills/maintain-verification-skill, MIT (© 2026 Lauren Tan). Changed for dk-agent-kit: the target is docs/agents/verify.md run under the dk:verify protocol, readers per doc section, drift fixed in a PR into pre-main or filed as a needs-triage issue. -->

# Verify doc check

A verify doc rots the moment the stack changes: a renamed env var, a moved script, a port that is no longer free. This check runs the repo's `docs/agents/verify.md` the way the next `dk:verify` run will, from the doc alone, and turns each step that fails into a fix or an issue. One run covers one repo.

**From the doc alone** means: the doc, the fresh-worktree setup in `docs/agents/workflow.md`, and the `dk:verify` protocol. Every other fact you needed to get a step through (a README line, a file from the main checkout, a memory, a guess that worked) is **drift**: a fact the doc owes.

`$RUN` is `$SCRATCH/verify-doc/<repo>/`. Wherever the doc writes `<N>`, use the key `verify-doc`.

## Outcome

Name one in the report:

- **clean**: every section read against the source and every step run; nothing drifted.
- **changed**: drift found; each instance fixed in the PR or filed as an issue.
- **blocked**: a step could not run for a reason outside the doc (Docker down, no network, a login only the maintainer holds). Name the step and the reason.

## Edit scope

A fix touches only the doc and the harness it names (its scripts, stubs, helpers). Each failing step is one of three kinds:

- **Doc drift**: the doc says something the repo no longer does or lacks a fact the run needed. Fix the doc.
- **Harness gap**: the repo works, but a script the doc names cannot drive it. Fix the script.
- **Product gap**: the app itself is broken. File it as an issue; the doc keeps describing correct behaviour.

## 1. Fresh worktree

```sh
git fetch -q origin
git worktree add --detach "$RUN/tree" origin/pre-main
```

When `git ls-remote --heads origin pre-main` prints nothing, base it on `origin/main` and say so in the report. Run the fresh-worktree setup from `workflow.md` in it. No `docs/agents/verify.md` there: stop and point at `/dk:setup`.

Start `$RUN/run.md`, the **run log**: one line per doc step with the command as run, the result, and its kind when it failed. It stays in `$RUN`, never in the tree.

Done when `$RUN/tree` is checked out at the base you name in the report, the fresh-worktree setup exited zero there, and `$RUN/run.md` exists.

## 2. Source wave

Split the doc by its sections (stack start, database, stubs, seeding, login, endpoints, browser, and any others it has). Launch one read-only `dk:codebase-analyzer` per section, all in one message. Each gets the section's text and the worktree path, checks every claim it makes against the source (each script and path exists, each env var is read under that name, each port, route, seeded user and migration tool matches), and returns: claims confirmed, likely drift with `file:line`, and the one live step that exercises the section.

Done when every section has a returned list. Spot-check each cited drift yourself before it counts.

## 3. Live pass

Run the doc's recipe in its own order, exactly as written, under `dk:verify` steps 2 and 3 (ports checked before each start, every process and port noted). Exercise every section at least once:

- the stack starts and its health or ready endpoint answers;
- the database migrates, and the Down half runs down and up again;
- each stub the doc names starts, or its absence shows the log line the doc quotes;
- seeding runs on the migrated database;
- the login yields a read and a write that succeed;
- one route under each endpoint prefix answers;
- the frontend loads at 1280 px and at 390 × 844 and the seeded user logs in.

A step that fails: log it with its output, find the variant that works, log that too, and go on with the variant so the later steps still run. A step you cannot reach is **unreachable** only with the prerequisite it needs and the route you tried. The live pass is required even when the source wave came back clean.

Done when every step has a line in the run log.

## 4. Tear down

`dk:verify` step 7, then `git worktree remove "$RUN/tree"`. Done when none of your ports listens, `dk-pg url verify-doc` finds no database, and the worktree is gone.

## 5. Fix or file

- **Doc drift and harness gaps**: one PR through `dk:issue-flow` (one issue for the run, its branch off `pre-main`), carrying each fix. Run every fixed step again in a fresh worktree of the branch before opening it; the PR's Evidence is the failing run-log line beside the passing one.
- **Product gaps**, and drift you cannot prove a fix for: one issue each, labelled `needs-triage`, opening with `Found by the verify doc check` and the run-log lines. Search open issues first (`dk:issue-flow` step 3) and comment on a match instead.

Done when every failed line in the run log names the PR that fixes it or the issue (new or commented) that records it.

Report the outcome, the run-log path, and the PR and issues.
