---
name: setup
description: "Set up or refresh a repo's adapter files for the dk skills (tracker, labels, glossary rule, standards, workflow parameters)."
disable-model-invocation: true
---

<!-- Replaces mattpocock/skills setup-matt-pocock-skills (MIT); templates adapted from its seeds. -->

# Set up a repo for dk

The dk skills keep the shared process; each repo keeps only its own facts in small adapter files. This skill writes or refreshes them. It is idempotent: on a repo that already has them, it shows the drift and fixes only that.

| File | Holds | Read by |
|---|---|---|
| `docs/agents/issue-tracker.md` | `gh` recipes, sub-issues, blocking, scope amendments | every skill that touches issues |
| `docs/agents/triage-labels.md` | label strings | triage, to-spec, to-tickets, issue-flow |
| `docs/agents/domain.md` | glossary and ADR locations, the glossary change rule | domain-modeling, grill-with-docs, triage |
| `docs/agents/workflow.md` | repo parameters only | issue-flow |
| `docs/agents/verify.md` | stack start, stubs, seeding, login, endpoints | verify |
| `GLOSSARY.md` | the domain glossary (Matt's skills look for this name) | all |
| `CODING_STANDARDS.md` | judgement calls for review | code-review |
| `.claude/settings.json` | `env.GH_REPO` | the harness |

## 1. Explore

Read what exists before proposing anything: `git remote -v`, `AGENTS.md` / `CLAUDE.md`, `docs/agents/*`, `GLOSSARY.md` or `CONTEXT.md`, `docs/adr/`, `CODING_STANDARDS.md`, `.claude/settings.json`, `.gitignore` (are `docs/agents/` and `docs/research/` tracked? `git check-ignore -v docs/agents/x.md docs/research/x.md`), and the labels (`gh label list --json name`).

## 2. Draft, then confirm in one round

Draft every change, then show the user the list with one recommended answer per decision, worded so "yes" accepts it:

- **Tracker and labels**: fill [issue-tracker.md](issue-tracker.md) and [triage-labels.md](triage-labels.md) from the repo's existing label table and workflow; list labels to create.
- **Glossary**: rename `CONTEXT.md` to `GLOSSARY.md` with `git mv`, and update every reference (`git grep -n 'CONTEXT\.md'`, excluding vendored and generated code). Fill [domain.md](domain.md) with the repo's existing glossary change rule, quoted from its docs.
- **Coding standards**: move the judgement calls from `AGENTS.md` (a "Code defaults" section or similar) into `CODING_STANDARDS.md` per [coding-standards.md](coding-standards.md). Lines that only navigate (where a module lives, which file to read first) stay in `AGENTS.md`.
- **Workflow**: cut `docs/agents/workflow.md` down to the parameters in [workflow-parameters.md](workflow-parameters.md); the shared sequence lives in the `dk:issue-flow` skill. Keep every repo-specific fact, and drop only lines `dk:issue-flow` states equally.
- **Verify**: cut the repo's verify recipe down to `docs/agents/verify.md` with the facts the `dk:verify` skill lists under "The repo's verify doc"; the protocol lives in the skill.
- **AGENTS.md**: the pointer block below, replacing whatever section pointed at the workflow before.
- **Ignore rules**: a `.gitignore` exception for `docs/research/` when it is ignored.

Completion criterion for the draft: every file in the table above is either unchanged with a reason, or has a concrete diff.

## 3. Write through a PR

Call the Skill tool with `dk:issue-flow` and work in a worktree off `origin/pre-main` on `chore/dk-setup` (no issue number needed). Create missing labels with `gh label create`. Commit, open the PR with the `dk:pr` body, and report it. The maintainer merges.

## AGENTS.md block

```markdown
## Workflow

Issues live in GitHub Issues and move issue → worktree → PR into `pre-main` → batch merge to `main`, which deploys. The dk skills carry the shared sequence (`dk:issue-flow`); this repo's parameters are in `docs/agents/workflow.md`, tracker commands in `docs/agents/issue-tracker.md`, labels in `docs/agents/triage-labels.md`, the glossary rule in `docs/agents/domain.md`, review standards in `CODING_STANDARDS.md`.
```
