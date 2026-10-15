# 03 – Settings and files

How a FlickOS setting is owned, stored, changed and applied. These rules are
why a change made in Settings, in the panel, with a key or on the command line
always ends up the same, and why nothing FlickOS does can damage a user's own
configuration.

## Owning a setting

### SET-1 Must: Every setting has exactly one owner

One program stores a setting and applies it. Everything else, Settings
included, asks that program. No two programs write the same file.

| Setting | Owner |
|---|---|
| Layout, style, desktop clicks, clock, apps button, menu style | `flickos-layout` |
| Tiling | `flick-tiler` |
| Mouse, touchpad, keyboard, idle, language, night light, Do Not Disturb, startup apps | `flickos-control` |
| Time, time zone | `timedatectl` (systemd) |
| Animations (`enable-animations`) | GSettings; `flickos-control animations` changes it and records it |
| System language | `localectl` (systemd) |

A page in Settings for a setting it doesn't own is a view: it reads with the
owner's `list`/`current`/`status`/`state` and changes things by running the
owner's `set`. It never opens the owner's files.

### SET-2 Must: CLI first: every setting is a command

A setting exists on the command line before it gets a page. The owner has
commands a user could type:

```
flickos-layout clicks list        # the choices: id, name, description
flickos-layout clicks current     # the one in use
flickos-layout clicks set both-menu
flickos-control get [KEY]         # key, value, where it comes from
flickos-control set KEY VALUE|default
```

- `list` prints one choice per line, fields separated by tabs, id first.
- `set` applies the change at once and exits 0, or prints why not and exits 1.
- When a page needs many values at once, the owner gets a command that prints
  them all as JSON (`flickos-layout state`). One run replaces many, and Python
  starting up is most of what a run costs.
- When a page needs something the owner can't do, add it to the owner
  (`flick-tiler floating add`), not to the page.

This keeps every setting scriptable, testable in the boot test without a
window, and usable over ssh when the desktop is broken.

### SET-3 Should: Add a setting only when a default won't do

Every setting is a row to read, a code path to test and a way for two
computers to behave differently. Before adding one, try to find a default that
suits almost everyone. Add the setting when people really do want different
things (12-hour or 24-hour clock), or when the default can't be known
(keyboard layout).

## Storing it

### SET-4 Must: System defaults in `/etc/xdg/flickos/`, user choices in `~/.config/flickos/`

- **System default:** a conffile, `/etc/xdg/flickos/NAME.conf`, in the owner's
  package. An administrator or a custom build changes the default for every
  account there, and dpkg keeps their change on upgrade.
- **User choice:** `~/.config/flickos/NAME`, written only when the user changes
  something. Absent means "use the system default".
- **Format:** INI (`configparser`) or `KEY=value` lines, with a comment at the
  top saying which program writes it and where to change it.
- **Broken or missing:** a file that can't be read is treated as absent, with a
  warning on stderr. Never refuse to start because of a config file.
- **Not a choice:** a record of what happened goes in `$XDG_STATE_HOME/flickos/`
  (`~/.local/state/flickos/`), not in `~/.config`. The history of changes
  (`history.jsonl`) is the only one so far. Every owner appends its changes
  there with its own `record()` in the same format
  ([design](../design/flickos-history.md#adr-002-one-append-only-file-in-xdg_state_homeflickos)).

### SET-5 Must: Never write into files the user owns

FlickOS never creates, edits or deletes the user's configuration for other
programs: `~/.config/labwc/`, `~/.config/waybar/`, `~/.config/foot/`, GTK's
`settings.ini`, and the like. It also never copies FlickOS config into `$HOME`,
because a copied file stops getting updates.

What FlickOS needs is generated into the **overlay**, `$XDG_RUNTIME_DIR/flickos/`:

- regenerated at every login (`flickos-layout prepare`, `flickos-control prepare`),
- written atomically ([SET-6](#set-6-must-write-files-atomically)),
- deleted when not needed (the default layout and style have no rc.xml overlay),
- in RAM, so it never outlives the session.

When a user's own file blocks a FlickOS setting (their `rc.xml` hides the
overlay), say so: `flickos-layout doctor` lists it, and Settings shows the
warning on the page it affects.

Exceptions: FlickOS's own files under `~/.config/flickos/`, and the files a
setting is *about*, changed with that setting's standard tool:
`~/.config/mimeapps.list` through `xdg-mime`, `~/.config/autostart/` for
startup applications, `~/.config/xdg-terminals.list` for the default
terminal.

### SET-6 Must: Write files atomically

Write to a temporary file in the same folder, then rename it over the old one
(`write_atomic()` in `flickos-control`). A crash, a full disk or a second
process reading at the same moment must never see half a file.

## Changing it

### SET-7 Must: A change applies at once

Changing a setting takes effect immediately, without logging out: labwc
reloads (`flickos-layout reconfigure`), the panel restarts, the daemon gets a
signal. When a setting really can't apply until later, the row says when:
"From the next login", "The login screen uses it at its next start".

### SET-8 Must: Every setting can go back to its default

`set KEY default` (or the owner's equivalent) stores the default, and every
choice list includes the default. labwc never resets an option that
disappears from its config, so "default" writes the default value
explicitly rather than removing the line.

### SET-9 Must: Change a shared setting only while it still holds FlickOS's value

Some settings belong to everyone: the GTK theme, the icon theme, GTK's window
button layout. FlickOS changes one only while it holds a value FlickOS set.
`flickos-layout style set` changes `gtk-theme` only while it is one of the
styles' themes, so a theme chosen in nwg-look is kept. A layout changes
`button-layout` only while it holds the default or a layout's value.

## System settings

### SET-10 Must: System changes go through pkexec and a checked helper

A change outside the user's account (another user, `/etc`, a system service)
runs through polkit, never through `sudo` or a root GUI.

1. Prefer a system service that already asks polkit itself: `timedatectl`,
   `localectl`, logind.
2. Otherwise add a verb to the package's helper, `/usr/libexec/flickos/NAME-helper`
   (today only `control-helper`), run with `pkexec`:
   - one polkit action per verb (`org.flickos.control.VERB`, matched with
     `org.freedesktop.policykit.exec.argv1`), with a `<message>` that says
     what will change in plain words,
   - `auth_admin_keep` for the active session, `auth_admin` otherwise,
   - every argument checked against a fixed list or pattern before anything
     changes, and the helper exits with an error on anything else,
   - acting on the calling user only (`PKEXEC_UID`) unless the verb is about
     other users, and then never on the calling user's own account, a
     logged-in account or the last administrator.
3. The GUI stays a normal user process. It shows "Waiting for the password…"
   while pkexec asks.
4. A verb that only reads, and whose answer the GUI must share with a verb
   that changes (the software undo's plan: `packages-list`, `packages-plan`),
   may run without pkexec and has no polkit action. The helper lists them in
   `READ_ONLY` and refuses every other verb without root. Keep the checks in
   the helper, not in the GUI, so what runs as root is what was shown.
