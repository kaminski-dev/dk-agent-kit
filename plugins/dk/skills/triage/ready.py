#!/usr/bin/env python3
"""List the open ready-for-agent issues no open issue blocks. Changes nothing.

Run from inside the repo: gh is asked about origin's github.com repo, whatever
GH_REPO says. Prints, oldest first:

  ## Ready     issues with no open blocker
  ## Blocked   the other ready-for-agent issues, each with its open blockers

A blocker is a native dependency or a `Blocked by: #n` line in the issue body;
`owner/repo#n` there names another repo's issue, looked up in that repo.
The first cut is the search `-is:blocked`, which counts only open native
blockers. GitHub does not document that qualifier; it was checked by hand on
2026-11-02. Where search rejects it, every issue's native blockers are read
through the API instead, every page of them. Exit 1: gh failed, or origin is
no github.com repo.
"""
import json
import os
import re
import subprocess
import sys

LIST = ["gh", "issue", "list", "--state", "open", "--label", "ready-for-agent", "--limit", "1000",
        "--json", "number,title,body,createdAt"]
BODY_BLOCKER = re.compile(r"^\s*Blocked by:?(.*)$", re.I | re.M)
# #12 is this repo's issue, owner/repo#12 another repo's; the lookbehind keeps the second from reading as #12.
BLOCKER_REF = re.compile(r"(?<![\w/.-])((?:[\w.-]+/[\w.-]+)?)#(\d+)")


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"gh {' '.join(args)}: {r.stderr.strip() or r.returncode}")
    return r


def origin_repo():
    """owner/name of origin on github.com, from the configured URL (before any insteadOf)."""
    url = subprocess.run(["git", "config", "--get", "remote.origin.url"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    if not m:
        sys.exit(f"origin's URL ({url or 'none'}) names no github.com repo, so there is no repo to ask gh about.")
    return m.group(1)


def main():
    if len(sys.argv) > 1:
        print(__doc__.strip())
        return 0 if sys.argv[1] in ("-h", "--help") else 1

    repo = os.environ["GH_REPO"] = origin_repo()  # an inherited GH_REPO would point gh at another repo
    issues = json.loads(gh(*LIST[1:]).stdout)
    first_cut = gh(*LIST[1:], "--search", "-is:blocked", check=False)
    natively_free = {i["number"] for i in json.loads(first_cut.stdout)} if first_cut.returncode == 0 else set()

    states = {}

    def is_open(ref):
        if ref not in states:
            other, n = ref
            where = ["--repo", other] if other else []
            states[ref] = gh("issue", "view", n, *where, "--json", "state", "--jq", ".state").stdout.strip().upper()
        return states[ref] == "OPEN"

    ready, blocked = [], []
    for issue in sorted(issues, key=lambda i: (i.get("createdAt") or "", i["number"])):
        open_blockers = set()
        if issue["number"] not in natively_free:
            pages = json.loads(gh("api", "--paginate", "--slurp",
                                  f"repos/{repo}/issues/{issue['number']}/dependencies/blocked_by").stdout)
            native = [b for page in pages for b in page]
            open_blockers |= {f"#{b['number']}" for b in native if b["state"].lower() == "open"}
        for line in BODY_BLOCKER.findall(issue["body"] or ""):
            open_blockers |= {f"{other}#{n}" for other, n in BLOCKER_REF.findall(line) if is_open((other, n))}
        (blocked if open_blockers else ready).append((issue, sorted(open_blockers)))

    print("## Ready")
    for issue, _ in ready:
        print(f"- #{issue['number']} {issue['title']}")
    print("\n## Blocked")
    for issue, by in blocked:
        print(f"- #{issue['number']} {issue['title']}: blocked by " + ", ".join(by))
    return 0


if __name__ == "__main__":
    sys.exit(main())
