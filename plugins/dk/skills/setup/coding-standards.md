# Writing CODING_STANDARDS.md

`CODING_STANDARDS.md` is read by the Standards reviewer in `dk:code-review`, not by the implementer up front. It holds judgement calls only: conventions a reviewer can apply to a diff that no linter could ever check (the shape new query code takes, where writes go, how a dialog is built, which error type a handler returns).

Anything mechanical (a banned import, a file-location rule, a fixed syntactic pattern) belongs in the repo's linter or CI, with a one-line pointer here at most. Lines that only help an implementer find their way (where a module lives) stay in `AGENTS.md`.

Shape: one `##` heading per area (Go, TypeScript, UI, tests), a bullet per rule, each rule stating the expected shape and, when it isn't obvious, the reason or the ADR behind it.
