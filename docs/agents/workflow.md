# Workflow

This repo's parameters for the sequence in the `dk:issue-flow` skill. The kit differs from the client repos in one way: there is no `pre-main` and no deploy.

## Worktree

- Path and branch: `git worktree add ~/workspace/dk-agent-kit-<issue> -b <type>/<issue>-<slug> origin/main`, with `type` one of `fix`, `feat`, `docs`, `chore`. No install step.

## PRs and merge

- PRs target `main`; the maintainer merges. `Closes #N` closes the issue on merge, so there is no batch PR and no post-deploy check.
- CI (`.github/workflows/test.yml`) runs the checks from `AGENTS.md` on every push and PR.
- A merge reaches the maintainer's sessions after `git -C ~/workspace/dk-agent-kit pull` and `/reload-plugins`: the plugins load from that checkout.

## Evidence

- A hook or guard change shows the failing case from `tests/hooks/guard_bash_cases.json` before and after, and its replay against past transcripts.
- A skill change that alters behaviour shows one run of the skill on a real issue, or says why none was possible.

## Customer reply

None: the kit has no customer.
