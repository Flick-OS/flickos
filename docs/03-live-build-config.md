# 03 – live-build configuration

live-build reads **`auto/config`** (the build options) and **`config/`** (what
goes into the image). The Debian Live Manual (see [08 – Reference](08-reference.md))
is the full reference. This page covers what FlickOS uses.

## Rule of thumb: package, or live-build config?

| Put it in… | When |
|---|---|
| A **FlickOS package** (`packages/`) | It should exist on **installed** systems and may need updates later: apps, config files, themes, wallpapers |
| **live-build config** (`config/`) | It's about **building the image** or only matters in the **live session**: kernel, installer, live tools, boot options |

When unsure, use a package.

## `auto/config`: build options

`auto/config` is a shell script that calls `lb config noauto` with every option.
`lb config` runs it automatically. **Change options only here**, never in the
generated `config/common`, `config/binary`, etc. Those get deleted by `lb clean`.

| Option | Value | Meaning |
|---|---|---|
| `--distribution` | `trixie` | Debian release to build from |
| `--architectures` | `amd64` | CPU architecture |
| `--archive-areas` | `main contrib non-free non-free-firmware` | Debian sections enabled (needed for firmware) |
| `--mirror-bootstrap`, `--mirror-binary` | `http://deb.debian.org/debian/` | Mirror used during build / written into the installed system |
| `--binary-images` | `iso-hybrid` | ISO that also boots when written raw to USB |
| `--bootloaders` | `syslinux,grub-efi` | syslinux for BIOS, GRUB for UEFI |
| `--debian-installer` | `none` | No Debian text installer (Calamares is used) |
| `--apt-recommends` | `false` | Don't auto-install Recommends (keeps image small). **This applies to every package**, not just FlickOS's: `0050-flickos-recommends.hook.chroot` installs `flickos-desktop`'s Recommends, but anything else's must be listed explicitly. Missing one can break the image silently: without `user-setup` (recommended by live-config) the live user is never created and autologin fails |
| `--apt-indices` | `false` | Don't ship apt package lists in the image. Users run `apt update` first |
| `--firmware-chroot` | `true` | Install every firmware package in the archive (Wi-Fi, GPU, sound…). Firmware for hardware FlickOS can't run on is removed again by `0060-trim-firmware.hook.chroot` |
| `--firmware-binary` | `false` | Only used by the Debian installer (firmware on the ISO outside the system), which FlickOS doesn't use |
| `--memtest` | `none` | No memtest boot entry |
| `--updates`, `--security` | `true` | Enable trixie-updates and security repos |
| `--backports` | `false` | No trixie-backports |
| `--iso-application`, `--iso-volume`, `--iso-publisher`, `--iso-preparer` | FlickOS… | ISO metadata. `--iso-volume` is `FlickOS ${FLICKOS_VERSION} amd64`: `auto/config` reads the version from `packages/flickos-branding/usr/lib/flickos-release` |
| `--image-name` | `flickos` | live-build's output name `flickos-amd64.hybrid.iso`. `tools/build-iso.sh` renames it to `FlickOS-64bit-vVERSION.iso` |
| `--bootappend-live` | `boot=live components quiet splash username=user hostname=flickos` | Kernel command line for the live session |
| `--bootappend-live-failsafe` | `boot=live components memtest noapic … nosplash vga=788 username=user hostname=flickos` | Kernel command line for the *safe mode* boot entry (live-build's default plus the FlickOS user and hostname) |

After editing `auto/config`: `sudo lb clean && lb config && sudo lb build`.

Useful extra kernel options for `--bootappend-live` (also typeable at the boot
menu): `noautologin`, `nottyautologin`, `locales=de_DE.UTF-8`,
`keyboard-layouts=de`, `timezone=Europe/Berlin`. See `man live-config`.

## `config/package-lists/`: what's installed

Each `*.list.chroot` file is a plain list of package names, one per line.
Lines starting with `#` are comments. All lists are combined, so file names
are just for organizing.

| File | Contents | Why here, not in `flickos-desktop` |
|---|---|---|
| `flickos.list.chroot` | `flickos-desktop` | Pulls in the whole desktop. See [04 – Packages](04-packages.md) |
| `system.list.chroot` | `linux-image-amd64`, `systemd-sysv` | Kernel/init belong to the image, not a desktop meta-package |
| `live.list.chroot` | `live-boot`, `live-config`, `live-config-systemd`, `user-setup`, `live-tools` | Live-session only. `user-setup` and `live-tools` are only *recommended* by live-config, so they must be listed explicitly (see the `--apt-recommends` note above) |
| `installer.list.chroot` | `calamares`, `flickos-installer` | Installer, live-session only ([09](09-customizing.md#installer)) |

To add a package to every FlickOS install, add it to `flickos-desktop`
instead of a list. A package list only affects the ISO, and nothing
reinstalls it later if a user removes it.

**What happens to live-only packages on install:** Calamares copies the whole
live filesystem to disk, then its `packages` module
(`/etc/calamares/modules/packages.conf` from `flickos-installer`)
removes `live-boot`, `live-config`, `live-config-systemd`, `live-tools`,
`calamares` and `flickos-installer`.

live-build also supports `*.list.chroot_install` (in the image and installed systems)
and `*.list.chroot_live` (live-only) suffixes. live-build records the live-only
packages in `live/filesystem.packages-remove` on the ISO. FlickOS doesn't
use these yet, because Calamares's removal list above is separate.

**`*.list.binary`: package pool on the medium.** These packages (with all their
dependencies) are not installed in the image but put into `/pool` and `/dists`
on the ISO, an apt repository that Calamares's `sources-media` job adds to the
target system during the install. `grub-pc.list.binary` and
`grub-efi.list.binary` hold the bootloaders, which `bootloader-config`
installs for the firmware it finds (they conflict, so they can't both be in the
image), and `cryptsetup.list.binary` holds `cryptsetup-initramfs` for encrypted
installs. Keep the GRUB lists separate: live-build downloads each list in one apt
transaction. Without the pool the install fails offline with *Package grub-pc
has no installation candidate*.

Because the image has no apt indices (`--apt-indices false`), apt in the
installer only knows the installed packages and the pool when offline. Every
package name in Calamares's `packages.conf` must therefore be installed in the
image, or the removal fails with *Unable to locate package*.

## `config/hooks/normal/`: scripts run during the build

Files named `NNNN-name.hook.chroot` run **inside the image** as root, in
alphabetical order, after all packages are installed. Use them for things a
package can't reasonably do.

| Hook | Does |
|---|---|
| `0010-sanity.hook.chroot` | Fails the build if a package the image needs is missing (e.g. `user-setup`, which live-config only *recommends*). Runs before the slow squashfs and ISO steps. Edit its `REQUIRED` list when the image gains a must-have package |
| `0050-flickos-recommends.hook.chroot` | Installs the Recommends of `flickos-desktop` (because `--apt-recommends false`), without recursing into *their* recommends |
| `0060-trim-firmware.hook.chroot` | Removes firmware for hardware FlickOS can't run on: datacenter network cards and switch chips, NVIDIA Tesla GPUs, server HBAs, Qualcomm ARM SoCs (~277 MB in the 2.0 build; the Qualcomm packages aren't installed by live-build at all, but stay on the list in case that changes). Simulates the removal first and fails the build if apt would remove anything else. Edit its `TRIM` list to change what's removed |
| `0100-services.hook.chroot` | Enables NetworkManager, sets `graphical.target` as default |
| `0150-flathub.hook.chroot` | Adds the Flathub remote for Flatpak (needs network during the build) |
| `0200-firewall.hook.chroot` | Turns on the ufw firewall ([09](09-customizing.md#firewall)) |

Rules:

- Start with `#!/bin/sh` and `set -e`, so a failing command fails the build
  instead of silently producing a broken image.
- Make them executable: `chmod +x config/hooks/normal/NNNN-*.hook.chroot`.
- Number FlickOS hooks **0001–0999**. `lb config` adds symlinks to
  live-build's standard cleanup hooks (numbered 1000–9020, git-ignored),
  and yours should run before those.
- There's no network restriction. You can `apt-get install` in a hook.
- `*.hook.binary` hooks run outside the image in the `binary/` folder. Use them
  to change ISO contents, like bootloader menus.

Example: a hook that enables a service:

```sh
#!/bin/sh
set -e
systemctl enable bluetooth
```

## Apt sources: the FlickOS repository

FlickOS does **not** use live-build's `config/archives/` folder. The FlickOS apt
source (`/etc/apt/sources.list.d/flickos.sources`, pointing to
https://dvbondoy.github.io/flickos-apt) and its key come from the
`flickos-archive-keyring` package. That way a package update can change the
repository address on installed systems later
([05](05-apt-repository.md#moving-the-repository-eg-to-flickosnet)).

If you ever need `config/archives/` for another repository:

- `NAME.list.chroot`: used **only during the build**, then removed.
- `NAME.list.binary`: stays in the image and on installed systems.
- `NAME.key.chroot` / `NAME.key.binary`: key files. Avoid them: live-build puts
  them in `/etc/apt/trusted.gpg.d/`, which makes apt trust the key for *every*
  repository. Prefer a keyring package with `Signed-By:`.
- `@DISTRIBUTION@` in a list file is replaced by `trixie` at build time.

Important: at the end of the chroot stage, live-build runs `apt update` with all
sources installed in the image, including `flickos.sources`. **If the FlickOS
repository is unreachable or not correctly signed, the build fails.** Packages
themselves are installed from `config/packages.chroot/`, not from the online repo.

## `config/bootloaders/`: ISO boot menu

Files here are copied over live-build's own boot menu templates
(`/usr/share/live/build/bootloaders/`), so only files FlickOS changes are in the
repo: splash images, entry names, colors and a 10-second timeout, for both
syslinux (BIOS) and GRUB (UEFI). Details and the placeholder trap in `grub.cfg`:
[09 – Boot menu](09-customizing.md#boot-menu).

## `config/packages.chroot/`: local packages

Generated by `packages/build.sh` and git-ignored. live-build turns every
`*_all.deb` / `*_amd64.deb` here into a temporary apt repo during the build,
so package lists and hooks can install them by name. That's why an ISO
always contains the FlickOS packages exactly as they are in your working tree.

## Adding files directly to the image

Prefer packages. For live-only files, live-build supports:

| Folder | Copied to |
|---|---|
| `config/includes.chroot_after_packages/` | The root filesystem, after packages are installed (e.g. `config/includes.chroot_after_packages/etc/foo` → `/etc/foo`) |
| `config/includes.chroot_before_packages/` | The root filesystem, before packages are installed (e.g. preseeding config) |
| `config/includes.binary/` | The ISO itself, outside the squashfs (e.g. a README on the disc) |

Files added this way are copied to installed systems by Calamares, and never
updated afterwards. For something like `/etc/systemd/...` overrides, make sure
they're harmless on an installed system, or put them in a package.
