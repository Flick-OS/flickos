# Releasing the next version of FlickOS

A trimmed, repeatable checklist for every release **after** v2.0 — it assumes
the one-time setup is already done: the apt repo signing key exists
(`repo/conf/distributions` has a `SignWith:` fingerprint), the apt repo is
hosted at https://dvbondoy.github.io/flickos-apt/, and (optionally) the
`SF_USER`/`SF_SSH_PRIVATE_KEY` CI secrets are set on the GitHub repo. Not part
of the project docs (see `docs/06-ci-and-releases.md` for the full picture,
background and troubleshooting) — feel free to move, rename or delete this
file.

Replace `X.Y` below with the new version, e.g. `2.1`.

## 1. Prepare

- [ ] Every changed package has a bumped changelog (`dch -i -D trixie "..."`,
      never edit `debian/changelog` by hand, never leave `UNRELEASED`):
      ```sh
      grep -l UNRELEASED packages/*/debian/changelog   # must print nothing
      ```
- [ ] Set the new version in **both** places (`build-iso.sh` aborts if they differ):
  - `FLICKOS_VERSION="X.Y"` in `packages/flickos-branding/usr/lib/flickos-release`,
    then bump that package: `cd packages/flickos-branding && dch -i -D trixie "FlickOS X.Y." && cd -`
  - `version`, `shortVersion`, `versionedName`, `shortVersionedName` in
    `packages/flickos-installer/etc/calamares/branding/flickos/branding.desc`,
    then bump that package too.
- [ ] Confirm `flickos.sources` does **not** have `Enabled: no`:
      ```sh
      grep -i '^Enabled:' packages/flickos-archive-keyring/etc/apt/sources.list.d/flickos.sources
      ```
- [ ] Publish the apt repo and confirm it's live:
      ```sh
      repo/publish.sh && repo/upload.sh
      curl -fsSI https://dvbondoy.github.io/flickos-apt/dists/trixie/InRelease
      ```
      GitHub Pages can serve stale files for up to ~10 minutes after a push —
      re-check if this 404s or the hash looks wrong.
- [ ] Commit everything:
      ```sh
      git add -A && git commit -m "Prepare FlickOS X.Y"
      ```
- [ ] Write release notes: what's new, known issues.

## 2. Build and test locally

```sh
tools/build-iso.sh --purge          # → FlickOS-64bit-vX.Y.iso, SHA256SUMS
tools/boot-test.py --strict         # must pass
tools/test-iso.sh --bios            # boot menu + desktop
tools/test-iso.sh --uefi
tools/test-iso.sh --reset --install # Calamares install, reboot, log in, labwc starts
tools/test-iso.sh --disk            # sudo apt update && sudo apt upgrade — no errors
```

## 3. Push and wait for CI

```sh
git push
```
Wait for the `main` branch workflow in GitHub Actions to pass (build + boot test).

## 4. Tag — this is the irreversible, public step

```sh
git tag -a vX.Y -m "FlickOS X.Y"
git push origin vX.Y
```

CI rejects any tag that isn't `v` + `FLICKOS_VERSION`, so this only works if
step 1's version bump is correct.

## 5. After the tag

- [ ] Watch the tagged workflow run. If `SF_USER`/`SF_SSH_PRIVATE_KEY` aren't
      set as repo secrets, it skips the SourceForge upload — run
      `tools/upload-release.sh` by hand instead.
- [ ] On SourceForge → **Files** → `vX.Y`:
  - upload the release notes as `README.md` in that folder,
  - click ⓘ next to `FlickOS-64bit-vX.Y.iso` → **Default Download For** →
    select all → **Save**.
- [ ] Update the SourceForge project summary/description if the base or
      features changed.
- [ ] On GitHub → **Releases** → `vX.Y`: paste the release notes (the release
      itself is auto-created with just `SHA256SUMS` — the ISO is too big to attach).
- [ ] Download the ISO from SourceForge and verify: `sha256sum -c SHA256SUMS`.
- [ ] Announce on r/flickos.

## If a release turns out broken

```sh
git push --delete origin vX.Y
git tag -d vX.Y
```
Delete the GitHub Release. On SourceForge, hide or delete the files in `vX.Y/`
and restore the previous version's default download. Fix the issue, bump to
`X.Y.1`, and release again — never reuse a version number people may already
have downloaded.
