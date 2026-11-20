# FlickOS 2.3

FlickOS 2.3 is still based on **Debian 13 "trixie"**. It is made for people
**coming from Windows**: it brings your files over from the Windows part of
your disk, tells you what to use instead of a Windows program, and puts
websites like WhatsApp or Outlook in windows of their own. It also has a
**more polished look**, its own **login screen** and **lock screen**, **media
controls** and **weather** in the panel, a **volume and brightness ring**, and
many ways to make the desktop your own.

## Coming from 2.2, 2.1 or 2.0

You don't need to reinstall. Everything in 2.3 comes through FlickOS's apt
repository:

```sh
sudo apt update && sudo apt upgrade
```

Use `apt upgrade`, not `apt-get upgrade`: `apt-get` keeps the FlickOS desktop
back because it needs new packages. Then restart. If Firefox was open, close
it and open it again, so it can make web apps.

New installs also get **fastfetch**, which shows the FlickOS logo in the
terminal. An upgraded system can add it with `sudo apt install fastfetch`.

Coming from **2.1 or 2.0**, read the
[2.2 release notes](https://sourceforge.net/projects/flickos/files/v2.2/)
too: restore points need a new install, and a few apps only arrive if you
add them yourself.

Coming from FlickOS 1.x (Ubuntu/LXLE based), there is still **no in-place
upgrade**. Back up your files and install 2.3 fresh.

## What's new

### Coming from Windows

- **Bring Files from Windows** copies your Desktop, Documents, Downloads,
  Music, Pictures and Videos, your OneDrive folders and your Chrome, Edge or
  Brave bookmarks from the Windows part of the disk. It only reads Windows and
  never changes it, never overwrites a file (a different file with the same
  name is copied as *NAME (from Windows)*), and unlocks BitLocker with your
  recovery key. Files that live only in OneDrive's cloud are listed with
  where to download them instead of being copied.
  - In the **live session**, it copies to a USB drive, so you can save your
    files before installing. **Install FlickOS** offers to do that first when
    it finds Windows.
  - On an installed system it is in the start menu, and the Welcome window
    shows a card for it when the computer has Windows.
  - The installer can also install FlickOS **next to Windows** (*Install
    alongside*), shrinking the Windows partition.
- **Windows programs:** double-click a `.exe`, `.msi` or `.msix` file and a
  window says what the program is and what to use instead: the FlickOS
  version in Software, its web version, or similar apps, from a list of 161
  Windows programs. Nothing in the file is run.
  - **Try with Wine** installs Wine from Software, with the 32-bit part most
    Windows programs need (about 3 GB). Many programs don't work with Wine,
    and the window says so.
  - **Software's search** knows the same programs: search for *photoshop* or
    *ms word* and Software says what to use instead, above the results.
- **Web apps:** WhatsApp, Outlook, Teams, Netflix and other websites in a
  window of their own, with a taskbar button and a place in the start menu,
  sharing Firefox's sign-ins. Find them in **Software → Explore → Web Apps**,
  or make one of any address with *New Web App…*. Firefox makes them with
  the button at the right of its address bar, so they get the site's own
  name and icon.

### The desktop

- **A new wallpaper:** the Dark and Light styles and the login screen now show
  a wave on a sandy shore, seen from above. If you never chose a wallpaper,
  you get it at your next login after the update. A wallpaper you chose stays,
  and the old ones are still in *Settings → Wallpaper*.
- **A new system font:** Inter, in windows, the panels, title bars,
  notifications and the launcher. The terminal keeps DejaVu, and a style with
  a font of its own keeps it. A font you chose in *Settings → Appearance* stays
  in your windows and the panels.
- **Window shadows:** a soft shadow shows which window is in front, in every
  style. Turning it off in *Settings → Accessibility* can help on an old
  computer.
- **Window borders** stand out better on dark pages. In the Dark and Light
  styles the focused window's border is now a soft blue.
- **Rounder corners:** windows and pop-ups share one corner size, and the start
  menu, Quick Settings and the phone popup now keep a small gap from the edges
  of the screen and the panel.
- **New mouse cursors:** Bibata, on the desktop and the login screen.
- **Tidier panels:** the buttons in Redmond, Cupertino and Traditional have one
  rounded shape and light up the same way. In Redmond, a short line marks the
  focused window, and the clock shows the date in words (*Fri 06 Nov*).
- **FlickOS's own login screen:** pick your name from a list instead of
  typing it. It remembers the last user and each user's session, can show
  the password as you type it, and has Shut Down and Restart, zoom
  (`Super+=`, `Super+-`, `Super+0`) and, with more than one keyboard layout,
  a button that shows the layout in use.
- **Your picture:** choose one in *Settings → Users*. It shows on the login
  screen, on the lock screen and in the start menu.
- **FlickOS's own lock screen** for `Super+L`, the menus and the idle lock,
  in the style's colors. When the screen locks by itself, a key or a mouse
  move within a few seconds unlocks it again. The volume, microphone and
  media keys work while the screen is locked.
- **The level ring:** the volume, microphone and brightness keys show the new
  level for a moment. It can be turned off in *Settings → Notifications*.
- **Media controls** in the panel (previous, play or pause, next, and what is
  playing), and a **sound spectrum** above the panel or as a ring in the
  middle of the screen, in the style's colors or rainbow ones. Off by
  default: *Settings → Media Controls*.
- **The weather** in the panel for a place you choose, from Open-Meteo. Off
  by default: *Settings → Weather*. While it is on, only the place's
  position, rounded to about 1 km, is sent, at most once an hour.
- **Pinned apps** in the dock and panel can be added, moved and removed in
  *Settings → Desktop Layout & Style*.
- **Keys for every keyboard layout:** a FlickOS shortcut whose key needs
  Shift or AltGr on your keyboard moves to the key in the same place (on a
  Nordic keyboard, `Super+[` becomes `Super+Å`). The shortcut sheet shows
  the keys as your keyboard labels them, and now fits small screens.
- **Tiling** now tiles the windows that are already open when you turn it on.
- **The clock's calendar** marks today. Scroll over the clock for another
  month, right-click for the year.
- **The start menu** is translated into **Finnish** (thanks, Pekka Kurki),
  and the start menu, Quick Settings, the login screen, the Welcome window
  and the Coming from Windows windows can now be translated. Help is welcome.
- **Save Report…** in *Settings → About* puts what a bug report needs in one
  file for you to attach. Nothing is sent. Your home folder, your user and
  computer names and web addresses are left out; file names stay, so read it
  first.

### Make it yours

- **More styles in Software:** *Seven*, *Aye3wm*, *Footprint*, *Elemental*,
  *Experience* and *Eleven*, each with its own look and layout, under
  **Software → Styles**. *Try* uses one until you log out; *Use* keeps it.
- **A floating panel for Redmond:** a slimmer, see-through bar that floats
  above the bottom of the screen and fills it, solid, while a window is
  maximized, fullscreen or tiled. Off by default, and Redmond's panel is solid
  without it: *Settings → Desktop Layout & Style*.
- **Your own styles and layouts:** start from any FlickOS style or layout
  and change only what you want. Your own panel tweaks (CSS), and your own
  labwc settings added on top of FlickOS's. FlickOS checks your files first,
  so a mistake can't leave you without a panel. *Settings → Desktop Layout &
  Style* has a button for each folder, and `flickos-layout` can try a style,
  share it as one file and apply your changes as you save them.
- **The plain session:** if your changes break something, pick **FlickOS
  (Plain Session)** from the button at the bottom left of the login screen to
  get FlickOS without them.

## Fixes

- **Folders opened in Firefox** instead of the file manager from *Show in
  Folder* and Settings' folder buttons.
- **A second panel** appeared on a screen turned on while you were logged in.
- **The clock's calendar** was an empty box after a screen was turned on or
  off, or after the panel was changed.
- **The panels** ignored the font chosen in *Settings → Appearance*.
- **Phone** couldn't pair with a computer running KDE Connect. A computer's
  clipboard is now ignored, since KDE Connect sends it at every change; text
  shared from a computer still arrives.
- **Redmond's tray menus** were unreadable in the Light style.
- **Screen recordings** of a whole screen of odd size (a virtual machine's
  window) failed, and a recording of a screen that never changed was
  announced as saved but empty.
- **Media controls** kept showing a video that had been closed, and counted
  Flathub's Spotify as silent.
- **The dock** could crash at start when switching layouts, and a dock on the
  left ran past the bottom of the screen.
- **Restore points** made by apt commands with options are named after the
  packages again, and *Put Back* lists the change a restore point was made
  before.
- **History** names apps better (Thunar no longer shows as *Bulk Rename*).
- **Sound** could crackle or break up while the computer was busy, because
  sound never got the real-time priority it needs.

## Trying it and installing

1. Download `FlickOS-64bit-v2.3.iso` and check it:
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
keys move (see *Keys for every keyboard layout*); hold `Super` to see yours.

## Known issues

- **Bring Files from Windows** has been tested on test disks, not yet on many
  real Windows computers. After copying, open a few files from your OneDrive
  folders: if one opens empty, download it from OneDrive instead, and please
  tell us.
- **The login screen** can't change an expired password. Press `Ctrl+Alt+F1`
  and log in on the text screen, which asks for a new one. If you ever get
  the old login screen, where you type your user name, the new one couldn't
  start: please tell us, with the output of
  `journalctl -b -t flickos-greeter`.
- **Web apps** use a Firefox feature that Mozilla hasn't turned on for Linux
  yet. A site that moves you to another address when you sign in (Teams does)
  may show in Software as not installed after you made its web app.
- **Wine** runs some Windows programs, not most, and takes about 3 GB.
- **Restore points only on new installs** with btrfs (see the 2.2 notes).
  They cover the system, not your home folder: keep backing up your files.
- **Opening Settings or the Welcome window a second time** doesn't bring the
  open window to the front, so it looks as if nothing happened. Find the
  window in the taskbar.
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

- ISO: https://sourceforge.net/projects/flickos/files/v2.3/
- Website: https://flickos.org
- Source code and issues: https://github.com/Flick-OS/flickos
- Community: https://www.reddit.com/r/flickos/
