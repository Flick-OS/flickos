# FlickOS 2.4

FlickOS 2.4 is still based on **Debian 13 "trixie"**, and it is the **last
2.x release with new features**. It brings **Tool Kits**, which set up a
computer for programming, studying, teaching children or security testing
in one step; **Classroom**, a teacher's view of a room of FlickOS computers;
a **new start menu style** you drive by typing; **Redmond+**, a panel that
groups each app's windows; FlickOS's **own GTK themes**, so windows, title
bars and the desktop finally look like one thing; and **hooks** that run your
own programs when something happens on the desktop.

## What comes next

Work now moves to **FlickOS 3.0**, on Debian 14 "forky", once Debian releases
it (expected in 2027). 2.x keeps getting fixes until then and for **12 months
after 3.0's release**, and 3.0 will come with a tested way to upgrade, so you
won't need to reinstall. The 3.0 release notes will give the exact end date.

## Coming from 2.3 or older

You don't need to reinstall. Everything in 2.4 comes through FlickOS's apt
repository, and a system with automatic updates on already has most of it:

```sh
sudo apt update && sudo apt upgrade
```

Use `apt upgrade`, not `apt-get upgrade`: `apt-get` keeps the FlickOS desktop
back because it needs new packages. Then restart.

At your next login, the Dark and Light styles switch your windows to
FlickOS's new GTK themes, unless you picked another GTK theme yourself.

Coming from **2.2, 2.1 or 2.0**, read the
[2.3 release notes](https://sourceforge.net/projects/flickos/files/v2.3/) too,
and the [2.2 ones](https://sourceforge.net/projects/flickos/files/v2.2/) from
2.1 or 2.0: restore points need a new install, and a few apps only arrive if
you add them yourself.

Coming from FlickOS 1.x (Ubuntu/LXLE based), there is still **no in-place
upgrade**. Back up your files and install 2.4 fresh.

## What's new

### Tool Kits

- **One switch for each kind of work**, in the new **Tool Kits** window (in
  the start menu, on a Welcome card and in *Settings → More Settings*). Each
  kit installs a set of apps and tools through Software, and removes them
  again:
  - **Programming:** a base kit (Git, a C compiler, everyday command-line
    tools), Python, web (Node.js and npm), C and C++, and containers (Podman
    and Distrobox).
  - **Study**, for students, and **Young Learners**, apps for children's
    learning.
  - **Security testing:** network, web testing, passwords, forensics,
    reverse engineering and wireless. Only test computers and networks you
    are allowed to test; the window and Software say so.
- **Setup steps** after a kit is on: your name for Git, an SSH key, Rust,
  capturing network packets without administrator rights, choosing a Wi-Fi
  adapter for testing, and the ports devices on your network may reach.
- **Newer versions:** a tool's latest version for your account only (through
  mise), and Metasploit from its maker's repository, both off until you turn
  them on.
- **Environments:** a Debian testing or Kali Linux container with a kit's
  tools inside, whose apps show in your start menu, without changing your
  system.
- In **Software**, kits are under *Developer Tools*, *Education* and
  *Security Tools*.

Guide: https://flickos.org/guides/tool-kits/

### Classroom

- **A teacher's view of a classroom**, on the school's own network and with no
  server: thumbnails of every student's screen, **lock the class** with a
  message, send a message or a web page, **view or control** one student's
  screen to help, and **show your own screen** on theirs.
- Neither part comes with FlickOS. Install it in a terminal:
  `sudo apt install flickos-classroom-teacher` on the teacher's computer and
  `sudo apt install flickos-classroom-view` on each student's. Nothing is
  shared until the student, or the school on a lab computer, turns sharing
  on in *Settings → Classroom* and pairs with the teacher's six-digit code. While sharing is on, a button in
  the panel shows it, and it turns red while a teacher is looking.

### The desktop

- **One look from edge to edge:** FlickOS's own GTK themes, *FlickOS-Arc-Dark*
  and *FlickOS-Arc*, give windows the same corners as the panels and menus,
  and the title bars of other windows now match the apps' own header bars.
  The previous themes are still in *Settings → Appearance*.
- **A new start menu style, Prompt:** type to find apps and folders, work out
  sums (Enter copies the answer), or run desktop tasks such as *Restart
  Panel* or *Shut Down*; start with `/` to find files and `>` to run a
  command. Every app is a tile underneath, the
  first six pins open with `Ctrl+1` to `Ctrl+6`, a plugged-in drive gets a
  button with an eject, and a newly installed app is marked *New*.
  Right-click an app to pin it, hide it or open it in Software. Choose it in
  *Settings → Desktop Layout & Style*. Press `F1` in it for its keys.
- **The classic start menu** now has *Recent* and *Trash*, with Settings and
  Software beside the power buttons.
- **A new layout, Redmond+:** Redmond's panel with one taskbar button per app,
  its windows listed when you point at it, a right-click menu to minimize,
  maximize, close, pin or unpin, and a *more* button for apps that don't fit,
  so the tray is never pushed off the screen. Choose it in *Settings →
  Desktop Layout & Style*.
- **The docks** of Cupertino and Footprint have the same right-click menu,
  with *Pin to Dock* and *Unpin from Dock*.
- **Window buttons on the left, the right or split**, for every layout:
  *Settings → Desktop Layout & Style → Window buttons*.
- **Switching desktops** (`Super+Ctrl+Left`/`Right`, `Super+1`…) shows them
  as circles on a card in the middle of the screen.
- **A new style, Tortuga**, in *Software → Styles*: floating islands for a
  panel and a dock that shows your desktops as a 2×2 grid. Every style in
  Software now has screenshots.
- **The login screen's own page**, *Settings → Login Screen*: logging in
  automatically, its language and keyboard layout, a background picture
  (yours too), and where the login box goes (left, middle or right).
- **Startup Applications** can start any command or script, not only apps:
  *Add Command…*.
- **Hooks:** run your own programs when the screen locks or unlocks, the
  computer wakes, a screen comes or goes, your phone connects, a setting
  changes, or a screenshot or recording is saved. Nothing runs until you add
  one. Guide: https://flickos.org/guides/hooks/
- **Packages and Flatpaks:** double-click a `.deb`, `.flatpak` or
  `.flatpakref` file and Software shows what it is, what it needs and what a
  Flatpak may reach, then installs it.
- **Weather** can show wind in km/h, m/s, mph or knots: *Settings →
  Weather*.
- **Tiling** no longer rearranges the windows that are already open when you
  turn it on. *Settings → Tiling → Tile open windows* brings that back.
- **Settings can now be translated**, like the start menu and the Welcome
  window. Help is welcome.

## Fixes

- **.zip and .7z files** couldn't be opened or made in the file manager and
  Xarchiver.
- **Thunar's Set as Wallpaper** did nothing.
- **Settings → Wallpaper** stopped listing pictures after a removed style's
  wallpaper.
- **Use for the Whole System** (*Language & Region*) didn't change the system
  language.
- **Check for Updates Now** could miss updates published since the last
  check.
- **Undo of a kernel install** in History left the kernel installed.
- **Background tasks** (the daily app update, the weekly count) stopped after
  each update until the next restart.
- **Ejecting a USB drive** from the start menu or Thunar failed for some
  drives.
- **Add Phone** could hang when the phone asked to pair straight away.
- **Displays** opened too small to show the map of the screens.
- **File dialogs in the Light style** had blank buttons at the bottom, and
  buttons with text in a header bar (Displays' *Cancel* and *Apply*) touched
  its edges.
- **The lines** in the start menu, Quick Settings and the phone popup hardly
  showed.
- **Security:** adding a user account in Settings now refuses a full name
  that could have passed options to the system's account tool.

## Trying it and installing

1. Download `FlickOS-64bit-v2.4.iso` and check it:
   `sha256sum -c SHA256SUMS`
2. Write it to a USB stick (for example with Balena Etcher or `dd`) and boot it.
3. The live session logs in automatically as `user` (password `live`).
   Coming from Windows? Plug in a USB drive and open **Bring Files from
   Windows** first. Then choose **Install FlickOS**. It is pinned first in
   the start menu and is also in the right-click desktop menu.

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

Right-click the desktop for the menu. On some keyboard layouts a few of these
keys move; hold `Super` to see yours.

## Known issues

- **Classroom** needs the teacher's and the students' computers on a network
  that lets computers see each other. Many school and guest Wi-Fi networks
  don't; a wired network or the school's own staff network usually does.
- **Redmond+** is new and drawn by a different panel program than the other
  layouts. If something in it misbehaves, tell us, and switch back to Redmond
  in *Settings → Desktop Layout & Style*.
- **Bring Files from Windows** has been tested on test disks, not yet on many
  real Windows computers. After copying, open a few files from your OneDrive
  folders: if one opens empty, download it from OneDrive instead, and please
  tell us.
- **The login screen** can't change an expired password. Press `Ctrl+Alt+F1`
  and log in on the text screen, which asks for a new one.
- **Web apps** use a Firefox feature that Mozilla hasn't turned on for Linux
  yet. A site that moves you to another address when you sign in (Teams does)
  may show in Software as not installed after you made its web app.
- **Wine** runs some Windows programs, not most, and takes about 3 GB.
- **Restore points only on new installs** with btrfs (see the 2.2 notes).
  They cover the system, not your home folder: keep backing up your files.
- **Opening Settings or the Welcome window a second time** doesn't bring the
  open window to the front. Find the window in the taskbar.
- **Low-contrast secondary text:** the gray descriptions under settings are
  hard to read, most of all in the Light style.
- **Tiling** uses the same arrangement on all monitors.
- **Traditional's window list** shows the windows of all 4 desktops, not
  only the current one's.
- **Eleven's clock** can be too wide for the panel in languages with a long
  date.
- **Quick Settings** has no Bluetooth switch yet.
- **Phone** needs the firewall to let it in. If the firewall is on, allow
  phones in *Settings → Phone*.
- There is no upgrade path from 1.x (see above).

## Downloads

- ISO: https://sourceforge.net/projects/flickos/files/v2.4/
- Website: https://flickos.org
- Source code and issues: https://github.com/Flick-OS/flickos
- Community: https://www.reddit.com/r/flickos/
