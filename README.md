# FlickOS

FlickOS is a lightweight Linux distribution. Version **2.0** is based on
Debian 13 (trixie) with a Wayland desktop built on [labwc](https://labwc.github.io/),
and ships as a bootable live ISO with the Calamares graphical installer.
(FlickOS 1.x was based on Ubuntu 20.04 and LXLE.)

- **Downloads:** https://sourceforge.net/projects/flickos/files/
- **Package repository:** https://dvbondoy.github.io/flickos-apt/
- **Issues:** https://github.com/dvbondoy/FlickOS/issues
- **Community:** https://www.reddit.com/r/flickos/
- **Website:** https://flickos.net
- **License:** GPL-3.0-or-later ([LICENSE](LICENSE)). Some files have their own
  license (wallpapers from Unsplash, installer settings from Debian): see each
  package's `debian/copyright`.
- **Name and logo:** a changed FlickOS you share needs its own name and logo;
  see [TRADEMARKS.md](TRADEMARKS.md).

This repository contains everything needed to build it:

- the **live-build configuration** that turns Debian packages into an ISO,
- the **FlickOS Debian packages** (desktop meta-package, default settings, repo keyring),
- the **apt repository tooling** that publishes those packages so installed systems get updates,
- the **CI workflow** that builds the ISO on GitHub.

## Quick start

On a Debian 13 machine:

```sh
sudo apt install live-build build-essential debhelper dpkg-dev devscripts reprepro rsync wget \
                 qemu-system-x86 qemu-utils ovmf xorriso \
                 meson pkgconf gettext libgtk-3-dev \
                 libgtk-layer-shell-dev libjson-c-dev libwayland-dev wayland-protocols

tools/build-iso.sh            # clean + build packages + build FlickOS-64bit-v2.0.iso (30–50 min)
tools/boot-test.py            # headless boot test: boots, logs in, checks the desktop
tools/test-iso.sh             # boot it in a QEMU window (UEFI; --bios for BIOS)
```

`packages/build.sh` needs the repository public key to exist, and the ISO build
needs the apt repository to be online. On a fresh checkout, follow the one-time
setup in [docs/05-apt-repository.md](docs/05-apt-repository.md) first.

## Documentation

Read these in order the first time. Afterwards, use them as reference.

| Doc | What it covers |
|---|---|
| [01 – Overview](docs/01-overview.md) | How the pieces fit together, repository layout, boot flow |
| [02 – Building and testing](docs/02-building-and-testing.md) | Building the ISO locally, testing in QEMU (BIOS and UEFI), installing to a VM disk |
| [03 – live-build configuration](docs/03-live-build-config.md) | `auto/config`, package lists, hooks, boot menu, adding files to the image |
| [04 – Packages](docs/04-packages.md) | The FlickOS packages, changing them, versioning, creating a new package |
| [05 – Apt repository](docs/05-apt-repository.md) | Signing key, publishing to SourceForge, moving the repository, key backup and rotation |
| [06 – CI and releases](docs/06-ci-and-releases.md) | Version number, GitHub Actions workflow, SourceForge uploads, release checklist |
| [07 – Troubleshooting](docs/07-troubleshooting.md) | Common failures and how to fix them |
| [08 – Reference](docs/08-reference.md) | Command cheat sheet, file index, glossary, external manuals |
| [09 – Customizing](docs/09-customizing.md) | How FlickOS is put together and how to change it: desktop, apps, menus, keybindings, installer, boot menu, boot splash, OS name, firewall |
| [10 – Custom builds](docs/10-custom-builds.md) | Building a variant for someone else: site defaults, a variant meta-package, rebranding, a client apt suite, unattended and OEM installs |
| [Design guidelines (HIG)](docs/hig/README.md) | How FlickOS programs look, behave, read and are built: principles, windows, writing, style, accessibility, performance, packaging, code. Every package follows them; review changes with its checklist |
