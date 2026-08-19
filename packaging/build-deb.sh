#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEFAULT_VERSION=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$ROOT/dotlet/__init__.py")
VERSION=${VERSION:-$DEFAULT_VERSION}
ARCH=${ARCH:-$(dpkg --print-architecture)}
BUILD="$ROOT/build/deb-root"
OUTPUT="$ROOT/dist"

rm -rf "$BUILD"
install -d "$BUILD/DEBIAN" "$BUILD/usr/lib/dotlet" "$BUILD/usr/bin" "$BUILD/usr/libexec" \
  "$BUILD/lib/systemd/system" "$BUILD/etc/default" "$BUILD/etc/sudoers.d" "$OUTPUT"
install -d "$BUILD/usr/share/doc/dotlet"
cp -R "$ROOT/dotlet" "$BUILD/usr/lib/dotlet/"
find "$BUILD/usr/lib/dotlet" -type d -name __pycache__ -prune -exec rm -rf {} +
install -m 0755 "$ROOT/bin/dotlet" "$BUILD/usr/bin/dotlet"
install -m 0755 "$ROOT/libexec/dotlet-apply" "$BUILD/usr/libexec/dotlet-apply"
install -m 0644 "$ROOT/systemd/dotlet.service" "$BUILD/lib/systemd/system/dotlet.service"
install -m 0644 "$ROOT/systemd/dotlet-named.service" "$BUILD/lib/systemd/system/dotlet-named.service"
install -m 0644 "$ROOT/config/dotlet.default" "$BUILD/etc/default/dotlet"
install -m 0440 "$ROOT/config/dotlet.sudoers" "$BUILD/etc/sudoers.d/dotlet"
install -m 0644 "$ROOT/README.md" "$ROOT/LICENSE" "$BUILD/usr/share/doc/dotlet/"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@ARCH@/$ARCH/g" "$ROOT/packaging/control" > "$BUILD/DEBIAN/control"
install -m 0755 "$ROOT/packaging/postinst" "$BUILD/DEBIAN/postinst"
install -m 0755 "$ROOT/packaging/prerm" "$BUILD/DEBIAN/prerm"
install -m 0755 "$ROOT/packaging/postrm" "$BUILD/DEBIAN/postrm"
dpkg-deb --root-owner-group --build "$BUILD" "$OUTPUT/dotlet_${VERSION}_${ARCH}.deb"
echo "$OUTPUT/dotlet_${VERSION}_${ARCH}.deb"
