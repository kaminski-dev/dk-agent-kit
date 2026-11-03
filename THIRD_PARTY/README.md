# Third-party sources

Material adapted from these projects keeps its original license. Each adapted
file names its source and upstream commit at the top, and `upstream/` (added
with the first vendored skill) records the commit each copy was taken from.

| Source | Commit read | License | Used for |
|---|---|---|---|
| [mattpocock/skills](https://github.com/mattpocock/skills) | `49dd158` (2026-10-09, after v1.3.1) | MIT, [mattpocock-skills.LICENSE](mattpocock-skills.LICENSE) | 21 skills in `plugins/dk` |
| [cursor/plugins: pstack](https://github.com/cursor/plugins/tree/main/pstack) | `1dcc2ba` (v0.15.21) | MIT, [pstack.LICENSE](pstack.LICENSE) | `blast-radius`, `verify-doc-check`, retro's correct step and rule-to-check table, code-review's Correctness test question and Defensive Interior entry, the `comment-reviewer` agent (from Comment Sicko) |
| [humanlayer/humanlayer](https://github.com/humanlayer/humanlayer) | `99abe67` | Apache-2.0, [humanlayer.LICENSE](humanlayer.LICENSE) | `research-codebase` and its three helper agents |
| [t3dotgg/tstack](https://github.com/t3dotgg/tstack) | `1085050` (2026-10-27) | MIT (© 2026 Theo Browne), [tstack.LICENSE](tstack.LICENSE) | `modernize`; issue-flow's `pr-wait` watcher, ready gate, PR-open fallback and comment attribution; the review budget in `code-review`, `implement` and the reviewer agents; `pr`'s problem-first opener and title; `handoff`'s receiving section |

`dk-guard`, the settings fragment and `issue-flow`, apart from its tstack material, are original work. `upstream/UPSTREAM.md` lists every adapted file and what changed.
