#!/usr/bin/env python3
"""Wait for the review bot's verdict on a PR's head commit (dk:issue-flow step 6).

    python3 -I wait-review.py <PR> [--bot LOGIN] [--polls 40] [--interval 30]

Run it in the repo's checkout (or with GH_REPO set). It polls every --interval
seconds and reads the head on every poll; a new head restarts the count.

Exit codes, with the verdict on stdout:
  0  `reviews <id>...`: the bot's reviews of the head, or `clean`: a round with no findings
  1  no verdict after --polls polls (20 minutes by default)
  2  a gh call failed; its error is on stderr
  3  `rate limited` or `paused`: the bot will not review this head on its own
"""
import argparse
import json
import subprocess
import sys
import time

RATE_LIMITED = ("<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->",
                "<!-- end of auto-generated comment: rate limited by coderabbit.ai -->")
RECENT = ("<!-- recent_review_start -->", "<!-- recent_review_end -->")


class GhFailed(Exception):
    pass


def gh(*args):
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhFailed(f"gh {' '.join(args)}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def gh_list(path):
    """Every item of a paginated list endpoint; --paginate prints one JSON array per page."""
    out, items, decoder, i = gh("api", "--paginate", path), [], json.JSONDecoder(), 0
    while i < len(out):
        if out[i].isspace():
            i += 1
            continue
        page, i = decoder.raw_decode(out, i)
        items.extend(page)
    return items


def section(body, markers):
    start, end = markers
    return body.split(start, 1)[1].split(end, 1)[0] if start in body else ""


def head(pr):
    view = json.loads(gh("pr", "view", pr, "--json", "headRefOid,commits"))
    return view["headRefOid"], view["commits"][-1]["committedDate"]


def reviews_of(pr, bot, sha):
    """The bot's reviews of sha that carry findings: a body, or inline comments that start a thread."""
    reviews = [r for r in gh_list(f"repos/{{owner}}/{{repo}}/pulls/{pr}/reviews")
               if r["user"]["login"] == bot and r["commit_id"] == sha]
    if not reviews:
        return []
    own = {c["pull_request_review_id"] for c in gh_list(f"repos/{{owner}}/{{repo}}/pulls/{pr}/comments")
           if c["user"]["login"] == bot and c.get("in_reply_to_id") is None}
    return [str(r["id"]) for r in reviews if r.get("body") or r["id"] in own]


def summary_verdict(pr, bot, sha, since):
    for c in gh_list(f"repos/{{owner}}/{{repo}}/issues/{pr}/comments"):
        if c["user"]["login"] != bot:
            continue
        body = c.get("body") or ""
        if "review in progress" in body:
            return None
        if f"and {sha}" in section(body, RECENT):
            return 0, "clean"
        if "rate limited" in body and f"and {sha}" in body:
            return 3, "rate limited"
        if "Reviews paused" in body and c["updated_at"] > since:
            return 3, "paused"
    return None


def wait(pr, bot, polls, interval):
    current, polled = None, 0
    while polled < polls:
        sha, since = head(pr)
        if sha != current:  # a new head restarts the count
            current, polled = sha, 0
        found = reviews_of(pr, bot, sha)
        verdict = (0, "reviews " + " ".join(found)) if found else summary_verdict(pr, bot, sha, since)
        if verdict:
            if head(pr)[0] == sha:
                return verdict
            continue  # the head moved: the next poll takes it
        polled += 1
        time.sleep(interval)
    return 1, f"no verdict from {bot} on {current} after {polls} polls"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pr")
    ap.add_argument("--bot", default="coderabbitai[bot]")
    ap.add_argument("--polls", type=int, default=40)
    ap.add_argument("--interval", type=float, default=30)
    args = ap.parse_args()
    try:
        code, line = wait(args.pr, args.bot, args.polls, args.interval)
    except GhFailed as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    print(line)
    sys.exit(code)


if __name__ == "__main__":
    main()
