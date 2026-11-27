#!/usr/bin/env python3
"""Runs fork-guard.py as a real PreToolUse hook on Agent tool payloads.

The prompts copy the shapes of past Agent calls: implementer forks were asked
to implement an issue, to commit, push or open a PR, or to run `git worktree
add`; sweep forks were handed a slice of files in a worktree and told not to
commit. The hook denies the first kind when it is a fork and prints nothing
otherwise.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "fork-guard.py")

WORKTREE_BRIEF = ("You are the fork for this ticket. Worktree already exists: ~/workspace/acme-42 on branch "
                  "fix/42-empty-cart (based on origin/pre-main). Work only there; scratch in $SCRATCH/42/. "
                  "Load dk:tdd, commit per green step, then report back the commit list.")
IMPLEMENT_BRIEF = ("You own issue #42 (Checkout answers 500 on an empty cart) end to end: dk:issue-flow for every "
                   "git step, dk:tdd, dk:verify, then open the PR against pre-main. Report the PR URL.")
SWEEP_BRIEF = ("You are fork B of the #41 comment sweep. Your file set: src/components/** in ~/workspace/acme-41. "
               "Edit nothing else. Do NOT commit, do NOT run gates. Write notes to $S/41/notes-B.md and hand back "
               "the counts.")


def run(tool_input=None, raw=None, tool="Agent"):
    payload = {"session_id": "test", "cwd": HERE, "hook_event_name": "PreToolUse",
               "tool_name": tool, "tool_input": tool_input}
    out = subprocess.run([sys.executable, "-I", HOOK], input=raw if raw is not None else json.dumps(payload),
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    return out.returncode, json.loads(out.stdout) if out.stdout.strip() else None, out.stderr


def fork(prompt, description="Work a ticket"):
    return {"description": description, "prompt": prompt, "subagent_type": "fork"}


def assert_denied(result):
    code, out, err = result
    assert code == 0, (code, err)
    spec = (out or {}).get("hookSpecificOutput", {})
    assert spec.get("hookEventName") == "PreToolUse", out
    assert spec.get("permissionDecision") == "deny", out
    reason = spec.get("permissionDecisionReason", "")
    assert "plain subagent" in reason and "brief" in reason, reason
    return reason


def assert_allowed(result):
    assert result == (0, None, ""), result


def case_a_fork_told_to_commit_in_an_existing_worktree_is_denied():
    assert_denied(run(fork(WORKTREE_BRIEF)))
    assert_denied(run(fork("The worktree already exists. Commit per green step and report the SHAs.")))


def case_a_fork_told_to_commit_on_a_named_branch_is_denied():
    assert_denied(run(fork("Worktree (already created, work only here): /home/u/workspace/acme-7, branch "
                           "feat/7-export. Write the fixture first, commit after each green step.")))
    assert_denied(run(fork("Follow the flow for this ticket in worktree `~/workspace/acme-8` on branch "
                           "`refactor/8-drop-dead-code` from origin/pre-main; commit per green step.")))


def case_a_fork_told_to_implement_an_issue_is_denied():
    assert_denied(run(fork(IMPLEMENT_BRIEF)))
    assert_denied(run(fork("You are the fork for issue #43 only. Execute directly. Follow the /dk:implement "
                           "instructions above for it.")))
    assert_denied(run(fork("Carry out the work and report back.", description="Implement #44 search order")))


def case_a_fork_assigned_a_ticket_in_other_words_is_denied():
    assert_denied(run(fork("You are responsible for ticket #42. Fix the checkout bug in /home/u/acme-42 and open the PR.")))
    assert_denied(run(fork("Take issue #45 and report back the commit list.")))
    assert_denied(run(fork("Fix ticket #46 in the shared checkout.")))
    assert_denied(run(fork("The empty-cart crash is #47; when it passes, open a PR against pre-main.")))


def case_a_fork_handed_a_git_worktree_command_is_denied():
    assert_denied(run(fork("Verify on a fresh checkout: `git worktree add ~/workspace/acme-verify --detach "
                           "origin/main`, drive the stack, report PASS or FAIL per check.")))
    assert_denied(run(fork("Run `git -C . worktree add ../acme-42 -b fix/42` and work there.")))
    assert_denied(run(fork('Run git -C "my repo" worktree add ../acme-43 -b fix/43, then work there.')))


def case_a_read_only_sweep_fork_is_allowed():
    assert_allowed(run(fork(SWEEP_BRIEF, description="Sweep components")))
    assert_allowed(run(fork("Read src/billing/ and list every caller of charge() with file:line. Change nothing.",
                            description="Map charge callers")))


def case_a_sweep_fork_told_the_worktree_already_exists_is_allowed():
    assert_allowed(run(fork("The worktree already exists; do not commit. Read src/cart/ and list every TODO with "
                            "file:line for #41, and do not open a PR.", description="List cart TODOs")))


def case_a_sweep_fork_in_the_parents_worktree_and_branch_is_allowed():
    assert_allowed(run(fork("You are the fork doing the mechanical sweep of the remaining pages in the worktree "
                            "~/workspace/acme-58 (branch feat/58-second-pass). Work only in that worktree. Do not "
                            "run git commit.", description="Sweep remaining pages")))


def case_a_fork_asked_to_commit_is_denied_wherever_the_ask_appears():
    assert_denied(run(fork("The worktree already exists. Fix checkout for #42, commit changes and report")))


def case_a_fork_told_to_implement_an_issue_with_words_in_between_is_denied():
    assert_denied(run(fork("Work on issue #42: change the code and run the tests")))
    assert_denied(run(fork("Implement the fix for issue #42 in the shared checkout; commit changes")))


def case_an_instruction_to_commit_push_or_open_a_pr_is_denied():
    for prompt in ("Work in src, then commit.", "Fix it, commit, push.", "Once green, commit and push.",
                   "Set up the tree\ncommit per green step", "1. Read it\n2. Push the branch.", "**Commit** the fix",
                   "Run `git push origin HEAD`.", "Run gh pr create --fill.", "Create a pull request when it passes.", "Please commit your changes.",
                   "When the tests pass commit your changes.", "Now commit the fix.", "Commit src/cart.ts and report.",
                   "Open a new PR.", "Run `git add -A && git commit -m x`.", "Steps:\n1) Fix it\n2) Push the branch",
                   "I will be away, so commit the fix.",
                   "I will review it while you commit the rest.", "At the end commit per change.",
                   "Once finished commit your work.", "Work in src \u2014 commit once green.",
                   "Work test-first, with a commit per step.", "Make the fixes, committing per step."):
        assert_denied(run(fork(prompt)))


def case_an_ask_after_a_negation_that_does_not_reach_it_is_denied():
    for prompt in ("Do not touch port 5432, commit per green step.", "Never use the shared browser. Then open the PR.",
                   "If the tests do not pass, commit the red test or the note.", "Do not push but commit your changes.",
                   "Do not edit tests and docs, commit per step or per file.",
                   "Do not push, commit per green step.", "Do not touch main, one commit per finding.",
                   "It is there (do not create another), commit the fix.",
                   "Do not touch main, a commit for each finding.", "Do not delegate, implement #42.",
                   "Do not run the whole suite and commit your changes.", "Don't forget to commit the rest.", "Do not work on main so push the branch.",
                   "Do not stop at a plan, implement #42.", "Rules (never skip):\n- Commit per green step",
                   "Read the docs first. Commit the rest."):
        assert_denied(run(fork(prompt)))


def case_a_negated_ask_is_allowed_wherever_the_negation_stands():
    for prompt in ("Do not edit tests, commit, push, or open a PR.",
                   "Do not edit files, commit changes, push the branch, open a PR.", "Do **not** commit, push.",
                   "Do not edit (or move) files, commit changes, or push the branch.",
                   "You cannot edit files, push the branch, or open a PR.", "You may not commit, push.",
                   "Report only; no edits, git commit, or git push.", "Not allowed: edit files, commit changes.",
                   "Work without running git add, git commit, or git push.", "Forbidden:\n- git commit\n- git push",
                   "Do not edit src, implement #42, or fix #43.", "Do not edit files, run git worktree add, or commit.", "Never commit, push.", "Do not commit and push.",
                   "Do not commit the notes or\nopen a PR", "Don\u2019t commit, or push the branch.",
                   "Do not, under any circumstances, commit the files",
                   "Do not edit files, branches or run git worktree add ../x.",
                   "Never:\n- commit the files\n- push the branch", "Do not implement #42, only describe it.",
                   "Change no history, e.g. git commit.", "Never run `git worktree add ../x -b y`."):
        assert_allowed(run(fork(prompt)))


def case_an_ask_meant_for_somebody_else_is_allowed():
    for prompt in ("List the callers; I will review, commit and push it.", "Another fork owns #43; leave it alone.",
                   "The other fork owns #43.", "A sibling fork owns #44.",
                   "Sweep src; the parent will check it and open the PR.",
                   "The main session will commit your changes.",
                   "I will review your edits, then commit and push."):
        assert_allowed(run(fork(prompt)))


def case_commit_push_and_fix_as_nouns_are_allowed():
    for prompt in ("Report the commit list and the last push.", "Commit: abc1234", "Review the fix for #42.",
                   "Crash between effect and commit, retries.", "Read the stub (push.jsonl).", "List the open PRs of #42.",
                   "Review the branch that implements #42.", "Commits: 39b5a91 (fix) for issue #42.",
                   "Commit to one answer.",
                   "Check the audit after commit per #602.", "List every commit per author.", 'Check step 4, "commit per green step".'):
        assert_allowed(run(fork(prompt)))


def case_a_fork_fixing_a_slice_of_an_issues_sweep_is_allowed():
    for prompt in ("Fix the typos in your slice of #41.", "Fix the typos in src/a for #41.", "You own src/billing/** for #41.",
                   "You own /Users/me/wt/src/billing/** for #41.", "Fix the typos in the src/billing folder for #41.",
                   "You are working on src/a for #41.", "Fix the rest of #41's comments.",
                    "Fix every comment for the #41 comment sweep."):
        assert_allowed(run(fork(prompt)))


def case_a_fork_told_to_implement_an_issue_in_other_shapes_is_denied():
    for prompt in ("Implement #360 cleanup and verify it.", "Implement https://github.com/o/r/issues/42.", "Implement the part of #42 that covers checkout.",
                   "Your task is to implement issue #42.", "We need to implement issue #42.", "Now fix o/r#42.",
                   "Start with dk:implement.", "/dk:implement 42", "Implement the CI/CD change for issue #42.",
                   "Fix issue #42. The bug is in src/cart.ts.", "You own issue #42. Work in ../wt-42.",
                   "Fix issue #42 in src/cart.", "You will be responsible for issue #42.",
                   "You are the fork that implements #43.", "You are the fork that fixes #44.", "You are fixing #45.",
                   "You are working on #46.",
                   "Skill: dk:implement",
                   "You are the fork implementing #206 end to end.", "/dk:implement #42", "Follow the dk:implement flow.",
                   "You are responsible for ticket #42.", "You are the fork for issue #43 only."):
        assert_denied(run(fork(prompt)))


def case_a_quoted_git_worktree_add_to_run_is_denied_and_a_quoted_mention_is_not():
    assert_denied(run(fork("Use `git worktree add` for the control run.")))
    assert_denied(run(fork("Start with `git worktree add`.")))
    assert_allowed(run(fork("Read what \"git worktree add\" does.")))
    assert_allowed(run(fork("Grep the docs for `git worktree add` and read how they use dk:implement-spec.")))
    assert_allowed(run(fork("The doc reference: `git worktree add ../x -b y` is stale; say why.")))


def case_a_negation_wrapped_over_a_line_reaches_the_next_line_and_a_finished_sentence_does_not():
    for prompt in ("Do not commit or\nOpen a PR", "Do not commit, \nOpen a PR", "Do not commit and\nOpen a PR"):
        assert_allowed(run(fork(prompt)))
    for prompt in ("Do not commit.\nOpen a PR", "Do not commit;\nOpen a PR", "Do not commit\nOpen a PR"):
        assert_denied(run(fork(prompt)))


def case_run_with_a_colon_before_a_quoted_git_worktree_add_is_denied():
    assert_denied(run(fork("Run: `git worktree add`")))
    assert_denied(run(fork("Run `git worktree add`")))


def case_a_fork_told_not_to_commit_or_open_a_pr_is_allowed():
    assert_allowed(run(fork("Review #41; do not commit or open a PR", description="Review cart")))


def case_a_fork_told_only_where_the_worktree_and_branch_are_is_allowed():
    assert_allowed(run(fork("The worktree already exists on branch feat/58; inspect files and return findings only",
                            description="Inspect cart")))
    assert_allowed(run(fork("The worktree already exists on branch feat/58; do not commit; inspect src/cart",
                            description="Inspect cart")))


def case_a_fork_told_not_to_run_git_worktree_add_is_allowed():
    assert_allowed(run(fork("Do not run git worktree add; inspect the existing checkout", description="Inspect")))


def case_a_mention_of_git_worktree_add_is_allowed():
    assert_allowed(run(fork("Review documentation that mentions `git worktree add`; do not run commands",
                            description="Review docs")))


def case_a_plain_subagent_with_the_same_prompt_is_allowed():
    for prompt in (WORKTREE_BRIEF, IMPLEMENT_BRIEF):
        assert_allowed(run({"description": "Implement #42", "prompt": prompt, "subagent_type": "general-purpose"}))
        assert_allowed(run({"description": "Implement #42", "prompt": prompt}))


def case_malformed_input_fails_open():
    assert_allowed(run(raw="not json"))
    assert_allowed(run(raw='["a list"]'))
    assert_allowed(run(tool_input="a string"))
    assert_allowed(run(tool_input=None))
    assert_allowed(run({"subagent_type": "fork", "prompt": 3, "description": ["Implement #42"]}))


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]


def main():
    failed = 0
    for case in CASES:
        try:
            case()
            print(f"ok   {case.__name__[5:]}")
        except Exception as e:
            failed += 1
            print(f"FAIL {case.__name__[5:]}: {e!r}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
