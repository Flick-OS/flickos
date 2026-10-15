# 04 – FlickOS packages

FlickOS's own packages live in `packages/`. Each is a **native Debian source
package**: a folder with a `debian/` directory and the files it installs. They
have no upstream tarball; this repo *is* the upstream. The exceptions are
`waypaper` and `sfwbar`, third-party apps that Debian trixie lacks, packaged the
same way (see [waypaper](#waypaper) and [sfwbar](#sfwbar)).

## The packages

### `flickos-desktop` (meta-package)

Installs no files. It exists only for its dependencies, which together are
the FlickOS desktop. Everything is in `packages/flickos-desktop/debian/control`.

- **`Depends:`** packages the session can't work without (labwc, waybar,
  PipeWire, portals, polkit, NetworkManager, `flickos-settings`,
  `flickos-archive-keyring`, …). Also `systemd-timesyncd`: systemd only
  *recommends* a time daemon, so without it installed systems never set their
  clock from the network; `xdg-terminal-exec`, which Super+Enter and the
  menu run; and `brightness-udev`, brightnessctl's udev rule (the `video`
  group may set the backlight), without which the brightness keys and Quick
  Settings' slider do nothing.
- **`Recommends:`** apps and tools users may reasonably remove (foot, fuzzel,
  Thunar, lxtask, nano, …).

Why the split matters: if a user removes a package listed in **Depends**, apt
also removes `flickos-desktop`. After that, `apt autoremove` would delete every
package that was only installed for it, which is the whole desktop.
**Recommends** can be removed safely.

Rule: **only put something in Depends if FlickOS is broken without it.**

Because the ISO is built with `--apt-recommends false`, the hook
`config/hooks/normal/0050-flickos-recommends.hook.chroot` installs the
Recommends explicitly.

**Caveat:** live-build leaves `/etc/apt/apt.conf.d/00recommends`
(`APT::Install-Recommends "false";`) in the image, so **installed systems
also skip Recommends.** A package you *add* to `Recommends:` later only
reaches new ISO installs, not existing systems on `apt upgrade`. If existing
users must get a new package, put it in `Depends:`. To switch installed
systems back to Debian's default (install Recommends), add a hook
`0900-restore-recommends.hook.chroot` containing
`rm -f /etc/apt/apt.conf.d/00recommends`. Future `apt install` commands will
then also pull in Recommends, which makes installs larger.

### `flickos-settings`

Default desktop configuration:

| File in package | Installed to | Purpose |
|---|---|---|
| `usr/bin/flickos-session` | `/usr/bin/` | Starts the session: config directories, input settings (`flickos-control prepare`), desktop layout overlay (`flickos-layout prepare`), `$XDG_RUNTIME_DIR/flickos/bin` last on `PATH` (flickos-phone's `flickos-phone-on`, for the file manager's *Send to Phone*), keyboard layout, `exec labwc` (with `FLICKOS_PLAIN=1`: `labwc -C` on flickos-layout's plain folder). Run by the login screen and by the tty1 script |
| `usr/bin/flickos-session-plain` | `/usr/bin/` | The plain session: `FLICKOS_PLAIN=1 flickos-session`, FlickOS without the user's own changes ([09 – The plain session](09-customizing.md#your-own-style)) |
| `etc/profile.d/95-flickos-session.sh` | `/etc/profile.d/` | On tty1 login (live autologin, text login) runs `flickos-session` |
| `usr/share/wayland-sessions/flickos.desktop` | same | The session for other display managers |
| `etc/xdg/labwc/rc.xml`, `menu.xml`, `environment` | `/etc/xdg/labwc/` | Keybindings, root menu, cursor |
| `etc/xdg/labwc/autostart` | `/etc/xdg/labwc/` | Calls `/usr/libexec/flickos/autostart` |
| `usr/libexec/flickos/autostart` | `/usr/libexec/flickos/` | Starts kept screen arrangements (`flickos-control displays start`: kanshi, only while one is kept), wallpaper (`flickos-layout wallpaper`), panel (`flickos-layout panel`), notifications (and Do Not Disturb again: `flickos-control notifications`), applets, night light (`flickos-control night-light`, else the script), idle lock (`flickos-control idle`, else a fixed swayidle), the phone connection (`flickos-phone daemon`, which exits at once while off; not in the live session), and last the startup applications (`flickos-control startup run`) |
| `usr/libexec/flickos/open-default` | `/usr/libexec/flickos/` | `browser` or `files`: starts the user's default app (`xdg-mime query default`, then `gio launch`), else `x-www-browser`, or Thunar (pcmanfm where Thunar is missing: systems installed before it replaced pcmanfm). Super+B, Super+E and the menu |
| `etc/xdg/flickos/` | `/etc/xdg/flickos/` | foot, fuzzel and default-app config: `mimeapps.list` (folders: Thunar, else pcmanfm), and `xdg-terminals.list` (foot, for `xdg-terminal-exec`); `Thunar/uca.xml`, Thunar's right-click actions (Open Terminal Here with `xdg-terminal-exec`, Send to Phone); `autostart/` hides the XDG autostart entries of what autostart starts itself (nm-applet, blueman, the polkit agent, xdg-user-dirs) and keeps the print queue applet off |
| `etc/xdg/xfce4/xfconf/xfce-perchannel-xml/thunar.xml` | same | Thunar's defaults (xfconf): the path as buttons, a larger window. xfconfd is started by D-Bus without the session's `XDG_CONFIG_DIRS`, so it can't live in `/etc/xdg/flickos` |
| `usr/lib/systemd/user/thunar.service.d/flickos.conf` | same | `XDG_CONFIG_DIRS`/`XDG_DATA_DIRS` with FlickOS's folders for a Thunar started by D-Bus (another program's *Show in Folder*), which otherwise reads Debian's `uca.xml` and saves a copy in `~/.config/Thunar/` that hides FlickOS's actions |
| `etc/firefox-esr/flickos.js` | `/etc/firefox-esr/` | Firefox default prefs (Debian's firefox-esr reads every `.js` there; a user's own choice wins): vertical tabs |
| `usr/lib/firefox-esr/distribution/distribution.ini` | same | Firefox's distribution customization: a FlickOS bookmark on the bookmarks toolbar, added once per profile (a deleted one stays deleted); id `flickos`, shown in Help → About |
| `usr/libexec/flickos/lock` | `/usr/libexec/flickos/` | Locks the screen (Super+L, the menus): `flickos-control lock` (the background chosen in Settings), else `swaylock -f -c 383c4a` |
| `usr/libexec/flickos/night-light` | `/usr/libexec/flickos/` | Starts wlsunset timed for the time zone's city (`zone1970.tab`), passing its own options on (`flickos-control night-light` gives `-t`) |
| `usr/share/flickos/` | `/usr/share/flickos/` | waybar and mako config (the mako config has the `do-not-disturb` mode) |
| `usr/share/backgrounds/flickos/default.jpg` | same | Wallpaper for layouts without their own, and without flickos-layouts |
| `usr/share/glib-2.0/schemas/90_flickos-settings.gschema.override` | same | GTK theme (Arc-Dark), icons (Numix-Circle), fonts, dark mode, title bar buttons of windows that draw their own |
| `usr/share/themes/FlickOS-Arc-Dark/labwc/themerc` | same | labwc window theme in Arc-Dark colors (arc-theme has none for labwc) |
| `usr/share/themes/FlickOS-Arc/labwc/themerc` | same | The same in Arc (light) colors, for the Light style |
| `usr/share/themes/*/labwc/*.svg`, `*.xbm` | same | Title bar buttons: Arc's round close button and round hover (SVG, `tools/make-titlebuttons.py`) and arc-openbox's glyphs (`.xbm`) |

Every file is explained in [09 – Customizing](09-customizing.md).

`debian/install` maps source paths to install paths.

**How labwc finds config:** labwc looks for each file first in
`~/.config/labwc/`, then in `/etc/xdg/labwc/`, and uses **the first one it
finds**. It doesn't merge them (see `man labwc-config`). So:

- Users with no personal config get FlickOS defaults, **and get your updates**.
- A user who copies e.g. `rc.xml` to `~/.config/labwc/` takes full control of
  that file and stops receiving your changes to it. The other files still come
  from `/etc/xdg/labwc/`.

**Conffiles:** everything a package installs under `/etc` is a *conffile*. If a
user edited `/etc/xdg/labwc/rc.xml` and you ship a new version, `dpkg` asks
them whether to keep theirs or take yours. It never silently overwrites their
edits. This is normal Debian behavior.

### `flickos-layouts`

Desktop layouts, Dark/Light styles and the `flickos-layout` tool, which applies
the chosen layout and style at login and live (see
[09 – Desktop layouts](09-customizing.md#desktop-layouts) and
[09 – Styles](09-customizing.md#styles-darklight)).

| File in package | Installed to | Purpose |
|---|---|---|
| `usr/bin/flickos-layout` | `/usr/bin/` | Python 3 tool: `list`, `current`, `set`, `style list/current/set/new` (`new`: a user's own style, [09 – Your own style](09-customizing.md#your-own-style)), `layout new` (a user's own layout from one of FlickOS's, waybar only), `tweaks new` (a starter for the user's panel CSS, `~/.config/flickos/tweaks/style.css`), `check` (a style, `--layout` a layout, or everything of the user's), `explain` (which file each program reads), `clicks list/current/set`, `launcher list/current/set`, `menu-style list/current/set`, `clock list/current/set`, `state` (all of them and doctor's warnings as JSON, for the Settings window), `prepare`, `panel`, `reload-panel` (generate the panel again and restart it: flickos-phone, when its button comes or goes), `supervise`, `wallpaper`, `doctor`, `pick` (chooser), `first-run`. Every `set` also takes `default` (removes the user's choice), and every change that shows is recorded for *Settings → History* |
| `usr/libexec/flickos/check-css` | same | `FILE…`: parses CSS with GTK 3's own parser (python3-gi, no display) and prints one JSON line per file, `ok` or the first error's file, line and column. flickos-layout runs it on the user's CSS before the panel reads it, since waybar exits on any CSS error ([09 – Panel tweaks](09-customizing.md#panel-tweaks)) |
| `usr/libexec/flickos/desktop` | same | `N`, `next` or `previous`: goes to that labwc desktop (ext-workspace-v1). What a desktop button in the panel runs on a click or scroll; a small stdlib program because a click must be quick |
| `usr/share/flickos/layouts/ID/` | same | One folder per layout (`redmond`, `cupertino`, `traditional`): `layout.ini`, `waybar.jsonc`, `style.css`, `preview.png` |
| `usr/share/backgrounds/flickos/ID.jpg` | same | The layouts' photos (their wallpapers until 1.37), now only choices in waypaper |
| `debian/links` | `/usr/share/backgrounds/flickos/flickos-ID.png` | Links to the styles' wallpapers, for waypaper |
| `usr/share/flickos/layouts/common/` | same | `modules.jsonc` and `base.css`, shared by every layout. `custom/phone` (flickos-phone's button) is defined there, and the generated panel has it just before `custom/tiler` only while `flickos-phone get enabled` says yes (never in the live session) |
| `usr/share/flickos/styles/ID/` | same | One folder per style (`dark`, `light`): `style.ini` (GTK, icon and labwc theme names), the palettes `waybar-colors.css`, `foot.ini`, `fuzzel.ini`, `mako.conf`, and `wallpaper.png` (shown with every layout). Users' own styles are in `~/.local/share/flickos/styles/ID/` (looked at first; `Inherits=`) |
| `etc/xdg/flickos/layouts.conf` | same | Default layout, style, desktop clicks, apps button, start menu style, clock and Quick Settings (conffile) |
| `usr/share/applications/flickos-layout.desktop` | same | *Desktop Layout & Style* in the app launcher (`flickos-layout pick`) |
| `etc/skel/.config/flickos/choose-layout` | same | First-login marker: new accounts see the chooser once (`flickos-layout first-run`). Conffile |
| `debian/flickos-layouts.lintian-overrides` | `/usr/share/lintian/overrides/` | Allows the marker in `/etc/skel` (see below) |
| `tests/` | not installed | Unit tests |

- **Why it's a Depends of `flickos-desktop`:** the session script and autostart
  only use it if it's installed, so FlickOS still starts without it. But a
  *Recommends* never reaches installed systems (see the caveat above), and
  layouts are part of FlickOS for every user. The sanity hook's `REQUIRED` list
  includes it too.
- **It depends on `flickos-settings` (>= 1.10)**, whose `rc.xml`, foot, fuzzel
  and mako configs are the base of the overlay, whose panel is the fallback when
  a layout can't be started, which has the `FlickOS-Arc` window theme and
  (1.10) the default desktop click bindings. flickos-settings in turn
  `Breaks: flickos-layouts (<< 1.6)`: its autostart leaves starting mako to
  `flickos-layout panel` (1.3) and runs `flickos-layout first-run` (1.4) and
  `flickos-layout wallpaper` (1.6), which older versions don't have.
- **It recommends `waypaper`** for the chooser's *Wallpaper…* button, which is
  only shown when waypaper is installed.
- **It ships a file in `/etc/skel`**, which lintian reports as
  `package-contains-file-in-etc-skel` because existing home directories never
  get it. Here that's the point: only accounts created after installation
  (Calamares, `adduser`) should see the first-login chooser. The override in
  `debian/flickos-layouts.lintian-overrides` silences it.
- **It depends on `libglib2.0-bin`** for `gsettings` (the icon theme, to find
  icons for pinned apps in a bar; GTK settings when switching styles) and
  `gio launch` (clicks on those icons).
- **It depends on `sfwbar`** (`+flickos4` or later: `+flickos3` has the
  `running` class and `sensor_maximized`, `+flickos4` highlights the current
  desktop) for the Cupertino dock and Traditional's bottom panel (window list
  and desktop switcher).
- **It gives a layout labwc desktops** (`Desktops=`, only Traditional: 4)
  through the rc.xml overlay: `<desktops>` named `1` to `4` and the keys
  Super+Ctrl+←/→ and Super+1 to Super+4 (with Shift to take the window
  along). A layout with desktops needs a switcher: an sfwbar `pager`, or
  (1.55) desktop buttons in waybar, `flickos/desktops` in a bar, which
  become one `custom/desk#N` per desktop. waybar's supervisor follows
  labwc's desktops and rewrites their files in
  `$XDG_RUNTIME_DIR/flickos/desktops/`; a click runs
  `/usr/libexec/flickos/desktop`. No FlickOS layout uses them yet (they are
  for users' own layouts, `docs/design/flickos-ricing.md` phase 5).
- **It takes the user's panel tweaks** (1.58, ricing phase 7):
  `~/.config/flickos/tweaks/style.css` is imported last into the generated
  panel CSS and copied after the dock's. Every CSS file of the user's
  (tweaks, add-ons', their own layout's) is read by `check-css` first, and
  one GTK can't read is left out: waybar 0.12 exits on any CSS error.
- **It merges other programs' labwc fragments** into the rc.xml overlay
  (`FRAGMENTS`, in this order): flickos-control's `control/labwc.xml`
  (`<libinput>` device categories, appended after the system rc.xml's, and
  `<keyboard>` options) and flick-tiler's `tiler/labwc.xml`. For
  flickos-control's `control/environment` (the keyboard layout) it writes an
  overlay `labwc/environment`: the system one's lines (and its `environment.d/`),
  then the fragment's, since labwc reads only the first environment file it finds.
- **It plugs in add-ons** (`addons()`): programs that aren't FlickOS packages
  (yet), each a folder `~/.config/flickos/addons/NAME/` or
  `/usr/share/flickos/addons/NAME/` (the user's wins; an empty one turns off
  the system's). Its `labwc.xml` gives keybinds and window rules only, merged
  after `FRAGMENTS`; a key the desktop already binds is left out, and a
  keybind's `description="…"` (FlickOS's, labwc logs unknown attributes) is
  taken out and written to `$XDG_RUNTIME_DIR/flickos/shortcuts/addons.json`
  for flickos-shortcuts. Its `waybar.jsonc` (`custom/` modules the layout doesn't have) goes
  before the tiling button (`MODULE_BEFORE`, after the phone's), and its
  `style.css` is imported after the layout's. `flickos-layout addons` lists
  them; `reconfigure` and `reload-panel` apply a change. Nothing is generated
  without one. See [09](09-customizing.md#add-ons).
- **It owns the panel clock's hours** (`clock`: `24h`, the default and the
  layouts' own formats, or `12h`): generating the panel gives each bar with a
  clock its formats with `%I:%M %p` for `%H:%M` (the bar's own, else the
  include's, else waybar's `{:%H:%M}`). *Settings → Date & Time* sets it.
- **It owns the apps button's choice** (`launcher`: `menu`, flickos-menu's
  start menu, the default while that is installed, or `fuzzel`, the app
  launcher, the only choice without it). While the
  start menu is on, it writes the menu's corner (`Menu=` in `layout.ini`) to
  `menu/anchor`, adds the Super-tap keybinds to the rc.xml overlay, points the
  generated `custom/launcher` and the desktop clicks at the menu, and runs
  `flickos-menu daemon` with the panel. While it is off, none of that exists.
  It doesn't depend on flickos-menu. See [flickos-menu](#flickos-menu).
- **It owns the Quick Settings choice** (`quick-settings`: `off`, the
  default, or `on`, offered while flickos-menu is installed). While it is on,
  it writes the corner (`Quick=` in `layout.ini`) to `menu/quick`, groups the
  generated panel's `wireplumber` and `battery` into `group/quick` (one hover,
  `#quick:hover` in base.css) and points their clicks at it (`QUICK_TOGGLE`;
  the volume icon's right click opens pavucontrol), binds Super+A in the
  rc.xml overlay (replacing labwc's default maximize), makes desktop clicks
  close it, and runs `flickos-menu daemon` with the panel; the daemon runs
  while the start menu or Quick Settings is on. It Breaks flickos-menu before
  1.6, which has no `quick`.
- **It depends on `python3-gi` and `gir1.2-gtk-3.0`** for the chooser window.
  GTK 3 follows the Arc theme. zenity (GTK 4/libadwaita) was rejected because
  libadwaita ignores Arc and would add about 12 MB. Both packages were already in
  the image.
- **Unit tests run during the build:** `debian/rules` has
  `override_dh_auto_test: python3 -m unittest discover -s tests`, so
  `packages/build.sh` stops if a test fails. That's why `python3` is in
  `Build-Depends`. Skip them with `DEB_BUILD_OPTIONS=nocheck`.
  `PYTHONDONTWRITEBYTECODE=1` in `debian/rules` keeps a `__pycache__` folder from
  ending up next to the installed script.

### `waypaper`

[waypaper](https://github.com/anufrievroman/waypaper), a GTK 3 wallpaper
picker for swaybg (*Settings → Wallpaper*). It isn't in Debian trixie, so
FlickOS packages upstream's release: pure Python, installed as is to
`/usr/lib/python3/dist-packages/waypaper/` with a small `/usr/bin/waypaper`
launcher, so building it needs nothing beyond debhelper. Its dependencies
(python3-gi, python3-pil, python3-imageio, python3-screeninfo,
python3-platformdirs) are all in Debian.

- **Version:** upstream's, plus `+flickosN` (`2.9+flickos1`), so a FlickOS
  change can be released without a new upstream version (`dch -i` bumps N).
- **FlickOS changes** (listed in `debian/README.source`, with how to update to
  a new upstream release): defaults in `/etc/xdg/waypaper/config.ini`, which a
  patched `config.py` reads before the user's config, and the desktop file
  without its `#!` line.
- **A Depends of `flickos-desktop`**, not a Recommends, so installed systems
  get it: the Settings menu has an entry for it.
- **License:** GPL-3+ (`debian/copyright`), like FlickOS's own files.

### `sfwbar`

[sfwbar](https://github.com/LBCrion/sfwbar), a GTK 3 layer-shell panel for
stacking Wayland compositors. FlickOS uses it where waybar falls short: the
Cupertino layout's dock (a taskbar with pinned apps that hides and slides back
up when the pointer touches the bottom edge, `sensor`, without reserving
screen space, `exclusive_zone = "0"`), the Traditional layout's bottom
panel (a window list whose titles get shorter as windows open, and a pager for
labwc's desktops, which it reads over `ext-workspace-v1`; waybar 0.12 has
neither) and the Footprint layout's dock on the left edge
([flickos-style-footprint](#flickos-style-footprint)).
Debian packaged it up to 1.0~beta13, then removed it, so FlickOS packages
upstream's source.

- **The only compiled FlickOS package:** `Architecture: any`, built with meson
  by `debian/rules`. Its `Build-Depends` (meson, gettext, GTK 3,
  gtk-layer-shell, json-c, Wayland headers) must be on the build host and are
  installed in CI. The optional features are set explicitly in `debian/rules`,
  so the result doesn't depend on which `-dev` packages the host has: the
  pulse, pipewire, alsa and xkbmap modules are off. It builds no `-dbgsym`
  package, because `packages/build.sh` stages every `.deb` it finds.
- **A git commit, not a release:** 1.0_beta17 documents taskbar `pins` but
  only implements them for the pager, and its `size = "auto"` bars collapse to
  1px. The vendored commit (in `debian/README.source`, with update steps) has
  both working. Version: `1.0~beta17+git20260910+flickosN`, which sorts after
  beta17 and before `1.0~beta18+flickos1`.
- **FlickOS changes** (listed in `debian/README.source`, marked `FlickOS:` in
  the code): an app's dock button gets the CSS class `running` while the app has
  a window (the open-app line), a bar property `sensor_maximized`: the dock
  hides only while the active window is maximized or fullscreen on its monitor,
  a fix so the pager marks the current desktop `focused` (upstream never
  did once another state flag was set), GTK's animation setting followed
  instead of forced on (the dock slides only while GSettings'
  `enable-animations` is on; `bar_sensor_hide` finishes a hide that happened
  at once, or the dock never came back), and `WindowInfo()` reading a dock
  button's window from the click, so a click on the dock minimizes the
  focused app and raises it again (upstream read the app id as a window),
  and (+flickos7) a full-length bar asks for no length and takes the one the
  compositor gives it, its content filling it through a homogeneous grid
  (upstream asked for the monitor's length, so Footprint's left dock, below
  the top bar, ran past the bottom of the screen).
- **Used by `flickos-layouts`** (a Depends): `flickos-layout` generates the
  layout's sfwbar config (`Dock=`) in the layout overlay and runs `sfwbar -f FILE`
  ([The generated panel](09-customizing.md#the-generated-panel)).
- **License:** GPL-3 (version 3 only), protocol files MIT/HPND, weather icons
  MIT (`debian/copyright`).

### `flick-tiler`

Opt-in window tiling for the labwc session: master and stack, columns, grid
and monocle, with gaps. It is off until a user turns it on (Super+T or the
panel button). One Python 3 file, `usr/bin/flick-tiler`, standard library only;
it speaks the few Wayland messages it needs (wlr-foreign-toplevel) itself, so
it needs no bindings.

- **How it tiles:** labwc can't be told to move a window, so flick-tiler
  rewrites labwc *regions* and has labwc reload.
  [09](09-customizing.md#window-tiling) explains the mechanism.
- **Settings:** `/etc/xdg/flickos/tiler.conf` (conffile: `Enabled`, `Mode`,
  `MasterRatio`, `Gap`, `Float`), then the user's `~/.config/flickos/tiler`.
- **Depends on flickos-layouts (>= 1.8)**, whose `flickos-layout reconfigure`
  merges the tiling fragment into the rc.xml overlay, and flickos-settings
  (>= 1.11) for the Super+T binding and the autostart line.
- **Commands for the Settings window** (flickos-control): `flick-tiler floating
  list|add|remove PATTERN` changes the `Float=` list (the whole list goes into
  the user's file, since it replaces the system one), `flick-tiler gap N` the
  gap, and `status` also gives the main window width (`ratio`) and `gap`.
  `mode`, `ratio` and `gap` take `default` (removes the user's value).
- **Show Desktop:** `flick-tiler show-desktop` (the panel's Show Desktop
  button, `custom/desktop`: a slim strip at the right end of the panel in
  every layout)
  minimizes every shown window, and when none is shown gives back the ones it
  minimized, the focused one last. labwc 0.8 has no `ToggleShowDesktop`, and
  the daemon already follows the windows, tiling on or off.
- **Bring an app forward:** `flick-tiler focus-app APP-ID…` activates (and
  restores) the main window of that app that had the focus last, exit status
  1 if none is open. flickos-menu's grid sends it over the control socket
  before starting an app.
- **History:** every change of these settings (Super+T and the panel
  included) is recorded for *Settings → History*, like flickos-layout's (see
  flickos-control).
- **A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`.
- **Unit tests** in `tests/` (arrangements, window bookkeeping, fragment, the
  Wayland client against a fake compositor), run at package build like
  flickos-layouts'.

### `flickos-shortcuts`

The keyboard shortcut sheet: hold Super on its own for `HOLD_MS` (0.7 s) and
the session's shortcuts appear in the middle of the screen until Super is let
go. Also *Settings → Keyboard Shortcuts* and the app launcher
(`flickos-shortcuts show`, closes on any key or click). One Python 3 file,
`usr/bin/flickos-shortcuts`, plus `usr/share/flickos/shortcuts/style.css`
(Arc-Dark, in `tools/check-palette.py`).

- **How it sees Super:** labwc 0.8 sends the modifier state to *every* client
  with a keyboard, not only the focused one. The daemon keeps a bare Wayland
  connection with a keyboard (standard library, like flick-tiler's) and reads
  the `modifiers` events; nothing is bound in rc.xml. Other compositors
  (sway, Mutter) don't do this, so the daemon only works on labwc.
- **The sheet** is a GTK 3 layer-shell surface (gtk-layer-shell) on the
  overlay layer. It takes no keyboard focus and lets clicks through, so the
  shortcuts keep working while it is shown. It fades in (`FADE_IN_MS`, 100)
  and out (`FADE_OUT_MS`, 80) like flickos-menu's windows, only while
  GSettings' `enable-animations` is on (`Sheets`; a test compares the curve
  with flickos-menu's when both are in the tree); a zoom key (`BUSY_SIGNAL`)
  hides it at once. About 65 ms of CPU per fade. Design:
  [design/flickos-fades.md](design/flickos-fades.md).
- **What it lists:** the keybinds of the rc.xml labwc uses (first of
  `$XDG_CONFIG_HOME`, then `$XDG_CONFIG_DIRS`: a user's own, the flickos-layouts
  overlay with flick-tiler's keys while tiling is on, or flickos-settings'),
  plus labwc's built-in ones (`DEFAULT_KEYBINDS`) with `<default />`. Read
  again every time it is shown. Descriptions come from `COMMANDS` and
  `ACTIONS`, and for add-ons' keys from flickos-layouts'
  `$XDG_RUNTIME_DIR/flickos/shortcuts/addons.json` (under *Other*); media,
  volume and brightness keys are left out.
- **Started by** flickos-settings' autostart (`flickos-shortcuts daemon`, one
  per session: `$XDG_RUNTIME_DIR/flickos/shortcuts.lock`).
- **A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`.
- **Unit tests** in `tests/` (rc.xml reading, descriptions, the hold timing,
  the fades with a fake window, the Wayland client against a fake
  compositor), run at package build.

### `flickos-phone`

Pages, files and text between an Android phone with the **KDE Connect app**
and the computer: *Share → KDE Connect → this computer* on the phone arrives
here as a notification (a click opens the page or file; files go into
Downloads), and `flickos-phone send FILE|URL`, `--text`, `--clipboard` go the
other way. One Python 3 file, `usr/bin/flickos-phone`, standard library only
(no GTK, except the file chooser of `send --choose`), plus the conffile `etc/xdg/flickos/phone.conf`. Design, decisions
and the phase 0 measurements with a real phone:
[design/flickos-phone.md](design/flickos-phone.md).

- **Off by default** (`flickos-phone set enabled yes|no|default`); while off
  nothing runs. Never in the live session. Settings in `[Phone]` of
  `phone.conf`, then `~/.config/flickos/phone` (`Enabled`, `Name`,
  `Networks`, `Notifications`, `NotificationApps`, `Calls`, `Media`,
  `Commands`); every change is recorded
  for *Settings → History*.
- **The protocol:** only the part of KDE Connect's (version 8) that moving
  things needs: pairing, `kdeconnect.share.request`, `kdeconnect.clipboard`,
  `kdeconnect.ping`, plus the phone's battery (in) and
  `kdeconnect.findmyphone.request` (out, to ring it), and
  `kdeconnect.sftp` / `kdeconnect.sftp.request` (browse the phone's files),
  and `kdeconnect.mpris` in / `kdeconnect.mpris.request` out (what the phone
  plays, for the phone popup's row; ADR-018). The phone's
  notifications (`kdeconnect.notification` in,
  `kdeconnect.notification.request` out) are announced only while that
  setting is on. Calls (`kdeconnect.telephony` in,
  `kdeconnect.telephony.request_mute` out, which mutes the phone's ringer)
  are announced only while that setting is on. Media control of this
  computer (`kdeconnect.mpris` out, `kdeconnect.mpris.request` in) is
  announced only while that setting is on. Named commands (`kdeconnect.runcommand.request`
  in, `kdeconnect.runcommand` out) are announced only while the user has
  added one: the phone is sent the names and asks by key, and the command
  line stays here. The phone's app hides everything else (remote input,
  replies). In KDE Connect the device that opens the TCP connection is the
  TLS *server*; the daemon never opens one to a phone (it broadcasts, and
  answers a phone's broadcast with a UDP packet so the phone connects), so it
  is always the TLS client and Python's `ssl` can check an unknown phone's
  certificate. A paired phone's certificate is pinned.
- **Pairing:** `flickos-phone pair` waits for the phone to ask, shows the
  verification key both screens show, and asks (`--json`: events as JSON
  lines and the answer on stdin, for *Settings → Phone*'s *Add Phone…*).
  Pair requests at any other time are refused, and the window closes as soon
  as `pair` goes away. `devices`, `forget ID`, and `state` (everything the
  Settings page shows, one JSON object, with each connected phone's
  address). `ping [--to ID] [TEXT]` shows TEXT as a notification on the
  phone (for add-ons such as flickos-phone-screen's reminder).
  `notifications list|allow NAME|block NAME` chooses which of the phone's
  apps may show their notifications here (`set notifications yes|no|default`
  turns that on; off until then, and nothing while the screen is locked).
  `set calls yes|no|default` shows who is calling, with *Mute*, and pauses
  what is playing until the call ends (off until then; nothing is shown
  while the screen is locked). `set media yes|no|default` shows what's
  playing here in the phone's app, and the phone can play, pause, skip and
  change the volume (off until then; nothing changes while the screen is
  locked; the players are read when one `playerctl --follow`, running only
  while a paired phone is connected, prints a change, never on a timer).
  `player play|pause|play-pause|next|previous|volume PERCENT [--to ID]`
  controls what the phone plays (the player `state`'s `playing` names, also
  a `watch` line `playing`; the phone sends each change, nothing is read on
  a timer). `commands list`, `commands add NAME COMMAND` and
  `commands remove KEY` are the named commands the phone may run (empty
  until one is added; the phone asks by key; a command runs as the user;
  nothing runs while the screen is locked; `set commands default` clears
  the list). `browse [--to ID]` opens the folders the
  phone offers in the file manager, after the phone's key matches the one
  it paired with.
- **Where it listens:** only on the NetworkManager connections in `Networks`
  (the one a phone was paired on is added; `flickos-phone network
  list|add|remove`, `set networks`), or while `pair` runs. FlickOS's firewall
  drops incoming connections: with ufw on, phones need TCP 1716 and 1739–1764
  allowed, and UDP 1716 so the computer hears a phone that joins the network
  (*Settings → Phone → Let phones through the firewall*). Links have TCP
  keepalive (`KEEPALIVE`), so a phone that left the network without a word is
  dropped within about a minute and the daemon announces again.
- **Panel button** (`custom/phone`, only while it's on; flickos-layouts puts
  it before the tiling button): `status --panel` gives waybar the phone icon,
  dimmed while no phone is connected, and a tooltip; the daemon sends waybar
  `SIGRTMIN+9` (`PANEL_SIGNAL`) when a phone connects or goes. A click opens
  `flickos-phone menu` (fuzzel): *Send Files to Phone…* (`send --choose`,
  GTK's file chooser), *Send Text to Phone…* (`send --type-text`, typed into
  fuzzel), *Send Clipboard to Phone* (a web address
  goes as a page, anything else onto the phone's clipboard), *Send
  Screenshot to Phone* (`send --screenshot`, with grim), *Ring My Phone*
  (`ring`), *Browse Phone* (`browse`: the folders the phone offers, in the
  file manager, and only while `gvfsd-sftp` is installed), *Show Phone Screen* (only while a program called
  `flickos-phone-screen` is installed: the proprietary phone screen add-on, see
  `docs/design/flickos-phone-screen.md`), the newest received items (*Open*, *Show … in Folder*, *Copy*),
  *Phone Settings*. The tooltip shows the phone's battery.
  `set enabled` runs `flickos-layout reload-panel`, so the button comes and
  goes at once.
- **Send to Phone** in Thunar's menu for files: a custom action in
  flickos-settings' `/etc/xdg/flickos/Thunar/uca.xml` runs
  `flickos-phone send --notify %F` (the result as a notification). Thunar
  can't hide a custom action, so the item is always there; while the phone
  connection is off the notification says to turn it on in *Settings →
  Phone* (`not_running_reason`). A `~/.config/Thunar/uca.xml` of the
  user's hides it (Thunar reads only the first `uca.xml`); *Settings →
  Phone* warns about one without it. The daemon keeps a link `flickos-phone-on`
  in `$XDG_RUNTIME_DIR/flickos/bin`, which flickos-settings'
  `flickos-session` puts last on `PATH`, while the phone connection runs:
  flickos-screenshot offers *Send to Phone* only while it finds it.
- **Files:** identity and paired phones in `$XDG_DATA_HOME/flickos/phone/`
  (0700), what came from a phone (the last 20, a week) in
  `$XDG_STATE_HOME/flickos/phone/received.jsonl` (`flickos-phone received`),
  the daemon's lock and control socket in `$XDG_RUNTIME_DIR/flickos/phone/`.
- **Started by** flickos-settings' autostart (`flickos-phone daemon`, which
  exits at once while off; one per session), and by `set enabled yes`.
- **A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`.
- **Unit tests** in `tests/` (certificates and the verification key against
  `openssl`, file names, settings, and a pretend phone on 127.0.0.1 that
  pairs, shares and fetches), run at package build.

### `flickos-screenshot`

Screenshots and screen recordings, modeled on the Windows Snipping Tool. One
Python 3 file, `usr/bin/flickos-screenshot` (GTK 3 and gtk-layer-shell only
for the bar, the frozen screen and a recording's outline; GStreamer only in
the recorder), plus its desktop file *Screenshot*, FlickOS's portal-wlr
config and screen chooser. Design and measurements:
[design/flickos-screenshot.md](design/flickos-screenshot.md).

- **Keys** (flickos-settings' rc.xml): Print = `shot region`, Shift+Print =
  `shot screen` (every screen), Ctrl+Print = `shot region --copy-only`,
  Super+Shift+S = the capture bar (Photo or Video, or Text while tesseract is
  installed, Area, Full Screen, a delay
  of 3, 5 or 10 seconds, and a video's sound; the delay is remembered
  in `$XDG_STATE_HOME/flickos/screenshot/last`, and the sound is a setting),
  Super+Shift+R = the bar
  with Video chosen, or stop the recording (`bar --video`). *Screenshot* is
  also in both root menus.
- **An area** is chosen on a frozen screen: `grim -t ppm` grabs every screen
  before GTK is imported, one layer-shell surface per screen shows its part
  dimmed, and the area is cut out of that grab (`to_pixels`: layout
  coordinates to the picture's pixels, whatever the layout's origin and the
  screens' scale). Drag, or click for the whole screen; arrow keys, Space,
  Enter, Tab and Escape do the same from the keyboard. With a delay the area
  is chosen first and cut out of a second grab taken when the delay is over.
- **Text** (`shot region|screen --text`, the bar's Text; ADR-011): the
  picture is read by tesseract (`tesseract-ocr` is only a Suggests, so Text
  is offered only while it is installed), the text is copied and printed,
  and the notification shows how it starts; the picture isn't saved.
  English first, at most three installed languages; an area up to 1 MP is
  read at twice its size, which fixes most mistakes in small screen text,
  and a picture with no text found is read again with a local threshold
  (a dark window on a black screen).
- **Settings** (`get`/`set`, `state` for the Settings page): where
  screenshots and recordings are saved (`folder`, `recordings-folder`; empty
  means Pictures/Screenshots and Videos/Screen Recordings), the pointer in
  screenshots (`pointer`, default no) and a recording's sound (`sound`,
  default none). The system default is the conffile
  `/etc/xdg/flickos/screenshot.conf`, the user's choice
  `~/.config/flickos/screenshot`. `set KEY default` puts the system's back.
  Every change is recorded for History. *Settings → Screenshots* (flickos-control)
  runs these commands and lists the keys.
- **Every screenshot** is saved in the screenshots folder
  (Pictures/Screenshots, unless its setting says otherwise) as `Screenshot
  YYYY-MM-DD HH-MM-SS.png` (never overwritten: ` (2)`), copied with `wl-copy`,
  and announced by a notification whose click opens it in the markup window.
  A copy-only picture is kept as `$XDG_RUNTIME_DIR/flickos/screenshot/last.png`
  for that click.
  The sound theme's shutter sound plays and what was taken flashes white,
  from the `feedback` child, started before the grab and told on its stdin;
  off with the desktop's event sounds or animations (GSettings), and Do Not
  Disturb silences the sound. The next grab waits for `flash.lock`.
- **The markup window** (`edit FILE`, a plain GTK window titled
  *Screenshot*): pen, highlighter, arrow, box, text, *Hide* (a solid box,
  never a blur that could be read back) and crop, in five Arc colors and three
  widths; undo and redo; zoom (Ctrl+plus/minus, Ctrl+0 fits); *Copy*,
  *Save* (into the screenshot's own file; a copy-only one asks where) and
  *Save As…*; *Send to Phone* while flickos-phone runs (`flickos-phone
  send`); *New Screenshot* hides it and runs the bar with only Photo
  (`bar --photo`). Closing, or a new picture over unsaved markup, asks first,
  unless it was copied. One window per session: a second `edit` hands its
  picture over (`edit-request`, SIGUSR1 to the PID in `screenshot/edit.lock`).
- **Recording** (`record region|screen [--delay N] [--sound
  none|computer|microphone|both]`, `stop`, `status [--panel]`): the recorder
  asks xdg-desktop-portal's ScreenCast for one screen and encodes it with
  GStreamer in the same process, which loads no GTK: H.264 (x264 ultrafast)
  and Opus in a fragmented MP4, written straight into the recordings folder
  (Videos/Screen Recordings, unless its setting says otherwise) as
  `Screen Recording YYYY-MM-DD HH-MM-SS.mp4`, so a crash keeps all
  but the last second. An area is recorded by cropping its screen
  (`recording_crop`, positions and scale from `wlr-randr --json`), with a line
  drawn just outside it (the `outline` child). It counts down (3 s by
  default) before anything is kept; meanwhile a stream with no frame is
  restarted (portal-wlr's stuck first frame, `Recorder`). The panel's
  `custom/recording` (flickos-layouts, next to the clock) shows the countdown
  and then the time from `$XDG_RUNTIME_DIR/flickos/screenshot/panel.json`,
  which the recorder rewrites and signals (SIGRTMIN+10 to the user's
  waybars) once a second; a click runs `stop`, which signals only the PID in
  `recording.lock`. It also stops when the portal ends the session or less
  than 200 MB are free.
- **The portal's screen chooser**: the conffile
  `/etc/xdg/xdg-desktop-portal-wlr/labwc` runs
  `/usr/libexec/flickos/screencast-chooser`, which answers the screen named
  in `$XDG_RUNTIME_DIR/flickos/screenshot/screencast-request` if that file is
  at most 2 s old, and asks as before for everyone else (slurp, else
  fuzzel). portal-wlr reads it only when it starts: after the install, from
  the next login. A user's own `~/.config/xdg-desktop-portal-wlr/` file wins.
- **Runs nothing in the background** and nothing at login: each command ends
  when the picture is saved (the notification's child waits up to 30 s for a
  click), a recording when it is stopped, and the markup window when it is
  closed. One capture at a time
  (`$XDG_RUNTIME_DIR/flickos/screenshot.lock`), one recording
  (`screenshot/recording.lock`).
- **A Depends of `flickos-desktop`** and of `flickos-settings` (its keys run
  it), and in the sanity hook's `REQUIRED`.
- **Unit tests** in `tests/` (the crop math, file names, saving, copying,
  notifications, the settings and their History lines, the recording's crop and pipelines, the recorder's
  countdown, gates and restart with a fake pipeline, the panel's signal with a
  fake `/proc`, the chooser script, the markup's undo, crop and zoom math,
  what it draws (with python3-cairo where installed) and the hand-over
  between two `edit`s), with stub programs on `PATH`, run at package build.

### `flickos-countme`

The anonymous weekly count: how many computers run which FlickOS version,
without knowing which ones (Fedora's "countme" idea). What is sent and kept:
[PRIVACY.md](../PRIVACY.md). One Python 3 file, `usr/bin/flickos-countme`
(stdlib only), plus `usr/libexec/flickos/countme-helper` (root, through
pkexec).

- **The request:** `GET URL?version=2.0&age=N`, at most once per ISO week
  (UTC). `version` is `FLICKOS_VERSION` from flickos-branding's
  `/usr/lib/flickos-release`; `age` is 1 (first request of a computer installed
  in the last week, so each install is counted once), 2 (a month), 3 (half a
  year) or 4 (`AGE_BUCKETS`). Nothing else: no id, no hardware.
- **When:** `flickos-countme.timer` (daily, random delay up to 6 h,
  `Persistent=true`) starts `flickos-countme.service` (oneshot, user
  `_flickos-countme` from `debian/flickos-countme.sysusers`, sandboxed). A run
  that already counted this week exits at once. Nothing is sent with
  `boot=live`, while `Enabled=no`, or while `URL` is empty (it is
  `https://flickos-countme.dvbondoy.workers.dev/v1/countme`, `server/countme/`). A failed request
  is retried the next day. Installing or upgrading the package starts nothing
  (`dh_installsystemd --no-start`).
- **Settings:** `/etc/flickos/countme` (not a conffile): `Enabled=` (default
  yes), `Installed=` (written only by installers up to
  flickos-installer 1.24, which asked; else the first
  run's date in `/var/lib/flickos-countme/first-run`), `Url=` (testing).
  `flickos-countme enable|disable` run `pkexec countme-helper on|off` (polkit
  `org.flickos.countme.policy`; turning it off needs no password).
  `status` (JSON) and `show` print the state and the exact request.
- **Installer:** asks nothing (it did up to flickos-installer 1.24); the
  first slide of its install slideshow (`branding/flickos/show.qml`) says the
  count is on and where to turn it off.
- **Settings window:** the *Privacy* page of flickos-control, shown while
  flickos-countme is installed.
- **A Depends of `flickos-desktop`** (since 1.26) and in `REQUIRED`: systems
  installed before it get it with an upgrade and, never asked, are counted
  until they turn it off (opt-out). Removing the package removes the desktop,
  so turning it off is the way out.
- **The server:** `server/countme/` (Cloudflare Worker + D1, deploy steps in
  its README). While `URL` in `usr/bin/flickos-countme` is empty, nothing is
  sent.
- **Unit tests** in `tests/` (age buckets, weeks, config, live session, retry
  after a failure, the helper), run at package build. The boot test checks
  that the timer is enabled and that the live session sends nothing.

### `flickos-recovery`

Restore points of the whole system: a read-only btrfs snapshot before every
software change, putting one back, the boot menu's *Restore points*, and
recovering by itself after starts that failed. Design, decisions and
measurements:
[flickos-recovery.md](design/flickos-recovery.md). One Python 3 file,
`usr/bin/flickos-recovery` (stdlib only), plus `usr/libexec/flickos/recovery-helper`
(root, through pkexec).

- **Only on FlickOS's btrfs layout** (ADR-001): `/` the `@` subvolume and
  `/.snapshots` the `@snapshots` one, which the installer makes when btrfs
  is chosen (the default since flickos-installer 1.28). On ext4, on a user's
  own btrfs layout and in the live session every command says so and does
  nothing.
- **The apt hook:** `etc/apt/apt.conf.d/80flickos-recovery` runs
  `flickos-recovery apt-hook` in `DPkg::Pre-Install-Pkgs` (version 3 list on
  stdin), whichever program runs apt.
  - One change gets one restore point, `/.snapshots/NAME` (the time) plus
    `NAME.json` (why, which program, the packages).
  - The newest `KEEP` (5) are kept, and none is made with less than 2 GiB or
    10 % of the disk free.
  - On ext4 the hook reads `/proc/self/mountinfo` and leaves before
    importing anything else: 34 ms per apt run on a 2014 laptop.
  - It never stops apt, except right after putting back (exit status 100,
    which the apt line turns into a failure). If the program is gone,
    `|| cat` reads apt's list so apt goes on.
- **Commands:**
  - `list`, `state` (JSON for the Settings page), `plan NAME` (apt's history
    since then).
  - `create [REASON]`, `delete NAME|--all`, `restore NAME`,
    `get`/`set enabled|auto-recover yes|no|default`
    (`/.snapshots/.flickos-recovery.conf`: in `@snapshots`, so neither putting
    back nor a start from a restore point loses a change).
  - The changing ones need root. Run by a user they `exec` pkexec and the
    helper (polkit `org.flickos.recovery.policy`, one action per verb).
  - Only snapshots with a `NAME.json` are restore points: a user's own are
    never touched.
- **Putting back** (ADR-003):
  - The running `@` moves into `@snapshots` as a "before putting back"
    restore point, and a writable snapshot of NAME becomes the new `@`.
  - GRUB is installed again from the restored system (chroot,
    `--no-nvram`). If that fails, the swap is undone.
  - Until the restart apt is refused. The marker
    `/.snapshots/.flickos-recovery-pending` holds the boot id.
  - At the next start `flickos-recovery-settle.service` (only while the
    marker exists) makes the old system read-only. The next change made as
    root does it too, for a restored system without that service.
- **The boot menu** (ADR-004):
  - `etc/grub.d/42_flickos-recovery` adds a *Restore points* submenu that
    `source`s `/boot/grub/flickos-recovery.cfg`, and nothing at all off the
    btrfs layout.
  - The tool writes that file after every change, one entry per restore
    point with its own kernel and initramfs (disk access from
    grub-mkconfig_lib), and commits it: GRUB reads only the last btrfs
    commit.
  - The postinst runs `update-grub` and `flickos-recovery grub` on the
    layout only. Purging takes the submenu out.
- **Starting a restore point:**
  - `usr/share/initramfs-tools/hooks/flickos-recovery` adds the overlay
    module.
  - `scripts/local-bottom/flickos-recovery` puts a tmpfs layer over a
    snapshot named by `rootflags=subvol=@snapshots/NAME`, drops fstab's
    `/` line, and writes `/run/flickos/restore-point-boot`.
  - Nothing changed then is kept, and no restore point is made. `restore`
    of that one is *Keep*.
- **The start counter** (ADR-005):
  - `flickos-recovery-start.service` (oneshot, before greetd) runs
    `start begin`.
  - `flickos-recovery-good.service` runs `start good-watch`: once
    `gtkgreet` or `labwc` has been up `GOOD_SECONDS` (5), the count is 0
    and the start counts as good.
  - Both need `/.snapshots` to be a mount point.
  - The counter is `/.snapshots/.flickos-start.json`, and `.flickos-start.cfg`
    in GRUB's words, which the stub sources. At `LIMIT` (2) failed starts,
    or while recovering, the `.cfg` also holds the newest good restore
    point's own menu entry (`--id flickos-recover`, built from
    `.flickos-grub.json`, which `write_grub` saves).
  - GRUB then starts it (`auto-recover` yes, Option B) or waits with it
    highlighted (no, Option A), and waits if starts from it fail too.
  - A restore point is `good` when it was taken in a start that had already
    worked.
  - `start keep|try-again|status`; the helper has `keep`, `try-again` and
    `auto-recover`.
- **At login**, started from a restore point: flickos-settings' autostart
  runs `flickos-recovery notify`. It waits until FlickOS's mako owns the
  notification service, then sends a critical notification whose click
  opens Settings' *Restore Points* page.
- **The log:** `/var/log/flickos-recovery.log` (in `@log`, fsynced,
  `etc/logrotate.d/flickos-recovery`).
- **Settings window:** flickos-control's *Restore Points* page (System
  group, only on the btrfs layout: the list, *Put Back…*, the switches
  `restore-points` and `restore-points.auto`, and a banner with *Keep…* and
  *Try Again* while running from a restore point), and restore points in
  *History*.
- **A Depends of `flickos-desktop`** (since 1.30) and in `REQUIRED`:
  existing ext4 installs get it and nothing of it runs. They get restore
  points only by installing again.
- **Unit tests** in `tests/`:
  - a fake `/proc`, `/.snapshots` and btrfs;
  - the apt line run through `sh` with a stand-in program;
  - the GRUB stub with a stand-in `findmnt`;
  - the counter's states;
  - the helper's argument checks.

  The boot test checks that the live session has none of it.

### `flickos-menu`

The start menu for the panel's apps button (the default) and Quick Settings
(off by default), in the style of the
desktop layout (`MenuStyle=`): Redmond's is classic (Windows 7: pinned apps,
*All Apps* by category and search on the left; the user, their folders,
Settings, Software and the power buttons on the right), Traditional's is
categories (GNOME 2/Whisker), Cupertino's a full-screen grid of app icons
(Launchpad), with the power buttons top right while Quick Settings is off.
Log Out, Restart and Shut Down run on a second click: the first turns the
button red and says to click again. **On by default** (since flickos-layouts 1.23): a user who wants fuzzel back picks
*App launcher* under *Apps button* in *Settings → Desktop Layout & Style*
(`flickos-layout launcher set fuzzel`). Design and measurements:
[design/flickos-menu.md](design/flickos-menu.md).

**Quick Settings** is the daemon's second window, opened by the panel's volume
and battery icons and Super+A while the user turns it on under *Quick
Settings* in *Settings → Desktop Layout & Style* (`flickos-layout
quick-settings set on`): switches for Wi-Fi, Do Not Disturb, night light,
tiling and the phone, sliders for volume and brightness, the battery,
Settings and the power buttons. Design, measurements and what is left (Bluetooth):
[design/flickos-quick-settings.md](design/flickos-quick-settings.md).

| File in package | Installed to | Purpose |
|---|---|---|
| `usr/bin/flickos-menu` | `/usr/bin/` | One Python 3 file: `daemon`, `toggle`, `show`, `hide`, `super`, `quick`, `list`, `pinned`, `pin`, `unpin`, `bench` |
| `usr/share/flickos/menu/quick.py` | same | Quick Settings' code, which the daemon loads only while it is on (`load_quick`) |
| `usr/share/flickos/menu/style.css` | same | The look of both windows, in GTK theme colors only, so both styles recolor it (in `tools/check-palette.py`) |
| `etc/xdg/flickos/menu.conf` | same | Default pinned apps (conffile). The live session uses flickos-installer's `/etc/xdg/flickos-live/flickos/menu.conf` |
| `tests/` | not installed | Unit tests |

- **Nothing runs while it is off.** flickos-layouts starts `flickos-menu daemon`
  with the panel only while the menu is on, and `flickos-layout launcher set
  fuzzel` stops it. Without `$XDG_RUNTIME_DIR/flickos/menu/anchor` (written by
  flickos-layouts while the menu is on) `toggle` runs fuzzel and no daemon
  starts.
- **Fast:** the daemon keeps the menu built and hidden; the panel button,
  labwc's Super keybind and desktop clicks reach it with `pkill` (SIGUSR1
  toggle, SIGUSR2 Super tap, SIGWINCH hide), so no Python starts per click.
  Showing it takes a few milliseconds; icons are loaded in the background.
- **Fades:** the start menu, Quick Settings and the phone popup fade in
  (`FADE_IN_MS`, 100) and out (`FADE_OUT_MS`, 80) by the window's own opacity
  (`Fader`), only while GSettings' `enable-animations` is on; the full-screen
  grid never fades. A window fading out takes no keys or clicks (they go to the
  window below), and showing it again maps it anew, since labwc gives a layer
  surface the keyboard only when it is mapped. About 55 ms of CPU per fade,
  the daemon and labwc together, and nothing between fades. Design:
  [design/flickos-fades.md](design/flickos-fades.md).
- **A tap of Super** is labwc's `onRelease` keybind; the daemon ignores it
  unless Super was pressed alone and let go within `TAP_MS` (600 ms), so a hold
  still shows flickos-shortcuts' sheet.
- **Costs while on:** about 35 MB of private memory and no CPU while idle.
  Quick Settings adds about 2 MB, and about 31 MB when the start menu is off.
- **Quick Settings owns no setting.** Each control runs the program that owns
  it (`nmcli`, `flickos-control set`, `flick-tiler on|off`, `flickos-phone
  set enabled`, `wpctl`, `brightnessctl`) and reads it again at every show, in
  threads; the battery and backlight come from `/sys`. A control whose
  program or hardware is missing is left out. While hidden nothing runs;
  while shown, volume, Wi-Fi and battery are read every 2 seconds. Its code is
  a second file because this script, in `/usr/bin`, has no `.pyc`: compiling
  it would cost every start menu session about 2 MB.
- **Pinned apps:** `Pinned=` in the first `flickos/menu.conf` in
  `XDG_CONFIG_DIRS`, until the user pins or unpins one (right-click an app, or the Menu key);
  then `~/.config/flickos/menu`.
- **Launching** goes through GLib (`Gio.DesktopAppInfo`), so `Terminal=true`
  apps open in the user's terminal (xdg-terminal-exec) and folders in their
  file manager.
- **A Depends of `flickos-desktop`**, so installed systems get it (a Recommends
  wouldn't reach them), and in the sanity hook's `REQUIRED`. It depends on
  `procps` for `pkill`, and on `python3-gi-cairo` for the empty input region
  of a window fading out.
- **Unit tests** in `tests/`, run at package build.

### `flickos-control`

The Settings window (*Settings → All Settings*, or `flickos-control` in the
app launcher): one window with a sidebar of pages grouped under *Desktop*,
*Devices*, *Apps*, *System* and *Accounts and security*, and the owner of the mouse,
touchpad, keyboard and idle settings. One Python 3 file,
`usr/bin/flickos-control`, GTK 3 through python3-gi with no CSS of its own, so
it follows the Dark or Light style. Design and decisions:
[design/flickos-control.md](design/flickos-control.md).

- **Pages:** *Desktop Layout & Style* (layout with previews, style, desktop
  clicks), *Displays* (the screens now, *Arrange Screens…* starts wdisplays through `displays arrange`, which moves a screen it turns on over another beside them,
  *Keep This Arrangement*, the kept arrangements; night light on or off and
  its warmth; shown while kanshi and wlr-randr are installed), *Mouse & Touchpad*, *Keyboard* (layout and
  variant, repeat, Num Lock, and the system layout), *Language & Region*
  (language and formats for the account, the system's through `localectl
  set-locale`, which asks for the password; shown while the `locales`
  package is installed), *Default Applications* (browser, file
  manager, text editor, image and document viewer, media player through
  `xdg-mime default`; the terminal through `~/.config/xdg-terminals.list`),
  *Startup Applications* (XDG autostart entries on or off, *Add App…*,
  *Remove*), *Notifications* (Do Not Disturb), *Power & Idle* (lock and sleep times; what the power button, closing the
  lid and closing it while plugged in do, read from logind; the lid rows only
  with a lid switch), *Memory* (how much memory the computer has and uses,
  and *Firefox: use less memory*: the helper's `firefox-memory on|off` writes
  or deletes `/etc/firefox-esr/flickos-memory.js`, default prefs Debian's
  Firefox reads at its next start; recommended when `old_computer()` finds
  at most 3 GiB or no graphics acceleration; `docs/design/flickos-firefox.md`),
  *Date & Time* (time zone and network
  time through `timedatectl`, which asks for the password; night-light is
  restarted for the new time zone), *Updates* (automatically or not, which
  updates, restarting when nobody is logged in; installed systems only),
  *Login* (log in automatically; only on
  installed systems with flickos-greeter), *Users* (add and remove accounts,
  administrator or not, set a password; installed systems only), *Firewall*
  (ufw on or off; shown while ufw is installed), *Tiling* (on/off, arrangement, main window width, gap, apps that
  always float), *Keyboard Shortcuts* (the list, and a button for the sheet),
  *Phone* (flickos-phone on or off, the name phones see, *Add Phone…* with the
  verification key through `flickos-phone pair --json`, the paired phones and
  networks with *Forget*, what came from a phone with *Open*/*Copy*, and *Let
  phones through the firewall*, the system setting `firewall.phones`: the
  helper's `firewall-phones on|off` writes a ufw app profile,
  `/etc/ufw/applications.d/flickos-phones`, and allows it from private
  addresses only; the profile is the readable state. Read with one
  `flickos-phone state`, again every 3 s while shown; installed systems with
  flickos-phone only),
  *History* (recent changes with *Undo*; see below) and
  *More Settings* (tiles that start Wallpaper, Appearance, Displays, Network,
  Sound, Bluetooth, Printers and Software Updates; a tile is hidden when its app
  isn't installed), *Restore Points* (flickos-recovery's restore points with
  *Put Back…*, which shows `flickos-recovery plan` before the password; the
  switches are the system settings `restore-points` and `restore-points.auto`;
  a banner with *Keep…* and *Try Again* while running from a restore point;
  only on the btrfs layout, `recovery_available()` reads
  `/proc/self/mountinfo`), *Privacy* (the weekly
  count through `flickos-countme`, only while it is installed) and *About* (FlickOS version from `/usr/lib/flickos-release`,
  Debian, Linux, computer, processor, memory, graphics via `lspci`, disk,
  desktop; *Copy System Info* puts the same text plus the FlickOS packages'
  versions on the clipboard with `wl-copy`, and *Report a Problem* opens the
  GitHub issues).
- **Search:** a box above the page list finds pages, the rows and headings
  the pages build (collected by `Ui.row()`/`Ui.heading()` while the window
  opens) and the tiles' apps, also by `SEARCH_KEYWORDS` ("wifi", "volume",
  "monitor"). A result opens the page scrolled to the setting with its
  control focused, or starts the app. Ctrl+F, or a letter typed outside a
  text field, starts a search; Escape clears it.
- **Its own settings** (`SETTINGS`): touchpad (`tap`, natural scrolling,
  disable while typing, pointer speed, click method), mouse (left-handed,
  natural scrolling, pointer speed, acceleration) and keyboard (repeat delay and
  rate, Num Lock, layout, variant), plus `locale.language` and
  `locale.formats` (below). `flickos-control set KEY VALUE` saves one in
  `~/.config/flickos/input` or `keyboard` (system defaults: the conffiles
  `/etc/xdg/flickos/input.conf` and `keyboard.conf`, all commented out),
  writes `$XDG_RUNTIME_DIR/flickos/control/labwc.xml` and `environment`, and runs
  `flickos-layout reconfigure`. `get` lists them. `prepare` writes the two files
  at login (flickos-session runs it before `flickos-layout prepare`). labwc
  never resets an option that disappears from its config, so a value once set
  stays written, and `set KEY default` stores the default rather than
  removing it. Only keys labwc 0.8.3 parses are used; the tests hold its list.
- **Locking:** `flickos-control lock` execs `swaylock -f -c 383c4a` (the
  Arc-Dark color, `lock.background` `color`) or, with `wallpaper`, adds the
  images the user's swaybg shows (`-i OUTPUT:PATH` per `-o` group, `-s` its
  mode). swayidle runs it, and flickos-settings' `/usr/libexec/flickos/lock`
  (Super+L, the menus, the start menu). `idle.lock-before-sleep` (default
  yes) is swayidle's `before-sleep`. `~/.config/flickos/lock`, conffile
  `lock.conf`.
- **Idle:** `flickos-control idle` (run by autostart, not in the live session)
  execs swayidle with the chosen times (`idle.lock-after`,
  `idle.suspend-after`; `~/.config/flickos/idle`, system defaults in the
  conffile `/etc/xdg/flickos/idle.conf`) and `FLICKOS_IDLE=1` in its
  environment. A change stops FlickOS's swayidle (that mark, or autostart's
  old fixed lock command) and starts a new one; a user's own swayidle is left
  alone. It also locks the screen when logind asks (`lock`: the lid set to
  *Lock the screen*, `loginctl lock-session`).
- **Language and formats** (`~/.config/flickos/locale`, no system conffile:
  the system's is `/etc/default/locale`) become `LANG`, `LANGUAGE` (empty),
  `LC_MESSAGES` and the installer's nine `LC_*` format variables in
  `control/environment`, after the keyboard lines; a format the system
  doesn't set follows the language. Apps started afterwards use them, the
  rest from the next login. `set` accepts only a generated locale (`locale
  -a`); the page adds another first through the helper's `locale-add`.
- **Night light** (`night-light.enabled`, default on, and
  `night-light.temperature`, wlsunset's `-t`; `~/.config/flickos/night-light`,
  conffile `/etc/xdg/flickos/night-light.conf`): `flickos-control
  night-light` (autostart) execs flickos-settings' `night-light` script with
  `-t` and `FLICKOS_NIGHT_LIGHT=1`, or nothing while it is off. A change or a
  new time zone restarts only FlickOS's wlsunset (the mark, or the script's
  own `-l -L`/`-S -s` options).
- **Screen zoom** (*Accessibility*; `zoom.area` screen or lens,
  `zoom.lens-size`, `zoom.step`, `zoom.smooth`; `~/.config/flickos/zoom`,
  conffile `zoom.conf`) is labwc's `<magnifier>` in `control/labwc.xml`: the
  area becomes `width` and `height` (-1 for the whole screen), the step
  `increment`, smoothing `useFilter`. flickos-layout sets these over
  flickos-settings' rc.xml values (flickos-layouts >= 1.37); labwc applies
  them at once, even while zoomed. The keys are flickos-settings'.
- **Animations** (*Accessibility*, *Motion*; `flickos-control animations
  current|set on|off|default`) are GSettings' `enable-animations`, which GTK's
  transitions and the fades of flickos-menu's windows and the shortcut sheet
  read. GSettings stores it (not a file of flickos-control's), so a change in
  nwg-look or `gsettings` shows here too; `set` runs `gsettings set` (`reset`
  for default) and records the change for History as `animations` (Undo and
  *Put Back as It Was…* run `animations set OLD`).
- **Do Not Disturb** (`notifications.do-not-disturb`,
  `~/.config/flickos/notifications`, conffile `notifications.conf`) is
  mako's `do-not-disturb` mode (flickos-settings' mako config: all but
  critical notifications invisible). `set` runs `makoctl mode -a|-r` only
  while this user's mako owns `org.freedesktop.Notifications` (a `makoctl`
  call before would have D-Bus start a plain mako); `flickos-control
  notifications` (autostart) waits for mako and adds the mode again when it
  is on. A user's own mako config without the mode is named on the page.
- **Startup applications** (`flickos-control startup
  list|enable|disable|add|remove|run`): the XDG autostart entries labwc
  doesn't run, by the spec (`~/.config/autostart` first, then `autostart` in
  `XDG_CONFIG_DIRS`; `Hidden`, `OnlyShowIn`/`NotShowIn`, `TryExec`, `Exec`
  field codes, `Terminal`, `Path`, `X-GNOME-Autostart-Delay`). Off is
  `X-GNOME-Autostart-enabled=false`, for a system entry in a user copy;
  `add` copies an installed app's desktop file, `remove` deletes the user's
  own. `run` (autostart, last) waits at most 10 s for the tray, then starts
  the entries that are on.
- **Automatic updates** are read from `apt-config dump`
  (`flickos-control updates` prints them): on or off
  (`APT::Periodic::Unattended-Upgrade`), the scope (the
  `Unattended-Upgrade::Origins-Pattern` list: `security`, `debian` =
  Debian's own plus FlickOS's repo and its community apps (the default, from
  flickos-archive-keyring's `51flickos-origins`), `all` = also
  `trixie-updates`, `debian-only` = Debian's own alone (an older helper's
  `debian`; shown, never offered), else `custom`; the lists from before the
  community repository, `PREVIOUS_UPDATE_SCOPES`, show as the choice they
  were, and the postinst's `control-helper updates refresh` writes a stored
  choice again with today's list),
  restarting (`no`, `idle` = when nobody is logged in, `always`), and the last
  run (the stamp file's time).
- **Kept screen arrangements** (`flickos-control displays
  list|save|forget NAME|all|start`): `save` writes a kanshi profile for the
  screens connected now (from `wlr-randr --json`) into
  `~/.config/flickos/displays`, one per set of screens, named after them so
  keeping them again replaces it. `start` (autostart) execs `kanshi -c` that
  file with `FLICKOS_DISPLAYS=1`, only while a profile is kept and no other
  kanshi runs; `save` and `forget` make it reread (SIGHUP), start it or stop
  it. kanshi applies the profile of the connected screens at login and on
  every plug or unplug.
- **The system keyboard layout** (login screen, console, new accounts) is
  `/etc/default/keyboard`. Debian's systemd forbids changing it through
  `localectl`, so the Keyboard page runs `pkexec
  /usr/libexec/flickos/control-helper keyboard MODEL LAYOUT VARIANT OPTIONS`:
  polkit action `org.flickos.control.keyboard`
  (`usr/share/polkit-1/actions/org.flickos.control.policy`, one action per verb
  via `exec.argv1`, admin password). The helper checks every value against
  xkb-data's `evdev.lst`, rewrites only the `XKB*` lines, runs `udevadm trigger`
  and `setupcon --save-only -k`. The same helper has `autologin-on` and
  `autologin-off` (actions `org.flickos.control.autologin-on`/`-off`): for
  the user who ran pkexec (`PKEXEC_UID`, a regular account) only, it makes
  them the only member of group `autologin` (`gpasswd -M`), or takes them out.
- **User accounts** go through the same helper, one action each
  (`org.flickos.control.user-add`, `-remove`, `-admin`, `-password`):
  `user-add NAME FULLNAME yes|no` runs `adduser --disabled-password` (so
  `/etc/skel`, and with it the first-login markers, is copied), sets the
  password it reads on standard input with `chpasswd` and adds the installer's
  groups for the first account (`DEFAULT_GROUPS`, flickos-installer's
  `users.conf` without `sudo`; a test compares them), plus `sudo` for an
  administrator; if a step fails, the account is removed again. `user-remove
  NAME keep|delete` runs `userdel [--remove]`, not for the calling user and not
  while the account has processes running. `user-admin NAME yes|no` changes
  membership in `sudo` (polkit's and sudo's administrators on Debian).
  `user-password NAME` reads the password on standard input. Only regular
  accounts (`UID_MIN`..`UID_MAX` of `/etc/login.defs`), names that match
  adduser's `NAME_REGEX`, and never away from the last administrator.
- **The firewall** goes through the same helper: `firewall-on` runs `ufw
  --force enable` (no question about ssh connections), `firewall-off` runs
  `ufw disable` (actions `org.flickos.control.firewall-on`/`-off`). The page
  reads `ENABLED=` from `/etc/ufw/ufw.conf`, which everyone can read, because
  `ufw status` needs root. Rules stay a job for `sudo ufw` in a terminal. ufw
  is a Recommends of flickos-desktop, not a dependency of this package: without
  it the page is left out.
- **The power button and the lid** go through the same helper: `power
  power-key|lid|lid-external-power poweroff|suspend|lock|ignore|default`
  rewrites `/etc/systemd/logind.conf.d/60-flickos.conf` and runs `systemctl
  reload systemd-logind` (action `org.flickos.control.power`). **Adding a
  language:** `locale-add LOCALE` (a UTF-8 locale of
  `/usr/share/i18n/SUPPORTED`) turns its `/etc/locale.gen` line on and runs
  `locale-gen --keep-existing` (action `org.flickos.control.locale-add`).
  **Automatic updates:** `updates auto yes|no`, `scope
  security|debian|all`, `reboot no|idle` (each also `default`) keeps the
  choices in `/etc/apt/apt.conf.d/60flickos-updates` (after Debian's files;
  `#clear` replaces the origins; action `org.flickos.control.updates`).
- **For the other settings it owns nothing.** Each page runs the command that owns the setting,
  the same one a user could type: `flickos-layout state|set`, `style set`,
  `clicks set`, … and `doctor` (its warnings are shown on the page),
  `flick-tiler status|modes|on|off|mode|ratio|gap|floating`, `flickos-shortcuts
  list|show`. Pages read when they are shown (Super+T, the panel or the chooser
  may have changed something), in a background thread with a spinner until the
  answer is there, so the window opens at once. Changes run in the background
  too (`Gio.Subprocess`), and the page shows what the command printed.
- **History** (*History* page, `flickos-control history [--days N] [--json]`,
  `history undo ID`, `history clear`): every program that owns settings
  (this one, flickos-layout, flick-tiler) appends one JSON line per change
  that shows to `~/.local/state/flickos/history.jsonl` (0600; the older half is
  dropped above 256 KiB), with its own `record()` in the same format. The page
  shows the last 90 days, one framed list per day, at most 100 rows. Changes
  of one setting less than two minutes apart are one, and one that ends where
  it started is left out. **Undo** runs the owner's command with the old
  value (`flickos-control set KEY OLD`, `flickos-layout set OLD`, `flick-tiler
  on|off|mode|ratio|gap|floating`, where `default` removes the user's value),
  only for the setting's newest change and only while the setting still holds
  its new value. The file holds values, never commands. `history.enabled` (on
  by default; conffile `/etc/xdg/flickos/history.conf`, which the other
  owners read too) turns recording off and deletes the file. Design:
  [design/flickos-history.md](design/flickos-history.md).
  - **System settings** (power button and lid, firewall, automatic login,
    automatic updates, time zone, network time, the login screen's keyboard
    layout) change through `flickos-control system KEY [VALUE]`, which the
    pages run: it reads the value, runs the helper or `timedatectl`, and
    records the change once it worked; undo runs it with the old value.
    Default applications go through `flickos-control default-app list|set
    CATEGORY APP`, startup applications through `startup`, and the Users and
    Language pages record added and removed accounts, administrator on or off
    (the only one of these with Undo) and added languages.
  - **Software** comes from apt's own log, read by the helper without root
    (`control-helper packages-list [DAYS]`): installs, removals and updates,
    leaving out the installation (up to the installer's removal of itself; in
    the live session, the image's build). An install or removal has *Undo*:
    `packages-plan ID` (no root) says what it would do, the page shows that
    first, and `pkexec control-helper packages-undo ID` (action
    `org.flickos.control.packages-undo`) checks it again with `apt-get -s` and
    refuses an undo that would remove anything else, anything flickos-desktop
    depends on, or install a live-session package. Updates, autoremoves and
    transactions that both installed and removed are shown without Undo.
  - **Put back as it was** (*Put Back as It Was…*, `flickos-control history
    restore WHEN [--dry-run]`): every setting changed since WHEN that needs
    no password (FlickOS's own settings, layout, tiling, default and startup
    applications) gets its value then, flickos-layout's in one `set`. The
    dialog shows what goes back per day first. The restore is one row in the
    list, and its Undo puts back what it changed. System settings and
    software keep their own Undo.
- **Commands:** `flickos-control [--page ID]` opens the window (one per
  session: `$XDG_RUNTIME_DIR/flickos/control.lock`), `flickos-control list`
  prints the page ids, `flickos-control about` prints the system information
  (the text *Copy System Info* copies), `flickos-control system KEY [VALUE]`
  and `default-app list|set` print and change system settings and default
  applications.
- **Depends on** flickos-layouts (>= 1.22: 1.13 merges its fragment and
  writes the environment overlay, 1.19 has `state`, 1.22 records its changes
  and takes `default`), flick-tiler (>= 1.5, for `floating`, `gap`, the width
  in `status`, recording and `default`), flickos-shortcuts, `pkexec` and `xkb-data` for
  the helper, `xdg-utils` for default apps, and `kanshi` and `wlr-randr` for
  kept screen arrangements.
- **A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`.
- **Unit tests** in `tests/` (reading the commands' output, tiles, the command
  line, the lock, the settings and fragments against labwc 0.8.3's key list,
  the helper), run at package build. The boot test opens the window on each
  page and saves screenshots (`boot-test/control-*.png`), applies a
  touchpad option, a layout and the formats live, keeps and forgets a
  screen arrangement (kanshi started and stopped), and records a clock change
  and undoes it through `history`.

### `flickos-software`

*Software*: find, install and remove apps from Debian, FlickOS's repository
(FlickOS's own and other developers' community apps) and Flathub. One Python
3 file, `usr/bin/flickos-software` (GTK 3 only for the window), its desktop
file, the Flatpak update timer and an apt setting. It replaced
gnome-packagekit's `gpk-application` in both menus, the welcome window and
the start menu. Design and measurements:
[design/flickos-software.md](design/flickos-software.md).

- **Apps, not packages:** every desktop app in the apt sources' AppStream
  catalogs (DEP-11, which the `appstream` package's apt hook keeps in
  `/var/lib/swcatalog`) and in Flathub's (`appstream.xml` under
  `/var/lib/flatpak/appstream/flathub`). The apt catalogs are three sources,
  told apart by their origin (`APT_ORIGINS`; FlickOS's repository writes its
  catalogs with `repo/conf/dep11.py`): Debian, FlickOS (`trixie`) and FlickOS
  Community (`trixie-community`, apps other developers publish, which FlickOS
  builds from their public source and reviews; the page says so). An app in
  more than one shows once (`merge`: same ID without case, desktop IDs,
  `SAME_APPS`), with **an apt source as the default** (`SOURCES` order) and
  Flathub offered next to it.
- **The front page's shelves** (Made for FlickOS, then Apps to start with)
  are `/usr/share/flickos/software/featured.json`, replaced by the store's
  Worker's copy (`server/store/`, which serves this same file) once fetched:
  at most every `FEATURED_HOURS`, a plain GET with nothing about the user,
  kept in `~/.cache/flickos/software/featured.json`.
- **The index:** the window never reads the catalogs. `flickos-software index`
  writes `~/.cache/flickos/software/index.json` (one row per app) and a
  `pages-N.jsonl` (descriptions, screenshots, versions); the window runs it
  in a child when a catalog changed and keeps showing the old one meanwhile.
  `refresh` fetches what is missing: apt's lists through PackageKit (the live
  image has none) and Flathub's catalog through libflatpak, both without a
  password in an active session.
- **Installing and removing** run as child commands (`install`/`remove
  --json`, one JSON line per step, SIGTERM cancels): Debian apps through
  PackageKit, which asks for the password; Flathub apps through libflatpak
  into the system installation, without one for an administrator. `plan`
  simulates first and the page says what an app brings (Flathub's runtimes
  with their sizes) or what goes with it. A change that would remove part of
  the desktop (`flickos-*`, `flick-*`, flickos-desktop's Depends) is refused
  by the command itself.
- **Icons and screenshots:** the theme's icon by name, then the catalog's
  file, then a download kept in `~/.cache/flickos/software/images/`.
  `/etc/apt/apt.conf.d/50flickos-software` turns on Debian's 64 px icon
  tarball (the `DEP-11-icons` target), because trixie's catalog names icon
  and screenshot addresses that appstream.debian.org no longer serves; an
  app also on Flathub shows Flathub's screenshots.
- **Flatpak updates:** `flickos-software-update.timer` (daily, enabled, never
  in the live session) runs `/usr/libexec/flickos/software-update`, which
  follows apt's own settings: Flathub's catalog with
  `APT::Periodic::Update-Package-Lists` (only once something fetched it), the
  apps with `APT::Periodic::Unattended-Upgrade`. So *Settings → Updates*
  turns it on and off with the rest.
- **Styles** (1.3, [design/flickos-ricing.md](design/flickos-ricing.md)
  phase 4b): an apt package whose metainfo is an AppStream add-on extending
  `flickos-layout.desktop` with a `FlickOS::style` custom value (the style's
  folder) is a style (`style_of`): it shows only under *Styles* (Software's
  own category `X-FlickOS-Style`) and on the *Styles for your desktop*
  shelf, and once installed its page has *Try* (`flickos-layout try`, until
  logout) and *Use* (`style set`) instead of *Open*. FlickOS's style
  packages (`flickos-style-*`) can be removed, unlike its other packages.
  `repo/conf/dep11.py` carries the add-on's `Type`, `Extends` and `Custom`
  into the catalog as they are. Other developers publish styles as
  community packages (1.4, phase 4c): one from the community catalog is
  shown only when its `FlickOS::style` is its own package's name
  (`own_style`), as `repo/community/check.py` requires.
- Command line: `search WORDS`, `list [--installed|--category ID|--shelves]`,
  `info ID`, `plan|install|remove [--source debian|flickos|community|flathub]
  ID`. It owns no settings and sends nothing about its user.

### `flickos-style-seven`

**Seven**, FlickOS's own extra style: Arc's light windows with the Numix
icons, see-through sky blue title bars and frames (its own labwc theme
`Seven`, with glassy SVG buttons), a see-through dark blue panel
(`wm_bg` `rgba(14, 42, 76, 0.82)`), a black terminal, a light launcher and
notifications, and a sky wallpaper with the halo. It suits the Redmond
layout. Design, the spike and the naming rule (an allusion, like Redmond and
Cupertino; no other system's names or assets): ADR-013 and sections 11–12
of [design/flickos-ricing.md](design/flickos-ricing.md).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-seven`. It
  then lists after Dark and Light. Depends flickos-layouts (>= 1.53),
  arc-theme and numix-icon-theme, which every FlickOS system has, so it
  adds only its own 300 KB.
- **Files:** `usr/share/flickos/styles/seven/` (style.ini, the four
  palettes, wallpaper.png, linked as `/usr/share/backgrounds/flickos/flickos-seven.png`
  for waypaper), `usr/share/themes/Seven/labwc/` (themerc and the buttons),
  `usr/share/metainfo/io.github.dvbondoy.flickos.styles.Seven.metainfo.xml`
  (the add-on Software reads; keep its ID, Software knows the style by it).
- **Generated:** `tools/make-seven.py` writes every file but the metainfo
  from one place (colors, buttons, wallpaper SVG in `artwork/`); run it after
  a change, then bump the version. `tools/check-palette.py` checks its
  colors against `ALLOWED_SEVEN`.
- **Tests:** the metainfo's add-on form, every button in every state, no
  other system's trademarks, and (in the source tree) `flickos-layout check
  seven` and the themerc's keys against FlickOS-Arc's.
- **Removing it** while it is in use: the style in use falls back to the
  default at the next change or login, as for a deleted user style.

### `flickos-style-aye3`

**Aye3wm** (id `aye3`), FlickOS's second extra style and the first package with a
layout: Arc-Dark windows with the Numix icons, flat slate blue title bars on
the focused window and grey ones on the others, 2 px borders (its own labwc
theme `Aye3`, only a themerc: labwc draws its built-in buttons), a black
panel, a black opaque terminal in the classic X terminal's colors, a plain
grey launcher, slate blue notifications and a near-black wallpaper with
tiled windows drawn faintly and the halo. Its layout **aye3** is one black
bar at the bottom: the apps button and the desktops as numbered boxes on the
left (4 desktops, flickos-layouts' desktop buttons), the status as monospace
text on the right (`W:`, `CPU`, `MEM`, `VOL`, `BAT`, the date and time).
Design: ADR-014 and phase 5 step 5e of
[design/flickos-ricing.md](design/flickos-ricing.md); named by allusion
(ADR-013).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-aye3`.
  Software's *Use* sets the style and the layout together (the metainfo's
  `FlickOS::layout`); *Try* only the style. Depends flickos-layouts
  (>= 1.57), arc-theme and numix-icon-theme.
- **Files:** `usr/share/flickos/styles/aye3/` (style.ini, the four palettes,
  wallpaper.png, linked as `/usr/share/backgrounds/flickos/flickos-aye3.png`),
  `usr/share/flickos/layouts/aye3/` (layout.ini, waybar.jsonc, style.css with
  `../common` includes, as it sits next to flickos-layouts' layouts; and
  preview.png), `usr/share/themes/Aye3/labwc/themerc`,
  `usr/share/metainfo/io.github.dvbondoy.flickos.styles.Aye3.metainfo.xml`
  (keep its ID).
- **Generated:** `tools/make-aye3.py` writes the style, the themerc, the
  wallpaper and the layout's preview (SVGs in `artwork/`); the layout's three
  config files are written by hand. `tools/check-palette.py` checks the
  colors and the layout's CSS against `ALLOWED_AYE3`.
- **Tests:** the metainfo (both custom values), no other system's name, the
  files, and (in the source tree, over a share folder with flickos-layouts'
  `common/`) `flickos-layout check aye3` and `check --layout aye3`.

### `flickos-style-footprint`

**Footprint**, FlickOS's third extra style, with a layout that has a dock:
GTK's Adwaita-dark windows with the Adwaita icons, grey title bars with the
title in the middle and round buttons that light on hover (its own labwc
theme `Footprint`, with SVG buttons), a black top bar, a dark grey terminal
in the Tango colors, a grey launcher and notifications, and a dusk wallpaper
of blue-grey hills with the halo. Its layout **footprint** is a black top bar
(the desktops as dots, the current one a pill, on the left, and no apps
button: the dock's *Show Apps* is the layout's, `check --layout` accepts it
since flickos-layouts 1.62; the clock in bold and the recording button in the middle; tiling,
tray, volume, battery and Show Desktop on the right; Cantarell) and a dock on
the left edge (sfwbar: the pinned apps, then other open apps, a dot under
each open one, the list of an app's windows on hover, and *Show Apps* at the
bottom, which runs what the apps button runs). The dock keeps its width and
is in labwc's bottom layer, so the top bar spans the whole width above it.
The start menu is the full-screen grid, at the top left. Design: ADR-016 and
phase 8 of [design/flickos-ricing.md](design/flickos-ricing.md); named by
allusion (ADR-013).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-footprint`.
  Software's *Use* sets the style and the layout together. Depends
  flickos-layouts (>= 1.61: the dock's `Exec("flickos/launcher")`), sfwbar
  (>= +flickos7: a full-length dock fits below the top bar),
  gnome-themes-extra-data (Adwaita-dark), adwaita-icon-theme,
  adwaita-icon-theme-legacy (full-color icons for apps that name an older
  icon, such as Settings and Software: without it they fall back to dark
  grey symbolic ones that vanish on the dark apps grid; Adwaita only
  recommends it) and fonts-cantarell.
- **Files:** `usr/share/flickos/styles/footprint/` (style.ini, the four
  palettes, wallpaper.png, linked as
  `/usr/share/backgrounds/flickos/flickos-footprint.png`),
  `usr/share/flickos/layouts/footprint/` (layout.ini, waybar.jsonc, style.css,
  dock.config, dock.css, preview.png), `usr/share/themes/Footprint/labwc/`
  (themerc and 32 button SVGs),
  `usr/share/metainfo/io.github.dvbondoy.flickos.styles.Footprint.metainfo.xml`
  (keep its ID).
- **Generated:** `tools/make-footprint.py` writes the style, the window theme
  and its buttons, the wallpaper and the layout's preview (SVGs in
  `artwork/`); the layout's five config files are written by hand.
  `tools/check-palette.py` checks the colors, the layout's and the dock's CSS
  against `ALLOWED_FOOTPRINT`.
- **Tests:** the metainfo, no other desktop's name, every button in every
  state, the dock on the left in the bottom layer with both placeholders, and
  (in the source tree) `flickos-layout check footprint`, `check --layout
  footprint` and the generated dock.

### `flickos-style-elemental`

**Elemental**, FlickOS's fourth extra style, with its own layout: GTK's
light Adwaita windows with the elementary icons (Debian's
`elementary-icon-theme`), title bars in the window's own grey with the title
in the middle and plain glyph buttons that get a faint round face on hover
(its own labwc theme `Elemental`, with SVG buttons), a see-through dark top
bar with white text, a dark slate terminal, a light launcher and
notifications, and a seashore seen from above with the halo. Its layout
**elemental** is a thin top bar (the halo and "Applications" on the left,
the date and time in the middle, the status on the right, bold Inter with a
text shadow), a light frosted dock at the bottom (icons with a soft
shadow that grow under the pointer, a dark dot under open apps), and close on the left of the title bar with maximize on
the right. The dock's behavior is Cupertino's: `layout.ini` names
`../cupertino/dock.config`, so renaming that file means changing this
layout too. Design: ADR-017 and phase 9 of
[design/flickos-ricing.md](design/flickos-ricing.md); named by allusion
(ADR-013).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-elemental`.
  Software's *Use* sets the style and the layout together. Depends
  flickos-layouts (>= 1.53), sfwbar, gnome-themes-extra-data (the
  `Adwaita/gtk-3.0` folder flickos-layout looks for; the theme itself is
  built into GTK 3), elementary-icon-theme (35 MB on disk) and
  fonts-inter-variable (1.7 MB).
- **Files:** `usr/share/flickos/styles/elemental/` (style.ini, the four
  palettes, wallpaper.png, linked as
  `/usr/share/backgrounds/flickos/flickos-elemental.png`),
  `usr/share/flickos/layouts/elemental/` (layout.ini, waybar.jsonc,
  style.css, dock.css, preview.png), `usr/share/themes/Elemental/labwc/`
  (themerc and 32 button SVGs),
  `usr/share/metainfo/io.github.dvbondoy.flickos.styles.Elemental.metainfo.xml`
  (keep its ID).
- **Generated:** `tools/make-elemental.py` writes the style, the window
  theme and its buttons, the wallpaper and the layout's preview (SVGs in
  `artwork/`); the layout's four config files and the metainfo are written
  by hand. `tools/check-palette.py` checks the colors, the layout's and the
  dock's CSS against `ALLOWED_ELEMENTAL`.
- **Tests:** the metainfo, no name of the desktop it recalls but the icon
  theme's, every button in every state, `close:max`, the bar's
  "Applications" and clock, the bar drawn at the alpha `check` tests, and
  (in the source tree) the dock config, pins and corners Cupertino's,
  `flickos-layout check elemental` and `check --layout elemental` with a
  stand-in for the icon theme, and the generated dock.

### `flickos-greeter`

The login screen of installed systems: greetd runs gtkgreet in the cage kiosk
compositor, in the Arc-Dark colors. Nothing replaces greetd's own
`/etc/greetd/config.toml` (it is ignored):

- `usr/lib/systemd/system/greetd.service.d/flickos.conf`: a drop-in that
  skips greetd with `boot=live` (the live session keeps its tty1 autologin),
  runs `greetd-config` before each start and points greetd at its output.
- `usr/libexec/flickos/greetd-config`: writes
  `/run/flickos-greetd/config.toml`: VT 7, the greeter as `_greetd`, and an
  `initial_session` (automatic login, once per boot) for the first member of
  the group `autologin`.
- `usr/libexec/flickos/greeter`: sets the keyboard layout from
  `/etc/default/keyboard` and `GTK_THEME=Arc-Dark`, then runs
  `cage -d -s -- gtkgreet --command flickos-session --style …`.
- `usr/share/flickos/greeter/gtkgreet.css`: wallpaper (flickos-settings'
  `default.jpg`) and login box. Checked by `tools/check-palette.py`.
- `etc/greetd/environments` (conffile): `flickos-session-plain`, which
  gtkgreet lists in its session box below `--command`'s `flickos-session`.
  Every line is an entry, so the file has no comments.
- `debian/flickos-greeter.sysusers`: creates the group `autologin`
  (`dh-sequence-installsysusers` adds the `systemd-sysusers` call to the
  postinst).

greetd's postinst enables it as `display-manager.service` but doesn't start
it, so an upgraded system switches to the login screen at the next boot.
**A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`. See
[09 – Login screen](09-customizing.md#login-screen).

### `flickos-installer`

Calamares configuration and FlickOS branding, the `flickos-install` launcher,
and the live-session menu with *Install FlickOS*. It replaces Debian's
`calamares-settings-debian` and is only in the live image
(`config/package-lists/installer.list.chroot`): Calamares removes it from
installed systems. See [09 – Installer](09-customizing.md#installer).

### `flickos-branding`

The logo (`usr/share/icons/hicolor/`: `flickos.svg`, `flickos-symbolic.svg`), the
Plymouth boot splash theme (`usr/share/plymouth/themes/flickos/`), the installed
system's GRUB theme (`usr/share/flickos/grub/`, applied by the conffile
`/etc/default/grub.d/flickos-theme.cfg`; the postinst and postrm run
`update-grub` where `/boot/grub/grub.cfg` exists; see
[09 – Boot menu](09-customizing.md#installed-systems)), and the FlickOS name in `/etc/os-release`, `/etc/issue` and `/etc/issue.net`. Those three
files belong to Debian's `base-files`, so the package **diverts** Debian's
versions (`dpkg-divert`) and generates FlickOS versions from them in
`debian/flickos-branding.postinst`. File triggers regenerate them whenever
`base-files` is upgraded. `usr/lib/flickos-release` holds the FlickOS name and
version. This is the only FlickOS package with hand-written maintainer scripts
(`postinst`, `postrm`, `triggers`); flickos-greeter's postinst is only
debhelper's generated sysusers snippet. See [09 – OS name and login banner](09-customizing.md#os-name-and-login-banner).

It also gives fastfetch the FlickOS logo: with `ID=debian` fastfetch would
show Debian's. The conffile `/etc/xdg/fastfetch/config.jsonc` (read after a
user's `~/.config/fastfetch/`, also outside the session) points at
`usr/share/flickos/fastfetch/flickos.txt`, generated from `flickos.svg` by
`tools/make-fastfetch-logo.py`. fastfetch itself is a Recommends of
flickos-desktop (since 1.31, so new installs only). See [09 – fastfetch](09-customizing.md#fastfetch).

### `flickos-archive-keyring`

Installs the FlickOS apt repository's public key to
`/usr/share/keyrings/flickos-archive-keyring.asc`. The source file is
`packages/flickos-archive-keyring/keyrings/flickos-archive-keyring.asc`,
created by `repo/new-key.sh` (see [05 – Apt repository](05-apt-repository.md)).
It must be committed to git. It's the *public* key and safe to publish.

Also ships the repository itself (`/etc/apt/sources.list.d/flickos.sources`,
both distributions: `trixie` for FlickOS's packages and, since 1.6,
`trixie-community` for other developers' apps), so a new version of this
package can move it, and `/etc/apt/apt.conf.d/51flickos-origins`, which adds
both (`origin=FlickOS,codename=${distro_codename},label=FlickOS` and
`…-community,label=FlickOS Community`, their `Origin`, `Codename` and
`Label`) to the origins automatic updates install: Debian's `50unattended-upgrades` list plus this is
the Updates page's default scope. A choice on that page replaces the whole
list (`60flickos-updates`), and *Security fixes only* leaves FlickOS out.

## Anatomy of a package

```
packages/flickos-settings/
├── etc/…                     files to install (any layout you like)
└── debian/
    ├── control               name, dependencies, description
    ├── changelog             version history. The top entry IS the version
    ├── copyright             who owns which files, under which license
    ├── install               "source-path   destination-dir/" lines
    ├── rules                 build script. `dh $@` handles everything
    └── source/format         "3.0 (native)"
```

| File | Notes |
|---|---|
| `control` | First stanza = source package, then one stanza per binary package. Lines starting with `#` are comments. Use `Architecture: all` for anything without compiled code. `${misc:Depends}` must stay |
| `changelog` | Strict format, so edit with `dch`, not by hand. The version and distribution come from the top entry |
| `copyright` | [DEP-5](https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/) format, installed as `/usr/share/doc/PACKAGE/copyright`. `Files: *` is FlickOS's own work, GPL-3+ (the project license, `LICENSE`). Every file that came from elsewhere (a photo, a config copied from a Debian package) gets its own `Files:` stanza with its authors and license, after `Files: *` (the last match wins). Update it when you add such a file |
| `install` | Paths are relative to the package root. Destination is a directory |
| `rules` | Must be executable (`chmod +x`). `dh $@` runs the standard debhelper sequence |
| `source/format` | `3.0 (native)` for all FlickOS packages |
| `PACKAGE.postinst`, `.postrm`, `.triggers` (optional) | Maintainer scripts run by dpkg on install/remove, and trigger declarations. `#DEBHELPER#` marks where debhelper inserts generated code. Must be executable. Example: `flickos-branding` |

## Building

```sh
sh packages/build.sh
```

This builds **every** folder in `packages/` that has a `debian/` directory, and
puts the `.deb` files in `config/packages.chroot/`. It stops with an error if
the repository public key doesn't exist yet.

To build or inspect a single package by hand:

```sh
cd packages/flickos-settings
dpkg-buildpackage -us -uc -b        # .deb appears in packages/
dpkg-deb -c ../flickos-settings_1.0_all.deb    # list files inside
dpkg-deb -I ../flickos-settings_1.0_all.deb    # show control info
```

`build.sh` builds in a copy (`packages/.build/`) to keep build leftovers out of
the source tree. If you build by hand, clean up afterwards: `debian/.debhelper/`,
`debian/files`, `debian/flickos-settings/`, `debian/*.substvars` and the
`../*.deb`, `../*.buildinfo`, `../*.changes` files.

To test a package on a running FlickOS or Debian system without rebuilding the ISO:

```sh
sudo apt install ./config/packages.chroot/flickos-settings_1.1_all.deb
```

## Changing a package

Example: add a keybinding to `rc.xml`.

1. **Edit the file:** `packages/flickos-settings/etc/xdg/labwc/rc.xml`.
2. **Bump the version** with a changelog entry:
   ```sh
   export DEBFULLNAME="Jon" DEBEMAIL="dvbondoy@gmail.com"   # put these in ~/.bashrc or ~/.zshrc
   cd packages/flickos-settings
   dch -i -D trixie "Add Super+L to lock the screen."
   ```
   `dch -i` goes from `1.0` to `1.1`, and `-D trixie` sets the distribution.
   Without `-D`, dch writes `UNRELEASED`. Check the top of `debian/changelog`.
3. **Build and test:** `sh packages/build.sh`, then install the `.deb` in a VM or rebuild the ISO.
4. **Commit** the file change and the changelog together.
5. **Publish** so installed systems receive it: `repo/publish.sh` and upload.
   See [05 – Apt repository](05-apt-repository.md).

**Always bump the version when contents change.** apt only upgrades to a
*higher* version, and reprepro refuses a different file with a version it
already has.

### Version numbers

Keep it simple: `1.0`, `1.1`, `1.2`, … `2.0`. Native packages must **not** use
a `-1` suffix. Compare two versions with:

```sh
dpkg --compare-versions 1.10 gt 1.9 && echo yes    # yes: dpkg compares numerically
```

## Adding or removing a desktop package

Edit `packages/flickos-desktop/debian/control`, add the package under
`Depends:` or `Recommends:` (comma-separated, one per line, indented), then
bump the version with `dch -i -D trixie "Add firefox-esr."`.

Check that the name exists in trixie first: `apt policy firefox-esr` on a trixie
machine, or search at https://packages.debian.org/trixie/.

**Removing** a package from `flickos-desktop` does **not** remove it from
systems that already have it installed. It only stops new installs from
getting it. To really remove something from existing installs, add
`Conflicts:`/`Breaks:` (use with care) or document it in release notes.

## Creating a new package

Example: `flickos-wallpapers`.

```sh
cp -r packages/flickos-archive-keyring packages/flickos-wallpapers
cd packages/flickos-wallpapers
rm -rf keyrings debian/changelog
mkdir -p usr/share/backgrounds/flickos-extra
cp ~/Pictures/beach.jpg ~/Pictures/forest.jpg usr/share/backgrounds/flickos-extra/
```

(An extra wallpaper collection. The default wallpaper itself lives in
`flickos-settings`, see [09](09-customizing.md#wallpaper). Using a separate
directory guarantees the two packages never ship the same file.)

Then:

1. `debian/control`: change `Source:` and `Package:` to `flickos-wallpapers`,
   update `Depends:` and `Description:`. The description's first line is a short
   summary. Following lines start with one space, and blank lines are ` .`.
2. `debian/install`: `usr/share/backgrounds/flickos-extra/*   usr/share/backgrounds/flickos-extra/`
3. `debian/copyright`: change `Upstream-Name:`, and add a stanza for the
   photos, since they aren't FlickOS's own work (see `flickos-layouts`' for
   Unsplash photos).
4. `debian/changelog`: `dch --create --package flickos-wallpapers -v 1.0 -D trixie "Initial release."`
5. Build: `sh packages/build.sh`.
6. Make something pull it in, e.g. add `flickos-wallpapers` to
   `flickos-desktop`'s `Depends:` (or `Recommends:`) and bump that package's version too.
7. Publish both. See [05](05-apt-repository.md).

## Checking quality with lintian (optional)

`lintian` reports packaging mistakes:

```sh
sudo apt install lintian
lintian config/packages.chroot/flickos-settings_*.deb
```

Warnings like `no-manual-page` are expected for small distro packages. Errors (`E:`) are worth fixing.
