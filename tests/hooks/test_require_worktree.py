#!/usr/bin/env python3
"""Runs require-worktree.py as a real PreToolUse hook against throwaway git repos.

Each case builds a primary checkout, opted in or not, sometimes with a linked
worktree, and sends an Edit or Write payload for a file in it. The hook either
denies with the worktree hint or prints nothing.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "plugins", "dk-guard", "scripts", "require-worktree.py")

OPT_IN = {"env": {"DK_REQUIRE_WORKTREE": "1"}}
WORKFLOW = ("# Workflow\n\n## Worktree\n\n"
            "- Path and branch: `git worktree add ~/workspace/acme-<issue> -b <type>/<issue>-<slug> origin/pre-main`,"
            " then `pnpm install`.\n")


def make_repo(root, name, settings=None, workflow=None):
    path = os.path.join(root, name)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", path]
    subprocess.run(["git", "init", "-q", path], check=True)
    os.makedirs(os.path.join(path, "src"))
    with open(os.path.join(path, "src", "a.ts"), "w") as f:
        f.write("foo\n")
    if settings is not None:
        os.makedirs(os.path.join(path, ".claude"))
        with open(os.path.join(path, ".claude", "settings.json"), "w") as f:
            json.dump(settings, f)
    if workflow is not None:
        os.makedirs(os.path.join(path, "docs", "agents"))
        with open(os.path.join(path, "docs", "agents", "workflow.md"), "w") as f:
            f.write(workflow)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
    return path


def add_worktree(repo, path):
    subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b", "feat/1-x", path], check=True)
    return path


def run(file_path, tool="Edit", cwd=None, raw=None):
    tool_input = {"file_path": file_path, "old_string": "foo", "new_string": "bar"} if tool == "Edit" \
        else {"file_path": file_path, "content": "bar\n"}
    payload = {"session_id": "test", "cwd": cwd or os.path.dirname(file_path), "hook_event_name": "PreToolUse",
               "tool_name": tool, "tool_input": tool_input}
    out = subprocess.run([sys.executable, "-I", HOOK], input=raw if raw is not None else json.dumps(payload),
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    return out.returncode, json.loads(out.stdout) if out.stdout.strip() else None, out.stderr


def denied(out):
    spec = (out or {}).get("hookSpecificOutput", {})
    return spec.get("permissionDecision") == "deny", spec.get("permissionDecisionReason", "")


def case_edit_in_opted_in_primary_is_denied_with_the_workflow_command(root):
    repo = make_repo(root, "acme", OPT_IN, WORKFLOW)
    code, out, err = run(os.path.join(repo, "src", "a.ts"))
    assert code == 0, (code, err)
    deny, reason = denied(out)
    assert deny, out
    assert "git worktree add ~/workspace/acme-<issue> -b <type>/<issue>-<slug> origin/pre-main" in reason, reason


def case_write_of_a_new_file_in_a_new_directory_is_denied(root):
    repo = make_repo(root, "acme-new", OPT_IN, WORKFLOW)
    _, out, _ = run(os.path.join(repo, "src", "feature", "b.ts"), tool="Write", cwd=repo)
    assert denied(out)[0], out


def case_relative_path_resolves_against_cwd(root):
    repo = make_repo(root, "acme-rel", OPT_IN, WORKFLOW)
    _, out, _ = run("src/a.ts", cwd=repo)
    assert denied(out)[0], out


def case_without_workflow_doc_the_hint_is_generic(root):
    repo = make_repo(root, "acme-bare", OPT_IN)
    _, out, _ = run(os.path.join(repo, "src", "a.ts"))
    deny, reason = denied(out)
    assert deny and "git worktree add " in reason, out


def case_same_edit_in_a_linked_worktree_goes_through(root):
    repo = make_repo(root, "acme-wt", OPT_IN, WORKFLOW)
    wt = add_worktree(repo, os.path.join(root, "acme-wt-1"))
    assert run(os.path.join(wt, "src", "a.ts")) == (0, None, "")
    assert run(os.path.join(wt, "src", "c.ts"), tool="Write", cwd=repo) == (0, None, "")


def case_repo_that_has_not_opted_in_goes_through(root):
    repo = make_repo(root, "plain-repo", {"env": {"GH_REPO": "x/y"}}, WORKFLOW)
    assert run(os.path.join(repo, "src", "a.ts")) == (0, None, "")
    off = make_repo(root, "off-repo", {"env": {"DK_REQUIRE_WORKTREE": "0"}}, WORKFLOW)
    assert run(os.path.join(off, "src", "a.ts")) == (0, None, "")


def case_path_outside_a_repo_goes_through(root):
    plain = os.path.join(root, "notes")
    os.makedirs(plain)
    assert run(os.path.join(plain, "todo.md"), tool="Write") == (0, None, "")


def case_broken_settings_fail_open(root):
    repo = make_repo(root, "broken-settings", None, WORKFLOW)
    os.makedirs(os.path.join(repo, ".claude"))
    with open(os.path.join(repo, ".claude", "settings.json"), "w") as f:
        f.write("{ not json")
    assert run(os.path.join(repo, "src", "a.ts")) == (0, None, "")


def case_unexpected_payload_fails_open(root):
    repo = make_repo(root, "acme-payload", OPT_IN, WORKFLOW)
    assert run(os.path.join(repo, "src", "a.ts"), raw="not json") == (0, None, "")
    assert run(os.path.join(repo, "src", "a.ts"), raw='["a list"]') == (0, None, "")
    assert run(os.path.join(repo, "src", "a.ts"), raw='{"tool_input": {"file_path": 3}}') == (0, None, "")


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as root:
        root = os.path.realpath(root)
        for case in CASES:
            try:
                case(root)
                print(f"ok   {case.__name__[5:]}")
            except Exception as e:
                failed += 1
                print(f"FAIL {case.__name__[5:]}: {e!r}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
