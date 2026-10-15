# 07 – Troubleshooting

When something fails, first read the **end of `build.log`** (or the CI log).
The first `E:` or `P: … failed` line usually tells you why.

```sh
grep -n -E '^E:|failed|error' build.log | head
```

## Building packages

**`Missing repository public key. Run repo/new-key.sh first.`**
The keyring package has no key file. Run `repo/new-key.sh` on your machine. If
the key already exists in your `~/.gnupg`, re-export it instead:
`gpg --armor --export FINGERPRINT > packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc`.

**`dpkg-checkbuilddeps: error: unmet build dependencies: debhelper-compat (= 13)`**
`sudo apt install debhelper`.

**`dpkg-checkbuilddeps: error: unmet build dependencies: build-essential:native`**
`sudo apt install build-essential`. `dpkg-dev` pulls it in only as a
Recommends, so it's missing after `apt-get install --no-install-recommends`
(as in CI).

**`dpkg-checkbuilddeps: error: unmet build dependencies: meson … libgtk-layer-shell-dev …`** (while building `sfwbar`)
The build host lacks `sfwbar`'s compilers and headers, the only FlickOS
package with C code. Install the last group of the tool list in
[02](02-building-and-testing.md), or `sudo apt install` exactly what the error
names.

**`dh: command not found` / `dpkg-buildpackage: command not found`**
`sudo apt install debhelper dpkg-dev`.

**`debian/rules: Permission denied`**
`chmod +x packages/*/debian/rules`. In git: `git update-index --chmod=+x packages/NAME/debian/rules`.

**`dh_install: … missing files`**
A source path in `debian/install` doesn't exist. Paths are relative to the
package folder (`packages/NAME/`). Check spelling and that the file is committed.

**`dpkg-parsechangelog` / `dch` errors about the changelog format**
The changelog is whitespace-sensitive. The sign-off line starts with exactly
one space and ` -- `, and there are **two** spaces between the email and the date.
Restore it with `git checkout packages/NAME/debian/changelog` and use `dch`.

## Building the ISO

**`lb: command not found`**
`sudo apt install live-build`.

**Build seems to skip your change**
Stage files in `.build/` say that stage is already done. Use `tools/build-iso.sh`,
which always cleans first.

**An option removed from `auto/config` still takes effect**
The generated `config/common` etc. still have it. `sudo lb clean` (which runs
`auto/clean`) deletes them. Then run `lb config` again.

**`E: You need to install wget on your host system.`**
`sudo apt install wget`. Needed by the firmware step.

**`E: Unable to locate package NAME`** (during chroot stage)
- Typo, or the package doesn't exist in trixie. Check https://packages.debian.org/trixie/NAME.
- If it's in `contrib`/`non-free`, check `--archive-areas` in `auto/config`.
- If it's a FlickOS package: `config/packages.chroot/` is empty or stale, so run
  `sh packages/build.sh`.

**`… has unmet dependencies` / `Depends: X but it is not going to be installed`**
Usually a package name that changed between Debian releases, or conflicting
packages. Try it in a trixie container:
`docker run --rm -it debian:trixie sh -c "apt update && apt install -s PACKAGE"`.

**Failure in `0050-flickos-recommends.hook.chroot`**
One of `flickos-desktop`'s Recommends can't be installed (typo or missing
package). The apt error above it names the package. Fix `debian/control`, bump
the version, rebuild the packages.

**`sanity: these required packages are not installed: …`**
A package the image needs wasn't installed, usually because it is only
*Recommended* by another package and the build uses `--apt-recommends false`.
Add it to a file in `config/package-lists/`. The check lives in
`config/hooks/normal/0010-sanity.hook.chroot`.

**`trim-firmware: removing … would also remove: …`**
Debian reorganised its firmware packages, and removing one on the trim list
would now take another package with it. Check what the named package contains
(`apt-cache show NAME`). If it's also useless on amd64 desktops, add it to `TRIM`
in `config/hooks/normal/0060-trim-firmware.hook.chroot`. Otherwise remove the
package that depends on it from `TRIM`.

**A device works in other live ISOs but not in FlickOS (no Wi-Fi, no GPU acceleration)**
Its firmware may have been trimmed. On the machine, `sudo dmesg | grep -i firmware`
shows `failed to load` lines with the file name. Find the package with
`apt-file search FILENAME` on a Debian machine. If it's on the `TRIM` list in
`0060-trim-firmware.hook.chroot`, remove it from the list and rebuild.

**`apt update` fails at the end of the chroot stage: `404 Not Found`, `Could not resolve`, `NO_PUBKEY`, `The repository … is not signed`**
This is the FlickOS repository from
`packages/flickos-archive-keyring/etc/apt/sources.list.d/flickos.sources`:
- `Could not resolve` / 404: the repository isn't uploaded (run
  `repo/publish.sh && repo/upload.sh`), or the URL is wrong. Open
  https://dvbondoy.github.io/flickos-apt/dists/trixie/InRelease in a browser.
- `NO_PUBKEY` / `not signed` / `invalid signature`: the key in
  `flickos-archive-keyring` doesn't match the key reprepro signs with. Compare
  `gpg --show-keys packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc`
  with `SignWith:` in `repo/conf/distributions`. Then `reprepro -b repo export` and `repo/upload.sh`.
- To build while offline or before the repository exists, temporarily add the
  line `Enabled: no` to `flickos.sources`. **Don't release an ISO built like
  that**: installed systems would never get FlickOS updates.

**`repo/upload.sh`: `Permission denied (publickey)`**
GitHub doesn't know your SSH key. Add it at https://github.com/settings/keys
(or `gh auth login`, choosing SSH) and test with `ssh -T git@github.com`. The
account needs write access to `dvbondoy/flickos-apt`.

**`apt update`: `Hash Sum mismatch` on the FlickOS repository right after `repo/upload.sh`**
GitHub Pages' CDN can serve old index files for up to 10 minutes after a push.
Wait and run `apt update` again.

**`tools/upload-release.sh`: `Permission denied (publickey)`**
SourceForge doesn't know your SSH key, or it isn't active yet (can take a few
minutes). Check https://sourceforge.net/auth/shell_services and test with
`sftp dvbondoy@frs.sourceforge.net`. A different account: `SF_USER=name tools/upload-release.sh`.

**`build-iso.sh`: `Version mismatch`**
`FLICKOS_VERSION` in `packages/flickos-branding/usr/lib/flickos-release` and
`version:` in the installer's `branding.desc` differ. Update both
([06](06-ci-and-releases.md#the-version-number)).

**CI: `Tag vX.Y doesn't match FLICKOS_VERSION`**
The tag must be `v` + the version in `flickos-release`. Delete the tag
(`git push --delete origin vX.Y; git tag -d vX.Y`), fix the version or tag, and push again.

**`mount: … permission denied` / chroot errors**
You didn't run `lb build` with `sudo`. In a container, it must be `--privileged`.

**Build breaks halfway and later builds fail oddly (`device busy`, leftover mounts)**
```sh
sudo lb clean --purge
mount | grep "$(pwd)/chroot"        # anything still mounted?
sudo umount -R "$(pwd)/chroot/proc" "$(pwd)/chroot/sys" "$(pwd)/chroot/dev" 2>/dev/null
sudo lb clean --purge
```
Rebooting also clears stuck mounts.

**`umount: …/chroot/sys: target is busy`** (after `lb chroot_sysfs remove`)
A process started by a hook is still running inside the chroot. Find it with
`sudo sh -c 'for p in /proc/[0-9]*; do readlink $p/root | grep -q /chroot && echo ${p#/proc/} $(tr "\0" " " < $p/cmdline); done'`
and `sudo kill` it, then `sudo umount chroot/sys` and resume with `sudo lb build`.
It used to be a `gpg-agent --homedir /tmp/ostree-gpg-…` that `flatpak remote-add`
left behind; `0150-flathub.hook.chroot` now kills it. A new hook that starts a
daemon must stop it too.

**Disk full**
`cache/` and `chroot/` are big. `sudo lb clean --purge` frees everything.

**`Palette check failed: … is not in the Arc-Dark palette`** (at the start of `build-iso.sh`)
A config file uses a color outside FlickOS's Arc-Dark palette, often a leftover
from before Arc or a typo. Use the palette color it should be (see
[09 – The Arc-Dark palette](09-customizing.md#the-arc-dark-palette)). If the color
is intentional and new, add it with a comment to `tools/check-palette.py`.

**`unknown labwc theme key '…'`**
The key is misspelled or doesn't exist in this labwc version; labwc would ignore
it silently. Compare with `man labwc-theme`, and update `LABWC_KEYS` in
`tools/check-palette.py` only when labwc really added the key.

**GTK apps are Arc-Dark, but some app looks light / like Adwaita**
It's a libadwaita app, which ignores GTK themes by design. Nothing to fix in FlickOS.

## Boot test (`tools/boot-test.py`)

Start with `boot-test/serial.log`. It has everything the guest printed. Run
with `--verbose` to watch it live.

**Exit 2: `xorriso not found` / `qemu-system-x86_64 not found`**
`sudo apt install xorriso qemu-system-x86`.

**Exit 2: `could not find a live boot entry`**
The ISO has no `/isolinux/live.cfg` or `/boot/grub/grub.cfg` in the expected
format. Check `--bootloaders` in `auto/config`, and look inside the ISO with
`xorriso -indev FlickOS-64bit-v2.0.iso -ls /isolinux/ /boot/grub/`.

**Exit 3: timed out waiting for `login: `**
Read the end of `serial.log`:
- Ends in the kernel or initramfs (e.g. `Unable to find a medium containing a
  live file system`): a live-boot problem. The kernel and initrd may not match
  the squashfs, so rebuild with `tools/build-iso.sh --purge`.
- Ends in a `(initramfs)` shell prompt: same as above.
- systemd was still starting units: the machine is slow (no KVM?). Try
  `--timeout 1200`.
- Empty log: QEMU didn't start. Run the `qemu-system-x86_64` command by hand
  to see its error.

**Exit 3: `login failed`**
- Most likely the live user doesn't exist: see *Authentication failure* under
  [Live session / installed system](#live-session--installed-system).
- Otherwise the user or password changed: check `username=` in
  `--bootappend-live` and `LIVE_USER`/`LIVE_PASSWORD` at the top of `boot-test.py`.

**`WARN systemd: degraded`**
A unit failed. The failed units are listed below the warning. Look at them in a
live session: `systemctl status UNIT`, `journalctl -b -u UNIT`. Units that
don't apply in VMs are common, so decide per unit whether to fix, mask or ignore it.

**`FAIL labwc running` (or waybar/mako/PipeWire)**
The graphical session on tty1 didn't start. Look at `screen.png`, then boot
with `tools/test-iso.sh`, switch to tty2 and investigate (see *Live session*
below). PipeWire and waybar depend on labwc, so if labwc fails, those fail too.

**`FAIL panel and notifications supervised, neither restarted`** (or *no panel
program crashed during the layout and style switches*)
A panel program failed at least once. The check prints the lines it found in
`$XDG_RUNTIME_DIR/flickos/panel.log`, which say which program and why; the
supervisor restarted it, so `screen.png` may well show a normal desktop. A
failure that prints nothing is the other half of the check: waybar or mako is
not a child of `flickos-layout`, so nothing would restart it (an older
flickos-layouts in the image, or autostart starting waybar itself because
flickos-layouts is missing).

**`FAIL network reachable`**
QEMU's user networking has no internet, e.g. a proxy or firewall in CI. It can
also mean NetworkManager didn't configure the interface: check `nmcli` in a live session.

**`screen.png` missing**
The screenshot is best-effort through QMP. It's never a test failure.

## CI

**Workflow doesn't start**
The file must be at `.github/workflows/iso.yml` on the pushed branch, and Actions
must be enabled in the repo settings.

**Boot test much slower in CI, with a *running without KVM* warning**
The runner didn't expose `/dev/kvm` to the container. The test still works,
with longer timeouts. If it times out anyway, pass a larger `--timeout` in the
workflow's *Boot test* step.

**`Permission denied` on a script in CI but works locally**
The executable bit isn't committed. See [06](06-ci-and-releases.md#requirements-for-ci-to-pass).

**Release step fails with `403` / `Resource not accessible by integration`**
Repo Settings → Actions → General → Workflow permissions → **Read and write**.

## Apt repository

**`reprepro: … already registered with different checksums`**
You rebuilt a package with changes but the same version. Bump it (`dch -i -D trixie "…"`).

**`gpg: signing failed: Inappropriate ioctl for device`**
gpg can't show the passphrase prompt. Run `export GPG_TTY=$(tty)` and retry.
Add it to your shell rc file.

**`gpg: signing failed: No secret key`**
The secret key isn't on this machine. Import your backup:
`gpg --import flickos-archive-secret.asc`.

**Users don't receive an update**
1. Version bumped? `dpkg-parsechangelog -l packages/NAME/debian/changelog -S Version`
2. Published and uploaded? `curl -fsSL URL/dists/trixie/main/binary-amd64/Packages | grep -A1 "Package: NAME"`
3. On the user system: `sudo apt update && apt policy NAME`
4. If it's a *new* entry in `flickos-desktop`'s `Recommends:`, installed systems
   won't install it. See [04](04-packages.md#flickos-desktop-meta-package).

## Live session / installed system

**Live session: `flickos login: user (automatic login)` then `Authentication failure`**
The live user was never created, so there is nothing to log into. live-config
creates it only when the **`user-setup`** package is installed, and that package
is merely *recommended* by live-config while the image is built with
`--apt-recommends false`. It must therefore be listed in
`config/package-lists/live.list.chroot`. Check an ISO with:

```sh
grep -c '^Setting up user-setup' build.log      # 1 = installed
```

The same applies to any other package's Recommends
([03](03-live-build-config.md#autoconfig-build-options)).

**Black screen or labwc doesn't start in QEMU**
Use `-device virtio-vga`. To see the error, switch to tty2 (in the QEMU window
send Ctrl+Alt+F2; autologin is on there in the live session) and run `labwc`
by hand to read its output. If it's a GPU/renderer error, try
`WLR_RENDERER=pixman labwc`.

**Installed system: text login prompt instead of the login screen**
The login screen (`flickos-greeter`) didn't start. Log in on tty1, which starts
the desktop as before, then check in foot:
- `systemctl status greetd` and `journalctl -b -u greetd`. systemd restarts
  greetd up to 5 times in 30 s, then gives up.
- `readlink /etc/systemd/system/display-manager.service` should point to
  `greetd.service`. Another display manager there wins; `sudo systemctl enable
  --force greetd` switches back.
- `cat /run/flickos-greetd/config.toml`: written by `greetd-config` before each
  start. Missing means the drop-in didn't run (`systemctl cat greetd` shows it).
- The greeter's own errors (cage, gtkgreet) are in the journal too. For a
  GPU/renderer error, try `WLR_RENDERER=pixman` in the `greeter` script.
- Upgraded systems switch to the login screen only after a reboot.

**Installed system: logging in at the login screen returns to it**
The session exited right away. Log in on tty1 (Ctrl+Alt+F1) to see
`flickos-session`'s errors, or run `flickos-session` from a text console.
`~/.profile` is read before the session starts (greetd sources it), so an
error or an `exec` there can end the login too.

**Installed system: automatic login doesn't happen**
`getent group autologin` must list the user (first member wins); greetd logs
them in once per boot, not after logging out. Add them with
`sudo gpasswd -a USER autologin`.

**Installed system: tty1 shows a login prompt but labwc doesn't start after login**
- `ls /etc/profile.d/95-flickos-session.sh /usr/bin/flickos-session`: is
  `flickos-settings` installed?
- The script only runs on **tty1** and only in a login shell.
- Run `flickos-session` by hand to see errors.

**User changed labwc settings but FlickOS updates don't apply**
They have their own copy in `~/.config/labwc/`, which wins over `/etc/xdg/labwc/`.
Expected. See [04](04-packages.md#flickos-settings).

**"Install FlickOS" does nothing / Calamares doesn't open**
Run `flickos-install -d` in foot to see Calamares's output. Common causes:
- `sudo: a password is required`: the live user's passwordless sudo is missing
  (live-config's `sudo` component didn't run). Check `sudo -n true`.
- Qt can't connect to the display: check `echo $WAYLAND_DISPLAY` in foot, and
  that `qt6-wayland` is installed.
- Calamares's log: `.cache/calamares/session.log` in `/home/user/` or `/root/`.

**"Install FlickOS" is still in the menu after installing**
`flickos-installer` wasn't removed. Check `dpkg -l flickos-installer` on the
installed system, and look for errors from the `packages` job in the Calamares
log. Remove it by hand with `sudo apt purge flickos-installer calamares`.

**Keyboard layout is wrong in the desktop**
Check `cat /etc/default/keyboard`, then log out and in. The session script
(`flickos-session`) and the login screen read it when they start. A user's `~/.config/labwc/environment` with `XKB_DEFAULT_*` values
overrides it.

**No network icon in the panel**
nm-applet must run with `--indicator` (waybar's tray doesn't support old-style
icons), and waybar's config must include `"tray"`. Check `pgrep -a nm-applet`.

**Two panels on top of each other on a screen**
waybar 0.12 adds a second bar to a screen that is turned on while it runs and
was off when waybar started or last reloaded (a laptop's own screen turned on
next to an external one). Since flickos-layouts 1.54 the panel's supervisor
watches the screens and reloads waybar once they have been still for 1.5 s,
which leaves one bar per screen; `panel.log` says `the screens changed:
reloading waybar`. With an older flickos-layouts, or if it happens anyway:
`pkill -USR2 -x waybar` (waybar's own reload).

**No panel at all (no bar, but the wallpaper and the menu are there)**
The panel, notifications and the dock run under a supervisor
(`flickos-layout supervise`, one per program) that restarts one that fails, so a
missing bar means it failed repeatedly or never started. Everything they print
goes to **`$XDG_RUNTIME_DIR/flickos/panel.log`** — the session's stderr goes
nowhere a user can read, so that log is the only trace:

```sh
cat $XDG_RUNTIME_DIR/flickos/panel.log     # "restarting it in Ns", "giving up"
pgrep -af 'flickos-layout (panel|supervise)'   # supervisors still running?
pgrep -a waybar; ls $XDG_RUNTIME_DIR/flickos/waybar/
```

- `waybar … giving up` after five restarts: the lines above it are waybar's own
  output. A bar that keeps dying right after an output appears or disappears is
  usually the VM's or a second monitor's mode change.
- No `starting the panel` line at all: `flickos-layout panel` never ran (labwc
  didn't start its autostart, or flickos-layouts isn't installed).
- `another flickos-layout has been busy for 10s`: a sibling autostart command
  hung while holding `layout.lock`. The panel carries on without the lock, so
  this is a warning, not the cause.

Start the panel by hand to watch it fail in a terminal:

```sh
waybar -c $XDG_RUNTIME_DIR/flickos/waybar/config.jsonc -s $XDG_RUNTIME_DIR/flickos/waybar/style.css
```

**My own rc.xml replaces all of FlickOS's keys**
labwc merges a user's `~/.config/labwc/rc.xml` over FlickOS's, except when it
is a copy of FlickOS's file or has `<default />`, when a `menu.xml` uses
FlickOS's menu ids, or when there is a `~/.config/labwc/autostart`.
`flickos-layout explain labwc` says which; `flickos-layout doctor` says what to
change. It takes effect at the next login
([09 – Your own labwc files](09-customizing.md#your-own-labwc-files)).

**Something looks or acts wrong, and you have changed your own config**
Log out and pick **flickos-session-plain** in the login screen's session list
(on a text login, run `flickos-session-plain`). It is FlickOS without your own
changes: labwc reads only FlickOS's files (`labwc -C` on
`$XDG_RUNTIME_DIR/flickos/plain/labwc`), and flickos-layout leaves out your own
styles, add-ons, `~/.config/waybar` and `~/.config/mako`. Nothing of yours is
changed, and choices can't be changed there. If the problem is gone, it comes
from your files: `flickos-layout check` lists what's wrong with them. *Settings →
About* says "plain session" while you are in it.

**Panel is a single top bar (taskbar, clock, status) instead of the chosen layout**
That's flickos-settings' fallback panel: `flickos-layout panel` couldn't generate
the layout's panel. Run `flickos-layout set $(flickos-layout current)` in a
terminal to see the error (JSON syntax in `waybar.jsonc`, a missing `include` or
palette file, or no `XDG_RUNTIME_DIR`). `flickos-layout doctor` lists user files
that replace the panel (`~/.config/waybar/config`).

**Tray, status icons or clock disappear while many windows are open**
The window list pushed them off the bar. waybar 0.12 (trixie) doesn't ellipsize
taskbar titles, so the window list asks for the full width of all its buttons,
and GTK gives every module at least the width it asks for: what is packed after
the window list ends up past the edge of the bar. Everything comes back as
windows are closed. Redmond's window list therefore shows icons only: about 35
windows fit its bar at 1080p (46 px each). A user who sets `"format": "{icon}
{title}"` in `~/.config/waybar/` gets the pushing back; upstream waybar's
`expand` and `truncate` options, which shrink the buttons instead, are newer
than 0.12. Traditional's window list is sfwbar's, which shortens titles
instead; when even "…" doesn't fit (about 23 windows at 1280 px, 35 at
1920 px), its last buttons are cut off and the desktop switcher stays.

**Traditional: the desktop switcher doesn't highlight the current desktop**
sfwbar older than `1.0~beta17+git20260910+flickos4` never marks it (an
upstream bug FlickOS patches, see `packages/sfwbar/debian/README.source`):
`apt policy sfwbar`. Switching still works. If there are no desktop buttons
at all, check that `$XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml` has
`<desktops number="4">` (`flickos-layout set traditional` regenerates it and
reloads labwc) and that no `~/.config/labwc/rc.xml` replaces it
(`flickos-layout explain labwc`, `doctor`).

**Tray icons missing after switching layouts**
waybar owns the tray (`StatusNotifierWatcher`). After a restart, applets must
register again, which takes a few seconds. Check
`busctl --user get-property org.kde.StatusNotifierWatcher /StatusNotifierWatcher org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems`.
If an applet never comes back, restart it (`pkill nm-applet; nm-applet --indicator &`).

**Switching to Light (or Dark) didn't change the GTK theme or icons**
`style set` only switches `gtk-theme` and `icon-theme` while they are one of the
styles' themes (`Arc`/`Arc-Dark`, `Numix-Circle`/`Numix-Circle-Light`), so a
theme chosen in *Settings → Appearance* (nwg-look) is kept. `flickos-layout doctor`
names it. Pick Arc or Arc-Dark in Appearance (or
`gsettings set org.gnome.desktop.interface gtk-theme Arc-Dark`), then choose the
style again. Already open GTK apps usually update live; restart one that doesn't.

**Window title bars show labwc's icon instead of the app's**
labwc takes window icons from `<theme><icon>` in rc.xml; unset, it looks for an
icon theme named like the window theme and shows only hicolor's icons. Check
`grep '<icon>' $XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml` (or the system rc.xml):
it should name the GTK icon theme (`gsettings get org.gnome.desktop.interface icon-theme`).
A `~/.config/labwc/rc.xml` that replaces FlickOS's (a copy of it, or one with
`<default />`: `flickos-layout explain labwc`) needs its own `<icon>`. If the
window's app id has no desktop file (`lswt` lists app ids), labwc and the panel
have no icon for it either.

**Some apps stay light (or dark) whatever the style: they look like Adwaita**
Those are libadwaita (GTK 4) apps, e.g. GNOME apps. libadwaita ignores GTK
themes by design; it only follows `color-scheme`, which styles do set
(`prefer-dark` for Dark, `default` for Light). Nothing to fix in FlickOS.

**Terminal, launcher or notifications keep the old colors after a style switch**
- Open foot windows keep their colors; new ones get the style's.
- `~/.config/foot/foot.ini`, `~/.config/fuzzel/fuzzel.ini` or
  `~/.config/mako/config` replace FlickOS's config, including the style's colors
  (`flickos-layout doctor` lists them).
- The session started before flickos-layouts 1.3: log out and in, so the
  overlay is in `XDG_CONFIG_DIRS` and mako runs with the generated config
  (`tr '\0' ' ' < /proc/$(pgrep -x mako)/cmdline`).
- Check the generated files: `ls -R $XDG_RUNTIME_DIR/flickos/`. With Light there
  are `xdg/foot/foot.ini` and `xdg/fuzzel/fuzzel.ini`; `mako/config` includes
  `styles/ID/mako.conf`.

**Window borders and menus don't follow the style**
labwc takes the window theme from the overlay `rc.xml`, unless a
`~/.config/labwc/rc.xml` that labwc doesn't merge hides it (`flickos-layout
explain labwc`), or a merged one sets its own `<theme><name>`. The overlay also keeps a theme other than `FlickOS-Arc-Dark`
or `FlickOS-Arc` that an administrator set in `/etc/xdg/labwc/rc.xml`. Check
`grep -A1 '<theme>' $XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml`.

**Desktop Layout & Style does nothing when chosen from the menu**
Run `flickos-layout pick` in a terminal to see why. "already open" means a
chooser window is still open, maybe behind other windows or on another output;
the lock is `$XDG_RUNTIME_DIR/flickos/pick.lock`. "GTK 3 is not available"
means `python3-gi` or `gir1.2-gtk-3.0` is missing: the chooser then falls back
to a fuzzel list, and without fuzzel only `flickos-layout set ID` works.

**A pinned app is missing from the Cupertino dock**
Apps whose desktop file doesn't exist, has `Hidden=true`, or whose `TryExec`
program isn't installed are skipped. Check `ls /usr/share/applications/ID` and
the `pins =` line in `$XDG_RUNTIME_DIR/flickos/dock/sfwbar.config`. An app whose
window has a different app id than its desktop file name shows up twice (pin
and window).

**The Cupertino dock doesn't appear**
While the active window is maximized, it is hidden until the pointer touches
the bottom edge right below it (the middle of the screen; in a QEMU window,
fullscreen QEMU with Ctrl+Alt+F so the pointer reaches the last row). `pgrep -a sfwbar` should show one
`sfwbar -f /run/user/…/flickos/dock/sfwbar.config`. If not, run
`flickos-layout set cupertino` in a terminal for errors, then that `sfwbar -f …`
command to see sfwbar's own messages.

**No boot splash, only text during boot**
- `splash` missing from the kernel line: check `cat /proc/cmdline`.
- Wrong theme: `plymouth-set-default-theme` should print `flickos`. Fix with
  `sudo plymouth-set-default-theme -R flickos` (`-R` rebuilds the initramfs).
- In a VM, Plymouth needs a graphics device with a framebuffer. Use
  `-device virtio-vga` (as `tools/test-iso.sh` does).

**Boot menu still says "Live system" or shows Debian's splash**
`config/bootloaders/` wasn't used: check the files exist and are committed, then
rebuild with `tools/build-iso.sh`. In `build.log`, look for the
`binary_syslinux`/`binary_grub_cfg` steps. A black GRUB background usually means
the splash PNG isn't 8-bit RGB (`identify config/bootloaders/grub-pc/splash.png`).

**GRUB boot entry is missing or broken**
A bare placeholder word (e.g. `KERNEL_LIVE`, `MEMTEST`, `LINUX_LIVE`) appears in
`config/bootloaders/grub-pc/grub.cfg` outside `@…@`, even in a comment. See
[09 – Boot menu](09-customizing.md#boot-menu).

**`dpkg-divert: error: 'diversion of /usr/lib/os-release …' clashes`**
Another package diverts the same file. List diversions with `dpkg-divert --list`.
Only one package can divert a file.

**Firewall blocks something (e.g. SSH, KDE Connect, a game server)**
`sudo ufw allow PORT/tcp` (or `/udp`), or temporarily `sudo ufw disable` to confirm
the firewall is the cause. See [09 – Firewall](09-customizing.md#firewall).

**Brightness keys do nothing / no brightness slider in Quick Settings**
brightnessctl (Debian's isn't built with logind) needs `brightness-udev`'s
udev rule, which makes the backlight writable for the `video` group (a Depends
of flickos-desktop since 1.24). Check:
- `ls -l /sys/class/backlight/*/brightness` shows group `video` and `rw` for
  it. If not: `dpkg -s brightness-udev`, then `sudo udevadm trigger -c add -s
  backlight`.
- `id` lists `video`. Accounts from the installer, *Settings → Users* and the
  live user have it; for another one, `sudo adduser NAME video`, then log in
  again.
- Quick Settings also leaves the slider out while the laptop screen is off,
  and on computers without `/sys/class/backlight` (most desktops).

**Screen locks or suspends during testing**
swayidle only runs on installed systems (not in the live session). In a test
VM, stop it with `pkill swayidle`.

## Window tiling (flick-tiler)

### How it works, in one paragraph

labwc cannot be told by another program to move or resize a window, so
flick-tiler never does. It tiles through labwc's **regions**: it writes one
region per tiled window, plus a window rule that snaps each new window to the
next unused region, into the fragment
`$XDG_RUNTIME_DIR/flickos/tiler/labwc.xml`. `flickos-layout reconfigure` merges
that fragment into the overlay `rc.xml` (`$XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml`)
and reloads labwc, which then gives every window the new geometry of its
region. So a tiling problem is always in one of four places: the **daemon**,
the **fragment**, the **merge into the overlay**, or **labwc reading the
overlay**. The daemon runs for the whole session, tiling on or off: autostart
starts it at login, and while tiling is off it simply writes no fragment. So
**no daemon at all means something went wrong**, not that tiling is off.
Details in
[09 – Window tiling](09-customizing.md#window-tiling).

### First checks

Run these in a terminal **inside the session** (not over the serial console,
which lacks the session environment):

```sh
flick-tiler status                                  # {"alt": "off"} = tiling is off
pgrep -fa '[f]lick-tiler daemon'                    # exactly one, all session long
ls $XDG_RUNTIME_DIR/flickos/tiler/                  # control, daemon.lock, labwc.xml while on
grep -c '<region' $XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml   # regions that reached labwc
flickos-layout doctor                               # user config that blocks the overlay
dpkg-query -W flick-tiler flickos-layouts flickos-settings
```

Versions must match: flick-tiler 1.1 depends on **flickos-layouts >= 1.8**
(`flickos-layout reconfigure`, the merge into the overlay and the panel button)
and **flickos-settings >= 1.11** (Super+T and the autostart line). flickos-layouts declares
`Breaks: flick-tiler (<< 1.1)`, so apt refuses the broken combination — but a
half-finished upgrade can still leave you with only one of them.

### Symptoms

**Turning tiling on does nothing to the windows already open**
By design: labwc applies window rules only when a window *opens*, so
flick-tiler cannot capture windows that are already there. A notification says
so. Press **Super+Shift+T** in each window you want tiled, or just open a new
window. `flick-tiler status` shows how many windows it manages.

**New windows don't tile at all**
Work down the chain:

```sh
flick-tiler status        # "off" → turn it on (Super+T); no answer → no daemon
pgrep -fa '[f]lick-tiler daemon'
test -e $XDG_RUNTIME_DIR/flickos/tiler/labwc.xml && echo fragment ok
grep -c '<region' $XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml    # 0 → the merge didn't happen
tr '\0' '\n' < /proc/$(pgrep -x labwc)/environ | grep XDG_CONFIG_DIRS
```

- `XDG_CONFIG_DIRS` must start with `<XDG_RUNTIME_DIR>/flickos/xdg`. If it
  doesn't, labwc never reads the overlay and **nothing** the tiler writes has
  any effect. That happens when the session didn't start through
  `flickos-session`, or when `flickos-layout prepare` failed at login.
- A user's own `~/.config/labwc/rc.xml` that labwc doesn't merge (a copy of
  FlickOS's, or one with `<default />`) replaces the whole system file,
  including the overlay: tiling can't work at all. `flickos-layout doctor`
  says why and what to change; then log in again.
- Regions present but windows still float: run `labwc --reconfigure` by hand,
  then `flick-tiler off && flick-tiler on`.
- No daemon at all: autostart didn't start it (`grep -n flick-tiler
  /usr/libexec/flickos/autostart`), or it stopped. Start one with
  `flick-tiler daemon &` and read its messages; they normally go to the
  session's output (tty1 in the live session, `journalctl -b -u greetd` on an
  installed system).

**The panel button is missing**
- It appears a second or two after login, once waybar has run
  `flick-tiler status` for the first time. A screenshot taken immediately
  after login can miss it.
- `flick-tiler status` must print one line of JSON. If it prints nothing or an
  error, waybar has nothing to show.
- The module lives in flickos-layouts' `layouts/common/modules.jsonc`
  (`custom/tiler`), so it needs flickos-layouts >= 1.8 and it has to be in
  the generated panel: `grep -A8 custom/tiler $XDG_RUNTIME_DIR/flickos/waybar/config.jsonc`.
- A user's own `~/.config/waybar/` replaces the FlickOS panel entirely
  (`flickos-layout doctor` reports it), so the button is gone.
- The icon comes from the icon theme (`view-dual-symbolic` and friends in
  `adwaita-icon-theme`). Without it the button is a blank but clickable gap.

**Show Desktop does nothing**
- The daemon does it: `flick-tiler show-desktop` prints `flick-tiler isn't
  running` without one (see above). It needs flick-tiler >= 1.7.
- A second click gives back only what the first one minimized, and only
  while no window is shown; otherwise it minimizes the shown ones again.

**The panel button doesn't follow what the keys do**
flick-tiler tells waybar with `SIGRTMIN+8` (`PANEL_SIGNAL` in `flick-tiler`,
`"signal": 8` in `modules.jsonc`). Test it by hand:

```sh
flick-tiler status; pkill -RTMIN+8 -x waybar      # the icon should match the state
```

If the signal works but nothing changes, the running waybar is using a config
without `"signal": 8` (an old flickos-layouts, or the user's own panel).
Clicking the button always refreshes it, signal or not.

**There are no gaps between the windows**
This cannot be fixed in the current design, and `Gap=` in
`/etc/xdg/flickos/tiler.conf` does nothing. labwc's `<core><gap>` applies only
to *movement actions* such as `MoveToEdge` (`man labwc-config`; in the 0.8.3
source `rc.gap` is read only by `src/snap.c` and `src/view.c`, never by
`src/regions.c`). Regions are also parsed with `atoi`
(`src/config/rcxml.c`), so their geometry is whole percentages of each
output's usable area — a pixel-exact gap can't even be expressed. If gaps
matter, they have to come from a labwc that supports them.

**Tiled terminals leave a few pixels of wallpaper at their edges**
foot resizes in whole character cells, so it cannot fill a region exactly.
Other applications fill their region. Nothing to fix in flick-tiler.

**A window is in the wrong place, or the count is wrong**
Dragging a window out of its place unsnaps it in labwc, and flick-tiler cannot
see that (wlr-foreign-toplevel reports no geometry), so it still counts the
window. Press **Super+Shift+T** to tile it again where it belongs, or
**Super+Shift+F** to let it float on purpose.

**A dialog jumps into a tile for a moment and then floats**
The window rule matches every window, so a dialog is snapped on open and
released immediately after: flick-tiler drops the region again for windows
that have a parent and for the app ids in `Float=`
(`/etc/xdg/flickos/tiler.conf`). Add app ids there (shell patterns, matched
case-insensitively against the Wayland app id) for apps that should never
tile. The app id is normally the name of the app's desktop file without
`.desktop` (`ls /usr/share/applications`), and the WM_CLASS for XWayland apps;
`wlrctl toplevel list` prints the ids of open windows if you install it
(`sudo apt install wlrctl`, not part of FlickOS).

**Windows stay stuck in their tiles although tiling is off**
Only a daemon that died without warning (`kill -9`, a crash, a lost session)
leaves its fragment behind, and labwc then keeps applying the regions. A
normal stop — `off`, `pkill` (TERM), Ctrl+C, logging out — removes the
fragment and reloads labwc first. Either command clears what's left:

```sh
flick-tiler off            # deletes the fragment and reloads labwc
flick-tiler on             # a fresh daemon also clears what the old one left
```

By hand, if flick-tiler itself is gone:

```sh
rm -f $XDG_RUNTIME_DIR/flickos/tiler/labwc.xml && flickos-layout reconfigure
```

**`flick-tiler: tiling is off (turn it on with Super+T or flick-tiler on)`**
A command that needs the daemon (`focus`, `swap`, `promote`, `tile`, `float`)
was run while tiling is off. Only `on`, `off`, `toggle`, `mode` and `status`
work without a daemon.

**Super+T does nothing**
That binding is in flickos-settings' `/etc/xdg/labwc/rc.xml`, not in the
fragment, so it works even while tiling is off — unless a user `rc.xml`
replaces it:

```sh
grep -n 'flick-tiler toggle' /etc/xdg/labwc/rc.xml
grep -n 'flick-tiler' $XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml   # the other keys, only while on
```

The other keys (Super+J/K, Super+M, Super+[ ], Super+Shift+…) exist **only**
while tiling is on, because they are part of the fragment.

**`flick-tiler isn't running; saved for the next login.`**
No daemon answered, so the choice was only written to
`~/.config/flickos/tiler`. Expected from a text console; inside a session it
means the daemon is gone — see *New windows don't tile at all* above. The
daemon needs a Wayland session with `zwlr_foreign_toplevel_manager_v1`
(labwc); anywhere else it exits with *cannot connect to the Wayland
compositor*.

**The Cupertino dock lies on top of tiled windows**
The dock reserves no space (`exclusive_zone = "0"`), and regions cover the
whole usable area, so tiled windows extend under it. Expected with that
layout; the panel (waybar) does reserve space and is never covered.

**Tiling is on again after a reboot (or off although it was on)**
The choice is saved per user in `~/.config/flickos/tiler` and only the system
default is in `/etc/xdg/flickos/tiler.conf`:

```sh
cat ~/.config/flickos/tiler       # [Tiler] Enabled=yes|no, Mode=, MasterRatio=
```

At login, autostart runs `flick-tiler daemon`, which reads that file and
tiles straight away when it says `Enabled=yes`. Setting `Enabled=yes` in
`/etc/xdg/flickos/tiler.conf` turns tiling on for everyone who hasn't chosen.

### The files it uses

| Path | What it is |
|---|---|
| `$XDG_RUNTIME_DIR/flickos/tiler/labwc.xml` | The fragment: regions, window rule, keybinds. Gone = tiling off |
| `$XDG_RUNTIME_DIR/flickos/tiler/control` | The daemon's socket; every command but `status` needs it |
| `$XDG_RUNTIME_DIR/flickos/tiler/daemon.lock` | Keeps it to one daemon per session |
| `$XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml` | The overlay labwc reads: FlickOS `rc.xml` + the fragment |
| `~/.config/flickos/tiler` | The user's choice (`Enabled`, `Mode`, `MasterRatio`) |
| `/etc/xdg/flickos/tiler.conf` | System defaults, including `Float=` |

Nothing is written to `$HOME` except `~/.config/flickos/tiler`, and the
runtime files are gone after logout.

### Watching it work

Run the daemon in the foreground to see every error as it happens. Only one
daemon runs at a time (the lock), so stop the one from autostart first:

```sh
pkill -f '[f]lick-tiler daemon'            # stop the session's daemon
flick-tiler daemon                         # the same thing in the foreground; Ctrl+C to stop
```

Ctrl+C removes the fragment and reloads labwc, exactly as a normal stop does.
The setting in `~/.config/flickos/tiler` is untouched, so the next login (or
`flick-tiler daemon &`) picks up where you left off.

Two environment variables help while developing: `FLICKOS_LAYOUT` names
the program it calls to merge and reload (`FLICKOS_LAYOUT=true` skips that),
and `FLICK_TILER_PREFIX` points at a source tree, so
`FLICK_TILER_PREFIX=packages/flick-tiler packages/flick-tiler/usr/bin/flick-tiler daemon`
runs the working copy with its own `tiler.conf`.

What labwc actually got:

```sh
grep -o '<region[^/]*/>' $XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml
sed -n '/<windowRules>/,/<\/windowRules>/p' $XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml
```

Exit codes: `0` ok, `1` error, `2` wrong usage. `flick-tiler status` prints
`{"alt": "off"}` whenever no daemon answers, whatever the saved setting says.

### Testing a change

```sh
cd packages/flick-tiler && python3 -m unittest discover -s tests -v   # also runs at package build
tools/boot-test.py       # checks "tiling off by default…" and "tiling on starts the daemon…"
```

The boot test only proves the plumbing. For behaviour, drive a live VM with
`tools/test-iso.sh --live` and watch the windows, or import `tools/boot-test.py`
from a script, replace its `CHECKS` and let it take screenshots for you.

### Limits that are not bugs

- Windows open before tiling was turned on stay floating (Super+Shift+T).
- No gaps (see above).
- One arrangement for all outputs, and none per desktop: in Traditional, which
  has 4 desktops, tiling arranges the windows of all of them together (labwc
  doesn't say which desktop a window is on), so a desktop has empty places
  where another desktop's windows are.
- Two windows opening in the same instant can land in the same tile; open one
  of them again, or press Super+Shift+T in it.
- A window dragged out of its tile keeps counting until it is tiled again or
  closed.

## Shortcut sheet (flickos-shortcuts)

Holding Super shows nothing:

```sh
pgrep -af 'flickos-shortcuts daemon'   # running? autostart starts it
flickos-shortcuts daemon               # in a session terminal: prints why it stops
flickos-shortcuts show                 # the sheet without the daemon
flickos-shortcuts list                 # what it would show
```

- `already running`: another daemon holds `$XDG_RUNTIME_DIR/flickos/shortcuts.lock`.
- `GTK 3 with layer shell is not available`: `gir1.2-gtklayershell-0.1` is
  missing (a Depends; `sudo apt install flickos-shortcuts`).
- The sheet shows only when **Super alone** is held: with another modifier
  down (Shift, Ctrl, Alt) it waits until that is let go.
- `no labwc rc.xml found`: no `labwc/rc.xml` in `~/.config` or any
  `XDG_CONFIG_DIRS` folder (the sheet says so instead of listing keys).
- A shortcut with a vague description (*Run …*, under *Other*) is a command
  `COMMANDS` doesn't know ([09](09-customizing.md#shortcut-sheet-hold-super)).

## Settings window (flickos-control)

A mouse, touchpad or keyboard setting doesn't apply:

```sh
flickos-control get                                  # what is set, and where (user, system, default)
cat $XDG_RUNTIME_DIR/flickos/control/labwc.xml       # the fragment for labwc
grep -A3 '<libinput>' $XDG_RUNTIME_DIR/flickos/xdg/labwc/rc.xml   # merged into the overlay?
flickos-layout doctor                                # user files that hide the overlay
```

- A `~/.config/labwc/rc.xml` that labwc doesn't merge replaces the whole
  overlay, so none of these settings (nor layouts or tiling) apply; then a
  `~/.config/labwc/environment` also hides the keyboard layout. `doctor` and
  the page's warning bar say so and what to change.
- Back to the *Device default* click method takes effect at the next login:
  labwc keeps a libinput option that disappears from its config.
- The keyboard layout of the login screen and the console is
  `/etc/default/keyboard`, changed only by *Use for Login Screen and
  Console…*. `localectl set-x11-keymap` doesn't work on Debian (localed is
  read-only there). The console picks it up at the next boot.
- *Use for Login Screen and Console…* (or *Log in automatically*) does nothing: `pkexec` needs the polkit
  agent (mate-polkit, started by autostart) to ask for the password. Try
  `pkexec /usr/libexec/flickos/control-helper keyboard pc105 us "" ""` in a
  terminal to see its message.

Other pages:

- **Super+B or Super+E opens the wrong app:** `xdg-mime query default
  x-scheme-handler/https` (or `inode/directory`) shows the default;
  `/usr/libexec/flickos/open-default browser` falls back to `x-www-browser`
  when the default's desktop file is missing. **Super+Enter:** `DEBUG=1
  xdg-terminal-exec` shows which list and terminal it picks (the first
  installed one in `~/.config/xdg-terminals.list`, then
  `/etc/xdg/flickos/xdg-terminals.list`); a terminal whose `Exec=` isn't
  quoted by the desktop-entry rules (double quotes only) is skipped.
- **The screen locks at the old time:** `pgrep -a swayidle` shows the times;
  a change restarts only FlickOS's swayidle (`FLICKOS_IDLE=1` in its
  environment). Not in the live session.
- **"Set the time automatically" is greyed out:** `timedatectl show -p
  CanNTP` is `no` without `systemd-timesyncd` (a Depends of flickos-desktop
  since 1.16).
- **Login page missing:** it shows only on installed systems with
  flickos-greeter (group `autologin`), never with `boot=live`.

## Getting more information

- **For a bug report:** *Settings → All Settings → About → Copy System Info*,
  or `flickos-control about` in a terminal, gives the FlickOS, Debian and
  Linux versions, the hardware and the versions of FlickOS's packages.
- `man lb_config`, `man lb_build`, `man live-build`, `man live-boot`, `man live-config`
- `man dh`, `man dh_install`, `man deb-control`, `man deb-changelog`, `man dch`
- `man reprepro`
- Debian Live Manual: https://live-team.pages.debian.net/live-manual/
- live-build source (to see exactly what a step does): `/usr/lib/live/build/`
