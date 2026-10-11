#!/usr/bin/env bash
# dk-pg against a real Docker: two issues at once on different ports, a second
# `up` reuses the running database, `down` leaves nothing behind, and two
# checkouts with the same directory name keep apart. Runs from throwaway repos
# so their labels match no real container. Skips when no Docker daemon answers.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
dkpg="$root/plugins/dk-guard/bin/dk-pg"
fail() { echo "FAIL: $*" >&2; exit 1; }

docker info >/dev/null 2>&1 || { echo "dk-pg: skipped, no Docker daemon"; exit 0; }

tmp=$(mktemp -d)
repo="$tmp/dkpg-test-$$"
one="$tmp/one/app" two="$tmp/two/app"
a="t$$a" b="t$$b" c="t$$c"
cleanup() {
  (cd "$repo" 2>/dev/null && { "$dkpg" down "$a"; "$dkpg" down "$b"; }) >/dev/null 2>&1 || true
  for r in "$one" "$two"; do (cd "$r" 2>/dev/null && "$dkpg" down "$c") >/dev/null 2>&1 || true; done
  rm -rf "$tmp"
}
trap cleanup EXIT
volumes=$(docker volume ls -q | wc -l)
git init -q "$repo"
cd "$repo"

url_a=$("$dkpg" up "$a")
url_b=$("$dkpg" up "$b" --db app)
[[ "$url_a" =~ ^postgres://postgres:postgres@127\.0\.0\.1:[0-9]+/postgres\?sslmode=disable$ ]] || fail "url a: $url_a"
[[ "$url_b" =~ ^postgres://postgres:postgres@127\.0\.0\.1:[0-9]+/app\?sslmode=disable$ ]] || fail "url b: $url_b"
for issue in "$a" "$b"; do
  fs=$(docker exec "$(docker ps -q --filter "label=dk.issue=$issue")" sh -c 'df -P "$PGDATA" | tail -1 | cut -d" " -f1')
  [[ "$fs" == tmpfs ]] || fail "issue $issue keeps its data on $fs, not tmpfs"
done
port() { sed -E 's/.*:([0-9]+)\/.*/\1/' <<<"$1"; }
[[ "$(port "$url_a")" != "$(port "$url_b")" ]] || fail "both issues on port $(port "$url_a")"

if command -v psql >/dev/null; then
  [[ "$(psql "$url_a" -tAc 'select 1')" == 1 ]] || fail "issue a does not accept connections"
  [[ "$(psql "$url_b" -tAc 'select current_database()')" == app ]] || fail "issue b is not database app"
fi

[[ "$("$dkpg" up "$a")" == "$url_a" ]] || fail "second up for a changed the url"
[[ "$(docker ps -aq --filter "label=dk.issue=$a" | wc -l | tr -d ' ')" == 1 ]] || fail "second up started another container"
[[ "$("$dkpg" url "$a")" == "$url_a" ]] || fail "url a differs from up"
[[ "$("$dkpg" url "$b")" == "$url_b" ]] || fail "url b differs from up"

"$dkpg" down "$a" >/dev/null
[[ -z "$(docker ps -aq --filter "label=dk.issue=$a")" ]] || fail "container for a left behind"
[[ "$("$dkpg" url "$b")" == "$url_b" ]] || fail "down a touched b"
"$dkpg" url "$a" >/dev/null 2>&1 && fail "url a still answers after down"
"$dkpg" up "$a" --db 'a b/c' >/dev/null 2>&1 && fail "up took a database name the URL cannot carry"
"$dkpg" down "$b" >/dev/null
[[ -z "$(docker ps -aq --filter "label=dk.issue=$b")" ]] || fail "container for b left behind"
"$dkpg" down "$b" >/dev/null || fail "down twice is not a no-op"

git init -q "$one"; git init -q "$two"
url_one=$(cd "$one" && "$dkpg" up "$c")
url_two=$(cd "$two" && "$dkpg" up "$c")
[[ "$url_one" != "$url_two" ]] || fail "two checkouts named app share one database"
(cd "$one" && "$dkpg" down "$c") >/dev/null
[[ "$(cd "$two" && "$dkpg" url "$c")" == "$url_two" ]] || fail "down in one checkout removed the other's database"
(cd "$two" && "$dkpg" down "$c") >/dev/null
[[ -z "$(docker ps -aq --filter "label=dk.issue=$c")" ]] || fail "container for c left behind"
[[ "$(docker volume ls -q | wc -l)" == "$volumes" ]] || fail "volumes left behind"
echo "dk-pg: all checks passed"
