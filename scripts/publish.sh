#!/usr/bin/env bash
# Publish the local lemonade-cashier repo to GitHub.
#
# Idempotent: if the repo already exists, it just sets the remote and
# pushes. Requires `gh` authenticated (`gh auth login`).

set -euo pipefail

REPO_NAME="${REPO_NAME:-lemonade-cashier}"
VISIBILITY="${VISIBILITY:-private}"   # change to --public if you want
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$REPO_DIR"

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI not installed. install with: sudo apt install gh" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "error: gh is not authenticated. run: gh auth login" >&2
  exit 1
fi

OWNER="$(gh api user --jq .login)"
EXPECTED_URL="https://github.com/${OWNER}/${REPO_NAME}.git"

if gh repo view "${OWNER}/${REPO_NAME}" >/dev/null 2>&1; then
  echo "repo ${OWNER}/${REPO_NAME} already exists — wiring remote and pushing"
else
  echo "creating ${OWNER}/${REPO_NAME} (${VISIBILITY})"
  gh repo create "${OWNER}/${REPO_NAME}" \
    "--${VISIBILITY}" \
    --description "Local-first cashier assistant for AMD Strix Halo (Lemonade + FastFlowLM + GAIA), with deterministic financial core, audit/replay, and offline AI agents." \
    --source "$REPO_DIR" \
    --remote origin \
    --push
  echo
  echo "done: $EXPECTED_URL"
  exit 0
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$EXPECTED_URL"
else
  git remote add origin "$EXPECTED_URL"
fi
git push -u origin main
echo
echo "done: $EXPECTED_URL"
