# Workflow

This repo's parameters for the sequence in the `dk:issue-flow` skill.

## Worktree

- From the repo root: `git worktree add ../api-<N> -b <type>/<N>-<slug> origin/pre-main`, with `type` one of `fix`, `feat`, `docs`, `chore`. Then `go mod download`.

## PRs and merge

- PRs target `pre-main`; the maintainer merges and batches `pre-main` into `main`, which deploys.
- CI: `ci-go` (test, lint, Go Vulnerability Check) on every PR; `build-push` on `main`.

## Customer reply

None for toolchain and dependency changes: the PR says the customer does not see it.
