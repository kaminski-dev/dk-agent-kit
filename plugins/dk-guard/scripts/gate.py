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

The cache holds one entry per worktree, outside the repo, and a pass drops the
entries of worktrees that are gone:
$DK_GATE_CACHE when set (tests), else the dk-guard plugin's data directory
(~/.claude/plugins/data/dk-guard-dk-agent-kit/gate-cache, under
$CLAUDE_CONFIG_DIR when set). A hand run does not get the hooks'
CLAUDE_PLUGIN_DATA, so both sides use this fixed path.

At most DK_GATE_SLOTS gates (default 2) run at once on the machine, hand
runs and push runs alike, sessions with another CLAUDE_CONFIG_DIR included. A
run that needs the gate takes a slot first: an exclusive flock on one of the
files slot-0.lock, slot-1.lock, ... in
~/.claude/plugins/data/dk-guard-dk-agent-kit/gate-slots/ (whatever
CLAUDE_CONFIG_DIR says; $DK_GATE_CACHE/slots/ in tests), which the kernel releases when the holder dies, so
a killed run leaves no stale slot. With every slot held it waits up to
DK_GATE_WAIT seconds (default 240), then gives up and says the gates are busy;
the gate does not run, and nothing counts as passed. A cached pass takes no
slot.

One gate runs per checkout at a time, so two overlapping runs cannot leave a
pass the later, failing one contradicts. Before its slot a run takes an
exclusive flock on checkout-<hash of the root>.lock beside the slots, released
the same way; a pass drops the locks of worktrees that are gone. A second run waits for it holding no slot, then reads the cache
again: it reuses the first run's pass on the same tree and runs the gate
otherwise (--fresh always runs). That wait and the slot wait share the
DK_GATE_WAIT seconds; a run whose checkout stays busy gives up and says so.

The gate runs with DK_GATE_WORKERS (default 4: two gates on a 12-core machine,
with cores left for the sessions) in its environment, for the gate script to
pass to its tools (`go test -p`, `vitest --maxWorkers`, ...); a gate that
ignores it runs as before.

A hand run prints the gate's output as it comes and exits 0 on a pass, 1 on
a failure and 3 when the gate did not run (no slot freed, or its checkout's
other run outlasted the wait); a checkout without an executable gate exits 0
and says so.
"""
import datetime
import fcntl
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
BUSY = "busy"
SLOTS, CHECKOUT, LATE = "slots", "checkout", "late"  # why a check is BUSY


def setting(name, default):
    """A positive whole number from the environment, else `default`."""
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


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


def slots_dir():
    """The cap is the machine's, so the slots sit at one path whatever CLAUDE_CONFIG_DIR says."""
    if os.environ.get("DK_GATE_CACHE"):
        return os.path.join(os.environ["DK_GATE_CACHE"], "slots")
    return os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "dk-guard-dk-agent-kit", "gate-slots")


def checkout_lock(root):
    """The file a run holds while it gates `root`. It sits beside the slots, so it too is the machine's."""
    return os.path.join(slots_dir(), f"checkout-{hashlib.sha256(root.encode()).hexdigest()[:16]}.lock")


def slot_locks():
    return [os.path.join(slots_dir(), f"slot-{i}.lock") for i in range(setting("DK_GATE_SLOTS", 2))]


def take_lock(paths, root, wait, on_wait=None):
    """Hold an exclusive flock on the first of `paths` that is free: returns (the open file, None), or (None, the
    "<pid> <root>" line of each holder) when none freed within `wait` seconds; on_wait(holders) is called once,
    when the wait starts. The lock is held while the file stays open, and the kernel releases it when the holder
    dies. A lock file that cannot be made is no reason to block a gate: the result is then (None, None)."""
    try:
        os.makedirs(slots_dir(), exist_ok=True)
        files = [open(path, "a+") for path in paths]
    except OSError:
        return None, None
    deadline, told = time.monotonic() + wait, False
    while True:
        for f in files:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                continue
            for other in files:
                if other is not f:
                    other.close()
            f.seek(0)
            f.truncate()
            f.write(f"{os.getpid()} {root}\n")
            f.flush()
            return f, None
        holders = []
        for f in files:
            f.seek(0)
            holders.append(f.read().strip())
        if time.monotonic() >= deadline:
            for f in files:
                f.close()
            return None, holders
        if on_wait and not told:
            on_wait(holders)
            told = True
        time.sleep(0.2)


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
        if os.path.islink(os.path.join(root, rel)):  # a gate linked to an ignored script runs that script
            h.update(b"target\0")
            _hash_file(h, os.path.realpath(os.path.join(root, rel)))
    for ref in BASE_REFS:
        mb = (git(root, "merge-base", "HEAD", ref) or "").strip() if head else ""
        h.update(f"base {ref} {mb or '-'}\0".encode())
    return h.hexdigest()


def last_pass(root):
    """The stored pass for `root`, whatever tree it was on, else None."""
    try:
        with open(entry_path(root)) as f:
            entry = json.load(f)
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) and entry.get("root") == root else None


def cached_pass(root, k):
    """The stored pass for `root` when its key is `k`, else None."""
    entry = last_pass(root) if k is not None else None
    return entry if entry and entry.get("key") == k else None


def forget(root):
    try:
        os.remove(entry_path(root))
    except FileNotFoundError:
        pass


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
    drop_gone(os.path.dirname(path))
    return True


def drop_gone(directory):
    """Remove the entries and the checkout locks of worktrees that no longer exist, so the cache and the locks
    hold one file per live worktree."""
    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name)) as f:
                root = json.load(f).get("root")
            if isinstance(root, str) and not os.path.isdir(root):
                os.remove(os.path.join(directory, name))
        except (OSError, ValueError, AttributeError):
            pass  # dropped by another run meanwhile, or unreadable, which cached_pass reads as no pass
    try:
        locks = [os.path.join(slots_dir(), name) for name in os.listdir(slots_dir()) if name.startswith("checkout-")]
    except OSError:
        return
    for path in locks:
        try:
            with open(path) as f:
                root = f.read().strip().partition(" ")[2]
            if root and not os.path.isdir(root):
                os.remove(path)
        except OSError:
            pass  # dropped by another run meanwhile


def run_gate(gate, root, timeout=None, capture=True):
    """Run the gate; return (failure or None, combined output).

    With capture the gate runs in its own process group, so a timeout kills its test runners with it. With
    capture=False it shares this process's group, so Ctrl-C reaches it, and the output goes to this process's
    stdout as it comes; the returned output is empty."""
    env = {**os.environ, "DK_GATE_WORKERS": str(setting("DK_GATE_WORKERS", 4))}
    try:
        proc = subprocess.Popen([gate], cwd=root, stdin=subprocess.DEVNULL, env=env,
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


def last_seconds(root):
    """The seconds the last pass of `root` took, 0 with none on record."""
    seconds = (last_pass(root) or {}).get("seconds")
    return seconds if isinstance(seconds, (int, float)) else 0


def waited_for(cause, holders):
    """What a wait is on, from the holders' "<pid> <root>" lines: for SLOTS the roots whose gates hold the slots,
    for CHECKOUT the pid of the run that gates the same root. It is the entry of a BUSY check whose wait ran out."""
    pid_or_root = 0 if cause == CHECKOUT else 2
    return {"cause": cause, "holders": [line.partition(" ")[pid_or_root] or "?" for line in holders]}


def why_busy(root, entry):
    """What kept a BUSY check from running the gate, as the clause both callers open their message with."""
    if entry["cause"] == CHECKOUT:
        return (f"another run of {GATE} in {root} is still going (pid {', '.join(entry['holders'])}), so this one "
                "did not run")
    if entry["cause"] == LATE:
        return (f"only {entry['left']} s of the {entry['timeout']} s were left once the gate's turn came and the "
                f"tree was hashed, less than the {entry['needs']} s the last pass took, so {GATE} in {root} did "
                "not run")
    return f"gates are busy ({', '.join(entry['holders'])} held every slot), so {GATE} in {root} did not run"


def check(root, timeout=None, capture=True, fresh=False, wait=None, on_wait=None):
    """Gate `root`: returns (status, output, entry). status is "cached", "passed", "passed, not cached", BUSY or
    the failure ("failed (exit 1)", "timed out after 540 s", ...); entry is the cached pass for "cached", and for
    BUSY what why_busy() words: waited_for() the checkout or the slots, or LATE with the seconds that were left.

    One gate runs per root at a time: a run first waits for the run in flight on the same root, holding no slot,
    then reads the cache again, so it reuses that run's pass on the same tree. Then it waits for a slot. `timeout`
    covers both waits and the run together; the waits take at most `wait` seconds in all (default DK_GATE_WAIT),
    and on_wait(waited_for(...)) is called once as each starts. Under a timeout the run is left the seconds the
    root's last pass took: the waits end early enough for it, and a gate with less left once the tree is hashed
    does not start, so both report BUSY instead of a gate the timeout would kill."""
    gate = os.path.join(root, GATE)
    if not fresh:
        entry = cached_pass(root, key(root))
        if entry:
            return "cached", "", entry
    start = time.monotonic()
    wait = setting("DK_GATE_WAIT", 240) if wait is None else wait
    if timeout is not None:
        wait = max(0, min(wait, timeout - last_seconds(root)))
    waits = []

    def tell(cause):
        def told(holders):
            waits.append(cause)
            if on_wait:
                on_wait(waited_for(cause, holders))
        return told

    turn, holders = take_lock([checkout_lock(root)], root, wait, tell(CHECKOUT))
    if holders is not None:
        return BUSY, "", waited_for(CHECKOUT, holders)
    slot = None
    try:
        if waits and not fresh:
            entry = cached_pass(root, key(root))
            if entry:
                return "cached", "", entry
        slot, holders = take_lock(slot_locks(), root, max(0, start + wait - time.monotonic()), tell(SLOTS))
        if holders is not None:
            return BUSY, "", waited_for(SLOTS, holders)
        before = key(root)  # the tree may have changed during the wait for a slot
        if not fresh:
            entry = cached_pass(root, before)
            if entry:
                return "cached", "", entry
        left = None
        if timeout is not None:
            left, needs = timeout - (time.monotonic() - start), last_seconds(root)
            if needs and left < needs:
                return BUSY, "", {"cause": LATE, "left": max(0, round(left)), "needs": needs, "timeout": timeout}
            left = max(1, round(left))
        forget(root)  # a run that fails may fail on an input the key cannot see, so the older pass vouches for nothing
        run_start = time.monotonic()
        failure, output = run_gate(gate, root, left, capture)
        if failure:
            return failure, output, None
        after = key(root)
        if before is not None and after == before and store_pass(root, before, time.monotonic() - run_start):
            return "passed", output, None
        return "passed, not cached", output, None
    finally:
        for held in (slot, turn):
            if held:
                held.close()


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

    def on_wait(waited):
        holders = ", ".join(waited["holders"])
        if waited["cause"] == CHECKOUT:
            print(f"dk-gate: another run of {GATE} in {root} is going (pid {holders}); waiting for it to end.",
                  flush=True)
        else:
            print(f"dk-gate: {len(waited['holders'])} gates are running ({holders}); waiting for a slot.", flush=True)

    status, _, entry = check(root, capture=False, fresh="--fresh" in argv, on_wait=on_wait)
    head = f"dk-gate: {GATE} in {root}"
    if status == BUSY:
        again = {SLOTS: "Run dk-gate again in a minute.", LATE: "Run dk-gate again.",
                 CHECKOUT: "Run dk-gate again when that run ends; its pass on this same tree is reused."}
        print(f"dk-gate: {why_busy(root, entry)}. {again[entry['cause']]}")
        return 3
    if status == "cached":
        print(f"{head} passed at {entry['passed_at']} on this same tree, so it did not run again (cached). "
              "`dk-gate --fresh` runs it anyway.")
    elif status == "passed":
        print(f"{head} passed; a push of this same tree reuses the pass.")
    elif status.startswith("passed"):
        print(f"{head} passed, but the pass is not cached: the tree changed while it ran, or the cache could not "
              "be written.")
    else:
        print(f"{head} {status}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
