# 04 – Windows and layout

How FlickOS windows are built: which kind to use, how big, how the content is
laid out, and how they react to what the user does. The Settings window
(`flickos-control`) is the reference. Its `Ui` class has the shared pieces
(rows, headings, pages, notices), so a new page gets them right by using it.

## Kinds of windows

| Kind | Use for | Example |
|---|---|---|
| **Main window** | An app: something opened from a menu, closed when done | Settings, Welcome, the layout chooser |
| **Dialog** | A question or a short form that must be answered before going on | *Add User*, *Remove …?* |
| **Layer-shell surface** | Part of the desktop, above or below all windows, no title bar | The start menu, the shortcut sheet, the dock |
| **Notification** | A result that has no window to go in ([INT-12](02-desktop-integration.md#int-12-should-notify-only-when-there-is-no-window-to-show-it-in)) | "Tiling is on" |

### WIN-1 Must: labwc draws the title bar

Windows use server-side decorations: a plain `Gtk.Window` with a title, no
`Gtk.HeaderBar`, no `set_titlebar()`. labwc draws the title bar in the
FlickOS theme and puts the buttons where the layout wants them (on the left
in Cupertino). Client-side title bars look different from every other window
and ignore the layout's button order.

### WIN-2 Must: One window per program and session

Opening a program that is already open doesn't open a second window. Take a
lock in `$XDG_RUNTIME_DIR/flickos/` (`single_instance()` in `flickos-control`)
and, when it is held, exit 0 with a short message on stdout ("Settings is
already open."). A second Settings window would show stale values and race
the first one's changes.

### WIN-3 Must: Windows fit on a 1366×768 screen

Many FlickOS computers are old laptops with 1366×768 screens. With the panel
and the title bar, about 1366×700 is left. A window's default size is at most
**1280×680**, and everything in it can be reached at that size, with scrolling
where needed.

- **Should:** it is still usable at 1024×600 (netbooks), with scrolling.
- Put long content in a `Gtk.ScrolledWindow` with the horizontal scrollbar off
  (`Ui.page()`), so the window can be smaller than its content.
- Pick a default size that shows the common case without scrolling: Settings
  is 900×660, Welcome 760×560.

### WIN-4 Must: The title is the program's name

The window title is the desktop file's `Name`, or starts with it, so people
recognize it in the taskbar (`Settings`, `Desktop Layout & Style`, `Welcome to
FlickOS`). A dialog's title names its job in Title
Case: `Add User`, `Change Password`. Don't put the app's name in a dialog title
and don't add a version.

## Layout

### WIN-5 Should: Space things on a fixed scale

Use these spacings (pixels, at scale 1). Don't invent others.

| Where | Spacing |
|---|---|
| Around a page or window content | 24 (`Ui.page()`) |
| Between groups (heading plus its list) | 18 |
| Between items in a group, between cards | 12 |
| Between a control and its label, buttons in a row | 6 to 12 |
| Inside a row, around the text (`Ui.row()`) | 10 |
| Between a title and its subtitle | 2 |

The rest comes from the Arc theme's own padding. Don't set margins on theme
widgets (buttons, entries) to change their size.

### WIN-6 Must: Settings are rows in framed lists, grouped under headings

A settings page is a column of groups. Each group is a heading
(`Ui.heading()`, bold, sentence case) and a framed list (`Ui.framed_list()`)
of rows (`Ui.row()`). A row has:

- a title on the left (sentence case, what the setting is: "Acceleration"),
- an optional subtitle under it, dimmed, saying what it does or its current
  effect,
- the control on the right, vertically centered.

Use `Ui` for this. Rows built with it are also indexed for search
([INT-4](02-desktop-integration.md#int-4-must-every-setting-can-be-found-from-settings)).

### WIN-7 Should: Pick the control that fits the choice

| Choice | Control |
|---|---|
| On or off, applies at once | `Gtk.Switch` |
| On or off inside a form or dialog (applies with its button) | `Gtk.CheckButton` |
| One of a few (2–4) things that are easier to see than to name | Cards (`Ui.cards()`): layouts, styles |
| One of a list | `Gtk.ComboBoxText` in a row (`Ui.combo_row()`) |
| A number in a range where the exact value doesn't matter | `Gtk.Scale`, applied once it rests (`SLIDER_DELAY_MS`) |
| A time or amount with a few sensible values | A combo with named values ("5 minutes", "Never"), not a spin button |
| Something another app does | A button that starts that app, ending in "…" (*Arrange Screens…*) |

### WIN-8 Should: Changes apply at once, without Apply or OK

In a main window, a control changes the setting as soon as it is used
([SET-7](03-settings-and-files.md#set-7-must-a-change-applies-at-once)).
There is no *Apply*, *OK* or *Save*, and closing the window loses nothing.
Use an explicit button only for a form whose values belong together (a dialog
with several fields), an action that needs a password, or a choice that is
expensive to try one option at a time. Put a short "Applying…" in the row while
the owner command runs.

The layout chooser (`flickos-layout pick`) keeps *Apply* for the last reason:
it is also a new account's first window, and every layout tried would restart
the panel. Settings' layout page applies at once.

### WIN-9 Should: Leave out what can't be used

A page, card, tile or row for something that isn't installed or doesn't apply
on this computer (no lid, no ufw, the live session) is left out, not shown
greyed out. Settings pages do it with `available()`, Welcome with `cards()`.
Grey a control out (`set_sensitive(False)`) only while it is temporarily
unusable and it is clear why: a form not yet valid, a command running, a
choice that depends on another one on the same page ("Start menu style" while
the apps button isn't the menu).

## Feedback

### WIN-10 Must: Show results and errors where the user is looking

- **A form field that is wrong:** a dimmed hint under the fields saying what's
  wrong ("The passwords don't match."), and the dialog's main button
  insensitive until it's right. No dialog about a dialog.
- **A change that failed:** the owner's message in the page's status label or
  in a warning bar (`Ui.notice()`, a `Gtk.InfoBar`) at the top of the page.
  Make the text selectable, so it can be copied into a bug report.
- **A warning about the system** (a user file blocks a setting): a warning bar
  on the page it affects.
- **Never** only print to stderr from a window. The user doesn't see it.

What the message says: [TXT-6](05-writing.md#txt-6-must-errors-say-what-happened-and-what-to-do).

### WIN-11 Must: Show that something is loading

Anything that takes longer than about 100 ms after the window is drawn shows
that it is working: a spinner with "Loading…" (`Ui.loading()`) in place of the
content, or "Applying…" in the row that changed. The rest of the window stays
usable ([PERF-2](08-performance.md#perf-2-must-never-block-the-main-loop)).

### WIN-12 Should: Say something when there is nothing

An empty list says so in a dimmed row ("None", "No settings found"), with the
way to add something next to it when there is one (*Add App…*). A blank frame
looks broken.

## Dialogs

### WIN-13 Must: Ask before what can't be undone, and only then

An action that loses something for good (removing a user, deleting their
files) asks first, with a `Gtk.MessageDialog`:

- the question names the thing: "Remove Ana Cruz?",
- the secondary text says what will be lost or what happens next,
- buttons are *Cancel* and a verb for the action (*Remove*), never *Yes*/*No*
  or *OK*,
- the action button has the `destructive-action` style class,
- the default response is *Cancel*, so Enter doesn't destroy anything.

Actions that can be undone (switching a layout, turning a setting off) don't
ask. Asking too often teaches people to click through.

**Exception: pop-ups.** flickos-menu's menus and Quick Settings close when
they lose the focus, so they can't hold a dialog. There, such a button asks
for a second click instead: the first click turns it `destructive-action` and
says next to it what a second click does ("Click again to shut down"); the
second click within a few seconds runs it, and anything else puts it back
(flickos-menu's `PowerRow`, used by Log Out, Restart and Shut Down).

### WIN-14 Must: Dialog buttons are Cancel and a verb

A dialog with a form has *Cancel* on the left and the action on the right,
named for what it does (*Add*, *Change*), with the `suggested-action` style
class, as the default response. Enter in the last field activates it
(`activates_default=True`). Escape cancels. Dialogs are modal and transient for
their window.
