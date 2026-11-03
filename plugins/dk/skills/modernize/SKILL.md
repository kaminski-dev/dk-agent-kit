---
name: modernize
description: "Bring a stale PR up to date: judge whether its idea still belongs, then rebase it, rework it or recommend closing it."
argument-hint: "PR number"
disable-model-invocation: true
---

<!-- Adapted from t3dotgg/tstack@1085050 skills/modernize, MIT (© 2026 Theo Browne). Changed for dk-agent-kit: user-invoked; the base from docs/agents/workflow.md, the worktree from dk:issue-flow step 2, detached at the observed head; the push is --force-with-lease=<branch>:<observed sha> to HEAD:<branch>, from the worktree's literal path so the gate runs; checks from AGENTS.md; comments open with dk:issue-flow step 6's attribution note; Codex agents/openai.yaml not taken. -->

# Modernize

Modernize the idea, not just the branch. A clean rebase does not prove the PR still belongs in the product.

The grant covers rebasing the PR's commits and updating its branch. Merging, closing, retargeting the base and widening the scope stay the maintainer's. A PR comment is posted only when the user asked for one, and opens with the attribution note from `dk:issue-flow` step 6's **Comments.** paragraph.

## 1. Record the PR

```sh
gh pr view <PR> --json url,state,title,body,author,baseRefName,headRefName,headRefOid,isCrossRepository,reviewDecision,statusCheckRollup,closingIssuesReferences,commits
gh pr diff <PR>
```

Read its linked issues, its comments and review threads too. The base is the one `docs/agents/workflow.md` names (`pre-main` unless it names another); a PR whose `baseRefName` differs is reported, never retargeted. A PR whose `isCrossRepository` is true lives in a fork, so its branch is not this skill's to push: assess it and report.

Then `git fetch -q origin` and check `git ls-remote origin refs/heads/<branch>` prints `headRefOid`; that SHA is the **observed sha**, the lease the push is held to. Record the merge base: `git merge-base origin/<base> <observed sha>`.

Done when you can state, in one sentence, the smallest coherent goal the PR was trying to reach, before judging how it reached it.

## 2. Check what changed around it

Read the base's commits since the merge base (`git log --stat <merge-base>..origin/<base>`), first those touching the PR's files, then the rest for moved boundaries. Search merged and open PRs (`gh pr list --state all --search "<term>"`) where titles, paths or behaviour suggest a replacement or a competing implementation.

A **conceptual conflict** is one Git cannot see. Look for each:

- the same user-facing problem already solved;
- APIs, types, schemas, dependencies or module boundaries changed;
- both sides now owning the same behaviour or invariant;
- the code being changed deleted, moved or deliberately simplified;
- landing the PR restoring an old behaviour, or making two ways to do one thing;
- the original benefit no longer worth its maintenance cost.

Done when each bullet has a finding or a "none found" backed by the commit or PR you checked. A PR with no textual conflicts is still unjudged until then.

## 3. Choose one disposition

- **MODERNIZE**: the goal is still useful and the implementation is still the right shape. Go to step 4.
- **REWORK**: the goal is still useful, but a mechanical rebase would keep the wrong implementation. Describe the smallest credible rewrite and stop before pushing, unless the user also asked for the rework.
- **CLOSE**: the PR is superseded, obsolete, pointed the wrong way, or no longer worth its cost. Cite the evidence and stop. Closing is the maintainer's call.

Be willing to recommend CLOSE. Age alone is not evidence, and sunk effort is no reason to keep a PR alive.

## 4. Rebase without losing intent

For MODERNIZE only:

1. Make the worktree as `dk:issue-flow` step 2 does, with `<N>` the PR's issue (the PR number when it links none), detached at the observed sha so no local branch is touched: `git worktree add --detach ~/workspace/<prefix>-<N> <observed sha>`. When the PR's old worktree is still at that path, its uncommitted work is the user's: reuse it detached (`git -C <path> checkout --detach <observed sha>`) only when `git -C <path> status --porcelain` prints nothing, and otherwise add `~/workspace/<prefix>-<N>-modernize` beside it. Run the fresh-worktree setup from `workflow.md`.
2. `git rebase origin/<base>`.
3. Resolve each conflict by the PR's intent and the base's newer invariants. A conflict that exposes a product or architecture disagreement sends you back to step 3, not to a guess.
4. Compare the commit series before and after: `git range-diff <merge-base>..<observed sha> origin/<base>..HEAD`, then read the final diff (`git diff origin/<base>...HEAD`). Done when no intended behaviour has dropped out and no behaviour the base already landed comes back.
5. Run the checks `AGENTS.md` lists for the touched area. Tell a real failure from one the base already has (run it on `origin/<base>`) or an infrastructure failure.
6. Push from the worktree's literal path, so the gate runs (`dk:issue-flow` step 6):

   ```sh
   cd ~/workspace/<prefix>-<N> && git push --force-with-lease=<branch>:<observed sha> origin HEAD:<branch>
   ```

   A refused lease means someone pushed since step 1: fetch, go back to step 1, and judge the new head before any second push.

## Report

Lead with MODERNIZE, REWORK or CLOSE and the reason. Then:

- the base's meaningful changes since the merge base;
- each conceptual conflict, or that none was found and what was checked;
- the rebase and push result, with the range-diff's verdict, when performed;
- the checks run, each with its result;
- the decision or work left, with the PR's link.

Keep observed facts apart from judgment, and name what you could not verify.
