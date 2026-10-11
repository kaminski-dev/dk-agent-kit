#!/usr/bin/env bash
# Merges the kit's user-settings fragment into ~/.claude/settings.json and
# installs the kit's plugins from this checkout. A plugin cannot ship
# permission rules or autoMode settings, so those travel this way.
#
#   ./bootstrap.sh            show the settings diff, change nothing
#   ./bootstrap.sh --apply    back up settings.json, write the merge, install plugins
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
[[ -f "$settings" ]] || echo '{}' > "$settings"

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
' "$settings" "${layers[@]}")

if diff -u --label "$settings" --label "$settings (merged)" "$settings" <(printf '%s\n' "$merged"); then
  echo "bootstrap: settings already up to date"
  changed=0
else
  changed=1
fi

if [[ "${1:-}" != "--apply" ]]; then
  echo
  echo "bootstrap: dry run. --apply writes this and runs:"
  echo "  claude plugin marketplace add $repo"
  for p in "${plugins[@]}"; do echo "  claude plugin install $p@dk-agent-kit"; done
  exit 0
fi

if ((changed)); then
  backup="$settings.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$settings" "$backup"
  printf '%s\n' "$merged" > "$settings"
  echo "bootstrap: wrote $settings (backup: $backup)"
fi

if ! claude plugin marketplace list 2>/dev/null | grep -q 'dk-agent-kit'; then
  claude plugin marketplace add "$repo"
fi
for p in "${plugins[@]}"; do
  claude plugin install "$p@dk-agent-kit"
done
echo "bootstrap: done. Run /reload-plugins in open sessions."
