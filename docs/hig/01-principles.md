# 01 – Principles

Four ideas are behind every rule in this HIG. When a situation isn't covered by
a rule, decide by these. When two of them pull in different directions, the
one higher in the list wins.

## 1. Nothing breaks, nothing is lost

People install FlickOS on the computer they use every day, often an old one
that holds everything they have. A desktop that loses their settings, breaks
after an update or can't be put back the way it was isn't worth being fast or
pretty.

- **The user's files are theirs.** FlickOS never writes into `~/.config/waybar`,
  `~/.config/labwc/rc.xml` or any other file the user may have edited. It
  generates what it needs in `$XDG_RUNTIME_DIR/flickos/` at every login, and it
  *warns* about user files that get in the way (`flickos-layout doctor`)
  instead of changing them.
- **Updates reach everyone.** Installed systems get FlickOS changes only
  through the apt repository, so every change ships in a package with a higher
  version. Nothing that should keep working is dropped straight into the image.
- **Every change can be undone.** A setting can always go back to its default
  (`set KEY default`), and to what it was before: its owner records every
  change, and *Settings → History* undoes it, or puts every setting back as
  it was on an earlier day. A layout, style or menu choice
  can be switched back live. Actions that can't be undone (removing a user, deleting files) ask first and
  say what will be lost.
- **One broken piece doesn't take the rest down.** A dock that fails to start
  is left out and the bars still start. A panel program that crashes is
  restarted (`flickos-layout supervise`). A program that isn't installed makes
  its card, tile or page disappear instead of showing a broken button.

## 2. Light and fast

FlickOS came from LXLE, a desktop for old and low-end computers, and it keeps
that promise. Speed is a feature people notice every day. Memory and disk are
what decide whether FlickOS runs on their machine at all.

- **Windows open at once.** Something is on screen within about half a second,
  and slow work happens after the window is drawn, with a spinner.
- **Off means off.** A feature that is turned off runs no process, holds no
  memory and adds nothing to login time. The start menu's daemon runs only
  while the menu is on, kanshi only while a screen arrangement is kept.
- **New features are opt-in.** Existing behavior stays the default, and a new
  feature is turned on in Settings by the people who want it. Making one the
  default later is a decision of its own, with its cost stated (the start
  menu).
- **Costs are known.** Every new daemon, dependency or feature states what it
  costs in memory, disk and startup time, measured, before it is merged.
  gufw was rejected because it would pull in a 134 MB web engine for one page
  of switches.

## 3. Familiar

People come to FlickOS from Windows, macOS or older Linux desktops. They
should find things where they expect them and never have to learn a new
concept to do an everyday job.

- **The layouts copy what people know.** Redmond works like Windows, Cupertino
  like macOS, Traditional like GNOME 2. Inside a layout, follow the desktop it
  copies (the start menu's Redmond style is a Windows 7 menu).
- **Plain words.** "Sleep", "Lock Screen", "Keyboard layout", not "suspend to
  RAM", "swaylock" or "XKB".
- **Settings are in Settings.** Every user-facing setting can be found in the
  Settings window (by its page or its search box), even when another program
  owns it.
- **One way to look.** Every FlickOS window follows the same Arc theme, the same
  spacing and the same wording. A user switching between Settings, the start
  menu and the welcome window shouldn't see three designs.

## 4. Reuse, don't rewrite

FlickOS is Debian with a small layer of its own. The less code it has, the
fewer bugs, the less to maintain and the easier it is to trust.

- **Use what Debian ships.** A setting goes through the tool that already
  handles it: `timedatectl` for the time, `localectl` for the language,
  `xdg-mime` for default apps, kanshi for screen arrangements, ufw for the
  firewall. FlickOS adds a view over them, not a replacement.
- **A hub, not a rewrite.** When a good app for a job already exists
  (wdisplays, pavucontrol, nm-connection-editor), Settings starts it rather
  than rebuilding it as a page.
- **Build only what is missing.** FlickOS writes its own program only when
  nothing in Debian does the job on labwc (tiling, the start menu, the shortcut
  sheet). Such programs stay small: one file, Python's standard library, GTK 3.
- **Stay close to Debian.** `ID=debian` stays in `os-release`, packages are
  ordinary native Debian packages, and a FlickOS system can drop back to plain
  Debian by removing FlickOS's packages.

## When the principles meet

- A feature that would be familiar but costs a lot of memory (a blurred panel,
  an animated dock): make it opt-in, or leave it out (*light* over *familiar*).
- A faster way that writes into the user's config files: don't
  (*nothing lost* over *light*).
- A rewrite that would look more polished than the Debian tool it replaces:
  start the Debian tool instead, unless it can't do the job on labwc (*reuse*).
