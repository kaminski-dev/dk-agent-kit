#!/usr/bin/env bash
# dk-assets against a local bare repo standing in for origin (a github.com URL
# rewritten by insteadOf): the pushed verify-assets/<N> tree, the printed SHA
# and URLs, a rerun replacing the branch, and the refusals. HOME and the global
# git config point into the temp dir, so nothing outside it is read or changed.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
dkassets="$root/plugins/dk-guard/bin/dk-assets"
fail() { echo "FAIL: $*" >&2; exit 1; }

tmp=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home" GIT_CONFIG_GLOBAL="$tmp/home/.gitconfig" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME"
git config --global user.name t
git config --global user.email t@t
git config --global init.defaultBranch main
git config --global url."$tmp/remotes/".insteadOf "https://github.com/"

origin="$tmp/remotes/acme/app.git"
git init -q --bare "$origin"
app="$tmp/app"
git init -q "$app"
git -C "$app" remote add origin https://github.com/acme/app.git
git -C "$app" commit -q --allow-empty -m init
git -C "$app" push -q origin main

# The session's scratch directory, as Claude Code lays it out.
export CLAUDE_CODE_SESSION_ID=0f1e2d3c-test
shots="$tmp/claude-501/-proj/$CLAUDE_CODE_SESSION_ID/scratchpad/31/shots"
mkdir -p "$shots"
printf 'png a' >"$shots/before.png"
printf 'png b' >"$shots/after.png"
printf 'png c' >"$shots/fixed.png"
cd "$app"

remote_sha() { git -C "$origin" rev-parse -q --verify "refs/heads/verify-assets/$1" || true; }
tree_of() { git -C "$origin" ls-tree "$1" | awk '{print $4}' | sort | tr '\n' ' '; }

# A push prints the commit SHA, then one embeddable URL per file in argument order.
out=$("$dkassets" push 31 "$shots/before.png" "$shots/after.png")
sha=$(sed -n 1p <<<"$out")
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || fail "first line is not a commit SHA: $out"
[[ "$(remote_sha 31)" == "$sha" ]] || fail "origin's verify-assets/31 is not the printed SHA"
[[ "$(sed -n '2,$p' <<<"$out")" == "https://github.com/acme/app/blob/$sha/before.png?raw=true
https://github.com/acme/app/blob/$sha/after.png?raw=true" ]] || fail "URLs: $out"
[[ "$(tree_of "$sha")" == "after.png before.png " ]] || fail "tree: $(tree_of "$sha")"
[[ "$(git -C "$origin" show "$sha:before.png")" == "png a" ]] || fail "before.png content differs"
[[ "$(git -C "$origin" rev-list --count "$sha")" == 1 ]] || fail "commit is not an orphan"

# A rerun for the same issue replaces the branch: the old files are gone.
out=$("$dkassets" push 31 "$shots/fixed.png")
sha2=$(sed -n 1p <<<"$out")
[[ "$sha2" != "$sha" && "$(remote_sha 31)" == "$sha2" ]] || fail "rerun did not replace verify-assets/31"
[[ "$(tree_of "$sha2")" == "fixed.png " ]] || fail "rerun tree: $(tree_of "$sha2")"
[[ "$(git -C "$origin" rev-list --count "$sha2")" == 1 ]] || fail "rerun commit is not an orphan"

# A missing file fails before anything is pushed, and names the file.
if err=$("$dkassets" push 31 "$shots/fixed.png" "$shots/missing.png" 2>&1); then fail "missing file accepted: $err"; fi
grep -qxF "dk-assets: no such file: $shots/missing.png" <<<"$err" || fail "error does not name the missing file: $err"
[[ "$(remote_sha 31)" == "$sha2" ]] || fail "a failed run changed verify-assets/31"

# Files outside the session's scratch directory are refused: one in the repo tree,
# a symlink in scratch pointing there, another session's scratch, and any file when
# no session is known.
printf 'secret' >"$app/config.png"
ln -s "$app/config.png" "$shots/link.png"
other="$tmp/claude-501/-proj/another-session/scratchpad/31"
mkdir -p "$other" && printf 'png o' >"$other/other.png"
for f in "$app/config.png" "$shots/link.png" "$other/other.png" "$shots/../../../../../../app/config.png"; do
  if err=$("$dkassets" push 32 "$f" 2>&1); then fail "file outside scratch accepted: $f"; fi
  grep -qF "dk-assets: outside this session's scratch directory: $f" <<<"$err" || fail "refusal for $f: $err"
done
mkdir -p "$shots/again" && printf 'png a2' >"$shots/again/before.png" && printf 'x' >"$shots/before (1).png"
if err=$("$dkassets" push 32 "$shots/before.png" "$shots/again/before.png" 2>&1); then fail "two files named before.png accepted"; fi
grep -qxF "dk-assets: two files named before.png; the branch holds them flat" <<<"$err" || fail "duplicate name: $err"
# A name the URL cannot carry is refused with the characters allowed and what to do.
if err=$("$dkassets" push 32 "$shots/before (1).png" 2>&1); then fail "a name the URL cannot carry was accepted"; fi
grep -qxF "dk-assets: rename 'before (1).png': a file name takes only letters, digits, '.', '_' and '-', so its URL needs no escaping" <<<"$err" || fail "name refusal: $err"
"$dkassets" push "32:main" "$shots/fixed.png" >/dev/null 2>&1 && fail "an issue that is not a number was accepted"
if err=$(env -u CLAUDE_CODE_SESSION_ID "$dkassets" push 32 "$shots/fixed.png" 2>&1); then fail "accepted without a session"; fi
[[ -z "$(remote_sha 32)" ]] || fail "a refused run pushed verify-assets/32"

# A push origin rejects fails with origin's reason and leaves the branch as it was.
printf '#!/bin/sh\necho "no pushes today" >&2\nexit 1\n' >"$origin/hooks/pre-receive"
chmod +x "$origin/hooks/pre-receive"
if err=$("$dkassets" push 31 "$shots/before.png" 2>&1); then fail "rejected push reported success: $err"; fi
grep -qF "no pushes today" <<<"$err" || fail "origin's reason missing: $err"
grep -qxF "dk-assets: origin rejected the push to verify-assets/31" <<<"$err" || fail "no rejection line: $err"
[[ "$(remote_sha 31)" == "$sha2" ]] || fail "a rejected push changed verify-assets/31"

echo "dk-assets: all checks passed"
