---
name: post-deploy-check
description: "Run the post-deploy check on an issue labelled awaiting-verification and post the verdict with its evidence: close, keep open, or send the work back. Use when an awaiting-verification issue's due date has passed, when asked to verify a deploy, or from dk:issue-flow step 7."
---

# Post-deploy check

An `awaiting-verification` issue is merged and deployed; one time-boxed check on production stands between it and closing. This skill runs that check and turns the result into a **verdict**. Only positive evidence closes an issue: an empty result counts as zero occurrences once the same selector has shown it can match.

## 1. Read the check

`gh issue view N --json number,title,body,labels,comments,state`. From the comments take the exact query, its source, the deploy time, the due date and any pass rule. A later comment that moves the due date or corrects the query wins.

Without an issue number, list the candidates (`gh issue list --state open --label awaiting-verification --json number,title`) and run every issue whose due date has passed.

Done when you hold the query, the deploy time in UTC and the due date. A missing deploy time comes from the deploy record: the batch PR's merge and the deploy run that `workflow.md` names (`gh run list --workflow <deploy> --branch main --json headSha,updatedAt,conclusion`). When the query or due date is missing, ask for it in a comment and keep the label. Before the due date, a run is a progress report: post it as one, and leave the label and state alone.

## 2. Read the source

The repo's `docs/agents/observability.md` (or, without it, the post-deploy line in `docs/agents/workflow.md`) names the access command, the label and container names, the query tool's quirks, the known noise and the repo's **control** line. Run the query exactly as the comment states; a quirk that forces a change (a window split into hours, a flag) goes into the evidence as run.

A part the doc reserves for the maintainer (production database, a logged-in browser, an expired CLI session) is theirs: run every other part, then hand them the exact command with the window filled in.

## 3. Prove the check can fire

Before reading the window, show that the query can match at all. Any one of these is the **control**:

- the old-behaviour query returns lines over a window before the deploy; their rate is how many the window would hold without the fix;
- the line the fix adds appears at least once since the deploy;
- the repo's control line (same stream selector, same window, a line that is always there, such as health requests or the startup line) returns lines.

When every control comes back empty, the selector names nothing: a wrong label, a container renamed by a rolling deploy, a datasource or project mix-up, an expired session. That is a **broken check**, and the comment names it so whatever follows. Fix the selector against the doc and rerun this step with it; the original query and its empty result stay in the evidence.

## 4. Read the window

Run the query from the deploy time to the due date (to now, when that is later). Record the count and a few sample lines: timestamp, message, request or record id. Leave customer content (mail bodies, names, addresses) out of the comment. Lines the doc lists as known noise are counted apart, never as the old behaviour.

## 5. Verdict

| Verdict | When | Action |
|---|---|---|
| **Pass** | control fired; the new line is present, or the old behaviour is absent from a window its pre-deploy rate would have filled; the comment's pass rule holds | comment the evidence, `gh issue edit N --remove-label awaiting-verification`, close |
| **Shipped but not exercised** | control fired, and nothing shows the trigger occurred: no new line, no old behaviour, and no pre-deploy rate that makes zero meaningful; or fewer events than the pass rule needs | comment the evidence and a new due date; the label stays and the issue stays open |
| **Regressed** | the old behaviour still appears after the deploy | comment the lines as evidence, swap `awaiting-verification` for `needs-triage`; the maintainer decides whether the brief still holds |
| **Broken check** | every control empty, even after fixing the selector | comment what returned nothing and the corrected query; the label stays and the issue stays open |
| **Waiting on the maintainer** | a part only the maintainer can run (step 2) | comment the parts already run and the exact command for theirs; the label stays and the issue stays open |

Only **Pass** closes. Post one comment per run:

```md
## Post-deploy check: <verdict>

Window: <from> to <to> UTC (deploy <time>, due <date>)
Source: <tool and datasource>

Control: `<query>` → <n> lines
Query: `<query, as run>` → <n> lines
<samples or counts>

<next step: closed / new due date / back to triage / corrected query / command for the maintainer>
```
