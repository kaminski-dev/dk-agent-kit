# dk-agent-kit

A Claude Code marketplace with two plugins: `dk-guard` (hooks and the `dk-pg`, `dk-gc` and `dk-assets` commands, always on) and `dk` (skills and agents). `README.md` covers install and layout.

## Rules

1. **Every skill or agent edit goes through the `dk:writing-for-agents` skill.** Call it before writing.
2. **A repeated mistake becomes a check, not more prose.** Guard changes start with a failing case in `tests/hooks/guard_bash_cases.json`, and get replayed against past transcripts with `tests/hooks/replay_history.py` before they ship.
3. **Vendored files keep their provenance.** A change to a file from mattpocock/skills, pstack, tstack or HumanLayer updates its row in `upstream/UPSTREAM.md`; HumanLayer files also update their "Modified" notice (Apache-2.0).
4. **Cross-skill calls name the skill with its `dk:` prefix.** A bare name can resolve to a built-in skill (`/code-review` exists in Claude Code).
5. **Changes reach `main` through a PR.** The guard blocks direct pushes to `main`.

## Workflow

Issues live in GitHub Issues and move issue → worktree → PR into `main`. The dk skills carry the shared sequence (`dk:issue-flow`); this repo's parameters are in `docs/agents/workflow.md`, tracker commands in `docs/agents/issue-tracker.md`, labels in `docs/agents/triage-labels.md`.

## Checks

`python3 -I tests/run.py <base>` runs the checks the changes since `<base>` need (the branch's base, `origin/main` unless the work branched elsewhere), plus the always-on ones; `python3 -I tests/run.py` runs every check, as CI does. A new test file needs its row in the map in `tests/run.py`; `tests/test_run.py` fails until it has one. `claude plugin validate .` is one of the checks: its only expected warning is the missing `version`, once per plugin, left out on purpose so installs track commits.
