"""The phone popup, the third window of flickos-menu's daemon.

flickos-menu loads this file only while the phone connection is on
($XDG_RUNTIME_DIR/flickos/menu/phone exists): compiling it costs memory that
a session without the phone shouldn't pay (flickos-menu runs from /usr/bin,
so it has no .pyc).

The popup owns no setting (HIG SET-1). It draws the action tiles flickos-phone
describes (`actions --json`) and only the fixed parts: the phone's line, a
Mute row while a phone rings, what the phone plays, the newest received
items, Open Phone and Phone Settings. A new action reaches it with a
flickos-phone release alone. It runs an action's command only when that
command is flickos-phone or the screen add-on.

What the phone plays is Later item 15. Until flickos-phone sends it, the row
stays hidden. The shape it will send, in `state` and as a `watch` line:
{"id", "title", "artist", "playing"} (a watch line uses "event": "playing").
The buttons run `flickos-phone player play|pause|next`, which that release adds.

Reads run at every show, in a thread. `watch` runs only while the popup is
shown, so nothing wakes while it is closed (PERF-5). Design:
docs/design/flickos-phone.md (ADR-012).

The first part has no GTK (the tests use it); PhonePopup is the window.
"""

import datetime
import json
import mimetypes
import os
import sys
import urllib.parse

NAMESPACE = "flickos-menu"      # the layer-shell namespace, the start menu's
PHONE_WIDTH = 360               # Quick Settings' width: the same corner
TILE_COLUMNS = 2                # Quick Settings' tiles, two to a line
# The popup's other parts (the phone's line, the buttons, the panel) take
# about this much of the screen's height; the rest is for what scrolls.
PHONE_CHROME_HEIGHT = 220
PHONE_MIN_BODY = 200            # what scrolls is never cut below this
PHONE_READ_SECONDS = 10         # a read that takes longer is left as it was
# The newest received items. The menu shows five (flickos-phone's MENU_RECEIVED);
# the popup is a glance, so three (ADR-012).
POPUP_RECEIVED = 3
# watch appends; the daemon's own list keeps this many (flickos-phone's RECEIVED_ITEMS).
RECEIVED_KEEP = 20
# An action's command is one of these. Anything else in the JSON is not run:
# a phone's words are never a command line (ADR-012).
ACTION_PROGRAMS = ("flickos-phone", "flickos-phone-screen")
# What the phone plays (Later item 15). The command arrives with that release.
PLAYER = ("flickos-phone", "player")
PLAYER_ACTIONS = ("play", "pause", "next")
# The daemon's control socket, under $XDG_RUNTIME_DIR/flickos (flickos-phone's).
PHONE_CONTROL = os.path.join("phone", "control")


class PopupError(Exception):
    pass


def warn(message):
    print(f"flickos-menu: {message}", file=sys.stderr)


def battery_suffix(battery):
    """The phone line's battery, as the Phone window writes it."""
    if not isinstance(battery, (list, tuple)) or len(battery) < 2:
        return ""
    try:
        charge = int(battery[0])
    except (TypeError, ValueError):
        return ""
    return f" · {charge} %" + (", charging" if battery[1] else "")


def phone_line(phone):
    """(name, status) for the phone's line. phone is a state entry, or None."""
    if not phone:
        return "No phone paired", "Add one in Phone Settings"
    name = phone.get("name") or "Phone"
    if phone.get("connected"):
        return name, "Connected" + battery_suffix(phone.get("battery"))
    return name, "Not connected"


def short_address(url, limit=60):
    """Host and path, as the Phone window shortens a page."""
    parts = urllib.parse.urlsplit(url or "")
    text = parts.netloc + parts.path
    text = text[4:] if text.startswith("www.") else text
    if not text:
        return url or "Page"
    return text if len(text) <= limit else text[:limit - 1] + "…"


def when_text(seconds):
    """14:02, Yesterday 14:02, or Tue 22 Sep. Empty when there is no time."""
    if not seconds:
        return ""
    try:
        moment = datetime.datetime.fromtimestamp(seconds)
    except (OverflowError, OSError, ValueError):
        return ""
    today = datetime.date.today()
    if moment.date() == today:
        return moment.strftime("%H:%M")
    if (today - moment.date()).days == 1:
        return "Yesterday " + moment.strftime("%H:%M")
    return moment.strftime("%a %d %b")


def action_target(state, chosen):
    """The phone `--to` should name when several are paired, else None."""
    phones = [phone for phone in (state.get("phones") or []) if isinstance(phone, dict) and phone.get("id")]
    if len(phones) <= 1:
        return None
    if chosen and any(phone.get("id") == chosen for phone in phones):
        return chosen
    connected = [phone for phone in phones if phone.get("connected")]
    return (connected or phones)[0].get("id")


def chosen_phone(state, chosen):
    """The paired phone the line shows."""
    phones = [phone for phone in (state.get("phones") or []) if isinstance(phone, dict)]
    if chosen:
        for phone in phones:
            if phone.get("id") == chosen:
                return phone
    connected = [phone for phone in phones if phone.get("connected")]
    return (connected or phones or [None])[0]


def action_tiles(rows):
    """The tiles to draw: shown actions whose command this popup may run.
    A tile has the action's short words (flickos-phone 1.19), else its label."""
    tiles = []
    if not isinstance(rows, list):
        return tiles
    for row in rows:
        if not isinstance(row, dict) or not row.get("shown"):
            continue
        command = row.get("command")
        if (not isinstance(command, list) or not command or command[0] not in ACTION_PROGRAMS
                or not all(isinstance(arg, str) for arg in command)):
            continue
        label = row.get("short") or row.get("label") or "Phone"
        tiles.append({"id": str(row.get("id") or ""), "label": str(label),
                      "icon": str(row.get("icon") or "phone"), "command": list(command)})
    return tiles


def tile_icon(name, has_icon):
    """The tile's icon: the -symbolic one, as Quick Settings' tiles have, else
    the name itself, else the phone (HIG VIS-6: the first the theme has)."""
    for candidate in (name + "-symbolic", name, "phone-symbolic", "phone"):
        if has_icon(candidate):
            return candidate
    return "application-x-executable"


def ringing_rows(state):
    """Phones that are ringing: id, name, caller. Empty when none is."""
    rows = state.get("ringing") if isinstance(state, dict) else None
    if not isinstance(rows, list):
        return []
    found = []
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            found.append({"id": str(row["id"]), "name": str(row.get("name") or "Phone"),
                          "caller": str(row.get("caller") or "")})
    return found


def mute_command(device_id):
    """Silence that phone's ringer (ADR-014)."""
    command = ["flickos-phone", "mute"]
    if device_id:
        command += ["--to", device_id]
    return command


def playing_row(state):
    """What the phone plays, or None. Hidden until flickos-phone sends it."""
    row = state.get("playing") if isinstance(state, dict) else None
    if not isinstance(row, dict):
        return None
    title, artist = str(row.get("title") or ""), str(row.get("artist") or "")
    if not title and not artist:
        return None
    return {"id": str(row.get("id") or ""), "title": title, "artist": artist,
            "playing": bool(row.get("playing"))}


def player_command(action, device_id):
    """play, pause or next on what the phone plays (Later item 15)."""
    if action not in PLAYER_ACTIONS:
        raise ValueError(action)
    command = list(PLAYER) + [action]
    if device_id:
        command += ["--to", device_id]
    return command


def received_icons(item):
    """Icon names for a received item's row, the first the theme has wins:
    the file's type, a page, or text. A copy of flickos-phone's, so the
    popup's rows look like the Phone window's."""
    kind, value = item.get("kind"), item.get("value") or ""
    if kind == "page":
        return ["text-html", "text-x-generic"]
    if kind == "file":
        mime = mimetypes.guess_type(value)[0] or ""
        names = [mime.replace("/", "-"), mime.split("/")[0] + "-x-generic"] if "/" in mime else []
        return names + ["application-octet-stream", "unknown"]
    return ["text-x-generic"]


def received_entry(item):
    """(title, subtitle, action, command, icons) for one received item, as
    the Phone window's row: a click does the action (its first one). action
    and command are None when there is nothing to do (a file that is gone)."""
    if not isinstance(item, dict):
        return None
    kind, value = item.get("kind"), item.get("value") or ""
    button, command, gone = None, None, False
    if kind == "page":
        title, button, command = short_address(value), "Open", ["xdg-open", value]
    elif kind == "file":
        title = os.path.basename(value) or "File"
        if item.get("exists") is False:
            gone = True
        elif item.get("openable"):
            button, command = "Open", ["xdg-open", value]
        else:
            button, command = "Show in Folder", ["xdg-open", os.path.dirname(value) or "."]
    elif item.get("app"):
        # An address an app registered with flickos-phone (its "app", the
        # app's name): opened in that app, as the window's first action.
        title, button, command = f"For {item['app']}", "Open", ["xdg-open", value.strip()]
    else:
        lines = value.strip().splitlines()
        title = (lines[0] if lines else "") or "Text"
        title = title if len(title) <= 60 else title[:59] + "…"
        if value.strip():
            button, command = "Copy", ["wl-copy", "--", value]
    parts = []
    if kind == "clipboard":
        parts.append("Clipboard")
    if item.get("device"):
        parts.append(str(item["device"]))
    when = when_text(item.get("time"))
    if when:
        parts.append(when)
    if gone:
        parts.append("no longer there")
    return title, " · ".join(parts), button, command, received_icons(item)


def popup_received(items):
    """The newest POPUP_RECEIVED items, newest first."""
    if not isinstance(items, list):
        return []
    rows = []
    for item in reversed(items):
        entry = received_entry(item)
        if entry is not None:
            rows.append(entry)
        if len(rows) == POPUP_RECEIVED:
            break
    return rows


def apply_event(state, event):
    """Fold one `watch` line into the state the popup shows."""
    phones = state.setdefault("phones", [])
    kind = event.get("event") if isinstance(event, dict) else None
    if kind == "connected":
        phone = event.get("phone") if isinstance(event.get("phone"), dict) else {}
        device_id = phone.get("id")
        if not device_id:
            return state
        found = next((item for item in phones if item.get("id") == device_id), None)
        row = {"id": device_id, "name": phone.get("name") or (found or {}).get("name") or "Phone",
               "connected": True, "battery": phone.get("battery")}
        if found:
            found.update(row)
        else:
            phones.append(row)
    elif kind == "disconnected":
        for phone in phones:
            if phone.get("id") == event.get("id"):
                phone["connected"] = False
                phone["battery"] = None
    elif kind == "forgotten":
        state["phones"] = [phone for phone in phones if phone.get("id") != event.get("id")]
        state["ringing"] = [row for row in (state.get("ringing") or []) if row.get("id") != event.get("id")]
        playing = state.get("playing")
        if isinstance(playing, dict) and playing.get("id") == event.get("id"):
            state["playing"] = None
    elif kind == "battery":
        for phone in phones:
            if phone.get("id") == event.get("id") and phone.get("connected"):
                phone["battery"] = event.get("battery")
    elif kind == "received":
        item = event.get("item")
        if isinstance(item, dict):
            items = state.setdefault("received", [])
            items.append(item)
            del items[:-RECEIVED_KEEP]
    elif kind == "call":
        device_id = event.get("id")
        ringing = [row for row in (state.get("ringing") or []) if row.get("id") != device_id]
        if event.get("state") == "ringing" and device_id:
            name = next((phone.get("name") or "Phone" for phone in phones if phone.get("id") == device_id), "Phone")
            ringing.append({"id": device_id, "name": name, "caller": event.get("caller") or ""})
        state["ringing"] = ringing
    elif kind == "playing":
        title, artist = event.get("title") or "", event.get("artist") or ""
        if title or artist:
            state["playing"] = {"id": event.get("id") or "", "title": title, "artist": artist,
                                "playing": bool(event.get("playing", True))}
        else:
            state["playing"] = None
    return state


def run_json(command, timeout=PHONE_READ_SECONDS):
    """A flickos-phone command's JSON, or PopupError with what it said."""
    import subprocess
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        warn(f"reading the phone: {error}")
        raise PopupError("the phone connection didn't answer") from error
    if done.returncode != 0:
        raise PopupError(error_line(done.stderr or done.stdout) or "the phone connection didn't answer")
    try:
        value = json.loads(done.stdout)
    except ValueError:
        raise PopupError("the phone connection answered in a way that can't be read") from None
    if not isinstance(value, (dict, list)):
        raise PopupError("the phone connection answered in a way that can't be read")
    return value


def error_line(stderr):
    """The last line a command printed, without its program name."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    if not lines:
        return ""
    text = lines[-1]
    return text.split(": ", 1)[1] if ": " in text else text


def watch_events(path, stop):
    """Yield `watch` events until a byte arrives on stop or the daemon closes.
    Raises PopupError when the daemon isn't running or refuses another window.
    Blocks: nothing polls."""
    import select
    import socket
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.connect(path)
    except OSError:
        raise PopupError("the phone connection isn't running") from None
    with conn:
        conn.sendall(b'{"command": "watch"}\n')
        conn.settimeout(None)
        buf = b""
        while True:
            try:
                readable, _, _ = select.select([conn, stop], [], [])
            except (OSError, ValueError):
                break
            if stop in readable:
                break
            try:
                chunk = conn.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("error") and "event" not in event:
                    raise PopupError(str(event["error"]))
                yield event


def closed_text(state):
    """Why the popup has nothing to show, or "" when the connection is on."""
    if not isinstance(state, dict):
        return "The phone connection didn't answer."
    if state.get("live"):
        return "Not available in the live session."
    if not state.get("enabled"):
        return "The phone connection is off. Turn it on in Phone Settings."
    if state.get("blocked"):
        return "KDE Connect is already running on this computer. Use it, or quit it to use this."
    if not state.get("running"):
        return "The phone connection isn't running. Turn it off and on again in Phone Settings."
    return ""


# --- The window (GTK) ------------------------------------------------------------

class PhonePopup:
    """The phone at a glance: its line, the action tiles, Mute while it rings,
    what it plays, the newest received items, Open Phone and Phone Settings.
    Built once, then shown and hidden. Every show reads flickos-phone again,
    in a thread; while shown it follows `watch` and sleeps while hidden."""

    def __init__(self, menu):
        self.menu = menu
        self.GLib, self.Gdk, self.Gio, self.Gtk, self.GtkLayerShell = (
            menu.GLib, menu.Gdk, menu.Gio, menu.Gtk, menu.GtkLayerShell)
        Gtk, GtkLayerShell = self.Gtk, self.GtkLayerShell
        self.corner = None
        self.state = None
        self.chosen = None
        self.quiet = False
        self.combo_open = False
        self.reads = 0
        self.action_reads = 0
        self.watch_gen = 0
        self.watch_write = None
        self.shown_at = None
        window = self.window = Gtk.Window(title="Phone")
        self.fader = menu.fader(window)
        window.get_style_context().add_class("flickos-phone")
        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_namespace(window, NAMESPACE)
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.ON_DEMAND)
        window.connect("key-press-event", self.on_key)
        window.connect("focus-out-event", self.on_focus_out)
        window.connect("delete-event", lambda *_: self.hide() or True)
        window.connect_after("draw", self.on_draw)

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        frame.get_style_context().add_class("phone")
        frame.set_size_request(PHONE_WIDTH, -1)
        window.add(frame)

        self.phone_name = Gtk.Label(xalign=0, wrap=True, max_width_chars=28)
        self.phone_name.set_markup("<b>Phone</b>")
        self.phone_status = Gtk.Label(xalign=0, wrap=True, max_width_chars=36)
        self.phone_status.get_style_context().add_class("dim-label")
        self.phone_status.get_style_context().add_class("subtitle")
        self.chooser = Gtk.ComboBoxText()
        self.chooser.set_no_show_all(True)
        self.chooser.get_accessible().set_name("Phone")
        self.chooser.connect("changed", self.on_phone)
        self.chooser.connect("notify::popup-shown", self.on_combo)
        # Name and status as one line of two, as in the Phone window.
        line = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        line.pack_start(self.phone_name, False, False, 0)
        line.pack_start(self.phone_status, False, False, 0)
        frame.pack_start(line, False, False, 0)
        frame.pack_start(self.chooser, False, False, 0)

        self.loading = Gtk.Box(spacing=8)
        self.loading.set_no_show_all(True)
        self.loading.pack_start(Gtk.Spinner(active=True), False, False, 0)
        self.loading.pack_start(Gtk.Label(label="Loading…"), False, False, 0)
        for child in self.loading.get_children():
            child.show()        # frame.show_all() skips a no_show_all box's children
        frame.pack_start(self.loading, False, False, 0)

        # A GTK window grows only to its content's minimum size, and a
        # scrolled window's is one line: the popup kept the height it had
        # while empty and showed one line of tiles. fit() sets the minimum
        # to what the body needs, up to what fits on the screen.
        self.scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        body = self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.scrolled.add(body)
        frame.pack_start(self.scrolled, True, True, 0)

        self.tiles = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        body.pack_start(self.tiles, False, False, 0)
        self.tiles_empty = Gtk.Label(xalign=0, wrap=True, max_width_chars=36)
        self.tiles_empty.get_style_context().add_class("dim-label")
        self.tiles_empty.set_no_show_all(True)
        body.pack_start(self.tiles_empty, False, False, 0)

        self.calls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.calls.set_no_show_all(True)
        body.pack_start(self.calls, False, False, 0)
        self.media = Gtk.Box(spacing=8)
        self.media.set_no_show_all(True)
        body.pack_start(self.media, False, False, 0)

        heading = Gtk.Label(xalign=0)
        heading.set_markup("<b>Received</b>")
        body.pack_start(heading, False, False, 0)
        self.received = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.received.set_header_func(lambda row, before: row.set_header(Gtk.Separator() if before else None))
        # A row's click does its action, as in the Phone window.
        self.received.connect("row-activated", lambda _list, row: self.open_received(row.command))
        received_frame = Gtk.Frame()
        received_frame.add(self.received)
        body.pack_start(received_frame, False, False, 0)

        self.message = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=40)
        self.message.get_style_context().add_class("message")
        self.message.set_no_show_all(True)
        frame.pack_start(self.message, False, False, 0)
        frame.pack_start(Gtk.Separator(), False, False, 0)
        bottom = Gtk.Box(spacing=8)
        bottom.get_style_context().add_class("bottom")
        # O, not P: Play and Pause (Later item 15) take P, and the two must not share it.
        open_phone = Gtk.Button.new_with_mnemonic("_Open Phone")
        open_phone.connect("clicked", lambda _b: self.menu.run(["flickos-phone", "window"]))
        settings = Gtk.Button.new_with_mnemonic("Phone _Settings")
        settings.connect("clicked", lambda _b: self.menu.run(["flickos-control", "--page", "phone"]))
        bottom.pack_start(open_phone, True, True, 0)
        bottom.pack_start(settings, True, True, 0)
        self.open_phone = open_phone
        frame.pack_start(bottom, False, False, 0)
        frame.show_all()
        for widget in (self.chooser, self.loading, self.tiles_empty, self.calls, self.media, self.message):
            widget.hide()
        self.fit()          # the size it shows with, so the first show doesn't resize
        # Loading the icon theme takes about 0.1 s. Here, not at the first
        # show (the spinner and the tiles need it).
        Gtk.IconTheme.get_default().has_icon("phone-symbolic")
        window.realize()
        window.get_preferred_size()

    # Showing ------------------------------------------------------------------

    def visible(self):
        return self.fader.visible()

    def place(self, corner):
        GtkLayerShell = self.GtkLayerShell
        vertical = corner.split("-")[0]
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, vertical == "top")
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.BOTTOM, vertical == "bottom")
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.LEFT, False)

    def show(self, corner):
        if corner != self.corner:
            self.place(corner)
            self.corner = corner
        self.message.hide()
        self.loading.set_visible(self.state is None)
        self.shown_at = self.menu.clock()
        self.fit()
        self.fader.show()
        self.window.set_focus_visible(False)
        self.open_phone.grab_focus()
        self.read_snapshot()

    def hide(self):
        self.stop_watch()
        self.fader.hide()

    def destroy(self):
        self.hide()
        self.fader.hide_now()
        self.window.destroy()

    def on_key(self, _window, event):
        if event.keyval == self.Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def on_focus_out(self, *_args):
        # The phone chooser's list is another window. Closing for that would
        # shut the popup as it opens.
        if not self.combo_open:
            self.hide()
        return False

    def on_combo(self, combo, _pspec):
        self.combo_open = bool(combo.get_property("popup-shown"))

    def on_draw(self, *_args):
        if self.shown_at is not None:
            self.menu.log(f"phone shown in {self.menu.clock() - self.shown_at:.1f} ms")
            self.shown_at = None
        return False

    def say(self, text):
        self.message.set_text(text)
        self.message.set_visible(bool(text))

    def fit(self):
        """Make room for the whole body, or as much as the screen has
        (larger text, a short screen), and scroll the rest. Also shrinks
        it again when rows go away."""
        width = max(self.body.get_allocated_width(), PHONE_WIDTH - 26)   # less padding and border
        _minimum, natural = self.body.get_preferred_height_for_width(width)
        limit = None
        display = self.Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or (display.get_monitor(0) if display.get_n_monitors() else None)
        if monitor is not None:
            limit = max(PHONE_MIN_BODY, monitor.get_geometry().height - PHONE_CHROME_HEIGHT)
        height = natural if limit is None else min(natural, limit)
        # The minimum before the maximum would refuse one below it, and the
        # other way around.
        if height > self.scrolled.get_max_content_height() >= 0:
            self.scrolled.set_max_content_height(height)
            self.scrolled.set_min_content_height(height)
        else:
            self.scrolled.set_min_content_height(height)
            self.scrolled.set_max_content_height(height)

    # Reading ------------------------------------------------------------------

    def read_snapshot(self):
        """state and the action tiles, off the main loop. A newer read wins."""
        self.reads += 1
        number = self.reads
        chosen = self.chosen

        def work():
            state = run_json(["flickos-phone", "state"])
            target = action_target(state, chosen)
            command = ["flickos-phone", "actions", "--json"]
            if target:
                command += ["--to", target]
            return state, run_json(command), target

        self._ask(number, work, self.answer)

    def read_actions(self):
        """The tiles for the phone the chooser shows, after it changes."""
        self.action_reads += 1
        number = self.action_reads
        target = action_target(self.state or {}, self.chosen)

        def work():
            command = ["flickos-phone", "actions", "--json"]
            if target:
                command += ["--to", target]
            return run_json(command)

        self._ask(number, work, self.actions_answer)

    def _ask(self, number, work, answer):
        import threading
        import traceback

        def thread():
            try:
                result, error = work(), None
            except PopupError as failure:
                result, error = None, str(failure)
            except Exception:
                traceback.print_exc()
                result, error = None, "Something went wrong reading the phone. Try again."
            self.GLib.idle_add(answer, number, result, error)

        threading.Thread(target=thread, daemon=True).start()

    def answer(self, number, result, error):
        if number != self.reads:
            return False
        self.loading.hide()
        if error:
            self.say(self.sentence(error))
            return False
        state, actions, target = result
        self.chosen = target or (chosen_phone(state, self.chosen) or {}).get("id")
        self.show_state(state)
        self.show_actions(actions)
        self.fit()
        if self.visible() and state.get("running") and not closed_text(state):
            self.ensure_watch()
        return False

    def actions_answer(self, number, actions, error):
        if number != self.action_reads:
            return False
        if error:
            self.say(self.sentence(error))
            return False
        self.show_actions(actions)
        self.fit()
        return False

    def sentence(self, text):
        text = (text or "").strip()
        if not text:
            return "Something went wrong."
        if text[-1] not in ".!?":
            text += "."
        return text[0].upper() + text[1:]

    def show_state(self, state):
        self.state = state
        reason = closed_text(state)
        self.fill_phones()
        self.fill_ringing()
        self.fill_playing()
        self.fill_received()
        if reason:
            self.tiles_empty.set_text(reason)
            self.tiles_empty.show()
            self.tiles.hide()
        else:
            self.tiles.show()

    def show_actions(self, actions):
        if closed_text(self.state or {}):
            return
        tiles = action_tiles(actions)
        for child in self.tiles.get_children():
            self.tiles.remove(child)
        Gtk = self.Gtk
        theme = Gtk.IconTheme.get_default()
        for number, tile in enumerate(tiles):
            # Quick Settings' tile: the icon, then the words beside it.
            button = Gtk.Button()
            button.get_style_context().add_class("tile")
            content = Gtk.Box(spacing=10)
            icon = tile_icon(tile["icon"], theme.has_icon)
            content.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
            label = Gtk.Label(label=tile["label"], xalign=0, wrap=True, max_width_chars=14)
            content.pack_start(label, True, True, 0)
            button.add(content)
            button.get_accessible().set_name(tile["label"])
            button.connect("clicked", lambda _b, command=tile["command"]: self.menu.run(command))
            self.tiles.attach(button, number % TILE_COLUMNS, number // TILE_COLUMNS, 1, 1)
        self.tiles.show_all()
        if tiles:
            self.tiles_empty.hide()
        elif self.state and not self.state.get("phones"):
            self.tiles_empty.set_text("No phone is paired. Add one in Phone Settings.")
            self.tiles_empty.show()
        elif self.state and not (chosen_phone(self.state, self.chosen) or {}).get("connected"):
            self.tiles_empty.set_text("This phone isn't connected.")
            self.tiles_empty.show()
        else:
            self.tiles_empty.set_text("Nothing to send from here right now.")
            self.tiles_empty.show()

    def fill_phones(self):
        state = self.state or {}
        phones = [phone for phone in (state.get("phones") or []) if isinstance(phone, dict)]
        phone = chosen_phone(state, self.chosen)
        self.chosen = phone.get("id") if phone else None
        self.quiet = True
        self.chooser.remove_all()
        if len(phones) > 1:
            for item in phones:
                self.chooser.append(item.get("id") or "", item.get("name") or "Phone")
            if self.chosen:
                self.chooser.set_active_id(self.chosen)
            self.chooser.show()
        else:
            self.chooser.hide()
        self.quiet = False
        self.fill_line()

    def fill_line(self):
        name, status = phone_line(chosen_phone(self.state or {}, self.chosen))
        self.phone_name.set_markup(f"<b>{self.GLib.markup_escape_text(name)}</b>")
        self.phone_status.set_text(status)

    def on_phone(self, combo):
        if self.quiet:
            return
        device_id = combo.get_active_id()
        if device_id and device_id != self.chosen:
            self.chosen = device_id
            self.fill_line()
            self.read_actions()

    def fill_ringing(self):
        for child in self.calls.get_children():
            self.calls.remove(child)
        rows = ringing_rows(self.state or {})
        for row in rows:
            line = self.Gtk.Box(spacing=8)
            text = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, valign=self.Gtk.Align.CENTER)
            title = self.Gtk.Label(label="Incoming call", xalign=0)
            caller = self.Gtk.Label(label=row["caller"] or row["name"], xalign=0, wrap=True, max_width_chars=28)
            caller.get_style_context().add_class("dim-label")
            caller.get_style_context().add_class("subtitle")
            text.pack_start(title, False, False, 0)
            text.pack_start(caller, False, False, 0)
            # One Mute can take the mnemonic. A second phone ringing keeps
            # the word, so the two underlines don't land on the same letter.
            if len(rows) == 1:
                button = self.Gtk.Button.new_with_mnemonic("_Mute")
            else:
                button = self.Gtk.Button(label="Mute")
            button.set_tooltip_text("Mute the ringer")
            button.get_accessible().set_name(f"Mute {row['name']}")
            button.connect("clicked", lambda _b, device=row["id"]: self.mute(device))
            line.pack_start(text, True, True, 0)
            line.pack_start(button, False, False, 0)
            # show_all() skips a no_show_all box's children, so each line
            # shows itself.
            line.show_all()
            self.calls.pack_start(line, False, False, 0)
        self.calls.set_visible(bool(rows))

    def fill_playing(self):
        for child in self.media.get_children():
            self.media.remove(child)
        row = playing_row(self.state or {})
        if row is None:
            self.media.hide()
            return
        text = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, valign=self.Gtk.Align.CENTER)
        title = self.Gtk.Label(label=row["title"] or row["artist"], xalign=0, wrap=True, max_width_chars=24)
        text.pack_start(title, False, False, 0)
        if row["title"] and row["artist"]:
            artist = self.Gtk.Label(label=row["artist"], xalign=0, wrap=True, max_width_chars=24)
            artist.get_style_context().add_class("dim-label")
            artist.get_style_context().add_class("subtitle")
            text.pack_start(artist, False, False, 0)
        action = "pause" if row["playing"] else "play"
        verb = "Pause" if row["playing"] else "Play"
        play = self.Gtk.Button.new_with_mnemonic("_Pause" if row["playing"] else "_Play")
        play.get_accessible().set_name(verb)
        play.connect("clicked", lambda _b, action=action, device=row["id"]: self.player(action, device))
        nxt = self.Gtk.Button.new_with_mnemonic("_Next")
        nxt.get_accessible().set_name("Next")
        nxt.connect("clicked", lambda _b, device=row["id"]: self.player("next", device))
        self.media.pack_start(text, True, True, 0)
        self.media.pack_start(play, False, False, 0)
        self.media.pack_start(nxt, False, False, 0)
        # show_all() skips a no_show_all box's children.
        for child in self.media.get_children():
            child.show_all()
        self.media.show()

    def fill_received(self):
        for child in self.received.get_children():
            self.received.remove(child)
        rows = popup_received((self.state or {}).get("received"))
        if not rows:
            self.received.add(self.row("Nothing yet", "What a phone sends shows here for a week", None, None))
        for title, subtitle, action, command, icons in rows:
            self.received.add(self.row(title, subtitle, action, command, icons))
        self.received.show_all()

    def row(self, title, subtitle, action, command, icons=None):
        Gtk = self.Gtk
        line = Gtk.Box(spacing=8, margin=8)
        if icons:
            line.pack_start(Gtk.Image.new_from_gicon(self.Gio.ThemedIcon.new_from_names(icons), Gtk.IconSize.DND),
                            False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        label = Gtk.Label(label=title, xalign=0, wrap=True, max_width_chars=28)
        text.pack_start(label, False, False, 0)
        if subtitle:
            second = Gtk.Label(label=subtitle, xalign=0, wrap=True, max_width_chars=32)
            second.get_style_context().add_class("dim-label")
            second.get_style_context().add_class("subtitle")
            text.pack_start(second, False, False, 0)
        line.pack_start(text, True, True, 0)
        row = Gtk.ListBoxRow(activatable=bool(action and command))
        row.command = command
        if action and command:
            row.set_tooltip_text(action)
            row.get_accessible().set_description(f"{action} {title}")
        row.add(line)
        return row

    def open_received(self, command):
        """Copy stays here. Opening a page or a file closes the popup."""
        if not command:
            return
        if command[0] == "wl-copy":
            self.run_keep(command, "Could not copy")
            return
        self.menu.run(command)

    def mute(self, device_id):
        self.run_keep(mute_command(device_id), "Could not mute the ringer")

    def player(self, action, device_id):
        self.run_keep(player_command(action, device_id), "Could not change what's playing")

    def run_keep(self, command, failed):
        """Run command without closing. Say so, with the command's own words,
        when it fails (WIN-10)."""
        Gio, GLib = self.Gio, self.GLib
        try:
            process = Gio.Subprocess.new(list(command), Gio.SubprocessFlags.STDOUT_SILENCE
                                         | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as error:
            self.say(f"{failed}: {error.message}")
            return

        def finished(process, result):
            try:
                _ok, _stdout, stderr = process.communicate_utf8_finish(result)
                ok = process.get_successful()
            except GLib.Error as error:
                stderr, ok = error.message, False
            if not ok:
                detail = error_line(stderr or "")
                self.say(f"{failed}: {detail}" if detail else failed + ".")

        process.communicate_utf8_async(None, None, finished)

    # watch, only while shown --------------------------------------------------

    def ensure_watch(self):
        if self.watch_write is not None:
            return
        root = self.menu.root
        if not root:
            return
        read, write = os.pipe()
        self.watch_write = write
        self.watch_gen += 1
        generation = self.watch_gen
        import threading
        threading.Thread(target=self.watch_loop, args=(os.path.join(root, PHONE_CONTROL), read, generation),
                         daemon=True).start()

    def stop_watch(self):
        self.watch_gen += 1
        write = self.watch_write
        self.watch_write = None
        if write is None:
            return
        try:
            os.write(write, b"x")
        except OSError:
            pass
        os.close(write)

    def watch_loop(self, path, stop, generation):
        try:
            for event in watch_events(path, stop):
                self.GLib.idle_add(self.on_watch, generation, event)
        except PopupError as error:
            self.GLib.idle_add(self.watch_failed, generation, str(error))
        finally:
            os.close(stop)

    def watch_failed(self, generation, text):
        if generation != self.watch_gen:
            return False
        if self.visible():
            self.say(self.sentence(text))
        write = self.watch_write
        self.watch_write = None
        if write is not None:
            os.close(write)
        return False

    def on_watch(self, generation, event):
        if generation != self.watch_gen or self.state is None or not self.visible():
            return False
        kind = event.get("event")
        apply_event(self.state, event)
        if kind in ("connected", "disconnected", "forgotten"):
            self.fill_phones()
            self.fill_ringing()
            self.read_actions()
        elif kind == "battery":
            self.fill_line()
        elif kind == "received":
            self.fill_received()
        elif kind == "call":
            self.fill_ringing()
        elif kind == "playing":
            self.fill_playing()
        else:
            return False                # not drawn here (a transfer's progress is the window's)
        self.fit()
        return False
