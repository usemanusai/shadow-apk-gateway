#!/usr/bin/env bash
# Download the Frida server binary for Android x86_64
# Usage: ./server_download.sh [version] [arch]

set -euo pipefail

VERSION="${1:-16.5.2}"
ARCH="${2:-x86_64}"
PLATFORM="android"

FILENAME="frida-server-${VERSION}-${PLATFORM}-${ARCH}"
URL="https://github.com/frida/frida/releases/download/${VERSION}/${FILENAME}.xz"
OUTPUT_DIR="$(dirname "$0")/bin"

mkdir -p "$OUTPUT_DIR"

echo "[*] Downloading Frida server v${VERSION} for ${PLATFORM}-${ARCH}"
echo "    URL: ${URL}"

if command -v curl &> /dev/null; then
    curl -L -o "${OUTPUT_DIR}/${FILENAME}.xz" "$URL"
elif command -v wget &> /dev/null; then
    wget -O "${OUTPUT_DIR}/${FILENAME}.xz" "$URL"
else
    echo "[!] Neither curl nor wget found"
    exit 1
fi

echo "[*] Extracting..."
if command -v xz &> /dev/null; then
    xz -d "${OUTPUT_DIR}/${FILENAME}.xz"
else
    echo "[!] xz not found, trying unxz..."
    unxz "${OUTPUT_DIR}/${FILENAME}.xz"
fi

chmod +x "${OUTPUT_DIR}/${FILENAME}"
echo "[✓] Frida server ready at: ${OUTPUT_DIR}/${FILENAME}"
echo ""
echo "Push to device with:"
echo "  adb push ${OUTPUT_DIR}/${FILENAME} /data/local/tmp/frida-server"
echo "  adb shell 'chmod 755 /data/local/tmp/frida-server'"
echo "  adb shell 'su -c /data/local/tmp/frida-server -D &'"
