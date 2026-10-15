# 06 – Visual style

FlickOS looks like one thing: arc-theme's Arc-Dark by default, Arc in the Light
style, Numix-Circle icons, the system font. A FlickOS program gets almost all
of that for free by *not* styling itself.

The palette itself, with every color's role, is in
[09 – Customizing: The Arc-Dark palette](../09-customizing.md#the-arc-dark-palette).

## Color

### VIS-1 Must: Only the palette's colors

Every color in a FlickOS file is one of arc-theme's colors: Arc-Dark's, or
Arc's for the Light style's own files. `tools/check-palette.py` holds both
lists and checks every file that contains colors, and `build-iso.sh` stops on
a color that isn't in them.

The one color of FlickOS's own is the **brand amber**, `#ffb13d`, with
`#2f343f` for text on it (never white: 1.81:1). It is only for the brand
surfaces: the logo, the boot menus, the boot splash, the installer and the
artwork. The checker allows it only in those files (`BRAND_FILES`), so the
desktop keeps Arc's blue; a program's accent is `@theme_selected_bg_color`
([VIS-2](#vis-2-must-follow-the-style-that-is-in-use)), never amber. The one
exception is the logo on the panel's start button, through the styles'
`brand_color` (`#c98000` on Light, where `#ffb13d` is too faint).

A new color is a design decision: add it to the checker deliberately, with the
arc-theme role it comes from, in the same commit.

### VIS-2 Must: Follow the style that is in use

The user picks Dark or Light in *Settings → Desktop Layout & Style*, and every
FlickOS surface follows at once. How depends on what draws it:

| Surface | How it follows the style | Example |
|---|---|---|
| A GTK window | The GTK theme. No CSS at all | Settings, Welcome, the layout chooser |
| A GTK surface that needs CSS (layer shell, custom widgets) | CSS that uses only the theme's named colors: `@theme_bg_color`, `@theme_fg_color`, `@theme_base_color`, `@theme_selected_bg_color`, `@borders`, `alpha(@…, 0.25)` | The start menu |
| The panel | The layout's CSS uses only named colors, defined by the style's `waybar-colors.css` | Every layout |
| foot, fuzzel, mako | The style's palette file, `include=`d after the base config | `styles/light/foot.ini` |

**Stays Arc-Dark in every style:** the boot menus, the boot splash, the
installer and the login screen, because they show before any user has picked a
style. The boot menus, the splash and the installer have the brand amber as
their accent ([VIS-1](#vis-1-must-only-the-palettes-colors)); the login screen
has none. Also the lock screen's plain color and the color around a wallpaper
that doesn't fill the screen (`SWAYLOCK`, `WALLPAPER_COLOR`), which frame
pictures rather than hold text. These are the only places a FlickOS file
hard-codes Arc-Dark hex colors for something the user sees.

**Don't:** write `#2f343f` into a new program's CSS. It is right in Dark and
wrong in Light.

### VIS-3 Must: Never pick dark or light yourself

Don't set `gtk-application-prefer-dark-theme`, load a theme, or choose colors
by testing which style is on. The user's style (and any GTK theme they chose
in *Appearance*) decides.

## Shape

### VIS-4 Should: No CSS unless there is no other way

A normal GTK window has no CSS of its own. The Arc theme already styles buttons,
lists, entries and headings, and any CSS is something that can clash with a
theme the user picks later. Use style classes the theme knows instead:
`dim-label` for secondary text, `suggested-action` and `destructive-action` for
buttons.

When CSS is needed (a layer-shell surface has no window frame to inherit):

- ship it as `/usr/share/flickos/NAME/style.css`,
- scope every selector under a class named after the program
  (`.flickos-menu .app`), so it can't leak into anything else,
- load it with `STYLE_PROVIDER_PRIORITY_APPLICATION`, so a user's
  `gtk.css` still wins,
- style your own classes, and don't restyle the theme's widgets.

### VIS-5 Should: Keep it flat and still

FlickOS draws translucency without blur (panel, terminal) and no shadows.
Its pop-ups (start menu, Quick Settings, phone popup, shortcut sheet) may
fade in and out, at most 100 ms, never full screen, and only while
GSettings' `enable-animations` is on; nothing else animates beyond GTK's own
transitions. Input never waits for a fade. Stack transitions are `NONE`,
except a crossfade of at most 100 ms between a pop-up's pages (the classic
start menu's Home and All Apps).

Motion costs frames on old graphics hardware and adds nothing to finding
things; a short fade of a small window costs about 55 ms of CPU and nothing
between fades
([design/flickos-fades.md](../design/flickos-fades.md)).

## Icons

### VIS-6 Must: Icons come from the icon theme, by standard name

- Use [freedesktop icon names](https://specifications.freedesktop.org/icon-naming-spec/latest/)
  (`preferences-system`, `system-shutdown`), which Numix-Circle and
  Numix-Circle-Light both have. Never ship a PNG for something the theme
  already draws.
- When a name may be missing (a theme the user chose), try several and use the
  **first one the theme has**: `next(n for n in names if theme.has_icon(n))`.
  Don't pass a list to `Gio.ThemedIcon.new_from_names()`: GTK 3 tries every
  name in one theme before the next, so a poor fallback can win.
- FlickOS's own logo is the icon `flickos`.
- Small buttons inside a row use `-symbolic` icons (`list-remove-symbolic`),
  which take the text color in both styles.

### VIS-7 Should: Icon sizes come from GTK

Use `Gtk.IconSize`: `BUTTON` (16) inside rows, `LARGE_TOOLBAR` (24) for icon
buttons, `DND` (32) for cards, `DIALOG` (48) for big tiles. Set a pixel size
only where a layout needs it (the start menu's full-screen grid).

## Text

### VIS-8 Must: The system font, relative sizes

Text uses the font the user set in *Appearance*. Don't set a font family,
except `monospace` for keys and code (the shortcut sheet's key caps). Make
text bigger or bolder with Pango markup (`<b>`, `size='x-large'`) or relative
CSS, not fixed sizes, so a larger system font makes everything larger
([A11Y-7](07-accessibility.md#a11y-7-must-layouts-survive-larger-text-and-scaling)).

Hierarchy is done with weight and dimming, not color: headings are bold,
secondary text has `dim-label`, and the accent color is kept for selection
and the suggested action.

## Artwork

### VIS-9 Must: Artwork is generated, and its source is recorded

- Layout previews come from `tools/make-layout-previews.sh`, the placeholder
  art (boot, splash, installer) from `tools/make-placeholder-art.sh`, both from
  the palette, and the fastfetch logo from `flickos.svg` by
  `tools/make-fastfetch-logo.py`. Regenerate them when a layout or a color changes, and don't
  edit the images by hand.
- A picture from elsewhere (a wallpaper photo) has its own stanza in the
  package's `debian/copyright` with its author and license
  ([PKG-5](09-packaging.md#pkg-5-must-every-file-has-a-known-license)).

## Styles made by others

Users make their own styles, and others share them
([09 – Your own style](../09-customizing.md#your-own-style),
[design](../design/flickos-ricing.md)). VIS-1 is for what FlickOS ships: a
user's style may use any colors. In return FlickOS promises that its own
surfaces follow any style through the named colors
([VIS-2](#vis-2-must-follow-the-style-that-is-in-use)), so a style never has to
know about each program, and that the names it uses stay the same.

### VIS-10 Must: The palette keys are an interface

Users' styles inherit FlickOS's (`Inherits=`) and set some of these keys, so a
key that changes breaks their styles without a word. These are frozen:

| File | Keys |
|---|---|
| `waybar-colors.css` | `@define-color` `wm_bg`, `bg_color`, `base_color`, `fg_color`, `selected_bg_color`, `selected_fg_color`, `borders`, `warning_color`, `error_color`, `brand_color` |
| `foot.ini` | `[colors]` `alpha`, `background`, `foreground`, `regular0`–`regular7`, `bright0`–`bright7` |
| `fuzzel.ini` | `[main]` `icon-theme`; `[colors]` `background`, `text`, `prompt`, `input`, `match`, `selection`, `selection-text`, `selection-match`, `border` |
| `mako.conf` | `background-color`, `text-color`, `border-color`; `[urgency=critical]` `border-color` |

- **Add** a key when FlickOS needs one: to Dark, Light and the base configs at
  once (`tests/test_styles.py` and `tools/check-palette.py` check that every
  style sets the same keys). A user's style that doesn't set it gets the
  parent's.
- **Don't rename or remove** one without a reason. If you must, keep the old
  name working for at least two releases (define it from the new one in
  FlickOS's palette files, which `check` then accepts), and have
  `flickos-layout check` say `OLD is now NEW` until it goes.
- The keys `check` accepts in a style's palette files are the ones Dark's own
  files set (`base_palette_keys`): adding one to Dark is what allows it.
- A style's palette files hold colors only (no `include=`, no keys that run
  programs), whoever made the style. `check` refuses anything else.

**Contrast** is the user's choice in their own style. `check` warns below
A11Y-6's ratios (4.5:1 text, 3:1 the accent's text); a style shared as a
community package must pass.

### VIS-11 Must: The panel's shared names are an interface

Users' own layouts (flickos-layouts 1.56, [docs/09 *Your own
layout*](../09-customizing.md#your-own-layout)) include FlickOS's shared
modules and CSS by their full paths and refer to its names in their own
config and CSS, so a name that changes breaks their panel without a word.
These are frozen:

| What | Names |
|---|---|
| Shared files | `/usr/share/flickos/layouts/common/modules.jsonc`, `/usr/share/flickos/layouts/common/base.css` |
| Modules in `modules.jsonc` | `custom/launcher`, `custom/desktop`, `custom/tiler`, `custom/phone`, `custom/recording`, `wlr/taskbar`, `clock`, `wireplumber`, `battery`, `tray` |
| Placeholders flickos-layout fills in | `flickos/pinned` (`custom/pin#CLASS`), `flickos/desktops` (`custom/desk#N`) |
| Signals (`SIGRTMIN+N`) | 8 `custom/tiler`, 9 `custom/phone`, 10 `custom/recording`, 11 the desktop buttons |
| Groups | `group/quick` (`#quick` in CSS) |
| Classes FlickOS's buttons set | `custom/tiler`: `on`, `off` and the arrangement's id; `custom/phone`: `waiting`; `custom/recording`: `recording`; desktop buttons: `active` |

- **Add** freely: a new module, class or signal reaches users' layouts that
  ask for it. A new signal takes the next free number.
- **Don't rename or remove** one without a reason. If you must, keep the old
  name working for at least two releases (both in `modules.jsonc`, or the
  program setting both classes), and have `flickos-layout check` say
  `OLD is now NEW` until it goes.
- `base.css`'s look may change: that's how fixes reach users' layouts. Its
  selectors for the names above stay.
- Users' panel tweaks (flickos-layouts 1.58, [docs/09 *Panel
  tweaks*](../09-customizing.md#panel-tweaks)) may rely on these names and on
  waybar's own (`window#waybar`, its `top`/`bottom` classes, `#clock`, …), not
  on a layout's own selectors: a layout's CSS may change in an update, and a
  tweak that stops matching does nothing. If you make a layout's rule
  stronger than the tweaks starter's (`TWEAKS_EXAMPLES`), `StarterSelectorsTest`
  fails: make the example as strong.
- `tests/test_layouts.py` (`InterfaceTest`) lists these names; change it
  together with this rule.
