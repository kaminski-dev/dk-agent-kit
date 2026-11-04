#!/usr/bin/env python3
"""Runs fork-guard.py as a real PreToolUse hook on Agent tool payloads.

The prompts copy the shapes of past Agent calls: implementer forks were handed
an issue to implement, a worktree with its branch, or a `git worktree add` to
run; sweep forks were handed a slice of files in a worktree and told not to
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


def case_a_fork_handed_a_worktree_path_is_denied():
    assert_denied(run(fork(WORKTREE_BRIEF)))
    assert_denied(run(fork("The worktree already exists. Commit per green step and report the SHAs.")))


def case_a_fork_handed_a_worktree_path_and_its_branch_is_denied():
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
