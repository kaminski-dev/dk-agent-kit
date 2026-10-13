# Issue tracker: GitHub

Issues and PRs live on GitHub (`acme/ledger`). Use `gh`, always with `--json` for reads.

## Issues

- **Read**: `gh issue view N --json number,title,body,labels,comments,state`.
- **List**: `gh issue list --state open --label <label> --json number,title,labels`.
- **Create**: `gh issue create --title "…" --body-file <file> --label <label>`.
- **Comment**: `gh issue comment N --body-file <file>`.
- **Labels**: `gh issue edit N --add-label <a> --remove-label <b>`.
- **Close**: `gh issue close N --comment "…"`.
- **Blocking**: a `Blocked by: #n` line at the top of the body.
- **Scope amendment**: a comment starting `Scope amendment:` records work folded into the current PR.

## Pull requests

- **Create**: `gh pr create --base pre-main --head <branch> --title "…" --body-file <file>`.
- **Read**: `gh pr view N --json title,body`.
- External PRs are not a triage surface here.

## Out of scope

The repo has no `.out-of-scope/` directory yet: no request has been rejected.
