# Issue tracker: GitHub

Issues and PRs live on GitHub (`acme/api`). Use `gh`, always with `--json` for reads.

## Issues

- **Read**: `gh issue view N --json number,title,body,labels,comments,state`.
- **List**: `gh issue list --state all --search "<term>" --json number,title,labels,state`.
- **Create**: `gh issue create --title "…" --body-file <file> --label <label>`.
- **Comment**: `gh issue comment N --body-file <file>`.
- **Labels**: `gh issue edit N --add-label <a> --remove-label <b>`.
- **Close**: `gh issue close N --comment "…"`.

## CI

- **Runs**: `gh run list --workflow ci-go.yml --branch pre-main --json databaseId,conclusion,createdAt`.

## Out of scope

The repo has no `.out-of-scope/` directory yet: no request has been rejected.
