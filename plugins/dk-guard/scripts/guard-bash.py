#!/usr/bin/env python3
"""dk-guard PreToolUse hook for the Bash tool.

Reads the hook JSON on stdin and answers with a permission decision:
deny for commands that destroyed shared state before (docker prune, unfiltered
mass removal, pushes to main, force pushes, git clean of ignored files),
leaked a credential (reading a credential file) or broke the shell (a zsh
special parameter such as `path` as a loop or read variable), ask for
rewriting the shared pre-main branch or answering dk-gc's question for the
human (--yes, piped input), and
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
OPENERS = r"[;&|\n({`]|\$\(|\b(?:then|do|else|while|until|if)\s|-c\s+['\"]"
START = r"(?:^|" + OPENERS + r")\s*"
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


# The splitter reads the command the way the shell does, into segments (simple commands) of words, so each rule
# sees a command's own words wherever they are spelled: after `2>&1`, inside `$(...)`, in `bash -lc '...'`.
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
REDIRECT = re.compile(r"&>>?|\d*(?:<<<|<<-|<<|<>|<&|>>[&|!]?|>[&|!]?|<)")
OPERATOR = re.compile(r"&&|\|\||\|&|\||;;|;&|;\||;|&\||&!|&")
LEAD = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "fi", "done", "esac"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?\+?=")
# Commands that run the command after their own options; letters are the options that take a value.
WRAPPERS = {"sudo": "ugpChDrtUT", "env": "uCS", "nice": "n", "xargs": "nILPsEdaJR", "timeout": "sk",
            "gtimeout": "sk", "command": "", "exec": "a", "nohup": "", "time": "", "builtin": "", "noglob": ""}


class Unsplittable(Exception):
    """The splitter cannot read the command; the raw-string checks decide instead."""


class Segment:
    """One simple command: its words with quotes removed (a substitution reads `$()`), its redirections as
    (operator, target), and the segments of its substitutions in `subs`."""

    def __init__(self, shell, substituted):
        self.shell, self.substituted = shell, substituted
        self.words, self.redirects, self.subs, self.scripts = [], [], [], set()
        self.piped_in = self.piped_out = self.started = False
        self.pipe_to = None


class Splitter:
    """Splits `text` into every segment it runs, in order: substitutions, here-doc bodies that expand, and the
    scripts of `bash -c '...'`, `zsh -fc '...'` and the like included."""

    def __init__(self, text, shell="zsh", substituted=False, depth=0):
        if depth > 16:
            raise Unsplittable("nested too deep")
        self.s, self.i, self.shell, self.substituted, self.depth = text, 0, shell, substituted, depth
        self.out, self.heredocs = [], []

    def run(self):
        self.parse(None, self.substituted)
        self.read_heredocs()
        return self.out

    def peek(self, k=0):
        return self.s[self.i + k] if self.i + k < len(self.s) else ""

    def at_expansion(self):
        return self.s.startswith(("$(", "${", "`"), self.i)

    def parse(self, end, substituted):
        seg = Segment(self.shell, substituted)
        while True:
            c = self.peek()
            if not c:
                if end:
                    raise Unsplittable("missing " + end)
                break
            if c in " \t":
                self.i += 1
            elif c == "\\" and self.peek(1) == "\n":
                self.i += 2
            elif c == "#":
                while self.peek() not in ("", "\n"):
                    self.i += 1
            elif c == "\n":
                self.i += 1
                seg = self.close(seg)
                self.read_heredocs()
            elif c == ")":
                self.i += 1
                if end == ")":
                    break
                seg = self.close(seg)  # a case pattern's `)`
            elif c in "<>" and self.peek(1) == "(":
                self.i += 2
                seg.subs.append(self.nested())
                self.add_word(seg, "$()")
            elif REDIRECT.match(self.s, self.i):
                op = REDIRECT.match(self.s, self.i).group()
                self.i += len(op)
                self.redirect(seg, op.lstrip("0123456789"))
            elif OPERATOR.match(self.s, self.i):
                op = OPERATOR.match(self.s, self.i).group()
                self.i += len(op)
                seg = self.close(seg, piped=op in ("|", "|&"))
            elif c == "(" and not seg.started and self.peek(1) != "(":
                self.i += 1
                seg = self.close(seg)
                self.parse(")", substituted)  # a subshell
            else:
                word, _, subs = self.word()
                seg.subs += subs
                if self.add_word(seg, word):
                    seg = self.close(seg)
        self.close(seg)

    def add_word(self, seg, word):
        """Add a word; True when it opens a function body (`f() { ... }`), which starts a new segment."""
        first = not seg.started and word not in LEAD
        seg.started = seg.started or first
        seg.words.append(word)
        return first and word.endswith("()") and len(word) > 2

    def close(self, seg, piped=False):
        if not (seg.words or seg.redirects):
            return seg
        self.out.append(seg)
        self.add_scripts(seg)
        nxt = Segment(self.shell, seg.substituted)
        if piped:
            seg.piped_out = nxt.piped_in = True
            seg.pipe_to = nxt
        return nxt

    def add_scripts(self, seg):
        """Split the script of each `<shell> [options] -c <script>` in the segment, in that shell."""
        words = seg.words
        for k, w in enumerate(words):
            shell = os.path.basename(w)
            if shell not in SHELLS:
                continue
            j, has_c = k + 1, False
            while j < len(words) and words[j][:1] in ("-", "+") and len(words[j]) > 1:
                has_c = has_c or (not words[j].startswith("--") and "c" in words[j][1:])
                j += 2 if words[j] in ("-o", "+o") else 1
            if has_c and j < len(words):
                seg.scripts.add(j)
                inner = Splitter(words[j], shell, seg.substituted, self.depth + 1).run()
                if inner:
                    inner[0].piped_in = seg.piped_in
                self.out += inner

    def redirect(self, seg, op):
        while self.peek() in (" ", "\t"):
            self.i += 1
        if self.peek() in ("<", ">") and self.peek(1) == "(":
            self.i += 2
            seg.subs.append(self.nested())
            target, quoted = "$()", False
        elif not self.peek() or self.peek() in "\n;&|<>)":
            raise Unsplittable("redirection without a target")
        else:
            target, quoted, subs = self.word()
            seg.subs += subs
        seg.redirects.append((op, target))
        if op in ("<<", "<<-"):
            self.heredocs.append((seg, target, op == "<<-", not quoted))

    def read_heredocs(self):
        """Consume the bodies of the here-docs opened on the line just ended; split the substitutions of those
        whose delimiter is unquoted, since the shell runs them."""
        pending, self.heredocs = self.heredocs, []
        for seg, delim, strip_tabs, expands in pending:
            lines = []
            while self.i < len(self.s):
                j = self.s.find("\n", self.i)
                line = self.s[self.i:] if j < 0 else self.s[self.i:j]
                self.i = len(self.s) if j < 0 else j + 1
                if (line.lstrip("\t") if strip_tabs else line) == delim:
                    break
                lines.append(line)
            if expands:
                body, subs = Splitter("\n".join(lines), self.shell, True, self.depth + 1), []
                body.double([], subs, None)
                self.out += body.out
                seg.subs += subs

    def word(self):
        """Read one word at the cursor: (text without quotes, whether any part was quoted, substitutions)."""
        buf, subs, quoted = [], [], False
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\n;&|<>)":
                break
            if c == "\\":
                if self.peek(1) != "\n":
                    buf.append(self.peek(1))
                    quoted = True
                self.i += 2
            elif c == "'":
                j = self.s.find("'", self.i + 1)
                if j < 0:
                    raise Unsplittable("unterminated '")
                buf.append(self.s[self.i + 1:j])
                self.i, quoted = j + 1, True
            elif self.s.startswith("$'", self.i):
                buf.append(self.ansi_c())
                quoted = True
            elif c == '"':
                self.i += 1
                self.double(buf, subs, '"')
                quoted = True
            elif self.at_expansion():
                self.expansion(buf, subs)
            elif c == "(":
                buf.append(self.balanced("(", ")", subs))  # zsh glob qualifier, array, `f()`, `foreach x (a b)`
            else:
                buf.append(c)
                self.i += 1
        return "".join(buf), quoted, subs

    def double(self, buf, subs, term):
        """Read a double-quoted string up to `term` (None: to the end, for a here-doc body)."""
        while True:
            c = self.peek()
            if not c:
                if term:
                    raise Unsplittable('unterminated "')
                return
            if c == term:
                self.i += 1
                return
            if c == "\\" and self.peek(1) and self.peek(1) in '$`"\\\n':
                if self.peek(1) != "\n":
                    buf.append(self.peek(1))
                self.i += 2
            elif self.at_expansion():
                self.expansion(buf, subs)
            else:
                buf.append(c)
                self.i += 1

    def ansi_c(self):
        self.i += 2
        buf = []
        while True:
            c = self.peek()
            if not c:
                raise Unsplittable("unterminated $'")
            self.i += 1
            if c == "'":
                return "".join(buf)
            if c == "\\":
                nxt = self.peek()
                self.i += 1
                buf.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
            else:
                buf.append(c)

    def expansion(self, buf, subs):
        """Read `$(...)`, a backtick substitution, `${...}` or `$((...))` at the cursor."""
        if self.s.startswith("$((", self.i):
            self.i += 1
            buf.append("$" + self.balanced("(", ")", subs))
        elif self.s.startswith("$(", self.i):
            self.i += 2
            subs.append(self.nested())
            buf.append("$()")
        elif self.s.startswith("${", self.i):
            self.i += 1
            buf.append("$" + self.balanced("{", "}", subs))
        else:
            subs.append(self.backtick())
            buf.append("$()")

    def nested(self):
        """Split a `$(...)` or `<(...)` body; the cursor is past its opening parenthesis."""
        start = len(self.out)
        self.parse(")", True)
        return self.out[start:]

    def backtick(self):
        self.i += 1
        buf = []
        while True:
            c = self.peek()
            if not c:
                raise Unsplittable("unterminated `")
            if c == "`":
                self.i += 1
                break
            if c == "\\" and self.peek(1) and self.peek(1) in "`\\$":
                buf.append(self.peek(1))
                self.i += 2
            else:
                buf.append(c)
                self.i += 1
        inner = Splitter("".join(buf), self.shell, True, self.depth + 1).run()
        self.out += inner
        return inner

    def balanced(self, open_, close, subs):
        """Raw text from the `open_` at the cursor to its matching `close`, splitting substitutions inside."""
        start, depth = self.i, 0
        while True:
            c = self.peek()
            if not c:
                raise Unsplittable("missing " + close)
            if c == "\\":
                self.i += 2
                continue
            if c == "'":
                j = self.s.find("'", self.i + 1)
                if j < 0:
                    raise Unsplittable("unterminated '")
                self.i = j + 1
                continue
            if c == '"':
                self.i += 1
                self.double([], subs, '"')
                continue
            if self.i > start and self.at_expansion():
                self.expansion([], subs)
                continue
            depth += {open_: 1, close: -1}.get(c, 0)
            self.i += 1
            if depth == 0:
                return self.s[start:self.i]


def split(cmd):
    """Every segment of the command in order, or None when it cannot be split."""
    try:
        return Splitter(cmd).run()
    except (Unsplittable, RecursionError):
        return None


def command(seg):
    """(wrappers, words from the program on): leading keywords, assignments and wrappers such as `sudo -u x`
    dropped."""
    words, i, wrappers = seg.words, 0, []
    while i < len(words):
        w = words[i]
        name = os.path.basename(w)
        if w in LEAD or ASSIGNMENT.match(w):
            i += 1
        elif name in WRAPPERS:
            wrappers.append(name)
            i += 1
            while i < len(words) and words[i].startswith("-") and len(words[i]) > 1:
                opt = words[i]
                i += 1
                if opt == "--":
                    break
                if len(opt) == 2 and opt[1] in WRAPPERS[name]:
                    i += 1
            if name in ("timeout", "gtimeout"):
                i += 1  # the duration
        else:
            break
    return wrappers, words[i:]


def commands(segs, cwd):
    """(segment, words from the program on, the directory it runs in) for each segment, following `cd`s."""
    for seg in segs:
        _, words = command(seg)
        if words[:1] == ["cd"] and len(words) > 1:
            target = os.path.expanduser(words[1])
            if "$" in target or "`" in target or cwd is None:
                cwd = None
            else:
                cwd = target if os.path.isabs(target) else os.path.join(cwd, target)
        yield seg, words, cwd


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
        findings += git_findings(tokens, effective_cwd(cmd, offset, cwd))
    return findings


def git_findings(tokens, path):
    """Findings for one `git` invocation (`tokens[0]` is git), run in `path` (None when unknown)."""
    args = tokens[1:]
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
    findings = []
    if not args:
        return findings
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


PRUNE = ("deny", "docker/podman prune is machine-wide: it deletes other projects' containers, volumes and images. "
         "Remove only what you started, by name or by label, e.g. `docker rm -f <name>` or "
         "`docker rm -f $(docker ps -aq --filter label=dk.issue=<n>)`.")
MASS_REMOVAL = ("deny", "Mass docker removal without a label or name filter hits other projects' resources. Filter "
                "by a label your session set, e.g. --filter label=dk.issue=<n>.")


def check_docker(cmd):
    findings = []
    for _, tokens in segments(cmd, "docker|podman"):
        if "prune" in tokens:
            findings.append(PRUNE)
    mass = re.finditer(r"\b(?:docker|podman)\s+(?:rm|rmi|stop|kill|(?:container|volume|network|image)\s+rm)\b[^;&|\n]*?"
                       r"\$\(\s*((?:docker|podman)\s+[^)]*)\)", cmd)
    piped = re.finditer(r"\b((?:docker|podman)\s+(?:ps|volume\s+ls|images|image\s+ls|network\s+ls)\b[^|;&\n]*)\|\s*"
                        r"xargs\s+(?:-\S+\s+)*(?:docker|podman)\s+(?:rm|rmi|stop|kill|volume\s+rm)", cmd)
    for m in list(mass) + list(piped):
        if not re.search(r"(?:--filter|-f)[=\s]+[\"']?(?:label|name|ancestor|id)=", m.group(1)):
            findings.append(MASS_REMOVAL)
    return findings


def is_docker(words):
    return bool(words) and os.path.basename(words[0]) in ("docker", "podman")


def removes(words):
    return words[1:2] in (["rm"], ["rmi"], ["stop"], ["kill"]) \
        or (words[1:2] in (["container"], ["volume"], ["network"], ["image"]) and words[2:3] == ["rm"])


def lists(words):
    return words[1:2] in (["ps"], ["images"]) or (words[1:2] in (["volume"], ["image"], ["network"])
                                                   and words[2:3] == ["ls"])


def filtered(words):
    """True when a docker listing filters by label, name, ancestor or id (`--filter x`, `--filter=x`, `-qf x`)."""
    it = iter(words)
    for w in it:
        if w == "--filter" or re.fullmatch(r"-[a-zA-Z]*f", w):
            value = next(it, "")
        elif w.startswith("--filter="):
            value = w[len("--filter="):]
        else:
            continue
        if re.match(r"(?:label|name|ancestor|id)=", value):
            return True
    return False


def docker_words(segs):
    findings = []
    for seg in segs:
        _, words = command(seg)
        if not is_docker(words):
            continue
        if "prune" in words:
            findings.append(PRUNE)
        if removes(words):
            findings += [MASS_REMOVAL for sub in seg.subs for inner in sub
                         if is_docker(command(inner)[1]) and not filtered(command(inner)[1])]
        if lists(words) and seg.pipe_to is not None and not filtered(words):
            wrappers, target = command(seg.pipe_to)
            if "xargs" in wrappers and is_docker(target) and removes(target):
                findings.append(MASS_REMOVAL)
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


DK_GC = re.compile(r"(?:^|(\|\|?|" + OPENERS + r"))\s*" + PREFIX
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


def quoted_text(cmd, pos, shell=""):
    """True when `pos` sits in a quoted string that is data, not the script of `<shell> -c '...'`."""
    quote = open_quote(cmd, pos)
    return quote is not None and not re.search(shell + r"-c\s+$", cmd[:quote])


def check_dk_gc(cmd):
    # `2>&1` and `&>` would end the match at their `&` and hide a later --yes or `<`; `<&3` stays as input
    cmd = OUTPUT_REDIRECT.sub(lambda r: " " * len(r.group()), cmd)
    for m in DK_GC.finditer(cmd):
        sep, rest = m.group(1) or "", m.group(2)
        if quoted_text(cmd, m.end(1) if m.group(1) else m.start()):
            continue
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
LOOP = re.compile(START + r"(?:for|foreach|select)\s+((?:[A-Za-z_]\w*\s+)*?[A-Za-z_]\w*)\b(?=\s+in\b|\s*[(;\n]|\s*$)")


def check_zsh_names(cmd):
    targets = [(m.start(1), m.group(1).split()) for m in LOOP.finditer(cmd)]
    targets += [(offset, [t.partition("?")[0] for t in tokens[1:] if not t.startswith("-")])
                for offset, tokens in segments(cmd, "read")]
    for offset, names in targets:
        if quoted_text(cmd, offset, shell=r"\bzsh\s+(?:(?:[-+]o\s+\w+|[-+][a-zA-Z]+)\s+)*"):
            continue
        hit = next((n for n in names if n in ZSH_SPECIAL), None)
        if hit:
            return [("deny", f"`{hit}` is a special parameter in zsh, the shell this runs in (`path` is tied to "
                     "PATH, so every later command is \"command not found\"; `status`, `argv` and the like are "
                     "read-only or special). Name the loop or read variable something else, e.g. `p` or `file`.")]
    return []


FILE_CHECKS = {"ls", "stat", "test", "[", "[["}


def in_code_span(cmd, m):
    # a real backtick substitution of the bare path would run the file, not read it
    return bool(re.search(r"`[\w~/${}.-]*$", cmd[:m.start()]) and re.match(r"[\w./-]*\\?`", cmd[m.end():]))


def only_checks_file(cmd, pos):
    start = None
    for start in re.finditer(START, cmd[:pos]):
        pass
    opener = cmd[start.start():start.end()].strip() if start else ""
    if opener in ("$(", "`") or (opener == "(" and start.start() > 0 and cmd[start.start() - 1] in "<>"):
        return False  # its output is substituted into another command
    words = re.sub("^" + PREFIX, "", cmd[start.end() if start else 0:pos]).split()
    end = re.search(r"[;&|\n)`]", cmd[pos:])
    piped = end and end.group() == "|" and cmd[pos + end.end():pos + end.end() + 1] != "|"
    return bool(words) and words[0] in FILE_CHECKS and not piped


def check_credentials(cmd):
    scan = OUTPUT_REDIRECT.sub(lambda r: " " * len(r.group()), cmd)  # `2>&1 | xargs cat` still pipes
    m = next((m for m in CREDENTIALS.finditer(cmd)
              if not in_code_span(cmd, m) and not only_checks_file(scan, m.start())), None)
    if m:
        return [("deny", f"This reads {m.group(0)}, which holds a credential. Sentry event details come from "
                 "the repo's Sentry helper, named in its docs/agents/observability.md; anything else goes "
                 "through the CLI that owns the credential (sentry-cli, aws, gh, ssh-add).")]
    return []


def git_words(segs, cwd):
    findings = []
    for _, words, path in commands(segs, cwd):
        if words and os.path.basename(words[0]) == "git":
            findings += git_findings(words, path)
    return findings


def decide(cmd, cwd):
    segs = split(cmd)
    raw = strip_heredocs(cmd)
    if segs is None:  # a command the splitter cannot read gets the raw-string checks, so the guard never fails open
        findings = check_docker(raw) + check_git(raw, cwd) + check_credentials(raw) + check_gh(raw) \
            + check_postgres(raw) + check_dk_gc(raw) + check_zsh_names(raw)
    else:
        findings = docker_words(segs) + git_words(segs, cwd) + check_credentials(raw) + check_gh(raw) \
            + check_postgres(raw) + check_dk_gc(raw) + check_zsh_names(raw)
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
