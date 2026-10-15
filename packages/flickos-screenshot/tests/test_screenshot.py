"""Tests for usr/bin/flickos-screenshot. Run: python3 -m unittest discover -s tests

They run on the maintainer's desktop too, so they never touch its session:
grim, wl-copy, notify-send, xdg-user-dir and xdg-open are stub scripts in a
temporary PATH, and every XDG folder and HOME point into a temporary folder.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
PROGRAM = os.path.join(PACKAGE, "usr/bin/flickos-screenshot")
CHOOSER = "usr/libexec/flickos/screencast-chooser"

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_screenshot", PROGRAM)
fs = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fs)
RealFeedback = fs.Feedback              # Sandbox replaces it
RealNotify = fs.notify                  # and this

# cairo, to check what the markup window writes: the build doesn't have it.
try:
    import cairo
except ImportError:
    cairo = None

# GStreamer, only to check that the pipelines parse: the build doesn't have it.
try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst as GST
    GST.init(None)
    if not all(GST.ElementFactory.find(element) for element in fs.ELEMENTS):
        GST = None
except (ImportError, ValueError):
    GST = None

# Stub programs: each records its arguments (and stdin) in $STUB_LOG/NAME.
STUBS = {
    "grim": 'echo "$@" >> "$STUB_LOG/grim"\n'
            'for last; do :; done\n'
            '[ -n "$GRIM_FAILS" ] && { echo "grim: failed to create display" >&2; exit 1; }\n'
            'printf "picture" > "$last"\n',
    "wl-copy": 'echo "$@" >> "$STUB_LOG/wl-copy"\n/bin/cat > "$STUB_LOG/clipboard"\n'
               '[ -z "$WL_COPY_FAILS" ]\n',
    "notify-send": 'printf "%s\\n" "$@" > "$STUB_LOG/notify-send"\n'
                   '[ -n "$NOTIFY_ANSWER" ] && echo "$NOTIFY_ANSWER"\nexit 0\n',
    "xdg-user-dir": 'case "$1" in VIDEOS) echo "$VIDEOS_DIR" ;; *) echo "$PICTURES_DIR" ;; esac\n',
    "wlr-randr": '[ -n "$WLR_RANDR_FAILS" ] && exit 1\nprintf "%s" "$WLR_RANDR_JSON"\n',
    "xdg-open": 'echo "$@" >> "$STUB_LOG/xdg-open"\n',
}


class Sandbox(unittest.TestCase):
    """A fake home, runtime folder and PATH for every test."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="flickos-screenshot-test-")
        self.addCleanup(shutil.rmtree, self.root)
        self.home = os.path.join(self.root, "home")
        self.runtime = os.path.join(self.root, "run")
        self.bin = os.path.join(self.root, "bin")
        self.log = os.path.join(self.root, "log")
        for folder in (self.home, self.runtime, self.bin, self.log):
            os.makedirs(folder)
        for name, body in STUBS.items():
            self.stub(name, body)
        self.pictures = os.path.join(self.home, "Pictures")
        env = {
            "HOME": self.home, "XDG_RUNTIME_DIR": self.runtime,
            "XDG_STATE_HOME": os.path.join(self.home, ".local/state"),
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            # The stubs only: /bin is /usr/bin on Debian, which has the real
            # grim and wl-copy. The stubs call anything else by its path.
            "PATH": self.bin, "STUB_LOG": self.log, "PICTURES_DIR": self.pictures,
            "VIDEOS_DIR": os.path.join(self.home, "Videos"), "WLR_RANDR_JSON": "[]",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("GRIM_FAILS", "WL_COPY_FAILS", "NOTIFY_ANSWER", "WLR_RANDR_FAILS", "WAYLAND_DISPLAY",
                    "DISPLAY"):
            os.environ.pop(var, None)
        # The notification child would outlive the test: record it instead.
        self.notices = []
        patcher = mock.patch.object(fs, "notify", lambda notice, target=None, **fields:
                                    self.notices.append((notice, target, fields)))
        patcher.start()
        self.addCleanup(patcher.stop)
        # So would the sound and flash child: record what it is told.
        self.feedbacks = []
        sandbox = self

        class Feedback:
            def __init__(self):
                sandbox.feedbacks.append("started")

            def show(self, area=None):
                sandbox.feedbacks.append(("show", area))

            def close(self):
                pass

        patcher = mock.patch.object(fs, "Feedback", Feedback)
        patcher.start()
        self.addCleanup(patcher.stop)
        # waybar is looked for in a fake /proc, never the desktop's.
        self.proc = os.path.join(self.root, "proc")
        os.makedirs(self.proc)
        patcher = mock.patch.object(fs, "PROC", self.proc)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Never the build host's settings or its History switch.
        for name in ("SYSTEM_CONF", "HISTORY_CONF"):
            patcher = mock.patch.object(fs, name, os.path.join(self.root, name.lower()))
            patcher.start()
            self.addCleanup(patcher.stop)

    def history(self):
        path = os.path.join(os.environ["XDG_STATE_HOME"], "flickos", "history.jsonl")
        try:
            with open(path, encoding="utf-8") as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def stub(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def fake_process(self, pid, comm, cmdline=b""):
        folder = os.path.join(self.proc, str(pid))
        os.makedirs(folder)
        with open(os.path.join(folder, "comm"), "w") as f:
            f.write(comm + "\n")
        with open(os.path.join(folder, "cmdline"), "wb") as f:
            f.write(cmdline)

    def logged(self, name):
        path = os.path.join(self.log, name)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return f.read()

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fs.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class GeometryTest(unittest.TestCase):
    def test_union(self):
        self.assertEqual(fs.union([(0, 0, 1366, 768), (1366, 0, 1920, 1080)]), (0, 0, 3286, 1080))

    def test_corners_in_any_order(self):
        self.assertEqual(fs.corners((50, 80), (10, 20)), (10, 20, 40, 60))
        self.assertEqual(fs.corners((10, 80), (50, 20)), (10, 20, 40, 60))

    def test_scale_one_origin_zero(self):
        self.assertEqual(fs.to_pixels((100, 100, 800, 400), (0, 0, 1920, 1080), (1920, 1080)),
                         (100, 100, 800, 400))

    def test_layout_origin_not_zero(self):
        """The maintainer's HDMI screen at 1366,0 with the laptop's screen off."""
        box = (1366, 0, 1920, 1080)
        self.assertEqual(fs.to_pixels((1466, 100, 800, 400), box, (1920, 1080)), (100, 100, 800, 400))
        self.assertEqual(fs.to_pixels(box, box, (1920, 1080)), (0, 0, 1920, 1080))

    def test_scale_two(self):
        """grim draws the layout at the highest scale: 2 for a HiDPI screen."""
        self.assertEqual(fs.to_pixels((100, 50, 300, 200), (0, 0, 1280, 800), (2560, 1600)),
                         (200, 100, 600, 400))

    def test_negative_origin(self):
        box = (-1920, 0, 3840, 1080)
        self.assertEqual(fs.to_pixels((-100, 0, 200, 50), box, (3840, 1080)), (1820, 0, 200, 50))

    def test_area_across_two_screens(self):
        rects = [(0, 0, 1366, 768), (1366, 0, 1920, 1080)]
        box = fs.union(rects)
        self.assertEqual(fs.to_pixels((1300, 100, 200, 100), box, (3286, 1080)), (1300, 100, 200, 100))

    def test_clamped_to_the_picture(self):
        self.assertEqual(fs.to_pixels((-50, -50, 100, 100), (0, 0, 100, 100), (100, 100)), (0, 0, 50, 50))
        self.assertEqual(fs.to_pixels((90, 90, 50, 50), (0, 0, 100, 100), (100, 100)), (90, 90, 10, 10))

    def test_monitor_at(self):
        rects = [(0, 0, 1366, 768), (1366, 0, 1920, 1080)]
        self.assertEqual(fs.monitor_at((10, 10), rects), 0)
        self.assertEqual(fs.monitor_at((1366, 10), rects), 1)
        # Below the smaller screen: the nearest one.
        self.assertEqual(fs.monitor_at((100, 1000), rects), 0)
        self.assertEqual(fs.monitor_at((1400, 1000), rects), 1)

    def test_clamp_point(self):
        box = (0, 0, 100, 50)
        self.assertEqual(fs.clamp_point((-5, 70), box), (0, 49))
        self.assertEqual(fs.clamp_point((20, 20), box), (20, 20))


class SaveTest(Sandbox):
    def source(self, content=b"png"):
        path = os.path.join(self.root, "shot.png")
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_name_and_folder_created(self):
        folder = os.path.join(self.pictures, "Screenshots")
        path = fs.save_picture(self.source(), folder, when=0)
        self.assertEqual(os.path.dirname(path), folder)
        self.assertRegex(os.path.basename(path), r"^Screenshot \d{4}-\d\d-\d\d \d\d-\d\d-\d\d\.png$")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"png")

    def test_never_overwrites(self):
        folder = os.path.join(self.root, "out")
        first = fs.save_picture(self.source(b"one"), folder, when=0)
        second = fs.save_picture(self.source(b"two"), folder, when=0)
        third = fs.save_picture(self.source(b"three"), folder, when=0)
        self.assertEqual(second, first[:-4] + " (2).png")
        self.assertEqual(third, first[:-4] + " (3).png")
        with open(first, "rb") as f:
            self.assertEqual(f.read(), b"one")

    def test_no_temporary_file_left(self):
        folder = os.path.join(self.root, "out")
        fs.save_picture(self.source(), folder, when=0)
        self.assertEqual([n for n in os.listdir(folder) if n.startswith(".")], [])

    def test_unwritable_folder_raises(self):
        folder = os.path.join(self.root, "locked")
        os.makedirs(folder)
        os.chmod(folder, 0o500)
        self.addCleanup(os.chmod, folder, 0o700)
        if os.access(folder, os.W_OK):
            self.skipTest("running as root")
        with self.assertRaises(OSError):
            fs.save_picture(self.source(), folder)

    def test_pictures_dir(self):
        self.assertEqual(fs.pictures_dir(), os.path.join(self.pictures, "Screenshots"))

    def test_pictures_dir_unset_means_home_pictures(self):
        """xdg-user-dir answers the home folder when PICTURES isn't set."""
        os.environ["PICTURES_DIR"] = self.home
        self.assertEqual(fs.pictures_dir(), os.path.join(self.home, "Pictures", "Screenshots"))

    def test_pictures_dir_without_xdg_user_dir(self):
        os.unlink(os.path.join(self.bin, "xdg-user-dir"))
        self.assertEqual(fs.pictures_dir(), os.path.join(self.home, "Pictures", "Screenshots"))

    def test_shown_folder(self):
        self.assertEqual(fs.shown_folder(os.path.join(self.home, "Pictures", "Screenshots")),
                         "Pictures/Screenshots")
        self.assertEqual(fs.shown_folder("/mnt/shots"), "/mnt/shots")


class LastTest(Sandbox):
    def test_default(self):
        self.assertEqual(fs.read_last(), 0)

    def test_remembered(self):
        fs.write_last(5)
        self.assertEqual(fs.read_last(), 5)
        with open(fs.state_path()) as f:
            self.assertEqual(f.read(), "delay=5\n")
        fs.write_last(3)
        self.assertEqual(fs.read_last(), 3)

    def test_broken_or_old_sound_line_is_the_default(self):
        """sound= was the bar's memory until the sound became a setting."""
        os.makedirs(os.path.dirname(fs.state_path()))
        for text in ("delay=7\nsound=loud\n", "delay=5\nsound=computer\n", "delay=soon\n", "\x00\x01", ""):
            with open(fs.state_path(), "w") as f:
                f.write(text)
            expected = 5 if text.startswith("delay=5\n") else 0
            self.assertEqual(fs.read_last(), expected, text)

    def test_delay_argument(self):
        self.assertEqual(fs.delay_seconds("10"), 10)
        for text in ("-1", "61", "abc", "2.5"):
            with self.assertRaises(fs.argparse.ArgumentTypeError):
                fs.delay_seconds(text)


class SettingsTest(Sandbox):
    """get/set/state, and the History line each change appends."""

    def changes(self):
        return [(entry["owner"], entry["key"], entry["old"], entry["new"]) for entry in self.history()]

    def test_defaults_and_no_user_file(self):
        settings = fs.load_settings()
        self.assertEqual(settings.folder, os.path.join(self.pictures, "Screenshots"))
        self.assertEqual(settings.recordings_folder, os.path.join(self.home, "Videos", "Screen Recordings"))
        self.assertEqual((settings.pointer, settings.sound, settings.user_keys), (False, "none", frozenset()))
        self.assertFalse(os.path.exists(fs.user_conf()))
        code, out, err = self.run_main("get", "pointer")
        self.assertEqual((code, out, err), (0, "no\n", ""))
        state = json.loads(self.run_main("state")[1])
        self.assertEqual(state["sound"], {"value": "none", "default": True})
        self.assertTrue(state["folder"]["default"])
        self.assertEqual(state["folder"]["value"], settings.folder)

    def test_system_file_then_the_users(self):
        with open(fs.SYSTEM_CONF, "w", encoding="utf-8") as f:
            f.write("[Screenshot]\nPointer=yes\nSound=computer\nFolder=/srv/shots\n")
        self.assertEqual(fs.load_settings().pointer, True)
        self.assertEqual(fs.load_settings().sound, "computer")
        self.assertEqual(fs.load_settings().folder, "/srv/shots")
        self.assertEqual(self.run_main("set", "pointer", "no")[0], 0)
        self.assertEqual(fs.load_settings().pointer, False)       # the user wins
        self.assertEqual(fs.load_settings().sound, "computer")    # the system still
        self.assertEqual(self.run_main("set", "pointer", "default")[0], 0)
        self.assertTrue(fs.load_settings().pointer)               # the system's again
        self.assertFalse(os.path.exists(fs.user_conf()))          # nothing of the user's left

    def test_set_records_and_default_removes_the_choice(self):
        folder = os.path.join(self.home, "Shots")
        self.assertEqual(self.run_main("set", "pointer", "yes")[0], 0)
        self.assertEqual(self.run_main("set", "sound", "both")[0], 0)
        self.assertEqual(self.run_main("set", "folder", folder)[0], 0)
        self.assertEqual(self.run_main("set", "folder", "~/Shots")[0], 0)   # the same folder
        self.assertEqual(self.run_main("set", "sound", "both")[0], 0)       # no change
        self.assertEqual(fs.load_settings().user_keys, frozenset({"pointer", "sound", "folder"}))
        with open(fs.user_conf(), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("flickos-screenshot set KEY VALUE", text)
        self.assertIn("Pointer=yes\n", text)
        self.assertEqual(self.changes(), [
            ("flickos-screenshot", "pointer", "no", "yes"),
            ("flickos-screenshot", "sound", "none", "both"),
            ("flickos-screenshot", "folder", "default", folder)])
        self.assertEqual(os.stat(os.path.join(os.environ["XDG_STATE_HOME"], "flickos", "history.jsonl")).st_mode
                         & 0o777, 0o600)
        entry = self.history()[0]
        self.assertEqual(entry["v"], 1)
        self.assertTrue(all(isinstance(entry[field], str) for field in ("id", "time", "owner", "key", "old", "new")))
        self.assertEqual(self.run_main("set", "folder", "default")[0], 0)
        self.assertEqual(self.run_main("set", "pointer", "default")[0], 0)
        self.assertEqual(self.run_main("set", "sound", "default")[0], 0)
        self.assertEqual(fs.load_settings().user_keys, frozenset())
        self.assertFalse(os.path.exists(fs.user_conf()))
        self.assertEqual(self.changes()[-3:], [
            ("flickos-screenshot", "folder", folder, "default"),
            ("flickos-screenshot", "pointer", "yes", "no"),
            ("flickos-screenshot", "sound", "both", "none")])

    def test_bad_values_change_nothing(self):
        taken = os.path.join(self.home, "not-a-folder")
        with open(taken, "w", encoding="utf-8") as f:
            f.write("x")
        for argv in (["set", "pointer", "maybe"], ["set", "sound", "loud"],
                     ["set", "folder", "Shots"], ["set", "folder", taken],
                     ["set", "recordings-folder", ""]):
            code, _out, err = self.run_main(*argv)
            self.assertEqual(code, 1, argv)
            self.assertTrue(err.startswith("flickos-screenshot: "), argv)
        self.assertEqual(self.history(), [])
        self.assertFalse(os.path.exists(fs.user_conf()))

    def test_broken_file_is_the_defaults(self):
        os.makedirs(os.path.dirname(fs.user_conf()))
        with open(fs.user_conf(), "w", encoding="utf-8") as f:
            f.write("\x00\x01")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            settings = fs.load_settings()
        self.assertIn("screenshot:", err.getvalue())
        self.assertEqual((settings.pointer, settings.sound), (False, "none"))
        with open(fs.SYSTEM_CONF, "w", encoding="utf-8") as f:
            f.write("[Screenshot]\nPointer=maybe\nSound=loud\nFolder=relative\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            settings = fs.load_settings()
        self.assertEqual((settings.pointer, settings.sound), (False, "none"))
        self.assertEqual(settings.folder, os.path.join(self.pictures, "Screenshots"))
        self.assertIn("pointer:", err.getvalue())
        self.assertIn("sound:", err.getvalue())
        self.assertIn("folder:", err.getvalue())

    def test_history_off(self):
        with open(fs.HISTORY_CONF, "w", encoding="utf-8") as f:
            f.write("[History]\nEnabled=no\n")
        self.assertEqual(self.run_main("set", "pointer", "yes")[0], 0)
        self.assertTrue(fs.load_settings().pointer)
        self.assertEqual(self.history(), [])


class ShotScreenTest(Sandbox):
    def test_saved_copied_and_notified(self):
        code, out, _err = self.run_main("shot", "screen")
        self.assertEqual(code, 0)
        saved = out.strip()
        self.assertTrue(saved.startswith(os.path.join(self.pictures, "Screenshots", "Screenshot ")))
        with open(saved) as f:
            self.assertEqual(f.read(), "picture")
        self.assertEqual(self.logged("grim").split()[:2], ["-t", "png"])
        self.assertEqual(self.logged("wl-copy").strip(), "--type image/png")
        self.assertEqual(self.logged("clipboard"), "picture")
        self.assertEqual(self.notices, [("saved", saved, {"folder": "Pictures/Screenshots"})])
        # The sound and the flash, over every screen.
        self.assertEqual(self.feedbacks, ["started", ("show", None)])
        # Nothing is left in the runtime folder but the (empty) folder itself.
        self.assertEqual(os.listdir(os.path.join(self.runtime, "flickos", "screenshot")), [])

    def test_runtime_folder_is_private(self):
        self.run_main("shot", "screen")
        mode = os.stat(os.path.join(self.runtime, "flickos", "screenshot")).st_mode
        self.assertEqual(stat.S_IMODE(mode), 0o700)

    def test_pointer(self):
        self.run_main("shot", "screen", "--pointer")
        self.assertIn("-c", self.logged("grim").split())

    def test_the_pointer_and_folder_settings(self):
        folder = os.path.join(self.home, "Shots")
        self.assertEqual(self.run_main("set", "folder", folder)[0], 0)
        self.assertEqual(self.run_main("set", "pointer", "yes")[0], 0)
        code, out, _err = self.run_main("shot", "screen")
        self.assertEqual(code, 0)
        self.assertTrue(out.strip().startswith(folder + os.sep))
        self.assertIn("-c", self.logged("grim").split())

    def test_copy_only_is_not_saved(self):
        code, out, _err = self.run_main("shot", "screen", "--copy-only")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertFalse(os.path.exists(os.path.join(self.pictures, "Screenshots")))
        last = os.path.join(self.runtime, "flickos", "screenshot", "last.png")
        self.assertTrue(os.path.exists(last))
        self.assertEqual(self.notices, [("copied", last, {})])

    def test_not_copied_still_saved(self):
        os.environ["WL_COPY_FAILS"] = "1"
        code, out, _err = self.run_main("shot", "screen")
        self.assertEqual(code, 0)
        self.assertEqual(self.notices[0][0], "not-copied")
        self.assertTrue(os.path.exists(out.strip()))

    def test_not_saved_still_copied(self):
        os.makedirs(self.pictures)
        os.chmod(self.pictures, 0o500)
        self.addCleanup(os.chmod, self.pictures, 0o700)
        if os.access(self.pictures, os.W_OK):
            self.skipTest("running as root")
        code, _out, _err = self.run_main("shot", "screen")
        self.assertEqual(code, 1)
        notice, target, fields = self.notices[0]
        self.assertEqual(notice, "not-saved")
        self.assertEqual(target, os.path.join(self.runtime, "flickos", "screenshot", "last.png"))
        self.assertEqual(fields["folder"], "Pictures/Screenshots")
        self.assertEqual(self.logged("clipboard"), "picture")

    def test_grim_fails(self):
        os.environ["GRIM_FAILS"] = "1"
        code, _out, err = self.run_main("shot", "screen")
        self.assertEqual(code, 1)
        self.assertIn("failed to create display", err)
        self.assertEqual(self.notices[0][0], "failed")
        self.assertIsNone(self.logged("wl-copy"))
        self.assertEqual(self.feedbacks, ["started"])

    def test_grim_missing(self):
        os.unlink(os.path.join(self.bin, "grim"))
        code, _out, err = self.run_main("shot", "screen")
        self.assertEqual(code, 1)
        self.assertIn("grim is not installed", err)

    def test_delay_waits_before_the_grab(self):
        waited = []
        with mock.patch.object(fs.time, "sleep", waited.append):
            self.run_main("shot", "screen", "--delay", "3")
        # subprocess also sleeps while it waits for the stubs.
        self.assertEqual(waited[0], 3)
        self.assertIsNotNone(self.logged("grim"))

    def test_one_capture_at_a_time(self):
        with fs.single_capture() as first:
            self.assertTrue(first)
            code, _out, err = self.run_main("shot", "screen")
        self.assertEqual(code, 1)
        self.assertIn("already", err)
        self.assertIsNone(self.logged("grim"))

    def test_no_runtime_dir(self):
        del os.environ["XDG_RUNTIME_DIR"]
        code, _out, err = self.run_main("shot", "screen")
        self.assertEqual(code, 1)
        self.assertIn("XDG_RUNTIME_DIR", err)


class ShotRegionTest(Sandbox):
    def test_grab_is_ppm_then_removed_and_cancel_saves_nothing(self):
        """The grab happens before GTK; a cancelled area saves nothing."""
        class Cancelled:
            def __init__(self, _gi, grab_path, _shot, hint):
                assert hint == fs.HINTS["shot"]
                self.grab_path = grab_path
                assert os.path.exists(grab_path)

            def run(self):
                return None

        with mock.patch.object(fs, "load_gtk", lambda: object()), \
                mock.patch.object(fs, "FrozenScreen", Cancelled):
            code, _out, err = self.run_main("shot", "region")
        self.assertEqual(code, 1)
        self.assertIn("cancelled", err)
        self.assertEqual(self.logged("grim").split()[:2], ["-t", "ppm"])
        self.assertEqual(os.listdir(os.path.join(self.runtime, "flickos", "screenshot")), [])
        self.assertIsNone(self.logged("wl-copy"))
        self.assertEqual(self.feedbacks, ["started"])

    def test_chosen_area_is_saved(self):
        class Chosen:
            def __init__(self, _gi, _grab, shot, _hint):
                self.shot = shot
                self.area = (10, 20, 300, 200)

            def run(self):
                with open(self.shot, "w") as f:
                    f.write("area")
                return self.shot

        with mock.patch.object(fs, "load_gtk", lambda: object()), \
                mock.patch.object(fs, "FrozenScreen", Chosen):
            code, out, _err = self.run_main("shot", "region")
        self.assertEqual(code, 0)
        with open(out.strip()) as f:
            self.assertEqual(f.read(), "area")
        self.assertEqual(self.logged("clipboard"), "area")
        # Only the area flashes.
        self.assertEqual(self.feedbacks, ["started", ("show", (10, 20, 300, 200))])

    def test_delay_chooses_the_area_first(self):
        """With a delay the area is chosen, then the screen is grabbed again
        when the delay is over and the area cut out of that grab."""
        events = []

        class Chooser:
            box = (0, 0, 1920, 1080)

            def __init__(self, _gi, grab_path, shot, hint):
                self.grab_path = grab_path
                events.append(("choose", shot, "3 seconds" in hint))

            def run(self):
                return (10, 20, 300, 200)

        def cut(_gi, grab_path, area, box, shot):
            with open(grab_path) as f:
                events.append(("cut", f.read(), area, box))
            with open(shot, "w") as f:
                f.write("area")

        def sleep(seconds):
            if seconds == 3:
                events.append(("sleep", seconds))

        with mock.patch.object(fs, "load_gtk", lambda: object()), \
                mock.patch.object(fs, "FrozenScreen", Chooser), mock.patch.object(fs, "cut_area", cut), \
                mock.patch.object(fs.time, "sleep", sleep):
            code, out, _err = self.run_main("shot", "region", "--delay", "3", "--pointer")
        self.assertEqual(code, 0)
        self.assertEqual(events, [("choose", None, True), ("sleep", 3),
                                  ("cut", "picture", (10, 20, 300, 200), (0, 0, 1920, 1080))])
        # The frozen screen's grab without the pointer, the area's with it.
        self.assertEqual([line.split()[:3] for line in self.logged("grim").splitlines()],
                         [["-t", "ppm", os.path.join(self.runtime, "flickos", "screenshot", fs.GRAB)],
                          ["-t", "ppm", "-c"]])
        with open(out.strip()) as f:
            self.assertEqual(f.read(), "area")
        self.assertEqual(self.feedbacks, ["started", ("show", (10, 20, 300, 200))])
        self.assertEqual(os.listdir(os.path.join(self.runtime, "flickos", "screenshot")), [])

    def test_delay_cancelled_waits_for_nothing(self):
        class Cancelled:
            box = (0, 0, 1920, 1080)

            def __init__(self, *_args):
                pass

            def run(self):
                return None

        waited = []
        with mock.patch.object(fs, "load_gtk", lambda: object()), \
                mock.patch.object(fs, "FrozenScreen", Cancelled), mock.patch.object(fs.time, "sleep", waited.append):
            code, _out, err = self.run_main("shot", "region", "--delay", "5")
        self.assertEqual(code, 1)
        self.assertIn("cancelled", err)
        self.assertNotIn(5, waited)
        self.assertEqual(len(self.logged("grim").splitlines()), 1)
        self.assertEqual(self.feedbacks, [])

    def test_no_display(self):
        def no_gtk():
            raise fs.ShotError("The area can't be chosen without a Wayland display.")

        with mock.patch.object(fs, "load_gtk", no_gtk):
            code, _out, err = self.run_main("shot", "region")
        self.assertEqual(code, 1)
        self.assertIn("Wayland display", err)
        self.assertEqual(self.notices[0][0], "failed")
        self.assertEqual(os.listdir(os.path.join(self.runtime, "flickos", "screenshot")), [])


class FeedbackTest(Sandbox):
    """The shutter sound and the flash: the child's command line, the lock that
    makes the next grab wait, and what the child does."""

    def setUp(self):
        super().setUp()
        self.folder = fs.runtime_dir()
        self.stub("pw-play", "exit 0\n")
        self.stub("busctl", '[ -n "$MAKO_RUNS" ] && echo "b true" || echo "b false"\n')
        self.stub("makoctl", 'echo "$@" >> "$STUB_LOG/makoctl"\nprintf "default\\n%s\\n" "$MAKO_MODE"\n')
        self.sounds = os.path.join(self.root, "share")
        os.environ["XDG_DATA_DIRS"] = self.sounds
        os.environ["XDG_DATA_HOME"] = os.path.join(self.home, ".local/share")
        for var in ("MAKO_RUNS", "MAKO_MODE"):
            os.environ.pop(var, None)

    def sound(self, theme, name):
        path = os.path.join(self.sounds, "sounds", theme, "stereo", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def test_child_is_told_on_its_stdin(self):
        with mock.patch.object(fs.subprocess, "Popen") as popen:
            feedback = RealFeedback()
            feedback.show((1, 2, 30, 40))
            feedback.show()                 # only once
        self.assertEqual(popen.call_args.args[0][1:], [os.path.abspath(PROGRAM), "feedback"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        stdin = popen.return_value.stdin
        stdin.write.assert_called_once_with("flash 1 2 30 40\n")
        stdin.close.assert_called_once_with()
        with mock.patch.object(fs.subprocess, "Popen") as popen:
            RealFeedback().show()
        popen.return_value.stdin.write.assert_called_once_with("flash\n")
        with mock.patch.object(fs.subprocess, "Popen") as popen:
            RealFeedback().close()          # cancelled: nothing is written
        popen.return_value.stdin.write.assert_not_called()
        popen.return_value.stdin.close.assert_called_once_with()

    def test_flash_lock_makes_the_next_grab_wait(self):
        fs.wait_for_flash(self.folder)      # no flash yet: no file, no wait
        self.assertFalse(os.path.exists(os.path.join(self.folder, fs.FLASH_LOCK)))
        with open(os.path.join(self.folder, fs.FLASH_LOCK), "a") as lock:
            fs.fcntl.flock(lock, fs.fcntl.LOCK_EX)
            with mock.patch.object(fs, "FEEDBACK_SECONDS", 0.2):
                start = time.monotonic()
                fs.wait_for_flash(self.folder)
                self.assertGreaterEqual(time.monotonic() - start, 0.2)
        start = time.monotonic()
        fs.wait_for_flash(self.folder)
        self.assertLess(time.monotonic() - start, 0.2)

    def test_grab_waits_for_the_flash(self):
        with mock.patch.object(fs, "wait_for_flash") as wait:
            self.run_main("shot", "screen")
        wait.assert_called_once_with(self.folder)

    def test_shutter_sound_of_the_theme_then_freedesktop(self):
        self.assertIsNone(fs.shutter_sound("mine"))
        fallback = self.sound("freedesktop", "screen-capture.oga")
        self.assertEqual(fs.shutter_sound("mine"), fallback)
        own = self.sound("mine", "camera-shutter.ogg")
        self.assertEqual(fs.shutter_sound("mine"), own)
        # The user's own sounds come first.
        os.environ["XDG_DATA_HOME"] = os.path.join(self.root, "user-share")
        user = os.path.join(self.root, "user-share", "sounds", "mine", "stereo", "screen-capture.wav")
        os.makedirs(os.path.dirname(user))
        open(user, "w").close()
        self.assertEqual(fs.shutter_sound("mine"), user)

    def test_do_not_disturb(self):
        # No mako: makoctl never runs, since D-Bus would start one.
        self.assertFalse(fs.do_not_disturb())
        self.assertIsNone(self.logged("makoctl"))
        os.environ["MAKO_RUNS"] = "1"
        self.assertFalse(fs.do_not_disturb())
        os.environ["MAKO_MODE"] = "do-not-disturb"
        self.assertTrue(fs.do_not_disturb())
        os.unlink(os.path.join(self.bin, "makoctl"))
        self.assertFalse(fs.do_not_disturb())

    def run_child(self, line="flash\n", **desktop):
        """Run the feedback child, told line: returns (sounds played, flashes)."""
        settings = {"animations": True, "event-sounds": True, "sound-theme": "freedesktop", **desktop}
        played, flashed, loaded = [], [], []
        lock = os.path.join(self.folder, fs.FLASH_LOCK)

        def flash(gi, area=None):
            # The next grab waits while the flash is shown.
            with open(lock) as other, self.assertRaises(BlockingIOError):
                fs.fcntl.flock(other, fs.fcntl.LOCK_EX | fs.fcntl.LOCK_NB)
            flashed.append((gi, area))

        with mock.patch.object(fs, "desktop_settings", lambda: settings), \
                mock.patch.object(fs, "play_sound", played.append), \
                mock.patch.object(fs, "load_gtk", lambda: loaded.append(1) or "gtk"), \
                mock.patch.object(fs, "run_flash", flash), \
                mock.patch.object(sys, "stdin", io.StringIO(line)):
            code, _out, _err = self.run_main("feedback")
        self.assertEqual(code, 0)
        # GTK is loaded before the picture is taken, and only for a flash.
        self.assertEqual(bool(loaded), settings["animations"])
        return played, flashed

    def test_child_plays_and_flashes(self):
        sound = self.sound("freedesktop", "screen-capture.oga")
        self.assertEqual(self.run_child("flash 5 6 70 80\n"), ([sound], [("gtk", (5, 6, 70, 80))]))
        self.assertEqual(self.run_child(), ([sound], [("gtk", None)]))
        self.assertEqual(self.run_child("flash 5 x 70 80\n"), ([sound], [("gtk", None)]))

    def test_child_does_nothing_when_cancelled(self):
        self.sound("freedesktop", "screen-capture.oga")
        self.assertEqual(self.run_child(""), ([], []))
        self.assertFalse(os.path.exists(os.path.join(self.folder, fs.FLASH_LOCK)))

    def test_child_follows_the_desktop(self):
        sound = self.sound("freedesktop", "screen-capture.oga")
        self.assertEqual(self.run_child(animations=False), ([sound], []))
        self.assertEqual(self.run_child(**{"event-sounds": False}), ([], [("gtk", None)]))
        os.environ["MAKO_RUNS"], os.environ["MAKO_MODE"] = "1", "do-not-disturb"
        self.assertEqual(self.run_child(), ([], [("gtk", None)]))

    def test_no_sound_file_no_sound(self):
        self.assertEqual(self.run_child()[0], [])

    def test_play_sound(self):
        with mock.patch.object(fs.subprocess, "Popen") as popen:
            fs.play_sound("/s.oga")
        self.assertEqual(popen.call_args.args[0], ["pw-play", "--media-role", "Notification", "/s.oga"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        os.unlink(os.path.join(self.bin, "pw-play"))
        with mock.patch.object(fs.subprocess, "Popen") as popen:
            fs.play_sound("/s.oga")
        popen.assert_not_called()

    def test_flash_fades_out(self):
        self.assertEqual(fs.flash_alpha(0), fs.FLASH_ALPHA)
        self.assertLess(fs.flash_alpha(fs.FLASH_SECONDS / 2), fs.FLASH_ALPHA / 2)
        self.assertEqual(fs.flash_alpha(fs.FLASH_SECONDS), 0)
        self.assertEqual(fs.flash_alpha(fs.FLASH_SECONDS * 2), 0)

    def test_desktop_settings(self):
        with mock.patch.dict(sys.modules, {"gi": None}):
            self.assertEqual(fs.desktop_settings(),
                             {"animations": True, "event-sounds": True, "sound-theme": "freedesktop"})


class TextTest(Sandbox):
    """shot --text, with a stub tesseract: it lists $TESSERACT_LANGS and
    "reads" $TESSERACT_TEXT, ending the page with a form feed as it does."""

    def setUp(self):
        super().setUp()
        self.stub(fs.OCR, 'if [ "$1" = "--list-langs" ]; then\n'
                          '  echo \'List of available languages in "/usr/share/tessdata/" (2):\'\n'
                          '  for name in ${TESSERACT_LANGS-osd eng}; do echo "$name"; done; exit 0\n'
                          'fi\n'
                          'echo "$@ OMP=$OMP_THREAD_LIMIT" >> "$STUB_LOG/tesseract"\n'
                          '[ -n "$TESSERACT_FAILS" ] && { echo "Error, cannot read input file $1" >&2; exit 1; }\n'
                          'case "$*" in *thresholding_method=2*) ;; *) [ -n "$TESSERACT_LOCAL_ONLY" ] && exit 0 ;; esac\n'
                          'printf "%s\\n\\f" "$TESSERACT_TEXT"\n')
        os.environ["TESSERACT_TEXT"] = "Hello <world> & more"
        for var in ("TESSERACT_LANGS", "TESSERACT_FAILS", "TESSERACT_LOCAL_ONLY"):
            os.environ.pop(var, None)

    def screenshot_folder(self):
        return os.path.join(self.runtime, "flickos", "screenshot")

    def test_screen_text_is_copied_printed_and_not_saved(self):
        code, out, _err = self.run_main("shot", "screen", "--text")
        self.assertEqual(code, 0)
        self.assertEqual(out, "Hello <world> & more\n")
        self.assertEqual(self.logged("wl-copy").strip(), "--type text/plain;charset=utf-8")
        self.assertEqual(self.logged("clipboard"), "Hello <world> & more")
        self.assertEqual(self.notices, [("text-copied", None, {"text": "Hello &lt;world&gt; &amp; more"})])
        # The picture is read, then gone; nothing is saved.
        shot = os.path.join(self.screenshot_folder(), fs.SHOT)
        self.assertEqual(self.logged("tesseract").split(), [shot, "stdout", "-l", "eng", "OMP=1"])
        self.assertFalse(os.path.exists(os.path.join(self.pictures, "Screenshots")))
        self.assertEqual(os.listdir(self.screenshot_folder()), [])
        self.assertEqual(self.feedbacks, ["started", ("show", None)])

    def test_the_pointer_setting_is_left_out(self):
        self.run_main("set", "pointer", "yes")
        self.run_main("shot", "screen", "--text")
        self.assertNotIn("-c", self.logged("grim").split())
        self.run_main("shot", "screen", "--text", "--pointer")
        self.assertIn("-c", self.logged("grim").splitlines()[-1].split())

    def test_area_says_it_copies_text(self):
        hints = []

        class Chosen:
            def __init__(self, _gi, _grab, shot, hint):
                hints.append(hint)
                self.shot, self.area = shot, (1, 2, 3, 4)

            def run(self):
                with open(self.shot, "w") as f:
                    f.write("area")
                return self.shot

        with mock.patch.object(fs, "load_gtk", lambda: object()), mock.patch.object(fs, "FrozenScreen", Chosen):
            code, out, _err = self.run_main("shot", "region", "--text")
        self.assertEqual((code, out), (0, "Hello <world> & more\n"))
        self.assertEqual(hints, [fs.HINTS["text"]])

    def test_nothing_found_is_read_again_with_a_local_threshold(self):
        os.environ["TESSERACT_LOCAL_ONLY"] = "1"
        code, out, _err = self.run_main("shot", "screen", "--text")
        self.assertEqual((code, out), (0, "Hello <world> & more\n"))
        runs = self.logged("tesseract").splitlines()
        self.assertEqual(len(runs), 2)
        self.assertNotIn("thresholding_method", runs[0])
        self.assertIn(" ".join(fs.OCR_RETRY), runs[1])

    def test_no_text_copies_nothing(self):
        os.environ["TESSERACT_TEXT"] = "  \n"
        code, out, err = self.run_main("shot", "screen", "--text")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(len(self.logged("tesseract").splitlines()), 2)
        self.assertIn("no text found", err)
        self.assertEqual(self.notices, [("no-text", None, {})])
        self.assertIsNone(self.logged("wl-copy"))
        self.assertEqual(os.listdir(self.screenshot_folder()), [])

    def test_not_copied_is_still_printed(self):
        os.environ["WL_COPY_FAILS"] = "1"
        code, out, _err = self.run_main("shot", "screen", "--text")
        self.assertEqual((code, out), (1, "Hello <world> & more\n"))
        self.assertEqual(self.notices, [("text-not-copied", None, {})])

    def test_tesseract_fails(self):
        os.environ["TESSERACT_FAILS"] = "1"
        code, _out, err = self.run_main("shot", "screen", "--text")
        self.assertEqual(code, 1)
        self.assertIn("cannot read input file", err)
        self.assertEqual(len(self.logged("tesseract").splitlines()), 1)
        self.assertEqual(self.notices[0][0], "text-failed")
        self.assertIsNone(self.logged("wl-copy"))
        self.assertEqual(os.listdir(self.screenshot_folder()), [])

    def test_tesseract_missing_grabs_nothing(self):
        os.unlink(os.path.join(self.bin, fs.OCR))
        code, _out, err = self.run_main("shot", "region", "--text")
        self.assertEqual(code, 1)
        self.assertIn("tesseract-ocr", err)
        self.assertEqual(self.notices, [("text-failed", None, {"error": fs.NO_OCR})])
        self.assertIsNone(self.logged("grim"))
        self.assertEqual(self.feedbacks, [])

    def test_text_or_copy_only(self):
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
            fs.main(["shot", "screen", "--text", "--copy-only"])
        self.assertEqual(caught.exception.code, 2)

    def test_languages(self):
        for listed, expected in (("osd eng", ["eng"]), ("deu eng osd", ["eng", "deu"]),
                                 ("ara chi_sim deu eng fra", ["eng", "ara", "chi_sim"]),
                                 ("osd", None), ("", None)):
            os.environ["TESSERACT_LANGS"] = listed
            self.assertEqual(fs.ocr_languages(), expected, listed)
        os.environ["TESSERACT_LANGS"] = "fra eng"
        self.run_main("shot", "screen", "--text")
        self.assertIn("-l eng+fra ", self.logged("tesseract"))

    def test_the_bar_reads_text_without_the_pointer(self):
        self.run_main("set", "pointer", "yes")
        choice = {"mode": "screen", "delay": 3, "video": False, "text": True, "sound": "none"}
        with mock.patch.object(fs, "load_gtk", return_value="gtk"), \
                mock.patch.object(fs, "run_bar", return_value=choice), \
                mock.patch.object(fs, "capture", return_value=0) as capture, \
                mock.patch.object(fs.time, "sleep"):
            self.assertEqual(self.run_main("bar")[0], 0)
        capture.assert_called_once_with("screen", False, False, "gtk", 3, text=True)

    def test_bar_failure_says_text(self):
        choice = {"mode": "screen", "delay": 0, "video": False, "text": True, "sound": "none"}
        with mock.patch.object(fs, "load_gtk", return_value="gtk"), \
                mock.patch.object(fs, "run_bar", return_value=choice), \
                mock.patch.object(fs, "capture", side_effect=fs.ShotError("broken")), \
                mock.patch.object(fs.time, "sleep"):
            self.assertEqual(self.run_main("bar")[0], 1)
        self.assertEqual(self.notices, [("text-failed", None, {"error": "broken"})])


class TextExcerptTest(unittest.TestCase):
    def test_markup_is_escaped(self):
        self.assertEqual(fs.text_excerpt("a < b && c > d"), "a &lt; b &amp;&amp; c &gt; d")

    def test_first_lines_only_and_long_ones_cut(self):
        text = "one\n\n  two  \n" + "x" * 100 + "\nfour"
        lines = fs.text_excerpt(text).split("\n")
        self.assertEqual(lines[:2], ["one", "two"])
        self.assertEqual(len(lines), fs.NOTICE_LINES)
        self.assertEqual(lines[2], "x" * (fs.NOTICE_LINE_CHARS - 1) + "…")
        self.assertEqual(fs.text_excerpt("a\nb\nc\nd"), "a\nb\nc …")


class OcrPictureTest(unittest.TestCase):
    """The upscale before reading, where GdkPixbuf is (not at package build)."""

    def setUp(self):
        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
        except (ImportError, ValueError):
            self.skipTest("no GdkPixbuf")
        self.GdkPixbuf = GdkPixbuf
        self.root = tempfile.mkdtemp(prefix="flickos-screenshot-test-")
        self.addCleanup(shutil.rmtree, self.root)

    def picture(self, width, height):
        path = os.path.join(self.root, f"{width}x{height}.png")
        pixbuf = self.GdkPixbuf.Pixbuf.new(self.GdkPixbuf.Colorspace.RGB, False, 8, width, height)
        pixbuf.fill(0x383c4aff)
        pixbuf.savev(path, "png", [], [])
        return path

    def test_a_small_area_is_read_at_twice_its_size(self):
        bigger = os.path.join(self.root, "bigger.png")
        self.assertEqual(fs.ocr_picture(self.picture(300, 40), bigger), bigger)
        read = self.GdkPixbuf.Pixbuf.new_from_file(bigger)
        self.assertEqual((read.get_width(), read.get_height()), (600, 80))

    def test_a_screen_is_read_as_it_is(self):
        source = self.picture(1920, 1080)
        self.assertEqual(fs.ocr_picture(source, os.path.join(self.root, "bigger.png")), source)

    def test_not_a_picture_is_read_as_it_is(self):
        source = os.path.join(self.root, "broken.png")
        with open(source, "w") as f:
            f.write("picture")
        self.assertEqual(fs.ocr_picture(source, os.path.join(self.root, "bigger.png")), source)


class NotifyTest(Sandbox):
    def test_click_opens_the_picture(self):
        picture = os.path.join(self.root, "a.png")
        open(picture, "w").close()
        os.environ["NOTIFY_ANSWER"] = "default"
        self.run_main("notify", picture, "Screenshot copied", "Paste it anywhere.")
        args = self.logged("notify-send").splitlines()
        self.assertIn(f"--icon={picture}", args)
        self.assertIn("--action=default=Open", args)
        self.assertEqual(args[-2:], ["Screenshot copied", "Paste it anywhere."])
        for _ in range(50):     # xdg-open is started, not waited for
            if self.logged("xdg-open"):
                break
            fs.time.sleep(0.02)
        self.assertEqual(self.logged("xdg-open").strip(), picture)

    def test_closed_without_click_opens_nothing(self):
        picture = os.path.join(self.root, "a.png")
        open(picture, "w").close()
        self.run_main("notify", picture, "t", "b")
        self.assertIsNone(self.logged("xdg-open"))

    def test_failure_has_no_action(self):
        self.run_main("notify", "", "Screenshot failed", "grim is not installed.")
        args = self.logged("notify-send").splitlines()
        self.assertNotIn("--action=default=Open", args)
        self.assertIn("--icon=applets-screenshooter", args)

    def children(self):
        """Patch Popen: this program's children are recorded, not started."""
        real, started = subprocess.Popen, []

        def popen(argv, *args, **kwargs):
            if argv[0] == sys.executable:
                started.append(argv)
                return mock.Mock()
            return real(argv, *args, **kwargs)

        patcher = mock.patch.object(fs.subprocess, "Popen", popen)
        patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def test_click_edits_a_screenshot(self):
        picture = os.path.join(self.root, "a.png")
        open(picture, "w").close()
        os.environ["NOTIFY_ANSWER"] = "default"
        started = self.children()
        self.run_main("notify", picture, "Screenshot copied", "Paste it anywhere.", "--edit")
        self.assertIn("--action=default=Edit", self.logged("notify-send").splitlines())
        self.assertEqual([argv[1:] for argv in started], [[PROGRAM, "edit", picture]])
        self.assertIsNone(self.logged("xdg-open"))

    def test_screenshots_are_edited_recordings_played(self):
        started = self.children()
        RealNotify("saved", "/p/a.png", folder="Pictures/Screenshots")
        RealNotify("copied", "/run/last.png")
        RealNotify("recorded", "/v/a.mp4", icon="video-x-generic", folder="Videos")
        RealNotify("failed", error="grim is not installed.")
        self.assertEqual(["--edit" in argv for argv in started], [True, True, False, False])

    def test_notice_texts_fill_in(self):
        for notice, (title, body) in fs.NOTICES.items():
            self.assertTrue(title and title[0].isupper(), notice)
            filled = body.format(folder="Pictures/Screenshots", error="disk full", text="Hello")
            # The action comes before anything mako might cut off.
            self.assertLess(len(filled), 80, notice)


class CommandLineTest(Sandbox):
    def test_usage_errors_exit_2(self):
        for argv in (["shot"], ["shot", "window"], ["shot", "screen", "--delay", "99"], ["frobnicate"]):
            with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
                fs.main(argv)
            self.assertEqual(caught.exception.code, 2, argv)

    def test_no_command_is_the_bar(self):
        with mock.patch.object(fs, "cmd_bar", lambda _opts: 42):
            self.assertEqual(fs.main([]), 42)

    def test_runs_as_a_program(self):
        """The file runs on its own (shebang, no GTK at start) and prints its help."""
        result = subprocess.run([sys.executable, PROGRAM, "--help"], capture_output=True, text=True,
                                timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn("shot", result.stdout)


HEADS = [
    # The laptop's screen is off: wlr-randr gives no position for it.
    {"name": "eDP-1", "enabled": False, "modes": [{"width": 1366, "height": 768, "current": False}]},
    {"name": "HDMI-A-1", "enabled": True, "position": {"x": 1366, "y": 0}, "scale": 1.0, "transform": "normal",
     "modes": [{"width": 1920, "height": 1080, "current": True}]},
    {"name": "DP-1", "enabled": True, "position": {"x": 0, "y": 0}, "scale": 2.0, "transform": "normal",
     "modes": [{"width": 1024, "height": 768, "current": False}, {"width": 2732, "height": 1536, "current": True}]},
    {"name": "DP-2", "enabled": True, "position": {"x": 3286, "y": 0}, "scale": 1.0, "transform": "90",
     "modes": [{"width": 1920, "height": 1080, "current": True}]},
]
SCREENS = [
    {"name": "HDMI-A-1", "pixels": (1920, 1080), "rect": (1366, 0, 1920, 1080)},
    {"name": "DP-1", "pixels": (2732, 1536), "rect": (0, 0, 1366, 768)},
]


class ScreensTest(Sandbox):
    def test_enabled_screens_with_layout_and_pixels(self):
        os.environ["WLR_RANDR_JSON"] = json.dumps(HEADS)
        self.assertEqual(fs.screens(), SCREENS + [
            {"name": "DP-2", "pixels": (1080, 1920), "rect": (3286, 0, 1080, 1920)}])

    def test_unknown_is_empty(self):
        os.environ["WLR_RANDR_FAILS"] = "1"
        self.assertEqual(fs.screens(), [])
        os.environ.pop("WLR_RANDR_FAILS")
        for text in ("not json", "{}", '[{"name": "X", "enabled": true}]'):
            os.environ["WLR_RANDR_JSON"] = text
            self.assertEqual(fs.screens(), [], text)


class RecordingCropTest(unittest.TestCase):
    def test_whole_screen_is_no_crop(self):
        self.assertEqual(fs.recording_crop((1366, 0, 1920, 1080), SCREENS),
                         (SCREENS[0], (1366, 0, 1920, 1080), None))

    def test_area_on_a_screen_not_at_zero(self):
        screen, part, crop = fs.recording_crop((1466, 100, 800, 400), SCREENS)
        self.assertEqual(screen["name"], "HDMI-A-1")
        self.assertEqual(part, (1466, 100, 800, 400))
        self.assertEqual(crop, (100, 100, 1920 - 900, 1080 - 500))

    def test_scale_two(self):
        _screen, _part, crop = fs.recording_crop((100, 50, 300, 200), SCREENS)
        self.assertEqual(crop, (200, 100, 2732 - 800, 1536 - 500))

    def test_size_made_even(self):
        _screen, _part, crop = fs.recording_crop((1367, 1, 301, 151), SCREENS)
        left, top, right, bottom = crop
        self.assertEqual((1920 - left - right, 1080 - top - bottom), (300, 150))

    def test_across_two_screens_takes_the_one_with_most(self):
        screen, part, _crop = fs.recording_crop((1300, 100, 400, 100), SCREENS)
        self.assertEqual(screen["name"], "HDMI-A-1")
        self.assertEqual(part, (1366, 100, 334, 100))

    def test_errors(self):
        for rect, found in (((0, 0, 100, 100), []), ((5000, 5000, 100, 100), SCREENS),
                            ((1400, 10, 10, 300), SCREENS)):
            with self.assertRaises(fs.ShotError):
                fs.recording_crop(rect, found)


class PipelineTest(unittest.TestCase):
    def test_video_only(self):
        text = fs.pipeline_description()
        self.assertTrue(text.startswith("pipewiresrc name=source do-timestamp=true keepalive-time=1000 "))
        self.assertIn(f"video/x-raw,framerate={fs.FRAMERATE}/1", text)
        self.assertIn("identity name=video-gate", text)
        self.assertIn("x264enc speed-preset=ultrafast tune=zerolatency ! video/x-h264,profile=baseline", text)
        self.assertIn("mp4mux name=mux fragment-duration=1000 ! filesink name=file", text)
        self.assertNotIn("videocrop", text)
        self.assertNotIn("pulsesrc", text)
        self.assertNotIn("audio-gate", text)

    def test_crop(self):
        self.assertIn("videocrop left=1 top=2 right=3 bottom=4 ! videoconvert",
                      fs.pipeline_description((1, 2, 3, 4)))

    def test_sounds(self):
        computer = fs.pipeline_description(sound="computer")
        self.assertIn("pulsesrc device=@DEFAULT_MONITOR@ do-timestamp=true ! audioconvert", computer)
        microphone = fs.pipeline_description(sound="microphone")
        self.assertIn(" pulsesrc do-timestamp=true ! audioconvert", microphone)
        self.assertNotIn("device=", microphone)
        both = fs.pipeline_description(sound="both")
        self.assertIn("audiomixer name=mix", both)
        self.assertEqual(both.count("pulsesrc"), 2)
        self.assertEqual(both.count("! mix."), 2)
        for text in (computer, microphone, both):
            self.assertEqual(text.count("audio/x-raw,channels=2 ! identity name=audio-gate ! opusenc ! queue ! mux."),
                             1)

    @unittest.skipUnless(GST, "GStreamer with every element isn't installed")
    def test_every_pipeline_parses(self):
        for crop in (None, (1, 2, 3, 4)):
            for sound in fs.SOUNDS:
                pipeline = GST.parse_launch(fs.pipeline_description(crop, sound))
                for name in ("source", "file", "video-gate"):
                    self.assertIsNotNone(pipeline.get_by_name(name), (sound, name))

    def test_duration_text(self):
        self.assertEqual([fs.duration_text(s) for s in (0, 42.9, 725, 3723)],
                         ["0:00", "0:42", "12:05", "1:02:03"])

    def test_panel_status(self):
        self.assertEqual(fs.panel_status(countdown=3)["text"], "Recording in 3")
        self.assertEqual(fs.panel_status(countdown=3)["class"], "countdown")
        self.assertEqual(fs.panel_status()["class"], "countdown")
        status = fs.panel_status(elapsed=42)
        self.assertEqual((status["text"], status["class"]), ("0:42", "recording"))
        self.assertIn("Super+Shift+R", status["tooltip"])


class PanelTest(Sandbox):
    def test_signals_only_the_users_waybars(self):
        self.fake_process(101, "waybar")
        self.fake_process(102, "waybar-wrapper")
        self.fake_process(103, "bash")
        os.makedirs(os.path.join(self.proc, "self"))
        with mock.patch.object(fs.os, "kill") as kill:
            fs.signal_panel()
        kill.assert_called_once_with(101, fs.signal.SIGRTMIN + fs.PANEL_SIGNAL)

    def test_write_and_delete(self):
        runtime = fs.runtime_dir()
        with mock.patch.object(fs, "signal_panel") as signalled:
            fs.write_panel(runtime, fs.panel_status(elapsed=5))
            with open(os.path.join(runtime, fs.PANEL)) as f:
                self.assertEqual(json.load(f)["text"], "0:05")
            fs.write_panel(runtime, None)
        self.assertFalse(os.path.exists(os.path.join(runtime, fs.PANEL)))
        self.assertEqual(signalled.call_count, 2)
        self.assertEqual(os.listdir(runtime), [])

    def test_recorder_lock_and_pid(self):
        runtime = fs.runtime_dir()
        self.assertIsNone(fs.recorder_pid())
        with fs.recorder_lock(runtime) as first:
            self.assertTrue(first)
            with fs.recorder_lock(runtime) as second:
                self.assertFalse(second)
            # The PID must be a flickos-screenshot, not a PID reused since.
            self.assertIsNone(fs.recorder_pid())
            self.fake_process(os.getpid(), "python3", b"/usr/bin/python3\0/usr/bin/flickos-screenshot\0record\0")
            self.assertEqual(fs.recorder_pid(), os.getpid())
        self.assertIsNone(fs.recorder_pid())

    def test_stop_signals_the_recorder(self):
        with mock.patch.object(fs, "recorder_pid", return_value=4242), \
                mock.patch.object(fs.os, "kill") as kill:
            self.assertEqual(self.run_main("stop")[0], 0)
        kill.assert_called_once_with(4242, fs.signal.SIGTERM)

    def test_stop_without_recording_clears_a_stale_button(self):
        runtime = fs.runtime_dir()
        with open(os.path.join(runtime, fs.PANEL), "w") as f:
            f.write("{}")
        with mock.patch.object(fs.os, "kill") as kill:
            code, _out, err = self.run_main("stop")
        self.assertEqual(code, 1)
        self.assertIn("no recording is running", err)
        self.assertFalse(os.path.exists(os.path.join(runtime, fs.PANEL)))
        kill.assert_not_called()                # no waybar in the fake /proc

    def test_status(self):
        self.assertEqual(self.run_main("status")[1], "not recording\n")
        self.assertEqual(self.run_main("status", "--panel")[1], "")
        runtime = fs.runtime_dir()
        with open(os.path.join(runtime, fs.PANEL), "w") as f:
            f.write('{"text": "0:01"}\n')
        with mock.patch.object(fs, "recorder_pid", return_value=4242):
            self.assertEqual(self.run_main("status")[1], "recording\n")
            self.assertEqual(self.run_main("status", "--panel")[1], '{"text": "0:01"}\n')


# A stand-in for the parts of GStreamer and GLib the Recorder uses.
class FakeBuffer:
    def __init__(self, pts=0, corrupted=False):
        self.pts, self.corrupted = pts, corrupted

    def has_flags(self, flag):
        return self.corrupted and flag == "CORRUPTED"


class FakeInfo:
    def __init__(self, buffer):
        self.buffer = buffer

    def get_buffer(self):
        return self.buffer


class FakePad:
    def __init__(self):
        self.offset = 0

    def set_offset(self, offset):
        self.offset = offset


class FakePipeline:
    def __init__(self):
        self.states, self.events, self.time = [], [], 0

    def set_state(self, state):
        self.states.append(state)
        return "SUCCESS"

    def send_event(self, event):
        self.events.append(event)

    def get_clock(self):
        return mock.Mock(get_time=lambda: self.time + 1000)

    def get_base_time(self):
        return 1000


def fake_gi():
    Gst = mock.Mock()
    Gst.BufferFlags.CORRUPTED = "CORRUPTED"
    Gst.PadProbeReturn.OK, Gst.PadProbeReturn.DROP = "OK", "DROP"
    Gst.CLOCK_TIME_NONE = 2 ** 64 - 1
    Gst.State.NULL, Gst.State.PLAYING = "NULL", "PLAYING"
    Gst.StateChangeReturn.FAILURE = "FAILURE"
    Gst.MessageType.EOS, Gst.MessageType.ERROR = "EOS", "ERROR"
    Gst.Event.new_eos = lambda: "eos"
    GLib = mock.Mock()
    GLib.timeout_add_seconds = mock.Mock(return_value=77)
    return fs.argparse.Namespace(Gst=Gst, GLib=GLib)


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.pipeline = FakePipeline()
        self.shown = []
        self.recorder = fs.Recorder(fake_gi(), self.pipeline, 3, on_status=self.shown.append,
                                    clock=lambda: self.now)
        self.recorder.gates = [FakePad(), FakePad()]
        self.recorder.start()
        patcher = mock.patch.object(fs, "warn")
        patcher.start()
        self.addCleanup(patcher.stop)

    def at(self, now, frames=0, corrupted=0):
        self.now = now
        for _ in range(corrupted):
            self.assertEqual(self.recorder.source_probe(None, FakeInfo(FakeBuffer(corrupted=True))), "DROP")
        for _ in range(frames):
            self.assertEqual(self.recorder.source_probe(None, FakeInfo(FakeBuffer())), "OK")
        return self.recorder.poll()

    def texts(self):
        return [status["text"] for status in self.shown]

    def test_counts_down_then_opens_the_gate(self):
        self.at(0.0)
        self.at(0.5, frames=10)
        self.pipeline.time = 2_900_000_000
        self.at(2.0)
        self.assertIsNone(self.recorder.gate)
        self.at(3.0)
        self.assertEqual(self.recorder.gate, 2_900_000_000)
        self.assertEqual([pad.offset for pad in self.recorder.gates], [-2_900_000_000] * 2)
        self.at(4.25)
        self.assertEqual(self.texts(), ["Recording in 3", "Recording in 1", "0:00", "0:01"])
        self.assertEqual(self.pipeline.states, ["PLAYING"])
        self.assertTrue(self.recorder.started)

    def test_gate_drops_what_came_before(self):
        info = lambda pts: FakeInfo(FakeBuffer(pts=pts))
        self.assertEqual(self.recorder.gate_probe(None, info(5)), "DROP")
        self.recorder.gate = 100
        self.assertEqual(self.recorder.gate_probe(None, info(99)), "DROP")
        self.assertEqual(self.recorder.gate_probe(None, info(100)), "OK")
        self.assertEqual(self.recorder.gate_probe(None, info(2 ** 64 - 1)), "OK")

    def test_stuck_first_frame_restarts_the_pipeline(self):
        """portal-wlr's stall: one CORRUPTED buffer, then nothing."""
        self.at(0.0, corrupted=1)
        self.at(0.75)
        self.assertEqual(self.pipeline.states, ["PLAYING"])
        self.at(1.0)
        self.assertEqual(self.pipeline.states, ["PLAYING", "NULL", "PLAYING"])
        self.assertEqual(self.recorder.restarts, 1)
        self.at(1.5, frames=1)
        self.at(3.0)
        self.assertIsNotNone(self.recorder.gate)
        self.assertEqual(self.recorder.restarts, 1)

    def test_waits_for_a_frame_after_the_countdown(self):
        self.at(0.0)
        self.at(0.9)
        self.at(1.0)                            # restart 1
        self.at(1.9, frames=1)
        self.at(3.0)
        self.assertIsNotNone(self.recorder.gate)
        recorder = fs.Recorder(fake_gi(), FakePipeline(), 0, on_status=self.shown.append, clock=lambda: self.now)
        self.now = 10.0
        recorder.start()
        recorder.poll()
        self.assertIsNone(recorder.gate)
        self.assertEqual(self.shown[-1]["text"], "Starting")

    def test_gives_up_after_the_last_restart(self):
        for step in range(1, fs.MAX_RESTARTS + 2):
            self.at(float(step))
        self.assertIsInstance(self.recorder.result, fs.ShotError)
        self.assertEqual(self.recorder.restarts, fs.MAX_RESTARTS)
        self.assertFalse(self.recorder.started)
        self.recorder.loop.quit.assert_called_once()

    def test_stop_before_it_started_cancels(self):
        self.at(1.0, frames=1)
        self.recorder.stop()
        self.assertEqual(self.recorder.result, "cancelled")
        self.assertEqual(self.pipeline.events, [])

    def test_stop_ends_the_stream_first(self):
        self.at(0.0, frames=1)
        self.at(3.0)
        self.recorder.stop()
        self.recorder.stop()                    # a second click does nothing more
        self.assertEqual(self.pipeline.events, ["eos"])
        self.assertIsNone(self.recorder.result)
        self.recorder.message(None, mock.Mock(type="EOS"))
        self.assertEqual(self.recorder.result, "stopped")
        self.recorder.gi.GLib.source_remove.assert_called_once_with(77)

    def test_end_of_stream_that_never_comes(self):
        self.at(0.0, frames=1)
        self.at(3.0)
        self.recorder.stop()
        self.recorder.gi.GLib.timeout_add_seconds.assert_called_once_with(fs.EOS_SECONDS,
                                                                         self.recorder.eos_timeout)
        self.recorder.eos_timeout()
        self.assertEqual(self.recorder.result, "stopped")

    def test_error_ends_it(self):
        error = mock.Mock(type="ERROR")
        error.parse_error.return_value = (mock.Mock(message="Stream lost"), None)
        with contextlib.redirect_stderr(io.StringIO()):
            self.recorder.message(None, error)
        self.assertIsInstance(self.recorder.result, fs.ShotError)
        self.assertIn("Stream lost", str(self.recorder.result))

    def test_disk_almost_full_stops(self):
        self.recorder.folder = "/somewhere"
        self.at(0.0, frames=1)
        with mock.patch.object(fs, "free_mb", return_value=fs.MIN_FREE_MB - 1), \
                contextlib.redirect_stderr(io.StringIO()):
            self.at(3.0)
        self.assertEqual(self.pipeline.events, ["eos"])
        self.recorder.message(None, mock.Mock(type="EOS"))
        self.assertEqual(self.recorder.result, "full")


class FakeRecorder:
    """Writes a few bytes into the file and ends as told."""
    result, started = "stopped", True

    def __init__(self, gi, pipeline, countdown, folder=None, on_status=None):
        self.pipeline, self.countdown, self.on_status = pipeline, countdown, on_status

    def run(self):
        self.on_status(fs.panel_status(elapsed=1))
        if self.started:
            with open(self.pipeline.elements["file"].props["location"], "wb") as f:
                f.write(b"mp4")
        return self.result


class FakeElement:
    def __init__(self):
        self.props = {}

    def set_property(self, name, value):
        self.props[name] = value


class RecordTest(Sandbox):
    def setUp(self):
        super().setUp()
        os.environ["WLR_RANDR_JSON"] = json.dumps(HEADS[:2])
        self.portal = mock.Mock()
        self.portal.open.return_value = (9, 42)
        self.descriptions = []
        gi = fake_gi()

        def parse_launch(description):
            self.descriptions.append(description)
            pipeline = mock.Mock()
            pipeline.elements = {name: FakeElement() for name in ("source", "file")}
            pipeline.get_by_name = pipeline.elements.get
            self.pipeline = pipeline
            return pipeline

        gi.Gst.parse_launch = parse_launch
        for name, value in (("load_gst", lambda: gi), ("Portal", lambda _gi: self.portal),
                            ("Recorder", FakeRecorder), ("signal_panel", lambda: None),
                            ("show_outline", mock.Mock(return_value=None))):
            patcher = mock.patch.object(fs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.folder = os.path.join(self.home, "Videos", "Screen Recordings")

    def test_screen_recorded_saved_and_notified(self):
        code, out, _err = self.run_main("record", "screen")
        self.assertEqual(code, 0)
        path = out.strip()
        self.assertEqual(os.path.dirname(path), self.folder)
        self.assertRegex(os.path.basename(path), r"^Screen Recording \d{4}-\d\d-\d\d \d\d-\d\d-\d\d\.mp4$")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"mp4")
        self.assertEqual(self.notices, [("recorded", path, {"icon": "video-x-generic",
                                                             "folder": "Videos/Screen Recordings"})])
        # The only screen is asked for, so the portal doesn't ask; no crop.
        self.assertEqual(self.portal.open.call_args.args[:2], (os.path.join(self.runtime, "flickos", "screenshot"),
                                                               "HDMI-A-1"))
        self.assertNotIn("videocrop", self.descriptions[0])
        self.assertEqual(self.pipeline.elements["source"].props, {"fd": 9, "path": "42"})
        self.portal.close.assert_called_once()
        self.assertEqual(os.listdir(os.path.join(self.runtime, "flickos", "screenshot")), [fs.RECORDING_LOCK])

    def test_several_screens_let_the_portal_ask(self):
        os.environ["WLR_RANDR_JSON"] = json.dumps(HEADS)
        self.assertEqual(self.run_main("record", "screen", "--sound", "both")[0], 0)
        self.assertIsNone(self.portal.open.call_args.args[1])
        self.assertIn("audiomixer", self.descriptions[0])

    def test_area_is_cropped_and_outlined(self):
        with mock.patch.object(fs, "choose_area", return_value=(1466, 100, 801, 400)):
            self.assertEqual(self.run_main("record", "region", "--delay", "5")[0], 0)
        self.assertEqual(self.portal.open.call_args.args[1], "HDMI-A-1")
        self.assertIn("videocrop left=100 top=100 right=1020 bottom=580 ", self.descriptions[0])
        fs.show_outline.assert_called_once_with((1466, 100, 801, 400))

    def test_escape_on_the_frozen_screen(self):
        with mock.patch.object(fs, "choose_area", side_effect=fs.Cancelled()):
            code, _out, err = self.run_main("record", "region")
        self.assertEqual((code, self.notices), (1, []))
        self.assertIn("cancelled", err)
        self.portal.open.assert_not_called()

    def test_portal_chooser_said_no(self):
        self.portal.open.side_effect = fs.Cancelled()
        code, _out, _err = self.run_main("record", "screen")
        self.assertEqual((code, self.notices), (1, []))
        self.assertFalse(os.path.exists(self.folder) and os.listdir(self.folder))
        self.portal.close.assert_called_once()

    def test_stopped_during_the_countdown_keeps_nothing(self):
        with mock.patch.object(FakeRecorder, "result", "cancelled"), \
                mock.patch.object(FakeRecorder, "started", False):
            code, _out, _err = self.run_main("record", "screen")
        self.assertEqual((code, self.notices), (1, []))
        self.assertEqual(os.listdir(self.folder), [])

    def test_failure_before_anything_was_recorded(self):
        with mock.patch.object(FakeRecorder, "result", fs.ShotError("No picture.")), \
                mock.patch.object(FakeRecorder, "started", False):
            code, _out, _err = self.run_main("record", "screen")
        self.assertEqual(code, 1)
        self.assertEqual(self.notices, [("record-failed", None, {"error": "No picture."})])
        self.assertEqual(os.listdir(self.folder), [])

    def test_failure_after_it_started_keeps_the_file(self):
        with mock.patch.object(FakeRecorder, "result", fs.ShotError("The recording stopped: gone.")):
            code, out, _err = self.run_main("record", "screen")
        self.assertEqual(code, 1)
        notice, target, fields = self.notices[0]
        self.assertEqual((notice, target), ("record-broken", out.strip()))
        self.assertTrue(os.path.exists(out.strip()))

    def test_one_recording_at_a_time(self):
        with fs.recorder_lock(fs.runtime_dir()):
            code, _out, err = self.run_main("record", "screen")
        self.assertEqual(code, 1)
        self.assertIn("already running", err)

    def test_videos_folder_unwritable(self):
        os.makedirs(os.path.join(self.home, "Videos"))
        os.chmod(os.path.join(self.home, "Videos"), 0o500)
        self.addCleanup(os.chmod, os.path.join(self.home, "Videos"), 0o700)
        if os.access(os.path.join(self.home, "Videos"), os.W_OK):
            self.skipTest("running as root")
        code, _out, _err = self.run_main("record", "screen")
        self.assertEqual(code, 1)
        self.assertEqual(self.notices[0][0], "record-failed")
        self.portal.open.assert_not_called()

    def test_the_sound_and_folder_settings(self):
        folder = os.path.join(self.home, "Clips")
        self.assertEqual(self.run_main("set", "recordings-folder", folder)[0], 0)
        self.assertEqual(self.run_main("set", "sound", "computer")[0], 0)
        code, out, _err = self.run_main("record", "screen")
        self.assertEqual(code, 0)
        self.assertEqual(os.path.dirname(out.strip()), folder)
        self.assertIn(f"pulsesrc device={fs.COMPUTER_SOUND}", self.descriptions[-1])

    def test_sound_on_the_command_line_does_not_change_the_setting(self):
        self.assertEqual(self.run_main("record", "screen", "--sound", "microphone")[0], 0)
        self.assertEqual(fs.load_settings().sound, "none")
        self.assertIn("pulsesrc ", self.descriptions[-1])
        self.assertNotIn(fs.COMPUTER_SOUND, self.descriptions[-1])
        self.assertEqual(self.history(), [])


class BarVideoTest(Sandbox):
    def test_super_shift_r_stops_a_recording(self):
        with mock.patch.object(fs, "recorder_pid", return_value=4242), \
                mock.patch.object(fs.os, "kill") as kill, mock.patch.object(fs, "load_gtk") as gtk:
            self.assertEqual(self.run_main("bar", "--video")[0], 0)
        kill.assert_called_once_with(4242, fs.signal.SIGTERM)
        gtk.assert_not_called()

    def test_video_replaces_the_bar_with_the_recorder(self):
        choice = {"mode": "region", "delay": 0, "video": True, "text": False, "sound": "microphone"}
        with mock.patch.object(fs, "load_gtk"), mock.patch.object(fs, "run_bar", return_value=choice) as bar, \
                mock.patch.object(fs.os, "execv", side_effect=SystemExit(0)) as execv:
            with self.assertRaises(SystemExit):
                fs.main(["bar", "--video"])
        self.assertEqual(bar.call_args.args[1:], (True, False))
        argv = execv.call_args.args[1]
        self.assertEqual(argv[2:], ["record", "region", "--delay", str(fs.COUNTDOWN), "--sound", "microphone"])
        self.assertEqual(fs.read_last(), 0)                 # only the delay is remembered here
        self.assertEqual(fs.load_settings().sound, "microphone")
        self.assertEqual([(entry["key"], entry["old"], entry["new"]) for entry in self.history()],
                         [("sound", "none", "microphone")])


    def test_photo_delay_goes_to_the_capture(self):
        """The bar only waits for itself to hide; the capture waits the delay."""
        choice = {"mode": "region", "delay": 5, "video": False, "text": False, "sound": "none"}
        waited = []
        with mock.patch.object(fs, "load_gtk", return_value="gtk"), \
                mock.patch.object(fs, "run_bar", return_value=choice), \
                mock.patch.object(fs, "capture", return_value=0) as capture, \
                mock.patch.object(fs.time, "sleep", waited.append):
            self.assertEqual(self.run_main("bar")[0], 0)
        self.assertEqual(waited, [fs.HIDE_SECONDS])
        capture.assert_called_once_with("region", False, False, "gtk", 5, text=False)
        self.assertEqual(fs.read_last(), 5)
        self.assertEqual(fs.load_settings().sound, "none")
        self.assertFalse(os.path.exists(fs.user_conf()))

    def test_photo_only_for_the_markup_window(self):
        with mock.patch.object(fs, "load_gtk"), mock.patch.object(fs, "run_bar", return_value=None) as bar:
            self.assertEqual(self.run_main("bar", "--photo")[0], 0)
        self.assertEqual(bar.call_args.kwargs, {"photo_only": True})


def shape(tool="pen", points=((1, 1), (5, 5)), color="#fc4138", width=6):
    return {"tool": tool, "color": color, "width": width, "points": list(points)}


class MarkupTest(unittest.TestCase):
    def test_undo_redo_and_unsaved(self):
        markup = fs.Markup((100, 50))
        self.assertFalse(markup.dirty)
        first, second = shape(), shape("arrow")
        markup.add(first)
        self.assertTrue(markup.dirty)
        markup.keep()                   # saved or copied
        self.assertFalse(markup.dirty)
        self.assertTrue(markup.undo())
        self.assertEqual((markup.shapes, markup.dirty), ([], True))
        self.assertTrue(markup.redo())
        self.assertEqual((markup.shapes, markup.dirty), ([first], False))
        markup.undo()
        markup.add(second)              # a new change drops what was undone
        self.assertFalse(markup.redo())
        self.assertEqual(markup.shapes, [second])
        markup.undo()
        self.assertFalse(markup.undo())
        self.assertTrue(markup.dirty)   # the kept picture had the first shape

    def test_crop_is_a_change_and_keeps_the_shapes(self):
        markup = fs.Markup((100, 50))
        markup.add(shape())
        markup.set_crop((10, 5, 20, 30))
        markup.set_crop((10, 5, 20, 30))    # the same crop again is nothing
        self.assertEqual((markup.crop, len(markup.done)), ((10, 5, 20, 30), 2))
        markup.undo()
        self.assertEqual((markup.crop, len(markup.shapes)), ((0, 0, 100, 50), 1))
        markup.redo()
        self.assertEqual(markup.crop, (10, 5, 20, 30))

    def test_equal_shapes_undo_the_last(self):
        markup = fs.Markup((10, 10))
        first = shape()
        markup.add(first)
        markup.add(dict(first))
        markup.undo()
        self.assertIs(markup.shapes[0], first)

    def test_arrow_head(self):
        left, right = fs.arrow_head((0, 0), (100, 0), 6)
        length = 6 * fs.ARROW_HEAD
        self.assertAlmostEqual(left[0], 100 - length * math.cos(fs.ARROW_ANGLE))
        self.assertAlmostEqual(left[1], -right[1])
        self.assertAlmostEqual(abs(left[1]), length * math.sin(fs.ARROW_ANGLE))
        # A thin arrow still has a head that can be seen.
        left, _right = fs.arrow_head((0, 0), (0, 100), 1)
        self.assertAlmostEqual(100 - left[1], fs.ARROW_HEAD_MIN * math.cos(fs.ARROW_ANGLE))

    def test_crop_rect(self):
        self.assertEqual(fs.crop_rect((50, 40), (10, -5), (100, 80)), (10, 0, 40, 40))
        self.assertEqual(fs.crop_rect((-10, 0), (200, 100), (100, 80)), (0, 0, 100, 80))
        self.assertEqual(fs.crop_rect((30.4, 30.6), (30.4, 30.6), (100, 80)), (30, 31, 1, 1))
        self.assertEqual(fs.crop_rect((100, 80), (100, 80), (100, 80)), (99, 79, 1, 1))

    def test_move_crop(self):
        size = (100, 100)
        self.assertEqual(fs.move_crop((10, 10, 50, 50), "nw", 5, 5, size), (15, 15, 45, 45))
        self.assertEqual(fs.move_crop((10, 10, 50, 50), "ne", 10, -20, size), (10, 0, 60, 60))
        # A corner never passes the opposite one, and nothing leaves the picture.
        self.assertEqual(fs.move_crop((10, 10, 50, 50), "se", -100, -100, size), (10, 10, 1, 1))
        self.assertEqual(fs.move_crop((10, 10, 50, 50), "sw", 100, 100, size), (59, 10, 1, 90))
        self.assertEqual(fs.move_crop((10, 10, 50, 50), "move", 100, -100, size), (50, 0, 50, 50))

    def test_handles(self):
        rect = (10, 10, 50, 50)
        self.assertEqual(fs.hit_handle((11, 59), rect, 5), "sw")
        self.assertEqual(fs.hit_handle((30, 30), rect, 5), "move")
        self.assertIsNone(fs.hit_handle((90, 90), rect, 5))
        self.assertEqual(fs.crop_corner(rect, "ne"), (60, 10))
        self.assertEqual([fs.opposite(h) for h in fs.CROP_HANDLES], ["nw", "se", "sw", "ne"])

    def test_fit_and_zoom(self):
        self.assertEqual(fs.fit_scale((1920, 1080), (960, 540)), 0.5)
        self.assertEqual(fs.fit_scale((100, 100), (1000, 1000)), 1)         # never bigger
        self.assertEqual(fs.fit_scale((100, 100), (1000, 1000), 2), 0.5)    # one screen pixel at scale 2
        self.assertEqual(fs.fit_scale((100000, 100), (100, 100)), fs.ZOOMS[0])
        self.assertEqual(fs.next_zoom(0.5, 1), 0.67)
        self.assertEqual(fs.next_zoom(0.4, 1), 0.5)
        self.assertEqual(fs.next_zoom(0.4, -1), 0.33)
        self.assertEqual(fs.next_zoom(fs.ZOOMS[-1], 1), fs.ZOOMS[-1])
        self.assertEqual(fs.next_zoom(fs.ZOOMS[0], -1), fs.ZOOMS[0])

    def test_tools_colors_and_widths(self):
        # Unique mnemonics (A11Y-3), also against the action bar's N, S, V, C and E.
        letters = [label[label.index("_") + 1].lower() for _tool, label, _tip, _icons in fs.TOOLS]
        self.assertEqual(len(set(letters)), len(letters))
        self.assertFalse(set(letters) & set("nsvce"))
        for _id, name, color in fs.COLORS:
            self.assertRegex(color, r"^#[0-9a-f]{6}$", name)
        self.assertEqual(fs.hex_rgb("#ff8000"), (1.0, 128 / 255, 0.0))


@unittest.skipUnless(cairo, "needs python3-cairo")
class RenderTest(Sandbox):
    def picture(self, width=40, height=20):
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
        cr = cairo.Context(surface)
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        return surface

    def pixel(self, surface, x, y):
        surface.flush()
        data = surface.get_data()
        offset = y * surface.get_stride() + x * 4
        blue, green, red = data[offset], data[offset + 1], data[offset + 2]    # little-endian xRGB
        return f"#{red:02x}{green:02x}{blue:02x}"

    def test_hide_is_solid_and_the_crop_cuts(self):
        markup = fs.Markup((40, 20))
        markup.add(shape("hide", ((5, 5), (15, 15)), color="#2b2e39"))
        out = fs.render_picture(self.picture(), markup)
        self.assertEqual((out.get_width(), out.get_height()), (40, 20))
        self.assertEqual(self.pixel(out, 10, 10), "#2b2e39")
        self.assertEqual(self.pixel(out, 30, 10), "#ffffff")
        markup.set_crop((5, 5, 20, 10))
        out = fs.render_picture(self.picture(), markup)
        self.assertEqual((out.get_width(), out.get_height()), (20, 10))
        self.assertEqual(self.pixel(out, 0, 0), "#2b2e39")
        self.assertEqual(self.pixel(out, 15, 5), "#ffffff")

    def test_highlighter_lets_the_picture_through(self):
        markup = fs.Markup((40, 20))
        markup.add(shape("highlighter", ((5, 10), (35, 10)), color="#5294e2", width=3))
        color = self.pixel(fs.render_picture(self.picture(), markup), 20, 10)
        self.assertNotIn(color, ("#ffffff", "#5294e2"))

    def test_pen_arrow_and_box_draw(self):
        for tool, points, x, y in (("pen", [(20, 10)], 20, 10), ("arrow", [(2, 10), (38, 10)], 15, 10),
                                   ("rectangle", [(5, 5), (35, 15)], 5, 10)):
            markup = fs.Markup((40, 20))
            markup.add(shape(tool, points, color="#fc4138"))
            self.assertEqual(self.pixel(fs.render_picture(self.picture(), markup), x, y), "#fc4138", tool)

    def test_write_png_leaves_nothing_behind(self):
        folder = os.path.join(self.root, "out")
        os.makedirs(folder)
        path = os.path.join(folder, "a.png")
        fs.write_picture(self.picture(), path)
        with open(path, "rb") as f:
            self.assertEqual(f.read(4), b"\x89PNG")
        self.assertEqual(os.listdir(folder), ["a.png"])
        with self.assertRaises(OSError):
            fs.write_picture(self.picture(), os.path.join(self.root, "missing", "a.png"))


class PhoneTest(Sandbox):
    """Send to Phone: shown only while flickos-phone runs."""

    def setUp(self):
        super().setUp()
        self.edit_runtime = os.path.join(self.runtime, "flickos", "screenshot")
        os.makedirs(self.edit_runtime)
        self.link = os.path.join(self.runtime, "flickos", "bin", fs.PHONE_ON)

    def test_phone_on_only_while_its_daemon_runs(self):
        self.assertFalse(fs.phone_on(self.edit_runtime))
        self.stub("flickos-phone", "exit 0\n")
        self.assertFalse(fs.phone_on(self.edit_runtime))
        os.makedirs(os.path.dirname(self.link))
        os.symlink(os.path.join(self.bin, "flickos-phone"), self.link)
        self.assertTrue(fs.phone_on(self.edit_runtime))
        os.unlink(os.path.join(self.bin, "flickos-phone"))     # uninstalled, the link dangles
        self.assertFalse(fs.phone_on(self.edit_runtime))

    def test_sent_file_is_deleted_either_way(self):
        self.stub("flickos-phone", '/bin/cat "$2" > "$STUB_LOG/sent"; echo "$@" > "$STUB_LOG/phone"\n'
                                   '[ -z "$PHONE_FAILS" ] || { echo "flickos-phone: no phone is connected" >&2; exit 1; }\n'
                                   'echo "Sent to Pixel."\n')
        for fails in ("", "1"):
            path = os.path.join(self.edit_runtime, "Screenshot x.png")
            with open(path, "w") as f:
                f.write("picture")
            result = subprocess.run(fs.phone_send_argv(path), capture_output=True, text=True,
                                    env=dict(os.environ, PHONE_FAILS=fails))
            self.assertEqual(result.returncode, 1 if fails else 0)
            self.assertFalse(os.path.exists(path))
            with open(os.path.join(self.log, "phone")) as f:
                self.assertEqual(f.read(), f"send {path}\n")
            with open(os.path.join(self.log, "sent")) as f:
                self.assertEqual(f.read(), "picture")

    def test_picture_name(self):
        self.assertEqual(fs.picture_name("/p/Screenshot a.jpg", True), "Screenshot a.jpg")
        last = os.path.join(self.edit_runtime, fs.LAST)
        open(last, "w").close()
        os.utime(last, (0, time.mktime((2026, 9, 29, 10, 20, 30, 0, 0, -1))))
        self.assertEqual(fs.picture_name(last, False), "Screenshot 2026-09-29 10-20-30.png")
        os.unlink(last)                     # replaced meanwhile: now
        self.assertRegex(fs.picture_name(last, False), r"^Screenshot \d{4}-\d\d-\d\d \d\d-\d\d-\d\d\.png$")


class EditTest(Sandbox):
    def setUp(self):
        super().setUp()
        # cmd_edit ignores SIGUSR1 until its window handles it; not in the tests.
        patcher = mock.patch.object(fs.signal, "signal")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.picture = os.path.join(self.root, "a.png")
        open(self.picture, "w").close()
        self.edit_runtime = os.path.join(self.runtime, "flickos", "screenshot")

    def test_no_such_file(self):
        code, _out, err = self.run_main("edit", os.path.join(self.root, "nope.png"))
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)

    def test_first_edit_opens_the_window(self):
        opened = []
        sandbox = self

        class Editor:
            def __init__(self, gi, runtime):
                opened.append((gi, runtime))

            def run(self, path):
                with open(os.path.join(runtime, fs.EDIT_LOCK)) as f:
                    sandbox.assertEqual(f.read().strip(), str(os.getpid()))
                sandbox.assertFalse(os.path.exists(os.path.join(runtime, fs.EDIT_REQUEST)))
                opened.append(path)
                return True

        runtime = fs.runtime_dir()
        with open(os.path.join(runtime, fs.EDIT_REQUEST), "w") as f:
            f.write("/left/by/an/old/window.png\n")
        with mock.patch.object(fs, "load_gtk", lambda **_kw: "gtk"), mock.patch.object(fs, "Editor", Editor):
            os.chdir(self.root)
            self.addCleanup(os.chdir, HERE)
            code = self.run_main("edit", "a.png")[0]
        self.assertEqual((code, opened), (0, [("gtk", runtime), self.picture]))

    def test_second_edit_shows_its_picture_in_the_first(self):
        runtime = fs.runtime_dir()
        self.fake_process(os.getpid(), "python3", b"/usr/bin/python3\0/usr/bin/flickos-screenshot\0edit\0x.png\0")
        with fs.pid_lock(os.path.join(runtime, fs.EDIT_LOCK)), mock.patch.object(fs.os, "kill") as kill, \
                mock.patch.object(fs, "load_gtk") as gtk:
            code, out, _err = self.run_main("edit", self.picture)
        self.assertEqual(code, 0)
        self.assertIn("already open", out)
        kill.assert_called_once_with(os.getpid(), fs.signal.SIGUSR1)
        gtk.assert_not_called()
        self.assertEqual(fs.take_edit_request(runtime), self.picture)
        self.assertIsNone(fs.take_edit_request(runtime))
        self.assertEqual(sorted(os.listdir(runtime)), [fs.EDIT_LOCK])

    def test_a_lock_held_by_another_program_is_not_signalled(self):
        runtime = fs.runtime_dir()
        self.fake_process(os.getpid(), "python3", b"/usr/bin/python3\0/usr/bin/something-else\0")
        with fs.pid_lock(os.path.join(runtime, fs.EDIT_LOCK)), mock.patch.object(fs.os, "kill") as kill:
            code, _out, err = self.run_main("edit", self.picture)
        self.assertEqual(code, 1)
        self.assertIn("can't be asked", err)
        kill.assert_not_called()
        self.assertEqual(sorted(os.listdir(runtime)), [fs.EDIT_LOCK])


class ChooserTest(unittest.TestCase):
    """screencast-chooser, with a fake runtime folder and PATH: the fallback
    (slurp) is a stub that only says it was asked."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="flickos-chooser-test-")
        self.addCleanup(shutil.rmtree, self.root)
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        for tool in ("cat", "date", "stat", "rm", "grep", "head"):
            os.symlink(shutil.which(tool, path="/usr/bin:/bin"), os.path.join(self.bin, tool))
        self.request = os.path.join(self.root, "flickos", "screenshot", "screencast-request")
        os.makedirs(os.path.dirname(self.request))

    def fallback(self):
        path = os.path.join(self.bin, "slurp")
        with open(path, "w") as f:
            f.write("#!/bin/sh\necho asked\n")
        os.chmod(path, 0o755)

    def choose(self, outputs, request=None, age=0):
        if request is not None:
            with open(self.request, "w") as f:
                f.write(request + "\n")
            if age:
                old = time.time() - age
                os.utime(self.request, (old, old))
        result = subprocess.run(["/bin/sh", os.path.join(PACKAGE, CHOOSER)], input="\n".join(outputs) + "\n",
                                capture_output=True, text=True, timeout=30,
                                env={"PATH": self.bin, "XDG_RUNTIME_DIR": self.root})
        self.assertEqual(result.stderr, "")
        self.assertFalse(os.path.exists(self.request))
        return result.stdout

    def test_answers_a_fresh_request_for_a_listed_screen(self):
        self.fallback()
        self.assertEqual(self.choose(["eDP-1", "HDMI-A-1"], "HDMI-A-1"), "HDMI-A-1\n")

    def test_asks_for_a_stale_or_unknown_request_or_none(self):
        self.fallback()
        self.assertEqual(self.choose(["HDMI-A-1"], "HDMI-A-1", age=10), "asked\n")
        self.assertEqual(self.choose(["HDMI-A-1"], "DP-9"), "asked\n")
        self.assertEqual(self.choose(["HDMI-A-1"], ""), "asked\n")
        self.assertEqual(self.choose(["HDMI-A-1"]), "asked\n")

    def test_without_a_chooser_only_one_screen_is_answered(self):
        self.assertEqual(self.choose(["HDMI-A-1"]), "HDMI-A-1\n")
        self.assertEqual(self.choose(["HDMI-A-1", "DP-1"]), "")


class PackageTest(unittest.TestCase):
    def test_desktop_file(self):
        path = os.path.join(PACKAGE, "usr/share/applications/flickos-screenshot.desktop")
        with open(path) as f:
            text = f.read()
        self.assertIn(f"\nName={fs.TITLE}\n", text)
        self.assertIn("\nExec=flickos-screenshot\n", text)

    def test_docstring_names_every_command(self):
        for command in ("bar [--video|--photo]", "shot region|screen", "record region|screen", "stop",
                        "edit FILE", "status [--panel]", "area", "outline X Y W H", "notify FILE", "feedback"):
            self.assertIn(command, fs.__doc__)

    def test_portal_config_runs_the_chooser(self):
        with open(os.path.join(PACKAGE, "etc/xdg/xdg-desktop-portal-wlr/labwc")) as f:
            config = f.read()
        self.assertIn("\n[screencast]\n", config)
        self.assertIn("\nchooser_type=dmenu\n", config)
        self.assertIn(f"\nchooser_cmd=/{CHOOSER}\n", config)
        self.assertTrue(os.access(os.path.join(PACKAGE, CHOOSER), os.X_OK))
        with open(os.path.join(PACKAGE, CHOOSER)) as f:
            chooser = f.read()
        self.assertIn(f"/flickos/{fs.RUNTIME}/{fs.REQUEST}\n", chooser)
        with open(os.path.join(PACKAGE, "debian/install")) as f:
            install = f.read()
        self.assertIn("etc/xdg/xdg-desktop-portal-wlr/labwc", install)
        self.assertIn("usr/libexec/flickos/", install)

    def test_depends_on_every_element_package(self):
        with open(os.path.join(PACKAGE, "debian/control")) as f:
            control = f.read()
        for package in set(fs.ELEMENTS.values()) | {"gir1.2-gstreamer-1.0", "xdg-desktop-portal-wlr",
                                                    "wlr-randr"}:
            self.assertRegex(control, rf"\n +{re.escape(package)},", package)

    def test_tesseract_is_only_suggested(self):
        """Text is offered only while it is installed (ADR-011)."""
        with open(os.path.join(PACKAGE, "debian/control")) as f:
            control = f.read()
        self.assertRegex(control, r"\nSuggests: tesseract-ocr\n")
        depends = control.split("\nDepends:")[1].split("\nDescription:")[0]
        depends = [line for line in depends.splitlines() if not line.startswith(("#", "Suggests:"))]
        self.assertNotIn("tesseract", "\n".join(depends))


if __name__ == "__main__":
    unittest.main()
