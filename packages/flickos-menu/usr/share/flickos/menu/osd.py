"""The volume and brightness ring and the desktop card, drawn by flickos-menu's
daemon or its pop-up.

After a volume, microphone or brightness key (flickos-settings' level
script, then /usr/libexec/flickos/osd), a ring shows the new level for
HIDE_MS: an arc in the theme's selected color, filled clockwise from the
top, the level's icon in the middle, both dimmed while muted. It takes no
keys and no clicks, sits MARGIN above the bottom panel (exclusive zone 0
keeps it off panels), fades in and out like the menu while GSettings'
enable-animations is on, and the arc slides to a new level.

flickos-menu loads this file at the first message only (load_osd), so a
session that never presses those keys doesn't compile it. Design:
docs/design/flickos-osd.md.

The desktop card is the same idea for Super+Ctrl+Left/Right and Super+number
(flickos-layouts' /usr/libexec/flickos/desktop show): a rounded card in the
middle of the screen, one circle per desktop, the current one in the theme's
selected color, and its name under them. It replaces labwc's own pop-up
(docs/design/flickos-desktops.md ADR-006).

The first part has no GTK (the tests use it); Ring and Card are the windows.
"""

import math
import time

NAMESPACE = "flickos-osd"       # the layer-shell namespace
KINDS = ("volume", "mic", "brightness")
SIZE = 112                      # the window, layout pixels
MARGIN = 64                     # above the bottom edge or panel
ICON_SIZE = 40
RING_WIDTH = 6
HIDE_MS = 1500                  # shown this long after the last change
SLIDE_MS = 120                  # the arc's move to a new level
BACKGROUND_ALPHA = 0.94
MUTED_ALPHA = 0.4
CARD_RADIUS = 12                # the lock and login screens' card (HIG VIS-5)
CARD_ALPHA = 0.9                # the lock screen's CARD_ALPHA
CARD_HEIGHT = 76
CARD_MIN_WIDTH = 160
CARD_PAD = 28                   # sides, beside the circles
DOT = 14                        # a circle's diameter
DOT_GAP = 14
DESKTOP_MAX = 9                 # flickos-layouts' MAX_DESKTOPS

def _(text):
    """text in the user's language: load_osd replaces this with the menu's
    translation. Loaded on its own (the tests), English."""
    return text


def N_(text):
    """Marks text for the translation template; _() translates it where it is shown."""
    return text


# load_osd sets these to the menu's, so every pop-up fades the same way.
fade_opacity = None
FADE_IN_MS = 100
FADE_OUT_MS = 80


def parse_message(text):
    """'volume 45 muted' → ('volume', 45, True); 'desktop 2 4' → ('desktop', 2, 4)
    (the second of four); None if it isn't one."""
    words = text.split()
    if words[:1] == ["desktop"]:
        try:
            index, count = (int(word) for word in words[1:])
        except ValueError:
            return None
        if len(words) == 3 and 2 <= count <= DESKTOP_MAX and 1 <= index <= count:
            return "desktop", index, count
        return None
    if not 2 <= len(words) <= 3 or words[0] not in KINDS or words[2:] not in ([], ["muted"]):
        return None
    try:
        percent = int(words[1])
    except ValueError:
        return None
    return words[0], max(0, min(100, percent)), len(words) == 3


def icon_names(kind, percent, muted):
    """The icon's names, best first (the first the theme has is drawn)."""
    if kind == "brightness":
        return ["display-brightness-symbolic", "weather-clear-symbolic"]
    if kind == "mic":
        # Adwaita's microphone-sensitivity-muted is a plain microphone.
        return (["microphone-disabled-symbolic", "audio-input-microphone-muted-symbolic",
                 "microphone-sensitivity-muted-symbolic"] if muted
                else ["audio-input-microphone-symbolic", "microphone-sensitivity-high-symbolic"])
    if muted or percent == 0:
        level = "muted"
    elif percent < 34:
        level = "low"
    elif percent < 67:
        level = "medium"
    else:
        level = "high"
    return [f"audio-volume-{level}-symbolic"]


# What a screen reader says (the window's accessible name): kind → (level, muted).
DESCRIPTIONS = {
    "volume": (N_("Volume {percent}%"), N_("Volume {percent}%, muted")),
    "mic": (N_("Microphone {percent}%"), N_("Microphone muted")),
    "brightness": (N_("Brightness {percent}%"), N_("Brightness {percent}%")),
}


DESKTOP_NAME = N_("Desktop {number}")      # the card's text and its accessible name


def description(kind, percent, muted):
    return _(DESCRIPTIONS[kind][1 if muted else 0]).format(percent=percent)


def card_width(count):
    """The desktop card's width for that many circles."""
    return max(CARD_MIN_WIDTH, 2 * CARD_PAD + count * DOT + (count - 1) * DOT_GAP)


def dot_centres(count):
    """x of each circle's centre inside the card, left to right."""
    width = card_width(count)
    left = (width - (count * DOT + (count - 1) * DOT_GAP)) / 2
    return [left + DOT / 2 + i * (DOT + DOT_GAP) for i in range(count)]


def arc_end(percent):
    """The arc's end in radians, from the top (-π/2) clockwise."""
    return -math.pi / 2 + 2 * math.pi * max(0.0, min(100.0, percent)) / 100


def slide(start, end, elapsed):
    """(level, finished) elapsed ms into the arc's move from start to end:
    eased out, like a fade in."""
    t = min(max(elapsed / SLIDE_MS, 0.0), 1.0)
    return start + (end - start) * (1 - (1 - t) ** 3), t >= 1.0


class Ring:
    """The ring's layer-shell window. update() shows a level; the window
    hides HIDE_MS after the last one, then calls gone (the pop-up uses it to
    linger and exit). Frame ticks run only while it fades or slides."""

    AT_BOTTOM = True        # else centered on the screen
    TITLE = "FlickOS level"

    def size(self):
        return SIZE, SIZE

    def __init__(self, gtk, gone=None):
        self.GLib, self.Gdk, self.Gtk, self.GtkLayerShell = gtk
        import cairo
        self.cairo = cairo
        self.gone = gone
        self.kind, self.level, self.muted = "volume", 0, False
        self.shown = None           # the arc's level while it slides
        self.slide_from = None      # (level, start ms) of a slide
        self.fade = None            # (from, to, start ms, ms, ease out)
        self.hide_timer = None
        self.tick = None
        self.icons = {}

        Gtk, GtkLayerShell = self.Gtk, self.GtkLayerShell
        window = self.window = Gtk.Window(title=self.TITLE)
        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_namespace(window, NAMESPACE)
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
        if self.AT_BOTTOM:
            GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.BOTTOM, True)
            GtkLayerShell.set_margin(window, GtkLayerShell.Edge.BOTTOM, MARGIN)
        GtkLayerShell.set_exclusive_zone(window, 0)
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
        window.set_size_request(*self.size())
        window.set_app_paintable(True)
        visual = window.get_screen().get_rgba_visual()
        if visual is not None:
            window.set_visual(visual)
        window.connect("draw", self.draw)
        # Clicks go through it. GTK clears the region when it maps again.
        window.connect("map", lambda w: w.input_shape_combine_region(cairo.Region()))
        window.realize()

    def animate(self):
        return self.Gtk.Settings.get_default().props.gtk_enable_animations

    @staticmethod
    def now():
        return time.monotonic() * 1000

    def update(self, kind, level, muted):
        animate = self.animate()
        if self.shown is None or kind != self.kind:
            self.shown = 0 if animate else level      # a new ring grows from empty
        self.kind, self.level, self.muted = kind, level, muted
        if animate and self.shown != level:
            self.slide_from = (self.shown, self.now())
        else:
            self.slide_from, self.shown = None, level
        self.present(description(kind, level, muted))

    def present(self, name):
        """Show the window (a screen reader says name), fade it in, and hide it
        again HIDE_MS after the last call."""
        animate = self.animate()
        self.window.get_accessible().set_name(name)
        if self.hide_timer is not None:
            self.GLib.source_remove(self.hide_timer)
        self.hide_timer = self.GLib.timeout_add(HIDE_MS, self.on_hide_timer)
        if not self.window.get_visible():
            self.Gtk.Widget.set_opacity(self.window, 0.0 if animate else 1.0)
            self.window.show()
        if animate:
            self.fade_to(1.0, FADE_IN_MS, True)
        else:
            self.fade = None
            self.Gtk.Widget.set_opacity(self.window, 1.0)
        self.ticking()
        self.window.queue_draw()

    def on_hide_timer(self):
        self.hide_timer = None
        if self.animate():
            self.fade_to(0.0, FADE_OUT_MS, False)
            self.ticking()
        else:
            self.hidden()
        return False    # GLib timeout: once

    def fade_to(self, end, duration, ease_out):
        start = self.Gtk.Widget.get_opacity(self.window)
        if self.fade is not None and self.fade[1] == end:
            return
        # From where it is, at the same speed.
        self.fade = (start, end, self.now(), duration * abs(end - start), ease_out)

    def ticking(self):
        if self.tick is None and (self.fade is not None or self.slide_from is not None):
            self.tick = self.window.add_tick_callback(self.on_tick)

    def on_tick(self, _widget, _clock):
        now = self.now()
        if self.fade is not None:
            start, end, began, duration, ease_out = self.fade
            value, finished = fade_opacity(start, end, now - began, duration, ease_out)
            self.Gtk.Widget.set_opacity(self.window, value)
            if finished:
                self.fade = None
                if end == 0.0:
                    # Not from inside the tick: hiding there kept GTK's frame
                    # clock running (60 wake-ups a second while hidden).
                    self.GLib.idle_add(self.hidden)
        if self.slide_from is not None:
            self.shown, finished = slide(self.slide_from[0], self.level, now - self.slide_from[1])
            if finished:
                self.slide_from = None
            self.window.queue_draw()
        if self.fade is not None or self.slide_from is not None:
            return True
        self.tick = None
        return False

    def hidden(self):
        if self.hide_timer is not None or self.fade is not None:
            return False    # shown again meanwhile
        self.window.hide()
        if self.gone is not None:
            self.gone()
        return False        # GLib idle: once

    def visible(self):
        return self.window.get_visible()

    def destroy(self):
        if self.hide_timer is not None:
            self.GLib.source_remove(self.hide_timer)
            self.hide_timer = None
        self.window.destroy()

    # Drawing --------------------------------------------------------------------

    def color(self, name, fallback):
        found, rgba = self.window.get_style_context().lookup_color(name)
        return (rgba.red, rgba.green, rgba.blue) if found else fallback

    def icon(self, names, rgb):
        scale = self.window.get_scale_factor()
        key = (tuple(names), rgb, scale)
        if key not in self.icons:
            theme = self.Gtk.IconTheme.get_default()
            name = next((n for n in names if theme.has_icon(n)), names[0])
            info = theme.lookup_icon_for_scale(name, ICON_SIZE, scale, self.Gtk.IconLookupFlags.FORCE_SYMBOLIC)
            surface = None
            if info is not None:
                try:
                    pixbuf, _was_symbolic = info.load_symbolic(self.Gdk.RGBA(*rgb, 1.0), None, None, None)
                    surface = self.Gdk.cairo_surface_create_from_pixbuf(pixbuf, scale, self.window.get_window())
                except self.GLib.Error:
                    pass
            self.icons[key] = surface
        return self.icons[key]

    def draw(self, _widget, cr):
        cairo = self.cairo
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        fg = self.color("theme_fg_color", (0.8, 0.8, 0.8))
        bg = self.color("theme_bg_color", (0.2, 0.2, 0.2))
        accent = self.color("theme_selected_bg_color", fg)
        centre = SIZE / 2
        radius = centre - 2
        cr.arc(centre, centre, radius, 0, 2 * math.pi)
        cr.set_source_rgba(*bg, BACKGROUND_ALPHA)
        cr.fill_preserve()
        cr.set_line_width(1)
        cr.set_source_rgba(*fg, 0.12)      # an edge over a background of its own color
        cr.stroke()

        ring = radius - 8 - RING_WIDTH / 2
        cr.set_line_width(RING_WIDTH)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.arc(centre, centre, ring, 0, 2 * math.pi)
        cr.set_source_rgba(*fg, 0.15)
        cr.stroke()
        if (self.shown or 0) >= 0.5:
            cr.arc(centre, centre, ring, -math.pi / 2, arc_end(self.shown))
            if self.muted:
                cr.set_source_rgba(*fg, MUTED_ALPHA)
            else:
                cr.set_source_rgb(*accent)
            cr.stroke()

        surface = self.icon(icon_names(self.kind, self.level, self.muted), fg)
        if surface is not None:
            cr.set_source_surface(surface, centre - ICON_SIZE / 2, centre - ICON_SIZE / 2)
            cr.paint_with_alpha(0.5 if self.muted else 1.0)
        return True


class Card(Ring):
    """The desktop card: update(index, count) shows it for HIDE_MS. Same
    window, fade and hide timer as the ring, centered on the screen, no arc."""

    AT_BOTTOM = False
    TITLE = "FlickOS desktop"

    def size(self):
        return card_width(getattr(self, "count", 2)), CARD_HEIGHT

    def update(self, index, count):
        self.index, self.count = index, count
        self.window.set_size_request(*self.size())
        self.present(_(DESKTOP_NAME).format(number=index))

    def draw(self, _widget, cr):
        cairo = self.cairo
        width, height = self.size()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        fg = self.color("theme_fg_color", (0.8, 0.8, 0.8))
        bg = self.color("theme_bg_color", (0.2, 0.2, 0.2))
        accent = self.color("theme_selected_bg_color", fg)
        r = CARD_RADIUS
        cr.new_sub_path()
        for cx, cy, start in ((width - r, r, -90), (width - r, height - r, 0), (r, height - r, 90), (r, r, 180)):
            cr.arc(cx, cy, r, math.radians(start), math.radians(start + 90))
        cr.close_path()
        cr.set_source_rgba(*bg, CARD_ALPHA)
        cr.fill_preserve()
        cr.set_line_width(1)
        cr.set_source_rgba(*fg, 0.12)
        cr.stroke()

        y = 22 + DOT / 2
        for i, x in enumerate(dot_centres(self.count)):
            cr.arc(x, y, DOT / 2, 0, 2 * math.pi)
            if i + 1 == self.index:
                cr.set_source_rgb(*accent)
            else:
                cr.set_source_rgba(*fg, 0.25)
            cr.fill()

        import gi
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo
        layout = self.window.create_pango_layout(_(DESKTOP_NAME).format(number=self.index))
        _ink, logical = layout.get_pixel_extents()
        cr.set_source_rgb(*fg)
        cr.move_to((width - logical.width) / 2, y + DOT / 2 + 10)
        PangoCairo.show_layout(cr, layout)
        return True
