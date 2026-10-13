#!/usr/bin/env bash
# Merges the kit's user-settings fragment into ~/.claude/settings.json, adds
# the zsh options block to ~/.zshenv, installs the kit's plugins from this
# checkout and adds --isolated to an existing user-scope playwright MCP server.
# A plugin cannot ship permission rules, autoMode settings, shell options or
# MCP arguments, so those travel this way.
#
#   ./bootstrap.sh            show the settings, .zshenv and MCP diffs, write nothing
#   ./bootstrap.sh --apply    back up both files, write them, install plugins,
#                             re-register the playwright server
#
# Objects merge key by key, arrays gain the entries they lack (nothing is
# removed or reordered), scalars from the fragment win. A private overlay at
# ~/.config/dk-agent-kit/private.json (client-specific autoMode.environment,
# for example) is merged last and never lives in this public repo.
set -euo pipefail

repo=$(cd "$(dirname "$0")" && pwd)
settings=${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}
private=${DK_PRIVATE_SETTINGS:-$HOME/.config/dk-agent-kit/private.json}
plugins=(dk-guard dk)

command -v jq >/dev/null || { echo "bootstrap: jq is required" >&2; exit 1; }
# a missing settings file merges as {}; only --apply writes it
current='{}'
[[ -f "$settings" ]] && current=$(cat "$settings")

layers=("$repo/settings/user.fragment.json")
[[ -f "$private" ]] && layers+=("$private")

merged=$(jq -s '
  def merge($a; $b):
    if ($a | type) == "object" and ($b | type) == "object" then
      reduce ($b | keys_unsorted[]) as $k ($a; .[$k] = merge($a[$k]; $b[$k]))
    elif ($a | type) == "array" and ($b | type) == "array" then
      $a + [$b[] as $x | select($a | any(. == $x) | not) | $x]
    elif $b == null then $a
    else $b end;
  reduce .[1:][] as $layer (.[0]; merge(.; $layer))
' <(printf '%s\n' "$current") "${layers[@]}")

if diff -u --label "$settings" --label "$settings (merged)" <(printf '%s\n' "$current") <(printf '%s\n' "$merged"); then
  echo "bootstrap: settings already up to date"
  changed=0
else
  changed=1
fi

# The Bash tool runs zsh, and agents write bash: this block in the zsh
# environment file stops the glob and =word errors that mismatch causes.
zshenv=${ZDOTDIR:-$HOME}/.zshenv
zsh_block='# >>> dk-agent-kit zsh options >>>
# An unmatched glob (--include=*.go) is passed through literally, and a word
# starting with = (echo ====) is not expanded to a command path.
setopt NO_NOMATCH
unsetopt EQUALS
# <<< dk-agent-kit zsh options <<<'
zsh_current=$(cat "$zshenv" 2>/dev/null || true)
# A block written by hand (no marker) counts when it sets both options.
zsh_opt() { grep -Eiq "^[[:space:]]*($1)[[:space:]]*(#.*)?\$" <<<"$zsh_current"; }
if grep -qxF '# >>> dk-agent-kit zsh options >>>' <<<"$zsh_current" ||
  { zsh_opt 'setopt[[:space:]]+no_?nomatch|unsetopt[[:space:]]+nomatch' &&
    zsh_opt 'unsetopt[[:space:]]+equals|setopt[[:space:]]+no_?equals'; }; then
  echo "bootstrap: zsh options already in $zshenv"
  zsh_changed=0
else
  zsh_merged=$zsh_block
  [[ -n "$zsh_current" ]] && zsh_merged=$(printf '%s\n\n%s' "$zsh_current" "$zsh_block")
  diff -u --label "$zshenv" --label "$zshenv (merged)" \
    <(printf '%s\n' "$zsh_current") <(printf '%s\n' "$zsh_merged") || true
  zsh_changed=1
fi

# Without --isolated, two sessions started from one directory share the
# Playwright MCP browser profile and the second gets "Browser is already in
# use". `claude mcp get` shows the server that wins in the current directory,
# so it runs from / where no project or local server shadows the user one; it
# also health-checks the server, the dry run's one side effect. It joins the
# args with spaces, so an arg containing a space would split; the playwright
# args have none.
mcp_changed=0
mcp_field() { sed -n "s/^  $1: //p" <<<"$mcp"; }
mcp_json() {
  jq -cn --arg cmd "$(mcp_field Command)" --arg args "$1" \
    --arg env "$(sed -n '/^  Environment:$/,/^$/s/^    //p' <<<"$mcp")" '
    {type: "stdio", command: $cmd, args: ($args | split(" ") | map(select(. != ""))),
     env: ([$env | split("\n")[] | select(. != "") | capture("^(?<k>[^=]+)=(?<v>.*)$") | {(.k): .v}] | add // {})}'
}
shell_quote() { local q="'\\''"; printf "'%s'" "${1//\'/$q}"; }
if ! command -v claude >/dev/null; then
  echo "bootstrap: no claude CLI on PATH, playwright MCP server not checked"
elif ! mcp=$(cd / && claude mcp get playwright 2>&1); then
  if grep -q '^No MCP server named "playwright"' <<<"$mcp"; then
    echo "bootstrap: no user-scope playwright MCP server, none added"
  else
    printf 'bootstrap: claude mcp get playwright failed, MCP server not checked:\n%s\n' "$mcp"
  fi
elif ! grep -q '^  Scope: User config' <<<"$mcp" || [[ "$(mcp_field Type)" != stdio ]]; then
  echo "bootstrap: the playwright MCP server is not a user-scope stdio server, left as is"
elif [[ -z "$(mcp_field Command)" ]] || ! grep -q '^  Args:' <<<"$mcp"; then
  printf 'bootstrap: no command or args in claude mcp get playwright, left as is:\n%s\n' "$mcp"
elif mcp_args=$(mcp_field Args); [[ " $mcp_args " =~ \ --isolated[\ =] ]]; then
  echo "bootstrap: playwright already runs with --isolated"
else
  diff -u --label "claude mcp get playwright" --label "claude mcp get playwright (merged)" \
    <(printf '  Args: %s\n' "$mcp_args") <(printf '  Args: %s\n' "$mcp_args --isolated") || true
  mcp_old=$(mcp_json "$mcp_args")
  mcp_new=$(mcp_json "$mcp_args --isolated")
  mcp_changed=1
fi

if [[ "${1:-}" != "--apply" ]]; then
  echo
  echo "bootstrap: dry run. --apply writes this and runs:"
  echo "  claude plugin marketplace add $repo"
  for p in "${plugins[@]}"; do echo "  claude plugin install $p@dk-agent-kit"; done
  if ((mcp_changed)); then
    echo "  claude mcp remove playwright -s user"
    echo "  claude mcp add-json -s user playwright $(shell_quote "$mcp_new")"
  fi
  exit 0
fi

if ((changed)); then
  backup=
  if [[ -f "$settings" ]]; then
    backup="$settings.bak-$(date +%Y%m%d-%H%M%S)"
    cp "$settings" "$backup"
  fi
  printf '%s\n' "$merged" > "$settings"
  echo "bootstrap: wrote $settings${backup:+ (backup: $backup)}"
fi

if ((zsh_changed)); then
  if [[ -f "$zshenv" ]]; then
    zsh_backup="$zshenv.bak-$(date +%Y%m%d-%H%M%S)"
    cp "$zshenv" "$zsh_backup"
    echo "bootstrap: backed up $zshenv to $zsh_backup"
  fi
  printf '%s\n' "$zsh_merged" > "$zshenv"
  echo "bootstrap: wrote the zsh options block to $zshenv"
fi

if ! claude plugin marketplace list 2>/dev/null | grep -q 'dk-agent-kit'; then
  claude plugin marketplace add "$repo"
fi
for p in "${plugins[@]}"; do
  claude plugin install "$p@dk-agent-kit"
done

if ((mcp_changed)); then
  echo "bootstrap: re-registering playwright with --isolated; if the add fails, restore it with"
  echo "  claude mcp add-json -s user playwright $(shell_quote "$mcp_old")"
  claude mcp remove playwright -s user
  claude mcp add-json -s user playwright "$mcp_new"
  echo "bootstrap: playwright now runs with --isolated in sessions started from now on"
fi
echo "bootstrap: done. Run /reload-plugins in open sessions."
