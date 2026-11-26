# Ready gate

For the session that hands a PR over to the maintainer, before its handoff (`dk:issue-flow` step 6). `<base directory>` is the skill's base directory, the folder this file sits in, written out literally.

The PR goes to the maintainer once it passes this gate on the latest commit. Read the live PR with `gh pr view <PR> --json headRefOid,state,isDraft,reviewDecision,mergeable,mergeStateStatus`: it is open, not a draft, and on its `headRefOid`:

- your proof (step 5) covers every change in the diff, the review fixes included;
- required checks are green;
- every bot finding is fixed or answered on its thread, a body finding in its PR comment;
- no human review requests changes: `gh pr view <PR> --json latestReviews --jq '.latestReviews[] | select(.state == "CHANGES_REQUESTED") | .author.login'` prints nothing;
- the branch is up to date with the base, and GitHub reports it mergeable.

`python3 -I <base directory>/pr-wait <PR> --until ready` reports the mechanical part: its `ready on <sha>` line, for that head, covers the checks, the bot's verdict, the threads and a branch neither BEHIND nor DIRTY. The proof, the answers and the human reviews are yours to check. A condition you cannot read, such as a mergeable state GitHub leaves empty, has not passed: the verdict is **Blocked**, and it names what you could not read. Your handoff of the PR ends with exactly one verdict, its last line:

- **Ready to merge**: the gate passes. The PR stays open for the maintainer to merge.
- **Waiting for required approval**: the gate passes, and only a required human approval remains (`reviewDecision` is `REVIEW_REQUIRED`).
- **Blocked**: a condition fails that you cannot fix. Name it, what you tried, and what it needs.

**Customer reply.** When the change is one the customer sees, post the reply on the issue once the gate passes, before the handoff: the review loop is over by then, so the reply describes what merges and stays as posted. Write it as `workflow.md` describes. A handoff that ends **Blocked** posts none yet.

Then the watch to the merge ([watch.md](watch.md)) starts as the handoff goes out: you start it for your own PR, and a subagent leaves it to its orchestrator, which starts it as it hands the subagent's PR over.
