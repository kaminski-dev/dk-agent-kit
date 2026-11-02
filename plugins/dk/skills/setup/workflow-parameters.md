# What stays in docs/agents/workflow.md

The `dk:issue-flow` skill holds the shared sequence. A repo's `workflow.md` keeps only what differs per repo:

- **Worktree**: the full command in `dk:issue-flow` step 2's form, in backticks (`git worktree add ~/workspace/<prefix>-<N> -b <type>/<N>-<slug> origin/<base>`), since the `require-worktree` hook shows the first backticked `git worktree add` line in its deny message; the allowed branch types; and the fresh-worktree setup (installs, generated files) before gates mean anything.
- **CI and deploy**: which workflows run on a PR and on `main`, and how to watch a deploy.
- **Review bot**: the bases whose PRs a review bot reviews and its login, for the wait in `dk:issue-flow` step 6.
- **Batch-review fixes**: `push` or `pr`, the route `dk:issue-flow` step 7 takes for batch PR review findings.
- **Evidence specifics**: where the browser tool writes screenshots, anything repo-specific about verify assets.
- **Post-deploy checks**: which log or error source the `awaiting-verification` query runs against.
- **Customer reply**: language, form of address, headers, tone.
- **Production data**: how one-off data fixes and backfills are delivered.

A line `dk:issue-flow` states equally goes; a line that sharpens it for this repo stays.
