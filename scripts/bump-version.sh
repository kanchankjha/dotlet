#!/bin/sh
# Bump the version in dotlet/__init__.py and optionally create a git tag
set -eu

usage() {
  echo "Usage: $0 [--tag] <major|minor|patch|VERSION>"
  echo ""
  echo "Arguments:"
  echo "  major         Bump major version (X.0.0)"
  echo "  minor         Bump minor version (x.Y.0)"
  echo "  patch         Bump patch version (x.y.Z)"
  echo "  VERSION       Set explicit version (e.g., 1.2.3)"
  echo ""
  echo "Options:"
  echo "  --tag         Create an annotated git tag after bumping"
  echo "  --help, -h    Show this help message"
  echo ""
  echo "Examples:"
  echo "  $0 patch           # 0.2.1 -> 0.2.2"
  echo "  $0 minor           # 0.2.1 -> 0.3.0"
  echo "  $0 major           # 0.2.1 -> 1.0.0"
  echo "  $0 1.0.0           # Set to 1.0.0"
  echo "  $0 --tag patch     # Bump patch and create tag v0.2.2"
  exit 1
}

TAG=false
VERSION_ARG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --tag)
      TAG=true
      shift
      ;;
    --help|-h)
      usage
      ;;
    *)
      if [ -z "$VERSION_ARG" ]; then
        VERSION_ARG="$1"
      else
        echo "Error: Unexpected argument '$1'"
        usage
      fi
      shift
      ;;
  esac
done

if [ -z "$VERSION_ARG" ]; then
  echo "Error: Version argument required"
  usage
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
INIT_FILE="$ROOT/dotlet/__init__.py"

# Extract current version
CURRENT=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$INIT_FILE")
if [ -z "$CURRENT" ]; then
  echo "Error: Could not read current version from $INIT_FILE"
  exit 1
fi

echo "Current version: $CURRENT"

# Parse current version
MAJOR=$(echo "$CURRENT" | cut -d. -f1)
MINOR=$(echo "$CURRENT" | cut -d. -f2)
PATCH=$(echo "$CURRENT" | cut -d. -f3)

case "$VERSION_ARG" in
  major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    NEW_VERSION="$MAJOR.$MINOR.$PATCH"
    ;;
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    NEW_VERSION="$MAJOR.$MINOR.$PATCH"
    ;;
  patch)
    PATCH=$((PATCH + 1))
    NEW_VERSION="$MAJOR.$MINOR.$PATCH"
    ;;
  *)
    # Validate explicit version format
    if ! echo "$VERSION_ARG" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
      echo "Error: Invalid version format '$VERSION_ARG'. Expected X.Y.Z"
      exit 1
    fi
    NEW_VERSION="$VERSION_ARG"
    ;;
esac

echo "New version: $NEW_VERSION"

# Update __init__.py
sed -i.bak "s/^__version__ = \"[^\"]*\"/__version__ = \"$NEW_VERSION\"/" "$INIT_FILE"
rm -f "$INIT_FILE.bak"

echo "Updated $INIT_FILE"

if [ "$TAG" = true ]; then
  # Check for uncommitted changes (excluding the version bump we just made)
  if ! git diff --quiet -- ':!dotlet/__init__.py'; then
    echo "Warning: You have uncommitted changes. Commit them before tagging."
  fi

  # Commit the version bump
  git add "$INIT_FILE"
  git commit -m "chore: bump version to $NEW_VERSION"

  # Create annotated tag
  TAG_NAME="v$NEW_VERSION"
  git tag -a "$TAG_NAME" -m "Release $NEW_VERSION"

  echo ""
  echo "Created tag: $TAG_NAME"
  echo ""
  echo "To push the release:"
  echo "  git push origin main"
  echo "  git push origin $TAG_NAME"
fi
