#!/usr/bin/env python3
"""dk-guard PreToolUse hook for the Bash tool.

Reads the hook JSON on stdin and answers with a permission decision:
deny for commands that destroyed shared state before (docker prune, unfiltered
mass removal, pushes to main, force pushes, git clean of ignored files),
leaked a credential (reading a credential file) or broke the shell (a zsh
special parameter such as `path` as a loop, read or assigned variable, `$name:`
before a zsh modifier, a variable holding a spaced command as the command, a
function named like one of the user's zsh aliases) or blocked the session (a CI
or merge wait outside run_in_background) or dropped the issue body (`gh issue
view --comments`) or a dk:verify run's evidence (`rm` inside a verify.XXXXXX run
directory) or ran a Markdown code span (a backtick span in an unquoted here-doc
body), ask for
rewriting the shared pre-main branch, a push to the current branch when the
guard cannot tell which branch that is, or answering dk-gc's question for the
human (--yes, piped input), and
hints for `gh pr view --comments`, which drops the body, for an unlabelled
Postgres server that dk-pg should start instead, and for `git worktree remove`
in a loop, which dk-gc does. Everything else passes.

The rules match on words: the command is split once, as the shell reads it,
into segments of words (quotes, here-docs, redirections, substitutions and
`<shell> -c` scripts included). Quoted text and quoted here-doc bodies are data
to the command rules, so a commit message may mention a command; a credential
path is caught even when quoted. The substitutions of an unquoted here-doc run,
so they are checked. A command the splitter cannot read gets the raw-string
checks, so a parse failure never lets a command through.

This raises the floor against agent mistakes; it is not a security boundary.
"""
import collections
import dataclasses
import itertools
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

# The raw-string checks, for a command the splitter cannot read.
# Where a command can start: line start, after a control operator, inside $( or
# backticks, after a shell keyword, or at the opening quote of `bash -c '...'`.
OPENERS = r"[;&|\n({`]|\$\(|\b(?:then|do|else|while|until|if)\s|-c\s+['\"]"
START = r"(?:^|" + OPENERS + r")\s*"
PREFIX = r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:(?:sudo|command|exec|nohup|time|env|nice|xargs(?:\s+-\S+)*|g?timeout\s+\S+)\s+)*"
END = r"[^;&|\n)`]*"


# A here-doc operator and its delimiter word: plain characters, backslash escapes and closed quotes, starting the
# way a delimiter does (a digit after `<<` is a shift, as in `1<<2`).
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*"
                     r"""((?=[A-Za-z_'"\\])(?:[^\s;&|<>()'"\\]|\\.|'[^']*'|"(?:[^"\\]|\\.)*")+)(?!['"])""")


def without_arithmetic(line):
    """The line with each $((...)) and ((...)) cut out up to its balancing paren or the line's end, since a << in
    one is a shift."""
    kept, i = [], 0
    while (start := line.find("((", i)) >= 0:
        kept.append(line[i:start])
        depth, i = 0, start
        while i < len(line):
            depth += {"(": 1, ")": -1}.get(line[i], 0)
            i += 1
            if depth == 0:
                break
    return " ".join(kept + [line[i:]])


def heredoc_lines(cmd):
    """Yield (line, None) for each command line and (line, expands) for each line of a heredoc body, `expands`
    True when no part of its delimiter word is quoted or escaped."""
    lines, i = cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        i += 1
        yield line, None
        for dash, word in HEREDOC.findall(without_arithmetic(line)):
            delim, expands = shlex.split(word)[0], not re.search(r"['\"\\]", word)
            while i < len(lines):
                body = lines[i]
                i += 1
                if (body.lstrip("\t") if dash else body) == delim:
                    break
                yield body, expands


def strip_heredocs(cmd):
    """The command lines without heredoc bodies, for the raw-string command checks; check_heredoc_backticks reads
    the bodies that expand."""
    return "\n".join(line for line, expands in heredoc_lines(cmd) if expands is None)


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
# A function name holds no `$` or `=`: `X=$(date)` is an assignment whose substitution reads as `$()`.
FUNCTION_NAME = re.compile(r"[^\s$=()]+")
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
        self.modifier_names = []  # `$name:x`, x a zsh modifier, unquoted or double-quoted
        self.heredoc_backticks = []  # the backtick substitutions in the body of its unquoted here-docs
        self.defines = None  # the function name when the segment is `f()`, `f ()` or `function f`
        self.loop_last = None  # for a one-line `for x (a b) cmd` header, the last segment of the sublist it repeats
        self.piped_in = self.piped_out = self.started = False
        self.pipe_to = None


class Splitter:
    """Splits `text` into every segment it runs, in order: substitutions, here-doc bodies that expand, and the
    scripts of `bash -c '...'`, `zsh -fc '...'` and the like included."""

    def __init__(self, text, shell="zsh", substituted=False, depth=0):
        if depth > 16:
            raise Unsplittable("nested too deep")
        self.s, self.i, self.shell, self.substituted, self.depth = text, 0, shell, substituted, depth
        self.out, self.heredocs, self.modifier_names, self.backticks = [], [], [], []
        self.command_subs = 0  # how many `$(...)` the cursor is inside

    def run(self):
        self.parse(None, self.substituted)
        self.read_heredocs()
        return self.out

    def peek(self, k=0):
        return self.s[self.i + k] if self.i + k < len(self.s) else ""

    def at_expansion(self):
        return self.s.startswith(("$(", "${", "`"), self.i)

    def parse(self, end, substituted):
        seg, open_short_fors = Segment(self.shell, substituted), []
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
                self.end_sublist(open_short_fors)
            elif c == ")":
                self.i += 1
                if end == ")":
                    break
                seg = self.close(seg)  # a case pattern's `)`
            elif (keyword := list_loop(seg.words)) and not REDIRECT.match(self.s, self.i) \
                    and not OPERATOR.match(self.s, self.i):
                # zsh's one-line `for x (a b) cmd` and `foreach x (a b) cmd; …; end`: the body gets its own segment
                if keyword == "for" and not re.match(r"(?:do|\{)(?=[\s;&|<>()]|$)", self.s[self.i:]):
                    open_short_fors.append(seg)
                seg = self.close(seg)
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
                if op not in ("&&", "||", "|", "|&"):
                    self.end_sublist(open_short_fors)
            elif c == "(" and not seg.started and self.peek(1) != "(":
                self.i += 1
                seg = self.close(seg)
                self.parse(")", substituted)  # a subshell
            else:
                mark = len(self.modifier_names)
                word, quoted, subs = self.word()
                seg.subs += subs
                self.take_modifiers(seg, mark)
                if self.add_word(seg, word, quoted):
                    seg = self.close(seg)
        self.close(seg)
        self.end_sublist(open_short_fors)

    def end_sublist(self, open_short_fors):
        for header in open_short_fors:
            header.loop_last = self.out[-1]
        open_short_fors.clear()

    def add_word(self, seg, word, quoted=False):
        """Add a word; True when it ends a function's name (`f() {`, `f () {`, `function f {`), so its body starts
        a new segment."""
        first = not seg.started and word not in LEAD
        seg.started = seg.started or first
        seg.words.append(word)
        named = command_words(seg.words)[1]
        if first and not quoted and FUNCTION_NAME.fullmatch(word[:-2]) and word.endswith("()"):
            seg.defines = word[:-2]
        elif not quoted and named[1:] == ["()"] and FUNCTION_NAME.fullmatch(named[0]):
            seg.defines = named[0]
        elif named[:1] == ["function"] and len(named) == 2:
            seg.defines = word[:-2] if word.endswith("()") else word
        return seg.defines is not None

    def take_modifiers(self, seg, mark):
        """Move the modifier names noted since `mark` to `seg`; a substitution inside the word took its own."""
        seg.modifier_names += self.modifier_names[mark:]
        del self.modifier_names[mark:]

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
            mark = len(self.modifier_names)
            target, quoted, subs = self.word()
            seg.subs += subs
            self.take_modifiers(seg, mark)
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
                seg.modifier_names += body.modifier_names
                seg.heredoc_backticks += body.backticks

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
                if buf[-1] == "()":
                    break  # `f(){ ...`: the name ends here and the body opens
            else:
                self.note_modifier()
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
                self.note_modifier()
                buf.append(c)
                self.i += 1

    def note_modifier(self):
        m = MODIFIER.match(self.s, self.i)
        if m:
            self.modifier_names.append(m.group(1))

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
        self.command_subs += 1
        self.parse(")", True)
        self.command_subs -= 1
        return self.out[start:]

    def backtick(self):
        start = self.i
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
        if not self.command_subs:
            self.backticks.append(self.s[start:self.i])
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


def list_loop(words):
    """`for` or `foreach` when `words` are a loop header up to its zsh word list (`for x y (a b)`, `for ((…))`),
    so a word after it starts the body; else None."""
    words = list(itertools.dropwhile(lambda w: w in LEAD, words))
    names = words[1:-1]
    if words[:1] in (["for"], ["foreach"]) and len(words) > 1 and words[-1].startswith("(") \
            and "in" not in names and all(re.fullmatch(r"[A-Za-z_]\w*", n) for n in names):
        return words[0]
    return None


def split(cmd):
    """Every segment of the command in order, or None when it cannot be split."""
    try:
        return Splitter(cmd).run()
    except (Unsplittable, RecursionError):
        return None


def command(seg):
    """(wrappers, words from the program on): leading keywords, assignments and wrappers such as `sudo -u x`
    dropped."""
    return command_words(seg.words)


def command_words(words):
    i, wrappers = 0, []
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


def cd_into(cwd, target):
    """The directory `cd target` (or `git -C target`) leaves you in, from `cwd`; None when either is known only at
    run time (`cd "$WT"`)."""
    target = os.path.expanduser(target)
    if cwd is None or "$" in target or "`" in target:
        return None
    return target if os.path.isabs(target) else os.path.join(cwd, target)


def commands(segs, cwd):
    """(segment, words from the program on, the directory it runs in) for each segment, following `cd`s."""
    for seg in segs:
        _, words = command(seg)
        if words[:1] == ["cd"] and len(words) > 1:
            cwd = cd_into(cwd, words[1])
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
    """The directory a command at `offset` of the raw text runs in, following earlier `cd`s."""
    for m in re.finditer(r"(?:^|[;&|\n(]|\b(?:then|do|else)\s)\s*cd\s+(\S+)", cmd[:offset]):
        cwd = cd_into(cwd, m.group(1).strip("'\""))
    return cwd


def short_ref(ref):
    return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref


def check_git(cmd, cwd):
    findings = []
    for offset, tokens in segments(cmd, "git"):
        findings += git_findings(tokens, effective_cwd(cmd, offset, cwd))
    return findings


def git_subcommand(tokens, path):
    """(the words from the subcommand on, the directory it runs in) for one `git` invocation run in `path`, its
    global options dropped and `-C` followed."""
    args = tokens[1:]
    while args and args[0].startswith("-"):
        opt = args.pop(0)
        if opt == "-C" and args:
            path = cd_into(path, args.pop(0))
        elif opt in ("-c", "--git-dir", "--work-tree", "--namespace") and args:
            args.pop(0)
    return args, path


def git_findings(tokens, path):
    """Findings for one `git` invocation (`tokens[0]` is git), run in `path` (None when unknown)."""
    args, path = git_subcommand(tokens, path)
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


def git_words(segs, cwd):
    findings = []
    for _, words, path in commands(segs, cwd):
        if words and os.path.basename(words[0]) == "git":
            findings += git_findings(words, path)
    return findings


UNKNOWN_BRANCH = ("ask", "This push goes to the current branch, and the guard cannot tell which branch that is (the "
                  "directory is known only at run time, or is no checkout), so it cannot rule out main. Name the "
                  "branch: `git push -u origin <branch>`.")


def destination(spec):
    """The remote ref a refspec writes: `dst` of `src:dst`, else the source itself."""
    src, colon, dst = spec.lstrip("+").partition(":")
    return dst if colon else src


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
    # no refspec, or HEAD as the destination, pushes to the current branch
    if branch is None and (not refspecs or "HEAD" in map(destination, refspecs)):
        return [UNKNOWN_BRANCH]
    if not refspecs:
        refspecs = [branch] if branch != "HEAD" else []
    findings = []
    for spec in refspecs:
        plus = spec.startswith("+")
        is_delete = delete or spec.lstrip("+").startswith(":")
        dst = destination(spec)
        dst = short_ref(branch if dst == "HEAD" else dst)
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


BOOLEANS = {"1": True, "t": True, "T": True, "true": True, "True": True, "TRUE": True,
            "0": False, "f": False, "F": False, "false": False, "False": False, "FALSE": False}


def run_options(options):
    """Split `docker run` options into flags (`--rm=True` read as `--rm`, `--rm=false` dropped, as docker parses
    booleans) and label keys (`--label k=v`, `--label=k=v`, `-l k=v`, `-lk=v`)."""
    flags, labels = [], set()
    it = iter(options)
    for a in it:
        short = re.fullmatch(r"-([ditPq]*)l(.*)", a)
        if a == "--label":
            labels.add(next(it, "").partition("=")[0])
        elif short:
            flags += ["-" + short.group(1)] if short.group(1) else []
            labels.add((short.group(2) or next(it, "")).partition("=")[0])
        elif a.startswith("--label="):
            labels.add(a[len("--label="):].partition("=")[0])
        elif re.fullmatch(r"--[\w-]+=\w+", a) and a.partition("=")[2] in BOOLEANS:
            name, _, value = a.partition("=")
            flags += [name] if BOOLEANS[value] else []
        else:
            flags.append(a)
    return flags, labels


def check_postgres(cmd):
    cmd = cmd.replace("\\\n", " ")
    return next(filter(None, (postgres_findings(tokens) for _, tokens in segments(cmd, "docker|podman"))), [])


def postgres_findings(tokens):
    """Findings for one `docker` or `podman` invocation (`tokens[0]` is the program)."""
    args = tokens[1:]
    if args[:2] == ["container", "run"]:
        args = args[1:]
    if args[:1] != ["run"]:
        return []
    i = run_image(args[1:])
    if i is None or not POSTGRES_IMAGE.match(args[1 + i]):
        return []
    flags, labels = run_options(args[1:1 + i])  # what follows the image is the container's command
    detached = any(a == "--detach" or re.fullmatch(r"-[ditPq]*d[ditPq]*", a) for a in flags)
    if "dk.issue" not in labels and (detached or "--rm" not in flags):
        return [("hint", "This Postgres server carries no issue label, so nothing ties it to an issue or "
                 "cleans it up. `dk-pg up <issue>` starts a throwaway one on a free port (--rm, tmpfs, labels "
                 "dk.repo and dk.issue) and prints its URL; `dk-pg url <issue>` reprints it, "
                 "`dk-pg down <issue>` removes it.")]
    return []


def check_gh(cmd):
    return next(filter(None, (gh_findings(tokens) for _, tokens in segments(cmd, "gh"))), [])


def gh_findings(tokens):
    if tokens[1:3] in (["issue", "view"], ["pr", "view"]) and "--comments" in tokens \
            and not any(t.startswith("--json") for t in tokens):
        if tokens[1] == "issue":
            return [("deny", "Piped `gh issue view --comments` prints the comments but not the body. Use "
                     "`gh issue view <N> --json title,body,labels,comments`.")]
        return [("hint", "Piped `gh pr view --comments` prints the comments but not the body. If you "
                 "need both, use `--json title,body,labels,comments`.")]
    return []


def postgres_words(segs):
    return next(filter(None, (postgres_findings(w) for _, w in map(command, segs) if is_docker(w))), [])


def gh_words(segs):
    return next(filter(None, (gh_findings(w) for _, w in map(command, segs)
                              if w and os.path.basename(w[0]) == "gh")), [])


FOREGROUND_WAIT = ("deny", "This waits on CI or a merge in the foreground, and the session answers nothing until it "
                   "returns. Start the same command with run_in_background (or as a Monitor until-loop) and keep "
                   "answering the user; a single `gh pr checks <N>` without --watch reads the state once.")
LOOP_KEYWORDS = ("for", "foreach", "select", "while", "until", "repeat")
GH_REPO_FLAG = r"(?:\s+(?:-R\s*\S+|--repo[=\s]\S+))*"
# the gh calls that read PR or run state, the ones a wait repeats; writes such as `gh pr comment` wait on nothing
READS = {"pr": ("checks", "view", "status", "list"), "run": ("view", "list", "watch")}
# `gh api` reads with no method and no fields or body (fields alone make it a POST), with GET named last (the fields
# become query parameters), or as a GraphQL query
API_FIELDS = ("--field", "--raw-field", "--input")
API_SHORT_FIELDS = ("-f", "-F")
API_VALUE_OPTIONS = ("-H", "--header", "-q", "--jq", "-t", "--template", "--cache", "-p", "--preview", "--hostname")
# a GraphQL document that opens with a query (`{ … }` or `query …`) reads; a mutation, a subscription, or a document
# the guard cannot see (`-F query=@q.graphql`, a substitution) may write
GRAPHQL_QUERY = re.compile(r"\s*(?:#[^\n]*\n\s*)*(?:\{|query\b)")
# gh keeps the last method flag, so a method writes only when no later one replaces it
API_WRITE = r"\s(?:(?:-X\s*=?|--method[=\s]\s*)(?=[^\s=])(?!['\"]?(?i:get)\b)(?!" + END + r"\s(?:-X|--method\b))|" \
    + "|".join(API_SHORT_FIELDS) + r"|(?:" + "|".join(API_FIELDS) + r")\b)"
API_GET = r"\s(?:-X\s*=?|--method[=\s]\s*)['\"]?(?i:get)\b(?!" + END + r"\s(?:-X|--method\b))"
API_QUERY = r"(?=" + END + r"\sgraphql\b)(?=" + END + r"\s(?:-[fF]\s*|--(?:raw-)?field[=\s]\s*)['\"]?query=['\"]?" \
    + GRAPHQL_QUERY.pattern + ")"
GH_POLL = r"\bgh" + GH_REPO_FLAG + r"\s+(?:(?:" + "|".join(
    rf"{group}\s+(?:{'|'.join(subs)})" for group, subs in READS.items()) + r")\b|api\b(?:" + API_QUERY \
    + r"|(?!" + END + r"\sgraphql\b)(?:(?!" + END + API_WRITE + r")|(?=" + END + API_GET + r"))))"
RAW_WAITS = [re.compile(p, re.S) for p in (
    START + PREFIX + r"(gh)" + GH_REPO_FLAG + r"\s+(?:pr\s+checks\b" + END + r"\s--watch\b(?!=false)|run\s+watch\b)",
    START + PREFIX + r"(watch)\s" + END + GH_POLL,
    START + r"(" + "|".join(LOOP_KEYWORDS) + r")\b(?=.*?" + GH_POLL + r")(?=.*?\bsleep\b)",
    START + r"(while|until)\b[^;\n]*?" + GH_POLL,
)]


def gh_args(words):
    """gh's words from the subcommand on, past its repo flag; None for a command other than gh."""
    if not words or os.path.basename(words[0]) != "gh":
        return None
    rest = words[1:]
    while rest and (rest[0] in ("-R", "--repo") or rest[0].startswith(("-R", "--repo="))):
        rest = rest[2:] if rest[0] in ("-R", "--repo") else rest[1:]
    return rest


def polls(words):
    args = gh_args(words)
    if args and args[0] == "api":
        return api_reads(args[1:])
    return args is not None and len(args) > 1 and args[1] in READS.get(args[0], ())


def api_reads(args):
    method, fields, endpoint, it = None, [], None, iter(args)
    for w in it:
        if w in ("-X", "--method"):
            method = next(it, "")
        elif w.startswith("-X"):
            method = w[2:].lstrip("=")
        elif w.startswith("--method="):
            method = w.split("=", 1)[1]
        elif w in API_SHORT_FIELDS or w in API_FIELDS:
            fields.append(next(it, ""))
        elif w[:2] in API_SHORT_FIELDS:
            fields.append(w[2:])
        elif w.split("=", 1)[0] in API_FIELDS:
            fields.append(w.split("=", 1)[1])
        elif w in API_VALUE_OPTIONS:
            next(it, None)
        elif endpoint is None and not w.startswith("-"):
            endpoint = w
    if endpoint == "graphql":
        return any(f.startswith("query=") and GRAPHQL_QUERY.match(f[len("query="):]) for f in fields)
    return (method or "GET").upper() == "GET" and (method is not None or not fields)


def watches(words):
    if words and os.path.basename(words[0]) == "watch":  # watch(1) reruns its command until stopped
        return bool(re.search(GH_POLL, " ".join(words[1:])))
    args = gh_args(words) or []
    return args[:2] == ["run", "watch"] or args[:2] == ["pr", "checks"] and any(
        w == "--watch" or w.startswith("--watch=") and w != "--watch=false" for w in args)


def check_waits(cmd):
    hits = [m for pattern in RAW_WAITS for m in pattern.finditer(cmd)]
    return [FOREGROUND_WAIT] if any(not quoted_text(cmd, m.start(1)) for m in hits) else []


@dataclasses.dataclass
class Loop:
    keyword: str
    in_condition: bool  # a while or until condition runs on every pass, so polling there waits even without a sleep
    condition_polls: bool = False
    body_polls: bool = False
    sleeps: bool = False
    loop_last: object = None

    def waits(self):
        return self.condition_polls or (self.body_polls and self.sleeps)


def wait_words(segs):
    loops = []  # innermost last
    for seg in segs:
        _, words = command(seg)
        keywords = list(itertools.takewhile(lambda w: w in LEAD or w in LOOP_KEYWORDS and w != "repeat", seg.words))
        rest = seg.words[len(keywords):]
        if rest[:1] == ["repeat"]:
            # zsh keeps `repeat N do cmd` in one segment; the short form `repeat N cmd` repeats cmd alone, no loop
            long_form = rest[2:3] == ["do"]
            _, words = command_words(rest[3:] if long_form else rest[2:])
            keywords += ["repeat"] if long_form else []
            if not long_form and rest[1:2] != ["1"] and polls(words):
                return [FOREGROUND_WAIT]
        elif seg.words == ["end"] and loops and loops[-1].keyword == "foreach":  # zsh: foreach x (…) … end
            if loops.pop().waits():
                return [FOREGROUND_WAIT]
        if watches(words):
            return [FOREGROUND_WAIT]
        for kw in keywords:
            if kw in LOOP_KEYWORDS:
                loop = Loop(kw, in_condition=kw in ("while", "until"), loop_last=seg.loop_last)
                # this segment's substitutions came before it in segs: the condition of a while or until, the first
                # body command of a repeat, the word list of a for (read once)
                sub_polls = any(polls(command(s)[1]) for sub in seg.subs for s in sub)
                loop.condition_polls = loop.in_condition and sub_polls
                loop.body_polls = kw == "repeat" and sub_polls
                loops.append(loop)
            elif kw == "do" and loops:
                loops[-1].in_condition = False
            elif kw == "done" and loops and loops.pop().waits():
                return [FOREGROUND_WAIT]
        if loops and loops[-1].in_condition and not seg.substituted and polls(words):
            loops[-1].condition_polls = True
        for loop in loops:
            loop.body_polls = loop.body_polls or polls(words)
            loop.sleeps = loop.sleeps or words[:1] == ["sleep"]
        while loops and loops[-1].loop_last is seg:
            if loops.pop().waits():
                return [FOREGROUND_WAIT]
    return [FOREGROUND_WAIT] if any(loop.waits() for loop in loops) else []


DK_GC = re.compile(r"(?:^|(\|\|?|" + OPENERS + r"))\s*" + PREFIX
                   + r"(?:python3?\s+(?:-\S+\s+)*)?(?:[^\s;&|()<>'\"]*/)?dk-gc"
                   + r"(?=$|[\s;&|)`<>]|['\"](?:$|[\s;&|)]))(" + END + ")")
DK_GC_YES = ("ask", "dk-gc removes worktrees, branches and databases after one yes, and that yes is the human's. "
             "Run `dk-gc` or `dk-gc --dry-run` and leave the answer to them.")
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
            return [DK_GC_YES]
    return []


def dk_gc_words(segs):
    for seg in segs:
        _, words = command(seg)
        if words and re.fullmatch(r"python3?", os.path.basename(words[0])):
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
        if not words or os.path.basename(words[0]) != "dk-gc" or "--dry-run" in words:
            continue
        if "--yes" in words or seg.piped_in or any(op.startswith("<") for op, _ in seg.redirects):
            return [DK_GC_YES]
    return []


WORKTREE_LOOP = ("hint", "This loop removes worktrees by hand. `dk-gc --dry-run` lists the worktrees and branches of "
                 "merged PRs and the databases of closed issues; `dk-gc` removes them after the human's yes and keeps "
                 "a worktree with uncommitted changes.")
RAW_WORKTREE_LOOP = re.compile(START + r"(" + "|".join(k for k in LOOP_KEYWORDS if k != "repeat")
                               + r")\b(?=.*?\bgit\b[^;&|\n]*?\sworktree\s+remove\b)", re.S)


def check_worktree_loop(cmd):
    cmd = strip_heredocs(cmd)
    return [WORKTREE_LOOP] if any(not quoted_text(cmd, m.start(1)) for m in RAW_WORKTREE_LOOP.finditer(cmd)) else []


def worktree_loop_words(segs):
    loops = []  # innermost last
    for seg in segs:
        for kw in itertools.takewhile(lambda w: w in LEAD or w in LOOP_KEYWORDS and w != "repeat", seg.words):
            if kw in LOOP_KEYWORDS:
                loops.append(kw)
            elif kw == "done" and loops:
                loops.pop()
        if seg.words == ["end"] and loops[-1:] == ["foreach"]:  # zsh: foreach x (…) … end
            loops.pop()
        _, words = command(seg)
        if loops and words and os.path.basename(words[0]) == "git" \
                and git_subcommand(words, None)[0][:2] == ["worktree", "remove"]:
            return [WORKTREE_LOOP]
    return []


# zsh names that break the shell when assigned: `path` is tied to PATH (later commands are "not found"), the
# others are read-only or special arrays. The Bash tool runs zsh, so a loop, `read` or assignment on them breaks the
# call.
ZSH_SPECIAL = {"path", "PATH", "fpath", "module_path", "cdpath", "manpath", "status", "pipestatus", "argv",
               "commands", "functions", "aliases", "options", "parameters", "history"}
LOOP = re.compile(START + r"(?:for|foreach|select)\s+((?:[A-Za-z_]\w*\s+)*?[A-Za-z_]\w*)\b(?=\s+in\b|\s*[(;\n]|\s*$)")
LOOP_ITEM = r"\"[^\"]*\"|'[^']*'|[^\s;&|()\"']+"
ZSH_SCRIPT_OPENER = r"\bzsh\s+(?:(?:[-+]o\s+\w+|[-+][a-zA-Z]+)\s+)*"
DECLARE = {"local", "typeset", "declare", "export", "readonly", "integer", "float"}
ASSIGN_PARTS = re.compile(r"([A-Za-z_]\w*)(?:\[[^]]*\])?(\+?=)(.*)", re.S)


def check_zsh_names(cmd):
    targets = [(m.start(1), m.group(1).split()) for m in LOOP.finditer(cmd)]
    targets += [(offset, [t.partition("?")[0] for t in tokens[1:] if not t.startswith("-")])
                for offset, tokens in segments(cmd, "read")]
    for m in re.finditer(START, cmd):
        text = re.match(END, cmd[m.end():]).group()
        try:
            words = shlex.split(text)
        except ValueError:
            words = text.split()
        targets.append((m.end(), list(overwritten(words))))
    for offset, names in targets:
        if quoted_text(cmd, offset, shell=ZSH_SCRIPT_OPENER):
            continue
        findings = zsh_name_findings(names)
        if findings:
            return findings
    return []


def zsh_name_findings(names):
    hit = next((n for n in names if n in ZSH_SPECIAL), None)
    if hit:
        return [("deny", f"`{hit}` is a special parameter in zsh, the shell this runs in (`path` is tied to "
                 "PATH, so every later command is \"command not found\"; `status`, `argv` and the like are "
                 "read-only or special). Name the variable something else, e.g. `p` or `file`.")]
    return []


def assignments(words):
    """(name, operator, value) for each variable a simple command sets: its leading assignments, or the names after
    a DECLARE word (a bare name there has no operator and value)."""
    words = list(itertools.dropwhile(lambda w: w in LEAD, words))
    if words[:1] and words[0] in DECLARE:
        rest = [w for w in words[1:] if not w.startswith(("-", "+"))]
    else:
        rest = itertools.takewhile(ASSIGNMENT.match, words)
    for w in rest:
        m = ASSIGN_PARTS.fullmatch(w)
        yield m.groups() if m else (w, None, None)


def overwritten(words):
    """The zsh special names a simple command overwrites. PATH itself, `path+=(…)` and a value that keeps the old one
    (`path=(/opt/bin $path)`) edit the search path on purpose; `local path`, or `typeset path` in a function, empties
    it, while `typeset -p path` only prints it."""
    words = list(itertools.dropwhile(lambda w: w in LEAD, words))
    localizes = words[:1] in (["local"], ["typeset"], ["declare"], ["integer"], ["float"]) \
        and not any(re.fullmatch(r"[-+]\w*p\w*", w) for w in words[1:])
    for name, op, value in assignments(words):
        keeps = op and re.search(r"\$\{?(?:%s|%s)\b" % (name, name.upper()), value)
        edits = name == "PATH" or keeps or op == "+=" and name.endswith("path")
        if name in ZSH_SPECIAL and (op is None and localizes or op and not edits):
            yield name


def loop_header(words):
    """(names, items) when `words` open a for, foreach or select loop, else None; no items when the loop runs over
    the positional parameters. Items from zsh's `(a "b c")` list keep their quotes."""
    words = list(itertools.dropwhile(lambda w: w in LEAD, words))
    if words[:1] not in (["for"], ["foreach"], ["select"]):
        return None
    names = list(itertools.takewhile(lambda w: w != "in" and not w.startswith("("), words[1:]))
    rest = words[1 + len(names):]
    if rest[:1] == ["in"]:
        return names, rest[1:]
    return names, re.findall(LOOP_ITEM, rest[0][1:-1]) if rest else []


def zsh_name_words(segs):
    for seg in (seg for seg in segs if seg.shell == "zsh"):
        names, loop = list(overwritten(seg.words)), loop_header(seg.words)
        if loop:
            names += loop[0]
        else:
            _, words = command(seg)
            if words[:1] == ["read"]:
                names += [w.partition("?")[0] for w in words[1:] if not w.startswith("-")]
        findings = zsh_name_findings(names)
        if findings:
            return findings
    return []


# A zsh modifier after an unbraced name: `$c:refs/heads/x` reads `:r` (drop the extension), then `efs/heads/x`.
MODIFIER = re.compile(r"\$([A-Za-z_]\w*|\d):(?:[aAcehlPqQrstu&]|g[s&])")


def modifier_findings(name):
    return [("deny", f"In zsh, `${name}:` before a letter applies a modifier (`:r` drops an extension, `:t` keeps "
             "the last path part), so the text after the colon is lost. Write `${" + name + "}:` for a literal "
             "colon, or `${" + name + ":t}` and the like when you mean the modifier.")]


def check_modifiers(cmd):
    for m in MODIFIER.finditer(cmd):
        escaped = re.search(r"(?<!\\)(?:\\\\)*\\$", cmd[:m.start()])
        quote = open_quote(cmd, m.start())
        if escaped or quote is not None and cmd[quote] == "'" and quoted_text(cmd, m.start(), shell=ZSH_SCRIPT_OPENER):
            continue
        return modifier_findings(m.group(1))
    return []


def modifier_words(segs):
    return next((modifier_findings(name) for seg in segs if seg.shell == "zsh" for name in seg.modifier_names), [])


# zsh does not word-split a variable: `G="git grep -n"; $G foo` runs a command named `git grep -n`.
VARIABLE_COMMAND = ("deny", "zsh does not word-split a variable, so a command kept in a string runs as one word "
                    "(\"command not found: git grep -n\"). Use a function with a descriptive name, an array "
                    "(`cmd=(git grep -n); $cmd foo`), or `${=name}`, which splits it (the fix for a loop "
                    "over quoted commands).")
SPACED_RAW = re.compile(r"(?:^|[\s;&|(])([A-Za-z_]\w*)=(?:\"[^\"]*\s[^\"]*\"|'[^']*\s[^']*')")
LOOP_ITEMS_RAW = re.compile(START + r"(?:for|foreach|select)\s+((?:[A-Za-z_]\w*\s+)*?[A-Za-z_]\w*)(?:\s+in\b|\s*\()"
                            + r"((?:[ \t]*(?:" + LOOP_ITEM + "))*)")


def check_command_variable(cmd):
    spaced = [(m.start(1), m.end(), [m.group(1)], START) for m in SPACED_RAW.finditer(cmd)]
    # the one-line `for c (…) $c` starts its body right after the list's `)`
    spaced += [(m.start(1), m.end(), spaced_loop_names(m.group(1).split(), re.findall(LOOP_ITEM, m.group(2))),
                r"(?:" + START + r"|^\)\s*)") for m in LOOP_ITEMS_RAW.finditer(cmd)]
    for start, end, names, opener in spaced:
        if quoted_text(cmd, start, shell=ZSH_SCRIPT_OPENER):
            continue
        for name in names:
            use = opener + PREFIX + r"[\"']?\$\{?" + name + r"\}?[\"']?(?=\s|[;&|)]|$)"
            if re.search(use, cmd[end:]):
                return [VARIABLE_COMMAND]
    return []


def spaced_loop_names(names, items):
    """The loop names that get an item with a space: zsh deals the items to the names in turn."""
    return [name for k, name in enumerate(names) if any(re.search(r"\s", i) for i in items[k::len(names)])]


def command_variable_words(segs):
    spaced = set()
    for seg in (seg for seg in segs if seg.shell == "zsh"):
        _, words = command(seg)
        m = re.fullmatch(r"\$\{?([A-Za-z_]\w*)\}?", words[0]) if words else None
        if m and m.group(1) in spaced:
            return [VARIABLE_COMMAND]
        assigned = [(name, not value.startswith("(") and bool(re.search(r"\s", value)))
                    for name, op, value in assignments(seg.words) if op]
        loop = loop_header(seg.words)
        if loop:
            names, items = loop
            assigned += [(name, name in spaced_loop_names(names, items)) for name in names]
        for name, holds_spaces in assigned:
            if holds_spaces:
                spaced.add(name)
            else:
                spaced.discard(name)
    return []


# A function named like one of the user's zsh aliases fails: "defining function based on alias", or the alias runs.
# bootstrap.sh writes the alias names, one per line, beside the private settings overlay; without the file, no deny.
ALIASES_FILE = "~/.config/dk-agent-kit/zsh-aliases"
FUNCTION_RAW = re.compile(START + r"(?:function\s+([^\s(){};&|<>'\"$]+)|([^\s(){};&|<>'\"$=]+)\s*\(\s*\))")


def alias_names():
    try:
        with open(os.path.expanduser(ALIASES_FILE), encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip() and not line.startswith("#")}
    except (OSError, UnicodeDecodeError):
        return set()


def alias_function_findings(names):
    hit = next((n for n in names if n in alias_names()), None) if names else None
    return [("deny", f"`{hit}` is one of your zsh aliases, so zsh refuses to define a function with that name "
             "(\"defining function based on alias\") or runs the alias instead. Use a descriptive name, e.g. "
             "`git_in`.")] if hit else []


def check_function_names(cmd):
    names = [m.group(1) or m.group(2) for m in FUNCTION_RAW.finditer(cmd)
             if not quoted_text(cmd, m.start(1) if m.group(1) else m.start(2), shell=ZSH_SCRIPT_OPENER)]
    return alias_function_findings(names)


def function_name_words(segs):
    return alias_function_findings([seg.defines for seg in segs if seg.shell == "zsh" and seg.defines])


FILE_CHECKS = {"ls", "stat", "test", "[", "[["}
# Tools whose first operand is a pattern or script, not a file: a credential name there is text being searched or
# edited (`sed -i '' 's#~/.sentryclirc#…#' a.ts`), unless the script itself reads files (`script_reads`).
PatternTool = collections.namedtuple("PatternTool", "short_takes long_takes pattern_opts no_pattern script_reads")
# an escape and a plain character are disjoint alternatives, so a failed match cannot backtrack exponentially
SED_ADDRESS = r"(?:\d+|\$|/(?:\\.|[^/\\])*/)"
SED_SUBSTITUTION = re.compile(rf"\s*(?:{SED_ADDRESS}(?:,{SED_ADDRESS})?)?\s*s(.)(?:\\.|(?!\1)[^\\])*\1"
                              r"(?:\\.|(?!\1)[^\\])*\1[gpIiM0-9]*\s*", re.S)
GREP = PatternTool("efmABCdD", {"--regexp", "--file", "--max-count", "--after-context", "--before-context", "--context",
                                "--include", "--exclude", "--exclude-dir", "--exclude-from", "--binary-files",
                                "--devices", "--directories"},
                   {"-e", "--regexp"}, set(), lambda script: False)
RG = PatternTool("efgtTmABCjMrEd", {"--regexp", "--file", "--glob", "--iglob", "--type", "--type-not", "--max-count",
                                    "--after-context", "--before-context", "--context", "--max-depth", "--replace",
                                    "--ignore-file", "--type-add", "--sort", "--sortr", "--max-filesize"},
                 {"-e", "--regexp"}, {"--files", "--type-list"}, lambda script: False)
# sed's r, R, w, W and e commands and the s///e flag read or run files, so only plain substitutions are text
SED = PatternTool("efl", {"--expression", "--file"}, {"-e", "--expression"}, set(),
                  lambda script: not all(SED_SUBSTITUTION.fullmatch(c)
                                         for c in re.split(r"[;\n]", script) if c.strip()))
AWK = PatternTool("Fvf", set(), set(), set(), lambda script: re.search(r"\bgetline\b|\bsystem\s*\(", script))
PATTERN_TOOLS = {"grep": GREP, "egrep": GREP, "fgrep": GREP, "rg": RG, "sed": SED, "gsed": SED,
                 "awk": AWK, "gawk": AWK, "mawk": AWK, "nawk": AWK}


def in_code_span(text, m):
    """True when a literal backtick pair encloses the match: a Markdown code span in text, not a read (a real
    backtick substitution of the bare path would run the file). In raw text an escaped closing backtick keeps its
    backslash, so one may stand before it."""
    return bool(re.search(r"`[\w~/${}.-]*$", text[:m.start()]) and re.match(r"[\w./-]*\\?`", text[m.end():]))


def last_start(cmd, pos):
    """The last place a command can start before `pos`, or None."""
    return next(reversed(list(re.finditer(START, cmd[:pos]))), None)


def only_checks_file(cmd, pos):
    start = last_start(cmd, pos)
    opener = cmd[start.start():start.end()].strip() if start else ""
    if opener in ("$(", "`") or (opener == "(" and start.start() > 0 and cmd[start.start() - 1] in "<>"):
        return False  # its output is substituted into another command
    words = re.sub("^" + PREFIX, "", cmd[start.end() if start else 0:pos]).split()
    end = re.search(r"[;&|\n)`]", cmd[pos:])
    piped = end and end.group() == "|" and cmd[pos + end.end():pos + end.end() + 1] != "|"
    return bool(words) and words[0] in FILE_CHECKS and not piped


def pattern_args(words):
    """Indexes of the words that are the pattern or script of a grep, rg, sed or awk call (`words[0]` is the
    program): the value of -e, else the first operand when no -e or -f gave one."""
    tool = PATTERN_TOOLS.get(os.path.basename(words[0])) if words else None
    if tool is None:
        return set()
    found, operands, given, k = set(), [], False, 1
    while k < len(words):
        w, k = words[k], k + 1
        if w == "--":
            operands += range(k, len(words))
            break
        if w.startswith("--"):
            name = w.partition("=")[0]
            given = given or name in ("--regexp", "--file", "--expression") or name in tool.no_pattern
            if name in tool.pattern_opts:
                found.add(k - 1 if "=" in w else k)
            k += 1 if "=" not in w and name in tool.long_takes else 0
        elif w.startswith("-") and len(w) > 1:
            if w == "-i" and k < len(words) and re.fullmatch(r"|\.\w+", words[k]) and tool is SED:
                k += 1  # BSD sed: `-i ''` or `-i .bak`
                continue
            for j, c in enumerate(w[1:], 1):
                if c in tool.short_takes:
                    given = given or c in "ef"
                    attached = j < len(w) - 1
                    if "-" + c in tool.pattern_opts:
                        found.add(k - 1 if attached else k)
                    k += 0 if attached else 1
                    break
        else:
            operands.append(k - 1)
    if not given and operands:
        found.add(operands[0])
    return {k for k in found if k < len(words) and not tool.script_reads(words[k])}


def in_pattern_arg(cmd, pos):
    start, quote = last_start(cmd, pos), open_quote(cmd, pos)
    close = cmd.find(cmd[quote], pos) if quote is not None else -1
    end = close + 1 if close >= 0 else re.compile(r"\s|$").search(cmd, pos).start()
    word = cmd[start.end() if start else 0:end] + (cmd[quote] if quote is not None and close < 0 else "")
    try:
        words = shlex.split(re.sub("^" + PREFIX, "", word))  # up to the end of the word `pos` sits in
    except ValueError:
        return False
    if REDIRECT.match(words[-1]) or len(words) > 1 and REDIRECT.fullmatch(words[-2]):
        return False  # the shell reads a redirection's target
    _, words = command_words(drop_redirections(words))
    return len(words) - 1 in pattern_args(words)


def check_credentials(cmd):
    scan = OUTPUT_REDIRECT.sub(lambda r: " " * len(r.group()), cmd)  # `2>&1 | xargs cat` still pipes
    m = next((m for m in CREDENTIALS.finditer(cmd) if not in_code_span(cmd, m)
              and not only_checks_file(scan, m.start()) and not in_pattern_arg(scan, m.start())), None)
    return credential_findings(m.group(0)) if m else []


def credential_findings(path):
    return [("deny", f"This reads {path}, which holds a credential. Sentry event details come from the repo's "
             "Sentry helper, named in its docs/agents/observability.md; anything else goes through the CLI that "
             "owns the credential (sentry-cli, aws, gh, ssh-add).")]


def credential_words(segs):
    for seg in segs:
        _, words = command(seg)
        # ls, stat or test read nothing, unless their output feeds a pipe or a substitution
        if words[:1] and words[0] in FILE_CHECKS and not seg.piped_out and not seg.substituted:
            continue
        offset = len(seg.words) - len(words)
        not_reads = seg.scripts | {offset + k for k in pattern_args(words)}
        texts = [w for k, w in enumerate(seg.words) if k not in not_reads] + [t for _, t in seg.redirects]
        for text in texts:
            for m in CREDENTIALS.finditer(text):
                if not in_code_span(text, m):
                    return credential_findings(m.group(0))
    return []


# Under the issue number's directory any six characters or a glob name a run; elsewhere mktemp's six are rarely all
# lowercase, which keeps a file such as `verify.output` out.
RUN_DIR = re.compile(r"(?:^|/)(?:verify\.(?=[a-z]{0,5}[A-Z0-9])[A-Za-z0-9]{6}|\d+/verify\.(?:[A-Za-z0-9]{6}|\*))(?:/|$)")
VERIFY_RM = ("deny", "This deletes inside a dk:verify run directory (verify.XXXXXX), and a rerun needs no cleanup: "
             "screenshots overwrite by name, and a rerun takes a new `mktemp -d \"$SCRATCH/<N>/verify.XXXXXX\"` "
             "while the earlier runs stay as evidence. The control worktree goes with `git worktree remove`.")
VARIABLE = re.compile(r"\$\{(\w+)\}|\$(\w+)")
RAW_ASSIGN = re.compile(r"(?:^|[\s;&|(])(?:export\s+)?([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;&|)]*)")
RAW_CD = re.compile(START + r"cd\s+(\"[^\"]*\"|'[^']*'|[^\s;&|)]+)")


def run_path(cwd, target, known):
    """The path `target` names from `cwd`, with the variables this command set (`known`) filled in; one it did not
    set stays as written."""
    text = os.path.expanduser(VARIABLE.sub(lambda m: known.get(m.group(1) or m.group(2), m.group()), target))
    if text.startswith("$"):
        return text
    return os.path.normpath(text if cwd is None or text.startswith("/") else os.path.join(cwd, text))


def rm_operands(rm_words):
    options = True
    for w in rm_words[1:]:
        if options and w == "--":
            options = False
        elif not (options and w.startswith("-") and len(w) > 1):
            yield w


def removes_run(words, cwd, known):
    return bool(words) and os.path.basename(words[0]) == "rm" \
        and any(RUN_DIR.search(run_path(cwd, t, known)) for t in rm_operands(words))


def verify_rm_words(segs, cwd):
    known = {}
    for seg in segs:
        for name, op, value in assignments(seg.words):
            if op == "=":
                known[name] = run_path(None, value, known)
        _, words = command(seg)
        if words[:1] == ["cd"]:
            cwd = run_path(cwd, words[1], known) if len(words) > 1 and words[1] != "-" else None
        if removes_run(words, cwd, known):
            return [VERIFY_RM]
    return []


def check_verify_rm(cmd, cwd):
    steps = sorted([(m.start(1), "set", m.group(1), m.group(2)) for m in RAW_ASSIGN.finditer(cmd)]
                   + [(m.start(1), "cd", None, m.group(1)) for m in RAW_CD.finditer(cmd)])
    for offset, tokens in segments(cmd, r"(?:[\w./~-]*/)?rm"):
        if quoted_text(cmd, offset):
            continue
        known, here = {}, cwd
        for pos, kind, name, value in (s for s in steps if s[0] < offset and not quoted_text(cmd, s[0])):
            if kind == "set":
                known[name] = run_path(None, value.strip("'\""), known)
            else:
                here = run_path(here, value.strip("'\""), known)
        if removes_run(tokens, here, known):
            return [VERIFY_RM]
    return []


UNESCAPED_BACKTICK = re.compile(r"(?<!\\)(?:\\\\)*`(?:([^`]*)`)?")


def heredoc_backtick_findings(span):
    """`span` is the backtick substitution, or None for a backtick that never closes."""
    runs = f"{span} runs as a command" if span else "a backtick that never closes stops the shell with a parse error"
    return [("deny", f"The shell runs each backtick span in an unquoted here-doc body, so {runs} instead of staying "
             "text. Quote the delimiter (`<<'EOF'`) to keep the body as text; `$(...)` is the way to interpolate "
             "on purpose.")]


def check_heredoc_backticks(cmd):
    body = "\n".join(line for line, expands in heredoc_lines(cmd) if expands)
    m = UNESCAPED_BACKTICK.search(body)
    return heredoc_backtick_findings(None if m.group(1) is None else f"`{m.group(1)}`") if m else []


def heredoc_backtick_words(segs):
    return next((heredoc_backtick_findings(span) for seg in segs for span in seg.heredoc_backticks), [])


def decide(cmd, cwd, background=False):
    segs = split(cmd)
    if segs is None:  # a command the splitter cannot read gets the raw-string checks, so the guard never fails open
        raw = strip_heredocs(cmd)
        findings = check_docker(raw) + check_git(raw, cwd) + check_credentials(raw) + check_gh(raw) \
            + check_postgres(raw) + check_dk_gc(raw) + check_zsh_names(raw) + check_waits(raw) \
            + check_modifiers(raw) + check_command_variable(raw) + check_function_names(raw) \
            + check_verify_rm(raw, cwd) + check_heredoc_backticks(cmd)
    else:
        findings = docker_words(segs) + git_words(segs, cwd) + credential_words(segs) + gh_words(segs) \
            + postgres_words(segs) + dk_gc_words(segs) + zsh_name_words(segs) + wait_words(segs) \
            + modifier_words(segs) + command_variable_words(segs) + function_name_words(segs) \
            + verify_rm_words(segs, cwd) + heredoc_backtick_words(segs)
    findings += check_worktree_loop(cmd) if segs is None else worktree_loop_words(segs)
    if background:  # the same wait started with run_in_background blocks nothing
        findings = [f for f in findings if f is not FOREGROUND_WAIT]
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
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command") or ""
    cwd = data.get("cwd") or os.getcwd()
    level, reason = decide(cmd, cwd, tool_input.get("run_in_background") is True)
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
