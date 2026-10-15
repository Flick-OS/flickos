"""Tests for usr/bin/flickos-shortcuts. Run: python3 -m unittest discover -s tests"""

import importlib.machinery
import importlib.util
import os
import re
import socket
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_shortcuts",
                                               os.path.join(PACKAGE, "usr/bin/flickos-shortcuts"))
fs = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fs)

# Never the build host's $XDG_RUNTIME_DIR (flickos-layouts' add-on descriptions).
RUNTIME = tempfile.TemporaryDirectory(prefix="flickos-shortcuts-test-")
_runtime = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": RUNTIME.name})


def setUpModule():
    _runtime.start()


def tearDownModule():
    _runtime.stop()
    RUNTIME.cleanup()

# Shaped like flickos-settings' rc.xml plus flick-tiler's fragment.
RC_XML = """<?xml version="1.0"?>
<labwc_config>
  <keyboard>
    <default />
    <keybind key="W-Return"><action name="Execute"><command>foot</command></action></keybind>
    <keybind key="W-d"><action name="Execute"><command>sh -c 'pkill -x fuzzel || fuzzel'</command></action></keybind>
    <keybind key="A-F3"><action name="Execute"><command>sh -c 'pkill -x fuzzel || fuzzel'</command></action></keybind>
    <keybind key="W-q"><action name="Close" /></keybind>
    <keybind key="W-a"><action name="None" /></keybind>
    <keybind key="W-t"><action name="Execute"><command>flick-tiler toggle</command></action></keybind>
    <keybind key="W-S-d"><action name="Execute"><command>flick-tiler show-desktop</command></action></keybind>
    <keybind key="C-Print"><action name="Execute"><command>sh -c 'grim -g "$(slurp)" - | wl-copy'</command></action></keybind>
    <keybind key="XF86AudioMute"><action name="Execute"><command>wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle</command></action></keybind>
    <keybind key="W-x"><action name="ToggleDecorations" /></keybind>
    <keybind key="W-z"><action name="Execute" command="my-tool --flag" /></keybind>
    <keybind key="Q-z"><action name="Close" /></keybind>
  </keyboard>
  <keyboard>
    <keybind key="W-S-t"><action name="SnapToRegion" region="ft3" /><action name="Execute"><command>flick-tiler tile</command></action></keybind>
    <keybind key="W-bracketleft"><action name="Execute"><command>flick-tiler ratio -5</command></action></keybind>
  </keyboard>
</labwc_config>
"""


def rc_file(text=RC_XML):
    handle = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False)
    handle.write(text)
    handle.close()
    return handle.name


class KeyTest(unittest.TestCase):
    def test_key_parts(self):
        self.assertEqual(fs.key_parts("W-S-Return"), (("Super", "Shift"), "Return"))
        self.assertEqual(fs.key_parts("S-Mod4-a"), (("Super", "Shift"), "a"))
        self.assertEqual(fs.key_parts("Print"), ((), "Print"))
        self.assertIsNone(fs.key_parts("Q-z"))

    def test_same_key_written_differently(self):
        self.assertEqual(fs.key_parts("W-S-t"), fs.key_parts("S-W-t"))

    def test_format_keys(self):
        parts = [fs.key_parts(k) for k in ("A-F4", "W-q")]
        self.assertEqual(fs.format_keys(parts), ["Super + Q", "Alt + F4"])
        arrows = [fs.key_parts(k) for k in ("A-Left", "A-Right", "A-Up", "A-Down")]
        self.assertEqual(fs.format_keys(arrows), ["Alt + ← → ↑ ↓"])
        self.assertEqual(fs.format_keys([fs.key_parts("W-bracketleft")]), ["Super + ["])


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.path = rc_file()
        self.addCleanup(os.unlink, self.path)

    def test_defaults_replaced_and_removed(self):
        binds = dict(fs.read_keybinds(self.path))
        self.assertEqual(binds["W-Return"], [("Execute", {"command": "foot"})])
        self.assertNotIn("W-a", binds)          # action None removes it
        self.assertIn("A-Tab", binds)           # from <default />
        self.assertNotIn("Q-z", binds)          # unknown modifier

    def test_actions_with_arguments(self):
        binds = dict(fs.read_keybinds(self.path))
        self.assertEqual(binds["W-S-t"][0], ("SnapToRegion", {"region": "ft3"}))
        self.assertEqual(binds["W-z"], [("Execute", {"command": "my-tool --flag"})])

    def test_without_default(self):
        path = rc_file(RC_XML.replace("<default />", ""))
        self.addCleanup(os.unlink, path)
        self.assertNotIn("A-Tab", [key for key, _ in fs.read_keybinds(path)])

    def test_broken_file(self):
        path = rc_file("<labwc_config>")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(fs.ShortcutsError):
            fs.read_keybinds(path)


class ConfigFilesTest(unittest.TestCase):
    """Which rc.xml files labwc reads: the first, the plain session's, or
    every one while it merges (docs/design/flickos-ricing.md)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="flickos-shortcuts-test-")
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.user = self.write("home/labwc/rc.xml", "<labwc_config><keyboard>"
                               "<keybind key='W-F12'><action name='Execute'><command>mine</command></action></keybind>"
                               "<keybind key='W-t'><action name='None' /></keybind></keyboard></labwc_config>")
        self.overlay = self.write("overlay/labwc/rc.xml", RC_XML)
        self.system = self.write("system/labwc/rc.xml", RC_XML)
        self.runtime = os.path.join(root, "run")
        os.makedirs(os.path.join(self.runtime, "flickos"))
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": os.path.join(root, "home"),
                                           "XDG_CONFIG_DIRS": f"{root}/overlay:{root}/system",
                                           "XDG_RUNTIME_DIR": self.runtime})
        env.start()
        self.addCleanup(env.stop)

    def write(self, relative, text):
        path = os.path.join(self.tmp.name, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_first_file_without_merging(self):
        self.assertEqual(fs.rc_xml_files(), [self.user])
        self.assertEqual(fs.find_rc_xml(), self.user)

    def test_merging_reads_every_file_least_important_first(self):
        self.write("run/flickos/labwc-merge", "")
        self.assertEqual(fs.rc_xml_files(), [self.system, self.overlay, self.user])
        binds = dict(fs.read_keybinds(fs.rc_xml_files()))
        self.assertIn("W-F12", binds)           # the user's key
        self.assertIn("W-d", binds)             # FlickOS's keys stay
        self.assertNotIn("W-t", binds)          # the user's None removes FlickOS's
        self.assertEqual(fs.find_rc_xml(), self.user)

    def test_merging_skips_a_broken_file(self):
        self.write("run/flickos/labwc-merge", "")
        self.write("home/labwc/rc.xml", "<labwc_config>")
        self.assertIn("W-d", dict(fs.read_keybinds(fs.rc_xml_files())))

    def test_users_default_comes_back_after_flickos_keys(self):
        """Spike Q1b: <default /> in the user's file re-binds labwc's defaults."""
        self.write("run/flickos/labwc-merge", "")
        self.write("home/labwc/rc.xml", "<labwc_config><keyboard><default /></keyboard></labwc_config>")
        binds = dict(fs.read_keybinds(fs.rc_xml_files()))
        self.assertNotEqual(binds["W-Return"], [("Execute", {"command": "foot"})])

    def test_plain_session_reads_only_its_folder(self):
        plain = self.write("run/flickos/plain/labwc/rc.xml", RC_XML)
        self.write("run/flickos/labwc-merge", "")       # the plain folder wins
        self.assertEqual(fs.rc_xml_files(), [plain])
        self.assertNotIn("W-F12", dict(fs.read_keybinds(fs.rc_xml_files())))

    def test_shortcuts_reads_the_same_files(self):
        self.write("run/flickos/labwc-merge", "")
        texts = [text for rows in fs.shortcuts().values() for text, _keys in rows]
        self.assertIn("Run mine", texts)


class DescribeTest(unittest.TestCase):
    def test_known(self):
        self.assertEqual(fs.describe([("Execute", {"command": "foot"})]), ("Applications", "Terminal"))
        # flickos-settings 1.16: the user's default apps.
        for command, text in (("xdg-terminal-exec", "Terminal"),
                              ("/usr/libexec/flickos/open-default browser", "Web browser"),
                              ("/usr/libexec/flickos/open-default files", "File manager")):
            self.assertEqual(fs.describe([("Execute", {"command": command})]), ("Applications", text))
        self.assertEqual(fs.describe([("SnapToRegion", {"region": "ft1"}),
                                      ("Execute", {"command": "flick-tiler tile"})]),
                         ("Tiling", "Tile this window"))
        self.assertEqual(fs.describe([("ShowMenu", {"menu": "client-menu"})]), ("Windows", "Window menu"))
        self.assertEqual(fs.describe([("GoToDesktop", {"to": "2"})]), ("Windows", "Go to desktop 2"))
        self.assertEqual(fs.describe([("GoToDesktop", {"to": "2"})], "W-F2"), ("Windows", "Go to desktop 2"))
        self.assertEqual(fs.describe([("GoToDesktop", {"to": "2"})], "W-2"),
                         ("Windows", "Go to the desktop with that number"))
        self.assertEqual(fs.describe([("SendToDesktop", {"to": "3"})], "W-S-3"),
                         ("Windows", "Move window to the desktop with that number"))
        self.assertEqual(fs.describe([("GoToDesktop", {"to": "left", "wrap": "no"})]),
                         ("Windows", "Go to the desktop on the left"))
        self.assertEqual(fs.describe([("SendToDesktop", {"to": "right"})]),
                         ("Windows", "Move window to the desktop on the right"))

    def test_unknown(self):
        self.assertEqual(fs.describe([("Execute", {"command": "/usr/bin/my-tool --x"})]), ("Other", "Run my-tool"))
        self.assertEqual(fs.describe([("ToggleDecorations", {})]), ("Other", "Toggle decorations"))

    def test_every_tiler_key_is_described(self):
        for command in ("toggle", "mode next", "focus next", "focus prev", "swap next", "swap prev",
                        "promote", "ratio -5", "ratio +5", "tile", "float"):
            section, _ = fs.describe([("Execute", {"command": f"flick-tiler {command}"})])
            self.assertEqual(section, "Tiling", command)

    def test_screenshot_keys(self):
        for command, text in (("flickos-screenshot shot region --copy-only", "Area, copied only"),
                              ("flickos-screenshot shot region", "Area"),
                              ("flickos-screenshot shot screen", "Whole screen"),
                              ("flickos-screenshot bar --video", "Record the screen, or stop"),
                              ("flickos-screenshot", "Area, screen, video or delay")):
            self.assertEqual(fs.describe([("Execute", {"command": command})]), ("Screenshots", text))

    def test_zoom_keys(self):
        """flickos-settings' zoom keybinds: the zoom action names the row, not
        the Execute that tells the daemon Super is busy."""
        path = rc_file("""<labwc_config><keyboard>
    <keybind key="W-equal"><action name="ZoomIn" /><action name="Execute"><command>sh -c "pkill -WINCH -U $(id -u) -f '[f]lickos-shortcuts daemon$'"</command></action></keybind>
    <keybind key="W-KP_Add"><action name="ZoomIn" /><action name="Execute"><command>sh -c "pkill -WINCH -U $(id -u) -f '[f]lickos-shortcuts daemon$'"</command></action></keybind>
    <keybind key="W-minus"><action name="ZoomOut" /></keybind>
    <keybind key="W-0"><action name="ToggleMagnify" /></keybind>
  </keyboard></labwc_config>""")
        self.addCleanup(os.unlink, path)
        self.assertEqual(fs.shortcuts(path), {"Zoom": [
            ("Zoom in", ["Super + =", "Super + Keypad +"]),
            ("Zoom out", ["Super + -"]),
            ("Zoom off, or back on", ["Super + 0"])]})

    def test_shipped_signals_reach_their_process(self):
        """pkill -x compares the process name, which Linux cuts to 15
        characters: `pkill -x flickos-shortcuts` never matches. And the zoom
        keys' BUSY_SIGNAL pattern finds the daemon, not the sh running it."""
        path = os.path.join(os.path.dirname(PACKAGE), "flickos-settings/etc/xdg/labwc/rc.xml")
        if not os.path.exists(path):
            self.skipTest("flickos-settings is not next to this package")
        commands = [c.text or "" for c in fs.ET.parse(path).getroot().iter("command")]
        for command in commands:
            for name in re.findall(r"\b(?:pkill|pgrep)\b[^|;&]*?-x\s+([^\s'\"]+)", command):
                self.assertLessEqual(len(name), 15, command)
        busy = [c for c in commands if "-WINCH" in c and "lickos-shortcuts" in c]
        self.assertTrue(busy)
        for command in busy:
            pattern = re.search(r"-f '([^']+)'", command).group(1)
            self.assertTrue(re.search(pattern, "/usr/bin/python3 /usr/bin/flickos-shortcuts daemon"), command)
            self.assertIsNone(re.search(pattern, command), command)

    def test_every_shipped_key_is_described(self):
        """No key of flickos-settings' rc.xml falls back to "Run PROGRAM" (HIG INT-5)."""
        path = os.path.join(os.path.dirname(PACKAGE), "flickos-settings/etc/xdg/labwc/rc.xml")
        if not os.path.exists(path):
            self.skipTest("flickos-settings is not next to this package")
        for section, rows in fs.shortcuts(path).items():
            for text, keys in rows:
                self.assertFalse(text.startswith("Run "), f"{section}: {text} {keys}")


class ShortcutsTest(unittest.TestCase):
    def setUp(self):
        self.path = rc_file()
        self.addCleanup(os.unlink, self.path)

    def test_grouped(self):
        sections = fs.shortcuts(self.path)
        self.assertEqual(list(sections), ["Applications", "Windows", "Tiling", "Screenshots", "Other"])
        apps = dict(sections["Applications"])
        self.assertEqual(apps["App launcher"], ["Super + D", "Alt + F3"])
        windows = dict(sections["Windows"])
        self.assertEqual(windows["Close window"], ["Super + Q", "Alt + F4"])
        self.assertEqual(windows["Show desktop"], ["Super + Shift + D"])
        self.assertEqual(windows["Snap to half of screen"], ["Super + ← → ↑ ↓"])
        self.assertEqual(dict(sections["Tiling"])["Narrower main area"], ["Super + ["])

    def test_start_menu_tap(self):
        """flickos-layouts' overlay while the start menu is on: a tap of Super."""
        command = "sh -c 'pkill -USR2 -U \"$(id -u)\" -x flickos-menu || flickos-menu super'"
        binds = "".join(f'<keybind key="{key}" onRelease="yes"><action name="Execute">'
                        f'<command>{command}</command></action></keybind>' for key in ("Super_L", "Super_R"))
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
            f.write(f"<labwc_config><keyboard>{binds}</keyboard></labwc_config>")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(fs.shortcuts(f.name), {"Applications": [("Start menu (tap)", ["Super"])]})

    def test_quick_settings(self):
        """flickos-layouts' overlay while Quick Settings is on: Super+A, which
        replaces labwc's default (maximize) since it comes later."""
        command = ("sh -c 'printf quick > \"$XDG_RUNTIME_DIR/flickos/menu/request\"; "
                   "pkill -USR1 -U \"$(id -u)\" -x flickos-menu || flickos-menu quick'")
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
            f.write(f'<labwc_config><keyboard><keybind key="W-a"><action name="ToggleMaximize"/></keybind>'
                    f'<keybind key="W-a"><action name="Execute"><command>{command}</command></action></keybind>'
                    f'</keyboard></labwc_config>')
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(fs.shortcuts(f.name), {"Session": [("Quick Settings", ["Super + A"])]})

    def test_numbered_desktops(self):
        """flickos-layouts' overlay for Traditional's 4 desktops: one row per action."""
        binds = "".join(f'<keybind key="{mods}{n}"><action name="{name}" to="{n}"/></keybind>'
                        for mods, name in (("W-", "GoToDesktop"), ("W-S-", "SendToDesktop"))
                        for n in range(1, 5))
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
            f.write(f"<labwc_config><keyboard>{binds}</keyboard></labwc_config>")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(fs.shortcuts(f.name), {"Windows": [
            ("Go to the desktop with that number", ["Super + 1 2 3 4"]),
            ("Move window to the desktop with that number", ["Super + Shift + 1 2 3 4"])]})

    def test_addon_descriptions(self):
        """flickos-layouts' descriptions of add-on keybinds, by command."""
        path = os.path.join(RUNTIME.name, "flickos", fs.ADDON_DESCRIPTIONS)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.addCleanup(os.unlink, path)
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"my-tool --flag": "Search what you did", "other": 3}')
        self.assertEqual(fs.addon_descriptions(), {"my-tool --flag": "Search what you did"})
        self.assertIn(("Search what you did", ["Super + Z"]), fs.shortcuts(self.path)["Other"])
        with open(path, "w", encoding="utf-8") as f:
            f.write("[broken")
        self.assertEqual(fs.addon_descriptions(), {})
        self.assertIn(("Run my-tool", ["Super + Z"]), fs.shortcuts(self.path)["Other"])

    def test_media_keys_left_out(self):
        text = repr(fs.shortcuts(self.path))
        self.assertNotIn("XF86", text)
        self.assertNotIn("wpctl", text)

    def test_find_rc_xml(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as system:
            os.makedirs(os.path.join(system, "labwc"))
            with open(os.path.join(system, "labwc", "rc.xml"), "w") as f:
                f.write(RC_XML)
            env = {"XDG_CONFIG_HOME": home, "XDG_CONFIG_DIRS": f"/nonexistent:{system}"}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(fs.find_rc_xml(), os.path.join(system, "labwc", "rc.xml"))
                os.makedirs(os.path.join(home, "labwc"))
                open(os.path.join(home, "labwc", "rc.xml"), "w").close()
                self.assertEqual(fs.find_rc_xml(), os.path.join(home, "labwc", "rc.xml"))

    def test_columns(self):
        sections = fs.shortcuts(self.path)
        columns = fs.split_columns(sections)
        self.assertLessEqual(len(columns), fs.COLUMNS)
        self.assertEqual([name for column in columns for name, _ in column], list(sections))
        self.assertEqual(fs.split_columns({}), [[]])

    def test_list_command(self):
        with mock.patch("sys.stdout") as out:
            self.assertEqual(fs.main(["list", "--file", self.path]), 0)
        printed = "".join(call.args[0] for call in out.write.call_args_list)
        self.assertIn("Super + Enter", printed)
        self.assertIn("Terminal", printed)


class HoldTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.timers = {}
        self.hold = fs.Hold(lambda: self.events.append("show"),
                            lambda now: self.events.append("hide now" if now else "hide"),
                            (self.start, self.timers.pop))

    def start(self, ms, callback):
        handle = len(self.timers) + 100
        self.timers[handle] = callback
        return handle

    def fire(self):
        for callback in list(self.timers.values()):
            self.timers.clear()
            callback()

    def test_hold_and_release(self):
        self.hold.modifiers(fs.MOD_SUPER)
        self.assertEqual(self.events, [])
        self.fire()
        self.assertEqual(self.events, ["show"])
        self.hold.modifiers(fs.MOD_SUPER)       # repeated state: nothing new
        self.assertEqual(self.timers, {})
        self.hold.modifiers(0)
        self.assertEqual(self.events, ["show", "hide"])

    def test_quick_tap(self):
        self.hold.modifiers(fs.MOD_SUPER)
        self.hold.modifiers(0)
        self.assertEqual(self.timers, {})
        self.assertEqual(self.events, [])

    def test_other_modifier_cancels(self):
        self.hold.modifiers(fs.MOD_SUPER)
        self.hold.modifiers(fs.MOD_SUPER | 1)     # Super+Shift
        self.assertEqual(self.timers, {})
        self.hold.modifiers(fs.MOD_SUPER)         # Shift let go: counts again
        self.fire()
        self.assertEqual(self.events, ["show"])
        self.hold.modifiers(fs.MOD_SUPER | 4)     # Ctrl while shown hides it
        self.assertEqual(self.events, ["show", "hide"])

    def test_busy_until_super_let_go(self):
        self.hold.modifiers(fs.MOD_SUPER)
        self.hold.busy()                          # Super+= zoomed: no sheet
        self.assertEqual(self.timers, {})
        self.hold.modifiers(fs.MOD_SUPER | 1)     # Shift and back: still busy
        self.hold.modifiers(fs.MOD_SUPER)
        self.assertEqual(self.timers, {})
        self.hold.modifiers(0)
        self.hold.modifiers(fs.MOD_SUPER)         # a new hold counts again
        self.fire()
        self.assertEqual(self.events, ["show"])
        self.hold.busy()                          # Super+scroll while shown hides it, without a fade
        self.assertEqual(self.events, ["show", "hide now"])

    def test_busy_after_super_let_go(self):
        """The signal of a quick Super+= can come after Super is up: the next
        hold still shows the sheet."""
        self.hold.modifiers(fs.MOD_SUPER)
        self.hold.modifiers(0)
        self.hold.busy()
        self.hold.modifiers(fs.MOD_SUPER)
        self.fire()
        self.assertEqual(self.events, ["show"])


class FadeCurveTest(unittest.TestCase):
    def test_ends(self):
        self.assertEqual(fs.fade_opacity(0.0, 1.0, 0, 100, True), (0.0, False))
        self.assertEqual(fs.fade_opacity(0.0, 1.0, 100, 100, True), (1.0, True))
        self.assertEqual(fs.fade_opacity(1.0, 0.0, 250, 80, False), (0.0, True))
        self.assertEqual(fs.fade_opacity(0.4, 1.0, 0, 0, True), (1.0, True))

    MENU = os.path.join(PACKAGE, "../flickos-menu/usr/bin/flickos-menu")

    @unittest.skipUnless(os.path.exists(MENU), "flickos-menu is not next to this package")
    def test_the_same_as_the_start_menu(self):
        """The sheet and the menu's windows fade alike (docs/design/flickos-fades.md)."""
        loader = importlib.machinery.SourceFileLoader("flickos_menu_fades", self.MENU)
        menu = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(menu)
        self.assertEqual((fs.FADE_IN_MS, fs.FADE_OUT_MS), (menu.FADE_IN_MS, menu.FADE_OUT_MS))
        for args in ((0.0, 1.0, 16.7, 100, True), (1.0, 0.0, 40, 80, False), (0.3, 1.0, 50, 100, True)):
            self.assertEqual(fs.fade_opacity(*args), menu.fade_opacity(*args))


class FakeWindow:
    def __init__(self, name):
        self.name = name
        self.opacity = 1.0
        self.shown = False
        self.destroyed = False
        self.ticks = {}

    def show_all(self):
        self.shown = True

    def destroy(self):
        self.destroyed = True
        self.shown = False

    def add_tick_callback(self, callback):
        key = object()
        self.ticks[key] = callback
        return key

    def remove_tick_callback(self, key):
        del self.ticks[key]


class FakeGtk:
    def __init__(self):
        self.animations = True
        gtk = self

        class Widget:
            @staticmethod
            def get_opacity(window):
                return window.opacity

            @staticmethod
            def set_opacity(window, value):
                window.opacity = value

        class Settings:
            @staticmethod
            def get_default():
                return mock.Mock(props=mock.Mock(gtk_enable_animations=gtk.animations))

        self.Widget, self.Settings = Widget, Settings


class SheetsTest(unittest.TestCase):
    def setUp(self):
        self.gtk = FakeGtk()
        self.built = []
        self.sheets = fs.Sheets(self.gtk, self.build)

    def build(self):
        window = FakeWindow(len(self.built) + 1)
        self.built.append(window)
        return window

    def frames(self, *times_ms):
        for ms in times_ms:
            for window in self.built:
                for key, callback in list(window.ticks.items()):
                    if not callback(window, mock.Mock(get_frame_time=lambda ms=ms: ms * 1000)):
                        window.ticks.pop(key, None)

    def test_fades_in_and_out_then_destroys(self):
        self.sheets.show()
        sheet = self.built[0]
        self.assertEqual((sheet.shown, sheet.opacity), (True, 0.0))
        self.frames(0, 17, 100)
        self.assertEqual(sheet.opacity, 1.0)
        self.assertEqual(sheet.ticks, {})
        self.sheets.hide()
        self.assertFalse(sheet.destroyed)                 # fading out
        self.frames(200, 240, 280)
        self.assertTrue(sheet.destroyed)
        self.assertEqual((self.sheets.window, self.sheets.leaving, self.sheets.ticks), (None, None, {}))

    def test_let_go_while_it_fades_in(self):
        self.sheets.show()
        sheet = self.built[0]
        self.frames(0, 17)
        reached = sheet.opacity
        self.sheets.hide()
        self.assertEqual(len(sheet.ticks), 1)             # the fade in stopped, one fade out
        self.frames(30)
        self.assertLessEqual(sheet.opacity, reached)
        self.frames(200)
        self.assertTrue(sheet.destroyed)

    def test_a_new_hold_during_a_fade_out(self):
        self.sheets.show()
        self.frames(0, 100)
        self.sheets.hide()
        self.sheets.show()
        old, new = self.built
        self.assertTrue(old.destroyed)
        self.assertEqual(old.ticks, {})
        self.assertIs(self.sheets.window, new)
        self.assertIsNone(self.sheets.leaving)

    def test_busy_and_no_animations_hide_at_once(self):
        self.sheets.show()
        self.sheets.hide(now=True)
        self.assertTrue(self.built[0].destroyed)
        self.gtk.animations = False
        self.sheets.show()
        self.assertEqual((self.built[1].opacity, self.built[1].ticks), (1.0, {}))
        self.sheets.hide()
        self.assertTrue(self.built[1].destroyed)

    def test_hide_without_a_sheet(self):
        self.sheets.hide()
        self.assertEqual(self.built, [])


def event(object_id, opcode, payload=b""):
    return struct.pack("=II", object_id, (8 + len(payload)) << 16 | opcode) + payload


def requests(data):
    """[(object id, opcode, payload)] from the client's bytes."""
    out = []
    while data:
        object_id, word = struct.unpack_from("=II", data)
        size = word >> 16
        out.append((object_id, word & 0xFFFF, data[8:size]))
        data = data[size:]
    return out


class ModifiersTest(unittest.TestCase):
    def test_keyboard_from_seat(self):
        client, server = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(server.close)
        seen = []
        mods = fs.Modifiers(client, seen.append)
        registry = requests(server.recv(4096))[0][2]
        self.assertEqual(struct.unpack("=I", registry)[0], 2)

        server.sendall(event(2, 0, fs.pack_uint(9) + fs.pack_string("wl_output") + fs.pack_uint(4))
                       + event(2, 0, fs.pack_uint(7) + fs.pack_string("wl_seat") + fs.pack_uint(9)))
        self.assertTrue(mods.dispatch())
        (obj, opcode, payload), = requests(server.recv(4096))
        self.assertEqual((obj, opcode), (2, 0))                 # registry.bind
        self.assertTrue(payload.startswith(fs.pack_uint(7) + fs.pack_string("wl_seat") + fs.pack_uint(1)))
        seat = struct.unpack_from("=I", payload, len(payload) - 4)[0]

        server.sendall(event(seat, 0, fs.pack_uint(1 | 2)))     # pointer and keyboard
        mods.dispatch()
        (obj, opcode, payload), = requests(server.recv(4096))
        self.assertEqual((obj, opcode), (seat, 1))              # get_keyboard
        keyboard = struct.unpack("=I", payload)[0]

        # The keymap comes with a file descriptor, which must be closed.
        read_end, write_end = os.pipe()
        os.close(write_end)
        socket.send_fds(server, [event(keyboard, 0, fs.pack_uint(1) + fs.pack_uint(10))], [read_end])
        os.close(read_end)
        server.sendall(event(keyboard, 4, struct.pack("=5I", 1, fs.MOD_SUPER, 0, 16, 0)))
        mods.dispatch()
        if not seen:
            mods.dispatch()
        self.assertEqual(seen, [fs.MOD_SUPER])

    def test_compositor_gone(self):
        client, server = socket.socketpair()
        self.addCleanup(client.close)
        mods = fs.Modifiers(client, lambda _: None)
        server.close()
        self.assertFalse(mods.dispatch())


if __name__ == "__main__":
    unittest.main()
