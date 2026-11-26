#!/usr/bin/env python3
"""Static checks on the dk:modernize skill's prose; the checks across skills are in tests/test_skills.py."""
import importlib.util
import pathlib
import re

_spec = importlib.util.spec_from_file_location("_skills", pathlib.Path(__file__).resolve().parent / "_skills.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
errors, frontmatter, skills = lib.errors, lib.frontmatter, lib.skills

# A stale PR is judged as an idea before its branch is rebased, and only a leased push updates it (#123).
modernize = skills.get("modernize")
modernize_text = modernize.read_text() if modernize else ""
if not modernize:
    errors.append("skills/modernize: missing; a stale PR has no procedure")
elif frontmatter(modernize).get("disable-model-invocation") != "true":
    errors.append("skills/modernize: must be user-invoked (disable-model-invocation: true)")
for what, pattern in (
    ("its tstack provenance marker", r"<!-- Adapted from t3dotgg/tstack@1085050 skills/modernize, MIT \(© 2026 Theo Browne\)\. "
                                     r"Changed for dk-agent-kit: "),
    ("the three dispositions", r"MODERNIZE.*REWORK.*CLOSE"),
    ("that age alone is not evidence", r"Age alone is not evidence"),
    ("the base read from workflow.md", r"base.*`docs/agents/workflow\.md`"),
    ("the worktree from dk:issue-flow step 2", r"`dk:issue-flow` step 2"),
    ("the base's new commits checked for conceptual conflicts", r"conceptual conflict"),
    ("the series compared with git range-diff", r"git range-diff"),
    ("the push leased to the observed remote head, every ref quoted",
     r'git push --force-with-lease="refs/heads/<branch>:<observed sha>" origin "HEAD:refs/heads/<branch>"'),
    # CodeRabbit on #136, round 2 (#112): headRefName reaches the shell only once Git accepts it as a branch name.
    ("the branch checked before any shell use, stopping when it fails",
     r'`git check-ref-format --branch "<branch>"`[^.]*stop.*?`git ls-remote origin "refs/heads/<branch>"`'),
    # Git accepts `$`, backticks and `"` in a branch name, which double quotes still expand.
    ("the branch limited to letters, digits, '.', '_', '-' and '/' before any shell use",
     r"only letters, digits, `\.`, `_`, `-` and `/`"),
    # CodeRabbit on #136 (#112): a wrong base stops first, a fork's head comes from refs/pull, the work stays in the worktree.
    ("a base mismatch stopping before any change to the branch, until the user's word",
     r"`baseRefName` differs stops here, before any change to its branch[^.]*only on the user's word"),
    ("a fork PR's head fetched read-only from refs/pull", r"`git fetch -q origin pull/<PR>/head`"),
    ("items 2 to 5 run inside the chosen worktree", r"Items 2 to 5 run inside that worktree"),
    # CodeRabbit on #136, round 4 (#112): a fork's branch is never pushed, and the base gets the branch's checks.
    ("a fork PR stopping before step 4", r"`isCrossRepository` is true[^.]*stop before step 4"),
    # CodeRabbit local review on #136 (#112): only an open PR is changed, and <PR> and <term> reach the shell checked.
    ("a PR that is not open stopping before any change", r"`state` is not `OPEN` stops here"),
    ("the PR number checked as digits before the first command", r"`<PR>` is the PR's number, digits only"),
    ("the search term kept free of shell syntax", r"`<term>`[^.]*none of"),
    ("the base checked like the branch before any shell use", r"`<base>` passes the same two checks"),
    ("the push from the path item 1 chose, -modernize included", r"`~/workspace/<prefix>-<N>-modernize`, written literally"
                                                                  r".*cd <that path> && git push"),
):
    if modernize and not re.search(pattern, modernize_text, re.S):
        errors.append(f"skills/modernize: does not name {what}")
for span in re.findall(r"`(git [^`]*)`", modernize_text):
    for token in span.split():
        if "<base>" in token and not token.startswith('"'):
            errors.append(f"skills/modernize: `{span}` leaves `<base>` unquoted")
if re.search(r"--force-with-lease(?!=)", modernize_text):
    errors.append("skills/modernize: a bare --force-with-lease leases against whatever the last fetch saw; "
                  "name the branch and the observed sha")

lib.finish("dk:modernize")
