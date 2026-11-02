# Issue tracker: GitHub

Issues and PRs live on GitHub (`acme/ledger`). Use `gh`, always with `--json` for reads.

## Issues

- **Read**: `gh issue view N --json number,title,body,labels,comments,state`.
- **List**: `gh issue list --state open --label <label> --json number,title,labels`.
- **Ready** (first cut): `gh issue list --state open --label ready-for-agent --search "-is:blocked" --limit 1000 --json number,title,labels,body`. `is:blocked` counts only open native blockers; GitHub does not document it, and it was checked by hand on 2026-11-02. `/dk:triage` also leaves out an issue whose body names an open `Blocked by: #n`.
- **Create**: `gh issue create --title "…" --body-file <file> --label <label>`.
- **Comment**: `gh issue comment N --body-file <file>`.
- **Labels**: `gh issue edit N --add-label <a> --remove-label <b>`.
- **Close**: `gh issue close N --comment "…"`.
- **Blocking**: native dependencies. `gh api --method POST repos/acme/ledger/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where the database id is `gh api repos/acme/ledger/issues/<n> --jq .id`. Read an issue's blockers with `gh api repos/acme/ledger/issues/<n>/dependencies/blocked_by --jq '.[] | "#\(.number) \(.state)"'`.
- **Scope amendment**: a comment starting `Scope amendment:` records work folded into the current PR.

## Pull requests

- **Create**: `gh pr create --base pre-main --head <branch> --title "…" --body-file <file>`.
- **Read**: `gh pr view N --json title,body`.
- External PRs are not a triage surface here.

## Out of scope

The repo has no `.out-of-scope/` directory yet: no request has been rejected.
