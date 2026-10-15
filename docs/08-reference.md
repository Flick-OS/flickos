# 08 – Reference

## Command cheat sheet

### Everyday

```sh
tools/build-iso.sh                  # clean + packages + ISO   (--purge: also drop cache)
tools/boot-test.py                  # headless boot test       (-v: show console, --strict)
tools/test-iso.sh                   # live session, UEFI       (--bios for BIOS)
tools/test-iso.sh --install         # live + test disk, run Calamares   (--reset: new disk)
tools/test-iso.sh --disk            # boot the installed test disk
```

### Packages

```sh
cd packages/NAME && dch -i -D trixie "What changed."   # bump version
sh packages/build.sh                                    # build all
dpkg-deb -c config/packages.chroot/NAME_*_all.deb       # list contents
dpkg-deb -I config/packages.chroot/NAME_*_all.deb       # show metadata
lintian config/packages.chroot/NAME_*_all.deb           # check quality
dpkg-parsechangelog -l packages/NAME/debian/changelog -S Version
```

### Measuring (HIG PERF-7)

```sh
tools/package-cost.py PKG...        # what PKG adds to the image (--host: to this computer)
tools/measure.py PID                # CPU, memory, wakeups   (--tree, -- COMMAND, --for S)
```

### Apt repository

```sh
repo/new-key.sh                               # once, ever
repo/publish.sh                               # build + add to repo
reprepro -b repo list trixie                  # show contents
reprepro -b repo remove trixie NAME           # remove a package
reprepro -b repo export                       # re-sign indexes
repo/upload.sh                                # push to dvbondoy.github.io/flickos-apt
curl -fsSI https://dvbondoy.github.io/flickos-apt/dists/trixie/InRelease   # check it's online
```

### live-build

```sh
lb config                        # generate config from auto/config
sudo lb build                    # build
sudo lb clean                    # clean build + generated config, keep download cache
sudo lb clean --purge            # clean everything including cache
```

### Release

```sh
grep FLICKOS_VERSION packages/flickos-branding/usr/lib/flickos-release   # current version
tools/upload-release.sh                       # ISO + SHA256SUMS → SourceForge files/vX.Y/
git tag -a v2.0 -m "FlickOS 2.0" && git push origin v2.0
```

### Links

| What | URL |
|---|---|
| Downloads (SourceForge Files) | https://sourceforge.net/projects/flickos/files/ |
| Apt repository | https://dvbondoy.github.io/flickos-apt/ (GitHub repo `dvbondoy/flickos-apt`, branch `gh-pages`) |
| Code, CI, issues | https://github.com/dvbondoy/FlickOS |
| Community | https://www.reddit.com/r/flickos/ |
| SourceForge SSH keys | https://sourceforge.net/auth/shell_services |
| Website (planned) | https://flickos.net |

## File index

| Path | Edit? | Purpose |
|---|---|---|
| `auto/config` | ✏️ | All live-build options |
| `auto/clean` | rarely | `lb clean` plus removal of generated config |
| `config/package-lists/*.list.chroot` | ✏️ | Packages in the image |
| `config/hooks/normal/0NNN-*.hook.chroot` | ✏️ | Build-time scripts inside the image |
| `config/packages.chroot/` | ❌ generated | Built FlickOS `.deb`s |
| `config/common`, `config/binary`, `config/bootstrap`, `config/chroot`, `config/source` | ❌ generated | Output of `lb config` |
| `config/hooks/live/`, `config/hooks/normal/[1-9]NNN-*` | ❌ generated | Symlinks to live-build's standard hooks |
| `packages/build.sh` | rarely | Builds all packages |
| `tools/build-iso.sh` | rarely | Full clean ISO build |
| `tools/test-iso.sh` | rarely | QEMU window: live / install / installed disk |
| `tools/boot-test.py` | ✏️ `CHECKS` list | Headless boot test (local + CI) |
| `tools/upload-release.sh` | rarely | Upload ISO + `SHA256SUMS` to SourceForge Files |
| `LICENSE` | no | GPL-3.0 |
| `.test-vm/` | ❌ generated | Test disk and UEFI variables |
| `boot-test/` | ❌ generated | Boot test serial log and screenshot |
| `SHA256SUMS`, `build.log` | ❌ generated | Build outputs |
| `packages/flickos-desktop/debian/control` | ✏️ | Desktop package selection |
| `packages/flickos-settings/` | ✏️ | Desktop config: session, keybindings, menu, startup programs, panel, theme, wallpaper |
| `packages/flickos-greeter/` | ✏️ | Login screen of installed systems (greetd + gtkgreet) |
| `packages/flickos-installer/` | ✏️ | Calamares config + branding, launcher, live menu |
| `tools/make-placeholder-art.sh` | rarely | Regenerates wallpaper, installer, boot menu and boot splash images (Arc-Dark palette; logo rendered from flickos-branding's `flickos.svg`, needs librsvg2-bin) |
| `tools/make-fastfetch-logo.py` | when `flickos.svg` changes | Regenerates flickos-branding's fastfetch logo (`usr/share/flickos/fastfetch/flickos.txt`) from `flickos.svg`; `--preview` prints it without writing |
| `tools/make-layout-previews.sh` | when a layout changes | Regenerates the chooser's `preview.png` per layout (schematic, or from boot-test screenshots) |
| `tools/check-menus.py` | no | Checks the live menu equals the installed menu plus *Install FlickOS*; run by `build-iso.sh` |
| `tools/check-palette.py` | ✏️ when adding a color | Checks all color-bearing files use the Arc-Dark palette and the labwc theme uses valid keys; run by `build-iso.sh` |
| `tools/package-cost.py` | no | Packages and KB a package would add to the image (compares with the last build's `flickos-amd64.packages`) |
| `tools/measure.py` | no | CPU, PSS/Private memory and wakeups of a process (and its children) while it runs |
| `packages/flickos-branding/` | ✏️ `usr/lib/flickos-release` each release | FlickOS version, boot splash, OS name, login banner |
| `config/bootloaders/` | ✏️ | ISO boot menu (syslinux + GRUB) |
| `config/hooks/normal/0200-firewall.hook.chroot` | rarely | Turns on ufw |
| `config/hooks/normal/0060-trim-firmware.hook.chroot` | ✏️ `TRIM` list | Removes firmware for hardware FlickOS can't run on |
| `config/hooks/normal/0150-flathub.hook.chroot` | rarely | Adds Flathub |
| `packages/flickos-archive-keyring/keyrings/*.asc` | only on key rotation | Repo public key |
| `packages/flickos-archive-keyring/etc/apt/sources.list.d/flickos.sources` | when the repo moves | FlickOS apt source (repo URL) |
| `packages/*/debian/changelog` | via `dch` | Package versions |
| `repo/conf/distributions` | rarely | Repo definition + signing key |
| `repo/conf/options` | no | reprepro paths |
| `repo/new-key.sh`, `repo/publish.sh`, `repo/upload.sh` | rarely | Repo scripts |
| `repo/db/`, `repo/public/` | ❌ generated | Repo database / output |
| `.github/workflows/iso.yml` | ✏️ | CI |
| `chroot/`, `binary/`, `cache/`, `.build/`, `FlickOS-64bit-v*.iso`, `build.log` | ❌ generated | Build output |

## Glossary

| Term | Meaning |
|---|---|
| **apt repository** | Web folder with `dists/` (signed indexes) and `pool/` (`.deb` files) that apt downloads from |
| **binary stage** | live-build step that turns `chroot/` into the ISO |
| **bootstrap stage** | live-build step that creates a minimal Debian in `chroot/` with debootstrap |
| **Calamares** | Graphical installer. Copies the live system to disk and configures it |
| **chroot** | Running programs with a folder (e.g. `chroot/`) as their `/`. Here, the image being built |
| **chroot stage** | live-build step that installs packages and runs hooks inside `chroot/` |
| **component** | Section of a repo (`main`, `contrib`, …). FlickOS uses `main` |
| **conffile** | A package file under `/etc`. dpkg preserves user edits on upgrade |
| **codename** | Release name used in apt lines: `trixie` = Debian 13 |
| **debhelper / `dh`** | Tools that do the standard packaging steps automatically |
| **`Depends` / `Recommends`** | Hard vs soft dependency. Removing a Depends removes the package that needs it |
| **dpkg-divert** | Tells dpkg to install another package's file under a different name, so a package can replace it safely |
| **file trigger** | dpkg runs a package's postinst (`triggered`) when files it is interested in change |
| **fingerprint** | 40-hex-character ID of a GPG key |
| **greetd** | Display manager of installed systems. Runs the greeter (gtkgreet in cage) and starts the session after login |
| **hook** | Script live-build runs during the build |
| **hybrid ISO** | ISO that boots both from optical media and when written raw to USB |
| **InRelease** | Signed index file at `dists/trixie/InRelease`. apt checks its signature |
| **keyring package** | Package that installs a repo's public key so apt can verify it |
| **live-boot** | initramfs code that boots from the ISO's squashfs |
| **live-config** | Boot-time scripts that set up the live user, hostname, autologin |
| **meta-package** | Package with no files, only dependencies |
| **native package** | Debian package with no separate upstream source. Version has no `-N` suffix |
| **OVMF** | UEFI firmware for QEMU |
| **QMP** | QEMU's JSON control socket. The boot test uses it for screenshots |
| **serial console** | Text console on the (virtual) serial port `ttyS0`. The boot test reads and types on it |
| **reprepro** | Tool that maintains a signed apt repository |
| **`signed-by`** | apt source option limiting which key may sign that repo |
| **Plymouth** | Program that shows the graphical boot splash and disk password prompt |
| **squashfs** | Compressed read-only filesystem holding the live system |
| **syslinux / GRUB EFI** | Bootloaders for BIOS / UEFI boot |
| **tty1** | First text console. The live session logs in there automatically; on installed systems it's the text login fallback. Either way `flickos-session` starts labwc |

## External documentation

| Topic | Where |
|---|---|
| live-build | Debian Live Manual: https://live-team.pages.debian.net/live-manual/, `man lb_config` |
| live-boot / live-config boot options | `man live-boot`, `man live-config` |
| Debian packaging | Debian New Maintainers' Guide / Guide for Debian Maintainers: https://www.debian.org/doc/devel-manuals, `man dh` |
| `debian/control` fields | Debian Policy ch. 5: https://www.debian.org/doc/debian-policy/ch-controlfields.html |
| reprepro | `man reprepro`, `/usr/share/doc/reprepro/` |
| apt sources format | `man sources.list` |
| labwc config | `man labwc-config`, `man labwc-menu`, `man labwc-actions`, https://labwc.github.io/ |
| Calamares | https://calamares.io/docs/, FlickOS config in `packages/flickos-installer/etc/calamares/` |
| GitHub Actions | https://docs.github.com/actions |
| Debian package search | https://packages.debian.org/trixie/ |
