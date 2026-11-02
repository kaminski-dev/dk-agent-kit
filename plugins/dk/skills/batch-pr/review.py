#!/usr/bin/env python3
"""Run the batch's one local CodeRabbit review. Usage: review.py <out-dir>

Run from inside the repo, after batch.py. It fetches origin's main and pre-main,
checks origin/pre-main out in a detached worktree under <out-dir>, and runs there

  coderabbit review --agent --committed --base-commit <merge base of origin/main and origin/pre-main>

The findings go to <out-dir>/review-<merge base, 12 characters>.txt, whose path it
prints; the worktree is removed. --use-credits is never passed.

Exit 0: reviewed. Exit 4: coderabbit is not on PATH; nothing ran. Exit 3: <out-dir>
already holds this batch's review (same merge base), whose path it prints: one
review per batch, so fixes pushed onto pre-main do not earn a second one. Exit 1:
git or coderabbit failed (a rate limit, a login); its message is on stderr, and
the batch counts as unreviewed.
"""
import pathlib
import shutil
import subprocess
import sys

BRANCHES = ("main", "pre-main")


def sh(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{' '.join(cmd)}: {(r.stderr or r.stdout).strip() or r.returncode}")
    return r.stdout.strip()


def main():
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        print(__doc__.strip())
        return 0 if sys.argv[1:] in (["-h"], ["--help"]) else 1
    out = pathlib.Path(sys.argv[1]).resolve()

    if not shutil.which("coderabbit"):
        print("No local review: coderabbit is not on PATH.")
        return 4

    sh("git", "fetch", "-q", "origin", *(f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in BRANCHES))
    base = sh("git", "merge-base", "origin/main", "origin/pre-main")
    short = base[:12]
    findings = out / f"review-{short}.txt"
    if findings.exists():
        print(f"This batch was reviewed already: {findings}")
        return 3

    out.mkdir(parents=True, exist_ok=True)
    tree = out / f"pre-main-{short}"
    sh("git", "worktree", "add", "-q", "--detach", str(tree), "origin/pre-main")
    try:
        r = subprocess.run(["coderabbit", "review", "--agent", "--committed", "--base-commit", base],
                           cwd=tree, capture_output=True, text=True)
    finally:
        gone = subprocess.run(["git", "worktree", "remove", "--force", str(tree)], capture_output=True, text=True)
        if gone.returncode:
            print(f"The review's worktree is left at {tree}: {gone.stderr.strip()}", file=sys.stderr)
    if r.returncode:
        sys.exit(f"coderabbit review failed ({r.returncode}): {(r.stderr + r.stdout).strip()}")
    findings.write_text(r.stdout + r.stderr)
    print(f"Reviewed origin/pre-main against {short}: {findings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
