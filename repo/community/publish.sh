#!/bin/sh
# Publish the community apps in repo/community/apps/ to the signed
# trixie-community (FLICKOS_DEBIAN-community) distribution in repo/public/ (Software design, ADR-004).
# Upload it afterwards with repo/upload.sh, like FlickOS's own packages.
#
# Usage: repo/community/publish.sh [--from DIR]
#
# For each app whose listed version isn't the published one, it takes the
# .deb that the community CI built on main (an artifact named
# community-NAME-COMMIT, downloaded with gh), checks it again here
# (check.py), and adds it with reprepro. --from DIR takes NAME_VERSION_*.deb
# from DIR instead (repo/community/build.py's output, for a trial). The
# signing key stays on this computer; CI never sees it.
#
# Taking an app away:
#   - withdrawn/NAME (its first line: why, in a few words), with apps/NAME
#     deleted: a bad app. It publishes an empty package, VERSION+withdrawn1,
#     built here (build.py --withdrawn), which replaces the app on every
#     computer that installed it: the automatic updates install it and the
#     app's files are gone. Keep the file; the empty package stays.
#   - apps/NAME deleted without withdrawn/NAME: an app that is merely no longer
#     offered. It leaves the distribution; computers keep what they have.
#
# Only artifacts of runs on main in this repository count: a pull request
# runs its own copy of the workflow and could upload anything under any name.
#
# Needs reprepro, and for downloads gh (`sudo apt install gh`, `gh auth login`).
set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO="${REPO:-$ROOT/repo}"
APPS="$ROOT/repo/community/apps"
WITHDRAWN="$ROOT/repo/community/withdrawn"
# FLICKOS_DEBIAN: the suite names.
. "$ROOT/packages/flickos-branding/usr/lib/flickos-release"
DIST="$FLICKOS_DEBIAN-community"
GH_REPO="${GH_REPO:-dvbondoy/FlickOS}"
FROM=""

case "$1" in
    --from) FROM="$(cd "$2" && pwd)" ;;
    "") ;;
    *) echo "Usage: $0 [--from DIR]" >&2; exit 2 ;;
esac

if grep -q '^SignWith: CHANGE-ME' "$REPO/conf/distributions"; then
    echo "No signing key configured. Run repo/new-key.sh first." >&2
    exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# field NAME KEY: a value from the app's file (build.py checks the format).
field() {
    sed -n "s/^[[:space:]]*$2[[:space:]]*=[[:space:]]*//p" "$APPS/$1" | sed 's/[[:space:]]*$//'
}

published() {
    reprepro -b "$REPO" list "$DIST" "$1" | sed -n 's/^[^:]*: [^ ]* //p' | head -n 1
}

for file in "$WITHDRAWN"/*; do
    if [ -f "$file" ] && [ -f "$APPS/$(basename "$file")" ]; then
        echo "==> $(basename "$file") is both listed and withdrawn: delete repo/community/apps/$(basename "$file")" >&2
        exit 1
    fi
done

for file in "$APPS"/*; do
    [ -f "$file" ] || continue
    name="$(basename "$file")"
    version="$(field "$name" version)"
    commit="$(field "$name" commit)"
    if [ "$(published "$name")" = "$version" ]; then
        echo "==> $name $version is published"
        continue
    fi
    dir="$WORK/$name"
    mkdir -p "$dir"
    if [ -n "$FROM" ]; then
        cp "$FROM"/"${name}_${version}"_*.deb "$dir/" 2>/dev/null || true
    else
        if ! command -v gh >/dev/null; then
            echo "gh is needed to download what CI built: sudo apt install gh && gh auth login (or use --from DIR)." >&2
            exit 1
        fi
        artifact="community-$name-$commit"
        run="$(gh api "repos/$GH_REPO/actions/artifacts?name=$artifact" --jq \
            '[.artifacts[] | select(.expired | not)
              | select(.workflow_run.head_branch == "main")
              | select(.workflow_run.head_repository_id == .workflow_run.repository_id)]
             | first | .workflow_run.id // empty')"
        if [ -z "$run" ]; then
            echo "==> $name $version: no CI build on main for $commit (merged? CI green? artifacts last 90 days)" >&2
            exit 1
        fi
        echo "==> $name $version: downloading CI run $run's $artifact"
        gh run download "$run" -R "$GH_REPO" -n "$artifact" -D "$dir"
    fi
    set -- "$dir"/"${name}_${version}"_*.deb
    if [ ! -f "$1" ] || [ $# -ne 1 ]; then
        echo "==> $name: expected one ${name}_${version}_*.deb, found: $(ls "$dir")" >&2
        exit 1
    fi
    deb="$1"
    if [ "$(dpkg-deb -f "$deb" Package)" != "$name" ] || [ "$(dpkg-deb -f "$deb" Version)" != "$version" ]; then
        echo "==> $name: $(basename "$deb") isn't $name $version" >&2
        exit 1
    fi
    echo "==> $name $version: checking again"
    python3 "$ROOT/repo/community/check.py" "$deb"
    reprepro -b "$REPO" includedeb "$DIST" "$deb"
done

# Withdrawn apps: the empty package replaces them everywhere.
for file in "$WITHDRAWN"/*; do
    [ -f "$file" ] || continue
    name="$(basename "$file")"
    version="$(published "$name")"
    case "$version" in
        "") echo "==> $name is withdrawn and was never published: nothing to replace"; continue ;;
        *+withdrawn*) echo "==> $name is withdrawn ($version)"; continue ;;
    esac
    echo "==> $name $version: withdrawing it ($(head -n 1 "$file"))"
    deb="$(python3 "$ROOT/repo/community/build.py" --withdrawn "$name" --version "$version" \
        --reason "$(head -n 1 "$file")" --out "$WORK/withdrawn")"
    reprepro -b "$REPO" includedeb "$DIST" "$deb"
done

# Apps taken off the list (not withdrawn) leave the distribution (and the
# shelf: featured.json).
reprepro -b "$REPO" list "$DIST" | sed -n 's/^[^:]*: \([^ ]*\) .*/\1/p' | sort -u | while read -r name; do
    if [ ! -f "$APPS/$name" ] && [ ! -f "$WITHDRAWN/$name" ]; then
        echo "==> $name is no longer listed: removing it"
        reprepro -b "$REPO" remove "$DIST" "$name"
    fi
done

# Also makes the distribution's (empty) indices the first time, which apt on
# every computer with flickos-archive-keyring 1.6 needs.
reprepro -b "$REPO" export "$DIST"

echo "==> $DIST:"
reprepro -b "$REPO" list "$DIST"
echo "==> Next: repo/upload.sh"
