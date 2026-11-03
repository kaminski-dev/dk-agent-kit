#!/usr/bin/env python3
"""Runs dk:issue-flow's wait-review.py against a stubbed gh.

Each case is one PR state, served by a fake `gh` on PATH, which logs the GH_REPO
each call carried. The script runs in a checkout whose origin is acme/ledger on
github.com. The comment bodies copy the shapes CodeRabbit writes: its summary
comment with its status and recent-review blocks, the rate-limit notice and the pause notice.
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
with open(os.path.join(os.environ["STATE"], "repos"), "a") as f:
    f.write(os.environ.get("GH_REPO", "-") + "\n")
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
    # the lock keeps concurrent views from losing a count; the replace keeps a view
    # killed mid-write (wait-review.py's deadline does that) from leaving an empty file
    import fcntl
    count = os.path.join(os.environ["STATE"], "views")
    with open(count + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        n = int(open(count).read() or 0) if os.path.exists(count) else 0
        tmp = f"{count}.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(str(n + 1))
        os.replace(tmp, count)
    heads = fix["heads"]
    sha, date = heads[min(n, len(heads) - 1)]
    print(json.dumps({"headRefOid": sha}))
else:
    print(json.dumps(fix.get(name, [])))
'''


def summary(recent="", notice="", updated="2026-11-02T12:05:00Z"):
    body = notice + "\n<!-- recent_review_start -->\n" + recent + "\n<!-- recent_review_end -->\n" if recent else notice
    return {"user": BOT, "updated_at": updated, "body": body}


def status(verdict="No actionable comments were generated in the recent review."):
    """The status block above the walkthrough, where a clean round now puts its verdict; the SHA stays in the recent-review block."""
    return f"<!-- recent_review_status_start -->\n\n{verdict}\n\n<!-- recent_review_status_end -->\n<!-- walkthrough_start -->\n"


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
    "clean round in the status block": (dict(
        heads=AT_NOON, notes=[summary(reviewed(HEAD, verdict=""), status())]), 0, "clean"),
    "clean status block for an older commit": (dict(
        heads=AT_NOON, notes=[summary(reviewed(OLD, verdict=""), status())]), 1, "no verdict"),
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
    "push during the last sleep restarts the wait": (dict(
        heads=[[HEAD, "2026-11-02T12:00:00Z"], [NEW, "2026-11-02T12:10:00Z"]], args=["--minutes", str(1 / 60), "--interval", "5"],
        reviews=[{"id": 11, "user": BOT, "commit_id": NEW, "body": "x"}], within=4), 0, "reviews 11"),
    "an inherited GH_REPO: every gh call asks for origin's repo": (dict(
        heads=AT_NOON, reviews=[{"id": 12, "user": BOT, "commit_id": HEAD, "body": "x"}],
        env={"GH_REPO": "kaminski-dev/dk-agent-kit"}, repo="acme/ledger"), 0, "reviews 12"),
}


def case_env(root, name, fix):
    case = os.path.join(root, name.replace(" ", "-"))
    os.makedirs(case)
    with open(os.path.join(case, "fix.json"), "w") as f:
        json.dump(fix, f)
    return case, {"PATH": f"{root}/bin:{os.environ['PATH']}", "FIX": f"{case}/fix.json", "STATE": case}


def run(root, name, fix):
    case, env = case_env(root, name, fix)
    start = time.monotonic()
    proc = subprocess.run([sys.executable, "-I", SCRIPT, "1", "--minutes", "0.01", "--interval", "0", *fix.get("args", [])],
                          capture_output=True, text=True, env={**env, **fix.get("env", {})}, cwd=f"{root}/checkout",
                          timeout=30)
    log = os.path.join(case, "repos")
    repos = set(open(log).read().split()) if os.path.exists(log) else set()
    return proc, time.monotonic() - start, repos


def concurrent_pr_views(root, calls):
    case, env = case_env(root, "concurrent pr views", dict(heads=AT_NOON))
    procs = [subprocess.Popen(["gh", "pr", "view", "1", "--json", "headRefOid"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(calls)]
    errors = []
    for p in procs:
        _, err = p.communicate(timeout=30)
        if p.returncode:
            errors.append(err.strip().splitlines()[-1] if err.strip() else f"exit {p.returncode}")
    views = os.path.join(case, "views")
    if not os.path.exists(views):
        return errors, ""
    with open(views) as f:
        return errors, f.read()


def main():
    failed, total = 0, len(CASES) + 1
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(f"{root}/bin")
        with open(f"{root}/bin/gh", "w") as f:
            f.write(STUB)
        os.chmod(f"{root}/bin/gh", 0o755)
        subprocess.run(["git", "init", "-q", f"{root}/checkout"], check=True)
        subprocess.run(["git", "-C", f"{root}/checkout", "remote", "add", "origin", "https://github.com/acme/ledger.git"],
                       check=True)
        calls = 40
        errors, views = concurrent_pr_views(root, calls)
        if errors or views != str(calls):
            failed += 1
            print(f"FAIL concurrent pr views: {len(errors)} of {calls} crashed {errors[:1]}, counter {views!r} (want '{calls}')")
        else:
            print("ok   concurrent pr views")
        for name, (fix, code, out) in CASES.items():
            proc, took, repos = run(root, name, fix)
            within = fix.get("within", 25)
            if proc.returncode == code and out in proc.stdout and fix.get("err", "") in proc.stderr and took <= within \
                    and ("repo" not in fix or repos == {fix["repo"]}):
                print(f"ok   {name}")
            else:
                failed += 1
                print(f"FAIL {name}: exit {proc.returncode} (want {code}), stdout {proc.stdout.strip()!r} "
                      f"(want {out!r}), stderr {proc.stderr.strip()[-200:]!r}, {took:.1f} s (want <= {within} s), "
                      f"GH_REPO {sorted(repos)} (want {fix.get('repo', 'any')!r})")
    print(f"\n{total - failed}/{total} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
