# 05 – Writing

Every word in a window, a menu, a notification or a command's output is part of
the interface. People read less than we hope, so the words have to be short,
plain and the same everywhere.

## Voice

### TXT-1 Must: Plain words, about what the user wants to do

- Say what a setting *does* for the user, not how it works: "Lock the screen
  after", not "swayidle timeout". "Night light: warmer colors in the evening",
  not "wlsunset temperature".
- Don't name the program behind a feature in the interface (labwc, swaylock,
  kanshi, XKB, unattended-upgrades). They belong in docs, in `--help` and in
  error details, where an expert looks for them.
- Talk to the user as "you" and about FlickOS as "FlickOS", never "we" or "I".
- Short sentences. One idea per sentence. A row subtitle is one line where
  possible.
- Be calm and exact. No exclamation marks, no "Oops", no "Please" or "Sorry" in
  front of every instruction, no "simply" or "just".

**Do:** "Everything here can be changed later."
**Don't:** "Don't worry! You can simply change all of these settings at any
time you want!"

## Form

### TXT-2 Must: Title Case for names, sentence case for everything else

**Title Case** (capitalize every word except *a, an, the, and, or, of, for, to,
in, on, at, by* unless first or last):

- window and dialog titles: *Settings*, *Add User*
- page names: *Desktop Layout & Style*, *Power & Idle*
- buttons: *Keep This Arrangement*, *Check for Updates Now…*, and the tooltip
  of an icon-only button when it is only the button's name (*Shut Down*)
- menu items: *Lock Screen*, *All Settings*
- desktop file `Name`

**Sentence case** (capitalize only the first word and proper names):

- headings inside a page: *Desktop clicks*, *Kept arrangements*
- row titles and subtitles, check box and radio labels, card titles
- choices in a combo box: *Security fixes only*, *When nobody is logged in*
- tooltips that explain something (*Tile firefox again*), hints, warnings,
  notifications, status text
- desktop file `Comment`

Proper names keep their capitals everywhere: FlickOS, Debian, Wi-Fi,
Bluetooth, Do Not Disturb, the layouts (Redmond, Cupertino, Traditional) and
styles (Dark, Light).

### TXT-3 Must: An ellipsis means "more is needed before this happens"

A button or menu item ends in an ellipsis when choosing it doesn't finish the
job but opens something that needs more from the user first: a dialog
(*Add User…*), a password prompt (*Use for the Whole System…*), or another app
where the user does the job (*Arrange Screens…*).

- Use the single character `…` (U+2026), never three dots.
- No ellipsis when the action happens at once (*Lock Now*, *Copy System Info*),
  or when a menu entry opens an app that is the destination itself (*Settings*,
  *Wallpaper* in the labwc menu).
- Status text for something in progress also ends in `…`: *Loading…*,
  *Applying…*, *Waiting for the password…*

### TXT-4 Should: Punctuation

- A complete sentence ends with a period: subtitles, descriptions, hints,
  errors. A label that isn't a sentence has none: row titles, buttons,
  headings, choices, desktop file `Comment`.
- Use `&` only in page names and menu items that already have it (*Date &
  Time*). Write "and" everywhere else.
- Keys: *Super*, *Ctrl*, *Alt*, *Shift*, *Enter*, *Escape*, *Tab*. In running
  text they are joined with `+` and no spaces: *Super+T*, *Ctrl+F*. (The
  shortcut sheet draws key caps with room around the `+`, which is its own
  display.)
- A path through menus uses `→`: *Settings → Desktop Layout & Style*.
- Numbers as digits with a space before the unit: *5 minutes*, *4000 K*,
  *32 MB*. Write the plural out properly, never "minute(s)".
- Quotes: straight `"` in code, but no quotes around UI names in the
  interface. Italic in docs.

### TXT-5 Must: Use FlickOS's words

The same thing has the same name everywhere: menus, Settings, the start menu,
notifications, docs.

| Use | Not |
|---|---|
| Settings | Preferences, Control Panel, Control Center |
| app (in sentences). *Applications* only in established names (*Default Applications*, *Startup Applications*) | program, application (in sentences) |
| Lock Screen | Lock (on its own) |
| Log Out (button), log out (verb), login (noun) | Sign Out, Logout (as a verb) |
| Sleep | Suspend |
| Restart | Reboot |
| Shut Down (button), shut down (verb) | Power Off, Halt |
| desktop layout, layout | theme (for a layout) |
| style (*Dark*, *Light*) | theme, mode. *Theme* is GTK's, in *Appearance* |
| panel | bar, taskbar, waybar |
| dock | sfwbar |
| desktop (Traditional's 1 to 4) | workspace, virtual desktop |
| apps button, start menu | launcher, fuzzel |
| window buttons | title bar buttons, decorations |
| wallpaper | background |
| screen (in sentences). *Displays* is the page name | monitor, output |
| folder | directory |
| Super key | Windows key, Meta, Mod4, logo key |
| keyboard shortcut | hotkey, keybinding |
| Wi-Fi | WiFi, wifi, wireless LAN |
| administrator | root, sudo, admin |
| turn on, turn off | enable, disable, activate |
| Do Not Disturb | DND |
| phone (the phone connection's page and messages; tablets pair the same way) | device, mobile, handset |
| pair, forget (a phone) | link, connect, trust (for pairing); unpair, remove, delete (for forgetting) |

Add a word here when a new feature brings one.

## Messages

### TXT-6 Must: Errors say what happened and what to do

An error message in a window has up to two parts:

1. **What happened**, in the user's words: "The keyboard layout couldn't be
   changed."
2. **What to do**, when there is something: "Check that you typed the
   administrator's password."

Then, if it helps a bug report, the owner command's own message on the next
line, selectable. No stack traces, no exit codes, no "Error:" prefix (the
warning bar already says it's an error). A bug in FlickOS's own code shows
its exception type and message rather than loading forever (`Ui.background()`).

### TXT-7 Must: Command-line output follows one form

- **Messages for people** go to stderr as `NAME: message`, message in lower case
  and without a final period unless it is several sentences:
  `flickos-welcome: no cards to show`. Use the program's `warn()`.
- **Output for scripts** (`list`, `current`, `status`) goes to stdout, one item
  per line, fields separated by tabs, the id first, and doesn't change between
  versions except by adding fields at the end. JSON (`state`) for anything
  nested.
- **Exit codes:** 0 ok, 1 error, 2 usage error. Document them in the program's
  docstring.
- **`--help`** comes from argparse, with a one-line lower-case help string for
  every command.
- **Success is quiet**, apart from a short confirmation when a `set` did
  something the user can't see (`applied`). The boot test depends on these
  words, so don't change them casually.

## Translation-ready

FlickOS is English-only today and doesn't use gettext yet. These rules keep
the text ready for it, so translating later means marking strings, not
rewriting code.

### TXT-8 Must: Whole sentences in one string

- Never build a sentence from pieces (`"Remove " + name + "?"` is fine as one
  f-string, `"Remove" + " " + thing + " " + suffix` isn't). A translator must
  see the whole sentence, in its word order.
- Put the whole value in a placeholder, never part of a word or a plural
  ending.
- Plurals: pick between two complete strings (`"1 minute"` / `f"{n} minutes"`),
  never add an "s".
- Don't reuse one string in two places that only happen to look the same in
  English (the verb *Remove* and the heading *Remove*).

### TXT-9 Must: Leave room and let the system format

- No words inside images or icons. The FlickOS name in the artwork is the only
  text allowed, since it's never translated.
- Labels wrap or ellipsize ([A11Y-7](07-accessibility.md#a11y-7-must-layouts-survive-larger-text-and-scaling)).
  Assume a translation is up to 50% longer.
- Dates, times and numbers are formatted by the locale (`time.strftime` with
  `%x`, `%X`, or the user's 12/24-hour choice), not by hand-built patterns.
