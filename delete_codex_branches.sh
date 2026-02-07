#!/bin/sh
set -eu  # no -o pipefail (dash doesn’t support it)

git fetch --prune origin >/dev/null 2>&1

local_branches=$(git branch --list "codex/*" | sed 's/^[ *]*//')
remote_branches=$(git ls-remote --heads origin "codex/*" | awk '{print $2}' | sed 's#refs/heads/##')

if [ -z "$local_branches" ] && [ -z "$remote_branches" ]; then
  echo "No branches starting with 'codex/' found."
  exit 0
fi

echo "The following branches will be deleted:"
[ -n "$local_branches" ] && echo "\nLocal branches:\n$local_branches"
[ -n "$remote_branches" ] && echo "\nRemote branches:\n$remote_branches"
echo

printf "Are you sure you want to delete these branches? (y/N) "
read confirm
case "$confirm" in
  [Yy]*) ;;
  *) echo "Aborted."; exit 0;;
esac

if [ -n "$local_branches" ]; then
  echo "$local_branches" | xargs -r git branch -D
  echo "✅ Deleted local branches."
fi

if [ -n "$remote_branches" ]; then
  echo "$remote_branches" | xargs -I {} git push origin --delete {}
  echo "✅ Deleted remote branches."
fi

echo "🎯 Done."
