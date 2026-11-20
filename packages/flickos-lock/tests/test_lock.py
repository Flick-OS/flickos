"""Tests for usr/bin/flickos-lock. Run: python3 -m unittest discover -s tests

No display needed: the lock screen's GTK side is tried in a headless labwc
(docs/design/flickos-lock.md, ADR-010). PAM runs for real, through a private
PAM folder (pam_start_confdir) whose service accepts only one word.
"""

import ast
import contextlib
import fcntl
import glob
import importlib.machinery
import importlib.util
import io
import os
import pwd
import re
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
PACKAGES = os.path.dirname(PACKAGE)
PROGRAM = os.path.join(PACKAGE, "usr/bin/flickos-lock")

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_lock", PROGRAM)
fl = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fl)

# Never the build host's $XDG_RUNTIME_DIR or Wayland session.
RUNTIME = tempfile.TemporaryDirectory(prefix="flickos-lock-test-")
_environment = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": RUNTIME.name, "WAYLAND_DISPLAY": "wayland-test"})


def setUpModule():
    _environment.start()


def tearDownModule():
    _environment.stop()
    RUNTIME.cleanup()


class TempTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-lock-test-")
        self.addCleanup(shutil.rmtree, self.tmp)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def write(self, name, text=""):
        path = self.path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path


class ShownTest(TempTest):
    """What the lock screen shows, without GTK."""

    def test_split_image_as_swaylock(self):
        self.assertEqual(fl.split_image("/p/a.jpg"), (None, "/p/a.jpg"))
        self.assertEqual(fl.split_image("HDMI-A-1:/p/a.jpg"), ("HDMI-A-1", "/p/a.jpg"))
        self.assertEqual(fl.split_image("/p/b:c.jpg"), (None, "/p/b:c.jpg"))
        self.assertEqual(fl.split_image("DP-1:/p/b:c.jpg"), ("DP-1", "/p/b:c.jpg"))
        self.assertEqual(fl.split_image(":/p/a.jpg"), (None, "/p/a.jpg"))

    def test_image_for_a_screen(self):
        images = [("DP-1", "/dp.jpg"), (None, "/all.jpg"), ("HDMI-A-1", "/hdmi.jpg")]
        outputs = {"DP-1": (0, 0), "HDMI-A-1": (1920, 0)}
        self.assertEqual(fl.image_for(images, (1920, 0), outputs), "/hdmi.jpg")
        self.assertEqual(fl.image_for(images, (0, 0), outputs), "/dp.jpg")
        self.assertEqual(fl.image_for(images, (5000, 0), outputs), "/all.jpg")
        # Before wlr-randr answered: the picture for every output.
        self.assertEqual(fl.image_for(images, (0, 0), {}), "/all.jpg")
        self.assertIsNone(fl.image_for([("DP-1", "/dp.jpg")], (0, 0), {}))
        self.assertIsNone(fl.image_for([], (0, 0), outputs))

    def test_enabled_outputs(self):
        text = ('[{"name": "HDMI-A-1", "enabled": true, "position": {"x": 1488, "y": 0}},'
                ' {"name": "eDP-1", "enabled": false}]')
        self.assertEqual(fl.enabled_outputs(text), {"HDMI-A-1": (1488, 0)})
        self.assertEqual(fl.enabled_outputs("not json"), {})
        self.assertEqual(fl.enabled_outputs('{"a": 1}'), {})

    def test_placement(self):
        self.assertEqual(fl.placement((3840, 2160), (1920, 1080), "fill"), (1920, 1080, 0, 0))
        # A tall picture fills the width and is cut top and bottom.
        self.assertEqual(fl.placement((1000, 2000), (1000, 500), "fill"), (1000, 2000, 0, -750))
        self.assertEqual(fl.placement((1000, 2000), (1000, 500), "fit"), (250, 500, 375, 0))
        self.assertEqual(fl.placement((1000, 2000), (1000, 500), "stretch"), (1000, 500, 0, 0))
        self.assertEqual(fl.placement((100, 50), (1000, 500), "center"), (100, 50, 450, 225))

    def test_zoom_steps(self):
        self.assertEqual(fl.next_zoom(100, 1), 150)
        self.assertEqual(fl.next_zoom(300, 1), 300)
        self.assertEqual(fl.next_zoom(100, -1), 100)
        self.assertEqual(fl.next_zoom(200, -1), 150)
        self.assertEqual(fl.next_zoom(300, 0), 100)
        self.assertEqual(fl.next_zoom(170, 1), 200)            # nearest step first
        self.assertEqual(fl.zoom_css(150), ".flickos-lock .card { font-size: 150%; }\n")

    def test_zoom_kept_for_the_session(self):
        self.assertEqual(fl.read_zoom(self.tmp), 100)
        self.write("zoom", "200\n")
        self.assertEqual(fl.read_zoom(self.tmp), 200)
        self.write("zoom", "175\n")                            # not a step
        self.assertEqual(fl.read_zoom(self.tmp), 100)
        self.write("zoom", "big")
        self.assertEqual(fl.read_zoom(self.tmp), 100)

    def test_clock_format(self):
        self.assertEqual(fl.clock_format("24h\n"), "%H:%M")
        self.assertEqual(fl.clock_format("12h\n"), "%-I:%M %p")
        self.assertEqual(fl.clock_format(""), "%H:%M")          # flickos-layout missing
        self.assertEqual(fl.clock_format("odd"), "%H:%M")

    def test_name_and_picture(self):
        entry = pwd.struct_passwd(("jo", "x", 1000, 1000, "Jo Bloggs,,,", self.path("home"), "/bin/sh"))
        self.assertEqual(fl.display_name(entry), "Jo Bloggs")
        self.assertEqual(fl.display_name(pwd.struct_passwd(("jo", "x", 1, 1, ",,,", "/", "/bin/sh"))), "jo")
        self.assertEqual(fl.FACE_FILES[0], "/var/lib/AccountsService/icons/{user}")    # Settings' comes first
        with mock.patch.object(fl, "FACE_FILES", (self.path("accounts/{user}"), "~/.face")):
            face = self.write("home/.face", "picture")
            self.assertEqual(fl.picture_file(entry), face)
            accounts = self.write("accounts/jo", "picture")
            self.assertEqual(fl.picture_file(entry), accounts)
        with mock.patch.object(fl, "FACE_FILES", (self.path("accounts/{user}x"), "~/.none")):
            self.assertIsNone(fl.picture_file(entry))

    def test_live_session(self):
        self.write("proc/cmdline", "BOOT_IMAGE=/vmlinuz quiet\n")
        self.assertFalse(fl.live_session(self.path("proc")))
        self.write("proc/cmdline", "boot=live components quiet splash\n")
        self.assertTrue(fl.live_session(self.path("proc")))
        self.assertFalse(fl.live_session(self.path("missing")))

    def test_shared_screen(self):
        """ADR-011: no "show password" while recorded or on the second screen."""
        runtime = self.path("run")
        os.makedirs(runtime)
        self.assertFalse(fl.shared_screen(runtime))
        lock = self.write("run/screenshot/recording.lock", "1234\n")
        self.assertFalse(fl.shared_screen(runtime))           # left behind, nobody records
        with open(lock) as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertTrue(fl.shared_screen(runtime))
        self.assertFalse(fl.shared_screen(runtime))
        self.write("run/second-screen/on")
        self.assertTrue(fl.shared_screen(runtime))

    def test_moved_far(self):
        self.assertFalse(fl.moved_far(None, (100, 100)))
        self.assertFalse(fl.moved_far((10, 10), (15, 15)))
        self.assertTrue(fl.moved_far((10, 10), (30, 10)))


class PamTest(TempTest):
    """The real libpam, with a private PAM folder whose service accepts only
    the word "secret" (pam_exec gets the password on stdin)."""

    def setUp(self):
        super().setUp()
        check = self.write("check.sh", '#!/bin/sh\nread -r word\n[ "$word" = secret ]\n')
        os.chmod(check, 0o755)
        self.write("pam/test-lock", f"auth [success=1 default=ignore] pam_exec.so expose_authtok quiet {check}\n"
                                    "auth requisite pam_deny.so\nauth required pam_permit.so\n")
        for name, value in (("PAM_CONFDIR", self.path("pam")), ("PAM_SERVICE", "test-lock")):
            patcher = mock.patch.object(fl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.user = pwd.getpwuid(os.getuid()).pw_name

    def test_right_and_wrong(self):
        self.assertEqual(fl.authenticate(self.user, "secret")[0], fl.PAM_SUCCESS)
        code, words, _shown = fl.authenticate(self.user, "wrong")
        self.assertEqual(code, fl.PAM_AUTH_ERR)
        self.assertTrue(words)
        self.assertEqual(fl.authenticate(self.user, "")[0], fl.PAM_AUTH_ERR)
        self.assertEqual(fl.authenticate(self.user, "secret and more")[0], fl.PAM_AUTH_ERR)

    def test_messages_are_passed_on(self):
        self.write("pam/test-lock", "auth requisite pam_echo.so Account locked by the test\n"
                                    "auth requisite pam_deny.so\n")
        code, _words, shown = fl.authenticate(self.user, "secret")
        self.assertEqual(code, fl.PAM_AUTH_ERR)
        self.assertEqual(shown, ["Account locked by the test"])

    def test_no_service(self):
        with mock.patch.object(fl, "PAM_SERVICE", "missing-service"):
            self.assertNotEqual(fl.authenticate(self.user, "secret")[0], fl.PAM_SUCCESS)



class PackageTest(unittest.TestCase):
    def test_depends_on_the_library_itself(self):
        """trixie's gir1.2-gtksessionlock-0.1 doesn't depend on its library."""
        with open(os.path.join(PACKAGE, "debian/control"), encoding="utf-8") as f:
            depends = re.search(r"^Depends:(.*?)(?=^\S)", f.read(), re.M | re.S).group(1)
        names = {part.split()[0] for part in depends.replace("\n", " ").split(",") if part.strip()}
        self.assertLessEqual({"gir1.2-gtksessionlock-0.1", "libgtk-session-lock0", "python3-gi-cairo",
                              "swaylock", "libpam0g"}, names)


class PamServiceTest(unittest.TestCase):
    def test_service_file(self):
        """ADR-005: common-auth only, not login's stack (pam_nologin)."""
        with open(os.path.join(PACKAGE, "etc/pam.d/flickos-lock"), encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        self.assertEqual(lines, ["@include common-auth"])
        self.assertEqual(fl.PAM_SERVICE, "flickos-lock")
        self.assertIsNone(fl.PAM_CONFDIR)


class FakeCompositor:
    """Just enough of a Wayland compositor for PreLock: a registry with or
    without ext_session_lock_manager_v1, then locked, finished or silence."""

    def __init__(self, answer="locked", manager=True):
        self.client, self.server = socket.socketpair()
        self.answer, self.manager, self.requests = answer, manager, []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def send(self, object_id, opcode, payload=b""):
        self.server.sendall(struct.pack("=II", object_id, (8 + len(payload)) << 16 | opcode) + payload)

    def requests_from(self):
        buffer = b""
        while True:
            while len(buffer) >= 8:
                object_id, word = struct.unpack_from("=II", buffer)
                size = word >> 16
                if len(buffer) < size:
                    break
                yield object_id, word & 0xFFFF, buffer[8:size]
                buffer = buffer[size:]
            data = self.server.recv(4096)
            if not data:
                return
            buffer += data

    def serve(self):
        for object_id, opcode, payload in self.requests_from():
            self.requests.append((object_id, opcode))
            if (object_id, opcode) == (1, 0):                  # sync: list the globals first
                callback = struct.unpack("=I", payload)[0]
                for name, interface in ((1, b"wl_compositor"), (7, b"ext_session_lock_manager_v1")):
                    if interface.startswith(b"ext") and not self.manager:
                        continue
                    data = interface + b"\0"
                    self.send(2, 0, struct.pack("=II", name, len(data)) + data + b"\0" * (-len(data) % 4)
                              + struct.pack("=I", 1))
                self.send(callback, 0, struct.pack("=I", 0))
            elif (object_id, opcode) == (4, 1):                # manager.lock(new_id)
                lock = struct.unpack("=I", payload)[0]
                if self.answer == "locked":
                    self.send(lock, 0)
                elif self.answer == "finished":
                    self.send(lock, 1)

    def close(self):
        self.server.close()
        self.client.close()


class PreLockTest(unittest.TestCase):
    def prelock(self, **kwargs):
        compositor = FakeCompositor(**kwargs)
        self.addCleanup(compositor.close)
        compositor.client.settimeout(0.5)
        return fl.PreLock(compositor.client), compositor

    def test_locked(self):
        pre, compositor = self.prelock()
        self.assertTrue(pre.lock())
        self.assertIn((2, 0), compositor.requests)            # bound the manager
        self.assertIn((4, 1), compositor.requests)            # asked to lock
        pre.abandon()
        pre.abandon()                                          # twice is fine
        self.assertIsNone(pre.sock)

    def test_refused(self):
        pre, _compositor = self.prelock(answer="finished")
        self.assertFalse(pre.lock())

    def test_no_protocol(self):
        pre, _compositor = self.prelock(manager=False)
        with self.assertRaisesRegex(fl.LockError, "no ext-session-lock-v1"):
            pre.lock()

    def test_no_answer(self):
        pre, _compositor = self.prelock(answer=None)
        with self.assertRaisesRegex(fl.LockError, "didn't answer"):
            pre.lock()

    def test_no_session(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": ""}):
            with self.assertRaisesRegex(fl.LockError, "not in a Wayland session"):
                fl.PreLock.connect()
        with self.assertRaisesRegex(fl.LockError, "cannot reach the compositor"):
            fl.PreLock.connect()                               # wayland-test doesn't exist


class SingleLockTest(TempTest):
    """ADR-003: one lock; a second request waits until the first has locked."""

    def test_free(self):
        lock = fl.take_lock_or_wait(self.tmp, timeout=0.2)
        self.addCleanup(lock.close)
        self.assertIsNotNone(lock)

    def test_already_locked(self):
        first = fl.take_lock_or_wait(self.tmp, timeout=0.2)
        self.addCleanup(first.close)
        self.write(fl.LOCKED_FILE, "1\n")
        self.assertIsNone(fl.take_lock_or_wait(self.tmp, timeout=0.2))

    def test_waits_for_the_first(self):
        first = fl.take_lock_or_wait(self.tmp, timeout=0.2)
        self.addCleanup(first.close)
        threading.Timer(0.15, lambda: self.write(fl.LOCKED_FILE, "1\n")).start()
        start = time.monotonic()
        self.assertIsNone(fl.take_lock_or_wait(self.tmp, timeout=2))
        self.assertGreater(time.monotonic() - start, 0.1)

    def test_first_never_locks(self):
        first = fl.take_lock_or_wait(self.tmp, timeout=0.2)
        self.addCleanup(first.close)
        with self.assertRaisesRegex(fl.LockError, "didn't finish locking"):
            fl.take_lock_or_wait(self.tmp, timeout=0.2)

    def test_stale_marker_after_a_dead_guard(self):
        """The marker of a guard that died doesn't count: the flock is free."""
        self.write(fl.LOCKED_FILE, "1\n")
        lock = fl.take_lock_or_wait(self.tmp, timeout=0.2)
        self.addCleanup(lock.close)
        self.assertIsNotNone(lock)


STAND_IN = """#!/usr/bin/python3
import sys, time
steps = sys.argv[1].split(",")
for step in steps:
    if step == "go":
        if sys.stdin.readline().strip() != "go":
            sys.exit(5)
    elif step.startswith("exit"):
        sys.exit(int(step[4:]))
    elif step == "hang":
        time.sleep(30)
    else:
        print(step.replace("_", " "), flush=True)
"""


class GuardTest(TempTest):
    """ADR-004: whatever goes wrong ends in swaylock holding the lock."""

    def setUp(self):
        super().setUp()
        self.stand_in = self.write("screen", STAND_IN)
        os.chmod(self.stand_in, 0o755)
        self.write(fl.LOCKED_FILE, "1\n")
        self.pre = mock.Mock()
        self.swaylock = mock.Mock(return_value=0)
        self.hooks = mock.Mock()
        self.opts = mock.Mock(image=["/w.jpg"], scaling="fill", class_message=None, release=None, class_image=None)

    def guard(self, steps):
        import subprocess

        def start(command, **kwargs):
            self.command = command
            return subprocess.Popen([sys.executable, self.stand_in, steps], **kwargs)
        with mock.patch.object(fl, "READY_SECONDS", 1), mock.patch.object(fl, "LOCK_TIMEOUT", 1), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            status = fl.guard(self.pre, self.opts, 123.5, self.tmp, start=start, run=self.swaylock,
                              hooks=self.hooks)
        self.log = err.getvalue()
        return status

    def test_unlocked(self):
        self.assertEqual(self.guard("ready,go,locked,unlocked_2,exit0"), 0)
        self.pre.abandon.assert_called()
        self.swaylock.assert_not_called()
        self.assertFalse(os.path.exists(self.path(fl.LOCKED_FILE)))
        self.assertEqual(self.command[-4:], ["--image", "/w.jpg", "--scaling", "fill"][-2:] + ["--grace-until",
                                                                                              "123.500"])
        self.assertIn("unlocked 2", self.log)
        self.assertEqual(self.hooks.call_args_list, [mock.call("locked"), mock.call("unlocked")])

    def test_hooks_after_the_events_not_before(self):
        order = []
        self.pre.abandon.side_effect = lambda: order.append("abandon")
        self.hooks.side_effect = lambda event: order.append(event)
        self.guard("ready,go,locked,unlocked_2,exit0")
        self.assertEqual(order, ["abandon", "locked", "unlocked"])
        self.assertFalse(os.path.exists(self.path(fl.LOCKED_FILE)))     # the marker is gone before `unlocked`

    def test_a_hook_bug_cannot_end_the_guard(self):
        self.hooks.side_effect = RuntimeError("boom")
        self.assertEqual(self.guard("ready,go,locked,unlocked_2,exit0"), 0)
        self.swaylock.assert_not_called()
        self.assertIn("hooks locked: RuntimeError('boom')", self.log)
        self.assertIn("hooks unlocked: RuntimeError('boom')", self.log)

    def test_dies_before_ready(self):
        self.assertEqual(self.guard("exit1"), 0)
        self.hooks.assert_not_called()
        self.pre.abandon.assert_called()
        self.assertEqual(self.swaylock.call_args.args[0][0], "swaylock")
        self.assertIn("swaylock takes over", self.log)

    def test_never_ready(self):
        self.assertEqual(self.guard("hang"), 0)
        self.swaylock.assert_called_once()

    def test_never_takes_over(self):
        self.assertEqual(self.guard("ready,go,hang"), 0)
        self.hooks.assert_not_called()
        self.swaylock.assert_called_once()

    def test_dies_while_locked(self):
        self.assertEqual(self.guard("ready,go,locked,exit1"), 0)
        self.assertEqual(self.hooks.call_args_list, [mock.call("locked")])      # swaylock's unlock is no `unlocked`
        self.swaylock.assert_called_once()
        self.assertFalse(os.path.exists(self.path(fl.LOCKED_FILE)))

    def test_ends_without_unlocking(self):
        self.assertEqual(self.guard("ready,go,locked,exit0"), 0)
        self.swaylock.assert_called_once()

    def test_swaylock_failing(self):
        self.swaylock.return_value = 1
        self.assertEqual(self.guard("exit1"), 1)

    def test_class_lock(self):
        """The screen is told the message and the release file; the class
        mark goes with the lock, whether the screen unlocked or died."""
        self.opts.class_message, self.opts.release = "Eyes up", "/run/x/release"
        self.write(fl.CLASS_FILE, "/run/x/release\n")
        self.assertEqual(self.guard("ready,go,locked,unlocked_0,exit0"), 0)
        self.assertEqual(self.command[-4:], ["--class-message", "Eyes up", "--release", "/run/x/release"])
        self.assertFalse(os.path.exists(self.path(fl.CLASS_FILE)))
        self.write(fl.CLASS_FILE, "/run/x/release\n")
        self.assertEqual(self.guard("ready,go,locked,exit1"), 0)
        self.swaylock.assert_called_once()          # swaylock: the student's own password
        self.assertFalse(os.path.exists(self.path(fl.CLASS_FILE)))

    def test_demo_class_lock(self):
        """A demo (--class-image) is a class lock: the screen is told the picture too."""
        self.opts.class_message, self.opts.release = "Look", "/run/x/release"
        self.opts.class_image = "/run/x/demo.jpg"
        self.write(fl.CLASS_FILE, "/run/x/release\n")
        self.assertEqual(self.guard("ready,go,locked,unlocked_0,exit0"), 0)
        self.assertEqual(self.command[-6:], ["--class-message", "Look", "--release", "/run/x/release",
                                             "--class-image", "/run/x/demo.jpg"])


class ClassLockTest(TempTest):
    """flickos-classroom-view's class lock (its ADR-007)."""

    def test_release(self):
        release = self.write("release", "x\n")
        now = os.stat(release).st_mtime
        self.assertIsNone(fl.class_release(release, now + 1))
        self.assertIsNone(fl.class_release(release, now + fl.CLASS_FAILSAFE - 1))
        self.assertEqual(fl.class_release(release, now + fl.CLASS_FAILSAFE), "failsafe")
        os.unlink(release)
        self.assertEqual(fl.class_release(release), "teacher")

    def test_a_lock_during_a_class_lock_is_remembered(self):
        first = fl.take_lock_or_wait(self.tmp, timeout=0.2)
        self.addCleanup(first.close)
        self.write(fl.LOCKED_FILE, "1\n")
        self.assertIsNone(fl.take_lock_or_wait(self.tmp, timeout=0.2))
        self.assertFalse(os.path.exists(self.path(fl.WANTED_FILE)))     # an ordinary lock: nothing to remember
        self.write(fl.CLASS_FILE, "/run/x/release\n")
        self.assertIsNone(fl.take_lock_or_wait(self.tmp, timeout=0.2))
        self.assertTrue(os.path.exists(self.path(fl.WANTED_FILE)))

    def test_released_only_by_class_release(self):
        with open(PROGRAM, encoding="utf-8") as f:
            source = f.read()
        check = source[source.index("    def check_release("):source.index("    def add_screen(")]
        self.assertIn("why = class_release(self.opts.release)\n        if why is None:\n            return True", check)
        self.assertLess(check.index("WANTED_FILE"), check.index('self.unlock("teacher")'))

    def test_demo_frames_only_during_a_class_lock(self):
        with open(PROGRAM, encoding="utf-8") as f:
            source = f.read()
        demo = source[source.index("    def check_demo("):source.index("    def load_demo(")]
        self.assertIn("if not self.class_lock:\n            return False", demo)
        check = source[source.index("    def check_release("):source.index("    def add_screen(")]
        # The password box back (the computer locked itself meanwhile): the teacher's picture goes.
        self.assertLess(check.index("self.demo.clear()"), check.index("screen.show_password(True)"))

    def test_load_demo_scales_only_when_the_size_differs(self):
        pixbuf = mock.Mock(get_width=mock.Mock(return_value=1920), get_height=mock.Mock(return_value=1080))
        pixbuf.scale_simple.return_value = "scaled"
        gdkpixbuf = mock.Mock()
        gdkpixbuf.Pixbuf.new_from_file.return_value = pixbuf
        screen = mock.Mock(GdkPixbuf=gdkpixbuf, opts=mock.Mock(class_image="/run/x/demo.jpg"))
        fl.LockScreen.load_demo(screen, {"same": (1920, 1080, 1), "small": (1366, 768, 1), "none": (0, 0, 1)})
        frames = screen.GLib.idle_add.call_args.args[1]
        self.assertIs(frames["same"][0], pixbuf)                   # the teacher's own size: no copy
        self.assertEqual(frames["small"][0], "scaled")
        pixbuf.scale_simple.assert_called_once_with(1365, 768, gdkpixbuf.InterpType.BILINEAR)  # fits, keeps 16:9
        self.assertNotIn("none", frames)                           # a screen not drawn yet

    def test_no_keys_during_a_class_lock(self):
        with open(PROGRAM, encoding="utf-8") as f:
            source = f.read()
        key = source[source.index("    def on_key("):source.index("    def on_scroll(")]
        self.assertLess(key.index("if self.class_lock:\n            return True"), key.index("self.in_grace()"))


class FireTest(TempTest):
    """fire() is the contract of docs/design/flickos-hooks.md, ADR-004: with no
    hooks it does nothing, with some it starts `flickos-hooks run EVENT` and
    returns at once, and it never fails. A stand-in flickos-hooks on PATH
    records how it was started."""

    def setUp(self):
        super().setUp()
        self.config = self.path("config")
        self.bin = self.path("bin")
        self.stand_in = self.write("bin/flickos-hooks", '''#!/bin/sh
d=$(dirname "$0")
echo "$$" > "$d/pid"
echo "$@" > "$d/args"
env | grep '^FLICKOS_' | sort > "$d/env.tmp"
mv "$d/env.tmp" "$d/env"
exec sleep "${HOOK_STAND_IN_SLEEP:-0}"
''')
        os.chmod(self.stand_in, 0o755)
        env = {key: value for key, value in os.environ.items() if not key.startswith("FLICKOS_")}
        env.update(XDG_CONFIG_HOME=self.config, PATH=self.bin + ":" + os.environ["PATH"])
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.kill_stand_in)

    def kill_stand_in(self):
        with contextlib.suppress(OSError, ValueError):
            with open(self.path("bin/pid"), encoding="utf-8") as f:
                os.kill(int(f.read()), 9)

    def folder(self, event="locked", files=("10-hook",)):
        os.makedirs(os.path.join(self.config, "flickos", "hooks", event + ".d"))
        for name in files:
            self.write(f"config/flickos/hooks/{event}.d/{name}", "#!/bin/sh\n")

    def started(self, wait=3):
        """Whether the stand-in has run (env, written last, is there)."""
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if os.path.exists(self.path("bin/env")):
                time.sleep(0.05)
                return True
            time.sleep(0.02)
        return False

    def test_no_folder_no_hooks_no_start(self):
        fl.fire("locked")
        self.assertFalse(self.started(0.3))

    def test_an_empty_folder_starts_nothing(self):
        self.folder(files=())
        fl.fire("locked")
        self.assertFalse(self.started(0.3))

    def test_a_hook_starts_the_runner_with_the_event_and_values(self):
        self.folder()
        fl.fire("locked", file="/tmp/a b", phone_id="x")
        self.assertTrue(self.started())
        self.assertEqual(self.read_file("bin/args"), "run locked\n")
        env = self.read_file("bin/env")
        self.assertIn("FLICKOS_FILE=/tmp/a b\n", env)
        self.assertIn("FLICKOS_PHONE_ID=x\n", env)

    def read_file(self, name):
        with open(self.path(name), encoding="utf-8") as f:
            return f.read()

    def test_another_events_folder_does_not_count(self):
        self.folder("woke")
        fl.fire("locked")
        self.assertFalse(self.started(0.3))

    def test_it_does_not_wait_for_the_hooks(self):
        self.folder()
        with mock.patch.dict(os.environ, {"HOOK_STAND_IN_SLEEP": "30"}):
            begin = time.monotonic()
            fl.fire("locked")
            self.assertLess(time.monotonic() - begin, 2)
            self.assertTrue(self.started())

    def test_the_plain_session_and_hooks_start_nothing(self):
        self.folder()
        for variable in ("FLICKOS_PLAIN", "FLICKOS_HOOK"):
            with self.subTest(variable), mock.patch.dict(os.environ, {variable: "1"}):
                fl.fire("locked")
                self.assertFalse(self.started(0.3))

    def test_a_missing_runner_is_not_an_error(self):
        self.folder()
        os.unlink(self.stand_in)
        fl.fire("locked")                                           # setsid is there, flickos-hooks isn't
        with mock.patch.dict(os.environ, {"PATH": self.bin}):       # neither is setsid
            fl.fire("locked")


class HooksCallersTest(unittest.TestCase):
    """Hooks are fired by the guard, after the lock is confirmed and after the
    unlock, and by nothing else (hooks design, risks: the lock screen)."""

    def tree(self):
        with open(PROGRAM, encoding="utf-8") as f:
            return ast.parse(f.read())

    def callers(self, name):
        found = []
        for function in ast.walk(self.tree()):
            if isinstance(function, ast.FunctionDef):
                for node in ast.walk(function):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
                        found.append((function.name, [a.value for a in node.args if isinstance(a, ast.Constant)]))
        return found

    def test_only_the_guard_fires_and_only_these_two(self):
        self.assertEqual(sorted(self.callers("fire_hooks")), [("guard", ["locked"]), ("guard", ["unlocked"])])
        self.assertEqual(self.callers("fire"), [])          # reached only through guard's `hooks`

    def test_no_class_calls_hooks(self):
        """The lock screen (its classes) decides the unlock; it must not run user programs."""
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.ClassDef):
                for call in ast.walk(node):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                        self.assertNotIn(call.func.id, ("fire", "fire_hooks"), node.name)


class SwaylockTest(unittest.TestCase):
    def test_fallback_command(self):
        runtime = os.path.join(RUNTIME.name, "flickos")
        style = os.path.join(runtime, fl.SWAYLOCK_STYLE)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(style)
        self.assertEqual(fl.swaylock_command(["/w.jpg", "DP-1:/d.jpg"], "fit"),
                         ["swaylock", "-c", "383c4a", "-i", "/w.jpg", "-i", "DP-1:/d.jpg", "-s", "fit"])
        self.assertEqual(fl.swaylock_command([], None, daemonize=True), ["swaylock", "-f", "-c", "383c4a"])
        os.makedirs(os.path.dirname(style), exist_ok=True)
        with open(style, "w") as f:
            f.write("color=383c4aff\n")
        self.addCleanup(os.unlink, style)
        self.assertEqual(fl.swaylock_command([], None), ["swaylock", "-C", style])

    def test_style_path_is_flickos_layouts(self):
        """flickos-layouts writes it (STYLE_PALETTES/SWAYLOCK_PALETTE), flickos-control reads the same."""
        source = os.path.join(PACKAGES, "flickos-layouts/usr/bin/flickos-layout")
        if not os.path.exists(source):
            self.skipTest("flickos-layouts is not in this tree")
        with open(source, encoding="utf-8") as f:
            text = f.read()
        folder = re.search(r'^STYLE_PALETTES = "(.*)"', text, re.M).group(1)
        name = re.search(r'^SWAYLOCK_PALETTE = "(.*)"', text, re.M).group(1)
        self.assertEqual(fl.SWAYLOCK_STYLE, os.path.join(folder, name))


class CommandTest(TempTest):
    def main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            status = fl.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def test_usage(self):
        self.assertEqual(self.main()[0], 2)
        with self.assertRaises(SystemExit):
            self.main("lock", "--scaling", "sideways")

    def test_lock_without_compositor_uses_swaylock(self):
        with mock.patch.object(fl.os, "execvp") as execvp:
            execvp.side_effect = SystemExit(0)
            with self.assertRaises(SystemExit):
                self.main("lock", "--image", "/w.jpg", "--scaling", "fit")
        self.assertEqual(execvp.call_args.args[1][:2], ["swaylock", "-f"])
        self.assertEqual(execvp.call_args.args[1][-4:], ["-i", "/w.jpg", "-s", "fit"])

    def test_already_locked(self):
        folder = fl.lock_folder()
        first = fl.take_lock_or_wait(folder, timeout=0.2)
        self.addCleanup(first.close)
        with open(os.path.join(folder, fl.LOCKED_FILE), "w") as f:
            f.write("1\n")
        self.addCleanup(os.unlink, os.path.join(folder, fl.LOCKED_FILE))
        self.assertEqual(self.main("lock")[0], 0)

    def test_empty_image(self):
        status, _out, err = self.main("lock", "--image", "DP-1:")
        self.assertEqual(status, 1)
        self.assertIn("no picture", err)

    def test_class_image_needs_a_class_lock(self):
        status, _out, err = self.main("lock", "--class-image", "/run/x/demo.jpg")
        self.assertEqual(status, 1)
        self.assertIn("--class-image is for a class lock", err)

    def test_class_lock_arguments(self):
        self.assertEqual(self.main("lock", "--class-message", "x")[0], 1)
        self.assertEqual(self.main("lock", "--release", "/run/x")[0], 1)
        status, _out, err = self.main("lock", "--class-message", "x", "--release", "/run/x", "--grace")
        self.assertEqual(status, 1)
        self.assertIn("no grace period", err)


class UnlockPathTest(unittest.TestCase):
    """ADR-005: unlock_and_destroy has one caller, unlock(); unlock() is called
    only after PAM_SUCCESS, within the grace period, or when a class lock is
    released (by the teacher or the failsafe)."""

    def calls(self, name):
        with open(PROGRAM, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = []
        for function in ast.walk(tree):
            if isinstance(function, ast.FunctionDef):
                for node in ast.walk(function):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                            and node.func.attr == name:
                        found.append((function.name, ast.literal_eval(node.args[0]) if node.args else None))
        return found

    def test_one_caller(self):
        self.assertEqual(self.calls("unlock_and_destroy"), [("unlock", None)])

    def test_unlock_reasons(self):
        self.assertEqual(sorted(self.calls("unlock")),
                         [("check_release", "failsafe"), ("check_release", "teacher"), ("checked", "password"),
                          ("on_key", "grace"), ("on_motion", "grace")])

    def test_password_only_after_success(self):
        with open(PROGRAM, encoding="utf-8") as f:
            source = f.read()
        checked = source[source.index("    def checked("):source.index("    def in_grace(")]
        self.assertIn('if code == PAM_SUCCESS:\n            self.unlock("password")', checked)

    def test_grace_only_in_grace(self):
        with open(PROGRAM, encoding="utf-8") as f:
            source = f.read()
        key = source[source.index("    def on_key("):source.index("    def on_scroll(")]
        self.assertIn('if self.in_grace():\n            self.unlock("grace")', key)
        motion = source[source.index("    def on_motion("):source.index("    def set_zoom(")]
        self.assertIn("if not self.in_grace():\n            return False", motion)

    def test_grace_counts_time_asleep(self):
        """The deadline is on CLOCK_BOOTTIME, set by the front, read by the lock screen."""
        with open(PROGRAM, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("grace_until = boottime() + GRACE_SECONDS if opts.grace else 0", source)
        self.assertIn("return not self.unlocked and boottime() < self.grace_until", source)
        # Monotonic first: the two are equal until the first suspend, so
        # boottime read first could be the smaller by the time between them.
        before = time.monotonic()
        self.assertGreaterEqual(fl.boottime(), before)


def luminance(rgb):
    def channel(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def hex_color(text):
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))


class StyleTest(unittest.TestCase):
    def css(self):
        with open(os.path.join(PACKAGE, "usr/share/flickos/lock/style.css"), encoding="utf-8") as f:
            return f.read()

    def test_card_alpha_is_the_programs(self):
        alpha = re.search(r"\.card \{[^}]*alpha\(@theme_bg_color, ([\d.]+)\)", self.css()).group(1)
        self.assertEqual(float(alpha), fl.CARD_ALPHA)

    def test_theme_colors_only(self):
        """VIS-1/VIS-2: no written-out colors; every selector under .flickos-lock (VIS-4)."""
        css = re.sub(r"/\*.*?\*/", "", self.css(), flags=re.S)
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,8}\b|rgba?\(")
        for selector in re.findall(r"([^{}]+)\{", css):
            for part in selector.split(","):
                self.assertTrue(part.strip().startswith(".flickos-lock"), part)

    def test_text_readable_on_the_card_in_every_style(self):
        """ADR-007 (Q4): the style's text color on its background at
        CARD_ALPHA passes 4.5:1 over a black and over a white wallpaper."""
        palettes = glob.glob(os.path.join(PACKAGES, "*/usr/share/flickos/styles/*/waybar-colors.css"))
        if not palettes:
            self.skipTest("no styles in this tree")
        for palette in palettes:
            with open(palette, encoding="utf-8") as f:
                colors = dict(re.findall(r"@define-color (\w+) (#[0-9a-fA-F]{6});", f.read()))
            if "fg_color" not in colors or "bg_color" not in colors:
                continue
            fg, bg = hex_color(colors["fg_color"]), hex_color(colors["bg_color"])
            for wall in ((0, 0, 0), (1, 1, 1)):
                card = tuple(fl.CARD_ALPHA * c + (1 - fl.CARD_ALPHA) * w for c, w in zip(bg, wall))
                with self.subTest(palette=palette, wall=wall):
                    self.assertGreaterEqual(contrast(fg, card), 4.5)


class SharedPathsTest(unittest.TestCase):
    """The files other packages own (ADR-011, ADR-019's clock)."""

    def constant(self, package, program, name):
        path = os.path.join(PACKAGES, package, program)
        if not os.path.exists(path):
            self.skipTest(f"{package} is not in this tree")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        return text, re.search(rf'^{name} = (.*?)(?:\s+#.*)?$', text, re.M).group(1)

    def test_recording_lock(self):
        text, runtime = self.constant("flickos-screenshot", "usr/bin/flickos-screenshot", "RUNTIME")
        lock = re.search(r'^RECORDING_LOCK = "(.*?)"', text, re.M).group(1)
        self.assertEqual(fl.RECORDING_LOCK, os.path.join(runtime.strip('"'), lock))

    def test_second_screen_file(self):
        _text, value = self.constant("flickos-phone", "usr/bin/flickos-phone", "SECOND_SCREEN_FILE")
        self.assertEqual(fl.SECOND_SCREEN_FILE, os.path.join(*re.findall(r'"(.*?)"', value)[1:]))

    def test_clock_choices(self):
        text, _value = self.constant("flickos-layouts", "usr/bin/flickos-layout", "CLOCKS")
        block = text[text.index("\nCLOCKS = "):]
        block = block[:block.index("\n)") + 2] if "\n)" in block[:400] else block[:block.index("\n\n")]
        for choice in re.findall(r'"(\d+h)"', block):
            self.assertIn(choice, fl.CLOCK_FORMATS)


if __name__ == "__main__":
    unittest.main()
