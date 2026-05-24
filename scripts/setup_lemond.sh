#!/usr/bin/env bash
# Download and extract the embedded lemond runtime into vendor/lemonade/.
# Re-run to upgrade to a new version.

set -euo pipefail

LEMOND_VERSION="10.6.0"
ARCHIVE="lemonade-embeddable-${LEMOND_VERSION}-ubuntu-x64.tar.gz"
DOWNLOAD_URL="https://github.com/lemonade-sdk/lemonade/releases/download/v${LEMOND_VERSION}/${ARCHIVE}"
VENDOR_DIR="$(cd "$(dirname "$0")/.." && pwd)/vendor/lemonade"

echo "Setting up embedded lemond ${LEMOND_VERSION} -> ${VENDOR_DIR}"

mkdir -p "${VENDOR_DIR}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${ARCHIVE}..."
if command -v gh &>/dev/null; then
    gh release download "v${LEMOND_VERSION}" \
        --repo lemonade-sdk/lemonade \
        --pattern "${ARCHIVE}" \
        --dir "${TMP}"
else
    curl -fL --progress-bar -o "${TMP}/${ARCHIVE}" "${DOWNLOAD_URL}"
fi

echo "Extracting..."
tar -xzf "${TMP}/${ARCHIVE}" -C "${VENDOR_DIR}" --strip-components=1

chmod +x "${VENDOR_DIR}/lemond" "${VENDOR_DIR}/lemonade"

echo "Done. Verify with: vendor/lemonade/lemond --help"
