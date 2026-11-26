#!/usr/bin/env python3
"""dk-gate: run a checkout's .claude/gate.sh, and skip the run when it already passed on the same tree.

    dk-gate [--fresh] [<dir>]   run the gate of the checkout holding <dir> (default: the current directory)

The push hook (push-gate.py) and an agent's hand run both come here, so a pass
by hand is the pass the next push reuses. Before a run it computes a key over
everything a pass depends on: the committed tree, the tracked changes, the
contents of untracked files that are not ignored, the gate script, the
lockfiles at the root (ignored or not), and the merge base of HEAD with
origin/pre-main, origin/main and origin/master (the gates select by changed
path against it). When the key matches the checkout's last pass, the gate does
not run and the pass is reported as cached. Only a pass is stored, and only
when the key after the run equals the key before it, so a tree that changed
while the gate ran is gated again. --fresh runs the gate whatever the cache
holds, for an input the key cannot see (a toolchain upgrade, a database).

The cache holds one entry per worktree, outside the repo:
$DK_GATE_CACHE when set (tests), else the dk-guard plugin's data directory
(~/.claude/plugins/data/dk-guard-dk-agent-kit/gate-cache, under
$CLAUDE_CONFIG_DIR when set). A hand run does not get the hooks'
CLAUDE_PLUGIN_DATA, so both sides use this fixed path.

A hand run prints the gate's output as it comes and exits with the gate's
code; a checkout without an executable gate exits 0 and says so.
"""
import datetime
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

GATE = os.path.join(".claude", "gate.sh")
TAIL_LINES, TAIL_CHARS = 40, 4000
KEY_VERSION = "1"
BASE_REFS = ("origin/pre-main", "origin/main", "origin/master")
LOCKFILES = ("bun.lock", "bun.lockb", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.sum", "Cargo.lock",
             "uv.lock", "poetry.lock", "Gemfile.lock", "composer.lock")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def git(cwd, *args):
    try:
        out = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def toplevel(path):
    return (git(path, "rev-parse", "--show-toplevel") or "").strip() or None


def tail(output):
    return "\n".join(output.rstrip().splitlines()[-TAIL_LINES:])[-TAIL_CHARS:]


def cache_dir():
    if os.environ.get("DK_GATE_CACHE"):
        return os.environ["DK_GATE_CACHE"]
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(config, "plugins", "data", "dk-guard-dk-agent-kit", "gate-cache")


def entry_path(root):
    return os.path.join(cache_dir(), hashlib.sha256(root.encode()).hexdigest()[:16] + ".json")


def _hash_file(h, path):
    try:
        st = os.lstat(path)
    except OSError:
        h.update(b"missing\0")
        return
    if os.path.islink(path):
        h.update(b"link\0" + os.readlink(path).encode(errors="surrogateescape") + b"\0")
    elif os.path.isdir(path):
        h.update(b"dir\0")  # a nested repository: git lists it, not its files
    else:
        h.update(b"exec\0" if st.st_mode & 0o111 else b"file\0")
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        except OSError:
            h.update(b"unreadable")
        h.update(b"\0")


def key(root):
    """A hash of everything a pass of the gate in `root` depends on, or None when git cannot read the checkout."""
    h = hashlib.sha256(f"dk-gate {KEY_VERSION}\0{root}\0".encode())
    head = (git(root, "rev-parse", "-q", "--verify", "HEAD^{tree}") or "").strip()
    h.update(f"tree {head or EMPTY_TREE}\0".encode())
    try:
        diff = subprocess.run(["git", "-C", root, "-c", "core.quotePath=false", "diff", "HEAD" if head else EMPTY_TREE,
                               "--binary", "--no-color", "--no-ext-diff", "--no-textconv"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if diff.returncode != 0:
        return None
    h.update(b"diff\0" + diff.stdout + b"\0")
    untracked = git(root, "ls-files", "-z", "--others", "--exclude-standard")
    if untracked is None:
        return None
    for rel in sorted(p for p in untracked.split("\0") if p):
        h.update(b"untracked\0" + rel.encode(errors="surrogateescape") + b"\0")
        _hash_file(h, os.path.join(root, rel))
    for rel in (GATE, *LOCKFILES):
        h.update(b"input\0" + rel.encode() + b"\0")
        _hash_file(h, os.path.join(root, rel))
    for ref in BASE_REFS:
        mb = (git(root, "merge-base", "HEAD", ref) or "").strip() if head else ""
        h.update(f"base {ref} {mb or '-'}\0".encode())
    return h.hexdigest()


def cached_pass(root, k):
    """The stored pass for `root` when its key is `k`, else None."""
    if k is None:
        return None
    try:
        with open(entry_path(root)) as f:
            entry = json.load(f)
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) and entry.get("root") == root and entry.get("key") == k else None


def store_pass(root, k, seconds):
    entry = {"root": root, "key": k, "passed_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
             "seconds": round(seconds, 1)}
    path = entry_path(root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".entry-")
        with os.fdopen(fd, "w") as f:
            json.dump(entry, f)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def run_gate(gate, root, timeout=None, capture=True):
    """Run the gate in its own process group; return (failure or None, combined output).

    With capture=False the output goes to this process's stdout as it comes and the returned output is empty."""
    try:
        proc = subprocess.Popen([gate], cwd=root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.STDOUT if capture else None, start_new_session=capture)
    except OSError as e:
        return f"could not run: {e.strerror}", ""
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the gate's test runners go with it
        except ProcessLookupError:
            pass  # the group exited between the timeout and the kill
        try:
            out, _ = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired as e:
            # A child that left the group still holds the pipe: keep what was read, stop waiting.
            proc.kill()
            out = e.output or b""
        failure = f"timed out after {timeout} s"
    else:
        failure = f"failed (exit {proc.returncode})" if proc.returncode else None
    return failure, (out or b"").decode("utf-8", errors="replace")


def check(root, timeout=None, capture=True, fresh=False):
    """Gate `root`: returns (status, output, entry). status is "cached", "passed", "passed, not cached" or the
    failure ("failed (exit 1)", "timed out after 540 s", ...); entry is the cached pass for "cached"."""
    gate = os.path.join(root, GATE)
    before = key(root)
    if not fresh:
        entry = cached_pass(root, before)
        if entry:
            return "cached", "", entry
    start = time.monotonic()
    failure, output = run_gate(gate, root, timeout, capture)
    if failure:
        return failure, output, None
    after = key(root)
    if before is not None and after == before and store_pass(root, before, time.monotonic() - start):
        return "passed", output, None
    return "passed, not cached", output, None


def main(argv):
    args = [a for a in argv if a != "--fresh"]
    if len(args) > 1 or any(a.startswith("-") for a in args):
        print("usage: dk-gate [--fresh] [<dir>]", file=sys.stderr)
        return 2
    root = toplevel(args[0] if args else os.getcwd())
    if not root:
        print(f"dk-gate: {args[0] if args else os.getcwd()} is not in a git checkout", file=sys.stderr)
        return 2
    if not os.access(os.path.join(root, GATE), os.X_OK):
        print(f"dk-gate: {root} has no executable {GATE}; nothing to run")
        return 0
    sys.stdout.flush()
    status, _, entry = check(root, capture=False, fresh="--fresh" in argv)
    head = f"dk-gate: {GATE} in {root}"
    if status == "cached":
        print(f"{head} passed at {entry['passed_at']} on this same tree, so it did not run again (cached). "
              "`dk-gate --fresh` runs it anyway.")
    elif status == "passed":
        print(f"{head} passed; a push of this same tree reuses the pass.")
    elif status.startswith("passed"):
        print(f"{head} passed, but the tree changed while it ran, so the pass is not cached.")
    else:
        print(f"{head} {status}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
