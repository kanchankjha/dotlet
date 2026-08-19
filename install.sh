#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKIP_UPDATE=0
PASSWORD_MODE=random
PASSWORD_MODE_SET=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [--no-update] [--prompt-password | --random-password]

Build Dotlet from this Git checkout and install it with APT.
  --no-update        Do not refresh APT package indexes before installation.
  --prompt-password  Securely prompt for the admin password after installation.
  --random-password  Generate a random admin password (the default).
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-update) SKIP_UPDATE=1 ;;
    --prompt-password|--random-password)
      if [ "$PASSWORD_MODE_SET" -eq 1 ]; then
        echo "Choose only one password mode." >&2
        usage >&2
        exit 2
      fi
      PASSWORD_MODE_SET=1
      if [ "$1" = "--prompt-password" ]; then
        PASSWORD_MODE=prompt
      else
        PASSWORD_MODE=random
      fi
      ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

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

APT_DIR=$(mktemp -d /tmp/dotlet-install.XXXXXX)
chmod 0755 "$APT_DIR"
APT_PACKAGE="$APT_DIR/$(basename "$PACKAGE")"
cp "$PACKAGE" "$APT_PACKAGE"
chmod 0644 "$APT_PACKAGE"
cleanup() {
  rm -rf "$APT_DIR"
}
trap cleanup EXIT HUP INT TERM

run_root apt-get install -y "$APT_PACKAGE"

if [ "$PASSWORD_MODE" = "prompt" ]; then
  run_root /usr/bin/dotlet set-password admin --prompt
  run_root rm -f /var/lib/dotlet/initial-password
fi

echo
echo "Dotlet $VERSION is installed."
if [ "$PASSWORD_MODE" = "random" ]; then
  echo "Initial password: sudo cat /var/lib/dotlet/initial-password"
else
  echo "Admin password: the password entered during installation"
fi
echo "UI (through an SSH tunnel): http://127.0.0.1:8080"
