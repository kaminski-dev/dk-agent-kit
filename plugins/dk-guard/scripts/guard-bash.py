#!/usr/bin/env python3
"""dk-guard PreToolUse hook for the Bash tool.

Reads the hook JSON on stdin and answers with a permission decision:
deny for commands that destroyed shared state before (docker prune, unfiltered
mass removal, pushes to main, force pushes, git clean of ignored files) or
broke the shell (a zsh special parameter such as `path` as a loop or read
variable), ask
for rewriting the shared pre-main branch, reading a credential file or
answering dk-gc's question for the human (--yes, piped input), and
hints for gh calls that silently drop the issue body and for an unlabelled
Postgres server that dk-pg should start instead. Everything else passes.

This raises the floor against agent mistakes; it is not a security boundary.
Text inside heredocs is ignored, so a commit message may mention a command.
"""
import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}
SHARED = {"pre-main"}
FORCE_OK = re.compile(r"^verify-assets/")
CREDENTIALS = re.compile(r"\.sentryclirc|\.aws/credentials|(?<![\w.])\.netrc\b|\.ssh/id_[a-z0-9]+\b(?!\.pub)")

# Where a command can start: line start, after a control operator, inside $( or
# backticks, after a shell keyword, or at the opening quote of `bash -c '...'`.
START = r"(?:^|[;&|\n({`]|\$\(|\b(?:then|do|else)\s|-c\s+['\"])\s*"
PREFIX = r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:(?:sudo|command|exec|nohup|time|env|nice|xargs(?:\s+-\S+)*|g?timeout\s+\S+)\s+)*"
END = r"[^;&|\n)`]*"


def strip_heredocs(cmd):
    """Drop heredoc bodies; they are data, not commands."""
    lines, out, i = cmd.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for dash, _, delim in re.findall(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2", line):
            while i < len(lines):
                body = lines[i]
                i += 1
                if (body.lstrip("\t") if dash else body) == delim:
                    break
    return "\n".join(out)


def segments(cmd, program):
    """Yield (offset, tokens) for each invocation of `program` (a regex)."""
    for m in re.finditer(START + PREFIX + r"(" + program + r")\b(" + END + ")", cmd):
        text = m.group(1) + m.group(2)
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.replace("'", " ").replace('"', " ").split()
        yield m.start(1), drop_redirections(tokens)


def drop_redirections(tokens):
    """Remove `2>`, `>/dev/null`, `<file` and the target of a bare operator."""
    out, skip = [], False
    for t in tokens:
        if skip:
            skip = False
        elif re.match(r"^(?:\d*|&)(?:>>?|<)&?", t):
            skip = re.fullmatch(r"(?:\d*|&)(?:>>?|<)&?", t) is not None
        else:
            out.append(t)
    return out


def current_branch(path):
    if path is None:
        return None
    try:
        out = subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def effective_cwd(cmd, offset, cwd):
    """The directory a command at `offset` runs in, following earlier `cd`s.

    None when a `cd` target is only known at run time (`cd "$WT"`).
    """
    for m in re.finditer(r"(?:^|[;&|\n(]|\b(?:then|do|else)\s)\s*cd\s+(\S+)", cmd[:offset]):
        target = os.path.expanduser(m.group(1).strip("'\""))
        if "$" in target or "`" in target or cwd is None:
            cwd = None
        else:
            cwd = target if os.path.isabs(target) else os.path.join(cwd, target)
    return cwd


def short_ref(ref):
    return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref


def check_git(cmd, cwd):
    findings = []
    for offset, tokens in segments(cmd, "git"):
        args, path = tokens[1:], effective_cwd(cmd, offset, cwd)
        while args and args[0].startswith("-"):
            opt = args.pop(0)
            if opt == "-C" and args:
                p = os.path.expanduser(args.pop(0))
                if "$" in p or path is None:
                    path = None
                else:
                    path = p if os.path.isabs(p) else os.path.join(path, p)
            elif opt in ("-c", "--git-dir", "--work-tree", "--namespace") and args:
                args.pop(0)
        if not args:
            continue
        sub, rest = args[0], args[1:]
        if sub == "push":
            findings += check_push(rest, path)
        elif sub == "clean":
            flags = "".join(a.lstrip("-") for a in rest if re.match(r"^-[a-zA-Z]+$", a))
            if re.search("[xX]", flags) and "n" not in flags and "--dry-run" not in rest:
                findings.append(("deny", "git clean -x/-X deletes ignored files too, and ignored files have held "
                                 "unrecoverable work here (docs/*, prototypes). Run `git clean -n` first and "
                                 "remove the specific paths you created."))
    return findings


def check_push(rest, path):
    force = delete = False
    lease = False
    positional = []
    it = iter(rest)
    for a in it:
        if a in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
            next(it, None)
        elif a.startswith("--force-with-lease") or a == "--force-if-includes":
            lease = True
        elif a == "--force" or (re.match(r"^-[a-zA-Z]+$", a) and "f" in a):
            force = True
        elif a in ("--delete", "-d"):
            delete = True
        elif a == "--mirror":
            return [("deny", "git push --mirror rewrites every ref on the remote. Push one branch.")]
        elif not a.startswith("-"):
            positional.append(a)

    refspecs = positional[1:]
    branch = current_branch(path)
    if not refspecs:
        refspecs = [branch] if branch and branch != "HEAD" else []
    findings = []
    for spec in refspecs:
        plus = spec.startswith("+")
        spec = spec.lstrip("+")
        src, _, dst = spec.partition(":")
        if not _:
            dst = src
        if dst == "HEAD":
            dst = branch or "HEAD"
        is_delete = delete or (_ and src == "")
        dst = short_ref(dst)
        if dst in PROTECTED:
            findings.append(("deny", f"Pushing to {dst} deploys to production. Push a feature branch and open a "
                             "PR against pre-main."))
        elif dst in SHARED and (force or plus or lease or is_delete):
            findings.append(("ask", f"This rewrites or deletes the shared {dst} branch, which other open PRs "
                             "target. Only the maintainer does that."))
        elif (force or plus) and not FORCE_OK.match(dst):
            findings.append(("deny", f"Plain force push to {dst} is blocked. Use --force-with-lease, which "
                             "refuses to overwrite commits you have not seen."))
    return findings


def check_docker(cmd):
    findings = []
    for _, tokens in segments(cmd, "docker|podman"):
        if "prune" in tokens:
            findings.append(("deny", "docker/podman prune is machine-wide: it deletes other projects' containers, "
                             "volumes and images. Remove only what you started, by name or by label, e.g. "
                             "`docker rm -f <name>` or `docker rm -f $(docker ps -aq --filter label=dk.issue=<n>)`."))
    mass = re.finditer(r"\b(?:docker|podman)\s+(?:rm|rmi|stop|kill|(?:container|volume|network|image)\s+rm)\b[^;&|\n]*?"
                       r"\$\(\s*((?:docker|podman)\s+[^)]*)\)", cmd)
    piped = re.finditer(r"\b((?:docker|podman)\s+(?:ps|volume\s+ls|images|image\s+ls|network\s+ls)\b[^|;&\n]*)\|\s*"
                        r"xargs\s+(?:-\S+\s+)*(?:docker|podman)\s+(?:rm|rmi|stop|kill|volume\s+rm)", cmd)
    for m in list(mass) + list(piped):
        if not re.search(r"(?:--filter|-f)[=\s]+[\"']?(?:label|name|ancestor|id)=", m.group(1)):
            findings.append(("deny", "Mass docker removal without a label or name filter hits other projects' "
                             "resources. Filter by a label your session set, e.g. --filter label=dk.issue=<n>."))
    return findings


POSTGRES_IMAGE = re.compile(r"^(?:[\w.:-]+/)*(?:postgres|postgis/postgis|pgvector/pgvector|bitnami/postgresql)"
                            r"(?:[:@]\S*)?$")
RUN_FLAGS = {"--rm", "--detach", "--interactive", "--tty", "--init", "--privileged", "--publish-all",
             "--read-only", "--no-healthcheck", "--oom-kill-disable", "--quiet"}


def run_image(args):
    """Index of the image in a `docker run` argument list: the first argument that is no option or option value."""
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            i += 1 if "=" in a or a in RUN_FLAGS else 2
        elif a.startswith("-") and len(a) > 1:
            # -dit is all flags; -p 5432:5432 takes the next argument; -p5432:5432 carries its value
            i += 2 if len(a[1:].lstrip("ditPq")) == 1 else 1
        else:
            return i
    return None


def run_options(options):
    """Split `docker run` options into flags (`--rm=true` read as `--rm`, `--rm=false` dropped) and label keys."""
    flags, labels = [], set()
    it = iter(options)
    for a in it:
        if a in ("--label", "-l"):
            labels.add(next(it, "").partition("=")[0])
        elif a.startswith("--label="):
            labels.add(a[len("--label="):].partition("=")[0])
        elif re.fullmatch(r"--[\w-]+=(?:true|false)", a):
            name, _, value = a.partition("=")
            flags += [name] if value == "true" else []
        else:
            flags.append(a)
    return flags, labels


def check_postgres(cmd):
    cmd = cmd.replace("\\\n", " ")
    for _, tokens in segments(cmd, "docker|podman"):
        args = tokens[1:]
        if args[:2] == ["container", "run"]:
            args = args[1:]
        if args[:1] != ["run"]:
            continue
        i = run_image(args[1:])
        if i is None or not POSTGRES_IMAGE.match(args[1 + i]):
            continue
        flags, labels = run_options(args[1:1 + i])  # what follows the image is the container's command
        detached = any(a == "--detach" or re.fullmatch(r"-[ditPq]*d[ditPq]*", a) for a in flags)
        if "dk.issue" not in labels and (detached or "--rm" not in flags):
            return [("hint", "This Postgres server carries no issue label, so nothing ties it to an issue or "
                     "cleans it up. `dk-pg up <issue>` starts a throwaway one on a free port (--rm, tmpfs, labels "
                     "dk.repo and dk.issue) and prints its URL; `dk-pg url <issue>` reprints it, "
                     "`dk-pg down <issue>` removes it.")]
    return []


def check_gh(cmd):
    for _, tokens in segments(cmd, "gh"):
        if tokens[1:3] in (["issue", "view"], ["pr", "view"]) and "--comments" in tokens \
                and not any(t.startswith("--json") for t in tokens):
            return [("hint", "Piped `gh issue|pr view --comments` prints the comments but not the body. If you "
                     "need both, use `--json title,body,labels,comments`.")]
    return []


DK_GC = re.compile(r"(?:^|(\|\|?|[;&\n({`]|\$\(|\b(?:then|do|else)\s|-c\s+['\"]))\s*" + PREFIX
                   + r"(?:python3?\s+(?:-\S+\s+)*)?(?:[^\s;&|()<>'\"]*/)?dk-gc"
                   + r"(?=$|[\s;&|)`<>]|['\"](?:$|[\s;&|)]))(" + END + ")")
OUTPUT_REDIRECT = re.compile(r"\d*>>?&(?:\d+|-)?|&>>?")


def open_quote(cmd, pos):
    """Index of the quote that `pos` sits inside, or None outside quotes."""
    quote, start, i = None, None, 0
    while i < pos:
        c = cmd[i]
        if c == "\\" and quote != "'":
            i += 1
        elif quote is None and c in "'\"":
            quote, start = c, i
        elif c == quote:
            quote = None
        i += 1
    return start if quote else None


def check_dk_gc(cmd):
    # `2>&1` and `&>` would end the match at their `&` and hide a later --yes or `<`; `<&3` stays as input
    cmd = OUTPUT_REDIRECT.sub(lambda r: " " * len(r.group()), cmd)
    for m in DK_GC.finditer(cmd):
        sep, rest = m.group(1) or "", m.group(2)
        quoted = open_quote(cmd, m.end(1) if m.group(1) else m.start())
        if quoted is not None and not re.search(r"-c\s+$", cmd[:quoted]):
            continue  # a pattern or a string, not a shell command
        piped = sep == "|" or (sep == "&" and cmd[m.start() - 1:m.start()] == "|")
        args = rest.split()
        if "--dry-run" not in args and ("--yes" in args or "<" in rest or piped):
            return [("ask", "dk-gc removes worktrees, branches and databases after one yes, and that yes is "
                     "the human's. Run `dk-gc` or `dk-gc --dry-run` and leave the answer to them.")]
    return []


# zsh names that break the shell when assigned: `path` is tied to PATH (later commands are "not found"), the
# others are read-only or special arrays. The Bash tool runs zsh, so a loop or `read` on them breaks the call.
ZSH_SPECIAL = {"path", "PATH", "fpath", "module_path", "cdpath", "manpath", "status", "pipestatus", "argv",
               "commands", "functions", "aliases", "options", "parameters", "history"}
LOOP_START = r"(?:^|[;&|\n({`]|\$\(|\b(?:then|do|else|while|until|if)\s|zsh\s+-c\s+['\"])\s*"
LOOP = re.compile(LOOP_START + r"(?:for|foreach|select)\s+((?:[A-Za-z_]\w*\s+)*?[A-Za-z_]\w*)\b(?=\s+in\b|\s*[(;\n]|\s*$)")
READ = re.compile(LOOP_START + PREFIX + r"read\b(" + END + ")")


def check_zsh_names(cmd):
    targets = [(m, m.group(1).split()) for m in LOOP.finditer(cmd)]
    for m in READ.finditer(cmd):
        try:
            tokens = shlex.split(m.group(1))
        except ValueError:
            tokens = m.group(1).split()
        targets.append((m, [t.partition("?")[0] for t in drop_redirections(tokens) if not t.startswith("-")]))
    for m, names in targets:
        quoted = open_quote(cmd, m.start(1))
        if quoted is not None and not re.search(r"zsh\s+-c\s+$", cmd[:quoted]):
            continue  # a pattern, or code in another language or shell
        hit = next((n for n in names if n in ZSH_SPECIAL), None)
        if hit:
            return [("deny", f"`{hit}` is a special parameter in zsh, the shell this runs in (`path` is tied to "
                     "PATH, so every later command is \"command not found\"; `status`, `argv` and the like are "
                     "read-only or special). Name the loop or read variable something else, e.g. `p` or `file`.")]
    return []


def check_credentials(cmd):
    m = CREDENTIALS.search(cmd)
    if m:
        # ask, not deny, until a helper covers Sentry event details (retro #10)
        return [("ask", f"This reads {m.group(0)}, which holds a credential. Prefer the CLI that owns it "
                 "(sentry-cli, aws, gh); approve only if no CLI command covers it.")]
    return []


def decide(cmd, cwd):
    cmd = strip_heredocs(cmd)
    findings = check_docker(cmd) + check_git(cmd, cwd) + check_credentials(cmd) + check_gh(cmd) \
        + check_postgres(cmd) + check_dk_gc(cmd) + check_zsh_names(cmd)
    for level in ("deny", "ask"):
        reasons = [r for l, r in findings if l == level]
        if reasons:
            return level, " ".join(dict.fromkeys(reasons))
    hints = [r for l, r in findings if l == "hint"]
    return ("hint", " ".join(hints)) if hints else ("allow", "")


def log(event):
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not base:
        return
    try:
        with open(os.path.join(base, "guard-bash.jsonl"), "a") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass


def main():
    data = json.load(sys.stdin)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    cwd = data.get("cwd") or os.getcwd()
    level, reason = decide(cmd, cwd)
    if level == "allow":
        return
    out = {"hookEventName": "PreToolUse"}
    if level == "hint":
        out["additionalContext"] = reason
    else:
        out["permissionDecision"] = level
        out["permissionDecisionReason"] = "dk-guard: " + reason
        log({"session": data.get("session_id"), "cwd": cwd, "decision": level, "reason": reason, "command": cmd[:500]})
    print(json.dumps({"hookSpecificOutput": out}))


if __name__ == "__main__":
    main()
