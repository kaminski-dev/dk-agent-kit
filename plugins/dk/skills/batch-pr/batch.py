#!/usr/bin/env python3
"""Collect what the batch PR from pre-main into main carries. Opens nothing.

Run from inside the repo. It fetches origin's main and pre-main, then prints:

  ## PRs              each PR merged into pre-main that main does not hold yet
  ## Lines            their Closes #N / Refs #N lines, one per issue
  ## Without a line   merged PRs whose body names no issue

Exit 0: collected. Exit 3: a PR from pre-main into main is already open; its
URL is printed. Exit 4: nothing to batch (no pre-main on origin, or pre-main
holds no commit that main lacks). Exit 1: git or gh failed, or a PR merged
into pre-main has a merge commit this clone does not hold; it names them.
A shallow clone is deepened first.

An issue named by both a Closes and a Refs line gets Refs: a post-deploy
check outranks closing on merge.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ISSUE_LINE = re.compile(r"^\s*(close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs)(?::\s*|\s+)#(\d+)\s*$", re.I | re.M)


def sh(*cmd, ok=(0,)):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in ok:
        sys.exit(f"{' '.join(cmd)}: {r.stderr.strip() or r.returncode}")
    return r


def gh_json(*args):
    return json.loads(sh("gh", *args).stdout or "[]")


def merged_since(day):
    """PRs merged into pre-main on or after day, re-asked with a doubled limit until gh returns fewer."""
    limit = 100
    while True:
        merged = gh_json("pr", "list", "--base", "pre-main", "--state", "merged", "--search", f"merged:>={day}",
                         "--limit", str(limit), "--json", "number,title,body,mergeCommit")
        if len(merged) < limit:
            return merged
        limit *= 2


def main():
    if len(sys.argv) > 1:
        print(__doc__.strip())
        return 0 if sys.argv[1] in ("-h", "--help") else 1

    open_batch = gh_json("pr", "list", "--base", "main", "--head", "pre-main", "--state", "open", "--json", "url")
    if open_batch:
        print(f"A batch PR is already open: {open_batch[0]['url']}")
        return 3

    if not sh("git", "ls-remote", "--heads", "origin", "pre-main").stdout.strip():
        print("Nothing to batch: origin has no pre-main.")
        return 4
    if sh("git", "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        sh("git", "fetch", "-q", "--unshallow", "origin", "main", "pre-main")
    sh("git", "fetch", "-q", "origin", "main", "pre-main")
    in_batch = set(sh("git", "rev-list", "origin/main..origin/pre-main").stdout.split())
    if not in_batch:
        print("Nothing to batch: pre-main is not ahead of main.")
        return 4
    # A merge lands on pre-main's first-parent line when it is merged, so no batch PR was merged before
    # the oldest of those commit times; a day earlier absorbs the time zone of search's merged: date.
    merged_at = sh("git", "log", "--first-parent", "--format=%ct", "origin/main..origin/pre-main").stdout.split()
    since = (datetime.fromtimestamp(min(map(int, merged_at)), timezone.utc) - timedelta(days=1)).date().isoformat()

    merged = merged_since(since)
    batch, unknown = [], []
    for p in merged:
        oid = (p.get("mergeCommit") or {}).get("oid")
        if oid in in_batch:
            batch.append(p)
        elif not oid or sh("git", "cat-file", "-e", f"{oid}^{{commit}}", ok=(0, 1, 128)).returncode != 0:
            unknown.append(p)
    if unknown:
        names = ", ".join(f"#{p['number']}" for p in unknown)
        sys.exit(f"Merged into pre-main since {since}, but their merge commit is not in this clone: {names}. "
                 "Fetch it, or check whether pre-main was rewritten, before opening the batch PR.")
    batch.sort(key=lambda p: p["number"])

    kind_of, without = {}, []
    for p in batch:
        found = ISSUE_LINE.findall(p["body"] or "")
        if not found:
            without.append(p)
        for word, issue in found:
            kind = "Refs" if word.lower() == "refs" else "Closes"
            kind_of[int(issue)] = "Refs" if kind_of.get(int(issue)) == "Refs" else kind

    print("## PRs")
    for p in batch:
        print(f"- #{p['number']} {p['title']}")
    print("\n## Lines")
    for issue in sorted(kind_of):
        print(f"{kind_of[issue]} #{issue}")
    if without:
        print("\n## Without a line")
        for p in without:
            print(f"- #{p['number']} {p['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
