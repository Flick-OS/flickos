# 11 – Moving to a new Debian release

How FlickOS moves from one Debian release to the next. It uses trixie
(Debian 13) → forky (Debian 14) as the example, but the steps are the same for
any release. Read [05 – Apt repository](05-apt-repository.md) and
[06 – CI and releases](06-ci-and-releases.md) first.

The move is two jobs, and the second is the harder one:

1. **A new ISO on the new release** (FlickOS 3.0). This is mostly mechanical, with a long tail of testing.
2. **Moving installed systems over.** The apt repository is the only way to reach them, and a mistake there can remove their desktop.

- [The phases at a glance](#the-phases-at-a-glance)
- [Debian's calendar and FlickOS's](#debians-calendar-and-flickoss)
- [Things to know before you start](#things-to-know-before-you-start)
- [Phase 1: a workbench on the new release](#phase-1-a-workbench-on-the-new-release)
- [Phase 2: make it build](#phase-2-make-it-build)
- [Phase 3: make it work](#phase-3-make-it-work)
- [Phase 4: the repository and the cut-over](#phase-4-the-repository-and-the-cut-over)
- [Phase 5: the upgrade path for installed systems](#phase-5-the-upgrade-path-for-installed-systems)
- [Phase 6: release](#phase-6-release)
- [After the release: keeping the old release alive](#after-the-release-keeping-the-old-release-alive)
- [Watch-outs](#watch-outs)
- [Checklist](#checklist)

## The phases at a glance

| Phase | When | Goal | Done when |
|---|---|---|---|
| 1. Workbench | Now: forky is Debian *testing* | A `forky` branch that builds in a forky container | `tools/build-iso.sh` runs to the end, or fails on something real |
| 2. Make it build | Until Debian's freeze | Every package and the ISO build on forky | ISO built, sanity hook passes, all package tests pass |
| 3. Make it work | During the freeze | Everything FlickOS relies on behaves the same | Boot test and the manual test list pass |
| 4. Repository and cut-over | Hard freeze or the release | forky suites published; `main` is forky, a `trixie` branch keeps 2.x | `dists/forky/InRelease` online, both branches publish |
| 5. Upgrade path | Before you tell anyone to upgrade | A tested, FlickOS-owned way from 2.x to 3.0 | Upgrades of the test matrix pass, and the way back works |
| 6. Release | After Debian 14.0 | FlickOS 3.0 ISO, notes, site | Tag `v3.0` built, published and announced |

Phases 1–3 happen on a branch while `main` keeps shipping 2.x. Nothing a user
sees changes until phase 4.

## Debian's calendar and FlickOS's

Debian's release team announces the freeze dates on
`debian-devel-announce`. Past releases froze between January and May and came
out in the summer. Each freeze step is a signal for FlickOS:

| Debian | What it means for FlickOS |
|---|---|
| New release is *testing* (now) | Versions still move every week. Start phases 1–2; expect churn. |
| Transition and toolchain freeze | Library and compiler versions settle. Rebuild sfwbar and re-run phase 2. |
| Soft freeze | No new packages enter. A package that isn't in testing by now won't be in the release: replace it. |
| Hard freeze | Versions are almost final. Do phase 3 for real. Make a 3.0 beta ISO for testers. |
| Release (14.0) | Debian is final. Do phases 4–6. |
| First point release (14.1, about 2 months later) | A safe time to open the upgrade path to everyone. |
| Old release's security support ends (about 3 years after its release; trixie came out 2025-08-09) | 2.x stops getting FlickOS updates. LTS covers Debian's own packages until about mid-2030. |

## Things to know before you start

1. **There are two delivery paths** ([01 – Overview](01-overview.md)). The ISO
   is a snapshot. Installed systems change only through the apt repository, and
   only when their sources name the right suite.
2. **The release has one name in the tree.** `FLICKOS_DEBIAN` in
   `packages/flickos-branding/usr/lib/flickos-release` is read by
   `auto/config`, `repo/publish.sh`, `repo/upload.sh`,
   `repo/community/publish.sh`, `tools/release.sh` and `tools/boot-test.py`.
   The installer's sources helpers read `/etc/os-release` instead. Four places
   can't read it and name the release themselves:
   - `repo/conf/distributions`
   - `flickos.sources` (flickos-archive-keyring)
   - the two workflows' `debian:…` containers
   - the build host

   `tools/build-iso.sh` stops when any of them differs.
3. **Both suites share one pool.** reprepro keeps one `pool/` for every
   suite. A version in both suites must be the very same file, and a rebuild
   is not guaranteed to be byte-identical. So each package gets its own
   version for the new release (phase 4).
4. **Installed systems never install Recommends.** live-build's
   `00recommends` stays on installed systems. A package the new release adds
   as a *Recommends* never reaches them; only a *Depends*, or the upgrade
   tool, can add it.
5. **Removing a Depends removes the desktop.** If the new release renames or
   drops a package that flickos-desktop *Depends* on, apt removes
   flickos-desktop, and autoremove then takes the desktop with it.
6. **The build host must be the new release.** sfwbar is compiled against
   the host's libraries, so a forky ISO is built on forky: in a container, a
   VM, or CI.
7. **Your desktop stays on trixie.** You develop on an installed FlickOS 2.x.
   forky work happens in a container (building) and in QEMU (testing), never
   by upgrading your own computer before phase 5.

## Phase 1: a workbench on the new release

**Goal:** a `forky` branch whose ISO builds in a forky container.

1. **Make the branch:** `git switch -c forky main`. Merge `main` into it
   often, so the branch never falls far behind 2.x. Keep it checked out in
   a worktree of its own (`git worktree add ../FlickOS-forky forky`), and
   merge with `tools/sync-release.sh [--dry-run] [--push]` from either
   folder. It finds the newer release's worktree from `flickos-release`,
   stops before changing anything when that worktree has uncommitted
   changes or the merge would conflict, and afterwards lists lines the merge
   added outside the docs that name trixie. After the cut-over it refuses
   to merge `main` into the trixie branch (see *After the release*).
2. **Switch the names** on the branch, all in one commit:
   - `FLICKOS_DEBIAN="forky"` in `flickos-release`.
   - `repo/conf/distributions`: **add** three stanzas, `forky`,
     `forky-community` and `forky-testing`. Copy the trixie ones and change
     only `Codename:`, `Suite:` and the trixie in `Description:`. Keep the
     labels (*FlickOS*, *FlickOS Community*, *FlickOS Testing*): the update
     origins match on them. **Keep the trixie stanzas.** Both branches
     publish into the same local reprepro database (`repo/db/`, git-ignored),
     and that database must know every suite.
   - `flickos.sources`: `Suites: forky forky-community`.
   - `.github/workflows/iso.yml` and `community.yml`: `debian:forky`.
   - Add `Enabled: no` to `flickos.sources` for now. The ISO build ends with
     an `apt update` that needs `dists/forky/` online, and it isn't published
     until phase 4. This is the offline-testing hack from
     [07](07-troubleshooting.md). The boot test's *FlickOS apt source enabled*
     check fails while it is there; that failure is expected until phase 4.
3. **Get a forky build host.** A privileged container is the quickest: it is
   what CI builds in, needs no install, and builds straight in your working
   tree at full speed. Make an image with the build tools once, so a build
   doesn't download them again (a `--rm` container started from plain
   `debian:forky` loses them when it ends). `tools/build-host.Containerfile`
   lists them:

   ```sh
   sudo apt install podman
   sudo podman build --network host --build-arg DEBIAN=forky -t flickos-forky \
       -f tools/build-host.Containerfile "$(mktemp -d)"
   ```

   Then each build is:

   ```sh
   sudo podman run --rm -it --privileged --network host -v "$PWD":/src -w /src \
       flickos-forky tools/build-iso.sh
   sudo find . -mindepth 1 -maxdepth 1 ! -name cache ! -name chroot ! -name binary \
       ! -name .build -exec chown -R "$USER" {} +
   ```

   `build-iso.sh` runs without sudo as root, so its output is owned by root
   on your side, hence the `chown`. **Never chown live-build's own folders**
   (`cache/`, `chroot/`, `binary/`, `.build/`): chown clears setuid and
   setgid bits, and the next build copies `cache/bootstrap` into the image.
   A plain `chown -R "$USER" .` did that once (2026-10-29): the ISO's base
   system belonged to uid 1000, `su`, `passwd` and `unix_chkpwd` had lost
   their bits, and no password worked. The fix is `sudo rm -rf cache/bootstrap
   chroot` and a new build. live-build's `cache/` and `chroot/` are
   in your folder and outlive the container, so only what changed in forky
   is downloaded again. The image keeps the build tools at the day you made
   it; the ISO's packages are always fetched fresh. Make it again with
   `--pull --no-cache` added at each freeze step, or when a build tool's
   newer forky version matters. `--network host` uses the host's network
   directly: without it, the container's DNS or forwarding can break after
   the host's network changes, and `apt update` then fetches nothing (every
   package is "unable to locate"). For a shell in the container, put `bash`
   in place of `tools/build-iso.sh`.
4. **Let CI build it too.** `iso.yml` runs on `main`, tags and pull requests,
   so open a **draft pull request** from `forky` into `main`. Every push then
   builds and boot-tests the forky ISO. Don't merge it before phase 4.
5. **Check every package FlickOS uses:**

   ```sh
   tools/check-debian-deps.py forky
   ```

   The script reads every `debian/control` and `config/package-lists/` and
   asks Debian's archive with `rmadison` (devscripts; it needs the network but
   not forky itself). It lists what forky lacks and where it is named, then
   the trixie and forky versions of the packages whose behavior FlickOS
   relies on (`WATCH`). Run it again at every freeze step.

**Done when** the ISO builds to the end, or fails on something real that you
have written down. Keep one list of findings: a tracking issue, or a
`docs/design/forky.md` that you delete at the end.

### What the script found on 2026-10-26

forky is still *testing*, so this will change, but it shows the size of the job:

| Package | trixie | forky | FlickOS relies on it for |
|---|---|---|---|
| **evince** | 48.1 | **missing** (GNOME replaced it with `papers`) | flickos-desktop's Recommends, `mimeapps.list`'s PDF/TIFF/DjVu default |
| **labwc** | 0.8.3 | **0.20.2** | everything: see phase 3 |
| **waybar** | 0.12.0 | **0.15.0** | the panel and every layout |
| **calamares** | 3.3.14 | **3.4.2** | the installer's module files |
| python3 | 3.13 | 3.14 | every FlickOS program |
| linux | 6.12 | 7.2 | firmware, `0060-trim-firmware` |
| systemd | 257 | 262 | units, sysusers, logind |
| grub | 2.12 | 2.14 | boot menu theme, restore points' menu |
| plymouth | 24 | 26 | boot splash |
| apt | 3.0 | 3.3 | the recovery hook, update settings |
| kanshi | 1.5.1 | 1.9.0 | *Displays* |
| xdg-desktop-portal-wlr | 0.7.1 | 0.8.4 | screen recording |
| cava | 0.10.4 | 1.0.0 | the sound spectrum |
| foot / fuzzel / mako | 1.21 / 1.12 / 1.10 | 1.28 / 1.15 / 1.11 | the styles' palette files |
| cage / greetd / gtkgreet | 0.2 / 0.10.3 / 0.8 | 0.3 / 0.10.3 / 0.8 | the login screen |
| appstream / packagekit / flatpak | 1.0 / 1.3 / 1.16 | 1.2 / 1.4 / 1.18 | Software, `repo/conf/dep11.py` |
| firefox-esr | 140 | 153 | prefs; trixie gets 153 too, so it is not forky-specific |

## Phase 2: make it build

**Goal:** every package and the ISO build on forky, and every package's unit
tests pass there. `packages/build.sh` runs them at package build, under
forky's Python.

Work through these in order. Each one is a commit on the `forky` branch:

1. **Missing packages** (from `check-debian-deps.py`). For each one, decide
   on a replacement:
   - **evince → papers:** change flickos-desktop's Recommends, its
     description, and flickos-settings' `mimeapps.list`
     (`org.gnome.Papers.desktop`; check the desktop file's real name in the
     package). Keep `org.gnome.Evince.desktop` second in the list, like the
     Thunar/pcmanfm pair, for systems that keep evince.
   - A missing *Depends* is more serious than a missing Recommends (point 5
     above). Look for a renamed package with `apt-cache search` in the
     container, or `rmadison -s forky NAME`.
2. **sfwbar**, the only compiled package. Rebuild it against forky's GTK and
   gtk-layer-shell (0.10). Look for new compiler warnings and run the dock
   (Cupertino, Traditional, Footprint, Elemental) in phase 3. Its FlickOS
   patches (`debian/README.source`) may need refreshing if you also move to a
   newer upstream commit; don't do both at once.
   **neatvnc**, the other compiled package (flickos-classroom-view's wayvnc
   without H.264): take forky's Debian source (`apt-get source neatvnc`) and
   make the changes in its `debian/README.source` again. Its version must stay
   above forky's own, or apt takes Debian's (with 53 MB of video libraries).
3. **waypaper:** check its Python dependencies under 3.14.
4. **Python 3.14:** the package tests catch most problems. The risky parts
   are `ctypes` (flickos-layout's `Inotify`, flickos-lock's PAM) and
   deprecation warnings that became errors. Run
   `python3 -W error::DeprecationWarning -m unittest discover -s tests` in a
   package's folder when something looks odd.
5. **debhelper 14** is available, but compat 13 still works. Stay on 13 and
   change compat deliberately, in its own commit, later.
6. **lintian:** a newer lintian has new tags. Fix them or add overrides with
   a reason.
7. **live-build:**
   - `0060-trim-firmware` fails when apt would remove something not in
     `TRIM`, which happens when forky's firmware packages are named
     differently. Update the list.
   - `0010-sanity`'s `REQUIRED` stops a build that lost a must-have package.
   - Read `lb config`'s warnings in `build.log`; forky's live-build may
     deprecate options in `auto/config` (syslinux is the likeliest).
8. **The palette and theme checks:** `tools/check-palette.py` holds the labwc
   theme keys 0.8.3 knows. labwc 0.20 may add or rename keys (see phase 3).

**Done when** `tools/build-iso.sh` finishes in the container, and CI on the
draft pull request builds the ISO.

## Phase 3: make it work

**Goal:** everything FlickOS relies on still works on forky's versions. This
is the longest phase, so start it before the freeze and repeat it at the hard
freeze.

Start with `tools/boot-test.py -v --iso FILE` (its *apt source enabled* check
fails until phase 4). Then go through the components below. Each row says
what FlickOS relies on and how to see whether it still holds. A workaround
that is no longer needed can go, but **only on the forky branch**: the trixie
branch keeps it.

### labwc 0.8.3 → 0.20.2 (the biggest risk)

| FlickOS relies on | Where | How to check |
|---|---|---|
| Modifier state sent to every client with a keyboard, not only the focused one | flickos-shortcuts (hold Super), flickos-menu (tap Super) | Hold Super with a window focused: the sheet shows. Tap Super: the menu opens. If upstream fixed this, both need a new design: a `Super_L` keybind or a protocol. |
| `-m` merging (system, overlay, user; first `<menu id>` wins; every autostart runs) | flickos-session, flickos-layouts' `merge_decision` | `flickos-layout explain labwc` with a user `rc.xml` that has a keybind; the keybind works and FlickOS's keys still work |
| Exactly the options flickos-control writes | flickos-control's `SETTINGS` (its tests hold the list) | Compare with forky's `labwc-config(5)`; change each Settings value and see it applied |
| Regions and window rules that snap new windows | flick-tiler | Super+T, open three windows, change the mode and the gap |
| No `ToggleShowDesktop` | flick-tiler's `show-desktop` | If 0.20 has it, flick-tiler's version can stay; don't switch on the trixie branch |
| `ext-workspace` desktops, reused ids, no `urgent` | flickos-layouts' `Desktops=`, sfwbar's pager, Aye3, Footprint | Traditional's pager and Aye3's desktop buttons follow Super+1…4 |
| Theme keys, SVG buttons, `<theme><icon>` | flickos-settings' themes, every style's themerc | Every style's title bar, `tools/check-palette.py` |
| `<magnifier>` options | zoom, flickos-control's *Accessibility* | Super+=, Super+-, Super+0, Super+scroll |
| Keyboard focus given to a layer surface only on map | flickos-menu's fades | Open and close the menu quickly; type right after it opens |
| `HEADLESS-*` virtual outputs | second screen (flickos-phone-screen add-on) | Only with a tablet; otherwise note it as untested |
| Session lock: a client that is abandoned keeps the screens covered | flickos-lock's guard and take-over | The boot test's lock checks, plus killing the lock screen by hand |

### waybar 0.12 → 0.15

| FlickOS relies on | Where | How to check |
|---|---|---|
| A second bar on a screen turned on while it runs (worked around) | `supervise`'s `ScreenWatch` | Plug in a second screen; one bar per screen. If fixed, the reload is still harmless. |
| Exiting on any CSS parse error, at start and on reload | `check-css`, `css_errors` | A broken `~/.config/flickos/tweaks/style.css` is left out with a warning, and the panel stays |
| A group's `on-click` never running | Quick Settings' `group/quick` | Click volume and battery: Quick Settings opens |
| Signals `SIGRTMIN+8…13`, `catches_signal` | tiler, phone, recording, desktops, media, weather | Each button updates when its state changes |
| Custom modules' JSON, `{alt}`, `interval`, calendar markup, clock `actions` | `common/modules.jsonc`, the weather, the clock | Every layout's panel looks as it does on 2.x (compare with `preview.png`) |
| HIG VIS-11's frozen names | users' own layouts and tweaks | `flickos-layout check` on a user layout copied from 2.x. A waybar CSS change that breaks users' CSS goes into the release notes. |

### The rest

| Component | FlickOS relies on | How to check |
|---|---|---|
| **Calamares 3.3 → 3.4** | Module files in flickos-installer: `partition.conf` (swap choice), **`mount.conf`'s btrfs subvolumes `@` and `@snapshots`** (restore points need exactly these), `users` (`autologinGroup`, `defaultGroups`), `shellprocess` and the sources helpers, `packages` (removes flickos-installer), `show.qml` | Install with `tools/test-iso.sh --install` on BIOS and UEFI, with and without encryption, then `flickos-recovery state` on the installed system |
| **GRUB 2.12 → 2.14** | The installed theme, `42_flickos-recovery`, `flickos-recovery.cfg`, the start counter GRUB reads | Boot menu look; *Restore points* submenu; two failed starts lead to the recovery entry |
| **apt 3.0 → 3.3** | flickos-recovery's `DPkg::Pre-Install-Pkgs` hook (version 3), `apt-config dump` (the *Updates* page), the one-line `sources.list` the installer writes | Install a package: a restore point appears; *Updates* page; consider writing `debian.sources` (deb822) in `calamares-sources-final` instead |
| **systemd 257 → 262** | sysusers (countme, greeter), sandboxed units (countme, software-update), timers, logind `conf.d`, greetd's drop-in | `systemctl --failed`, `systemd-analyze security flickos-countme.service`, the power button setting |
| **greetd / gtkgreet / cage** | The login screen, the plain session entry | Log in, log out, pick the plain session |
| **gtk-session-lock** | The gir package that doesn't depend on its library (flickos-lock's explicit Depends) | If `0.2.0-3` fixed it, the extra Depends is harmless; keep it |
| **xdg-desktop-portal 1.20 → newer** | Its Realtime interface refuses every request, so flickos-settings' `realtime.conf` turns that route off | With `realtime.conf` removed, restart PipeWire while the portal runs: its `data-loop.0` thread is `SCHED_RR`. If so, delete the file and its `debian/links` |
| **xdg-desktop-portal-wlr 0.7 → 0.8** | The chooser config, the stuck first frame restart | Record an area and a full screen; the file plays |
| **kanshi 1.5 → 1.9, wlr-randr 0.4 → 0.5** | Profiles from `displays save`, `wlr-randr --json` fields | Save an arrangement, unplug and plug back |
| **foot, fuzzel, mako, swaylock** | Config keys in flickos-settings and every style's palette | `foot --check-config`, start fuzzel and mako from a terminal and read the warnings; lock with each style |
| **cava 0.10 → 1.0** | `CAVA_CONFIG`, raw 8-bit output | Turn on the spectrum, play music |
| **appstream 1.2, packagekit 1.4, flatpak 1.18** | Software's catalog cache API, install and remove, Flathub; `repo/conf/dep11.py` on the publishing computer | Search, install and remove an app from each source |
| **plymouth 24 → 26** | The FlickOS splash theme | Boot and shut down with `splash` |
| **Kernel 6.12 → 7.2** | Firmware packages (`TRIM`), hardware | Boot on your real computers from a USB stick, not only in QEMU |
| **Thunar, PipeWire, playerctl** | `uca.xml` actions, `thunar.xml` defaults, media controls | Right-click → Open Terminal Here and Send to Phone; media buttons |

### Manual test list

Do this on a forky ISO in QEMU (`tools/test-iso.sh`) and once on real
hardware:

- Live session; install on BIOS and UEFI; first login (Welcome).
- Every layout with every style, and each `flickos-style-*` package
  (install the debs from `config/packages.opt-in/`).
- Tiling; start menu (each style); Quick Settings; the shortcut sheet.
- Lock with Super+L; idle lock; the swaylock fallback.
- Screenshot, markup window, recording, text from the screen.
- Phone pairing, sending a file, notifications (with a phone).
- Media controls and spectrum; weather.
- Every Settings page, History undo, *Put Back as It Was…*.
- Software: install and remove from Debian, FlickOS, Community, Flathub.
- Restore points: make one, put it back, and start from one in the boot menu.

**Done when** the boot test passes (apart from the expected *apt source*
check) and the manual list passes. Review the changes against
`docs/hig/checklist.md` as usual.

## Phase 4: the repository and the cut-over

**Goal:** the forky suites are published, `main` is forky, and a `trixie`
branch keeps 2.x alive.

Do this once, in this order:

1. **Do pending repository moves first.** If the planned move to
   `apt.flickos.org` is still open, do it on trixie before the cut-over. One change
   at a time is easier to debug, and both keyrings then name the same
   address.
2. **Release the last 2.x packages from `main`** (`repo/publish.sh` on main
   as usual), so the split starts from published versions.
3. **Make the trixie branch:** `git branch trixie main`. In that branch's
   `iso.yml`, add `trixie` to `on.push.branches`, so 2.x fixes still get CI.
   Tags (`v2.*`) already trigger it.
4. **Merge the forky branch into `main`** (the draft pull request). Remove
   `Enabled: no` from `flickos.sources`.
5. **Give every package a forky version,** because of the shared pool. The
   rule is: **forky's version is higher than anything trixie will ever
   publish.**

   ```sh
   # The maintainer in debian/control; without it dch makes a non-maintainer upload.
   export DEBFULLNAME="Your Name" DEBEMAIL=you@example.org
   for p in packages/*/; do
       (cd "$p" && dch -i --no-auto-nmu -D forky "Built for Debian 14 (forky).")
   done
   head -qn1 packages/*/debian/changelog    # check every version, especially sfwbar and waypaper
   ```

   Then, on the trixie branch, a fix to a package at `1.69` (forky has
   `1.70`) is `dch -v 1.69.1 -D trixie`. `1.69.1` sorts below `1.70`, so a
   system upgraded to forky still moves up. sfwbar is the same:
   `…+flickos7.1` on trixie, `…+flickos8` on forky. Check with
   `dpkg --compare-versions 1.69.1 lt 1.70 && echo ok`.
6. **The keyring for forky:** flickos-archive-keyring's new version has
   `Suites: forky forky-community` and is published **only to forky**. Its
   `51flickos-origins` uses `${distro_codename}` and needs no change.
7. **Publish in this order**, because apt fails on a suite without a
   `Release` file:
   1. `forky-community`, even if it is empty: `repo/community/publish.sh`,
      or `reprepro -b repo export forky-community`.
   2. `forky`: `repo/publish.sh`, then `repo/upload.sh`.
   3. Check `curl -fsSI …/dists/forky/InRelease` and
      `…/dists/forky-community/InRelease`.
8. **Community apps:** for each app in `trixie-community`, decide on one of:
   - **copy** it when it works on forky unchanged:
     `reprepro -b repo copy forky-community trixie-community NAME`. The same
     file in the same pool is allowed. Run `repo/community/check.py` on it in
     a forky container first, since its dependencies are checked against
     forky's apt.
   - **rebuild** it with a new version from the developer when its
     dependencies changed.

   Tell the developers. Withdrawn apps (`withdrawn/NAME`) need their empty
   package in forky-community too.
9. **EXTRAS** (Notes, Write, Phone Screen, from their own repositories):
   check their dependencies with `rmadison` (Phone Screen needs scrcpy and
   SDL3), give each one a forky version, and publish them with
   `repo/publish.sh` from main.
10. **DEP-11:** the publishing computer runs `repo/conf/dep11.py` for every
    suite. Check that Software in a forky VM shows FlickOS's apps and styles.

**Done when** a forky VM with the published sources runs `apt update` clean,
and a 2.x VM still updates from trixie.

## Phase 5: the upgrade path for installed systems

**Goal:** a user on 2.x can move to 3.0 safely, and back.

Automatic updates never cross a release (`${distro_codename}` stays trixie),
so nothing happens until the user acts. If a user only edits Debian's
`sources.list`, they keep FlickOS's trixie packages on a forky base, and they
can lose flickos-desktop (points 4 and 5 above). They need a FlickOS-owned
way: an upgrade command, for example `flickos-upgrade`, offered on the
*Updates* page through `control-helper` (pkexec, like every system change).

### What the upgrade must do, in order

1. **Check first**, and stop with a clear message if any check fails:
   - Not the live session, on AC power, no `~test` packages installed (the
     testing suite).
   - Every 2.x update is installed (`apt-get -s upgrade` lists nothing).
   - forky's suites are online (fetch `dists/forky/InRelease`).
   - Enough free space: simulate the whole upgrade and read apt's sizes;
     leave room for the restore point.
2. **Simulate, and refuse if it would remove the desktop.** After the sources
   are switched (step 4), run `apt-get -s full-upgrade` and stop if any
   `Remv` line names `flickos-desktop`, a package in its Depends, or a
   `flickos-` package. This is the most important check.
3. **Take a restore point** on FlickOS's btrfs layout, named
   "Before FlickOS 3.0" (`flickos-recovery create Before FlickOS 3.0`). flickos-recovery's apt
   hook also takes one per transaction. Without the btrfs layout (ext4),
   tell the user plainly that there is no way back and ask them to back up.
4. **Switch both sources:**
   - Debian's `/etc/apt/sources.list`, and any `sources.list.d/*.sources` that
     names trixie: `trixie` → `forky`, including `-updates` and `-security`.
   - `flickos.sources`: write **exactly** the forky keyring's file. dpkg then
     sees the conffile as unchanged and asks nothing when the forky keyring
     installs the same text.
   - List third-party sources and leave them as they are (Debian's own
     advice is to check them).
   - Keep the old files (`*.flickos-trixie`) so the tool can undo this step
     if anything before the upgrade fails.
5. **Upgrade the way Debian's release notes say:** `apt update`, then
   `apt upgrade --without-new-pkgs`, then `apt full-upgrade`. Run it visibly,
   in a terminal window, so dpkg's conffile questions are seen and
   answered. Read Debian 14's release notes, chapter *Upgrades from
   Debian 13*, for anything new.
6. **Install what Recommends would have brought.** Because of
   `00recommends`, a replacement like papers for evince never arrives on its
   own. Keep a small map in the tool (old package → new) and install the new
   one only where the old one was installed.
7. **Check the result:** flickos-desktop installed, `dpkg --audit` empty,
   `systemctl --failed` empty after the restart.
8. **Restart.** The way back is *Settings → Restore Points → Put Back…* on the
   "Before FlickOS 3.0" point; flickos-recovery reinstalls GRUB from the
   restored system.

### Testing the upgrade

Test in QEMU before anyone else does, and before the forky suites are public:

1. Install the latest 2.x ISO (from SourceForge) with
   `tools/test-iso.sh --install --iso FlickOS-64bit-v2.N.iso`, then start it
   with `--disk`.
2. Point it at your local repository instead of GitHub Pages: on your
   computer, run `python3 -m http.server -d repo/public 8000`; in the VM, use
   `URIs: http://10.0.2.2:8000` in `flickos.sources`.
3. Run the upgrade, and the way back, for each case:

| Case | Watch for |
|---|---|
| Default install (btrfs) | Restore point taken, put back works |
| ext4 install | The no-way-back warning |
| Encrypted install | Boots after the upgrade (initramfs, GRUB) |
| User with own `~/.config/labwc/rc.xml`, own style, own layout, panel tweaks, an add-on | Their files untouched; `flickos-layout check` and `doctor` say what needs changing |
| Phone paired, community app installed, Flathub apps | Still there and still updating |
| Automatic updates on, *Security fixes only* chosen | The setting survives (`60flickos-updates`) |
| A user who removed some Recommends (LibreOffice, say) | The upgrade doesn't bring them back |

### Optional: warn users who upgrade by hand

A last 2.x update could make `flickos-layout doctor` and the *About* page
warn when `/etc/os-release`'s `VERSION_CODENAME` differs from the suites in
`flickos.sources`, with the right command to fix it.

**Done when** every case above passes in both directions.

## Phase 6: release

1. **Version:** `tools/release.sh 3.0` on `main`. It bumps flickos-branding
   and flickos-installer with `dch -D forky` (from `FLICKOS_DEBIAN`) and
   publishes. Then build, test, push, and tag `v3.0`
   ([06](06-ci-and-releases.md#release-checklist)).
2. **When:** after Debian 14.0, not before; Debian can still change in the
   last days. A beta ISO during the hard freeze is the place for early
   testers. Open the upgrade path to everyone a few weeks after 3.0, or after
   Debian's first point release.
3. **Release notes:**
   - Debian 14 and the big version changes (labwc, waybar, Calamares).
   - What users of their own layouts, tweaks and add-ons should check
     (`flickos-layout check`).
   - How to upgrade, and how to go back.
   - How long 2.x keeps getting fixes.
4. **Elsewhere:**
   - The website: downloads, and the developers' guide (`/learn/publish/`
     names `trixie-community`).
   - [05](05-apt-repository.md)'s *Adding the repo by hand*.
   - The SourceForge folder `v3.0/` and the Discord post happen on their own.
   - countme counts `version=3.0` without a server change (its Worker accepts
     any `X.Y`).
5. **Sweep the docs:** `git grep -n -i 'trixie\|debian 13'` in `docs/`,
   the READMEs and the `server/` READMEs. Leave the trixie branch's
   docs as they are.

## After the release: keeping the old release alive

- **Publish trixie fixes from the trixie branch:** `git switch trixie`, fix,
  `dch -v X.Y.N -D trixie`, `repo/publish.sh && repo/upload.sh`,
  `git switch main`. `publish.sh` reads `FLICKOS_DEBIAN` from the tree you
  have checked out, so the branch decides the suite. **Never** publish from
  the wrong branch: `main`'s packages would land in forky, which is right
  there and wrong for trixie.
- **Fix bugs on main first,** then backport to trixie only what 2.x users
  need: security, data loss, broken upgrades.
- **Only Debian's packages get Debian's security fixes.** FlickOS's own
  packages get fixes only when you publish them.
- **At the end of trixie's security support,** announce it. Stop publishing
  to trixie, but **never delete the trixie suites**: installed systems' `apt
  update` would fail. Keep the old stanzas in `repo/conf/distributions` for
  as long as the suites are online.

## Watch-outs

The traps in one place:

1. A package removed from a *Depends* takes flickos-desktop and the desktop
   with it, both on upgrade and through autoremove.
2. A new *Recommends* never reaches installed systems (`00recommends`).
3. The same version in two suites must be the same file (one pool).
4. A trixie fix must have a lower version than forky's.
5. Publish `forky-community` before the keyring that names it.
6. Keep every suite's stanza in `repo/conf/distributions` on both branches.
7. The ISO build's final `apt update` needs the suite online: use
   `Enabled: no` until phase 4, then remove it (`build-iso.sh` warns, the
   boot test fails, `release.sh` refuses).
8. sfwbar is compiled: build it on the release it is for.
9. labwc's modifier broadcast is the behavior most likely to change, and
   flickos-shortcuts and the Super tap depend on it.
10. waybar CSS changes can break users' own layouts and tweaks: say so in the
    release notes.
11. Calamares' `mount.conf` subvolumes must stay `@` and `@snapshots`, or
    restore points silently stop working on new installs.
12. Users' files are never changed
    ([HIG SET-5](hig/03-settings-and-files.md#set-5-must-never-write-into-files-the-user-owns)),
    and the upgrade tool follows the same rule.
13. Don't upgrade your own development computer before phase 5 passes.
14. Debian packages can still leave testing until the soft freeze: re-run
    `tools/check-debian-deps.py` at every freeze step.

## Checklist

**Phase 1: workbench**
- [ ] `forky` branch in its own worktree; `main` merged in regularly (`tools/sync-release.sh`)
- [ ] `FLICKOS_DEBIAN="forky"`, three forky stanzas added (trixie kept), `flickos.sources` suites, workflow containers
- [ ] `Enabled: no` added (temporarily)
- [ ] forky container builds; draft pull request runs CI
- [ ] `tools/check-debian-deps.py forky` run; findings written down

**Phase 2: build**
- [ ] Missing packages replaced (evince → papers, `mimeapps.list`)
- [ ] sfwbar builds; waypaper's dependencies checked
- [ ] All package tests pass on Python 3.14
- [ ] lintian clean; `TRIM` and `REQUIRED` updated; `lb config` warnings read
- [ ] ISO builds in the container and in CI

**Phase 3: work**
- [ ] labwc table checked
- [ ] waybar table checked
- [ ] Calamares install on BIOS, UEFI, encrypted; `flickos-recovery state` works
- [ ] Remaining components table checked
- [ ] Manual test list passed in QEMU and on real hardware
- [ ] Boot test passes (apart from *apt source enabled*)

**Phase 4: repository**
- [ ] Pending repository move done first
- [ ] Last 2.x packages published; `trixie` branch made, its `iso.yml` builds it
- [ ] forky merged into main; `Enabled: no` removed
- [ ] Every package bumped for forky; version rule checked
- [ ] Keyring for forky published only to forky
- [ ] `forky-community` published before `forky`; both InRelease online
- [ ] Community apps copied or rebuilt; EXTRAS published; DEP-11 checked

**Phase 5: upgrade**
- [ ] Upgrade tool with checks, removal guard, restore point, sources switch, Recommends map
- [ ] Every case of the test matrix passed, upgrade and way back
- [ ] (Optional) hand-upgrade warning in a 2.x update

**Phase 6: release**
- [ ] Debian 14.0 is out
- [ ] `tools/release.sh 3.0`, ISO built and tested, tag `v3.0`
- [ ] Release notes, website, docs/05, docs sweep
- [ ] Upgrade path opened to everyone (after a few weeks or Debian 14.1)
- [ ] End date for 2.x fixes announced
