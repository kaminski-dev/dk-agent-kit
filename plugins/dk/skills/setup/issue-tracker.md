# Issue tracker: GitHub

Issues, specs and PRs for this repo live on GitHub (`<owner>/<repo>`, also set as `GH_REPO` in `.claude/settings.json`). Use `gh`, always with `--json` for reads: plain output drops fields when piped.

## Issues

- **Read**: `gh issue view N --json number,title,body,labels,comments,state`.
- **List**: `gh issue list --state open --label <label> --json number,title,labels`. Same files or area: add `--search "<term>"`.
- **Create**: `gh issue create --title "…" --body-file <file> --label <label>`.
- **Comment**: `gh issue comment N --body-file <file>`.
- **Labels**: `gh issue edit N --add-label <a> --remove-label <b>`.
- **Close**: `gh issue close N --comment "…"`; declined work also gets `wontfix`.

## Epics and links

- **Spec (epic)**: an issue labelled `spec`. Its tickets are sub-issues: `gh issue create --parent <spec> …`, or `gh issue edit <spec> --add-sub-issue <child>`.
- **Blocking**: native dependencies. `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where the database id is `gh api repos/<owner>/<repo>/issues/<n> --jq .id`. Without them, a `Blocked by: #n` line at the top of the body.
- **Scope amendment**: a comment on the issue starting `Scope amendment:` records work folded into the current PR; the PR lists it under "Also in this PR".

## Pull requests

- **Read**: `gh pr view N --json title,body,comments,reviews,files` and `gh pr diff N`.
- **Create**: `gh pr create --base pre-main --body-file <file>`.
- PRs are not a triage surface here.

## Agents

Background sub-agents report back through a notification; wait for it instead of polling their output.
