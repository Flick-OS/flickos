#!/bin/sh
# Build every package under packages/ and stage the .debs in
# config/packages.chroot/, where live-build installs every one of them into the
# image. Opt-in packages (flickos-style-*, flickos-kit-*, flickos-fleet,
# flickos-classroom-view, flickos-classroom-teacher and libneatvnc0, installed from the apt repository
# only) go to config/packages.opt-in/ instead, which repo/publish.sh reads too.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/config/packages.chroot"
OPT_IN="$ROOT/config/packages.opt-in"
WORK="$ROOT/packages/.build"

if [ ! -e "$ROOT/packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc" ]; then
    echo "Missing repository public key. Run repo/new-key.sh first." >&2
    exit 1
fi

rm -rf "$WORK"
mkdir -p "$WORK" "$OUT" "$OPT_IN"

for src in "$ROOT"/packages/*/debian; do
    pkg="$(basename "$(dirname "$src")")"
    # Older versions of the packages it builds (neatvnc builds libneatvnc0).
    for bin in $(sed -n 's/^Package: *//p' "$src/control"); do
        rm -f "$OUT/${bin}"_*.deb "$OPT_IN/${bin}"_*.deb
    done
    echo "==> Building $pkg"
    # Build from a copy so build artifacts stay out of the source tree.
    cp -r "$ROOT/packages/$pkg" "$WORK/$pkg"
    (cd "$WORK/$pkg" && dpkg-buildpackage -us -uc -b)
done

# Two packages with the same file fail only deep inside lb build (dpkg:
# "trying to overwrite"). Catch it here.
overlap="$(for deb in "$WORK"/*.deb; do
    dpkg-deb -c "$deb" | awk -v p="$(basename "$deb")" '$1 !~ /^d/ { sub(/^\.\//, "", $6); print $6 "\t" p }'
done | sort | awk -F'\t' '$1 == last { print $1 ": " lastp ", " $2 } { last = $1; lastp = $2 }')"
if [ -n "$overlap" ]; then
    echo "Files in more than one package:" >&2
    echo "$overlap" >&2
    exit 1
fi

# A version already published (repo/public/pool, where repo/publish.sh puts
# it) must have the same files: apt never replaces an installed package with
# other contents under the same version, and reprepro refuses it. Different
# files mean a change without a version bump, or a branch that took a number
# main published meanwhile (docs/06, "Package versions on branches"). Only a
# warning: a compiled package (sfwbar) can differ between two builds of the
# same source, and CI has no pool.
POOL="$ROOT/repo/public/pool"
if [ -d "$POOL" ]; then
    for deb in "$WORK"/*.deb; do
        published="$(find "$POOL" -name "$(basename "$deb")" -print -quit)"
        [ -n "$published" ] || continue
        if [ "$(dpkg-deb -I "$deb" md5sums 2>/dev/null)" != "$(dpkg-deb -I "$published" md5sums 2>/dev/null)" ]; then
            echo "WARNING: $(basename "$deb") is already published with other files." >&2
            echo "  Give the package a new version (dch -i, or dch -v X.Y~test1 on a branch" >&2
            echo "  that isn't merged yet). Installing this build would not replace the" >&2
            echo "  published one, or would replace it with other contents." >&2
        fi
    done
fi

for deb in "$WORK"/*.deb; do
    case "$(basename "$deb")" in
        flickos-style-*|flickos-kit-*|flickos-fleet_*|flickos-classroom-view_*|flickos-classroom-teacher_*|libneatvnc0_*) cp "$deb" "$OPT_IN"/ ;;
        *) cp "$deb" "$OUT"/ ;;
    esac
done
echo "==> Staged in $OUT:"
ls -1 "$OUT"
echo "==> Not in the image, staged in $OPT_IN:"
ls -1 "$OPT_IN"
