---
name: batch-pr
description: "Open the batch PR from pre-main into main, carrying every merged PR's Closes or Refs line."
disable-model-invocation: true
---

# Batch PR

The batch PR takes everything merged into `pre-main` since the last batch into `main`, and its merge deploys. It carries every merged PR's `Closes #N` or `Refs #N` line, for the reason the `dk:issue-flow` skill gives in step 6. This skill opens the PR; the maintainer merges it and moves both branches.

## 1. Collect

From the repo's checkout, with `<base directory>` the one this skill's header names, written out literally:

```sh
python3 -I <base directory>/batch.py
```

It reads origin and opens nothing. Act on its exit code:

- **0**: it printed `## PRs` (merged into `pre-main`, not yet in `main`), `## Lines` (one `Closes` or `Refs` line per issue) and, when a PR names no issue, `## Without a line`. Go on to step 2.
- **3**: a batch PR is already open. Give the user the URL it printed, and stop.
- **4**: nothing to batch (`pre-main` holds nothing that `main` lacks, or origin has no `pre-main`). Pass its line on, and stop.
- **1**: `git` or `gh` failed, or a merged PR's merge commit is missing from the clone (it names the PRs). Show its message, and stop.

Done when you hold the PR list and the lines.

## 2. Write the body

Call the Skill tool with `dk:pr` and write the body to `batch-pr.md` in the session's scratchpad directory:

- **Summary**: the `## PRs` list as printed. A PR from `## Without a line` gets `(no issue)` after its title.
- **Evidence**: the latest CI run on `pre-main` (`gh run list --branch pre-main --limit 1 --json workflowName,conclusion,url`); each PR carries its own evidence.
- **Merge Danger**: read each PR's own Merge Danger (`gh pr view N --json body`). The batch is a one-way door when any of them is, and names that PR.
- **Closing lines**: every line under `## Lines`, exactly as printed, as the body's last lines.

Done when every PR from step 1 appears in the Summary and every line under `## Lines` in the closing lines.

## 3. Open

```sh
gh pr create --base main --head pre-main --title "Batch: pre-main into main, <YYYY-MM-DD>" --body-file <scratchpad>/batch-pr.md
```

Give the user the URL, and name each `(no issue)` PR: an issue it was meant to close stays open after the merge.
