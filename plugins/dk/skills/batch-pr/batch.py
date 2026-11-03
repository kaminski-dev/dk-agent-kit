#!/usr/bin/env python3
"""Collect what the batch PR from pre-main into main carries. Opens nothing.

Run from inside the repo. Every gh call asks about origin's github.com repo, whatever
GH_REPO says. It fetches origin's main and pre-main, then prints:

  ## PRs              each PR merged into pre-main that main does not hold yet
  ## Lines            their Closes #N / Refs #N lines, one per issue
  ## Without a line   merged PRs whose body names no issue

Exit 0: collected. Exit 3: a PR from pre-main into main is already open; its
URL is printed. Exit 4: nothing to batch (no pre-main on origin, or pre-main
holds no commit that main lacks). Exit 1: git or gh failed, origin is no
github.com repo, a PR merged into pre-main has a merge commit this clone does
not hold (it names them), or pre-main holds merge commits that no merged PR of
origin's repo matches (it names the repo).
Both branches are fetched by name, so a single-branch clone gets pre-main too;
a shallow clone is deepened first.

An issue named by both a Closes and a Refs line gets Refs: a post-deploy
check outranks closing on merge.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

BRANCHES = ("main", "pre-main")
ISSUE_LINE = re.compile(r"^\s*(close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs)(?::\s*|\s+)#(\d+)\s*$", re.I | re.M)


def sh(*cmd, ok=(0,)):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in ok:
        sys.exit(f"{' '.join(cmd)}: {r.stderr.strip() or r.returncode}")
    return r


def origin_repo():
    """owner/name of origin on github.com, from the configured URL (before any insteadOf)."""
    url = sh("git", "config", "--get", "remote.origin.url", ok=(0, 1)).stdout.strip()
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    if not m:
        sys.exit(f"origin's URL ({url or 'none'}) names no github.com repo, so there is no repo to ask gh about.")
    return m.group(1)


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

    repo = os.environ["GH_REPO"] = origin_repo()  # an inherited GH_REPO would point gh at another repo
    open_batch = gh_json("pr", "list", "--base", "main", "--head", "pre-main", "--state", "open", "--json", "url")
    if open_batch:
        print(f"A batch PR is already open: {open_batch[0]['url']}")
        return 3

    if not sh("git", "ls-remote", "--heads", "origin", "pre-main").stdout.strip():
        print("Nothing to batch: origin has no pre-main.")
        return 4
    # Explicit refspecs: a single-branch clone's configured one would leave origin/pre-main uncreated.
    shallow = sh("git", "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    sh("git", "fetch", "-q", *(["--unshallow"] if shallow else []), "origin",
       *(f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in BRANCHES))
    for b in BRANCHES:
        if sh("git", "rev-parse", "-q", "--verify", f"refs/remotes/origin/{b}^{{commit}}", ok=(0, 1)).returncode:
            sys.exit(f"origin/{b} is missing after fetching it; the range origin/main..origin/pre-main cannot be read.")
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
    if not batch and sh("git", "rev-list", "--merges", "origin/main..origin/pre-main").stdout.strip():
        sys.exit(f"origin/main..origin/pre-main holds merge commits, but no PR merged into pre-main of "
                 f"{repo} since {since} matches one. Check that {repo} "
                 "is where this checkout's PRs are merged.")
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
