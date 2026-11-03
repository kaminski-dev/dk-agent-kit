#!/usr/bin/env python3
"""Runs dk:issue-flow's pr-wait against a stubbed gh.

Each case is one PR state, served by a fake `gh` on PATH that logs every call
with the GH_REPO it carried. The GraphQL answer comes from the case's `polls`
list, one entry per poll (the last one repeats), or from its `timeline`, picked
by the seconds since the first poll; `check_polls` does the same for the checks. The watcher runs in a checkout whose origin
is acme/ledger on github.com, with HOME in the case's directory so its lock and
state files stay there. The summary-comment bodies copy the shapes CodeRabbit
writes: its status and recent-review blocks, the rate-limit and the pause notice.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "plugins", "dk", "skills", "issue-flow", "pr-wait")
OLD, HEAD, NEW = "0" * 40, "1" * 40, "2" * 40
BASE, MOVED = "a" * 40, "b" * 40
ME = {"login": "kaminski-dev", "__typename": "User"}
BOT = {"login": "coderabbitai", "__typename": "Bot"}  # GraphQL names a bot without REST's [bot]
NO_FINDINGS = "No actionable comments were generated in the recent review."
NOTE = "> [!NOTE]\n> **Claude Opus 5.5 responding on behalf of kaminski-dev**\n\n"

STUB = r'''#!/usr/bin/env python3
import fcntl, json, os, sys, time
fix = json.load(open(os.environ["FIX"]))
state = os.environ["STATE"]
args = sys.argv[1:]
with open(os.path.join(state, "calls"), "a") as f:
    f.write(json.dumps([os.environ.get("GH_REPO", "-"), args]) + "\n")


def count(name):
    """How many calls of this kind came before; the lock keeps concurrent calls from losing one."""
    path = os.path.join(state, name + ".count")
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        n = int(open(path).read() or 0) if os.path.exists(path) else 0
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(str(n + 1))
        os.replace(tmp, path)
        return n


if args[:2] in (["pr", "view"], ["pr", "checks"], ["pr", "diff"], ["api", "graphql"]):
    name = args[1]
else:
    path = next(a for a in args if a.startswith("repos/"))
    name = "rules" if "/rules/" in path else "protection" if "/protection/" in path else "compare"
n = count(name)
if n < fix.get("fail", {}).get(name, 0):
    print("gh: HTTP 502: Bad Gateway (https://api.github.com/graphql)", file=sys.stderr)
    sys.exit(1)
if n < fix.get("rate_limit", {}).get(name, 0):
    print("gh: API rate limit exceeded for user ID 1. (HTTP 403)", file=sys.stderr)
    sys.exit(1)
if name in fix.get("forbid", []):
    print("gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)", file=sys.stderr)
    sys.exit(1)
if name == "view":
    print(json.dumps({"number": 1}))
elif name == "checks":
    rows = fix["check_polls"][min(n, len(fix["check_polls"]) - 1)] if "check_polls" in fix else fix.get("checks", [])
    if not rows:
        print("no checks reported on the 'feat/1-x' branch", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(rows))
    buckets = {r["bucket"] for r in rows}
    sys.exit(1 if buckets & {"fail", "cancel"} else 8 if "pending" in buckets else 0)
elif name == "diff":
    print("\n".join(fix.get("files", [])))
elif name == "graphql":
    if "timeline" in fix:
        start = os.path.join(state, "start")
        if not os.path.exists(start):
            open(start, "w").write(str(time.time()))
        elapsed = time.time() - float(open(start).read())
        poll = [p for at, p in fix["timeline"] if at <= elapsed][-1]
    else:
        poll = fix["polls"][min(n, len(fix["polls"]) - 1)]
    print(json.dumps({"data": {"viewer": {"login": "kaminski-dev"}, "repository": {"pullRequest": poll}}}))
elif name == "rules":
    print("\n".join(fix.get("required", [])))
elif name == "protection":
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    sys.exit(1)
else:
    jq = args[args.index("--jq") + 1]
    print(fix.get("behind_by", 0) if jq == ".behind_by" else "\n".join(fix.get("moved", [])))
'''


def pr(head=HEAD, state="OPEN", merge="CLEAN", base=BASE, comments=(), reviews=(), threads=()):
    return {
        "url": "https://github.com/acme/ledger/pull/1", "state": state, "headRefOid": head, "baseRefName": "main",
        "mergeStateStatus": merge, "author": ME, "baseRef": {"target": {"oid": base}},
        "comments": {"nodes": list(comments)}, "reviews": {"nodes": list(reviews)},
        "reviewThreads": {"nodes": list(threads)},
    }


def comment(body, author=ME, id="IC_1"):
    return {"id": id, "url": f"https://github.com/acme/ledger/pull/1#{id}", "body": body, "author": author}


def review(db_id, body="", commit=HEAD, author=BOT, state="COMMENTED"):
    return {"id": f"PRR_{db_id}", "databaseId": db_id, "url": f"https://github.com/acme/ledger/pull/1#r{db_id}",
            "state": state, "body": body, "commit": {"oid": commit}, "author": author}


def thread(*nodes, resolved=False, path="src/app.py", line=12):
    return {"isResolved": resolved, "path": path, "line": line, "comments": {"nodes": list(nodes)}}


def inline(review_id, body="Rename this.", author=BOT, id="RC_1"):
    return {"id": id, "url": f"https://github.com/acme/ledger/pull/1#{id}", "body": body, "author": author,
            "pullRequestReview": {"databaseId": review_id}}


def summary(recent="", notice=""):
    body = notice + "\n<!-- recent_review_start -->\n" + recent + "\n<!-- recent_review_end -->\n" if recent else notice
    return comment(body, author=BOT, id="IC_summary")


def status(verdict=NO_FINDINGS):
    """The status block above the walkthrough, where a clean round puts its verdict; the SHA stays in the recent-review block."""
    return f"<!-- recent_review_status_start -->\n\n{verdict}\n\n<!-- recent_review_status_end -->\n<!-- walkthrough_start -->\n"


def reviewed(sha, verdict=NO_FINDINGS + "\n"):
    return verdict + f"Reviewing files that changed from the base of the PR and between {OLD} and {sha}."


def rate_limited(sha):
    return ("<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->\n"
            f"> Reviewing files that changed from the base of the PR and between {OLD} and {sha}.\n"
            "<!-- end of auto-generated comment: rate limited by coderabbit.ai -->\n")


def paused(last, latest):
    return ("<!-- This is an auto-generated comment: review paused by coderabbit.ai -->\n> ## Reviews paused\n"
            f"> - Last reviewed commit: {last}\n> - Latest commit, not reviewed: {latest}\n"
            "<!-- end of auto-generated comment: review paused by coderabbit.ai -->\n")


GREEN = [{"name": "test", "bucket": "pass", "link": "https://ci/test", "description": ""}]
FAILED = [{"name": "test", "bucket": "fail", "link": "https://ci/test", "description": ""}]
QUIET = ["--minutes", str(1.5 / 60)]  # a case whose event must not come ends at its deadline
HUMAN = "Please rename the flag"

# name: (fixture, exit code, lines stdout must hold, text stdout must not hold)
CASES = {
    "a required check not yet started": (dict(
        polls=[pr()], required=["test"], args=["--until", "green", *QUIET],
        checks=[{"name": "lint", "bucket": "pass", "link": "https://ci/lint", "description": ""}]),
        1, ["deadline passed"], "#1 green on"),
    "checks green": (dict(polls=[pr()], required=["test"], checks=GREEN, args=["--until", "green"]),
                     0, ["green on 1111111"], "deadline"),
    "a check that registers late is not green by omission": (dict(
        polls=[pr()], check_polls=[GREEN, GREEN + [{"name": "e2e", "bucket": "pending", "link": "", "description": ""}]],
        args=["--until", "green", *QUIET]), 1, ["deadline passed"], "#1 green on"),
    "no checks and none required on a fresh head is not green yet": (dict(polls=[pr()], args=["--until", "green", *QUIET]),
                                                                      1, ["deadline passed"], "#1 green on"),
    "no checks and none required, stable, on a head seen 3 minutes ago is green": (dict(
        polls=[pr()], env={"PR_WAIT_REGISTER_SECONDS": "0"}, args=["--until", "green"]),
        0, ["green on 1111111: no checks reported"], "deadline"),
    "the review bot's own check never gates": (dict(
        polls=[pr()], args=["--until", "green"],
        checks=GREEN + [{"name": "CodeRabbit", "bucket": "pending", "link": "", "description": ""}]),
        0, ["green on 1111111"], "deadline"),
    "a check named like the bot's first letters gates": (dict(
        polls=[pr()], args=["--until", "green"],
        checks=GREEN + [{"name": n, "bucket": "fail", "link": "https://ci/x", "description": ""}
                        for n in ("code-lint", "Code style", "coder")]),
        1, ["check failed: code-lint", "check failed: Code style", "check failed: coder"], "#1 green on"),
    "a check failed": (dict(polls=[pr()], required=["test"], checks=FAILED),
                       1, ["required check failed: test https://ci/test"], "#1 ready on"),
    "a human comment from the gh user": (dict(
        polls=[pr(), pr(comments=[comment(HUMAN)])], checks=GREEN, args=["--until", "any-change"]),
        0, [f"comment from kaminski-dev: {HUMAN}"], "deadline"),
    "an attributed agent comment is dropped": (dict(
        polls=[pr(), pr(comments=[comment(NOTE + "Fixed in abc1234.")])], checks=GREEN,
        args=["--until", "any-change", *QUIET]), 1, ["deadline passed"], "comment from"),
    "an attributed thread reply is dropped, the maintainer's reply is not": (dict(
        polls=[pr(threads=[thread(inline(5, author=ME, body="Why?"))]),
               pr(threads=[thread(inline(5, author=ME, body="Why?"), inline(6, NOTE + "Because.", ME, "RC_2"),
                                  inline(6, "Still unsure.", ME, "RC_3"))])],
        checks=GREEN, args=["--until", "any-change"]),
        0, ["thread reply from kaminski-dev on src/app.py:12: Still unsure."], "Because"),
    "an unresolved thread blocks ready": (dict(
        polls=[pr(reviews=[review(7, "Two findings.")], threads=[thread(inline(7))])], checks=GREEN),
        1, ["coderabbitai[bot] reviewed 1111111: reviews 7", "blocked by 1 unresolved thread"], "#1 ready on"),
    "the base moved over touched files": (dict(
        polls=[pr(), pr(base=MOVED)], checks=GREEN, files=["src/app.py", "README.md"], moved=["src/app.py", "docs/a.md"],
        args=["--until", "any-change"]), 0, ["main moved to bbbbbbb and touches files in this PR: src/app.py"], "deadline"),
    "the base moved over untouched files": (dict(
        polls=[pr(), pr(base=MOVED)], checks=GREEN, files=["src/app.py"], moved=["docs/a.md"],
        args=["--until", "any-change", *QUIET]), 1, ["deadline passed"], "moved"),
    "a base move whose overlap cannot be read is said, then retried": (dict(
        polls=[pr(), pr(base=MOVED)], files=["src/app.py"], moved=["src/app.py"], fail={"compare": 1},
        checks=[{"name": "test", "bucket": "pending", "link": "", "description": ""}], args=["--until", "green", *QUIET]),
        1, ["main moved to bbbbbbb; could not read", "main moved to bbbbbbb and touches files in this PR: src/app.py"],
        "#1 green on"),
    "BEHIND": (dict(polls=[pr(), pr(merge="BEHIND")], checks=GREEN, args=["--until", "any-change"]),
               0, ["merge state is BEHIND"], "deadline"),
    "DIRTY": (dict(polls=[pr(merge="DIRTY")], checks=GREEN), 1, ["merge state is DIRTY"], "#1 ready on"),
    "an UNKNOWN merge state is not ready yet": (dict(
        polls=[pr(merge="UNKNOWN", reviews=[review(7, "x")])], checks=GREEN, args=QUIET),
        1, ["deadline passed"], "#1 ready on"),
    "merged": (dict(polls=[pr(state="MERGED")]), 0, ["merged: https://github.com/acme/ledger/pull/1"], "deadline"),
    "closed": (dict(polls=[pr(state="CLOSED")]), 1, ["closed without merging"], "deadline"),
    "a 5xx then success": (dict(polls=[pr()], required=["test"], checks=GREEN, fail={"graphql": 1},
                                args=["--until", "green", "--minutes", "0.5"], err="HTTP 502"),
                           0, ["green on 1111111"], "stopped"),
    "a 5xx reading the required checks is retried, not read as none required": (dict(
        polls=[pr()], required=["test"], fail={"rules": 1}, args=["--until", "green", *QUIET],
        checks=GREEN + [{"name": "lint", "bucket": "fail", "link": "https://ci/lint", "description": ""}]),
        0, ["green on 1111111", "required 1/1 green"], "check failed"),
    "a 403 reading the required checks is said, and every CI check gates": (dict(
        polls=[pr()], forbid=["rules"], checks=GREEN, args=["--until", "green"]),
        0, ["required checks could not be read (HTTP 403", "every CI check gates", "green on 1111111"], "stopped"),
    "a rate-limit 403 reading the required checks is retried": (dict(
        polls=[pr()], required=["test"], rate_limit={"rules": 1}, args=["--until", "green", *QUIET],
        checks=GREEN + [{"name": "lint", "bucket": "fail", "link": "https://ci/lint", "description": ""}]),
        0, ["green on 1111111", "required 1/1 green"], "could not be read"),
    "the deadline passing": (dict(polls=[pr()], checks=GREEN, args=QUIET),
                             1, ["deadline passed: no ready on 1111111 after"], "#1 ready on"),
    "the bot login read from workflow.md": (dict(
        polls=[pr(reviews=[review(8, "x"), review(9, "y", author={"login": "greptile-apps", "__typename": "Bot"})])],
        checks=GREEN, checkout="greptile"), 0, ["greptile-apps[bot] reviewed 1111111: reviews 9", "ready on"], "reviews 8"),
    "a base the review bot does not review": (dict(polls=[pr()], checks=GREEN, checkout="no-bot"),
                                              0, ["ready on 1111111"], "deadline"),
    "a bot review with a body": (dict(polls=[pr(reviews=[review(7, "x")])], checks=GREEN),
                                 0, ["coderabbitai[bot] reviewed 1111111: reviews 7", "ready on 1111111"], "deadline"),
    "a bodiless bot review with its own inline comment": (dict(
        polls=[pr(reviews=[review(7)], threads=[thread(inline(7), resolved=True)])], checks=GREEN),
        0, ["reviews 7", "ready on"], "deadline"),
    "a bot review holding only a thread reply is no review": (dict(
        polls=[pr(reviews=[review(5, "x", commit=OLD), review(8)],
                  threads=[thread(inline(5), inline(8, id="RC_2"), resolved=True)])], checks=GREEN, args=QUIET),
        1, ["deadline passed"], "reviews"),
    "a bot review of an older commit": (dict(polls=[pr(reviews=[review(9, "x", commit=OLD)])], checks=GREEN, args=QUIET),
                                        1, ["deadline passed"], "reviews"),
    "a clean round": (dict(polls=[pr(comments=[summary(reviewed(HEAD))])], checks=GREEN),
                      0, ["coderabbitai[bot] reviewed 1111111: clean", "ready on"], "deadline"),
    "a clean round in the status block": (dict(
        polls=[pr(comments=[summary(reviewed(HEAD, verdict=""), status())])], checks=GREEN), 0, ["clean", "ready on"], "deadline"),
    "a clean status block for an older commit": (dict(
        polls=[pr(comments=[summary(reviewed(OLD, verdict=""), status())])], checks=GREEN, args=QUIET),
        1, ["deadline passed"], "clean"),
    "a review in progress": (dict(
        polls=[pr(comments=[summary(reviewed(HEAD), "review in progress by coderabbit.ai\n")])], checks=GREEN, args=QUIET),
        1, ["deadline passed"], "clean"),
    "rate limited on the head": (dict(polls=[pr(comments=[summary(reviewed(OLD), rate_limited(HEAD))])], checks=GREEN),
                                 1, ["coderabbitai[bot] rate limited on 1111111"], "#1 ready on"),
    "paused after the head commit": (dict(polls=[pr(comments=[summary(notice=paused(OLD, HEAD))])], checks=GREEN),
                                     1, ["coderabbitai[bot] paused on 1111111"], "#1 ready on"),
    "a pause naming an older commit": (dict(polls=[pr(comments=[summary(notice=paused(OLD, OLD))])], checks=GREEN, args=QUIET),
                                       1, ["deadline passed"], "paused"),
    "a push to the head restarts the deadline": (dict(
        timeline=[[0, pr()], [2.0, pr(head=NEW)], [4.5, pr(head=NEW, reviews=[review(11, "x", commit=NEW)])]],
        checks=GREEN, args=["--minutes", str(3 / 60), "--interval", "0.2"]),
        0, ["reviews 11", "ready on 2222222"], "deadline"),
    "an inherited GH_REPO: every gh call asks for origin's repo": (dict(
        polls=[pr(reviews=[review(12, "x")])], checks=GREEN, env={"GH_REPO": "kaminski-dev/dk-agent-kit"}, repo="acme/ledger"),
        0, ["reviews 12"], "deadline"),
}


def case_env(root, name, fix):
    case = os.path.join(root, name.replace(" ", "-").replace(":", "").replace("'", ""))
    os.makedirs(case)
    with open(os.path.join(case, "fix.json"), "w") as f:
        json.dump(fix, f)
    return case, {"PATH": f"{root}/bin:{os.environ['PATH']}", "FIX": f"{case}/fix.json", "STATE": case, "HOME": case}


def start(root, case, env, fix, extra=()):
    args = [sys.executable, "-I", SCRIPT, "1", "--interval", "0", "--minutes", "0.5", *fix.get("args", []), *extra]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**env, **fix.get("env", {})}, cwd=os.path.join(root, fix.get("checkout", "checkout")))


def calls(case):
    path = os.path.join(case, "calls")
    return [json.loads(line) for line in open(path)] if os.path.exists(path) else []


def check(name, proc, out, err, code, want, unwanted, fix=None, case=None):
    fix = fix or {}
    problems = []
    if proc.returncode != code:
        problems.append(f"exit {proc.returncode} (want {code})")
    problems += [f"stdout lacks {w!r}" for w in want if w not in out]
    if unwanted and unwanted in out:
        problems.append(f"stdout holds {unwanted!r}")
    if fix.get("err", "") not in err:
        problems.append(f"stderr lacks {fix['err']!r}")
    if "repo" in fix:
        seen = calls(case)
        if {r for r, _ in seen} != {fix["repo"]} or any("-R" in a and a[a.index("-R") + 1] != fix["repo"] for _, a in seen):
            problems.append(f"gh asked about {sorted({r for r, _ in seen})} (want {fix['repo']!r})")
    if problems:
        return f"FAIL {name}: {'; '.join(problems)}\n     stdout {out.strip()!r}\n     stderr {err.strip()[-300:]!r}"
    return f"ok   {name}"


def run_case(root, name, fix, code, want, unwanted):
    case, env = case_env(root, name, fix)
    proc = start(root, case, env, fix)
    out, err = proc.communicate(timeout=60)
    return check(name, proc, out, err, code, want, unwanted, fix, case)


def second_watcher(root):
    """A second watcher on the same PR exits at once, while the first keeps watching."""
    name = "a second watcher exits"
    fix = dict(polls=[pr()], checks=GREEN, args=["--until", "any-change"])
    case, env = case_env(root, name, fix)
    first = start(root, case, env, fix)
    try:
        for _ in range(100):
            if os.path.exists(os.path.join(case, "graphql.count")):
                break
            time.sleep(0.05)
        second = start(root, case, env, fix)
        out, err = second.communicate(timeout=30)
        result = check(name, second, out, err, 2, ["already watches acme/ledger#1"], "deadline")
        if first.poll() is not None:
            result = f"FAIL {name}: the first watcher stopped too ({first.returncode})"
    finally:
        first.kill()
        first.communicate()
    return result


def restart_replays(root):
    """An event that arrived while no watcher ran is reported by the next one."""
    name = "a restart replays a missed event"
    fix = dict(polls=[pr()], checks=GREEN, args=["--until", "any-change", *QUIET])
    case, env = case_env(root, name, fix)
    out, err = start(root, case, env, fix).communicate(timeout=30)
    if "comment from" in out:
        return f"FAIL {name}: the first run reported {out!r}"
    with open(os.path.join(case, "fix.json"), "w") as f:
        json.dump(dict(fix, polls=[pr(comments=[comment(HUMAN)])]), f)
    if os.path.exists(os.path.join(case, "graphql.count")):
        os.remove(os.path.join(case, "graphql.count"))
    proc = start(root, case, env, fix)
    out, err = proc.communicate(timeout=30)
    return check(name, proc, out, err, 0, [f"comment from kaminski-dev: {HUMAN}"], "deadline")


def checkout(root, name, workflow=None):
    path = os.path.join(root, name)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "remote", "add", "origin", "git@github.com:acme/ledger.git"], check=True)
    if workflow:
        os.makedirs(os.path.join(path, "docs", "agents"))
        with open(os.path.join(path, "docs", "agents", "workflow.md"), "w") as f:
            f.write(f"# Workflow\n\n## PRs and merge\n\n{workflow}\n- PRs target `main`.\n")


def main():
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(f"{root}/bin")
        with open(f"{root}/bin/gh", "w") as f:
            f.write(STUB)
        os.chmod(f"{root}/bin/gh", 0o755)
        checkout(root, "checkout")
        checkout(root, "greptile", "- **Review bot**: `greptile-apps[bot]` on PRs into `main`.")
        checkout(root, "no-bot", "- **Review bot**: `coderabbitai[bot]` on PRs into `pre-main`.")
        with ThreadPoolExecutor(8) as pool:
            jobs = [pool.submit(run_case, root, name, *spec) for name, spec in CASES.items()]
            jobs += [pool.submit(second_watcher, root), pool.submit(restart_replays, root)]
            results = [job.result() for job in jobs]
    for line in results:
        print(line)
    failed = sum(line.startswith("FAIL") for line in results)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
