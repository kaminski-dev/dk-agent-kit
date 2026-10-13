# Workflow

This repo's parameters for the sequence in the `dk:issue-flow` skill. The kit differs from the client repos in one way: there is no `pre-main` and no deploy.

## Worktree

- Path and branch: `git worktree add ~/workspace/dk-agent-kit-<issue> -b <type>/<issue>-<slug> origin/main`, with `type` one of `fix`, `feat`, `docs`, `chore`. No install step.

## PRs and merge

- PRs target `main`; the maintainer merges. `Closes #N` closes the issue on merge, so there is no batch PR and no post-deploy check.
- CI (`.github/workflows/test.yml`) runs the checks from `AGENTS.md` on every push and PR.
- A merge reaches the maintainer's sessions after `git -C ~/workspace/dk-agent-kit pull` and `/reload-plugins`: the plugins load from that checkout.

## Evidence

- A guard change shows the failing case from `tests/hooks/guard_bash_cases.json` before and after, and its replay against past transcripts.
- A Stop gate change shows its case in `tests/hooks/test_stop_gate.py` before and after, and a headless session (`claude -p --plugin-dir plugins/dk-guard`) with and without the change.
- A session hook change (`require-worktree`, `session-baseline`) shows its fixture case in `tests/hooks/test_require_worktree.py` or `tests/hooks/test_session_baseline.py` before and after, and a headless session (`claude -p --plugin-dir plugins/dk-guard`) with the change.
- A skill change that alters behaviour shows one run of the skill on a real issue, or says why none was possible.
- A change to `dk:implement`, `dk:triage`, `dk:code-review` or `dk:verify` also shows its eval run: `claude plugin eval plugins/dk --case '<skill>-*' --trust-plugin --scaffold --allow-tools Bash Write Edit --ablation none --no-publish`. The cases replay jetztbar #1091 and clientdata #353 on fixture repos in `plugins/dk/evals/`, plus the skill branches that broke before (#35: uncommitted and untracked work in a review, an issue too thin for a brief, a repo with no database), with stand-ins for `gh`, `govulncheck`, `dk-pg` and the Postgres binaries, so no run reaches GitHub or starts a database. They make paid model calls, so CI runs only `tests/test_evals.py`, which checks the fixtures are red before the fix.

## Customer reply

None: the kit has no customer.
