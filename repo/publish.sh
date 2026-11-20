#!/bin/sh
# Build all FlickOS packages and add them to the signed apt repository in
# repo/public/. Upload it afterwards with repo/upload.sh
# (served at https://dvbondoy.github.io/flickos-apt/).
#
# Also builds and adds the apps in EXTRAS from their own repositories next to
# this one (proprietary; docs/design/flickos-store.md, ADR-008). EXTRAS is
# empty since 2026-11-11: Notes, Write and Phone Screen were removed from the
# repo. They are never in the ISO, because packages/build.sh doesn't build
# them.
#
# Bump the version in debian/changelog (dch -i) before republishing a changed
# package; reprepro refuses a different file with the same version.
#
# Packages for testers: a version with ~test (dch -v 1.0~test1) is never added
# to trixie (FLICKOS_DEBIAN). `repo/publish.sh --testing` adds only those, to
# trixie-testing, and nothing else (no EXTRAS); testers add that suite by hand
# (docs/05-apt-repository.md, "Testing packages"). 1.0~test1 sorts before
# 1.0, so the release in trixie replaces it on the testers' next upgrade.
#
# Usage: repo/publish.sh [--testing]
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$ROOT/repo"
# Folder names, looked for in EXTRAS_DIR. Empty by default: EXTRAS="flickos-notes"
# publishes one by hand. flickos-notes, -write and -phone-screen were taken out
# on 2026-11-11 (store ADR-008's amendment); flickos-trail is private, sold
# once the store opens.
EXTRAS="${EXTRAS-}"
EXTRAS_DIR="${EXTRAS_DIR:-$(dirname "$ROOT")}"
WORK="$REPO/.extras-build"
# FLICKOS_DEBIAN: the suite names.
. "$ROOT/packages/flickos-branding/usr/lib/flickos-release"
SUITE="$FLICKOS_DEBIAN"
TESTING_SUITE="$FLICKOS_DEBIAN-testing"

case "$1" in
--testing) TESTING=yes; EXTRAS= ;;
"") TESTING= ;;
*) echo "Usage: repo/publish.sh [--testing]" >&2; exit 2 ;;
esac

# True for a package version meant for testers only.
for_testers() {
    case "$(dpkg-deb -f "$1" Version)" in *~test*) return 0 ;; esac
    return 1
}

if grep -q '^SignWith: CHANGE-ME' "$REPO/conf/distributions"; then
    echo "No signing key configured. Run repo/new-key.sh first." >&2
    exit 1
fi

for name in $EXTRAS; do
    if [ ! -f "$EXTRAS_DIR/$name/debian/changelog" ]; then
        echo "No $EXTRAS_DIR/$name/debian/. Clone it there, set EXTRAS_DIR, or leave it out of EXTRAS." >&2
        exit 1
    fi
done

sh "$ROOT/packages/build.sh"

rm -rf "$WORK"
mkdir -p "$WORK"
for name in $EXTRAS; do
    src="$EXTRAS_DIR/$name"
    if [ -n "$(git -C "$src" status --porcelain 2>/dev/null)" ]; then
        echo "==> Warning: $src has uncommitted changes, and they are published too."
    fi
    echo "==> Building $name from $src"
    # A copy, so build artifacts stay out of the app's own tree.
    cp -r "$src" "$WORK/$name"
    rm -rf "${WORK:?}/${name:?}/.git"
    (cd "$WORK/$name" && dpkg-buildpackage -us -uc -b)
done

if [ -n "$TESTING" ]; then
    found=
    for deb in "$ROOT"/config/packages.chroot/*.deb "$ROOT"/config/packages.opt-in/*.deb; do
        [ -e "$deb" ] || continue
        for_testers "$deb" || continue
        reprepro -b "$REPO" includedeb "$TESTING_SUITE" "$deb"
        found=yes
    done
    [ -n "$found" ] || echo "==> No package has a ~test version: nothing added to $TESTING_SUITE."
    echo "==> $TESTING_SUITE contents:"
    reprepro -b "$REPO" list "$TESTING_SUITE"
    echo "==> Next: repo/upload.sh"
    exit 0
fi

for deb in "$ROOT"/config/packages.chroot/*.deb "$ROOT"/config/packages.opt-in/*.deb "$WORK"/*.deb; do
    [ -e "$deb" ] || continue
    if for_testers "$deb"; then
        echo "==> Not in $SUITE: $(basename "$deb") is for testers (repo/publish.sh --testing)"
        continue
    fi
    reprepro -b "$REPO" includedeb "$SUITE" "$deb"
done

# Convenience copy for manual setup on non-FlickOS machines.
cp "$ROOT/packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc" "$REPO/public/"

echo "==> Repository contents:"
reprepro -b "$REPO" list "$SUITE"
echo "==> Next: repo/upload.sh"
