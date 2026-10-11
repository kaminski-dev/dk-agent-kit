---
name: research-codebase
description: "Document how the codebase works today for an issue or question, written by a ticket-blind subagent into docs/research/."
disable-model-invocation: true
argument-hint: "Issue number, or a question about the codebase"
---

<!-- Adapted from humanlayer/humanlayer@99abe67 .claude/commands/research_codebase.md, Apache-2.0. Modified for dk-agent-kit: split into a ticket-blind question step and a single documentarian subagent (idea from humanlayer/humanlayer-pi@f4bd3ed create-research-questions), output to tracked docs/research/, GitHub issues instead of Linear/thoughts/. -->

Produce a research document that describes the codebase **as it exists today**: what exists, where, and how it connects. The writer is a **documentarian** — a technical writer mapping existing territory — and stays **ticket-blind**: it sees neutral research questions, never the issue, so the planned change cannot bend what it reports.

## 1. Write the research questions (this session)

1. Work in the issue's worktree (the `dk:issue-flow` skill), so the document lands on the issue's branch. Read the input. For an issue number, run `gh issue view <N> --json title,body,labels,comments`. Otherwise the argument is the user's question.
2. Write 2–8 **research questions** about how the codebase works today. Each one asks "how does it work", in the shape of: "Trace the flow from `<entry point>` to `<data store>`", "How do `<A>` and `<B>` exchange data, on both sides?", "Where is `<table/column/config key>` read and written?". Phrase them neutrally, so a reader of the questions alone could not guess the planned change or a solution. When the issue touches UI, add a question about the existing component library and styling conventions.
3. Compute the output path: `docs/research/YYYY-MM-DD-<issue>-<slug>.md` (drop `<issue>-` when there is none), where `<slug>` is a 2–4 word kebab-case name for the researched area, also neutral.
4. Run `git check-ignore -q <output path>`. Exit status 0 means the path is ignored: stop and tell the user the repo needs a `.gitignore` exception for `docs/research/`.
5. Save the questions file to your session scratchpad directory (from the system prompt; `mktemp -d` if none is listed) as `research-questions.md`:

   ```markdown
   ---
   output: docs/research/2026-01-08-42-session-storage.md
   issue: 42            # or "none"
   ---
   # Research questions
   1. ...
   ## Key context pointers
   - Paths, packages, and links named in the input, verbatim. Omit the section if there are none.
   ```

Done when the questions file exists, every question is descriptive, and the output path is confirmed tracked.

## 2. Dispatch the documentarian (one subagent)

Dispatch ONE `general-purpose` subagent in the foreground. Its prompt is the brief below with the questions file's absolute path filled in; pass nothing else from the issue or this conversation.

> You are a documentarian. Your whole brief is `<questions file path>`: read it, answer every research question, and write one Markdown document to the `output` path it names (relative to the repo root).
>
> Describe what exists, where it lives, and how the parts connect, citing `file:line` (or `file:start-end`) for every claim. Your reader wants a map of the territory as it stands; write every sentence as description of current behaviour.
>
> Fan out in parallel with the Agent tool, grouping related questions into 2–6 well-scoped prompts: `dk:codebase-locator` finds where things live, `dk:codebase-analyzer` traces how specific code works, `dk:codebase-pattern-finder` shows existing examples and tests. Start with locators, then send analyzers at the most promising findings. Wait for all of them, then verify any surprising claim by reading the cited lines yourself. If the Agent tool is unavailable to you, do the same work directly with Grep, Glob and Read.
>
> Gather `date` (`date +%Y-%m-%d`), `git_commit` (`git rev-parse --short HEAD`) and `branch` (`git branch --show-current`), then write:
>
> ```markdown
> ---
> date: <YYYY-MM-DD>
> git_commit: <short sha>
> branch: <branch>
> issue: <from the questions file>
> questions:
>   - <each research question, verbatim>
> ---
> # Research: <area>
> ## Summary
> <a few paragraphs: how the researched area works today>
> ## Detailed findings
> ### <one section per question; the heading states the answer as a takeaway>
> <prose with inline file:line citations; tables, Mermaid, call trees or file trees where they show structure faster than prose; how this area is tested today, or that it has no tests>
> ## Code references
> - `path/to/file.ext:12-40` — what is there (group by area; say whether a group is exhaustive)
> ## Open questions
> - <each question, or part of one, you could not answer from the code, and what you checked>
> ```
>
> Done when every research question has an answer with `file:line` references or appears under Open questions. Reply with the document path and the number of open questions.

## 3. Check and report (this session)

1. Read the document against the issue or question. Rewrite any sentence that judges, recommends, proposes, or rates — anything that reads as an opinion or a solution — into neutral description of what the code does, or delete it.
2. Check the completion criterion yourself: every research question has an answer with `file:line` references, or is listed under Open questions. Send the subagent back (SendMessage) for any question that has neither.
3. When an issue was given, comment on it with `gh issue comment <N> --body "<one line>: <link>"`, where the link is `https://github.com/<owner>/<repo>/blob/<branch>/<output path>` (from `gh repo view --json owner,name`); note in the comment that it resolves once the branch is pushed.
4. Tell the user the document path, a two-line summary, the open questions, and that the document is uncommitted and ready to commit.
