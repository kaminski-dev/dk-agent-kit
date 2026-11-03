# Upstream sources

Each vendored or ported file, the commit it was taken from, and how far it was changed. `upstream/sync.sh` reads this file and shows, per source, what changed upstream in the adapted paths since the recorded commit. Merging upstream changes is a manual edit through `dk:writing-for-agents`, recorded by bumping the commit here.

`sync.sh` parses two things, so keep them in this shape (`tests/test_skills.py` fails on either one broken):

- **Section heading**: `## <owner>/<repo> [label] (<license>) @ <short commit>`. The first word is the GitHub repo; the commit ends the line. One commit per section: a file taken at another commit of the same repo gets its own section.
- **Upstream path column** (the second): paths from the repo root, comma-separated, no globs and no shorthand (`pstack/skills/a, pstack/skills/b`, not `pstack/skills/a, b`). A directory covers everything under it. Backticks are ignored.

## mattpocock/skills (MIT) @ 49dd158

| dk skill | Upstream path | Changes |
|---|---|---|
| code-review | skills/engineering/code-review | default `origin/pre-main`; uncommitted and untracked work reviewed too; scope amendments count as requested; baseline gains Defensive Interior, Swallowed Error, Dead Code, Deprecated API; reviewers run as `dk:reviewer`; Comments axis run by `dk:comment-reviewer`; fourth axis Correctness (crash windows, failed state shown as empty, boundary values, tests that cannot fail, doc lines the code does not back), whose test question carries the Empty Test checklist; standards sources start at `CODING_STANDARDS.md`; falls back to `origin/main` without `pre-main` |
| codebase-design | skills/engineering/codebase-design | as-is |
| domain-modeling | skills/engineering/domain-modeling | glossary change rule from `docs/agents/domain.md` |
| grill-with-docs | skills/engineering/grill-with-docs | `dk:` references |
| grilling | skills/productivity/grilling | as-is |
| handoff | skills/productivity/handoff | as-is |
| implement | skills/engineering/implement | `dk:issue-flow`, commit per green step, `dk:verify` before review, `dk:pr`; several tickets fan out by `dk:issue-flow` step 2 and are dry-merged with `git merge-tree` before the report |
| implement-spec | skills/engineering/implement-spec | integration branch off the base from `workflow.md` (`pre-main` by default), implementer worktrees from it launched by `dk:issue-flow` step 2's fan-out rules, scratch per agent, `dk:verify` on the whole spec, one PR into the base |
| improve-codebase-architecture | skills/engineering/improve-codebase-architecture | `dk:` references; glossary edits by the context and the `domain.md` rule |
| pr | skills/engineering/pr | Also in this PR, Deviations, `Closes`/`Refs` (repeated on the batch PR), evidence on `verify-assets`, `dk:blast-radius` for one-way doors |
| prototype | skills/engineering/prototype | tracking issue, tracked paths, pushed `proto/` branch, versioned artifact titles; production never renders a variant |
| research | skills/engineering/research | narrower trigger; notes in `docs/research/` |
| retro | skills/engineering/retro | `dk:` references; a window of sessions, extracted by `extract.py`; correct step and rule-to-check table from pstack |
| tdd | skills/engineering/tdd | `dk:` references |
| teach | skills/productivity/teach | as-is |
| to-spec | skills/engineering/to-spec | `spec` label instead of `ready-for-agent` |
| to-tickets | skills/engineering/to-tickets | adapter files, same-place search, shared-module check; Blocked by only when a ticket gates it |
| triage | skills/engineering/triage | adapter files, same-place and premise checks, yes-only decisions batched, parallel-wave check; brief gains an optional Blocked by line; ready list (`ready.py`) asks about origin's repo whatever GH_REPO says, and leaves out issues with an open blocker, native (every page) or a body line; verify step runs the failing check the issue names and is done when the report quotes each command with its exit status; a bug whose check could not run goes to `needs-info` |
| writing-for-agents | skills/productivity/writing-for-agents | as-is |
| setup | skills/engineering/setup-matt-pocock-skills | rewritten; templates adapted; `docs/agents/verify.md` row and Verify step for `dk:verify`; Batch-review fixes and Review bot workflow parameters; Worktree parameter is the full backticked `git worktree add` command the `require-worktree` hook reads; tracker template gains the Ready list and the blocker read, every page |

## cursor/plugins pstack (MIT) @ 1dcc2ba

| dk file | Upstream path | Changes |
|---|---|---|
| skills/blast-radius | pstack/skills/blast-radius | model-invoked; shared-modules section; pointers to how/why/arena/unslop dropped |
| skills/retro correct step, rule-to-check table | pstack/skills/correct | folded into the retro as a step; proposes fixes instead of making them; table in the retro report, not the instruction file |
| code-review Empty Test, Defensive Interior | pstack/skills/principle-test-behavior-not-implementation, pstack/skills/principle-boundary-discipline | condensed: Defensive Interior into a baseline entry, Empty Test into the Correctness axis's test question, its empty-result shape narrowed to no-op subjects |
| skills/verify-doc-check | pstack/skills/maintain-verification-skill | target is `docs/agents/verify.md` under `dk:verify`; readers per doc section; worktree on `origin/pre-main`, `origin/main` without it; fixes in one PR into `pre-main`, product gaps as `needs-triage` issues; teardown proven by `dk-pg status` |
| agents/comment-reviewer | pstack/agents/comment-sicko.md | scoped to comments on added lines; Restates (Reshape folded in), Narrates history, Stale, Commented-out code findings; Suppression left to Standards; repo comment policy overrides the keep list; report only, persona and `/how` `/why` calls dropped |

## humanlayer/humanlayer (Apache-2.0) @ 99abe67

| dk file | Upstream path | Changes |
|---|---|---|
| skills/research-codebase | .claude/commands/research_codebase.md | ticket-blind split, single documentarian subagent, `docs/research/` output |
| agents/codebase-locator, codebase-analyzer, codebase-pattern-finder | .claude/agents/codebase-locator.md, .claude/agents/codebase-analyzer.md, .claude/agents/codebase-pattern-finder.md | trimmed, positive phrasing, Bash for reads |

## t3dotgg/tstack (MIT) @ 1085050

| dk file | Upstream path | Changes |
|---|---|---|
| skills/issue-flow/pr-wait | skills/babysit-pr/scripts/pr-wait | run with Monitor in `dk:issue-flow` step 6, replacing its CI wait; kept: the `<PR> [--until ready\|green\|any-change]` interface, one line per event, exit status by outcome, required checks from rulesets and branch protection, the two-identical-polls guard, a lock per PR, the replay state file, backoff on 5xx, 429 and network errors; changed: ends at the Waits deadline (20 minutes, restarted by a push to the head) and prints that it passed; gating bots and their login from `workflow.md`'s Review bot parameter (default `coderabbitai[bot]` on PRs into `main`), Greptile and Macroscope gating removed; the gh user's comments kept, only comments carrying the attribution note dropped; a review-bot event prints the review id for step 6's findings read |
| skills/code-review answer step, skills/implement, skills/issue-flow step 6 bot loop, agents/reviewer, agents/comment-reviewer | skills/sol-loop, skills/babysit-pr/SKILL.md | findings as `<id> [blocker\|should\|nit] <file>:<line> <claim>. Fix: …`, judged against intent, the hard and judgement mark folded in; comment-reviewer findings are nits unless a comment states something false; a ledger of id, severity and outcome (`fixed:`, `disagree:`, `declined:`, each with evidence); later rounds cover only open ids and code changed since; 3 rounds, 5 for security, permissions, auth, data loss or concurrency, ending early on a nits-only round; `git diff --shortstat <base>` after each round, growth cut first; declined findings worth doing go to scope intake; `dk:implement` and step 6's bot loop follow the same budget; reviewers are `dk:reviewer` agents, not Sol through T3 Code |
| skills/issue-flow step 6 ready gate, skills/implement asking and Decisions taken | skills/full-send, skills/full-stop | ready gate on the latest commit (proof covers the diff, required checks green, every bot finding fixed or answered, no human review requesting changes, branch up to date and mergeable); the handoff ends in one verdict: Ready to merge, Waiting for required approval or Blocked; asking only for no proof possible, a gate that cannot pass, a step outside the grant, an ambiguous goal or another PR making this one obsolete, through AskUserQuestion with the recommendation first, defaults listed under Decisions taken; merging stays the maintainer's, so the merge grant, merge-queue handling, T3 Code tools and testing-permission override are not taken |
| skills/pr opener and title, skills/issue-flow step 6 PR open | skills/file-pr | Summary opens with one plain sentence on the problem, before any visual; the title says why the change matters; step 6 checks for an existing PR for the branch before `gh pr create`, and opens it through REST, against the base from `workflow.md`, when GraphQL is rate-limited |
| skills/issue-flow steps 6 and 7 attribution | skills/leaving-pr-comments | every comment or thread reply the agent posts starts with a `> [!NOTE]` line naming the model acting for the maintainer, its format written once so `pr-wait` can match it; a review thread is resolved only after its reply posted and GitHub returned its URL; `dk:triage`'s disclaimer stays |
| skills/handoff receiving section | skills/takeover | receiving rules only: a handoff is context, not proof, checked against the code, the current head and uncommitted work; the earlier implementation is re-judged, not defended; imported commits keep their authorship and trailers |
| skills/modernize | skills/modernize | user-invoked; kept: one disposition of MODERNIZE, REWORK or CLOSE, the base's new commits checked for conceptual conflicts, `git range-diff` of the series before and after; base from `workflow.md`, worktree from `dk:issue-flow` step 2, push with `--force-with-lease=<branch>:<observed sha>`; Codex `agents/openai.yaml` not taken |
