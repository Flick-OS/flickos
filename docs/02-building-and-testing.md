# 02 – Building and testing

## Requirements

- A **Debian 13 (trixie)** host. Other distros' `live-build` versions differ
  and may produce broken images. On another OS, use a trixie VM or container.
- **Root access** (`sudo`). live-build uses `chroot` and `mount`.
- **~15 GB free disk** and an internet connection. Packages download from
  `deb.debian.org`.

Install the tools once:

```sh
sudo apt install live-build build-essential debhelper dpkg-dev devscripts reprepro rsync wget \
                 qemu-system-x86 qemu-utils ovmf xorriso \
                 meson pkgconf gettext libgtk-3-dev \
                 libgtk-layer-shell-dev libjson-c-dev libwayland-dev wayland-protocols
```

| Tool | Used for |
|---|---|
| `live-build` | Building the ISO (`lb` command) |
| `debhelper`, `dpkg-dev` | Building `.deb` packages |
| `devscripts` | `dch` for editing `debian/changelog` |
| `reprepro` | Managing the apt repository |
| `wget` | Required by live-build's firmware step |
| `qemu-system-x86`, `qemu-utils`, `ovmf` | Testing in a VM (`qemu-img` for disks, OVMF for UEFI) |
| `xorriso` | Extracting the kernel from the ISO for the headless boot test |
| `meson`, `pkgconf`, `gettext`, `lib…-dev`, `wayland-protocols` | Compiling `sfwbar`, the only FlickOS package with C code (its `Build-Depends`) |

For KVM acceleration (much faster VMs), add yourself to the `kvm` group once:
`sudo adduser $USER kvm`, then log out and back in.

## The three scripts

| Script | Does |
|---|---|
| `tools/build-iso.sh` | Clean → build FlickOS packages → `lb config` → `lb build` → `SHA256SUMS` |
| `tools/boot-test.py` | Boots the ISO headless, logs in over the serial console, runs checks |
| `tools/test-iso.sh` | Opens the ISO or a test install in a QEMU window for hands-on testing |

A normal development loop:

```sh
tools/build-iso.sh && tools/boot-test.py && tools/test-iso.sh
```

## Building: `tools/build-iso.sh`

```sh
tools/build-iso.sh            # normal build; keeps the package download cache
tools/build-iso.sh --purge    # also deletes the cache (releases, or when builds act strangely)
```

Run it as your normal user. It asks for your sudo password once at the start.
When run as root (in CI), it skips sudo.

Output in the repository root:

| File | What it is |
|---|---|
| `FlickOS-64bit-v2.0.iso` | The bootable image |
| `SHA256SUMS` | Checksum of the ISO |
| `build.log` | Full output of the package build, `lb config` and `lb build`. Check it when something fails |
| `flickos-amd64.packages` | Every package and version in the image |
| `flickos-amd64.contents` | Every file in the image |

live-build writes `flickos-amd64.hybrid.iso` (from `--image-name flickos` in
`auto/config`). The script then renames it to `FlickOS-64bit-vVERSION.iso`, the
naming used on SourceForge since FlickOS 1.x, with `VERSION` taken from
`packages/flickos-branding/usr/lib/flickos-release`
([06 – The version number](06-ci-and-releases.md#the-version-number)).

Before building, the script checks the installer's `branding.desc` shows the same
version, and stops with *Version mismatch* if not. When cleaning, it deletes
older `FlickOS-64bit-v*.iso` files, since each is over 2 GB.

### What the script does, step by step

You can run these by hand if you need to debug a single step:

```sh
sudo lb clean             # 1. (add --purge to also drop cache/)
sh packages/build.sh      # 2.
lb config                 # 3.
sudo lb build             # 4.
```

1. **`sudo lb clean`** runs `auto/clean`. It removes `chroot/`, `binary/`, the
   stage files in `.build/` and the config files `lb config` generated. It keeps
   `cache/` (downloaded `.deb` files) unless you pass `--purge`. Without cleaning,
   `lb build` skips stages it thinks are already done, and your changes don't
   make it into the image.
2. **`packages/build.sh`** builds every `packages/*/` source package with
   `dpkg-buildpackage` in a scratch copy (`packages/.build/`), then copies the
   `.deb` files into `config/packages.chroot/`. live-build turns that folder into
   a temporary local apt repo during the build, so `flickos-desktop` can be
   installed by name.
3. **`lb config`** runs `auto/config`, which calls `lb config noauto` with all
   of FlickOS's options. This writes `config/common`, `config/bootstrap`,
   `config/chroot`, `config/binary` and `config/source`.
4. **`sudo lb build`** runs three stages:
   - **bootstrap:** `debootstrap` creates a minimal Debian system in `chroot/`.
   - **chroot:** adds apt sources, installs everything in `config/package-lists/`,
     runs `config/hooks/`, then removes the build-only apt sources.
   - **binary:** compresses `chroot/` into a squashfs, adds kernel, initrd
     and bootloaders, and writes the ISO.

## Automated testing: `tools/boot-test.py`

```sh
tools/boot-test.py                     # test the newest FlickOS-64bit-v*.iso
tools/boot-test.py --verbose           # also print the serial console live
tools/boot-test.py --iso some.iso      # test a specific ISO
tools/boot-test.py --strict            # fail if any systemd unit failed
tools/boot-test.py --timeout 900       # wait longer for the login prompt
tools/boot-test.py --max-used-mb 900   # also fail if the idle desktop uses more memory
```

It needs no window and no interaction. The same script runs in CI.

### How it works

1. **Extracts the boot files from the ISO** with `xorriso`: the kernel, the initrd
   and the kernel command line from the first entry of `/isolinux/live.cfg`
   (or `/boot/grub/grub.cfg`).
2. **Boots them directly with QEMU**, skipping the bootloader. The live boot
   menus wait for a keypress, so they can't be automated. The command line is the
   ISO's own, minus `quiet splash`, plus `console=tty0 console=ttyS0,115200`, so
   kernel and systemd messages and a login prompt appear on the serial port. The
   ISO is still attached as a CD, which is where live-boot finds the system.
3. **Logs in on the serial console** as `user` / `live`. The graphical session
   on tty1 (autologin + labwc) starts independently, just as on real hardware.
4. **Waits for systemd** (`systemctl is-system-running --wait`). `degraded`
   (some unit failed) is a warning, or a failure with `--strict`. The failed
   units are printed.
5. **Runs the checks** from the `CHECKS` list at the top of the script. Each
   one is a shell command that must exit 0. Some retry for a while, because the
   desktop starts in the background.
6. **Takes a screenshot** of the virtual screen through QEMU's QMP socket.
7. **Reports memory use**: `MemTotal − MemAvailable` from `/proc/meminfo`
   (memory the system can't give back without swapping), plus the 15 largest
   processes. With `--max-used-mb N` it also fails when more than N MB are in use.

The bootloaders themselves (syslinux, GRUB) are **not** covered. Test those by
hand with `tools/test-iso.sh`, at least before each release.

### Results

Everything is printed as `PASS`/`WARN`/`FAIL` lines. Files in `boot-test/`:

| File | Contents |
|---|---|
| `serial.log` | Everything the guest printed on the serial console: kernel log, systemd messages, command output |
| `screen.png` | Screenshot of the desktop at the end. It should show labwc with waybar |
| `memory.txt` | Memory in use with the desktop idle, and the largest processes |

**Reading the memory number:** it's measured in the **live session**, which runs
from RAM (changed files live in a RAM overlay), with nothing opened. An installed
system uses somewhat less. Compare releases against each other rather than
against other distributions. When the number grows noticeably, `memory.txt`
shows which process caused it. Once you've seen a few builds, set
`--max-used-mb` in the CI workflow a little above the usual value to catch regressions.

Exit codes: `0` all passed, `1` a check failed, `2` setup problem (missing
tool, no ISO), `3` never reached a login prompt, or login failed.

Timeouts: 300 s to reach the login prompt with KVM, 1200 s without. Check retry
times are multiplied by 4 without KVM.

### Adding a check

Edit `CHECKS` in `tools/boot-test.py`:

```python
CHECKS = [
    ...
    ("bluetooth active", "systemctl is-active --quiet bluetooth", 30),
    ("firefox installed", "command -v firefox-esr", 0),
]
```

Each entry is `(description, shell command, seconds to keep retrying)`.
Commands run as `user` in a bash login shell. `sudo -n` works without a password
in the live session. Use `0` for things that are already true at login, and a
retry time for services or desktop programs that start in the background.

## Manual testing: `tools/test-iso.sh`

Opens a QEMU window. Always check a new ISO by hand before a release, on
**both** firmware types, because they use different bootloaders (syslinux vs GRUB).

```sh
tools/test-iso.sh                    # live session, UEFI
tools/test-iso.sh --bios             # live session, BIOS
tools/test-iso.sh --install          # live session + persistent 20 G test disk (UEFI) → run the installer
tools/test-iso.sh --install --bios   # same, BIOS
tools/test-iso.sh --disk             # boot the installed test disk, no ISO
tools/test-iso.sh --reset --install  # throw away the old test disk and start over
```

Options: `--iso FILE` (default: newest `FlickOS-64bit-v*.iso`), `--mem 8G`
(default `4G`), `--size 40G` (disk size when created, default `20G`).

The test disk (`disk.qcow2`), its UEFI variables (`OVMF_VARS.fd`, which store
the boot entry Calamares creates) and the firmware used for installing are kept
in `.test-vm/`. `--disk` automatically uses the firmware the disk was installed
with. For plain live sessions, UEFI uses throwaway variables, so they never mess
up the test install.

With `--install`, the VM boots the ISO **once**. When Calamares finishes and
you choose restart, the VM boots from the installed disk.

### What to check in the live session

- [ ] FlickOS boot menu appears (logo, *Start FlickOS*), boots by itself after 10 s
- [ ] FlickOS boot splash (logo + spinner) instead of text, then labwc automatically
- [ ] waybar is visible, nm-applet shows, network works (`curl -I https://deb.debian.org`)
- [ ] `Super+Return` opens foot, `Super+D` opens fuzzel, `Super+E` opens Thunar, with the path as buttons
- [ ] Right-click desktop shows the root menu
- [ ] Audio: `wpctl status` lists a sink
- [ ] `apt update` succeeds, which means the FlickOS repo is reachable and correctly signed
- [ ] `apt policy flickos-desktop` shows the FlickOS repo as a source
- [ ] Keybindings: `Alt+Tab`, `Super+Arrows` (snap), volume keys, `Print` (screenshot notification)
- [ ] Right-click menu shows **Install FlickOS**; the installer opens with FlickOS branding and working links on its welcome page
- [ ] *Office → Writer* opens LibreOffice; a video file opens in VLC; play/pause key controls VLC
- [ ] *Settings → Desktop Layout & Style* opens the chooser in Arc-Dark with three previews; applying Cupertino, then Redmond, changes the panel and window buttons, and the network icon comes back
- [ ] Applying *Light* recolors GTK apps, icons, panel, window borders, the root menu, fuzzel, notifications (`notify-send Hi`) and **new** foot windows; *Dark* switches back
- [ ] *Settings → Appearance* opens nwg-look; a GTK theme chosen there (e.g. Adwaita) is kept when switching to Light and back

### What to check on the installed system

- [ ] The graphical login screen appears (Arc-Dark, FlickOS wallpaper, clock), **no** autologin unless it was chosen in the installer
- [ ] The keyboard layout chosen in the installer works in the password field
- [ ] Logging in starts labwc; a wrong password shows an error and asks again
- [ ] Ctrl+Alt+F1 shows a text login prompt, and logging in there also starts labwc
- [ ] A second install with *Log in automatically* checked boots straight to the desktop (`getent group autologin` lists the user)
- [ ] The first login opens *Desktop Layout & Style*; choosing Cupertino and Light applies right away. After logging out and in, the chooser doesn't open again and the choice is kept
- [ ] `sudo apt update && sudo apt upgrade` works
- [ ] `cat /etc/apt/sources.list.d/flickos.sources` shows `URIs: https://dvbondoy.github.io/flickos-apt`
- [ ] `dpkg -l 'live-*' flickos-installer calamares` shows they're gone (Calamares removed them)
- [ ] Right-click menu has **no** *Install FlickOS* entry
- [ ] The keyboard layout chosen in the installer works in foot
- [ ] Leaving the VM idle for 5 minutes locks the screen
- [ ] Boot shows the FlickOS splash; tty2 (Ctrl+Alt+F2) shows `FlickOS 2.0 (Debian 13)` above the login prompt
- [ ] `sudo ufw status` shows `Status: active`

### Without the script

The equivalent raw QEMU commands, if you ever need to tweak something:

```sh
# BIOS
qemu-system-x86_64 -enable-kvm -cpu host -m 4G -smp 2 -device virtio-vga \
    -cdrom FlickOS-64bit-v2.0.iso

# UEFI with persistent variables and a test disk
qemu-img create -f qcow2 disk.qcow2 20G
cp /usr/share/OVMF/OVMF_VARS_4M.fd vars.fd
qemu-system-x86_64 -enable-kvm -cpu host -m 4G -smp 2 -device virtio-vga \
    -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
    -drive if=pflash,format=raw,file=vars.fd \
    -drive file=disk.qcow2,if=virtio \
    -cdrom FlickOS-64bit-v2.0.iso -boot once=d
```

## Measuring what a change costs

HIG PERF-7 asks every new program, daemon, dependency or feature to state its
cost. Two scripts give the numbers:

```sh
tools/package-cost.py swappy                  # packages and KB a package would add to the image
tools/package-cost.py config/packages.chroot/flickos-foo_1.0_all.deb
tools/measure.py PID                          # CPU, PSS/Private memory and wakeups until it exits
tools/measure.py --tree -- flickos-control    # start a program, count the processes it starts too
```

`package-cost.py` asks apt to simulate the install without Recommends, the way
the image installs packages. It compares with the **image**, not with the build
host: the last build's package list, `flickos-amd64.packages`, becomes a
pretend dpkg status file. So a library the host happens to have (GTK 4 from an
editor) still counts when the image lacks it. Without that list (after
`lb clean`, before the next build) or with `--host`, it compares with the host
and says so. No sudo either way.

`measure.py` only reads `/proc`, so it can watch the developer's own session.
Wakeups are voluntary context switches a minute: an idle daemon should have
almost none. Stop what you started by PID, never with `pkill NAME`, which on a
FlickOS desktop also hits the session's own copies.

## Writing to a USB stick

```sh
lsblk                                  # find the USB device, e.g. /dev/sdX
sudo dd if=FlickOS-64bit-v2.0.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

`dd` overwrites the target without asking. Check the device name twice.
