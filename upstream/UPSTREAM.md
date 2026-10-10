# Upstream sources

Each vendored or ported file, the commit it was taken from, and how far it was changed. `upstream/sync.sh` shows what mattpocock/skills changed since; the pstack and HumanLayer ports are compared by hand (`git log <commit>..origin/main -- <path>` in a clone). Merging upstream changes is a manual edit through `dk:writing-for-agents`, recorded by bumping the commit here.

## mattpocock/skills (MIT) @ 49dd158

| dk skill | Upstream path | Changes |
|---|---|---|
| code-review | skills/engineering/code-review | default `origin/pre-main`; scope amendments count as requested; baseline gains Defensive Interior, Swallowed Error, Dead Code, Deprecated API, Empty Test; reviewers run as `dk:reviewer` |
| codebase-design | skills/engineering/codebase-design | as-is |
| domain-modeling | skills/engineering/domain-modeling | glossary change rule from `docs/agents/domain.md` |
| grill-with-docs | skills/engineering/grill-with-docs | `dk:` references |
| grilling | skills/productivity/grilling | as-is |
| handoff | skills/productivity/handoff | as-is |
| implement | skills/engineering/implement | `dk:issue-flow`, commit per green step, runtime proof before review, `dk:pr` |
| implement-spec | skills/engineering/implement-spec | integration branch off `origin/pre-main`, implementer worktrees from it, scratch per agent, one PR into `pre-main` |
| improve-codebase-architecture | skills/engineering/improve-codebase-architecture | `dk:` references; glossary edits by the context and the `domain.md` rule |
| pr | skills/engineering/pr | Also in this PR, Deviations, `Closes`/`Refs`, evidence on `verify-assets`, `dk:blast-radius` for one-way doors |
| prototype | skills/engineering/prototype | tracking issue, tracked paths, pushed `proto/` branch, versioned artifact titles; production never renders a variant |
| research | skills/engineering/research | narrower trigger; notes in `docs/research/` |
| retro | skills/engineering/retro | `dk:` references |
| tdd | skills/engineering/tdd | `dk:` references |
| teach | skills/productivity/teach | as-is |
| to-spec | skills/engineering/to-spec | `spec` label instead of `ready-for-agent` |
| to-tickets | skills/engineering/to-tickets | adapter files, same-place search, shared-module check |
| triage | skills/engineering/triage | adapter files, same-place and premise checks, yes-only decisions batched, parallel-wave check |
| writing-for-agents | skills/productivity/writing-for-agents | as-is |
| setup | skills/engineering/setup-matt-pocock-skills | rewritten; templates adapted |

## cursor/plugins pstack (MIT) @ d73344b

| dk file | Upstream path | Changes |
|---|---|---|
| skills/blast-radius | pstack/skills/blast-radius | model-invoked; shared-modules section; pointers to how/why/arena/unslop dropped |
| code-review Empty Test, Defensive Interior | pstack/skills/principle-test-behavior-not-implementation, principle-boundary-discipline | condensed into baseline entries |

## humanlayer/humanlayer (Apache-2.0) @ 99abe67

| dk file | Upstream path | Changes |
|---|---|---|
| skills/research-codebase | .claude/commands/research_codebase.md | ticket-blind split, single documentarian subagent, `docs/research/` output |
| agents/codebase-locator, codebase-analyzer, codebase-pattern-finder | .claude/agents/* | trimmed, positive phrasing, Bash for reads |
