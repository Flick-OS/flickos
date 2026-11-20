# 05 – Apt repository

The FlickOS apt repository is how installed systems receive updates to
`flickos-*` packages, and where other developers' apps are published
(distribution `trixie-community`, [below](#community-apps-trixie-community)). It's a folder of static files (`dists/`, `pool/`),
signed with a GPG key. No server software is needed. FlickOS hosts it on
**GitHub Pages**, from the `gh-pages` branch of the dedicated
[`dvbondoy/flickos-apt`](https://github.com/dvbondoy/flickos-apt) repository, at
**https://dvbondoy.github.io/flickos-apt/**.

```
Your machine                              GitHub Pages                       Installed FlickOS
────────────                              ────────────                       ─────────────────
packages/*  ──build.sh──► .deb
                            │
repo/conf ──► reprepro ◄────┘
                  │
                  ▼  signs with your GPG key
             repo/public/ ── repo/upload.sh ──► dvbondoy.github.io/flickos-apt ◄── apt update / upgrade
                             (git push to                                        (source + key from
                              gh-pages)                                           flickos-archive-keyring)
```

**Why not the SourceForge Files section?** Downloads from Files are redirected
to mirrors that sync with a delay. apt then sees a new `InRelease` next to old
`Packages` files and fails with *hash sum mismatch*. GitHub Pages deploys each
push as a whole (its CDN may serve old copies for up to 10 minutes, so a
mismatch right after an upload goes away on its own). Files is used for the
ISOs ([06](06-ci-and-releases.md)).

## Files

| Path | In git? | What |
|---|---|---|
| `repo/conf/distributions` | yes | Repo definition: three distributions, `trixie` (FlickOS's packages, label *FlickOS*), `trixie-community` (other developers' apps, label *FlickOS Community*) and `trixie-testing` (packages for testers, label *FlickOS Testing*, [below](#testing-packages-trixie-testing)), component `main`, arch `amd64`, the `SignWith:` key fingerprint, and the DEP-11 hook |
| `repo/conf/dep11.py` | yes | reprepro `DebIndices` hook: writes `main/dep11/Components-amd64.yml(.gz)` (AppStream data for Software) from the metainfo files in the packages; needs `gir1.2-appstream-1.0` |
| `repo/community/` | yes | The community apps' list (`apps/NAME`), checks, build and publish scripts ([its README](../repo/community/README.md)) |
| `repo/conf/options` | yes | Tells reprepro to write output to `repo/public/` and its database to `repo/db/` |
| `repo/new-key.sh` | yes | One-time key setup |
| `repo/publish.sh` | yes | Build all packages and add them to the repo (`--testing`: only the `~test` versions, to `trixie-testing`) |
| `repo/upload.sh` | yes | Push `repo/public/` and `repo/screenshots/` to the `gh-pages` branch of `dvbondoy/flickos-apt` |
| `repo/screenshots/` | yes | The style packages' screenshots for Software, `NAME/1.png` and `2.png`, served at `https://dvbondoy.github.io/flickos-apt/screenshots/` (the addresses in their metainfo); taken by `tools/make-style-shots.sh` |
| `repo/db/` | **no** | reprepro's database of what the repo contains |
| `repo/public/` | **no** | The finished repository to upload |
| `repo/.gh-pages/` | **no** | `repo/upload.sh`'s clone of the `gh-pages` branch |
| `packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc` | yes | Public key |
| `packages/flickos-archive-keyring/etc/apt/sources.list.d/flickos.sources` | yes | The apt source installed systems use (holds the **repo URL**) |

The apt source is shipped **in a package**, not baked into the ISO. When the
repository moves (e.g. to apt.flickos.org), a new version of `flickos-archive-keyring`
updates it on every installed system. See [Moving the repository](#moving-the-repository-eg-to-aptflickosorg).

## One-time setup

### 1. Create the signing key

```sh
repo/new-key.sh                                  # default name: "FlickOS Archive Signing Key <dvbondoy@gmail.com>"
repo/new-key.sh "FlickOS Archive <me@example>"   # or a custom one
```

It prompts for a passphrase, then:

1. creates an RSA-4096 signing key in your `~/.gnupg`,
2. exports the **public** key to `packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc`,
3. writes the fingerprint into `SignWith:` in `repo/conf/distributions`.

It refuses to run if a key was already exported, because replacing the key breaks
updates for everyone.

Commit both changed files:

```sh
git add packages/flickos-archive-keyring/keyrings/ repo/conf/distributions
git commit -m "Add FlickOS archive signing key"
```

### 2. Back up the secret key (do this now)

If you lose the secret key, **you can never ship updates to existing installs
again**. Users would have to reinstall a new keyring by hand.

```sh
gpg --list-secret-keys                 # find the fingerprint
gpg --armor --export-secret-keys FINGERPRINT > flickos-archive-secret.asc
```

Store `flickos-archive-secret.asc` and your passphrase somewhere safe and
offline, such as an encrypted USB stick or a password manager. **Never commit it.**

gpg also saved a revocation certificate in `~/.gnupg/openpgp-revocs.d/FINGERPRINT.rev`.
Back that up too. You need it if the key is ever stolen.

To restore on a new machine: `gpg --import flickos-archive-secret.asc`.

### 3. Give GitHub your SSH key

Uploads are a `git push` over SSH to `git@github.com:dvbondoy/flickos-apt.git`.

1. If you don't have an SSH key yet: `ssh-keygen -t ed25519`.
2. Add it to GitHub: `gh auth login` (choose SSH) uploads it, or paste
   `~/.ssh/id_ed25519.pub` at **https://github.com/settings/keys**.
3. Test: `ssh -T git@github.com`. It should greet you by username.

Another account can upload if it has write access to `dvbondoy/flickos-apt`.

The repository was created once with GitHub Pages serving the root of its
`gh-pages` branch (**Settings → Pages**). `repo/upload.sh` adds a `.nojekyll`
file so Pages serves every file unchanged.

### 4. First publish (before the first ISO build)

**The ISO build fails if the repository is unreachable**: at the end of the
chroot stage, live-build runs `apt update` with FlickOS's apt source installed.
So publish once before building:

```sh
repo/publish.sh && repo/upload.sh
```

## Publishing packages

```sh
repo/publish.sh      # build all packages, add them to repo/public/, sign
repo/upload.sh       # upload to https://dvbondoy.github.io/flickos-apt/
```

`repo/publish.sh`:

1. checks a signing key is configured,
2. runs `packages/build.sh`,
3. builds the apps in `EXTRAS` (none by default) from their own
   repositories next to this one, in copies under `repo/.extras-build/`
   (see below),
4. adds each `.deb` to the `trixie` distribution with `reprepro includedeb`,
   signing the index (gpg asks for your passphrase),
5. copies the public key to `repo/public/flickos-archive-keyring.asc` for people
   who want to add the repo by hand,
6. prints what the repo now contains.

If a package's version didn't change and its file is identical, reprepro skips it.
If the version didn't change but the file **did**, reprepro stops with
*"already registered with different checksums"*. Bump the version (see
[04](04-packages.md#changing-a-package)) and run it again.

`repo/upload.sh`:

1. clones the `gh-pages` branch to `repo/.gh-pages/` (first run only), then
   resets it to the remote branch,
2. copies `repo/public/` over it with `rsync --delete`, so the branch is an
   exact copy of `repo/public/` (plus `.nojekyll`),
3. commits and pushes. If nothing changed it stops without a commit.

GitHub Pages usually serves the new files within a minute or two. Check the
**Actions** tab of `dvbondoy/flickos-apt` (*pages build and deployment*) if not.

Every upload is a commit, so the branch keeps old `.deb` files in its history.
If the repository grows past GitHub's ~1 GB guidance, squash the history:
`git -C repo/.gh-pages checkout --orphan tmp && git -C repo/.gh-pages commit -m "Squash" && git -C repo/.gh-pages branch -M tmp gh-pages && git -C repo/.gh-pages push -f origin gh-pages`.

### Apps from other repositories (`EXTRAS`)

`EXTRAS` lists the folders of proprietary apps that `publish.sh` builds from
their own repositories and adds to the repo. **It is empty by default.**
Notes, Write and Phone Screen were published free of charge until
2026-11-11, when they were removed from the repo
([store ADR-008](design/flickos-store.md#adr-008-free-of-charge-until-the-store-opens),
amended that day). Trail was never put back after 0.6.
Their source is in their own repositories, not under `packages/`, so they are
never in the ISO. To publish one again, name it; `publish.sh` expects the
folder next to this checkout (`../flickos-notes` and so on) and stops if it
is missing:

```sh
EXTRAS="flickos-notes" repo/publish.sh             # one of them
EXTRAS_DIR=~/src EXTRAS="flickos-notes flickos-write" repo/publish.sh
```

It builds what is in each folder, committed or not, and warns about
uncommitted changes. Bump an app's version (`dch -i -D trixie`) before
publishing a change, as for FlickOS's own packages.

Taking an app out of the repo takes three steps, and the last two are by hand
(gpg asks for the passphrase in a terminal):

```sh
reprepro -b repo remove trixie flickos-notes       # from the index
reprepro -b repo deleteunreferenced                # its .deb from the pool
repo/upload.sh                                     # rsync --delete drops it from GitHub Pages
```

Computers that have the app keep it and get no updates; a reinstall fails
once the pool file is gone.

### AppStream data (DEP-11)

Both distributions run `repo/conf/dep11.py` whenever their `Packages` index
changes. It reads the metainfo files (`usr/share/metainfo/*.metainfo.xml`)
in the packages, converts them with libappstream and writes
`main/dep11/Components-amd64.yml` and `.yml.gz` with origin
`flickos-DISTRIBUTION-main`, which go into the signed `Release`. apt's
`appstream` hook fetches them like Debian's, and Software shows the
packages as apps of the source FlickOS or FlickOS Community (design:
[Software, ADR-002](design/flickos-software.md#adr-002-one-catalog-from-appstream-three-sources)).
A package without metainfo (the desktop's own parts) is no app there. The
icon and categories come from the launchable's desktop file when the
metainfo has none. The publishing computer needs `gir1.2-appstream-1.0`
(flickos-software depends on it).

## Community apps (`trixie-community`)

Other developers' apps, built by CI from their public source, checked and
reviewed, then signed here like FlickOS's own (Software design,
[ADR-004](design/flickos-software.md#adr-004-other-developers-publish-debs-in-a-flickos-community-repository)).
Everything about the list, the rules and the review is in
[`repo/community/README.md`](../repo/community/README.md); the developers'
guide is *Publish your app for FlickOS* on the website.

```sh
repo/community/publish.sh      # what CI built on main for each listed app → trixie-community
repo/upload.sh                 # the same upload as for FlickOS's packages
```

`publish.sh` downloads the artifact `community-NAME-COMMIT` of a CI run on
`main` (never a pull request's) with `gh` (`sudo apt install gh`,
`gh auth login`), checks it again with `check.py`, and adds it with
`reprepro includedeb trixie-community`; apps whose file was removed leave the
distribution. It also exports the distribution's indices, which must exist
online **before** flickos-archive-keyring 1.6 (which turns the suite on) is
published or an ISO is built: apt fails `update` on a suite whose `Release`
is missing. So the first time, run `repo/community/publish.sh` (with no apps
it exports an empty distribution), then `repo/publish.sh`, then
`repo/upload.sh`.

To take a bad app back from every computer, write `repo/community/withdrawn/NAME`
(the reason) and delete `apps/NAME`: `publish.sh` then publishes an empty
`VERSION+withdrawn1` package, which the automatic updates install over it
(details in the community README).

Automatic updates install community apps (`label=FlickOS Community` in
flickos-archive-keyring's `51flickos-origins` and flickos-control's
`UPDATE_SCOPES`, design Q10).

## Testing packages (`trixie-testing`)

A package that testers should try before everyone gets it goes into its own
distribution, which nobody has unless they add it by hand. Automatic updates
never use it (it isn't in flickos-archive-keyring's `51flickos-origins`), so
even testers get its updates when they run `apt upgrade`.

1. **Give the package a test version:** `dch -v 1.0~test1 -D trixie "…"`
   (a later fix: `~test2`). `~` sorts before everything, so `1.0~test1` is
   older than `1.0`: when the package is released, testers move to the
   release on their next upgrade without doing anything. A package that only
   works with a newer version of another one says so with `Breaks:` on the
   test version (`Breaks: flickos-control (<< 1.48~)`), so installing it
   brings that one along. A branch that waits to be merged uses these
   versions even when nobody tests it, so it never takes a number main
   publishes ([06](06-ci-and-releases.md#package-versions-on-branches)).
2. **Publish only the test versions:**

   ```sh
   repo/publish.sh --testing   # builds everything, adds only *~test* versions to trixie-testing
   repo/upload.sh
   ```

   An ordinary `repo/publish.sh` never adds a `~test` version to `trixie`
   (it says so and skips it), and `--testing` adds nothing else, not even
   `EXTRAS`. So the testing packages can be published from a branch without
   publishing the branch's other changes. `tools/build-iso.sh` warns when a
   `~test` version would go into the ISO.
3. **Testers add the suite once**, with the key their system already has:

   ```sh
   sudo tee /etc/apt/sources.list.d/flickos-testing.sources <<'EOF'
   Types: deb
   URIs: https://dvbondoy.github.io/flickos-apt
   Suites: trixie-testing
   Components: main
   Signed-By: /usr/share/keyrings/flickos-archive-keyring.asc
   EOF
   sudo apt update && sudo apt install PACKAGE
   ```

   They get fixes with `sudo apt update && sudo apt upgrade`, and leave by
   deleting that file (the package stays until its release replaces it).
4. **Release:** `dch -v 1.0 -D trixie "…"` and an ordinary `repo/publish.sh`.
   Take the test versions out of the suite when they are no longer needed:
   `reprepro -b repo remove trixie-testing PACKAGE`.

A test version installed by hand from a `.deb` (`1.0` built locally before it
had `~test1`) sorts *above* the test versions; go back to them with
`sudo apt install --allow-downgrades PACKAGE=1.0~test1`.

### Verifying the published repo

From any machine:

```sh
curl -fsSL https://dvbondoy.github.io/flickos-apt/dists/trixie/InRelease | head -20
curl -fsSL https://dvbondoy.github.io/flickos-apt/dists/trixie-community/InRelease | grep dep11
```

It should start with `-----BEGIN PGP SIGNED MESSAGE-----` and list `Packages`
files. Then on a FlickOS system (or VM):

```sh
sudo apt update                       # no GPG or 404 errors
apt policy flickos-settings           # shows your new version as candidate
sudo apt upgrade
```

## Keep `repo/db/` or you lose history

`repo/db/` and `repo/public/` are not in git. They exist only on the machine
where you publish. If you lose them, run `repo/publish.sh` again. It rebuilds
the repo with the **current** version of each package, which is all apt needs.
Only older versions are lost. The community apps come back with
`repo/community/publish.sh`, as long as CI's artifacts of their builds are
younger than 90 days (otherwise re-run the *Community apps* workflow on
`main`).

## Managing repo contents

```sh
reprepro -b repo list trixie                         # what's published
reprepro -b repo remove trixie flickos-wallpapers    # remove a package
reprepro -b repo export                              # re-sign/re-export indexes
reprepro -b repo check                               # consistency check
```

After any change, run `repo/upload.sh` again.

## Moving the repository (e.g. to apt.flickos.org)

Installed systems learn the repository address from
`/etc/apt/sources.list.d/flickos.sources`, which comes from
`flickos-archive-keyring`. They can only receive a new address **from the old
one**, so the order matters:

1. **Host the repository at the new address too.** Upload the same `repo/public/`
   content there, e.g. to `https://apt.flickos.org/`. Check it with the `curl`
   command above.
2. **Change the address** in
   `packages/flickos-archive-keyring/etc/apt/sources.list.d/flickos.sources`
   (`URIs:` line). Also update `repo/upload.sh` and this page.
3. **Bump and publish** `flickos-archive-keyring`
   (`dch -i -D trixie "Move repository to apt.flickos.org."`), then upload to
   **both** locations.
4. **Keep uploading to both** for a transition period (e.g. 6–12 months), so
   systems that were offline for a while still receive the package with the new
   address.
5. After that, stop updating the old location. Leave a README there pointing to
   the new address.

New ISOs pick up the new address automatically, because it comes from the package.

## Adding the repo by hand (non-FlickOS Debian trixie)

For testing FlickOS packages on a plain Debian system:

```sh
sudo curl -fsSL -o /usr/share/keyrings/flickos-archive-keyring.asc \
    https://dvbondoy.github.io/flickos-apt/flickos-archive-keyring.asc
sudo tee /etc/apt/sources.list.d/flickos.sources <<'EOF'
Types: deb
URIs: https://dvbondoy.github.io/flickos-apt
Suites: trixie
Components: main
Signed-By: /usr/share/keyrings/flickos-archive-keyring.asc
EOF
sudo apt update && sudo apt install flickos-desktop
```

## Key rotation (rare)

The key never expires (`new-key.sh` creates it with `never`). Rotate only if the
key is compromised or you want stronger crypto. The safe order:

1. Create the new key: `gpg --quick-gen-key "FlickOS Archive Signing Key 2 <…>" rsa4096 sign never`.
2. Export **both** public keys into the keyring package:
   `gpg --armor --export OLD_FPR NEW_FPR > packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc`
3. Bump `flickos-archive-keyring`'s version, publish, and **wait** until users
   have upgraded. They then trust both keys.
4. Switch `SignWith:` in `repo/conf/distributions` to the new fingerprint, then
   run `reprepro -b repo export` and `repo/upload.sh`.
5. Later, export only the new key into the keyring package, bump, and publish again.

If the key was **stolen**, import and publish the revocation certificate
(`gpg --import ~/.gnupg/openpgp-revocs.d/OLD.rev`), do the steps above quickly,
and tell users.
