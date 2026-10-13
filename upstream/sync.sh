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

# One line per source: "<owner/repo> <commit> <path>...", from each
# "## <owner>/<repo> ... @ <commit>" heading and the Upstream path column
# (comma-separated) of the table under it.
sources() {
  awk '
    function flush() { if (repo != "" && paths != "") print repo, commit, paths }
    /^## / {
      flush(); repo = ""; paths = ""; rows = 0
      if (match($0, / @ [0-9a-f]+$/)) { repo = $2; commit = substr($0, RSTART + 3) }
      next
    }
    repo != "" && /^\|/ {
      if (++rows <= 2) next
      split($0, cell, "|"); n = split(cell[3], p, ",")
      for (i = 1; i <= n; i++) { gsub(/[ `]/, "", p[i]); if (p[i] != "") paths = paths " " p[i] }
    }
    END { flush() }
  ' "$here/UPSTREAM.md"
}

while read -r repo base paths <&3; do
  clone="$dir/$repo"
  if [[ -d "$clone/.git" ]]; then
    git -C "$clone" fetch -q origin
  else
    git clone -q "https://github.com/$repo" "$clone"
  fi
  head=$(git -C "$clone" rev-parse --short refs/remotes/origin/HEAD)
  out=""
  for p in $paths; do
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
echo "Full diff of one path: git -C <clones-dir>/<owner>/<repo> diff <recorded> origin/HEAD -- <path>"
