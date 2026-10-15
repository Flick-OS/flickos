# 10 – Code

FlickOS's programs are small, read-once-understand-all Python files. These
rules keep them that way, and collect the traps in GTK 3, labwc and Wayland
that have already cost a day each.

## Shape of a program

### CODE-1 Must: One program, one Python file, standard library

- A FlickOS program is one executable file, `#!/usr/bin/python3`, in
  `usr/bin/` or `usr/libexec/flickos/`. No modules next to it, no `setup.py`, no
  pip, no virtualenv.
- It imports the Python standard library, plus `gi` (python3-gi) for a window.
  Anything else needs a reason in `debian/control`
  ([PERF-8](08-performance.md#perf-8-must-no-heavy-dependencies)).
- When the file gets long, split it into sections with a comment banner
  (`# --- The window ---`), not into modules. A reader should be able to find
  everything with one search.

### CODE-2 Must: The docstring is the manual

The module docstring says, in plain sentences:

1. what the program is and what it owns (which settings, which files),
2. how it fits with the other FlickOS programs,
3. every command, one line each,
4. the exit codes (`0 ok, 1 error, 2 usage error`).

Keep it in step with the code. `flickos-welcome` is a short example,
`flickos-control` a long one.

### CODE-3 Must: Tables at the top drive the code

What a program shows or supports is a table of constants at the top, not
logic spread through functions: `PAGES`, `TILES`, `SETTINGS` in
`flickos-control`, `CARDS` in `flickos-welcome`, `COMMANDS`/`ACTIONS` in
`flickos-shortcuts`, `CLICKS` in `flickos-layout`. Adding a page, card or
keybinding is adding a row. Every constant has a short comment saying what it
is and who else depends on its value ("Below flickos-shortcuts' HOLD_MS
(700)").

### CODE-4 Must: Commands through argparse, `main()` returns the exit code

```python
def main(argv=None):
    parser = argparse.ArgumentParser(prog=NAME, description="…")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser("list", help="print …").set_defaults(func=cmd_list)
    opts = parser.parse_args(argv)
    return opts.func(opts)

if __name__ == "__main__":
    sys.exit(main())
```

One `cmd_NAME(opts)` function per command. Tests call `main([...])`.

A pkexec helper is the exception: it runs as root, so it checks its fixed
verbs and arguments by hand (`VERBS` in `control-helper`) and accepts nothing
else, not even the options and abbreviations argparse would add.

### CODE-5 Should: Write like the code around you

- PEP 8 names and 4-space indents, lines up to about 120 characters.
- f-strings, `contextlib.suppress` for an error that's expected and harmless,
  `dataclasses` for records. No type hints (none of the programs use them).
- Comments say *why*, especially the fact about labwc, GTK or Debian that
  forces the code to look this way ("labwc never resets an option that
  disappears"). Don't comment what the next line obviously does.
- Test hooks are environment variables named `FLICKOS_NAME_PREFIX`, read once
  at the top.

## Failing well

### CODE-6 Must: Expected failures are messages, bugs are loud

- An expected failure (a command failed, a file is missing, input is wrong)
  raises the program's own exception (`ControlError`) or returns an error, and
  becomes a message for the user ([TXT-6](05-writing.md#txt-6-must-errors-say-what-happened-and-what-to-do)).
- An unexpected exception in a background task prints its traceback to stderr
  *and* shows its type and message in the window. A spinner that never stops
  is the worst kind of error message.
- No bare `except:`. Catch what you expect, and let the rest through.
- A missing optional program is not an error: check with `shutil.which()` and
  leave its feature out.

### CODE-7 Must: Run other programs safely

- Always an argument list, never `shell=True` with anything a user or a file
  supplied.
- Secrets (passwords) go on stdin, never in arguments, where `ps` would show
  them.
- A program started for the user lives on after the window closes: `Popen(...,
  start_new_session=True, stdin=DEVNULL)` or `Gio.Subprocess` with
  `wait_async` so it's reaped.
- A command that can hang gets a timeout (`COMMAND_SECONDS`).

### CODE-8 Must: Files and locks the FlickOS way

- Config paths from the XDG variables with their fallbacks (`XDG_CONFIG_HOME`
  or `~/.config`). Session state in `$XDG_RUNTIME_DIR/flickos/`. Fail clearly
  if `XDG_RUNTIME_DIR` isn't set.
- Write with a temporary file and a rename ([SET-6](03-settings-and-files.md#set-6-must-write-files-atomically)).
- Single instance and shared state are guarded with `fcntl.flock` on a file in
  `$XDG_RUNTIME_DIR/flickos/`, never with a PID check alone. A lock that
  another program might hold is waited for with a limit.

## GTK 3

### CODE-9 Must: Load GTK 3 late and check for a display

```python
def load_gtk():
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib
        GLib.set_prgname(APP_ID)
        from gi.repository import Gtk
    except (ImportError, ValueError) as error:
        warn(f"GTK 3 is not available ({error})")
        return None
    if not Gtk.init_check(sys.argv[:1])[0]:
        warn("cannot open a window (no display)")
        return None
    return Gtk
```

GTK 3 only ([01](01-principles.md#4-reuse-dont-rewrite)): GTK 4 and libadwaita
ignore the Arc theme and draw their own title bars. Surfaces that are part of
the desktop use gtk-layer-shell (`GtkLayerShell`), with keyboard
interactivity only while they need keys.

### CODE-10 Must: Avoid the known traps

These have each broken a FlickOS program before:

| Trap | What to do |
|---|---|
| A GLib source with a priority *higher* than GDK's events that maps a layer-shell window hangs forever in `gtk_widget_map` | Use `GLib.PRIORITY_DEFAULT` for signal handlers and idles that show windows |
| `Gio.ThemedIcon.new_from_names()` tries every name in one theme first, so a poor fallback wins | Pick the first name with `Gtk.IconTheme.get_default().has_icon()` ([VIS-6](06-visual-style.md#vis-6-must-icons-come-from-the-icon-theme-by-standard-name)) |
| `Gtk.Clipboard.set_text()` needs a recent input serial on Wayland and fails silently without one | Copy with `wl-copy` |
| `Gio.AppInfo.get_all_for_type()` reads `mimeinfo.cache`, not the apps' `MimeType=` | Rely on desktop-file-utils, and check `get_supported_types()` |
| `xdg-terminal-exec` skips a desktop file whose `Exec=` uses single quotes | Double quotes only in `Exec=` |
| The first show of a new layer-shell window costs 50–100 ms | Build it hidden, `realize()` and `get_preferred_size()` ahead ([PERF-10](08-performance.md#perf-10-should-do-slow-work-before-it-is-needed-off-the-critical-path)) |
| `GtkFlowBox` filtering hides children with `set_child_visible(False)` | Check `get_child_visible()` when looking for the first shown child |
| An active `Gtk.Spinner` on a `GtkStack` page that isn't shown keeps animating: 60 redraws a second, measured as about 3,500 wakeups a minute (Software, 2026-10) | Start a spinner on `map` and stop it on `unmap` (`Ui.loading()`, Software's `spinner()`); a hidden spinner doesn't animate |

Add a row when you find a new one.

## labwc and Wayland

### CODE-11 Must: Work with what labwc and Wayland allow

- **No X11.** Nothing uses `xdotool`, `xprop`, `DISPLAY` or X11-only GDK calls.
- **Windows can't be placed from outside.** labwc doesn't let one program move
  another's windows. Tiling writes labwc regions and window rules into a
  fragment that `flickos-layout reconfigure` merges ([`flick-tiler`](../../packages/flick-tiler/usr/bin/flick-tiler)).
- **Windows can't be embedded.** Settings starts another app's window instead
  of showing it inside.
- **labwc ignores config keys it doesn't know**, without a warning. Before
  relying on an rc.xml key, confirm in a spike that labwc 0.8.3 (trixie)
  accepts it, and keep the list in a test.
- **labwc never resets a removed option.** Write the default value explicitly
  ([SET-8](03-settings-and-files.md#set-8-must-every-setting-can-go-back-to-its-default)).
- **labwc sends modifier changes to every client**, focused or not. That's
  what lets `flickos-shortcuts` and `flickos-menu` see Super without a
  keybinding. Don't treat a modifier event as proof of focus.
- **labwc reads the first rc.xml it finds and never merges.** FlickOS's
  changes go through the overlay ([SET-5](03-settings-and-files.md#set-5-must-never-write-into-files-the-user-owns)).

### CODE-12 Should: Spike before building

Before a design depends on how labwc, GTK or a Debian tool behaves, test that
behavior on its own in the headless labwc harness, and write down what was
confirmed (date, versions) in the design doc's phase 0. Several FlickOS
designs changed after a spike showed the obvious approach doesn't work on
labwc.

## Shell

### CODE-13 Must: Shell scripts are POSIX sh

- `#!/bin/sh`, POSIX only (it runs under dash), `set -e` in hooks and
  wherever a failed step must stop the script.
- Quote every variable expansion. Use `command -v` to test for a program.
- Keep shell for glue (session start, autostart, small wrappers). Anything with
  logic, parsing or state is Python.
- live-build hooks are in `config/hooks/normal/`, numbered 0001–0999, and
  executable.
