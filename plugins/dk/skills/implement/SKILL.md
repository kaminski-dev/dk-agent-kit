---
name: implement
description: "Implement one ticket (or a small set) end to end: worktree, TDD, review, verified PR."
argument-hint: "Issue number(s), or a spec/ticket path"
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

Call the Skill tool with `dk:issue-flow` and follow it for every git and GitHub step: reading the ticket, the worktree, scope intake, commits, evidence and the PR. Fetch each ticket and state its title before starting. If the reference is ambiguous, ask.

Call the Skill tool with `dk:tdd` where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end. Commit after each green step.

When the code is done, call the Skill tool with `dk:verify` and prove the change.

Then call the Skill tool with `dk:code-review` to review the work, and answer its findings by its **Answer findings** step: each id fixed, disagreed with or declined in the ledger, within its round budget. The PR body carries the ledger.

Finally open the PR with the body from the `dk:pr` skill, per `dk:issue-flow`.

## Several tickets

With more than one ticket, each gets an implementer subagent that runs the sequence above in its own worktree, launched by the fan-out rules in `dk:issue-flow` step 2.

Before reporting, dry-merge the tickets' branches: fetch, then run `git merge-tree --write-tree --name-only` on each branch against `origin/<base>` (the base, `dk:issue-flow` step 2) and on each pair of branches. Exit status 1 is a conflict, with the conflicting files listed after the tree id. The report names each conflict by its two tickets and its files, or says the branches merge cleanly.
