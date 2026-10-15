# Audit of the existing packages

Where FlickOS's packages don't yet follow the HIG. First audit 2026-09-26
(commit `76b060b`). Most of it was fixed the same day in flickos-control 1.13,
flickos-layouts 1.21, flickos-menu 1.4, flickos-shortcuts 1.5, flickos-welcome
1.2, flickos-settings 1.24 and flickos-installer 1.18. This page lists only
what is still open. When a finding is fixed, delete its row in the same
commit. When a rule changes, check the packages again
([README](README.md#changing-the-hig)).

Findings marked **check** need a test before anyone can say whether they're
real. **decide** means the fix changes the look and needs the maintainer's
decision first.

## Open findings

| Package | Rule | Level | Finding | Suggested fix |
|---|---|---|---|---|
| All GTK windows | [A11Y-6](07-accessibility.md#a11y-6-must-text-is-readable-in-both-styles-and-color-is-never-the-only-signal) | decide | arc-theme draws dimmed text (`dim-label`: row subtitles, descriptions, hints) at 55% opacity, which is below 4.5:1 in both styles: 3.3–3.6:1 in Arc-Dark, 2.3–2.4:1 in Arc. White on the selection blue is 3.1:1. Normal text passes (5.7–7.8:1) | Dimmed text would need at least 74% opacity in Dark and 89% in Light. Options: FlickOS programs load a small CSS that raises `.dim-label` (one value, 0.9, passes both styles but hardly dims in Dark); or use dimming only where the text isn't needed to use the control; or accept arc-theme's values and write that down in A11Y-6. The selection color is arc-theme's own and can only change with a theme of FlickOS's own |
| flickos-control | [WIN-2](04-windows.md#win-2-must-one-window-per-program-and-session) | check | A second start prints "Settings is already open." and exits, but the open window doesn't come forward, so from the menu nothing seems to happen. flickos-welcome, the chooser and Software do the same | Find out whether labwc 0.8.3 lets the second process activate the first window (an xdg-activation token passed to it over a socket). If it can't, record the limit in `docs/design/flickos-control.md` |
| flickos-control, flickos-phone, flickos-software | [CODE-1](10-code.md#code-1-must-one-program-one-python-file-standard-library), [PERF-1](08-performance.md#perf-1-must-meet-the-time-budgets) | decide | A script in `/usr/bin` gets no `.pyc`, so Python compiles it at every start: flickos-control's 7,200 lines take about 170 ms of its 0.88 s to the first frame (and of every `get`, which Quick Settings runs at each show), flickos-phone's 4,000 lines run again at every `status --panel`, flickos-software's 2,600 lines take about 160 ms of its `list` (about 300 ms in all, against PERF-1's 200 ms) and of the `plan` child each app page starts | An exception to CODE-1: the program stays one file, moved to a module (`/usr/share/flickos/NAME/NAME.py`, byte-compiled by `dh_python3` or `py3compile` in the package), with a two-line launcher in `/usr/bin`. Or accept the cost and write it into PERF-1 |
| flickos-control | [PERF-3](08-performance.md#perf-3-must-build-first-read-later) | | Constructors still read: every settings page reads all 18 settings files (`load_values`), *Keyboard* the XKB rules (40 ms), *More Settings* asks the icon theme (110 ms, its first load). Since 1.32 they run after the first frame, one page per idle call, but each still holds the main loop that long | Read in `shown()`: the settings pages already read again there (`reload`), so the constructor can set the controls from the defaults; *Keyboard* fills its lists when shown |
| All GTK windows | [A11Y-7](07-accessibility.md#a11y-7-must-layouts-survive-larger-text-and-scaling) | check | Tried at text scale 1.5 in the headless harness (Settings, Welcome, the chooser, the classic and categories menus), all usable. Screen scale 2 and the grid menu aren't tried yet | Try screen scale 2 on a large output, and the Cupertino grid menu at text scale 1.5 |

## Fixed on 2026-09-26

For the record, so the same thing isn't reported again:

- **flickos-control 1.13:** every switch, list and slider in a row is named
  after the row for screen readers (`Ui.name_control()`), as are the time zone
  lists and the floating list's remove buttons. Ctrl+W closes the window. The
  power button's choice reads "Shut down", and the password dialog is titled
  *Change Password*.
- **flickos-layouts 1.21:** the chooser opens at 620×680 and fits 1366×768. Its
  choices scroll and the buttons stay in view. Why it keeps *Apply* is in the
  code and in [WIN-8](04-windows.md#win-8-should-changes-apply-at-once-without-apply-or-ok).
- **flickos-menu 1.4:** the Menu key and Shift+F10 open the pin menu of the
  focused app (the key used to go to the search field). "Lock Screen", "All
  Apps", "Pin to Start Menu". Tooltips carry the whole app name and the user's
  name, which the classic menu cuts short at large text sizes.
- **flickos-shortcuts 1.5:** the sheet uses the theme's named colors, so it is
  light in the Light style. Headings and the hint are in the text color, since
  the accent blue is below 4.5:1 on Arc's light background.
- **flickos-welcome 1.2:** one window per session, Escape closes it, *_Close*
  has a mnemonic, the cards have accessible names, and the app id is set.
- **flickos-settings 1.24, flickos-installer 1.18:** the Session menu says
  *Sleep* and *Restart*.

## Checked on 2026-10-05

flickos-phone's phases 7–11 (notifications, calls, *Browse Phone*, media
control, named commands; flickos-phone 1.9–1.14, flickos-control
1.27–1.31) against the checklist, and Settings' opening time. Fixed in
flickos-phone 1.15 and flickos-control 1.32:

- **PERF-5:** media control read the players with `playerctl` every 2
  seconds while a phone was connected: 21 s of CPU in 38 minutes, ten times
  the daemon's own. One `playerctl --follow` now wakes the daemon only when
  a player changes. VLC, which owns two MPRIS names, showed twice on the
  phone.
- **PERF-1:** Settings took 1.3 s to its first frame. It now builds only the
  page it opens on before the first frame (0.88 s).
- **CODE-2:** flickos-phone's docstring listed no commands.
- **Beyond the checklist:** a phone notification's text was read as
  markup, so a chat message could restyle itself into a fake alert; shown
  notifications (a waiting `notify-send` each) and cached icons had no
  limit; the tests wrote icons into the build host's `~/.cache`.
- **TXT-6:** *Browse Phone*'s errors for an incomplete answer from the phone
  said nothing about what to do.
- **PKG-3, PKG-9:** flickos-control's `Breaks` didn't cover the commands
  list (flickos-phone 1.14). The boot test didn't check that media control
  is off in the live session, or that `ssh-keyscan` is installed.

In line: every new feature is off until turned on and announces its packets
only then (INT-9, PERF-4; commands only while the list has one); each has a
`set … default` and History labels with Undo (SET-8); the conffile documents
the new keys (SET-4); nothing acts on the phone's word while the screen is
locked; the *Add Command* dialog has *Cancel* and a suggested *Add* that
stays off until both fields are filled (WIN-14), with unique mnemonics
(A11Y-3); the browse password goes on stdin and a named command starts in
its own session with no input (CODE-7); new dependencies are commented
(PKG-4) and every phase came with unit tests (PKG-8).

## Checked and passing

What the first audit looked at and found in line:

- **WIN-1:** no program uses a header bar or client-side title bar.
- **WIN-3:** Settings (900×660), Welcome (760×560), the chooser (620×680) and
  Settings' dialogs fit 1366×768.
- **WIN-13, WIN-14:** removing a user asks with a named object, a *Remove*
  button in the destructive style and *Cancel* as the default. The *Add User*
  form has *Cancel* plus a suggested *Add* that stays insensitive until the
  form is valid.
- **TXT-3:** every button that opens a dialog, a password prompt or another
  app ends in `…`, and none that acts at once does.
- **TXT-7, CODE-2, CODE-4:** every program has a docstring with its commands
  and exit codes 0/1/2, and `NAME: message` warnings. All use argparse
  subcommands except `control-helper`, whose hand-checked verbs CODE-4 allows.
- **VIS-2, VIS-4:** Settings, Welcome and the chooser have no CSS. The start
  menu's and the shortcut sheet's CSS use only the theme's named colors, scoped
  under their program's class. The login screen's hard-coded colors are an
  allowed exception.
- **VIS-6:** Settings' tiles and the start menu pick the first icon name the
  theme has.
- **A11Y-8:** the start menu's icon buttons set a tooltip and an accessible
  name (`icon_button()`), the example the rule uses.
- **INT-9, PERF-4:** the start menu runs nothing while it is off (the boot test
  checks that no daemon runs, and that there is no anchor file and no keybind).
  History, on by default under INT-9's exception for records (2026-09-26),
  runs no process and generates nothing in the overlay.
- **INT-5:** the shortcut sheet reads the keybinds from the rc.xml labwc uses,
  and the boot test checks that it lists FlickOS's keys with descriptions.
- **SET-10:** `control-helper` has one polkit action per verb, checks every
  value, and takes passwords on stdin.
- **PKG-4, PKG-8:** every program package comments its dependencies and runs
  its unit tests at build time.
- **CODE-7:** no `shell=True`, no bare `except:` anywhere.
