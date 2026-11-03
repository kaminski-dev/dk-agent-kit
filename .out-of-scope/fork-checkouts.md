# Fork, ssh-alias and GHE checkouts

The kit's scripts take the repo they ask `gh` about from the checkout's `origin` remote, and only from there. A checkout whose `origin` is a fork of the repo the work happens in, an ssh host alias (`git@gh-work:owner/repo.git`) or a GitHub Enterprise host is not supported.

## Why this is out of scope

`batch.py`, `wait-review.py` and `ready.py` each read `origin`'s configured URL in `origin_repo()` and pass the `owner/repo` they find to `gh` as `GH_REPO`; `dk-gc`'s `slug_of()` reads it the same way. The URL must name `github.com`:

```python
m = re.search(r"(?:^|[@/])github\.com(?::\d+)?[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url, re.I)
```

Falling back to `gh`'s own repo resolution, even with an inherited `GH_REPO` stripped, lets `gh repo set-default` or `gh`'s ranking of remotes (an `upstream` ahead of `origin`) pick a repo other than the checkout's own. That is the bug class #97 closed: a script reading or writing another repo's PRs and issues without an error.

What each unsupported shape does today:

- **Fork**: the scripts ask about the fork. `wait-review.py` fails loudly, since the PR is on the upstream. `ready.py` lists the fork's issues without an error.
- **ssh alias or GHE host**: `origin_repo()` finds no repo, and every script stops before its first `gh` call. `dk-gc` keeps everything in such a checkout.

No checkout that runs these scripts has had one of these shapes, so the cost of a second resolution path buys nothing yet.

## If a real case shows up

The override would be `git config dk.repo <owner/repo>`, read in `origin_repo()` before the URL. That is one change per copy, `tests/test_skills.py` keeps the copies in step, and the skill text needs no new flag.

## Prior requests

- #103: "Origin pinning (#97): fork checkouts, non-github.com origins and squash-merged pre-main"
