---
name: batch-pr
description: "Open the batch PR from pre-main into main, carrying every merged PR's Closes or Refs line."
disable-model-invocation: true
---

# Batch PR

The batch PR takes everything merged into `pre-main` since the last batch into `main`, and its merge deploys. It carries every merged PR's `Closes #N` or `Refs #N` line, for the reason the `dk:issue-flow` skill gives in step 6. Before it opens, one local CodeRabbit review of the batch lets you fix what it finds, so the review bot on the PR sees a mostly clean diff. This skill opens the PR; the maintainer merges it and moves both branches.

## 1. Collect

From the repo's checkout, with `<base directory>` the one this skill's header names, written out literally:

```sh
python3 -I <base directory>/batch.py
```

It reads origin and opens nothing. Act on its exit code:

- **0**: it printed `## PRs` (merged into `pre-main`, not yet in `main`), `## Lines` (one `Closes` or `Refs` line per issue) and, when a PR names no issue, `## Without a line`. Go on to step 2.
- **3**: a batch PR is already open. Give the user the URL it printed, and stop.
- **4**: nothing to batch (`pre-main` holds nothing that `main` lacks, or origin has no `pre-main`). Pass its line on, and stop.
- **1**: `git` or `gh` failed, origin is no github.com repo, a merged PR's merge commit is missing from the clone (it names the PRs), or `pre-main` holds merge commits of branches but no PR merged in the repo it names. Show its message, and stop.

Done when you hold the PR list and the lines.

## 2. Review

One local review per batch: the CLI's reviews are rate-limited, so the review bot on the PR gives the fixes their second look. Start it with `run_in_background`, `<scratchpad>` being the session's scratchpad directory, and write the body (step 3) while it runs:

```sh
python3 -I <base directory>/review.py <scratchpad>/batch-review
```

Act on its exit code:

- **0**: it printed the findings file. Read it and list every finding before fixing any, then work them through the route `docs/agents/workflow.md` sets as **Batch-review fixes** (`pr` when it sets none), as `dk:issue-flow` step 7 describes it, with these changes, since no PR exists yet:
  - `push`: the k-th finding's worktree takes `batch-review-<k>` for `<N>`, and the pushed commit's SHA is the fix's record, kept for the body in place of a thread reply.
  - `pr`: one fix PR into `pre-main` for the findings. Give the user its URL and hold step 4 until they say it is merged, so the fixes are on `pre-main` before the batch PR opens. Once it is merged, run step 1 again and write step 3's body from its new output, since the first collection predates the fix PR.
  - A finding you skip, or that fails a fold-in test and becomes its own issue, keeps its reason for the body.
- **3**: this batch was reviewed in this session already; work the file it names as under **0**, if that is not done.
- **4**: the `coderabbit` CLI is not on PATH. Tell the user there is no local review, and go on with the body.
- **1**: `git` or the CLI failed (a rate limit, a login). Show its message and ask the user whether to run it once more later or open the PR without it.

Done when every finding is fixed on `pre-main` (a pushed SHA, or a merged fix PR that a second run of step 1 lists), filed as an issue, or skipped with a reason, or when the review did not run and the user knows why.

## 3. Write the body

Call the Skill tool with `dk:pr` and write the body to `batch-pr.md` in the session's scratchpad directory:

- **Summary**: the `## PRs` list as printed. A PR from `## Without a line` gets `(no issue)` after its title.
- **Evidence**: the batch PR's own checks, which run the CI workflows `docs/agents/workflow.md` names on the batch head: name those workflows here, and step 4 reads their result. When `workflow.md` names a run of that CI against `pre-main` (a nightly), add its latest run: `gh run list --workflow <workflow> --limit 1 --json workflowName,headBranch,headSha,conclusion,url`, one call per workflow, since the latest run across all workflows can be a Dependabot run that tests nothing. Each PR carries its own evidence.
- **Merge Danger**: read each PR's own Merge Danger (`gh pr view N --json body`). The batch is a one-way door when any of them is, and names that PR.
- **Local review**: each finding from step 2 with its file and line and what became of it: the fix's SHA, the fix PR, the issue it was filed as, or the reason it was skipped. When the review did not run, say why.
- **Closing lines**: every line under `## Lines`, exactly as printed, as the body's last lines.

Done when every PR from step 1 appears in the Summary, every finding from step 2 under Local review, and every line under `## Lines` in the closing lines.

## 4. Open

```sh
gh pr create --base main --head pre-main --title "Batch: pre-main into main, <YYYY-MM-DD>" --body-file <scratchpad>/batch-pr.md
```

Give the user the URL, and name each `(no issue)` PR: an issue it was meant to close stays open after the merge. Read its checks as `dk:issue-flow` step 6 says: they are the batch's evidence. Then wait for the review bot as `dk:issue-flow` step 6's **Review bot** says; what it still finds takes step 7's route.
