#!/usr/bin/env python3
"""Say whether a spec can finish, before any worktree exists. Changes nothing.

usage: preflight.py <spec number>

Run from inside the repo: gh is asked about origin's github.com repo, whatever
GH_REPO says. It reads the spec's sub-issues (its tickets) and each open
ticket's blockers, and prints:

  ## Can finish now          open ready-for-agent tickets with no open blocker: the frontier
  ## Waits inside the spec   tickets whose open blockers are all tickets of this spec that can finish
  ## Cannot finish           each other open ticket, with why: an open blocker outside the spec,
                             no ready-for-agent label, a wait on a ticket that cannot finish, or
                             a home in another repo (owner/repo#n), whose work no branch here holds
  ## Done                    closed tickets

A blocker is a native dependency or a `Blocked by: #n` line in the ticket body,
as in dk:triage's ready.py; `owner/repo#n` there names another repo's issue,
which is always outside the spec.
Exit 0: every open ticket can finish. Exit 3: one cannot, or the spec has no
open ticket; the last line, on stderr, says what blocks it. Exit 1: gh failed,
or origin is no github.com repo.
"""
import json
import os
import re
import subprocess
import sys

BODY_BLOCKER = re.compile(r"^\s*Blocked by:?(.*)$", re.I | re.M)
# #12 is this repo's issue, owner/repo#12 another repo's; the lookbehind keeps the second from reading as #12.
BLOCKER_REF = re.compile(r"(?<![\w/.-])((?:[\w.-]+/[\w.-]+)?)#(\d+)")


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh {' '.join(args)}: {r.stderr.strip() or r.returncode}")
    return r.stdout


def origin_repo():
    """None when origin is no github.com repo. Read from the configured URL, before any insteadOf rewrites it."""
    url = subprocess.run(["git", "config", "--get", "remote.origin.url"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"^(?:[\w.+-]+://(?:[^@/?#]+@)?|(?:[^@/:]+@)?)github\.com(?::\d+)?[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url, re.I)
    return m.group(1) if m else None


def pages(path):
    return [item for page in json.loads(gh("api", "--paginate", "--slurp", path)) for item in page]


def main():
    if len(sys.argv) != 2 or not sys.argv[1].lstrip("#").isdigit():
        print(__doc__.strip())
        return 0 if sys.argv[1:] in (["-h"], ["--help"]) else 1
    spec = sys.argv[1].lstrip("#")

    repo = origin_repo()
    if not repo:
        sys.exit("origin names no github.com repo, so there is no repo to ask gh about.")
    os.environ["GH_REPO"] = repo  # an inherited GH_REPO would point gh at another repo
    tickets, elsewhere = {}, {}
    for t in pages(f"repos/{repo}/issues/{spec}/sub_issues"):
        home = t.get("repository_url", "").removeprefix("https://api.github.com/repos/") or repo
        if home.lower() == repo.lower():
            tickets[t["number"]] = t
        else:
            elsewhere[f"{home}#{t['number']}"] = t
    states = {}

    def is_open(other, n):
        if (other, n) not in states:
            where = ["--repo", other] if other else []
            states[(other, n)] = gh("issue", "view", n, *where, "--json", "state", "--jq", ".state").strip().upper()
        return states[(other, n)] == "OPEN"

    open_tickets = {n: t for n, t in tickets.items() if t["state"].lower() == "open"}
    inside, outside = {}, {}
    for n, t in open_tickets.items():
        blockers = {f"#{b['number']}" for b in pages(f"repos/{repo}/issues/{n}/dependencies/blocked_by")
                    if b["state"].lower() == "open"}
        for line in BODY_BLOCKER.findall(t.get("body") or ""):
            blockers |= {f"{other}#{m}" for other, m in BLOCKER_REF.findall(line)
                         if (not other and int(m) in open_tickets) or is_open(other, m)}
        inside[n] = sorted(int(b[1:]) for b in blockers if b.startswith("#") and int(b[1:]) in open_tickets)
        reasons = [f"blocked by {b}, outside the spec" for b in sorted(blockers)
                   if not (b.startswith("#") and int(b[1:]) in open_tickets)]
        if "ready-for-agent" not in {label["name"] for label in t.get("labels", [])}:
            reasons.append("not ready-for-agent")
        outside[n] = reasons

    # A ticket can finish when nothing outside blocks it and every ticket it waits on can finish.
    finishable, grew = set(), True
    while grew:
        grew = False
        for n in open_tickets:
            if n not in finishable and not outside[n] and all(b in finishable for b in inside[n]):
                finishable.add(n)
                grew = True

    def why(n):
        stuck = [f"waits on #{b}, which cannot finish" for b in inside[n] if b not in finishable]
        return "; ".join(outside[n] + stuck) or "waits in a cycle of tickets"

    order = sorted(open_tickets)
    away = sorted(elsewhere, key=lambda ref: (ref.split("#")[0].lower(), int(ref.split("#")[1])))
    away_open = [ref for ref in away if elsewhere[ref]["state"].lower() == "open"]
    title = {**{f"#{n}": t["title"] for n, t in tickets.items()}, **{r: t["title"] for r, t in elsewhere.items()}}
    sections = (
        ("Can finish now", [(f"#{n}", "") for n in order if n in finishable and not inside[n]]),
        ("Waits inside the spec", [(f"#{n}", "waits on " + ", ".join(f"#{b}" for b in inside[n]))
                                   for n in order if n in finishable and inside[n]]),
        ("Cannot finish", [(f"#{n}", why(n)) for n in order if n not in finishable]
         + [(ref, f"in {ref.split('#')[0]}, not this repo") for ref in away_open]),
        ("Done", [(f"#{n}", "") for n in sorted(tickets) if n not in open_tickets]
         + [(ref, "") for ref in away if ref not in away_open]),
    )
    for i, (heading, rows) in enumerate(sections):
        print(("\n" if i else "") + f"## {heading}")
        for ref, note in rows:
            print(f"- {ref} {title[ref]}" + (f": {note}" if note else ""))

    stuck = sections[2][1]
    if not open_tickets and not away_open:
        print(f"Spec #{spec} cannot finish: it has no open ticket.", file=sys.stderr)
        return 3
    if stuck:
        print(f"Spec #{spec} cannot finish: " + "; ".join(f"{ref} {note}" for ref, note in stuck) + ".", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
