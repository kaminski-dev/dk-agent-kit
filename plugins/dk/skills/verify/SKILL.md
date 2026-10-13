---
name: verify
description: "Prove a change works by driving it in a stack you started, against a control run of the pre-fix state. Use before calling any change verified, or when asked to verify or prove a fix."
---

# Verify

**Verified** means driven in a stack you started, with the proof matched to what changed and a **control run** that shows the pre-fix behaviour. Passing gates are the floor, never the proof.

This skill is the protocol. The repo's facts live in its `docs/agents/verify.md` (contents listed under [The repo's verify doc](#the-repos-verify-doc)); read it before step 1. When a repo has none, take the start command from its README or `AGENTS.md` and name each fact you had to discover in the PR, so the doc can be written from it.

`<N>` is the issue number, `$SCRATCH/<N>/` your scratch directory from `dk:issue-flow`.

Each run starts in a fresh **run directory**: `mkdir -p "$SCRATCH/<N>" && mktemp -d "$SCRATCH/<N>/verify.XXXXXX"`. Shell variables last one Bash call, so write the path it prints literally in every later command; `$RUN` below stands for it. Everything the run writes goes in `$RUN`, and a rerun makes a new one, so earlier runs stay where they are and nothing needs deleting.

## 1. Owe the proof

List what the diff changes and take the matching rows; each row touched is owed in full.

| Change | Proof |
| --- | --- |
| Handler or endpoint | unit tests, the repo's integration suite, and one request against the running API, through the UI or with the login from step 3 |
| Migration | the stack started on a fresh database, then the migration run down and up again with the repo's migration tool, so the Down half runs |
| UI | a browser at desktop and phone width (step 5), the flow the issue describes driven beyond the page load, console clean |
| External service (mail, storage, push, payments) | unit tests at the service boundary, plus the handler's behaviour observed with the service absent or stubbed as the repo doc says |
| Bug fix | a regression test seen **red** on the pre-fix state, or by mutating the fix, before its green run counts |

A change no row covers (docs, CI, tooling) owes what the Evidence section of the repo's `workflow.md` asks. Done when every changed area has its proof named.

## 2. Start the stack

- **Database**: the repo doc says whether the stack needs one. For Postgres, `dk-pg up <N>` starts a throwaway Postgres on a free port, waits until it accepts connections and prints its URL (`--db NAME` when the repo expects a database name); `dk-pg url <N>` prints it again. Point the stack and the integration suite at that URL. It starts empty every time, so seeding is the repo doc's step.
- **Ports**: before starting a process, `lsof -iTCP:<port> -sTCP:LISTEN` shows the port free; a stale process from an earlier run answers with old code. Use the repo doc's way of moving to a free port.
- **External services**: stub them or leave them absent, as the repo doc says per service. The stack never talks to a production service.
- **Files**: logs, cookie jars, stub output and builds go in `$RUN`.

Note every process and port you start; step 7 removes them.

## 3. Log in

The repo doc says whether the API needs a login; an API without one is called without credentials, and this step ends there. The usual shape: a login request sets an HttpOnly session cookie; reads accept the cookie, and writes (POST, PUT, PATCH, DELETE) also need `Authorization: Bearer <access token>`, or they answer 401 (CSRF protection). The seeded user, the password and where the token comes from (a token endpoint, or the cookie's value) are in the repo doc. When a later write gets 401, the token expired: fetch it again.

## 4. Control run, then the change

Drive one scenario twice, with the same input and the same steps:

1. **Control**: the pre-fix state, built in a throwaway worktree (`git worktree add --detach "$RUN/base" <base>`, with `<base>` the branch's base from `workflow.md`). It shows the bug, or the feature's absence.
2. **Change**: your branch, which shows the fix.

For a fix, a control that already behaves correctly means the scenario misses the bug: rework the scenario until the control fails, then run the change. Keep the output of both runs; they are the before and after of the PR's evidence.

## 5. Browser

Drive a browser of your own. The Playwright MCP server runs one browser per session, and the session's subagents share it:

- **Main agent, no other verifier in the session**: the MCP browser.
- **Subagent, or the MCP answers "Browser is already in use"** (another session holds its profile): a standalone Playwright script in `$RUN` with its own user-data directory, `chromium.launchPersistentContext('$RUN/profile', { headless: true })`, run from the repo so `playwright` resolves (the verify doc says how). The "already in use" answer means the MCP server runs without `--isolated`; name it in your report.

Check 1280 px, then 390 × 844 (`browser_resize` or `page.setViewportSize`), and see the change at both widths. Console errors (`browser_console_messages` or `page.on('console')`) are findings: each is fixed, or explained in the PR. Screenshots go in `$RUN/shots/`; the MCP writes only under its own roots, so move its files there.

## 6. Evidence

Each proof owed in step 1 appears in the PR's Evidence section (`dk:pr`) as a before and after: control and change output, test runs, screenshots. The screenshots in `$RUN/shots/` go on `verify-assets/<N>` as `dk:issue-flow` step 5 describes. A proof that runs only in CI waits for it as `dk:issue-flow` step 6 says.

## 7. Tear down

Before reporting, stop what you started: every process (its port is free again under `lsof`), your browser (`browser_close`, or the script's `close()`), `dk-pg down <N>` when you started one, and `git worktree remove "$RUN/base"`. The files stay in `$RUN` with the session's scratch. Done when none of your ports listens, `git worktree list` no longer shows `$RUN/base` and, with dk-pg, `dk-pg url <N>` finds no running database.

## The repo's verify doc

`docs/agents/verify.md` holds only the repo's facts; everything this skill says stays out of it:

- **Stack start**: commands, required env, ports and how to move off a taken one, startup gotchas.
- **Database**: whether the stack needs one; then its name and migration tool, and how to point the stack and the integration suite at the `dk-pg` URL.
- **Stubs**: per external service, whether absence is enough or which stub to run, and what it must answer.
- **Seeding**: the scripts or SQL for test data, and their order relative to migrations.
- **Login**: whether the API needs one; then the seeded user and password, the login endpoint, and where the access token comes from.
- **Endpoints**: route prefixes and the surfaces worth observing.
- **Browser**: frontend ports, breakpoints, and the harness quirks that look like bugs.
