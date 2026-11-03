---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up, or pick one up.
argument-hint: "What will the next session be used for? Or the path of a handoff to pick up."
disable-model-invocation: true
---

<!-- Adapted from t3dotgg/tstack@1085050 skills/takeover, MIT (© 2026 Theo Browne). Changed for dk-agent-kit: pickup rules copied into each handoff document; imported commits come over by cherry-pick; replacement-PR, modernize and merge steps not taken. -->

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to the temporary directory of the user's OS (`$TMPDIR`, else `/tmp`; `%TEMP%` on Windows) - not the current workspace.

Open the document with the "Picking up a handoff" section below, copied verbatim: the agent that picks it up reads the document, not this skill.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Skill tool for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly. When the argument is the path of an existing handoff document, you are the one picking it up: follow the section below instead of writing a new one.

## Picking up a handoff

This handoff is context, not proof: it records what the last agent believed when it stopped, and the work may have moved since. Before your first edit, check each of its claims against the repo as it is now and mark it holds, stale or wrong:

- the current head of the branch it names, with that branch's issue and PR, their latest comments and review findings;
- uncommitted work in its worktree (`git status`, `git diff`), which no commit records;
- the code each claim points at, read at that head.

Re-judge the earlier implementation as you would review someone else's: keep what holds against the issue and rework what does not, whoever built it.

To continue on a new branch, bring the earlier commits over with `git cherry-pick`, which keeps each commit's author and its `Co-Authored-By` trailers, and put your fixes in commits of your own on top.

Your report names what you inherited, which claims were stale or wrong, and what you changed.
