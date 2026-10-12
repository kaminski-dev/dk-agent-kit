#!/usr/bin/env bash
# dk-gc against a fixture workspace: a main checkout whose origin is a local
# bare repo (a github.com URL rewritten by insteadOf), worktrees in every state,
# and stubbed gh and docker that answer from fixture files. HOME and the global
# git config point into the temp dir, so nothing outside it is read or changed.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
dkgc="$root/plugins/dk-guard/bin/dk-gc"
fail() { echo "FAIL: $*" >&2; exit 1; }

tmp=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home" GIT_CONFIG_GLOBAL="$tmp/home/.gitconfig" GIT_CONFIG_NOSYSTEM=1
unset GH_REPO GH_TOKEN GITHUB_TOKEN
mkdir -p "$HOME"
ws="$tmp/workspace" remotes="$tmp/remotes" fx="$tmp/fixture"
export DKGC_FIXTURE="$fx"
mkdir -p "$ws" "$remotes" "$fx/stubs"
git config --global user.name t
git config --global user.email t@t
git config --global init.defaultBranch main
git config --global advice.detachedHead false
git config --global url."$remotes/".insteadOf "https://github.com/"

# gh: answers `pr list -R o/r --state s` and `issue view N -R o/r` from $DKGC_FIXTURE/o_r/.
cat >"$fx/stubs/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >>"$DKGC_FIXTURE/gh.log"
args=("$@") repo= state=
while (($#)); do
  case "$1" in -R|--repo) repo=$2; shift 2 ;; --state) state=$2; shift 2 ;; *) shift ;; esac
done
[[ -n "$repo" ]] || { echo "fixture gh: no -R in: ${args[*]}" >&2; exit 1; }
dir="$DKGC_FIXTURE/${repo/\//_}"
case "${args[0]} ${args[1]}" in
  "pr list") cat "$dir/pr-$state.json" ;;
  "issue view") cat "$dir/issue-${args[2]}.json" ;;
  *) echo "fixture gh: unexpected: ${args[*]}" >&2; exit 1 ;;
esac
EOF
# docker: `ps` prints $DKGC_FIXTURE/docker-ps (id, name, dk.root, dk.issue, tab-separated); `rm` logs and drops ids.
cat >"$fx/stubs/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >>"$DKGC_FIXTURE/docker.log"
ps="$DKGC_FIXTURE/docker-ps"
case "$1" in
  ps) cat "$ps" ;;
  rm) shift
      for a; do
        [[ "$a" == -* ]] && continue
        grep -q "^$a	" "$ps" || { echo "Error: No such container: $a" >&2; exit 1; }
        grep -v "^$a	" "$ps" >"$ps.new" || true
        mv "$ps.new" "$ps"
      done ;;
  *) echo "fixture docker: unexpected: $*" >&2; exit 1 ;;
esac
EOF
chmod +x "$fx/stubs/gh" "$fx/stubs/docker"
export PATH="$fx/stubs:$PATH"
: >"$fx/docker-ps"

# acme/app: the main checkout at $ws/app.
git init -q --bare "$remotes/acme/app.git"
app="$ws/app"
git init -q "$app"
git -C "$app" remote add origin https://github.com/acme/app.git
git -C "$app" commit -q --allow-empty -m init
git -C "$app" push -q origin main
mkdir -p "$fx/acme_app"

# worktree <dir> <branch>: a pushed worktree with one commit; prints its sha.
worktree() {
  git -C "$app" worktree add -q -b "$2" "$ws/$1" main
  git -C "$ws/$1" commit -q --allow-empty -m "work on $2"
  git -C "$ws/$1" push -q origin "$2"
  git -C "$ws/$1" rev-parse HEAD
}
pr() { printf '{"number":%s,"headRefName":"%s","headRefOid":"%s","baseRefName":"%s","isCrossRepository":false}' "$@"; }

done1=$(worktree app-1 feat/1-done)
open3=$(worktree app-3 feat/3-open)
echo "[$(pr 11 feat/1-done "$done1" main)]" >"$fx/acme_app/pr-merged.json"
echo "[$(pr 13 feat/3-open "$open3" main)]" >"$fx/acme_app/pr-open.json"

state() {
  git -C "$app" worktree list --porcelain
  git -C "$app" for-each-ref
  git -C "$remotes/acme/app.git" for-each-ref
  cat "$fx/docker-ps"
  ls "$ws"
}
has() { grep -qF -- "$2" <<<"$1" || fail "output lacks '$2':"$'\n'"$1"; }
lacks() { ! grep -qF -- "$2" <<<"$1" || fail "output has '$2':"$'\n'"$1"; }

# A dry run lists what finished and changes nothing.
before=$(state)
out=$("$dkgc" --dry-run --workspace "$ws")
has "$out" "remove worktree $ws/app-1 "
has "$out" "remove branch feat/1-done "
has "$out" "PR #11 merged"
lacks "$out" "feat/3-open"
lacks "$out" "app-3"
has "$out" "Dry run: nothing changed."
[[ "$(state)" == "$before" ]] || fail "dry run changed something"

# Without a yes on stdin, nothing changes.
out=$("$dkgc" --workspace "$ws" </dev/null)
has "$out" "Nothing changed."
[[ "$(state)" == "$before" ]] || fail "an unconfirmed run changed something"

# After confirmation it removes what it listed, and only that.
listed=$("$dkgc" --dry-run --workspace "$ws" | grep '^  remove ')
out=$(echo y | "$dkgc" --workspace "$ws")
[[ "$(grep '^  remove ' <<<"$out")" == "$listed" ]] || fail "confirmed run listed other items than the dry run"
[[ ! -e "$ws/app-1" ]] || fail "merged worktree app-1 still there"
git -C "$app" rev-parse -q --verify refs/heads/feat/1-done >/dev/null && fail "branch feat/1-done still there"
[[ -d "$ws/app-3" ]] || fail "worktree with an open PR removed"
git -C "$app" rev-parse -q --verify refs/heads/feat/3-open >/dev/null || fail "branch with an open PR removed"
[[ "$(git -C "$app" rev-parse --abbrev-ref HEAD)" == main ]] || fail "main checkout moved"

out=$("$dkgc" --dry-run --workspace "$ws")
lacks "$out" "remove "
echo "dk-gc: all checks passed"
