# Upstream sources

Each vendored or ported file, the commit it was taken from, and how far it was changed. `upstream/sync.sh` reads this file and shows, per source, what changed upstream in the adapted paths since the recorded commit. Merging upstream changes is a manual edit through `dk:writing-for-agents`, recorded by bumping the commit here.

`sync.sh` parses two things, so keep them in this shape:

- **Section heading**: `## <owner>/<repo> [label] (<license>) @ <short commit>`. The first word is the GitHub repo; the commit ends the line. One commit per section: a file taken at another commit of the same repo gets its own section.
- **Upstream path column** (the second): paths from the repo root, comma-separated, no globs and no shorthand (`pstack/skills/a, pstack/skills/b`, not `pstack/skills/a, b`). A directory covers everything under it. Backticks are ignored.

## mattpocock/skills (MIT) @ 49dd158

| dk skill | Upstream path | Changes |
|---|---|---|
| code-review | skills/engineering/code-review | default `origin/pre-main`; uncommitted and untracked work reviewed too; scope amendments count as requested; baseline gains Defensive Interior, Swallowed Error, Dead Code, Deprecated API, Empty Test; reviewers run as `dk:reviewer`; Comments axis run by `dk:comment-reviewer`; falls back to `origin/main` without `pre-main` |
| codebase-design | skills/engineering/codebase-design | as-is |
| domain-modeling | skills/engineering/domain-modeling | glossary change rule from `docs/agents/domain.md` |
| grill-with-docs | skills/engineering/grill-with-docs | `dk:` references |
| grilling | skills/productivity/grilling | as-is |
| handoff | skills/productivity/handoff | as-is |
| implement | skills/engineering/implement | `dk:issue-flow`, commit per green step, `dk:verify` before review, `dk:pr` |
| implement-spec | skills/engineering/implement-spec | integration branch off `origin/pre-main`, implementer worktrees from it, scratch per agent, `dk:verify` on the whole spec, one PR into `pre-main` |
| improve-codebase-architecture | skills/engineering/improve-codebase-architecture | `dk:` references; glossary edits by the context and the `domain.md` rule |
| pr | skills/engineering/pr | Also in this PR, Deviations, `Closes`/`Refs` (repeated on the batch PR), evidence on `verify-assets`, `dk:blast-radius` for one-way doors |
| prototype | skills/engineering/prototype | tracking issue, tracked paths, pushed `proto/` branch, versioned artifact titles; production never renders a variant |
| research | skills/engineering/research | narrower trigger; notes in `docs/research/` |
| retro | skills/engineering/retro | `dk:` references |
| tdd | skills/engineering/tdd | `dk:` references |
| teach | skills/productivity/teach | as-is |
| to-spec | skills/engineering/to-spec | `spec` label instead of `ready-for-agent` |
| to-tickets | skills/engineering/to-tickets | adapter files, same-place search, shared-module check; Blocked by only when a ticket gates it |
| triage | skills/engineering/triage | adapter files, same-place and premise checks, yes-only decisions batched, parallel-wave check; brief gains an optional Blocked by line |
| writing-for-agents | skills/productivity/writing-for-agents | as-is |
| setup | skills/engineering/setup-matt-pocock-skills | rewritten; templates adapted; `docs/agents/verify.md` row and Verify step for `dk:verify` |

## cursor/plugins pstack (MIT) @ d73344b

| dk file | Upstream path | Changes |
|---|---|---|
| skills/blast-radius | pstack/skills/blast-radius | model-invoked; shared-modules section; pointers to how/why/arena/unslop dropped |
| code-review Empty Test, Defensive Interior | pstack/skills/principle-test-behavior-not-implementation, pstack/skills/principle-boundary-discipline | condensed into baseline entries |
| agents/comment-reviewer | pstack/agents/comment-sicko.md | scoped to comments on added lines; Restates (Reshape folded in), Narrates history, Stale, Commented-out code findings; Suppression left to Standards; repo comment policy overrides the keep list; report only, persona and `/how` `/why` calls dropped |

## humanlayer/humanlayer (Apache-2.0) @ 99abe67

| dk file | Upstream path | Changes |
|---|---|---|
| skills/research-codebase | .claude/commands/research_codebase.md | ticket-blind split, single documentarian subagent, `docs/research/` output |
| agents/codebase-locator, codebase-analyzer, codebase-pattern-finder | .claude/agents/codebase-locator.md, .claude/agents/codebase-analyzer.md, .claude/agents/codebase-pattern-finder.md | trimmed, positive phrasing, Bash for reads |
