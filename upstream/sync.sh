#!/usr/bin/env bash
# Shows what each upstream source changed in the files the kit adapted, since
# the commit recorded for it in UPSTREAM.md. Read-only: it prints, never edits.
#   upstream/sync.sh [clones-dir]   (default: fresh clones in a temp dir)
# A clones dir keeps <owner>/<repo> clones between runs: missing ones are
# cloned, present ones fetched.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
dir=${1:-}
if [[ -z "$dir" ]]; then
  dir=$(mktemp -d)
  trap 'rm -rf "$dir"' EXIT
fi

# One line per source: "<owner/repo> <commit> <branch> <path>...", from each
# "## <owner>/<repo> ... @ <commit>[..<branch>]" heading (HEAD when it names no
# branch) and the Upstream path column (comma-separated, each listed once) of
# the table under it.
sources() {
  awk '
    function flush() { if (repo != "" && paths != "") print repo, commit, branch, paths }
    /^## / {
      flush(); repo = ""; paths = ""; rows = 0; split("", seen)
      if (match($0, / @ [0-9a-f]+(\.\.[^ ]+)?$/)) {
        repo = $2; commit = substr($0, RSTART + 3); branch = "HEAD"
        if (i = index(commit, "..")) { branch = substr(commit, i + 2); commit = substr(commit, 1, i - 1) }
      }
      next
    }
    repo != "" && /^\|/ {
      if (++rows <= 2) next
      split($0, cell, "|"); n = split(cell[3], p, ",")
      for (i = 1; i <= n; i++) { gsub(/[ `]/, "", p[i]); if (p[i] != "" && !seen[p[i]]++) paths = paths " " p[i] }
    }
    END { flush() }
  ' "$here/UPSTREAM.md"
}

while read -r repo base branch paths <&3; do
  clone="$dir/$repo"
  if [[ -d "$clone/.git" ]]; then
    # Without --prune a branch deleted upstream keeps comparing as it last was.
    git -C "$clone" fetch -q --prune origin
    # Fetch neither recreates a missing origin/HEAD (git before 2.48) nor
    # moves an existing one when upstream changes its default branch.
    git -C "$clone" remote set-head origin --auto >/dev/null
  else
    git clone -q "https://github.com/$repo" "$clone"
  fi
  if ! head=$(git -C "$clone" rev-parse --verify -q --short "refs/remotes/origin/$branch"); then
    echo "$repo $base..$branch: branch not found upstream"
    continue
  fi
  out=""
  for p in $paths; do
    if ! git -C "$clone" cat-file -e "$base:$p" 2>/dev/null; then
      out+=$'\n'"$p: not found at $base"$'\n'
      continue
    fi
    git -C "$clone" diff --quiet "$base" "$head" -- "$p" && continue
    out+=$'\n'"=== $p"$'\n'
    out+=$(git -C "$clone" log --oneline "$base..$head" -- "$p")$'\n'
    out+=$(git -C "$clone" diff --stat "$base" "$head" -- "$p")$'\n'
  done
  if [[ -z "$out" ]]; then
    echo "$repo $base..$head: no changes to adapted files"
  else
    echo "$repo $base..$head"
    printf '%s\n' "$out"
  fi
done 3< <(sources)
if [[ -n "${1:-}" ]]; then
  echo "Full diff of one path: git -C $dir/<owner>/<repo> diff <recorded>..<head> -- <path>, with <recorded>..<head> as printed above"
else
  echo "Full diff of one path: rerun as upstream/sync.sh <clones-dir> to keep the clones, then git -C <clones-dir>/<owner>/<repo> diff <recorded>..<head> -- <path>, with <recorded>..<head> as printed above"
fi
