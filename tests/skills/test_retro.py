#!/usr/bin/env python3
"""Static checks on the dk:retro skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, skills = lib.errors, lib.skills

# The retro's correct step judges a test as the review does (pstack correct, e5136d8).
retro_test = re.search(r"^   \d\. \*\*Test\*\*.*$", skills["retro"].read_text(), re.M)
if not retro_test or not re.search(r"still passes when the behaviour it checks breaks.*fails when only the internals change",
                                   retro_test.group(0)):
    errors.append("skills/retro: the correct step's **Test** level does not ask for a test that fails when the behaviour "
                  "breaks and keeps passing when only the internals change")

lib.finish("dk:retro")
