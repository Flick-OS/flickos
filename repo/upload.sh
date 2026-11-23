#!/bin/sh
# Upload the apt repository (repo/public/, made by repo/publish.sh) to the
# gh-pages branch of the dedicated dvbondoy/flickos-apt GitHub repo, where it
# is served as https://dvbondoy.github.io/flickos-apt/ (see
# packages/flickos-archive-keyring/etc/apt/sources.list.d/flickos.sources).
#
# Needs push access to git@github.com:dvbondoy/flickos-apt.git (SSH key added
# to your GitHub account).
#
# Usage: repo/upload.sh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="git@github.com:dvbondoy/flickos-apt.git"
# REPO_DATA: public/ and .gh-pages/, shared by every checkout (repo/data-dir.sh).
. "$ROOT/repo/data-dir.sh"
CLONE="$REPO_DATA/.gh-pages"
BASE="https://dvbondoy.github.io/flickos-apt"
# FLICKOS_DEBIAN: the suite names.
. "$ROOT/packages/flickos-branding/usr/lib/flickos-release"

if [ ! -f "$REPO_DATA/public/dists/$FLICKOS_DEBIAN/InRelease" ]; then
    echo "No signed repository in repo/public/. Run repo/publish.sh first." >&2
    exit 1
fi

if [ ! -d "$CLONE/.git" ]; then
    echo "==> Cloning $REMOTE (gh-pages) to $CLONE"
    rm -rf "$CLONE"
    git clone --branch gh-pages --single-branch "$REMOTE" "$CLONE"
fi

echo "==> Syncing repo/public/ into $CLONE"
git -C "$CLONE" fetch origin gh-pages
git -C "$CLONE" reset --hard origin/gh-pages
# --delete below would remove a suite the site has and repo/public/ lacks:
# every installed system of that release would lose its updates. Suites are
# never deleted (docs/11), so a missing one means the wrong repo/public/.
for dir in "$CLONE"/dists/*/; do
    [ -d "$dir" ] || continue
    suite="$(basename "$dir")"
    if [ ! -d "$REPO_DATA/public/dists/$suite" ]; then
        echo "Refusing to upload: the site has dists/$suite and $REPO_DATA/public/ doesn't." >&2
        echo "Uploading would delete it. Publish from the checkout whose repo/ holds every suite (docs/11, \"The 2.x worktree\")." >&2
        exit 1
    fi
done
# --delete keeps the branch identical to repo/public/, except .git itself.
rsync -rt --delete --exclude=.git "$REPO_DATA/public/" "$CLONE/"
# The style packages' screenshots (tools/make-style-shots.sh), at the
# addresses in their metainfo: $BASE/screenshots/NAME/N.png.
rsync -rt --delete "$ROOT/repo/screenshots/" "$CLONE/screenshots/"
# Stops GitHub Pages' Jekyll build from skipping or rewriting repo files.
touch "$CLONE/.nojekyll"

if [ -z "$(git -C "$CLONE" status --porcelain)" ]; then
    echo "==> No changes to publish."
    exit 0
fi

git -C "$CLONE" add -A
git -C "$CLONE" commit -q -m "Publish apt repo $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git -C "$CLONE" push origin gh-pages

echo "==> Check: curl -fsSI $BASE/dists/$FLICKOS_DEBIAN/InRelease"
[ -d "$REPO_DATA/public/dists/$FLICKOS_DEBIAN-testing" ] &&
    echo "==>        curl -fsSI $BASE/dists/$FLICKOS_DEBIAN-testing/InRelease"
exit 0
