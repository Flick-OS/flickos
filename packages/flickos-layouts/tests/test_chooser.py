"""Tests for the layout chooser (flickos-layout pick). Run: python3 -m unittest discover -s tests

The GTK window itself is covered by the boot test; here GTK is never started.
"""

import configparser
import contextlib
import io
import os
import struct
import sys
import unittest
from unittest import mock

from test_engine import PACKAGE, EngineTest, fl

LAYOUTS = os.path.join(PACKAGE, "usr/share/flickos/layouts")
DESKTOP_FILE = os.path.join(PACKAGE, "usr/share/applications/flickos-layout.desktop")


def png_size(path):
    with open(path, "rb") as f:
        header = f.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", header[16:24])


class ChooserTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_layout("flickos", order=10)
        self.make_layout("mac", order=20, extra="Preview=preview.png\n")

    def test_preview_path(self):
        self.assertIsNone(self.layout("flickos").preview)
        self.assertEqual(self.layout("mac").preview, os.path.join(self.layouts_dir, "mac/preview.png"))

    def test_single_instance(self):
        with fl.single_instance("pick.lock") as first:
            self.assertTrue(first)
            with fl.single_instance("pick.lock") as second:
                self.assertFalse(second)
        with fl.single_instance("pick.lock") as again:
            self.assertTrue(again)
        del os.environ["XDG_RUNTIME_DIR"]
        with fl.single_instance("pick.lock") as no_runtime:
            self.assertTrue(no_runtime)

    def test_second_pick_exits_without_a_window(self):
        with mock.patch.object(fl, "pick_gtk") as gtk, fl.single_instance("pick.lock"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fl.main(["pick"]), 0)
        gtk.assert_not_called()
        self.assertIn("already open", out.getvalue())

    def test_pick_uses_gtk_then_fuzzel(self):
        with mock.patch.object(fl, "pick_gtk", return_value=0) as gtk, \
                mock.patch.object(fl, "pick_fuzzel") as fuzzel:
            self.assertEqual(fl.main(["pick"]), 0)
        layouts, current, styles, current_style, current_clicks = gtk.call_args.args
        self.assertEqual((list(layouts), current, list(styles), current_style, current_clicks),
                         (["flickos", "mac"], "flickos", ["dark"], "dark", "right-menu"))
        fuzzel.assert_not_called()

        self.set_user_choice("mac")
        self.make_light_style()
        self.set_user_choice("light", kind="style")
        self.set_user_choice("both-menu", kind="clicks")
        with mock.patch.object(fl, "pick_gtk", return_value=None), \
                mock.patch.object(fl, "pick_fuzzel", return_value=0) as fuzzel:
            self.assertEqual(fl.main(["pick"]), 0)
        self.assertEqual(fuzzel.call_args.args[1::2] + fuzzel.call_args.args[4:], ("mac", "light", "both-menu"))

        with mock.patch.object(fl, "pick_gtk", return_value=None), \
                mock.patch.object(fl, "pick_fuzzel", return_value=None), self.quiet():
            self.assertEqual(fl.main(["pick"]), 1)

    def test_gtk_missing(self):
        with mock.patch.dict(sys.modules, {"gi": None}), self.quiet():
            self.assertIsNone(fl.pick_gtk(fl.layouts(), "flickos", fl.styles(), "dark", "right-menu"))

    def test_set_messages(self):
        self.assertEqual(fl.set_messages("Layout 'Mac' applied.\n", "flickos-layout: a warning\n\n"),
                         ["Layout 'Mac' applied.", "a warning"])

    def fuzzel(self, selections, set_result=None):
        """Run pick_fuzzel with fuzzel printing selections (layout, then style).
        Returns (status, run mock, notify mock)."""
        self.make_light_style()
        results = [mock.Mock(stdout=selection) for selection in selections]
        if set_result:
            results.append(set_result)
        with mock.patch.object(fl.shutil, "which", return_value="/usr/bin/fuzzel"), \
                mock.patch.object(fl.subprocess, "run", side_effect=results) as run, \
                mock.patch.object(fl, "notify") as notify:
            status = fl.pick_fuzzel(fl.layouts(), "flickos", fl.styles(), "dark")
        return status, run, notify

    def test_fuzzel_applies_selection(self):
        done = mock.Mock(returncode=0, stdout="Layout 'Mac' applied.\n", stderr="flickos-layout: note\n")
        status, run, notify = self.fuzzel(["1\n", "0\n"], done)
        self.assertEqual(status, 0)
        command = run.call_args_list[0].args[0]
        self.assertEqual(command[:3], ["fuzzel", "--dmenu", "--index"])
        self.assertIn("--select-index=0", command)
        entries = run.call_args_list[0].kwargs["input"].splitlines()
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0].startswith("Flickos (current): The flickos layout\0icon\x1f"))
        styles = run.call_args_list[1].kwargs["input"].splitlines()
        self.assertTrue(styles[0].startswith("Dark (current): The dark style\0"))
        self.assertEqual(run.call_args_list[2].args[0][-2:], ["set", "mac"])
        notify.assert_called_once_with(fl.CHOOSER_TITLE, ["Layout 'Mac' applied.", "note"])

    def test_fuzzel_style_only(self):
        done = mock.Mock(returncode=0, stdout="Style 'Light' applied.\n", stderr="")
        status, run, _ = self.fuzzel(["0\n", "1\n"], done)
        self.assertEqual(status, 0)
        self.assertEqual(run.call_args_list[2].args[0][-3:], ["set", "--style", "light"])

    def test_fuzzel_failed_set_is_reported(self):
        done = mock.Mock(returncode=1, stdout="", stderr="flickos-layout: broken\n")
        status, _, notify = self.fuzzel(["1\n", "1\n"], done)
        self.assertEqual(status, 1)
        self.assertIn("Could not apply", notify.call_args.args[0])

    def test_fuzzel_cancel_or_current_does_nothing(self):
        for selections, menus in ((["", ""], 1), (["7\n", ""], 1), (["1\n", ""], 2), (["0\n", "0\n"], 2)):
            status, run, notify = self.fuzzel(selections)
            self.assertEqual(status, 0)
            self.assertEqual(run.call_count, menus)
            notify.assert_not_called()

    def test_without_fuzzel(self):
        with mock.patch.object(fl.shutil, "which", return_value=None):
            self.assertIsNone(fl.pick_fuzzel(fl.layouts(), "flickos", fl.styles(), "dark"))

    def test_apply_command(self):
        with mock.patch.object(fl, "self_command", lambda *args: list(args)):
            current = ("a", "dark", "right-menu")
            self.assertIsNone(fl.apply_command(current, current))
            self.assertEqual(fl.apply_command(("b", "dark", "right-menu"), current), ["set", "b"])
            self.assertEqual(fl.apply_command(("b", "light", "right-menu"), current), ["set", "b", "--style", "light"])
            self.assertEqual(fl.apply_command(("a", "light", "right-menu"), current), ["set", "--style", "light"])
            self.assertEqual(fl.apply_command(("a", "dark", "both-menu"), current), ["set", "--clicks", "both-menu"])
            self.assertEqual(fl.apply_command(("b", "light", "both-menu"), current),
                             ["set", "b", "--style", "light", "--clicks", "both-menu"])

    def test_palette_colors(self):
        path = self.write("palette.css", "/* @define-color no #000000; */\n@define-color wm_bg #FF0080;\n"
                                         "@define-color named @wm_bg;\n")
        colors = fl.palette_colors(path)
        self.assertEqual(colors["wm_bg"], (1.0, 0.0, 128 / 255))
        self.assertNotIn("named", colors)
        self.assertEqual(fl.palette_colors(self.path("missing.css")), {})


class FirstRunTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_layout("flickos", order=10)
        self.marker = self.write("home/.config/flickos/choose-layout", "# marker\n")
        self.cmdline = self.write("proc/cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=1234 ro quiet splash\n")
        patcher = mock.patch.object(fl, "PROC", self.path("proc"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def first_run(self):
        with mock.patch.object(fl, "cmd_pick", return_value=0) as pick:
            self.assertEqual(fl.main(["first-run"]), 0)
        return pick

    def test_new_account_sees_chooser_once(self):
        self.first_run().assert_called_once()
        self.assertFalse(os.path.exists(self.marker))
        self.first_run().assert_not_called()

    def test_marker_deleted_before_chooser_opens(self):
        with mock.patch.object(fl, "cmd_pick", side_effect=lambda _opts: self.assertFalse(
                os.path.exists(self.marker)) or 0) as pick:
            self.assertEqual(fl.main(["first-run"]), 0)
        pick.assert_called_once()

    def test_no_marker(self):
        os.unlink(self.marker)
        self.first_run().assert_not_called()

    def test_layout_already_chosen(self):
        self.set_user_choice("flickos")
        self.first_run().assert_not_called()
        self.assertFalse(os.path.exists(self.marker))

    def test_live_session(self):
        self.write("proc/cmdline", "BOOT_IMAGE=/live/vmlinuz boot=live components quiet splash\n")
        self.first_run().assert_not_called()
        self.assertFalse(os.path.exists(self.marker))

    def test_live_system(self):
        self.assertFalse(fl.live_system())
        for text, live in (("boot=live components", True), ("noboot=live", False),
                           ("boot=local", False), ("quiet boot=live", True)):
            with self.subTest(cmdline=text):
                self.write("proc/cmdline", text + "\n")
                self.assertEqual(fl.live_system(), live)
        os.unlink(self.cmdline)
        self.assertFalse(fl.live_system())


class ShippedChooserFilesTest(unittest.TestCase):

    def test_first_run_marker_in_skel(self):
        marker = os.path.join(PACKAGE, "etc/skel/.config/flickos", fl.FIRST_RUN_MARKER)
        self.assertTrue(os.path.isfile(marker))
        with open(os.path.join(PACKAGE, "debian/install"), encoding="utf-8") as f:
            sources = [line.split()[0] for line in f if line.strip() and not line.startswith("#")]
        self.assertIn(os.path.relpath(marker, PACKAGE), sources)

    def test_every_layout_has_a_preview(self):
        with mock.patch.object(fl, "layout_dirs", lambda users=None: [LAYOUTS]), contextlib.redirect_stderr(io.StringIO()):
            found = fl.layouts()
        self.assertTrue(found)
        for layout in found.values():
            with self.subTest(layout=layout.id):
                self.assertIsNotNone(layout.preview)
                self.assertEqual(png_size(layout.preview), (fl.PREVIEW_WIDTH, fl.PREVIEW_HEIGHT))

    def test_desktop_file(self):
        ini = configparser.ConfigParser(interpolation=None)
        ini.optionxform = str
        ini.read(DESKTOP_FILE, encoding="utf-8")
        entry = ini["Desktop Entry"]
        self.assertEqual(entry["Exec"], "flickos-layout pick")
        self.assertEqual(entry["Name"], fl.CHOOSER_TITLE)
        self.assertEqual(entry["Icon"], fl.CHOOSER_ICON)
        self.assertIn("Settings", entry["Categories"].split(";"))


if __name__ == "__main__":
    unittest.main()
