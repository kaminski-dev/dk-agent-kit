---
name: research
description: Research a question that needs several primary sources (API or library behaviour, version differences, vendor docs, standards) in a background agent, and capture the findings as a Markdown file in docs/research/. Use when the user wants a topic researched or reading legwork delegated; a single fact is a plain web search instead.
---

Spin up a **background agent** to do the research, so you keep working while it reads.

Its job:

1. Investigate the question against **primary sources** (official docs, source code, specs, first-party APIs), not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file, citing each claim's source.
3. Save it as `docs/research/YYYY-MM-DD-<slug>.md` (with `<issue>-` before the slug when the work belongs to an issue). Run `git check-ignore -q <that path>` first; an ignored path loses the notes, so report it to the user instead of writing there.
