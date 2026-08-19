#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKIP_UPDATE=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [--no-update]

Build Dotlet from this Git checkout and install it with APT.
  --no-update  Do not refresh APT package indexes before installation.
EOF
}

case "${1:-}" in
  "") ;;
  --no-update) SKIP_UPDATE=1 ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if [ ! -r /etc/os-release ]; then
  echo "Dotlet source installation requires Ubuntu, Kali, or another Debian-based Linux distribution." >&2
  exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-} ${ID_LIKE:-}" in
  *ubuntu*|*kali*|*debian*) ;;
  *)
    echo "Unsupported distribution: ${PRETTY_NAME:-unknown}. Dotlet currently supports Debian-based systems." >&2
    exit 1
    ;;
esac

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Root access is required. Install sudo or rerun this script as root." >&2
    exit 1
  fi
}

if [ "$SKIP_UPDATE" -eq 0 ]; then
  run_root apt-get update
fi

if ! command -v dpkg-deb >/dev/null 2>&1; then
  run_root apt-get install -y dpkg
fi

ARCH=$(dpkg --print-architecture)
VERSION=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$ROOT/dotlet/__init__.py")
if [ -z "$VERSION" ]; then
  echo "Could not determine the Dotlet version." >&2
  exit 1
fi

ARCH="$ARCH" VERSION="$VERSION" "$ROOT/packaging/build-deb.sh"
PACKAGE="$ROOT/dist/dotlet_${VERSION}_${ARCH}.deb"
if [ ! -f "$PACKAGE" ]; then
  echo "Package build did not produce $PACKAGE" >&2
  exit 1
fi

run_root apt-get install -y "$PACKAGE"

echo
echo "Dotlet $VERSION is installed."
echo "Initial password: sudo cat /var/lib/dotlet/initial-password"
echo "UI (through an SSH tunnel): http://127.0.0.1:8080"
