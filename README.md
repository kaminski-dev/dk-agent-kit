# dk-agent-kit

My Claude Code setup as a plugin marketplace: guardrails that hold whether or
not the agent reads its instructions, and the skills I work with,
adapted from [mattpocock/skills](https://github.com/mattpocock/skills),
[pstack](https://github.com/cursor/plugins/tree/main/pstack) and
[HumanLayer](https://github.com/humanlayer/humanlayer).

Claude Code only for now. Codex and other hosts will follow.

## What is in it

| Path | What it does |
|---|---|
| `plugins/dk-guard` | PreToolUse hook on Bash. It **denies** `docker`/`podman prune`, mass removal without a label or name filter, pushes to `main`/`master` (explicit, `HEAD:main`, or a bare push while on main), plain force pushes (`--force-with-lease` and `verify-assets/*` are fine), `git push --mirror`, `git clean -x`, reading `~/.sentryclirc`, `~/.aws/credentials`, `~/.netrc` or a private SSH key (`ls`, `stat` or `[ -e ]` pass when their output feeds no other command; Sentry events come from the Sentry helper named in the repo's `docs/agents/observability.md`), and a zsh special parameter such as `path` (tied to `PATH`), `status` or `argv` as a `for` or `read` variable, which leaves every later command "not found". It **asks** before rewriting or deleting `pre-main` and before `dk-gc --yes` or `dk-gc` with piped input, so its one yes stays the human's. Piped `gh issue view --comments` gets a hint that the body is missing, and a Postgres server started by `docker run` (detached or without `--rm`) and without a `dk.issue` label gets a hint to use `dk-pg`. The hook fails closed (`onFailure: block`). `bin/dk-pg` is on the agent's PATH: `dk-pg up <issue>` starts a throwaway Postgres (`--rm`, tmpfs, labels `dk.repo`, `dk.root` and `dk.issue`) on a free port and prints its URL, `dk-pg url <issue>` reprints it, `dk-pg down <issue>` removes it. `dk-gc` lists, grouped by repo, the worktrees and local and remote branches of merged PRs and the `dk-pg` databases of closed issues, then removes them after one yes (`--dry-run` only lists); it never removes `pre-main`, `verify-assets/*`, the base of any PR, a branch with an open PR or a worktree with uncommitted changes. A Stop hook runs the repo's executable `.claude/gate.sh` when the tree has uncommitted changes: a failing gate blocks the turn's end once and hands the agent the gate's last lines; a second failure ends the turn and tells you. It fails open. |
| `plugins/dk` | The skills, called as `/dk:<name>`. You start: `triage`, `implement`, `implement-spec`, `to-spec`, `to-tickets`, `research-codebase`, `grill-with-docs`, `improve-codebase-architecture`, `teach`, `prototype`, `retro`, `verify-doc-check`, `handoff`, `setup`. Other skills call: `issue-flow`, `verify`, `post-deploy-check`, `tdd`, `code-review`, `pr`, `blast-radius`, `research`, `grilling`, `domain-modeling`, `codebase-design`, `writing-for-agents`. Agents: the read-only reviewers `reviewer` and `comment-reviewer`, and HumanLayer's `codebase-locator`, `codebase-analyzer`, `codebase-pattern-finder`. Each repo supplies its facts in adapter files that `/dk:setup` writes. |
| `upstream/` | `UPSTREAM.md` records the commit and changes for every adapted file; `sync.sh` shows what mattpocock/skills, pstack and HumanLayer changed since in those files. |
| `settings/user.fragment.json` | What a plugin cannot ship: permission deny and ask rules, and `autoMode.hard_deny` lines. Merged into `~/.claude/settings.json` by `bootstrap.sh`. |
| `bootstrap.sh` | Shows the settings diff and the zsh options block for `~/.zshenv`; `--apply` backs both files up, writes them and installs the plugins from this checkout. |
| `tests/` | The guard's case matrix (taken from real incidents), fixture repos for the Stop gate and the session hooks, a `dk-pg` run against Docker, a `dk-gc` run against fixture repos with stubbed `gh` and `docker`, a bootstrap merge test, an `upstream/sync.sh` run against fixture upstream repos, a check of the skill-eval fixtures, and `replay_history.py` for checking the guard against past transcripts. |
| `THIRD_PARTY/` | Licenses and commits of the projects material is adapted from. |

Every rule traces back to something that went wrong in a real session: a
triage agent ran `docker container prune -f` and deleted other projects'
containers; prototype work in ignored `docs/*` was lost; an agent scraped a
token out of `~/.sentryclirc`. Rules in prose did not prevent these, so they
live in a hook now. The hook raises the floor against mistakes; it is not a
security boundary.

## Workflow

Every issue reaches `ready-for-agent` by one of two paths, then follows the
same line to deploy.

```mermaid
flowchart LR
  subgraph feature["Big feature"]
    grill["dk:grill-with-docs"] --> research["dk:research-codebase"]
    research --> spec["dk:to-spec<br/>epic, label spec"]
    spec --> tickets["dk:to-tickets<br/>sub-issues"]
  end
  subgraph bug["Bug or side finding"]
    new(["new issue<br/>needs-triage"]) --> triage["dk:triage<br/>agent brief"]
  end
  tickets --> ready(["ready-for-agent"])
  triage --> ready
```

`dk:research-codebase` reads the ticket and turns it into neutral questions;
the documentarian subagent that answers them never sees the ticket or the
conversation, so it describes the code as it is rather than arguing for a
solution.

```mermaid
flowchart LR
  ready(["ready-for-agent"]) --> implement["dk:implement<br/>worktree off pre-main"]
  implement --> verify["dk:verify<br/>control run, teardown"]
  verify --> review["dk:code-review<br/>Standards, Spec, Comments"]
  review --> pr["dk:pr<br/>PR into pre-main"]
  implement -. "side finding" .-> intake{"scope<br/>intake"}
  intake -- "small, same place" --> implement
  intake -- "otherwise" --> new(["new issue"])
```

```mermaid
flowchart LR
  pr["merged into pre-main"] --> batch(["batch PR to main<br/>deploys"])
  batch -- "Closes" --> closed(["issue closed"])
  batch -- "Refs" --> check["dk:post-deploy-check<br/>awaiting-verification"]
  check --> closed
  closed -.-> retro["dk:retro<br/>monthly"]
  retro -. "repeat mistake" .-> guard[["new dk-guard check"]]
  closed -.-> vdc["dk:verify-doc-check<br/>monthly"]
  vdc -. "drifted step" .-> fix(["fix PR or new issue"])
```

The scope intake decides what a side finding becomes: small work in the same
place joins the issue as a recorded scope amendment, anything else is a new
issue. An issue with a `Refs` line stays open until its post-deploy check
passes.

Two runs come back every month, started by hand in each repo: `/dk:retro`
over the month's sessions turns each repeated mistake into a check, and
`/dk:verify-doc-check` runs the repo's `docs/agents/verify.md` in a fresh
worktree and fixes or files every step that no longer works.

### Where a command gets stopped

```mermaid
flowchart LR
  subgraph call["Every Bash call"]
    bash["agent runs Bash"] --> hook["L1 guard-bash<br/>PreToolUse, fails closed"]
    hook -- "pass" --> deny["L2 deny rules<br/>settings.json"]
    hook -- "deny, ask or hint" --> d1["bash -c '… prune'<br/>git -C … push main<br/>gh … --comments, piped"]
    deny -- "deny" --> d2["docker … prune …<br/>git push … main<br/>Read ~/.sentryclirc"]
    deny -- "pass" --> mode{"auto<br/>mode?"}
    mode -- "other modes" --> run["command runs"]
    mode -- "auto mode" --> auto["L4 classifier<br/>hard_deny"]
    auto -- "pass" --> run
    auto -. "may deny" .-> d3["judged destructive"]
  end
  subgraph turn["Every turn end"]
    done["agent says done"] --> stop["L3 Stop gate<br/>runs .claude/gate.sh"]
    stop -- "pass" --> ends["turn ends"]
    stop -- "first fail: errors fed back" --> done
    stop -- "second fail: you are told" --> ends
  end
```

The hook runs before the permission rules, and nothing it returns overrides
a matching deny rule. L1, L2 and the L3 Stop gate are deterministic and
ship here. L4 runs only in auto mode, is a judgement call, and is only a
backstop. CI is the next layer, outside the session, and skill
text and `AGENTS.md` the last.

## Session hooks

`dk-guard` also opens every session with a baseline of at most 15 lines:
repo and branch, primary checkout or worktree, uncommitted changes, the open
PR for the branch, the labels of the issue the branch names
(`<type>/<issue>-<slug>`) and the `dk-pg` databases running for it. It is
silent outside a git repo.

A repo can require worktrees with one committed setting in its
`.claude/settings.json`:

```json
{ "env": { "DK_REQUIRE_WORKTREE": "1" } }
```

An Edit or Write to a file in that repo's primary checkout is then denied
with the worktree command from its `docs/agents/workflow.md`; the same edit in
a linked worktree goes through. Several sessions share a primary checkout and
only the branch pointer moves, which is where parallel sessions collided.
Both hooks fail open: a crash never blocks an edit.

## Install

```sh
git clone https://github.com/kaminski-dev/dk-agent-kit ~/workspace/dk-agent-kit
cd ~/workspace/dk-agent-kit
./bootstrap.sh            # read the diff
./bootstrap.sh --apply    # write it, add the marketplace, install dk-guard and dk
```

The marketplace is added from the local path, and its relative plugin
sources load straight from this checkout: after `git pull`, `/reload-plugins`
or a restart applies the changes, with no version bump and no
`claude plugin update`. Client-specific settings
(`autoMode.environment`, for example) go in `~/.config/dk-agent-kit/private.json`;
bootstrap merges that file last, and it never enters this repo.

Merge rules: objects merge key by key, arrays gain the entries they lack and
nothing is removed, scalars from the fragment win. A second run is a no-op.

The Bash tool runs zsh, and agents write bash. Bootstrap appends a marked
block to `~/.zshenv` (`$ZDOTDIR/.zshenv` when set) with `setopt NO_NOMATCH`
(an unmatched glob such as `--include=*.go` passes through literally) and
`unsetopt EQUALS` (`echo ====` is not expanded to a command path). The rest
of the file stays as it is. A file that already has the marker, or sets both
options by hand, is left alone.

## Test

```sh
python3 -I tests/hooks/test_guard_bash.py
python3 -I tests/hooks/test_stop_gate.py
python3 -I tests/hooks/test_require_worktree.py
python3 -I tests/hooks/test_session_baseline.py
python3 -I tests/test_skills.py
python3 -I tests/test_evals.py
bash tests/test_bootstrap.sh
bash tests/test_dk_pg.sh      # skips without a Docker daemon
bash tests/test_dk_gc.sh
bash tests/test_sync.sh
claude plugin validate .
```

The evals for `dk:implement`, `dk:triage`, `dk:code-review` and `dk:verify` live in
`plugins/dk/evals/` and need a model, so they run by hand (the command is in
`docs/agents/workflow.md`), not in CI.

`replay_history.py <commands.jsonl>` runs every past Bash command through the
guard and lists what it would deny, ask or hint, so a new rule can be checked
for false positives before it ships.

## Adding a rule

A repeated mistake becomes a check, not another paragraph: add a case to
`tests/hooks/guard_bash_cases.json` that reproduces it, see it fail, change the
guard, and replay the history to see what else the rule catches.
