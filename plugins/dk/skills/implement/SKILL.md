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

**Tier.** When the code is done, run `python3 -I <base directory>/../code-review/tier <base>`, with `<base directory>` the one this skill's header names and `<base>` the branch's base, both written out literally. `dk:verify`, `dk:code-review` and `dk:pr` each read it themselves: a small change gets a red/green test, one reviewer for one round (a second when a behaviour fix reopens review) and the short PR body, and a risky one adds blast radius to the PR.

Then call the Skill tool with `dk:verify` and prove the change.

Then call the Skill tool with `dk:code-review` to review the work, and answer its findings by its **Answer findings** step: each id fixed, disagreed with or declined in the ledger, within its round budget. The PR body carries the ledger.

Finally open the PR with the body from the `dk:pr` skill, per `dk:issue-flow`.

## Asking

A question in a plain message reads like a finished run, so it goes unseen. When the maintainer has said they are away for the run, ask only for one of these reasons:

- no proof of the change is possible;
- the ready gate (`dk:issue-flow` step 6) cannot pass, and you cannot fix that yourself;
- the next step is outside the grant, which is this issue's worktree, branch and PR: deleting data, touching production, changing anything outside the repo, closing a PR, or force-pushing another branch;
- the goal is ambiguous in a way that changes the result;
- another PR makes this one obsolete.

Ask through the AskUserQuestion tool, and put the PR link when one exists, what blocks you and the options in the question, your recommendation first. With no question tool, or no answer from it, take the safe path: stop where the work stands, and open your final message with the question.

Decide everything else with a sensible default, including the seams `dk:tdd` asks you to agree, and list each decision under **Decisions taken** in the report.

## Several tickets

With more than one ticket, each gets an implementer subagent that runs the sequence above in its own worktree, launched by the fan-out rules in `dk:issue-flow` step 2. Launch them in the background, so each implementer's return wakes you on its own.

As each implementer returns, hand its PR over in its own message: the report below for that PR, ending with its verdict. Implementers that return together still get one message each, and the dry-merge starts only after the last of them is sent. A small PR then reaches the maintainer when its own run ends, not when the wave's slowest one does.

Once the last implementer returns and its PR is handed over, dry-merge the tickets' branches: fetch, then run `git merge-tree --write-tree --name-only` on each branch against `origin/<base>` (the base, `dk:issue-flow` step 2) and on each pair of branches. Exit status 1 is a conflict, with the conflicting files listed after the tree id. The dry-merge message names each conflict by its two tickets and its files, or says the branches merge cleanly. Each conflicting pair gets a merge order: the PR whose verdict is **Ready to merge** merges first, the one handed over first when both or neither are. The message says that you rebase the later branch onto `origin/<base>` once the first PR has merged (its watcher's `merged` line, or the maintainer's word), resolve the conflict, push, and hand the later PR over again with its new head and verdict.

## Report

Each PR's report carries the PR link and its head, the tier line, the proof, `dk:code-review`'s **Answer findings** report (the rounds run, the ledger, the shortstat before and after, each declined finding's issue number), the **Decisions taken** with the reason for each, and the risks that remain. It ends with the verdict from `dk:issue-flow` step 6's **Ready gate.**, one per PR. With one ticket the report is the final message; with several, each handover message is its PR's report and the dry-merge message comes last. A run stopped before any PR reports where it stopped, the question and the **Decisions taken**, and ends on the question, with no verdict line.
