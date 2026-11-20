#!/bin/sh
# One-time setup: create the repository signing key, export the public half
# into the flickos-archive-keyring package, and point reprepro at it.
#
# Usage: repo/new-key.sh ["Name <email>"]
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEYFILE="$ROOT/packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc"
KEY_UID="${1:-FlickOS Archive Signing Key <dvbondoy@gmail.com>}"

if [ -e "$KEYFILE" ]; then
    echo "Key already exported to $KEYFILE; refusing to replace it." >&2
    echo "Changing the key breaks updates for every installed system." >&2
    exit 1
fi

# Prompts for a passphrase. Keep it; reprepro needs it to sign.
FPR="$(gpg --status-fd 1 --quick-gen-key "$KEY_UID" rsa4096 sign never \
    | awk '/KEY_CREATED/ { print $4 }')"

if [ -z "$FPR" ]; then
    echo "Key generation failed." >&2
    exit 1
fi

gpg --armor --export "$FPR" > "$KEYFILE"
sed -i "s/^SignWith:.*/SignWith: $FPR/" "$ROOT/repo/conf/distributions"

cat <<EOF
Created signing key $FPR
  public key: $KEYFILE
  reprepro:   repo/conf/distributions now signs with it

Back up the secret key somewhere offline:
  gpg --armor --export-secret-keys $FPR > flickos-archive-secret.asc
A revocation certificate was saved in ~/.gnupg/openpgp-revocs.d/.
EOF
