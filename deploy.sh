#!/bin/bash
# Merge main into current claude branch and push to trigger CI/CD

set -e

CURRENT=$(git branch --show-current)

if [[ "$CURRENT" != claude/* ]]; then
  echo "Error: not on a claude/* branch (currently on '$CURRENT')"
  exit 1
fi

echo "Fetching latest main..."
git fetch origin main

echo "Merging origin/main into $CURRENT..."
git merge origin/main --no-edit

echo "Pushing $CURRENT..."
git push origin "$CURRENT"

echo "Done. CI/CD triggered on $CURRENT."
