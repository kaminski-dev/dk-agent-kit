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
