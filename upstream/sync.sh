#!/usr/bin/env bash
# Shows what mattpocock/skills changed in each vendored skill since the
# commit recorded in UPSTREAM.md. Read-only: it prints diffs, never edits.
#   upstream/sync.sh [path-to-clone]   (default: a fresh clone in a temp dir)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
base=$(grep -m1 -oE 'mattpocock/skills \(MIT\) @ [0-9a-f]+' "$here/UPSTREAM.md" | awk '{print $4}')
clone=${1:-}
if [[ -z "$clone" ]]; then
  clone=$(mktemp -d)
  trap 'rm -rf "$clone"' EXIT
  git clone -q https://github.com/mattpocock/skills "$clone"
fi
git -C "$clone" fetch -q origin
head=$(git -C "$clone" rev-parse --short origin/main)
echo "mattpocock/skills $base..$head"
paths=$(sed -n '/^## mattpocock/,/^## /p' "$here/UPSTREAM.md" | grep -oE 'skills/(engineering|productivity)/[a-z-]+' | sort -u)
changed=0
for p in $paths; do
  if ! git -C "$clone" diff --quiet "$base" origin/main -- "$p"; then
    changed=1
    echo; echo "=== $p"
    git -C "$clone" log --oneline "$base..origin/main" -- "$p"
    git -C "$clone" diff --stat "$base" origin/main -- "$p"
  fi
done
((changed)) || echo "no upstream changes to vendored skills"
echo; echo "Full diff of one skill: git -C <clone> diff $base origin/main -- <path>"
