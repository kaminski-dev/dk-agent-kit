# api

The booking API: a Go HTTP server (`cmd/api`) with a Sentry tunnel (`internal/tunnel`). The production image is built from `Dockerfile`.

## Workflow

Issues move issue → worktree → PR into `pre-main`. The dk skills carry the shared sequence (`dk:issue-flow`); this repo's parameters are in `docs/agents/workflow.md`, tracker commands in `docs/agents/issue-tracker.md`, labels in `docs/agents/triage-labels.md`.

## Checks

`go build ./...`, `go vet ./...`, `golangci-lint run ./...`, `go test ./...`, and `govulncheck ./...` (v1.7.0, as in CI; it is on PATH here). CI (`.github/workflows/ci-go.yml`) runs the same on every PR.
