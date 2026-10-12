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
dirty2=$(worktree app-2 feat/2-dirty)
echo wip >"$ws/app-2/notes.txt"
again4=$(worktree app-4 feat/4-again)
ahead5=$(worktree app-5 feat/5-ahead)
git -C "$ws/app-5" commit -q --allow-empty -m "after the merge"
assets6=$(worktree app-6 verify-assets/6)
behind7=$(worktree app-7 feat/7-behind)
git -C "$ws/app-7" commit -q --allow-empty -m "pushed from elsewhere"
git -C "$ws/app-7" push -q origin feat/7-behind
head7=$(git -C "$ws/app-7" rev-parse HEAD)
git -C "$ws/app-7" reset -q --hard "$behind7"
# feat/8-loose: a local branch whose worktree is gone and whose remote GitHub deleted.
loose8=$(worktree app-8 feat/8-loose)
git -C "$app" worktree remove "$ws/app-8"
git -C "$app" push -q origin --delete feat/8-loose
# Remote-only branches: a base of an open PR, the batch branch, one pushed to after its merge.
main=$(git -C "$app" rev-parse main)
git -C "$app" push -q origin main:refs/heads/feat/10-base main:refs/heads/pre-main
git -C "$app" worktree add -q -b pre-main "$ws/app-pre-main" main
moved11=$(worktree app-11 feat/11-moved)
git -C "$ws/app-11" commit -q --allow-empty -m "pushed after the merge"
git -C "$ws/app-11" push -q origin feat/11-moved
git -C "$app" worktree remove "$ws/app-11"
git -C "$app" branch -q -D feat/11-moved
# pre-master: an integration branch with a merged PR of its own (a batch) and merged PRs into it.
git -C "$app" branch pre-master main
git -C "$app" push -q origin pre-master
echo "[$(pr 11 feat/1-done "$done1" main), $(pr 12 feat/2-dirty "$dirty2" main), $(pr 14 feat/4-again "$again4" main),
  $(pr 16 feat/5-ahead "$ahead5" main), $(pr 17 verify-assets/6 "$assets6" main), $(pr 18 feat/7-behind "$head7" main),
  $(pr 19 feat/8-loose "$loose8" main), $(pr 20 feat/10-base "$main" main), $(pr 22 pre-main "$main" main),
  $(pr 23 feat/11-moved "$moved11" main), $(pr 24 pre-master "$main" main), $(pr 25 feat/13-batched "$main" pre-master)]" \
  >"$fx/acme_app/pr-merged.json"
# A second checkout of acme/app: its remote branches are the same ones, handled once.
git clone -q https://github.com/acme/app.git "$ws/app-copy"
echo "[$(pr 13 feat/3-open "$open3" main), $(pr 15 feat/4-again "$again4" main), $(pr 21 feat/12-next "$main" feat/10-base)]" \
  >"$fx/acme_app/pr-open.json"

# A repo without origin, and one whose PRs gh cannot list (no fixture), each with a worktree.
git init -q "$ws/notes"
git -C "$ws/notes" commit -q --allow-empty -m init
git -C "$ws/notes" worktree add -q -b feat/1-done "$ws/notes-1"
git init -q --bare "$remotes/acme/other.git"
git init -q "$ws/other"
git -C "$ws/other" remote add origin git@github.com:acme/other.git
git -C "$ws/other" commit -q --allow-empty -m init
git -C "$ws/other" worktree add -q -b feat/1-done "$ws/other-1"

# dk-pg databases: issue 1 closed, issue 3 open, one from a checkout that is gone.
printf '%s\t%s\t%s\t%s\n' c1 dk-pg-app-1 "$app" 1 c3 dk-pg-app-3 "$app" 3 c9 dk-pg-gone-9 "$tmp/gone" 9 >"$fx/docker-ps"
echo '{"state":"CLOSED"}' >"$fx/acme_app/issue-1.json"
echo '{"state":"OPEN"}' >"$fx/acme_app/issue-3.json"

state() {
  git -C "$app" worktree list --porcelain
  git -C "$ws/notes" worktree list --porcelain
  git -C "$ws/other" worktree list --porcelain
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
has "$out" "remove worktree $ws/app-7 "
has "$out" "keep worktree $ws/app-2 (feat/2-dirty, PR #12 merged; uncommitted changes)"
has "$out" "keep worktree $ws/app-4 (feat/4-again, PR #14 merged; open PR #15)"
has "$out" "keep worktree $ws/app-5 (feat/5-ahead, PR #16 merged; commits it did not merge)"
lacks "$out" "remove worktree $ws/app-6"
lacks "$out" "verify-assets/6 ("
lacks "$out" "remove branch feat/2-dirty"
lacks "$out" "remove branch feat/4-again"
lacks "$out" "remove branch feat/5-ahead"
has "$out" "remove branch feat/8-loose (PR #19 merged)"
for gone in feat/1-done feat/2-dirty feat/5-ahead feat/7-behind; do has "$out" "remove remote origin/$gone (PR #"; done
has "$out" "keep remote origin/feat/4-again (PR #14 merged; open PR #15)"
has "$out" "keep remote origin/feat/10-base (PR #20 merged; base of open PR #21)"
has "$out" "keep remote origin/feat/11-moved (PR #23 merged; commits it did not merge)"
lacks "$out" "pre-main"
has "$out" "remove database dk-pg-app-1 (issue #1 closed)"
lacks "$out" "dk-pg-app-3"
has "$out" "keep database dk-pg-gone-9 (issue #9; no GitHub checkout at $tmp/gone)"
[[ "$(grep -c '^app ' <<<"$out")" == 1 ]] || fail "repo app listed in more than one group"
lacks "$out" "notes"
has "$out" "other (acme/other)"$'\n'"  branches skipped: gh could not list its PRs"
lacks "$out" "other-1"
lacks "$out" "origin/main"
has "$out" "keep branch pre-master (PR #24 merged; base of PR #25)"
has "$out" "keep remote origin/pre-master (PR #24 merged; base of PR #25)"
[[ "$(grep -c "remove remote origin/feat/1-done " <<<"$out")" == 1 ]] || fail "remote branch listed once per checkout"
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
[[ -d "$ws/notes-1" && -d "$ws/other-1" ]] || fail "worktree of a repo without PRs removed"
[[ ! -e "$ws/app-7" ]] || fail "worktree behind its merged PR still there"
git -C "$app" rev-parse -q --verify refs/heads/pre-master >/dev/null || fail "integration branch pre-master removed"
for kept in app-pre-main:pre-main app-2:feat/2-dirty app-3:feat/3-open app-4:feat/4-again app-5:feat/5-ahead app-6:verify-assets/6; do
  [[ -d "$ws/${kept%%:*}" ]] || fail "worktree ${kept%%:*} removed"
  git -C "$app" rev-parse -q --verify "refs/heads/${kept#*:}" >/dev/null || fail "branch ${kept#*:} removed"
done
[[ "$(cat "$ws/app-2/notes.txt")" == wip ]] || fail "uncommitted file in app-2 lost"
[[ "$(cut -f1 "$fx/docker-ps" | tr '\n' ' ')" == "c3 c9 " ]] || fail "containers left: $(cut -f1 "$fx/docker-ps")"
grep -q '^rm -fv c1$' "$fx/docker.log" || fail "container c1 not removed with its volumes"
git -C "$app" rev-parse -q --verify refs/heads/feat/8-loose >/dev/null && fail "branch feat/8-loose still there"
remote_heads=$(git -C "$remotes/acme/app.git" for-each-ref --format='%(refname:short)' refs/heads | sort | tr '\n' ' ')
[[ "$remote_heads" == "feat/10-base feat/11-moved feat/3-open feat/4-again main pre-main pre-master verify-assets/6 " ]] \
  || fail "remote branches left: $remote_heads"
[[ "$(git -C "$app" rev-parse --abbrev-ref HEAD)" == main ]] || fail "main checkout moved"

out=$("$dkgc" --dry-run --workspace "$ws")
lacks "$out" "remove "
echo "dk-gc: all checks passed"
