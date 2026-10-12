---
name: implement-spec
description: "Implement a whole epic (a spec issue and its sub-issues) on one integration branch."
argument-hint: "Spec issue number"
disable-model-invocation: true
---

You have been provided a spec: a GitHub issue labelled `spec`, whose sub-issues are the tickets that implement it. Read `docs/agents/issue-tracker.md` for the tracker commands; if it is missing, tell the user to run `/dk:setup`. Call the Skill tool with `dk:issue-flow` for the branch, scratch, commit and PR rules every agent here follows.

The goal is the entire spec implemented on a single **integration branch**, merged into `pre-main` through one PR that closes the spec and every ticket.

The tickets are not a list of steps. They are a **task graph** with blocking relationships between them. This means there is always a **frontier** of tickets which are ready to be grabbed.

Communication to and from subagents should be sparse. Communicate primarily through **context pointers**: to the spec, tickets, research notes, and previous commits. Don't duplicate information already available via pointers.

**Implementer subagents** should be run in the background where possible for maximum concurrency.

## Steps

1. Read the spec and tickets (`gh issue view <spec> --json title,body,comments` and its sub-issues) to understand the task graph.

2. (optional) Use an **exploration subagent** to conduct any exploration required by the tickets - relevant codebase files or external documentation. It saves its Markdown notes in `$SCRATCH/<spec>/notes/`, outside the repo and readable by every later subagent, so **implementer subagents** focus on implementation rather than exploration. When `docs/research/` already holds a `dk:research-codebase` document for this spec, point at it instead.

3. Create the integration branch and its worktree from the remote `pre-main`: `git worktree add ~/workspace/<prefix>-<spec> -b feat/<spec>-<slug> origin/pre-main` (prefix from `docs/agents/workflow.md`).

4. Use **implementer subagents** to implement each ticket, each in its own worktree on its own branch made from the integration branch: `git worktree add ~/workspace/<prefix>-<ticket> -b <type>/<ticket>-<slug> feat/<spec>-<slug>`. Create these worktrees yourself and hand each implementer its path; the harness's own worktree isolation branches from `main`, the wrong base. Each implementer subagent:
   - works only inside its worktree and its own `$SCRATCH/<ticket>/`;
   - calls the Skill tool with `dk:tdd` to build the ticket, committing after each green step;
   - follows the scope-intake rule from `dk:issue-flow` for anything new it finds;
   - merges the integration branch tip into its own branch and reruns the gates before reporting done.

5. Once an **implementer subagent** completes, merge its work to the integration branch with a **merger subagent**, then remove the ticket's worktree.

6. If this changes the **frontier** of available tickets, kick off more **implementer subagents** to work on the new tickets. This allows for maximum concurrency.

7. Once all tickets are complete, call the Skill tool with `dk:verify` and prove the whole spec in a running stack, then call the Skill tool with `dk:code-review` on the integration branch against `origin/pre-main`. Fix all issues raised by the code review in a single **implementer subagent**.

8. Open one PR from the integration branch into `pre-main`, body from the `dk:pr` skill, with a `Closes #N` (or `Refs #N`, per `dk:issue-flow`) line for the spec and for every ticket.

9. Clean up all remaining **implementer subagent** worktrees.
