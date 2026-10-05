#!/bin/sh
# Installs the Baran host tools without Homebrew (Linux, or a Mac without it):
#   curl -fsSL https://raw.githubusercontent.com/belokonandreyka/baran-host/main/install.sh | sh
# Needs curl, tar and python3. Run it again to update.
set -eu

ARCHIVE="${BARAN_ARCHIVE:-https://github.com/belokonandreyka/baran-host/archive/refs/heads/main.tar.gz}"
DEST="${BARAN_HOME:-$HOME/.local/share/baran}"
BIN="$HOME/.local/bin"

command -v python3 >/dev/null || { echo "baran needs python3" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "$ARCHIVE" | tar xz -C "$tmp"

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")" "$BIN"
mv "$tmp"/baran-host-* "$DEST"
ln -sf "$DEST/bin/baran" "$BIN/baran"

echo "Installed $("$BIN/baran" --version) in $DEST"
case ":$PATH:" in
    *":$BIN:"*) echo "Next: baran pair" ;;
    *) echo "Next: $BIN/baran pair   ($BIN is not in your PATH)" ;;
esac
