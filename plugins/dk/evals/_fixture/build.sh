#!/usr/bin/env bash
# Builds an eval workspace in the current directory, which `claude plugin eval --scaffold`
# makes $HOME/cwd. usage: build.sh <repo dir under _fixture> <issues state file> [branch patch]
#
# The workspace gets the repo (main and pre-main, origin a bare repo beside it), the
# tracker stand-in's state in .tracker/, and .bin/ first on PATH through the temp HOME's
# shell rc: .bin/gh is the stand-in, so no call reaches GitHub, and .bin/git* call git by
# absolute path, because the macOS sandbox resolves plain git to the xcrun shim, which
# cannot run there. With a patch, a fix/<N>-* branch carrying it is checked out.
set -euo pipefail
F=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WS=$PWD
repo=$1 issues=$2 patch=${3:-}

git=$(command -v git)
if [ "$(uname)" = Darwin ] && [ "$git" = /usr/bin/git ]; then git=$(xcrun --find git); fi
exec_path=$("$git" --exec-path)
mkdir -p .bin .tracker
cp "$F/bin/gh" .bin/gh
printf '#!/bin/sh\nexec "%s" "$@"\n' "$git" > .bin/git
for t in git-receive-pack git-upload-pack git-upload-archive; do
  printf '#!/bin/sh\nexec "%s/%s" "$@"\n' "$exec_path" "$t" > ".bin/$t"
done
chmod +x .bin/*
for rc in "$HOME/.bashrc" "$HOME/.zshenv"; do
  printf 'export PATH="%s/.bin:$PATH"\n' "$WS" >> "$rc"
done
PATH="$WS/.bin:$PATH"

cp "$F/issues/$issues.json" .tracker/state.json
num=${issues%%-*}
[ -f "$F/acceptance-$num.py" ] && cp "$F/acceptance-$num.py" .tracker/acceptance.py

git init -q --bare origin.git
cp -R "$F/$repo" "$repo"
cd "$repo"
git init -q -b main
git config user.name "Eval Agent"
git config user.email eval@example.com
git add -A
git commit -qm "Initial import"
git branch pre-main
git remote add origin ../origin.git
git push -q origin main pre-main
git fetch -q origin
if [ -n "$patch" ]; then
  git checkout -q -b "fix/$num-${patch%.patch}" origin/pre-main
  git apply "$F/$patch"
  git add -A
  git commit -qm "$(head -1 "$F/$patch.msg")"
  git push -q origin HEAD
fi
