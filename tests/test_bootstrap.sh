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
  "permissions": { "defaultMode": "auto", "deny": ["Bash(git push * main)", "Bash(rm -rf /)"],
                   "allow": ["Bash(npm test)", "Bash(git push -u origin HEAD)"] },
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

# A claude stub on PATH for every run, so none reaches the real claude CLI or
# ~/.claude.json. It logs each call and keeps the playwright server in
# $tmp/mcp.json: `mcp get` prints it the way claude 2.1 does, `remove` and
# `add-json` change it.
mkdir -p "$tmp/bin"
cat > "$tmp/bin/claude" <<EOF
#!/usr/bin/env bash
echo "claude \$*" >> "$tmp/claude.log"
state="$tmp/mcp.json"
case "\$1 \$2" in
  "mcp get")
    [[ -f "\$state" ]] || { echo "No MCP server named \\"\$3\\"."; exit 1; }
    jq -r '"\(.name):", "  Scope: \(.scope // "User config (available in all your projects)")", "  Status: ✔ Connected",
      "  Type: stdio", "  Command: \(.command)", "  Args: \(.args | join(" "))", "  Environment:",
      (.env // {} | to_entries[] | "    \(.key)=\(.value)"), "",
      "To remove this server, run: claude mcp remove \(.name) -s user"' "\$state" ;;
  "mcp remove") rm -f "\$state" ;;
  "mcp add-json") jq --arg n "\$5" '. + {name: \$n}' <<<"\$6" > "\$state" ;;
esac
EOF
chmod +x "$tmp/bin/claude"
export PATH="$tmp/bin:$PATH"
mcp_writes() { grep -cE '^claude mcp (remove|add)' "$tmp/claude.log" || true; }
echo '{"name":"playwright","command":"npx","args":["-y","@playwright/mcp@latest"],"env":{"PW_TEST":"a=b"}}' > "$tmp/mcp.json"

out=$("$root/bootstrap.sh")
grep -q '^+.*docker container prune' <<<"$out" || fail "dry run shows no added deny rule"
[[ "$(jq -r .model "$tmp/settings.json")" == opus ]] || fail "dry run changed the file"
grep -q '^+setopt NO_NOMATCH' <<<"$out" || fail "dry run shows no zsh block"
cmp -s "$tmp/home/.zshenv" "$tmp/zshenv.orig" || fail "dry run changed .zshenv"
grep -q '^claude mcp get playwright$' "$tmp/claude.log" || fail "dry run did not ask the stub for the playwright server"
grep -qx -- '+  Args: -y @playwright/mcp@latest --isolated' <<<"$out" || fail "dry run shows no --isolated change: $out"
[[ "$(mcp_writes)" == 0 ]] || fail "dry run changed the MCP server: $(cat "$tmp/claude.log")"
! grep -q 'a=b' <<<"$out" || fail "dry run printed an MCP env value: $out"

out=$("$root/bootstrap.sh" --apply)
! grep -q 'a=b' <<<"$out" || fail "--apply printed an MCP env value: $out"
mcp_bak=$(ls "$tmp"/playwright-mcp.json.bak-*) || fail "--apply kept no copy of the old MCP server"
[[ "$(jq -c '[.args, .env]' "$mcp_bak")" == '[["-y","@playwright/mcp@latest"],{"PW_TEST":"a=b"}]' ]] || fail "MCP backup is not the old server: $(cat "$mcp_bak")"
[[ -n "$(find "$mcp_bak" -perm 600)" ]] || fail "MCP backup is not mode 600: $(ls -l "$mcp_bak")"
grep -qF "$mcp_bak" <<<"$out" || fail "--apply does not name the MCP backup: $out"

s="$tmp/settings.json"
[[ "$(jq -r .model "$s")" == opus ]] || fail "model lost"
[[ "$(jq -r .permissions.defaultMode "$s")" == auto ]] || fail "defaultMode lost"
[[ "$(jq '[.permissions.deny[] | select(. == "Bash(git push * main)")] | length' "$s")" == 1 ]] || fail "deny entry duplicated"
jq -e '.permissions.deny | index("Bash(rm -rf /)")' "$s" >/dev/null || fail "existing deny entry lost"
jq -e '.permissions.deny | index("Bash(docker container prune *)")' "$s" >/dev/null || fail "fragment deny missing"
allow='["Bash(npm test)","Bash(git push -u origin HEAD)","Bash(dk-assets push *)","Bash(git push)"]'
[[ "$(jq -c .permissions.allow "$s")" == "$allow" ]] || fail "allow rules not merged once: $(jq -c .permissions.allow "$s")"
[[ "$(jq -r '.autoMode.hard_deny[0]' "$s")" == '$defaults' ]] || fail "hard_deny must start with \$defaults"
[[ "$(jq -c .autoMode.soft_deny "$s")" == '["$defaults","Bash(psql:*) needs confirmation"]' ]] || fail "soft_deny changed"
[[ "$(jq -c .autoMode.environment "$s")" == '["kept as is","private line"]' ]] || fail "private overlay not merged"
grep -q "plugin install dk-guard@dk-agent-kit" "$tmp/claude.log" || fail "plugin not installed"
grep -E '^claude mcp (remove|add)' "$tmp/claude.log" > "$tmp/mcp.log" || true
[[ "$(sed -n 1p "$tmp/mcp.log")" == 'claude mcp remove playwright -s user' ]] || fail "--apply did not remove the user-scope server first: $(cat "$tmp/mcp.log")"
grep -q '^claude mcp add-json -s user playwright ' <(sed -n 2p "$tmp/mcp.log") || fail "--apply did not add the server back at user scope: $(cat "$tmp/mcp.log")"
[[ "$(wc -l < "$tmp/mcp.log")" -eq 2 ]] || fail "--apply ran more MCP changes than remove and add: $(cat "$tmp/mcp.log")"
[[ "$(jq -c '[.command, .args, .env]' "$tmp/mcp.json")" == '["npx",["-y","@playwright/mcp@latest","--isolated"],{"PW_TEST":"a=b"}]' ]] ||
  fail "re-registered server lost its command, args or env: $(cat "$tmp/mcp.json")"
ls "$tmp"/settings.json.bak-* >/dev/null || fail "no backup written"
z="$tmp/home/.zshenv"
head -1 "$z" | grep -q '.bun/bin' || fail "existing .zshenv line lost"
[[ "$(grep -c '^# >>> dk-agent-kit zsh options >>>$' "$z")" == 1 ]] || fail "zsh block marker not written once"
grep -qx 'setopt NO_NOMATCH' "$z" && grep -qx 'unsetopt EQUALS' "$z" || fail "zsh options missing"
cmp -s "$(ls "$z".bak-* | head -1)" "$tmp/zshenv.orig" || fail "no .zshenv backup written"

: > "$tmp/claude.log"
out=$("$root/bootstrap.sh")
grep -q "already up to date" <<<"$out" || fail "second run not idempotent"
grep -q "playwright already runs with --isolated" <<<"$out" || fail "second run does not say the server is isolated: $out"
cp "$z" "$tmp/zshenv.applied"
"$root/bootstrap.sh" --apply >/dev/null
[[ "$(mcp_writes)" == 0 ]] || fail "second run changed the MCP server: $(cat "$tmp/claude.log")"

# a local-scope server shadows the user one: left as is
echo '{"name":"playwright","scope":"Local config (private to you in this project)","command":"npx","args":["-y","@playwright/mcp@latest"]}' > "$tmp/mcp.json"
: > "$tmp/claude.log"
out=$("$root/bootstrap.sh" --apply)
grep -q "not a user-scope stdio server, left as is" <<<"$out" || fail "local-scope run does not say so: $out"
[[ "$(mcp_writes)" == 0 ]] || fail "local-scope run changed the MCP server: $(cat "$tmp/claude.log")"
cmp -s "$z" "$tmp/zshenv.applied" || fail "second --apply changed .zshenv"
[[ "$(jq -c .permissions.allow "$s")" == "$allow" ]] || fail "second --apply changed the allow rules"

# a hand-written block without the marker
mkdir -p "$tmp/home2"
printf '# Agent-friendly zsh\nsetopt NO_NOMATCH\nunsetopt EQUALS\n' > "$tmp/home2/.zshenv"
cp "$tmp/home2/.zshenv" "$tmp/zshenv2.orig"
# and no playwright server: bootstrap says so and never adds one
rm "$tmp/mcp.json"
: > "$tmp/claude.log"
out=$(HOME="$tmp/home2" "$root/bootstrap.sh" --apply)
grep -q "no user-scope playwright MCP server" <<<"$out" || fail "no-server run does not say so: $out"
[[ "$(mcp_writes)" == 0 ]] || fail "no-server run changed the MCP servers: $(cat "$tmp/claude.log")"
cmp -s "$tmp/home2/.zshenv" "$tmp/zshenv2.orig" || fail "hand-written zsh options duplicated"
# neither file yet: the dry run writes nothing, --apply creates both, the block at the top of .zshenv
mkdir -p "$tmp/home3/.claude"
s3="$tmp/home3/.claude/settings.json"
HOME="$tmp/home3" CLAUDE_SETTINGS="$s3" "$root/bootstrap.sh" >/dev/null
[[ ! -e "$s3" ]] || fail "dry run created the settings file"
[[ ! -e "$tmp/home3/.zshenv" ]] || fail "dry run created .zshenv"
HOME="$tmp/home3" CLAUDE_SETTINGS="$s3" "$root/bootstrap.sh" --apply >/dev/null
jq -e '.permissions.deny | index("Bash(docker container prune *)")' "$s3" >/dev/null || fail "--apply did not create the settings"
[[ "$(head -1 "$tmp/home3/.zshenv")" == '# >>> dk-agent-kit zsh options >>>' ]] || fail "new .zshenv does not start with the block: $(head -3 "$tmp/home3/.zshenv")"
echo "bootstrap: all checks passed"
