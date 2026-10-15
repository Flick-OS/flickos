# 09 – Customizing FlickOS

How FlickOS is put together, and step-by-step recipes for changing it:
wallpaper, default apps, menus, keybindings, program defaults, installer, boot
menu, boot splash, OS name and firewall.

- [Before you start](#before-you-start)
- [How FlickOS config directories work](#how-flickos-config-directories-work)
- [Session startup](#session-startup)
- [Login screen](#login-screen)
- [Desktop layouts](#desktop-layouts)
- [Window tiling](#window-tiling)
- [Wallpaper](#wallpaper)
- [Default apps](#default-apps)
- [Settings window](#settings-window)
- [Menu entries](#menu-entries)
- [Add-ons](#add-ons)
- [Your own labwc files](#your-own-labwc-files)
- [Keybindings](#keybindings)
- [Program defaults](#program-defaults)
- [Installer](#installer)
- [Boot menu](#boot-menu)
- [Boot splash](#boot-splash)
- [OS name and login banner](#os-name-and-login-banner)
- [fastfetch](#fastfetch)
- [Firewall](#firewall)
- [Artwork](#artwork)
- [Ideas for later](#ideas-for-later)

## Before you start

### Where customizations live

| Package | Contains |
|---|---|
| `flickos-settings` | Desktop configuration: session script, labwc config, startup programs, program defaults, wallpaper, GTK theme defaults |
| `flickos-layouts` | Desktop layouts and the `flickos-layout` tool ([Desktop layouts](#desktop-layouts)) |
| `flickos-desktop` | Which apps and services are installed ([04](04-packages.md#flickos-desktop-meta-package)) |
| `flickos-greeter` | Login screen of installed systems ([Login screen](#login-screen)) |
| `flickos-installer` | Calamares configuration, branding, launcher, live-session menu ([Installer](#installer)) |
| `flickos-branding` | Boot splash, OS name in `/etc/os-release`, console login banner, fastfetch logo |
| `config/bootloaders/` (not a package) | ISO boot menu ([Boot menu](#boot-menu)) |
| `config/hooks/normal/0200-firewall.hook.chroot` (not a package) | Turns the firewall on in the ISO ([Firewall](#firewall)) |

The rule for deciding between a package and live-build config is in
[03](03-live-build-config.md#rule-of-thumb-package-or-live-build-config).

### Three rules

1. **Never install a file another package already owns.** dpkg refuses to
   install the package (`trying to overwrite '…', which is also in package …`).
   Before adding a file under `/etc` or `/usr`, check on a trixie system:
   ```sh
   dpkg -S /etc/xdg/foot/foot.ini          # installed packages
   apt-file search /etc/xdg/foot/foot.ini  # all packages (sudo apt install apt-file && sudo apt-file update)
   ```
   Debian's foot, fuzzel, waybar and Thunar **already ship** their
   default configs in `/etc/xdg`. That's why FlickOS uses its
   [own config directories](#how-flickos-config-directories-work).
2. **Users' own config always wins.** Programs read `~/.config/…` first. You're
   setting *defaults*, and a user who customizes a program stops receiving your
   changes for that file ([04](04-packages.md#flickos-settings)).
3. **Every change ships the same way:** edit → bump version → build → test → publish.

### Shipping a change

```sh
cd packages/flickos-settings
dch -i -D trixie "Describe the change."          # bump version (04)
cd ../..
# new top-level folder in the package? add it to debian/install
tools/build-iso.sh && tools/boot-test.py          # build + automated test (02)
tools/test-iso.sh                                 # look at it (02)
repo/publish.sh                                   # ship to installed systems (05), then upload
```

**Faster loop for config-only changes:** build just the packages
(`sh packages/build.sh`) and boot an existing ISO or test install with
`tools/test-iso.sh`. On the host, run `python3 -m http.server` in
`config/packages.chroot/`. Inside the VM, download the new `.deb` from
`http://10.0.2.2:8000/` and install it with `sudo apt install ./flickos-settings_*.deb`.
Then log out (`Super+Shift+E`) and log in again.

**Even faster, for experiments:** edit the files directly inside a running VM
(`sudo nano /etc/xdg/labwc/rc.xml`), then choose *Settings → Reload Desktop
Config* in the menu (labwc config) or log out and in (everything else). Copy the
result back into `packages/` when it works.

Details: [04 – Changing a package](04-packages.md#changing-a-package),
[02 – Building and testing](02-building-and-testing.md),
[05 – Publishing packages](05-apt-repository.md#publishing-packages).

---

## How FlickOS config directories work

FlickOS ships program defaults in its own directories and puts them **first**
in the XDG search paths. That avoids clashing with files Debian's packages own.

| Directory | Holds | Takes priority over |
|---|---|---|
| `$XDG_RUNTIME_DIR/flickos/xdg/` | Runtime overlay: files generated for the chosen [desktop layout](#desktop-layouts) and [style](#styles-darklight) at every login (`labwc/rc.xml`, `foot/foot.ini`, `fuzzel/fuzzel.ini`). RAM only, never edited by hand | Everything below |
| `/etc/xdg/flickos-live/` | Live-session-only config (from `flickos-installer`) | Everything below |
| `/etc/xdg/flickos/` | Program config: `foot/foot.ini`, `fuzzel/fuzzel.ini`, `mimeapps.list` | `/etc/xdg/…` from Debian packages |
| `/usr/share/flickos/` | Data: `waybar/`, `mako/`. `applications/` overrides can go here too | `/usr/share/…` |

The session script `packages/flickos-settings/usr/bin/flickos-session` sets
this up at every login, just before `exec labwc`:

```sh
XDG_CONFIG_DIRS="/etc/xdg/flickos:${XDG_CONFIG_DIRS:-/etc/xdg}"
XDG_DATA_DIRS="/usr/share/flickos:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
[ -d /etc/xdg/flickos-live ] && XDG_CONFIG_DIRS="/etc/xdg/flickos-live:$XDG_CONFIG_DIRS"
timeout 10 flickos-layout prepare && XDG_CONFIG_DIRS="$XDG_RUNTIME_DIR/flickos/xdg:$XDG_CONFIG_DIRS"
```

(Simplified: the real script only runs `flickos-layout` if it's installed and
`XDG_RUNTIME_DIR` is set.) The overlay folder is added even when it's empty, so
a later `flickos-layout set` can put files there without a new login.

Programs following the XDG spec look in `~/.config` first, then each directory
in `XDG_CONFIG_DIRS` in order, and use the **first** file they find.

The variables are set in the session script, not in labwc's `environment`
file, because labwc only reads the first `environment` file it finds. A user's
`~/.config/labwc/environment` would silently drop them.

The boot test checks that the live labwc session got the right `XDG_CONFIG_DIRS`
(check *session uses FlickOS config dirs*).

---

## Session startup

What happens after login. The [login screen](#login-screen) runs
`flickos-session` directly. A login on tty1 (the live session's autologin, or
the text login) reads `/etc/profile.d/95-flickos-session.sh`, which runs it
on tty1 only.

1. `flickos-session` sets the config directories, runs
   `flickos-layout prepare` ([Desktop layouts](#desktop-layouts)), sets the
   keyboard layout ([below](#keyboard-layout)), then runs `exec labwc`: with
   `-m` while the user's own labwc files are merged
   ([Your own labwc files](#your-own-labwc-files)), with `-C` in the plain
   session.
2. labwc reads `/etc/xdg/labwc/rc.xml`, `menu.xml` and `environment`, then runs
   `/etc/xdg/labwc/autostart`.
3. That file only calls **`/usr/libexec/flickos/autostart`**, which starts everything:

| Program | Purpose | Notes |
|---|---|---|
| `xdg-user-dirs-update` | Creates `~/Desktop`, `~/Pictures`, … | Screenshots go to `~/Pictures/Screenshots` |
| `swaybg` | Wallpaper | Started by `flickos-layout wallpaper`: the user's choice or the style's wallpaper ([Wallpaper](#wallpaper)). Without flickos-layouts, autostart starts swaybg directly |
| `mako` | Notifications | Started by `flickos-layout panel` with a config generated for the chosen style, unless the user has their own ([mako](#mako-notifications)) |
| `waybar` | Panel | Started by `flickos-layout panel` with the chosen layout's config and style's colors, unless the user has their own ([waybar](#waybar-panel)). Without flickos-layouts, autostart starts the default panel and mako directly |
| `polkit-mate-authentication-agent-1` | Password prompts for admin actions | |
| `nm-applet --indicator` | Network tray icon | `--indicator` is required: waybar's tray only shows StatusNotifierItem icons |
| `blueman-applet` | Bluetooth tray icon | Only if installed **and** a Bluetooth adapter exists (`/sys/class/bluetooth` not empty). It's a Python process, so it isn't started needlessly. A USB adapter plugged in later appears after the next login |
| `wl-paste --watch cliphist store` | Clipboard history (`Super+V`) | Only if installed |
| `/usr/libexec/flickos/night-light` | Warmer screen colors at night | Runs `wlsunset` with the coordinates of the system time zone's city (from tzdata's `zone1970.tab`, offline). No time zone set (e.g. UTC in the live session) → fixed times 18:30–06:30 |
| `flickos-shortcuts daemon` | Keyboard shortcut sheet while Super is held | Only if installed ([Shortcut sheet](#shortcut-sheet-hold-super)) |
| `flickos-layout first-run` | Desktop Layout & Style chooser at the first login of a new account | Only if flickos-layouts is installed; never in the live session ([First login](#first-login)) |
| `flickos-control idle` (swayidle) | Lock and suspend after the times in *Settings → Power & Idle* (default 5 and 15 min); a fixed swayidle without flickos-control | **Not in the live session**, so installs are never interrupted |
| `flickos-control startup run` | The XDG autostart entries (*Settings → Startup Applications*): `~/.config/autostart`, then `/etc/xdg/flickos/autostart` and `/etc/xdg/autostart` | Last. Waits up to 10 s for the tray |

**To add a startup program**, add a line to
`packages/flickos-settings/usr/libexec/flickos/autostart`. End it with `&`
unless it exits immediately. Use `if command -v PROGRAM >/dev/null; then … fi`
for anything in `Recommends:`, which users may uninstall. If the program's
package also installs an entry in `/etc/xdg/autostart`, hide it with a file of
the same name and `Hidden=true` in
`packages/flickos-settings/etc/xdg/flickos/autostart/`, or it starts twice. A
program users may choose to run (a tray applet) can instead stay an XDG
autostart entry; an override there with `X-GNOME-Autostart-enabled=false`
makes it off by default and switchable in Settings.

**Why a separate script:** labwc only reads the first `autostart` it finds. A
user who creates `~/.config/labwc/autostart` would lose the whole FlickOS
desktop (panel, tray, polkit agent), unless their file calls the script:

```sh
/usr/libexec/flickos/autostart
my-own-program &
```

Tell users this in your release notes or user docs.

---

## Login screen

Installed systems boot to a graphical login screen (`packages/flickos-greeter/`):
**greetd** is the display manager, and its greeter is **gtkgreet** running in
the **cage** kiosk compositor. After a successful login gtkgreet asks greetd to
start `flickos-session`. The live session doesn't use it: it logs in
automatically on tty1 (live-config), and the drop-in skips greetd with
`boot=live`.

| File | Purpose |
|---|---|
| `usr/lib/systemd/system/greetd.service.d/flickos.conf` | Drop-in: `ConditionKernelCommandLine=!boot=live`, runs `greetd-config` before each start, `greetd --config /run/flickos-greetd/config.toml` |
| `usr/libexec/flickos/greetd-config` | Writes that config: `vt = 7`, the greeter as `_greetd`, and the automatic login |
| `usr/libexec/flickos/greeter` | Keyboard layout from `/etc/default/keyboard`, `GTK_THEME=Arc-Dark`, `exec cage -d -s -- gtkgreet …` |
| `usr/share/flickos/greeter/gtkgreet.css` | Wallpaper and login box (Arc-Dark palette) |

greetd's own `/etc/greetd/config.toml` is ignored. Calamares doesn't run its
`displaymanager` module, which would rewrite that file for its own setup.

- **VT 7:** the login screen runs on VT 7 (Debian's greetd default). tty1
  keeps its text login as a fallback (Ctrl+Alt+F1), which starts the same
  session through the profile.d script. greetd sources `/etc/profile` for its
  sessions too, but the script only acts on tty1.
- **Automatic login:** `greetd-config` logs in the first member of the group
  `autologin` once per boot (greetd's `initial_session`). The installer's *Log
  in automatically* adds the user to that group (`autologinGroup` in
  `users.conf`); the package creates it (`debian/flickos-greeter.sysusers`).
  On a running system: `sudo gpasswd -a USER autologin` (or `-d` to stop).
  It applies at the next boot.
- **Look:** gtkgreet's widgets come from the Arc-Dark GTK theme. The CSS sets
  the wallpaper (`background-size: cover`; gtkgreet's own `--background`
  draws the image unscaled) and styles `#body` (the login box) and `#clock`.
  gtkgreet has no shutdown or restart buttons.
- **Back to the text login:** `sudo systemctl disable greetd` (the tty1 login
  starts FlickOS as before). `enable` brings the login screen back.
- **Test:** `tools/test-iso.sh --install`, then boot the disk
  (`tools/test-iso.sh --disk`). The boot test only checks that greetd is
  enabled and not running in the live session.

---

## Desktop layouts

A **desktop layout** decides how the panel is arranged and,
optionally, the order of the window title bar buttons. Layouts come from the
`flickos-layouts` package. The same chooser also sets the
[style](#styles-darklight) and the [desktop clicks](#desktop-clicks). Users switch at any time with *Settings → Desktop Layout & Style*
(the [chooser](#the-chooser)) or `flickos-layout set ID`. Both apply right away, and
the choice is remembered.

| Id | Name | Bars | Window buttons |
|---|---|---|---|
| `redmond` (**default**) | Redmond | One bottom panel: logo launcher button, window list of app icons (the title is in the tooltip, as in Windows 7), then tray (network is nm-applet's icon there), volume and battery icons and a two-line clock | Right (labwc default) |
| `cupertino` | Cupertino | Thin top bar (logo launcher button, clock, tray and status) and a centered dock at the bottom that fits its icons ([sfwbar](04-packages.md#sfwbar)). The dock takes no screen space. It is shown unless the active window is maximized (or fullscreen) on its monitor; then it hides until the pointer touches the bottom edge below it. It shows pinned apps, then other open apps. A line under an icon marks an open app, in the accent color for the active one. Hovering an app with several windows lists them | Left: `close,iconify,max:` |
| `traditional` | Traditional | Top panel (logo and *Applications* launcher button, clock, tray and status) and a bottom panel ([sfwbar](04-packages.md#sfwbar)): window list with titles, which get shorter as windows open, then a switcher for 4 desktops at the right end, as in GNOME 2. Super+Ctrl+←/→ goes to the next desktop (as in Windows), with Shift the window goes along | Right (labwc default) |

The launcher opens fuzzel. All bars of a layout run in **one** waybar process,
so there is always exactly one tray. A layout's sfwbar bar (`Dock=`:
Cupertino's dock, Traditional's bottom panel) is a separate sfwbar process
without a tray.

**Limits** (tell users in release notes):

- Only Traditional has more than one desktop: waybar has no labwc desktop
  switcher, and Traditional's is sfwbar's.
- Traditional's window list shows the windows of every desktop: labwc doesn't
  tell other programs which desktop a window is on. Clicking one on another
  desktop goes there. When even the shortest titles don't fit (about 23
  windows at 1280 px), the last buttons are cut off; Alt+Tab still reaches
  them.
- Redmond's window list (waybar) doesn't shrink its buttons: waybar 0.12
  doesn't ellipsize their titles. So it shows icons only, and titles only in
  the tooltip: with titles, many open windows would push the tray, status and
  clock off the bar.
- The dock has no magnification or drag-to-pin. Pinned apps are set in
  `layout.ini`.
- The hidden dock reappears only when the pointer touches the bottom edge
  right below it: the strip that reacts is as wide as the dock.
- The dock only knows whether the active window is maximized, not where windows
  are (labwc doesn't tell other programs). So it stays shown over the bottom of
  a normal window moved down to it, and over a maximized window that isn't the
  active one.
- No global menu bar in Cupertino.

### Files

| File in `packages/flickos-layouts/` | Purpose |
|---|---|
| `usr/bin/flickos-layout` | The tool: one Python 3 file, standard library only |
| `usr/share/flickos/layouts/ID/layout.ini` | One folder per layout. The folder name is the id (`a-z`, `0-9`, `-`, `_`) |
| `usr/share/flickos/layouts/ID/waybar.jsonc`, `style.css` | The layout's bars and CSS |
| `usr/share/flickos/layouts/cupertino/dock.config`, `dock.css` | Cupertino's dock: sfwbar config (see `sfwbar(1)`) and its CSS |
| `usr/share/flickos/layouts/traditional/windowlist.config`, `windowlist.css` | Traditional's bottom panel (window list and desktop switcher): sfwbar config and its CSS |
| `usr/share/flickos/layouts/ID/preview.png` | 240×150 image shown in the chooser (`tools/make-layout-previews.sh`) |
| `usr/share/flickos/styles/ID/wallpaper.png` | The style's [wallpaper](#wallpaper), shown with every layout |
| `usr/share/backgrounds/flickos/ID.jpg` | The layouts' photos, their wallpapers until flickos-layouts 1.37; now only choices in waypaper |
| `debian/links` | Links each style's wallpaper to `/usr/share/backgrounds/flickos/flickos-ID.png`, where waypaper shows it |
| `usr/share/applications/flickos-layout.desktop` | *Desktop Layout & Style* in the app launcher (Settings category) |
| `etc/skel/.config/flickos/choose-layout` | Marker copied into new accounts: the chooser opens at their [first login](#first-login) |
| `usr/share/flickos/layouts/common/modules.jsonc` | Module settings shared by all layouts: launcher, taskbar, clock, volume, battery, tray |
| `usr/share/flickos/layouts/common/base.css` | CSS shared by all layouts (fonts, translucent bars, module padding, volume and battery icons, tooltips) |
| `usr/share/flickos/styles/ID/waybar-colors.css` | The panel palette of each [style](#styles-darklight): `@define-color` with Arc-Dark or Arc values. The only CSS files with color values |
| `etc/xdg/flickos/layouts.conf` | `[Defaults] Layout=`, `Style=`, `Clicks=`, `Launcher=`, `MenuStyle=`, `Clock=` and `QuickSettings=`: defaults for users who haven't chosen (conffile) |
| `tests/test_engine.py`, `tests/fixtures/rc.xml` | Unit tests for the engine |
| `tests/test_layouts.py` | Unit tests for the shipped layouts and panel generation (see [Adding a layout](#adding-a-layout)) |
| `tests/test_chooser.py` | Unit tests for `pick` (lock, fuzzel fallback, which command a selection runs), `first-run`, previews, the desktop file and the marker. GTK itself isn't started |
| `tests/test_styles.py` | Unit tests for styles: overlay files, GTK settings, commands and the shipped palettes |

The tests run while the package builds (`override_dh_auto_test` in `debian/rules`).

`layout.ini` (Cupertino):

```ini
[Layout]
Name=Cupertino
Comment=Top bar with status icons and a dock at the bottom; window buttons on the left
Order=20
Waybar=waybar.jsonc
Style=style.css
Preview=preview.png
Menu=top-left
MenuStyle=grid
TitlebarLayout=close,iconify,max:
Dock=dock.config
DockStyle=dock.css
Pinned=firefox-esr.desktop;thunar.desktop;foot.desktop;libreoffice-writer.desktop;vlc.desktop;org.xfce.mousepad.desktop
```

`Order` sorts `list`. `Waybar` and `Style` are paths relative to the layout's
folder, or absolute. `TitlebarLayout` is optional and sets labwc's
`<theme><titlebar><layout>`. Comments go on their own lines (`#`): a `#` after
a value is part of the value. `TitlebarLayout` is `left:right`, with the buttons `icon`, `menu`, `iconify`,
`max`, `close`, `shade` and `desk`. An invalid value is ignored with a warning.
`set` also gives the layout's buttons to windows that draw their own title bar
([GTK settings](#gtk-settings-and-nwg-look)).
A layout with a missing `Name`, `Waybar` or `Style` isn't listed.

`Preview` (optional) is an image for the chooser, scaled to fit 240×150. A
layout without one gets an empty space.

`Wallpaper` (optional) is shown with `swaybg -m fill` while the layout is in
use, unless the user chose their own ([Wallpaper](#wallpaper)). FlickOS's
layouts have none: they show the style's wallpaper, so a layout switch keeps
the picture. A layout of your own may bring one; it wins over the style's.

`Menu` (optional) is `bottom-left` or `top-left`: where the [start
menu](#start-menu) opens, in the corner of the bar with the apps button. A
layout without it keeps fuzzel even while the start menu is on. `MenuStyle`
(optional) is its kind of menu: `classic` (default), `categories` or `grid`.
`tests/test_layouts.py` checks that the corner matches the bar's position.

`Quick` (optional) is `bottom-right` or `top-right`: where [Quick
Settings](#quick-settings) opens, at the end of the bar with the volume and
battery icons. A layout without it has no Quick Settings even while it is on.
`tests/test_layouts.py` checks that it matches the bar's position.

`Pinned` (optional) lists desktop file ids separated by `;`. They are shown
where a bar in `waybar.jsonc` has the module name **`flickos/pinned`**, and in
the dock where its config has the line **`pins = "flickos/pinned"`**.

`Dock` and `DockStyle` (optional, both or neither) are a bar run by
[sfwbar](04-packages.md#sfwbar) next to waybar (Cupertino's dock,
Traditional's bottom panel): an sfwbar config without a `#CSS` section
(syntax `#Api2`, see `sfwbar(1)`), and its CSS. The CSS follows the same rule as
`style.css`: palette color names only. sfwbar's names are `window#sfwbar` (the
bar's window), `grid#STYLE` (the taskbar or pager with `style = "STYLE"`),
`button#taskbar_item` (a window), `button#taskbar_popup` (an app, with the
classes `focused` and `running`), `window#taskbar_popup` (the list of an
app's windows) and `button#pager_item` (a desktop, `focused` for the current
one).

`Desktops` (optional, 1 to 9, default 1) is how many labwc desktops the layout
has, named `1`, `2`, … so the switcher's buttons stay small. More than one
also binds Super+Ctrl+←/→ (go to the next desktop, no wrapping; Windows' keys,
as GNOME 2's Ctrl+Alt+←/→ belong to apps under HIG INT-5) and
Super+Ctrl+Shift+←/→ (take the active window along), plus Super+1 to Super+N
(go to that desktop) and Super+Shift+1 to Super+Shift+N (move the active
window there), in the overlay rc.xml. Only give a layout desktops if it shows
them: sfwbar's `pager` does (waybar can't on labwc), and a unit test checks
this. When the next layout has fewer, labwc moves the windows of the desktops
that go to the first one.

### The generated panel

`flickos-layout panel` (and `set`) never run a layout's files directly. They
generate two files in `$XDG_RUNTIME_DIR/flickos/waybar/` and start
`waybar -c config.jsonc -s style.css` with them:

- **`config.jsonc`:** the layout's `waybar.jsonc` (one bar object or a list of
  bars) with relative `include` paths made absolute, and `flickos/pinned`
  replaced by one `custom/pin#app-ID` module per pinned app. Each has a tooltip
  with the app's `Name` and runs `gio launch FILE.desktop` on click.
- **`style.css`:** `@import` of the style's palette, `@import` of the layout's
  `style.css` (which imports `common/base.css`), then one
  `#custom-pin.app-ID { background-image: url("ICON"); }` rule per pinned app.

For a layout with a dock, also `$XDG_RUNTIME_DIR/flickos/dock/sfwbar.config`,
started as `sfwbar -f sfwbar.config` next to waybar:

- the layout's `Dock=` file with the `pins = "flickos/pinned"` line changed to
  the pinned apps' ids (desktop id without `.desktop`, which sfwbar compares
  with window app ids), or removed when none is installed;
- every `Exec("flickos/launcher")` changed to what the panel's apps button
  runs: the start menu while it is on, else fuzzel (Footprint's *Show Apps*);
- then a `#CSS` line, the style's palette and the layout's `DockStyle=` file,
  copied in (sfwbar loads that CSS from a string, where `@import` can't find
  relative files).

The file is deleted for a layout without a dock. `set` stops the FlickOS
sfwbar (`-f` below `$XDG_RUNTIME_DIR/flickos/`) together with waybar and starts
the new layout's dock, if any.

**Pinned apps:** the desktop file is looked up in `$XDG_DATA_HOME` and
`$XDG_DATA_DIRS` (`applications/ID`). An app is **skipped** if the file doesn't
exist, has `Hidden=true`, isn't `Type=Application`, or its `TryExec` program
isn't installed. So pinning an app from `Recommends` is safe.

**Dock icons** follow the icon theme spec: the current icon theme
(`gsettings get org.gnome.desktop.interface icon-theme`, normally Numix-Circle),
its `Inherits` chain, then Numix, Adwaita, and hicolor last, then `pixmaps/`. The
48 px (or scalable) size is preferred. `Icon=` with an absolute path is used as
is. An app without an icon gets an empty button with a tooltip.

If anything goes wrong while generating (a JSON syntax error, a missing
`include` or palette), `panel` starts flickos-settings' default panel instead,
and `set` keeps the old panel and exits with 1. A dock that can't be generated
is left out (`panel` warns, `set` exits with 1); the bars still start.

### Keeping the panel running

autostart runs `flickos-layout panel` once, so nothing would bring waybar, mako
or the dock back if one of them exited by itself — and waybar does exit when an
output changes under it, which happens in the first seconds of a session in a VM
or with a second monitor. Each of them therefore runs under a supervisor,
`flickos-layout supervise -- COMMAND …`: `panel` itself is waybar's, and mako's
and the dock's are started with `setsid -f`. `set` starts the new panel and dock
the same way.

The supervisor restarts a program that failed after 1 s, doubling the wait up to
8 s, and gives up after `RESTART_LIMIT` (5) failures in a row; one that ran for
`RESTART_HEALTHY_SECONDS` (60) starts counting from zero again. It does **not**
restart a program that was meant to end: one that exited 0, one that was killed
(how `set` stops the old panel), or any of them once the Wayland socket is gone.

Everything they print, and every restart, goes to
**`$XDG_RUNTIME_DIR/flickos/panel.log`** (truncated when it passes 256 KB). The
session's stderr is labwc's, which nobody can read after login, so that file is
the only trace a failed panel leaves; [07](07-troubleshooting.md#live-session--installed-system)
has the symptoms.

The same reasoning applies to the lock the layout commands share
(`$XDG_RUNTIME_DIR/flickos/layout.lock`): autostart starts `wallpaper`, `panel`,
`first-run` and the tiler daemon at once, so waiting for it is given up after 10
seconds (`LOCK_SECONDS`) with a warning, and the command carries on without it.
A sibling that hangs costs a warning, never the panel.

### Commands

| Command | Does |
|---|---|
| `flickos-layout list` | One line per layout: id, name, description (tab-separated) |
| `flickos-layout current` | The layout in use |
| `flickos-layout set [ID] [--style STYLE] [--clicks CLICKS]` | Saves the choice, regenerates the overlay and the panel files and, inside the session, runs `labwc --reconfigure`, restarts the FlickOS panel and, for a new layout, replaces a FlickOS wallpaper with the layout's. Outside a session (no `WAYLAND_DISPLAY`/`LABWC_PID`) it only saves: "applies at next login". `--style` and `--clicks` also set the style and the desktop clicks, with one panel restart. Without `ID` the layout stays |
| `flickos-layout style list`, `style current`, `style set ID` | The same for [styles](#styles-darklight) |
| `flickos-layout clicks list`, `clicks current`, `clicks set ID` | The same for [desktop clicks](#desktop-clicks) |
| `flickos-layout wallpaper` | Shows the [wallpaper](#wallpaper) (autostart): `waypaper --restore` if the user chose one there, else swaybg with `~/.config/flickos/wallpaper`, the layout's, the style's or the default wallpaper. If waypaper fails, the layout's or the style's |
| `flickos-layout prepare` | Regenerates the overlay (`xdg/`). Run by the session script at login, before labwc starts |
| `flickos-layout panel` | Starts mako with the generated notification config, generates the panel files, starts the layout's dock (sfwbar), then stays on as waybar's [supervisor](#keeping-the-panel-running) (autostart). If anything goes wrong it starts flickos-settings' default panel and notification config. A user's own waybar or mako config is used as is |
| `flickos-layout supervise -- COMMAND …` | Runs one panel program and restarts it when it fails. Started by `panel` and `set`, not meant to be typed |
| `flickos-layout doctor` | Lists user config that stops a layout or style from applying. Exit code 1 if it finds any |
| `flickos-layout state` | Every choice (layouts, styles, clicks, apps button, menu style), the ones in use and `doctor`'s warnings as one JSON object. The Settings window reads its layout page with it |
| `flickos-layout pick` | Opens the [chooser](#the-chooser) |
| `flickos-layout first-run` | Opens the chooser if this is a new account's [first login](#first-login). Run by autostart |

**Which layout is used:** `~/.config/flickos/layout` (written by `set`), else
`Layout=` in `/etc/xdg/flickos/layouts.conf`, else `redmond`. An unknown id
falls back to the next one with a warning, so removing a layout never breaks a
login. Styles (`style`, `Style=`) and desktop clicks (`clicks`, `Clicks=`) are
chosen the same way.

### The chooser

*Settings → Desktop Layout & Style* in the root menu and *Desktop Layout & Style*
in the app launcher both run `flickos-layout pick`:

- **Window:** GTK 3 (python3-gi), so it follows the Arc theme and Numix icons.
  It lists every layout with its preview, name and description, then the styles
  (Dark, Light) as radio buttons with color swatches from their panel palette,
  then the desktop clicks, and marks the current ones. *Apply* (or double-click
  a layout, or Enter) runs `flickos-layout set` in the background with only
  what changed (`ID`, `--style`, `--clicks`), so the panel restarts while the
  window stays open. A style is only passed when it changed, because setting
  one also resets the GTK theme. The line under the list shows what the
  command printed. *Wallpaper…* (only when waypaper is installed) opens
  waypaper.
- **Warnings:** the `doctor` warnings are shown in a yellow bar above the list
  and refreshed after every change.
- **One window only:** a second `pick` finds `$XDG_RUNTIME_DIR/flickos/pick.lock`
  taken, prints "The layout chooser is already open." and exits with 0.
- **Without GTK** (python3-gi missing, or no display): two `fuzzel --dmenu`
  lists, layout then style (`--index`, the current one preselected; desktop
  clicks stay as they are). The result comes as a
  notification (`notify-send`). Without fuzzel too, `pick` exits with 1 and
  points to `list`/`set`.

zenity was the original plan, but zenity 4 uses libadwaita, which ignores Arc and
would add about 12 MB. python3-gi and GTK 3 were already in the image.

**Previews** are schematic drawings in the Arc-Dark palette on the Dark
style's `wallpaper.png`, made by `tools/make-layout-previews.sh` (ImageMagick). Run it
again after changing a wallpaper. Screenshots scaled down to
240×150 are hard to read, so drawings are the default. To use real screenshots
instead: run `tools/boot-test.py` (it saves `boot-test/layout-ID.png` for each
layout), then `tools/make-layout-previews.sh boot-test`. Bump flickos-layouts'
version afterwards. `tests/test_chooser.py` checks every shipped layout has a
240×150 PNG.

### First login

A new account on an installed system sees the **welcome window**
(flickos-welcome) at its first login, and at every login after that until it
ticks **Do not show on startup** in the window (`flickos-welcome startup set
off`; `startup current` prints `on` or `off`): cards for the layout chooser,
Settings, Wi-Fi, the keyboard shortcuts, the software manager and the project's
links. Each card runs the program that owns that job, and a card whose program
isn't installed is left out.

- Each package ships its own marker in `/etc/skel/.config/flickos/`:
  `welcome` (flickos-welcome) and `choose-layout` (flickos-layouts, for the
  chooser on its own). `adduser` and Calamares copy `/etc/skel` into every new
  home directory, so the account created during installation (and any added
  later) gets them. Existing accounts never do: upgrading doesn't open either.
- autostart runs `flickos-welcome first-run` in the background when that
  package is installed, and `flickos-layout first-run` only when it isn't — so
  exactly one window can open.
- `first-run` opens the window only if `~/.config/flickos/welcome` exists,
  `Enabled=no` isn't set in `/etc/xdg/flickos/welcome.conf`, and `boot=live`
  isn't on the kernel command line.
- It deletes `choose-layout` in every case, so the chooser never opens on its
  own. `welcome` stays while the window is shown on startup: *Do not show on
  startup* deletes it and unticking writes it again. Accounts that saw the
  window before flickos-welcome 1.4 lost their marker then, so upgrading
  doesn't bring it back.
- The live user is created from `/etc/skel` too, so the markers are there, but
  `first-run` only deletes them (and deletes `welcome` with `Enabled=no`). The
  boot test checks this.

To stop new accounts from seeing it on one machine, set `Enabled=no` in
`/etc/xdg/flickos/welcome.conf`, or delete the markers from `/etc/skel` (dpkg
keeps them deleted, they're conffiles).

The cards are the `CARDS` table in `usr/bin/flickos-welcome`; the addresses
they open are `[Links]` in `welcome.conf`. **A link whose address is empty
shows no card**, which is why `Donate=` ships empty: an address FlickOS doesn't
control must never be shipped as a default.

Test it with `tools/test-iso.sh --install`, then `--disk` (see
[02](02-building-and-testing.md#what-to-check-on-the-installed-system)).

### How a layout is applied

Nothing is copied into the home folder. Each login, `flickos-layout prepare`
writes what the layout needs into **`$XDG_RUNTIME_DIR/flickos/`** (RAM, deleted at
logout), and the session script puts `…/flickos/xdg` first in `XDG_CONFIG_DIRS`.
Updated FlickOS packages therefore reach every user at their next login.

| Overlay file | Contents | Exists when |
|---|---|---|
| `xdg/labwc/rc.xml` | A copy of the first system `rc.xml` in `XDG_CONFIG_DIRS` (skipping the overlay itself), with `<theme><titlebar><layout>` and `<theme><name>` set | It differs from the system file: the layout has `TitlebarLayout`, or the style's window theme isn't the one in the system file |
| `xdg/foot/foot.ini`, `xdg/fuzzel/fuzzel.ini` | `include=` of flickos-settings' config, then of the style's palette ([Styles](#styles-darklight)) | The style isn't Dark |
| `waybar/config.jsonc`, `waybar/style.css` | The generated panel ([above](#the-generated-panel)) | Once the panel has started |
| `mako/config` | `include=` of `/usr/share/flickos/mako/config`, then of the style's `mako.conf` | Once notifications have started |
| `layout.lock` | `flock` lock, so two `set` commands can't interleave | Always |

- A file that isn't needed is **deleted**, so labwc falls back to
  `/etc/xdg/labwc/rc.xml`. With the default layout and style the `xdg/` folder is empty.
- If the system `rc.xml` can't be parsed, the overlay file is deleted with a
  warning, and labwc keeps using the system file.
- Files are written to a temporary name and renamed, so labwc never reads a
  half-written file.
- **Panel restart:** `set` stops only waybar processes of the current user whose
  `-c` config lies under `/usr/share/flickos/` or `$XDG_RUNTIME_DIR/flickos/`
  (SIGTERM, up to 3 seconds so the tray is released, then SIGKILL). It starts the
  new waybar in its own session with the old panel's environment. A waybar the
  user started with their own config is never touched. The waybar started by
  `flickos-layout` has `FLICKOS_LAYOUT=ID` and `FLICKOS_STYLE=ID` in its
  environment. The boot test checks this.
- Open windows keep their buttons until labwc redraws them after
  `labwc --reconfigure`.
- **Windows that draw their own title bar** (Firefox without *Title Bar*, GTK
  header bars, libadwaita apps) show GTK's buttons, not labwc's. `set` changes
  them too ([GTK settings](#gtk-settings-and-nwg-look)); apps pick the change
  up when they restart.

### User config that blocks a layout

User files are respected and never changed. `flickos-layout doctor` (and `set`,
and the chooser) warns about:

| User file or state | Effect |
|---|---|
| `~/.config/waybar/config` or `config.jsonc` | The user's own panel is used; layouts and styles don't change it |
| `~/.config/labwc/rc.xml` | Merged over FlickOS's: only its own keys and settings change. A copy of FlickOS's file or one with `<default />` replaces every system `rc.xml`, including the overlay; window buttons and the window theme don't change ([Your own labwc files](#your-own-labwc-files)) |
| `~/.config/labwc/autostart` without `/usr/libexec/flickos/autostart` | The FlickOS panel and notifications aren't started at all |
| `~/.config/foot/foot.ini`, `~/.config/fuzzel/fuzzel.ini`, `~/.config/mako/config` | That program keeps the user's colors when the style changes |
| `gtk-theme` or `icon-theme` not one of the styles' themes (chosen in nwg-look) | Styles don't change it ([GTK settings](#gtk-settings-and-nwg-look)) |
| `button-layout` not one of the layouts' values (set with `gsettings`) | Layouts don't change the buttons of windows that draw their own title bar ([GTK settings](#gtk-settings-and-nwg-look)) |
| A wallpaper chosen in waypaper (`wallpaper =` in `~/.config/waypaper/config.ini`), or `~/.config/flickos/wallpaper` | Layouts don't change the wallpaper ([Wallpaper](#wallpaper)) |
| Session started before `flickos-layouts` was installed | The overlay isn't in `XDG_CONFIG_DIRS`; window buttons, borders, terminal and launcher colors change after logging out and in |

### Desktop clicks

What a click on the empty desktop does. Users choose in the chooser, or with
`flickos-layout clicks set ID`:

| Id | Left click | Right click |
|---|---|---|
| `right-menu` (**default**) | Nothing | Desktop (root) menu |
| `both-menu` | Desktop menu | Desktop menu (labwc's own default) |
| `left-launcher` | App launcher (fuzzel) | Desktop menu |

Middle click keeps labwc's default (the desktop menu). **Every** desktop click
also runs `pkill -x fuzzel`: labwc doesn't move the keyboard focus when the
desktop is clicked, so fuzzel wouldn't notice the click and stay open. While
the [start menu](#start-menu) is on, the clicks come from `MENU_CLICK_ACTIONS`
instead: every click also closes the menu, and `left-launcher` opens the menu.

- **Where:** the choices are built into `flickos-layout` (`CLICKS` and
  `CLICK_ACTIONS`), not files. flickos-settings' `rc.xml` has the `right-menu`
  bindings in `<mouse><context name="Root">`, after `<default />`.
- **How:** any other choice makes `prepare`/`set` write the overlay `rc.xml`
  with the `Left` and `Right` `Press` bindings of the last `Root` context
  replaced. The default needs no overlay, so an administrator's own bindings in
  the system `rc.xml` stay until a user picks another choice.
- **Change the default:** `Clicks=` in `layouts.conf`. If you change the
  bindings in flickos-settings' `rc.xml`, change `DEFAULT_CLICKS` or
  `CLICK_ACTIONS` to match (the fixture `tests/fixtures/rc.xml` has a copy, and
  `ClicksTest` checks it).

### Start menu

A classic start menu for the apps button (package `flickos-menu`, see
[04](04-packages.md#flickos-menu) and
[design/flickos-menu.md](design/flickos-menu.md)). **On by default**: the apps
button and a tap of Super open it; Super+D stays fuzzel. A user switches it
under *Apps button* in *Settings → Desktop Layout & Style*, or:

```sh
flickos-layout launcher list          # fuzzel, and menu while flickos-menu is installed
flickos-layout launcher set fuzzel    # off: the menu's daemon stops, applies at once
flickos-layout launcher set menu      # on again
flickos-layout launcher set default   # back to the system default (the menu)
```

While it is on, for a layout with a `Menu=` corner:

| What | Where it comes from |
|---|---|
| The apps button opens it | `custom/launcher`'s `on-click` in the generated `waybar/config.jsonc` (`MENU_TOGGLE`) |
| A tap of Super opens it (a hold still shows the shortcut sheet) | `Super_L`/`Super_R` `onRelease` keybinds in the rc.xml overlay (`MENU_SUPER`) |
| A desktop click closes it | `MENU_CLICK_ACTIONS` in the rc.xml overlay |
| It opens in the button's corner, in the layout's style | `$XDG_RUNTIME_DIR/flickos/menu/anchor`, from `Menu=` and `MenuStyle=` |
| It opens at once | `flickos-menu daemon`, run by `flickos-layout panel` under `supervise` |

While it is off, none of these exist. Super+D and Alt+F3 stay fuzzel either way.

**Each layout has its own kind of menu**, `MenuStyle=` in its `layout.ini`:

| `MenuStyle=` | Used by | What it is |
|---|---|---|
| `classic` (default) | Redmond | Windows 7: pinned apps, All apps, search; user, folders, Settings, Software, power |
| `categories` | Traditional | GNOME 2/Whisker: search on top, categories left (Favorites, All apps, sections, Folders), apps right as you point at a category, user and power buttons below |
| `grid` | Cupertino | Launchpad: every app as a big icon, full screen and see-through, the power buttons top right while Quick Settings is off; click the background or press Escape to close |

A user can pick one style for every layout instead, under *Start menu
style* in the Settings page, or:

```sh
flickos-layout menu-style list        # layout (each layout's own, the default), classic, categories, grid
flickos-layout menu-style set grid    # the grid in every layout, in the layout's corner
flickos-layout menu-style set layout  # back to each layout's own
```

`MenuStyle=` in `[Defaults]` of `layouts.conf` sets it for users who haven't
chosen (default `layout`).

A style is a `View` subclass in `flickos-menu` (`VIEWS`; add its name to
`MENU_STYLES` in both flickos-menu and flickos-layout). Its CSS is under
`.flickos-menu.style-NAME` in `style.css`. After `flickos-layout set`, a running
menu builds the new layout's style in the background, so it opens at once.

**Default pinned apps:** `Pinned=` in
`packages/flickos-menu/etc/xdg/flickos/menu.conf` (conffile), desktop ids
separated by `;`. The live session reads
`packages/flickos-installer/etc/xdg/flickos-live/flickos/menu.conf`, which
has *Install FlickOS* first; keep the rest the same. A user who pins or unpins
an app (right-click it, or `flickos-menu pin|unpin ID`) gets their own list in
`~/.config/flickos/menu`.

**Make fuzzel the default for everyone again:** `Launcher=fuzzel` in
`packages/flickos-layouts/etc/xdg/flickos/layouts.conf` (or on one machine in
`/etc/xdg/flickos/layouts.conf`).

**Other changes** are in `packages/flickos-menu/usr/bin/flickos-menu`:
`SECTIONS` (All apps' categories), `TOOLS` and `POWER` (right column), `PLACES`
(folders), `TAP_MS` (keep it below flickos-shortcuts' `HOLD_MS`), the sizes
`WIDTH_LEFT`, `WIDTH_RIGHT`, `HEIGHT` (classic), `CategoriesView.WIDTH`/`HEIGHT`,
`ICON_GRID`. The look is
`usr/share/flickos/menu/style.css`: GTK theme colors only (`@theme_bg_color`,
…), so both styles recolor it.

**Try it from the source tree:** in a FlickOS session, with the menu on,
`FLICKOS_MENU_PREFIX=$PWD FLICKOS_MENU_TIMING=1 usr/bin/flickos-menu daemon`
in `packages/flickos-menu` (after `pkill -x flickos-menu`), then click the
button. The times are in `$XDG_RUNTIME_DIR/flickos/menu/timing.log`;
`flickos-menu bench` times the index and search.

### Quick Settings

Switches and sliders behind the panel's volume and battery icons (package
`flickos-menu`, the start menu's daemon; see [04](04-packages.md#flickos-menu)
and [design/flickos-quick-settings.md](design/flickos-quick-settings.md)).
**Off by default**: a user turns it on under *Quick Settings* in *Settings →
Desktop Layout & Style*, or:

```sh
flickos-layout quick-settings list          # off, and on while flickos-menu is installed
flickos-layout quick-settings set on        # applies at once
flickos-layout quick-settings set default   # back to the system default (off)
```

While it is on, for a layout with a `Quick=` corner:

| What | Where it comes from |
|---|---|
| A click on the volume or battery icon opens it; the volume icon's right click opens the sound mixer, scrolling still changes the volume | `group/quick` with both icons' `on-click` (`QUICK_TOGGLE`) in the generated `waybar/config.jsonc` (waybar 0.12 never runs a group's own `on-click`) |
| The two icons light as one button | `#quick:hover` in `layouts/common/base.css` |
| Super+A opens it (labwc's default, maximize, is replaced; Super+Up still maximizes) | A `W-a` keybind in the rc.xml overlay (`QUICK_KEY`) |
| A desktop click closes it | `MENU_CLICK_ACTIONS`, or `QUICK_CLICK_ACTIONS` while the start menu is off |
| It opens in the icons' corner | `$XDG_RUNTIME_DIR/flickos/menu/quick`, from `Quick=` |
| It opens at once | `flickos-menu daemon`, which runs while the start menu or Quick Settings is on |

While it is off, none of these exist. `QuickSettings=on` in `[Defaults]` of
`layouts.conf` turns it on for users who haven't chosen.

**What it shows** is in `packages/flickos-menu/usr/share/flickos/menu/quick.py`:
`QUICK_TILES` (switches), `QUICK_READS` and `change_command` (each control's
owner: what it reads and runs; Quick Settings never changes a setting
itself), `quick_tiles` (a tile is left out when its program or hardware is
missing, as the phone's without a paired phone), `backlight` (the brightness
slider needs a backlight whose screen is on and that the user may change:
brightnessctl's udev rule is in Debian's `brightness-udev`, a Depends of
flickos-desktop, and gives the backlight to the `video` group). The look is in
`style.css` under `.flickos-quick`.

**Try it from the source tree:** as for the start menu, with
`FLICKOS_MENU_PREFIX=$PWD` (it finds `quick.py` there), then
`FLICKOS_MENU_PREFIX=$PWD usr/bin/flickos-menu quick`. The timing log has
*quick settings shown in* and *values in* (every owner has answered).

### Adding a layout

1. Copy a folder in `packages/flickos-layouts/usr/share/flickos/layouts/`, e.g.
   `redmond` to `mylayout`, and change `Name`, `Comment` and `Order` in
   `layout.ini`.
2. Edit `waybar.jsonc`. Start every bar with
   `"include": "../common/modules.jsonc"` and only override the settings that
   differ (values in the bar win over the included file). Give each bar a
   distinct `"name"`: waybar adds it as a CSS class (`window#waybar.NAME`).
   Put `"tray"` and `"custom/launcher"` in exactly **one** bar each, and
   `"custom/desktop"` (Show Desktop) last in the `"modules-right"` of one bar,
   so it sits at the screen edge.
3. Edit `style.css`. Keep `@import url("../common/base.css");` at the top. Use
   **named colors only** (`@wm_bg`, `@bg_color`, `@base_color`, `@fg_color`,
   `@selected_bg_color`, `@selected_fg_color`, `@borders`, `@warning_color`,
   `@error_color`), plus `transparent` and `alpha(@name, 0.8)`. The palette may
   change with a style, so color values like `#383c4a` are rejected by the tests.
4. Set `Menu=` to the corner of the bar with the apps button (`bottom-left` or
   `top-left`), and `MenuStyle=` if it shouldn't be `classic`, for the
   [start menu](#start-menu).
5. Add the id to `EXPECTED` in `tests/test_layouts.py`, and the CSS file (and a
   `DockStyle=` file) to `FILES` in `tools/check-palette.py`.
6. Add a preview: the id to `IDS` and a `draw` block in
   `tools/make-layout-previews.sh`, then run it. Keep `Preview=preview.png` in
   `layout.ini`.
7. Bump the version (`dch -i -D trixie`) and run `sh packages/build.sh`.

`tests/test_layouts.py` checks every shipped layout: `waybar.jsonc` parses (with
comments), includes and CSS imports exist, exactly one tray and one launcher,
every module in `modules-left/center/right` is defined in the bar or its
includes, `flickos/pinned` is used (in a bar or the dock's `pins` line)
exactly when `Pinned=` is set, a dock config starts with `#Api2` and has no
`#CSS` section, `TitlebarLayout` is valid, and the CSS (with `DockStyle=`) only
uses color names from the palette.

A new common module goes into `common/modules.jsonc`, and its styling into
`common/base.css`. Users' own layouts use those files by their full paths, so
a module, placeholder, signal, group or button class there is never renamed
or removed without the old name kept for two releases (HIG VIS-11;
`InterfaceTest` in `tests/test_layouts.py` lists them).

### Changing the default layout

Edit `Layout=` in `packages/flickos-layouts/etc/xdg/flickos/layouts.conf` and bump
the version. It's a conffile: if an administrator edited it, dpkg asks before
replacing it.

### Testing without a VM

```sh
cd packages/flickos-layouts && python3 -m unittest discover -s tests
cd ../..
HOME=$(mktemp -d) XDG_RUNTIME_DIR=$(mktemp -d) GSETTINGS_BACKEND=memory \
  XDG_CONFIG_DIRS=$PWD/packages/flickos-settings/etc/xdg \
  FLICKOS_LAYOUT_PREFIX=$PWD/packages/flickos-layouts \
  FLICKOS_SETTINGS_PREFIX=$PWD/packages/flickos-settings \
  packages/flickos-layouts/usr/bin/flickos-layout prepare    # then look in $XDG_RUNTIME_DIR/flickos/
```

`FLICKOS_LAYOUT_PREFIX` makes the tool read layouts, styles and `layouts.conf`
from the source tree instead of `/usr` and `/etc`. `FLICKOS_SETTINGS_PREFIX`
does the same for flickos-settings' foot, fuzzel and mako configs, which the
style files include. **Keep `GSETTINGS_BACKEND=memory`** when trying
`style set`: without it, the command changes the GTK settings of the desktop
you're working on.

The chooser works the same way (`… flickos-layout pick`) on any Wayland or X11
desktop. With a temporary `XDG_RUNTIME_DIR`, set `WAYLAND_DISPLAY` to the full
socket path (e.g. `/run/user/1000/wayland-0`) so GTK still finds the display.
Outside labwc, *Apply* only saves the choice.

Then look at `$XDG_RUNTIME_DIR/flickos/waybar/` after
`… flickos-layout set cupertino` (same variables). Add
`XDG_DATA_DIRS=$PWD/chroot/usr/share` after a build to resolve pinned apps and
icons against the image's files.

In a VM: `flickos-layout set cupertino`, then `traditional` and `redmond`, in a
terminal. The panel should restart once each time, `pgrep -c waybar` should print
`1`, `pgrep -c sfwbar` `1` for Cupertino and Traditional and `0` for Redmond, and the network icon
should come back in the tray. The boot test does the
same (checks *switch to …* and *tray survives the switch*) and saves
`boot-test/layout-redmond.png`, `layout-cupertino.png` and
`layout-traditional.png`.

**Check in a VM** when changing bars: open a dozen windows and make sure the
tray, status icons and clock are still there. waybar 0.12 doesn't ellipsize
taskbar titles, so a window list wider than the space left pushes the modules
after it off the edge of the bar (see
[Troubleshooting](07-troubleshooting.md#live-session--installed-system)). That
is why every waybar window list shows icons only (a unit test checks the
`format`). For Traditional's sfwbar window list: titles get shorter as windows
open and the desktop switcher stays at the right end; the current desktop is
highlighted, also after Super+Ctrl+←/→; clicking a window on another desktop
goes there. For the dock: it is shown on every monitor; maximized windows reach the
bottom edge; it hides while a maximized window is active (only on that
window's monitor) and comes back when it is restored, minimized or another
window is activated; pinned apps launch on click; open apps get the line under
their icon.

---

## Styles (Dark/Light)

A **style** recolors the desktop. Styles come from `flickos-layouts`, next to the
layouts, and are chosen in the same [chooser](#the-chooser) or with
`flickos-layout style set ID`. Both apply right away.

| Id | Name | GTK theme | Icons | Window theme (labwc) | `color-scheme` |
|---|---|---|---|---|---|
| `dark` (**default**) | Dark | `Arc-Dark` | `Numix-Circle` | `FlickOS-Arc-Dark` | `prefer-dark` |
| `light` | Light | `Arc` | `Numix-Circle-Light` | `FlickOS-Arc` | `default` |

**What follows the style:** GTK apps, icons, window borders and title bars, the
root and window menus, Alt+Tab, the panel, the app launcher (fuzzel, including
its icon theme), notifications, **new** terminal windows and the
[wallpaper](#wallpaper) (unless the user chose their own).

**What doesn't:**

- Open foot windows keep their colors until they're closed.
- Boot menus, boot splash, installer and the lock screen's color (`swaylock
  -c`, unless *Settings → Power & Idle* shows the wallpaper there) are always
  Arc-Dark, and so is the wallpaper's fill color. They run before or outside
  the user session.
- libadwaita apps always look like Adwaita
  ([GTK theme](#gtk-theme-icons-cursor-fonts-dark-mode)); with Light they at
  least follow `color-scheme`.
- A GTK or icon theme the user chose in *Appearance* ([below](#gtk-settings-and-nwg-look)).

### Style files

| File in `packages/flickos-layouts/usr/share/flickos/styles/ID/` | Purpose |
|---|---|
| `style.ini` | `[Style]` `Name`, `Comment`, `Order`, `GtkTheme`, `IconTheme`, `LabwcTheme`, `ColorScheme` (`default`, `prefer-dark` or `prefer-light`), and the palette files `Waybar`, `Foot`, `Fuzzel`, `Mako` (relative to the folder, or absolute); `Wallpaper` (optional) |
| `wallpaper.png` | The style's [wallpaper](#wallpaper): the halo (FlickOS's logo, drawn large), dark or light |
| `waybar-colors.css` | `@define-color` for the panel. Same names in every style; layout CSS uses only these names |
| `foot.ini` | `[colors]`: `alpha`, background, foreground and the 16 ANSI colors |
| `fuzzel.ini` | `[main] icon-theme` and `[colors]` |
| `mako.conf` | Background, text and border colors, and the `[urgency=critical]` border |

A style with a missing key or an invalid `ColorScheme` isn't listed. The window
themes live in flickos-settings: `usr/share/themes/FlickOS-Arc-Dark/labwc/themerc`
and `usr/share/themes/FlickOS-Arc/labwc/themerc`.

**flickos-settings' configs keep the Arc-Dark colors**
(`/etc/xdg/flickos/foot/foot.ini`, `fuzzel.ini`, `/usr/share/flickos/mako/config`),
so each program still works on its own. A style's files hold only colors. They are
included **after** the base config, so their keys win:

```ini
# $XDG_RUNTIME_DIR/flickos/xdg/foot/foot.ini, generated for the Light style
include=/etc/xdg/flickos/foot/foot.ini
include=/usr/share/flickos/styles/light/foot.ini
```

Dark's colors are the same as the base configs, so Dark needs no foot or fuzzel
overlay file. mako's config is always generated, because mako is started with
`-c` and a path can't change without restarting it; `makoctl reload` picks up the
new include.

### How a style is applied

`flickos-layout style set ID` (under the same lock as layouts):

1. Saves `~/.config/flickos/style`.
2. Regenerates the overlay ([table](#how-a-layout-is-applied)): `rc.xml` with
   `<theme><name>` set to the style's window theme, the foot and fuzzel files,
   `mako/config` and the panel's `style.css`.
3. Changes the [GTK settings](#gtk-settings-and-nwg-look). This happens even
   outside the session, because GTK settings live in dconf, not in the overlay.
4. Inside the session: `labwc --reconfigure` (window theme, menus),
   `makoctl reload`, then restarts the FlickOS panel.

**The window theme** in the overlay is only replaced if the system `rc.xml`
selects one of the styles' themes. An administrator who changed
`/etc/xdg/labwc/rc.xml` to their own theme keeps it.

**Which style is used:** `~/.config/flickos/style`, else `Style=` in
`/etc/xdg/flickos/layouts.conf`, else `dark`. An unknown id falls back with a
warning.

### GTK settings and nwg-look

`style set` always sets `color-scheme`. It changes `gtk-theme` and `icon-theme`
**only while they hold one of the styles' themes** (`Arc`/`Arc-Dark`,
`Numix-Circle`/`Numix-Circle-Light`). A theme chosen in *Settings → Appearance*
(nwg-look), e.g. Adwaita or Papirus, is kept, and `doctor` says so.

labwc's **window icons** (the title bar's `icon` button) use the same icon
theme: the overlay rc.xml's `<theme><icon>` is the current `icon-theme`.
flickos-settings' rc.xml has `Numix-Circle`; without it labwc looks for an icon
theme named like the window theme, finds none and shows only hicolor's icons
(FlickOS's own windows get labwc's). An `<icon>` in the system rc.xml that isn't
one of the styles' icon themes is kept. labwc reads it when it reconfigures, so
icons picked in nwg-look reach the title bars at the next style or layout change
or login.

A layout change touches only `button-layout` (`org.gnome.desktop.wm.preferences`):
the buttons of windows that draw their own title bar, like Firefox without
*Title Bar* or GTK header bars. `set` translates the layout's `TitlebarLayout`
into GTK's words (`iconify` → `minimize`, `max` → `maximize`; `shade` and
`desk` have none and are left out), so Cupertino gives `close,minimize,maximize:`.
A layout without `TitlebarLayout` resets the key to flickos-settings' default
([below](#gtk-theme-icons-cursor-fonts-dark-mode)). This happens **only while
the key holds the default or one of the layouts' values**. A value the user
set is kept, and `doctor` says so. The default comes from
`GSETTINGS_BACKEND=memory gsettings get …`, which has no user values.

**nwg-look** (`Recommends` of flickos-desktop and flickos-settings, menu entry
*Settings → Appearance*) is a GTK settings editor for wlroots compositors:
GTK theme, icons, cursor, fonts, color scheme. It applies them through
GSettings, which GTK apps under Wayland read, and can export them to
`~/.config/gtk-3.0/settings.ini` and `~/.gtkrc-2.0` for other apps. The FlickOS defaults are in
[GTK theme, icons, cursor, fonts, dark mode](#gtk-theme-icons-cursor-fonts-dark-mode).
It doesn't recolor FlickOS's panel, terminal, launcher or window borders; that
is what styles are for.

### Adding a style

1. Copy `styles/dark` to `styles/myid` in `packages/flickos-layouts/usr/share/flickos/`,
   and set `Name`, `Comment`, `Order` and the theme names in `style.ini`.
   The GTK and icon themes must be installed (add their packages to
   flickos-settings' `Depends`).
2. Change the colors in the four palette files. Keep exactly the same keys and
   color names.
3. For a new window theme, copy a folder in
   `packages/flickos-settings/usr/share/themes/` and add it to `LABWC_THEMES` in
   `tools/check-palette.py`.
4. Add the palette files to `tools/check-palette.py` (in `FILES` or
   `LIGHT_FILES`, or a new palette) and the id to `EXPECTED` in
   `tests/test_styles.py`.
5. Bump the versions of both packages.

**Checks:** `tests/test_styles.py` (at package build) checks that every style
loads, sets the same waybar color names and the same foot, fuzzel and mako keys,
and that fuzzel's icon theme matches `IconTheme`. `tools/check-palette.py` (run
by `build-iso.sh`) checks the colors, that both labwc themes use the same valid
keys, and that each style's foot, fuzzel and mako file sets exactly the color
keys of flickos-settings' base configs, with Dark's values equal to them. So a
color key added to a base config must be added to every style.

**Changing the default style:** `Style=` in `etc/xdg/flickos/layouts.conf`. New
users' GTK settings still come from flickos-settings'
`90_flickos-settings.gschema.override`, so change `gtk-theme`, `icon-theme` and
`color-scheme` there too.

**Testing without a VM:** see [Testing without a VM](#testing-without-a-vm)
(`… flickos-layout style set light`, with `GSETTINGS_BACKEND=memory`), then
`foot --check-config -c $XDG_RUNTIME_DIR/flickos/xdg/foot/foot.ini` and
`fuzzel --check-config --config $XDG_RUNTIME_DIR/flickos/xdg/fuzzel/fuzzel.ini`.
The boot test switches to Light and back, checks GTK settings, overlay files,
panel and notifications, that a custom GTK theme is kept, and saves
`boot-test/style-light.png` and `style-dark.png`.

### Your own style

Users make styles of their own, with no package and no root, in
`~/.local/share/flickos/styles/ID/` (`$XDG_DATA_HOME`). flickos-layout looks
there first, then in `flickos/styles` below each `XDG_DATA_DIRS` folder (an
administrator's in `/usr/local/share`), then in FlickOS's own folder. The
first folder with an id wins, so a user's `dark` would hide FlickOS's (`list`
shows each style's folder). The chooser and Settings list users' styles after
FlickOS's, with "Yours" after the description; *Settings → About* names a
user's style and its parent ("style dark-orange (yours, inherits dark)"), so
it shows in bug reports; and *Settings → Desktop Layout & Style* has *Back to
FlickOS's Look* (`flickos-layout set default --style default`, undone from
History) while the layout or style isn't the default (`state`'s `default`).
Design: [design/flickos-ricing.md](design/flickos-ricing.md).

```sh
flickos-layout style new dark-orange --from dark --name "Dark Orange"   # prints the folder
$EDITOR ~/.local/share/flickos/styles/dark-orange/waybar-colors.css
flickos-layout check dark-orange      # prints nothing when all is well
flickos-layout style set dark-orange
flickos-layout watch                  # in a terminal: each save shows at once
flickos-layout style set default      # FlickOS's look again
```

**Inherits=.** A style that names a parent holds only what differs. Every
`style.ini` key it lacks is the parent's (then only `Name=` is needed), and
each palette file it names is used **after** the parent's: the panel's CSS
imports the parent's `waybar-colors.css`, then the style's, so one
`@define-color` line overrides one color; foot, fuzzel and mako include the
parent's file, then the style's. The parent may be another user style. FlickOS's
files are used where they are, never copied, so an update to Dark reaches every
style that inherits it at the next login. `style new` writes a starter: a
`style.ini` with `Inherits=` and every other key commented out, and the four
palette files with every key and the parent's value commented out. Taking the
comment marks away from one line changes that one color.

| `style.ini` key | Meaning |
|---|---|
| `Inherits=ID` | The parent style |
| `Packages=a;b` | Debian packages the style's themes come from; `check` names the ones that aren't installed |

**Only colors.** A style's palette files may set only the keys Dark's own
files set: `@define-color NAME #rrggbb;` lines with Dark's names in
`waybar-colors.css`, the same sections and keys in `foot.ini`, `fuzzel.ini`
and `mako.conf`, no `include=`. Foot's `shell=` or mako's `on-button-left=`
would run programs, and a style must never do that, whoever made it.

**Missing themes.** A GTK, icon or window theme that isn't installed (in
`/usr/share`, `~/.themes`, `~/.icons`, `~/.local/share/themes` or `icons`) is
replaced by the parent's, else Dark's. `prepare` and `set` warn about the
style in use, `doctor` lists it, `check` reports it for any style.

**`flickos-layout check [ID]`** reads only. One line per problem, as
`FILE[:LINE]: error|warning: message`; exit status 1 with any error, so it
can run in a dotfiles hook. With an id it checks that style (also Dark and
Light); without one, all of the user's styles, then
`~/.config/labwc/*.xml` (well-formed; in `rc.xml`, sections labwc doesn't know
and numbers that aren't numbers, which labwc silently reads as 0), the
user's add-ons (what would otherwise only reach `panel.log`), `include=` lines
in the user's foot, fuzzel and mako configs that point at a missing file (mako
doesn't start without it), and `doctor`'s warnings. For a style: `style.ini`,
the parent, the palette keys, `Wallpaper=` (a PNG or JPEG inside the style's
folder), themes, `Packages=`, and contrast below HIG A11Y-6 (4.5:1 for text
on the backgrounds, 3:1 for the accent's text) as a warning. The panel's text
is tested on the panel's own color too, and a see-through palette color
(`rgba()`) over a black and a white wallpaper, at the alpha the panel draws
it. `style set`
refuses a style with errors.

**Following the style from your own config.** The colors of the style in use
are always in `$XDG_RUNTIME_DIR/flickos/style/foot.ini` and `fuzzel.ini`
(include= lines, Dark's too). A user's own `~/.config/foot/foot.ini` that
starts with `include=/run/user/1000/flickos/style/foot.ini` (foot and fuzzel
take only absolute paths or `~/`, no variables: use your own user id) keeps
following Dark and Light and can still change the font. There is no such file
for mako: mako won't start when an included file is missing.

**Which file wins: `flickos-layout explain [PROGRAM]`.** For the style,
labwc, the panel, the dock, foot, fuzzel, mako, the GTK and icon themes and
the wallpaper, it prints the files read, in order, and whose each one is
(yours, a style's colors, generated for this login, FlickOS's), with every
`include=` and `@import` followed. A user's own `rc.xml` or panel config
says what it replaces, and a foot or fuzzel config of the user's that
doesn't include the style's colors says the line that would. It reads only.

**Seeing each save: `flickos-layout watch`.** Run it in a terminal on the
desktop and leave it open while you edit: every save to your styles, your
add-ons, `~/.config/labwc/` or your foot, fuzzel and mako configs is applied
within about a second, with one line saying what was done (or `check`'s
errors, and then nothing is applied). A palette file of the style in use or
of one of its parents regenerates the panel, dock and notification files and
has FlickOS's waybar (`SIGUSR2`), dock (`SIGHUP`) and mako (`makoctl
reload`) read them again, without restarting them; its `style.ini` does what
`style set` does, without saving a choice; another style of yours is only
checked. An add-on reloads labwc and the panel; a labwc file reloads labwc
and says when whether your files are merged changes at the next login; foot
and fuzzel read theirs at each new window. It watches with inotify, so
nothing runs between saves; Ctrl+C ends it. One per session, not in the
plain session. *Settings → Desktop Layout & Style → Your own styles → Open
Folder* opens (and makes) `~/.local/share/flickos/styles`.

**Sharing a style: `export`, `import`, `try`.** `flickos-layout export ID
[FILE]` writes one of your own styles into one file (`ID.tar.gz` here by
default, never over an existing file): what your own styles in its chain
set, folded together when its parent is yours too, with `Inherits=` the
nearest FlickOS style, so Dark's updates still reach the copy. `flickos-layout
import FILE` takes such a file: one folder named after the style holding
only `style.ini`, the four color files and one PNG/JPEG wallpaper (64 KB per
text file, 20 MB for the wallpaper), plain files only, unpacked with a limit
before anything else reads it, then `check` on a scratch copy. Any error
refuses the whole file and nothing is kept; warnings (contrast, a missing
theme) ask "Keep it?", or need `--yes` outside a terminal. FlickOS's ids are
refused, one of yours needs `--replace`. Nothing in a style can run a
program, so importing never does. `flickos-layout try ID` shows a style until
you log out, without saving it or recording it in History; `style set ID`
keeps it, `try --end` goes back now, and *Settings → Desktop Layout & Style*
shows *Keep* and *End* while trying. The try's GSettings changes are recorded
in `~/.local/state/flickos/try.json`, and every login puts back each one you
didn't change yourself meanwhile, also when the runtime folder survived the
logout or the tried style was deleted.

```sh
flickos-layout export dark-orange          # ./dark-orange.tar.gz
flickos-layout import ~/Downloads/nord.tar.gz
flickos-layout try nord                    # until you log out
flickos-layout style set nord              # or: flickos-layout try --end
```

**FlickOS's extra styles: Seven.** Besides Dark and Light, FlickOS publishes
styles as packages, installed only by those who want them: *Software →
Styles* lists them, and an installed style's page has *Try* (until you log
out) and *Use*. The first is **Seven** (`flickos-style-seven`): light
windows, see-through sky blue title bars and a see-through dark blue panel.
The second, **Aye3wm** (`flickos-style-aye3`), also brings a layout of the
same name: its metainfo's `FlickOS::layout` makes *Use* set both, and the
layout lives in `/usr/share/flickos/layouts/aye3/` next to FlickOS's (only
FlickOS's own packages may: a community style can't bring a layout,
ADR-006). The third, **Footprint** (`flickos-style-footprint`), brings a
layout with a black top bar and a dock on the left edge. The fourth,
**Elemental** (`flickos-style-elemental`), brings light windows in one
grey with the elementary icons, and a layout with a thin see-through top bar
("Applications" on the left, the date and time in the middle), a light dock
at the bottom, and close on the left of the title bar with maximize on the
right.
A style package is an AppStream add-on of the layout chooser
(`<extends>flickos-layout.desktop</extends>` and a `FlickOS::style` custom
value naming its folder), which is how Software finds it; see
`packages/flickos-style-seven/` for the form. Other people publish their
styles the same way, as community packages (`repo/community/README.md`,
*Styles*): the style folder and window theme named after the package, only
a style's files in them, and `flickos-layout check` with no warning.

**The plain session.** To find out whether a problem comes from your own
changes, log in with **flickos-session-plain** (the login screen lists it under
flickos-session; `/etc/greetd/environments` from flickos-greeter; on a text
login, run it). It sets `FLICKOS_PLAIN=1`: flickos-layout then leaves out users'
styles (one in use becomes its FlickOS ancestor), the user's add-ons,
`~/.config/waybar` and `~/.config/mako`, refuses to change choices, and keeps
`$XDG_RUNTIME_DIR/flickos/plain/labwc/` as links to FlickOS's own labwc files
(the overlay's `rc.xml` and `environment` where it has them, the system's
`menu.xml` and `autostart`), and `flickos-session` starts `labwc -C` on that
folder, so `~/.config/labwc` is ignored. flickos-shortcuts reads that folder
too. Programs the user starts (foot, fuzzel) still read their own configs.
Nothing of the user's is changed.

### Your own layout

Users make layouts of their own the same way, in
`~/.local/share/flickos/layouts/ID/` (flickos-layouts 1.56). flickos-layout
looks there first, then in `flickos/layouts` below each `XDG_DATA_DIRS`
folder, then in FlickOS's own; the first folder with an id wins, and `doctor`
says when a user's layout hides FlickOS's. The chooser and Settings list
them after FlickOS's with "Yours" (a layout without `Preview=` gets a tile
with its name), and *Settings → About* says "(yours)" after it. The plain
session leaves them out. Design: [design/flickos-ricing.md](design/flickos-ricing.md),
phase 5.

```sh
flickos-layout layout new mybar --from traditional --name "My Bar"   # prints the folder
$EDITOR ~/.local/share/flickos/layouts/mybar/waybar.jsonc
flickos-layout check --layout mybar   # prints nothing when all is well
flickos-layout set mybar
flickos-layout watch                  # in a terminal: each save reloads the panel
flickos-layout set default            # FlickOS's layout again
```

**Waybar only.** A user's layout is a `layout.ini`, a waybar config and its
CSS, as in [Adding a layout](#adding-a-layout); `Dock=`/`DockStyle=` are
left out (`check` calls them an error). sfwbar is a beta FlickOS builds
itself, and its config language still changes (ADR-005). So a copy of
Cupertino has no dock, and a copy of Traditional has no window list.

**`layout new`** copies the layout in use (or `--from`) and changes its
`"include"` and `@import` paths into full ones,
`/usr/share/flickos/layouts/common/modules.jsonc` and `base.css`, so the
copy keeps getting FlickOS's fixes to the shared modules and CSS. The new
`layout.ini` keeps the corners, the start menu style and the title bar
buttons; a dock and desktops without a switcher are left out with a comment.
It never overwrites a layout that exists, FlickOS's included.

**Desktops** (flickos-layouts 1.55). `"flickos/desktops"` in a bar's modules
becomes one button per labwc desktop (`custom/desk#1` …, `#custom-desk` in
CSS, the current one with the class `active`); set `Desktops=N` in
`layout.ini` too. A click goes to that desktop, scrolling to the next or
previous one. waybar's supervisor follows labwc's desktops (ext-workspace)
and rewrites the buttons' files in `$XDG_RUNTIME_DIR/flickos/desktops/`;
`/usr/libexec/flickos/desktop N|next|previous` does the switching. labwc
doesn't tell other programs which desktop a window is on, so every desktop
always has a button.

**`flickos-layout check --layout ID`** reads only, one line per problem as for
styles (exit status 1 with an error). Errors: a `layout.ini` without
`Name=`/`Waybar=`/`Style=`, a waybar config that doesn't parse, an `include`
or `@import` that doesn't exist, `Dock=`. Warnings, each saying what is lost:
a `custom/` module used but defined nowhere, a color written out in the CSS
(it won't follow the style: use the named ones, HIG VIS-2), no apps button
(`custom/launcher`), no tray, no recording time (`custom/recording`), no Show
Desktop (`custom/desktop`), `Menu=`/`Quick=` not the corner of the bar with
the apps button or with `wireplumber` and `battery`, `Desktops=` without
`flickos/desktops`, and a module of yours on a signal FlickOS's buttons use
(8 tiling, 9 phone, 10 recording, 11 desktops). Since 1.58 it also names a
CSS mistake GTK can't read (line and column): the panel then uses FlickOS's
`common/base.css` in place of your CSS, since waybar would stop (see
[Panel tweaks](#panel-tweaks)). `check` without arguments includes the
user's layouts.

**`watch`** follows the user's layouts folder: a change to the layout in use
reloads the panel (its `layout.ini`, or desktop buttons added or removed,
apply it again); a change to another layout is checked.

**What stays the same for your layout** (HIG VIS-11): the module names in
`common/modules.jsonc`, `flickos/pinned` and `flickos/desktops`, the signals
8–11, `group/quick` and the classes FlickOS's buttons set. A layout's own
modules run commands, like `~/.config/waybar` would: a layout is shared only
as a reviewed package, never imported from a file (ADR-006).

### Panel tweaks

For changing the panel's look a little (text size, rounded or see-through
bars, room around a button, the dock's icons) without making a layout:
`~/.config/flickos/tweaks/style.css` (flickos-layouts 1.58, ricing phase 7,
ADR-015). It is imported after everything else in the generated panel CSS,
and its text is copied after the dock's CSS (sfwbar reads CSS from a string,
so its `@import`s and `url()`s are made absolute). One file for both: a rule
for waybar matches nothing in the dock, and the reverse. *Settings → Desktop
Layout & Style → Tweaks Folder* opens the folder; *About* says "panel
tweaks" while you have them. The plain session leaves them out.

```sh
flickos-layout tweaks new      # a starter with examples, all commented out; prints the path
flickos-layout watch           # in a terminal: each save shows at once
flickos-layout check           # names a mistake: FILE:LINE, the column and GTK's message
```

To turn an example on, delete the two lines around its rule that hold only a
comment mark (`/*` and `*/`). `--force` writes the starter over your file.

**A selector must be as strong as the layout's.** Tweaks come last, so they
win over a rule of the same strength, but not over a stronger one: `* {
font-size: 14px }` changes nothing on Redmond's clock (`#clock`) or
Cupertino's top bar (`window#waybar.topbar *`). The starter's examples are
strong enough for every FlickOS layout (`window#waybar.top` and
`window#waybar.bottom` are every bar: waybar gives each bar its position as a
class), and a test keeps them so. For anything else, `flickos-layout explain
panel` lists the files; copy the layout's selector. `window#waybar { margin }`
does nothing (waybar's `margin` setting in a layout does that), and a font too
tall for the bar makes the bar taller.

**A mistake never stops the panel.** waybar 0.12 exits on any CSS error it
can't parse (an unknown property, a missing `}`, a bad unit, an `@import` of a
missing file), at login and when reloaded, and after five restarts it gives
up. So before the panel reads any CSS of yours (the tweaks, your add-ons'
`style.css`, your own layout's), flickos-layout has GTK's own parser read it
in a child process, `/usr/libexec/flickos/check-css FILE…` (one JSON line per
file: `{"path": …}`, or with `"error": {"file", "line", "column",
"message"}`, maybe in a file it imports). A file it can't read is left out
with a warning in `panel.log`, `check` and `doctor`; while `watch` runs, a
broken save leaves the panel as it was. A misspelled color name isn't a
mistake to GTK: that rule only does nothing. Files that passed are
remembered by their text, their imports' and GTK's version in
`~/.cache/flickos/css-checked.json`, so a login with unchanged files runs no
check, and users without CSS of their own never do. Packages' CSS isn't
checked: FlickOS's own is tested (`GtkCheckerTest`), community styles have no
CSS.

---

## Window tiling

`flick-tiler` (package `packages/flick-tiler/`) arranges windows side by side
while labwc stays the window manager. It is off by default. Users turn it on
with **Super+T** or the panel button (left click: on/off, right click: choose
the arrangement, scroll: next arrangement). The choice is saved in
`~/.config/flickos/tiler`.

| Arrangement (`flick-tiler modes`) | Windows |
|---|---|
| `master-stack` (**default**) | Main window on the left (`MasterRatio`, 55%), the others stacked on the right |
| `columns` | Side by side, equal widths |
| `grid` | Rows and columns |
| `monocle` | All full screen; Super+J/K brings the next one to the front |

Keys while tiling is on:

| Key | Action |
|---|---|
| `Super+J` / `Super+K` | Focus the next / previous tiled window |
| `Super+Shift+J` / `Super+Shift+K` | Move the focused window forward / back |
| `Super+Shift+Enter` | Make the focused window the main one |
| `Super+M` | Next arrangement |
| `Super+[` / `Super+]` | Main window narrower / wider |
| `Super+Shift+T` | Tile the focused window (a window that was open before tiling, or was dragged out) |
| `Super+Shift+F` | Let the focused window float |

**How it works.** labwc 0.8 has no way for another program to move a window.
It does have *regions*: named rectangles in percent of the screen, to which a
window is tiled with `SnapToRegion`. When labwc reloads its config, every
window follows the new geometry of its region, and a window whose region is
gone is released (it floats, centered). So:

1. The daemon (`flick-tiler daemon`) follows the windows over
   wlr-foreign-toplevel. Autostart starts it at login and it runs for the
   whole session, tiling on or off, so Super+T takes effect at once. A lock
   (`tiler/daemon.lock`) allows one daemon at a time. While tiling is off it
   writes no fragment, so labwc runs with the plain FlickOS config.
2. It writes a fragment, `$XDG_RUNTIME_DIR/flickos/tiler/labwc.xml`:
   one region per tiled window (`ft1`, `ft2`, …), a window rule that snaps every
   new window to the next unused region, the keys above and `<core><gap>`.
3. `flickos-layout reconfigure` merges the fragment into the rc.xml overlay
   (like the layout's window buttons) and reloads labwc.
4. When a window opens or closes, is minimized, or the arrangement or order
   changes, the daemon computes the regions again. Moving a window only swaps
   the geometry of two regions.

Turning tiling off deletes the fragment, so labwc releases every window.
A fragment left by a daemon that died is deleted by the next `flick-tiler off`
or daemon start.

The panel button keeps no process running: waybar runs `flick-tiler status`
once, again after each click, and whenever flick-tiler sends it `SIGRTMIN+8`
(`"signal": 8` in `modules.jsonc`, `PANEL_SIGNAL` in `flick-tiler`). Idle cost
while tiling is off: nothing; while on: the daemon, about 18 MB.
Dialogs (windows with a parent) and the app ids in `Float=` are released right
after they open.

**Show Desktop.** The slim strip at the right end of the panel
(`custom/desktop` in `modules.jsonc`, drawn by `base.css` as a faint line with
no icon, lit on hover; as in Windows 7, pushing the pointer into the corner
hits it) and **Super+Shift+D** (flickos-settings' rc.xml) run `flick-tiler
show-desktop`, which the daemon answers whether tiling is on or off: it minimizes every shown window (dialogs follow
their parent), and while none is shown, it gives back the ones it minimized,
the focused one last. A window opened in between is hidden alone next time,
and only it comes back. Windows the user minimized stay minimized. labwc 0.8
has no `ToggleShowDesktop` action (0.9 does), and nothing else can tell labwc
to run an action, so the daemon does it over wlr-foreign-toplevel.

Problems: [07 – Window tiling](07-troubleshooting.md#window-tiling-flick-tiler)
has the symptom-by-symptom guide, the runtime files and how to watch the
daemon.

**Limits:** windows that were already open when tiling was turned on stay
floating until Super+Shift+T (labwc runs window rules only when a window
opens); a notification says how many. A window dragged out of its place still counts
until it is tiled again or closed. All outputs use the same arrangement, and
tiling doesn't know about desktops (Traditional's): labwc doesn't tell it which
desktop a window is on, so it arranges the windows of all desktops together,
and a desktop has empty places where another desktop's windows are.
Two windows that open in the same instant can land in the same place.

- **Defaults for everyone:** `etc/xdg/flickos/tiler.conf` (`Enabled=yes` turns
  it on for users who haven't chosen).
- **A new arrangement:** add it to `MODES` and `arrange()` in `flick-tiler`,
  and an icon rule `#custom-tiler.ID` in flickos-layouts' `layouts/common/base.css`.
- **Keys:** `KEYBINDS` in `flick-tiler`; Super+T itself is in flickos-settings'
  `rc.xml`, so it works while tiling is off.
- **Try it without a package:** `flick-tiler` needs no install to run
  (`FLICK_TILER_PREFIX=packages/flick-tiler packages/flick-tiler/usr/bin/flick-tiler daemon`
  inside a labwc session), but `flickos-layout reconfigure` must be the
  installed 1.7 or later.

## Wallpaper

Each [style](#styles-darklight) has its own wallpaper (`Wallpaper=wallpaper.png`
in `style.ini`): the halo, FlickOS's logo drawn large in the brand amber, on
dark for Dark, on light for Light. Switching the style switches it; switching the layout keeps it. At
login, autostart runs `flickos-layout wallpaper`, which shows the first of
these that exists:

1. **The user's choice in waypaper** (*Settings → Wallpaper*, or the chooser's
   *Wallpaper…* button): `waypaper --restore`.
2. **`~/.config/flickos/wallpaper`** (an image file or a link to one; the older
   way, still supported): `swaybg`.
3. **The layout's wallpaper** (`Wallpaper=` in `layout.ini`; FlickOS's
   layouts have none): `swaybg`.
4. **The style's wallpaper:** `swaybg`.
5. **flickos-settings' `/usr/share/backgrounds/flickos/default.jpg`**
   ([Artwork](#artwork)), for styles without one.

A choice whose image no longer exists is skipped. A user's own wallpaper (1 or 2)
is never replaced by a layout or style switch, and `flickos-layout doctor`
reports it. To follow the styles again, the user deletes the `wallpaper =` line
in `~/.config/waypaper/config.ini` (or `~/.config/flickos/wallpaper`).

**Older wallpapers:** until flickos-layouts 1.37 each layout showed its own
Unsplash photo. They stay installed at `/usr/share/backgrounds/flickos/ID.jpg`
(the paths waypaper always showed them at, so a user who picked one there keeps
it), next to `flickos-dark.png` and `flickos-light.png` (links to the styles'
wallpapers). Anyone can pick any of them in *Settings → Wallpaper*. A user who
never picked one gets the new wallpaper at their next login after the upgrade.

**Layout or style switch:** `flickos-layout set ID` and `style set ID` start
`swaybg` with the new wallpaper, wait half a second so it is drawn, then stop
the old one. They only replace a `swaybg` whose image is under
`/usr/share/flickos/layouts/`, `/usr/share/flickos/styles/` or
`/usr/share/backgrounds/flickos/`, and only while the user has no own choice.

**Replace a style's wallpaper:** put a PNG (or a JPEG, and change
`Wallpaper=` and `debian/links`) at
`packages/flickos-layouts/usr/share/flickos/styles/ID/wallpaper.png`, at least
1920×1080, at most 3840 px wide (each one adds to the ISO). Make sure you have
the right to redistribute it, and record its author and license in
flickos-layouts' `debian/copyright` (the current ones are FlickOS's own work,
rendered from `packages/flickos-layouts/artwork/wallpaper-ID.svg`, which isn't
installed). Then run `tools/make-layout-previews.sh` (the previews show
Dark's) and bump flickos-layouts. `tests/test_styles.py` checks every style
has one, linked into `/usr/share/backgrounds/flickos/`. To scale down a large
photo, or drop a PNG's unused alpha channel:

```sh
magick photo.jpg -auto-orient -resize '3840x2560>' -strip -quality 88 wallpaper.jpg
magick in.png -alpha off -strip wallpaper.png
```

**Scaling:** `swaybg … -m fill` in `swaybg_command()` in `flickos-layout` (and
the fallback in the autostart script). The modes are `fill` (crop), `fit`
(letterbox, uses the `-c` color around the image), `stretch`, `center` and
`tile`. In waypaper, the user picks one.

### waypaper (Settings → Wallpaper)

[waypaper](https://github.com/anufrievroman/waypaper) is a GTK 3 wallpaper
picker that runs swaybg. Debian trixie doesn't have it, so FlickOS packages
it: `packages/waypaper/` is upstream's code, installed as is (nothing is
built). `debian/README.source` there lists the FlickOS changes and how to
update to a new upstream release. It is a Depends of flickos-desktop, so
installed systems get it too.

FlickOS defaults are in `/etc/xdg/waypaper/config.ini` (a FlickOS patch in
`config.py` reads it before the user's config): the folders
`/usr/share/backgrounds/flickos` (the styles' wallpapers, the layouts' older
photos and the default) and
`~/Pictures`, backend `swaybg`, mode `fill` and the Arc-Dark background color.
Don't put `wallpaper =` there: that would count as every user's own choice.

---

## Default apps

"Default apps" means two different things.

### A. Which apps are installed

Edit `packages/flickos-desktop/debian/control`. Follow
[04 – Adding or removing a desktop package](04-packages.md#adding-or-removing-a-desktop-package)
and read the Recommends caveat in [04](04-packages.md#flickos-desktop-meta-package).

Current defaults (all in `Recommends:`):

| Purpose | Package | Desktop file |
|---|---|---|
| Web browser | `firefox-esr` | `firefox-esr.desktop` |
| Ad blocker for Firefox (on by default) | `webext-ublock-origin-firefox` | none |
| Text editor | `mousepad` | `org.xfce.mousepad.desktop` |
| Image viewer | `ristretto` | `org.xfce.ristretto.desktop` |
| PDF viewer | `evince` | `org.gnome.Evince.desktop` |
| Office suite | `libreoffice-writer`, `-calc`, `-impress`, `-draw`, `-gtk3`, `hunspell-en-us`, `hyphen-en-us` | `libreoffice-writer.desktop`, `libreoffice-calc.desktop`, `libreoffice-impress.desktop` |
| Media player | `vlc` | `vlc.desktop` |
| Archive manager | `xarchiver`, `thunar-archive-plugin` (Extract Here in Thunar) | `xarchiver.desktop` |
| Task manager | `lxtask` | `lxtask.desktop` |
| File manager | `thunar` | `thunar.desktop` (then `pcmanfm.desktop`, for systems installed before Thunar) |
| Terminal | `foot` | `foot.desktop` |
| Display settings | `wdisplays` | `network.cycles.wdisplays.desktop` |
| Network settings | `nm-connection-editor` | `nm-connection-editor.desktop` |
| Sound settings | `pavucontrol` | `org.pulseaudio.pavucontrol.desktop` |
| Bluetooth | `blueman` | `blueman-manager.desktop` |
| Printers | `cups`, `system-config-printer` | `system-config-printer.desktop` |
| Software and updates | `flickos-software` (FlickOS's own *Software*, a Depends; see [04](04-packages.md#flickos-software)), `gnome-package-updater` | `flickos-software.desktop`, `org.gnome.PackageUpdater.desktop` |
| CPU microcode (no app) | `intel-microcode`, `amd64-microcode` | – |

**Check the cost before adding an app.** A small app can pull in large
libraries. Atril, for example, brought a whole web engine (~200 MB) for EPUB
support, so FlickOS uses Evince (~20 MB) instead. Check on a trixie machine:

```sh
tools/package-cost.py PACKAGE     # every package it adds to the image, and their KB
```

A package's own `Installed-Size` says little: wf-recorder is 152 KB, but it
adds 16 packages and 57 MB to the image. The script compares with the last
build's package list, so what your own computer happens to have doesn't hide
anything ([02](02-building-and-testing.md#measuring-what-a-change-costs)).

After a build, `flickos-amd64.packages` lists everything in the image, and the
boot test's `memory.txt` shows memory use ([02](02-building-and-testing.md#results)).

**Swapping an app** (e.g. Chromium instead of Firefox) touches three places:

1. `flickos-desktop/debian/control`: replace the package.
2. `flickos-settings/etc/xdg/flickos/mimeapps.list`: replace the desktop file name.
3. `flickos-settings/etc/xdg/labwc/menu.xml`, `rc.xml` and
   `flickos-installer/etc/xdg/flickos-live/labwc/menu.xml`: only if the app is
   called by name. The terminal, browser and file manager are not: Super+Enter
   and the menu run `xdg-terminal-exec` (FlickOS's default:
   `flickos-settings/etc/xdg/flickos/xdg-terminals.list`), Super+B and Super+E
   run `/usr/libexec/flickos/open-default browser|files`, which start the
   `mimeapps.list` default. A new terminal needs only a line in `xdg-terminals.list`.

Find a package's desktop file name: `dpkg -L PACKAGE | grep '\.desktop$'`.

### B. Which app opens which file type

File: `packages/flickos-settings/etc/xdg/flickos/mimeapps.list`.

```ini
[Default Applications]
application/pdf=org.gnome.Evince.desktop
image/png=org.xfce.ristretto.desktop
```

- Find a file's MIME type in a VM: `xdg-mime query filetype somefile.pdf`.
- Check the result: `xdg-mime query default application/pdf`.
- Only reference apps that are installed. Other entries are ignored.
- Users override with `~/.config/mimeapps.list`.

Users choose their own in *Settings → Default Applications*, which writes
`~/.config/mimeapps.list` (`xdg-mime default`) and `~/.config/xdg-terminals.list`.

### Default terminal and browser alternatives

FlickOS's own keys, menu and launcher use the user's choice (above). Other
programs asking the system for "a terminal" or "a browser" (`x-www-browser`) use
Debian's *alternatives*, which are system-wide. foot and firefox-esr register themselves for these.
Check with `update-alternatives --display x-terminal-emulator` and
`update-alternatives --display x-www-browser`.

---

## Settings window

*Settings → All Settings* opens the Settings window (package `flickos-control`,
see [04](04-packages.md#flickos-control)). Every page runs the command that owns
the setting, so the window, the panel, the keys and the command line always
agree. Mouse, touchpad and keyboard settings are flickos-control's own.

| Page | Runs |
|---|---|
| Desktop Layout & Style | `flickos-layout list/current/set`, `style …`, `clicks …`, `doctor` |
| Mouse & Touchpad, Keyboard, Power & Idle | `flickos-control set KEY VALUE` (`flickos-control get` lists them); the system layout: `pkexec /usr/libexec/flickos/control-helper keyboard …` |
| Default Applications | `xdg-mime default APP TYPES…`; the terminal: `~/.config/xdg-terminals.list` |
| Date & Time | `timedatectl set-timezone`, `set-ntp` |
| Login | `pkexec /usr/libexec/flickos/control-helper autologin-on`, `autologin-off` |
| Firewall | `pkexec /usr/libexec/flickos/control-helper firewall-on`, `firewall-off` (`ufw --force enable`, `ufw disable`); state from `/etc/ufw/ufw.conf` |
| About | `flickos-control about` (also `lspci`, `dpkg-query`); *Copy System Info*: `wl-copy` |
| Tiling | `flick-tiler status/modes/on/off/mode/ratio/gap/floating` |
| Keyboard Shortcuts | `flickos-shortcuts list`, `show` |
| More Settings | the apps in `TILES` (the same as the Settings menu) |
| Privacy | `flickos-countme status`, `enable`, `disable` (shown while flickos-countme is installed) |

- **Add a tile for another settings app:** a line in `TILES` in
  `usr/bin/flickos-control` (id, name, icon names, command). Tiles of apps that
  aren't installed are hidden, so a Recommends is enough. Add the app to the
  Settings menu too (both files, see [Menu entries](#menu-entries)).
- **Change the mouse, touchpad, keyboard, idle or zoom defaults for everyone:**
  uncomment lines in `/etc/xdg/flickos/input.conf`, `keyboard.conf`,
  `idle.conf` or `zoom.conf` (conffiles of flickos-control). Users' own choices still win.
- **Add a mouse, touchpad or keyboard option:** a `Setting` in `SETTINGS`
  (labwc category and element, default) and a `control()` row on the page.
  Check the element in labwc's `src/config/rcxml.c` first: labwc ignores what
  it doesn't know, without a message. The tests compare every option against
  their copy of labwc 0.8.3's list (`LABWC_LIBINPUT`, `LABWC_KEYBOARD`); add
  it there if it is new in labwc.
- **Add a page:** a class with `widget` and `shown()` (called each time the
  page is shown) in `PAGE_CLASSES`, and a `Page` in `PAGES`. Read and change
  the setting through the command that owns it; if that command lacks
  something, add it there (that is how `flick-tiler floating` came about).
  Use stock GTK widgets only: they follow both styles without CSS.
- **Try it without building:** run `usr/bin/flickos-control --page ID` from the
  source tree inside the session; set `FLICKOS_LAYOUT_PREFIX` to
  `packages/flickos-layouts` to see the layout previews from the tree.

The design and its decisions are in
[design/flickos-control.md](design/flickos-control.md).

---

## Weekly count

Installed systems send one anonymous request a week, so FlickOS knows how many
computers run which version ([PRIVACY.md](../PRIVACY.md), package
[`flickos-countme`](04-packages.md#flickos-countme)). It is on by default and
turned off in *Settings → Privacy*; the installer says so on its first
slideshow slide, and the live session never sends it. Systems installed before
the count existed get it with an update and are counted the same way.

- **The server:** `server/countme/` (its README), deployed at
  `https://flickos-countme.dvbondoy.workers.dev`; `URL` in `packages/flickos-countme/usr/bin/flickos-countme`
  points at its `/v1/countme`. Moving it means a new `URL` and a package bump;
  computers that haven't upgraded keep sending to the old address. While `URL`
  is empty, nothing is sent.
- **Read the numbers:** <https://flickos-countme.dvbondoy.workers.dev/v1/stats>, or the SQL in the server's README.
- **Change the installer's notice:** the first slide of
  `packages/flickos-installer/etc/calamares/branding/flickos/show.qml`.
  Calamares 3.3's summary page takes no text of its own.
- **Send something more:** don't, without a new entry in PRIVACY.md and an
  installer question. Every value sent must stay coarse enough that it can't
  tell computers apart.
- **Test against a local server:** `npx wrangler dev` in `server/countme/`,
  `Url=http://127.0.0.1:8787/v1/countme` in `/etc/flickos/countme` of a test
  system, then `sudo systemctl start flickos-countme` and
  `journalctl -u flickos-countme`. `flickos-countme run --dry-run` prints the
  request without sending it.

---

## Menu entries

### A. labwc root menu (right-click on the desktop)

Which clicks open it is a user setting: [Desktop clicks](#desktop-clicks).

| Session | File |
|---|---|
| Installed system | `packages/flickos-settings/etc/xdg/labwc/menu.xml` |
| Live session | `packages/flickos-installer/etc/xdg/flickos-live/labwc/menu.xml`: the same menu plus *Install FlickOS* at the top |

**Change both files** when you edit the menu. The live copy only differs in
its first two lines inside `root-menu`. `tools/check-menus.py` (run by
`tools/build-iso.sh`) fails if the files differ in anything else except comments
and whitespace.

Current structure: Terminal, Web Browser, Files, Applications; **Office**
(Writer, Calc, Impress); Media Player; **Settings**
(Desktop Layout & Style, Wallpaper, Appearance, Displays, Network, Sound, Bluetooth, Printers, Reload Desktop Config);
**Session** (Lock Screen, Log Out, Suspend, Reboot, Shut Down).

Add an item:

```xml
<item label="Text Editor"><action name="Execute"><command>mousepad</command></action></item>
```

Add a submenu. Every `id` must be unique:

```xml
<menu id="office-menu" label="Office">
  <item label="Writer"><action name="Execute"><command>libreoffice --writer</command></action></item>
</menu>
```

`systemctl reboot`/`poweroff`/`suspend` work without sudo for the user at the
machine. logind allows the active local session to do this. Reference:
`man labwc-menu`, `man labwc-actions`. Test menu changes in a VM with *Settings →
Reload Desktop Config*.

### B. App launcher (fuzzel, `Super+D`)

fuzzel lists every `.desktop` file in `applications/` folders under
`XDG_DATA_DIRS`. Installed packages add their own entries.

**Add an entry for a command:** create e.g.
`packages/flickos-settings/usr/share/applications/flickos-about.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=About FlickOS
Comment=Version and system information
Exec=foot -H sh -c 'cat /etc/os-release; uname -a'
Icon=help-about
Terminal=false
Categories=System;
```

Add `usr/share/applications/*   usr/share/applications/` to
`flickos-settings/debian/install`. Validate with `desktop-file-validate FILE`
(package `desktop-file-utils`). Only use `flickos-` file names, so they never
clash with another package.

**Hide another package's entry:** copy its desktop file into
`packages/flickos-settings/usr/share/flickos/applications/` under the **same
file name**, and add `NoDisplay=true` directly under the `[Desktop Entry]` line.
The copy wins because `/usr/share/flickos` comes first in `XDG_DATA_DIRS`.
Example candidates: `org.xfce.mousepad-settings.desktop`, `blueman-adapters.desktop`.

---

## Add-ons

An add-on puts a program that isn't a FlickOS package (an experiment, or a
third-party tool) on the desktop without touching the user's own
labwc or waybar config.
flickos-layouts reads one folder per add-on and regenerates the overlay from
it at every login:

| File in `NAME/` | What it does |
|---|---|
| `labwc.xml` | `<keyboard>` keybinds and `<windowRules>`, merged into the overlay rc.xml after flickos-control's and flick-tiler's fragments. Anything else (`<core>`, `<libinput>`, keyboard options) is left out, and so is a keybind for a key the desktop already binds. Give each keybind `description="…"` for the shortcut sheet (HIG INT-5): flickos-layout takes it out before labwc reads the file |
| `waybar.jsonc` | `{"custom/NAME": {…}}`: panel buttons, placed just before the tiling button (after the phone's) in every layout. A module the layout already has (`custom/tiler`, `custom/phone`, …) is left out |
| `style.css` | Imported after the layout's CSS. Named colors only (`@fg_color`, `@error_color`, …) so it follows Dark and Light. A user's is read by GTK first and left out if it has a mistake ([Panel tweaks](#panel-tweaks)) |

The folder is `~/.config/flickos/addons/NAME/`, or
`/usr/share/flickos/addons/NAME/` for one a package ships. The user's wins, so
an empty user folder turns a system add-on off. `NAME` is lowercase letters,
digits, `-` and `_`. After a change:

```sh
flickos-layout addons        # name, folder, files found
flickos-layout reconfigure   # keys and window rules
flickos-layout reload-panel  # panel button and style
```

Problems (a broken file, a key already in use) are warnings in
`$XDG_RUNTIME_DIR/flickos/panel.log` at login, or on the terminal when run by
hand. Starting the program is not the add-on's job: use an XDG autostart entry
(*Settings → Startup Applications*).

A package that ships its add-on in `/usr/share/flickos/addons/NAME/` can hide
it for one user without touching the system folder: an empty folder of the
same name in `~/.config/flickos/addons/` wins and has no files, so no keys,
no panel button and no style (checked 2026-10-04). Delete that folder to get
the system add-on back.

---

## Your own labwc files

A user's own files in `~/.config/labwc/` are **merged** over FlickOS's:
`flickos-session` starts `labwc -m` (`--merge-config`), which reads the
system's files, then the layout overlay's, then the user's, each later key or
setting winning. So a small `rc.xml` with one key, a `<core><gap>`, a
`themerc-override` with one color or an `environment` with one variable adds
to FlickOS's and keeps every FlickOS key, the layout's window buttons and
theme, the desktop clicks, tiling and Settings' options. labwc's own example
files are written for a labwc without FlickOS, so don't copy them whole.

| In your file | What happens |
|---|---|
| A `<keybind>` | Added; one for a key FlickOS binds replaces FlickOS's |
| `<keybind key="W-t"><action name="None" /></keybind>` | Removes that key (here FlickOS's Super+T) |
| `<core>`, `<theme>`, `<margin>` … options | Set over FlickOS's |
| `<windowRules>`, `<regions>` | Added to FlickOS's |
| `menu.xml` with menus of **their own ids** | Added; a `root-menu` (or another id FlickOS's `menu.xml` uses) would be ignored, see below |

Merging is **off**, and the user's files replace FlickOS's as they always did,
when it would break FlickOS (`merge_decision` in flickos-layout, decided at
every login; [design ADR-003](design/flickos-ricing.md)):

| When | Why | To merge instead |
|---|---|---|
| The live session or the plain session | No user files in the one; the other ignores them | — |
| `rc.xml` is a copy of FlickOS's (its header comment, "FlickOS labwc defaults", is in it) | It would bring back keys you left out on purpose | Keep only your changes, without the comment |
| `rc.xml` has `<default />` (keyboard or mouse) | labwc's own keys would come back over FlickOS's (Super+Enter, Alt+F3, Super+A, the volume keys, the desktop clicks) | Delete the `<default />` lines |
| `menu.xml` defines a menu id FlickOS's has (`root-menu`, `office-menu`, …) | labwc keeps the first one read, FlickOS's | Give your menus ids of their own |
| `~/.config/labwc/autostart` exists | Every autostart would run, FlickOS's too | Start programs from *Settings → Startup Applications*, delete it |

A change takes effect at the next login: labwc's `-m` is chosen when it
starts. Until then a merging session stays merging, so a `<default />` added
during it brings labwc's own keys back over FlickOS's at the next reload
(Super+Enter then runs labwc's `lab-sensible-terminal`, which isn't
installed); `doctor` and `watch` say so, and deleting the line and running
`labwc --reconfigure` gets FlickOS's keys back at once. `flickos-layout explain labwc` says whether it merges and why not,
`flickos-layout doctor` (and `check`) what to change, and flickos-shortcuts'
sheet reads the files the way labwc does. While merging, `prepare` leaves
`$XDG_RUNTIME_DIR/flickos/labwc-merge`; the session script, flickos-shortcuts,
`explain` and `doctor` read it.

---

## Keybindings

File: `packages/flickos-settings/etc/xdg/labwc/rc.xml`, section `<keyboard>`.

### Current bindings

`<default />` at the top loads labwc's built-in bindings. FlickOS's own
bindings follow, and replace defaults that use the same key.

| Key | Action | Source |
|---|---|---|
| Hold `Super` alone | Keyboard shortcut sheet until Super is let go ([Shortcut sheet](#shortcut-sheet-hold-super)) | FlickOS |
| `Super+Enter` | Terminal (foot) | FlickOS |
| `Super+D`, `Alt+F3` | App launcher (fuzzel); closes it when it is open | FlickOS |
| `Super+E` | Files (Thunar) | FlickOS |
| `Super+B` | Web browser | FlickOS |
| `Super+V` | Clipboard history | FlickOS |
| `Super+Esc` | Task manager (lxtask) | FlickOS |
| `Super+Q`, `Alt+F4` | Close window | FlickOS, labwc |
| `Super+L` | Lock screen (`/usr/libexec/flickos/lock`: the background chosen in *Settings → Power & Idle*) | FlickOS |
| `Super+Shift+E` | Log out | FlickOS |
| `Super+Shift+D` | Show Desktop: minimize every window, again to bring them back ([Window tiling](#window-tiling), `flick-tiler show-desktop`) | FlickOS |
| `Super+T` | Window tiling on/off; more keys while it is on ([Window tiling](#window-tiling)) | FlickOS |
| `Print` / `Shift+Print` | Screenshot of an area (chosen on a frozen screen) / every screen, saved in `~/Pictures/Screenshots` and copied (flickos-screenshot) | FlickOS |
| `Super+Shift+S` | Screenshot bar: area or every screen, photo or video, with a delay of 3, 5 or 10 seconds | FlickOS |
| `Super+Shift+R` | Record the screen (the bar with Video chosen), or stop the recording; the panel shows the time and stops it too | FlickOS |
| Play/pause, stop, next, previous keys | `playerctl` (any MPRIS player: VLC, Firefox, …) | FlickOS |
| `Ctrl+Print` | Screenshot of an area, copied only | FlickOS |
| Volume / mic mute keys | `wpctl` (PipeWire) | FlickOS |
| Brightness keys | `brightnessctl` | FlickOS |
| `Alt+Tab` / `Alt+Shift+Tab` | Next / previous window | labwc |
| `Super+A` | Toggle maximize; [Quick Settings](#quick-settings) while that is on | labwc, FlickOS |
| `Alt+Arrows` | Move window to screen edge | labwc |
| `Super+Arrows` | Snap window to half the screen | labwc |
| `Alt+Space` | Window menu | labwc |

The full list of labwc defaults is in `man labwc-config` (section `<keyboard><default />`).

**Keep `<default />` in FlickOS's own `rc.xml`.** Without it, defining any
keybind turns off *all* of labwc's built-in bindings: no Alt+Tab, no
snapping. A user's own `rc.xml` must **not** have it: merged after FlickOS's,
it would bring labwc's keys back over FlickOS's, so such a file replaces
FlickOS's instead ([Your own labwc files](#your-own-labwc-files)).

### Adding or changing a binding

```xml
<keybind key="W-t"><action name="Execute"><command>mousepad</command></action></keybind>
```

- **Key format:** modifiers joined with `-`, then the key: `W-` Super, `A-` Alt,
  `C-` Ctrl, `S-` Shift. Examples: `W-S-Return`, `C-A-Delete`, `XF86AudioPlay`.
- **Find a key's name:** run `wev` (package `wev`) in a VM session, press the
  key and read the `sym:` field.
- **Shell syntax** (`&&`, `$(…)`) needs `sh -c '…'`, and `&` must be written
  `&amp;` in XML. See the clipboard binding (`W-v`) for an example.
- **Actions** other than `Execute` (e.g. `ToggleFullscreen`, `GoToDesktop`):
  `man labwc-actions`.
- **Test** in a VM: edit `/etc/xdg/labwc/rc.xml`, then *Settings → Reload Desktop
  Config*. When overriding a labwc default, check yours is the one that runs.

A user's own `~/.config/labwc/rc.xml` is merged over FlickOS's: its keys are
added, a key it binds again replaces FlickOS's, and `<action name="None" />`
removes one. It replaces FlickOS's file only when it is a copy of it or has
`<default />` ([Your own labwc files](#your-own-labwc-files)).

### Shortcut sheet (hold Super)

Holding Super on its own for 0.7 s shows the shortcuts until Super is let go
(package `flickos-shortcuts`, see [04](04-packages.md#flickos-shortcuts)). The
sheet reads the rc.xml labwc uses, so a new binding shows up by itself. What it
says about a binding:

- **A command FlickOS knows** (`COMMANDS` in `flickos-shortcuts`: a regex on
  the command, a section and a description). Add a line there when you add a
  binding, or it shows as *Run PROGRAM* under *Other*.
- **A labwc action** (`ACTIONS`): `Close`, `ToggleMaximize`, `SnapToEdge`, …
  Unknown actions show their name (`ToggleDecorations` → *Toggle decorations*).
- Keys with the same description share a row; `XF86…` keys are left out.

Try it without building: `flickos-shortcuts list` prints what the sheet shows
(`--file` for another rc.xml). The hold time is `HOLD_MS`, the look
`usr/share/flickos/shortcuts/style.css` (the GTK theme's named colors only, so the Light style recolors it).

It can't tell a long press of Super alone from Super held while pressing
other keys (labwc sends it only the modifiers), so holding Super through
several shortcuts (Super+J, J, J with tiling) also shows the sheet. It lets
keys and clicks through, so this only costs the view.

---

## Program defaults

Where each program's FlickOS defaults live, all in `packages/flickos-settings/`.
The **method** depends on where the program looks for config and whether
Debian already ships a file there.

| Program | File | Method | Reference |
|---|---|---|---|
| labwc | `etc/xdg/labwc/rc.xml`, `menu.xml`, `autostart`, `environment` | Direct: no Debian file there | `man labwc-config` |
| foot | `etc/xdg/flickos/foot/foot.ini` | `XDG_CONFIG_DIRS`; included by the [style](#styles-darklight) overlay | `man foot.ini` |
| fuzzel | `etc/xdg/flickos/fuzzel/fuzzel.ini` | `XDG_CONFIG_DIRS`; included by the style overlay | `man fuzzel.ini` |
| Default apps | `etc/xdg/flickos/mimeapps.list` | `XDG_CONFIG_DIRS` | [Default apps](#b-which-app-opens-which-file-type) |
| Thunar | `etc/xdg/xfce4/xfconf/xfce-perchannel-xml/thunar.xml` (settings), `etc/xdg/flickos/Thunar/uca.xml` (right-click actions) | xfconf's system defaults (direct); `XDG_CONFIG_DIRS` | [Thunar](#thunar-file-manager) |
| Night light | `usr/libexec/flickos/night-light` | Script started from autostart (through `flickos-control night-light`) | `man wlsunset` |
| waybar | flickos-layouts: `usr/share/flickos/layouts/ID/`, `common/`, `styles/ID/waybar-colors.css` (fallback: flickos-settings' `usr/share/flickos/waybar/`) | Files generated in `$XDG_RUNTIME_DIR/flickos/waybar/`, paths passed by `flickos-layout panel` | [waybar](#waybar-panel), `man waybar`, `man waybar-styles` |
| mako | `usr/share/flickos/mako/config` | Included by `$XDG_RUNTIME_DIR/flickos/mako/config`, passed by `flickos-layout panel` | `man 5 mako` |
| GTK apps | `usr/share/glib-2.0/schemas/90_flickos-settings.gschema.override` | GSettings override | `man glib-compile-schemas` |
| Window borders, title bars, menus | `usr/share/themes/FlickOS-Arc-Dark/labwc/themerc`, selected in `rc.xml`; `FlickOS-Arc` for the Light style | labwc theme | `man labwc-theme` |
| Cursor in labwc | `etc/xdg/labwc/environment` | Direct | `man labwc-config` |
| Keyboard layout | `usr/bin/flickos-session` | Session script (flickos-greeter's `greeter` does the same for the login screen) | `man xkeyboard-config` |
| Login screen | flickos-greeter: `usr/share/flickos/greeter/gtkgreet.css` | `gtkgreet --style` | [Login screen](#login-screen), `man gtkgreet` |

### The Arc-Dark palette

FlickOS's look is **arc-theme's Arc-Dark**. GTK apps get it from the GTK theme;
everything GTK themes don't reach (panel, terminal, launcher, notifications,
window borders, lock screen, boot menus, boot splash, login screen, installer,
artwork) uses the same colors, written into their own config files:

| Role | Color | Used for |
|---|---|---|
| `wm_bg` | `#2f343f` | Title bars, panel, installer sidebar |
| `bg_color` | `#383c4a` | Terminal, launcher, notifications, menus, boot splash, lock screen |
| `base_color` | `#404552` | Hover and active highlights |
| `borders` | `#2b2e39` | Borders, progress-bar track, terminal black |
| `fg_color` | `#d3dae3` | Text |
| `wm_title` | `#cfdae7` at 80 % (50 % unfocused) | Window titles |
| `selected_bg_color` / `selected_fg_color` | `#5294e2` / `#ffffff` | Accent, selections (white on blue) |
| `warning_color` / `error_color` / `success_color` | `#f27835` / `#fc4138` / `#73d216` | Battery warning, critical notifications, terminal colors |
| `wm_icon_bg` | `#90939b` | Muted hints (boot menu help) |

The values come from arc-theme's compiled stylesheet
(`/usr/share/themes/Arc-Dark/gtk-3.0/gtk.gresource`, resource
`/org/gnome/arc-theme/gtk-main-dark.css`). To read them:
`gresource extract /usr/share/themes/Arc-Dark/gtk-3.0/gtk.gresource /org/gnome/arc-theme/gtk-main-dark.css | grep define-color`.

**`tools/check-palette.py`** lists every allowed color, including the terminal
colors, and checks all files that contain colors. `tools/build-iso.sh` runs it
before building and stops if a file uses a color outside the palette or the
labwc theme has an unknown key. When you change a color, change it in the file,
add it to the checker if it's new, and run `python3 tools/check-palette.py`.

**The brand color** is FlickOS's own amber, `#ffb13d`, with `#2f343f` for text on
it (6.89:1; white on amber is 1.81:1). It is only on the brand surfaces: the
logo, the boot menus, the boot splash, the installer and the artwork. The desktop
keeps Arc's blue (`docs/design/flickos-accent.md`). `tools/check-palette.py`
allows it only in `BRAND_FILES` and fails if any other file uses it. The Light
style's wallpaper uses a deeper amber, `#c98000`, which is readable on light.

The [Light style](#styles-darklight)'s files are checked against a second list
with **Arc**'s colors (`ARC_LIGHT`: `#f5f6f7` background, `#ffffff` content,
`#e7e8eb` title bars and panel, `#dcdfe3` borders, `#5c616c` text, `#525d76`
title text, same accent and warning colors) plus terminal colors: Arc's accent,
error, warning and success colors darkened until they are readable on the light
background (`FLICKOS_LIGHT_ADDITIONS`).
Regenerate the artwork afterwards with `tools/make-placeholder-art.sh`.

### foot (terminal)

`etc/xdg/flickos/foot/foot.ini`: font, padding, transparency and the 16-color palette.
Debian's `/etc/xdg/foot/foot.ini` lists every option (commented out). Check
syntax in a VM: `foot -c /etc/xdg/flickos/foot/foot.ini --check-config`.

- **Transparency:** `alpha=0.9` in `[colors]` (0.0 transparent – 1.0 opaque). The
  wallpaper shows through. labwc has no blur, so text over a busy wallpaper can
  be harder to read; raise the value if needed.
- **Colors:** Arc has no terminal colors. FlickOS uses colors from Arc-Dark's
  stylesheet where one fits (red = error, green = success, yellow = warning,
  blue = accent, cyan and the bright variants = colors Arc uses elsewhere).
  Only magenta, bright magenta and bright green are FlickOS additions.
- **Styles:** with the Light style, foot reads a generated file that includes
  this one, then `styles/light/foot.ini` from flickos-layouts
  ([Styles](#styles-darklight)). A color key added here must be added to every
  style's `foot.ini`.

### fuzzel (launcher)

`etc/xdg/flickos/fuzzel/fuzzel.ini`: font, size, icon theme (`Numix-Circle`),
colors (`RRGGBBAA`, where the last two digits are opacity; the background is
translucent) and border. The selected entry uses Arc's selection style: white
text on the accent blue. `keyboard-focus=on-demand` closes fuzzel when another
window takes the keyboard (a click on it), not only on Esc. A click on the
empty desktop closes it through the [desktop clicks](#desktop-clicks), and the
panel's launcher button and `Super+D` close it when it is open
(`pkill -x fuzzel || fuzzel`). With the Light style, `styles/light/fuzzel.ini`
overrides the colors and the icon theme (`Numix-Circle-Light`).

### Thunar (file manager)

Thunar keeps its settings in xfconf. Its daemon, xfconfd, is started by D-Bus
(a systemd user service) without the session's `XDG_CONFIG_DIRS`, so FlickOS's
defaults are in `/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/thunar.xml`, not
under `/etc/xdg/flickos` (no Debian package ships that file). It sets only what
differs from Thunar's own defaults: the location bar as buttons
(`last-location-bar` = `ThunarLocationButtons`; Thunar's default is the text
entry, and Ctrl+L still types a path), and a larger window (960×600) with a
wider side pane. xfconf reads the system file and then the user's
`~/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml`, which Thunar writes
when a setting changes; a property the user has is theirs from then on.

Check a value with `xfconf-query -c thunar -p /last-location-bar`, and list
the names Thunar knows in its source's `thunar-preferences.c`. Test in a VM,
or on a private bus without the user's file:

```sh
env -i HOME=/tmp/t PATH=/usr/bin:/bin XDG_CONFIG_HOME=/tmp/t \
    dbus-run-session -- xfconf-query -c thunar -p /last-location-bar
```

`etc/xdg/flickos/Thunar/uca.xml` holds the right-click custom actions: *Open
Terminal Here* (`xdg-terminal-exec --dir=%f`, the user's default terminal)
and *Send to Phone* (flickos-phone). It replaces Debian's
`/etc/xdg/Thunar/uca.xml`, whose terminal action needs Xfce's helpers. Thunar
reads only the first `uca.xml` it finds, starting with `~/.config/Thunar/`,
so the file has all of FlickOS's actions. Thunar writes its own copy there
when the user edits custom actions, and also when the file it read has an
action without `<unique-id>` (it saves the ids it made up). Debian's file has
none, so running Thunar once without flickos-settings 1.34 leaves a copy with
only Debian's action, which hides FlickOS's: delete
`~/.config/Thunar/uca.xml` and quit Thunar (`thunar -q`). Every action in
FlickOS's file has a `<unique-id>` so that this never happens with it. A
Thunar started by D-Bus (`org.freedesktop.FileManager1`, e.g. ristretto's or
Firefox's *Show in Folder*) runs as the systemd user service `thunar.service`,
which doesn't have the session's `XDG_CONFIG_DIRS`, so it read Debian's file
and left that copy too. Since flickos-settings 1.37 the drop-in
`usr/lib/systemd/user/thunar.service.d/flickos.conf` gives it FlickOS's
folders; a copy left before that still has to be deleted by hand (Settings'
*Phone* page warns while the user's file lacks Send to Phone).

### waybar (panel)

waybar only looks in `~/.config/waybar/` and `/etc/xdg/waybar/`, and Debian owns
the latter. So `/usr/libexec/flickos/autostart` runs `flickos-layout panel`,
which generates the chosen [desktop layout](#desktop-layouts)'s panel in
`$XDG_RUNTIME_DIR/flickos/waybar/` and starts `waybar -c … -s …` with it, but
only when the user has no config of their own. **The panel is edited in the
layouts** (`packages/flickos-layouts/usr/share/flickos/layouts/`), not here.

`packages/flickos-settings/usr/share/flickos/waybar/config.jsonc` and `style.css`
are only the **fallback**: started if `flickos-layout` fails or isn't installed.
Keep them working, but they aren't what users normally see.

- **Style:** layout CSS uses named colors from the style's
  `usr/share/flickos/styles/ID/waybar-colors.css` (Arc's own names, e.g.
  `@wm_bg`, `@selected_bg_color`). Bars are translucent:
  `alpha(@wm_bg, 0.85)` in `common/base.css`; raise the value towards `1.0` for
  solid bars.
- **Keep `"tray"`** in exactly one bar per layout: nm-applet and blueman live
  there. The unit tests enforce it.
- **Status icons:** volume and battery are icon-only (value in the tooltip);
  `common/base.css` draws symbolic icons from the icon theme with
  `-gtk-icontheme("NAME-symbolic")` per CSS class (`.muted`, `.warning`,
  `.charging`, ...). There is no waybar network module: nm-applet in the tray
  shows the connection and has the Wi-Fi menu.
- **Clicks:** volume opens pavucontrol, the launcher opens fuzzel
  (`common/modules.jsonc`).
- **Modules:** `man waybar-wlr-taskbar`, `man waybar-clock`, `man waybar-custom`,
  `man waybar-wireplumber`, `man waybar-battery`,
  `man waybar-tray`. Every module has its own page.
- **Test in a VM:** `flickos-layout set ID` regenerates and restarts the panel.
  To see waybar's own errors (JSON or CSS syntax), run it in a terminal:
  `pkill waybar; waybar -c $XDG_RUNTIME_DIR/flickos/waybar/config.jsonc -s $XDG_RUNTIME_DIR/flickos/waybar/style.css`.
  In a normal session waybar runs
  [supervised](#keeping-the-panel-running) and everything it prints is in
  `$XDG_RUNTIME_DIR/flickos/panel.log`.

### mako (notifications)

mako only reads `~/.config/mako/config`, so it follows the same pattern as
waybar: `flickos-layout panel` starts
`mako -c $XDG_RUNTIME_DIR/flickos/mako/config`, a generated file that includes
`usr/share/flickos/mako/config` (font, size, timeouts, Arc-Dark colors) and then
the style's `mako.conf` (colors only). If that fails, it starts
`mako -c /usr/share/flickos/mako/config`. A user's own `~/.config/mako/config`
is used as is. mako runs under the same
[supervisor](#keeping-the-panel-running) as the panel, and logs to
`$XDG_RUNTIME_DIR/flickos/panel.log` with it. Critical notifications have a red border and never time out. Test in a VM: `notify-send "Hello" "FlickOS"`, or
`notify-send -u critical "Hello"`.

### GTK theme, icons, cursor, fonts, dark mode

GTK apps under Wayland read these from **GSettings**. FlickOS sets defaults with
the schema override file. glib's package trigger recompiles the schemas when the
package is installed.

Current: **`Arc-Dark`** + `prefer-dark`, **`Numix-Circle`** icons, Adwaita cursor
(size 24), DejaVu fonts at size 10, and the title bar buttons
`appmenu:minimize,maximize,close` (`org.gnome.desktop.wm.preferences
button-layout`) for windows that draw their own title bar. The schema's default
`appmenu:close` would give Firefox without *Title Bar* only a close button.
Layouts with `TitlebarLayout` change it ([GTK settings](#gtk-settings-and-nwg-look)).
These are the defaults for users who never
chose anything. The [Light style](#styles-darklight) switches theme, icons and
`color-scheme`, and users can pick anything in *Settings → Appearance*
([nwg-look](#gtk-settings-and-nwg-look)).

- **Packages:** `arc-theme` (Arc, Arc-Dark, Arc-Darker, Arc-Lighter for GTK 2/3/4)
  and `numix-icon-theme-circle` (Numix-Circle and Numix-Circle-Light, ~12,000 app
  icons; it depends on `numix-icon-theme`, ~71 MB together) are **Depends** of
  flickos-settings, because these defaults name them. The base `Numix` theme alone
  has no icons for apps like Firefox, VLC, LibreOffice or foot, so they would keep
  their original icons.
- **libadwaita apps ignore GTK themes** and always look like Adwaita. That's by
  design in libadwaita, not a FlickOS bug.
- **Theme names** must be installed: `ls /usr/share/themes /usr/share/icons`.
- **Check in a VM:** `gsettings get org.gnome.desktop.interface gtk-theme`
  and `… icon-theme`.
- **Users** change settings with `gsettings set …`. Those are stored per user and win.
- **Cursor:** also update `XCURSOR_THEME`/`XCURSOR_SIZE` in `etc/xdg/labwc/environment`,
  which labwc uses for its own cursor.
- **Other components:** changing the GTK theme alone leaves the panel, terminal,
  launcher, notifications and window borders in the style's colors. See
  [The Arc-Dark palette](#the-arc-dark-palette) and [Styles](#styles-darklight).

### Window decorations (labwc theme)

arc-theme has no labwc (or Openbox) theme, so FlickOS ships its own:
**`FlickOS-Arc-Dark`** in `packages/flickos-settings/usr/share/themes/FlickOS-Arc-Dark/labwc/themerc`,
selected with `<name>FlickOS-Arc-Dark</name>` inside `<theme>` in `rc.xml`, plus
rounded corners (`<cornerRadius>`). **`FlickOS-Arc`** (`usr/share/themes/FlickOS-Arc/`)
is the same theme in Arc's light colors; the Light style selects it through the
`rc.xml` overlay. Both files must have the same keys (`tools/check-palette.py`).

It sets the title bars (Arc's `wm_bg`), title text (80 % / 50 % alpha, written
`#cfdae7cc`), button icon colors, borders, the root and window menus (Arc's
white-on-blue selection), the Alt+Tab switcher and the window-snapping preview.

The Alt+Tab switcher's columns are set in `rc.xml`'s `<windowSwitcher>`: the
application's name (`desktop_entry_name`) and the window title, instead of labwc's
default shell type / app id / title. Its width and row spacing are the
`osd.window-switcher.*` keys in both themes. labwc 0.8.3's switcher is a text
list and can't show icons.

- **Colors:** `#rrggbb` or `#rrggbbaa` (alpha in hex: `cc` = 80 %, `80` =
  50 %). Openbox's `#rrggbb <alpha percent>` still works in labwc 0.8.3 but is
  logged as deprecated at every start, so `tools/check-palette.py` rejects it.
- **Keys:** only those listed in `man labwc-theme`. A misspelled key is silently
  ignored by labwc, so `tools/check-palette.py` checks every key against the list
  for labwc 0.8.3. When labwc gains keys in a newer version, add them there.
- **Title bar buttons** look like arc-theme's GTK header bar buttons. Close is
  Arc's 14 px red circle, with the X cut out on Arc-Dark's title bars and white on
  Arc's. The other buttons are arc-openbox's 8×8 glyphs (`.xbm`), which labwc
  colors with `window.*.button.unpressed.image.color`. Their `_hover` SVGs put the
  glyph on a 14 px circle, as Arc does, so labwc draws no hover box of its own.
  labwc picks a `.png` before an `.svg` before an `.xbm` of the same name, and
  draws PNG and SVG buttons in their own colors. All SVGs are generated: change a
  color or circle size in `tools/make-titlebuttons.py`, run it, and bump
  flickos-settings. The glyphs live in FlickOS-Arc-Dark's folder; the script copies
  them to FlickOS-Arc's. `tools/check-palette.py` checks the SVGs' colors.
- **labwc looks for themes** in `/usr/share/themes/<name>/labwc/` (and `openbox-3/`),
  plus the users' `~/.local/share/themes` and `~/.themes`.
- **Test in a VM:** edit `/usr/share/themes/FlickOS-Arc-Dark/labwc/themerc`, then
  *Settings → Reload Desktop Config*.

### Night light

`usr/libexec/flickos/night-light` looks up the system time zone
(`timedatectl`), finds that zone's coordinates in
`/usr/share/zoneinfo/zone1970.tab` and starts `wlsunset -l LAT -L LON`. The
coordinates are those of the zone's reference city, e.g. Berlin for
`Europe/Berlin`, which is accurate enough for sunset times. Nothing is looked
up online.

autostart runs it through `flickos-control night-light`, which adds `-t`
for the warmth chosen in *Settings → Displays* and doesn't run it at all
while night light is off there; the script passes its options on to wlsunset.

- **Change the fallback times** (used when there is no time zone): the
  `-S 06:30 -s 18:30` line.
- **Change the default warmth or turn it off for everyone:**
  `/etc/xdg/flickos/night-light.conf` (`Temperature=`, 2500–6000 K, and
  `Enabled=`); users' own choices win. The day temperature (`-T`, 6500 K)
  can be added in the script.
- **Users** who want exact coordinates put `pkill wlsunset; wlsunset -l LAT -L LON &`
  in their own `~/.config/labwc/autostart` (after calling the FlickOS script).
- **Test the lookup** on any machine: `sh usr/libexec/flickos/night-light` with a
  fake `wlsunset` that prints its arguments, or read `pgrep -a wlsunset` in a VM.

### Keyboard layout

labwc doesn't read the system keyboard setting, so the session script
(`flickos-session`, and the login screen's `greeter` for cage) copies
`/etc/default/keyboard` into `XKB_DEFAULT_LAYOUT`, `XKB_DEFAULT_VARIANT`,
`XKB_DEFAULT_MODEL` and `XKB_DEFAULT_OPTIONS`. That file is written by Calamares
(the installer's keyboard page) and by live-config (the `keyboard-layouts=` boot
option).

- **Test:** at the ISO boot menu, add `keyboard-layouts=de` to the kernel line
  and type in foot. Or choose a different layout in Calamares and check the
  installed system.
- **Users** override the layout in `~/.config/labwc/environment`, e.g.
  `XKB_DEFAULT_LAYOUT=us,de` and `XKB_DEFAULT_OPTIONS=grp:alt_shift_toggle`.

---

## Installer

`packages/flickos-installer/` replaces Debian's `calamares-settings-debian`
(it `Conflicts:`, `Replaces:` and `Provides: calamares-settings`). It's installed
through `config/package-lists/installer.list.chroot`.

| Path | Purpose |
|---|---|
| `etc/calamares/settings.conf` | Installer page and job sequence. `branding: flickos` |
| `etc/calamares/modules/*.conf` | Per-module config, copied from Debian. `packages.conf` removes live-only packages, `calamares` and `flickos-installer` from the installed system. `welcome.conf` turns on the support, known issues and release notes links |
| `etc/calamares/branding/flickos/` | `branding.desc` (names, colors, images), `show.qml` (slideshow during install), `logo.png`, `welcome.png` |
| `usr/lib/calamares/modules/`, `usr/share/calamares/helpers/` | Debian's helper jobs: GRUB install, apt sources, faster dpkg. Unchanged copies |
| `usr/bin/flickos-install` | Launcher: runs `sudo -E calamares` so it opens on the Wayland desktop |
| `usr/share/applications/flickos-install.desktop` | *Install FlickOS* in the app launcher |
| `etc/xdg/flickos-live/labwc/menu.xml` | Live-session menu with *Install FlickOS* |

**How the install entry disappears after installation:** Calamares copies the
live system, then its `packages` module removes `flickos-installer`. That deletes
`/etc/xdg/flickos-live`, so the session script no longer adds it, and labwc
falls back to the normal menu.

**Common changes:**

- **Name, version, colors:** `branding.desc`, under `strings:` and `style:`.
  Update the four version strings for each release, to match `FLICKOS_VERSION`
  ([06 – The version number](06-ci-and-releases.md#the-version-number)).
  `tools/build-iso.sh` refuses to build if `version` doesn't match.
- **Links on the welcome page:** `productUrl`, `supportUrl`, `knownIssuesUrl`,
  `releaseNotesUrl` in `branding.desc`. Currently the SourceForge project, GitHub
  issues and the SourceForge Files page. Switch `productUrl` to https://flickos.net
  once the website is online. To hide a link, set its `show…Url` to `false` in
  `modules/welcome.conf`.
- **Slideshow text:** `show.qml`. Every `Slide { … }` is one slide.
- **Installer images:** see [Artwork](#artwork).
- **Minimum disk/RAM:** `requiredStorage` / `requiredRam` in `modules/welcome.conf`.
- **Groups for new users:** `defaultGroups` in `modules/users.conf`. It already
  includes `sudo`, `lpadmin` (printers) and `bluetooth`.

**When Debian updates `calamares-settings-debian`:** compare its files with your
copies. Download it with `apt-get download calamares-settings-debian` and
unpack it with `dpkg -x`, especially `usr/share/calamares/helpers/` and
`settings.conf`. Merge the relevant fixes, bump the version and rebuild.

**Test the installer:** `tools/test-iso.sh --reset --install` ([02](02-building-and-testing.md#manual-testing-toolstest-isosh)).
Calamares writes its log to `.cache/calamares/session.log` in the home directory
of the user it runs as. Because of `sudo -E`, look in both `/home/user/` and `/root/`.
For more detail, start it from a terminal with `flickos-install -d`.

---

## Boot menu

The ISO's boot menu (syslinux for BIOS, GRUB for UEFI) is customized through
**`config/bootloaders/`**. live-build copies its own templates first
(`/usr/share/live/build/bootloaders/`), then copies FlickOS's files **over** them,
so only changed files live in the repo.

| File | Bootloader | What FlickOS changes |
|---|---|---|
| `syslinux_common/splash.png` | BIOS | Background image, 640×480, 8-bit RGB PNG |
| `syslinux_common/live.cfg.in` | BIOS | Entry names: *Start FlickOS*, *Start FlickOS (safe mode)* |
| `syslinux_common/menu.cfg` | BIOS | Menu title |
| `syslinux_common/stdmenu.cfg` | BIOS | Arc-Dark colors (`#AARRGGBB`; the selection is `#2f343f` on the [brand amber](#the-arc-dark-palette)), menu position below the logo |
| `isolinux/isolinux.cfg` | BIOS | `timeout 100`: boot automatically after 10 s |
| `grub-pc/splash.png` | UEFI | Background image, 800×600, 8-bit RGB PNG |
| `grub-pc/grub.cfg` | UEFI | Own entries (*Start FlickOS*, safe mode), `set timeout=10` |
| `grub-pc/live-theme/theme.txt` | UEFI | Arc-Dark colors with the brand amber for the selected entry and the countdown, no title text (the splash shows the name), the picture centered at its own size (`desktop-image-scale-method: "padding"`), menu position |

The safe mode entries use `--bootappend-live-failsafe` from `auto/config`.

**Placeholders.** live-build fills in `@…@` markers when it builds the ISO:
`@LINUX@`, `@INITRD@`, `@APPEND_LIVE@`, `@APPEND_LIVE_FAILSAFE@` (syslinux) and
`@KERNEL_LIVE@`, `@INITRD_LIVE@`, `@APPEND_LIVE@`, `@LB_BOOTAPPEND_LIVE_FAILSAFE@` (GRUB).
`@TIMEOUT_NOTIFICATION_LONG@` and `@KEYMAP_SHORT@` in `theme.txt` are filled in by GRUB itself.

**Trap in `grub.cfg`:** for backwards compatibility live-build also replaces the
**bare words** `KERNEL_LIVE`, `INITRD_LIVE`, `APPEND_LIVE`, `MEMTEST`,
`LINUX_LIVE` and similar anywhere in GRUB `.cfg` files, including comments. A
line containing `LINUX_LIVE` is deleted entirely. Never write those words
outside `@…@` markers.

**Common changes:**
- **Rename entries:** `menu label` lines in `live.cfg.in` (the `^` marks the
  hotkey letter) and `menuentry "…"` in `grub.cfg`. Keep them in sync.
- **Timeout:** `timeout` in `isolinux.cfg` (tenths of a second, `0` = wait
  forever), `set timeout=` in `grub.cfg` (seconds, `-1` = wait forever).
- **Add a boot option entry** (e.g. with `nomodeset` for broken graphics), GRUB:
  ```
  menuentry "Start FlickOS (basic graphics)" {
  	linux	@KERNEL_LIVE@ @APPEND_LIVE@ nomodeset
  	initrd	@INITRD_LIVE@
  }
  ```
  syslinux: add a `label` block to `live.cfg.in` with `append @APPEND_LIVE@ nomodeset`.
- **Images:** replace the two `splash.png` files, same sizes, **8 bits per
  channel, no transparency** (GRUB can't read 16-bit PNGs). Check with
  `identify splash.png` (ImageMagick): it must say `8-bit`.

**Test:** `tools/build-iso.sh`, then `tools/test-iso.sh --bios` (syslinux) and
`tools/test-iso.sh --uefi` (GRUB). The headless boot test skips the boot menu.
It reads the first entry's kernel line from `isolinux/live.cfg`, so keep the
`linux` / `initrd` / `append` structure of the first entry.

### Installed systems

live-build's files never reach an installed system, so **flickos-branding**
gives its GRUB menu (BIOS and UEFI) the live menu's look:

| File | Purpose |
|---|---|
| `usr/share/flickos/grub/theme.txt` | The live `theme.txt` with its picture next to it. Keep the two in sync |
| `usr/share/flickos/grub/background.png` | The UEFI menu's picture (`make-placeholder-art.sh` copies `grub-pc/splash.png`) |
| `etc/default/grub.d/flickos-theme.cfg` | Conffile: `GRUB_THEME` and `GRUB_BACKGROUND`, set only while the theme exists. `update-grub` reads it after `/etc/default/grub` |

`GRUB_THEME` gives the full look. When GRUB can't read `/usr` (a separate `/boot`
with an encrypted system), Debian's `00_header` skips the theme, and
`05_debian_theme` copies `GRUB_BACKGROUND` to `/boot/grub/.background_cache.png`
instead: the picture with GRUB's own text colors. The package's postinst and
postrm run `update-grub` where `/boot/grub/grub.cfg` exists (not in the ISO's
build chroot). The restore points' entries (flickos-recovery) appear in the same
menu.

**Use another theme:** set `GRUB_THEME` (and `GRUB_BACKGROUND`) in a file that
sorts after `flickos-theme.cfg` in `/etc/default/grub.d/`, or edit the conffile,
then `sudo update-grub`. To get Debian's own menu back, put
`unset GRUB_THEME GRUB_BACKGROUND` in such a file (they are shell).

---

## Boot splash

`flickos-branding` installs a **Plymouth** theme at
`/usr/share/plymouth/themes/flickos/` and makes it the default the first time it's
installed. Plymouth shows it from early boot until the login prompt, and at shutdown.

| File | Purpose |
|---|---|
| `flickos.plymouth` | Theme definition. Module `two-step` (logo + spinner), colors, positions. That module comes from the **plymouth-themes** package, which is why `flickos-branding` depends on it: without it `plymouth-set-default-theme` fails and the ISO build stops |
| `watermark.png` | Logo in the middle of the screen |
| `throbber-0001.png` … `0030.png` | Spinner animation while booting |
| `animation-0001.png` … `0030.png` | End animation, required by `two-step` even though it's turned off |
| `entry.png`, `bullet.png`, `lock.png` | Password dialog for encrypted disks |

**How it gets on screen:** the kernel line must contain `splash`.
- **Live ISO:** `--bootappend-live` in `auto/config` has `quiet splash`.
- **Installed systems:** Calamares's `grubcfg` job adds `splash` to
  `GRUB_CMDLINE_LINUX_DEFAULT` automatically when Plymouth is installed.

The theme lives inside the **initramfs**, so the package triggers
`update-initramfs` when it's installed or upgraded.

**Common changes:**
- **Colors:** `BackgroundStartColor`/`BackgroundEndColor` (`0xRRGGBB`, same
  value = solid color; Arc-Dark `0x383c4a`) and the progress bar colors in
  `flickos.plymouth`. Keep them in the [Arc-Dark palette](#the-arc-dark-palette);
  the bar is the brand amber.
- **Positions:** `WatermarkVerticalAlignment` (logo) and `VerticalAlignment`
  (spinner). `0` = top, `1` = bottom.
- **Images:** replace the PNGs, keeping the names. The spinner frames can be any
  size and any number of frames, numbered from `0001`.

**Test without rebooting**, in a VM or on an installed system:
```sh
sudo plymouthd; sudo plymouth show-splash; sleep 5; sudo plymouth quit
```
Run it from a text console (Ctrl+Alt+F2), not inside labwc. To test at boot,
remove `quiet` temporarily at the boot menu to see errors. `plymouth-set-default-theme`
without arguments prints the active theme.

**Encrypted installs:** `two-step` shows the disk password prompt using
`entry.png`, `bullet.png` and `lock.png`. Test it once with an encrypted
install (`tools/test-iso.sh --reset --install`, then tick *Encrypt system* in
Calamares).

---

## OS name and login banner

`flickos-branding` makes FlickOS visible where Linux shows the OS name, **without
pretending not to be Debian**:

| File | Content | Seen in |
|---|---|---|
| `/etc/os-release` (→ `/usr/lib/os-release`) | Debian's file with `PRETTY_NAME="FlickOS 2.0 (based on Debian GNU/Linux 13 (trixie))"`, `VARIANT="FlickOS 2.0"`, `VARIANT_ID=flickos` added. **`ID=debian`, `NAME`, `VERSION_ID` etc. unchanged** | `hostnamectl`, system info tools (e.g. fastfetch), "About" dialogs that read `os-release` |
| `/etc/issue` | `FlickOS 2.0 (Debian 13) \n \l` | Text console login prompt |
| `/etc/issue.net` | `FlickOS 2.0 (Debian 13)` | Network login banners |

`ID=debian` stays because installers, package managers and many scripts check it
to decide how to behave. Changing it breaks them.

**How it works.** These files belong to Debian's `base-files` package. Overwriting
them directly would break on the next `base-files` upgrade. Instead,
`debian/flickos-branding.postinst`:

1. **Diverts** each file with `dpkg-divert --no-rename`, so future `base-files`
   upgrades write their version to `FILE.debian` (e.g.
   `/usr/lib/os-release.debian`) instead of the real path, and copies Debian's
   current version there itself. `--no-rename` is used because dpkg-divert warns
   that renaming files of an Essential package (`base-files`) is dangerous.
2. **Generates** the FlickOS version from `FILE.debian` plus
   `/usr/lib/flickos-release`.
3. Declares **file triggers** (`debian/flickos-branding.triggers`) on the
   `.debian` files. When `base-files` updates them (e.g. Debian 13.8), dpkg runs
   the postinst again with `triggered`, and the FlickOS versions are regenerated.

Removing the package (`postrm`) deletes the generated files and removes the
diversions, which restores Debian's originals.

**Change the version or name:** edit `packages/flickos-branding/usr/lib/flickos-release`
(`FLICKOS_NAME`, `FLICKOS_VERSION`), bump the package version and rebuild. Do this
for every FlickOS release, together with the version strings in the installer's
`branding.desc`. The ISO name and volume label follow automatically
([06 – The version number](06-ci-and-releases.md#the-version-number)).

**Change the text layout:** the `generate_files` function in
`debian/flickos-branding.postinst`. Test it without installing anything: copy
Debian's `os-release` and `issue` to a temporary folder, run the function with
paths pointing there, and inspect the output.

**Check on a system:**
```sh
cat /etc/os-release; cat /etc/issue
dpkg-divert --list flickos-branding     # the three diversions
```

---

## fastfetch

fastfetch picks its logo from `ID=` in os-release, so on FlickOS it would draw
Debian's. flickos-branding ships a config that draws the FlickOS logo instead:

| File | Purpose |
|---|---|
| `etc/xdg/fastfetch/config.jsonc` | Conffile: the logo, keys and title in the terminal's blue (the style's accent, palette color 4), and fastfetch 2.40's default modules. A config without `modules` shows none, so the list must stay (`fastfetch --gen-config` prints fastfetch's own) |
| `usr/share/flickos/fastfetch/flickos.txt` | The logo: the app icon with its tile, in half blocks with 24-bit colors (`file-raw`, printed as is). Generated, don't edit |

fastfetch looks in `~/.config/fastfetch/` first, then every `XDG_CONFIG_DIRS`
folder (`/etc/xdg` also outside the session, e.g. over SSH), so a user's own
config wins. The tile is Arc-Dark's background: on the Dark style's terminal
it disappears, on the Light style's it shows as the icon does.

fastfetch is a Recommends of flickos-desktop (since 1.31: 2 MB with
libyyjson0). Systems installed before don't get new Recommends, so there it
takes `sudo apt install fastfetch`.

**Change the logo:** change `flickos.svg`, run
`python3 tools/make-fastfetch-logo.py` (`--preview` prints it first, `--width N`
for another size; it reads only the shapes `flickos.svg` uses and stops on
others), then `python3 tools/check-palette.py` (the logo is a brand file) and
bump flickos-branding's version.

**Check on a system:** `fastfetch` in a terminal;
`fastfetch --list-config-paths` shows where it looks.

---

## Firewall

The ISO ships with **ufw** turned on (`config/hooks/normal/0200-firewall.hook.chroot`
sets `ENABLED=yes` in `/etc/ufw/ufw.conf`, and the matching debconf answer). ufw's
defaults:

| Direction | Policy |
|---|---|
| Incoming | **Blocked**, except replies to connections this computer started, DHCP, and mDNS/UPnP discovery (`/etc/ufw/before.rules`), so printers and media servers on the network are still found |
| Outgoing | Allowed |
| Forwarded | Blocked |

Because the hook runs at build time, the firewall is on for the live session and
all installed systems. Existing systems that only receive `ufw` through
`apt upgrade` keep it off, which is ufw's own default.

**Users** turn it on or off on the *Firewall* page of the Settings window
([Settings window](#settings-window); administrator password). Rules need a
terminal:
```sh
sudo ufw status verbose
sudo ufw allow 22/tcp          # e.g. allow SSH
sudo ufw allow from 192.168.1.0/24
sudo ufw disable               # turn off
```

**Change the defaults for FlickOS:** `ufw allow` and similar commands can't run in
the build chroot, because they need the kernel's firewall. Instead, either:
- edit the policies in the hook with `sed` on `/etc/default/ufw`
  (`DEFAULT_INPUT_POLICY` etc.), or
- ship pre-made rule files in a package (`/etc/ufw/user.rules`,
  `/etc/ufw/user6.rules`). Generate them on a test VM with `ufw allow …`, then
  copy them out.

**Turn the firewall off by default:** delete the hook. ufw stays installed but disabled.

**Test:** the boot test checks `ufw status` (check *firewall active*). In a VM,
`sudo ufw status verbose` should show `Status: active` and `deny (incoming)`.

---

## Artwork

**The logo**, the halo (a flick through an open ring), is vector art in
`flickos-branding`, in the [Arc-Dark palette](#the-arc-dark-palette) and the
brand amber:

| File | Used by |
|---|---|
| `packages/flickos-branding/usr/share/icons/hicolor/scalable/apps/flickos.svg` | Icon `flickos`: full color on an Arc-Dark tile. **The source** of every logo image below |
| `packages/flickos-branding/usr/share/icons/hicolor/symbolic/apps/flickos-symbolic.svg` | Icon `flickos-symbolic`: one color (GTK draws it in the text color). The panel's launcher button (`-gtk-icontheme("flickos-symbolic")` in the layouts' `common/base.css`): the ring and dot (class `warning`) in the style's `brand_color` through `-gtk-icon-palette`, the flick in the text color, all of it in the accent color on hover |

Keep the two drawings in sync, and only use palette colors (`tools/check-palette.py`
checks both files). The symbolic version has no tile, a thicker ring and a bigger
dot, so it stays readable at 16–20 px. It must use **fills only**: GTK 3 recolors
a symbolic icon by setting the fill of every shape, so a stroke stays its own
color and the inside of a stroked ring gets filled (its ring is the color
logo's arc as an outline).

The images are made by `tools/make-placeholder-art.sh` (ImageMagick, with the logo
rendered from `flickos.svg` by `rsvg-convert`). Everything except the logo is still a
**placeholder**. The wallpapers aren't made by it: the styles' are drawn from
`packages/flickos-layouts/artwork/` ([Wallpaper](#wallpaper)), and flickos-settings'
fallback `default.jpg` is an Unsplash photo (see its `debian/copyright`).

| File | Size | Used by |
|---|---|---|
| `packages/flickos-installer/etc/calamares/branding/flickos/logo.png` | 256×256 | Calamares sidebar and window icon, slideshow |
| `packages/flickos-installer/etc/calamares/branding/flickos/welcome.png` | 457×300 | Calamares welcome page |
| `packages/flickos-installer/usr/share/pixmaps/flickos-install.png` | 256×256 | *Install FlickOS* launcher icon |
| `config/bootloaders/syslinux_common/splash.png` | 640×480 | BIOS boot menu background |
| `config/bootloaders/grub-pc/splash.png` | 800×600 | UEFI boot menu background |
| `packages/flickos-branding/usr/share/flickos/grub/background.png` | 800×600 | The installed system's boot menu ([Installed systems](#installed-systems)), a copy of the one above |
| `packages/flickos-branding/usr/share/plymouth/themes/flickos/*.png` | various | Boot splash: logo, spinner frames, password dialog |

The desktop layout previews
(`packages/flickos-layouts/usr/share/flickos/layouts/ID/preview.png`, 240×150)
come from a separate script, `tools/make-layout-previews.sh`. See
[The chooser](#the-chooser).

**Replace them** by overwriting the files at the same size, then bump the
package versions. Artwork you didn't make yourself needs a `Files:` stanza with its
author and license in the package's `debian/copyright`. Once you have real artwork, stop running the script, or delete
it, so it doesn't overwrite your files. To regenerate them (e.g.
after changing the logo or the palette):
`sudo apt install imagemagick librsvg2-bin && tools/make-placeholder-art.sh`.

---

## Ideas for later

| Idea | Why it isn't done | Where it would go |
|---|---|---|
| **Real artwork** | Needs a designer | Replace the files listed under [Artwork](#artwork) |
| **Firewall GUI** | `gufw` pulls in a large Python/GTK stack | `gufw` in `flickos-desktop` Recommends, plus a *Settings → Firewall* menu entry |
| **Welcome app on first login** | Needs to be written | A small script or app in `flickos-settings`, started once from `/usr/libexec/flickos/autostart` (check for a marker file in `~/.config/flickos/`) |
| **Exact night light location** | Would need network geolocation (privacy) | `geoclue-2.0` + a location-aware tool instead of the time-zone lookup |

For each one you adopt: packages go in `flickos-desktop`
([04](04-packages.md#adding-or-removing-a-desktop-package)), config files in
`flickos-settings` (this page), services and system setup in hooks
([03](03-live-build-config.md#confighooksnormal-scripts-run-during-the-build)),
and add a check to the boot test where it makes sense
([02](02-building-and-testing.md#adding-a-check)).
