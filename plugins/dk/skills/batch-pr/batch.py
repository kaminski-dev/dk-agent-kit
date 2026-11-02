#!/usr/bin/env python3
"""Collect what the batch PR from pre-main into main carries. Opens nothing.

Run from inside the repo. It fetches origin's main and pre-main, then prints:

  ## PRs              each PR merged into pre-main that main does not hold yet
  ## Lines            their Closes #N / Refs #N lines, one per issue
  ## Without a line   merged PRs whose body names no issue

Exit 0: collected. Exit 3: a PR from pre-main into main is already open; its
URL is printed. Exit 4: nothing to batch (no pre-main on origin, or pre-main
holds no commit that main lacks). Exit 1: git or gh failed.

An issue named by both a Closes and a Refs line gets Refs: a post-deploy
check outranks closing on merge.
"""
import json
import re
import subprocess
import sys

LINE = re.compile(r"^\s*(close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs)\s+#(\d+)\s*$", re.I | re.M)


def sh(*cmd, ok=(0,)):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in ok:
        sys.exit(f"{' '.join(cmd)}: {r.stderr.strip() or r.returncode}")
    return r


def gh_json(*args):
    return json.loads(sh("gh", *args).stdout or "[]")


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
    sh("git", "fetch", "-q", "origin", "main", "pre-main")
    ahead = int(sh("git", "rev-list", "--count", "origin/main..origin/pre-main").stdout)
    if not ahead:
        print("Nothing to batch: pre-main is not ahead of main.")
        return 4

    def holds(ref, oid):
        return sh("git", "merge-base", "--is-ancestor", oid, ref, ok=(0, 1, 128)).returncode == 0

    merged = gh_json("pr", "list", "--base", "pre-main", "--state", "merged", "--limit", "200",
                     "--json", "number,title,body,mergeCommit")
    batch = sorted((p for p in merged if p.get("mergeCommit")
                    and holds("origin/pre-main", p["mergeCommit"]["oid"])
                    and not holds("origin/main", p["mergeCommit"]["oid"])), key=lambda p: p["number"])

    keyword, without = {}, []
    for p in batch:
        found = LINE.findall(p["body"] or "")
        if not found:
            without.append(p)
        for word, issue in found:
            kind = "Refs" if word.lower() == "refs" else "Closes"
            keyword[int(issue)] = "Refs" if keyword.get(int(issue)) == "Refs" else kind

    print("## PRs")
    for p in batch:
        print(f"- #{p['number']} {p['title']}")
    print("\n## Lines")
    for issue in sorted(keyword):
        print(f"{keyword[issue]} #{issue}")
    if without:
        print("\n## Without a line")
        for p in without:
            print(f"- #{p['number']} {p['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
