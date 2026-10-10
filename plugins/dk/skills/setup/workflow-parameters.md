# What stays in docs/agents/workflow.md

The `dk:issue-flow` skill holds the shared sequence. A repo's `workflow.md` keeps only what differs per repo:

- **Worktree**: the path prefix (`~/workspace/<prefix>-<N>`), the allowed branch types, and the fresh-worktree setup (installs, generated files) before gates mean anything.
- **CI and deploy**: which workflows run on a PR and on `main`, and how to watch a deploy.
- **Evidence specifics**: where the browser tool writes screenshots, anything repo-specific about verify assets.
- **Post-deploy checks**: which log or error source the `awaiting-verification` query runs against.
- **Customer reply**: language, form of address, headers, tone.
- **Production data**: how one-off data fixes and backfills are delivered.

A line `dk:issue-flow` states equally goes; a line that sharpens it for this repo stays.
