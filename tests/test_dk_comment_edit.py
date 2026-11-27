#!/usr/bin/env python3
"""Runs dk-comment-edit against the eval `gh` stand-in: the maintainer's own attributed comment is replaced, and
another author's, one without the attribution note, a new body without it and an unknown id are refused. Then
checks its command line against the product repos' ask rules (tests/fixtures/product_ask_rules.json), which ask
before any `gh api` PATCH, PUT or DELETE: an ask outranks an allow, so the command is only prompt-free while its
line matches none of them.

The workspace is the shape plugins/dk/evals/_fixture/build.sh builds: .bin/gh first on PATH, its state in
.tracker/state.json. Nothing reaches GitHub.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CMD = ROOT / "plugins" / "dk-guard" / "bin" / "dk-comment-edit"
GH = ROOT / "plugins" / "dk" / "evals" / "_fixture" / "bin" / "gh"
WATCHER = ROOT / "plugins" / "dk" / "skills" / "issue-flow" / "pr-wait"
ASK = json.loads((ROOT / "tests" / "fixtures" / "product_ask_rules.json").read_text())["ask"]
NOTE = "> [!NOTE]\n> **Claude Opus 5.5 responding on behalf of kaminski-dev**\n\n"

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(name)


root = pathlib.Path(tempfile.mkdtemp(prefix="dk-comment-edit-"))
(root / ".bin").mkdir()
(root / ".tracker").mkdir()
(root / "repo").mkdir()
for args in (["init", "-q", "-b", "main"], ["remote", "add", "origin", "https://github.com/acme/app.git"]):
    subprocess.run(["git", *args], cwd=root / "repo", check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"})
shutil.copy(GH, root / ".bin" / "gh")
env = {"PATH": os.pathsep.join([str(root / ".bin"), os.environ["PATH"]]), "HOME": str(root), "TERM": "dumb"}
STATE = root / ".tracker" / "state.json"
STATE.write_text(json.dumps({
    "repo": "acme/app", "viewer": "kaminski-dev", "labels": [],
    "issues": {"7": {"title": "Login fails", "body": "", "state": "open", "labels": [], "comments": [
        {"id": 101, "author": "kaminski-dev", "body": NOTE + "Fixed in #12, out on Friday."},
        {"id": 102, "author": "customer", "body": NOTE + "Quoting the bot's format."},
        {"id": 103, "author": "kaminski-dev", "body": "The maintainer's own words."},
    ]}},
    "prs": [{"number": 12, "title": "Fix login", "body": "", "base": "main", "head": "fix/7-login", "state": "OPEN",
             "comments": [{"id": 201, "author": "kaminski-dev", "body": NOTE + "Ready for review."}],
             "threads": [{"path": "app.py", "line": 3, "comments": [
                 {"id": 301, "author": "coderabbitai[bot]", "body": "Handle None."},
                 {"id": 302, "author": "kaminski-dev", "body": NOTE + "Fixed in abc123."}]}]}],
}))


def body(cid):
    state = json.loads(STATE.read_text())
    held = [c for i in state["issues"].values() for c in i["comments"]]
    held += [c for p in state["prs"] for c in p.get("comments", []) + [c for t in p["threads"] for c in t["comments"]]]
    return next(c["body"] for c in held if c["id"] == cid)


def edit(*args, extra=None):
    return subprocess.run([str(CMD), *map(str, args)], cwd=root / "repo", env={**env, **(extra or {})},
                          capture_output=True, text=True)


new = root / "reply.md"
new.write_text(NOTE + "Fixed in #12, out on Monday.")

r = edit(101, new)
check("own issue comment: replaced", r.returncode == 0 and body(101) == new.read_text(), (r.returncode, r.stderr))
check("own issue comment: prints its URL",
      r.stdout.strip() == "https://github.com/acme/app/issues/7#issuecomment-101", r.stdout)
r = edit(201, new)
check("own PR comment: replaced", r.returncode == 0 and body(201) == new.read_text(), (r.returncode, r.stderr))
r = edit(302, new)
check("own thread reply: replaced", r.returncode == 0 and body(302) == new.read_text()
      and r.stdout.strip() == "https://github.com/acme/app/pull/12#discussion_r302", (r.returncode, r.stdout, r.stderr))

# gh would resolve {owner}/{repo} to GH_REPO or a fork's upstream; the edit pins origin's repo, as pr-wait does.
(root / ".tracker" / "repos.log").write_text("")
r = edit(201, new, extra={"GH_REPO": "kaminski-dev/dk-agent-kit"})
asked = {line.split("\t", 1)[0] for line in (root / ".tracker" / "repos.log").read_text().splitlines()}
check("an inherited GH_REPO: the edit asks gh about origin's acme/app",
      r.returncode == 0 and asked == {"acme/app"}, (r.returncode, r.stderr, asked))

r = edit(102, new)
check("another author's comment: refused and left as it was",
      r.returncode == 1 and body(102) == NOTE + "Quoting the bot's format." and "customer" in r.stderr
      and "kaminski-dev" in r.stderr, (r.returncode, r.stderr))
r = edit(301, new)
check("a bot's thread comment: refused", r.returncode == 1 and body(301) == "Handle None.", (r.returncode, r.stderr))
r = edit(103, new)
check("the maintainer's comment without the note: refused and left as it was",
      r.returncode == 1 and body(103) == "The maintainer's own words." and "attribution note" in r.stderr,
      (r.returncode, r.stderr))

bare = root / "bare.md"
bare.write_text("Fixed in #12, out on Tuesday.")
before = body(101)
r = edit(101, bare)
check("a new body without the note: refused, the comment left as it was",
      r.returncode == 1 and body(101) == before and "attribution note" in r.stderr and str(bare) in r.stderr,
      (r.returncode, r.stderr))

r = edit(999, new)
check("an unknown id: fails and says no comment has it",
      r.returncode == 1 and "no issue or PR comment 999" in r.stderr, (r.returncode, r.stderr))
r = edit("abc", new)
check("an id that is not a number: usage", r.returncode == 2 and "dk-comment-edit <comment id> <file>" in r.stderr,
      (r.returncode, r.stderr))
r = edit(101, root / "missing.md")
check("a missing file: fails and names it", r.returncode == 1 and "missing.md" in r.stderr, (r.returncode, r.stderr))

calls = (root / ".tracker" / "calls.log").read_text()
check("a refusal sends no PATCH", calls.count("PATCH") == 4, calls)

watcher = re.search(r'^ATTRIBUTION = re\.compile\(r"([^"\n]+)"\)$', WATCHER.read_text(), re.M)
own = re.search(r'^ATTRIBUTION = re\.compile\(r"([^"\n]+)"\)$', CMD.read_text(), re.M)
check("its ATTRIBUTION pattern is pr-wait's, which tests/skills/test_issue-flow.py ties to the skill's note",
      bool(watcher and own and watcher.group(1) == own.group(1)), (own and own.group(1), watcher and watcher.group(1)))
shutil.rmtree(root, ignore_errors=True)


def asks(rule, line):
    """Whether a Bash(...) permission rule matches a command line: `*` matches any run of characters, the rest
    literally, over the whole line, as Claude Code matches it against each command of a compound line."""
    inner = re.fullmatch(r"Bash\((.*)\)", rule, re.S).group(1)
    return re.fullmatch(".*".join(map(re.escape, inner.split("*"))), line, re.S) is not None


commands = ["dk-comment-edit 4821937 /private/tmp/claude-501/-proj/0f1e/scratchpad/7/reply.md",
            'dk-comment-edit 4821937 "$SCRATCH/7/reply.md"', "dk-comment-edit 4821937 reply-v2.md"]
hits = [(c, rule) for c in commands for rule in ASK if asks(rule, c)]
check("its command line matches none of the product repos' ask rules", not hits, hits)
raw = "gh api -X PATCH repos/acme/app/issues/comments/4821937 -F body=@reply.md"
check("the raw PATCH it stands for does match one (the matcher is not vacuous)", any(asks(r, raw) for r in ASK), raw)

print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
