"""Tests for usr/bin/flick-tiler. Run: python3 -m unittest discover -s tests"""

import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flick_tiler", os.path.join(PACKAGE, "usr/bin/flick-tiler"))
ft = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(ft)

# No test writes the real history (~/.local/state/flickos) or reads the
# system's history.conf; HistoryTest sets its own.
_STATE = tempfile.TemporaryDirectory(prefix="flick-tiler-test-state-")
os.environ["XDG_STATE_HOME"] = _STATE.name
ft.HISTORY_CONF = os.path.join(_STATE.name, "history.conf")
ft.HISTORY_SITE_CONF = os.path.join(_STATE.name, "site-history.conf")


def covers_screen(rects):
    """Every percent cell is in exactly one rect."""
    cells = {}
    for x, y, w, h in rects:
        for i in range(x, x + w):
            for j in range(y, y + h):
                cells[i, j] = cells.get((i, j), 0) + 1
    return len(cells) == 100 * 100 and set(cells.values()) == {1}


class ArrangeTest(unittest.TestCase):
    def test_split_fills_exactly(self):
        for parts in range(1, 12):
            spans = ft.split(parts)
            self.assertEqual(spans[0][0], 0)
            self.assertEqual(sum(size for _, size in spans), 100)
            for (start, size), (following, _) in zip(spans, spans[1:]):
                self.assertEqual(start + size, following)

    def test_tiling_modes_cover_screen(self):
        for mode in ("master-stack", "columns", "grid"):
            for count in range(1, 10):
                with self.subTest(mode=mode, count=count):
                    rects = ft.arrange(mode, count, 55)
                    self.assertEqual(len(rects), count)
                    self.assertTrue(covers_screen(rects))

    def test_master_stack(self):
        self.assertEqual(ft.arrange("master-stack", 1, 60), [(0, 0, 100, 100)])
        self.assertEqual(ft.arrange("master-stack", 3, 60),
                         [(0, 0, 60, 100), (60, 0, 40, 50), (60, 50, 40, 50)])

    def test_monocle_and_empty(self):
        self.assertEqual(ft.arrange("monocle", 3, 55), [(0, 0, 100, 100)] * 3)
        self.assertEqual(ft.arrange("grid", 0, 55), [])

    def test_next_mode_wraps(self):
        ids = list(ft.MODES)
        self.assertEqual(ft.next_mode(ids[-1]), ids[0])
        self.assertEqual(ft.next_mode(ids[0], -1), ids[-1])


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flick-tiler-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Not the build host's /etc/xdg/flickos/tiler.conf.
        patcher = mock.patch.object(ft, "SYSTEM_CONF", os.path.join(self.tmp, "none.conf"))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ft, "SITE_CONF", os.path.join(self.tmp, "no-site.conf"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_parse_clamps_and_ignores_bad_values(self):
        with mock.patch.object(ft, "warn"):
            s = ft.parse_settings({"enabled": "yes", "mode": "spiral", "masterratio": "95",
                                   "gap": "x", "float": "a b*\n c"})
        self.assertTrue(s.enabled)
        self.assertEqual(s.mode, ft.DEFAULT_MODE)
        self.assertEqual(s.ratio, ft.RATIO_MAX)
        self.assertEqual(s.gap, 8)
        self.assertEqual(s.floating, ("a", "b*", "c"))

    def test_system_conf_parses(self):
        with mock.patch.object(ft, "SYSTEM_CONF", os.path.join(PACKAGE, "etc/xdg/flickos/tiler.conf")), \
             mock.patch.object(ft, "warn") as warn:
            s = ft.load_settings()
        warn.assert_not_called()
        self.assertFalse(s.enabled)
        self.assertFalse(s.tile_open)
        self.assertIn("pavucontrol", s.floating)

    def write_conf(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_site_conf_goes_over_the_system_one_key_by_key(self):
        system = self.write_conf("system.conf", "[Tiler]\nmode=grid\ngap=4\n")
        site = self.write_conf("site.conf", "[Tiler]\ngap=12\nenabled=yes\n")
        with mock.patch.object(ft, "SYSTEM_CONF", system), mock.patch.object(ft, "SITE_CONF", site):
            s = ft.load_settings()
            self.assertEqual((s.mode, s.gap, s.enabled), ("grid", 12, True))
            # The user's own choice still wins, and `default` goes back to the site's.
            ft.save_choice(gap=2)
            self.assertEqual(ft.load_settings().gap, 2)
            self.assertEqual(ft.system_settings().gap, 12)

    def test_broken_site_conf_is_left_out(self):
        system = self.write_conf("system.conf", "[Tiler]\ngap=4\n")
        site = self.write_conf("site.conf", "no section here\n")
        with mock.patch.object(ft, "SYSTEM_CONF", system), mock.patch.object(ft, "SITE_CONF", site), \
             mock.patch.object(ft, "warn") as warn:
            self.assertEqual(ft.load_settings().gap, 4)
        warn.assert_called()

    def test_save_choice_keeps_other_keys(self):
        path = ft.user_conf()
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("[Tiler]\ngap=4\nenabled=no\n")
        ft.save_choice(enabled=True, mode="grid")
        values = ft.read_ini(path)
        self.assertEqual(values, {"gap": "4", "enabled": "yes", "mode": "grid"})

    def test_save_choice_writes_floating_as_one_line(self):
        ft.save_choice(floating=("gimp*", "foot"))
        self.assertEqual(ft.read_ini(ft.user_conf()), {"float": "gimp* foot"})
        self.assertEqual(ft.load_settings().floating, ("gimp*", "foot"))

    def test_change_floating(self):
        self.assertEqual(ft.change_floating(("a", "b"), "add", "c"), ("a", "b", "c"))
        # Adding one that is there (any case) moves it to the end, no duplicate.
        self.assertEqual(ft.change_floating(("a", "B"), "add", "b"), ("a", "b"))
        self.assertEqual(ft.change_floating(("a", "b"), "remove", "A"), ("b",))
        for action, pattern in (("remove", "zz"), ("add", "two words"), ("add", ""), ("add", " a")):
            with self.assertRaises(ft.TilerError):
                ft.change_floating(("a",), action, pattern)


def tiler(**settings):
    return ft.Tiler(ft.Settings(**{"enabled": True, "floating": ("pavucontrol",), **settings}))


def open_window(t, handle, app_id="foot", parent=0, new=True, focus=True):
    t.windows[handle] = ft.Window(app_id=app_id, parent=parent)
    if focus:
        for window in t.windows.values():
            window.states = frozenset()
        t.windows[handle].states = frozenset({2})
    changed = t.mapped(handle, new=new)
    t.commit()
    return changed


class TilerTest(unittest.TestCase):
    def test_new_windows_take_the_rule_region(self):
        t = tiler()
        t.commit()
        self.assertEqual(t.rule_region, "ft1")
        self.assertTrue(open_window(t, 100))
        self.assertEqual(t.windows[100].region, "ft1")
        self.assertEqual(t.rule_region, "ft2")
        open_window(t, 101)
        self.assertEqual(t.order, ["ft1", "ft2"])
        regions = t.regions()
        self.assertEqual(regions["ft1"], (0, 0, 55, 100))
        self.assertEqual(regions["ft2"], (55, 0, 45, 100))
        # The next window goes where the third one belongs.
        self.assertEqual(regions["ft3"], (55, 50, 45, 50))

    def test_existing_windows_and_off_are_not_tiled(self):
        t = tiler()
        t.commit()
        self.assertFalse(open_window(t, 100, new=False))
        self.assertIsNone(t.windows[100].region)
        off = tiler(enabled=False)
        off.commit()
        self.assertFalse(open_window(off, 100))
        self.assertIsNone(off.fragment())

    def test_untiled_counts_open_windows_outside_regions(self):
        t = tiler()
        t.commit()
        open_window(t, 100, new=False)
        open_window(t, 101, new=False, app_id="pavucontrol")
        open_window(t, 102, new=False, parent=100)
        open_window(t, 103, new=False)
        t.windows[103].states = frozenset({1})
        open_window(t, 104, focus=False)
        self.assertEqual(t.untiled(), [100])

    def test_float_rules_drop_the_region(self):
        t = tiler()
        t.commit()
        self.assertTrue(open_window(t, 100, app_id="PavuControl"))
        self.assertTrue(open_window(t, 101, parent=55))
        self.assertEqual(t.order, [])
        # Both were snapped to a region, which is now gone: they float.
        self.assertEqual(list(t.regions()), ["ft3"])

    def test_second_window_before_reload_is_not_counted(self):
        t = tiler()
        t.commit()
        t.windows[1], t.windows[2] = ft.Window(), ft.Window()
        self.assertTrue(t.mapped(1, new=True))
        self.assertFalse(t.mapped(2, new=True))
        self.assertEqual(t.order, ["ft1"])

    def test_close_and_minimize(self):
        t = tiler()
        t.commit()
        for handle in (1, 2, 3):
            open_window(t, handle)
        self.assertTrue(t.closed(2))
        self.assertEqual(t.order, ["ft1", "ft3"])
        self.assertEqual(t.regions()["ft3"], (55, 0, 45, 100))
        old = t.windows[3].states
        t.windows[3].states = frozenset({1})
        self.assertTrue(t.states_changed(3, old))
        regions = t.regions()
        self.assertEqual(regions["ft1"], (0, 0, 100, 100))
        # A minimized window keeps its region (and place) for when it comes back.
        self.assertEqual(regions["ft3"], (55, 0, 45, 100))
        self.assertFalse(t.closed(99))

    def test_focus_swap_promote(self):
        t = tiler()
        t.commit()
        for handle in (1, 2, 3):
            open_window(t, handle)
        self.assertEqual(t.focused(), 3)
        self.assertEqual(t.neighbour(1), 1)
        self.assertEqual(t.neighbour(-1), 2)
        self.assertTrue(t.promote())
        self.assertEqual(t.order, ["ft3", "ft2", "ft1"])
        self.assertTrue(t.promote())         # already main: swaps with the next
        self.assertEqual(t.order, ["ft2", "ft3", "ft1"])
        self.assertTrue(t.swap(1))
        self.assertEqual(t.order, ["ft2", "ft1", "ft3"])

    def test_tile_and_float_focused(self):
        t = tiler()
        t.commit()
        open_window(t, 1, new=False)
        self.assertTrue(t.tile_focused())
        self.assertEqual(t.windows[1].region, "ft1")
        t.commit()
        self.assertTrue(t.tile_focused())    # re-tiled: moves to the new region
        self.assertEqual(t.order, ["ft2"])
        self.assertTrue(t.float_focused())
        self.assertEqual(t.order, [])
        self.assertFalse(t.float_focused())

    def test_turning_off_releases_everything(self):
        t = tiler()
        t.commit()
        open_window(t, 1)
        self.assertTrue(t.enable(False))
        t.commit()
        self.assertEqual(t.order, [])
        self.assertIsNone(t.rule_region)
        self.assertIsNone(t.fragment())
        self.assertFalse(t.enable(False))

    def test_fragment(self):
        t = tiler(gap=6)
        t.commit()
        open_window(t, 1)
        top = ET.fromstring(t.fragment())
        self.assertEqual(top.findtext("core/gap"), "6")
        regions = {r.get("name"): r.attrib for r in top.iter("region")}
        self.assertEqual(regions["ft1"]["width"], "100%")   # alone: whole screen
        self.assertEqual(regions["ft2"]["x"], "55%")        # where the next one goes
        self.assertEqual(top.find("windowRules/windowRule").get("identifier"), "*")
        self.assertEqual(top.find("windowRules/windowRule/action").get("region"), "ft2")
        keys = {bind.get("key"): bind for bind in top.iter("keybind")}
        self.assertEqual(set(keys), {key for key, _ in ft.KEYBINDS})
        self.assertEqual(keys["W-S-t"].find("action").get("region"), "ft2")
        self.assertEqual(keys["W-j"].findtext("action/command"), "flick-tiler focus next")

    def open_windows_to_capture(self):
        """Tiling off; 100 used, 101 focused, 102 minimized, 103 fullscreen,
        104 floats by its app id, 105 a dialog."""
        t = tiler(enabled=False)
        t.commit()
        for handle in range(100, 106):
            open_window(t, handle, app_id="pavucontrol" if handle == 104 else "foot",
                        parent=100 if handle == 105 else 0, new=False, focus=handle in (100, 101))
        t.windows[102].states = frozenset({1})
        t.windows[103].states = frozenset({3})
        t.enable(True)
        return t

    def test_capture_gives_open_windows_a_region_and_a_key(self):
        t = self.open_windows_to_capture()
        steps = t.start_capture()
        # The focused one is the main window, and is focused last.
        self.assertEqual(steps, [(100, "XF86Macro2"), (101, "XF86Macro1")])
        self.assertEqual(t.order, ["ft1", "ft2"])
        self.assertEqual((t.windows[101].region, t.windows[100].region), ("ft1", "ft2"))
        self.assertTrue(all(t.windows[h].region is None for h in (102, 103, 104, 105)))
        t.commit()
        self.assertEqual(t.rule_region, "ft3")
        top = ET.fromstring(t.fragment())
        keys = {bind.get("key"): bind for bind in top.iter("keybind")}
        self.assertEqual(keys["XF86Macro1"].find("action").get("region"), "ft1")
        self.assertEqual(keys["XF86Macro2"].findtext("action[@name='Execute']/command"), "flick-tiler snapped ft2")
        self.assertEqual(top.find("windowRules/windowRule/action").get("region"), "ft3")

    def test_capture_lets_go_of_windows_whose_key_didnt_run(self):
        t = self.open_windows_to_capture()
        t.start_capture()
        del t.capture["ft1"]                # 101's keybind ran
        t.end_capture()
        self.assertEqual(t.order, ["ft1"])
        self.assertIsNone(t.windows[100].region)
        self.assertEqual(t.capture, {})
        t.commit()
        self.assertNotIn("XF86Macro2", t.fragment())

    def test_capture_takes_as_many_windows_as_there_are_keys(self):
        t = tiler(enabled=False)
        for handle in range(len(ft.CAPTURE_KEYS) + 2):
            open_window(t, handle, new=False)
        t.enable(True)
        self.assertEqual(len(t.start_capture()), len(ft.CAPTURE_KEYS))
        self.assertEqual(len(t.untiled()), 2)

    def test_turning_off_drops_the_capture(self):
        t = self.open_windows_to_capture()
        t.start_capture()
        t.enable(False)
        self.assertEqual((t.capture, t.order), ({}, []))

    def test_show_desktop_hides_and_restores_its_own_windows(self):
        for enabled in (True, False):
            t = tiler(enabled=enabled)
            t.commit()
            open_window(t, 1)
            open_window(t, 2)
            open_window(t, 3, parent=2)             # a dialog: follows its parent
            open_window(t, 4)
            open_window(t, 5, new=False, focus=False)
            t.windows[5].states = frozenset({1})    # minimized by the user
            t.windows[2].states = frozenset({2})    # focused
            t.windows[4].states = frozenset()
            hide, restore = t.show_desktop()
            # The focused window last, so it is restored last and keeps the focus.
            self.assertEqual((hide, restore), ([1, 4, 2], []))
            for handle in (1, 2, 4):
                t.windows[handle].states = frozenset({1})
            t.closed(4)                             # closed while hidden
            self.assertEqual(t.show_desktop(), ([], [1, 2]))
            # Nothing is left to restore, and nothing is shown.
            self.assertEqual(t.show_desktop(), ([], []))

    def test_show_desktop_hides_windows_opened_meanwhile(self):
        t = tiler()
        t.commit()
        open_window(t, 1)
        t.show_desktop()
        open_window(t, 2)
        t.windows[1].states = frozenset({1})    # open_window focuses 2 and clears the rest
        # A window is shown again: hide it, and restore only it next time.
        self.assertEqual(t.show_desktop(), ([2], []))
        t.windows[2].states = frozenset({1})
        self.assertEqual(t.show_desktop(), ([], [2]))

    def test_app_window_is_the_one_used_last(self):
        t = tiler(enabled=False)
        t.commit()
        open_window(t, 1, app_id="Geany", new=False, focus=False)    # open before the daemon
        self.assertEqual(t.app_window(["geany"]), 1)
        open_window(t, 2, app_id="foot")
        open_window(t, 3, app_id="foot")
        open_window(t, 4, app_id="foot", parent=3)                  # a dialog: never
        old = t.windows[2].states
        t.windows[2].states = frozenset({2})                        # focused again
        t.states_changed(2, old)
        self.assertEqual(t.app_window(["org.example.Foot", "FOOT"]), 2)
        self.assertIsNone(t.app_window(["firefox-esr"]))

    def test_status(self):
        t = tiler()
        self.assertEqual(t.status()["class"], ["on", "master-stack"])
        self.assertEqual(tiler(enabled=False).status()["alt"], "off")


class FillsScreenTest(unittest.TestCase):
    """What makes the floating panel full."""

    def setUp(self):
        self.t = tiler(enabled=False)
        open_window(self.t, 1)

    def test_a_plain_window_does_not(self):
        self.assertFalse(self.t.fills_screen())

    def test_maximized_or_fullscreen(self):
        for state in (0, 3):
            self.t.windows[1].states = frozenset({state})
            self.assertTrue(self.t.fills_screen())

    def test_minimized_does_not(self):
        self.t.windows[1].states = frozenset({0, 1})
        self.assertFalse(self.t.fills_screen())

    def test_a_tiled_window_does(self):
        t = tiler()
        t.commit()
        open_window(t, 1)
        self.assertTrue(t.fills_screen())


class DaemonTest(unittest.TestCase):
    """The daemon runs for the whole session, tiling on or off."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flick-tiler-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        run = os.path.join(self.tmp, "run")
        os.makedirs(run)
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
                                               "XDG_RUNTIME_DIR": run, "WAYLAND_DISPLAY": "wayland-test"})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("reconfigure", "signal_panel", "hint_untiled"):
            patcher = mock.patch.object(ft, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ft, "SYSTEM_CONF", os.path.join(self.tmp, "none.conf"))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ft, "SITE_CONF", os.path.join(self.tmp, "no-site.conf"))
        patcher.start()
        self.addCleanup(patcher.stop)
        # The build host may have wtype; CaptureTest has its own.
        patcher = mock.patch.object(ft, "WTYPE", os.path.join(self.tmp, "no-wtype"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def stale_fragment(self):
        ft.write_atomic(ft.fragment_path(), "<labwc_config/>\n")

    def test_lock_is_exclusive(self):
        first = ft.daemon_lock()
        self.assertIsNotNone(first)
        self.assertIsNone(ft.daemon_lock())
        first.close()
        second = ft.daemon_lock()
        self.assertIsNotNone(second)
        second.close()

    def test_daemon_serves_while_tiling_is_off(self):
        for enabled in (False, True):
            ft.save_choice(enabled=enabled)
            with mock.patch.object(ft, "serve", return_value=0) as serve:
                self.assertEqual(ft.run_daemon(), 0)
            self.assertEqual(serve.call_args.args[0].enabled, enabled)

    def panel_daemon(self):
        daemon = ft.Daemon(ft.Settings(enabled=False))
        open_window(daemon.tiler, 1)
        return daemon

    def test_panel_state_is_written_only_while_the_file_is_there(self):
        daemon = self.panel_daemon()
        daemon.tiler.windows[1].states = frozenset({0})
        daemon.update_panel()
        self.assertFalse(os.path.exists(ft.panel_state_path()))

    def test_panel_state_follows_the_windows(self):
        daemon = self.panel_daemon()
        path = ft.panel_state_path()
        ft.write_atomic(path, "")
        daemon.tiler.windows[1].states = frozenset({0})
        daemon.update_panel()
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), ft.PANEL_FILLED_CSS)
        daemon.tiler.windows[1].states = frozenset({0, 1})
        daemon.update_panel()
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "")

    def test_panel_state_is_not_rewritten_without_a_change(self):
        daemon = self.panel_daemon()
        ft.write_atomic(ft.panel_state_path(), "")
        with mock.patch.object(ft, "write_atomic") as write:
            daemon.update_panel()
        write.assert_not_called()

    def test_daemon_clears_a_stale_fragment_at_start(self):
        self.stale_fragment()
        with mock.patch.object(ft, "serve", return_value=0):
            ft.run_daemon()
        self.assertFalse(os.path.exists(ft.fragment_path()))
        self.reconfigure.assert_called_once_with()

    def test_second_daemon_exits(self):
        # daemon_lock() gives None while another daemon holds the lock.
        with mock.patch.object(ft, "serve") as serve, mock.patch.object(ft, "daemon_lock", return_value=None):
            self.assertEqual(ft.run_daemon(), 0)
        serve.assert_not_called()

    def test_turning_off_keeps_the_daemon_and_drops_the_fragment(self):
        daemon = ft.Daemon(ft.Settings(enabled=True))
        daemon.ready = True
        daemon.apply()
        self.assertTrue(os.path.exists(ft.fragment_path()))
        daemon.command(["toggle"], toplevels=None)
        self.assertFalse(daemon.tiler.settings.enabled)
        self.assertFalse(os.path.exists(ft.fragment_path()))
        self.assertFalse(ft.load_settings().enabled)
        daemon.command(["toggle"], toplevels=None)
        self.assertTrue(os.path.exists(ft.fragment_path()))

    def test_panel_is_signalled_only_on_a_change(self):
        daemon = ft.Daemon(ft.Settings(enabled=True))
        daemon.ready = True
        daemon.apply()
        self.assertEqual(self.signal_panel.call_count, 1)
        daemon.command(["status"], toplevels=None)
        self.assertEqual(self.signal_panel.call_count, 1)
        daemon.command(["mode", "grid"], toplevels=None)
        self.assertEqual(self.signal_panel.call_count, 2)

    def test_turning_on_hints_about_windows_already_open(self):
        daemon = ft.Daemon(ft.Settings(enabled=False))
        daemon.ready = True
        daemon.tiler.windows[100] = ft.Window(app_id="foot", mapped=True)
        daemon.command(["on"], toplevels=None)
        self.hint_untiled.assert_called_once_with(1)
        daemon.command(["off"], toplevels=None)
        daemon.tiler.windows.clear()
        daemon.command(["on"], toplevels=None)
        self.hint_untiled.assert_called_once_with(1)     # nothing floating: no second hint

    def test_tile_open_is_off_until_chosen(self):
        daemon = ft.Daemon(ft.load_settings())
        daemon.ready = True
        self.assertFalse(json.loads(daemon.command(["status"], toplevels=None))["tile_open"])
        self.assertTrue(json.loads(daemon.command(["tile-open", "on"], toplevels=None))["tile_open"])
        self.assertTrue(ft.load_settings().tile_open)
        daemon.command(["tile-open", "default"], toplevels=None)
        self.assertFalse(daemon.tiler.settings.tile_open)
        self.assertNotIn("TileOpen", open(ft.user_conf()).read())
        with self.assertRaises(ft.TilerError):
            daemon.command(["tile-open", "maybe"], toplevels=None)
        self.reconfigure.assert_not_called()            # nothing for labwc while tiling is off

    def test_settings_commands_without_a_daemon_are_saved(self):
        self.stale_fragment()
        with mock.patch.object(ft, "request", return_value=None), mock.patch("sys.stdout"):
            self.assertEqual(ft.main(["on"]), 0)
            self.assertEqual(ft.main(["mode", "grid"]), 0)
            self.assertEqual(ft.main(["tile-open", "on"]), 0)
        settings = ft.load_settings()
        self.assertTrue(settings.tile_open)
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.mode, "grid")
        # A fragment left by a daemon that died is cleared.
        self.assertFalse(os.path.exists(ft.fragment_path()))
        self.reconfigure.assert_called_once_with()

    def test_floating_through_the_daemon(self):
        ft.save_choice(floating=("pavucontrol",))
        daemon = ft.Daemon(ft.load_settings())
        daemon.ready = True
        daemon.command(["floating", "add", "gimp*"], toplevels=None)
        self.assertEqual(daemon.tiler.settings.floating, ("pavucontrol", "gimp*"))
        daemon.command(["floating", "remove", "pavucontrol"], toplevels=None)
        self.assertEqual(ft.load_settings().floating, ("gimp*",))
        with self.assertRaises(ft.TilerError):
            daemon.command(["floating", "remove", "pavucontrol"], toplevels=None)
        self.reconfigure.assert_not_called()

    def test_floating_without_a_daemon_is_saved(self):
        with mock.patch.object(ft, "request", return_value=None), mock.patch("sys.stdout"):
            self.assertEqual(ft.main(["floating", "add", "gimp*"]), 0)
        self.assertEqual(ft.load_settings().floating, ("gimp*",))
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(ft.main(["floating", "list"]), 0)
        self.assertEqual(out.getvalue(), "gimp*\n")
        with mock.patch.object(ft, "warn"):
            self.assertEqual(ft.main(["floating", "add"]), 2)

    def test_status_has_the_ratio_and_gap(self):
        ft.save_choice(ratio=60, gap=4)
        with mock.patch.object(ft, "request", return_value=None):
            status = ft.offline_status()
        self.assertEqual((status["ratio"], status["gap"]), (60, 4))

    def test_gap_through_the_daemon_rewrites_the_fragment(self):
        daemon = ft.Daemon(ft.Settings(enabled=True))
        daemon.ready = True
        daemon.apply()
        daemon.command(["gap", "99"], toplevels=None)
        self.assertEqual(ft.load_settings().gap, ft.GAP_MAX)
        self.assertIn(f"<gap>{ft.GAP_MAX}</gap>", open(ft.fragment_path()).read())
        with self.assertRaises(ft.TilerError):
            daemon.command(["gap", "wide"], toplevels=None)

    def test_gap_without_a_daemon_is_saved(self):
        with mock.patch.object(ft, "request", return_value=None), mock.patch("sys.stdout"):
            self.assertEqual(ft.main(["gap", "12"]), 0)
        self.assertEqual(ft.load_settings().gap, 12)

    def test_show_desktop_through_the_daemon(self):
        daemon = ft.Daemon(ft.load_settings())
        daemon.started()
        daemon.apply()
        open_window(daemon.tiler, 1)
        toplevels = mock.Mock()
        daemon.command(["show-desktop"], toplevels)
        toplevels.minimize.assert_called_once_with(1)
        toplevels.activate.assert_not_called()
        daemon.tiler.windows[1].states = frozenset({1})
        toplevels.reset_mock()
        daemon.command(["show-desktop"], toplevels)
        toplevels.minimize.assert_called_once_with(1, on=False)
        toplevels.activate.assert_called_once_with(1)

    def test_focus_app_through_the_daemon(self):
        daemon = ft.Daemon(ft.load_settings())
        daemon.started()
        daemon.apply()
        open_window(daemon.tiler, 1, app_id="geany")
        daemon.tiler.windows[1].states = frozenset({1})            # minimized
        toplevels = mock.Mock()
        reply = json.loads(daemon.command(["focus-app", "geany", "Geany"], toplevels))
        self.assertTrue(reply["found"])
        toplevels.minimize.assert_called_once_with(1, on=False)
        toplevels.activate.assert_called_once_with(1)
        toplevels.reset_mock()
        self.assertFalse(json.loads(daemon.command(["focus-app", "thunar"], toplevels))["found"])
        toplevels.activate.assert_not_called()

    def test_open_apps_through_the_daemon(self):
        daemon = ft.Daemon(ft.load_settings())
        daemon.started()
        daemon.apply()
        open_window(daemon.tiler, 1, app_id="Geany")
        open_window(daemon.tiler, 2, app_id="foot")
        open_window(daemon.tiler, 3, app_id="foot")
        toplevels = mock.Mock()
        reply = json.loads(daemon.command(["open-apps"], toplevels))
        self.assertEqual(reply["app_ids"], ["foot", "geany"])
        toplevels.activate.assert_not_called()
        toplevels.minimize.assert_not_called()

    def test_focus_app_exit_status(self):
        for reply, status in (({"found": True}, 0), ({"found": False}, 1), ({"error": "unknown"}, 1), (None, 1)):
            with mock.patch.object(ft, "request", return_value=reply) as request:
                self.assertEqual(ft.main(["focus-app", "geany"]), status)
            request.assert_called_once_with(["focus-app", "geany"])

    def test_other_commands_without_a_daemon_fail(self):
        for command in ("promote", "show-desktop"):
            with mock.patch.object(ft, "request", return_value=None), mock.patch.object(ft, "warn") as warn:
                self.assertEqual(ft.main([command]), 1)
            warn.assert_called_once()

    def test_menu_applies_the_arrangement_that_was_picked(self):
        """Picking any entry must reach the daemon, not only the current one."""
        seen = {}

        def fuzzel_picks(answer):
            def run(command, **kwargs):
                seen["command"] = command
                seen["entries"] = kwargs["input"].splitlines()
                return subprocess.CompletedProcess(command, 0, stdout=answer, stderr="")
            return run

        # Entry 0 is the on/off line, then one per arrangement in MODES order.
        for index, mode in ((1, "master-stack"), (2, "columns"), (4, "monocle")):
            sent = []
            with mock.patch.object(ft, "request", side_effect=lambda words: sent.append(words) or {"alt": "grid"}), \
                 mock.patch.object(ft.shutil, "which", return_value="/usr/bin/fuzzel"), \
                 mock.patch.object(ft.subprocess, "run", side_effect=fuzzel_picks(f"{index}\n")):
                self.assertEqual(ft.main(["menu"]), 0)
            self.assertIn(["mode", mode], sent)
        self.assertEqual(len(seen["entries"]), len(ft.MODES) + 1)
        # The current arrangement is marked and preselected.
        self.assertEqual(seen["entries"][3], "● Grid")
        self.assertIn("--select-index=3", seen["command"])

    def test_menu_ignores_a_cancelled_choice(self):
        for answer in ("", "\n", "-1\n", "99\n", "Grid\n"):
            sent = []
            with mock.patch.object(ft, "request", side_effect=lambda words: sent.append(words) or {"alt": "off"}), \
                 mock.patch.object(ft.shutil, "which", return_value="/usr/bin/fuzzel"), \
                 mock.patch.object(ft.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 1, stdout=answer, stderr="")):
                self.assertEqual(ft.main(["menu"]), 0)
            self.assertEqual(sent, [["status"]], answer)

    def test_menu_without_fuzzel(self):
        with mock.patch.object(ft, "request", return_value={"alt": "off"}), \
             mock.patch.object(ft.shutil, "which", return_value=None), mock.patch.object(ft, "warn") as warn:
            self.assertEqual(ft.main(["menu"]), 1)
        warn.assert_called_once()

    def test_status_without_a_daemon_is_off(self):
        ft.save_choice(enabled=True)
        with mock.patch.object(ft, "request", return_value=None):
            self.assertEqual(ft.offline_status()["alt"], "off")


class FakeLabwc:
    """Toplevels as the daemon's capture uses them: focus and sync, answered
    when the test says so; a pressed key runs the fragment's keybind."""

    def __init__(self, daemon):
        self.daemon = daemon
        self.syncs = []
        self.activated = []
        self.pressed = []

    def activate(self, handle):
        self.activated.append(handle)
        for other, window in self.daemon.tiler.windows.items():
            window.states = frozenset({2}) if other == handle else window.states - {2}

    def sync(self, handler):
        self.syncs.append(handler)

    def answer(self):
        syncs, self.syncs = self.syncs, []
        for handler in syncs:
            handler()
        self.daemon.capture_step(self)

    def press(self, key):
        self.pressed.append(key)
        tiler = self.daemon.tiler
        region = next(region for region, bound in tiler.capture.items() if bound == key)
        self.daemon.command(["snapped", region], toplevels=self)
        return True


def read_fragment():
    with open(ft.fragment_path()) as f:
        return f.read()


class CaptureTest(unittest.TestCase):
    """Turning tiling on tiles the windows open then (Daemon.capture_step)."""

    def setUp(self):
        DaemonTest.setUp(self)
        tool = os.path.join(self.tmp, "wtype")
        with open(tool, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(tool, 0o755)
        patcher = mock.patch.object(ft, "WTYPE", tool)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.daemon = ft.Daemon(ft.Settings(enabled=False, tile_open=True))
        self.daemon.ready = True
        self.labwc = FakeLabwc(self.daemon)
        patcher = mock.patch.object(ft, "press", side_effect=self.labwc.press)
        self.press = patcher.start()
        self.addCleanup(patcher.stop)
        windows = self.daemon.tiler.windows
        windows[100] = ft.Window(app_id="foot", mapped=True, states=frozenset({2}))
        windows[101] = ft.Window(app_id="mousepad", mapped=True)
        windows[102] = ft.Window(app_id="thunar", mapped=True, states=frozenset({1}))

    def test_open_windows_are_focused_and_tiled_one_by_one(self):
        daemon = self.daemon
        daemon.command(["on"], toplevels=self.labwc)
        self.assertIn('key="XF86Macro1"', read_fragment())
        self.assertEqual(self.reconfigure.call_count, 1)
        daemon.capture_step(self.labwc)                 # waits for the reload
        self.assertEqual(self.labwc.pressed, [])
        self.labwc.answer()                             # reloaded: 101 is focused
        self.assertEqual(self.labwc.activated, [101])
        self.labwc.answer()                             # pressed; then 100
        self.labwc.answer()                             # pressed; all replied
        self.assertEqual(self.labwc.activated, [101, 100])
        self.assertEqual(self.labwc.pressed, ["XF86Macro2", "XF86Macro1"])
        self.assertIsNone(daemon.capture)
        self.assertEqual(daemon.tiler.order, ["ft1", "ft2"])
        self.assertIsNone(daemon.tiler.windows[102].region)     # minimized: left alone
        daemon.apply()
        self.assertNotIn("XF86Macro", read_fragment())
        self.hint_untiled.assert_not_called()

    def test_a_key_that_doesnt_reply_lets_the_window_go(self):
        daemon = self.daemon
        self.press.side_effect = None
        self.press.return_value = True                  # pressed, but no keybind ran
        daemon.command(["on"], toplevels=self.labwc)
        for _ in range(3):
            self.labwc.answer()
        self.assertIsNotNone(daemon.capture)            # waiting for the replies
        with mock.patch.object(ft.time, "monotonic", return_value=ft.time.monotonic() + ft.CAPTURE_SECONDS + 1):
            daemon.capture_step(self.labwc)
        self.assertIsNone(daemon.capture)
        self.assertEqual(daemon.tiler.order, [])
        self.hint_untiled.assert_called_once_with(2)

    def test_a_window_that_lost_the_focus_gets_no_key(self):
        daemon = self.daemon
        daemon.command(["on"], toplevels=self.labwc)
        self.labwc.answer()
        daemon.tiler.windows[101].states = frozenset()  # something else took the focus
        self.labwc.answer()
        self.assertEqual(self.labwc.pressed, [])

    def test_turning_off_stops_the_capture(self):
        daemon = self.daemon
        daemon.command(["on"], toplevels=self.labwc)
        daemon.command(["off"], toplevels=self.labwc)
        self.assertIsNone(daemon.capture)
        self.labwc.answer()
        self.assertEqual(self.labwc.activated, [])

    def test_open_windows_stay_as_they_are_unless_chosen(self):
        self.daemon.tiler.settings.tile_open = False
        self.daemon.command(["on"], toplevels=self.labwc)
        self.assertIsNone(self.daemon.capture)
        self.assertNotIn("XF86Macro", read_fragment())
        self.assertEqual(self.labwc.activated, [])
        self.press.assert_not_called()
        self.hint_untiled.assert_called_once_with(2)

    def test_without_wtype_the_windows_stay_floating(self):
        with mock.patch.object(ft, "WTYPE", os.path.join(self.tmp, "none")):
            self.daemon.command(["on"], toplevels=self.labwc)
        self.assertIsNone(self.daemon.capture)
        self.hint_untiled.assert_called_once_with(2)


def message(object_id, opcode, payload=b""):
    return struct.pack("=II", object_id, (8 + len(payload)) << 16 | opcode) + payload


def read_message(sock):
    head = sock.recv(8)
    object_id, word = struct.unpack("=II", head)
    payload = sock.recv((word >> 16) - 8) if word >> 16 > 8 else b""
    return object_id, word & 0xFFFF, payload


class FakeDaemon:
    def __init__(self):
        self.tiler = tiler()
        self.tiler.commit()
        self.changed = False
        self.ready = False

    def started(self):
        self.ready = True


class WaylandTest(unittest.TestCase):
    """The client against a fake compositor on a socket pair."""

    def setUp(self):
        self.client, self.server = socket.socketpair()
        self.addCleanup(self.client.close)
        self.addCleanup(self.server.close)
        self.server.settimeout(2)
        self.daemon = FakeDaemon()
        self.wl = ft.Toplevels(self.client, self.daemon)

    def feed(self, *messages):
        self.server.sendall(b"".join(messages))
        self.assertTrue(self.wl.dispatch())

    def test_strings(self):
        self.assertEqual(ft.pack_string("abc"), struct.pack("=I", 4) + b"abc\0")
        self.assertEqual(ft.pack_string("abcd"), struct.pack("=I", 5) + b"abcd\0\0\0\0")
        reader = ft.Reader(ft.pack_string("abcd") + ft.pack_uint(7))
        self.assertEqual(reader.string(), "abcd")
        self.assertEqual(reader.uint(), 7)

    def test_session(self):
        registry = 2
        self.assertEqual(read_message(self.server), (1, 1, ft.pack_uint(registry)))
        self.feed(message(registry, 0, ft.pack_uint(1) + ft.pack_string("wl_seat") + ft.pack_uint(7)),
                  message(registry, 0, ft.pack_uint(2) + ft.pack_string(ft.MANAGER) + ft.pack_uint(3)))
        _, opcode, payload = read_message(self.server)          # bind wl_seat
        self.assertEqual(opcode, 0)
        seat = struct.unpack("=I", payload[-4:])[0]
        _, _, payload = read_message(self.server)               # bind manager, v3
        manager = struct.unpack("=I", payload[-4:])[0]
        self.assertEqual(struct.unpack("=I", payload[-8:-4])[0], 3)
        _, opcode, payload = read_message(self.server)          # wl_display.sync
        callback = struct.unpack("=I", payload)[0]

        # A window that was already open, then the sync is done.
        old = 0xFF000000
        self.feed(message(manager, 0, ft.pack_uint(old)), message(old, 1, ft.pack_string("mousepad")),
                  message(old, 5), message(callback, 0, ft.pack_uint(0)))
        self.assertTrue(self.daemon.ready)
        self.assertIsNone(self.daemon.tiler.windows[old].region)

        # A new window: tiled to the rule region, and focusable.
        new = 0xFF000001
        states = struct.pack("=I", 8) + struct.pack("=II", 2, 0)
        self.feed(message(manager, 0, ft.pack_uint(new)), message(new, 1, ft.pack_string("foot")),
                  message(new, 4, states), message(new, 5))
        self.assertTrue(self.daemon.changed)
        self.assertEqual(self.daemon.tiler.windows[new].region, "ft1")
        self.assertEqual(self.daemon.tiler.focused(), new)
        self.wl.activate(new)
        self.assertEqual(read_message(self.server), (new, 4, ft.pack_uint(seat)))
        self.wl.minimize(new)
        self.assertEqual(read_message(self.server), (new, 2, b""))
        self.wl.minimize(new, on=False)
        self.assertEqual(read_message(self.server), (new, 3, b""))

        # Closed: the client destroys the handle.
        self.daemon.changed = False
        self.feed(message(new, 6))
        self.assertTrue(self.daemon.changed)
        self.assertNotIn(new, self.daemon.tiler.windows)
        self.assertEqual(read_message(self.server), (new, 7, b""))

    def test_partial_message_waits(self):
        data = message(1, 1, ft.pack_uint(5))
        self.server.sendall(data[:6])
        self.assertTrue(self.wl.dispatch())
        self.server.sendall(data[6:])
        self.assertTrue(self.wl.dispatch())
        self.assertEqual(self.wl.buffer, b"")

    def test_protocol_error(self):
        self.server.sendall(message(1, 0, ft.pack_uint(3) + ft.pack_uint(1) + ft.pack_string("bad")))
        with self.assertRaises(ft.TilerError):
            self.wl.dispatch()


if __name__ == "__main__":
    unittest.main()


class HistoryTest(unittest.TestCase):
    """Changes are recorded for Settings > History (flickos-control), in the
    format flickos-control reads (docs/design/flickos-history.md, ADR-002)."""

    def setUp(self):
        DaemonTest.setUp(self)      # its setup, not its tests
        state = os.path.join(self.tmp, "state")
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": state})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.history = os.path.join(state, "flickos/history.jsonl")

    def entries(self):
        try:
            with open(self.history, encoding="utf-8") as f:
                return [(e["owner"], e["key"], e["old"], e["new"]) for e in map(json.loads, f)]
        except FileNotFoundError:
            return []

    def test_changes_that_show_are_recorded(self):
        daemon = ft.Daemon(ft.Settings(enabled=False))
        daemon.command(["on"], toplevels=None)
        daemon.command(["on"], toplevels=None)              # no change
        daemon.command(["mode", "grid"], toplevels=None)
        daemon.command(["ratio", "+5"], toplevels=None)
        daemon.command(["gap", "4"], toplevels=None)
        daemon.command(["floating", "add", "gimp*"], toplevels=None)
        daemon.command(["tile-open", "on"], toplevels=None)
        self.assertEqual(self.entries(), [
            ("flick-tiler", "enabled", "off", "on"),
            ("flick-tiler", "mode", "default", "grid"),
            ("flick-tiler", "ratio", "default", "60"),
            ("flick-tiler", "gap", "default", "4"),
            ("flick-tiler", "floating", "", "gimp*"),
            ("flick-tiler", "tile-open", "off", "on"),
        ])

    def test_default_removes_the_users_value(self):
        daemon = ft.Daemon(ft.Settings(enabled=True))
        daemon.command(["mode", "grid"], toplevels=None)
        daemon.command(["ratio", "70"], toplevels=None)
        for key in ("mode", "ratio", "gap"):
            daemon.command([key, "default"], toplevels=None)
        self.assertEqual(ft.read_ini(ft.user_conf()), {})
        settings = daemon.tiler.settings
        self.assertEqual((settings.mode, settings.ratio, settings.gap), (ft.DEFAULT_MODE, 55, 8))
        self.assertEqual(self.entries()[-2:], [("flick-tiler", "mode", "grid", "default"),
                                               ("flick-tiler", "ratio", "70", "default")])

    def test_without_a_daemon(self):
        with mock.patch.object(ft, "request", return_value=None), mock.patch("sys.stdout"):
            self.assertEqual(ft.main(["ratio", "65"]), 0)
            self.assertEqual(ft.main(["ratio", "--", "-10"]), 0)
            self.assertEqual(ft.main(["mode", "default"]), 0)       # nothing to change
            self.assertEqual(ft.main(["gap", "default"]), 0)
        self.assertEqual(ft.load_settings().ratio, 55)
        self.assertEqual(self.entries(), [("flick-tiler", "ratio", "default", "65"),
                                          ("flick-tiler", "ratio", "65", "55")])

    def test_off(self):
        with open(ft.HISTORY_CONF, "w") as f:
            f.write("[History]\nEnabled=no\n")
        self.addCleanup(os.unlink, ft.HISTORY_CONF)
        ft.save_choice(enabled=True)
        self.assertEqual(self.entries(), [])

    def test_the_site_can_turn_it_off(self):
        with open(ft.HISTORY_SITE_CONF, "w") as f:
            f.write("[History]\nEnabled=no\n")
        self.addCleanup(os.unlink, ft.HISTORY_SITE_CONF)
        ft.save_choice(enabled=True)
        self.assertEqual(self.entries(), [])

    def test_a_history_that_cant_be_written_never_stops_the_change(self):
        os.makedirs(os.path.join(self.tmp, "state"))
        with open(os.path.join(self.tmp, "state/flickos"), "w") as f:
            f.write("a file where the folder should be\n")
        with mock.patch.object(ft, "warn") as warn:
            ft.save_choice(gap=12)
        self.assertIn("history can't be written", warn.call_args.args[0])
        self.assertEqual(ft.load_settings().gap, 12)
