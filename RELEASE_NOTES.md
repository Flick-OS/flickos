# FlickOS 2.2

FlickOS 2.2 is still based on **Debian 13 "trixie"**, like 2.0 and 2.1. It
adds **restore points**, which can undo a software change that broke the
system, even from the boot menu. A new **Software** app installs apps from
Debian, Flathub and FlickOS's new community repository. FlickOS also has its
own look now: an amber halo logo, boot menus, wallpapers and a start button
in the brand color.

## Coming from 2.1 or 2.0

You don't need to reinstall. Everything in 2.2 comes through FlickOS's apt
repository:

```sh
sudo apt update && sudo apt upgrade
```

Use `apt upgrade`, not `apt-get upgrade`: `apt-get` keeps the FlickOS desktop
back because it needs new packages. Then restart.

**Restore points need a new install.** They work only on the btrfs layout
that the 2.2 installer sets up by default. An upgraded system (ext4) gets the
package, but nothing of it runs and nothing changes.

The old software manager (gnome-packagekit) stays installed after the upgrade.
The menus now open the new Software app, so you can remove the old one:

```sh
sudo apt remove gnome-packagekit
```

Coming from **2.0**, read the
[2.1 release notes](https://github.com/dvbondoy/FlickOS/releases/tag/v2.1)
too. Apps that FlickOS only recommends don't arrive with an upgrade. If you
want the ad blocker, the task manager and picture thumbnails that new
installs get, add them yourself:

```sh
sudo apt install gnome-package-updater webext-ublock-origin-firefox lxtask tumbler
```

The upgrade from 2.0 also adds FlickOS's anonymous **weekly count**. An
upgraded system is counted until you turn it off in *Settings → Privacy*.

Coming from FlickOS 1.x (Ubuntu/LXLE based), there is still **no in-place
upgrade**. Back up your files and install 2.2 fresh.

## What's new

- **Restore points:** before every software change (installing, removing or
  updating, from any program, also the automatic updates) FlickOS saves a
  restore point of the system. Your files in your home folder are not part of
  it. The newest 5 are kept, and none is made while the disk is nearly full.
  - **Settings → Restore Points** lists them in plain words. *Put Back…*
    shows what it would undo before it asks for your password, and the
    system goes back at the next restart. The system as it was before is kept
    as a restore point, so putting one back can be undone too. You can also
    make one by hand, delete them all, or turn them off.
  - **History** lists restore points next to the software changes they were
    made before.
  - **Boot menu:** if the system won't start, pick *Restore points* in the
    boot menu and start an older one. Nothing you do there is kept until you
    choose *Keep* in Settings.
  - **Recovering by itself:** after 2 starts in a row that don't reach the
    login screen, the computer starts the newest good restore point by
    itself. A notification at login says why, and Settings offers *Keep…* or
    *Try Again*. You can turn this off and have the boot menu wait for you
    instead.
- **The installer uses btrfs by default**, so new installs get restore
  points. ext4 is still offered. You can also choose whether to have swap
  (none, without hibernation, or with hibernation, the default), and a 10 GB
  disk is now enough.
- **Software:** a new app for finding, installing and removing apps. It
  replaces the old package manager window in the menus, the start menu and
  the Welcome window.
  - It shows apps, not packages, with icons, descriptions, screenshots and
    the space an app needs before you install it.
  - Apps come from Debian (the default), FlickOS, the FlickOS community
    repository and Flathub. The front page has a *Made for FlickOS* shelf.
  - Removing anything the desktop needs is refused.
  - Apps from Flathub are updated with the automatic updates.
- **Community repository:** other developers can publish apps for FlickOS.
  FlickOS builds each app from its public source code, checks it and reviews
  it before it is published. The app's page in Software says so, and that it
  can use your files like any app from Debian. Automatic updates install
  community apps' updates too. Developers: see *Publish your app for FlickOS*
  on the website.
- **FlickOS's own look:** a new halo logo, in amber. The boot menus, the
  splash screen and the installer use it, the installed system gets a FlickOS
  boot menu theme, and the Dark and Light styles have new wallpapers. On the
  desktop only the start button's logo is amber; everything else keeps Arc's
  blue.
- **Start menu:**
  - **Log Out, Restart and Shut Down take a second click.** The first click
    turns the button red; click again within 4 seconds to go ahead. Lock
    Screen still works at once.
  - **Cupertino has power buttons** at the top right of its app grid (while
    Quick Settings is off).
  - **Quick Settings** has Log Out, Restart and Shut Down next to Settings and
    Lock Screen, in every layout.
  - **Cupertino's app grid:** clicking an app that is already open brings its
    window forward instead of starting it again. A middle click, `Ctrl+click`
    or `Ctrl+Enter` starts another copy. The app under the pointer is
    highlighted, and the grid has a background again, so names stay readable
    over any window.
- **Faster starts:** the startup files (initramfs) are now compressed with
  zstd: about 10% smaller and unpacked in 0.6 s instead of 2.7 s on an older
  laptop. Upgraded systems get this at their next kernel update.

## Fixes

- **Sending files to the phone** no longer fails every first or second time.
  A file now counts as sent only once the phone has all of it, and is tried
  up to three times.
- **Cupertino's app grid** no longer stops starting apps after a click on its
  background.
- **Settings and the Phone window** no longer use the processor while they
  sit open: a hidden *Loading…* spinner kept redrawing 60 times a second.
- **Installs get `noatime` again** (fewer disk writes): Calamares had ignored
  FlickOS's mount options.

## Trying it and installing

1. Download `FlickOS-64bit-v2.2.iso` and check it:
   `sha256sum -c SHA256SUMS`
2. Write it to a USB stick (for example with Balena Etcher or `dd`) and boot it.
3. The live session logs in automatically as `user` (password `live`). Choose
   **Install FlickOS**. It is pinned first in the start menu and is also in the
   right-click desktop menu.

## Basics

| Key | Action |
|---|---|
| `Super` (tap) | Start menu |
| `Super` (hold) | Keyboard shortcuts |
| `Super+Enter` | Terminal |
| `Super+D` or `Alt+F3` | App launcher |
| `Super+E` | File manager |
| `Super+B` | Web browser |
| `Super+V` | Clipboard history |
| `Super+Q` | Close window |
| `Super+Shift+D` | Show desktop |
| `Super+Esc` | Task manager |
| `Print` | Screenshot of an area |
| `Super+Shift+S` | Screenshot or recording bar |
| `Super+Shift+R` | Screen recording (again to stop) |
| `Super+L` | Lock screen |
| `Super+Shift+E` | Log out |
| `Super+T` | Tiling on/off |

Right-click the desktop for the menu.

## Known issues

- **Restore points only on new installs** with btrfs (see above). They cover
  the system, not your home folder: keep backing up your files.
- **Opening Settings or the Welcome window a second time** doesn't bring the
  open window to the front, so it looks as if nothing happened. Find the
  window in the taskbar.
- **Low-contrast secondary text:** the gray descriptions under settings are
  hard to read, most of all in the Light style.
- **Tiling limits:** windows that are already open when tiling is turned on
  stay floating until you tile them with `Super+Shift+T`, and all monitors use
  the same arrangement.
- **Traditional's window list** shows the windows of all 4 desktops, not
  only the current one's.
- **Quick Settings** has no Bluetooth switch yet.
- **Phone** needs the firewall to let it in. If the firewall is on, allow
  phones in *Settings → Phone*.
- There is no upgrade path from 1.x (see above).

## Downloads

- ISO: https://sourceforge.net/projects/flickos/files/v2.2/
- Source code and issues: https://github.com/dvbondoy/FlickOS
- Community: https://www.reddit.com/r/flickos/
