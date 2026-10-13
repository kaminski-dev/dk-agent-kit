# ledger

The audit trail behind a small customer administration: every change to a Customer is written as an Audit Operation, one row per changed field. `ledger/audit_store.py` stores and lists them; `python3 -m ledger` is the command line.

## Workflow

Issues move issue → worktree → PR into `pre-main`. The dk skills carry the shared sequence (`dk:issue-flow`); this repo's parameters are in `docs/agents/workflow.md`, tracker commands in `docs/agents/issue-tracker.md`, labels in `docs/agents/triage-labels.md`, the stack in `docs/agents/verify.md`.

## Checks

`python3 -m unittest discover -s tests` from the repo root. There is no typechecker or linter.

## Standards

`CODING_STANDARDS.md`. Domain terms are in `GLOSSARY.md`.
