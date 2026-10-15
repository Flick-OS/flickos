"""Tests for reloading waybar when the screens change (`supervise`,
ScreenWatch): waybar 0.12 keeps a second bar on a screen turned on while it
runs. Run: python3 -m unittest discover -s tests
"""

import os
import signal
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_engine import fl


def message(object_id, opcode, payload=b""):
    return struct.pack("=II", object_id, (8 + len(payload)) << 16 | opcode) + payload


def global_event(name, interface):
    text = interface.encode() + b"\0"
    text += b"\0" * (-len(text) % 4)
    return message(fl.ScreenWatch.REGISTRY, 0, struct.pack("=II", name, len(interface) + 1) + text
                   + struct.pack("=I", 4))


def global_remove(name):
    return message(fl.ScreenWatch.REGISTRY, 1, struct.pack("=I", name))


SYNC_DONE = message(fl.ScreenWatch.SYNC, 0, struct.pack("=I", 1))


class ScreenWatchTest(unittest.TestCase):
    """A fake compositor on the other end of a socket pair."""

    def setUp(self):
        self.compositor, client = socket.socketpair()
        self.addCleanup(self.compositor.close)
        self.changes = []
        self.watch = fl.ScreenWatch(client, lambda: self.changes.append(time.monotonic()), settle=0.05)
        self.thread = threading.Thread(target=self.run_watch, daemon=True)
        self.thread.start()

    def run_watch(self):
        with self.watch.sock:
            self.watch.run()

    def send(self, *messages):
        self.compositor.sendall(b"".join(messages))

    def wait(self, seconds=0.3):
        time.sleep(seconds)

    def test_asks_for_the_registry_and_a_sync(self):
        data = self.compositor.recv(64)
        self.assertEqual(data, message(1, 1, struct.pack("=I", 2)) + message(1, 0, struct.pack("=I", 3)))

    def test_screens_at_start_change_nothing(self):
        self.send(global_event(1, "wl_compositor"), global_event(50, "wl_output"), global_event(52, "wl_output"),
                  SYNC_DONE)
        self.wait()
        self.assertEqual(self.changes, [])
        self.assertEqual(self.watch.screens, {50, 52})

    def test_a_new_screen_reloads_once_it_settles(self):
        self.send(global_event(50, "wl_output"), SYNC_DONE)
        self.send(global_event(60, "wl_output"))
        self.send(global_remove(60), global_event(61, "wl_output"))     # off and on again at once
        self.wait()
        self.assertEqual(len(self.changes), 1)
        self.send(global_remove(61))
        self.wait()
        self.assertEqual(len(self.changes), 2)

    def test_other_globals_change_nothing(self):
        self.send(global_event(50, "wl_output"), SYNC_DONE, global_event(70, "wl_seat"), global_remove(70),
                  global_remove(99))
        self.wait()
        self.assertEqual(self.changes, [])

    def test_ends_with_the_compositor(self):
        self.send(SYNC_DONE)
        self.compositor.close()
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())


class SuperviseReloadTest(unittest.TestCase):
    """supervise sends waybar its reload signal when the screens changed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp))
        self.got = os.path.join(self.tmp, "got")
        # A stand-in waybar: records SIGUSR2, then ends cleanly.
        self.waybar = os.path.join(self.tmp, "waybar")
        with open(self.waybar, "w") as f:
            f.write(f"#!{sys.executable}\nimport signal, sys, time\n"
                    f"def got(*_):\n    open({self.got!r}, 'w').write('reload')\n    sys.exit(0)\n"
                    "signal.signal(signal.SIGUSR2, got)\ntime.sleep(10)\n")
        os.chmod(self.waybar, 0o755)

    def test_reload_signal(self):
        watching = []
        with mock.patch.object(fl, "watch_screens", lambda env, changed, desktops=None: watching.append(changed)), \
                mock.patch.object(fl, "log_line"):
            timer = threading.Timer(0.5, lambda: watching[0]())
            timer.start()
            status = fl.supervise([self.waybar], dict(os.environ))
        self.assertEqual(status, 0)
        with open(self.got) as f:
            self.assertEqual(f.read(), "reload")
        self.assertEqual(fl.RELOAD_ON_SCREENS["waybar"], signal.SIGUSR2)

    def test_only_waybar_is_watched(self):
        watching = []
        with mock.patch.object(fl, "watch_screens", lambda env, changed, desktops=None: watching.append(changed)):
            fl.supervise(["true"], dict(os.environ))
        self.assertEqual(watching, [])

    def test_wayland_path(self):
        self.assertEqual(fl.wayland_path({"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/1"}),
                         "/run/user/1/wayland-0")
        self.assertEqual(fl.wayland_path({"WAYLAND_DISPLAY": "/tmp/w"}), "/tmp/w")
        self.assertIsNone(fl.wayland_path({"WAYLAND_DISPLAY": "wayland-0"}))
        self.assertIsNone(fl.wayland_path({}))
