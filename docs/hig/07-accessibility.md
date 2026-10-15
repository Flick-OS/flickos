# 07 – Accessibility

FlickOS runs on old laptops with worn touchpads, on small screens and on big
ones with scaling, for people with poor eyesight and people who never touch a
mouse. All four areas below are Must: a FlickOS program that can't be used one
of these ways is broken, not unpolished.

## Keyboard

### A11Y-1 Must: Everything works without a mouse

Every action in a FlickOS window or surface can be done from the keyboard
alone:

- Tab and the arrow keys reach every control, in reading order (top to bottom,
  left to right).
- Nothing is mouse-only. Something on right-click also opens with the Menu key
  and Shift+F10. Something on hover also shows on focus. A drag has a button or
  a key that does the same.
- A gesture or a timed key (hold Super, tap Super) always has a plain
  alternative too: the shortcut sheet is also *Keyboard Shortcuts* in the menu,
  and the start menu also opens from the panel button.
- The first focus is where the user will act: the search box in the start
  menu, the first field in a dialog.

### A11Y-2 Must: Escape backs out

- Escape closes dialogs, popovers, menus and sheets, and cancels whatever they
  were about to do.
- In a window with a search box, Escape first clears the search.
- **Should:** Escape also closes a window whose only job is a quick choice (the
  layout chooser). Main windows close with Super+Q (labwc) and should also
  close with Ctrl+W.

### A11Y-3 Must: Mnemonics on buttons and form labels

Buttons, check boxes and the labels of form fields have a mnemonic (Alt plus
the underlined letter): `Gtk.Button.new_with_mnemonic("_Add User…")`, and a
label with `use_underline=True, mnemonic_widget=entry`. Within one window or
dialog, each letter is used once. Standard buttons keep the usual letters:
*_Cancel*, *_Close*, *_Apply*, *_Remove*.

### A11Y-4 Should: The usual shortcuts work

- Ctrl+F focuses the search box where there is one. Typing a letter anywhere
  outside a text field starts a search (Settings does both).
- Enter activates the default button in a dialog or the first search result.
- A button's shortcut, if it has one, is in its tooltip.

## Seeing

### A11Y-5 Must: The focus is always visible

Keep the theme's focus ring. Never remove it in CSS (`outline: none`, a
transparent border on `:focus`). When the focused widget scrolls, it stays in
view (Settings' search scrolls the result's row into view and focuses its
control).

### A11Y-6 Must: Text is readable in both styles, and color is never the only signal

- **Contrast:** text meets WCAG AA against its background, in Dark and in
  Light: at least 4.5:1 for normal text, 3:1 for large text (18 pt, or 14 pt
  bold) and for the outlines of controls. Arc's accent blue (`#5294e2`) is
  below 4.5:1 on both backgrounds, so it isn't a color for text. The theme's own colors do. Check any color you set, and
  translucent backgrounds against the lightest and darkest wallpaper.
- **Dimmed text** (`dim-label`) is for secondary text only: a subtitle, a hint.
  Anything the user must read to use a control is not dimmed.
- **Not by color alone:** a state is also shown with a word, an icon or a
  shape. The chooser marks the layout in use with a "Current setting" badge,
  not just a highlight. A warning has the warning bar's icon, not just orange
  text. A running app in the dock has a marker, not only a tint.

## Assistive technology

### A11Y-7 Must: Layouts survive larger text and scaling

People turn up the font size in *Appearance* and the screen scale in
*Displays*. At text scale 1.5 and screen scale 2, nothing is cut off,
overlaps or needs horizontal scrolling:

- Labels that can grow wrap (`wrap=True` with `max_width_chars`, as
  `Ui.label()` does) or ellipsize with the full text in a tooltip.
- `set_size_request()` gives a *minimum* width, never a height for text, and
  never a fixed size for a container of text. Let GTK size things from their
  content.
- Test with `gsettings set org.gnome.desktop.interface text-scaling-factor 1.5`
  and a labwc output scale of 2 (`wlr-randr --output NAME --scale 2`).

### A11Y-8 Must: Every control has a name a screen reader can say

Orca isn't installed by default, but anyone can add it, and GTK 3 exposes
FlickOS windows to it through ATK.

- A button with only an icon has a tooltip *and* an accessible name, both
  saying what it does:
  ```python
  button = Gtk.Button(relief=Gtk.ReliefStyle.NONE, tooltip_text=text)
  button.get_accessible().set_name(text)          # flickos-menu's icon_button()
  ```
- A form field is named by its label (`mnemonic_widget`), a row's control by
  the row's title (`label.set_mnemonic_widget(control)`, or
  `get_accessible().set_name(title)`).
- An image that carries information not given in text next to it has an
  accessible description. A decorative one, or a layout preview beside the
  layout's name, doesn't need one.
- A layer-shell surface that takes no keyboard focus (the shortcut sheet while
  Super is held) is a shortcut, not the only way: the same content opens as an
  interactive surface (`flickos-shortcuts show`).
