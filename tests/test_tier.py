#!/usr/bin/env python3
"""Runs dk:code-review's tier script against fixture repos: each threshold, a risk path overriding size, a repo
with no risk-path list, deletions and untracked files counted, and the default list dk:setup's template carries."""
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TIER = ROOT / "plugins" / "dk" / "skills" / "code-review" / "tier"
TEMPLATE = ROOT / "plugins" / "dk" / "skills" / "setup" / "workflow-parameters.md"

LIST = "# Workflow\n\n## Risk paths\n\n- Migrations: `*migrations/*`\n- Mail: `*mail*`, `*sms*`\n\n## Evidence\n\n- `*.go`\n"
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(name)


def sh(cwd, *args):
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"FAIL setup: {' '.join(args)}: {out.stderr}")
    return out.stdout


def repo(workflow=LIST, files=None):
    """A repo whose `base` branch holds the workflow doc and `files` ({path: line count}), with HEAD on a branch
    from it."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="dk-tier-"))
    sh(d, "git", "init", "-q", "-b", "base")
    sh(d, "git", "config", "user.email", "t@example.com")
    sh(d, "git", "config", "user.name", "t")
    if workflow is not None:
        (d / "docs/agents").mkdir(parents=True)
        (d / "docs/agents/workflow.md").write_text(workflow)
    for path, n in (files or {"src/app.py": 1}).items():
        write(d, path, n)
    sh(d, "git", "add", "-A")
    sh(d, "git", "commit", "-qm", "base")
    sh(d, "git", "checkout", "-q", "-b", "work")
    return d


def write(d, path, n, start=0):
    p = d / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"line {i}\n" for i in range(start, start + n)))


def commit(d):
    sh(d, "git", "add", "-A")
    sh(d, "git", "commit", "-qm", "change")


def tier(d, *args, cwd=None):
    out = subprocess.run([sys.executable, "-I", str(TIER), *args], cwd=cwd or d, capture_output=True, text=True)
    return out.returncode, out.stdout.strip(), out.stderr.strip()


def first_word(d, *args):
    code, out, err = tier(d, *args)
    return (out.split(":")[0] if code == 0 else f"exit {code}: {err}"), out


def expect(name, d, want, *args):
    got, out = first_word(d, *(args or ("base",)))
    check(name, got == want, f"want {want}, got {out!r}")


# Size thresholds, in a repo with a risk-path list and no risk path touched.
d = repo()
write(d, "src/new.py", 60)
commit(d)
expect("60 changed lines in 1 file: small", d, "small")

d = repo()
write(d, "src/a.py", 20)
write(d, "src/b.py", 20)
write(d, "src/c.py", 20)
commit(d)
expect("60 changed lines in 3 files: small", d, "small")

d = repo()
write(d, "src/new.py", 61)
commit(d)
expect("61 changed lines: standard", d, "standard")

d = repo()
for name in "abcd":
    write(d, f"src/{name}.py", 1)
commit(d)
expect("4 files: standard", d, "standard")

d = repo()
write(d, "src/new.py", 500)
commit(d)
expect("500 changed lines: standard", d, "standard")

d = repo()
write(d, "src/new.py", 501)
commit(d)
expect("501 changed lines: risky", d, "risky")

# Deletions count as changed lines: 61 lines removed from a file is not a small change.
d = repo(files={"src/old.py": 61})
(d / "src/old.py").unlink()
commit(d)
expect("61 deleted lines: standard", d, "standard")
d = repo(files={"src/app.py": 40})
write(d, "src/app.py", 40, start=100)
commit(d)
expect("40 lines rewritten (40 added, 40 deleted): standard", d, "standard")

# A risk path overrides size, and its match is named.
d = repo()
write(d, "db/migrations/0002_add_index.sql", 1)
commit(d)
got, out = first_word(d, "base")
check("a 1-line migration: risky", got == "risky", out)
check("the risky line names the path and the glob", "db/migrations/0002_add_index.sql" in out
      and "*migrations/*" in out, out)
d = repo(files={"app/Mailer.py": 3})
(d / "app/Mailer.py").unlink()
commit(d)
expect("deleting a file on a risk path, matched without regard to case: risky", d, "risky")
d = repo()
write(d, "main.go", 1)
commit(d)
expect("a glob outside the ## Risk paths section is not a risk path", d, "small")

# Without a list, never small.
d = repo(workflow=None)
write(d, "src/new.py", 1)
commit(d)
got, out = first_word(d, "base")
check("no workflow.md: standard", got == "standard", out)
check("the standard line names the missing list", "risk-path list" in out, out)
d = repo(workflow="# Workflow\n\n## Evidence\n\n- none\n")
write(d, "src/new.py", 1)
commit(d)
expect("a workflow.md without ## Risk paths: standard", d, "standard")
d = repo(workflow="# Workflow\n\n## Risk paths\n\nNone yet.\n")
write(d, "src/new.py", 1)
commit(d)
expect("a ## Risk paths section with no glob: standard", d, "standard")
d = repo(workflow=None)
write(d, "src/new.py", 501)
commit(d)
expect("no list and over 500 lines: risky", d, "risky")

# Uncommitted and untracked work counts, as dk:code-review reviews it.
d = repo()
write(d, "src/app.py", 30, start=10)
write(d, "src/untracked.py", 30)
expect("31 unstaged and 30 untracked lines: standard", d, "standard")
d = repo()
write(d, "notes/mail-draft.txt", 1)
expect("an untracked file on a risk path: risky", d, "risky")
d = repo()
write(d, "other/mailout.txt", 70)
code, out, err = tier(d, "base", cwd=d / "src")
check("run from a subdirectory, an untracked file outside it on a risk path: risky", out.startswith("risky")
      and "other/mailout.txt" in out, out + err)

# The base: the argument, or origin/pre-main when origin has it, else origin/main.
d = repo()
write(d, "src/new.py", 61)
commit(d)
bare = pathlib.Path(tempfile.mkdtemp(prefix="dk-tier-origin-")) / "origin.git"
sh(d, "git", "init", "-q", "--bare", str(bare))
sh(d, "git", "remote", "add", "origin", str(bare))
sh(d, "git", "push", "-q", "origin", "base:refs/heads/main", "base:refs/heads/pre-main")
sh(d, "git", "fetch", "-q", "origin")
got, out = first_word(d)
check("no argument: standard against origin/pre-main", got == "standard", out)
sh(d, "git", "push", "-q", "origin", "work:refs/heads/pre-main")
sh(d, "git", "fetch", "-q", "origin")
code, out, err = tier(d)
check("no argument, branch level with origin/pre-main: nothing changed, so small", out.startswith("small"), out + err)
sh(d, "git", "push", "-q", "origin", "--delete", "pre-main")
sh(d, "git", "fetch", "-q", "--prune", "origin")
got, out = first_word(d)
check("no argument, origin has no pre-main: measured from origin/main", got == "standard", out)
code, out, err = tier(d, "no-such-ref")
check("a base that does not resolve: exit 2 with the ref named", code == 2 and "no-such-ref" in err, (code, out, err))

# dk:setup's template list is one the script reads, and it covers the default risk areas.
section = re.search(r"^## Risk paths\n.*?(?=^## |\Z)", TEMPLATE.read_text(), re.M | re.S)
check("setup's workflow-parameters.md carries a ## Risk paths template", section is not None)
if section:
    for path in ("db/migrations/0003_users.sql", "prisma/schema.prisma", "internal/auth/session.go",
                 "src/billing/invoice.ts", "src/payments/stripe.ts", "api/routes/users.ts", "openapi.yaml",
                 "src/mail/send.ts", "src/sms/twilio.ts", "src/push/fcm.ts", ".github/workflows/ci.yml",
                 "Dockerfile", "api/Dockerfile.prod", "package-lock.json", "pnpm-lock.yaml", "go.sum",
                 "uv.lock"):
        d = repo(workflow="# Workflow\n\n" + section.group(0))
        write(d, path, 1)
        commit(d)
        expect(f"setup's default list: {path} is risky", d, "risky")
    d = repo(workflow="# Workflow\n\n" + section.group(0))
    write(d, "src/components/Button.tsx", 5)
    commit(d)
    expect("setup's default list: a small UI change is small", d, "small")

print(f"{len(failures)} failures")
sys.exit(1 if failures else 0)
