"""Tests for the desktop buttons in waybar (docs/design/flickos-ricing.md,
phase 5 step 5a): the flickos/desktops module, the buttons' files, the
listener in ScreenWatch, supervise's signal, and usr/libexec/flickos/desktop.
Run: python3 -m unittest discover -s tests
"""

import importlib.machinery
import importlib.util
import json
import os
import shlex
import shutil
import signal
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_engine import PACKAGE, EngineTest, fl, read

_loader = importlib.machinery.SourceFileLoader("flickos_desktop", os.path.join(PACKAGE, "usr/libexec/flickos/desktop"))
helper = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(helper)

MANAGER = fl.ScreenWatch.WORKSPACES


def message(object_id, opcode, payload=b""):
    return struct.pack("=II", object_id, (8 + len(payload)) << 16 | opcode) + payload


def string(text):
    raw = text.encode() + b"\0"
    return struct.pack("=I", len(raw)) + raw + b"\0" * (-len(raw) % 4)


def global_event(name, interface, registry=2):
    return message(registry, 0, struct.pack("=I", name) + string(interface) + struct.pack("=I", 1))


def workspace(object_id, name, active=False):
    """A desktop as labwc announces it: new handle, name, state."""
    return (message(MANAGER, 1, struct.pack("=I", object_id)) + message(object_id, 1, string(name))
            + message(object_id, 3, struct.pack("=I", 1 if active else 0)))


def state(object_id, active):
    return message(object_id, 3, struct.pack("=I", 1 if active else 0))


def removed(object_id):
    return message(object_id, 5)


DONE = message(MANAGER, 2)


def parse(data):
    """[(object, opcode, payload)] of whole messages in data."""
    found = []
    while len(data) >= 8:
        object_id, word = struct.unpack_from("=II", data)
        found.append((object_id, word & 0xFFFF, data[8:word >> 16]))
        data = data[word >> 16:]
    return found


class ExpandTest(unittest.TestCase):

    def bars(self):
        return [{"name": "top", "modules-left": ["custom/launcher", "flickos/desktops"], "modules-right": ["clock"]},
                {"name": "other", "modules-center": ["clock"]}]

    def test_one_button_per_desktop(self):
        bars = self.bars()
        self.assertTrue(fl.expand_desktops(bars, 3))
        top, other = bars
        names = ["custom/desk#1", "custom/desk#2", "custom/desk#3"]
        self.assertEqual(top["modules-left"], ["custom/launcher"] + names)
        helper_path = shlex.quote(fl.DESKTOP_HELPER)
        self.assertEqual(top["custom/desk#2"], {
            "exec": 'cat "$XDG_RUNTIME_DIR/flickos/desktops/2.json" 2>/dev/null',
            "return-type": "json", "interval": "once", "signal": 11,
            "on-click": f"{helper_path} 2", "on-scroll-up": f"{helper_path} previous",
            "on-scroll-down": f"{helper_path} next"})
        self.assertNotIn("custom/desk#1", other)

    def test_one_desktop_has_no_buttons(self):
        bars = self.bars()
        self.assertFalse(fl.expand_desktops(bars, 1))
        self.assertEqual(bars[0]["modules-left"], ["custom/launcher"])
        self.assertFalse(any(key.startswith("custom/desk") for key in bars[0]))

    def test_no_placeholder(self):
        bars = [{"modules-left": ["clock"]}]
        self.assertFalse(fl.expand_desktops(bars, 4))
        self.assertEqual(bars, [{"modules-left": ["clock"]}])

    def test_signal_is_free(self):
        """No module FlickOS ships takes the desktop buttons' signal."""
        modules = fl.load_jsonc(os.path.join(PACKAGE, "usr/share/flickos/layouts/common/modules.jsonc"))
        taken = [settings.get("signal") for settings in modules.values() if isinstance(settings, dict)]
        self.assertNotIn(fl.DESKTOPS_SIGNAL, taken)
        self.assertEqual(fl.DESKTOPS_SIGNAL, 11)


class FilesTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.folder = os.path.join(self.root, fl.DESKTOPS_DIR)

    def button(self, number):
        return json.loads(read(os.path.join(self.folder, f"{number}.json")))

    def test_new_panel(self):
        fl.update_desktop_files(self.root, 3)
        self.assertEqual(fl.desktop_buttons(self.root), 3)
        self.assertEqual(self.button(2), {"text": "2", "class": [], "tooltip": "Desktop 2"})

    def test_regenerated_panel_keeps_the_state(self):
        fl.update_desktop_files(self.root, 5)
        fl.write_desktops(self.root, [("1", False), ("2", True), ("3", False), ("4", False), ("5", False)], 5)
        fl.update_desktop_files(self.root, 3)
        self.assertEqual(self.button(2)["class"], ["active"])
        self.assertEqual(sorted(os.listdir(self.folder)), ["1.json", "2.json", "3.json", "count"])

    def test_no_buttons_no_folder(self):
        fl.update_desktop_files(self.root, 4)
        fl.update_desktop_files(self.root, 0)
        self.assertFalse(os.path.exists(self.folder))
        self.assertEqual(fl.desktop_buttons(self.root), 0)
        self.assertEqual(fl.desktop_buttons(None), 0)

    def test_fewer_desktops_than_buttons(self):
        fl.update_desktop_files(self.root, 4)
        self.assertTrue(fl.write_desktops(self.root, [("one", True), ("two", False)], 4))
        self.assertEqual(self.button(1), {"text": "one", "class": ["active"], "tooltip": "Desktop one"})
        self.assertEqual(self.button(4)["text"], "")         # waybar hides it
        fl.write_desktops(self.root, [(str(n), n == 6) for n in range(1, 7)], 4)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "5.json")))

    def test_nothing_once_the_folder_is_gone(self):
        """The old panel's supervisor may still write after `set` dropped them."""
        self.assertFalse(fl.write_desktops(self.root, [("1", True)], 1))
        self.assertFalse(os.path.exists(self.folder))


class GeneratedPanelTest(EngineTest):

    def make(self, desktops):
        self.make_layout("desks", extra=f"Desktops={desktops}\n")
        self.write("layouts/desks/waybar.jsonc", '{"modules-left": ["flickos/desktops"], "modules-right": ["clock"]}')

    def test_panel_with_buttons(self):
        self.make(4)
        with self.quiet():
            fl.update_waybar(self.root, self.layout("desks"), self.style())
        bar = fl.load_jsonc(f"{self.root}/waybar/config.jsonc")[0]
        self.assertEqual(bar["modules-left"], [f"custom/desk#{n}" for n in range(1, 5)])
        self.assertEqual(fl.desktop_buttons(self.root), 4)

    def test_another_layout_drops_them(self):
        self.make(4)
        with self.quiet():
            fl.update_waybar(self.root, self.layout("desks"), self.style())
        self.make_layout("plain")
        with self.quiet():
            fl.update_waybar(self.root, self.layout("plain"), self.style())
        self.assertFalse(os.path.exists(os.path.join(self.root, fl.DESKTOPS_DIR)))


class ListenerTest(unittest.TestCase):
    """ScreenWatch with desktops, a fake compositor on the other end."""

    def setUp(self):
        self.compositor, client = socket.socketpair()
        self.addCleanup(self.compositor.close)
        self.seen = []
        self.watch = fl.ScreenWatch(client, lambda: None, settle=0.05, desktops=self.seen.append)
        threading.Thread(target=self.run_watch, daemon=True).start()
        self.compositor.recv(64)                         # get_registry, sync

    def run_watch(self):
        with self.watch.sock:
            self.watch.run()

    def send(self, *messages):
        self.compositor.sendall(b"".join(messages))
        time.sleep(0.15)

    def test_binds_the_manager(self):
        self.send(global_event(7, "wl_output"), global_event(9, "ext_workspace_manager_v1"))
        (object_id, opcode, payload), = parse(self.compositor.recv(256))
        self.assertEqual((object_id, opcode), (2, 0))
        self.assertEqual(payload, struct.pack("=I", 9) + string("ext_workspace_manager_v1") + struct.pack("=II", 1, 4))

    def test_desktops_in_announced_order(self):
        self.send(workspace(0xff000001, "1", active=True), workspace(0xff000002, "2"), DONE)
        self.send(state(0xff000001, False), state(0xff000002, True), DONE)
        self.assertEqual(self.seen, [[("1", True), ("2", False)], [("1", False), ("2", True)]])

    def test_reused_ids_out_of_order(self):
        """labwc 0.8.3 after 4 -> 2 -> 5 desktops (spike D3)."""
        self.send(*(workspace(0xff000000 + n, str(n), n == 2) for n in range(1, 5)), DONE)
        self.send(removed(0xff000003), removed(0xff000004), DONE)
        self.assertEqual([m[0] for m in parse(self.compositor.recv(256))], [0xff000003, 0xff000004])  # destroy
        self.send(workspace(0xff000004, "3"), workspace(0xff000003, "4"), workspace(0xff000005, "5"), DONE)
        self.assertEqual(self.seen[1], [("1", False), ("2", True)])
        self.assertEqual([name for name, _ in self.seen[2]], ["1", "2", "3", "4", "5"])

    def test_without_desktops_nothing_is_bound(self):
        compositor, client = socket.socketpair()
        watch = fl.ScreenWatch(client, lambda: None)
        compositor.recv(64)
        watch.handle(2, 0, struct.pack("=I", 9) + string("ext_workspace_manager_v1") + struct.pack("=I", 1))
        compositor.setblocking(False)
        with self.assertRaises(BlockingIOError):
            compositor.recv(64)
        compositor.close()
        client.close()


class SuperviseSignalTest(EngineTest):
    """supervise writes the files and signals its waybar once it catches it."""

    def setUp(self):
        super().setUp()
        self.got = self.path("got")
        self.waybar = self.write("bin/waybar", f"#!{sys.executable}\nimport signal, sys, time\n"
                                 f"def got(*_):\n    open({self.got!r}, 'w').write('read')\n    sys.exit(0)\n"
                                 f"signal.signal(signal.SIGRTMIN + {fl.DESKTOPS_SIGNAL}, got)\ntime.sleep(10)\n")
        os.chmod(self.waybar, 0o755)

    def run_supervise(self, desktops):
        calls = []
        with mock.patch.object(fl, "watch_screens", lambda env, changed, cb=None: calls.append(cb)), \
                mock.patch.object(fl, "log_line"), mock.patch.object(fl, "PROC", "/proc"):
            timer = threading.Timer(0.5, lambda: calls[0](desktops))
            timer.start()
            status = fl.supervise([self.waybar], dict(os.environ))
        return status, calls

    def test_signal_after_writing(self):
        fl.update_desktop_files(self.root, 2)
        status, _ = self.run_supervise([("1", False), ("2", True)])
        self.assertEqual(status, 0)
        self.assertEqual(read(self.got), "read")
        self.assertEqual(json.loads(read(f"{self.root}/desktops/2.json"))["class"], ["active"])

    def test_no_buttons_no_listener(self):
        calls = []
        with mock.patch.object(fl, "watch_screens", lambda env, changed, desktops=None: calls.append(desktops)), \
                mock.patch.object(fl, "log_line"), mock.patch.object(fl, "subprocess") as sub:
            sub.Popen.return_value.wait.return_value = 0
            fl.supervise([self.waybar], dict(os.environ))
        self.assertEqual(calls, [None])

    def test_catches_signal(self):
        proc = self.path("proc")
        self.write("proc/42/status", "Name:\twaybar\nSigCgt:\t0000000000000400\n")      # bit 10: signal 11
        with mock.patch.object(fl, "PROC", proc):
            self.assertTrue(fl.catches_signal(42, 11))
            self.assertFalse(fl.catches_signal(42, 12))
            self.assertFalse(fl.catches_signal(43, 11))


class FakeCompositor:
    """Answers the helper as labwc would: one manager, desktops 1-3 with 2
    active; records the requests."""

    def __init__(self, path, manager=True):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(1)
        self.manager, self.requests = manager, []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        conn, _ = self.server.accept()
        buffer = b""
        with conn:
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                buffer += data
                messages = parse(buffer)
                buffer = buffer[sum(8 + len(p) for _, _, p in messages):]
                for object_id, opcode, payload in messages:
                    self.requests.append((object_id, opcode))
                    if (object_id, opcode) == (1, 1) and self.manager:              # get_registry
                        conn.sendall(global_event(5, "wl_output") + global_event(9, "ext_workspace_manager_v1"))
                    elif (object_id, opcode) == (1, 0):                             # sync
                        conn.sendall(message(struct.unpack("=I", payload)[0], 0, struct.pack("=I", 1)))
                    elif (object_id, opcode) == (2, 0):                             # bind
                        conn.sendall(workspace(0xff000001, "1") + workspace(0xff000002, "2", True)
                                     + workspace(0xff000003, "3") + DONE)


class HelperTest(unittest.TestCase):

    def setUp(self):
        self.runtime = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.runtime)

    def run_helper(self, *args, manager=True):
        fake = FakeCompositor(os.path.join(self.runtime, "wayland-9"), manager)
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.runtime, "WAYLAND_DISPLAY": "wayland-9"}), \
                mock.patch("sys.stderr"):
            status = helper.main(list(args))
        fake.server.close()
        os.unlink(os.path.join(self.runtime, "wayland-9"))
        return status, [r for r in fake.requests if r[0] >= 0xff000000 or r == (4, 0)]

    def test_go_to_a_desktop(self):
        self.assertEqual(self.run_helper("3"), (0, [(0xff000003, 1), (4, 0)]))     # activate, commit

    def test_next_and_previous(self):
        self.assertEqual(self.run_helper("next"), (0, [(0xff000003, 1), (4, 0)]))
        self.assertEqual(self.run_helper("previous"), (0, [(0xff000001, 1), (4, 0)]))

    def test_nothing_to_do(self):
        for wanted in ("2", "9"):
            self.assertEqual(self.run_helper(wanted), (0, []))

    def test_no_desktops(self):
        self.assertEqual(self.run_helper("1", manager=False), (1, []))

    def test_usage(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(helper.main(["x"]), 2)
            self.assertEqual(helper.main([]), 2)

    def test_same_protocol_as_the_listener(self):
        watch = fl.ScreenWatch
        self.assertEqual(helper.WORKSPACE_MANAGER, fl.WORKSPACE_MANAGER)
        self.assertEqual((helper.MANAGER_WORKSPACE, helper.MANAGER_DONE),
                         (watch.MANAGER_WORKSPACE, watch.MANAGER_DONE))
        self.assertEqual((helper.WORKSPACE_NAME, helper.WORKSPACE_STATE, helper.WORKSPACE_REMOVED),
                         (watch.WORKSPACE_NAME, watch.WORKSPACE_STATE, watch.WORKSPACE_REMOVED))
        self.assertEqual(helper.STATE_ACTIVE, watch.STATE_ACTIVE)

    def test_installed(self):
        self.assertIn("usr/libexec/flickos/desktop ", read(os.path.join(PACKAGE, "debian/install")))
        self.assertTrue(os.access(os.path.join(PACKAGE, "usr/libexec/flickos/desktop"), os.X_OK))


if __name__ == "__main__":
    unittest.main()
