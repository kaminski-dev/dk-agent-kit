#!/usr/bin/env python3
"""Starts the Bash guard from its bytecode cache: what hooks.json runs before every Bash call.

Python compiles a script it runs on every start, about 10 ms for guard-bash.py, and caches a module it
imports, so this file imports the guard and calls its main(). The cache is `__pycache__/` beside the guard;
Python writes it on the first call, drops it when guard-bash.py's size or modification second differs, and
compiles on every call when the directory cannot be written to. An error here exits nonzero, which blocks
the call (`onFailure: block`).
"""
import importlib.util
import os

spec = importlib.util.spec_from_file_location(
    "guard_bash", os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-bash.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
guard.main()
