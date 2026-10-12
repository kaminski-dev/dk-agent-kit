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

When the code is done, call the Skill tool with `dk:verify` and prove the change in a stack you started. Passing gates are the floor, never the proof.

Then call the Skill tool with `dk:code-review` to review the work, and fix what it finds.

Finally open the PR with the body from the `dk:pr` skill, per `dk:issue-flow`.
