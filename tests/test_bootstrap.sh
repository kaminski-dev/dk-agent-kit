#!/usr/bin/env bash
# bootstrap.sh against fixture settings: merge keeps existing values, adds
# missing array entries once, never duplicates, and a second run is a no-op.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

cat > "$tmp/settings.json" <<'EOF'
{
  "model": "opus",
  "permissions": { "defaultMode": "auto", "deny": ["Bash(git push * main)", "Bash(rm -rf /)"] },
  "autoMode": { "soft_deny": ["$defaults", "Bash(psql:*) needs confirmation"], "environment": ["kept as is"] }
}
EOF
echo '{"autoMode": {"environment": ["private line"]}}' > "$tmp/private.json"

# a test HOME, so the zsh step never reaches the real ~/.zshenv
mkdir -p "$tmp/home"
printf 'export PATH="$HOME/.bun/bin:$PATH"\n' > "$tmp/home/.zshenv"
cp "$tmp/home/.zshenv" "$tmp/zshenv.orig"
unset ZDOTDIR
export HOME="$tmp/home" CLAUDE_SETTINGS="$tmp/settings.json" DK_PRIVATE_SETTINGS="$tmp/private.json"
out=$("$root/bootstrap.sh")
grep -q '^+.*docker container prune' <<<"$out" || fail "dry run shows no added deny rule"
[[ "$(jq -r .model "$tmp/settings.json")" == opus ]] || fail "dry run changed the file"
grep -q '^+setopt NO_NOMATCH' <<<"$out" || fail "dry run shows no zsh block"
cmp -s "$tmp/home/.zshenv" "$tmp/zshenv.orig" || fail "dry run changed .zshenv"

# apply without touching the real plugin registry: stub the claude CLI
mkdir -p "$tmp/bin"
printf '#!/bin/sh\necho "claude $*" >> "%s/claude.log"\n' "$tmp" > "$tmp/bin/claude"
chmod +x "$tmp/bin/claude"
PATH="$tmp/bin:$PATH" "$root/bootstrap.sh" --apply >/dev/null

s="$tmp/settings.json"
[[ "$(jq -r .model "$s")" == opus ]] || fail "model lost"
[[ "$(jq -r .permissions.defaultMode "$s")" == auto ]] || fail "defaultMode lost"
[[ "$(jq '[.permissions.deny[] | select(. == "Bash(git push * main)")] | length' "$s")" == 1 ]] || fail "deny entry duplicated"
jq -e '.permissions.deny | index("Bash(rm -rf /)")' "$s" >/dev/null || fail "existing deny entry lost"
jq -e '.permissions.deny | index("Bash(docker container prune *)")' "$s" >/dev/null || fail "fragment deny missing"
[[ "$(jq -r '.autoMode.hard_deny[0]' "$s")" == '$defaults' ]] || fail "hard_deny must start with \$defaults"
[[ "$(jq -c .autoMode.soft_deny "$s")" == '["$defaults","Bash(psql:*) needs confirmation"]' ]] || fail "soft_deny changed"
[[ "$(jq -c .autoMode.environment "$s")" == '["kept as is","private line"]' ]] || fail "private overlay not merged"
grep -q "plugin install dk-guard@dk-agent-kit" "$tmp/claude.log" || fail "plugin not installed"
ls "$tmp"/settings.json.bak-* >/dev/null || fail "no backup written"
z="$tmp/home/.zshenv"
head -1 "$z" | grep -q '.bun/bin' || fail "existing .zshenv line lost"
[[ "$(grep -c '^# >>> dk-agent-kit zsh options >>>$' "$z")" == 1 ]] || fail "zsh block marker not written once"
grep -qx 'setopt NO_NOMATCH' "$z" && grep -qx 'unsetopt EQUALS' "$z" || fail "zsh options missing"
cmp -s "$(ls "$z".bak-* | head -1)" "$tmp/zshenv.orig" || fail "no .zshenv backup written"

out=$(PATH="$tmp/bin:$PATH" "$root/bootstrap.sh")
grep -q "already up to date" <<<"$out" || fail "second run not idempotent"
cp "$z" "$tmp/zshenv.applied"
PATH="$tmp/bin:$PATH" "$root/bootstrap.sh" --apply >/dev/null
cmp -s "$z" "$tmp/zshenv.applied" || fail "second --apply changed .zshenv"
echo "bootstrap: all checks passed"
