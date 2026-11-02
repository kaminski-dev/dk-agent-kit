#!/usr/bin/env python3
"""Runs dk:issue-flow's wait-review.py against a stubbed gh.

Each case is one PR state, served by a fake `gh` on PATH. The comment bodies
copy the shapes CodeRabbit writes: its summary comment with the recent-review
block, the rate-limit notice and the pause notice.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "plugins", "dk", "skills", "issue-flow", "wait-review.py")
BOT = {"login": "coderabbitai[bot]"}
OLD, HEAD, NEW = "0" * 40, "1" * 40, "2" * 40

STUB = r'''#!/usr/bin/env python3
import json, os, sys
fix = json.load(open(os.environ["FIX"]))
args = sys.argv[1:]
if args[:2] == ["pr", "view"]:
    name = "pr"
else:
    path = next(a for a in args if a.startswith("repos/"))
    name = "reviews" if path.endswith("/reviews") else "inline" if "/pulls/" in path else "notes"
delays = {fix.get("stall"): 10, fix.get("slow"): 3}
if name in delays:
    import time
    time.sleep(delays[name])
if fix.get("fail") == name:
    print('{"message":"API rate limit exceeded"}')
    print("gh: API rate limit exceeded (HTTP 403)", file=sys.stderr)
    sys.exit(1)
if name == "pr":
    count = os.path.join(os.environ["STATE"], "views")
    n = int(open(count).read()) if os.path.exists(count) else 0
    open(count, "w").write(str(n + 1))
    heads = fix["heads"]
    sha, date = heads[min(n, len(heads) - 1)]
    print(json.dumps({"headRefOid": sha}))
else:
    print(json.dumps(fix.get(name, [])))
'''


def summary(recent="", notice="", updated="2026-11-02T12:05:00Z"):
    body = notice + "\n<!-- recent_review_start -->\n" + recent + "\n<!-- recent_review_end -->\n" if recent else notice
    return {"user": BOT, "updated_at": updated, "body": body}


def reviewed(sha, verdict="No actionable comments were generated in the recent review.\n"):
    return verdict + f"Reviewing files that changed from the base of the PR and between {OLD} and {sha}."


def rate_limited(sha):
    return ("<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->\n"
            f"> Reviewing files that changed from the base of the PR and between {OLD} and {sha}.\n"
            "<!-- end of auto-generated comment: rate limited by coderabbit.ai -->\n")


def paused(last, latest):
    return ("<!-- This is an auto-generated comment: review paused by coderabbit.ai -->\n> ## Reviews paused\n"
            f"> - Last reviewed commit: {last}\n> - Latest commit, not reviewed: {latest}\n"
            "<!-- end of auto-generated comment: review paused by coderabbit.ai -->\n")


AT_NOON = [[HEAD, "2026-11-02T12:00:00Z"]]

CASES = {
    "review with a body": (dict(heads=AT_NOON, reviews=[{"id": 7, "user": BOT, "commit_id": HEAD, "body": "x"}]),
                           0, "reviews 7"),
    "bodiless review with its own inline comment": (dict(
        heads=AT_NOON, reviews=[{"id": 7, "user": BOT, "commit_id": HEAD, "body": ""}],
        inline=[{"user": BOT, "in_reply_to_id": None, "pull_request_review_id": 7}]), 0, "reviews 7"),
    "thread reply is not a review": (dict(
        heads=AT_NOON, reviews=[{"id": 8, "user": BOT, "commit_id": HEAD, "body": ""}],
        inline=[{"user": BOT, "in_reply_to_id": 3, "pull_request_review_id": 8}]), 1, "no verdict"),
    "review of an older commit": (dict(heads=AT_NOON, reviews=[{"id": 9, "user": BOT, "commit_id": OLD, "body": "x"}]),
                                  1, "no verdict"),
    "clean round": (dict(heads=AT_NOON, notes=[summary(reviewed(HEAD))]), 0, "clean"),
    "review in progress": (dict(heads=AT_NOON, notes=[summary(reviewed(HEAD), "review in progress by coderabbit.ai\n")]),
                           1, "no verdict"),
    "rate limited on the head": (dict(heads=AT_NOON, notes=[summary(reviewed(OLD), rate_limited(HEAD))]),
                                 3, "rate limited"),
    "paused after the head commit": (dict(heads=AT_NOON, notes=[summary(notice=paused(OLD, HEAD))]), 3, "paused"),
    "pause older than the head commit": (dict(
        heads=AT_NOON, notes=[summary(notice=paused(OLD, OLD), updated="2026-11-02T11:00:00Z")]), 1, "no verdict"),
    "rate-limit notice in the recent-review block": (dict(
        heads=AT_NOON, notes=[summary(rate_limited(HEAD) + reviewed(OLD))]), 3, "rate limited"),
    "recent review of the head without a verdict": (dict(
        heads=AT_NOON, notes=[summary(reviewed(HEAD, verdict=""))]), 1, "no verdict"),
    "pause naming an older commit, written after the head commit was made": (dict(
        heads=AT_NOON, notes=[summary(notice=paused(OLD, OLD), updated="2026-11-02T12:30:00Z")]), 1, "no verdict"),
    "stalled gh call stops the wait": (dict(
        heads=AT_NOON, stall="reviews", args=["--gh-timeout", "1", "--minutes", "1"], err="timed out"), 2, ""),
    "slow successful gh calls end the wait on time": (dict(
        heads=AT_NOON, slow="reviews", args=["--minutes", str(1 / 60)], within=2.5), 1, f"no verdict from {BOT['login']} on {HEAD}"),
    "gh failure stops the wait": (dict(heads=AT_NOON, fail="reviews", err="rate limit"), 2, ""),
    "head moves after a match": (dict(
        heads=[[HEAD, "2026-11-02T12:00:00Z"], [NEW, "2026-11-02T12:10:00Z"]],
        reviews=[{"id": 9, "user": BOT, "commit_id": HEAD, "body": "x"}]), 1, f"on {NEW}"),
    "head moves before any review": (dict(
        heads=[[HEAD, "2026-11-02T12:00:00Z"], [NEW, "2026-11-02T12:10:00Z"]],
        reviews=[{"id": 10, "user": BOT, "commit_id": NEW, "body": "x"}]), 0, "reviews 10"),
}


def run(root, name, fix):
    case = os.path.join(root, name.replace(" ", "-"))
    os.makedirs(case)
    with open(os.path.join(case, "fix.json"), "w") as f:
        json.dump(fix, f)
    env = {"PATH": f"{root}/bin:{os.environ['PATH']}", "FIX": f"{case}/fix.json", "STATE": case}
    start = time.monotonic()
    proc = subprocess.run([sys.executable, "-I", SCRIPT, "1", "--minutes", "0.01", "--interval", "0", *fix.get("args", [])],
                          capture_output=True, text=True, env=env, timeout=30)
    return proc, time.monotonic() - start


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(f"{root}/bin")
        with open(f"{root}/bin/gh", "w") as f:
            f.write(STUB)
        os.chmod(f"{root}/bin/gh", 0o755)
        for name, (fix, code, out) in CASES.items():
            proc, took = run(root, name, fix)
            within = fix.get("within", 25)
            if proc.returncode == code and out in proc.stdout and fix.get("err", "") in proc.stderr and took <= within:
                print(f"ok   {name}")
            else:
                failed += 1
                print(f"FAIL {name}: exit {proc.returncode} (want {code}), stdout {proc.stdout.strip()!r} "
                      f"(want {out!r}), stderr {proc.stderr.strip()[-200:]!r}, {took:.1f} s (want <= {within} s)")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
