#!/usr/bin/env python3
"""Checks the fixtures behind plugins/dk/evals without running a model.

Each case's scaffold builds its workspace into a temp HOME the way
`claude plugin eval --scaffold` does (workspace = $HOME/cwd), and the checks
drive the stand-in `gh` and the fixture repo from there. A fixture that is
not red before the fix would let an eval pass without the skill doing its job.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVALS = ROOT / "plugins" / "dk" / "evals"
REFERENCE = pathlib.Path(__file__).resolve().parent / "evals"

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(name)


def scaffold(case):
    """Run a case's scaffold_script in a fresh HOME/cwd and return the workspace."""
    home = pathlib.Path(tempfile.mkdtemp(prefix="dk-eval-")) / "home"
    ws = home / "cwd"
    ws.mkdir(parents=True)
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": tempfile.gettempdir(), "TERM": "dumb"}
    script = EVALS / case / "scaffold.sh"
    r = subprocess.run(["bash", str(script)], cwd=ws, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAIL scaffold {case}: {r.stderr}")
    return ws


def run(ws, cmd, cwd=None, stdin=None):
    """Run cmd in a login-less shell that reads the workspace's rc, like the eval's Bash tool."""
    env = {"PATH": os.environ["PATH"], "HOME": str(ws.parent), "TERM": "dumb"}
    full = f'. "$HOME/.bashrc"; {cmd}'
    return subprocess.run(["bash", "-c", full], cwd=cwd or ws, env=env, input=stdin, capture_output=True, text=True)


def git(ws, repo, *args):
    return run(ws, "git " + " ".join(args), cwd=ws / repo)


def pull_on(ws, num, ref):
    """Push ref as ticket num's branch and open a PR through the stand-in, which runs num's acceptance check.

    Returns the stand-in's record of the PR, or gh's stderr when it recorded none.
    """
    git(ws, "app", "push", "-q", "-f", "origin", f"{ref}:refs/heads/fix/{num}-check")
    r = run(ws, f"gh pr create --base pre-main --head fix/{num}-check --title t --body 'Closes #{num}'", cwd=ws / "app")
    pull = ws / ".tracker" / "pulls" / f"{num}.md"
    return pull.read_text() if pull.exists() else r.stderr


# --- #353 fixture: Customer History order -------------------------------------------------------

ws = scaffold("implement-353")
heads = git(ws, "app", "ls-remote", "--heads", "origin").stdout
check("353: origin has main and pre-main", "refs/heads/main" in heads and "refs/heads/pre-main" in heads, heads)
tests = run(ws, "python3 -m unittest discover -s tests -q", cwd=ws / "app")
check("353: fixture's own tests pass", tests.returncode == 0, tests.stderr[-500:])

pr = pull_on(ws, "353", "origin/pre-main")
check("353: acceptance fails on the pre-fix state", "acceptance: fail" in pr, pr)

git(ws, "app", "checkout", "-q", "-b", "reference", "origin/pre-main")
patch = run(ws, f"git apply '{REFERENCE / 'reference-353.patch'}'", cwd=ws / "app")
check("353: reference fix applies", patch.returncode == 0, patch.stderr)
git(ws, "app", "commit", "-qam", "reference")
pr = pull_on(ws, "353", "reference")
check("353: acceptance passes on the reference fix", "acceptance: pass" in pr and "unit tests: pass" in pr, pr)

# A head that cannot be extracted still gets a PR and an acceptance line, and leaves no checkout behind.
broken = ws.parent / "broken-tar"
broken.mkdir()
(broken / "tar").write_text("#!/bin/sh\nexit 2\n")
(broken / "tar").chmod(0o755)
(ws / ".tracker" / "pr.md").unlink()
r = run(ws, f"PATH='{broken}':$PATH gh pr create --base pre-main --head fix/353-check --title t --body b", cwd=ws / "app")
pr = (ws / ".tracker" / "pr.md").read_text() if (ws / ".tracker" / "pr.md").exists() else ""
check("353: a failed extraction reports acceptance: fail", r.returncode == 0 and "acceptance: fail" in pr, pr or r.stderr)
left = sorted(p.name for p in (ws / ".tracker").glob("pr-*"))
check("353: a failed extraction leaves no checkout in .tracker", left == [], left)

shutil.rmtree(ws.parent.parent, ignore_errors=True)

# --- Fan-out fixture: #353 and #376 in one run, their fixes editing the same query --------------

ws = scaffold("implement-wave")
ready = json.loads(run(ws, "gh issue list --label ready-for-agent --json number").stdout or "[]")
check("wave: both tickets are briefed and ready", sorted(i["number"] for i in ready) == [353, 376], ready)
for num in ("353", "376"):
    pr = pull_on(ws, num, "origin/pre-main")
    check(f"wave: #{num}'s acceptance fails on the pre-fix state", "acceptance: fail" in pr, pr)
    git(ws, "app", "checkout", "-q", "-b", f"reference-{num}", "origin/pre-main")
    patch = run(ws, f"git apply '{REFERENCE / f'reference-{num}.patch'}'", cwd=ws / "app")
    check(f"wave: #{num}'s reference fix applies", patch.returncode == 0, patch.stderr)
    git(ws, "app", "commit", "-qam", f"reference-{num}")
    pr = pull_on(ws, num, f"reference-{num}")
    check(f"wave: #{num}'s acceptance passes on its reference fix",
          "acceptance: pass" in pr and "unit tests: pass" in pr, pr)
merge = git(ws, "app", "merge-tree", "--write-tree", "--name-only", "reference-353", "reference-376")
check("wave: the two reference fixes conflict in a dry merge",
      merge.returncode == 1 and "ledger/audit_store.py" in merge.stdout, (merge.returncode, merge.stdout, merge.stderr))
# The conflict is a constraint of the tickets, not of the reference fixes alone: #353 changes the ORDER BY,
# #376's brief has it drop the row LIMIT on the line below, and git conflicts on edits to adjacent lines.
# So every pair of branches that meets both briefs conflicts, and the report grader can require it.
store = git(ws, "app", "show", "origin/pre-main:ledger/audit_store.py").stdout
check("wave: list_by_entity's ORDER BY and row LIMIT are adjacent lines",
      '" ORDER BY changed_at DESC"\n            " LIMIT ?",' in store, store[-500:])
brief376 = json.loads(run(ws, "gh issue view 376 --json comments").stdout)["comments"][-1]["body"]
check("wave: #376's brief cuts the page in list_by_entity's statement, dropping its row LIMIT",
      "in the `list_by_entity` statement itself: its row `LIMIT ?` goes" in brief376, brief376)

# Parallel agents share the stand-in: a PR whose acceptance check is slow leaves every other gh call free,
# and when it finishes after a newer PR for the same ticket, the newer PR's record stays.
tracker = ws / ".tracker"
(tracker / "acceptance-353.py").write_text(
    "import pathlib, time\n"
    "t = pathlib.Path(__file__).parent\n"
    "if (t / 'slow-once').exists():\n"
    "    (t / 'slow-once').unlink()\n"
    "    (t / 'slow-started').write_text('')\n"
    "    time.sleep(6)\n")
(tracker / "slow-once").write_text("")
slow = subprocess.Popen(["bash", "-c", '. "$HOME/.bashrc"; gh pr create --base pre-main --head fix/353-check --title old --body old'],
                        cwd=ws / "app", env={"PATH": os.environ["PATH"], "HOME": str(ws.parent), "TERM": "dumb"},
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
deadline = time.monotonic() + 30
while not (tracker / "slow-started").exists() and time.monotonic() < deadline:
    time.sleep(0.1)
started = time.monotonic()
r = run(ws, "gh issue view 376 --json title")
took = time.monotonic() - started
check("wave: a gh call answers while another PR's acceptance check runs",
      (tracker / "slow-started").exists() and r.returncode == 0 and took < 3 and slow.poll() is None,
      (round(took, 1), r.stderr, slow.poll()))
run(ws, "gh pr create --base pre-main --head fix/353-check --title new --body new", cwd=ws / "app")
check("wave: the newer PR finished while the older one's check still ran", slow.poll() is None, slow.poll())
slow.communicate(timeout=60)
for record in (tracker / "pulls" / "353.md", tracker / "pr.md"):
    text = record.read_text()
    check(f"wave: an older PR's late check leaves the newer record in {record.name}",
          text.startswith("# PR #") and " new\n" in text.splitlines(True)[0] and "## Body\n\nnew\n" in text, text[:200])
shutil.rmtree(ws.parent.parent, ignore_errors=True)


def input_matches(case):
    """{grader name: input_match} from a case.yaml; stdlib only, so input_match stays single-quoted there."""
    text = (EVALS / case / "case.yaml").read_text()
    out = {}
    for block in re.split(r"\n  - ", text)[1:]:
        name = re.search(r"name: (\S+)", block)
        pattern = re.search(r"input_match: '((?:[^']|'')*)'", block)
        if name and pattern:
            out[name.group(1)] = pattern.group(1).replace("''", "'")
    return out


def brief(prompt, **extra):
    """An Agent call's input as the grader sees it: the tool input serialised as JSON."""
    return json.dumps({"description": "Implement a ticket", "prompt": prompt, **extra}, separators=(",", ":"))


matches = input_matches("implement-wave")
user_only = sorted(p.parent.name for p in (EVALS.parent / "skills").glob("*/SKILL.md")
                   if "\ndisable-model-invocation: true\n" in p.read_text())
named = matches.get("briefs-name-no-user-only-skill", "(?!)")
missed = [s for s in user_only if not re.search(named, brief(f"Call the Skill tool with dk:{s} for #353."))]
check("wave: the brief grader catches every user-only skill", user_only and not missed, missed)
flagged = [s for s in ("issue-flow", "tdd", "verify", "code-review", "pr")
           if re.search(named, brief(f"Call the Skill tool with dk:{s}."))]
check("wave: the brief grader passes the skills a brief should name", not flagged, flagged)
isolated = matches.get("no-harness-isolation", "(?!)")
check("wave: the isolation grader catches a brief with worktree isolation",
      re.search(isolated, brief("Work in ../app-353.", isolation="worktree")) is not None, isolated)
check("wave: the isolation grader passes a brief without it", re.search(isolated, brief("Work in ../app-353.")) is None,
      isolated)

# The review fixture: a branch that fixes #353 correctly but breaks one documented standard.
ws = scaffold("code-review-353")
branch = git(ws, "app", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
check("353 review: the fix branch is checked out", branch == "fix/353-history-order", branch)
diff = git(ws, "app", "diff", "origin/pre-main...HEAD").stdout
check("353 review: the diff seeds a value interpolated into SQL", "entity_type = '{entity_type}'" in diff, diff[:300])
pr = pull_on(ws, "353", "HEAD")
check("353 review: the seeded branch still meets #353's acceptance", "acceptance: pass" in pr and "unit tests: pass" in pr, pr)
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The review fixture with work in progress: the same branch, plus an uncommitted edit and an untracked
# file, each breaking a documented standard that a review of the commits alone cannot see.
ws = scaffold("code-review-wip")
branch = git(ws, "app", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
check("wip review: the fix branch is checked out", branch == "fix/353-history-order", branch)
status = git(ws, "app", "status", "--porcelain").stdout
check("wip review: one uncommitted edit and one untracked file",
      status == " M ledger/__main__.py\n?? ledger/export.py\n", status)
committed = git(ws, "app", "diff", "--name-only", "origin/pre-main...HEAD").stdout.split()
check("wip review: the commits touch neither", committed == ["ledger/audit_store.py", "tests/test_audit_store.py"], committed)
wip = git(ws, "app", "diff", "HEAD").stdout
check("wip review: the uncommitted edit formats a value into SQL",
      "WHERE entity_type = '{a.entity_type}'\"" in wip, wip[:400])
export = (ws / "app" / "ledger" / "export.py").read_text()
check("wip review: the untracked file formats a value into SQL", "entity_type = '%s'\" % entity_type" in export, export)
tests = run(ws, "python3 -m unittest discover -s tests -q", cwd=ws / "app")
check("wip review: the tests still pass with the work in progress", tests.returncode == 0, tests.stderr[-500:])
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The correctness fixture: #388 sends queued mail and follows every documented standard, but the provider
# call sits between the claim's commit and the sent mark's, and the Outbox tab's test only renders.
SEND_ONCE = """
import os, sqlite3, sys
from datetime import datetime, timedelta, timezone
from ledger.outbox import Outbox
db, log, phase = sys.argv[1:4]
class Provider:
    def send(self, to, subject, body, idempotency_key=None):
        with open(log, "a") as f:
            f.write(f"{subject}|{idempotency_key}\\n")
        if phase == "crash":
            os._exit(9)
outbox = Outbox(sqlite3.connect(db), Provider())
t = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
if phase == "crash":
    outbox.queue("accountant@example.com", "Week 41", "-", "2026-10-12T08:00:00Z")
    outbox.send_next(t)
else:
    print(outbox.send_next(t + timedelta(minutes=6)))
"""
RENDER_NOTHING = ("import sys, unittest, ledger.web as w; w.render_to_string = lambda c: None; "
                  "s = unittest.defaultTestLoader.loadTestsFromName('tests.test_outbox.OutboxTabTest'); "
                  "sys.exit(not unittest.TextTestRunner().run(s).wasSuccessful())")


def sends_after_crash(ws, tag):
    """A sender dies right after its send, a second runs past the lease: the first one's exit code, the id the
    second sent, and each send the provider saw as subject|idempotency_key."""
    script, db, log = ws.parent / "send_once.py", ws.parent / f"{tag}.db", ws.parent / f"{tag}.log"
    script.write_text(SEND_ONCE)
    crash = run(ws, f"PYTHONPATH=. python3 '{script}' '{db}' '{log}' crash", cwd=ws / "app")
    retry = run(ws, f"PYTHONPATH=. python3 '{script}' '{db}' '{log}' retry", cwd=ws / "app")
    return crash.returncode, retry.stdout.strip(), log.read_text().splitlines() if log.exists() else []


ws = scaffold("code-review-correctness")
branch = git(ws, "app", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
check("388 review: the feature branch is checked out", branch == "fix/388-outbox-mail", branch)
tests = run(ws, "python3 -m unittest discover -s tests -q", cwd=ws / "app")
check("388 review: the fixture's own tests pass", tests.returncode == 0, tests.stderr[-500:])
status = git(ws, "app", "status", "--porcelain").stdout
check("388 review: nothing uncommitted", status == "", status)
code, retried, sent = sends_after_crash(ws, "seeded")
check("388 review: a crash after the send leaves the mail to go out again, with no idempotency key",
      code == 9 and retried == "1" and sent == ["Week 41|None", "Week 41|None"], (code, retried, sent))
empty = run(ws, f'python3 -c "{RENDER_NOTHING}"', cwd=ws / "app")
check("388 review: the Outbox tab's test passes when rendering returns nothing", empty.returncode == 0, empty.stderr[-500:])

git(ws, "app", "checkout", "-q", "-b", "reference")
patch = run(ws, f"git apply '{REFERENCE / 'reference-388.patch'}'", cwd=ws / "app")
check("388 review: reference fix applies", patch.returncode == 0, patch.stderr)
tests = run(ws, "python3 -m unittest discover -s tests -q", cwd=ws / "app")
check("388 review: the reference fix's tests pass", tests.returncode == 0, tests.stderr[-500:])
code, retried, sent = sends_after_crash(ws, "reference")
check("388 review: on the reference fix the repeat carries the first send's idempotency key",
      code == 9 and retried == "1" and sent == ["Week 41|outbox-1", "Week 41|outbox-1"], (code, retried, sent))
empty = run(ws, f'python3 -c "{RENDER_NOTHING}"', cwd=ws / "app")
check("388 review: on the reference fix the Outbox tab's test fails when rendering returns nothing",
      empty.returncode != 0 and "test_lists_each_message_and_whether_it_went_out" in empty.stderr
      and "TypeError" in empty.stderr, empty.stderr[-500:])
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The verify fixture: a clean #353 fix in a repo whose verify doc says there is no database to start.
ws = scaffold("verify-no-db")
branch = git(ws, "app", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
check("verify: the clean fix branch is checked out", branch == "fix/353-ordered", branch)
diff = git(ws, "app", "diff", "origin/pre-main...HEAD", "--", "ledger").stdout
check("verify: the fix changes the ORDER BY alone",
      [l for l in diff.splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")]
      == ['-            " ORDER BY changed_at DESC"', '+            " ORDER BY changed_at DESC, action, changed_by, field_name"'], diff)
doc = (ws / "app" / "docs" / "agents" / "verify.md").read_text()
check("verify: the verify doc says the stack needs no database", "- **Database**: none." in doc, doc)
log = ws / ".tracker" / "postgres.log"
check("verify: the Postgres log starts empty", log.exists() and log.read_text() == "", log.exists())
for cmd in ("dk-pg up 353", "docker run -d postgres:17", "pg_ctl -D db start", "initdb -D db", "postgres -D db"):
    r = run(ws, cmd, cwd=ws / "app")
    check(f"verify: `{cmd}` reaches the stand-in and fails", r.returncode != 0 and log.read_text().endswith(cmd + "\n"),
          (r.returncode, log.read_text()))


def history(ref):
    """Field order of the 2026-10-02 edit in `ledger history`, on a fresh seeded database at ref."""
    tree = ws.parent / f"tree-{ref.replace('/', '-')}"
    git(ws, "app", "worktree", "add", "-q", "--detach", str(tree), ref)
    db = ws.parent / f"{tree.name}.db"
    run(ws, f"python3 -m ledger seed --db '{db}'", cwd=tree)
    out = run(ws, f"python3 -m ledger history customer 7 --db '{db}'", cwd=tree).stdout
    git(ws, "app", "worktree", "remove", "--force", str(tree))
    return [l.split()[3] for l in out.splitlines() if "2026-10-02" in l]


before, after = history("origin/pre-main"), history("HEAD")
check("verify: the control run on pre-main shows the old order", before == ["phone", "email", "city"], before)
check("verify: the branch shows the fields by name", after == ["city", "email", "phone"], after)
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The triage fixture: #353 as filed, on the pre-fix code.
ws = scaffold("triage-353")
issue = json.loads(run(ws, "gh issue view 353 --json labels,comments").stdout)
check("353 triage: the tracker holds the untriaged issue", issue == {"labels": [{"name": "needs-triage"}], "comments": []}, issue)
store = (ws / "app" / "ledger" / "audit_store.py").read_text()
check("353 triage: list_by_entity still orders by changed_at alone", '" ORDER BY changed_at DESC"' in store, store[-600:])
r = run(ws, "gh issue edit 353 --add-label bug --add-label ready-for-agent --remove-label needs-triage")
md = (ws / ".tracker" / "issue-353.md").read_text() if (ws / ".tracker" / "issue-353.md").exists() else ""
check("353 triage: a label edit reaches the file the graders read", "labels: bug, ready-for-agent\n" in md, md or r.stderr)
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The thin-issue fixture: #361 says something is wrong and nothing that would let a brief be written.
ws = scaffold("triage-thin")
issue = json.loads(run(ws, "gh issue view 361 --json title,body,labels,comments").stdout)
check("361 triage: the tracker holds the untriaged issue",
      issue["labels"] == [{"name": "needs-triage"}] and issue["comments"] == [], issue)
check("361 triage: the issue names no entity, field, value or steps",
      len(issue["body"]) < 120 and not any(c.isdigit() for c in issue["body"]), issue["body"])
others = [i["number"] for i in json.loads(run(ws, "gh issue list --state all --json number").stdout)]
check("361 triage: no other issue to match it against", others == [361], others)
store = (ws / "app" / "ledger" / "audit_store.py").read_text()
check("361 triage: the Audit Log list it names already defines its order",
      '" ORDER BY changed_at DESC, entity_type, entity_id, action, changed_by, field_name"' in store, store[-900:])
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# The ready-list fixture: open ready-for-agent issues, #371 blocked by the open #372 through a native link,
# #375 only by a body line naming #372; #373 and #376 name blockers that are closed.
ws = scaffold("triage-ready")
READY_PY = ROOT / "plugins" / "dk" / "skills" / "triage" / "ready.py"


def numbers(cmd):
    r = run(ws, cmd)
    return sorted(i["number"] for i in json.loads(r.stdout)) if r.returncode == 0 else r.stderr


def ready_py():
    """ready.py's two sections as ({ready numbers}, {blocked number: [blocker numbers]}), or its stderr."""
    r = run(ws, f"python3 -I '{READY_PY}'", cwd=ws / "app")
    if r.returncode != 0:
        return r.stderr or r.stdout
    section, ready_list, blocked_by = None, [], {}
    for line in r.stdout.splitlines():
        if line.startswith("## "):
            section = line[3:]
        elif line.startswith("- #") and section == "Ready":
            ready_list.append(int(line[3:].split()[0]))
        elif line.startswith("- #") and section == "Blocked":
            blocked_by[int(line[3:].split()[0])] = [int(n) for n in re.findall(r"#(\d+)", line.split("blocked by")[-1])]
    return sorted(ready_list), blocked_by


ready = "gh issue list --state open --label ready-for-agent --json number"
by_label, unblocked, blocked = numbers(ready), numbers(ready + " --search '-is:blocked'"), numbers(ready + " --search is:blocked")
check("ready: the label alone lists the blocked #371 and #375 too", by_label == [370, 371, 372, 373, 375, 376], by_label)
check("ready: -is:blocked leaves out #371 alone", unblocked == [370, 372, 373, 375, 376], unblocked)
check("ready: is:blocked counts only an open native blocker", blocked == [371], blocked)
blockers = json.loads(run(ws, "gh api repos/acme/ledger/issues/371/dependencies/blocked_by").stdout)
check("ready: the API names #372 as #371's open blocker",
      [(b["number"], b["state"]) for b in blockers] == [(372, "open")], blockers)
summary = json.loads(run(ws, "gh api repos/acme/ledger/issues/373 --jq .issue_dependencies_summary").stdout)
check("ready: #373's only blocker is closed", summary == {"blocked_by": 0, "total_blocked_by": 1}, summary)

got = ready_py()
check("ready.py: leaves out the native-blocked #371 and the body-blocked #375",
      got == ([370, 372, 373, 376], {371: [372], 375: [372]}), got)

state_file = ws / ".tracker" / "state.json"
state = json.loads(state_file.read_text())
state_file.write_text(json.dumps({**state, "search_qualifiers": False}))
r = run(ws, ready + " --search '-is:blocked'")
check("ready: a GitHub without the qualifier rejects it", r.returncode != 0, r.stdout)
got = ready_py()
check("ready.py: without the qualifier, the same list through the API",
      got == ([370, 372, 373, 376], {371: [372], 375: [372]}), got)
state_file.write_text(json.dumps(state))

# The tracker doc's blocking write, as written there: #370 blocked by the open #372.
db_id = run(ws, "gh api repos/acme/ledger/issues/372 --jq .id").stdout.strip()
r = run(ws, f"gh api --method POST repos/acme/ledger/issues/370/dependencies/blocked_by -F issue_id={db_id}")
check("ready: the doc's blocking write reaches the stand-in", r.returncode == 0, r.stderr)
got = ready_py()
check("ready.py: then leaves out #370 too", got == ([372, 373, 376], {370: [372], 371: [372], 375: [372]}), got)

# Past gh's default page of 30: the docs' first cut, run as written, and ready.py.
state = json.loads(state_file.read_text())
for n in range(400, 440):
    state["issues"][str(n)] = {"title": f"Issue {n}", "body": "", "state": "open", "labels": ["ready-for-agent"],
                               "comments": []}
state_file.write_text(json.dumps(state))
sources = [ROOT / "docs/agents/issue-tracker.md", ROOT / "plugins/dk/skills/setup/issue-tracker.md",
           EVALS / "_fixture/app/docs/agents/issue-tracker.md"]
commands = [(src, c) for src in sources for c in re.findall(r"`(gh issue list [^`]*ready-for-agent[^`]*)`", src.read_text())]
check("ready: each tracker doc carries the first cut", len(commands) == 3, commands)
for src, cmd in commands:
    got = numbers(cmd)
    check(f"ready: {src.relative_to(ROOT)}'s first cut lists all 44", isinstance(got, list) and len(got) == 44,
          (cmd, got if isinstance(got, str) else len(got)))
got = ready_py()
check("ready.py: lists all 43 past 30", isinstance(got, tuple) and len(got[0]) == 43, got)

# Past the blocker read's page of 30, GitHub's default.
state = json.loads(state_file.read_text())
for n in range(440, 470):
    state["issues"][str(n)] = {"title": f"Issue {n}", "body": "", "state": "closed", "labels": [], "comments": []}
state["issues"]["379"] = {"title": "Issue 379", "body": "", "state": "open", "labels": ["ready-for-agent"],
                          "comments": [], "blocked_by": [*range(440, 470), 372]}
state_file.write_text(json.dumps(state))
page_one = json.loads(run(ws, "gh api repos/acme/ledger/issues/379/dependencies/blocked_by").stdout)
check("ready: the blocker read's first page holds 30 closed blockers",
      len(page_one) == 30 and {b["state"] for b in page_one} == {"closed"}, page_one[-1:])
reads = [(src, c) for src in sources
         for c in re.findall(r"`(gh api (?!--method)[^`]*/dependencies/blocked_by [^`]*)`", src.read_text())]
check("ready: each tracker doc carries the blocker read", len(reads) == 3, reads)
for src, cmd in reads:
    cmd = re.sub(r"repos/[^/]+/[^/]+/issues/<n>", "repos/acme/ledger/issues/379", cmd)
    r = run(ws, cmd)
    check(f"ready: {src.relative_to(ROOT)}'s blocker read finds #372 on page two", "#372 open" in r.stdout,
          (cmd, r.stdout[-200:], r.stderr))
for qualifiers in (True, False):
    state_file.write_text(json.dumps({**state, "search_qualifiers": qualifiers}))
    got = ready_py()
    check(f"ready.py, search_qualifiers {qualifiers}: an open blocker on page two keeps #379 blocked",
          isinstance(got, tuple) and 379 not in got[0] and got[1].get(379) == [372], got)
state_file.write_text(json.dumps(state))

# Blockers in another repo: acme/billing#5 is closed, acme/billing#6 open; this repo has no #5 or #6.
state = json.loads(state_file.read_text())
state["other_repos"] = {"acme/billing": {"5": "closed", "6": "open"}}
for n, ref in (("377", "acme/billing#5"), ("378", "acme/billing#6")):
    state["issues"][n] = {"title": f"Issue {n}", "body": f"Blocked by: {ref}\n", "state": "open",
                          "labels": ["ready-for-agent"], "comments": []}
state_file.write_text(json.dumps(state))
r = run(ws, f"python3 -I '{READY_PY}'", cwd=ws / "app")
ready_part, _, blocked_part = r.stdout.partition("## Blocked")
check("ready.py: a closed cross-repo blocker leaves the issue ready", r.returncode == 0 and "- #377 " in ready_part,
      (r.returncode, r.stdout[-400:], r.stderr))
check("ready.py: an open cross-repo blocker is named as such",
      "- #378 Issue 378: blocked by acme/billing#6" in blocked_part, (r.stdout[-400:], r.stderr))
shutil.rmtree(ws.parent.parent, ignore_errors=True)

# --- #1091 fixture: govulncheck red on go1.27.1 and x/net v0.59.0 --------------------------------

ws = scaffold("triage-1091")
vuln = run(ws, "govulncheck ./...", cwd=ws / "api")
ids = sorted(set(l.split()[2] for l in vuln.stdout.splitlines() if l.startswith("Vulnerability #")))
check("1091: govulncheck exits 3 on the pinned toolchain", vuln.returncode == 3, vuln.stdout[-300:])
check("1091: it reports the issue's 12 IDs", len(ids) == 12 and "GO-2026-6617" in ids, ids)
scans = (ws / ".tracker" / "govulncheck.log").read_text()
check("1091: the scan is logged for the graders", scans == "./... exit=3\n", scans)
mod = ws / "api" / "go.mod"
mod.write_text(mod.read_text().replace("go 1.27.1", "go 1.27.2").replace("x/net v0.59.0", "x/net v0.60.0"))
vuln = run(ws, "govulncheck ./...", cwd=ws / "api")
check("1091: govulncheck exits 0 after the bump", vuln.returncode == 0, vuln.stdout[-300:])
issue = json.loads(run(ws, "gh issue view 1091 --json title,labels").stdout)
check("1091: the tracker holds the untriaged issue", issue["labels"] == [{"name": "needs-triage"}], issue)
shutil.rmtree(ws.parent.parent, ignore_errors=True)

print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
