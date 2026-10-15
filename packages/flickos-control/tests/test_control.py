"""Tests for usr/bin/flickos-control. Run: python3 -m unittest discover -s tests"""

import configparser
import datetime
import gzip
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True
INSTALLER_USERS = os.path.join(PACKAGE, "../flickos-installer/etc/calamares/modules/users.conf")
LAYOUTS_PACKAGE = os.path.join(PACKAGE, "../flickos-layouts")
_loader = importlib.machinery.SourceFileLoader("flickos_control", os.path.join(PACKAGE, "usr/bin/flickos-control"))
fc = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fc)

# No test writes the real history (~/.local/state/flickos); HistoryTest sets its own.
_STATE = tempfile.TemporaryDirectory(prefix="flickos-control-test-state-")
os.environ["XDG_STATE_HOME"] = _STATE.name

# Shaped like `flickos-layout list` and `flick-tiler modes`.
LAYOUT_LIST = ("redmond\tRedmond\tOne panel at the bottom: apps menu, window list\n"
               "cupertino\tCupertino\tTop bar and a dock\n")
MODES = "master-stack\tMain and stack\ncolumns\tColumns\n"

# Shaped like `flickos-shortcuts list`.
SHORTCUTS = """Applications:
  Super + Enter           Terminal
  Super + D or Alt + F3   App launcher

Windows:
  Super + Q               Close the window
"""


class ParseTest(unittest.TestCase):
    def test_items(self):
        items = fc.parse_items(LAYOUT_LIST + "\n")
        self.assertEqual([item.id for item in items], ["redmond", "cupertino"])
        self.assertEqual(items[1].name, "Cupertino")
        self.assertEqual(items[1].comment, "Top bar and a dock")
        # Without a description, or without a name.
        self.assertEqual(fc.parse_items(MODES)[1], fc.Item("columns", "Columns", ""))
        self.assertEqual(fc.parse_items("solo\n")[0], fc.Item("solo", "solo", ""))

    def test_shortcuts(self):
        sections = fc.parse_shortcuts(SHORTCUTS)
        self.assertEqual([name for name, _ in sections], ["Applications", "Windows"])
        self.assertEqual(sections[0][1], [("Super + Enter", "Terminal"),
                                          ("Super + D or Alt + F3", "App launcher")])
        self.assertEqual(fc.parse_shortcuts("Empty:\n\n"), [])

    def test_tiler_state(self):
        # flick-tiler 1.3's status, tiling off and on.
        off = {"text": " ", "alt": "off", "class": ["off", "columns"], "ratio": 60, "gap": 4, "tooltip": "…"}
        on = {"text": " ", "alt": "master-stack", "class": ["on", "master-stack"], "ratio": 55, "gap": 8}
        self.assertEqual(fc.tiler_state(json.dumps(off)), fc.TilerState(False, "columns", 60, 4))
        self.assertEqual(fc.tiler_state(json.dumps(on)), fc.TilerState(True, "master-stack", 55, 8))
        # flick-tiler before 1.3 had neither.
        self.assertEqual(fc.tiler_state('{"alt": "grid", "class": ["on", "grid"]}'), fc.TilerState(True, "grid"))
        with self.assertRaises(fc.ControlError):
            fc.tiler_state("")

    def test_layout_state(self):
        choices = {kind: {"current": "b", "choices": [{"id": "a", "name": "A", "comment": "First"},
                                                      {"id": "b", "name": "B", "comment": ""}]}
                   for kind in fc.LAYOUT_KINDS}
        state = fc.layout_state(json.dumps(dict(choices, warnings=["Your rc.xml hides FlickOS's."])))
        self.assertEqual(state.choices["style"], [fc.Item("a", "A", "First"), fc.Item("b", "B")])
        self.assertEqual(state.current, {kind: "b" for kind in fc.LAYOUT_KINDS})
        self.assertEqual(state.warnings, ["Your rc.xml hides FlickOS's."])
        self.assertNotIn("quick-settings", state.choices)       # flickos-layouts before 1.35
        choices["quick-settings"] = {"current": "off", "choices": [{"id": "off", "name": "Off"},
                                                                  {"id": "on", "name": "On", "comment": "Panel"}]}
        state = fc.layout_state(json.dumps(choices))
        self.assertEqual(state.choices["quick-settings"], [fc.Item("off", "Off"), fc.Item("on", "On", "Panel")])
        self.assertEqual(state.current["quick-settings"], "off")
        del choices["menu-style"]
        for text in ("", "[]", json.dumps(choices)):
            with self.assertRaises(fc.ControlError):
                fc.layout_state(text)

    def test_users_own_style_and_defaults(self):
        """flickos-layouts 1.45/1.46: user styles say so; the defaults for Back to FlickOS's Look."""
        choices = {kind: {"current": "a", "choices": [{"id": "a", "name": "A", "comment": "First"}]}
                   for kind in fc.LAYOUT_KINDS}
        choices["style"] = {"current": "mine", "default": "a",
                            "choices": [{"id": "a", "name": "A", "comment": "First", "user": False},
                                        {"id": "mine", "name": "Mine", "comment": "Based on A", "user": True,
                                         "parent": "a"}]}
        choices["layout"]["default"] = "a"
        state = fc.layout_state(json.dumps(choices))
        self.assertEqual(state.choices["style"], [fc.Item("a", "A", "First"), fc.Item("mine", "Mine",
                                                                                      "Based on A · Yours")])
        self.assertEqual(state.defaults, {"layout": "a", "style": "a"})
        self.assertTrue(fc.away_from_default(state))
        choices["style"]["current"] = "a"
        self.assertFalse(fc.away_from_default(fc.layout_state(json.dumps(choices))))
        del choices["style"]["default"], choices["layout"]["default"]       # before 1.46: never shown
        choices["style"]["current"] = "mine"
        self.assertFalse(fc.away_from_default(fc.layout_state(json.dumps(choices))))

    def test_layout_description(self):
        def state(user, parent=None):
            return json.dumps({"layout": {"current": "redmond", "choices": []},
                               "style": {"current": "mine", "choices": [{"id": "mine", "user": user,
                                                                         "parent": parent}]}})
        self.assertEqual(fc.layout_description(state(False)), "layout redmond, style mine")
        self.assertEqual(fc.layout_description(state(True, "dark")),
                         "layout redmond, style mine (yours, inherits dark)")
        self.assertEqual(fc.layout_description(state(True)), "layout redmond, style mine (yours)")
        self.assertEqual(fc.layout_description(""), "")
        trying = json.loads(state(True, "dark"))
        trying["trying"] = "mine"
        self.assertEqual(fc.layout_description(json.dumps(trying)),
                         "layout redmond, style mine (yours, inherits dark, trying)")
        trying["style"]["choices"][0]["user"] = False
        self.assertEqual(fc.layout_description(json.dumps(trying)), "layout redmond, style mine (trying)")
        mine = json.loads(state(False))
        mine["layout"] = {"current": "bar", "choices": [{"id": "bar", "user": True}, {"id": "redmond"}]}
        self.assertEqual(fc.layout_description(json.dumps(mine)), "layout bar (yours), style mine")
        mine["tweaks"] = True
        self.assertEqual(fc.layout_description(json.dumps(mine)), "layout bar (yours), style mine, panel tweaks")

    def test_layout_state_yours(self):
        choices = {kind: {"current": "a", "choices": [{"id": "a", "name": "A", "comment": ""}]}
                   for kind in fc.LAYOUT_KINDS}
        self.assertEqual(fc.layout_state(json.dumps(choices)).yours, frozenset())    # before flickos-layouts 1.56
        choices["layout"]["choices"].append({"id": "bar", "name": "Bar", "comment": "Mine", "user": True,
                                             "folder": "/x/bar"})
        state = fc.layout_state(json.dumps(choices))
        self.assertEqual(state.yours, frozenset({"bar"}))
        self.assertEqual(state.choices["layout"][1], fc.Item("bar", "Bar", "Mine · Yours"))

    def test_layout_state_trying(self):
        choices = {kind: {"current": "a", "choices": [{"id": "a", "name": "A", "comment": ""}]}
                   for kind in fc.LAYOUT_KINDS}
        self.assertIsNone(fc.layout_state(json.dumps(choices)).trying)     # before flickos-layouts 1.52
        choices["trying"] = "a"
        self.assertEqual(fc.layout_state(json.dumps(choices)).trying, "a")

    @unittest.skipUnless(os.path.isdir(LAYOUTS_PACKAGE), "flickos-layouts is not next to this package")
    def test_layout_state_reads_flickos_layouts_state(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
                       XDG_RUNTIME_DIR=home, GSETTINGS_BACKEND="memory",
                       FLICKOS_LAYOUT_PREFIX=os.path.abspath(LAYOUTS_PACKAGE))
            env.pop("LABWC_PID", None)
            text = subprocess.run([sys.executable, os.path.join(LAYOUTS_PACKAGE, "usr/bin/flickos-layout"), "state"],
                                  capture_output=True, text=True, env=env, check=True).stdout
        state = fc.layout_state(text)
        self.assertIn("redmond", [item.id for item in state.choices["layout"]])
        self.assertEqual(state.current["layout"], "redmond")
        self.assertEqual(state.defaults, {"layout": "redmond", "style": "dark"})

    @unittest.skipUnless(os.path.isdir(LAYOUTS_PACKAGE), "flickos-layouts is not next to this package")
    def test_user_styles_folder_is_flickos_layouts(self):
        loader = importlib.machinery.SourceFileLoader("flickos_layout_for_control",
                                                      os.path.join(LAYOUTS_PACKAGE, "usr/bin/flickos-layout"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        layout = importlib.util.module_from_spec(spec)
        loader.exec_module(layout)
        for data_home, config_home in (("/x/data", "/x/config"), (None, None)):
            env = {"HOME": "/x/home"} | ({"XDG_DATA_HOME": data_home} if data_home else {}) | \
                ({"XDG_CONFIG_HOME": config_home} if config_home else {})
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(fc.user_styles_folder(), layout.user_styles_dir())
                self.assertEqual(fc.user_layouts_folder(), layout.user_layouts_dir())
                self.assertEqual(fc.user_tweaks_folder(), layout.tweaks_folder())

    def test_countme_state(self):
        status = {"enabled": True, "sending": True, "reason": None, "last_week": "2026-W39",
                  "this_week": "2026-W39", "request": "https://count.example/v1/countme?version=2.0&age=2"}
        self.assertEqual(fc.countme_state(json.dumps(status)),
                         fc.CountmeState(True, None, "2026-W39", status["request"]))
        self.assertEqual(fc.countme_state('{"enabled": false, "reason": "turned off"}'),
                         fc.CountmeState(False, "turned off"))
        for text in ("", "[]"):
            with self.assertRaises(fc.ControlError):
                fc.countme_state(text)

    def test_output_messages(self):
        self.assertEqual(fc.output_messages("Layout 'Cupertino' applied.\n",
                                            "flickos-layout: a warning\nflickos-layout: a warning\n"),
                         ["Layout 'Cupertino' applied.", "a warning"])


class PagesTest(unittest.TestCase):
    def test_every_page_has_a_class(self):
        self.assertEqual([page.id for page in fc.PAGES], list(fc.PAGE_CLASSES))

    def test_a_groups_pages_are_together(self):
        groups = [page.group for page in fc.PAGES]
        starts = [group for i, group in enumerate(groups) if i == 0 or groups[i - 1] != group]
        self.assertEqual(len(starts), len(set(starts)))
        self.assertEqual(groups[-1], "")                # the pages without a heading come last
        self.assertEqual(fc.PAGES[0].id, "layout")      # the page the window opens on

    def test_group_headers(self):
        layout, tiling, displays, about = (next(p for p in fc.PAGES if p.id == i)
                                           for i in ("layout", "tiling", "displays", "about"))
        self.assertEqual(fc.group_header(layout, None), "Desktop")
        self.assertIsNone(fc.group_header(tiling, layout))
        self.assertEqual(fc.group_header(displays, tiling), "Devices")
        self.assertEqual(fc.group_header(about, displays), "line")

    def test_tiles_of_missing_apps_are_left_out(self):
        tiles = fc.available_tiles(which=lambda program: None if program == "pavucontrol" else "/usr/bin/x")
        self.assertNotIn("sound", [tile.id for tile in tiles])
        self.assertEqual(len(tiles), len(fc.TILES) - 1)

    def test_tile_ids_are_unique(self):
        ids = [tile.id for tile in fc.TILES]
        self.assertEqual(len(ids), len(set(ids)))


class SearchTest(unittest.TestCase):
    """The search box: what it finds and in which order."""

    def items(self):
        page = lambda pid, name: fc.search_item(name, "Page", fc.SEARCH_KEYWORDS[pid], page=pid)
        return [page("displays", "Displays"),
                fc.search_item("Night light", "Displays", "", page="displays", target="heading"),
                fc.search_item("Night light", "Displays", "", page="displays", target="row", focus="switch"),
                fc.search_item("Warmth", "Displays", "How warm the colors get at night", page="displays",
                               target="row", focus="combo"),
                page("idle", "Power & Idle"),
                fc.search_item("Close the lid", "Power & Idle", "", page="idle", target="row", focus="combo"),
                fc.search_item("Sound", "Opens pavucontrol", fc.SEARCH_KEYWORDS["tile:sound"],
                               command=("pavucontrol",)),
                fc.search_item("Network", "Opens nm-connection-editor", fc.SEARCH_KEYWORDS["tile:network"],
                               command=("nm-connection-editor",))]

    def titles(self, query):
        return [(item.title, item.where) for item in fc.find(fc.unique_items(self.items()), query)]

    def test_words_people_type(self):
        self.assertEqual(self.titles("wifi"), [("Network", "Opens nm-connection-editor")])
        self.assertEqual(self.titles("Volume"), [("Sound", "Opens pavucontrol")])
        self.assertEqual(self.titles("monitor"), [("Displays", "Page")])
        self.assertEqual(self.titles("lid"), [("Close the lid", "Power & Idle"), ("Power & Idle", "Page")])
        self.assertEqual(self.titles("   "), [])
        self.assertEqual(self.titles("nothing like this"), [])

    def test_order_and_every_word(self):
        # The title starting with the query first, then titles with all the words.
        self.assertEqual(self.titles("night"), [("Night light", "Displays"), ("Displays", "Page"),
                                                ("Warmth", "Displays")])
        self.assertEqual(self.titles("light warm"), [("Displays", "Page")])
        self.assertEqual(self.titles("colors night"), [("Displays", "Page"), ("Warmth", "Displays")])

    def test_one_result_per_setting(self):
        found = fc.find(fc.unique_items(self.items()), "night light")
        self.assertEqual([(item.title, item.focus) for item in found if item.page == "displays"][0],
                         ("Night light", "switch"))     # the row with the switch, not the heading

    def test_accents_and_case(self):
        item = fc.search_item("Café Écran", "Page")
        self.assertEqual(fc.find([item], "cafe ECRAN"), [item])
        self.assertEqual(fc.fold("Ärger Öl"), "arger ol")

    def test_every_page_and_tile_has_words(self):
        self.assertEqual(set(fc.SEARCH_KEYWORDS), {page.id for page in fc.PAGES} |
                         {f"tile:{tile.id}" for tile in fc.TILES})


class RunTest(unittest.TestCase):
    def test_run_returns_stdout(self):
        self.assertEqual(fc.run([sys.executable, "-c", "print('ok')"]), "ok\n")

    def test_run_failure_says_why(self):
        with self.assertRaisesRegex(fc.ControlError, "broken"):
            fc.run([sys.executable, "-c", "import sys; sys.exit('flickos-layout: broken')"])
        with self.assertRaises(fc.ControlError):
            fc.run(["/nonexistent/program"])

    def test_doctor_warnings_only_on_exit_code_1(self):
        for code, stdout, expected in ((1, "a\nb\n", ["a", "b"]), (0, "No problems found.\n", [])):
            result = subprocess.CompletedProcess([], code, stdout=stdout, stderr="")
            with mock.patch.object(fc.subprocess, "run", return_value=result):
                self.assertEqual(fc.doctor_warnings(), expected)
        with mock.patch.object(fc.subprocess, "run", side_effect=OSError("missing")):
            self.assertEqual(fc.doctor_warnings(), [])


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-control-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fc.main(["list"]), 0)
        self.assertEqual(out.getvalue().splitlines()[0], "layout\tDesktop Layout & Style")
        self.assertEqual(len(out.getvalue().splitlines()), len(fc.PAGES))

    def test_unknown_page(self):
        with mock.patch.object(fc, "warn") as warn, mock.patch.object(fc, "load_gtk") as load_gtk:
            self.assertEqual(fc.main(["--page", "nope"]), 2)
        warn.assert_called_once()
        load_gtk.assert_not_called()

    def test_second_window_is_not_opened(self):
        with fc.single_instance() as first:
            self.assertTrue(first)
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                 mock.patch.object(fc, "load_gtk") as load_gtk:
                self.assertEqual(fc.main(["--page", "tiling"]), 0)
            load_gtk.assert_not_called()
            self.assertIn("already open", out.getvalue())
        with fc.single_instance() as first:
            self.assertTrue(first)

    def test_no_gtk_is_an_error(self):
        with mock.patch.object(fc, "load_gtk", return_value=None):
            self.assertEqual(fc.main([]), 1)

    def test_no_runtime_dir(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": ""}), mock.patch.object(fc, "warn") as warn:
            self.assertEqual(fc.main([]), 1)
        warn.assert_called_once()


# What labwc 0.8.3 parses (src/config/rcxml.c: fill_libinput_category(), the
# <keyboard> options; src/config/libinput.c: get_device_type()). Names are
# case-insensitive in labwc. Refresh when Debian ships a new labwc.
BOOL = {"yes", "no", "true", "false", "on", "off"}
LABWC_CATEGORIES = {"default", "touch", "touchpad", "non-touch"}
LABWC_LIBINPUT = {
    "naturalscroll": BOOL, "lefthanded": BOOL, "tap": BOOL, "tapanddrag": BOOL, "draglock": BOOL,
    "middleemulation": BOOL, "disablewhiletyping": BOOL, "pointerspeed": "float -1..1",
    "accelprofile": {"flat", "adaptive"}, "tapbuttonmap": {"lrm", "lmr"},
    "clickmethod": {"none", "clickfinger", "buttonareas"}, "sendeventsmode": BOOL | {"disabledonexternalmouse"},
    "scrollfactor": "float", "calibrationmatrix": "6 floats",
}
LABWC_KEYBOARD = {"repeatrate": "int", "repeatdelay": "int", "numlock": BOOL}
# <magnifier> (src/config/rcxml.c; width and height -1: the whole screen),
# checked in a headless labwc 0.8.3 on 2026-10-03.
LABWC_MAGNIFIER = {"width": "int", "height": "int", "initscale": "float", "increment": "float",
                   "usefilter": BOOL}

# A few lines of xkb-data's evdev.lst.
RULES = """! model
  pc105           Generic 105-key PC
! layout
  us              English (US)
  de              German
! variant
  dvorak          us: English (Dvorak)
  nodeadkeys      de: German (no dead keys)
! option
  grp                  Switching to another layout
  grp:alt_shift_toggle Alt+Shift
"""
KEYBOARD_FILE = 'XKBMODEL="pc105"\nXKBLAYOUT="us"\nXKBVARIANT=""\nXKBOPTIONS=""\nBACKSPACE="guess"\n'


def labwc_accepts(section, name, value):
    kind = {"libinput": LABWC_LIBINPUT, "keyboard": LABWC_KEYBOARD,
            "magnifier": LABWC_MAGNIFIER}[section].get(name.lower())
    if kind is None:
        return False
    if isinstance(kind, set):
        return value.lower() in kind
    try:
        number = float(value) if kind.startswith("float") else int(value)
    except ValueError:
        return False
    return -1 <= number <= 1 if kind == "float -1..1" else True


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-control-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
                                           # Not the build host's /etc/xdg/flickos (autostart, ...).
                                           "XDG_CONFIG_DIRS": os.path.join(self.tmp, "xdg"),
                                           "XDG_RUNTIME_DIR": self.run_dir})
        env.start()
        self.addCleanup(env.stop)
        for key in ("WAYLAND_DISPLAY", "LABWC_PID"):
            os.environ.pop(key, None)
        rules = self.write("evdev.lst", RULES)
        self.keyboard = self.write("default-keyboard", KEYBOARD_FILE)
        self.locale = self.write("default-locale", 'LANG=en_US.UTF-8\nLC_TIME="en_GB.UTF-8"\n')
        for name, value in (("SYSTEM_CONF_DIR", os.path.join(self.tmp, "etc")), ("XKB_RULES", rules),
                            ("KEYBOARD_DEFAULTS", self.keyboard), ("LOCALE_DEFAULTS", self.locale)):
            patcher = mock.patch.object(fc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.control = os.path.join(self.run_dir, "flickos", "control")

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def set(self, key, value):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            status = fc.main(["set", key, value])
        return status, out.getvalue()

    def fragment(self):
        return ET.parse(os.path.join(self.control, "labwc.xml")).getroot()

    def environment(self):
        with open(os.path.join(self.control, "environment"), encoding="utf-8") as f:
            return f.read().splitlines()

    def test_every_setting_is_something_labwc_parses(self):
        values = {}
        for setting in fc.SETTINGS.values():
            if setting.kind == "bool":
                values[setting.key] = "yes"
            elif setting.kind == "number":
                values[setting.key] = fc.normalize(setting, setting.low)
            elif setting.kind == "choice":
                values[setting.key] = setting.choices[-1]
        top = ET.fromstring(fc.labwc_fragment(values))
        seen = 0
        for device in top.findall("libinput/device"):
            self.assertIn(device.get("category"), LABWC_CATEGORIES)
            for option in device:
                self.assertTrue(labwc_accepts("libinput", option.tag, option.text), (option.tag, option.text))
                seen += 1
        for section in ("keyboard", "magnifier"):
            for option in top.find(section):
                self.assertTrue(labwc_accepts(section, option.tag, option.text), (option.tag, option.text))
                seen += 1
        # The zoom area and lens size are both width and height.
        self.assertEqual(seen, len([s for s in fc.SETTINGS.values()
                                    if s.labwc[0] in ("libinput", "keyboard", "magnifier")]))
        for setting in fc.SETTINGS.values():
            for choice in setting.choices if setting.labwc[0] in ("libinput", "keyboard") else ():
                self.assertTrue(labwc_accepts(setting.labwc[0], setting.labwc[-1], choice))

    def test_normalize(self):
        s = fc.SETTINGS
        self.assertEqual(fc.normalize(s["touchpad.tap"], "On"), "yes")
        self.assertEqual(fc.normalize(s["touchpad.pointer-speed"], "-0.333"), "-0.33")
        self.assertEqual(fc.normalize(s["keyboard.repeat-rate"], "30.4"), "30")
        self.assertEqual(fc.normalize(s["touchpad.click-method"], "CLICKFINGER"), "clickfinger")
        for key, value in (("touchpad.tap", "maybe"), ("touchpad.pointer-speed", "2"),
                           ("keyboard.repeat-delay", "fast"), ("mouse.accel-profile", "linear"),
                           ("keyboard.layout", "us;rm -rf")):
            with self.assertRaises(fc.ControlError):
                fc.normalize(s[key], value)

    def test_set_saves_and_writes_the_fragment(self):
        self.assertEqual(self.set("touchpad.natural-scroll", "yes")[0], 0)
        self.assertEqual(self.set("mouse.left-handed", "yes")[0], 0)
        self.assertEqual(self.set("keyboard.repeat-rate", "40")[0], 0)
        top = self.fragment()
        self.assertEqual({d.get("category"): {o.tag: o.text for o in d} for d in top.findall("libinput/device")},
                         {"touchpad": {"naturalScroll": "yes"}, "non-touch": {"leftHanded": "yes"}})
        self.assertEqual(top.findtext("keyboard/repeatRate"), "40")
        with open(fc.user_file("input"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "[Touchpad]\nNaturalScroll=yes\n\n[Mouse]\nLeftHanded=yes\n")
        # Nothing about the layout: no environment fragment.
        self.assertFalse(os.path.exists(os.path.join(self.control, "environment")))

    def test_default_is_stored_explicitly(self):
        """labwc keeps a value that disappears, so "default" writes it."""
        self.set("touchpad.tap", "no")
        self.set("touchpad.tap", "default")
        self.assertEqual(self.fragment().findtext("libinput/device/tap"), "yes")

    def test_default_without_a_known_value_is_removed(self):
        self.set("touchpad.click-method", "clickfinger")
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        with mock.patch.object(fc.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            status, out = self.set("touchpad.click-method", "default")
        self.assertEqual(status, 0)
        self.assertIn("next login", out)
        self.assertFalse(os.path.exists(os.path.join(self.control, "labwc.xml")))

    def test_zoom(self):
        """Accessibility: labwc's <magnifier>, the area as width and height."""
        magnifier = lambda: {o.tag: o.text for o in self.fragment().find("magnifier")}
        self.assertEqual(self.set("zoom.area", "lens")[0], 0)
        self.assertEqual(magnifier(), {"width": "400", "height": "400"})
        self.set("zoom.lens-size", "600")
        self.set("zoom.step", "1")
        self.set("zoom.smooth", "no")
        self.assertEqual(magnifier(), {"width": "600", "height": "600", "increment": "1.00", "useFilter": "no"})
        self.set("zoom.area", "default")        # stored: labwc keeps a lens otherwise
        self.assertEqual(magnifier()["width"], "-1")
        with open(fc.user_file("zoom"), encoding="utf-8") as f:
            self.assertIn("Area=screen\n", f.read())
        with mock.patch.object(fc, "warn"):
            for key, value in (("zoom.area", "corner"), ("zoom.lens-size", "100"), ("zoom.step", "2")):
                self.assertEqual(self.set(key, value)[0], 1, key)
        self.assertEqual(fc.value_name(fc.HISTORY_OWNER, "zoom.step", "1.00", {}), "Large")
        self.assertEqual(fc.value_name(fc.HISTORY_OWNER, "zoom.lens-size", "300", {}), "Small")
        self.assertEqual(fc.value_name(fc.HISTORY_OWNER, "zoom.area", "lens", {}), "A lens around the pointer")

    def test_set_in_the_session_reconfigures(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        with mock.patch.object(fc.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            status, out = self.set("touchpad.tap", "no")
        self.assertEqual((status, out.strip()), (0, "Applied."))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], [fc.LAYOUT, "reconfigure"])

    def test_bad_values_are_refused(self):
        with mock.patch.object(fc, "warn"):
            self.assertEqual(self.set("touchpad.tap", "maybe")[0], 1)
            self.assertEqual(self.set("touchpad.nope", "yes")[0], 2)
        self.assertFalse(os.path.exists(fc.user_file("input")))

    def test_system_defaults_then_user(self):
        self.write("etc/input.conf", "[Touchpad]\nTap=no\nNaturalScroll=bogus\n")
        with mock.patch.object(fc, "warn") as warn:
            values, sources = fc.load_values()
        warn.assert_called_once()
        self.assertEqual((values, sources), ({"touchpad.tap": "no"}, {"touchpad.tap": "system"}))
        with mock.patch.object(fc, "warn"):
            self.set("touchpad.tap", "yes")
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, mock.patch.object(fc, "warn"):
            fc.main(["get", "touchpad.tap"])
            fc.main(["get", "mouse.pointer-speed"])
        self.assertEqual(out.getvalue().splitlines(), ["touchpad.tap\tyes\tuser", "mouse.pointer-speed\t0.00\tdefault"])

    def test_the_conffiles_document_real_settings(self):
        """Uncommented, the examples in input.conf and keyboard.conf are valid.
        The locale has none: the system's is /etc/default/locale."""
        for topic in fc.TOPICS:
            if topic == "locale":
                continue
            with open(os.path.join(PACKAGE, f"etc/xdg/flickos/{topic}.conf"), encoding="utf-8") as f:
                text = f.read()
            self.write(f"etc/{topic}.conf", text)
            with mock.patch.object(fc, "warn") as warn:
                self.assertEqual(fc.load_values()[0], {})       # all commented out
            examples = "\n".join(line[1:] for line in text.splitlines()
                                 if re.match(r"^#(\[[\w-]+\]|\w+=)", line))
            self.write(f"etc/{topic}.conf", examples)
            with mock.patch.object(fc, "warn") as warn:
                values = fc.load_values()[0]
            warn.assert_not_called()
            self.assertEqual(len(values), examples.count("="), topic)
            os.unlink(os.path.join(self.tmp, f"etc/{topic}.conf"))

    def test_xkb_rules(self):
        rules = fc.xkb_rules()
        self.assertEqual(rules["layout"], {"us": "English (US)", "de": "German"})
        self.assertEqual(rules["variant"]["de"], {"nodeadkeys": "German (no dead keys)"})
        self.assertIn("grp:alt_shift_toggle", rules["option"])
        self.assertEqual(fc.system_keyboard(), {"model": "pc105", "layout": "us", "variant": "", "options": ""})

    def test_layout_goes_to_the_environment_with_all_four_variables(self):
        self.assertEqual(self.set("keyboard.layout", "de")[0], 0)
        self.assertEqual(self.environment(), ["XKB_DEFAULT_MODEL=pc105", "XKB_DEFAULT_LAYOUT=de",
                                              "XKB_DEFAULT_VARIANT=", "XKB_DEFAULT_OPTIONS="])
        self.assertEqual(self.set("keyboard.variant", "nodeadkeys")[0], 0)
        self.assertIn("XKB_DEFAULT_VARIANT=nodeadkeys", self.environment())
        # Another layout drops a variant it hasn't.
        self.set("keyboard.layout", "us")
        self.assertIsNone(fc.load_values()[0].get("keyboard.variant"))
        with mock.patch.object(fc, "warn"):
            self.assertEqual(self.set("keyboard.layout", "xx")[0], 1)
            self.assertEqual(self.set("keyboard.variant", "nodeadkeys")[0], 1)    # not a us variant

    def test_back_to_the_system_layout(self):
        self.set("keyboard.layout", "de")
        self.set("keyboard.variant", "nodeadkeys")
        # In the session labwc keeps the variables: the system's are written.
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        with mock.patch.object(fc.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            self.set("keyboard.layout", "default")
        self.assertIn("XKB_DEFAULT_LAYOUT=us", self.environment())
        self.assertIn("XKB_DEFAULT_VARIANT=", self.environment())       # not de's variant
        # At the next login nothing is needed.
        with mock.patch("sys.stdout"):
            self.assertEqual(fc.main(["prepare"]), 0)
        self.assertFalse(os.path.exists(os.path.join(self.control, "environment")))

    def test_prepare_writes_and_deletes(self):
        with mock.patch("sys.stdout"):
            self.set("mouse.accel-profile", "flat")
        os.unlink(os.path.join(self.control, "labwc.xml"))
        self.assertEqual(fc.main(["prepare"]), 0)
        self.assertEqual(self.fragment().findtext("libinput/device/accelProfile"), "flat")
        os.unlink(fc.user_file("input"))
        self.assertEqual(fc.main(["prepare"]), 0)
        self.assertFalse(os.path.exists(os.path.join(self.control, "labwc.xml")))


class IdleTest(SettingsTest):
    """Settings > Power & Idle: flickos-control idle runs swayidle."""

    def fake_process(self, pid, comm, cmdline, environ, uid_ok=True):
        folder = os.path.join(self.proc, str(pid))
        os.makedirs(folder)
        with open(os.path.join(folder, "comm"), "w") as f:
            f.write(comm + "\n")
        with open(os.path.join(folder, "cmdline"), "wb") as f:
            f.write(b"\0".join(arg.encode() for arg in cmdline) + b"\0")
        with open(os.path.join(folder, "environ"), "wb") as f:
            f.write(b"\0".join(item.encode() for item in environ) + b"\0")

    def setUp(self):
        super().setUp()
        self.proc = os.path.join(self.tmp, "proc")
        os.makedirs(self.proc)
        with open(os.path.join(self.proc, "cmdline"), "w") as f:
            f.write("BOOT_IMAGE=/vmlinuz quiet\n")
        patcher = mock.patch.object(fc, "PROC", self.proc)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_command(self):
        self.assertEqual(fc.SWAYLOCK, "swaylock -f -c 383c4a")
        self.assertEqual(fc.LOCK_SCREEN, "flickos-control lock")
        self.assertEqual(fc.idle_command({}), ["swayidle", "-w", "timeout", "300", fc.LOCK_SCREEN,
                                               "timeout", "900", fc.SUSPEND, "before-sleep", fc.LOCK_SCREEN,
                                               "lock", fc.LOCK_SCREEN])
        # Never: left out; the lock before sleep and on logind's request stay.
        self.assertEqual(fc.idle_command({"idle.lock-after": "0", "idle.suspend-after": "0"}),
                         ["swayidle", "-w", "before-sleep", fc.LOCK_SCREEN, "lock", fc.LOCK_SCREEN])
        # No lock before sleep: only logind's request still locks.
        self.assertEqual(fc.idle_command({"idle.lock-before-sleep": "no"})[-4:],
                         ["900", fc.SUSPEND, "lock", fc.LOCK_SCREEN])

    def test_idle_execs_swayidle_with_the_mark(self):
        self.set("idle.lock-after", "600")
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/swayidle"), \
             mock.patch.object(fc.os, "execvpe") as execvpe:
            fc.main(["idle"])
        command, args, env = execvpe.call_args.args
        self.assertEqual(args[:5], ["swayidle", "-w", "timeout", "600", fc.LOCK_SCREEN])
        self.assertEqual(env[fc.IDLE_MARK], "1")

    def test_nothing_in_the_live_session(self):
        with open(os.path.join(self.proc, "cmdline"), "w") as f:
            f.write("boot=live components quiet\n")
        with mock.patch.object(fc.os, "execvpe") as execvpe, mock.patch("sys.stdout"):
            self.assertEqual(fc.main(["idle"]), 0)
        execvpe.assert_not_called()

    def test_only_flickos_swayidle_is_restarted(self):
        self.fake_process(101, "swayidle", ["swayidle", "-w"], [f"{fc.IDLE_MARK}=1"])
        self.fake_process(102, "swayidle", ["swayidle", "-w", "timeout", "300", fc.SWAYLOCK], ["HOME=/x"])
        self.fake_process(103, "swayidle", ["swayidle", "timeout", "60", "my-locker"], ["HOME=/x"])
        self.fake_process(104, "waybar", ["waybar"], [f"{fc.IDLE_MARK}=1"])
        self.assertEqual(sorted(fc.idle_daemons()), [101, 102])
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        with mock.patch.object(fc.os, "kill") as kill, mock.patch.object(fc.subprocess, "Popen") as popen:
            status, out = self.set("idle.suspend-after", "1800")
        self.assertEqual((status, out.strip()), (0, "Applied."))
        self.assertEqual(sorted(call.args[0] for call in kill.call_args_list), [101, 102])
        self.assertEqual(popen.call_args.args[0], [*fc.SELF, "idle"])
        # Idle settings don't touch labwc.
        self.assertFalse(os.path.exists(os.path.join(self.control, "labwc.xml")))

    def test_lock_background(self):
        # flickos-layout's swaybg, and waypaper's with an image per screen.
        self.fake_process(401, "swaybg", ["swaybg", "-i", "/usr/share/flickos/layouts/redmond/wallpaper.jpg",
                                          "-m", "fill", "-c", "#383c4a"], [])
        self.assertEqual(fc.wallpaper_images(), [(None, "/usr/share/flickos/layouts/redmond/wallpaper.jpg", "fill")])
        shutil.rmtree(os.path.join(self.proc, "401"))
        self.fake_process(402, "swaybg", ["swaybg", "-o", "DP-1", "-i", "/p/a.jpg", "-m", "fit",
                                          "-o", "HDMI-A-1", "-i", "/p/b:c.jpg", "-m", "fill"], [])
        self.fake_process(403, "swaybg", ["swaybg", "-c", "#383c4a"], [])       # a color only
        self.assertEqual(fc.wallpaper_images(), [("DP-1", "/p/a.jpg", "fit"), ("HDMI-A-1", "/p/b:c.jpg", "fill")])
        swaylock = ["swaylock", "-f", "-c", "383c4a"]
        self.assertEqual(fc.lock_command({}), swaylock)
        self.assertEqual(fc.lock_command({"lock.background": "wallpaper"}),
                         swaylock + ["-i", "DP-1:/p/a.jpg", "-i", "HDMI-A-1:/p/b:c.jpg", "-s", "fit"])
        # A path with a colon can't be given without its output; no image: the color.
        self.assertEqual(fc.lock_command({"lock.background": "wallpaper"}, [(None, "/p/b:c.jpg", "fill")]), swaylock)
        self.assertEqual(fc.lock_command({"lock.background": "wallpaper"}, []), swaylock)
        self.assertEqual(fc.lock_command({"lock.background": "wallpaper"}, [(None, "/p/a.jpg", "odd")]),
                         swaylock + ["-i", "/p/a.jpg"])

    def test_lock_command(self):
        self.assertEqual(self.set("lock.background", "wallpaper"),
                         (0, "Saved. The screen locks this way from now on.\n"))
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/swaylock"), \
             mock.patch.object(fc, "wallpaper_images", return_value=[(None, "/w.jpg", "fill")]), \
             mock.patch.object(fc.os, "execvp") as execvp:
            fc.main(["lock"])
        self.assertEqual(execvp.call_args.args, ("swaylock", ["swaylock", "-f", "-c", "383c4a", "-i", "/w.jpg",
                                                              "-s", "fill"]))
        with mock.patch.object(fc, "warn"):
            self.assertEqual(self.set("lock.background", "blurred")[0], 1)

    def test_duration_names(self):
        self.assertEqual([fc.duration_name(s) for s in (0, 60, 300, 3600, 7200, 90)],
                         ["Never", "1 minute", "5 minutes", "1 hour", "2 hours", "90 seconds"])
        for seconds in fc.IDLE_CHOICES:
            fc.normalize(fc.SETTINGS["idle.lock-after"], seconds)


class TerminalTest(SettingsTest):
    def test_default_follows_xdg_terminal_exec_order(self):
        system = os.path.join(self.tmp, "etc-xdg")
        os.environ["XDG_CONFIG_DIRS"] = system
        os.environ["XDG_CURRENT_DESKTOP"] = "labwc:wlroots"
        self.write("etc-xdg/xdg-terminals.list", "# FlickOS\nfoot.desktop\n")
        installed = {"foot.desktop": "Foot", "kitty.desktop": "kitty"}
        self.assertEqual(fc.default_terminal(installed), "foot.desktop")
        self.write("config/xdg-terminals.list", "-foot.desktop\ngone.desktop\n")
        self.assertEqual(fc.default_terminal(installed), "foot.desktop")    # nothing usable there
        fc.set_terminal("kitty.desktop")
        self.assertEqual(fc.default_terminal(installed), "kitty.desktop")
        with open(os.path.join(self.tmp, "config", "xdg-terminals.list")) as f:
            self.assertEqual(f.read().splitlines(), ["kitty.desktop", "-foot.desktop", "gone.desktop"])
        # A desktop-specific list comes first.
        self.write("config/labwc-xdg-terminals.list", "foot.desktop\n")
        self.assertEqual(fc.default_terminal(installed), "foot.desktop")
        with self.assertRaises(fc.ControlError):
            fc.set_terminal("../evil")


# Shaped like /usr/share/i18n/SUPPORTED and a locale definition's LC_IDENTIFICATION.
SUPPORTED = "C.UTF-8 UTF-8\nde_DE.UTF-8 UTF-8\nde_DE ISO-8859-1\nfil_PH UTF-8\nsr_RS@latin UTF-8\n"
LOCALE_DEFINITION = """comment_char %
LC_IDENTIFICATION
title      "German locale for Germany"
language   "German"
territory  "Germany"
END LC_IDENTIFICATION
"""


class LocaleTest(SettingsTest):
    """Settings > Language & Region: LANG and LC_* in the environment overlay."""

    def installed(self, *names):
        return mock.patch.object(fc, "installed_locales", return_value={fc.locale_key(n) for n in names})

    def test_names(self):
        self.assertEqual([fc.locale_key(n) for n in ("en_US.UTF-8", "fil_PH", "sr_RS@latin", "ca_ES.UTF-8@valencia")],
                         ["en_US.utf8", "fil_PH", "sr_RS@latin", "ca_ES.utf8@valencia"])
        self.assertEqual(fc.supported_locales(self.write("SUPPORTED", SUPPORTED)),
                         ["de_DE.UTF-8", "fil_PH", "sr_RS@latin"])
        self.assertEqual(fc.supported_locales(os.path.join(self.tmp, "none")), [])
        folder = os.path.join(self.tmp, "locales")
        self.write("locales/de_DE", LOCALE_DEFINITION)
        self.write("locales/sr_RS@latin", LOCALE_DEFINITION.replace("Germany", "Serbia").replace("German", "Serbian"))
        self.assertEqual(fc.locale_name("de_DE.UTF-8", folder), "German (Germany)")
        self.assertEqual(fc.locale_name("sr_RS@latin", folder), "Serbian (Serbia, latin)")
        self.assertEqual(fc.locale_name("xx_YY.UTF-8", folder), "xx_YY.UTF-8")
        self.assertEqual(fc.system_locale(), {"LANG": "en_US.UTF-8", "LC_TIME": "en_GB.UTF-8"})
        for name in ("de_DE.UTF-8", "fil_PH", "sr_RS@latin", "C.UTF-8"):
            fc.normalize(fc.SETTINGS["locale.language"], name)
        for name in ("de_DE.UTF-8 x", "../de", "de_DE;id", ""):
            with self.assertRaises(fc.ControlError, msg=name):
                fc.normalize(fc.SETTINGS["locale.language"], name)

    def test_language_and_formats(self):
        system = {"LANG": "en_US.UTF-8", "LANGUAGE": "en_US:en", "LC_TIME": "en_GB.UTF-8"}
        self.assertEqual(fc.locale_environment({}, False, system), [])
        language = dict(fc.locale_environment({"locale.language": "de_DE.UTF-8"}, False, system))
        # The language wins over LANGUAGE and LC_MESSAGES; formats the system
        # sets stay, the others follow the language.
        self.assertEqual((language["LANG"], language["LANGUAGE"], language["LC_MESSAGES"]),
                         ("de_DE.UTF-8", "", "de_DE.UTF-8"))
        self.assertEqual((language["LC_TIME"], language["LC_NUMERIC"]), ("en_GB.UTF-8", "de_DE.UTF-8"))
        formats = dict(fc.locale_environment({"locale.formats": "fil_PH"}, False, system))
        self.assertEqual((formats["LANG"], formats["LANGUAGE"]), ("en_US.UTF-8", "en_US:en"))
        self.assertEqual({formats[name] for name in fc.FORMAT_VARS}, {"fil_PH"})
        # In the session, back to the system's; without a system locale nothing.
        live = dict(fc.locale_environment({}, True, system))
        self.assertEqual((live["LANG"], live["LANGUAGE"], live["LC_TIME"], live["LC_PAPER"]),
                         ("en_US.UTF-8", "en_US:en", "en_GB.UTF-8", "en_US.UTF-8"))
        self.assertEqual(fc.locale_environment({}, True, {}), [])

    def test_set_needs_an_installed_locale(self):
        with self.installed("en_US.UTF-8"), mock.patch.object(fc, "warn") as warn:
            self.assertEqual(self.set("locale.language", "de_DE.UTF-8")[0], 1)
        self.assertIn("locale-add de_DE.UTF-8", warn.call_args.args[0])
        self.assertFalse(os.path.exists(fc.user_file("locale")))
        with self.installed("de_DE.utf8"):
            self.assertEqual(self.set("locale.language", "de_DE.UTF-8")[0], 0)
        self.assertIn("LANG=de_DE.UTF-8", self.environment())
        self.assertIn("LC_TIME=en_GB.UTF-8", self.environment())
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            fc.main(["get", "locale.language"])
        self.assertEqual(out.getvalue(), "locale.language\tde_DE.UTF-8\tuser\n")
        # Back to the system's: nothing at the next login.
        self.set("locale.language", "default")
        self.assertFalse(os.path.exists(os.path.join(self.control, "environment")))

    def test_applies_live_with_the_keyboard_layout(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        with self.installed("fil_PH"), \
             mock.patch.object(fc.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            status, out = self.set("locale.formats", "fil_PH")
        self.assertEqual(status, 0)
        self.assertIn("next login", out)
        self.assertEqual(run.call_args.args[0], [fc.LAYOUT, "reconfigure"])
        environment = self.environment()
        self.assertIn("XKB_DEFAULT_LAYOUT=us", environment)     # the session keeps them anyway
        self.assertIn("LC_MONETARY=fil_PH", environment)
        self.assertIn("LANG=en_US.UTF-8", environment)

    def test_system_locale_args(self):
        system = {"LANG": "en_PH.UTF-8", "LANGUAGE": "en_PH:en", "LC_TIME": "fil_PH", "LC_NUMERIC": "fil_PH"}
        self.assertEqual(fc.system_locale_args(system, None, None),
                         ["LANG=en_PH.UTF-8", "LANGUAGE=en_PH:en", "LC_NUMERIC=fil_PH", "LC_TIME=fil_PH"])
        self.assertEqual(fc.system_locale_args(system, "de_DE.UTF-8", None),
                         ["LANG=de_DE.UTF-8", "LC_NUMERIC=fil_PH", "LC_TIME=fil_PH"])
        args = fc.system_locale_args(system, None, "de_DE.UTF-8")
        self.assertEqual(args[:2], ["LANG=en_PH.UTF-8", "LANGUAGE=en_PH:en"])
        self.assertEqual(args[2:], [f"{name}=de_DE.UTF-8" for name in fc.FORMAT_VARS])


class PowerTest(unittest.TestCase):
    """Settings > Power & Idle: the power button and the lid (logind)."""

    def test_state_from_logind(self):
        text = 's "poweroff"\ns "suspend"\ns ""\n'
        with mock.patch.object(fc, "run", return_value=text) as run:
            self.assertEqual(fc.power_state(), {"power-key": "poweroff", "lid": "suspend",
                                                "lid-external-power": "default"})
        self.assertEqual(run.call_args.args[0], ["busctl", "get-property", *fc.LOGIND, "HandlePowerKey",
                                                 "HandleLidSwitch", "HandleLidSwitchExternalPower"])
        with mock.patch.object(fc, "run", return_value='s "poweroff"\n'), self.assertRaises(fc.ControlError):
            fc.power_state()

    def test_actions_are_the_helpers(self):
        self.assertEqual({setting: logind for setting, logind, _, _ in fc.POWER_SETTINGS}, helper.POWER_SETTINGS)
        for _, _, _, actions in fc.POWER_SETTINGS:
            self.assertLessEqual(set(actions), set(helper.POWER_ACTIONS))
            self.assertLessEqual(set(actions), set(fc.POWER_ACTIONS))

    def test_lid_switch(self):
        tmp = tempfile.mkdtemp(prefix="flickos-control-input-")
        self.addCleanup(shutil.rmtree, tmp)
        for device, sw in (("input0", "0"), ("input1", None)):
            os.makedirs(os.path.join(tmp, device, "capabilities"))
            if sw is not None:
                with open(os.path.join(tmp, device, "capabilities", "sw"), "w") as f:
                    f.write(sw + "\n")
        self.assertFalse(fc.has_lid(tmp))
        os.makedirs(os.path.join(tmp, "input2", "capabilities"))
        with open(os.path.join(tmp, "input2", "capabilities", "sw"), "w") as f:
            f.write("1\n")
        self.assertTrue(fc.has_lid(tmp))
        self.assertFalse(fc.has_lid(os.path.join(tmp, "none")))


# Shaped like `wlr-randr --json`: a laptop panel, and two identical monitors
# without a serial, one of them off.
SCREENS = [
    {"name": "eDP-1", "description": "BOE 0x0BCA (eDP-1)", "make": "BOE", "model": "0x0BCA", "serial": None,
     "physical_size": {"width": 290, "height": 170}, "enabled": True,
     "modes": [{"width": 1920, "height": 1080, "refresh": 60.008999, "preferred": True, "current": True},
               {"width": 1280, "height": 720, "refresh": 60.0, "preferred": False, "current": False}],
     "position": {"x": 0, "y": 0}, "transform": "normal", "scale": 1.25, "adaptive_sync": False},
    {"name": "DP-1", "description": "Dell Inc. DELL P2419H (DP-1)", "make": "Dell Inc.", "model": "DELL P2419H",
     "serial": None, "enabled": True,
     "modes": [{"width": 1920, "height": 1080, "refresh": 59.951, "preferred": True, "current": True}],
     "position": {"x": 1536, "y": 0}, "transform": "90", "scale": 1.0, "adaptive_sync": None},
    {"name": "DP-2", "description": "Dell Inc. DELL P2419H (DP-2)", "make": "Dell Inc.", "model": "DELL P2419H",
     "serial": None, "enabled": False, "modes": []},
]


class DisplaysTest(SettingsTest):
    """Settings > Displays: kanshi profiles in ~/.config/flickos/displays."""

    def test_output_lines(self):
        self.assertEqual(fc.screen_criteria(SCREENS[0], SCREENS), "BOE 0x0BCA Unknown")
        self.assertEqual(fc.screen_criteria(SCREENS[1], SCREENS), "DP-1")      # same identity as DP-2
        self.assertEqual(fc.output_line(SCREENS[0], SCREENS),
                         'output "BOE 0x0BCA Unknown" enable mode 1920x1080@60.009Hz position 0,0 scale 1.25 '
                         'transform normal adaptive_sync off')
        self.assertEqual(fc.output_line(SCREENS[1], SCREENS),
                         "output DP-1 enable mode 1920x1080@59.951Hz position 1536,0 scale 1 transform 90")
        self.assertEqual(fc.output_line(SCREENS[2], SCREENS), "output DP-2 disable")
        odd = dict(SCREENS[0], make='Acme "Pro"', serial="X1")
        self.assertEqual(fc.output_line(odd, [odd]).split(" enable")[0], """output 'Acme "Pro" 0x0BCA X1'""")
        both = dict(odd, model="it's")
        self.assertEqual(fc.screen_criteria(both, [both]), "eDP-1")

    def test_profile_is_named_after_the_screens(self):
        name, text = fc.screens_profile(SCREENS)
        self.assertEqual(fc.screens_profile(list(reversed(SCREENS)))[0], name)
        self.assertEqual(text.splitlines()[:2], ["# BOE 0x0BCA Unknown, DP-1, DP-2", f"profile {name} {{"])
        self.assertEqual([line.split()[1] for line in text.splitlines()[2:-1]], ["DP-1", "DP-2", '"BOE'])
        self.assertNotEqual(fc.screens_profile(SCREENS[:1])[0], name)

    def test_save_list_forget(self):
        os.environ["WAYLAND_DISPLAY"] = "wayland-1"
        with mock.patch.object(fc, "read_screens", return_value=SCREENS), \
             mock.patch.object(fc, "restart_displays") as restart, mock.patch("sys.stdout"):
            self.assertEqual(fc.main(["displays", "save"]), 0)
            self.assertEqual(fc.main(["displays", "save"]), 0)          # the same screens: replaced
        with mock.patch.object(fc, "read_screens", return_value=SCREENS[:1]), \
             mock.patch.object(fc, "restart_displays"), mock.patch("sys.stdout"):
            self.assertEqual(fc.main(["displays", "save"]), 0)
        self.assertEqual(restart.call_count, 2)
        profiles = fc.read_profiles()
        self.assertEqual([title for _, title, _ in profiles], ["BOE 0x0BCA Unknown, DP-1, DP-2", "BOE 0x0BCA Unknown"])
        with open(fc.displays_file()) as f:
            text = f.read()
        self.assertTrue(text.startswith(fc.DISPLAYS_HEADER))
        self.assertEqual(text.count("\nprofile "), 2)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            fc.main(["displays", "list"])
        self.assertEqual(out.getvalue().splitlines()[1], f"{profiles[1][0]}\tBOE 0x0BCA Unknown")
        with mock.patch.object(fc, "restart_displays"), mock.patch("sys.stdout"), mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["displays", "forget", "screens-none"]), 1)
            self.assertEqual(fc.main(["displays", "forget"]), 2)
            self.assertEqual(fc.main(["displays", "forget", profiles[0][0]]), 0)
            self.assertEqual([name for name, _, _ in fc.read_profiles()], [profiles[1][0]])
            self.assertEqual(fc.main(["displays", "forget", "all"]), 0)
        self.assertFalse(os.path.exists(fc.displays_file()))

    def test_overlapping_screens(self):
        # 1920x1080 at scale 1.25 is 1536 wide; the turned Dell is 1080 wide.
        self.assertEqual(fc.screen_box(SCREENS[0]), (0, 0, 1536, 864))
        self.assertEqual(fc.screen_box(SCREENS[1]), (1536, 0, 1080, 1920))
        self.assertIsNone(fc.screen_box(SCREENS[2]))
        self.assertEqual(fc.overlapping_screens(SCREENS), [])
        # wdisplays turns a screen back on at 0,0: on top of the other one.
        laptop = dict(SCREENS[0], scale=1.0, modes=[{"width": 1366, "height": 768, "current": True}])
        monitor = dict(SCREENS[1], transform="normal", position={"x": 0, "y": 0})
        self.assertEqual(fc.overlapping_screens([monitor, laptop]), [(monitor, laptop)])
        self.assertIn("DELL P2419H and BOE 0x0BCA overlap", fc.overlap_message([(monitor, laptop)]))
        self.assertEqual(fc.overlapping_screens([monitor, dict(laptop, enabled=False)]), [])
        self.assertEqual(fc.overlapping_screens([monitor, dict(laptop, position={"x": 1920, "y": 0})]), [])
        mirror = dict(laptop, modes=monitor["modes"])
        self.assertEqual(fc.overlapping_screens([monitor, mirror]), [])
        os.environ["WAYLAND_DISPLAY"] = "wayland-1"
        with mock.patch.object(fc, "read_screens", return_value=[monitor, laptop]), \
             mock.patch.object(fc, "restart_displays") as restart, mock.patch.object(fc, "warn") as warn:
            self.assertEqual(fc.main(["displays", "save"]), 1)
        self.assertIn("overlap", warn.call_args.args[0])
        restart.assert_not_called()
        self.assertEqual(fc.read_profiles(), [])

    def test_a_screen_turned_on_moves_beside_the_others(self):
        laptop = dict(SCREENS[0], name="eDP-1", scale=1.0, modes=[{"width": 1366, "height": 768, "current": True}])
        monitor = dict(SCREENS[1], name="HDMI-A-1", transform="normal", position={"x": 0, "y": 20})
        screens = [monitor, laptop]
        with mock.patch.object(fc, "read_screens", return_value=screens), mock.patch.object(fc, "run") as run:
            self.assertEqual(fc.place_turned_on({"HDMI-A-1"}), {"HDMI-A-1", "eDP-1"})
            run.assert_called_once_with(["wlr-randr", "--output", "eDP-1", "--pos", "1920,20"])
            run.reset_mock()
            # On before (the user put it there), beside, or the same area: left alone.
            fc.place_turned_on({"HDMI-A-1", "eDP-1"})
            laptop["position"] = {"x": 1920, "y": 0}
            fc.place_turned_on({"HDMI-A-1"})
            laptop.update(position={"x": 0, "y": 20}, modes=monitor["modes"])
            fc.place_turned_on({"HDMI-A-1"})
        run.assert_not_called()
        with mock.patch.object(fc, "read_screens", side_effect=fc.ControlError("gone")):
            self.assertEqual(fc.place_turned_on({"HDMI-A-1"}), {"HDMI-A-1"})

    def test_arrange_checks_only_while_wdisplays_runs(self):
        process = mock.Mock(returncode=0)
        process.wait.side_effect = [subprocess.TimeoutExpired("wdisplays", 1), subprocess.TimeoutExpired("wdisplays", 1),
                                    None]
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/wdisplays"), \
             mock.patch.object(fc.subprocess, "Popen", return_value=process) as popen, \
             mock.patch.object(fc, "read_screens", return_value=SCREENS[:1]), \
             mock.patch.object(fc, "place_turned_on", side_effect=lambda on: on | {"x"}) as place:
            self.assertEqual(fc.main(["displays", "arrange"]), 0)
        self.assertEqual(popen.call_args.args[0], ["wdisplays"])
        self.assertEqual([call.args[0] for call in place.call_args_list], [{"eDP-1"}, {"eDP-1", "x"}, {"eDP-1", "x"}])
        with mock.patch.object(fc.shutil, "which", return_value=None), mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["displays", "arrange"]), 1)

    def test_displays_starts_through_arrange(self):
        tile = next(tile for tile in fc.TILES if tile.id == "displays")
        self.assertEqual(tile.command[0], "wdisplays")                 # shown while wdisplays is installed
        self.assertEqual(tile.argv, (*fc.SELF, "displays", "arrange"))
        self.assertEqual(next(tile for tile in fc.TILES if tile.id == "sound").argv, ("pavucontrol",))
        # Same id as wdisplays' own entry, which it takes the place of.
        entry = configparser.ConfigParser(interpolation=None)
        entry.read(os.path.join(PACKAGE, "usr/share/flickos/applications/network.cycles.wdisplays.desktop"))
        self.assertEqual(entry["Desktop Entry"]["Exec"], "flickos-control displays arrange")
        self.assertEqual(entry["Desktop Entry"]["TryExec"], fc.ARRANGE[0])

    def test_save_needs_the_session(self):
        with mock.patch.object(fc, "warn") as warn:
            self.assertEqual(fc.main(["displays", "save"]), 1)
        self.assertIn("Wayland", warn.call_args.args[0])

    def test_read_screens(self):
        with mock.patch.object(fc, "run", return_value=json.dumps(SCREENS)):
            self.assertEqual(fc.read_screens(), SCREENS)
        # A virtual screen (a tablet as a second screen) is never kept or shown.
        virtual = dict(SCREENS[0], name="HEADLESS-PHONE", make=None, model=None, serial=None)
        with mock.patch.object(fc, "run", return_value=json.dumps(SCREENS + [virtual])):
            self.assertEqual(fc.read_screens(), SCREENS)
        for text in ("", "{}"):
            with mock.patch.object(fc, "run", return_value=text), self.assertRaises(fc.ControlError):
                fc.read_screens()

    def fake_kanshi(self, pid, marked):
        folder = os.path.join(self.proc, str(pid))
        os.makedirs(folder)
        with open(os.path.join(folder, "comm"), "w") as f:
            f.write("kanshi\n")
        with open(os.path.join(folder, "environ"), "wb") as f:
            f.write(f"{fc.DISPLAYS_MARK}=1\0".encode() if marked else b"HOME=/x\0")

    def test_kanshi_runs_only_with_a_kept_arrangement(self):
        self.proc = os.path.join(self.tmp, "proc")
        os.makedirs(self.proc)
        with mock.patch.object(fc, "PROC", self.proc):
            with mock.patch.object(fc.os, "execvpe") as execvpe:
                self.assertEqual(fc.main(["displays", "start"]), 0)
                execvpe.assert_not_called()
                fc.write_profiles([("screens-1", "eDP-1", "profile screens-1 {\n\toutput eDP-1 enable\n}\n")])
                with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/kanshi"):
                    fc.main(["displays", "start"])
            self.assertEqual(execvpe.call_args.args[:2], ("kanshi", ["kanshi", "-c", fc.displays_file()]))
            self.assertEqual(execvpe.call_args.args[2][fc.DISPLAYS_MARK], "1")
            # Running already, or a user's own kanshi: nothing more.
            self.fake_kanshi(201, marked=False)
            with mock.patch.object(fc.os, "execvpe") as execvpe, mock.patch.object(fc, "warn"):
                self.assertEqual(fc.main(["displays", "start"]), 0)
            execvpe.assert_not_called()
            self.fake_kanshi(202, marked=True)
            self.assertEqual(fc.display_daemons(), ([202], [201]))
            # A change: the running one rereads; none left: it stops.
            with mock.patch.object(fc.os, "kill") as kill, mock.patch.object(fc.subprocess, "Popen") as popen:
                fc.restart_displays()
                fc.write_profiles([])
                fc.restart_displays()
            self.assertEqual([call.args for call in kill.call_args_list], [(202, fc.signal.SIGHUP),
                                                                           (202, fc.signal.SIGTERM)])
            popen.assert_not_called()
            shutil.rmtree(os.path.join(self.proc, "202"))
            fc.write_profiles([("screens-1", "eDP-1", "profile screens-1 {\n\toutput eDP-1 enable\n}\n")])
            with mock.patch.object(fc.subprocess, "Popen") as popen:
                fc.restart_displays()
            self.assertEqual(popen.call_args.args[0], [*fc.SELF, "displays", "start"])

    def test_describe(self):
        self.assertEqual(fc.describe_screen(SCREENS[0]), ("BOE 0x0BCA", "eDP-1: 1920×1080, 60 Hz, scale 1.25, at 0,0"))
        self.assertEqual(fc.describe_screen(SCREENS[1])[1], "DP-1: 1920×1080, 60 Hz, turned 90, at 1536,0")
        self.assertEqual(fc.describe_screen(SCREENS[2])[1], "DP-2: off")
        headless = dict(SCREENS[1], modes=[{"width": 1280, "height": 720, "refresh": 0.0, "current": True}])
        self.assertEqual(fc.describe_screen(headless)[1], "DP-1: 1280×720, turned 90, at 1536,0")
        self.assertIn(" mode 1280x720 position", fc.output_line(headless, [headless]))


BASE_MAKO = os.path.join(PACKAGE, "../flickos-settings/usr/share/flickos/mako/config")


class NightLightTest(SettingsTest):
    """Settings > Displays: night light (flickos-control night-light)."""

    def setUp(self):
        super().setUp()
        self.proc = os.path.join(self.tmp, "proc")
        os.makedirs(self.proc)
        patcher = mock.patch.object(fc, "PROC", self.proc)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_wlsunset(self, pid, args, marked):
        folder = os.path.join(self.proc, str(pid))
        os.makedirs(folder)
        with open(os.path.join(folder, "comm"), "w") as f:
            f.write("wlsunset\n")
        with open(os.path.join(folder, "cmdline"), "wb") as f:
            f.write(b"\0".join(arg.encode() for arg in ["wlsunset", *args]) + b"\0")
        with open(os.path.join(folder, "environ"), "wb") as f:
            f.write(f"{fc.NIGHT_LIGHT_MARK}=1\0".encode() if marked else b"HOME=/x\0")

    def test_command(self):
        self.assertEqual(fc.night_light_command({}), [fc.NIGHT_LIGHT, "-t", "4000"])
        self.assertEqual(fc.night_light_command({"night-light.temperature": "2700"}), [fc.NIGHT_LIGHT, "-t", "2700"])
        self.assertIsNone(fc.night_light_command({"night-light.enabled": "no"}))
        setting = fc.SETTINGS["night-light.temperature"]
        for value, _ in fc.NIGHT_LIGHT_CHOICES:
            self.assertEqual(fc.normalize(setting, value), str(value))
        self.assertIn(setting.default, dict(fc.NIGHT_LIGHT_CHOICES))
        with mock.patch.object(fc, "warn"):
            self.assertEqual(self.set("night-light.temperature", "1000")[0], 1)
            self.assertEqual(self.set("night-light.temperature", "7000")[0], 1)     # not warmer than day

    def test_start_execs_the_script_with_the_mark(self):
        with mock.patch.object(fc.os.path, "isfile", return_value=True), \
             mock.patch.object(fc.os, "execve") as execve:
            fc.main(["night-light"])
            path, args, env = execve.call_args.args
            self.assertEqual((path, args), (fc.NIGHT_LIGHT, [fc.NIGHT_LIGHT, "-t", "4000"]))
            self.assertEqual(env[fc.NIGHT_LIGHT_MARK], "1")
            self.set("night-light.enabled", "no")
            execve.reset_mock()
            self.assertEqual(fc.main(["night-light"]), 0)
            execve.assert_not_called()

    def test_only_flickos_night_light_is_restarted(self):
        self.fake_wlsunset(301, ["-t", "3300", "-l", "14.59", "-L", "120.97"], marked=True)
        self.fake_wlsunset(302, ["-l", "14.59", "-L", "120.97"], marked=False)     # the script, before
        self.fake_wlsunset(303, ["-S", "06:30", "-s", "18:30"], marked=False)
        self.fake_wlsunset(304, ["-t", "3000", "-l", "52.5", "-L", "13.4"], marked=False)   # the user's own
        self.assertEqual(sorted(fc.night_light_daemons()), [301, 302, 303])
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        with mock.patch.object(fc.os, "kill") as kill, mock.patch.object(fc.subprocess, "Popen") as popen:
            self.assertEqual(self.set("night-light.temperature", "3300"), (0, "Applied.\n"))
            self.assertEqual(popen.call_args.args[0], [*fc.SELF, "night-light"])
            popen.reset_mock()
            self.set("night-light.enabled", "no")
            popen.assert_not_called()
        self.assertEqual(sorted(call.args[0] for call in kill.call_args_list), [301, 301, 302, 302, 303, 303])


class NotificationsTest(SettingsTest):
    """Settings > Notifications: Do Not Disturb (mako's mode)."""

    def test_running_needs_mako_before_asking_dbus(self):
        with mock.patch.object(fc, "own_processes", return_value=[]), \
             mock.patch.object(fc, "command_output") as output:
            self.assertFalse(fc.notifications_running())
        output.assert_not_called()
        for answer, running in (("b true\n", True), ("b false\n", False), ("", False)):
            with mock.patch.object(fc, "own_processes", return_value=[42]), \
                 mock.patch.object(fc, "command_output", return_value=answer) as output:
                self.assertIs(fc.notifications_running(), running)
            self.assertIn(fc.NOTIFICATIONS_BUS_NAME, output.call_args.args[0])

    def test_set_applies_only_to_a_running_mako(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        with mock.patch.object(fc, "notifications_running", return_value=True), \
             mock.patch.object(fc, "run") as run:
            self.assertEqual(self.set("notifications.do-not-disturb", "yes"), (0, "Applied.\n"))
            self.set("notifications.do-not-disturb", "no")
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [["makoctl", "mode", "-a", "do-not-disturb"], ["makoctl", "mode", "-r", "do-not-disturb"]])
        with mock.patch.object(fc, "notifications_running", return_value=False), \
             mock.patch.object(fc, "run") as run:
            status, out = self.set("notifications.do-not-disturb", "yes")
        run.assert_not_called()
        self.assertEqual((status, out), (0, "Saved. It applies when notifications start.\n"))
        self.assertEqual(fc.load_values()[0]["notifications.do-not-disturb"], "yes")

    def test_login_turns_it_on_again_once_mako_runs(self):
        with mock.patch.object(fc, "notifications_running") as running, mock.patch.object(fc, "run") as run:
            self.assertEqual(fc.main(["notifications"]), 0)        # off: nothing to wait for
        running.assert_not_called()
        run.assert_not_called()
        self.set("notifications.do-not-disturb", "yes")
        with mock.patch.object(fc, "notifications_running", side_effect=[False, False, True]), \
             mock.patch.object(fc.time, "sleep"), mock.patch.object(fc, "run") as run:
            self.assertEqual(fc.main(["notifications"]), 0)
        self.assertEqual(run.call_args.args[0], ["makoctl", "mode", "-a", "do-not-disturb"])
        with mock.patch.object(fc, "notifications_running", return_value=False), \
             mock.patch.object(fc.time, "sleep"), mock.patch.object(fc.time, "monotonic", side_effect=[0, 10, 99]), \
             mock.patch.object(fc, "run") as run, mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["notifications"]), 1)
        run.assert_not_called()

    def test_a_users_mako_config_without_the_mode_is_named(self):
        self.assertIsNone(fc.mako_config_problem())
        self.write("config/mako/config", "font=Sans 12\n")
        self.assertIn("[mode=do-not-disturb]", fc.mako_config_problem())
        self.write("config/mako/config", "[mode=do-not-disturb]\ninvisible=1\n")
        self.assertIsNone(fc.mako_config_problem())

    @unittest.skipUnless(os.path.exists(BASE_MAKO), "flickos-settings is not next to this package")
    def test_flickos_mako_config_has_the_mode(self):
        with open(BASE_MAKO) as f:
            text = f.read()
        self.assertIn(f"[mode={fc.DND_MODE}]\ninvisible=1\n", text)
        self.assertIn(f"[mode={fc.DND_MODE} urgency=critical]\ninvisible=0\n", text)


SETTINGS_AUTOSTART = os.path.join(PACKAGE, "../flickos-settings/etc/xdg/flickos/autostart")


class StartupTest(SettingsTest):
    """Settings > Startup Applications: XDG autostart (flickos-control startup)."""

    def setUp(self):
        super().setUp()
        self.system = os.path.join(self.tmp, "etc-xdg")
        self.flickos = os.path.join(self.tmp, "etc-xdg-flickos")
        os.environ.update(XDG_CONFIG_DIRS=f"{self.flickos}:{self.system}", XDG_CURRENT_DESKTOP="labwc:wlroots",
                          XDG_DATA_HOME=os.path.join(self.tmp, "data"), XDG_DATA_DIRS=os.path.join(self.tmp, "share"))

    def entry(self, folder, name, **keys):
        text = "[Desktop Entry]\nType=Application\n" + "".join(f"{k.replace('_', '-')}={v}\n" for k, v in keys.items())
        return self.write(os.path.join(folder, "autostart", name), text)

    def ids(self):
        return [(e.id, e.enabled, e.system) for e in fc.startup_entries()]

    def test_which_entries_run(self):
        self.entry("etc-xdg", "nm-applet.desktop", Name="NM", Exec="nm-applet")
        self.entry("etc-xdg-flickos", "nm-applet.desktop", Name="NM", Hidden="true")    # FlickOS starts it
        self.entry("etc-xdg", "kde.desktop", Name="KDE only", Exec="kde", OnlyShowIn="KDE;")
        self.entry("etc-xdg", "gnome.desktop", Name="Not GNOME", Exec="x", NotShowIn="GNOME;")
        self.entry("etc-xdg", "labwc.desktop", Name="Labwc", Exec="x", NotShowIn="labwc;")
        self.entry("etc-xdg", "missing.desktop", Name="Missing", Exec="x", TryExec="/nonexistent/program")
        self.entry("etc-xdg", "noexec.desktop", Name="No command")
        self.entry("config", "mine.desktop", Name="Mine", Exec="mine --start")
        self.entry("config", "off.desktop", Name="Off", Exec="off", X_GNOME_Autostart_enabled="false")
        self.assertEqual(self.ids(), [("mine.desktop", True, False), ("gnome.desktop", True, True),
                                      ("off.desktop", False, False)])

    def test_enable_disable_add_remove(self):
        self.entry("etc-xdg", "applet.desktop", Name="Applet", Exec="applet")
        with mock.patch("sys.stdout"):
            self.assertEqual(fc.main(["startup", "disable", "applet.desktop"]), 0)
        # A system entry is changed through a user copy.
        self.assertEqual(self.ids(), [("applet.desktop", False, True)])
        with open(os.path.join(self.tmp, "config/autostart/applet.desktop")) as f:
            self.assertIn("Exec=applet\nX-GNOME-Autostart-enabled=false\n", f.read())
        with mock.patch("sys.stdout"), mock.patch.object(fc, "warn") as warn:
            fc.main(["startup", "enable", "applet.desktop"])
            self.assertEqual(fc.main(["startup", "remove", "applet.desktop"]), 1)       # the system's
            self.assertIn("turn it off instead", warn.call_args.args[0])
            self.assertEqual(fc.main(["startup", "enable", "../evil.desktop"]), 1)
            self.assertEqual(fc.main(["startup", "enable"]), 2)
        self.assertEqual(self.ids(), [("applet.desktop", True, True)])
        self.write("share/applications/org.example.Chat.desktop", "[Desktop Entry]\nType=Application\n"
                   "Name=Chat\nExec=chat %U\n\n[Desktop Action new]\nName=New\nExec=chat --new\n")
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fc.main(["startup", "add", "org.example.Chat.desktop"]), 0)
        self.assertEqual(out.getvalue(), "Chat starts at every login from now on.\n")
        chat = [e for e in fc.startup_entries() if e.id == "org.example.Chat.desktop"][0]
        self.assertEqual(fc.exec_argv(chat.entry, chat.path), ["chat"])
        with mock.patch("sys.stdout"), mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["startup", "add", "org.example.None.desktop"]), 1)
            self.assertEqual(fc.main(["startup", "remove", "org.example.Chat.desktop"]), 0)
        self.assertEqual([e.id for e in fc.startup_entries()], ["applet.desktop"])

    def test_run_starts_the_entries_that_are_on(self):
        self.entry("config", "a.desktop", Name="A", Exec="a --x %U", Path=self.tmp)
        self.entry("config", "b.desktop", Name="B", Exec="b", X_GNOME_Autostart_Delay="5")
        self.entry("config", "c.desktop", Name="C", Exec="c", X_GNOME_Autostart_enabled="false")
        self.entry("config", "t.desktop", Name="T", Exec="htop", Terminal="true")
        self.entry("config", "bad.desktop", Name="Bad", Exec='bad "unclosed')
        with mock.patch.object(fc, "tray_running", side_effect=[False, True]), \
             mock.patch.object(fc.time, "sleep"), mock.patch.object(fc.subprocess, "Popen") as popen, \
             mock.patch.object(fc, "warn") as warn:
            self.assertEqual(fc.run_startup(), ["a.desktop", "b.desktop", "t.desktop"])
        self.assertIn("bad.desktop", warn.call_args.args[0])
        commands = [call.args[0] for call in popen.call_args_list]
        self.assertEqual(commands, [["a", "--x"], ["sh", "-c", 'sleep "$0"; exec "$@"', "5", "b"],
                                    ["xdg-terminal-exec", "htop"]])
        self.assertEqual(popen.call_args_list[0].kwargs["cwd"], self.tmp)
        self.assertTrue(all(call.kwargs["start_new_session"] for call in popen.call_args_list))
        # Nothing on: no waiting for the tray.
        for name in ("a", "b", "t", "bad"):
            os.unlink(os.path.join(self.tmp, "config/autostart", f"{name}.desktop"))
        with mock.patch.object(fc, "tray_running") as tray:
            self.assertEqual(fc.run_startup(), [])
        tray.assert_not_called()

    def test_desktop_files(self):
        self.assertEqual(fc.desktop_entry("# x\n[Desktop Entry]\nName=A\\sb\nName[de]=B\nName=C\n[Other]\nExec=d\n"),
                         {"Name": "A b"})
        text = "[Desktop Entry]\nName=A\nX-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-enabled=true\n\n" \
               "[Desktop Action x]\nExec=b\n"
        self.assertEqual(fc.set_desktop_key(text, fc.AUTOSTART_ENABLED, "false"),
                         "[Desktop Entry]\nName=A\nX-GNOME-Autostart-enabled=false\n\n[Desktop Action x]\nExec=b\n")
        self.assertEqual(fc.set_desktop_key("[Desktop Entry]\nName=A\n\n[X]\nK=1\n", "K", "2"),
                         "[Desktop Entry]\nName=A\nK=2\n\n[X]\nK=1\n")
        self.assertEqual(fc.exec_argv({"Exec": 'app --f=%f "a b" %U %%d %i %c', "Icon": "ic", "Name": "App"}),
                         ["app", "--f=", "a b", "%d", "--icon", "ic", "App"])
        with self.assertRaises(fc.ControlError):
            fc.exec_argv({"Exec": "%U"})

    @unittest.skipUnless(os.path.isdir(SETTINGS_AUTOSTART), "flickos-settings is not next to this package")
    def test_flickos_hides_what_its_autostart_starts(self):
        """flickos-settings' overrides: the programs its autostart starts are
        hidden, the print applet is off."""
        with open(os.path.join(SETTINGS_AUTOSTART, "../../../../usr/libexec/flickos/autostart")) as f:
            autostart = f.read()
        for name in os.listdir(SETTINGS_AUTOSTART):
            with open(os.path.join(SETTINGS_AUTOSTART, name)) as f:
                entry = fc.desktop_entry(f.read())
            if entry.get("Hidden") == "true":
                self.assertIn(name[:-8].replace("xdg-user-dirs", "xdg-user-dirs-update")
                              .replace("blueman", "blueman-applet"), autostart, name)
            else:
                self.assertEqual(entry.get(fc.AUTOSTART_ENABLED), "false", name)


# `apt-config dump` of Debian's 20auto-upgrades and 50unattended-upgrades,
# with flickos-archive-keyring 1.5's FlickOS line (before the community repo).
APT_DUMP = """APT::Periodic "";
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
Unattended-Upgrade "";
Unattended-Upgrade::Origins-Pattern "";
Unattended-Upgrade::Origins-Pattern:: "origin=Debian,codename=${distro_codename},label=Debian";
Unattended-Upgrade::Origins-Pattern:: "origin=Debian,codename=${distro_codename},label=Debian-Security";
Unattended-Upgrade::Origins-Pattern:: "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
Unattended-Upgrade::Origins-Pattern:: "origin=FlickOS,codename=${distro_codename},label=FlickOS";
Unattended-Upgrade::Package-Blacklist "";
"""
# flickos-archive-keyring's addition to Debian's origins, and the repository
# whose Origin and Label it names.
KEYRING_ORIGINS = os.path.join(PACKAGE, "../flickos-archive-keyring/etc/apt/apt.conf.d/51flickos-origins")
REPO_DISTRIBUTIONS = os.path.join(PACKAGE, "../../repo/conf/distributions")


class UpdatesTest(unittest.TestCase):
    """Settings > Updates: unattended-upgrades' settings."""

    def test_state(self):
        self.assertEqual(fc.updates_state(APT_DUMP, "/nonexistent"),
                         {"auto": True, "scope": "debian", "reboot": "no", "last": None})
        # Debian's own choice alone: an old helper's "debian", or an older
        # flickos-archive-keyring.
        debian_only = "".join(line for line in APT_DUMP.splitlines(True) if "FlickOS" not in line)
        self.assertEqual(fc.updates_state(debian_only, "/nonexistent")["scope"], "debian-only")
        # Today's list, with the community repository (keyring 1.6).
        community = APT_DUMP.replace('Unattended-Upgrade::Package-Blacklist', 'Unattended-Upgrade::Origins-Pattern:: '
                                     '"origin=FlickOS,codename=${distro_codename}-community,label=FlickOS Community";\n'
                                     'Unattended-Upgrade::Package-Blacklist')
        self.assertEqual(fc.updates_state(community, "/nonexistent")["scope"], "debian")
        off = APT_DUMP.replace('Unattended-Upgrade "1"', 'Unattended-Upgrade "0"')
        self.assertFalse(fc.updates_state(off, "/nonexistent")["auto"])
        disabled = APT_DUMP + 'APT::Periodic::Enable "0";\n'
        self.assertFalse(fc.updates_state(disabled, "/nonexistent")["auto"])
        extra = APT_DUMP + 'Unattended-Upgrade::Origins-Pattern:: "origin=Google LLC";\n'
        self.assertEqual(fc.updates_state(extra, "/nonexistent")["scope"], "custom")
        reboot = APT_DUMP + 'Unattended-Upgrade::Automatic-Reboot "true";\n'
        self.assertEqual(fc.updates_state(reboot, "/nonexistent")["reboot"], "always")
        idle = reboot + 'Unattended-Upgrade::Automatic-Reboot-WithUsers "false";\n'
        self.assertEqual(fc.updates_state(idle, "/nonexistent")["reboot"], "idle")
        self.assertIsNotNone(fc.updates_state(APT_DUMP, __file__)["last"])

    def test_scopes_are_the_helpers(self):
        self.assertEqual(fc.UPDATE_SCOPES, helper.UPDATE_SCOPES)
        self.assertEqual(set(helper.UPDATE_SETTINGS["reboot"]) | {"always"}, set(fc.UPDATE_REBOOT_NAMES))
        self.assertEqual(set(fc.UPDATE_SCOPES) | set(fc.OLD_UPDATE_SCOPES) | {"custom"}, set(fc.UPDATE_SCOPE_NAMES))
        self.assertFalse(set(fc.OLD_UPDATE_SCOPES) & set(helper.UPDATE_SETTINGS["scope"]))

    @unittest.skipUnless(os.path.exists(KEYRING_ORIGINS) and os.path.exists(REPO_DISTRIBUTIONS),
                         "flickos-archive-keyring or repo/ is not next to this package")
    def test_the_keyring_adds_flickos_to_debians_choice(self):
        """The default ("debian") is Debian's 50unattended-upgrades plus
        flickos-archive-keyring's file, which names the repo's Origin and Label."""
        with open(KEYRING_ORIGINS) as f:
            patterns = re.findall(r'^\s*"([^"]+)";', f.read(), re.M)
        self.assertEqual((*fc.OLD_UPDATE_SCOPES["debian-only"], *patterns), fc.UPDATE_SCOPES["debian"])
        for pattern in patterns:
            self.assertNotIn(pattern, fc.UPDATE_SCOPES["security"])
            self.assertIn(pattern, fc.UPDATE_SCOPES["all"])
        # One per distribution, FlickOS's own then the community's.
        with open(REPO_DISTRIBUTIONS) as f:
            stanzas = [dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
                       for block in f.read().split("\n\n") if block.strip()]
        release = stanzas[0]["Codename"]
        self.assertEqual(patterns, [f"origin={s['Origin']},codename=${{distro_codename}}"
                                    f"{s['Codename'].removeprefix(release)},label={s['Label']}" for s in stanzas])

    def test_the_page_is_for_installed_systems(self):
        with mock.patch.object(fc.os.path, "exists", return_value=True):
            with mock.patch.object(fc, "live_session", return_value=False):
                self.assertTrue(fc.page_available("updates"))
            with mock.patch.object(fc, "live_session", return_value=True):
                self.assertFalse(fc.page_available("updates"))


class DateTimeTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(fc.time_settings("Timezone=Asia/Manila\nNTP=yes\nCanNTP=no\n"),
                         {"Timezone": "Asia/Manila", "NTP": "yes", "CanNTP": "no"})
        regions = fc.zones_by_region(["America/Argentina/Salta", "America/New_York", "UTC"])
        self.assertEqual(regions, {"America": [("Argentina/Salta", "America/Argentina/Salta"),
                                               ("New York", "America/New_York")], "Other": [("UTC", "UTC")]})


class PageAvailabilityTest(unittest.TestCase):
    def test_login_needs_the_group_and_no_live_session(self):
        group = mock.Mock(gr_mem=["jon", "ann"])
        with mock.patch.object(fc, "live_session", return_value=False), \
             mock.patch.object(fc.grp, "getgrnam", return_value=group):
            self.assertEqual(fc.autologin_state(), (True, "jon"))
            self.assertTrue(fc.page_available("login"))
        with mock.patch.object(fc, "live_session", return_value=True):
            self.assertFalse(fc.page_available("login"))
        with mock.patch.object(fc, "live_session", return_value=False), \
             mock.patch.object(fc.grp, "getgrnam", side_effect=KeyError("autologin")):
            self.assertEqual(fc.autologin_state(), (False, None))
        self.assertTrue(fc.page_available("layout"))

    def test_firewall_follows_ufw_conf(self):
        tmp = tempfile.mkdtemp(prefix="flickos-control-ufw-")
        self.addCleanup(shutil.rmtree, tmp)
        conf = os.path.join(tmp, "ufw.conf")
        for text, state in (("# ENABLED=yes\nENABLED=yes\nLOGLEVEL=low\n", True), ("ENABLED=no\n", False),
                            ('ENABLED="YES"\n', True), ("LOGLEVEL=low\n", False)):
            with open(conf, "w") as f:
                f.write(text)
            self.assertIs(fc.firewall_state(conf), state, text)
        self.assertIsNone(fc.firewall_state(os.path.join(tmp, "none")))
        with mock.patch.object(fc, "UFW_CONF", conf):
            self.assertTrue(fc.page_available("firewall"))
        with mock.patch.object(fc, "UFW_CONF", os.path.join(tmp, "none")):
            self.assertFalse(fc.page_available("firewall"))

    def test_privacy_needs_flickos_countme(self):
        with mock.patch.object(fc.shutil, "which", return_value=None):
            self.assertFalse(fc.page_available("privacy"))
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/flickos-countme"):
            self.assertTrue(fc.page_available("privacy"))

    def test_unavailable_page_opens_the_first(self):
        with mock.patch.object(fc, "page_available", side_effect=lambda page: page != "login"), \
             mock.patch.object(fc, "single_instance") as lock, mock.patch.object(fc, "warn"), \
             mock.patch.object(fc, "load_gtk", return_value="gtk"), \
             mock.patch.object(fc, "open_window", return_value=0) as open_window:
            lock.return_value.__enter__.return_value = True
            self.assertEqual(fc.main(["--page", "login"]), 0)
        open_window.assert_called_once_with("gtk", "layout")


class UsersTest(unittest.TestCase):
    """The Users page's checks and account list."""

    def test_accounts_are_regular_users_by_full_name(self):
        entries = [mock.Mock(pw_name="root", pw_uid=0, pw_gecos="root", pw_dir="/root"),
                   mock.Mock(pw_name="jon", pw_uid=1000, pw_gecos="Jon,,,", pw_dir="/home/jon"),
                   mock.Mock(pw_name="ann", pw_uid=1001, pw_gecos="Ann Lee", pw_dir="/home/ann"),
                   mock.Mock(pw_name="nobody", pw_uid=65534, pw_gecos="nobody", pw_dir="/nonexistent")]
        with mock.patch.object(fc.pwd, "getpwall", return_value=entries), \
             mock.patch.object(fc.grp, "getgrnam", return_value=mock.Mock(gr_mem=["jon"])), \
             mock.patch.object(fc, "LOGIN_DEFS", "/nonexistent"):
            self.assertEqual(fc.accounts(), [fc.Account("ann", "Ann Lee", 1001, "/home/ann", False),
                                             fc.Account("jon", "Jon", 1000, "/home/jon", True)])

    def test_suggested_user_names(self):
        self.assertEqual(fc.suggest_user_name("Ann Lee"), "ann")
        self.assertEqual(fc.suggest_user_name("Ann Lee", taken={"ann"}), "annlee")
        self.assertEqual(fc.suggest_user_name("  José  Müller-Roth "), "jose")
        self.assertEqual(fc.suggest_user_name("2nd Floor"), "nd")
        self.assertEqual(fc.suggest_user_name("李"), "")
        for name in ("ann", "annlee", "jose", "nd"):
            self.assertIsNone(fc.user_name_problem(name, set()))

    def test_problems(self):
        self.assertIsNone(fc.user_name_problem("ann-lee_2", {"jon"}))
        for name in ("", "Ann", "2ann", "ann lee", "ann;id", "a" * 33, "jon"):
            self.assertIsNotNone(fc.user_name_problem(name, {"jon"}), name)
        self.assertIsNone(fc.full_name_problem("Ann Lee-Roth"))
        for full_name in ("Ann, Lee", "Ann:Lee", "a=b", "back\\slash", "new\nline", "x" * 101):
            self.assertIsNotNone(fc.full_name_problem(full_name), full_name)
        self.assertIsNone(fc.password_problem("secret", "secret"))
        self.assertIsNotNone(fc.password_problem("", ""))
        self.assertIsNotNone(fc.password_problem("secret", "secreT"))

    def test_users_page_only_on_installed_systems(self):
        with mock.patch.object(fc, "live_session", return_value=False):
            self.assertTrue(fc.page_available("users"))
        with mock.patch.object(fc, "live_session", return_value=True):
            self.assertFalse(fc.page_available("users"))


class AboutTest(unittest.TestCase):
    """The About page and `flickos-control about`."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-control-about-")
        self.addCleanup(shutil.rmtree, self.tmp)

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_release_file(self):
        # Shaped like flickos-branding's usr/lib/flickos-release.
        path = self.write("flickos-release", '# comment\nFLICKOS_NAME="FlickOS"\nFLICKOS_VERSION="2.0"\n')
        self.assertEqual(fc.read_shell_values(path), {"FLICKOS_NAME": "FlickOS", "FLICKOS_VERSION": "2.0"})

    def test_hardware(self):
        self.assertEqual(fc.memory_size("MemTotal:       16314560 kB\nMemFree: 1 kB\n"), "15.6 GiB")
        with mock.patch.object(fc.os, "cpu_count", return_value=8):
            self.assertEqual(fc.processor_name("processor\t: 0\nmodel name\t: AMD  Ryzen 5  5600U\n"),
                             "AMD Ryzen 5 5600U × 8")
        lspci = ('00:02.0 "VGA compatible controller" "Intel Corporation" "UHD Graphics 620" -r07 "Lenovo" "x"\n'
                 '01:00.0 "3D controller" "NVIDIA Corporation" "GP108M [GeForce MX150]" -ra1 "Lenovo" "y"\n'
                 '00:1f.3 "Audio device" "Intel Corporation" "Sunrise Point-LP HD Audio" -r21 "Lenovo" "z"\n')
        self.assertEqual(fc.graphics_names(lspci), ["Intel Corporation UHD Graphics 620",
                                                    "NVIDIA Corporation GP108M [GeForce MX150]"])

    def test_computer_name_skips_firmware_placeholders(self):
        dmi = self.tmp
        self.write("sys_vendor", "LENOVO\n")
        self.write("product_name", "To Be Filled By O.E.M.\n")
        with mock.patch.object(fc, "DMI", dmi):
            self.assertEqual(fc.computer_name(), "LENOVO")

    def test_text_for_a_bug_report(self):
        rows = [("FlickOS", "FlickOS 2.0"), ("Debian", "13.1"), ("Graphics", "Intel UHD 620")]
        packages = "ii \tflickos-control\t1.0\nrc \tflickos-old\t0.1\nii \tflick-tiler\t1.3\n"
        with mock.patch.object(fc, "system_info", return_value=rows), \
             mock.patch.object(fc, "command_output", return_value=packages):
            text = fc.system_info_text()
        self.assertEqual(text, "FlickOS:  FlickOS 2.0\nDebian:   13.1\nGraphics: Intel UHD 620\n\n"
                               "Packages:\n  flickos-control 1.0\n  flick-tiler 1.3\n")
        with mock.patch.object(fc, "system_info_text", return_value="x\n"), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fc.main(["about"]), 0)
        self.assertEqual(out.getvalue(), "x\n")

    def test_plain_session(self):
        with mock.patch.object(fc, "FLICKOS_RELEASE", self.write("flickos-release", 'FLICKOS_VERSION="2.2"\n')), \
             mock.patch.object(fc, "live_session", return_value=False), \
             mock.patch.object(fc, "command_output", return_value=""), \
             mock.patch.dict(os.environ, {"FLICKOS_PLAIN": "1"}):
            self.assertEqual(dict(fc.system_info())["FlickOS"], "FlickOS 2.2 (plain session)")

    def test_system_info_leaves_out_what_is_unknown(self):
        with mock.patch.object(fc, "FLICKOS_RELEASE", self.write("flickos-release", 'FLICKOS_VERSION="2.0"\n')), \
             mock.patch.object(fc, "DEBIAN_VERSION", os.path.join(self.tmp, "none")), \
             mock.patch.object(fc, "DMI", os.path.join(self.tmp, "none")), \
             mock.patch.object(fc, "PROC", os.path.join(self.tmp, "none")), \
             mock.patch.object(fc, "live_session", return_value=True), \
             mock.patch.object(fc, "command_output", return_value=""):
            rows = dict(fc.system_info())
        self.assertEqual(rows["FlickOS"], "FlickOS 2.0 (live session)")
        self.assertNotIn("Debian", rows)
        self.assertNotIn("Computer", rows)
        self.assertNotIn("Processor", rows)
        self.assertNotIn("Memory", rows)
        self.assertEqual(rows["Desktop"], "labwc")


_helper_loader = importlib.machinery.SourceFileLoader(
    "control_helper", os.path.join(PACKAGE, "usr/libexec/flickos/control-helper"))
helper = importlib.util.module_from_spec(importlib.util.spec_from_loader(_helper_loader.name, _helper_loader))
_helper_loader.exec_module(helper)


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-control-helper-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.rules = os.path.join(self.tmp, "evdev.lst")
        with open(self.rules, "w") as f:
            f.write(RULES)
        self.keyboard = os.path.join(self.tmp, "keyboard")
        with open(self.keyboard, "w") as f:
            f.write("# KEYBOARD CONFIGURATION FILE\n" + KEYBOARD_FILE)
        for name, value in (("XKB_RULES", self.rules), ("KEYBOARD_DEFAULTS", self.keyboard), ("AFTER", ())):
            patcher = mock.patch.object(helper, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_checks(self):
        known = helper.rules()
        helper.check_keyboard("pc105", "us,de", ",nodeadkeys", "grp:alt_shift_toggle", known)
        for args in (("pc999", "us", "", ""), ("", "", "", ""), ("", "xx", "", ""), ("", "us", "nodeadkeys", ""),
                     ("", "us", "a,b", ""), ("", "us", "", "evil:option"), ("", "us;id", "", "")):
            with self.assertRaises(helper.HelperError, msg=args):
                helper.check_keyboard(*args, known)

    def test_keyboard_rewrites_only_the_xkb_lines(self):
        with mock.patch.object(helper.os, "geteuid", return_value=0), mock.patch("sys.stdout"):
            self.assertEqual(helper.main(["keyboard", "pc105", "de", "nodeadkeys", ""]), 0)
        with open(self.keyboard) as f:
            self.assertEqual(f.read(), '# KEYBOARD CONFIGURATION FILE\nXKBMODEL="pc105"\nXKBLAYOUT="de"\n'
                                       'XKBVARIANT="nodeadkeys"\nXKBOPTIONS=""\nBACKSPACE="guess"\n')
        self.assertEqual(os.stat(self.keyboard).st_mode & 0o777, 0o644)

    def test_missing_lines_are_added(self):
        self.assertEqual(helper.rewrite("# x\nXKBLAYOUT=us\nXKBLAYOUT=fr\n", dict(zip(helper.FIELDS, ("", "de", "", "")))),
                         '# x\nXKBLAYOUT="de"\nXKBMODEL=""\nXKBVARIANT=""\nXKBOPTIONS=""\n')

    def test_refused(self):
        with mock.patch.object(helper.os, "geteuid", return_value=1000), mock.patch("sys.stderr"):
            self.assertEqual(helper.main(["keyboard", "pc105", "de", "", ""]), 1)
        with mock.patch.object(helper.os, "geteuid", return_value=0), mock.patch("sys.stderr"):
            self.assertEqual(helper.main(["keyboard", "pc105", "xx", "", ""]), 1)
            self.assertEqual(helper.main(["keyboard", "pc105"]), 1)
            self.assertEqual(helper.main(["shell"]), 2)
        with open(self.keyboard) as f:
            self.assertIn('XKBLAYOUT="us"', f.read())

    def test_autologin_is_for_the_calling_user_only(self):
        entry = mock.Mock(pw_name="jon", pw_uid=1000)
        group = mock.Mock(gr_mem=["ann"])
        runs = []
        with mock.patch.dict(os.environ, {"PKEXEC_UID": "1000"}), \
             mock.patch.object(helper.os, "geteuid", return_value=0), \
             mock.patch.object(helper.pwd, "getpwuid", return_value=entry), \
             mock.patch.object(helper.grp, "getgrnam", return_value=group), \
             mock.patch.object(helper, "LOGIN_DEFS", os.path.join(self.tmp, "none")), \
             mock.patch.object(helper.subprocess, "run",
                               side_effect=lambda cmd, **kw: runs.append(cmd) or
                               subprocess.CompletedProcess(cmd, 0, "", "")), mock.patch("sys.stdout"):
            self.assertEqual(helper.main(["autologin-on"]), 0)
            self.assertEqual(helper.main(["autologin-off"]), 0)       # not a member: nothing to do
            group.gr_mem = ["jon"]
            self.assertEqual(helper.main(["autologin-off"]), 0)
            with mock.patch("sys.stderr"):
                self.assertEqual(helper.main(["autologin-on", "root"]), 1)
        self.assertEqual(runs, [["gpasswd", "-M", "jon", "autologin"], ["gpasswd", "-d", "jon", "autologin"]])

    def test_autologin_refuses_system_accounts_and_missing_callers(self):
        with mock.patch.object(helper, "LOGIN_DEFS", os.path.join(self.tmp, "none")):
            with mock.patch.dict(os.environ, {"PKEXEC_UID": "0"}), \
                 mock.patch.object(helper.pwd, "getpwuid", return_value=mock.Mock(pw_name="root", pw_uid=0)):
                with self.assertRaisesRegex(helper.HelperError, "not a regular account"):
                    helper.calling_user()
            with mock.patch.dict(os.environ, {"PKEXEC_UID": ""}):
                with self.assertRaisesRegex(helper.HelperError, "pkexec"):
                    helper.calling_user()

    def account_mocks(self, users, admins, caller=None):
        """Patches for users {name: uid}, group sudo with admins, the default
        groups except 'scanner', and pkexec's caller; returns the commands run."""
        runs = []

        def getpwnam(name):
            if name not in users:
                raise KeyError(name)
            return mock.Mock(pw_name=name, pw_uid=users[name], pw_dir=f"/home/{name}")

        def getgrnam(name):
            if name == "sudo":
                return mock.Mock(gr_mem=list(admins))
            if name not in helper.DEFAULT_GROUPS or name == "scanner":
                raise KeyError(name)
            return mock.Mock(gr_mem=[])

        def run(cmd, **kw):
            runs.append((cmd, kw.get("input")))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        by_uid = {uid: name for name, uid in users.items()}
        for patcher in (mock.patch.dict(os.environ, {"PKEXEC_UID": str(users.get(caller, ""))}),
                        mock.patch.object(helper.os, "geteuid", return_value=0),
                        mock.patch.object(helper.pwd, "getpwnam", side_effect=getpwnam),
                        mock.patch.object(helper.pwd, "getpwuid", side_effect=lambda uid: getpwnam(by_uid[uid])),
                        mock.patch.object(helper.grp, "getgrnam", side_effect=getgrnam),
                        mock.patch.object(helper, "LOGIN_DEFS", os.path.join(self.tmp, "none")),
                        mock.patch.object(helper, "logged_in", return_value=False),
                        mock.patch.object(helper.subprocess, "run", side_effect=run),
                        mock.patch("sys.stdout"), mock.patch("sys.stderr")):
            patcher.start()
            self.addCleanup(patcher.stop)
        return runs

    def test_user_add(self):
        runs = self.account_mocks({"jon": 1000}, ["jon"])
        with mock.patch("sys.stdin", io.StringIO("pass:word 1\nignored\n")):
            self.assertEqual(helper.main(["user-add", "ann", "Ann Lee", "yes"]), 0)
        groups = "cdrom,floppy,audio,dip,video,plugdev,netdev,lpadmin,bluetooth,sudo"
        self.assertEqual(runs, [(["adduser", "--quiet", "--disabled-password", "--comment", "Ann Lee", "ann"], None),
                                (["chpasswd"], "ann:pass:word 1\n"),
                                (["usermod", "--append", "--groups", groups, "ann"], None)])
        runs.clear()
        with mock.patch("sys.stdin", io.StringIO("secret")):
            self.assertEqual(helper.main(["user-add", "bob", "", "no"]), 0)
        self.assertNotIn("sudo", runs[-1][0][3])

    def test_user_add_refuses_bad_input_before_changing_anything(self):
        runs = self.account_mocks({"jon": 1000}, ["jon"])
        for args, stdin in ((["jon", "Jon", "no"], "secret\n"), (["Ann", "Ann", "no"], "secret\n"),
                            (["-ann", "Ann", "no"], "secret\n"), (["ann", "Ann, Lee", "no"], "secret\n"),
                            (["ann", "Ann", "maybe"], "secret\n"), (["ann", "Ann", "no"], "\n"),
                            (["ann", "Ann", "no"], ""), (["ann", "Ann"], "secret\n")):
            with mock.patch("sys.stdin", io.StringIO(stdin)):
                self.assertEqual(helper.main(["user-add", *args]), 1, args)
        self.assertEqual(runs, [])

    def test_user_add_is_undone_when_the_password_fails(self):
        runs = self.account_mocks({"jon": 1000}, ["jon"])
        failing = helper.subprocess.run.side_effect

        def run(cmd, **kw):
            failing(cmd, **kw)
            return subprocess.CompletedProcess(cmd, 1 if cmd[0] == "chpasswd" else 0, "", "chpasswd: broken")

        with mock.patch.object(helper.subprocess, "run", side_effect=run), \
             mock.patch("sys.stdin", io.StringIO("secret\n")):
            self.assertEqual(helper.main(["user-add", "ann", "", "no"]), 1)
        self.assertEqual([cmd for cmd, _ in runs][-1], ["userdel", "--remove", "ann"])

    def test_user_remove(self):
        runs = self.account_mocks({"jon": 1000, "ann": 1001, "root": 0}, ["jon"], caller="jon")
        self.assertEqual(helper.main(["user-remove", "ann", "delete"]), 0)
        self.assertEqual(helper.main(["user-remove", "ann", "keep"]), 0)
        self.assertEqual(runs, [(["userdel", "--remove", "ann"], None), (["userdel", "ann"], None)])
        runs.clear()
        for args in (["jon", "keep"], ["root", "keep"], ["bob", "keep"], ["ann", "all"], ["ann"]):
            self.assertEqual(helper.main(["user-remove", *args]), 1, args)
        with mock.patch.object(helper, "logged_in", return_value=True):
            self.assertEqual(helper.main(["user-remove", "ann", "keep"]), 1)
        self.assertEqual(runs, [])

    def test_user_remove_says_when_the_account_is_gone_but_its_files_are_not(self):
        users = {"jon": 1000, "ann": 1001}
        self.account_mocks(users, ["jon"], caller="jon")

        def userdel(cmd, **kw):
            del users["ann"]
            return subprocess.CompletedProcess(cmd, 12, "", "userdel: /home/ann not owned by ann, not removing")

        with mock.patch.object(helper.subprocess, "run", side_effect=userdel), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(helper.main(["user-remove", "ann", "delete"]), 1)
        self.assertEqual(stderr.getvalue(), "control-helper: ann was removed, but not all of their files:\n"
                                            "userdel: /home/ann not owned by ann, not removing\n")

    def test_the_last_administrator_stays(self):
        runs = self.account_mocks({"jon": 1000, "ann": 1001}, ["ann"], caller="jon")
        self.assertEqual(helper.main(["user-remove", "ann", "keep"]), 1)
        self.assertEqual(helper.main(["user-admin", "ann", "no"]), 1)
        self.assertEqual(helper.main(["user-admin", "jon", "yes"]), 0)
        self.assertEqual(helper.main(["user-admin", "jon", "no"]), 0)      # not a member: nothing to do
        self.assertEqual(helper.main(["user-admin", "jon", "maybe"]), 1)
        self.assertEqual([cmd for cmd, _ in runs], [["gpasswd", "-a", "jon", "sudo"]])

    def test_user_password(self):
        runs = self.account_mocks({"jon": 1000, "root": 0}, ["jon"])
        with mock.patch("sys.stdin", io.StringIO("new secret\n")):
            self.assertEqual(helper.main(["user-password", "jon"]), 0)
        with mock.patch("sys.stdin", io.StringIO("new secret\n")):
            self.assertEqual(helper.main(["user-password", "root"]), 1)
        with mock.patch("sys.stdin", io.StringIO("line\rbreak\n")):
            self.assertEqual(helper.main(["user-password", "jon"]), 1)
        self.assertEqual(runs, [(["chpasswd"], "jon:new secret\n")])

    def test_firewall(self):
        runs = []
        ufw = os.path.join(self.tmp, "ufw")
        open(ufw, "w").close()
        with mock.patch.object(helper, "UFW", ufw), mock.patch.object(helper.os, "geteuid", return_value=0), \
             mock.patch.object(helper.subprocess, "run",
                               side_effect=lambda cmd, **kw: runs.append(cmd) or
                               subprocess.CompletedProcess(cmd, 0, "", "")), mock.patch("sys.stdout"):
            self.assertEqual(helper.main(["firewall-on"]), 0)
            self.assertEqual(helper.main(["firewall-off"]), 0)
            with mock.patch("sys.stderr"):
                self.assertEqual(helper.main(["firewall-on", "allow", "22"]), 1)
        self.assertEqual(runs, [[ufw, "--force", "enable"], [ufw, "disable"]])
        with mock.patch.object(helper, "UFW", os.path.join(self.tmp, "none")):
            with self.assertRaisesRegex(helper.HelperError, "not installed"):
                helper.cmd_firewall_on([])

    def test_power(self):
        drop_in = os.path.join(self.tmp, "logind.conf.d", "60-flickos.conf")
        runs = []
        with mock.patch.object(helper, "LOGIND_DROP_IN", drop_in), \
             mock.patch.object(helper.os, "geteuid", return_value=0), \
             mock.patch.object(helper.subprocess, "run",
                               side_effect=lambda cmd, **kw: runs.append(cmd) or
                               subprocess.CompletedProcess(cmd, 0, "", "")), mock.patch("sys.stdout"):
            self.assertEqual(helper.main(["power", "lid", "lock"]), 0)
            self.assertEqual(helper.main(["power", "power-key", "suspend"]), 0)
            self.assertEqual(helper.main(["power", "lid", "ignore"]), 0)
            with open(drop_in) as f:
                self.assertEqual(f.read(), helper.LOGIND_HEADER + "HandlePowerKey=suspend\nHandleLidSwitch=ignore\n")
            with mock.patch("sys.stderr"):
                for args in (["lid", "reboot"], ["lid"], ["HandleLidSwitch", "ignore"], ["lid", "ignore\nx=y"]):
                    self.assertEqual(helper.main(["power", *args]), 1, args)
            self.assertEqual(helper.main(["power", "lid", "default"]), 0)
            self.assertEqual(helper.main(["power", "power-key", "default"]), 0)
        self.assertFalse(os.path.exists(drop_in))
        self.assertEqual(runs, [["systemctl", "reload", "systemd-logind"]] * 5)

    def test_locale_add(self):
        supported = os.path.join(self.tmp, "SUPPORTED")
        with open(supported, "w") as f:
            f.write(SUPPORTED)
        locale_gen = os.path.join(self.tmp, "locale.gen")
        with open(locale_gen, "w") as f:
            f.write("# This file lists locales\n# de_DE ISO-8859-1\n# de_DE.UTF-8 UTF-8\nen_US.UTF-8 UTF-8\n")
        runs = []
        with mock.patch.object(helper, "I18N_SUPPORTED", supported), mock.patch.object(helper, "LOCALE_GEN", locale_gen), \
             mock.patch.object(helper.os, "geteuid", return_value=0), \
             mock.patch.object(helper.subprocess, "run",
                               side_effect=lambda cmd, **kw: runs.append(cmd) or
                               subprocess.CompletedProcess(cmd, 0, "", "")), mock.patch("sys.stdout"):
            self.assertEqual(helper.main(["locale-add", "de_DE.UTF-8"]), 0)
            self.assertEqual(helper.main(["locale-add", "fil_PH"]), 0)
            with mock.patch("sys.stderr"):
                for args in (["de_DE"], ["xx_YY.UTF-8"], ["C.UTF-8 UTF-8"], []):
                    self.assertEqual(helper.main(["locale-add", *args]), 1, args)
        with open(locale_gen) as f:
            self.assertEqual(f.read(), "# This file lists locales\n# de_DE ISO-8859-1\nde_DE.UTF-8 UTF-8\n"
                                       "en_US.UTF-8 UTF-8\nfil_PH UTF-8\n")
        self.assertEqual([list(cmd) for cmd in runs], [list(helper.LOCALE_GEN_COMMAND)] * 2)
        self.assertIsNone(helper.enable_locale("en_US.UTF-8 UTF-8\n", "en_US.UTF-8"))

    def test_updates(self):
        drop_in = os.path.join(self.tmp, "60flickos-updates")
        with mock.patch.object(helper, "UPDATES_DROP_IN", drop_in), \
             mock.patch.object(helper.os, "geteuid", return_value=0), mock.patch("sys.stdout"):
            self.assertEqual(helper.main(["updates", "scope", "all"]), 0)
            self.assertEqual(helper.main(["updates", "reboot", "idle"]), 0)
            self.assertEqual(helper.main(["updates", "auto", "no"]), 0)
            with open(drop_in) as f:
                text = f.read()
            self.assertEqual(helper.updates_choices(text), {"scope": "all", "reboot": "idle", "auto": "no"})
            self.assertIn('APT::Periodic::Unattended-Upgrade "0";\n#clear Unattended-Upgrade::Origins-Pattern;\n',
                          text)
            self.assertIn('"origin=FlickOS,codename=${distro_codename},label=FlickOS";', text)
            self.assertIn('Unattended-Upgrade::Automatic-Reboot-WithUsers "false";', text)
            with mock.patch("sys.stderr"):
                for args in (["auto", "maybe"], ["reboot", "always"], ["scope", "everything"], ["auto"],
                             ["Unattended-Upgrade::Mail", "root"]):
                    self.assertEqual(helper.main(["updates", *args]), 1, args)
            for setting in ("scope", "reboot", "auto"):
                self.assertEqual(helper.main(["updates", setting, "default"]), 0)
        self.assertFalse(os.path.exists(drop_in))

    def test_updates_refresh(self):
        """An upgrade writes a stored choice again with this version's origins."""
        drop_in = os.path.join(self.tmp, "60flickos-updates")
        with mock.patch.object(helper, "UPDATES_DROP_IN", drop_in), \
             mock.patch.object(helper.os, "geteuid", return_value=0), mock.patch("sys.stdout"):
            self.assertEqual(helper.main(["updates", "refresh"]), 0)
            self.assertFalse(os.path.exists(drop_in))
            current = helper.updates_text({"scope": "debian", "reboot": "idle"})
            with open(drop_in, "w") as f:
                f.write(current.replace(f'        "{helper.UPDATE_SCOPES["debian"][-1]}";\n', ""))
            self.assertEqual(helper.main(["updates", "refresh"]), 0)
            with open(drop_in) as f:
                self.assertEqual(f.read(), current)
            self.assertIn("FlickOS Community", current)
            # Not FlickOS's (no mark line): left as it is.
            with open(drop_in, "w") as f:
                f.write('Unattended-Upgrade::Origins-Pattern { "origin=Debian"; };\n')
            self.assertEqual(helper.main(["updates", "refresh"]), 0)
            with open(drop_in) as f:
                self.assertEqual(f.read(), 'Unattended-Upgrade::Origins-Pattern { "origin=Debian"; };\n')

    @unittest.skipUnless(shutil.which("apt-config"), "apt-config is not installed")
    def test_updates_as_apt_reads_them(self):
        """The drop-in after Debian's files, read by apt-config and the page."""
        parts = os.path.join(self.tmp, "apt.conf.d")
        os.makedirs(parts)
        with open(os.path.join(parts, "20auto-upgrades"), "w") as f:
            f.write('APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n')
        with open(os.path.join(parts, "50unattended-upgrades"), "w") as f:
            f.write("Unattended-Upgrade::Origins-Pattern {\n" + "".join(
                f'        "{p}";\n' for p in fc.OLD_UPDATE_SCOPES["debian-only"]) + "};\n")
        if os.path.exists(KEYRING_ORIGINS):
            shutil.copy(KEYRING_ORIGINS, parts)
        else:
            with open(os.path.join(parts, "51flickos-origins"), "w") as f:
                f.write('Unattended-Upgrade::Origins-Pattern {\n'
                        '        "origin=FlickOS,codename=${distro_codename},label=FlickOS";\n};\n')
        config = os.path.join(self.tmp, "apt.conf")
        with open(config, "w") as f:
            f.write(f'Dir::Etc::parts "{parts}";\n')

        def state():
            dump = subprocess.run(["apt-config", "dump"], env=dict(os.environ, APT_CONFIG=config),
                                  capture_output=True, text=True, check=True).stdout
            return fc.updates_state(dump, "/nonexistent")

        self.assertEqual(state(), {"auto": True, "scope": "debian", "reboot": "no", "last": None})
        for choices, expected in (({"auto": "no"}, {"auto": False}), ({"scope": "security"}, {"scope": "security"}),
                                  ({"scope": "debian"}, {}),
                                  ({"scope": "all", "reboot": "idle"}, {"scope": "all", "reboot": "idle"})):
            with open(os.path.join(parts, "60flickos-updates"), "w") as f:
                f.write(helper.updates_text(choices))
            self.assertEqual(state(), dict({"auto": True, "scope": "debian", "reboot": "no", "last": None},
                                           **expected), choices)

    def test_logged_in_looks_at_process_owners(self):
        proc = os.path.join(self.tmp, "proc")
        os.makedirs(os.path.join(proc, "1"))
        os.makedirs(os.path.join(proc, "self"))
        with mock.patch.object(helper, "PROC", proc):
            self.assertTrue(helper.logged_in(os.getuid()))
            self.assertFalse(helper.logged_in(os.getuid() + 1))

    @unittest.skipUnless(os.path.exists(INSTALLER_USERS), "flickos-installer is not next to this package")
    def test_new_accounts_get_the_installers_groups(self):
        with open(INSTALLER_USERS) as f:
            text = f.read()
        section = re.split(r"\n\S", text.split("defaultGroups:", 1)[1], maxsplit=1)[0]
        groups = re.findall(r"^ +- (\S+)", section, re.M)
        self.assertEqual(list(helper.DEFAULT_GROUPS), [g for g in groups if g != helper.ADMIN_GROUP])
        self.assertIn(f"sudoersGroup:    {helper.ADMIN_GROUP}", text)

    def test_the_policy_has_an_action_per_verb(self):
        top = ET.parse(os.path.join(PACKAGE, "usr/share/polkit-1/actions/org.flickos.control.policy")).getroot()
        argv1 = {a.find("annotate[@key='org.freedesktop.policykit.exec.argv1']").text for a in top.iter("action")}
        self.assertEqual(argv1, set(helper.VERBS) - set(helper.READ_ONLY))
        for action in top.iter("action"):
            self.assertEqual(action.find("annotate[@key='org.freedesktop.policykit.exec.path']").text,
                             "/usr/libexec/flickos/control-helper")


if __name__ == "__main__":
    unittest.main()


TILER_PACKAGE = os.path.join(PACKAGE, "../flick-tiler")


class HistoryTest(SettingsTest):
    """Settings > History: recording flickos-control's own changes, reading
    and shaping everyone's, and undoing (docs/design/flickos-history.md)."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.tmp, "state")})
        env.start()
        self.addCleanup(env.stop)
        # Not the build machine's apt log (SystemHistoryTest tests software changes).
        software = mock.patch.object(fc, "software_changes", return_value=[])
        software.start()
        self.addCleanup(software.stop)
        self.history = os.path.join(self.tmp, "state/flickos/history.jsonl")
        self.clock = 1_790_000_000

    def entries(self):
        return [(e["owner"], e["key"], e["old"], e["new"]) for e in fc.read_history()]

    def entry(self, key, old, new, seconds, owner=fc.HISTORY_OWNER):
        """An entry `seconds` after self.clock, as the owners write them."""
        when = datetime.datetime.fromtimestamp(self.clock + seconds).astimezone()
        return {"v": 1, "id": str((self.clock + seconds) * 10**9), "time": when.isoformat(timespec="seconds"),
                "owner": owner, "key": key, "old": old, "new": new}

    def write_history(self, *entries, extra=""):
        os.makedirs(os.path.dirname(self.history), exist_ok=True)
        with open(self.history, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(e) + "\n" for e in entries) + extra)

    def changes(self, *entries, days=None):
        self.write_history(*entries)
        return fc.shape_history(fc.read_history(), days=days)

    # Recording.

    def test_set_records_changes_that_show(self):
        self.set("touchpad.tap", "no")
        self.set("touchpad.tap", "no")                      # no change
        self.set("mouse.pointer-speed", "default")          # it was the default already
        self.set("touchpad.tap", "yes")
        self.set("keyboard.repeat-delay", "400")
        self.assertEqual(self.entries(), [
            ("flickos-control", "touchpad.tap", "default", "no"),
            ("flickos-control", "touchpad.tap", "no", "yes"),
            ("flickos-control", "keyboard.repeat-delay", "default", "400"),
        ])
        self.assertEqual(os.stat(self.history).st_mode & 0o777, 0o600)

    def test_a_removed_value_is_recorded_as_default(self):
        self.write("rules", "")
        with mock.patch.object(fc, "check_xkb", side_effect=lambda key, value, values, rules: {key: value}):
            self.set("keyboard.layout", "de")
        self.set("keyboard.layout", "default")
        self.assertEqual(self.entries()[-2:], [("flickos-control", "keyboard.layout", "default", "de"),
                                               ("flickos-control", "keyboard.layout", "de", "default")])

    def test_turning_it_off_clears_it_and_stops_recording(self):
        self.set("touchpad.tap", "no")
        status, out = self.set("history.enabled", "no")
        self.assertEqual((status, out.strip()), (0, "History turned off and cleared."))
        self.assertFalse(os.path.exists(self.history))
        self.set("touchpad.tap", "yes")
        self.assertEqual(self.entries(), [])
        self.set("history.enabled", "yes")
        self.set("touchpad.tap", "no")
        self.assertEqual(self.entries(), [("flickos-control", "touchpad.tap", "yes", "no")])

    def test_the_system_can_turn_it_off(self):
        self.write("etc/history.conf", "[History]\nEnabled=no\n")
        self.set("touchpad.tap", "no")
        self.assertEqual(self.entries(), [])

    # Reading and shaping.

    def test_unreadable_lines_are_left_out(self):
        good = self.entry("touchpad.tap", "default", "no", 0)
        self.write_history(dict(good, v=2), dict(good, id="x"), dict(good, time="yesterday"),
                           {k: v for k, v in good.items() if k != "new"}, good,
                           extra='{"v": 1, "id": "17900')     # half a line: the power went off
        self.assertEqual(self.entries(), [("flickos-control", "touchpad.tap", "default", "no")])
        self.assertEqual(fc.read_history(os.path.join(self.tmp, "none")), [])

    def test_changes_close_together_are_one(self):
        changes = self.changes(
            self.entry("mouse.pointer-speed", "default", "0.20", 0),
            self.entry("mouse.pointer-speed", "0.20", "0.40", 60),
            self.entry("touchpad.tap", "default", "no", 90),         # another setting in between
            self.entry("mouse.pointer-speed", "0.40", "0.60", 170),
            self.entry("mouse.pointer-speed", "0.60", "0.30", 400),   # later: a change of its own
        )
        # In the order of their last entries.
        self.assertEqual([(c.key, c.old, c.new) for c in changes], [
            ("mouse.pointer-speed", "0.60", "0.30"),
            ("mouse.pointer-speed", "default", "0.60"),
            ("touchpad.tap", "default", "no"),
        ])
        self.assertEqual(changes[1].id, str((self.clock + 170) * 10**9))
        self.assertEqual([(c.newest, c.undoable) for c in changes], [(True, True), (False, False), (True, True)])

    def test_a_change_that_ends_where_it_started_is_left_out(self):
        changes = self.changes(self.entry("enabled", "off", "on", 0, owner="flick-tiler"),
                               self.entry("enabled", "on", "off", 5, owner="flick-tiler"))
        self.assertEqual(changes, [])

    def test_old_changes_and_unknown_settings(self):
        changes = self.changes(self.entry("clock", "default", "12h", 0, owner="flickos-layout"),
                               self.entry("brightness", "50", "80", 1000, owner="flickos-brightness"),
                               self.entry("history.enabled", "yes", "no", 2000))
        self.assertEqual([(c.key, c.undoable) for c in changes],
                         [("history.enabled", False), ("brightness", False), ("clock", True)])
        now = datetime.datetime.fromtimestamp(self.clock + 91 * 86400).astimezone()
        self.assertEqual(fc.shape_history(fc.read_history(), now=now), [])
        self.assertEqual(len(fc.shape_history(fc.read_history(), now=now, days=92)), 3)

    # Undoing.

    def test_undo_commands(self):
        change = lambda owner, key, old, new: fc.Change("1", None, owner, key, old, new)
        self.assertEqual(fc.undo_commands(change("flickos-control", "touchpad.tap", "default", "no")),
                         [[*fc.SELF, "set", "touchpad.tap", "default"]])
        self.assertEqual(fc.undo_commands(change("flickos-layout", "layout", "redmond", "cupertino")),
                         [["flickos-layout", "set", "redmond"]])
        self.assertEqual(fc.undo_commands(change("flickos-layout", "menu-style", "default", "grid")),
                         [["flickos-layout", "menu-style", "set", "default"]])
        self.assertEqual(fc.undo_commands(change("flickos-layout", "quick-settings", "default", "on")),
                         [["flickos-layout", "quick-settings", "set", "default"]])
        self.assertEqual(fc.undo_commands(change("flick-tiler", "enabled", "off", "on")),
                         [["flick-tiler", "off"]])
        self.assertEqual(fc.undo_commands(change("flick-tiler", "ratio", "55", "70")),
                         [["flick-tiler", "ratio", "55"]])
        self.assertEqual(fc.undo_commands(change("flick-tiler", "floating", "a b", "a C d")),
                         [["flick-tiler", "floating", "remove", "C"], ["flick-tiler", "floating", "remove", "d"],
                          ["flick-tiler", "floating", "add", "b"]])
        with self.assertRaises(fc.ControlError):
            fc.undo_commands(change("flickos-control", "history.enabled", "yes", "no"))
        # Every setting History names, it can undo.
        for owner, key in fc.HISTORY_LABELS:
            self.assertTrue(fc.can_undo(change(owner, key, "1", "2")), (owner, key))
        self.assertEqual({key for owner, key in fc.HISTORY_LABELS if owner == fc.HISTORY_OWNER},
                         {key for key in fc.SETTINGS if key != "history.enabled"})

    def test_undo_puts_the_old_value_back(self):
        self.set("touchpad.tap", "no")
        self.set("touchpad.natural-scroll", "yes")
        [_, tap] = fc.shape_history(fc.read_history())
        status, _ = self.undo(tap.id)
        self.assertEqual(status, 0)
        self.assertEqual(fc.read_values(fc.user_file("input"))["touchpad.tap"], "yes")     # the default, stored
        # Undone right away: the change and its undo cancel out.
        self.assertEqual([c.key for c in fc.shape_history(fc.read_history())], ["touchpad.natural-scroll"])

    def test_a_later_undo_is_a_change_of_its_own(self):
        self.set("keyboard.repeat-delay", "400")
        self.write_history(self.entry("keyboard.repeat-delay", "default", "400", 0))     # long ago
        [change] = fc.shape_history(fc.read_history(), days=None)
        self.assertEqual(self.undo(change.id)[0], 0)
        [undo, change] = fc.shape_history(fc.read_history(), days=None)
        self.assertEqual((undo.old, undo.new, undo.newest, change.newest), ("400", "600", True, False))
        self.assertEqual(self.undo(undo.id)[0], 0)          # and can be undone too
        self.assertEqual(fc.read_values(fc.user_file("keyboard"))["keyboard.repeat-delay"], "400")

    def test_undo_refuses(self):
        self.set("touchpad.tap", "no")
        first = fc.shape_history(fc.read_history())[0]
        with mock.patch.object(fc, "time") as clock:
            clock.time_ns.return_value = int(first.id) + (fc.MERGE_SECONDS + 1) * 10**9
            self.set("touchpad.tap", "yes")
        with self.assertRaisesRegex(fc.ControlError, "changed again since"):
            fc.find_change(first.id, fc.shape_history(fc.read_history()))
        with self.assertRaisesRegex(fc.ControlError, "no change 42"):
            fc.find_change("42", fc.shape_history(fc.read_history()))
        # Edited by hand after the change: nothing is undone.
        newest = fc.shape_history(fc.read_history())[0]
        self.write("config/flickos/input", "[Touchpad]\nTap=no\n")
        with self.assertRaisesRegex(fc.ControlError, "without FlickOS"):
            fc.find_change(newest.id, fc.shape_history(fc.read_history()))
        with mock.patch.object(fc, "warn") as warn:
            self.assertEqual(fc.main(["history", "undo", newest.id]), 1)
        self.assertIn("without FlickOS", warn.call_args.args[0])

    def undo(self, change_id):
        """`history undo`, running flickos-control's own commands in this process."""
        def run(command, **_kwargs):
            self.assertEqual(command[:2], fc.SELF)
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                code = fc.main(command[2:])
            return subprocess.CompletedProcess(command, code, out.getvalue(), "")

        with mock.patch.object(fc.subprocess, "run", side_effect=run), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            status = fc.main(["history", "undo", change_id])
        return status, out.getvalue()

    # Words.

    def test_describe(self):
        names = {("flickos-layout", "layout"): {"redmond": "Redmond", "cupertino": "Cupertino"},
                 ("flick-tiler", "mode"): {"grid": "Grid"}}
        change = lambda owner, key, old, new: fc.describe(fc.Change("1", None, owner, key, old, new), names)
        self.assertEqual(change("flickos-layout", "layout", "redmond", "cupertino"),
                         ("Desktop layout: Cupertino", "Was Redmond"))
        self.assertEqual(change("flickos-layout", "layout", "cupertino", "default"),
                         ("Desktop layout: the default", "Was Cupertino"))
        self.assertEqual(change("flickos-control", "touchpad.tap", "default", "no"),
                         ("Tap to click: off", "Was the default"))
        self.assertEqual(change("flickos-control", "idle.lock-after", "300", "0"),
                         ("Lock the screen after: Never", "Was 5 minutes"))
        self.assertEqual(change("flickos-control", "lock.background", "color", "wallpaper"),
                         ("Lock screen background: The wallpaper", "Was Dark color"))
        self.assertEqual(change("flickos-control", "night-light.temperature", "4000", "2700"),
                         ("Night light warmth: Very strong", "Was Medium"))
        self.assertEqual(change("flick-tiler", "enabled", "off", "on"), ("Tiling: on", "Was off"))
        self.assertEqual(change("flick-tiler", "mode", "default", "grid"), ("Tiling arrangement: Grid",
                                                                            "Was the default"))
        self.assertEqual(change("flick-tiler", "ratio", "55", "70"), ("Main window width: 70 %", "Was 55 %"))
        self.assertEqual(change("flick-tiler", "floating", "a b", "a c"),
                         ("Apps that always float: c added; b removed", ""))
        self.assertEqual(change("flickos-brightness", "level", "50", "80"),
                         ("flickos-brightness level: 80", "Was 50"))

    def test_list_command(self):
        self.write_history(self.entry("touchpad.tap", "default", "no", 0),
                           self.entry("clock", "default", "12h", 1000, owner="flickos-layout"))
        with mock.patch.object(fc, "history_names", return_value={}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fc.main(["history", "--days", "100000"]), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual([line.split("\t")[0] for line in lines],
                         [str((self.clock + 1000) * 10**9), str(self.clock * 10**9)])
        self.assertEqual(lines[1].split("\t")[2:], ["undo", "Tap to click: off (was the default)"])
        with mock.patch.object(fc, "history_names", return_value={}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            fc.main(["history", "--days", "100000", "--json"])
        self.assertEqual(json.loads(out.getvalue())[0]["text"], "Time format: 12h")
        with mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["history", "undo"]), 2)
            self.assertEqual(fc.main(["history", "clear", "1"]), 2)
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(fc.main(["history", "clear"]), 0)
        self.assertEqual(fc.read_history(), [])

    # The other programs write what this one reads.

    def other_program(self, package, program, *args, prefix_variable):
        env = dict(os.environ, XDG_CONFIG_HOME=os.path.join(self.tmp, "config"), **{
            prefix_variable: os.path.abspath(package), "XDG_RUNTIME_DIR": self.run_dir})
        return subprocess.run([sys.executable, os.path.join(package, "usr/bin", program), *args],
                              env=env, capture_output=True, text=True, timeout=30, check=False)

    @unittest.skipUnless(os.path.isdir(LAYOUTS_PACKAGE), "flickos-layouts is not next to this package")
    def test_flickos_layout_writes_what_this_reads(self):
        # It saves and records even where it can't apply (no FlickOS here: exit code 1).
        result = self.other_program(LAYOUTS_PACKAGE, "flickos-layout", "clock", "set", "12h",
                                    prefix_variable="FLICKOS_LAYOUT_PREFIX")
        self.assertEqual(len(fc.read_history()), 1, result.stderr)
        [change] = fc.shape_history(fc.read_history())
        self.assertEqual((change.owner, change.key, change.old, change.new, change.undoable),
                         ("flickos-layout", "clock", "default", "12h", True))

    @unittest.skipUnless(os.path.isdir(TILER_PACKAGE), "flick-tiler is not next to this package")
    def test_flick_tiler_writes_what_this_reads(self):
        result = self.other_program(TILER_PACKAGE, "flick-tiler", "gap", "4", prefix_variable="FLICK_TILER_PREFIX")
        self.assertEqual(len(fc.read_history()), 1, result.stderr)
        [change] = fc.shape_history(fc.read_history())
        self.assertEqual((change.owner, change.key, change.old, change.new, change.undoable),
                         ("flick-tiler", "gap", "default", "4", True))


APT_LOG = """Start-Date: 2026-08-22  15:06:55
Commandline: apt-get -y install grub-efi
Requested-By: jon (1000)
Install: grub-efi:amd64 (2.12-9)
End-Date: 2026-08-22  15:06:58

Start-Date: 2026-08-22  15:07:17
Commandline: apt-get --purge -q -y remove live-boot flickos-installer calamares
Requested-By: jon (1000)
Purge: live-boot:amd64 (1:20250815), flickos-installer:amd64 (1.18), calamares:amd64 (3.3.14-1)
End-Date: 2026-08-22  15:07:20

Start-Date: 2026-08-22  15:07:25
Commandline: apt-get --purge -q -y autoremove
Requested-By: jon (1000)
Purge: task-english:amd64 (3.81)
End-Date: 2026-08-22  15:07:30

Start-Date: 2026-09-03  12:19:54
Commandline: apt install adb
Requested-By: jon (1000)
Install: android-liblog:amd64 (1:34.0.5-12, automatic), adb:amd64 (1:34.0.5-12), zlib1g:i386 (1:1.3, automatic)
Upgrade: libc6:amd64 (2.41-12, 2.41-13)
End-Date: 2026-09-03  12:20:00

Start-Date: 2026-09-03  13:10:03
Commandline: apt remove adb
Requested-By: jon (1000)
Remove: adb:amd64 (1:34.0.5-12)
End-Date: 2026-09-03  13:10:06

Start-Date: 2026-09-08  09:45:49
Commandline: packagekit role='update-packages'
Requested-By: jon (1000)
Upgrade: firefox-esr:amd64 (140.14.0esr-1, 140.15.0esr-1), fonts-noto:all (1, 2)
End-Date: 2026-09-08  09:46:30

Start-Date: 2026-09-09  10:00:00
Commandline: apt-get -y -q -o FlickOS::Undo=2026-09-03T13:10:03 install adb
Install: adb:amd64 (1:34.0.5-12)
End-Date: 2026-09-09  10:00:05

Start-Date: 2026-09-10  10:00:00
Commandline: apt autoremove
Requested-By: jon (1000)
Remove: android-liblog:amd64 (1:34.0.5-12)
End-Date: 2026-09-10  10:00:05

Start-Date: 2026-09-11  10:00:00
Commandline: apt install foo
Requested-By: jon (1000)
Install: foo:amd64 (1)
Remove: bar:amd64 (2)
End-Date: 2026-09-11  10:00:05

Start-Date: 2026-09-12  1
"""


class SoftwareHelperTest(unittest.TestCase):
    """control-helper packages-list|plan|undo: apt's log, checked undo."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-control-apt-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.log = os.path.join(self.tmp, "history.log")
        with open(self.log, "w") as f:
            f.write(APT_LOG)
        self.cmdline = os.path.join(self.tmp, "cmdline")
        with open(self.cmdline, "w") as f:
            f.write("BOOT_IMAGE=/vmlinuz quiet splash\n")
        for name, value in (("APT_LOG", self.log), ("CMDLINE", self.cmdline)):
            patcher = mock.patch.object(helper, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(helper, "native_arch", return_value="amd64")
        patcher.start()
        self.addCleanup(patcher.stop)

    def transaction(self, transaction_id):
        return next(t for t in helper.read_apt_log() if t["id"] == transaction_id)

    def test_parse(self):
        transactions = helper.read_apt_log()
        self.assertEqual(len(transactions), 9)                  # the cut-off last one is left out
        adb = self.transaction("2026-09-03T12:19:54")
        self.assertEqual(adb["command"], "apt install adb")
        self.assertEqual(adb["lists"]["Install"][1], ("adb", "amd64", "1:34.0.5-12"))
        self.assertEqual(adb["lists"]["Upgrade"], [("libc6", "amd64", "2.41-12, 2.41-13")])

    def test_rotated_logs_are_read_oldest_first(self):
        for number, day in ((2, "01"), (1, "02")):
            with gzip.open(f"{self.log}.{number}.gz", "wt") as f:
                f.write(f"Start-Date: 2026-07-{day}  10:00:00\nCommandline: apt install x{number}\n"
                        f"Install: x{number}:amd64 (1)\nEnd-Date: 2026-07-{day}  10:00:01\n")
        ids = [t["id"] for t in helper.read_apt_log()]
        self.assertEqual(ids[:3], ["2026-07-01T10:00:00", "2026-07-02T10:00:00", "2026-08-22T15:06:55"])

    def test_the_installation_is_left_out(self):
        ids = [t["id"] for t in helper.after_installation(helper.read_apt_log(), live=False)]
        self.assertEqual(ids[0], "2026-09-03T12:19:54")         # after the installer's autoremove
        self.assertEqual(len(ids), 6)
        # In the live session: everything since it started (its log has the image's build).
        with mock.patch.object(helper, "boot_time", return_value=datetime.datetime(2026, 9, 9, 9)):
            ids = [t["id"] for t in helper.after_installation(helper.read_apt_log(), live=True)]
        self.assertEqual(ids, ["2026-09-09T10:00:00", "2026-09-10T10:00:00", "2026-09-11T10:00:00"])
        with open(self.cmdline, "w") as f:
            f.write("boot=live quiet\n")
        self.assertTrue(helper.live_system())

    def test_what_each_transaction_did(self):
        change = lambda tid: helper.describe_transaction(self.transaction(tid), "amd64")
        install = change("2026-09-03T12:19:54")
        self.assertEqual((install["kind"], install["packages"], install["automatic"], install["upgraded"],
                          install["undoable"]), ("install", ["adb"], ["android-liblog", "zlib1g:i386"], 1, True))
        remove = change("2026-09-03T13:10:03")
        self.assertEqual((remove["kind"], remove["packages"], remove["purged"], remove["undoable"]),
                         ("remove", ["adb"], False, True))
        update = change("2026-09-08T09:45:49")
        self.assertEqual((update["kind"], update["upgraded"], update["undoable"]), ("update", 2, False))
        self.assertIn("newest version", update["why"])
        self.assertEqual(change("2026-09-09T10:00:00")["undo_of"], "2026-09-03T13:10:03")
        autoremove = change("2026-09-10T10:00:00")
        self.assertEqual((autoremove["autoremove"], autoremove["undoable"]), (True, False))
        mixed = change("2026-09-11T10:00:00")
        self.assertEqual((mixed["kind"], mixed["undoable"]), ("mixed", False))

    def test_list(self):
        changes = helper.software_changes(days=30, live=False, now=datetime.datetime(2026, 9, 20))
        self.assertEqual([c["id"] for c in changes][:2], ["2026-09-03T12:19:54", "2026-09-03T13:10:03"])
        self.assertEqual(len(helper.software_changes(days=5, live=False, now=datetime.datetime(2026, 9, 12))), 4)

    def plan(self, tid, installed, simulations, protected=frozenset()):
        results = iter(simulations)
        calls = []

        def simulate(args):
            calls.append(args)
            return next(results)

        plan = helper.undo_plan(self.transaction(tid), simulate=simulate,
                                installed=lambda names: set(names) & set(installed), protected=lambda: protected)
        return plan, calls

    def test_undo_an_install(self):
        # What it brought in goes too, named (never --autoremove: that takes everything unneeded).
        plan, calls = self.plan("2026-09-03T12:19:54", {"adb", "android-liblog", "zlib1g:i386"},
                                [({"adb", "android-liblog", "zlib1g:i386"}, set())])
        self.assertEqual(calls, [["remove", "adb", "android-liblog", "zlib1g:i386"]])
        self.assertEqual((plan["action"], plan["remove"], plan["upgraded"]),
                         ("remove", ["adb", "android-liblog", "zlib1g:i386"], 1))
        # Another package needs one of them: only what was asked for goes.
        plan, calls = self.plan("2026-09-03T12:19:54", {"adb", "android-liblog"},
                                [({"adb", "android-liblog", "fastboot"}, set()), ({"adb"}, set())])
        self.assertEqual((calls[1], plan["args"]), (["remove", "adb"], ["remove", "adb"]))
        # Even that would take something else: refused, named.
        with self.assertRaisesRegex(helper.HelperError, "also remove fastboot"):
            self.plan("2026-09-03T12:19:54", {"adb"}, [({"adb", "fastboot"}, set()), ({"adb", "fastboot"}, set())])
        with self.assertRaisesRegex(helper.HelperError, "which the FlickOS desktop needs"):
            self.plan("2026-09-03T12:19:54", {"adb"}, [({"adb"}, set())], protected={"adb"})
        with self.assertRaisesRegex(helper.HelperError, "none of these packages is installed"):
            self.plan("2026-09-03T12:19:54", set(), [])

    def test_undo_a_removal(self):
        plan, calls = self.plan("2026-09-03T13:10:03", set(), [(set(), {"adb", "android-liblog"})])
        self.assertEqual((calls, plan["action"], plan["install"]),
                         ([["install", "adb"]], "install", ["adb", "android-liblog"]))
        with self.assertRaisesRegex(helper.HelperError, "would remove fastboot"):
            self.plan("2026-09-03T13:10:03", set(), [({"fastboot"}, {"adb"})])
        with self.assertRaisesRegex(helper.HelperError, "installed again"):
            self.plan("2026-09-03T13:10:03", {"adb"}, [])
        with self.assertRaisesRegex(helper.HelperError, "only the live session uses"):
            helper.undo_plan({"id": "2026-09-12T10:00:00", "command": "apt purge calamares",
                              "lists": {"Purge": [("calamares", "amd64", "3")]}},
                             simulate=None, installed=lambda names: set(), protected=set)
        with self.assertRaisesRegex(helper.HelperError, "Updates can't be undone"):
            self.plan("2026-09-08T09:45:49", set(), [])

    def test_find(self):
        self.assertEqual(helper.find_transaction("2026-09-03T13:10:03", live=False)["command"], "apt remove adb")
        for tid, message in (("2026-09-03 13:10:03", "not a change id"), ("2026-01-01T00:00:00", "no change"),
                             ("2026-08-22T15:07:17", "part of installing")):
            with self.assertRaisesRegex(helper.HelperError, message):
                helper.find_transaction(tid, live=False)
        twice = helper.read_apt_log() + [self.transaction("2026-09-03T13:10:03")]
        with self.assertRaisesRegex(helper.HelperError, "more than one"):
            helper.find_transaction("2026-09-03T13:10:03", transactions=twice, live=False)

    def test_read_only_verbs_need_no_root(self):
        with mock.patch.object(helper.os, "geteuid", return_value=1000), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch.object(helper, "boot_time", return_value=datetime.datetime(2000, 1, 1)):
            self.assertEqual(helper.main(["packages-list", "100000"]), 0)
        self.assertEqual(len(json.loads(out.getvalue())), 6)
        with mock.patch.object(helper.os, "geteuid", return_value=1000), mock.patch("sys.stderr"):
            self.assertEqual(helper.main(["packages-undo", "2026-09-03T13:10:03"]), 1)

    def test_undo_runs_apt_get_with_the_mark(self):
        plan = {"id": "2026-09-03T13:10:03", "action": "install", "args": ["install", "adb"], "remove": [],
                "install": ["adb"], "upgraded": 0, "purged": False}
        with mock.patch.object(helper, "undo_plan", return_value=plan), \
                mock.patch.object(helper, "live_system", return_value=False), \
                mock.patch.object(helper.subprocess, "run") as run, \
                mock.patch.object(helper.os, "geteuid", return_value=0), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            self.assertEqual(helper.main(["packages-undo", "2026-09-03T13:10:03"]), 0)
            command = run.call_args.args[0]
            self.assertEqual(command[:5], ["/usr/bin/apt-get", "-y", "-q", "-o", "FlickOS::Undo=2026-09-03T13:10:03"])
            self.assertEqual(command[-2:], ["install", "adb"])
            self.assertEqual(run.call_args.kwargs["env"]["DEBIAN_FRONTEND"], "noninteractive")
            self.assertEqual(out.getvalue(), "Installed again: adb.\n")
            run.return_value = subprocess.CompletedProcess([], 100, "", "E: Could not get lock /var/lib/dpkg/lock\n")
            with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                self.assertEqual(helper.main(["packages-undo", "2026-09-03T13:10:03"]), 1)
            self.assertIn("Try again in a few minutes", err.getvalue())


class SystemHistoryTest(SettingsTest):
    """Phase 2: system settings, default apps, startup apps, users and
    software in the history."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.tmp, "state")})
        env.start()
        self.addCleanup(env.stop)

    # HistoryTest's helpers, not its tests.
    entries = HistoryTest.entries

    def system(self, key, value, old, returncode=0):
        with mock.patch.object(fc, "system_value", return_value=old), \
                mock.patch.object(fc, "restart_night_light") as night_light, \
                mock.patch.object(fc.subprocess, "run") as run, \
                mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch.object(fc, "warn"):
            run.return_value = subprocess.CompletedProcess([], returncode, "", "")
            status = fc.main(["system", key, value])
        return status, run.call_args.args[0] if run.called else None, night_light

    def test_system_settings(self):
        status, command, _ = self.system("firewall", "on", "off")
        self.assertEqual((status, command), (0, ["pkexec", fc.HELPER, "firewall-on"]))
        status, command, night_light = self.system("timezone", "Europe/Berlin", "Asia/Manila")
        self.assertEqual(command, ["timedatectl", "set-timezone", "Europe/Berlin"])
        night_light.assert_called_once()
        self.assertEqual(self.system("power.lid", "lock", "suspend")[1],
                         ["pkexec", fc.HELPER, "power", "lid", "lock"])
        self.system("updates.auto", "no", "yes", returncode=126)        # no password given: not recorded
        self.assertEqual(self.entries(), [("flickos-control", "firewall", "off", "on"),
                                          ("flickos-control", "timezone", "Asia/Manila", "Europe/Berlin"),
                                          ("flickos-control", "power.lid", "suspend", "lock")])
        with mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["system", "firewall", "maybe"]), 1)
            self.assertEqual(fc.main(["system", "timezone", "../etc"]), 1)
            self.assertEqual(fc.main(["system", "nonsense", "x"]), 2)
        with mock.patch.object(fc, "system_keyboard", return_value={"model": "pc105", "layout": "us",
                                                                    "variant": "", "options": "caps:none"}):
            self.assertEqual(fc.system_command("keyboard.system", "de(nodeadkeys)"),
                             ["pkexec", fc.HELPER, "keyboard", "pc105", "de", "nodeadkeys", "caps:none"])
            self.assertEqual(fc.system_value("keyboard.system"), "us")

    def test_undo_of_the_new_kinds(self):
        change = lambda key, old, new: fc.Change("1", None, "flickos-control", key, old, new)
        self.assertEqual(fc.undo_commands(change("firewall", "off", "on")), [[*fc.SELF, "system", "firewall", "off"]])
        self.assertFalse(fc.can_undo(change("updates.scope", "custom", "all")))      # set by hand: no way back
        self.assertEqual(fc.undo_commands(change("default-app.browser", "firefox-esr.desktop", "chromium.desktop")),
                         [[*fc.SELF, "default-app", "set", "browser", "firefox-esr.desktop"]])
        self.assertFalse(fc.can_undo(change("default-app.browser", "", "chromium.desktop")))
        self.assertEqual(fc.undo_commands(change("startup.x.desktop", "absent", "on")),
                         [[*fc.SELF, "startup", "remove", "x.desktop"]])
        self.assertEqual(fc.undo_commands(change("startup.x.desktop", "off", "absent")),
                         [[*fc.SELF, "startup", "add", "x.desktop"], [*fc.SELF, "startup", "disable", "x.desktop"]])
        self.assertEqual(fc.undo_commands(change("startup.x.desktop", "on", "off")),
                         [[*fc.SELF, "startup", "enable", "x.desktop"]])
        self.assertEqual(fc.undo_commands(change("user.bob", "standard", "administrator")),
                         [["pkexec", fc.HELPER, "user-admin", "bob", "no"]])
        self.assertFalse(fc.can_undo(change("user.bob", "absent", "standard")))
        self.assertFalse(fc.can_undo(change("language.de_DE.UTF-8", "absent", "added")))

    def test_words_of_the_new_kinds(self):
        describe = lambda key, old, new: fc.describe(fc.Change("1", None, "flickos-control", key, old, new), {})
        self.assertEqual(describe("power.lid", "suspend", "lock"), ("Closing the lid: Lock the screen", "Was Sleep"))
        self.assertEqual(describe("ntp", "no", "yes"), ("Set the time automatically: on", "Was off"))
        self.assertEqual(describe("updates.scope", "security", "all")[0],
                         "Which updates: All: also Debian's recommended updates")
        self.assertEqual(describe("user.bob", "absent", "administrator"), ("User account added: bob", "administrator"))
        self.assertEqual(describe("user.bob", "standard", "absent"), ("User account removed: bob", ""))
        self.assertEqual(describe("user.bob", "standard", "administrator"),
                         ("User account bob: administrator", "Was standard user"))
        with mock.patch.object(fc, "app_name", side_effect=lambda app: {"a.desktop": "A"}.get(app, app)):
            self.assertEqual(describe("default-app.browser", "", "a.desktop"), ("Web browser: A", "Was none"))
        with mock.patch.object(fc, "startup_name", return_value="Chat"):
            self.assertEqual(describe("startup.chat.desktop", "absent", "on"), ("Chat at login: on",
                                                                                "Was not in the list"))

    def test_default_app_command(self):
        answers = {"query": "firefox-esr.desktop\n"}

        def run(command):
            if command[:2] == ["xdg-mime", "query"]:
                return answers["query"]
            answers["set"] = command
            return ""

        with mock.patch.object(fc, "application_file", side_effect=lambda app: f"/apps/{app}"), \
                mock.patch.object(fc, "app_name", side_effect=lambda app: app.split(".")[0]), \
                mock.patch.object(fc, "run", side_effect=run), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fc.main(["default-app", "set", "browser", "chromium.desktop"]), 0)
        self.assertEqual(answers["set"][:3], ["xdg-mime", "default", "chromium.desktop"])
        self.assertIn("x-scheme-handler/https", answers["set"])
        self.assertEqual(out.getvalue(), "Web browser: chromium.\n")
        self.assertEqual(self.entries(), [("flickos-control", "default-app.browser", "firefox-esr.desktop",
                                           "chromium.desktop")])
        with mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["default-app", "set", "toaster", "x.desktop"]), 2)

    def test_animations_command(self):
        """GSettings stores it; the command changes it and records the change."""
        state = {"value": "true"}
        calls = []

        def run(command):
            calls.append(command)
            self.assertEqual(command[0], fc.GSETTINGS)
            self.assertEqual(tuple(command[2:4]), fc.ANIMATIONS)
            if command[1] == "set":
                state["value"] = command[4]
            elif command[1] == "reset":
                state["value"] = "true"
            return state["value"] + "\n"

        with mock.patch.object(fc, "run", side_effect=run), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fc.main(["animations", "current"]), 0)
            self.assertEqual(fc.main(["animations", "set", "off"]), 0)
            self.assertEqual(fc.main(["animations", "set", "no"]), 0)       # off already: nothing recorded
            self.assertEqual(fc.main(["animations", "set", "default"]), 0)
        self.assertEqual(out.getvalue(), "on\nAnimations: off.\nAnimations: off.\nAnimations: on.\n")
        self.assertIn([fc.GSETTINGS, "set", *fc.ANIMATIONS, "false"], calls)
        self.assertIn([fc.GSETTINGS, "reset", *fc.ANIMATIONS], calls)
        self.assertEqual(self.entries(), [("flickos-control", "animations", "on", "off"),
                                          ("flickos-control", "animations", "off", "on")])
        with mock.patch.object(fc, "run", side_effect=run), mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["animations", "set", "fast"]), 2)
            self.assertEqual(fc.main(["animations", "current", "on"]), 2)
        with mock.patch.object(fc, "run", return_value="'yes'\n"), self.assertRaises(fc.ControlError):
            fc.animations()

    def test_animations_in_the_history(self):
        change = fc.Change("1", None, "flickos-control", "animations", "on", "off")
        self.assertEqual(fc.undo_commands(change), [[*fc.SELF, "animations", "set", "on"]])
        self.assertTrue(fc.restorable(change))
        self.assertFalse(fc.can_undo(fc.Change("1", None, "flickos-control", "animations", "", "off")))
        self.assertEqual(fc.describe(change, {}), ("Animations: off", "Was on"))
        with mock.patch.object(fc, "run", return_value="false\n"):
            self.assertEqual(fc.current_value(change), "off")

    def test_startup_changes_are_recorded(self):
        states = iter(["on", "off"])
        with mock.patch.object(fc, "startup_state", side_effect=lambda _id: next(states)), \
                mock.patch.object(fc, "set_startup_enabled"), mock.patch("sys.stdout"):
            self.assertEqual(fc.main(["startup", "disable", "chat.desktop"]), 0)
        self.assertEqual(self.entries(), [("flickos-control", "startup.chat.desktop", "on", "off")])

    # Software.

    ITEMS = [
        {"id": "2026-09-03T12:19:54", "time": "2026-09-03T12:19:54", "kind": "install", "packages": ["adb"],
         "automatic": ["android-liblog"], "upgraded": 1, "purged": False, "autoremove": False, "undo_of": None,
         "undoable": True, "why": None},
        {"id": "2026-09-03T13:10:03", "time": "2026-09-03T13:10:03", "kind": "remove", "packages": ["adb"],
         "automatic": [], "upgraded": 0, "purged": True, "autoremove": False, "undo_of": None,
         "undoable": True, "why": None},
        {"id": "2026-09-09T10:00:00", "time": "2026-09-09T10:00:00", "kind": "install", "packages": ["adb"],
         "automatic": [], "upgraded": 0, "purged": False, "autoremove": False, "undo_of": "2026-09-03T13:10:03",
         "undoable": True, "why": None},
        {"id": "2026-09-10T10:00:00", "time": "2026-09-10T10:00:00", "kind": "update", "packages": [],
         "automatic": [], "upgraded": 14, "purged": False, "autoremove": False, "undo_of": None,
         "undoable": False, "why": "Updates can't be undone"},
        {"broken": True},
    ]

    def test_software_changes(self):
        with mock.patch.object(fc, "package_app_name", side_effect=lambda p: {"adb": "Android Debug Bridge"}.get(p, p)):
            changes = fc.software_changes(items=self.ITEMS)
            self.assertEqual([c.id for c in changes], ["2026-09-10T10:00:00", "2026-09-09T10:00:00",
                                                       "2026-09-03T13:10:03", "2026-09-03T12:19:54"])
            update, undo, removal, install = changes
            self.assertEqual((removal.undone, removal.undoable), (True, False))     # undone later
            self.assertEqual(fc.describe(install, {}), ("Installed: Android Debug Bridge",
                                                        "And 1 package it needed"))
            self.assertEqual(fc.describe(removal, {}), ("Removed: Android Debug Bridge",
                                                        "Its settings were deleted too · Undone"))
            self.assertEqual(fc.describe(undo, {})[1], "Undone from History")
            self.assertEqual(fc.describe(update, {}), ("Updates installed: 14 packages", ""))
            many = fc.SoftwareChange("x", None, "install", ["a", "b", "c", "d", "e"], [], 0, False, False, None,
                                     True, None)
            self.assertEqual(fc.describe(many, {})[0], "Installed: a, b, c and 2 more")
        # Cleared: apt's changes until then are left out.
        with mock.patch("sys.stdout"):
            fc.main(["history", "clear"])
        self.assertEqual(fc.software_changes(items=self.ITEMS), [])

    def test_app_names_of_packages(self):
        apps = os.path.join(self.tmp, "applications") + "/"
        self.write("applications/vlc.desktop", "[Desktop Entry]\nName=VLC media player\n")
        self.write("applications/hidden.desktop", "[Desktop Entry]\nName=Hidden\nNoDisplay=true\n")
        calls = []

        def dpkg_query(args):
            calls.append(args)
            if args[0] == "-W":     # libgone isn't installed any more
                return "vlc\tinstalled\nlibfoo:i386\tinstalled\nlibgone\tnot-installed\n"
            return f"/usr/bin/vlc\n{apps}hidden.desktop\n{apps}vlc.desktop\n\n/usr/lib/libfoo.so.1\n"

        with mock.patch.object(fc, "APPLICATIONS_DIR", apps), mock.patch.dict(fc.APP_NAME_CACHE, clear=True), \
                mock.patch.object(fc, "dpkg_query", side_effect=dpkg_query):
            fc.learn_app_names(["vlc", "libfoo:i386", "libgone", "vlc"])
            self.assertEqual([fc.package_app_name(p) for p in ("vlc", "libfoo:i386", "libgone")],
                             ["VLC media player", "libfoo:i386", "libgone"])
        self.assertEqual(calls[1], ["-L", "vlc", "libfoo:i386"])
        self.assertEqual(len(calls), 2)                     # all from the cache afterwards

    def test_undo_of_a_software_change_goes_through_the_helper(self):
        plan = {"id": "2026-09-03T13:10:03", "action": "install", "args": ["install", "adb"], "remove": [],
                "install": ["adb", "android-liblog"], "upgraded": 0, "purged": True}
        self.assertEqual(fc.plan_text(plan), ["Installs: adb, android-liblog.",
                                              "They are downloaded, so the computer needs to be online.",
                                              "Their settings were deleted when they were removed, so they start "
                                              "fresh."])
        with mock.patch.object(fc, "helper_json", return_value=plan) as ask, \
                mock.patch.object(fc, "run_undo", return_value=0) as undo, \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(fc.main(["history", "undo", "2026-09-03T13:10:03"]), 0)
        ask.assert_called_once_with(["packages-plan", "2026-09-03T13:10:03"])
        undo.assert_called_once_with([["pkexec", fc.HELPER, "packages-undo", "2026-09-03T13:10:03"]])


class RestoreTest(SettingsTest):
    """Phase 3: history restore WHEN puts back what changed since, without a
    password, as one change of its own."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.tmp, "state")})
        env.start()
        self.addCleanup(env.stop)
        self.history = os.path.join(self.tmp, "state/flickos/history.jsonl")
        self.clock = 1_790_000_000

    entries = HistoryTest.entries
    entry = HistoryTest.entry
    write_history = HistoryTest.write_history

    def at(self, seconds):
        return datetime.datetime.fromtimestamp(self.clock + seconds).astimezone()

    def write_changes(self):
        self.write_history(
            self.entry("layout", "default", "cupertino", 0, owner="flickos-layout"),
            self.entry("keyboard.repeat-delay", "default", "400", 10),
            # After the moment (100):
            self.entry("layout", "cupertino", "traditional", 200, owner="flickos-layout"),
            self.entry("layout", "traditional", "redmond", 300, owner="flickos-layout"),
            self.entry("keyboard.repeat-delay", "400", "300", 400),
            self.entry("touchpad.tap", "default", "no", 500),
            self.entry("touchpad.tap", "no", "yes", 600),             # the default again: nothing to do
            self.entry("firewall", "off", "on", 700),                   # asks for a password: left out
            self.entry("startup.chat.desktop", "absent", "on", 800),
            self.entry("default-app.browser", "", "chrome.desktop", 900),   # had none: can't go back
            self.entry("user.bob", "absent", "standard", 1000),
            self.entry("gap", "8", "20", 1100, owner="flick-tiler"),
        )

    def test_when(self):
        self.assertEqual(fc.parse_when("1790000000000000000"),
                         datetime.datetime.fromtimestamp(1790000000 - 1e-9).astimezone())
        self.assertEqual(fc.parse_when("2026-09-21").replace(tzinfo=None), datetime.datetime(2026, 9, 21, 23, 59, 59,
                                                                                             999999))
        self.assertEqual(fc.parse_when("2026-09-21T18:00+02:00").utcoffset(), datetime.timedelta(hours=2))
        self.assertIsNotNone(fc.parse_when("2026-09-21T18:00").tzinfo)
        with self.assertRaises(fc.ControlError):
            fc.parse_when("last tuesday")
        self.assertIsNone(fc.parse_when("", quiet=True))

    def test_plan(self):
        self.write_changes()
        plan = fc.restore_plan(self.at(100))
        self.assertEqual([(c.owner, c.key, c.old, c.new) for c in plan], [
            ("flickos-layout", "layout", "cupertino", "redmond"),
            ("flickos-control", "keyboard.repeat-delay", "400", "300"),
            ("flickos-control", "startup.chat.desktop", "absent", "on"),
            ("flick-tiler", "gap", "8", "20"),
        ])
        self.assertEqual(fc.restore_plan(self.at(5000)), [])

    def test_commands(self):
        change = lambda owner, key, old, new: fc.Change("1", None, owner, key, old, new)
        commands = fc.restore_commands([
            change("flickos-layout", "clock", "default", "12h"),
            change("flickos-layout", "quick-settings", "off", "on"),
            change("flickos-layout", "style", "default", "light"),
            change("flickos-control", "keyboard.repeat-delay", "400", "300"),
            change("flickos-layout", "layout", "cupertino", "redmond"),
            change("flick-tiler", "gap", "8", "20"),
        ])
        # flickos-layout last, in one `set` (labwc reloads once), the clock and
        # Quick Settings with their own commands.
        self.assertEqual(commands, [[*fc.SELF, "set", "keyboard.repeat-delay", "400"], ["flick-tiler", "gap", "8"],
                                    ["flickos-layout", "set", "cupertino", "--style", "default"],
                                    ["flickos-layout", "clock", "set", "default"],
                                    ["flickos-layout", "quick-settings", "set", "off"]])
        # Only commands of their own: no empty `set`.
        self.assertEqual(fc.restore_commands([change("flickos-layout", "quick-settings", "default", "on")]),
                         [["flickos-layout", "quick-settings", "set", "default"]])

    def test_restore_command(self):
        self.write_changes()
        when = self.at(100).isoformat()
        with mock.patch.object(fc, "run_undo") as run_undo, mock.patch.object(fc, "history_names", return_value={}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fc.main(["history", "restore", when, "--dry-run"]), 0)
            run_undo.assert_not_called()
            self.assertIn("  Desktop layout: cupertino (now redmond)\n", out.getvalue())
            run_undo.return_value = 0
            self.assertEqual(fc.main(["history", "restore", when]), 0)
        self.assertEqual(len(run_undo.call_args.args[0]), 4)
        restore = fc.read_history()[-1]
        self.assertEqual((restore["key"], restore["new"]), ("restore", self.at(100).isoformat(timespec="microseconds")))
        self.assertLess(fc.parse_when(restore["old"]), restore["when"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, mock.patch.object(fc, "warn"):
            self.assertEqual(fc.main(["history", "restore", self.at(5000).isoformat()]), 0)
            self.assertIn("Nothing to put back", out.getvalue())
            self.assertEqual(fc.main(["history", "restore"]), 2)

    def test_a_restore_is_shown_as_one_change(self):
        start = self.at(2000)
        restore = self.entry("restore", start.isoformat(timespec="microseconds"), self.at(100).isoformat(), 2005)
        self.write_history(
            self.entry("keyboard.repeat-delay", "default", "400", 0),
            self.entry("keyboard.repeat-delay", "400", "default", 2002),     # made by the restore
            restore)
        changes = fc.shape_history(fc.read_history(), days=None)
        self.assertEqual([(c.key, c.undoable) for c in changes], [("restore", True), ("keyboard.repeat-delay", False)])
        self.assertFalse(changes[1].newest)                  # the restore changed it since
        self.assertEqual(fc.undo_commands(changes[0]), [[*fc.SELF, "history", "restore",
                                                         start.isoformat(timespec="microseconds")]])
        title, detail = fc.describe(changes[0], {})
        self.assertTrue(title.startswith("Settings put back as they were on "), title)


class FirefoxMemoryTest(SettingsTest):
    """Firefox: use less memory (docs/design/flickos-firefox.md): the helper's
    file, the system setting and the Memory page's state."""

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, "etc-firefox-esr")
        os.makedirs(self.folder)
        self.syspref = os.path.join(self.tmp, "syspref")
        os.symlink(self.folder, self.syspref)
        self.prefs = os.path.join(self.folder, "flickos-memory.js")
        for module in (fc, helper):
            for name, value in (("FIREFOX_PREFS", self.prefs), ("FIREFOX_SYSPREF", self.syspref)):
                patcher = mock.patch.object(module, name, value)
                patcher.start()
                self.addCleanup(patcher.stop)

    def helper(self, *args):
        with mock.patch.object(helper.os, "geteuid", return_value=0), mock.patch("sys.stdout"), \
                mock.patch("sys.stderr"):
            return helper.main(["firefox-memory", *args])

    def test_the_helper_and_the_window_agree(self):
        """Both name the same file, link and first line (setUp patched the paths)."""
        sources = [fc.read_text(os.path.join(PACKAGE, path))
                   for path in ("usr/libexec/flickos/control-helper", "usr/bin/flickos-control")]
        for name in ("FIREFOX_PREFS", "FIREFOX_SYSPREF", "FIREFOX_MARK"):
            values = [re.search(rf'^{name} = ("[^"]*")', text, re.M).group(1) for text in sources]
            self.assertEqual(values[0], values[1], name)

    def test_on_and_off(self):
        self.assertIs(fc.firefox_memory_state(), False)
        self.assertEqual(fc.system_value("firefox.memory"), "off")
        self.assertEqual(self.helper("on"), 0)
        with open(self.prefs) as f:
            text = f.read()
        self.assertEqual(text, helper.firefox_memory_text())
        self.assertTrue(text.startswith(fc.FIREFOX_MARK + "\n"))
        for name, value in helper.FIREFOX_MEMORY_PREFS:
            self.assertIn(f'pref("{name}", {value});\n', text)
        self.assertNotIn("lockPref", text)
        self.assertEqual(os.stat(self.prefs).st_mode & 0o777, 0o644)
        self.assertIs(fc.firefox_memory_state(), True)
        self.assertEqual(fc.system_value("firefox.memory"), "on")
        self.assertEqual(self.helper("off"), 0)
        self.assertFalse(os.path.exists(self.prefs))
        self.assertEqual(self.helper("off"), 0)                 # already off
        for args in ([], ["maybe"], ["on", "now"], ["default"]):
            self.assertEqual(self.helper(*args), 1, args)
        self.assertFalse(os.path.exists(self.prefs))

    def test_a_file_of_someone_elses_is_off(self):
        with open(self.prefs, "w") as f:
            f.write('pref("dom.ipc.processCount.webIsolated", 2);\n')
        self.assertIs(fc.firefox_memory_state(), False)

    def test_without_debians_firefox(self):
        os.unlink(self.syspref)
        self.assertIsNone(fc.firefox_memory_state())
        with self.assertRaises(fc.ControlError):
            fc.system_value("firefox.memory")
        self.assertEqual(self.helper("on"), 1)
        self.assertFalse(os.path.exists(self.prefs))
        self.assertEqual(self.helper("off"), 0)                 # a file left behind can go
        os.symlink(self.tmp, self.syspref)                      # another folder
        self.assertIsNone(fc.firefox_memory_state())
        self.assertEqual(self.helper("on"), 1)

    def test_system_setting_and_history(self):
        with mock.patch.object(fc, "system_value", return_value="off"), \
                mock.patch.object(fc.subprocess, "run") as run, \
                mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch.object(fc, "warn"):
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            self.assertEqual(fc.main(["system", "firefox.memory", "on"]), 0)
            self.assertEqual(run.call_args.args[0], ["pkexec", fc.HELPER, "firefox-memory", "on"])
            self.assertEqual(fc.main(["system", "firefox.memory", "default"]), 1)
        change = fc.Change("1", None, "flickos-control", "firefox.memory", "off", "on")
        self.assertEqual(fc.describe(change, {}), ("Firefox uses less memory: on", "Was off"))
        self.assertEqual(fc.undo_commands(change), [[*fc.SELF, "system", "firefox.memory", "off"]])
        self.assertFalse(fc.restorable(change))

    def test_memory_state(self):
        proc = os.path.join(self.tmp, "proc")
        os.makedirs(proc)
        with open(os.path.join(proc, "meminfo"), "w") as f:
            f.write("MemTotal:        2020000 kB\nMemFree:          100000 kB\nMemAvailable:    1520000 kB\n")
        with mock.patch.object(fc, "PROC", proc), mock.patch.object(fc, "accelerated", return_value=True):
            state = fc.memory_state()
        self.assertEqual(state, {"total": 2020000, "used": 500000, "firefox": False,
                                 "old": ["This computer has 1.9 GB of memory."]})
        self.assertEqual(fc.gigabytes(state["used"]), "0.5 GB")


class PhonesFirewallTest(SettingsTest):
    """Phones through the firewall (flickos-phone): the helper's app profile and
    rules, and the system setting that reads the profile."""

    def setUp(self):
        super().setUp()
        self.profile = os.path.join(self.tmp, "flickos-phones")
        self.ufw_conf = os.path.join(self.tmp, "ufw.conf")
        with open(self.ufw_conf, "w") as f:
            f.write("ENABLED=yes\n")
        self.calls = []
        for module, name, value in ((fc, "PHONES_PROFILE", self.profile), (helper, "PHONES_PROFILE", self.profile),
                                    (fc, "UFW_CONF", self.ufw_conf), (helper, "UFW", self.ufw_conf),
                                    (helper, "run_tool", lambda command, stdin=None: self.calls.append(command))):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def helper(self, *args):
        with mock.patch.object(helper.os, "geteuid", return_value=0), mock.patch("sys.stdout"), \
                mock.patch("sys.stderr"):
            return helper.main(["firewall-phones", *args])

    def test_the_helper_and_the_window_agree(self):
        sources = [fc.read_text(os.path.join(PACKAGE, path))
                   for path in ("usr/libexec/flickos/control-helper", "usr/bin/flickos-control")]
        for name in ("PHONES_PROFILE", "PHONES_MARK"):
            values = [re.search(rf'^{name} = ("[^"]*")', text, re.M).group(1) for text in sources]
            self.assertEqual(values[0], values[1], name)

    def test_on_and_off(self):
        self.assertEqual(fc.system_value("firewall.phones"), "off")
        self.assertEqual(self.helper("on"), 0)
        self.assertTrue(fc.phones_allowed())
        self.assertEqual(fc.system_value("firewall.phones"), "on")
        with open(self.profile) as f:
            text = f.read()
        self.assertIn("[FlickOS Phones]\n", text)
        # UDP 1716: a phone's broadcast when it joins the network.
        self.assertIn("ports=1716,1739:1764/tcp|1716/udp\n", text)
        self.assertEqual(os.stat(self.profile).st_mode & 0o777, 0o644)
        ufw = helper.UFW
        self.assertEqual(self.calls, [[ufw, "app", "update", "FlickOS Phones"]]
                         + [[ufw, "allow", "from", network, "to", "any", "app", "FlickOS Phones"]
                            for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")])
        self.calls.clear()
        self.assertEqual(self.helper("off"), 0)
        self.assertEqual([call[1:3] for call in self.calls], [["delete", "allow"]] * 3)
        self.assertFalse(os.path.exists(self.profile))
        self.assertFalse(fc.phones_allowed())
        self.calls.clear()
        self.assertEqual(self.helper("off"), 0)             # already off: nothing to delete
        self.assertEqual(self.calls, [])
        for args in ([], ["maybe"], ["on", "now"]):
            self.assertEqual(self.helper(*args), 1, args)

    def test_refresh(self):
        # Nothing let in: nothing to do.
        self.assertEqual(self.helper("refresh"), 0)
        self.assertFalse(os.path.exists(self.profile))
        self.assertEqual(self.calls, [])
        # An older version's profile (TCP only): rewritten, its rules updated.
        with open(self.profile, "w") as f:
            f.write(helper.phones_profile_text().replace(helper.PHONES_PORTS, "1716,1739:1764/tcp"))
        self.assertEqual(self.helper("refresh"), 0)
        with open(self.profile) as f:
            self.assertEqual(f.read(), helper.phones_profile_text())
        self.assertEqual(self.calls, [[helper.UFW, "app", "update", "FlickOS Phones"]])
        # Up to date: no ufw at all.
        self.calls.clear()
        self.assertEqual(self.helper("refresh"), 0)
        self.assertEqual(self.calls, [])

    def test_postinst_refreshes(self):
        text = fc.read_text(os.path.join(PACKAGE, "debian/postinst"))
        self.assertIn("/usr/libexec/flickos/control-helper firewall-phones refresh || true\n", text)
        self.assertTrue(os.access(os.path.join(PACKAGE, "debian/postinst"), os.X_OK))

    def test_someone_elses_profile_is_left_alone(self):
        with open(self.profile, "w") as f:
            f.write("[FlickOS Phones]\nports=1:65535/tcp\n")
        self.assertFalse(fc.phones_allowed())
        self.assertEqual(self.helper("on"), 1)
        self.assertEqual(self.helper("off"), 1)
        self.assertEqual(self.helper("refresh"), 0)
        self.assertEqual(self.calls, [])
        with open(self.profile) as f:
            self.assertIn("1:65535", f.read())

    def test_without_ufw(self):
        with mock.patch.object(fc, "UFW_CONF", os.path.join(self.tmp, "none")):
            with self.assertRaises(fc.ControlError):
                fc.system_value("firewall.phones")
        with mock.patch.object(helper, "UFW", os.path.join(self.tmp, "none")):
            self.assertEqual(self.helper("on"), 1)

    def test_system_setting_and_history(self):
        with mock.patch.object(fc, "system_value", return_value="off"), \
                mock.patch.object(fc.subprocess, "run") as run, \
                mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch.object(fc, "warn"):
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            self.assertEqual(fc.main(["system", "firewall.phones", "on"]), 0)
            self.assertEqual(run.call_args.args[0], ["pkexec", fc.HELPER, "firewall-phones", "on"])
        change = fc.Change("1", None, "flickos-control", "firewall.phones", "off", "on")
        self.assertEqual(fc.describe(change, {}), ("Firewall lets phones in: on", "Was off"))
        self.assertEqual(fc.undo_commands(change), [[*fc.SELF, "system", "firewall.phones", "off"]])
        self.assertFalse(fc.restorable(change))


SETTINGS_UCA = os.path.join(PACKAGE, "../flickos-settings/etc/xdg/flickos/Thunar/uca.xml")
SCREENSHOT_PROGRAM = os.path.join(PACKAGE, "../flickos-screenshot/usr/bin/flickos-screenshot")


class ScreenshotTest(unittest.TestCase):
    """The Screenshots page's words and flickos-screenshot's changes in History."""

    def change(self, key, old, new):
        return fc.Change("1", None, "flickos-screenshot", key, old, new)

    def test_history(self):
        pointer = self.change("pointer", "no", "yes")
        self.assertEqual(fc.describe(pointer, {}), ("Pointer in screenshots: on", "Was off"))
        self.assertEqual(fc.undo_commands(pointer), [["flickos-screenshot", "set", "pointer", "no"]])
        self.assertTrue(fc.restorable(pointer))
        sound = self.change("sound", "none", "both")
        self.assertEqual(fc.describe(sound, {}),
                         ("Sound in a recording: Computer and microphone", "Was No sound"))
        folder = self.change("folder", "default", "/mnt/shots")
        self.assertEqual(fc.describe(folder, {}), ("Screenshots folder: /mnt/shots", "Was the default"))
        self.assertEqual(fc.undo_commands(folder), [["flickos-screenshot", "set", "folder", "default"]])
        home = os.path.expanduser("~")
        self.assertEqual(fc.value_name("flickos-screenshot", "recordings-folder",
                                       os.path.join(home, "Videos", "Clips"), {}), "Videos/Clips")
        back = self.change("folder", "/mnt/shots", "default")
        self.assertIsNone(fc.current_value(back))          # "default" is the user's file, not a path
        with mock.patch.object(fc, "run", return_value="/mnt/shots\n") as run:
            self.assertEqual(fc.current_value(folder), "/mnt/shots")
        run.assert_called_once_with(["flickos-screenshot", "get", "folder"])

    def test_page_available(self):
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/flickos-screenshot"):
            self.assertTrue(fc.page_available("screenshots"))
        with mock.patch.object(fc.shutil, "which", return_value=None):
            self.assertFalse(fc.page_available("screenshots"))

    @unittest.skipUnless(os.path.exists(SCREENSHOT_PROGRAM), "flickos-screenshot is not next to this package")
    def test_sound_words_are_the_owners(self):
        loader = importlib.machinery.SourceFileLoader("flickos_screenshot_words", SCREENSHOT_PROGRAM)
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        self.assertEqual(dict(fc.SCREENSHOT_SOUNDS), module.SOUNDS)


class PhoneTest(unittest.TestCase):
    """The Phone page's words and flickos-phone's changes in History."""

    def change(self, key, old, new):
        return fc.Change("1", None, "flickos-phone", key, old, new)

    def test_history(self):
        enabled = self.change("enabled", "no", "yes")
        self.assertEqual(fc.describe(enabled, {}), ("Phone connection: on", "Was off"))
        self.assertEqual(fc.undo_commands(enabled), [["flickos-phone", "set", "enabled", "no"]])
        self.assertTrue(fc.restorable(enabled))
        name = self.change("name", "default", "Den PC")
        self.assertEqual(fc.undo_commands(name), [["flickos-phone", "set", "name", "default"]])
        networks = self.change("networks", "", "a b")
        self.assertEqual(fc.describe(networks, {}), ("Networks for the phone connection: 2 networks", "Was none"))
        self.assertEqual(fc.undo_commands(networks), [["flickos-phone", "set", "networks", ""]])
        self.assertEqual(fc.value_name("flickos-phone", "networks", "a", {}), "1 network")
        calls = self.change("calls", "no", "yes")
        self.assertEqual(fc.describe(calls, {}), ("Phone calls: on", "Was off"))
        self.assertEqual(fc.undo_commands(calls), [["flickos-phone", "set", "calls", "no"]])
        self.assertTrue(fc.restorable(calls))
        media = self.change("media", "no", "yes")
        self.assertEqual(fc.describe(media, {}), ("Control what's playing from the phone: on", "Was off"))
        self.assertEqual(fc.undo_commands(media), [["flickos-phone", "set", "media", "no"]])
        self.assertTrue(fc.restorable(media))
        stored = '[{"key":"11111111-1111-1111-1111-111111111111","name":"Hello","command":"echo hi"}]'
        commands = self.change("commands", "", stored)
        self.assertEqual(fc.describe(commands, {}), ("Commands the phone can run: Hello", "Was none"))
        self.assertEqual(fc.undo_commands(commands), [["flickos-phone", "set", "commands", ""]])
        self.assertTrue(fc.restorable(commands))
        self.assertEqual(fc.value_name("flickos-phone", "commands", stored, {}), "Hello")
        two = ('[{"key":"11111111-1111-1111-1111-111111111111","name":"Hello","command":"echo hi"},'
               '{"key":"22222222-2222-2222-2222-222222222222","name":"Goodbye","command":"echo bye"}]')
        self.assertEqual(fc.value_name("flickos-phone", "commands", two, {}), "Hello, Goodbye")
        paired = self.change("device.eb0a", "absent", "HMD CREST")
        self.assertEqual(fc.describe(paired, {}), ("Phone paired: HMD CREST", ""))
        self.assertEqual(fc.describe(self.change("device.eb0a", "HMD CREST", "absent"), {}),
                         ("Phone forgotten: HMD CREST", ""))
        self.assertFalse(fc.can_undo(paired))
        with mock.patch.object(fc, "run", return_value="yes\n") as run:
            self.assertEqual(fc.current_value(enabled), "yes")
        run.assert_called_once_with(["flickos-phone", "get", "enabled"])

    def test_open_phone_is_searched(self):
        self.assertIn("open phone", fc.SEARCH_KEYWORDS["phone"])

    def test_page_available(self):
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/flickos-phone"), \
                mock.patch.object(fc, "live_session", return_value=False):
            self.assertTrue(fc.page_available("phone"))
        with mock.patch.object(fc.shutil, "which", return_value=None), \
                mock.patch.object(fc, "live_session", return_value=False):
            self.assertFalse(fc.page_available("phone"))
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/flickos-phone"), \
                mock.patch.object(fc, "live_session", return_value=True):
            self.assertFalse(fc.page_available("phone"))

    def test_thunar_actions_that_hide_send_to_phone(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        home, system, debian = (os.path.join(tmp, d) for d in ("home", "flickos", "debian"))

        def actions(folder, *ids):
            os.makedirs(os.path.join(folder, "Thunar"), exist_ok=True)
            with open(os.path.join(folder, "Thunar", "uca.xml"), "w", encoding="utf-8") as f:
                f.write("<actions>" + "".join(f"<action><unique-id>{i}</unique-id></action>" for i in ids)
                        + "</actions>")
            return os.path.join(folder, "Thunar", "uca.xml")

        actions(debian)
        actions(system, "flickos-terminal-here", fc.THUNAR_PHONE_ACTION)
        env = {"XDG_CONFIG_HOME": home, "XDG_CONFIG_DIRS": f"{system}:{debian}"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(fc.shutil, "which", return_value="/usr/bin/thunar") as which:
            self.assertIsNone(fc.thunar_hides_phone_action())           # no file of the user's
            user = actions(home, "1790919448825208-1")
            self.assertEqual(fc.thunar_hides_phone_action(), user)
            self.assertIn(user, fc.thunar_notice(user))
            actions(home, "1790919448825208-1", fc.THUNAR_PHONE_ACTION)
            self.assertIsNone(fc.thunar_hides_phone_action())           # kept it in their own
            with open(user, "w", encoding="utf-8") as f:
                f.write("<actions><action>")
            self.assertIsNone(fc.thunar_hides_phone_action())           # Thunar can't read it either
            actions(home, "mine")
            os.environ["XDG_CONFIG_DIRS"] = debian
            self.assertIsNone(fc.thunar_hides_phone_action())           # no Send to Phone to hide
            os.environ["XDG_CONFIG_DIRS"] = f"{system}:{debian}"
            which.return_value = None
            self.assertIsNone(fc.thunar_hides_phone_action())           # no Thunar

    @unittest.skipUnless(os.path.exists(SETTINGS_UCA), "flickos-settings is not next to this package")
    def test_send_to_phone_id_is_flickos_settings(self):
        ids = [e.text for e in ET.parse(SETTINGS_UCA).iter("unique-id")]
        self.assertIn(fc.THUNAR_PHONE_ACTION, ids)

    def test_summary(self):
        state = {"enabled": True, "running": True, "listening": True, "phones": [], "networks": []}
        self.assertEqual(fc.phone_summary(dict(state, enabled=False)), "Off")
        self.assertEqual(fc.phone_summary(state), "On. Add a phone below.")
        phone = {"id": "a", "name": "HMD CREST", "connected": False}
        self.assertEqual(fc.phone_summary(dict(state, phones=[phone])), "Waiting for the phone")
        self.assertEqual(fc.phone_summary(dict(state, phones=[phone], listening=False)),
                         "Waiting for a network where a phone was paired")
        self.assertEqual(fc.phone_summary(dict(state, phones=[dict(phone, connected=True)])),
                         "Connected to HMD CREST")
        self.assertEqual(fc.phone_summary(dict(state, running=False, phones=[phone])),
                         "Not running: turn it off and on again")
        self.assertIn("KDE Connect is already running",
                      fc.phone_summary(dict(state, running=False, blocked=True)))

    def test_addresses_and_times(self):
        self.assertEqual(fc.short_address("https://www.howtogeek.com/stop-chasing/?utm_source=facebook&x=1"),
                         "howtogeek.com/stop-chasing")
        self.assertEqual(fc.short_address("https://a.org/#:~:text=x"), "a.org")
        self.assertLessEqual(len(fc.short_address("https://a.org/" + "x" * 100)), 60)
        now = datetime.datetime(2026, 9, 27, 15, 0)
        self.assertEqual(fc.when_received(datetime.datetime(2026, 9, 27, 14, 2).timestamp(), now), "14:02")
        self.assertEqual(fc.when_received(datetime.datetime(2026, 9, 26, 9, 5).timestamp(), now), "Yesterday 09:05")
        self.assertEqual(fc.when_received(datetime.datetime(2026, 9, 22, 9, 5).timestamp(), now),
                         datetime.datetime(2026, 9, 22).strftime("%a %d %b"))


class OldComputerTest(unittest.TestCase):
    """old_computer() (docs/design/flickos-lite.md ADR-004) on fake /proc and
    /sys/class/drm trees."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-control-old-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proc = os.path.join(self.tmp, "proc")
        os.makedirs(self.proc)

    def meminfo(self, kb):
        with open(os.path.join(self.proc, "meminfo"), "w") as f:
            f.write(f"MemTotal:       {kb} kB\nMemAvailable:   {kb // 2} kB\n")

    def drm(self, driver, virtio=None, features="0"):
        """A DRM tree with one render node whose device has driver (or a
        virtio-pci device with a virtio child of driver virtio)."""
        drm = tempfile.mkdtemp(dir=self.tmp)
        device = os.path.join(drm, "devices", "pci0")
        drivers = os.path.join(drm, "drivers")
        os.makedirs(device)
        for name in (driver, virtio):
            if name:
                os.makedirs(os.path.join(drivers, name), exist_ok=True)
        os.symlink(os.path.join(drivers, driver), os.path.join(device, "driver"))
        if virtio:
            child = os.path.join(device, "virtio0")
            os.makedirs(child)
            os.symlink(os.path.join(drivers, virtio), os.path.join(child, "driver"))
            with open(os.path.join(child, "features"), "w") as f:
                f.write(features + "0" * 63 + "\n")
        os.makedirs(os.path.join(drm, "class", "renderD128"))
        os.symlink(device, os.path.join(drm, "class", "renderD128", "device"))
        return os.path.join(drm, "class")

    def test_memory(self):
        gpu = self.drm("i915")
        for kb, old in ((1_968_000, True), (3 * 1024 * 1024, True), (3 * 1024 * 1024 + 1, False),
                        (3_900_000, False)):
            self.meminfo(kb)
            self.assertEqual(bool(fc.old_computer(self.proc, gpu)), old, kb)
        self.meminfo(1_968_000)
        self.assertEqual(fc.old_computer(self.proc, gpu), ["This computer has 1.9 GB of memory."])
        os.unlink(os.path.join(self.proc, "meminfo"))
        self.assertEqual(fc.old_computer(self.proc, gpu), [])     # unknown: not old

    def test_graphics(self):
        self.meminfo(8_000_000)
        for name in ("i915", "amdgpu", "nouveau", "radeon", "vmwgfx"):
            self.assertTrue(fc.accelerated(self.drm(name)), name)
        for name in fc.SOFTWARE_DRIVERS:
            self.assertFalse(fc.accelerated(self.drm(name)), name)
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        self.assertFalse(fc.accelerated(empty))                  # no render node
        self.assertEqual(fc.old_computer(self.proc, empty),
                         ["Its graphics have no acceleration, so the processor draws the screen."])
        # A virtio GPU (QEMU's virtio-vga): a render node either way, 3D only with virgl.
        self.assertFalse(fc.accelerated(self.drm("virtio-pci", "virtio_gpu", features="0")))
        self.assertTrue(fc.accelerated(self.drm("virtio-pci", "virtio_gpu", features="1")))


class RestorePointsTest(unittest.TestCase):
    """The Restore Points page's reading side (flickos-recovery owns them)."""

    def mountinfo(self, text):
        tmp = tempfile.NamedTemporaryFile("w", delete=False)
        tmp.write(text)
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        return mock.patch.object(fc, "RECOVERY_MOUNTINFO", tmp.name)

    def test_available_only_on_the_btrfs_layout(self):
        layout = ("22 1 0:25 /@ / rw - btrfs /dev/vda2 rw\n"
                  "24 22 0:25 /@snapshots /.snapshots rw - btrfs /dev/vda2 rw\n")
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/flickos-recovery"), \
                mock.patch.object(fc, "live_session", return_value=False):
            with self.mountinfo(layout):
                self.assertTrue(fc.recovery_available())
            with self.mountinfo("22 1 8:2 / / rw - ext4 /dev/sda2 rw\n"):
                self.assertFalse(fc.recovery_available())
            with self.mountinfo(layout.replace("/@snapshots /.snapshots", "/snaps /.snapshots")):
                self.assertFalse(fc.recovery_available())
            with self.mountinfo(layout), mock.patch.object(fc, "live_session", return_value=True):
                self.assertFalse(fc.recovery_available())
        with mock.patch.object(fc.shutil, "which", return_value=None), self.mountinfo(layout):
            self.assertFalse(fc.recovery_available())

    def test_the_switch_is_a_system_setting(self):
        self.assertEqual(fc.check_system("restore-points", "off"), "off")
        with self.assertRaises(fc.ControlError):
            fc.check_system("restore-points", "maybe")
        self.assertEqual(fc.system_command("restore-points", "off"),
                         ["pkexec", fc.RECOVERY_HELPER, "enabled", "no"])
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/flickos-recovery"), \
                mock.patch.object(fc, "run", return_value="enabled\tyes\tdefault\n") as run:
            self.assertEqual(fc.system_value("restore-points"), "on")
        run.assert_called_once_with([fc.RECOVERY, "get", "enabled"])
        self.assertEqual(fc.system_command("restore-points.auto", "off"),
                         ["pkexec", fc.RECOVERY_HELPER, "auto-recover", "no"])
        with mock.patch.object(fc.shutil, "which", return_value="/usr/bin/flickos-recovery"), \
                mock.patch.object(fc, "run", return_value="auto-recover\tno\tsystem\n") as run:
            self.assertEqual(fc.system_value("restore-points.auto"), "off")
        run.assert_called_once_with([fc.RECOVERY, "get", "auto-recover"])

    def test_history_rows(self):
        state = {"available": True, "points": [
            {"name": "2026-10-10_02-55-48", "created": 1791600000.0,
             "description": "Before installing sl, 10 October 02:55"}]}
        point, = fc.history_restore_points(state)
        self.assertEqual(point.name, "2026-10-10_02-55-48")
        self.assertIsNotNone(point.when.tzinfo)
        self.assertEqual(fc.describe(point, {})[0], "Restore point: Before installing sl")
        self.assertEqual(fc.history_restore_points({"available": False, "points": state["points"]}), [])
        self.assertFalse(point.waiting)
        waiting, = fc.history_restore_points({**state, "restart_needed": True})
        self.assertTrue(waiting.waiting)

    def test_plan_lines(self):
        plan = {"changes": [{"date": "2026-10-10 02:55:52", "install": ["cowsay"], "upgrade": [], "remove": []},
                            {"date": "2026-10-10 03:00:00", "install": [], "upgrade": ["a", "b", "c", "d"],
                             "remove": ["vlc"]},
                            {"date": "2026-10-10 03:01:00", "install": [], "upgrade": [], "remove": []}]}
        self.assertEqual(fc.plan_lines(plan), ["• 2026-10-10 02:55: installs cowsay",
                                               "• 2026-10-10 03:00: updates a, b, c and 1 more; removes vlc"])
        many = {"changes": [{"date": f"2026-10-10 0{i}:00:00", "install": ["x"]} for i in range(10)]}
        self.assertEqual(fc.plan_lines(many, limit=3)[-1], "• and 7 more software changes")

    def test_output_messages_drop_the_programs_name(self):
        self.assertEqual(fc.output_messages("", "flickos-recovery: no restore point x\n"),
                         ["no restore point x"])
