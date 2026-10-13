#!/usr/bin/env bash
# upstream/sync.sh against fixture upstream repos: local repos stand in for the
# GitHub ones (a github.com URL rewritten by insteadOf), and a copy of sync.sh
# reads a fixture UPSTREAM.md next to it. HOME and the global git config point
# into the temp dir, so nothing outside it is read or changed.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
fail() { echo "FAIL: $*" >&2; exit 1; }

tmp=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home" GIT_CONFIG_GLOBAL="$tmp/home/.gitconfig" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME" "$tmp/remotes" "$tmp/kit/upstream"
git config --global user.name t
git config --global user.email t@t
git config --global init.defaultBranch main
git config --global url."$tmp/remotes/".insteadOf "https://github.com/"
cp "$root/upstream/sync.sh" "$tmp/kit/upstream/sync.sh"
sync="$tmp/kit/upstream/sync.sh"

# commit <repo> <message> <path>...: writes the message into each path and commits.
commit() {
  local repo="$tmp/remotes/$1" msg=$2; shift 2
  [[ -d "$repo" ]] || git init -q "$repo"
  for p; do mkdir -p "$(dirname "$repo/$p")"; echo "$msg" >>"$repo/$p"; done
  git -C "$repo" add -A
  git -C "$repo" commit -q -m "$msg"
  git -C "$repo" rev-parse --short HEAD
}

# Three sources, each with an adapted file, an unrelated file and later commits.
mp_base=$(commit acme/skills "mp base" skills/eng/review/SKILL.md skills/eng/other/SKILL.md)
commit acme/skills "mp: review tweak" skills/eng/review/SKILL.md >/dev/null
commit acme/skills "mp: unrelated" skills/eng/other/SKILL.md >/dev/null
ps_base=$(commit acme/plugins "ps base" pstack/skills/blast/SKILL.md pstack/agents/sicko.md cursor/x.md)
commit acme/plugins "ps: sicko tweak" pstack/agents/sicko.md >/dev/null
hl_base=$(commit hl/hl "hl base" .claude/agents/locator.md .claude/agents/thoughts.md)
commit hl/hl "hl: locator tweak" .claude/agents/locator.md >/dev/null
commit hl/hl "hl: thoughts tweak" .claude/agents/thoughts.md >/dev/null
quiet_base=$(commit quiet/q "quiet base" kept.md busy.md)
commit quiet/q "quiet: busy tweak" busy.md >/dev/null

cat >"$tmp/kit/upstream/UPSTREAM.md" <<EOF
# Upstream sources

Preamble that mentions acme/skills @ 0000000 in passing.

## acme/skills (MIT) @ $mp_base

| dk skill | Upstream path | Changes |
|---|---|---|
| review | skills/eng/review | as-is |

## acme/plugins pstack (MIT) @ $ps_base

| dk file | Upstream path | Changes |
|---|---|---|
| skills/blast | pstack/skills/blast | trimmed |
| agents/sicko | pstack/agents/sicko.md | trimmed |

## hl/hl (Apache-2.0) @ $hl_base

| dk file | Upstream path | Changes |
|---|---|---|
| agents/locator | .claude/agents/locator.md | trimmed |
| typo | \`.claude/agents/locator.md\`, misspelt.md | as-is |

## quiet/q (MIT) @ $quiet_base

| dk file | Upstream path | Changes |
|---|---|---|
| kept | kept.md | as-is |
EOF

out=$("$sync" 2>&1) || fail "sync.sh exited non-zero: $out"
expect() { grep -qF -- "$1" <<<"$out" || fail "missing \"$1\" in output:
$out"; }
refuse() { ! grep -qF -- "$1" <<<"$out" || fail "unexpected \"$1\" in output:
$out"; }

# Every source is compared against its own recorded commit.
expect "acme/skills $mp_base.."
expect "acme/plugins $ps_base.."
expect "hl/hl $hl_base.."
# Changed adapted files are listed with the commits that touched them.
expect "=== skills/eng/review"
expect "mp: review tweak"
expect "=== pstack/agents/sicko.md"
expect "ps: sicko tweak"
expect "=== .claude/agents/locator.md"
expect "hl: locator tweak"
# A path recorded on two rows is reported once.
[[ $(grep -c "=== .claude/agents/locator.md" <<<"$out") == 1 ]] || fail "locator.md reported more than once:
$out"
# Files the kit did not adapt stay out, even when they changed.
refuse "mp: unrelated"
refuse "hl: thoughts tweak"
refuse "=== pstack/skills/blast"

# A source whose adapted files did not change says so in one line.
[[ $(grep -c "quiet/q" <<<"$out") == 1 ]] || fail "quiet/q should get exactly one line:
$out"
expect "quiet/q $quiet_base.."
grep "quiet/q" <<<"$out" | grep -qF "no changes" || fail "quiet/q line should say no changes:
$out"
# A recorded path that does not exist at the recorded commit is named, not
# silently counted as unchanged.
expect "misspelt.md: not found at $hl_base"

echo "PASS test_sync"
