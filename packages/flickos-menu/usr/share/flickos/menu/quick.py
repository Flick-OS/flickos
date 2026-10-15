"""Quick Settings, the second window of flickos-menu's daemon.

flickos-menu loads this file only while Quick Settings is on (menu/quick
exists): compiling it costs memory that a session without Quick Settings
shouldn't pay (flickos-menu runs from /usr/bin, so it has no .pyc).

Quick Settings owns no setting (HIG SET-1): every control reads and changes
its setting with the command of the program that owns it, so History,
Settings and the panel stay right. The battery and the backlight are the
kernel's, read from /sys. Design: docs/design/flickos-quick-settings.md
(ADR-005: the owners' commands; ADR-006: read at every show, asleep while
hidden).

The first part has no GTK (the tests use it); QuickSettings is the window.
"""

import os
import sys

NAMESPACE = "flickos-menu"      # the layer-shell namespace, the start menu's


def warn(message):
    print(f"flickos-menu: {message}", file=sys.stderr)


SYS = "/sys"
QUICK_WIDTH = 360
QUICK_REFRESH_SECONDS = 2       # volume, Wi-Fi and battery, only while it is shown (PERF-5)
QUICK_READ_SECONDS = 10         # an owner that takes longer is left as it was
# A slider the user moved keeps its place this long: a read that was already
# on its way would move it back.
SLIDE_HOLD_MS = 1500
SINK = "@DEFAULT_AUDIO_SINK@"
# Switches: (key, title, icon while on, icon while off).
QUICK_TILES = (
    ("wifi", "Wi-Fi", "network-wireless-symbolic", "network-wireless-disabled-symbolic"),
    ("dnd", "Do Not Disturb", "notifications-disabled-symbolic", "notifications-disabled-symbolic"),
    ("night", "Night light", "night-light-symbolic", "night-light-symbolic"),
    ("tiler", "Tiling", "view-grid-symbolic", "view-grid-symbolic"),
    ("phone", "Phone", "phone-symbolic", "phone-symbolic"),
)
# The owners' reads, one run each per show: key -> commands. flickos-control
# prints all its settings in one run (Do Not Disturb and night light).
QUICK_READS = {
    "wifi": (["nmcli", "-t", "-f", "WIFI", "radio"],
             # Not `nmcli dev wifi`: that rescans when its list is 30 s old (2.5 s).
             ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev"]),
    "control": (["flickos-control", "get"],),
    "tiler": (["flick-tiler", "status"],),
    "phone": (["flickos-phone", "state"],),
    "volume": (["wpctl", "get-volume", SINK],),
}
TILER_MODES = ["flick-tiler", "modes"]      # read once: the arrangements' names
# The owner each tile needs, and the read that answers for it.
TILE_PROGRAMS = {"wifi": "nmcli", "dnd": "flickos-control", "night": "flickos-control",
                 "tiler": "flick-tiler", "phone": "flickos-phone"}
TILE_READS = {"wifi": "wifi", "dnd": "control", "night": "control", "tiler": "tiler", "phone": "phone"}
CONTROL_KEYS = {"dnd": "notifications.do-not-disturb", "night": "night-light.enabled"}
# systemd's and GNOME's order when a laptop has several backlights: the
# firmware's (ACPI) works on the most machines, raw (the GPU's) is last.
BACKLIGHT_TYPES = ("firmware", "platform", "raw")
INTERNAL_SCREENS = ("eDP", "LVDS", "DSI")


def change_command(key, value, device=None):
    """The owner's command that changes key to value (ADR-005)."""
    yes = "yes" if value else "no"
    if key == "wifi":
        return ["nmcli", "radio", "wifi", "on" if value else "off"]
    if key in CONTROL_KEYS:
        return ["flickos-control", "set", CONTROL_KEYS[key], yes]
    if key == "tiler":
        return ["flick-tiler", "on" if value else "off"]
    if key == "phone":
        return ["flickos-phone", "set", "enabled", yes]
    # As the volume and brightness keys (flickos-settings' rc.xml).
    if key == "volume":
        return ["wpctl", "set-volume", "-l", "1.0", SINK, f"{int(value)}%"]
    if key == "mute":
        return ["wpctl", "set-mute", SINK, "toggle"]
    if key == "brightness":
        return ["brightnessctl", "-q", "-d", device, "set", f"{int(value)}%"]
    raise ValueError(key)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def wifi_devices(sys_root=SYS):
    """The network interfaces that are Wi-Fi."""
    folder = os.path.join(sys_root, "class", "net")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [name for name in names if any(os.path.exists(os.path.join(folder, name, sub))
                                          for sub in ("wireless", "phy80211"))]


def screen_on(sys_root, backlight_path):
    """Whether the screen a backlight lights is on. A GPU's backlight sits
    below its connector, whose `enabled` says so; a firmware one doesn't: it
    counts as on while any built-in screen is, or when there's none to ask."""
    enabled = read_text(os.path.join(backlight_path, "device", "enabled"))
    if enabled is not None:
        return enabled == "enabled"
    import glob
    states = [read_text(path) for kind in INTERNAL_SCREENS
              for path in glob.glob(os.path.join(sys_root, "class", "drm", f"card*-{kind}-*", "enabled"))]
    return not states or "enabled" in states


def backlight(sys_root=SYS, access=os.access):
    """(name, folder) of the backlight to show a slider for: of the ones
    whose screen is on, the first in BACKLIGHT_TYPES; None without one, or
    when the user may not change it (brightnessctl needs its udev rule,
    Debian's brightness-udev)."""
    folder = os.path.join(sys_root, "class", "backlight")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    found = []
    for name in names:
        path = os.path.join(folder, name)
        kind = read_text(os.path.join(path, "type"))
        if kind in BACKLIGHT_TYPES and screen_on(sys_root, path):
            found.append((BACKLIGHT_TYPES.index(kind), name, path))
    if not found:
        return None
    _rank, name, path = min(found)
    return (name, path) if access(os.path.join(path, "brightness"), os.W_OK) else None


def brightness_percent(path):
    try:
        now = int(read_text(os.path.join(path, "brightness")))
        top = int(read_text(os.path.join(path, "max_brightness")))
    except (TypeError, ValueError):
        return None
    return round(now * 100 / top) if top > 0 else None


def batteries(sys_root=SYS):
    """The folders of the computer's batteries (not a mouse's: scope Device)."""
    folder = os.path.join(sys_root, "class", "power_supply")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, name) for name in names
            if read_text(os.path.join(folder, name, "type")) == "Battery"
            and read_text(os.path.join(folder, name, "scope")) != "Device"]


def battery_state(folders):
    """(percent, status, hours) of the batteries together; hours to empty
    while discharging, to full while charging, else None. None without a
    percentage."""
    def number(folder, *names):
        for name in names:
            value = read_text(os.path.join(folder, name))
            if value is not None:
                try:
                    return int(value)
                except ValueError:
                    pass
        return None

    statuses, now, full, rate, percents = [], 0, 0, 0, []
    for folder in folders:
        statuses.append(read_text(os.path.join(folder, "status")) or "Unknown")
        level, top = number(folder, "energy_now", "charge_now"), number(folder, "energy_full", "charge_full")
        speed = number(folder, "power_now", "current_now")
        capacity = number(folder, "capacity")
        if capacity is not None:
            percents.append(capacity)
        if level is not None and top:
            now, full, rate = now + level, full + top, rate + abs(speed or 0)
    if not percents:
        return None
    percent = round(now * 100 / full) if full and len(folders) > 1 else percents[0]
    status = next((s for s in ("Discharging", "Charging") if s in statuses), statuses[0])
    hours = None
    if rate > 0 and full:
        hours = now / rate if status == "Discharging" else (full - now) / rate if status == "Charging" else None
    return min(percent, 100), status, hours


def battery_text(state):
    """What the battery row says: "82%, 3:10 left" (HIG TXT-2)."""
    percent, status, hours = state
    time = f"{int(hours)}:{int(hours * 60) % 60:02d}" if hours is not None and hours < 100 else None
    if status == "Discharging":
        return f"{percent}%, {time} left" if time else f"{percent}%"
    if status == "Charging":
        return f"{percent}%, charging, full in {time}" if time else f"{percent}%, charging"
    if status == "Full":
        return f"{percent}%, fully charged"
    if status == "Not charging":
        return f"{percent}%, plugged in"
    return f"{percent}%"


def battery_icon(state):
    percent, status, _hours = state
    if status == "Full":
        return "battery-level-100-charged-symbolic"
    level = min(100, percent // 10 * 10)
    return f"battery-level-{level}{'-charging' if status == 'Charging' else ''}-symbolic"


def nmcli_fields(line):
    """The fields of a line of `nmcli -t`, which escapes : and \\ in values."""
    fields, current, escaped = [], "", False
    for char in line:
        if escaped:
            current, escaped = current + char, False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append(current)
            current = ""
        else:
            current += char
    fields.append(current)
    return fields


def parse_wifi(radio, devices):
    """(on, subtitle) from nmcli's Wi-Fi radio and its devices."""
    if radio.strip() != "enabled":
        return False, "Off"
    subtitle = "Not connected"
    for line in devices.splitlines():
        fields = nmcli_fields(line)
        if len(fields) < 4 or fields[1] != "wifi":
            continue
        if fields[2].startswith("connected") and fields[3]:
            return True, fields[3]
        if fields[2].startswith("connecting"):
            subtitle = "Connecting…"
    return True, subtitle


def parse_control(text):
    """{key: value} of `flickos-control get` (key, value, source per line)."""
    values = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            values[fields[0]] = fields[1]
    return values


def parse_tiler(text, modes=None):
    """(on, subtitle) of `flick-tiler status`: Off, or the arrangement."""
    import json
    status = json.loads(text)
    classes = status.get("class") or []
    on = status.get("alt") != "off"
    mode = classes[1] if len(classes) > 1 else ""
    return on, ((modes or {}).get(mode) or mode.replace("-", " ").capitalize() or "On") if on else "Off"


def parse_modes(text):
    return dict(line.split("\t", 1) for line in text.splitlines() if "\t" in line)


def parse_phone(text):
    """(paired, on, subtitle) of `flickos-phone state`. The tile is shown
    only once a phone is paired, never in the live session."""
    import json
    state = json.loads(text)
    phones = state.get("phones") or []
    paired = bool(phones) and not state.get("live")
    on = bool(state.get("enabled"))
    connected = next((phone.get("name") for phone in phones if phone.get("connected")), None)
    return paired, on, (connected or "Not connected") if on else "Off"


def parse_volume(text):
    """(percent, muted) of `wpctl get-volume`: "Volume: 0.41 [MUTED]"."""
    fields = text.split()
    if len(fields) < 2 or fields[0] != "Volume:":
        raise ValueError(text)
    return round(float(fields[1]) * 100), "[MUTED]" in fields


def volume_icon(percent, muted):
    if muted or percent == 0:
        return "audio-volume-muted-symbolic"
    return f"audio-volume-{'low' if percent < 34 else 'medium' if percent < 67 else 'high'}-symbolic"


def quick_tiles(which, sys_root=SYS, live=False, phone_paired=False):
    """The switches Quick Settings shows, in order: a tile is left out when
    it can't be used (HIG WIN-9)."""
    shown = []
    for key, *_ in QUICK_TILES:
        if which(TILE_PROGRAMS[key]) is None:
            continue
        if key == "wifi" and not wifi_devices(sys_root):
            continue
        if key == "phone" and (live or not phone_paired):
            continue
        shown.append(key)
    return shown


def error_line(stderr):
    """The last line an owner printed on error, without its name."""
    import re
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return re.sub(r"^[\w.-]+: (error: )?", "", lines[-1]) if lines else ""


class Coalescer:
    """A slider's changes: at most one command in flight, the newest value
    wins (drags send many). start(value, done) runs the change and calls
    done() when it has finished."""

    def __init__(self, start):
        self.start = start
        self.busy = False
        self.sent = None
        self.wanted = None

    def set(self, value):
        self.wanted = value
        if not self.busy:
            self.send()

    def send(self):
        self.busy, self.sent = True, self.wanted
        self.start(self.sent, self.done)

    def done(self, *_):
        self.busy = False
        if self.wanted != self.sent:
            self.send()


# --- The window (GTK) ------------------------------------------------------------

class QuickSettings:
    """Quick Settings: switches for Wi-Fi, Do Not Disturb, night light,
    tiling and the phone, sliders for volume and brightness, the battery,
    Settings and the power buttons (Lock Screen, Log Out, Restart, Shut Down),
    in the corner of the panel's status icons. Built
    once, then shown and hidden. Every show reads the owners again, all at
    once in threads, and corrects each control when its answer comes; while
    shown, volume, Wi-Fi and battery are read again every
    QUICK_REFRESH_SECONDS. Nothing runs while it is hidden (PERF-5). A change
    shows at once and is put back, with the owner's message, if the owner
    fails (WIN-10)."""

    def __init__(self, menu, buttons):
        """menu: the daemon's Menu (GTK, run, log, clock, live, fader,
        power_row). buttons: (text, icon, command) of the bottom row before
        the power buttons: Settings."""
        self.menu = menu
        self.GLib, self.Gdk, self.Gio, self.Gtk, self.GtkLayerShell = (
            menu.GLib, menu.Gdk, menu.Gio, menu.Gtk, menu.GtkLayerShell)
        Gtk, GtkLayerShell = self.Gtk, self.GtkLayerShell
        self.corner = None
        self.shown_at = self.read_at = None
        self.reads = {}             # read key -> number of its newest read; older answers are dropped
        self.waiting = set()        # reads of this show not answered yet
        self.changing = set()       # tiles with a change on its way: reads leave them alone
        self.moved = {}             # slider -> when the user last moved it
        self.quiet = False          # controls are being set from a read
        self.timer = None
        self.phone_paired = False   # from the last read: the phone tile needs a paired phone
        self.tiler_modes = None
        self.device = None          # (name, folder) of the backlight
        self.shown = []             # the tiles shown, in order
        self.muted = False
        window = self.window = Gtk.Window(title="Quick Settings")
        self.fader = menu.fader(window)
        window.get_style_context().add_class("flickos-quick")
        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_namespace(window, NAMESPACE)
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.ON_DEMAND)
        window.connect("key-press-event", self.on_key)
        window.connect("focus-out-event", lambda *_: self.hide() or False)
        window.connect("delete-event", lambda *_: self.hide() or True)
        window.connect_after("draw", self.on_draw)

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        frame.get_style_context().add_class("quick")
        frame.set_size_request(QUICK_WIDTH, -1)
        window.add(frame)
        self.grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        frame.pack_start(self.grid, False, False, 0)
        self.tiles = {}
        for key, title, _on, off in QUICK_TILES:
            self.tiles[key] = self.tile(key, title, off)

        self.sliders = {}
        self.mute = Gtk.Button(relief=Gtk.ReliefStyle.NONE, tooltip_text="Mute")
        self.mute.add(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic", Gtk.IconSize.BUTTON))
        self.mute.get_accessible().set_name("Mute")
        self.mute.connect("clicked", lambda _b: self.toggle_mute())
        self.volume = Coalescer(lambda value, done: self.run(
            change_command("volume", value), self.slid("volume", done)))
        self.brightness = Coalescer(lambda value, done: self.run(
            change_command("brightness", value, self.device[0]), self.slid("brightness", done)))
        brightness_icon = Gtk.Image.new_from_icon_name("display-brightness-symbolic", Gtk.IconSize.BUTTON)
        brightness_icon.get_style_context().add_class("slider-icon")
        for key, title, icon, coalescer in (("volume", "Volume", self.mute, self.volume),
                                            ("brightness", "Brightness", brightness_icon, self.brightness)):
            row = Gtk.Box(spacing=8)
            row.get_style_context().add_class("slider")
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            scale.set_draw_value(False)
            scale.get_accessible().set_name(title)
            value = Gtk.Label(label="", xalign=1, width_chars=4)
            scale.connect("value-changed", self.on_slide, key, coalescer, value)
            row.pack_start(icon, False, False, 0)
            row.pack_start(scale, True, True, 0)
            row.pack_start(value, False, False, 0)
            row.scale, row.value = scale, value
            self.sliders[key] = row
            frame.pack_start(row, False, False, 0)

        self.message = Gtk.Label(xalign=0, wrap=True, max_width_chars=40)
        self.message.get_style_context().add_class("message")
        self.message.set_no_show_all(True)
        frame.pack_start(self.message, False, False, 0)
        frame.pack_start(Gtk.Separator(), False, False, 0)
        # Lock Screen, Log Out, Restart, Shut Down; the line that asks for a
        # second click goes above the row.
        self.power = menu.power_row(Gtk.IconSize.BUTTON, symbolic=True)
        self.power.hint.set_xalign(1)
        frame.pack_start(self.power.hint, False, False, 0)
        bottom = Gtk.Box(spacing=8)
        bottom.get_style_context().add_class("bottom")
        self.battery_icon = Gtk.Image()
        self.battery = Gtk.Label(xalign=0)
        self.battery.set_ellipsize(3)       # Pango.EllipsizeMode.END
        for widget in (self.battery_icon, self.battery):
            widget.set_no_show_all(True)
        bottom.pack_start(self.battery_icon, False, False, 0)
        bottom.pack_start(self.battery, True, True, 0)
        bottom.pack_end(self.power.box, False, False, 0)
        for text, icon, command in reversed(buttons):
            button = Gtk.Button(relief=Gtk.ReliefStyle.NONE, tooltip_text=text)
            button.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
            button.get_accessible().set_name(text)
            button.connect("clicked", lambda _b, command=command: self.menu.run(command))
            bottom.pack_end(button, False, False, 0)
        frame.pack_start(bottom, False, False, 0)
        frame.show_all()
        for row in self.sliders.values():
            row.hide()      # show() shows the ones that can be used
        # Work out styles and sizes now, not at the first show.
        window.realize()
        window.get_preferred_size()

    def tile(self, key, title, icon):
        """A switch: a toggle button with an icon, the title and what it is
        doing below it."""
        Gtk = self.Gtk
        button = Gtk.ToggleButton()
        button.get_style_context().add_class("tile")
        box = Gtk.Box(spacing=10)
        button.image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        name = Gtk.Label(label=title, xalign=0)
        name.get_style_context().add_class("title")
        button.subtitle = Gtk.Label(xalign=0)
        button.subtitle.get_style_context().add_class("subtitle")
        for label in (name, button.subtitle):
            label.set_ellipsize(3)
            texts.pack_start(label, False, False, 0)
        box.pack_start(button.image, False, False, 0)
        box.pack_start(texts, True, True, 0)
        button.add(box)
        button.get_accessible().set_name(title)
        button.connect("toggled", self.on_toggled, key)
        box.show_all()
        return button

    # Showing ------------------------------------------------------------------

    def visible(self):
        return self.fader.visible()

    def place(self, corner):
        GtkLayerShell = self.GtkLayerShell
        vertical = corner.split("-")[0]
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, vertical == "top")
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.BOTTOM, vertical == "bottom")
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.RIGHT, True)

    def show(self, corner):
        import shutil
        if corner != self.corner:
            self.place(corner)
            self.corner = corner
        self.message.hide()
        self.power.disarm()
        self.shown = quick_tiles(shutil.which, live=self.menu.live, phone_paired=self.phone_paired)
        self.arrange()
        self.sliders["volume"].set_visible(shutil.which("wpctl") is not None)
        self.device = backlight() if shutil.which("brightnessctl") else None
        self.sliders["brightness"].set_visible(self.device is not None)
        self.update_local()
        self.shown_at = self.menu.clock()
        self.fader.show()
        self.window.set_focus_visible(False)    # no focus ring until the keyboard is used
        first = next((self.tiles[key] for key in self.shown), None)
        if first is not None:
            first.grab_focus()
        self.read_at = self.menu.clock()
        self.waiting = set()
        reads = {TILE_READS[key] for key in self.shown}
        if self.sliders["volume"].get_visible():
            reads.add("volume")
        # The phone's tile waits for a paired phone, which only its read tells.
        if shutil.which(TILE_PROGRAMS["phone"]) and not self.menu.live:
            reads.add("phone")
        self.read(reads)
        if self.timer is None:
            self.timer = self.GLib.timeout_add_seconds(QUICK_REFRESH_SECONDS, self.refresh)

    def arrange(self):
        """The tiles that are shown, two to a row."""
        for child in self.grid.get_children():
            self.grid.remove(child)
        for i, key in enumerate(self.shown):
            self.grid.attach(self.tiles[key], i % 2, i // 2, 1, 1)
            self.tiles[key].show()
        self.grid.set_visible(bool(self.shown))

    def hide(self):
        if self.timer is not None:
            self.GLib.source_remove(self.timer)
            self.timer = None
        self.power.disarm()
        self.fader.hide()

    def destroy(self):
        self.hide()
        self.fader.hide_now()
        self.window.destroy()

    def refresh(self):
        """While shown: what the keys and the tray change behind its back."""
        self.update_local()
        self.read({"volume"} if self.sliders["volume"].get_visible() else set())
        if "wifi" in self.shown:
            self.read({"wifi"})
        return True     # GLib timeout: again, until hide() removes it

    def on_key(self, _window, event):
        if event.keyval == self.Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def on_draw(self, *_):
        if self.shown_at is not None:
            self.menu.log(f"quick settings shown in {self.menu.clock() - self.shown_at:.1f} ms")
            self.shown_at = None
        return False

    # Reading ------------------------------------------------------------------

    def update_local(self):
        """The kernel's values: the battery and the backlight (no owner)."""
        state = battery_state(batteries())
        for widget in (self.battery_icon, self.battery):
            widget.set_visible(state is not None)
        if state is not None:
            self.battery.set_text(battery_text(state))
            self.battery_icon.set_from_icon_name(self.icon(battery_icon(state), "battery-symbolic"),
                                                 self.Gtk.IconSize.BUTTON)
        if self.device is not None and not self.held("brightness"):
            percent = brightness_percent(self.device[1])
            if percent is not None:
                self.set_slider("brightness", percent)

    def read(self, keys):
        """Ask the owners in the background (one thread each); answer() takes
        each one's answer in the main loop."""
        import threading
        for key in keys:
            number = self.reads.get(key, 0) + 1
            self.reads[key] = number
            commands = list(QUICK_READS[key])
            if key == "tiler" and self.tiler_modes is None:
                commands.append(TILER_MODES)
            self.waiting.add(key)
            threading.Thread(target=self.ask, args=(key, number, commands), daemon=True).start()

    def ask(self, key, number, commands):
        """In a thread: the commands' output, or None where one failed."""
        import subprocess
        outputs = []
        for command in commands:
            try:
                done = subprocess.run(command, capture_output=True, text=True, timeout=QUICK_READ_SECONDS,
                                      check=False)
                outputs.append(done.stdout if done.returncode == 0 else None)
            except (OSError, subprocess.SubprocessError):
                outputs.append(None)
        self.GLib.idle_add(self.answer, key, number, outputs)

    def answer(self, key, number, outputs):
        if number != self.reads.get(key):
            return False        # a newer read of it is on its way
        self.waiting.discard(key)
        try:
            self.apply(key, outputs)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            warn(f"quick settings: cannot read {key}: {error}")
        if not self.waiting and self.read_at is not None:
            self.menu.log(f"quick settings values in {self.menu.clock() - self.read_at:.1f} ms")
            self.read_at = None
        return False        # GLib idle: once

    def apply(self, key, outputs):
        if outputs[0] is None:
            return          # the owner didn't answer: the control keeps what it showed
        if key == "wifi" and outputs[1] is not None:
            self.set_tile("wifi", *parse_wifi(outputs[0], outputs[1]))
        elif key == "control":
            values = parse_control(outputs[0])
            for tile, setting in CONTROL_KEYS.items():
                if setting in values:
                    on = values[setting] == "yes"
                    self.set_tile(tile, on, "On" if on else "Off")
        elif key == "tiler":
            if len(outputs) > 1 and outputs[1] is not None:
                self.tiler_modes = parse_modes(outputs[1])
            self.set_tile("tiler", *parse_tiler(outputs[0], self.tiler_modes))
        elif key == "phone":
            paired, on, subtitle = parse_phone(outputs[0])
            self.set_tile("phone", on, subtitle)
            if paired != self.phone_paired:
                import shutil
                self.phone_paired = paired
                self.shown = quick_tiles(shutil.which, live=self.menu.live, phone_paired=paired)
                self.arrange()
        elif key == "volume" and not self.held("volume"):
            percent, muted = parse_volume(outputs[0])
            self.set_slider("volume", percent)
            self.set_muted(muted, percent)

    # Showing values -----------------------------------------------------------

    def icon(self, *names):
        """The first of names the icon theme has."""
        theme = self.Gtk.IconTheme.get_default()
        return next((name for name in names if theme.has_icon(name)), names[-1])

    def set_tile(self, key, on, subtitle):
        if key in self.changing:
            return
        tile = self.tiles[key]
        self.quiet = True
        tile.set_active(on)
        self.quiet = False
        self.show_state(key, on, subtitle)

    def show_state(self, key, on, subtitle):
        tile = self.tiles[key]
        tile.subtitle.set_text(subtitle)
        tile.get_accessible().set_description(subtitle)
        _key, _title, icon_on, icon_off = next(t for t in QUICK_TILES if t[0] == key)
        tile.image.set_from_icon_name(icon_on if on else icon_off, self.Gtk.IconSize.LARGE_TOOLBAR)

    def set_slider(self, key, percent):
        row = self.sliders[key]
        self.quiet = True
        row.scale.set_value(percent)
        self.quiet = False
        row.value.set_text(f"{int(percent)}%")

    def set_muted(self, muted, percent):
        self.muted = muted
        self.mute.get_child().set_from_icon_name(volume_icon(percent, muted), self.Gtk.IconSize.BUTTON)
        self.mute.set_tooltip_text("Unmute" if muted else "Mute")
        self.mute.get_accessible().set_name("Unmute" if muted else "Mute")

    def held(self, slider):
        """True while the user's own move of slider is fresher than a read."""
        coalescer = self.volume if slider == "volume" else self.brightness
        return coalescer.busy or self.menu.clock() - self.moved.get(slider, -SLIDE_HOLD_MS) < SLIDE_HOLD_MS

    # Changing -----------------------------------------------------------------

    def run(self, command, done):
        """Run an owner's command without blocking the window; then
        done(ok, message) with the owner's error message."""
        Gio, GLib = self.Gio, self.GLib
        try:
            process = Gio.Subprocess.new(command, Gio.SubprocessFlags.STDOUT_SILENCE
                                         | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as error:
            done(False, error.message)
            return

        def finished(process, result):
            try:
                _ok, _stdout, stderr = process.communicate_utf8_finish(result)
                ok = process.get_successful()
            except GLib.Error as error:
                stderr, ok = error.message, False
            done(ok, error_line(stderr or ""))

        process.communicate_utf8_async(None, None, finished)

    def on_toggled(self, tile, key):
        if self.quiet:
            return
        on = tile.get_active()
        title = next(t[1] for t in QUICK_TILES if t[0] == key)
        self.changing.add(key)
        self.show_state(key, on, "On" if on else "Off")
        self.message.hide()

        def done(ok, message):
            self.changing.discard(key)
            if not ok:
                self.set_tile(key, not on, "On" if not on else "Off")
                self.say(f"Could not turn {title} {'on' if on else 'off'}" + (f": {message}" if message else "."))
            if self.visible():
                self.read({TILE_READS[key]})    # what it is doing now (the network, the arrangement)

        self.run(change_command(key, on), done)

    def on_slide(self, scale, key, coalescer, value):
        if self.quiet:
            return
        percent = int(round(scale.get_value()))
        value.set_text(f"{percent}%")
        self.moved[key] = self.menu.clock()
        if key == "volume":
            self.set_muted(self.muted, percent)
        coalescer.set(percent)

    def slid(self, key, done):
        """A slider's change has finished: say so if it failed, then let
        the coalescer send the newest value."""
        def finished(ok, message):
            if not ok:
                self.say(f"Could not change the {key}" + (f": {message}" if message else "."))
            done()
        return finished

    def toggle_mute(self):
        def done(ok, message):
            if not ok:
                self.say(f"Could not mute: {message}" if message else "Could not mute.")
            self.read({"volume"})

        self.run(change_command("mute", None), done)

    def say(self, text):
        self.message.set_text(text)
        self.message.show()
