#!/usr/bin/env bash
# Merges the kit's user-settings fragment into ~/.claude/settings.json, adds
# the zsh options block to ~/.zshenv and installs the kit's plugins from this
# checkout. A plugin cannot ship permission rules, autoMode settings or shell
# options, so those travel this way.
#
#   ./bootstrap.sh            show the settings and .zshenv diffs, change nothing
#   ./bootstrap.sh --apply    back up both files, write them, install plugins
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

if [[ "${1:-}" != "--apply" ]]; then
  echo
  echo "bootstrap: dry run. --apply writes this and runs:"
  echo "  claude plugin marketplace add $repo"
  for p in "${plugins[@]}"; do echo "  claude plugin install $p@dk-agent-kit"; done
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
echo "bootstrap: done. Run /reload-plugins in open sessions."
