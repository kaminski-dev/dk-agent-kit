---
name: retro
description: "Run a retrospective on a session or a month of sessions, and turn each repeated mistake into a check."
disable-model-invocation: true
---

<!-- Adapted from cursor/plugins pstack@d73344b skills/correct, MIT (© 2026 Lauren Tan). Changed for dk-agent-kit: folded into the retro as its correct step, proposes fixes instead of making them, rule-to-check table in the retro report. -->

The user has asked for a **retrospective**. You are suggesting improvements to the coding agent's **environment** to improve future runs.

## Steps

1. Call the Skill tool with `dk:writing-for-agents` for the writing style guide.

2. Read the primary sources for the window the user names: one session, or a period such as the last month. Without one, take the current session. Transcripts live in `~/.claude/projects/<launch directory with / as ->/*.jsonl`, filed under the directory a session started in, so a repo's sessions can sit under its main checkout, its worktrees, or a parent directory: select them by each record's `cwd`. For a period, extract before reading: the user's **corrections** (prompts that redirect or reject the agent's work), interrupts, rejected tool calls, hook denials and failed checks, plus the repo's reverts, fix-up commits and review comments in the same window.

3. Group the mistakes into **mistake classes**. A class counts once it has happened twice, and keeps its evidence: session and date, or commit. Then look for candidates for improvement in these categories.

- **Navigation**: how easy was it for the agent to find the right files? Are there hidden dependencies between files? Would a **navigation pointer** make it easier? _Use when_ the session took a long time to find a piece of information.
- **Automated checks**: are there automated checks that could catch errors the agent made? Linting, typing, tests, filesystem linters? Read the repo's own check command first (its `package.json`/build-tool `lint`/`check` scripts, its CI workflow), so a check that already exists but sits unwired or silently broken is the finding, not a reinvention. A repo with no **guardrail** (no pre-commit hook and no CI job running its lint/typecheck/test command) is itself a finding: an un-linted repo is a standing missed opportunity, not a neutral default. _Use when_ the agent made a mistake an automated check could have caught, or the repo has no guardrail at all.
- **Coding standards**: should the **reviewer agent** be given a new rule to enforce? Should an existing rule be removed or clarified? A **mechanical** violation (a fixed syntactic pattern, a banned API, an import shape, a file-location rule) goes to step 4 for its check; `CODING_STANDARDS.md` keeps the genuine **judgement calls** (cross-file consistency, "matches the surrounding style"). _Use when_ the reviewer agent failed to catch a mistake.
- **Global AGENTS.md**: are there any steering instructions that should be moved to coding standards (or automated checks) instead? _Use when_ the AGENTS.md file is particularly large - in the repo OR the user's global scope.
- **Tool economy**: did the agent make expensive tool calls that could be streamlined? Is there any custom tooling (CLI's, MCP's) that is particularly token-inefficient? _Use when_ the agent made an expensive tool call.
- **No-ops**: look for instructions in steering files that don't modify the agent's behavior. _Use when_ the steering files are large and unwieldy.
- **Information access**: look for opportunities to increase the agent's access to information. Teeing dev server logs, readonly access to third-party services. _Use when_ a crucial piece of information was not available to the agent.

4. **Correct** each mistake class: take the first level in this order that stops it, and say why each level above it does not.

   1. **Architecture** makes the mistake impossible: one owner per piece of state, one supported way per task, internals hidden so the wrong import fails, one source of truth in place of hand-synced lists, old ways and dead code an agent would copy deleted.
   2. **Types** make the bad state unwritable.
   3. **Lint**: a lint rule, hook or CI job whose error names the file, type or function to use instead, built in the repo's own linter or guardrail. When the pattern is already common, it fails only on a change that adds more.
   4. **Test** of the behaviour, one that fails if every function it calls returned nothing.
   5. **Docs** or an agent rule, only for a judgement call: nothing fails when an agent skips it.

   Each proposed check names the past mistake from step 2 it would have failed on. Each proposed rule names its check, or says why only prose fits.

5. Build the **rule-to-check table**: one row per rule in the repo's steering files and coding standards, and one per rule step 4 proposes.

   | Rule | Enforced by | Broken in the window |
   |---|---|---|
   | the rule, in a few words | the check that fails (test, hook, lint rule or CI job, by path or name), or **prose only** | count and evidence, or none |

   A prose-only rule broken in the window is a repeat: step 4 gives it a check in this report. A rule whose mistake can no longer happen is a candidate to drop.

6. Present the candidates to the user in order of severity: each mistake class with its evidence, the level picked, and why a higher level did not work. Then present the rule-to-check table.

## Reference

### Implementation vs Review

Remember that all work goes through two stages: implementation and review. The implementation agent has the most **context pressure**. They are responsible for exploration, writing code, and debugging failures.

The review agent has the least context pressure - it receives a diff, so no exploration needed. It often does not need to write code or debug.

This means that the review agent should be responsible for imposing coding standards, not the implementation agent.

### Files

You have access to several files in the repo:

- `CLAUDE.md`/`AGENTS.md`: these files are pushed to the context window of any agent working in this repo. They should be used incredibly sparingly, usually only for **navigation pointers** to other files.
- `CODING_STANDARDS.md`: this file is read during review, not implementation. Add **navigation pointers** to docs folders if the standards file gets more than 1,000 lines long.
- Docs: use docs as references files, pointed to by other files. Look for existing docs before writing new ones.
- Skills: use skills for docs (since their description goes into the agent's context window), or for user-invoked commands. Follow the advice in the `dk:writing-for-agents` skill.
