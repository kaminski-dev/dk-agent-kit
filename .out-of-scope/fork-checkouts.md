# Fork, ssh-alias and GHE checkouts

The kit's scripts take the repo they ask `gh` about from the checkout's `origin` remote, and only from there. A checkout whose `origin` is a fork of the repo the work happens in, an ssh host alias (`git@gh-work:owner/repo.git`) or a GitHub Enterprise host is not supported.

## Why this is out of scope

`batch.py`, `pr-wait` and `ready.py` each read `owner/repo` from `origin`'s configured URL in `origin_repo()` and set it as `GH_REPO` before their first `gh` call (`pr-wait` takes `--repo` or a PR URL ahead of `origin`); `dk-gc`'s `slug_of()` reads it with the same pattern. The URL must name the host `github.com`, in any case, with or without an ssh port:

| origin URL | repo |
|---|---|
| `git@github.com:o/r.git`, `https://GitHub.com/o/r.git`, `ssh://git@github.com:22/o/r.git` | `o/r` |
| `https://notgithub.com/o/r.git`, `git@gh-work:o/r.git`, `git@ghe.corp.example:o/r.git` | none |

The alternative, letting `gh` resolve the repo itself (even with an inherited `GH_REPO` stripped), lets `gh repo set-default` or `gh`'s ranking of remotes (an `upstream` ahead of `origin`) pick a repo other than the checkout's own. That is the bug class #97 closed: a script reading another repo's PRs and issues without an error, and an agent acting on them. One rule, `origin`, keeps the answer the same in every shell.

What each unsupported shape does:

- **Fork**: the scripts ask about the fork. `pr-wait` fails loudly, since the PR is on the upstream. `ready.py` lists the fork's issues without an error.
- **ssh alias or GHE host**: no repo is found, and every script stops before its first `gh` call. `dk-gc` keeps everything in such a checkout.

## If a real case shows up

The override would be `git config dk.repo <owner/repo>`, read before the URL in each `origin_repo()` copy and in `dk-gc`'s `slug_of()`. `tests/test_skills.py` compares the `origin_repo()` copies whole, but only the pattern line of `slug_of()`, so that check would need to cover the override in `dk-gc` too. The skill text needs no new flag.

## Prior requests

- #103: "Origin pinning (#97): fork checkouts, non-github.com origins and squash-merged pre-main"
