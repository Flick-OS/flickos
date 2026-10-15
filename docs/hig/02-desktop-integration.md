# 02 – Fitting into the desktop

A FlickOS program is one part of a desktop that has three layouts, two styles,
a live session and an installed system. These rules keep it working, and
findable, in all of them.

## Finding it

### INT-1 Must: A program people open has a desktop file

Anything a user opens by name (a window, a sheet shown on request) has a
`.desktop` file in `/usr/share/applications/`, so fuzzel, the start menu and
Settings' search find it.

| Key | Rule |
|---|---|
| `Name` | Title Case, what the window is called ([TXT-2](05-writing.md#txt-2-must-title-case-for-names-sentence-case-for-everything-else)): `Settings`, `Keyboard Shortcuts` |
| `GenericName` | Only when `Name` doesn't say what it is |
| `Comment` | One sentence in sentence case, no final period, saying what the user can do: `Show the keyboard shortcuts (or hold the Super key)` |
| `Icon` | A freedesktop icon name that Numix-Circle has ([VIS-6](06-visual-style.md#vis-6-must-icons-come-from-the-icon-theme-by-standard-name)) |
| `Categories` | `Settings;DesktopSettings;` for settings, `System;` for system tools |
| `Keywords` | The words people type for it, including the words other desktops use (`hotkeys`, `control;center`) |
| `Exec` | The program and, if needed, its subcommand (`flickos-shortcuts show`) |
| `Terminal`, `StartupNotify` | `false` |

The file name is the Wayland app id ([INT-2](#int-2-should-the-wayland-app-id-is-the-desktop-file-name)).

**Don't:** give a daemon, a helper or a command-line-only tool a desktop file.
They aren't things people open.

### INT-2 Should: The Wayland app id is the desktop file name

Set `GLib.set_prgname(APP_ID)` before GTK starts, with `APP_ID` the desktop
file name without `.desktop`. labwc window rules, the dock's pins and the
taskbar match windows to apps by it. `flickos-control` does this in
`load_gtk()`.

### INT-3 Must: Every entry in the labwc menu is in both menus

The live menu (`flickos-installer`) is the installed menu (`flickos-settings`)
plus *Install FlickOS* and a separator. Change both in the same commit.
`tools/check-menus.py`, run by `build-iso.sh`, fails otherwise.

### INT-4 Must: Every setting can be found from Settings

A user-facing setting has a row on a Settings page (`flickos-control`), or a
tile on *More Settings* when another app owns it. The row's words, plus an
entry in `SEARCH_KEYWORDS` for a new page or tile, make it findable from the
search box. A test checks that every page and tile has keywords.

A setting that only exists on the command line or in a config file is fine for
experts, but it isn't a user-facing setting until it is in Settings.

### INT-5 Must: A new keybinding shows on the shortcut sheet

A key added to labwc (in `flickos-settings`' `rc.xml` or in a program's own
labwc fragment) gets a description in `flickos-shortcuts`' `COMMANDS` or
`ACTIONS`, so holding Super lists it. Before taking a key, check the sheet
(`flickos-shortcuts list`) and the keys of the desktop the layout copies. Use
Super for desktop actions. Leave Ctrl and Alt combinations to apps.

## Every layout, every style, every session

### INT-6 Must: It works in all three layouts and both styles

Test a change in Redmond (bottom panel), Cupertino (top bar and a dock that
auto-hides over windows) and Traditional (top panel, and window list with 4
desktops), in the Dark and the Light style. Things that break:

- A layer-shell surface (menu, sheet) anchored to the wrong edge, or covering
  the panel. Read the corner from the layout (`Menu=`, the `menu/anchor` file),
  don't assume the bottom left.
- Colors that are right in Dark and unreadable in Light
  ([VIS-2](06-visual-style.md#vis-2-must-follow-the-style-that-is-in-use)).
- Window buttons: Cupertino puts them on the left.

### INT-7 Must: The live session and the installed system each get what fits them

The live session (`boot=live` on the kernel command line) is for trying
FlickOS and installing it. Nothing done in it is kept.

- **Left out in the live session:** first-login windows, the *Login*, *Users* and
  *Updates* pages, idle locking, anything that only makes sense on an installed
  system. Check with `boot=live` in `/proc/cmdline` (see `live_system()` in
  `flickos-welcome`), and hide the page or card (`available()` returns false),
  don't show it disabled.
- **Only in the live session:** *Install FlickOS* and anything else for the
  installer, in `flickos-installer`, which Calamares removes on install.

### INT-8 Must: Only one window opens at first login

A new account's first login opens exactly one window: `flickos-welcome`.
Something new that a new user should see goes in as a card in it
(`CARDS`), not as another window from autostart.

## Starting and running

### INT-9 Must: New features are opt-in and run nothing while off

A new desktop feature keeps today's behavior as the default. It is turned on
with a switch in Settings, which runs the owning command's `set`
([SET-2](03-settings-and-files.md#set-2-must-cli-first-every-setting-is-a-command)).
While it is off:

- no process runs (no daemon waiting to be told it is on),
- nothing is generated in `$XDG_RUNTIME_DIR/flickos/`,
- no keybinding or panel module points at it.

Example: `flickos-menu`. While the apps button is fuzzel, no `flickos-menu`
process exists, there is no `menu/anchor` file, and the Super keybinds aren't
in the rc.xml overlay. `flickos-layout launcher set menu` creates all of them
and starts the daemon, and `set fuzzel` removes them again.

**The one exception: keeping a record.** A feature that runs no process,
generates nothing in the overlay, binds nothing and changes no behavior, and
only keeps a record of what the user does, may be on by default. It still has
a switch in Settings, and turning it off also deletes what it kept. The reason
is that a record started only after someone needs it is empty. The History
page is the one case so far: the owners append a line to
`~/.local/state/flickos/history.jsonl` when a setting changes, and nothing
else runs ([design](../design/flickos-history.md#adr-007-on-by-default-with-a-switch-to-turn-it-off)).

**A safety net.** A feature whose only job is to undo damage may be on by
default when, like a record, it would be useless if turned on only after the
damage. It runs no waiting daemon. It may run inside an operation that
already runs (an apt hook), and briefly at start. An ADR in its design
document states what it costs per event and the disk it holds. It keeps a
switch in Settings, which says what it holds and offers to delete it.
Restore points are the one case so far (planned): a snapshot in apt's hook
before each software change, and a start counter that runs for a few seconds
at each start
([design](../design/flickos-recovery.md#adr-002-a-restore-point-before-every-software-change-nothing-in-between-accepted)).

**Making a shipped feature the default.** A feature that has shipped opt-in
may later become the default, as a decision of its own: an ADR in its design
document that states what it then costs every session. It keeps its switch in
Settings, and everything above still holds while a user has it off. The start
menu is the one case so far: since flickos-layouts 1.23 the apps button opens
it unless the user chose the app launcher, for about 35 MB of private memory
and no CPU while idle
([design](../design/flickos-menu.md#adr-010-on-by-default)).

**A tool that runs only when asked.** A program that runs no process until
the user presses its key or opens it, generates nothing in the overlay, and
ends when its job is done may be installed for everyone with its keys bound,
like any app in the menu. What it costs while unused is its disk space and
its keys: an ADR in its design document names both, and the keys must not
take one an app or labwc already uses
([INT-5](#int-5-must-a-new-keybinding-shows-on-the-shortcut-sheet)). Anything
it adds that runs or shows without being asked (a panel module, a daemon)
still needs its own decision. Screenshots are the one case so far: the Print
keys, which existed already, Super+Shift+S and Super+Shift+R run
`flickos-screenshot`, and nothing of it runs in between
([design](../design/flickos-screenshot.md#adr-002-on-by-default-as-the-print-keys-already-are)).
Its panel button is such a decision: `custom/recording` is in every layout's
panel, empty and hidden while nothing records, because adding it only when a
recording starts would restart the panel into the video
([ADR-007](../design/flickos-screenshot.md#adr-007-while-recording-the-panel-shows-it-and-stops-it)).
It costs one `cat` of a missing file when the panel starts. Screen zoom is
the second case: labwc's own magnifier, so no program at all, with
Super+=, Super+-, Super+0 and Super+scroll bound for everyone
([design](../design/flickos-zoom.md#adr-002-on-by-default-keys-named-here)).

### INT-10 Must: Login programs start from FlickOS's autostart and stay single

A program that runs for the whole session is started by `flickos-settings`'
`/usr/libexec/flickos/autostart`, not by an XDG autostart entry (those are
the user's, handled by `flickos-control startup run`). It:

- runs once per session: a lock in `$XDG_RUNTIME_DIR/flickos/` (`daemon.lock`,
  `shortcuts.lock`) makes a second copy exit at once,
- doesn't hold up the others: autostart starts it in the background, and it
  waits for a shared lock at most a few seconds (`LOCK_SECONDS` in
  `flickos-layout`),
- exits when the compositor goes away.

### INT-11 Should: Panel programs run under the supervisor

A program that is part of the panel (a bar, the dock, the menu daemon) is
started by `flickos-layout panel` under `flickos-layout supervise`, which
restarts it after a crash and writes its output to
`$XDG_RUNTIME_DIR/flickos/panel.log`. Nothing else restarts panel programs,
and the session's own output goes nowhere a user can read.

### INT-12 Should: Notify only when there is no window to show it in

Use a notification (`notify-send -a NAME -i ICON`) for the result of
something that has no window: a key (Super+T turns tiling on), a background
job. When the user did something in a window, show the result in that window
([WIN-10](04-windows.md#win-10-must-show-results-and-errors-where-the-user-is-looking)).
Don't notify just to confirm what the user can already see.
