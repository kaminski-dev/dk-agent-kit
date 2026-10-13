# Workflow

This repo's parameters for the sequence in the `dk:issue-flow` skill.

## Worktree

- From the repo root: `git worktree add ../app-<N> -b <type>/<N>-<slug> origin/pre-main`, with `type` one of `fix`, `feat`, `docs`, `chore`. No install step.
- The sandbox this repo runs in does not let git write `.git/config`, so `git push -u` prints an upstream error after a successful push; push with `git push origin <branch>` and pass `--head <branch>` to `gh pr create`.

## PRs and merge

- PRs target `pre-main`; the maintainer merges and batches `pre-main` into `main`.
- There is no CI; the checks in `AGENTS.md` are the gate.

## Evidence

- A store change shows the regression test red on `origin/pre-main` and green on the branch, and `python3 -m ledger history` against a seeded database before and after (see `docs/agents/verify.md`).

## Customer reply

None: the owner reads the PR.
