"""The Phone window. Loaded only by `flickos-phone window`.

The daemon and the panel button never import this file, so they don't pay
for GTK or for compiling it. It holds no settings: Phone Settings is the
Settings window's Phone page. One window per session (the lock in the
command).
"""

import datetime
import mimetypes
import os
import signal
import threading
import urllib.parse
import urllib.request

# Underlines for the action buttons, which show the actions' short words. The
# shared words (ACTIONS) have none: the menu and `actions --json` show those.
# Letters stay unique with _Settings (GTK matches them in either case: C and c
# are the same key).
BUTTON_MNEMONIC = {
    "files": "Send _Files…",
    "text": "Send _Text…",
    "clipboard": "Send _Clipboard",
    "screenshot": "Send Screens_hot",
    "ring": "_Ring Phone",
    "browse": "_Browse Files",
    "screen": "Show Scr_een",
    "second-screen": "Sec_ond Screen",
    "second-screen-stop": "Stop Secon_d Screen",
}

# A received row's picture: a thumbnail this size, or the item's icon in its middle.
THUMBNAIL = 48

APP_ID = "flickos-phone"
TITLE = "Phone"
SETTINGS = ["flickos-control", "--page", "phone"]
# The empty and off states' button (HIG WIN-12). P is free next to _Settings
# and the action buttons' letters.
SETTINGS_BUTTON = "_Phone Settings"


def load_gtk():
    """(GLib, Gtk, Gio, Gdk, GdkPixbuf), or (None, why it isn't available)."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GLib
        GLib.set_prgname(APP_ID)
        from gi.repository import Gdk, GdkPixbuf, Gio, Gtk
    except (ImportError, ValueError) as error:
        return None, f"GTK 3 is not available ({error})"
    if not Gtk.init_check([APP_ID])[0]:
        return None, "cannot open a window (no Wayland display)"
    return (GLib, Gtk, Gio, Gdk, GdkPixbuf), None


def button_icon(name, has_icon):
    """An action button's icon: the -symbolic one, as a toolbar's, else the
    name itself, else the phone (HIG VIS-6: the first the theme has)."""
    for candidate in (name + "-symbolic", name, "phone-symbolic", "phone"):
        if has_icon(candidate):
            return candidate
    return "application-x-executable"


def when_text(seconds):
    """14:02, Yesterday 14:02, or Tue 22 Sep."""
    moment = datetime.datetime.fromtimestamp(seconds or 0)
    today = datetime.date.today()
    if moment.date() == today:
        return moment.strftime("%H:%M")
    if (today - moment.date()).days == 1:
        return "Yesterday " + moment.strftime("%H:%M")
    return moment.strftime("%a %d %b")


def picture_path(item):
    """The file of a received picture that is still there, for a thumbnail;
    None for anything else."""
    value = item.get("value") or ""
    if item.get("kind") != "file" or item.get("exists") is False:
        return None
    mime = mimetypes.guess_type(value)[0] or ""
    return value if mime.startswith("image/") else None


def transfer_text(item, format_size):
    """A transfer row's second line: To Pixel · 12.3 MB of 200.0 MB."""
    device = item.get("device") or "the phone"
    if item.get("state") == "waiting":
        if item.get("direction") == "in":
            return f"Starting to receive from {device}"
        return f"Waiting for {device} to fetch it"
    where = f"From {device}" if item.get("direction") == "in" else f"To {device}"
    return f"{where} · {format_size(item.get('done') or 0)} of {format_size(item.get('size') or 0)}"


def sentence(text):
    """flickos-phone's last line as the status line shows it: "flickos-phone:
    no phone is connected" becomes "No phone is connected.", as its
    notifications say it."""
    text = text.strip()
    if text.startswith("flickos-phone: "):
        text = text[len("flickos-phone: "):]
        if not text.split(" ", 1)[0].endswith(":"):        # "a.jpg: …" keeps the file's own name
            text = text[:1].upper() + text[1:]
        if text and text[-1] not in ".!?…":
            text += "."
    return text


def drop_command(uris, text, device_id=None, web_address=None):
    """flickos-phone's send for what was dropped on the window, or None when
    nothing in it can be sent. Files on this computer and web addresses go
    as they are; other text as text. A folder on the phone (gvfs, sftp://) or
    in the trash isn't a file here, so it is left out. web_address is
    flickos-phone's test for one."""
    things = []
    for uri in uris or ():
        parts = urllib.parse.urlsplit(uri)
        if parts.scheme == "file" and parts.netloc in ("", "localhost"):
            things.append(urllib.request.url2pathname(parts.path))
        elif web_address and web_address(uri):
            things.append(uri)
    argv = ["flickos-phone", "send"] + (["--to", device_id] if device_id else [])
    if things:
        return argv + ["--", *things]
    address = (text or "").strip()
    if not address:
        return None
    if "\n" not in address and web_address and web_address(address):
        return argv + ["--", address]
    return argv + [f"--text={text}"]


def run(page, phone, lock):
    """Show the window until it is closed. lock is the single-instance lock;
    it stays open for as long as this runs."""
    gtk, error = load_gtk()
    if gtk is None:
        phone.warn(error)
        return 1
    PhoneWindow(gtk, phone, page, lock).open()
    return 0


class PhoneWindow:
    """One page: the phone's line with Settings beside it, a row of action
    buttons, then everything received. A sidebar comes back with a second
    page worth having (a history of the phone's notifications). While the
    phone connection is off, the window says so."""

    def __init__(self, gtk, phone, _page, lock):
        # _page: there is one page, and a new window shows Received's list
        # from the top anyway.
        self.GLib, self.Gtk, self.Gio, self.Gdk, self.GdkPixbuf = gtk
        self.phone = phone
        self.lock = lock            # kept so the single-instance lock isn't closed
        self.state = None
        self.chosen = None          # the paired phone the actions go to
        self.quiet = False
        self.watching = False
        self.watch_write = None     # a byte here ends iter_watch; no timer
        self.reads = 0              # only the newest state read is shown
        self.commands = {}          # the shown actions' argv by id: Ctrl+V and drops
        self.device_id = None       # --to, while several phones are paired
        self.dropping = False       # the window takes drops (a phone is connected)
        self.thumbnails = {}        # path -> (mtime, pixbuf or None), read in a thread
        self.build()

    def build(self):
        Gtk = self.Gtk
        window = self.window = Gtk.Window(title=TITLE)
        window.set_icon_name("phone")
        window.set_default_size(640, 560)
        window.connect("delete-event", self.on_delete)
        window.connect("notify::is-active", self.on_active)
        window.connect("key-press-event", self.on_key)

        # Drops land on the content, not the window: GtkWindow is already a
        # drop target of GTK's own (application/x-rootwindow-drop).
        outer = self.drop_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.connect("drag-data-received", self.on_drop)
        window.add(outer)

        self.notice_bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING, no_show_all=True)
        self.notice_label = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=60)
        self.notice_bar.get_content_area().add(self.notice_label)
        self.notice_label.show()
        self.notice_settings = self.notice_bar.add_button(SETTINGS_BUTTON, self.Gtk.ResponseType.APPLY)
        self.notice_settings.set_use_underline(True)
        self.notice_settings.set_no_show_all(True)
        self.notice_bar.connect("response", lambda _bar, _response: self.open_settings())
        outer.pack_start(self.notice_bar, False, False, 0)

        # The phone's line, the chooser while several are paired, and Settings.
        header = Gtk.Box(spacing=12, margin_top=18, margin_bottom=12, margin_start=24, margin_end=24)
        line = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        self.phone_name = Gtk.Label(xalign=0, wrap=True, max_width_chars=30)
        self.phone_name.set_markup("<b>Phone</b>")
        self.phone_status = Gtk.Label(xalign=0, wrap=True, max_width_chars=40)
        self.phone_status.get_style_context().add_class("dim-label")
        line.pack_start(self.phone_name, False, False, 0)
        line.pack_start(self.phone_status, False, False, 0)
        header.pack_start(line, True, True, 0)
        self.chooser = Gtk.ComboBoxText(valign=Gtk.Align.CENTER)
        self.chooser.set_no_show_all(True)
        self.chooser.get_accessible().set_name("Phone")
        self.chooser.connect("changed", self.phone_chosen)
        header.pack_start(self.chooser, False, False, 0)
        self.settings_button = Gtk.Button.new_with_mnemonic("_Settings")
        self.settings_button.set_tooltip_text("Phone Settings")
        self.settings_button.set_valign(Gtk.Align.CENTER)
        self.settings_button.connect("clicked", self.open_settings)
        header.pack_start(self.settings_button, False, False, 0)
        outer.pack_start(header, False, False, 0)

        self.stack = Gtk.Stack(homogeneous=False)
        self.stack.add_named(self.loading_page(), "loading")
        self.stack.add_named(self.closed_page(), "closed")
        self.stack.add_named(self.phone_page(), "phone")
        outer.pack_start(self.stack, True, True, 0)

        self.status = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=60,
                                margin_top=12, margin_bottom=12, margin_start=24, margin_end=24)
        self.status.get_style_context().add_class("dim-label")
        outer.pack_start(self.status, False, False, 0)
        self.stack.set_visible_child_name("loading")

    def loading_page(self):
        box = self.Gtk.Box(spacing=8, margin_bottom=24, margin_start=24, margin_end=24)
        # Turns only while on screen: GTK 3 keeps animating an active spinner
        # on a stack page that isn't shown, 60 redraws a second (HIG CODE-10).
        spinner = self.Gtk.Spinner()
        spinner.connect("map", lambda s: s.start())
        spinner.connect("unmap", lambda s: s.stop())
        box.pack_start(spinner, False, False, 0)
        box.pack_start(self.dim("Loading…"), False, False, 0)
        return box

    def closed_page(self):
        box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, margin_bottom=24, margin_start=24,
                           margin_end=24)
        self.closed_label = self.Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=60)
        box.pack_start(self.closed_label, False, False, 0)
        self.closed_settings = self.settings_link()
        box.pack_start(self.closed_settings, False, False, 0)
        return box

    def settings_link(self):
        """Phone Settings, next to a message saying that's where to go."""
        button = self.Gtk.Button.new_with_mnemonic(SETTINGS_BUTTON)
        button.set_halign(self.Gtk.Align.START)
        button.set_margin_top(12)
        button.set_no_show_all(True)
        button.connect("clicked", self.open_settings)
        return button

    def phone_page(self):
        """The actions stay in place; only the received list scrolls."""
        Gtk = self.Gtk
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=24, margin_end=24)
        self.actions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                                   column_spacing=6, row_spacing=6, max_children_per_line=len(BUTTON_MNEMONIC),
                                   valign=Gtk.Align.START)
        top.pack_start(self.actions, False, False, 0)
        self.drop_hint = self.dim("You can also drop files or a link on this window. Ctrl+V sends the clipboard.")
        self.drop_hint.set_no_show_all(True)
        top.pack_start(self.drop_hint, False, False, 0)
        self.actions_empty = self.dim("Nothing to send from here right now.")
        self.actions_empty.set_no_show_all(True)
        top.pack_start(self.actions_empty, False, False, 0)
        page.pack_start(top, False, False, 0)
        # Files on their way, while there are any (`watch` lines `transfer`).
        self.transfers = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=18,
                                 margin_start=24, margin_end=24, no_show_all=True)
        heading = self.heading("Transfers")
        heading.show()
        self.transfers.pack_start(heading, False, False, 0)
        frame, self.transfer_list = self.framed_list()
        frame.show_all()
        self.transfers.pack_start(frame, False, False, 0)
        page.pack_start(self.transfers, False, False, 0)
        self.transfer_rows = {}         # transfer id -> (row, progress bar, second line)
        heading = self.heading("Received")
        heading.set_margin_top(18)
        heading.set_margin_start(24)
        page.pack_start(heading, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6, margin_bottom=12,
                      margin_start=24, margin_end=24)
        self.received_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.received_scroll.add(box)
        frame, self.received_rows = self.framed_list()
        # A row's click does its first action (Open, or Copy for text).
        self.received_rows.connect("row-activated", lambda _list, row: self.run_received(row.command))
        box.pack_start(frame, False, False, 0)
        page.pack_start(self.received_scroll, True, True, 0)
        return page

    def heading(self, text):
        label = self.Gtk.Label(xalign=0, use_markup=True)
        label.set_markup(f"<b>{self.GLib.markup_escape_text(text)}</b>")
        return label

    def dim(self, text):
        label = self.Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        label.set_text(text)
        label.get_style_context().add_class("dim-label")
        return label

    def framed_list(self):
        Gtk = self.Gtk
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        rows.set_header_func(lambda row, before: row.set_header(Gtk.Separator() if before else None))
        frame = Gtk.Frame()
        frame.add(rows)
        return frame, rows

    def open(self):
        self.GLib.unix_signal_add(self.GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.requested)
        self.GLib.idle_add(self.catch_up)
        self.window.show_all()
        self.refresh()
        self.Gtk.main()

    def on_delete(self, *_args):
        self.stop_watch()
        self.Gtk.main_quit()
        return False

    def stop_watch(self):
        write = self.watch_write
        self.watch_write = None
        if write is not None:
            try:
                os.write(write, b"x")
            except OSError:
                pass
            os.close(write)

    def on_active(self, window, _param):
        """A change made in Phone Settings shows when the window is used again.
        Nothing polls while it sits in the background."""
        if window.is_active() and self.state is not None:
            self.refresh()

    def catch_up(self):
        """A second `window` that arrived while this one was still starting."""
        page = self.phone.take_window_request()
        if page:
            self.show_page(page)
            self.present()
        return False

    def requested(self):
        """A second `window` (SIGUSR1): show its page and come forward."""
        self.show_page(self.phone.take_window_request())
        self.present()
        return True

    def present(self):
        if not self.window.is_active():
            # labwc lets only the focused client raise a window. Mapping it
            # again gives it the focus.
            self.window.hide()
            self.window.show()
        self.window.present()

    def show_page(self, page):
        """There is one page; Received is the list on it, newest first, so
        `--page received` scrolls that list to the top."""
        if page == "received":
            adjustment = self.received_scroll.get_vadjustment()
            adjustment.set_value(adjustment.get_lower())

    def phone_chosen(self, combo):
        if self.quiet:
            return
        device_id = combo.get_active_id()
        if device_id and device_id != self.chosen:
            self.chosen = device_id
            self.fill_phone_line()
            self.fill_actions()

    def refresh(self):
        """Read `state` off the main loop. A newer read wins (PERF-2)."""
        self.reads += 1
        number = self.reads

        def work():
            import io
            import json
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = self.phone.cmd_state(None)
            if code != 0:
                raise self.phone.PhoneError("the phone connection didn't answer")
            return json.loads(buf.getvalue())

        def finish(state, error):
            if number != self.reads:
                return False
            if error:
                self.status.set_text(error)
                if self.state is None:
                    self.show_closed(error)
                return False
            self.show_state(state)
            return False

        def thread():
            try:
                state, error = work(), None
            except self.phone.PhoneError as failure:
                state, error = None, str(failure)
            except Exception as failure:
                import traceback
                traceback.print_exc()
                state, error = None, f"{type(failure).__name__}: {failure}"
            self.GLib.idle_add(finish, state, error)

        threading.Thread(target=thread, daemon=True).start()

    def show_state(self, state):
        self.state = state
        self.status.set_text("")
        if state.get("live"):
            self.show_closed("Not available in the live session.", settings=False)
            return
        if not state.get("enabled"):
            self.show_closed("The phone connection is off. Turn it on in Phone Settings.")
            return
        if state.get("blocked"):
            self.set_notice("KDE Connect is already running on this computer. Use it, or quit it to use this.")
        elif not state.get("running"):
            self.set_notice("The phone connection isn't running. Turn it off and on again in Phone Settings.",
                            settings=True)
        else:
            self.set_notice("")
        self.fill_phones()
        self.fill_actions()
        self.fill_received()
        self.fill_transfers()
        self.stack.set_visible_child_name("phone")
        if state.get("running"):
            self.ensure_watch()

    def show_closed(self, message, settings=True):
        self.chooser.hide()
        self.phone_name.set_markup("<b>Phone</b>")
        self.phone_status.set_text("Off")
        self.set_notice("")
        self.closed_label.set_text(message)
        self.closed_settings.set_visible(settings)
        self.settings_button.hide()     # the message's own button, or none in the live session
        self.set_dropping(False)
        self.stack.set_visible_child_name("closed")

    def set_notice(self, text, settings=False):
        """settings: the bar has Phone Settings, in place of the header's
        Settings (one at a time)."""
        self.notice_label.set_text(text)
        self.notice_settings.set_visible(settings)
        self.notice_bar.set_visible(bool(text))
        self.settings_button.set_visible(not settings)

    def chosen_phone(self):
        phones = (self.state or {}).get("phones") or []
        if self.chosen:
            for phone in phones:
                if phone.get("id") == self.chosen:
                    return phone
        connected = [phone for phone in phones if phone.get("connected")]
        return (connected or phones or [None])[0]

    def fill_phones(self):
        phones = self.state.get("phones") or []
        phone = self.chosen_phone()
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
        self.fill_phone_line()

    def fill_phone_line(self):
        name, status = self.phone.phone_line(self.chosen_phone())
        self.phone_name.set_markup(f"<b>{self.GLib.markup_escape_text(name)}</b>")
        self.phone_status.set_text(status)

    def fill_actions(self):
        phone = self.chosen_phone()
        several = len((self.state.get("phones") or [])) > 1
        device_id = phone.get("id") if phone and several else None
        connected = bool(phone and phone.get("connected"))
        screen = [self.phone.SCREEN_COMMAND] if self.phone.shutil.which(self.phone.SCREEN_COMMAND) else None
        rows = [row for row in self.phone.action_list(
            connected, device_id=device_id, screenshot=self.phone.shutil.which("grim") is not None,
            files=self.phone.files_available(), screen=screen) if row["shown"]]
        self.device_id = device_id
        self.commands = {row["id"]: row["command"] for row in rows}
        self.set_dropping(connected)
        self.drop_hint.set_visible(connected)
        for child in self.actions.get_children():
            self.actions.remove(child)
        theme = self.Gtk.IconTheme.get_default()
        for row in rows:
            button = self.Gtk.Button.new_with_mnemonic(BUTTON_MNEMONIC.get(row["id"], row["short"]))
            button.set_image(self.Gtk.Image.new_from_icon_name(button_icon(row["icon"], theme.has_icon),
                                                               self.Gtk.IconSize.BUTTON))
            button.set_always_show_image(True)
            button.connect("clicked", lambda _b, argv=row["command"]: self.run_phone(argv))
            self.actions.add(button)
        self.actions.show_all()
        self.actions.set_visible(bool(rows))
        # Without a connected phone the phone's line says why ("No phone
        # paired, add one in Phone Settings", with Settings beside it).
        self.actions_empty.set_visible(not rows and connected)

    def fill_received(self):
        self.fill_list(self.received_rows, list(reversed(self.state.get("received") or [])))

    def fill_transfers(self):
        """Rows are updated in place, so Cancel stays where it is while the
        bar moves; a row goes when its transfer ends (a received file then
        shows in Received)."""
        items = {item.get("id"): item for item in self.state.get("transfers") or [] if item.get("id")}
        for transfer_id in list(self.transfer_rows):
            if transfer_id not in items:
                self.transfer_list.remove(self.transfer_rows.pop(transfer_id)[0])
        for transfer_id, item in items.items():
            if transfer_id not in self.transfer_rows:
                self.transfer_rows[transfer_id] = self.transfer_row(item)
                self.transfer_list.add(self.transfer_rows[transfer_id][0])
            _row, bar, note = self.transfer_rows[transfer_id]
            size = item.get("size") or 0
            bar.set_fraction(min(1.0, (item.get("done") or 0) / size) if size else 0.0)
            note.set_text(transfer_text(item, self.GLib.format_size))
        self.transfer_list.show_all()
        self.transfers.set_visible(bool(items))

    def transfer_row(self, item):
        Gtk = self.Gtk
        line = Gtk.Box(spacing=12, margin=10)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        text.pack_start(Gtk.Label(label=item.get("name") or "", xalign=0, wrap=True, max_width_chars=40),
                        False, False, 0)
        bar = Gtk.ProgressBar()
        text.pack_start(bar, False, False, 0)
        note = self.dim("")
        text.pack_start(note, False, False, 0)
        line.pack_start(text, True, True, 0)
        cancel = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER)
        cancel.get_accessible().set_name(f"Cancel {item.get('name') or ''}")
        argv = ["flickos-phone", "cancel", item["id"]]
        cancel.connect("clicked", lambda button: (button.set_sensitive(False), self.run_phone(argv)))
        line.pack_end(cancel, False, False, 0)
        row = Gtk.ListBoxRow(activatable=False)
        row.add(line)
        return row, bar, note

    def fill_list(self, rows, items):
        """One row per item: its picture, title and line, a click for the
        first action and ⋯ for the others (received_actions orders them)."""
        Gtk = self.Gtk
        for child in rows.get_children():
            rows.remove(child)
        pictures = []
        for item in items:
            title, note, actions = self.phone.received_actions(item)
            parts = []
            if note and note != "no longer there":
                parts.append(note)
            if item.get("device"):
                parts.append(item["device"])
            parts.append(when_text(item.get("time")))
            subtitle = " · ".join(parts)
            if note == "no longer there":
                subtitle += " · no longer there"
            icon = Gtk.Image.new_from_gicon(self.Gio.ThemedIcon.new_from_names(self.phone.received_icons(item)),
                                            Gtk.IconSize.DND)
            icon.set_size_request(THUMBNAIL, THUMBNAIL)
            path = picture_path(item)
            if path:
                pictures.append((path, icon))
            more = self.more_button(title, actions[1:]) if len(actions) > 1 else None
            row = self.row(title, more, subtitle, icon)
            row.command = None
            if actions:
                label, accessible, argv = actions[0]
                row.command = argv
                row.set_activatable(True)
                row.set_tooltip_text(label)
                row.get_accessible().set_description(accessible)
            rows.add(row)
        if not items:
            rows.add(self.row("Nothing yet", subtitle="What a phone sends shows here for a week"))
        rows.show_all()
        if pictures:
            threading.Thread(target=self.load_thumbnails, args=(pictures,), daemon=True).start()

    def more_button(self, title, actions):
        """⋯: the actions after the first, in a menu."""
        Gtk = self.Gtk
        menu = Gtk.Menu()
        for label, _accessible, argv in actions:
            entry = Gtk.MenuItem(label=label)
            entry.connect("activate", lambda _entry, command=argv: self.run_received(command))
            menu.append(entry)
        menu.show_all()
        button = Gtk.MenuButton(popup=menu, relief=Gtk.ReliefStyle.NONE)
        button.set_image(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.BUTTON))
        button.set_tooltip_text("More")
        button.get_accessible().set_name(f"More for {title}")
        return button

    def load_thumbnails(self, pictures):
        """In a thread: decoding a phone's photo takes tens of ms (PERF-2).
        Kept per path and mtime, so a refill doesn't decode again."""
        for path, image in pictures:
            pixbuf = self.thumbnail(path)
            if pixbuf is not None:
                self.GLib.idle_add(image.set_from_pixbuf, pixbuf)

    def thumbnail(self, path):
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            return None
        cached = self.thumbnails.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            pixbuf = self.GdkPixbuf.Pixbuf.new_from_file_at_scale(path, THUMBNAIL, THUMBNAIL, True)
            pixbuf = pixbuf.apply_embedded_orientation() or pixbuf      # phones store photos sideways
        except self.GLib.Error:
            pixbuf = None                                               # a type GdkPixbuf can't read: the icon stays
        self.thumbnails[path] = (mtime, pixbuf)
        return pixbuf

    def run_received(self, argv):
        """Open or copy a received item. Copying says so; an opened page or
        file is its own window."""
        if not argv:
            return
        self.start(argv)
        if argv[0] == "wl-copy":
            self.status.set_text("Copied.")

    def row(self, title, widget=None, subtitle="", icon=None):
        Gtk = self.Gtk
        line = Gtk.Box(spacing=12, margin=10)
        if icon is not None:
            line.pack_start(icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        label = Gtk.Label(label=title, xalign=0, wrap=True, max_width_chars=40)
        text.pack_start(label, False, False, 0)
        second = self.dim(subtitle)
        text.pack_start(second, False, False, 0)
        line.pack_start(text, True, True, 0)
        if widget is not None:
            widget.set_valign(Gtk.Align.CENTER)
            line.pack_end(widget, False, False, 0)
        row = Gtk.ListBoxRow(activatable=False)
        row.add(line)
        return row

    def set_dropping(self, on):
        """Files and links dropped on the window are sent, only while a phone
        is connected; otherwise the window refuses them."""
        if on == self.dropping:
            return
        self.dropping = on
        if on:
            self.drop_area.drag_dest_set(self.Gtk.DestDefaults.ALL, [], self.Gdk.DragAction.COPY)
            self.drop_area.drag_dest_add_uri_targets()
            self.drop_area.drag_dest_add_text_targets()
        else:
            self.drop_area.drag_dest_unset()

    def on_drop(self, _widget, _context, _x, _y, data, _info, _time):
        uris = data.get_uris() or []
        text = "" if uris else (data.get_text() or "")
        argv = drop_command(uris, text, self.device_id, self.phone.web_address)
        if argv is None:
            self.status.set_text("Only files on this computer, links and text can be sent." if uris else "")
            return
        self.run_phone(argv)

    def on_key(self, _window, event):
        """Ctrl+V sends the clipboard, as its button does."""
        mods = event.get_state() & self.Gtk.accelerator_get_default_mod_mask()
        if mods == self.Gdk.ModifierType.CONTROL_MASK and self.Gdk.keyval_to_lower(event.keyval) == self.Gdk.KEY_v:
            command = self.commands.get("clipboard")
            if command:
                self.run_phone(command)
                return True
        return False

    def open_settings(self, *_args):
        self.start(SETTINGS)

    def ensure_watch(self):
        if self.watching:
            return
        if self.watch_write is not None:
            os.close(self.watch_write)
            self.watch_write = None
        self.watching = True
        read, write = os.pipe()
        self.watch_write = write
        threading.Thread(target=self.watch_loop, args=(read,), daemon=True).start()

    def watch_loop(self, stop):
        try:
            for event in self.phone.iter_watch(stop):
                self.GLib.idle_add(self.on_watch, event)
        except self.phone.PhoneError as error:
            self.GLib.idle_add(self.say, str(error))
        except Exception as error:
            import traceback
            traceback.print_exc()
            self.GLib.idle_add(self.say, f"{type(error).__name__}: {error}")
        finally:
            os.close(stop)
            self.GLib.idle_add(self.watch_ended)

    def watch_ended(self):
        self.watching = False
        return False

    def on_watch(self, event):
        if self.state is None or not self.state.get("enabled"):
            return False
        self.phone.apply_watch(self.state, event)
        kind = event.get("event")
        if kind in ("connected", "disconnected", "forgotten"):
            self.fill_phones()
            self.fill_actions()
        elif kind == "battery":
            self.fill_phone_line()
        elif kind == "received":
            self.fill_received()
        elif kind == "transfer":
            self.fill_transfers()
        return False

    def say(self, text):
        if text:
            self.status.set_text(text)
        return False

    def start(self, argv):
        """An app of its own (a page, a folder, Settings). It outlives this window."""
        try:
            process = self.Gio.Subprocess.new(list(argv), self.Gio.SubprocessFlags.NONE)
        except self.GLib.Error as error:
            self.status.set_text(error.message)
            return
        process.wait_async(None, None, None)

    def run_phone(self, argv):
        """A flickos-phone action. --notify is for the menu, which has no
        window to say what happened; here the result is shown in the window."""
        command = [arg for arg in argv if arg != "--notify"]
        self.status.set_text("")
        flags = self.Gio.SubprocessFlags.STDOUT_PIPE | self.Gio.SubprocessFlags.STDERR_PIPE
        try:
            process = self.Gio.Subprocess.new(command, flags)
        except self.GLib.Error as error:
            self.status.set_text(error.message)
            return

        def done(process, result):
            try:
                _ok, stdout, stderr = process.communicate_utf8_finish(result)
                ok = process.get_successful()
            except self.GLib.Error as error:
                self.status.set_text(error.message)
                return
            text = (stderr or stdout or "").strip()
            if not ok:
                self.status.set_text(sentence(text.splitlines()[-1]) if text else "That didn't work.")
            elif text:
                self.status.set_text(sentence(text.splitlines()[-1]))

        process.communicate_utf8_async(None, None, done)
