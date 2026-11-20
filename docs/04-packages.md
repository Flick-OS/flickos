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
  Settings' slider do nothing; and `file`, with which `xdg-open` finds a local
  path's type on labwc (without it every folder went to the web browser);
  and `rtkit`, which PipeWire only *recommends*: without it the sound threads
  get no real-time priority and sound breaks up under load (`rtkit-daemon` is
  started by D-Bus when PipeWire asks; 141 KB on disk, about 3 MB of memory,
  no measurable CPU and about 16 wake-ups a minute while idle); and `unzip`,
  `zip` and `7zip`, which Xarchiver and Thunar's Extract Here and Create
  Archive run for .zip and .7z files (Xarchiver only *recommends* them, so
  without them those files were "not supported"; about 8 MB together).
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
| `usr/bin/flickos-session` | `/usr/bin/` | Starts the session: config directories (`/etc/xdg/flickos-site`, the site's defaults over FlickOS's, always on the path, even while it doesn't exist; [10](10-custom-builds.md#layer-1-site-defaults)), input settings (`flickos-control prepare`), desktop layout overlay (`flickos-layout prepare`), `$XDG_RUNTIME_DIR/flickos/bin` last on `PATH` (flickos-phone's `flickos-phone-on`, for the file manager's *Send to Phone*), mise's shims (`~/.local/share/mise/shims`) first on `PATH` while mise is installed (1.61; Tool Kits' per-user versions, [design/flickos-dev.md](design/flickos-dev.md) ADR-009), keyboard layout, `exec labwc` (with `FLICKOS_PLAIN=1`: `labwc -C` on flickos-layout's plain folder). Run by the login screen and by the tty1 script |
| `usr/bin/flickos-session-plain` | `/usr/bin/` | The plain session: `FLICKOS_PLAIN=1 flickos-session`, FlickOS without the user's own changes ([09 – The plain session](09-customizing.md#your-own-style)) |
| `etc/profile.d/95-flickos-session.sh` | `/etc/profile.d/` | On tty1 login (live autologin, text login) runs `flickos-session` |
| `usr/share/wayland-sessions/flickos.desktop` | same | The session for other display managers |
| `etc/xdg/labwc/rc.xml`, `menu.xml`, `environment` | `/etc/xdg/labwc/` | Keybindings, root menu, cursor |
| `etc/xdg/labwc/autostart` | `/etc/xdg/labwc/` | Calls `/usr/libexec/flickos/autostart` |
| `usr/libexec/flickos/autostart` | `/usr/libexec/flickos/` | Starts kept screen arrangements (`flickos-control displays start`: kanshi, only while one is kept), wallpaper (`flickos-layout wallpaper`), panel (`flickos-layout panel`), notifications (and Do Not Disturb again: `flickos-control notifications`), applets, night light (`flickos-control night-light`, else the script), idle lock (`flickos-control idle`, else a fixed swayidle), the phone connection (`flickos-phone daemon`, which exits at once while off; not in the live session), the classroom agent if installed (`flickos-classroom-view student run`, the same), and last the startup applications (`flickos-control startup run`) |
| `usr/libexec/flickos/open-default` | `/usr/libexec/flickos/` | `browser` or `files`: starts the user's default app (`xdg-mime query default`, then `gio launch`), else `x-www-browser`, or Thunar (pcmanfm where Thunar is missing: systems installed before it replaced pcmanfm). Super+B, Super+E and the menu |
| `etc/xdg/flickos/` | `/etc/xdg/flickos/` | foot, fuzzel and default-app config: `mimeapps.list` (folders: Thunar, else pcmanfm), and `xdg-terminals.list` (foot, for `xdg-terminal-exec`); `Thunar/uca.xml`, Thunar's right-click actions (Open Terminal Here with `xdg-terminal-exec`, Send to Phone, Set as Wallpaper with `waypaper --wallpaper`); `autostart/` hides the XDG autostart entries of what autostart starts itself (nm-applet, blueman, the polkit agent, xdg-user-dirs) and keeps the print queue applet off |
| `etc/xdg/xfce4/xfconf/xfce-perchannel-xml/thunar.xml` | same | Thunar's defaults (xfconf): the path as buttons, a larger window, one row for title and toolbar (header bar, menu bar off, HIG WIN-1's exception), no status bar, larger icons. xfconfd is started by D-Bus without the session's `XDG_CONFIG_DIRS`, so it can't live in `/etc/xdg/flickos` |
| `usr/lib/systemd/user/thunar.service.d/flickos.conf` | same | `XDG_CONFIG_DIRS`/`XDG_DATA_DIRS` with FlickOS's folders for a Thunar started by D-Bus (another program's *Show in Folder*), which otherwise reads Debian's `uca.xml` and saves a copy in `~/.config/Thunar/` that hides FlickOS's actions |
| `etc/firefox-esr/flickos.js` | `/etc/firefox-esr/` | Firefox default prefs (Debian's firefox-esr reads every `.js` there; a user's own choice wins): vertical tabs, web apps (Taskbar Tabs, for flickos-switch's `webapp`) |
| `usr/lib/firefox-esr/distribution/distribution.ini` | same | Firefox's distribution customization: a FlickOS bookmark on the bookmarks toolbar, added once per profile (a deleted one stays deleted); id `flickos`, shown in Help → About |
| `usr/libexec/flickos/level` | `/usr/libexec/flickos/` | The volume, microphone and brightness keys: changes the level (`wpctl`, `brightnessctl`, 5 % steps), then runs flickos-menu's `/usr/libexec/flickos/osd` for the ring if it is installed (nothing shows while locked; the volume, microphone and media keys work then, `allowWhenLocked` in `rc.xml`, flickos-lock's ADR-020) |
| `usr/libexec/flickos/lock` | `/usr/libexec/flickos/` | Locks the screen (Super+L, the menus): `flickos-control lock` (the background chosen in Settings), else `swaylock -f -c 383c4a` |
| `usr/libexec/flickos/night-light` | `/usr/libexec/flickos/` | Starts wlsunset timed for the time zone's city (`zone1970.tab`), passing its own options on (`flickos-control night-light` gives `-t`) |
| `usr/share/flickos/` | `/usr/share/flickos/` | waybar and mako config (the mako config has the `do-not-disturb` mode) |
| `usr/share/flickos/pipewire/realtime.conf` | same, linked as `50-flickos-realtime.conf` into the `conf.d` folders of PipeWire, its Pulse server, clients, JACK and filter chains (`debian/links`) | Sends PipeWire's real-time requests to rtkit, not to the portal: Debian 13's portal refuses them while PipeWire logs success |
| `usr/share/backgrounds/flickos/default.jpg` | same | Wallpaper for layouts without their own, and without flickos-layouts |
| `usr/share/glib-2.0/schemas/90_flickos-settings.gschema.override` | same | GTK theme (Arc-Dark), icons (Numix-Circle), fonts, dark mode, title bar buttons of windows that draw their own |
| `usr/share/themes/FlickOS-Arc-Dark/labwc/themerc` | same | labwc window theme in Arc-Dark colors (arc-theme has none for labwc) |
| `usr/share/themes/FlickOS-Arc/labwc/themerc` | same | The same in Arc (light) colors, for the Light style |
| `usr/share/themes/*/labwc/*.svg`, `*.xbm` | same | Title bar buttons: Arc's round close button and round hover (SVG, `tools/make-titlebuttons.py`) and arc-openbox's glyphs (`.xbm`) |

Every file is explained in [09 – Customizing](09-customizing.md).

**Thunar's wallpaper plugin is diverted** (`debian/flickos-settings.preinst`,
removed again by the `postrm`). Its *Set as wallpaper* sets one only where
`XDG_CURRENT_DESKTOP` is `XFCE` or `GNOME`; on FlickOS it did nothing and
said nothing. The diversion renames
`/usr/lib/x86_64-linux-gnu/thunarx-3/thunar-wallpaper-plugin.so` to
`….so.flickos-off`, which Thunar doesn't load (only `.so` files), and
`uca.xml`'s *Set as Wallpaper* takes its place (since 1.56). A Thunar that is
already running keeps the plugin until it quits (`thunar -q`).

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
| `usr/bin/flickos-layout` | `/usr/bin/` | Python 3 tool: `list`, `current`, `set`, `style list/current/set/new` (`new`: a user's own style, [09 – Your own style](09-customizing.md#your-own-style)), `layout new` (a user's own layout from one of FlickOS's, waybar only), `tweaks new` (a starter for the user's panel CSS, `~/.config/flickos/tweaks/style.css`), `check` (a style, `--layout` a layout, or everything of the user's), `explain` (which file each program reads), `clicks list/current/set`, `launcher list/current/set`, `menu-style list/current/set`, `clock list/current/set`, `buttons list/current/set` (where the window buttons are: the layout's own, left, right or split, for every layout; `set --buttons` too), `state` (all of them and doctor's warnings as JSON, for the Settings window), `prepare`, `panel`, `reload-panel` (generate the panel again and restart it: flickos-phone, when its button comes or goes), `supervise`, `wallpaper`, `doctor`, `pick` (chooser), `first-run`. Every `set` also takes `default` (removes the user's choice), and every change that shows is recorded for *Settings → History* |
| `usr/libexec/flickos/check-css` | same | `FILE…`: parses CSS with GTK 3's own parser (python3-gi, no display) and prints one JSON line per file, `ok` or the first error's file, line and column. flickos-layout runs it on the user's CSS before the panel reads it, since waybar exits on any CSS error ([09 – Panel tweaks](09-customizing.md#panel-tweaks)) |
| `usr/libexec/flickos/desktop` | same | `N`, `next` or `previous`: goes to that labwc desktop (ext-workspace-v1). What a desktop button in the panel runs on a click or scroll; a small stdlib program because a click must be quick. `show`: what the desktop keys run after labwc has switched; reads the current desktop and runs flickos-menu's `osd desktop NUMBER COUNT` for the circles card (desktops ADR-006) |
| `usr/share/flickos/layouts/ID/` | same | One folder per layout (`redmond`, `cupertino`, `traditional`): `layout.ini`, `waybar.jsonc`, `style.css`, `preview.png` |
| `usr/share/backgrounds/flickos/ID.jpg` | same | The layouts' photos (their wallpapers until 1.37), now only choices in waypaper |
| `usr/share/backgrounds/flickos/flickos-dark.png`, `flickos-light.png`, `flickos-home.png` | same | Dark's and Light's earlier wallpapers (the halo until FlickOS 2.3, then the house at dusk until flickos-layouts 1.81), now only choices in waypaper. Real files, so a user who picked one keeps it |
| `debian/links` | `/usr/share/backgrounds/flickos/flickos-shore.png` | Link to the styles' wallpaper, for waypaper |
| `usr/share/flickos/layouts/common/` | same | `modules.jsonc` and `base.css`, shared by every layout. `custom/phone` (flickos-phone's button) is defined there, and the generated panel has it just before `custom/tiler` only while `flickos-phone get enabled` says yes (never in the live session) |
| `usr/share/flickos/styles/ID/` | same | One folder per style (`dark`, `light`): `style.ini` (GTK, icon and labwc theme names), the palettes `waybar-colors.css`, `foot.ini`, `fuzzel.ini`, `mako.conf`, and `wallpaper.png` (shown with every layout). Users' own styles are in `~/.local/share/flickos/styles/ID/` (looked at first; `Inherits=`) |
| `etc/xdg/flickos/layouts.conf` | same | Default layout, style, desktop clicks, apps button, start menu style, clock, Quick Settings and floating panel (conffile). `/etc/xdg/flickos-site/flickos/layouts.conf` goes over it key by key ([10](10-custom-builds.md#layer-1-site-defaults)); `flickos-layout apply-defaults` applies a change of the defaults to the session without saving a choice, and a default style, layout or window buttons the account never chose reaches GTK once per change (`DEFAULT_LOOK` in `$XDG_STATE_HOME/flickos`), at login and in `apply-defaults` |
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
  and desktop switcher). A user's own pinned apps per layout
  (`flickos-layout pinned`, `~/.config/flickos/pinned`; Settings' *Pinned
  Apps*) replace the layout's `Pinned=`: a stopgap while sfwbar, in beta,
  can't pin apps itself in a way that lasts. `pinned add` and `remove` take
  an app's desktop id or a window's app id (`firefox-esr`, `Thunar`, a
  `StartupWMClass`; since 1.86), which is what a dock's right-click menu
  sends (Footprint's).
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
- **It moves keys the keyboard lacks** (1.71,
  [design/flickos-keys.md](design/flickos-keys.md)): labwc finds a keybind's
  key only where a layout of the keymap gives its symbol without Shift or
  AltGr, so Super+[ never fires on a Finnish keyboard. The last step of the
  overlay rc.xml (`move_keys`) reads labwc's keymap (`keyboard_names`: the
  user's labwc `environment`, flickos-control's, the system's, else
  `/etc/default/keyboard`; libxkbcommon through ctypes, not loaded for a US
  keyboard) and moves such a keybind to `KEY_ALIASES`' stand-in (`=` → `+`),
  else to the key in the same place on a US keyboard (`[` → `å`), unless that
  key is bound; `KEY_PAIRS` (`[`/`]`, the tiling ratio) move both or neither
  (`moved_keys`, pure). `keys/moved.json` lists what moved and what couldn't,
  for `explain labwc`, `doctor` and flickos-shortcuts.
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
- **It owns the floating panel choice** (`floating-panel`: `off`, the default,
  or `on`; `on` in a layout with `FloatingDefault=on`, Tortuga's, unless the
  user or the system chose). While it is on, a layout with `Floating=` and
  `FloatingFull=` in its `layout.ini` (Redmond and Tortuga) imports that CSS, its generated config has
  `reload_style_on_change`, and the overlay has `waybar/panel-state.css`, which
  flick-tiler changes, and `waybar/panel-full.css`. While it is off, none of
  that exists. See [design/flickos-floating-panel.md](design/flickos-floating-panel.md).
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
  patched `config.py` reads before the user's config, a `common.py` that
  leaves out links to nothing (one hid every picture after it in the grid,
  2.9+flickos2), and the desktop file without its `#!` line.
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

- **A compiled FlickOS package** (with `neatvnc`): `Architecture: any`, built with meson
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
  the top bar, ran past the bottom of the screen), and (+flickos8) a desktop
  file's `Icon=` that is a file's full path drawn as that file, so
  Firefox's web apps show their own icons (upstream looked every `Icon=` up
  in the icon theme and fell back to its default icon), and (+flickos9) a
  right click on a `group = popup` button always runs the taskbar's
  `RightClick` action (upstream ignored it on a pin without a window and on
  a group of several windows), with `WindowInfo()` answering `"appid"` and
  `"pinned"` for such a button: the base of Footprint's Pin to Dock menu.
- **Used by `flickos-layouts`** (a Depends): `flickos-layout` generates the
  layout's sfwbar config (`Dock=`) in the layout overlay and runs `sfwbar -f FILE`
  ([The generated panel](09-customizing.md#the-generated-panel)).
- **License:** GPL-3 (version 3 only), protocol files MIT/HPND, weather icons
  MIT (`debian/copyright`).

### `neatvnc`

Debian trixie's `neatvnc` 0.9.1+dfsg-1 source (the VNC server library under
wayvnc), rebuilt **without H.264** for
[flickos-classroom-view](#flickos-classroom-view) (its ADR-013). With
Debian's `libneatvnc0`, wayvnc brings libavcodec, libavfilter and libflite:
53 MB on every student computer. With this one, 1.2 MB. Debian's own wayvnc
runs on it unchanged.

- **Only `libneatvnc0`** is built (`Architecture: any`, meson), opt-in:
  `packages/build.sh` stages it in `config/packages.opt-in/`, never the ISO.
- **Packaging changes only**, no upstream code changed (`debian/README.source`):
  `-Dh264=disabled`, the libav `-dev` packages out of `Build-Depends`, no
  `libneatvnc-dev` (its files listed in `debian/not-installed`), no `-dbgsym`,
  `3.0 (native)`, and `GIT_DIR` pointed nowhere (meson.build would otherwise
  write the FlickOS repo's commit and branch into its version string).
- **Version** `0.9.1+dfsg+flickosN` (`~testN` on a branch): it must stay above Debian's, or apt
  installs Debian's again. flickos-classroom-view depends on it by version.
- **Tests:** upstream's own, run at build (`-Dtests=true`).
- **License:** ISC (upstream), Expat, BSD-3-Clause; Debian's packaging CC0;
  FlickOS's files GPL-3+ (`debian/copyright`).

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
  `MasterRatio`, `Gap`, `Float`, `TileOpen`), then the site's
  `/etc/xdg/flickos-site/flickos/tiler.conf` (key by key), then the user's
  `~/.config/flickos/tiler`. `mode|ratio|gap default` go back to the site's value.
- **Depends on flickos-layouts (>= 1.8)**, whose `flickos-layout reconfigure`
  merges the tiling fragment into the rc.xml overlay, and flickos-settings
  (>= 1.11) for the Super+T binding and the autostart line.
- **Commands for the Settings window** (flickos-control): `flick-tiler floating
  list|add|remove PATTERN` changes the `Float=` list (the whole list goes into
  the user's file, since it replaces the system one), `flick-tiler gap N` the
  gap, and `status` also gives the main window width (`ratio`) and `gap`.
  `mode`, `ratio` and `gap` take `default` (removes the user's value).
- **Windows already open** stay as they are when tiling is turned on, unless
  the user chose to tile them too (`flick-tiler tile-open on|off|default`,
  `TileOpen=`, off by default since 1.12; *Settings → Tiling*). Tiling them
  focuses each one in turn, which also switches desktops, so it is opt-in.
  `status` gives the choice as `tile_open`.
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
- **Floating panel:** while flickos-layouts' `waybar/panel-state.css` exists,
  the daemon keeps it saying whether a window is maximized, fullscreen or tiled
  (`update_panel`), and writes nothing without it
  ([design](design/flickos-floating-panel.md)).
- **History:** every change of these settings (Super+T and the panel
  included) is recorded for *Settings → History*, like flickos-layout's (see
  flickos-control).
- **A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`.
- **Unit tests** in `tests/` (arrangements, window bookkeeping, fragment, the
  Wayland client against a fake compositor), run at package build like
  flickos-layouts'.

### `flickos-cursor`

The mouse cursors: Bibata Modern Classic as the theme `FlickOS-Bibata`
(`usr/share/icons/FlickOS-Bibata/`), the sizes 24, 32, 48 and 64 out of Debian's
14: 5.5 MB against the 178 MB of `bibata-cursor-theme`, whose folder it doesn't
share, so both can be installed. A Depends of flickos-settings, which names it
in the GSettings override and labwc's `environment`; flickos-greeter's start
script names it too, for the login screen, and the three must match.

`usr/share/icons/FlickOS-Bibata/` is generated and committed:
`tools/make-cursor.py [SOURCE]`, needed only for a new Bibata or other sizes.
Costs and decisions: [design/flickos-polish.md](design/flickos-polish.md).

### `flickos-theme`

The GTK 3 and GTK 4 themes `FlickOS-Arc-Dark` and `FlickOS-Arc`: arc-theme
20221218's Sass, vendored in `src/` with FlickOS's changes marked `FlickOS:`
(corners of 6 and 8 px, the header bar's height from one `$header_height`, the
light theme's sidebars and file dialogs' bottom bar in the window's own colors,
with normal buttons in that bar since 1.2; Arc's colors stay), compiled
by `build.sh` (sassc and glib-compile-resources, in Build-Depends) into a
`gtk.gresource` per theme folder next to the labwc themes of the same names in
flickos-settings. `src/frame-*.css` is the window frame for client-side
decorated windows (Thunar's header bar), which labwc's theme can't reach; its
colors follow labwc's border colors (`tools/check-look.py` compares them, and
the header bar's colors with the title bar's). Needs no
arc-theme at run time; where the source and the 168 PNG assets come from:
`debian/README.source`. Tests (`tests/`, run after the build) check both parts of
both themes, that the gresources hold what `gtk.css` imports, and that GTK 3
parses every stylesheet. Design and decisions: [design/flickos-seamless-2x.md](design/flickos-seamless-2x.md)
(ADR-2X-1, ADR-2X-4).

**Who uses it** (since flickos-layouts 1.83): Dark's and Light's
`style.ini` name `FlickOS-Arc-Dark` and `FlickOS-Arc`; flickos-settings'
GSettings override and flickos-greeter's `GTK_THEME` name `FlickOS-Arc-Dark`;
flickos-layouts, flickos-settings, flickos-greeter and flickos-desktop depend
on it (and the sanity hook requires it). arc-theme stays installed, so
choosing `Arc-Dark` in nwg-look is a rollback, except that windows with their own
header bar then get arc-theme's own frame, not FlickOS's. An account whose
`gtk-theme` still holds the 2.x names `Arc-Dark` or `Arc` gets the style's theme
once, at its first login after the upgrade (`gtk-theme-moved` in
`$XDG_STATE_HOME/flickos/`, `move_retired_gtk_theme`), and by every `style set`;
Arc-Dark chosen again afterwards is kept.

### `flickos-shortcuts`

The keyboard shortcut sheet: hold Super on its own for `HOLD_MS` (0.7 s) and
the session's shortcuts appear in the middle of the screen until Super is let
go. Also *Settings → Keyboard Shortcuts* and the app launcher
(`flickos-shortcuts show`, closes on any key or click). One Python 3 file,
`usr/bin/flickos-shortcuts`, plus `usr/share/flickos/shortcuts/style.css`
(Arc-Dark, in `tools/check-palette.py`). While flickos-menu's prompt style is
the start menu (the second line of `$XDG_RUNTIME_DIR/flickos/menu/anchor`),
the sheet has a *Start menu* section with that menu's own keys
(`PROMPT_KEYS`, since 1.19; they aren't labwc's, so rc.xml doesn't have them).

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
- **Small screens:** the sheet takes the first arrangement in `FITS`
  (columns, and the `compact` class: smaller text, keys and margins) that fits
  the smallest screen less `FIT_MARGIN` (`fit_sheet`, `screen_room`): three
  roomy columns on a large screen, compact ones on a 1366x768 laptop. The
  compositor picks the screen and doesn't say which, so it fits them all. The
  choice is kept while the shortcuts, the screens and the GTK look stay the
  same (`_FITTED`; measuring costs about 20 ms an arrangement). When none
  fits, the closest is shown, and `show` scrolls. Descriptions aren't wrapped:
  GTK measures a wrapping label's height differently from one try to the next.
- **What it lists:** the keybinds of the rc.xml labwc uses (first of
  `$XDG_CONFIG_HOME`, then `$XDG_CONFIG_DIRS`: a user's own, the flickos-layouts
  overlay with flick-tiler's keys while tiling is on, or flickos-settings'),
  plus labwc's built-in ones (`DEFAULT_KEYBINDS`) with `<default />`. Read
  again every time it is shown. Descriptions come from `COMMANDS` and
  `ACTIONS`, and for add-ons' keys from flickos-layouts'
  `$XDG_RUNTIME_DIR/flickos/shortcuts/addons.json` (under *Other*); media,
  volume and brightness keys are left out. A key flickos-layouts moved for the
  keyboard layout (`keys/moved.json`) shows as the keyboard labels it (Super +
  Å; `key_name`, libxkbcommon's character or `DEAD_KEYS`), and moved number
  keys keep one row per desktop action (1.17).
- **Started by** flickos-settings' autostart (`flickos-shortcuts daemon`, one
  per session: `$XDG_RUNTIME_DIR/flickos/shortcuts.lock`).
- **A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`.
- **Unit tests** in `tests/` (rc.xml reading, descriptions, the hold timing,
  the fades with a fake window, the Wayland client against a fake
  compositor), run at package build.

### `flickos-lock`

The lock screen: a password box with a button that shows the password
(Alt+V), the time, the date and the user's name and picture on one card over
the wallpaper, in the colors of the GTK theme (so of the style in use). One
Python 3 file, `usr/bin/flickos-lock`, plus `usr/share/flickos/lock/style.css`
(theme colors only, in `tools/check-palette.py`) and the PAM file
`/etc/pam.d/flickos-lock` (`@include common-auth`). Design, decisions and
measurements: [design/flickos-lock.md](design/flickos-lock.md).

- **How it locks:** only through `ext-session-lock-v1`, so labwc keeps every
  screen covered whatever the lock screen does. `flickos-lock lock` (the
  *front*, standard library only) locks first with its own small Wayland
  client (`PreLock`, about 35 ms) and returns once labwc confirms, so
  swayidle's lock before sleep is safe; about 0.1 s in all, most of it
  Python compiling the file. It forks the *guard*, which starts the GTK lock
  screen (`flickos-lock screen`, gtk-session-lock) and, once that has loaded
  GTK, lets its own lock go; the lock screen takes over the (still covered)
  session within milliseconds. One lock at a time: the guard holds
  `$XDG_RUNTIME_DIR/flickos/lock/lock.lock`, and a second `lock` waits for
  `locked` there, then returns.
- **When something fails:** the lock screen dying, hanging before it takes
  over, or ending without an unlock: the guard starts swaylock (in the
  style's colors, `SWAYLOCK_STYLE`), which takes over the lock; the password
  unlocks it the same way. Without `ext-session-lock-v1`, `lock` runs
  `swaylock -f`. What happened is in `$XDG_RUNTIME_DIR/flickos/lock/lock.log`.
- **The password** is checked by PAM through ctypes (`authenticate`) in a
  thread; `unlock()` is the only caller of `unlock_and_destroy`, after
  `PAM_SUCCESS` or within the idle lock's grace period (a test checks both).
  Not login's PAM stack: its `pam_nologin` refuses during a scheduled shutdown.
- **What it shows:** see the design's ADR-006 and ADR-007. The eye is left
  out while flickos-screenshot records or the second screen is on (ADR-011);
  the live session says its password; "Caps Lock is on" is its own line
  (GTK's warning needs the icon slot the eye uses); Super+=, Super+-,
  Super+0 and Super+scroll scale the card (labwc runs no keybindings while
  locked), kept for the session in `lock/zoom`; the clock is set again after
  sleep (logind's `PrepareForSleep`).
- **Run by** flickos-control's `lock` (Super+L, the menus, swayidle) while
  it is installed and swaylock has no config of the user's or the system's.
  Owns no settings. Nothing runs while the screen is unlocked.
- **A class lock** (1.3, for flickos-classroom-view's ADR-007): `lock
  --class-message TEXT --release FILE` shows TEXT where the password box
  would be and takes no keys. The lock screen looks at FILE once a second
  (only during a class lock, `class_release`): removed, it unlocks
  ("teacher"); unrefreshed for `CLASS_FAILSAFE` (120 s), it unlocks
  ("failsafe"). The lock folder holds `class` meanwhile; a `lock` asked for
  then (swayidle) leaves `wanted`, and the release brings the password box
  back instead of unlocking. If the class lock screen dies, swaylock takes
  over with the student's own password: it is no security boundary.
- **A demo** (1.4, flickos-classroom-view's ADR-014): `--class-image FILE`
  with a class lock shows the picture in FILE (the teacher's screen, JPEG)
  instead of the card, fitted to each screen. Only during that class lock,
  FILE is looked at every `DEMO_CHECK_MS` (500 ms); a changed one is decoded
  and scaled in a thread (not scaled when its size is the screen's). The
  release, failsafe, `wanted` and swaylock rules are the class lock's; when
  the password box comes back, the picture goes.
- **A Depends of `flickos-desktop`** (1.32, phase 3 of the design) and in
  the sanity hook's `REQUIRED`: it replaces swaylock for everyone, installed
  systems included. swaylock stays as its fallback; a swaylock config of the
  user's or the system's keeps swaylock (the way back, ADR-009).
- **Boot test:** the last two checks lock through Super+L's script, kill the
  lock screen and see swaylock take over, then end the lock without a
  password (the guard and swaylock killed, `PreLock` takes the abandoned lock
  over and unlocks it). Typing the password stays a check by hand.
- **Unit tests** in `tests/` (the pre-lock against a fake compositor, the
  guard with a stand-in lock screen, PAM through a private PAM folder, the
  one unlock path and its five reasons, the class lock's release and
  `wanted`, the card's contrast in every style), run at package build.
- **Hooks** ([flickos-hooks](#flickos-hooks)): the guard, and only the guard,
  runs its `fire()` for `locked` (after "locked by the lock screen") and
  `unlocked` (after the marker is gone). It is never in the lock screen process,
  which decides the unlock, and a bug in it is logged, never the end of the guard
  (`fire_hooks`). When swaylock had to take over, `unlocked` doesn't fire.

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
  fuzzel; fuzzel while windows are offered too). It answers with the line
  portal-wlr gave for that screen: the bare name before 0.8,
  `Monitor: NAME DESCRIPTION` since, which 0.8 wants back whole. portal-wlr
  reads it only when it starts: after the install, from the next login. A
  user's own `~/.config/xdg-desktop-portal-wlr/` file wins.
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

### `flickos-media`

Media controls in the panel and a sound spectrum, just above the panel or
around a ring in the middle of the screen. One Python 3
file, `usr/bin/flickos-media` (GTK 3 and gtk-layer-shell only in the
spectrum), its conffile and its panel icon
(`usr/share/icons/hicolor/scalable/actions/flickos-spectrum-symbolic.svg`).
Design and measurements: [design/flickos-media.md](design/flickos-media.md).
A Depends of flickos-desktop and in the sanity hook's `REQUIRED`.

- **Off by default** (HIG INT-9). `flickos-media set controls on` runs
  `flickos-layout reload-panel`, which puts flickos-layouts' five
  `custom/media-*` modules (previous, play, next, the title, the spectrum's
  button; `MEDIA_MODULES`, `use_media`) into the generated panel before the
  phone's button, while `flickos-media get controls` says on. They show only
  while an app plays or has paused something.
- **The follower** (`follow`) is the title module's program: waybar starts it
  and it ends with waybar (its parent's death, or `POLLERR` on its pipe). One
  `playerctl --follow` tells it about every change (nothing while a track
  plays steadily). The follower holding `follow.lock` writes the buttons'
  JSON into `$XDG_RUNTIME_DIR/flickos/media/panel/`, which their modules
  `cat`, and sends waybar signal 12 (`PANEL_SIGNAL`); the player the buttons
  control is in `media/player`. The title shows 24 characters; a longer one
  scrolls through once when its track plays, then shows its start with "…"
  (one line to waybar every 0.35 s meanwhile, the follower's only timer), with the class `scrolling`, whose fixed width in base.css
  keeps the buttons beside it still.
- **The spectrum** (`strip`, run by the follower while `spectrum` is on and a
  player plays, stopped 3 s after it stops) is one layer-shell window per
  screen on the panel's edge with exclusive zone 0, which labwc places just
  above the panel. Clicks go through it (an empty input region on the
  GtkWindow, set again after every remap). cava does the sound work, with its
  config and shader copies in the runtime folder; the strip draws 48 bars at
  20 frames a second in the GTK theme's selection color. `spectrum-layer`
  `behind` = BOTTOM layer, `top` = TOP (a fullscreen window still covers
  it); a change remaps the windows, since `set_layer` alone waits for a
  commit a covered window never makes. `spectrum-shape` `radial` draws the
  bars around a ring instead (`strip --shape radial`, `ring_spokes`): one
  square window per screen, half its shorter side, anchored to no edge so
  labwc centers it, always on BOTTOM (the layer setting is for the strip),
  clicks going through it; the ring and the gradient are drawn once per size
  (`ring_picture`), the bars with cairo's FAST edges. A shape change restarts
  the strip. `spectrum-colors` `rainbow` (opt-in, ADR-012) draws every hue
  instead: round the ring from cyan at the top to red at the bottom, with a
  white ring (a cairo mesh, `rainbow_sectors`), or along the strip from the
  left (`strip_picture`), also drawn once per size; a change is the layer's
  SIGUSR1 (`look_again`), no restart.
- **Settings** (`get`/`set`/`toggle`, `state` for the Settings page):
  `controls` on|off, `spectrum` on|off (both off), `spectrum-layer`
  behind|top (behind), `spectrum-shape` strip|radial (strip), `spectrum-colors`
  style|rainbow (style). The system default is the conffile
  `/etc/xdg/flickos/media.conf`, the user's choice `~/.config/flickos/media`;
  `set KEY default` puts the system's back. Every change is recorded for
  History. *Settings → Media Controls* (flickos-control's `MediaPage`) runs
  these commands; the spectrum button's click and right click run `toggle`.
- **Cost**: nothing while off. With the controls on, the follower and
  playerctl (about 7 MB, no wakeups while nothing changes). The spectrum
  about 6 % of one thread of an older laptop while it shows, ~3 % while
  covered (cava still works), nothing in silence; 25 MB for the strip and
  6 MB for cava while it runs. The ring about 9 % while it shows (its
  window has about twice the strip's pixels).

### `flickos-weather`

The weather in the panel: the temperature and the sky now, the next hours and
days in the tooltip, for a place the user picks. One Python 3 file,
`usr/bin/flickos-weather` (standard library only, no GTK), and its conffile.
Design: [design/flickos-weather.md](design/flickos-weather.md); what it sends:
[PRIVACY.md](../PRIVACY.md#the-weather). A Depends of flickos-desktop and in
the sanity hook's `REQUIRED`.

- **Off by default** (HIG INT-9). `flickos-weather set enabled on` runs
  `flickos-layout reload-panel`, which puts flickos-layouts' `custom/weather`
  into the generated panel while `flickos-weather get enabled` says on: where
  a layout's bar has the `flickos/weather` placeholder (Eleven's left end;
  dropped while off), else before the tiling button (`use_weather`).
- **No daemon.** waybar runs `flickos-weather panel` every 15 minutes (the
  module's `interval`, HIG PERF-5's one exception). It answers from
  `~/.cache/flickos/weather/forecast.json` and asks Open-Meteo only when that
  is an hour old or for another place or unit (15 minutes after a failure);
  one screen's run fetches while the others wait on a lock. A setting changed
  while on sends waybar signal 13 (`PANEL_SIGNAL`), only to a waybar that
  catches it.
- **The button:** `text` the temperature, `alt` the temperature with its unit
  over the sky in words (a layout's `"format": "{alt}"`), `class` the sky
  (`clear`, `few-clouds-night`, …, drawn by base.css from the icon theme's
  `weather-*-symbolic`), `stale` after two hours, hidden after six; "Weather"
  (`unset`) until a place is chosen. A click opens *Settings → Weather*. The
  tooltip's hours follow the panel clock's 12/24-hour choice (the user's, else
  `Clock=` of the site's `layouts.conf`, else FlickOS's).
- **Settings** (`get`/`set`, `state` for the Settings page): `enabled` on|off
  (off), `units` auto|celsius|fahrenheit (auto: by the region of
  `LC_MEASUREMENT`/`LANG`), `wind` auto|kmh|ms|mph|kn (auto: mph with
  Fahrenheit, else km/h), `place` `LAT,LON,NAME` (rounded to two decimals,
  about 1 km). `find TEXT [--json]` searches places (Open-Meteo's search, only
  when asked); `refresh` fetches now. The system default is the conffile
  `/etc/xdg/flickos/weather.conf`, whose `[Server]` addresses (only ever
  read from that file) let an organization use its own Open-Meteo; the
  user's choice is `~/.config/flickos/weather`. Every change is recorded for
  History. *Settings → Weather* (flickos-control's `WeatherPage`) runs these
  commands.
- **Cost:** nothing while off. While on, about 70 ms of one Python start every
  15 minutes per screen, and at most 24 requests a day of about 3 KB.

### `flickos-hooks`

Your own programs, run when something happens on the desktop. One Python 3
file, `usr/bin/flickos-hooks` (standard library only, no GTK). Design:
[design/flickos-hooks.md](design/flickos-hooks.md). A Depends of flickos-desktop
and in the sanity hook's `REQUIRED`.

- **The hooks** are executable files in `~/.config/flickos/hooks/EVENT.d/`
  (`XDG_CONFIG_HOME` is honoured), in any language, run one after another in
  the order of their names. Hidden files, `~`, `.bak` and `.dpkg-*` files are
  left alone; `.sh` is fine.
- **No daemon.** The program that sees an event starts `flickos-hooks run
  EVENT`, through a `fire()` of its own that costs one failed `listdir` while
  there are no hooks (0.01 ms on the i3-4030U) and, with some, a `setsid -f`
  that returns at once (about 1.7 ms; the hook has run after about 45 ms).
  Who fires what:

  | Event | Values | Fired by |
  |---|---|---|
  | `locked`, `unlocked` | none | flickos-lock's guard: after the lock screen has the lock, after a real unlock (not when swaylock had to take over) |
  | `woke` | none | flickos-control's swayidle, from `after-resume` (`WOKE_COMMAND`: a shell test of the folder, then `setsid -f`, because `-w` would otherwise hold every swayidle event; design H4) |
  | `screens` | none | flickos-layout's panel supervisor (`screens_changed`): a screen came or went, or was turned off or on, and they settled. Moving one fires nothing |
  | `phone-connected`, `phone-disconnected` | `FLICKOS_PHONE_ID`, `FLICKOS_PHONE_NAME` (connected only) | flickos-phone's daemon, for a paired phone (`watch_connected`, `watch_disconnected`) |
  | `changed` | `FLICKOS_OWNER`, `FLICKOS_KEY`, `FLICKOS_OLD`, `FLICKOS_NEW`, as History has them | every owner of History's `record()` (below) |
  | `screenshot`, `recording` | `FLICKOS_FILE` | flickos-screenshot, once the file is saved (`finish`, `run_recording`); not a copy-only screenshot or a broken recording |
- **`changed`** fires only once the change is applied (design ADR-007): each
  owner's `record()` queues it before its History check, so History off makes
  no difference, and `fire_changed()` fires the queue when the command is done
  (`main()`'s `finally`), or where a long-running process has applied it:
  flick-tiler's daemon loop, flickos-phone's daemon after a pairing,
  Software's paid switch, the Settings window's languages and accounts,
  `flickos-layout watch`, and flickos-screenshot's bar before the recorder
  replaces it. Only the keys `changed_key()` allows fire: each owner's
  settings and choices; flickos-control also its system settings, default
  apps, startup apps, languages, accounts, animations and picture, but never
  the store key (`purchases`) or a History restore (`restore`), whose own
  changes fire as they are undone. A key History learns isn't promised to
  scripts until it is added there. Each owner has `tests/test_hooks_events.py`.
- **What `run` does:** the hooks of the event, 30 s each (SIGTERM to the hook's
  process group, SIGKILL 5 s later), output to `$XDG_RUNTIME_DIR/flickos/hooks.log`
  (private, started again above 256 KB). The environment is the session's
  without any `FLICKOS_*` variable (swayidle's `FLICKOS_IDLE` would leak), then
  `FLICKOS_EVENT`, the event's values and `FLICKOS_HOOK=1`. Two firings of one
  event never overlap (the second waits 60 s, then is dropped), and more than
  20 starts of one event in a minute are dropped with one log line.
- **Never:** in the plain session (`FLICKOS_PLAIN`), under a hook
  (`FLICKOS_HOOK`: a hook's own changes fire nothing), as root, from packages
  (there is no system folder), at the login screen or in the installer.
- **Commands:** `events` (event, values, meaning), `list` (event, file, state:
  `ready`, `not executable`, `ignored`; a folder named like no event is listed
  as `no such event`, the likeliest typo), `test EVENT [NAME=VALUE ...]` (runs
  the hooks now with their output on the terminal; exit 1 if one failed), `log`,
  and the internal `run`. Event names and value names are promised to scripts
  (design ADR-008): add, never rename or remove.
- **Tests:** `tests/test_hooks.py` runs real shell hooks in temporary XDG
  folders. A test finds every `def fire(` in the tree and checks it carries the
  same contract. flickos-lock's tests check that only the guard fires, with a
  stand-in `flickos-hooks`, one that hangs included; each owner of `changed`
  has `tests/test_hooks_events.py`.

### `flickos-switch`

*Bring Files from Windows* and the answer to a double-click on a Windows
program (`usr/bin/flickos-switch`, Python 3; udisks2 over D-Bus with `Gio`,
GTK 3 only for the windows; `flickos-switch-files.desktop` in the apps menu,
live and installed). It
finds Windows partitions, mounts them **read only** through udisks2 (the
kernel's ntfs3 reads NTFS; no ntfs-3g), and copies an account's Desktop,
Documents, Downloads, Music, Pictures and Videos, and the same folders under
`OneDrive*`, into the matching XDG folders (`xdg-user-dir`), or in the live
session into `Files from Windows/ACCOUNT/` on a USB drive. It owns no
settings and runs nothing in the background. Design and phase 0 facts:
[design/flickos-switch.md](design/flickos-switch.md).

- **Commands:** `find [--json]` (candidates from `GetManagedObjects`, no
  mounting: NTFS that isn't a recovery partition, and BitLocker volumes),
  `scan DEVICE [--json]` (mounts read only if needed, checks for
  `Windows/System32` and `Users`, counts each account's folders), `unlock
  DEVICE` (BitLocker, the recovery key on stdin), `copy DEVICE ACCOUNT
  FOLDER... [--to DIR] [--bookmarks] [--json]` (a JSON line per event:
  `plan`, `file`, `failed`, `done`), `release [DEVICE]`, `files` (the
  window, which runs the others with `Gio.Subprocess`), `before-install`
  (flickos-installer's *Install FlickOS* runs it first: `continue` without
  a Windows partition, else a dialog offering to copy the files first,
  printing `copy`, `continue` or `cancel`; `flickos-install` starts
  Calamares only on `continue`, or when flickos-switch is missing or
  fails).
- **What it never does:** write to the Windows disk; open a folder with
  NTFS's reparse bit (junctions such as *My Music*: ntfs3 can spin on one;
  attributes from `system.ntfs_attrib`, `read_attributes`); overwrite a
  file (the same size and date within 2 s is skipped, a different file is
  copied as `NAME (from Windows).EXT`); unmount or lock what it didn't
  mount or unlock (markers in `$XDG_RUNTIME_DIR/flickos/switch/`).
- **Skipped:** hidden-and-system files and `SKIP_NAMES` (`desktop.ini`,
  `Thumbs.db`), shortcuts (`.lnk`, `.url`), and files only in OneDrive
  (`cloud_only`: the reparse bit with the recall-on-access or offline
  attribute, or no blocks on disk, over 4 KiB or all zeros, since NTFS keeps
  small files in its file table). They read as zeros under ntfs3, so they
  are listed with where to download them.
- **Before copying:** the free space; on FAT32 (`filesystem_type` from
  mountinfo) files over 4 GiB are refused. A file that fails is listed and
  the copy goes on; *Stop* (SIGTERM) ends it after the current file.
- **Bookmarks:** Chrome's, Edge's and Brave's (each profile) become
  `Bookmarks from Windows.html` in Documents, which Firefox imports.
- **Welcome's card** (flickos-welcome 1.8, `WHEN`) shows only when `find`
  lists something.
- **Translatable** like flickos-welcome (domain `flickos-switch`, `po/`).
- **A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`.
- **Unit tests** in `tests/`, on a fake C: in a temporary folder whose NTFS
  attributes come from a dictionary; the spike's `make-fake-windows.py`
  builds real fake disks to try the commands with (`udisksctl loop-setup`).

**Windows programs** (phase 2a): `identify FILE... [--json]`, `open FILE`
and `lookup WORDS... [--json]`, whose code is
`/usr/share/flickos/switch/programs.py`, loaded only for them
(`load_programs`, as flickos-menu loads `quick.py`), so the files window
doesn't compile it.

- **`identify`** reads a `.exe` (PE: bits, the version information's
  product, maker, description and original name, whether it is signed),
  an `.msi` (SummaryInformation: Subject and Author), an `.msix` or
  `.msixbundle` (`AppxManifest.xml`) or a `.lnk` (its target), never
  running anything. Files are downloads from strangers: every offset is
  checked against the file's size through `Reader`, which stops at
  `PE_BUDGET` (1 MB) or `MSI_BUDGET` (16 MB); a manifest with a document
  type is refused; anything broken is `unknown`. It seeks to a version
  block wherever it is (Discord's is 160 MB in).
- **The Windows apps list** `/usr/share/flickos/switch/apps.json` (161
  entries): `files` (shell patterns), `makers`, `products`, `words`, and
  what to offer: `linux` (an app in Software), `web`, `similar` (each with
  a `why`), `note`, `wine` (`maybe` or `no`); `group` entries are kinds of
  software ("antivirus software"). `match` takes the name with the maker,
  or the product with the maker for a renamed file; a name alone only when
  the file has no maker. `tools/check-switch-list.py` checks every app
  against Software's catalog and every address on the web; run it before
  merging a list change (the package build has no network).
- **`open`** is `flickos-switch-open.desktop` (`NoDisplay`), the default
  for the Windows types in flickos-settings' `mimeapps.list`. `answer`
  decides the rows: *Install* when the list has a Linux version, else the
  web version, similar apps and *Try with Wine*, or *Search Software* for
  an unknown program. *Try with Wine* runs `wine start /unix FILE` (or
  `wine msiexec /i`) when Wine and its 32-bit part (`/usr/lib/wine/wine`)
  are installed, else opens Software on `org.winehq.wine`. Each button
  starts its program detached and closes the window.
- **`lookup`** (phase 2c, for Software's search) lists the entries whose
  name, a product or one of the `words` is the search (case, spaces and
  dashes aside, so "photo" finds nothing and "photoshop" Photoshop), those
  found by name first; `--json` prints them with `by` (`name` or `words`)
  and their sentences translated.
- **Translations:** the list's sentences go into the template through
  `po/extract`, which `tools/update-po.sh` runs.

**Web apps** (phase 3a) are Firefox's Taskbar Tabs, which flickos-settings'
`flickos.js` turns on (`browser.taskbarTabs.enabled`). Only Firefox's own
button at the right of the address bar makes a good one (the site's name,
icon and start page) and only it removes one, so flickos-switch never
writes into Firefox's profile or launchers:

- **`webapp list [--json]`** reads, read only, `taskbartabs/taskbartabs.json`
  in each profile Firefox's installs use (`profiles.ini`'s `Install…`
  sections, else `Default=1`; under `~/.mozilla/firefox` and
  `$XDG_CONFIG_HOME/mozilla/firefox`). A list that is broken, over 1 MB or
  of a version past `TASKBAR_TABS_VERSION` gives none. `--json` gives each
  web app's `id`, `name`, `start`, `hosts`, `icon`, `launcher` (its desktop
  file ID, `null` when the file is gone), `profile` and `container`.
  `--known` (1.4, for Software) adds the Windows apps list's web versions
  (`https://` only, read from `apps.json` without `programs.py`): each is
  matched to the web app Firefox has for its host (`known_webapps`), and
  the rest follow with `id` null (`-` in the plain output). Every entry
  then also has `entry` (the list's ID or null), `windows` and `made`.
- **`webapp add URL [--name NAME]`** (`http`/`https` only) opens the address
  in an ordinary Firefox window and a notification (`notify-send`, else the
  same text on stdout) says which button keeps it as a web app. When
  Firefox already has a web app for the host, that web app is opened
  instead and its ID printed.
- **`webapp remove ID`** opens the web app (the command its launcher runs,
  `webapp_command`) and the notification says which button removes it.
- **The Windows program window's** web version row runs `webapp add` when
  `firefox-esr` is installed, else `xdg-open`.

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
  is retried the next day. Installing or upgrading the package never runs the
  count (`dh_installsystemd --no-start` for the service only); the timer is
  started again after an upgrade (since 1.5: `--no-start` on it too stopped it
  until the next boot).
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
  - `flickos-recovery-good.service` runs `start good-watch`: once the
    login screen (`greeter-window`, or its fallback `gtkgreet`) or `labwc`
    has been up `GOOD_SECONDS` (5), the count is 0 and the start counts as
    good (`GOOD_PROCESSES`; a login screen missing from it makes every start
    look failed).
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
Recent and Trash at the top of the right column, Settings, Software and the
power buttons at its bottom), Traditional's is
categories (GNOME 2/Whisker), Cupertino's a full-screen grid of app icons
(Launchpad), with the power buttons top right while Quick Settings is off.
A fourth, `prompt` (since 1.32, ADR-022), is FlickOS's own and no layout's
default yet: a search line with the logo's ›, the first six pins on Ctrl+1–6 (digits shown while Ctrl is held),
every app as icons A–Z (typing a category's name, such as `games`, lists
its apps), folder chips (one line, as
many as fit; every folder is also found by typing its name), and the
user, Settings, Software and power below. Its grid is `Size=` (default `6x4`)
and drops rows to fit the screen; apps with a window get a bar, from
flick-tiler's `open-apps` (1.12). It also gets the search bar's results
(since 1.32~test8, ADR-017 to ADR-020): a sum such as `15*3` shows its answer
(Enter copies it with `wl-copy`), desktop tasks (*Restart Panel*, *Shut
Down*…; those that end the session want a second Enter) come below the apps,
and a first `=`, `/` or `>` asks for a sum, files and folders by name
(`fdfind` in the home folder, a Depends) or a command run by the user's shell
in a new terminal. The rows come from data files in
`/usr/share/flickos/menu/providers/` (`tasks.json`, `files.json`), read by
`usr/share/flickos/menu/providers.py`, which the other styles never load. Only
FlickOS's packages may add one: a live provider sees all that is typed.
The prompt style teaches itself (since 1.32~test16, Phase 19): for its first
32 shows every other one has a tip in the empty line (counted in
`~/.local/state/flickos/menu-tips`, nothing written after that), and a click
on › or F1 lists what the line takes and the menu's keys.
It opens in the corner of the bar with the apps button (`Menu=`
`bottom-left` or `top-left`), or above the middle of a bottom bar whose
apps button is in the middle (`bottom-center`, since 1.22; Eleven's).
In Redmond and Traditional an arrow in the gap points at the logo on the
button (`MenuArrow=`, the third line of `menu/anchor`, since 1.30; ADR-021).
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

**The level ring** (since 1.26) shows the new level for a moment after a
volume, microphone or brightness key: flickos-settings' `level` script
changes it, then runs `/usr/libexec/flickos/osd`, which hands
`KIND PERCENT [muted]` to whoever listens on
`$XDG_RUNTIME_DIR/flickos/menu/osd`. The daemon listens while it runs and
loads `osd.py` at the first one (78–96 ms to show on the i3, +0.8 MB);
without the daemon the client starts `flickos-menu osd-popup` on a socket it
bound itself, which lingers `OSD_LINGER_SECONDS` (30) after the ring hid and
exits (a daemon that starts meanwhile takes the socket over). On by default
under HIG INT-9's exception for a tool that runs only when asked;
*Settings → Notifications* turns it off (flickos-control's `osd.enabled`,
read by the client at every press). Design:
[design/flickos-osd.md](design/flickos-osd.md).

| File in package | Installed to | Purpose |
|---|---|---|
| `usr/bin/flickos-menu` | `/usr/bin/` | One Python 3 file: `daemon`, `toggle`, `show`, `hide`, `super`, `quick`, `list`, `pinned`, `pin`, `unpin`, `bench`, `osd-popup` |
| `usr/share/flickos/menu/quick.py` | same | Quick Settings' code, which the daemon loads only while it is on (`load_quick`) |
| `usr/share/flickos/menu/osd.py` | same | The level ring (`Ring`), loaded at the first level (`load_osd`) |
| `usr/libexec/flickos/osd` | same | The ring's client (stdlib): reads the switch and the level, sends it, starts `osd-popup` when nobody listens. `desktop NUMBER COUNT` sends the desktop card (circles, one per desktop; flickos-layouts' `desktop show` runs it) |
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
- **Translatable** (1.23, [12 – Translating](12-translating.md)): one
  gettext domain, `flickos-menu`, for the menu, Quick Settings, the phone
  popup and the level ring's screen reader text (`po/POTFILES` lists all four
  files). `_` loads the translation at
  the first text shown, so a click (`toggle`, `super`) still imports
  nothing; `load_quick`/`load_phone` give those files the menu's `_`
  (loaded on their own, as in the tests, they show English). Section and
  category names stay English as keys (`list`) and are translated where
  they're shown.
- **Unit tests** in `tests/`, run at package build.

### `flickos-welcome`

The window a new account sees at login on an installed system
(`usr/bin/flickos-welcome`, one Python 3 file, GTK 3 through python3-gi, no
CSS; *Welcome* in the apps menu through `flickos-welcome.desktop`). Its cards
(`CARDS`) each run the program that owns the job: `flickos-switch files`,
`flickos-layout pick`, `flickos-control`, `nm-connection-editor`,
`flickos-shortcuts show`, `flickos-software`, and `xdg-open` for the
addresses in the conffile `/etc/xdg/flickos/welcome.conf` (`[Links]`; the site's
`/etc/xdg/flickos-site/flickos/welcome.conf` goes over it key by key). A card
whose program is missing, or whose address is empty, is left out. It owns no
settings.

- **Cards shown only when a check finds something** (1.8, `WHEN`): the
  check is a command that must exit 0 and print a non-empty JSON list. It
  runs in a thread after the window is shown, never before, and the card is
  inserted where `CARDS` puts it. *Bring files from Windows* uses
  `flickos-switch find --json`, so it shows only when a Windows partition
  is there. `list` runs the checks before printing.

- **When it opens:** flickos-settings' autostart runs `flickos-welcome
  first-run` when it is installed and `flickos-layout first-run` only
  otherwise, so exactly one window opens. `first-run` opens the window while
  the marker `~/.config/flickos/welcome` exists (copied from `/etc/skel`; a
  lintian override covers it) and deletes flickos-layouts' `choose-layout`
  marker, so the chooser it replaces can't open too. Ticking *Do not show on
  startup* deletes the marker and unticking writes it, both atomically
  (`flickos-welcome startup current|set on|off|default`). With `boot=live`,
  or `Enabled=no` in `welcome.conf` (off for the whole machine), the marker
  is deleted and nothing opens.
- **Donate:** `DEFAULT_LINKS` keeps `donate` empty, so no payment address is
  ever baked into the program. **`Donate=` in `welcome.conf` must stay the
  same address as the installer branding's `donateUrl`**; a unit test
  compares them.
- **Translatable** (1.7, the first package that was; HIG TXT-10,
  [12 – Translating](12-translating.md)): gettext domain `flickos-welcome`
  from `LOCALE_DIR`, `_()` and `N_()` (`CARDS`, `TITLE`; translated in
  `cards()`), named `.format` placeholders, `# Translators:` comments.
  `startup current`, `list`'s ids and stderr stay English. `po/` holds
  `POTFILES`, the `.pot`, `LINGUAS` and each `LANG.po`; `debian/rules`
  compiles every `.po` and the desktop file's `Name[LANG]`
  (`msgfmt --desktop`). `TranslationTest` fails while the `.pot` is stale
  (`msgcmp` both ways, with the same xgettext options as
  `tools/update-po.sh`).
- **A Depends of `flickos-desktop`** and in the sanity hook's `REQUIRED`.
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
  clicks, the floating panel for a layout that has one), *Displays* (the screens now, *Arrange Screens…* starts wdisplays through `displays arrange`, which moves a screen it turns on over another beside them,
  *Keep This Arrangement*, the kept arrangements; night light on or off and
  its warmth; shown while kanshi and wlr-randr are installed), *Mouse & Touchpad*, *Keyboard* (layout and
  variant, repeat, Num Lock, and the system layout), *Language & Region*
  (language and formats for the account, the system's through the helper's
  `locale`, which asks for the password; shown while the `locales`
  package is installed), *Default Applications* (browser, file
  manager, text editor, image and document viewer, media player through
  `xdg-mime default`; the terminal through `~/.config/xdg-terminals.list`),
  *Startup Applications* (XDG autostart entries on or off, *Add App…*,
  *Remove*), *Notifications* (Do Not Disturb, the level ring), *Media Controls* (flickos-media's `controls`, `spectrum`, `spectrum-shape`, `spectrum-layer` and `spectrum-colors`, while it is installed), *Power & Idle* (lock and sleep times; what the power button, closing the
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
  *Login Screen* (log in automatically, the login screen's language and
  keyboard layout with the same buttons as *Language & Region* and
  *Keyboard*, its background and where its box sits, a way to your picture
  on *Users*; only on installed systems with flickos-greeter; design
  `docs/design/flickos-greeter.md` ADR-013 to ADR-015), *Users* (your picture, add and remove accounts,
  administrator or not, set a password; installed systems only), *Firewall*
  (ufw on or off, and *Servers you run*: the ports of your own servers that
  home and office networks may reach, the system setting `firewall.local-ports`,
  1.71; shown while ufw is installed), *Tiling* (on/off, arrangement, main window width, gap, apps that
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
  *Classroom* (1.75; installed systems with flickos-classroom-view only:
  sharing this screen with a teacher, the paired teacher, pairing and
  forgetting through `flickos-classroom-view student …`, and *Let the
  teacher's computer through the firewall*, the system setting
  `firewall.classroom`: the helper's `firewall-classroom on|off`, the phones'
  way with `/etc/ufw/applications.d/flickos-classroom` and TCP 47100; and
  *This is a lab computer*, the system setting `classroom.lab`, which runs
  `pkexec flickos-classroom-view lab on|off` (the owner's own polkit action)),
  *History* (recent changes with *Undo*; see below) and
  *More Settings* (tiles that start Wallpaper, Appearance, Displays, Network,
  Sound, Bluetooth, Printers, Software Updates, Software and Tool Kits, whose *Show Paid
  Apps* is in its own menu and whose `paid` changes History shows and undoes
  with `flickos-software paid set`, 1.63; a tile is hidden when its app
  isn't installed), *Restore Points* (flickos-recovery's restore points with
  *Put Back…*, which shows `flickos-recovery plan` before the password; the
  switches are the system settings `restore-points` and `restore-points.auto`;
  a banner with *Keep…* and *Try Again* while running from a restore point;
  only on the btrfs layout, `recovery_available()` reads
  `/proc/self/mountinfo`), *Privacy* (the weekly
  count through `flickos-countme`, only while it is installed) and *About* (FlickOS version from `/usr/lib/flickos-release`,
  Debian, Linux, computer, processor, memory, graphics via `lspci`, disk,
  desktop; *Copy System Info* puts the same text plus the FlickOS packages'
  versions on the clipboard with `wl-copy`, *Save Report…* writes that text,
  `flickos-layout doctor` and the end of `panel.log` and `lock/lock.log` to a
  file the user chooses, without personal names (`docs/design/flickos-control.md`,
  Phase 4), and *Report a Problem* opens the GitHub issues; while
  flickos-fleet is installed, an *Organization* row: who manages the
  computer from `flickos-fleet status --json`, *What Is Sent* (its
  `PRIVACY.md`), *Join an Organization…* (the code is looked up with
  `flickos-fleet lookup` and the organization's name shown before `pkexec
  flickos-fleet join CODE --yes`) and *Leave…*).
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
  `/etc/xdg/flickos/input.conf` and `keyboard.conf`, all commented out; then the
  site's, `/etc/xdg/flickos-site/flickos/NAME.conf`, over them key by key and under
  the user's: `get` shows `site` as the source; `history.conf` too),
  writes `$XDG_RUNTIME_DIR/flickos/control/labwc.xml` and `environment`, and runs
  `flickos-layout reconfigure`. `get` lists them. `prepare` writes the two files
  at login (flickos-session runs it before `flickos-layout prepare`). labwc
  never resets an option that disappears from its config, so a value once set
  stays written, and `set KEY default` stores the default rather than
  removing it. Only keys labwc 0.8.3 parses are used; the tests hold its list.
- **Locking:** `flickos-control lock` execs `flickos-lock lock` (the
  background as `--image`/`--scaling`, and `--grace` from swayidle's idle
  timeout, `LOCK_SCREEN_IDLE`) while flickos-lock is installed and swaylock
  has no config of its own. Otherwise `swaylock -f -C
  $XDG_RUNTIME_DIR/flickos/style/swaylock` (`SWAYLOCK_STYLE`, flickos-layouts'
  config in the style's colors) with `SWAYLOCK_OPTIONS` (the ring shown before
  typing, failed attempts, Caps Lock on the ring); `swaylock -f -c 383c4a` (the
  Arc-Dark color) without that file or while swaylock has a config of the
  user's or the system's (`SWAYLOCK_CONFIGS`), which `-C` would hide. The
  background is the color (`lock.background` `color`) or, with `wallpaper`, adds the
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
- **Window shadows** (*Accessibility*, *Effects*; `windows.shadows`, in
  `~/.config/flickos/windows`): labwc's `<dropShadows>`, on in flickos-settings'
  `rc.xml`, so nothing is written until someone changes it; off is a `<theme>`
  option in `control/labwc.xml`, which flickos-layout merges (1.80). The sizes
  and colors are each window theme's.
- **Animations** (*Accessibility*, *Effects*; `flickos-control animations
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
- **The level ring** (`osd.enabled`, on, `~/.config/flickos/osd`, conffile
  `osd.conf`, 1.57; *Show the level* on the Notifications page): whether
  flickos-menu's ring shows after the volume, microphone and brightness keys.
  `set` changes only the file: flickos-menu's client reads `[Osd] Enabled=`
  at every press ([design](design/flickos-osd.md)).
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
  Debian's own plus FlickOS's repo, its community apps and the apps bought
  from its store (the default, from flickos-archive-keyring's
  `51flickos-origins`; the store's origin matches nothing without a key),
  `all` = also
  `trixie-updates`, `debian-only` = Debian's own alone (an older helper's
  `debian`; shown, never offered), else `custom`; the lists from before the
  community repository and before the store, `PREVIOUS_UPDATE_SCOPES`, show
  as the choice they were, and the postinst's `control-helper updates refresh` writes a stored
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
  while the account has processes running, and deletes the account's picture
  (userdel leaves it, and a new account of that name would show it).
  `user-admin NAME yes|no` changes
  membership in `sudo` (polkit's and sudo's administrators on Debian).
- **Your picture** (`picture current`, `picture set FILE|default`, *Choose
  Picture…* and *Remove Picture* on *Users*): accountsservice owns it.
  `write_picture` turns the file into a PNG, cropped to the middle square, of
  at most `PICTURE_PIXELS` (288: flickos-greeter's 96 px at 300%), turned as its
  EXIF says, because accountsservice refuses a file over 1 MB; `SetIconFile` on
  the user's own object needs no password and copies it to
  `/var/lib/AccountsService/icons/USER`. Each user sets their own, so no helper
  verb. flickos-greeter, flickos-lock and flickos-menu read that file; the last
  two fall back on `~/.face`. History shows the change (`picture`) but can't
  undo it: the old picture isn't kept.
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
- **Support for 32-bit programs** (1.58, the system setting `i386`, no page:
  Software turns it on with Wine and off when Wine goes, through `flickos-control
  system i386 on|off`, so History records it): the helper's `i386-on` runs
  `dpkg --add-architecture i386`, `i386-off` refuses while an i386 package
  someone asked for is installed (apt's manual mark), purges the i386
  libraries left behind (apt never autoremoves the protected `libgcc-s1` or
  what it needs) when apt would remove nothing else with them, and the ones
  only config files are left of, then runs `dpkg --remove-architecture i386` (actions
  `org.flickos.control.i386-on`/`-off`). Read with `dpkg
  --print-foreign-architectures`.
- **The power button and the lid** go through the same helper: `power
  power-key|lid|lid-external-power poweroff|suspend|lock|ignore|default`
  rewrites `/etc/systemd/logind.conf.d/60-flickos.conf` and runs `systemctl
  reload systemd-logind` (action `org.flickos.control.power`). **Adding a
  language:** `locale-add LOCALE` (a UTF-8 locale of
  `/usr/share/i18n/SUPPORTED`) turns its `/etc/locale.gen` line on and runs
  `locale-gen --keep-existing` (action `org.flickos.control.locale-add`).
  **The system language:** `locale NAME=VALUE...` (`LANG` required, the
  other `LC_*` and `LANGUAGE` at most once, each a locale of `SUPPORTED`,
  `C`, `C.UTF-8` or `POSIX`) writes `/etc/locale.conf`, which
  `/etc/default/locale` links to in trixie, and that file too where it is
  one of its own (action `org.flickos.control.locale`). Debian's systemd
  refuses localed's `SetLocale` to everyone
  (`systemd-localed-read-only.conf`), so `localectl set-locale` fails with
  "Access denied" before polkit asks anything.
  **Automatic updates:** `updates auto yes|no`, `scope
  security|debian|all`, `reboot no|idle` (each also `default`) keeps the
  choices in `/etc/apt/apt.conf.d/60flickos-updates` (after Debian's files;
  `#clear` replaces the origins; action `org.flickos.control.updates`).
  **Makers' repositories** (1.84, Tool Kits' newer versions;
  [design/flickos-dev.md](design/flickos-dev.md) ADR-008, Q8 and Q9):
  `system upstream.mise|upstream.rapid7 on|off` runs the helper's `upstream
  ID on|off` (action `org.flickos.control.upstream`; History labels in
  `SYSTEM_LABELS`, not in fleet's keys). `UPSTREAMS` in the helper is the
  only list (id, address, suite, the key's fingerprint, the packages it may
  give, its update origin); an argument only names an entry. The makers' keys
  are shipped in `/usr/share/flickos-control/upstreams/ID.asc` (fingerprints
  checked against mise's install page and the key inside Rapid7's own
  installer, and again before each use: `openpgp_fingerprint`, a test too;
  mise's key runs out on 2028-01-02, Rapid7's on 2030-01-11, so a renewed one
  comes with a flickos-control update). `on` writes
  `/etc/apt/sources.list.d/flickos-upstream-ID.sources` (`Signed-By` the
  shipped key), `/etc/apt/preferences.d/flickos-upstream-ID` (the origin at
  −1, its packages at 500) and `/etc/apt/apt.conf.d/52flickos-upstream-ID`
  (its origin for unattended-upgrades; 60flickos-updates' list gets it too,
  except *Security fixes only*, and the Updates page leaves it out when
  naming the scope), fetches that one repository's lists, simulates the
  install and refuses it if anything would be removed, then installs; a
  failure deletes what it wrote. `off` removes the package (refused if apt
  would remove more) and the files. Neither package is in Debian, so there
  is no downgrade (an entry with a package of Debian's name would need one,
  ADR-008). The postinst's `upstream refresh` writes the files of the entries
  that are on from the new version's list.
- **Purchased apps** (since 1.64; [design/flickos-store.md](design/flickos-store.md),
  ADR-004): the key of apps bought from the FlickOS store, the password of
  apt's login for the store's repository. `flickos-control purchases
  list|add [--stdin]|remove|claim --stdin` and the *Purchased apps* row of
  the Updates page (*Add Key…*, *Remove*; it names no app). The key goes to
  the helper on standard input, never in arguments or files of the user's;
  `add` checks its format first, so a typo asks for no password. The
  helper's `purchases-add` (action `org.flickos.control.purchases-add`) asks
  the store's `/v1/key` what the key holds, or `/v1/link` to add it to the
  key already on the computer (a turned-off one is replaced), then writes
  `/etc/apt/auth.conf.d/flickos-store.conf` (root 0600),
  `/etc/apt/sources.list.d/flickos-store.sources` (`FLICKOS_DEBIAN-store`,
  FlickOS's key), `/var/lib/flickos-control/purchases.json` (0644: the
  key's last four characters, `valid` or `revoked`, products, packages, when
  checked; what `list` and Software read), updates only the store's list and
  writes the pins. `purchases-remove` deletes the four files and the pins.
  **The purchases check** (`purchases-check`): apt runs it as root after
  every update (`/etc/apt/apt.conf.d/61flickos-purchases`, a conffile; only
  while the login file exists), it asks `/v1/key` at most every 20 hours
  (`--now` at once) and writes `/etc/apt/preferences.d/flickos-store`, a
  `Pin-Priority: -1` for every package in the store's lists the key doesn't
  hold, so one refunded app never makes unattended-upgrades abort its run
  (tried in a container: it does without the pins). A `401` pins them all
  and prints a notice; `notifications` (autostart) shows it once per key
  with notify-send. `claim --stdin` is Software's Buy… (its ADR-011): it
  asks `/v1/claim` every 3 s for up to an hour, then adds the key; if the
  helper refuses, it prints the key, which the store hands out only once.
  `STORE_URL` (`https://store.flickos.org`) is in both programs.
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
  - **The key for bought apps** is recorded as `purchases` (the key's last
    four characters or `none`, never the key); only adding has Undo
    (`purchases remove`), since a removed key isn't kept.
  - **System settings** (power button and lid, firewall, automatic login,
    automatic updates, time zone, network time, the login screen's keyboard
    layout, background and box position; the kits' ports, container DHCP,
    packet capture and wireless test adapter, set in Tool Kits) change through `flickos-control system KEY [VALUE]`, which the
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
  (the text *Copy System Info* copies), `flickos-control report` prints what
  *Save Report…* saves, `flickos-control system KEY [VALUE]`
  and `default-app list|set` print and change system settings and default
  applications.
- **Translatable** (1.65, [12 – Translating](12-translating.md)): gettext
  domain `flickos-control` from `LOCALE_DIR`; `po/` has the template (about
  800 texts) and no language yet. The tables (`PAGES`, `TILES`,
  `HISTORY_LABELS`, `SYSTEM_LABELS`, `CHOICE_NAMES`, …) are translated where
  they are defined, when the program starts: no process of it shows text for
  longer than a language lasts. Search looks in the English and the
  translated `SEARCH_KEYWORDS` (`search_words()`). History's descriptions are
  whole patterns (`"{setting}: {value}"`, `"Was {value}"`), so `history`
  prints them translated too; the messages the pages show from the commands
  they run (`set`'s notes, errors) are translated, while what scripts, the
  boot test and bug reports read stays English: tab-separated output, ids,
  `Applied.`, `Kept: `, `about`, `report` and About's labels in them (`N_`,
  translated only on the page). Names of languages and countries come from
  iso-codes' translations, of keyboard layouts from xkeyboard-config's
  (`other_gettext()`). A broken `.mo` gives English, never a failed
  `prepare` at login. Not translated yet: the polkit messages, and text that
  other programs give (layout and style names, the shortcut sheet).
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
- **Hooks** ([flickos-hooks](#flickos-hooks)): the swayidle `idle` starts also
  has `after-resume WOKE_COMMAND`, which runs the user's `woke` hooks. It is
  a shell test of `~/.config/flickos/hooks/woke.d` and `setsid -f`, because
  `swayidle -w` waits for every command, idle locking included.

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
  `/var/lib/flatpak/appstream/flathub`). The apt catalogs are four sources,
  told apart by their origin (`APT_ORIGINS`; FlickOS's repository writes its
  catalogs with `repo/conf/dep11.py`): Debian, the FlickOS Store
  (`trixie-store`, since 1.16), FlickOS (`trixie`) and FlickOS Community
  (`trixie-community`, apps other developers publish, which FlickOS builds
  from their public source and reviews; the page says so). An app in
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
  by the command itself. FlickOS's styles and apps (a package of an app in
  the catalog, such as Notes; since 1.14) can be removed unless
  flickos-desktop Depends on them.
- **Files from outside** (1.19; [design](design/flickos-software.md) ADR-012):
  a double-click on a `.deb`, `.flatpak`, `.flatpakref` or `.flatpakrepo`
  runs `flickos-software open %F` (`flickos-software-open.desktop`, hidden
  from the menus; flickos-settings' `mimeapps.list` makes it the default for
  the four types, ahead of xarchiver). The window shows one page for all the
  files with what each is and needs, what a Flatpak may reach, and *Install*;
  the children are `plan --file` and `install --file` (repeat `--file`; one
  JSON `item` line per file). A start while the window is open writes the
  paths as small files in `$XDG_RUNTIME_DIR/flickos/software/open/`, which
  the window watches (`spool_files`/`take_spool`). Reading a file runs
  nothing from it: `dpkg-deb -f`, libflatpak's `BundleRef`, plain text.
  `.deb` files install in one PackageKit transaction (`install_files`, its
  untrusted-file action asks for the password every time); Flatpak files in
  one libflatpak transaction (a bundle is polkit's `install-bundle`, which
  asks for the password; a ref from a remote doesn't). A ref whose `Url` is
  Flathub's installs from the system's `flathub` remote and its own key is
  ignored; any other source needs an https address and a signing key, and a
  `.flatpakrepo` only adds the source. A bundle isn't planned as a
  transaction (libflatpak configures its remote, and would ask for the
  password, before it stops): only its runtime is.
- **Apps with a part of another architecture** (1.10, `OTHER_ARCH`;
  [design/flickos-switch.md](design/flickos-switch.md) ADR-004): Debian's Wine
  is installed as `wine`, `wine64` and `wine32:i386` in one transaction, after
  `flickos-control system i386 on` (its own password prompt) and a refresh
  that fetches i386's lists. All three are named: with `wine32` in the
  transaction apt meets `wine`'s "wine64 | wine32" with `wine32` alone. The
  plan shows the 32-bit part's size before i386's lists are there (a measured
  figure). A Wine installed without its 32-bit part gets *Add 32-bit Support*.
  Removing Wine removes all three, then turns i386 off when no i386 package
  someone asked for is left (a second prompt).
- **Windows programs in the search** (1.11,
  [design/flickos-switch.md](design/flickos-switch.md) phase 2c): each search
  runs `flickos-switch lookup --json` in a `Gio.Subprocess` (the previous one
  stopped, given up after `LOOKUP_MS`), and `windows_answer` turns its entries
  into one answer above the results: "Adobe Photoshop is a Windows program
  and isn't made for FlickOS." with the similar apps and the web version.
  Matches by the list's words count only when there are at most
  `WORD_MATCHES` ("excel", not "music"). Nothing when flickos-switch is
  missing; Software doesn't depend on it.
- **Web apps** (1.12, [design/flickos-switch.md](design/flickos-switch.md)
  phase 3b): the window runs `flickos-switch webapp list --json --known` in a
  `Gio.Subprocess` at its start and each time it becomes active (no timer),
  and `web_rows` turns the answer into rows that `Catalog.set_web` puts after
  the index's apps, so search, *Installed* and the categories show them. Their
  source is `WEB`, not in `SOURCES`: the index and the commands never have
  web apps. A row is `web:ENTRY` for a list's web version (the same page
  before and after it is made) or `web:ID` for one made from any address;
  its icon is Firefox's file once made, `web-browser` before. Explore's *Web
  Apps* category has *New Web App…* (an address, `https://` added when none
  is typed). A web app's page has no plan: *Install* runs `webapp add`,
  *Remove* `webapp remove`, both open the page in Firefox, whose address-bar
  button does it; *Open* runs its launcher. A Windows program's answer offers
  the web version's page. Nothing about web apps while `firefox-esr` or
  flickos-switch is missing.
- **Icons and screenshots:** the theme's icon by name, then the catalog's
  file, then a download kept in `~/.cache/flickos/software/images/`.
  `/etc/apt/apt.conf.d/50flickos-software` turns on Debian's 64 px icon
  tarball (the `DEP-11-icons` target), because trixie's catalog names icon
  and screenshot addresses that appstream.debian.org no longer serves; an
  app also on Flathub shows Flathub's screenshots.
- **Flatpak updates:** `flickos-software-update.timer` (daily, enabled, never
  in the live session; started again after an upgrade of the package since
  1.22, the service itself never started by it) runs `/usr/libexec/flickos/software-update`, which
  follows apt's own settings: Flathub's catalog with
  `APT::Periodic::Update-Package-Lists` (only once something fetched it), the
  apps with `APT::Periodic::Unattended-Upgrade`. So *Settings → Updates*
  turns it on and off with the rest.
- **Kits** (1.20, [design/flickos-dev.md](design/flickos-dev.md) phase 1):
  an apt package `flickos-kit-NAME` whose metainfo is an add-on extending
  `flickos-kits.desktop` with `FlickOS::kit` and `FlickOS::kit-category` is a
  kit (`kit_of`; FlickOS's own sources only): it shows only under *Developer
  Tools* (the category `X-FlickOS-Development`, given by Software) and on the
  *Tools for developers* shelf, with no *Open*, and can be removed
  (`KIT_PREFIX`). Removing one of a kit's members removes the kit and the plan
  lists that. *Set Up…* opens the Tool Kits window on an installed kit's row.
  Security kits (1.24, [design/flickos-security.md](design/flickos-security.md)
  phase 1; `FlickOS::kit-category` `security`) show only under *Security
  Tools* (`X-FlickOS-Security`), which has no shelf (ADR-S01) and says
  `PERMISSION` (ADR-S05) under its title (`CATEGORY_NOTES`); each security
  kit's page says it above the description (`kit_note`), and `info` prints it
  as `note`. `INDEX_VERSION` 7 makes an index of 6, which left them out, be
  rebuilt.
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
- **Paid apps** (1.13, design phase 3a): `featured.json` may give an app a
  price, `"paid": {ID: {"price": "$12", "buy": "https://…", "product":
  "notes"}}` (`parse_paid` leaves out an entry without a price, with a buy
  address that isn't `https://` or with an odd product). `Catalog.set_paid`
  puts them on the apps when the window loads (not in the index, so a new
  price needs only the Worker's deploy). Rows say *Paid · price*; the page
  has *Buy…*, which opens the `buy` address in the browser, a line saying
  what it does and a *Price* row. An app with `product` (FlickOS's store's)
  offers Buy… in place of Install until it is bought (`Catalog.bought`,
  filled by step 3c); one without it (another developer's) is a free
  download whose key the developer sells: Install and Buy…. The package's
  copy has no prices, so nothing shows until a deploy adds one.
- **The store's catalog** (1.16, design step 3b): the store repository's
  DEP-11 file, which the store's Worker serves without a key at
  `/v1/catalog/FLICKOS_DEBIAN/Components-amd64.yml.gz` (`STORE_CATALOG_URL`;
  the release from `/usr/lib/flickos-release`). `fetch_shop` fetches it with
  `featured.json`, at most every `FEATURED_HOURS`, into
  `~/.cache/flickos/software/store-catalog.yml.gz` (only a gzipped DEP-11
  file with a store's origin; rewritten only when it changed, since its time
  is the index's stamp, and `store-catalog.checked` says when it was asked).
  `index` reads it with libappstream after the system pool, so once a key
  brings the same catalog through apt (flickos-control `purchases`), the
  pool's copy wins. A store app shows only while `featured.json` prices it
  (`Catalog.sources`, `hidden`). Sold over its last free version (Notes in
  FlickOS's repository): one app, named and described by the store; not
  installed, the store only and Buy… (Q12); the free version installed, the
  store's page with Open, Remove and Buy… for the newer one. An installed
  package counts as the store's only once the key holds its product
  (`Catalog.bought`, step 3c). `install` refuses a store app that isn't
  bought. The live Worker answers `503` there until the store opens, so
  nothing shows meanwhile.
- **Bought apps** (1.17, design step 3c): what the key bought is
  flickos-control's `/var/lib/flickos-control/purchases.json`
  (`read_purchases`: the products while `valid`, or a key turned off), read
  with what is installed, and again whenever the window gets the focus back
  (`installed_changed` redraws only on a change). A bought app installs from
  the store; the page says *Bought (price)*, rows *Bought*. For a store app
  not bought, **Buy…** makes a claim code (`secrets.token_urlsafe(24)`), opens
  the buy address with `#claim=CODE` and runs `flickos-control purchases
  claim --stdin` (the code on stdin): the page waits (*Waiting for your
  payment…*, Cancel), the password is asked when the key comes, then the
  index and purchases are read again. **Add Key…** (not in the live session,
  where the page says to add it after installing) runs `flickos-control
  purchases add --stdin`. Closing the window while waiting asks first.
  Software never sees or keeps a key. The test buy page leaves a claim from
  Software alone (the store hands a key out once).
- **Its one setting** (ADR-007): `flickos-software paid current|set
  on|off|default`, `Paid=` in `[Software]` of the conffile
  `/etc/xdg/flickos/software.conf` (on), then
  `~/.config/flickos/software`. Off hides apps with a price that aren't
  installed or bought from the search, the categories and the shelves
  (`Catalog.hidden`). The window's menu button has *Show Paid Apps*; a
  change is recorded in History (owner `flickos-software`, key `paid`),
  which flickos-control shows and undoes, and the window reads the setting
  again when it becomes active.
- Command line: `search WORDS`, `list [--installed|--category ID|--shelves]`,
  `info ID` (with `price`, `buy` and `product` for a paid app), `plan|install|remove
  [--source debian|flickos|community|flathub] ID`, `paid current|set
  on|off|default`. It sends nothing about its user.

### `flickos-style-seven`

**Seven**, FlickOS's own extra style: Arc's light windows with the Numix
icons, see-through sky blue title bars and frames (its own labwc theme
`Seven`, with glassy SVG buttons), a see-through dark blue panel
(`wm_bg` `rgba(14, 42, 76, 0.82)`), a black terminal, a light launcher and
notifications, and a sky wallpaper with the halo. Since 1.2 it brings a
layout **seven**: Redmond's arrangement in a glass look, one 40 px
see-through panel at the bottom with a round glossy start button in the
accent color (the halo in it, kept amber on hover), large window icons
(28 px, icons only like Redmond's) in glass boxes, the active one brighter
and a blue glow under the pointer, the status, the two-line clock and a
wider Show Desktop strip. Its CSS uses named colors only and never draws the
bar lighter than base.css (the glass only darkens towards the bottom); no
pinned apps, since in waybar an open pinned app would show twice. Design,
the spike and the naming rule (an allusion, like Redmond and Cupertino; no
other system's names or assets): ADR-013 (amended for the layout) and
sections 11–12 of [design/flickos-ricing.md](design/flickos-ricing.md).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-seven`. It
  then lists after Dark and Light; Software's *Use* sets the style and the
  layout together (`FlickOS::layout`). Depends flickos-layouts (>= 1.53),
  arc-theme and numix-icon-theme, which every FlickOS system has, so it
  adds only its own 300 KB.
- **Files:** `usr/share/flickos/styles/seven/` (style.ini, the four
  palettes, wallpaper.png, linked as `/usr/share/backgrounds/flickos/flickos-seven.png`
  for waypaper), `usr/share/themes/Seven/labwc/` (themerc and the buttons),
  `usr/share/flickos/layouts/seven/` (layout.ini, waybar.jsonc, style.css,
  preview.png),
  `usr/share/metainfo/io.github.dvbondoy.flickos.styles.Seven.metainfo.xml`
  (the add-on Software reads; keep its ID, Software knows the style by it).
- **Generated:** `tools/make-seven.py` writes the style, the window theme
  and its buttons, the wallpaper and the layout's preview (SVGs in
  `artwork/`); the layout's three config files and the metainfo are written
  by hand. Run it after a change, then bump the version.
  `tools/check-palette.py` checks the colors and the layout's CSS against
  `ALLOWED_SEVEN`.
- **Tests:** the metainfo's add-on form (style and layout), every button in
  every state, no other system's trademarks, the layout (bottom bar, classic
  menu, two-line clock, icon-only window list without pins, named colors
  only, the bar never lighter than `check` tests it), and (in the source
  tree) `flickos-layout check seven`, `check --layout seven` and the
  themerc's keys against FlickOS-Arc's.
- **Screenshots:** Software shows two, named in the metainfo:
  `https://dvbondoy.github.io/flickos-apt/screenshots/seven/1.png` (Thunar
  and a terminal) and `2.png` (the start menu), 1366x768, from
  `repo/screenshots/seven/`, which `repo/upload.sh` publishes. After a
  change to the style or its layout, `tools/make-style-shots.sh seven`
  takes them again in a sealed-off headless FlickOS session (the working
  tree's style, a stand-in account, only the ISO's apps); Software keeps a
  downloaded one for 30 days. Every style package has its two the same way.
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
- **Screenshots:** two, as Seven's (`repo/screenshots/aye3/`).

### `flickos-style-footprint`

**Footprint**, FlickOS's third extra style, with a layout that has a dock:
GTK's Adwaita-dark windows with the Adwaita icons, grey title bars with the
title in the middle and round buttons that light on hover (its own labwc
theme `Footprint`, with SVG buttons), a black top bar, the accent `#3584e4`
(Adwaita-dark's own `#15539e` is only 2.8:1 on black), a dark grey terminal
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
The bar and the dock each have a 1 px line (the text color at 18 %) on the
edge toward the windows, so a dark window doesn't run into them. *Show Apps*
takes only its own button's clicks: sfwbar wraps each widget in an event box,
and a `vexpand` on the button stretched that box over the dock's whole bottom
half, so `dock.css` aligns the box with structural selectors instead (found
in 1.7; sfwbar names neither the sections nor the box).
*Show Apps* is the first section of `dock.config`, before the `bar` that sets
`mirror = "*"`: sfwbar copies a bar to the other screens when it reads that
line, so a section declared after it never reached a second monitor (found
in 1.8; a test keeps the order).
Right-clicking an app in the dock opens *Pin to Dock* or *Unpin from Dock*
(1.9): two `menu` sections in `dock.config` and `action[RightClick] =
Menu(If(WindowInfo("pinned"), "dock_unpin", "dock_pin"))` on the taskbar
(sfwbar +flickos9), each item running `flickos-layout pinned add|remove` with
the clicked app's app id. It saves the same list as Settings' *Pinned Apps*
(so History and Settings follow), and flickos-layout then makes the dock read
its config again (SIGHUP). It works for an app that is only pinned, one with
a window and one with several.
The start menu is the full-screen grid, at the top left. Design: ADR-016 and
phase 8 of [design/flickos-ricing.md](design/flickos-ricing.md); named by
allusion (ADR-013).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-footprint`.
  Software's *Use* sets the style and the layout together. Depends
  flickos-layouts (>= 1.86: the dock's `Exec("flickos/launcher")`, and
  `pinned` taking an app id), sfwbar
  (>= +flickos9: a full-length dock fits below the top bar, and the
  right-click menu),
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
- **Screenshots:** two, as Seven's (`repo/screenshots/footprint/`).

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
- **Screenshots:** two, as Seven's (`repo/screenshots/elemental/`).

### `flickos-style-experience`

**Experience**, FlickOS's fifth extra style, with its own layout, in the
colors of the early 2000s: deep blue title bars with a blue frame, the title
on the left and glossy rounded buttons with a white edge and a red close
(its own labwc theme `Experience`, with SVG buttons; faded on other windows),
Debian's Greybird windows with the Tango icons, a black console in the VGA
colors, a white launcher, pale yellow notifications, and a green hill under a
blue sky with the halo. Its layout **experience** is one 30 px blue panel at
the bottom: the apps button as a green Start button (the halo and "Start" in
bold italics, a round end), the window list as raised buttons (icons only,
as Redmond's: waybar 0.12 doesn't shorten titles), and the notification
area (tray, status, recording, clock, Show Desktop) on a lighter blue. The
title bar keeps labwc's own order (icon on the left; minimize, maximize,
close on the right), so the layout has no `TitlebarLayout=`. Its CSS uses
named colors only: the green is the style's `selected_bg_color` and the
notification area its `base_color`, so the layout follows any style. Design:
ADR-018 and phase 10 of [design/flickos-ricing.md](design/flickos-ricing.md);
named by allusion (ADR-013).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-experience`.
  Software's *Use* sets the style and the layout together. Depends
  flickos-layouts (>= 1.53), greybird-gtk-theme (5.4 MB) and
  tango-icon-theme (11.6 MB).
- **Files:** `usr/share/flickos/styles/experience/` (style.ini, the four
  palettes, wallpaper.png, linked as
  `/usr/share/backgrounds/flickos/flickos-experience.png`),
  `usr/share/flickos/layouts/experience/` (layout.ini, waybar.jsonc,
  style.css, preview.png), `usr/share/themes/Experience/labwc/` (themerc and
  32 button SVGs),
  `usr/share/metainfo/io.github.dvbondoy.flickos.styles.Experience.metainfo.xml`
  (keep its ID).
- **Generated:** `tools/make-experience.py` writes the style, the window
  theme and its buttons, the wallpaper and the layout's preview (SVGs in
  `artwork/`); the layout's three config files and the metainfo are written
  by hand. `tools/check-palette.py` checks the colors and the layout's CSS
  against `ALLOWED_EXPERIENCE`.
- **Tests:** the metainfo, no name of the system it recalls, every button in
  every state, titles on the left, the bottom bar with "Start", its clock and
  an icon-only window list, the CSS in named colors only, and (in the source
  tree) `flickos-layout check experience` and `check --layout experience`
  with stand-ins for the GTK and icon themes.
- **Screenshots:** two, as Seven's (`repo/screenshots/experience/`).

### `flickos-style-eleven`

**Eleven**, FlickOS's sixth extra style, with its own layout, dark in the
spirit of a well-known desktop of 2021: one dark grey for every title bar,
with dimmer text on other windows, a thin grey frame, the title on the left
and wide flat buttons in thin lines up to the window's corner, close turning
red under the pointer (its own labwc theme `Eleven`, with 46×32 SVG
buttons), GTK's Adwaita-dark windows with the Adwaita icons, a sky blue
accent, dark grey menus, launcher and notifications, a near-black console,
and folds of blue light on a deep blue with the halo. Its layout **eleven**
is one 48 px see-through dark panel at the bottom: in the middle the apps
button (the halo alone, larger) and the window list (24 px icons, a short
line under each and a longer blue one under the focused window; icons only,
as Redmond's), at the right the tray, status, recording, a two-line clock
(time over the locale's short date) and Show Desktop, in Open Sans; at the
left end the weather while it is on (`flickos/weather`, two lines; 1.2). The
start menu opens above the middle of the panel (`Menu=bottom-center`,
flickos-layouts 1.67, flickos-menu 1.22). The title bar keeps labwc's own
order, so the layout has no `TitlebarLayout=`. Its CSS uses named colors
only (the blue line is the style's `selected_bg_color`, lightened), so the
layout follows any style. Design: ADR-019 and phase 11 of
[design/flickos-ricing.md](design/flickos-ricing.md); named by allusion
(ADR-013).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-eleven`.
  Software's *Use* sets the style and the layout together. Depends
  flickos-layouts (>= 1.68), flickos-menu (>= 1.22),
  gnome-themes-extra-data, adwaita-icon-theme, adwaita-icon-theme-legacy
  (all already on FlickOS) and fonts-open-sans (2.8 MB).
- **Files:** `usr/share/flickos/styles/eleven/` (style.ini, the four
  palettes, wallpaper.png, linked as
  `/usr/share/backgrounds/flickos/flickos-eleven.png`),
  `usr/share/flickos/layouts/eleven/` (layout.ini, waybar.jsonc,
  style.css, preview.png), `usr/share/themes/Eleven/labwc/` (themerc and
  32 button SVGs),
  `usr/share/metainfo/io.github.dvbondoy.flickos.styles.Eleven.metainfo.xml`
  (keep its ID).
- **Generated:** `tools/make-eleven.py` writes the style, the window theme
  and its buttons, the wallpaper and the layout's preview (SVGs in
  `artwork/`); the layout's three config files and the metainfo are written
  by hand. `tools/check-palette.py` checks the colors and the layout's CSS
  against `ALLOWED_ELEVEN`.
- **Tests:** the metainfo, no name of the system it recalls, every button in
  every state at the button's size, titles on the left, the bottom bar with
  the apps button and the window list in the middle, `Menu=bottom-center`,
  its clock and an icon-only window list, the CSS in named colors only, and
  (in the source tree) `flickos-layout check eleven` and `check --layout
  eleven` with stand-ins for the GTK and icon themes.
- **Screenshots:** two, as Seven's (`repo/screenshots/eleven/`).

### `flickos-style-tortuga`

**Tortuga**, FlickOS's seventh extra style, with its own layout, named after
the island and recalling no other desktop: one slate for every title bar, with
dimmer text on other windows, a thin frame, the title in the middle and thin
glyphs that get a round face under the pointer, close's red (its own labwc
theme `Tortuga`, with 30×28 SVG buttons), GTK's Arc-Dark windows with the
Numix-Circle icons as in the Dark style, a lantern copper accent with dark text
on it, slate menus, launcher and notifications, a deep slate console, and an
island harbour at dusk with lanterns along the quay. Its layout **tortuga** is
one 40 px bar at the top drawn as three islands (the apps button and the
weather while it is on, the clock and the recording, the status) and a dock
at the bottom: the apps, and beside them the 4 desktops as a 2×2 grid, an
sfwbar `pager` with `cols = 2` and `primary_axis = rows` (without it sfwbar
reads 1 3 over 2 4). The islands are the floating panel
([design](design/flickos-floating-panel.md)), on by default in this layout
only (`FloatingDefault=on`, flickos-layouts 1.82): while a window fills the
screen they join into one panel, and the dock hides as Cupertino's does. With
the floating panel off the layout is one plain bar. Its CSS uses named colors
only, so the layout follows any style. Design: ADR-020 and phase 12 of
[design/flickos-ricing.md](design/flickos-ricing.md).

- **Opt-in:** not in the ISO and not in flickos-desktop; installed from
  Software (*Styles*) or with `sudo apt install flickos-style-tortuga`.
  Software's *Use* sets the style and the layout together. Depends
  flickos-layouts (>= 1.82), flick-tiler (>= 1.11), sfwbar (+flickos7),
  arc-theme and numix-icon-theme-circle, all already on FlickOS.
- **Files:** `usr/share/flickos/styles/tortuga/` (style.ini, the four
  palettes, wallpaper.png, linked as
  `/usr/share/backgrounds/flickos/flickos-tortuga.png`),
  `usr/share/flickos/layouts/tortuga/` (layout.ini, waybar.jsonc, style.css,
  floating.css, floating-full.css, dock.config, dock.css, preview.png),
  `usr/share/themes/Tortuga/labwc/` (themerc and 32 button SVGs),
  `usr/share/metainfo/io.github.dvbondoy.flickos.styles.Tortuga.metainfo.xml`
  (keep its ID).
- **Generated:** `tools/make-tortuga.py` writes the style, the window theme
  and its buttons, the wallpaper (from a fixed seed) and the layout's preview
  (SVGs in `artwork/`); the layout's files and the metainfo are written by
  hand. `tools/check-palette.py` checks the colors and the layout's CSS
  against `ALLOWED_TORTUGA`.
- **Tests:** the metainfo, nothing from the films or about piracy, the brand
  amber only as `brand_color`, every button in every state at the button's
  size, titles in the middle, the bar's size, islands at least 80 % solid, the
  desktops read by rows, the dock giving way to a full window, the CSS in named
  colors only, and (in the source tree) `flickos-layout check tortuga` and
  `check --layout tortuga` with stand-ins for the GTK and icon themes.
- **Screenshots:** two, as Seven's (`repo/screenshots/tortuga/`).

### `flickos-kits`

The Tool Kits window ([design/flickos-dev.md](design/flickos-dev.md), ADR-002 and
phase 2): one stdlib Python file, GTK only for the window, with a gettext
domain of its own (`po/`). It lists the kits (`KITS`: the same words as each
kit's metainfo, a test compares) with a switch each. A switch shows the plan
from `flickos-software plan --json` in a dialog (Cancel and a verb; removing
also says what else goes), then runs `flickos-software install|remove --json`,
so there is one installing path (PackageKit, its password, History's apt
hook). The security kits (1.4, [design/flickos-security.md](design/flickos-security.md)
phase 2) are a list of their own, *Security work*, under the permission
sentence (`PERMISSION`, the same words as Software's: a test compares), folded
(`FOLDED`) until one of them is installed or the window opens on one; once
opened or closed it stays so until the window closes. Under *Set up*, once any kit is installed and only when the step's program
is on the computer (`STEPS`): git's name and email (`git config --global`),
an SSH key (`ssh-keygen` in the user's terminal, so the passphrase is typed
there; *Copy Public Key* through `wl-copy`) and Rust (`rustup` in a terminal,
about 600 MB in `~/.rustup`). It writes none of those files itself (ADR-003).
Nothing runs in the background; in the live session it says that what is
installed is lost at restart.

Commands: `window [--kit NAME]`, `list [--json] [--category C]`, `plan [--remove] KIT`,
`install|remove KIT…`, `setup git|ssh|rust|ports|dhcp|capture|test-adapter`, `doctor` (see the program's
docstring). A Depends of `flickos-desktop`. It is opened from Welcome's *Tools
for your work* card, Settings' *Tool Kits* tile (More Settings), the menu, and
*Set Up…* on an installed kit's page in Software.

Two steps change the computer, not the user's files, so they are system
settings of flickos-control (it asks for the password, records History and
owns the value; this window runs `flickos-control system KEY VALUE`):
*Devices on this network* (`firewall.local-ports`, ADR-006: ports from 1024 up,
each with `/tcp` or `/udp`, written as a ufw app profile and allowed from
private networks only, as `firewall.phones` is; also a row on Settings'
Firewall page) and *Container networks with DHCP* (`containers.dhcp`, only
with the containers kit: the helper creates or deletes
`/etc/flickos/kits/netavark-on`, the file the kit's drop-ins wait for, and
starts or stops netavark's units). Two more are the security kits' (1.4, flickos-control 1.84,
flickos-security.md ADR-S02 and ADR-S08):

- *Capture packets without administrator rights* (`packet-capture`, shown
  while `dumpcap` is on the computer): a switch for the calling account. The
  helper's `packet-capture on` sets Debian's debconf answer
  `wireshark-common/install-setuid` to true, runs `dpkg-reconfigure -f
  noninteractive wireshark-common` (its postinst gives `dumpcap` the
  capabilities, `root:wireshark` 754) and adds the user to `wireshark`;
  `off` takes the user out and, when no member is left, sets the answer back
  and reconfigures, which takes the capabilities away. Refused while an
  administrator's `dpkg-statoverride` is on `dumpcap`. The value is whether
  the user is in the group; the row says "Applies when you log in again." while
  the session's groups differ from it, and `doctor` prints `capture next
  login` with `sg wireshark -c wireshark` for now. Nothing gets capabilities
  but `dumpcap` (no `setcap` on nmap or tcpdump).
- *Wireless adapter for testing* (`wireless.test-adapter`, shown while
  `aircrack-ng` is on the computer: `airmon-ng` is in `/usr/sbin`, off a
  user's PATH): a drop-down of the Wi-Fi adapters not on a network, by maker
  and model (`wifi_adapters`: `nmcli -t device show`, and NetworkManager's
  `PermHwAddress` through `busctl`, since the interface's address is random
  while NetworkManager scans), and *None*. The helper's
  `wireless-test-adapter ADDRESS` checks that a Wi-Fi adapter with that
  permanent address is there and not on a network, writes
  `/etc/NetworkManager/conf.d/90-flickos-test-adapter.conf` (`[keyfile]`
  `unmanaged-devices=mac:ADDRESS`) and runs `nmcli general reload`; `off`
  deletes it and reloads. The row then says to start monitor mode with
  `sudo airmon-ng start DEVICE`, never `check kill`. A chosen adapter that
  isn't plugged in stays in the list as "(not plugged in)"; `doctor` says
  `absent`, or `set without the wireless kit` once the kit is gone (the
  setting stays: it is undone by choosing *None*).

Each has a helper verb and a polkit action.

*Environments* (1.4, flickos-dev.md 8c; flickos-security.md ADR-S03, ADR-S04 and
phase 3): rootless distrobox containers, shown once any kit is installed.
Without distrobox and podman the section is one row, *Install Containers Kit…*
(the containers kit's switch and plan). One image per kit category, each named
in full (`ENV_IMAGES`: `docker.io/library/debian:testing` for the developer
kits, Q2; `docker.io/kalilinux/kali-rolling:latest` for the security kits,
Q-S2), never rootful (Q-S3). What goes inside: a developer kit's Depends from
`apt-cache show` (other kits' expanded, so there is no second list), a
security kit's environment list (`ENV_LISTS`, section 4 of the security
design) or Kali's whole `kali-tools-*` list (`--whole`, Q-S9), and
`--extra exploitation` (Kali's Metasploit and Exploit-DB). The containers and
classroom kits have none (`NO_ENV`).

- `env new NAME --kit …` runs in the user's terminal (the window's *New
  Environment…* opens it there): it first asks the image's own apt for
  today's sizes (`env plan`: `apt-get install --trivial-only` in a
  throwaway `podman run --rm` of the image, which stays for distrobox), says
  where it downloads from and that the environment shares the home folder,
  and asks. Then `distrobox create --no-entry` with podman labels
  (`ENV_LABEL`: category, kits, extras), apt inside, and `distrobox stop`
  (a large install once left `distrobox enter` unable to find the user until
  the environment restarted).
- Each environment's row: kind, kits, running or stopped, when it was last
  updated (this program's `~/.local/state/flickos/kits/environments.json`,
  else when it was made) and that automatic updates don't reach it; *Open
  Terminal* (`distrobox enter` in the user's terminal) and a menu: *Update…*
  (`env update`, `apt-get full-upgrade` inside then stop, in the terminal),
  *Stop*, *Make a Command Available…* (`env export NAME COMMAND [--menu]`:
  `distrobox-export --bin` into `~/.local/bin`, refused for a command the
  system has too; `--menu` runs `distrobox-export --app`, or for Kali's GUI
  tools without a menu entry, `ENV_APPS`, writes
  `~/.local/share/applications/NAME-COMMAND.desktop` "… (on NAME)"), *Start
  Database* with Kali's Metasploit (`env database`: `pg_ctlcluster` and, the
  first time, `msfdb init`, as the environment's root), and *Remove…*
  (asks; `distrobox rm --force`, which also deletes the commands and menu
  entries exported from it: the entries above are named so that it finds them;
  then `podman rmi` of its image when `podman ps --filter ancestor=` finds no
  other container made from it, the user's own included, and quietly not when
  podman can't say or refuses).

*Newer versions* (1.4, flickos-dev.md 8a and 8b, ADR-007 to ADR-009;
flickos-security.md ADR-S07; Q8 to Q11 and Q-S8 decided 2026-11-19), shown
once a kit that offers one is installed:

- A maker's repository is flickos-control's system setting `upstream.ID`
  (below), offered by `UPSTREAMS`: *mise* (with any kit that has tools in
  `USER_TOOLS`) and *Metasploit Framework* from Rapid7 (with any security
  kit). *Install…* shows what it is, the download and size (phase 0's) and
  that its package's scripts run as root (`UPSTREAM_TRUST`), then runs
  `flickos-control system upstream.ID on`, which asks for the password,
  adds the repository and installs the package; *Remove…* runs `off`. These
  are the only entries (Q8): NodeSource, Adoptium and GitHub CLI were left
  out, so newer Node comes per user through mise.
- With mise installed, a row per tool of the installed kits (`USER_TOOLS`:
  mise's name, title, kit, what the download is checked against, `latest` or
  Node's `lts`, Debian's package of the same tool; pipx's tools only while
  `pipx` or `uv` is there): whose version runs ("Yours: 26.13.1, from mise.
  It follows the newest long-term release. The computer has 20.19.2 from
  Debian."), the check (`CHECKS`; GitHub's digest says it is the weaker
  one), and *Use the Latest* (`mise use --global TOOL@latest`), *Keep This
  Version* (`mise use --global TOOL@VERSION`), *Follow the Latest*, and *Back
  to the Computer's Version* / *Remove Your Version* (`mise unuse --global`,
  which deletes mise's copy). A last row, *Your versions (mise)*: mise's
  version, when they were last updated (`~/.local/state/flickos/kits/versions.json`),
  that they get no restore points, History or automatic updates, *Update
  All* (`mise upgrade`, which keeps a kept version) and *Remove mise…*
  (puts the listed tools back to the computer's first, since a shim without
  mise hides the system's program).
- mise runs as the user with `MISE_YES=1` and no terminal; its list is read
  with `mise ls --global --json` and `MISE_OFFLINE=1`, so opening the window
  fetches nothing. flickos-settings' `flickos-session` (1.61) puts
  `~/.local/share/mise/shims` first on PATH while mise is installed; a
  session from before says "Programs use them from your next login."

Commands: `version list [--json]` (`maker ID on|off VERSION` and `tool NAME
KIT yours|computer|none VERSION CHECK` lines), `version maker mise|rapid7
[on|off]`, `version use TOOL [VERSION|latest|system]`, `version update`;
`doctor` adds `maker ID`, `version TOOL yours …` and `version path next
login` lines, and `version TOOL not first PATH` when another copy comes
before the user's mise version on the PATH `doctor` runs with (a shell
startup file's nvm or `~/.local/bin`: such a version wins only in apps
from the menu). `TOOL_COMMANDS` names a tool's command when it isn't the
last part of mise's name.

### `flickos-kit-*`

Opt-in developer kits ([design/flickos-dev.md](design/flickos-dev.md), ADR-001
and ADR-002) and security kits
([design/flickos-security.md](design/flickos-security.md), ADR-S01): one
native, `Architecture: all` meta-package per kind of work, whose **Depends**
are the Debian packages it needs. Not in the ISO or `flickos-desktop`;
`packages/build.sh` puts them in `config/packages.opt-in/` and
`repo/publish.sh` publishes them. Installed from Software's *Developer
Tools* (a shelf on its front page) or *Security Tools* (no shelf), removed
there too.

- `flickos-kit-base`: git, build-essential, gdb, make, curl, jq, ripgrep,
  fd-find, shellcheck, sqlite3, gh. Every other kit depends on it. No
  `man-db`: it enables a timer and cron jobs.
- `flickos-kit-python`: python3-venv, python3-dev, python3-pip, pipx.
- `flickos-kit-web`: nodejs, npm (Debian's Node 20, past its end of life;
  Debian's npm pulls a few hundred `node-*` packages).
- `flickos-kit-c`: cmake, meson, ninja-build, clang, valgrind, pkgconf.
- `flickos-kit-containers`: podman, podman-docker, distrobox, uidmap, passt.
  podman's `netavark` enables a DHCP socket and a service that would run all
  boot, so the kit ships a `flickos-kit.conf` drop-in for each of its three
  units with `ConditionPathExists=/etc/flickos/kits/netavark-on`: they stay
  off until the Tool Kits window (phase 2) creates that file.

- `flickos-kit-classroom` (Q15), titled *Young Learners* (Q16; the package,
  ID and `FlickOS::kit` keep `classroom`): gcompris-qt, kalzium, kgeography,
  kturtle, kmplot. Not a developer kit: no `flickos-kit-base`, category
  `classroom` (Software lists it under *Education*, the Tool Kits window under
  *For learning and teaching*). No Veyon: its student side can't capture a
  Wayland screen (docs/design/flickos-dev.md, Q15).
- `flickos-kit-study` (Q16), *Study*: xournalpp, labplot, kwordquiz, artha.
  For secondary school and university students; the same category as Young
  Learners, no `flickos-kit-base`.

The security kits (1.0, flickos-security.md phase 1, section 4) have the
category `security` (Software's *Security Tools*), depend on Debian's main
archive only and on no other kit (not `flickos-kit-containers`, Q-S1), and
their package descriptions end with the permission sentence (ADR-S05;
Software shows it from its own `PERMISSION`, so the metainfo leaves it out).
Their names say the kind of work, never "security" (Q-S7):

- `flickos-kit-network`: nmap, ndiff, ncat, netcat-openbsd, socat, wireshark,
  tshark, tcpdump, arp-scan, bind9-dnsutils, whois, traceroute, mtr-tiny,
  iperf3, ngrep, tcpflow, smbclient, ldap-utils, nbtscan, snmp, onesixtyone,
  bettercap, ettercap-graphical. Capture stays root-only as Debian installs
  it until the Tool Kits window's setting (phase 2, ADR-S02).
- `flickos-kit-web-testing`: sqlmap, gobuster, ffuf, wfuzz, dirb, whatweb,
  cewl, sslscan, testssl.sh.
- `flickos-kit-passwords`: john, hashcat, hydra, medusa, crunch, fcrackzip,
  pdfcrack, hashid. hashcat runs on the CPU through pocl; its page says what
  a GPU needs (Q-S4).
- `flickos-kit-forensics`: sleuthkit, autopsy, binwalk, foremost, scalpel,
  testdisk, dc3dd, ewf-tools, hashdeep, yara, libimage-exiftool-perl,
  steghide. No guymager: its smartmontools enables smartd (Q-S10).
- `flickos-kit-reversing`: gdb, binutils, ltrace, strace, edb-debugger,
  apktool, ghex, hexedit (gdb and binutils itself, since it has no base kit).
- `flickos-kit-wireless`: aircrack-ng, reaver, wifite, hcxtools,
  hcxdumptool, iw, macchanger. Its page says `airmon-ng start`, never
  `check kill`.

Each kit has metainfo `io.github.dvbondoy.flickos.kits.NAME`, an AppStream
add-on of type `addon` that extends `flickos-kits.desktop` (the Tool Kits
window, which doesn't exist yet: the add-on is read without it) with the
custom values `FlickOS::kit` (NAME) and `FlickOS::kit-category`
(`development`, `classroom` or `security`; appstreamcli ignores an `X-FlickOS-*` category in the
metainfo, so Software gives the row its own). Keep the IDs.

Every kit's `tests/test_kit.py` is the same file: the metainfo, that the Depends
are the base kit and Debian packages only, that no member is in `STARTS`
(packages that start or schedule something by themselves; add to it when a new
member does), and a security kit's name and permission sentence. A change to it
goes into the kits being changed; the others take the newest copy at their next
version (the developer kits' 1.0 copy predates the security kits). That every Depends is in Debian's archive is
`tools/check-debian-deps.py`'s job, which reads the kits' `control` files like
any other package's. Versions start at `1.0~test1` while the branch isn't merged.

### `flickos-fleet`

The agent of FlickOS's service for organizations that look after many
computers ([design/flickos-fleet.md](design/flickos-fleet.md); what it sends:
`packages/flickos-fleet/PRIVACY.md`, installed in
`/usr/share/doc/flickos-fleet/`). One Python 3 file, `usr/bin/flickos-fleet`
(stdlib only). Opt-in: not in the ISO or `flickos-desktop`;
`packages/build.sh` puts it in `config/packages.opt-in/` (Q8). It owns no
setting: every value goes to its owner.

- **The policy:** `{"version": N, "values": {KEY: VALUE}}`. Only the keys
  `kind_of()` knows (`LAYOUT_KEYS`, `CONTROL_PREFIXES`, `TILER_KEYS`, the
  welcome and menu keys, `SYSTEM_KEYS`, `countme`, `PACKAGE_KEYS`); any
  other is reported as failed, never run.
- **Site keys** go into the owners' files in `/etc/xdg/flickos-site/flickos/`
  (ADR-004), checked by the owners: `flickos-layout … list` before writing,
  `flickos-control get` (the source must be `site`) and `flick-tiler status`
  after; a refused value is taken out and reported with the owner's message.
  The agent writes only the files it made (`files` in its state): a site file
  from a variant's package is left alone. A changed file runs `flickos-control
  apply-defaults` (control's files only) and `flickos-layout apply-defaults`
  in each desktop session (found by its `labwc` process, run through
  `runuser` + `systemd-run --user --scope`).
- **System keys:** `flickos-control system KEY VALUE` as root (no pkexec, no
  History; ADR-011), only when `flickos-control system KEY` differs.
  `countme` through `countme-helper`. **Packages:** `apt-get` with ADR-002's
  options after repairing an interrupted dpkg; never removes
  `flickos-desktop`, its Depends or the agent, never installs live-only
  packages, and refuses a change apt's simulation says would take more.
- **The server** (ADR-010, `SERVER`, `Server=` in `/etc/flickos/fleet` for
  testing): `join CODE` shows the organization and asks, then keeps the token
  in `/etc/flickos/fleet` (root, 0600) and enables `flickos-fleet.timer`
  (every 30 minutes, 5 minutes' random delay; the package enables nothing,
  and since 1.1 starts the timer again after an upgrade where it is enabled).
  `run` checks in when due (`next` in `/var/lib/flickos-fleet/state.json`;
  the server's `interval` can only lengthen it), sends `CHECKIN_FIELDS` and,
  once a day, `INVENTORY_FIELDS`, and applies a newer policy. `status
  [--json]` for anyone; `leave` removes the site files and the token and
  stops the timer, with or without the server. `check FILE [--dry-run]`
  applies a policy file without a server.
- **Unit tests** in `tests/`: the owners as stand-ins, a fake server on
  127.0.0.1, and the real flickos-control, flickos-layout and flick-tiler from
  the source tree on what the agent writes (skipped where they aren't next
  to it). A test holds `PRIVACY.md` to the fields sent. No boot-test check:
  it isn't in the ISO.

### `flickos-classroom-view`

A teacher's view of a classroom of FlickOS computers
([design/flickos-classroom-view.md](design/flickos-classroom-view.md)). One
Python 3 file, `usr/bin/flickos-classroom-view` (stdlib, Pillow for
thumbnails, GTK 3 only for the console and the pairing window), with two
roles, in two binary packages built from this folder:
`flickos-classroom-view` (the program, the student's agent, the strip and a
lab computer's service: what every student's computer needs) and
`flickos-classroom-teacher` (the *Classroom* menu entry,
`flickos-classroom-teacher.desktop`, and `gir1.2-gtk-vnc-2.0`; Depends on
`flickos-classroom-view` of the same version), so a student's computer has no
teacher's window in its menu. `teacher` without gtk-vnc says it needs
flickos-classroom-teacher. Opt-in: not in the ISO or `flickos-desktop`;
`packages/build.sh` puts both in `config/packages.opt-in/`.

- **Student** (`student on|off|get sharing|status|pair|forget|run|panel`):
  the setting `sharing` (system default `Sharing=off` in
  `/etc/xdg/flickos/classroom.conf`, the user's in
  `~/.config/flickos/classroom`, recorded for History). `run` is started by
  FlickOS's autostart and exits at once while off and in the live session
  (INT-9). While on it answers mDNS (`_flickos-classroom._tcp`, joined and
  sent on every network with an IPv4 address, checked again every minute:
  joining with "any" takes only the default route's, found with two VMs) and listens
  on TCP 47100 (`PORT`; with ufw on, flickos-control's system setting
  `firewall.classroom` lets it in from private networks). Its key and
  certificate (EC P-256, `subjectAltName=DNS:<id>`) and the paired teacher's
  are in `~/.local/share/flickos/classroom/student/`; the local socket, the
  panel file and the class lock's release file are in
  `$XDG_RUNTIME_DIR/flickos/classroom/`.
  Every 30 s (`PROGRAM_CHECK_SECONDS`) the agent stops when the labwc of its
  `LABWC_PID` is gone (Debian keeps a user's processes after logout, and a
  leftover agent held the lock so the next login's quit) and starts again
  when an upgrade replaced its file, once no view, control or class lock
  would be cut. The lab service is restarted by the package's postinst
  (`dh_installsystemd` without `--no-start`, which stopped it at every
  upgrade).
- **TLS** (ADR-005): a teacher's connection is checked against the paired
  teacher's certificate only (`VERIFY_X509_PARTIAL_CHAIN`, as flickos-phone);
  one without a certificate may only pair, and only while `student pair`
  waits. **Pairing** (ADR-010): the console shows a six-digit code; both
  sides prove it bit by bit (20 rounds of commit, commit, open, open, bound
  to both fingerprints), so the code never crosses the network; three wrong
  tries end it.
- **Several teachers** (phase 3a, ADR-016): up to `MAX_TEACHERS` (16) in
  `teachers/FINGERPRINT.pem` and `.json` (name, since, source `paired` or,
  later, `fleet`) in the student's folder or `/etc/flickos/classroom/`
  (0644 there); 1.0~test8's one `teacher.pem` moves there at the agent's
  start. TLS trusts all of them; the certificate a connection used says
  which teacher it is (on a lab computer the service tells the session's
  agent in a first line, `{"type": "teacher", "fp", "name"}`). One teacher
  at a time: a second takes over (the first gets `{"type": "event", "what":
  "taken-over", "by"}` and its console doesn't reconnect until the teacher
  double-clicks the tile) unless the first's class lock, demo, view or control
  is on, when the second is answered `{"type": "busy", "teacher"}` (Q14).
  View and Control only for the teacher connected now. `student teachers`
  and `lab teachers` print `fingerprint name since source` lines; `student
  forget [FP]` and `lab forget [FP]` forget one (a fingerprint or its start)
  or all, and the service cuts a forgotten teacher's connection at once.
  `LAB_NOTICE` names the account logged in (Q15) and a lab computer shows it
  once more (`LAB_NOTICE_MARK` in `noticed`). `PRIVACY.md` (installed in
  `/usr/share/doc/flickos-classroom-view/`) says what a teacher can see; a
  test holds it to `VERBS`, the mDNS fields and the hello.
- **Verbs** (`VERBS`, ADR-006): `thumbnail` (a full-size `grim` capture
  reduced by Pillow to ~320 px, JPEG q50, every 1 or 2 s while asked, an
  unchanged screen not sent), `lock`/`unlock` (`flickos-lock lock
  --class-message TEXT --release FILE`; the agent refreshes FILE with every
  message from the teacher and removes it to unlock; flickos-lock lets go by
  itself after 2 minutes without it), `message` (`notify-send`), `open-url`
  (`xdg-open`, http and https only), `ping`, `demo` (on: the class lock with
  `--class-image` and `DEMO_MESSAGE`, letting a plain class lock go first;
  off: released) and `demo-frame` (a JPEG after its line, written to
  `demo.jpg` in the runtime folder, 0600; refused without a demo or when not
  a JPEG; the answer times the teacher's frames, Q13). Anything else is
  answered `unknown` and logged. Turning sharing off releases a class lock
  at once.
- **View and Control** (phase 2, ADR-012): a connection whose first line is
  `view` or `control` (not `hello`) runs beside the main session. The agent
  starts the strip first (`strip --text … [--stop]`, a gtk-layer-shell bar
  at the top with an exclusive zone; it prints `shown`, or within
  `STRIP_SECONDS` there is no session), then `wayvnc -C vnc.conf -S
  vnc-control.sock [-d -r] -u vnc.sock` in the runtime folder (an empty
  config, its own control socket; view: no input, the pointer drawn in), and
  pipes the TLS connection to that socket with no time limit and TCP
  keepalive. The session ends with the teacher's window, wayvnc, or the strip
  (Stop exits 3: the teacher's main session gets `{"type": "event", "what":
  "stopped"}`; any other exit ends it too, since it is never hidden). One at
  a time; wayvnc and the strip die with the agent (`PR_SET_PDEATHSIG`). On a
  lab computer the service's relay carries it, and Stop is offered for
  control only (Q10). Panel: viewed or controlled; demo while demoing.
- **The panel** (ADR-004): `student panel` prints `panel.json` for
  flickos-layouts' `custom/classroom` (signal 14): open, looking (thumbnails
  asked for), locked, demo, viewed, controlled, or no teacher paired; while sharing is on and the agent
  hasn't written it (the panel may start first), plain "on", never empty.
- **A lab computer** (ADR-011, `lab status|on|off|pair CODE|forget|run`):
  the administrator's system setting `classroom.lab` (flickos-control,
  `pkexec flickos-classroom-view lab …` through `org.flickos.classroom.lab`).
  `lab on` makes the computer's identity in `/etc/flickos/classroom/` (key
  root-only), writes the `lab` mark and enables
  `flickos-classroom-lab.service` (`lab run`, root; the package enables
  nothing). The service answers mDNS, listens on 47100, pairs (`lab pair
  CODE` through its socket in `/run/flickos-classroom/`) and passes a
  teacher's session to the agent of the seat's user (`ACTIVE_UID` in
  `/run/systemd/seats/seat0`; a session of `CLASS=greeter`, the login screen,
  counts as nobody) on `lab.sock` in that user's runtime folder,
  which takes root's connections only; no one at the screen: the console
  shows *Nobody logged in*. Meanwhile `sharing` reads on for every account
  and `student on|off|pair|forget` refuse. `lab on|off|pair|forget` restart
  the logged-in users' agents in the new mode. Purging the package removes
  `/etc/flickos/classroom`.
- **Settings > Classroom** (flickos-control 1.75; teachers since 1.78, while
  this package is installed and not in the live session): the sharing switch,
  *Teachers* (a row each from `student teachers`, the one connected now
  said, each with Forget…: `student forget FP`, or `pkexec … lab forget FP`
  on a lab computer; teachers from Fleet can't be forgotten there), Pair With
  a Teacher… (`student pair`, a window), the firewall switch, the *Lab
  computer* switch with Pair This Computer With a Teacher…, and Open
  Classroom (only where flickos-classroom-teacher is installed).
  History says and undoes `sharing` (and `classroom.lab`, a system setting).
- **Teacher** (`teacher`, the *Classroom* window): the paired students
  (`~/.local/share/flickos/classroom/teacher/students.json`) as a grid of
  tiles, found by mDNS every 5 s while open and kept connected (a thread
  each). **Classes** (phase 3a, ADR-017; `classes.json` beside it, with the
  class shown): the list at the top shows one class (or All Students), and
  only its students are connected; here first, absent greyed at the end,
  *N of M here*; on a lab computer the tile names the account logged in. The
  menu: New Class… (with the selected students), Rename Class…, Delete
  Class…, Put Selected in a Class, Take Selected out of This Class, Copy
  Attendance (`wl-copy`), Save Attendance… (CSV: name, account, here or
  absent, class, time; both only when pressed, Q16) and Teacher
  Certificate… (the PEM and fingerprint, to paste on Fleet's dashboard
  later, Q17). Add Students… adds to the class shown. Lock Screens…, Unlock Screens, Send Message…, Open Web Page… act on
  the selected tiles, else on all; Add Students… shows a code and pairs every
  student who types it; Forget… removes selected students. View and Control
  (one selected, connected student) open a window with gtk-vnc
  (`ScreenWindow`: `open_screen`, then a socket pair carried by `pipe`); one
  window a student. Show My Screen (a toggle, ADR-014): `demo` on for the
  selected students or all, then every `DEMO_SECONDS` grim's capture, encoded
  once when it changed (`demo_jpeg`: its own size up to 1920 wide, 1280 while
  slow, quality 60) and offered to each `Link`, whose one slot keeps only the
  newest frame. Slow (Q13): the last frame took over 1 s to reach a student;
  fast again under 0.5 s. Closing the window ends a demo.
- **Unit tests** in `tests/`: settings, the pairing proof (right code, wrong
  code, different certificates), and an agent on 127.0.0.1 with fake `grim`,
  `flickos-lock`, `notify-send` and `xdg-open`: pairing over TLS, every verb,
  a stranger teacher and a wrong student refused; a lab computer's service
  passing a session to the seat's agent, nobody at the screen, root-only
  socket; with fake `wayvnc` and strip (`WAYVNC`, `STRIP`: never the real
  wayvnc, which would serve the developer's screen): view, control and the
  student's Stop, no strip or no wayvnc refused, the lab's Stop for control
  only, the demo and its frames (only JPEG, never queued), `demo_jpeg`'s
  sizes and Q13's switch. No boot-test check: it isn't in the ISO.

### `flickos-greeter`

The login screen of installed systems: greetd runs FlickOS's own login
screen, `greeter-window`, in the cage kiosk compositor, in the Arc-Dark colors
(design: `docs/design/flickos-greeter.md`). Nothing replaces greetd's own
`/etc/greetd/config.toml` (it is ignored):

- `usr/lib/systemd/system/greetd.service.d/flickos.conf`: a drop-in that
  skips greetd with `boot=live` (the live session keeps its tty1 autologin),
  runs `greetd-config` before each start and points greetd at its output.
- `usr/libexec/flickos/greetd-config`: writes
  `/run/flickos-greetd/config.toml`: VT 7, the greeter as `_greetd`, and an
  `initial_session` (automatic login, once per boot) for the first member of
  the group `autologin`.
- `usr/libexec/flickos/greeter`: sets the keyboard layout from
  `/etc/default/keyboard` (with two layouts and no `grp:` option it adds
  `grp:alt_shift_toggle`: only XKB switches layouts in cage),
  `GTK_THEME=Arc-Dark` and `NO_AT_BRIDGE=1`, then
  runs `systemd-cat --identifier=flickos-greeter cage -d -s -- sh -c
  'greeter-window || exec gtkgreet …'`: gtkgreet comes up whenever the window
  ends without a login (ADR-010), and everything's output goes to the journal
  (greetd gives the greeter tty7).
- `usr/libexec/flickos/greeter-window`: the window (Python, GTK 3), a greetd
  client over `$GREETD_SOCK` (greetd-ipc: a native 32-bit length, then JSON).
  - The users (`users()`): UID from `UID_MIN` to `UID_MAX` of
    `/etc/login.defs`, a shell other than `nologin`/`false`, by full name, read
    in a thread; *Someone Else…* last. Pictures from
    `/var/lib/AccountsService/icons/USER` only (homes are 0700), else the
    initial on a circle in the theme's selected color.
  - The sessions (`sessions()`): `SESSIONS` (*FlickOS*, *FlickOS (Plain
    Session)*), then `/usr/share/wayland-sessions/*.desktop` but
    `HIDDEN_SESSIONS` (bare labwc), `Hidden`, `NoDisplay` and a missing
    `TryExec`. `start_session` gets the session's command (never anything
    typed) and `XDG_SESSION_TYPE=wayland`, `XDG_SESSION_DESKTOP`,
    `XDG_CURRENT_DESKTOP`.
  - The conversation (`Conversation`): `create_session` when the password is
    sent; the typed password answers PAM's first `secret` prompt; later
    prompts are asked on the card, PAM's text translated through PAM's own
    gettext domain (greetd's worker has no `LANG`); `auth_error` →
    `cancel_session` (whose `error` reply still clears greetd's state) and
    "Wrong password", "expired" (`NEW_AUTHTOK_REQD`: Ctrl+Alt+F1) or
    "can't log in now".
  - `STATE` (`/var/lib/greetd/flickos/state`, JSON, `0700` folder): the last
    user, each user's last session and the zoom, written atomically only
    after greetd accepted `start_session`. The last user is picked at start.
  - The card on one screen: `builtin_sizes()` reads the EDID size of
    connected `eDP`/`LVDS`/`DSI` connectors in `/sys/class/drm`,
    `choose_monitor()` matches it to GTK's monitors (else the first), and
    the card and the two bottom corners are overlay children placed by
    their margins.
    The wallpaper (the Dark style's, from flickos-layouts) covers each screen,
    decoded at screen size in a thread, under flickos-lock's `DIM`.
  - The clock: flickos-lock's `CLOCK_FORMATS`, 12h when the locale's `T_FMT`
    has `%r`, `%I` or `%l`; the date's format is translatable.
  - Shut Down and Restart (`POWER`): a popover at the bottom right, each
    needing a second click within `CONFIRM_SECONDS` (`TwoStep`, flickos-menu's),
    then logind's `PowerOff`/`Reboot` over the system bus, which the greeter's
    own session may do with no password. On a refusal `ListInhibitors` and
    `blocked_by()` name the block inhibitor on the card. No system bus, no
    button.
  - The keyboard layout: with two or more in `XKB_DEFAULT_LAYOUT`, a button
    with the short name and a popover naming the switch key (`keyboard()`,
    both from xkb-data's `evdev.xml`, in the `xkeyboard-config` domain's
    translations). It only shows the layout: cage changes it, and GTK sees the
    new group at the next key (`group_after()`).
  - Zoom (`ZOOM_STEPS`, flickos-lock's): Super+=, Super+-, Super+0 and
    Super+scroll, one font size on the window; pictures and icons follow
    through `zoomed`. `fit_clock()` hides the clock and date when the card
    wouldn't fit the screen.
  - Keys: arrows and Enter in the list, a letter jumps to a name, Escape back
    to the list, Alt+V shows the password (hidden again after
    `REVEAL_SECONDS`), and any key with Super stays out of the box.
  - Exits 0 only after greetd accepted the session; any exception ends it
    with status 1 (`sys.excepthook`), so gtkgreet takes over.
  - `--check`: the users, sessions and (with two layouts) layouts it would
    offer, tab-separated (the boot test's checks).
- `po/`: translations (docs/12), the template and no language yet. PAM's and
  xkeyboard-config's texts come from their own domains.
- `etc/xdg/flickos/greeter.conf` (conffile, every key commented out): the
  login screen's defaults for a custom build, `Background=` (a PNG or JPEG
  everyone can read; empty: the Dark wallpaper) and `Position=` (`left`,
  `center`, `right`). `/etc/flickos/greeter`, which flickos-control's helper
  writes (*Settings → Login Screen*), wins over it. A picture that is
  missing or isn't a PNG or JPEG (its first bytes) means the Dark wallpaper
  and a line in the journal. The file is read before the window shows, so
  the box doesn't jump to its place.
- `usr/share/flickos/greeter/style.css`: the card, flickos-lock's with
  `.flickos-greeter` (theme colors only; a test compares `CARD_ALPHA`).
- `usr/share/flickos/greeter/gtkgreet.css` and `etc/greetd/environments`
  (conffile, `flickos-session-plain`; every line is an entry, so no comments):
  the fallback gtkgreet's look and session list, until one release after 2.0.
- `debian/flickos-greeter.sysusers`: creates the group `autologin`
  (`dh-sequence-installsysusers` adds the `systemd-sysusers` call to the
  postinst).
- `tests/test_greeter.py`: the protocol both ways and the conversation
  against a fake greetd on a socketpair, users, sessions, state, screens,
  clock, zoom, the power buttons, the layouts from a fake `evdev.xml`,
  the background and box position (`read_config`, `background_file`,
  `card_position` left and right), `--check`, the CSS, the translations, the copies from flickos-lock and
  flickos-menu (compared when they are in the tree), flickos-recovery's
  `GOOD_PROCESSES`, and the `greeter` script's fallback and switch key with
  stand-ins for systemd-cat, cage and gtkgreet.

`Breaks: flickos-recovery (<< 1.6~)`: older flickos-recovery counted only
gtkgreet as a login screen that came up, so every start ended at this one
looked failed and GRUB started a restore point. greetd's postinst enables it
as `display-manager.service` but doesn't start it, so an upgraded system
switches to the login screen at the next boot. **A Depends of
`flickos-desktop`** and in the sanity hook's `REQUIRED`. See
[09 – Login screen](09-customizing.md#login-screen).

### `flickos-installer`

Calamares configuration and FlickOS branding, the `flickos-install` launcher,
and the live-session menu with *Install FlickOS*. It replaces Debian's
`calamares-settings-debian` and is only in the live image
(`config/package-lists/installer.list.chroot`): Calamares removes it from
installed systems. See [09 – Installer](09-customizing.md#installer).

`flickos-install` first runs `flickos-switch before-install` (1.34): when a
Windows disk is found, a dialog offers to copy its files first, since
Calamares' *Erase disk* doesn't mention Windows; the installer starts only
on *Continue*, or when flickos-switch is missing or fails. The same list
has `ntfs-3g`, whose `ntfsresize` Calamares (KPMcore) needs to shrink
Windows' NTFS partition for *Install alongside*.

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
`Label`) and, since 1.7, the store's (`…-store,label=FlickOS Store`, from
`server/store/new-repo.sh`; its sources entry is written only with a key,
by flickos-control's `purchases add`) to the origins automatic updates install: Debian's `50unattended-upgrades` list plus this is
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
| `po/` (optional) | Translations: `POTFILES`, the template `NAME.pot`, `LINGUAS` and one `LANG.po` per language, built by `debian/rules`. Example: `flickos-welcome`; see [12 – Translating](12-translating.md) |
| `PACKAGE.postinst`, `.postrm`, `.triggers` (optional) | Maintainer scripts run by dpkg on install/remove, and trigger declarations. `#DEBHELPER#` marks where debhelper inserts generated code. Must be executable. Example: `flickos-branding` |

## Building

```sh
sh packages/build.sh
```

This builds **every** folder in `packages/` that has a `debian/` directory, and
puts the `.deb` files in `config/packages.chroot/`, except the opt-in
`flickos-style-*` packages, which go to `config/packages.opt-in/` so the image
doesn't install them. It stops with an error if
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
3. **Check:** `tools/check-all.py` checks what changed since `main`: the
   changelog against the published pool, the syntax of changed scripts, the
   repo's check scripts, and the unit tests of the changed packages and of
   the packages whose tests read them (here flickos-shortcuts', which want a
   description for every key). It says what to fix; `--build` also builds the
   packages and runs lintian.
4. **Build and test:** `sh packages/build.sh`, then install the `.deb` in a VM or rebuild the ISO.
5. **Commit** the file change and the changelog together.
6. **Publish** so installed systems receive it: `repo/publish.sh` and upload.
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
