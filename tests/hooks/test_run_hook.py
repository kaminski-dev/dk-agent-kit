#!/usr/bin/env python3
"""Runs each hooks.json command as the harness starts it, through `sh -c` with the hook JSON on stdin, against a
copy of the plugin and a fixture PATH.

The fixture's interpreters are scripts that write their name and process id to a log and then start the real
interpreter, so a case reads which one a hook ran: `shim` for pyenv's shim (`<pyenv>/shims/python3`), a version's
name for `<pyenv>/versions/<name>/bin/python3`, `plain` for a python3 no version manager owns. The process id
shows whether the interpreter replaced the harness's `sh` or cost a process more.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, "..", "..", "plugins", "dk-guard"))
SYSTEM = "/usr/bin:/bin"  # git and sh for the hooks; a python3 there comes after every fixture interpreter

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(name)


def interpreter(path, name, works=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f'#!/bin/sh\necho "{name} $$" >> "$HOOK_LOG"\n'
                + (f'exec "{sys.executable}" "$@"\n' if works else f"echo '{name}: cannot start' >&2\nexit 1\n"))
    os.chmod(path, 0o755)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def hook_commands():
    hooks = json.load(open(os.path.join(PLUGIN, "hooks", "hooks.json")))["hooks"]
    return [h for groups in hooks.values() for g in groups for h in g["hooks"]]


def payload(tool, tool_input, cwd, event="PreToolUse"):
    return {"session_id": "test", "cwd": cwd, "hook_event_name": event, "tool_name": tool, "tool_input": tool_input}


class Run:
    """One hook call: its exit status and output, and the fixture interpreters it started, in order."""

    def __init__(self, root, plugin, command, data, path, cwd, env=None):
        log = os.path.join(root, "interpreters.log")
        open(log, "w").close()
        proc = subprocess.Popen(["sh", "-c", command.replace("${CLAUDE_PLUGIN_ROOT}", plugin)], cwd=cwd, text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env={"PATH": path, "HOME": os.path.join(root, "home"), "HOOK_LOG": log, **(env or {})})
        self.stdout, self.stderr = proc.communicate(json.dumps(data))
        self.status = proc.returncode
        started = [line.split() for line in open(log)]
        self.interpreters = [name for name, _ in started]
        self.one_process = all(int(pid) == proc.pid for _, pid in started)

    def decision(self):
        if self.status != 0:
            return f"exit {self.status}"
        if not self.stdout.strip():
            return "allow"
        return json.loads(self.stdout)["hookSpecificOutput"].get("permissionDecision", "hint")

    def __str__(self):
        return f"{self.decision()}, ran {self.interpreters}, one process: {self.one_process}, stderr: {self.stderr[-300:]!r}"


def main():
    hooks = hook_commands()
    guard, = [h for h in hooks if h.get("onFailure") == "block"]
    with tempfile.TemporaryDirectory() as root:
        root = os.path.realpath(root)
        plugin = shutil.copytree(PLUGIN, os.path.join(root, "plugin"), ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(root, "home"))
        project = os.path.join(root, "project")
        nested = os.path.join(project, "src", "deep")
        os.makedirs(nested)
        pyenv = os.path.join(root, "pyenv")
        shims = os.path.join(pyenv, "shims")
        interpreter(os.path.join(shims, "python3"), "shim")
        for version in ("3.11.9", "3.12.1"):
            interpreter(os.path.join(pyenv, "versions", version, "bin", "python3"), version)
        global_version = os.path.join(pyenv, "version")
        write(global_version, "3.11.9\n")
        plain = os.path.join(root, "plain", "bin")
        interpreter(os.path.join(plain, "python3"), "plain")
        with_pyenv = f"{shims}:{plain}:{SYSTEM}"

        calls = {
            "guard-bash": payload("Bash", {"command": "echo hi"}, project),
            "push-gate": payload("Bash", {"command": "echo hi"}, project),
            "require-worktree": payload("Edit", {"file_path": os.path.join(project, "a.txt"), "old_string": "a",
                                                 "new_string": "b"}, project),
            "fork-guard": payload("Agent", {"subagent_type": "general-purpose", "description": "look",
                                            "prompt": "Read the file."}, project),
            "session-baseline": {"session_id": "test", "cwd": project, "hook_event_name": "SessionStart",
                                 "source": "startup"},
        }

        def call_for(hook):
            name, = [n for n in calls if n in hook["command"]]
            return name, calls[name]

        check("hooks.json: a call for each of its commands", len(hooks) == len(calls) == 5, len(hooks))

        # Which interpreter starts, and in how many processes.
        for hook in hooks:
            name, data = call_for(hook)
            got = Run(root, plugin, hook["command"], data, with_pyenv, project)
            check(f"{name}, pyenv's shim first on PATH: the version pyenv's global file names starts, the shim "
                  "does not, and no process is added",
                  got.decision() == "allow" and got.interpreters == ["3.11.9"] and got.one_process, got)
            got = Run(root, plugin, hook["command"], data, f"{plain}:{SYSTEM}", project)
            check(f"{name}, no pyenv: the python3 on PATH starts, as before",
                  got.decision() == "allow" and got.interpreters == ["plain"] and got.one_process, got)

        def guard_run(path=with_pyenv, cwd=project, env=None, command="echo hi", plugin=plugin):
            return Run(root, plugin, guard["command"], payload("Bash", {"command": command}, cwd), path, cwd, env)

        got = guard_run(path=f"{plain}:{shims}:{SYSTEM}")
        check("a python3 ahead of the shims on PATH: that one starts", got.interpreters == ["plain"], got)
        got = guard_run(env={"PYENV_VERSION": "3.12.1"})
        check("PYENV_VERSION names a version: that one starts", got.interpreters == ["3.12.1"], got)
        write(os.path.join(project, ".python-version"), "3.12.1\n")
        got = guard_run(cwd=nested)
        check("a .python-version above the working directory: its version starts", got.interpreters == ["3.12.1"], got)
        got = guard_run(cwd=nested, env={"PYENV_VERSION": "3.11.9"})
        check("PYENV_VERSION and a .python-version: the variable wins, as in pyenv",
              got.interpreters == ["3.11.9"], got)

        # Whatever the launcher cannot settle alone goes to the shim, which decides as before.
        got = guard_run(cwd=nested, env={"PYENV_DIR": root})
        check("PYENV_DIR set: the shim decides", got.interpreters == ["shim"] and got.one_process, got)
        write(os.path.join(project, ".python-version"), "../../plain\n")
        got = guard_run(cwd=nested)
        check("a .python-version that climbs out of pyenv's versions: the shim decides, and nothing outside starts",
              got.interpreters == ["shim"], got)
        os.remove(os.path.join(project, ".python-version"))
        for text, label in (("3.9.0\n", "a version that is not installed"), ("system\n", "`system`"),
                            ("# pinned below\n3.11.9\n", "a comment line first"), ("", "nothing")):
            write(global_version, text)
            got = guard_run()
            check(f"the global version file holds {label}: the shim decides", got.interpreters == ["shim"], got)
        os.remove(global_version)
        got = guard_run()
        check("no global version file: the shim decides", got.interpreters == ["shim"], got)
        write(global_version, "3.11.9\n")
        got = guard_run(env={"PYENV_VERSION": "3.11.9:3.12.1"})
        check("PYENV_VERSION names several versions: the shim decides", got.interpreters == ["shim"], got)

        # The guard still decides, isolated, and fails closed.
        got = guard_run(command="git push origin main")
        check("the guard, started directly, denies a push to main",
              got.decision() == "deny" and got.interpreters == ["3.11.9"], got)
        planted = os.path.join(root, "planted")
        write(os.path.join(planted, "json.py"), "raise SystemExit(0)\n")
        got = guard_run(command="git push origin main", cwd=planted, env={"PYTHONPATH": planted})
        check("a json.py on PYTHONPATH and in the working directory is not imported (-I)", got.decision() == "deny", got)
        check("hooks.json: the Bash guard blocks when its command fails", guard.get("onFailure") == "block", guard)
        only_sh = os.path.join(root, "only-sh")
        os.makedirs(only_sh)
        os.symlink(shutil.which("sh"), os.path.join(only_sh, "sh"))
        got = guard_run(path=only_sh)
        check("no python3 on PATH: the guard's command fails, which blocks the call",
              got.status != 0 and not got.stdout.strip(), got)
        interpreter(os.path.join(shims, "python3"), "shim", works=False)
        write(global_version, "3.9.0\n")
        got = guard_run()
        check("the pyenv version is not installed and the shim fails: the guard's command fails",
              got.status != 0 and not got.stdout.strip() and got.interpreters == ["shim"], got)

        # The guard's bytecode cache: written on the first call, used after it, never trusted over the source.
        def install(name):
            return shutil.copytree(PLUGIN, os.path.join(root, name), ignore=shutil.ignore_patterns("__pycache__"))

        def cached(plugin):
            return glob.glob(os.path.join(plugin, "scripts", "__pycache__", "guard-bash.*.pyc"))

        without_pyenv = f"{plain}:{SYSTEM}"
        fresh = install("fresh")
        got = guard_run(path=without_pyenv, command="git push origin main", plugin=fresh)
        check("the first call after an install, with no cache yet, denies a push to main and leaves the cache",
              got.decision() == "deny" and len(cached(fresh)) == 1, f"{got}, cache: {cached(fresh)}")
        written = [os.stat(f).st_mtime_ns for f in cached(fresh)]
        got = guard_run(path=without_pyenv, command="git push origin main", plugin=fresh)
        check("the second call decides the same and leaves the cache as it was",
              got.decision() == "deny" and [os.stat(f).st_mtime_ns for f in cached(fresh)] == written, got)
        got = guard_run(path=without_pyenv, plugin=fresh)
        source = os.path.join(fresh, "scripts", "guard-bash.py")
        entry = '\n\nif __name__ == "__main__":'
        text = open(source).read()
        write(source, text.replace(entry, '\n\ndef decide(cmd, cwd, background=False):\n'
                                          '    return "deny", "edited between two calls"\n' + entry))
        edited = guard_run(path=without_pyenv, plugin=fresh)
        check("guard-bash.py edited between two calls: the next call runs the new code",
              entry in text and got.decision() == "allow" and edited.decision() == "deny"
              and "edited between two calls" in edited.stdout, f"before: {got}; after: {edited}")
        damaged = install("damaged")
        guard_run(path=without_pyenv, plugin=damaged)
        for f in cached(damaged):
            with open(f, "wb") as out:
                out.write(b"not bytecode")
        got = guard_run(path=without_pyenv, command="git push origin main", plugin=damaged)
        check("a damaged cache file: the guard compiles again and denies a push to main",
              bool(cached(damaged)) and got.decision() == "deny", got)
        readonly = install("readonly")
        scripts = os.path.join(readonly, "scripts")
        os.chmod(scripts, 0o555)
        if os.access(scripts, os.W_OK):
            print("SKIP a plugin directory that cannot be written to: this user writes to it anyway")
        else:
            got = guard_run(path=without_pyenv, command="git push origin main", plugin=readonly)
            again = guard_run(path=without_pyenv, plugin=readonly)
            check("a plugin directory that cannot be written to: the guard compiles on each call and decides",
                  got.decision() == "deny" and again.decision() == "allow" and not cached(readonly),
                  f"{got}; {again}; cache: {cached(readonly)}")
        os.chmod(scripts, 0o755)
        broken = install("broken")
        with open(os.path.join(broken, "scripts", "guard-bash.py"), "a") as f:
            f.write("\ndef (:\n")
        got = guard_run(path=without_pyenv, plugin=broken)
        check("a guard that does not compile: the guard's command fails, which blocks the call",
              got.status != 0 and not got.stdout.strip(), got)
        os.remove(os.path.join(broken, "scripts", "guard-bash.py"))
        got = guard_run(path=without_pyenv, plugin=broken)
        check("no guard-bash.py in the plugin: the guard's command fails",
              got.status != 0 and not got.stdout.strip(), got)

    print(f"\n{'FAIL' if failures else 'ok'}: {len(failures)} failed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
