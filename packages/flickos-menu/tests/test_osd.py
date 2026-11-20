"""Tests for the volume and brightness ring: the client
(usr/libexec/flickos/osd), the GTK-free part of osd.py and flickos-menu's
socket handover. Run: python3 -m unittest discover -s tests"""

import ast
import fcntl
import importlib.machinery
import importlib.util
import math
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
sys.dont_write_bytecode = True


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


client = load("flickos_osd_client", os.path.join(PACKAGE, "usr/libexec/flickos/osd"))
ring = load("flickos_menu_osd", os.path.join(PACKAGE, "usr/share/flickos/menu/osd.py"))
fm = load("flickos_menu_for_osd", os.path.join(PACKAGE, "usr/bin/flickos-menu"))


class Folder(unittest.TestCase):
    """A temp folder for XDG_RUNTIME_DIR and XDG_CONFIG_HOME, and the
    system's osd.conf in it. A short path: a socket's must fit 108 bytes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="osd")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp,
                                           "XDG_CONFIG_HOME": os.path.join(self.tmp, "config")})
        env.start()
        self.addCleanup(env.stop)
        self.system = os.path.join(self.tmp, "osd.conf")
        patch = mock.patch.object(client, "SYSTEM_CONF", self.system)
        patch.start()
        self.addCleanup(patch.stop)
        self.root = os.path.join(self.tmp, "flickos")
        self.path = os.path.join(self.root, client.SOCKET)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


class SettingTest(Folder):
    def test_on_by_default(self):
        self.assertTrue(client.enabled())

    def test_the_users_choice_wins_over_the_systems(self):
        self.write(self.system, "[Osd]\nEnabled=no\n")
        self.assertFalse(client.enabled())
        self.write(client.user_conf(), "# mine\n[Osd]\nEnabled = yes\n")
        self.assertTrue(client.enabled())

    def test_other_sections_comments_and_bad_values_are_not_the_setting(self):
        self.write(self.system, "[Other]\nEnabled=no\n[Osd]\n#Enabled=no\nEnabled=maybe\n")
        self.assertIsNone(client.read_enabled(self.system))
        self.assertTrue(client.enabled())

    def test_flickos_controls_file_and_conffile(self):
        """The file flickos-control writes and its conffile's example, as
        this reads them (the same section, key and words)."""
        control = os.path.join(PACKAGE, "..", "flickos-control", "usr", "bin", "flickos-control")
        if not os.path.exists(control):
            self.skipTest("flickos-control is not next to this package")
        with open(control, encoding="utf-8") as f:
            text = f.read()
        self.assertTrue('Setting("osd.enabled", "bool", ("osd", "enabled"), True)' in text)
        words = next(line for line in text.splitlines() if line.startswith("TRUE, FALSE = "))
        self.assertEqual(ast.literal_eval(words.split(" = ", 1)[1]), (client.TRUE, client.FALSE))
        conffile = os.path.join(os.path.dirname(control), "..", "..", "etc", "xdg", "flickos", "osd.conf")
        with open(conffile, encoding="utf-8") as f:
            example = "\n".join(line[1:] for line in f.read().splitlines() if line.startswith("#["))
        self.assertEqual(example, "[Osd]")
        self.write(self.system, "[Osd]\nEnabled=no\n")
        self.assertFalse(client.enabled())


class LevelTest(unittest.TestCase):
    def test_wpctl(self):
        self.assertEqual(client.parse_wpctl("Volume: 0.41\n"), (41, False))
        self.assertEqual(client.parse_wpctl("Volume: 0.40 [MUTED]\n"), (40, True))
        self.assertEqual(client.parse_wpctl("Volume: 1.50"), (150, False))
        self.assertIsNone(client.parse_wpctl(""))
        self.assertIsNone(client.parse_wpctl("Couldn't connect to PipeWire"))

    def test_brightnessctl(self):
        self.assertEqual(client.parse_brightnessctl("intel_backlight,backlight,647,69%,937\n"), (69, False))
        self.assertIsNone(client.parse_brightnessctl("Failed to read any devices of class 'backlight'."))
        self.assertIsNone(client.parse_brightnessctl("x,backlight,0,0%,0"))

    def test_messages_the_ring_reads(self):
        for level in ((0, False), (45, True), (100, False)):
            self.assertEqual(ring.parse_message(client.message("volume", *level)), ("volume", *level))
        self.assertEqual(client.message("volume", 150, False), "volume 100")
        self.assertEqual(client.KINDS, ring.KINDS)

    def test_desktop_card_message(self):
        sent = []
        with mock.patch.object(client, "enabled", return_value=True), mock.patch.object(client, "locked", return_value=False), \
                mock.patch.object(client, "deliver", side_effect=lambda root, text: sent.append(text) or True):
            self.assertEqual(client.main(["desktop", "2", "4"]), 0)
            with mock.patch("sys.stderr"):
                for bad in (["desktop"], ["desktop", "2"], ["desktop", "5", "4"], ["desktop", "x", "4"],
                            ["desktop", "1", "1"], ["desktop", "1", "10"]):
                    self.assertEqual(client.main(bad), 2, bad)
        self.assertEqual(sent, ["desktop 2 4"])
        self.assertIsNotNone(ring.parse_message(sent[0]))

    def test_the_level_script_names_the_same_kinds(self):
        script = os.path.join(PACKAGE, "..", "flickos-settings", "usr", "libexec", "flickos", "level")
        if not os.path.exists(script):
            self.skipTest("flickos-settings is not next to this package")
        with open(script, encoding="utf-8") as f:
            kinds = {line.split('"')[1].split()[0] for line in f if line.strip().startswith('"')}
        self.assertEqual(kinds, set(client.KINDS))

    def test_usage(self):
        # Not the desktop's own setting: with the ring off there, the level is never read.
        with mock.patch("sys.stderr"), mock.patch.object(client, "enabled", return_value=True), \
                mock.patch.object(client, "locked", return_value=False), \
                mock.patch.object(client, "runtime_root", return_value="/nonexistent/flickos"):
            self.assertEqual(client.main([]), 2)
            self.assertEqual(client.main(["loudness"]), 2)
            self.assertEqual(client.main(["volume", "lots"]), 2)


class DeliverTest(Folder):
    def test_the_same_socket_as_the_menu(self):
        self.assertEqual(client.SOCKET, fm.OSD_SOCKET)

    def test_a_listener_gets_the_line(self):
        os.makedirs(os.path.dirname(self.path))
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.path)
        server.listen(1)
        got = []

        def answer():
            connection, _address = server.accept()
            with connection:
                got.append(connection.recv(256))
                connection.sendall(b"ok")

        thread = threading.Thread(target=answer)
        thread.start()
        self.assertTrue(client.deliver(self.root, "brightness 30"))
        thread.join(2)
        server.close()
        self.assertEqual(got, [b"brightness 30\n"])

    def stand_in_menu(self):
        """A flickos-menu that writes its arguments and whether its fd
        listens on the socket, then exits."""
        menu = os.path.join(self.tmp, "flickos-menu")
        self.write(menu, "#!/usr/bin/python3\n"
                         "import socket, sys\n"
                         "s = socket.socket(fileno=int(sys.argv[2]))\n"
                         "listening = s.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)\n"
                         f"open({os.path.join(self.tmp, 'argv')!r}, 'a').write("
                         "' '.join(sys.argv[1:2] + sys.argv[3:]) + f' {listening}\\n')\n")
        os.chmod(menu, 0o755)
        return menu

    def started(self):
        for _try in range(100):
            if os.path.exists(os.path.join(self.tmp, "argv")):
                with open(os.path.join(self.tmp, "argv"), encoding="utf-8") as f:
                    lines = f.read().splitlines()
                if lines:
                    return lines
            time.sleep(0.02)
        return []

    def test_nobody_listening_starts_the_popup_on_the_bound_socket(self):
        with mock.patch.object(client, "MENU", self.stand_in_menu()):
            self.assertTrue(client.deliver(self.root, "volume 45 muted"))
        self.assertEqual(self.started(), ["osd-popup volume 45 muted 1"])
        self.assertTrue(os.path.exists(self.path))

    def test_a_dead_popups_file_is_replaced(self):
        os.makedirs(os.path.dirname(self.path))
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(self.path)
        stale.close()
        with mock.patch.object(client, "MENU", self.stand_in_menu()):
            self.assertTrue(client.deliver(self.root, "mic 0 muted"))
        self.assertEqual(self.started(), ["osd-popup mic 0 muted 1"])

    def test_without_flickos_menu_nothing_is_left(self):
        with mock.patch.object(client, "MENU", os.path.join(self.tmp, "missing")):
            self.assertFalse(client.deliver(self.root, "volume 10"))
        self.assertFalse(os.path.exists(self.path))

    def test_turned_off_nothing_is_read_or_sent(self):
        self.write(client.user_conf(), "[Osd]\nEnabled=no\n")
        with mock.patch.object(client, "read_level") as read, mock.patch.object(client, "deliver") as deliver:
            self.assertEqual(client.main(["volume"]), 0)
        read.assert_not_called()
        deliver.assert_not_called()

    def test_no_level_nothing_is_sent(self):
        with mock.patch.object(client, "run", return_value=""), mock.patch.object(client, "deliver") as deliver:
            self.assertEqual(client.main(["brightness"]), 0)
        deliver.assert_not_called()

    def hold_lock(self):
        """flickos-lock's guard: a separate open file holding the flock."""
        path = os.path.join(self.root, client.LOCK_FILE)
        self.write(path, "")
        lock = open(path, "a+", encoding="utf-8")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock

    def test_locked_nothing_is_read_or_sent(self):
        self.hold_lock()
        with mock.patch.object(client, "read_level") as read, mock.patch.object(client, "deliver") as deliver:
            self.assertEqual(client.main(["volume"]), 0)
            self.assertEqual(client.main(["volume", "40"]), 0)
        read.assert_not_called()
        deliver.assert_not_called()

    def test_after_the_unlock_the_ring_shows_again(self):
        self.hold_lock().close()
        self.assertFalse(client.locked(self.root))
        with mock.patch.object(client, "deliver") as deliver:
            self.assertEqual(client.main(["volume", "40"]), 0)
        deliver.assert_called_once()

    def test_a_left_behind_locked_file_is_not_a_lock(self):
        # A killed guard leaves `locked` and lets go of the flock.
        self.write(os.path.join(self.root, "lock", "locked"), "1\n")
        self.assertFalse(client.locked(self.root))

    def test_never_locked(self):
        self.assertFalse(client.locked(self.root))

    def test_the_same_lock_file_as_flickos_lock(self):
        lock = os.path.join(os.path.dirname(PACKAGE), "flickos-lock", "usr/bin/flickos-lock")
        if not os.path.exists(lock):
            self.skipTest("flickos-lock isn't in the tree")
        values = {target.id: node.value.value for node in ast.parse(open(lock, encoding="utf-8").read()).body
                  if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                  for target in node.targets if isinstance(target, ast.Name)}
        self.assertEqual(client.LOCK_FILE, os.path.join(values["FOLDER"], values["LOCK_FILE"]))

    def test_the_keys_that_run_while_locked(self):
        rc = os.path.join(os.path.dirname(PACKAGE), "flickos-settings", "etc/xdg/labwc/rc.xml")
        if not os.path.exists(rc):
            self.skipTest("flickos-settings isn't in the tree")
        with open(rc, encoding="utf-8") as f:
            text = f.read()
        for key in ("RaiseVolume", "LowerVolume", "Mute", "MicMute", "Play", "Pause", "Stop", "Next", "Prev"):
            self.assertIn(f'<keybind key="XF86Audio{key}" allowWhenLocked="yes">', text)


class HandoverTest(Folder):
    """A starting daemon takes the socket from a pop-up (osd_listen)."""

    def test_a_free_path(self):
        listener = fm.osd_listen(self.path)
        self.addCleanup(listener.close)
        self.assertEqual(listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN), 1)
        self.assertEqual(fm.own_file(self.path), os.stat(self.path).st_ino)

    def test_a_stale_file_is_replaced(self):
        os.makedirs(os.path.dirname(self.path))
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(self.path)
        stale.close()
        listener = fm.osd_listen(self.path)
        self.addCleanup(listener.close)
        self.assertIsNotNone(listener)

    def test_a_popup_is_asked_to_quit(self):
        os.makedirs(os.path.dirname(self.path))
        popup = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        popup.bind(self.path)
        popup.listen(1)
        got = []

        def quit_when_asked():      # as OsdServer: answer, drop the file, close
            connection, _address = popup.accept()
            with connection:
                got.append(connection.recv(256))
                connection.sendall(b"ok")
            os.unlink(self.path)
            popup.close()

        thread = threading.Thread(target=quit_when_asked)
        thread.start()
        listener = fm.osd_listen(self.path)
        thread.join(2)
        self.addCleanup(listener.close)
        self.assertEqual(got, [b"quit\n"])
        self.assertIsNotNone(listener)

    def test_gives_up(self):
        os.makedirs(os.path.dirname(self.path))
        other = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        other.bind(self.path)
        other.listen(8)            # never answers, never leaves
        self.addCleanup(other.close)
        self.assertIsNone(fm.osd_listen(self.path, tries=2))


class RingLogicTest(unittest.TestCase):
    def test_messages(self):
        self.assertEqual(ring.parse_message("volume 45\n"), ("volume", 45, False))
        self.assertEqual(ring.parse_message("mic 0 muted"), ("mic", 0, True))
        self.assertEqual(ring.parse_message("brightness 120"), ("brightness", 100, False))
        for bad in ("", "quit", "volume", "volume x", "volume 4 loud", "light 4", "volume 1 muted 2"):
            self.assertIsNone(ring.parse_message(bad), bad)

    def test_desktop_messages(self):
        self.assertEqual(ring.parse_message("desktop 2 4\n"), ("desktop", 2, 4))
        for bad in ("desktop", "desktop 2", "desktop 5 4", "desktop 0 4", "desktop 1 1", "desktop 1 10",
                    "desktop x 4", "desktop 2 4 muted"):
            self.assertIsNone(ring.parse_message(bad), bad)

    def test_card_geometry(self):
        self.assertEqual(ring.card_width(2), ring.CARD_MIN_WIDTH)
        self.assertGreater(ring.card_width(9), ring.card_width(6))
        for count in (2, 4, 9):
            centres = ring.dot_centres(count)
            self.assertEqual(len(centres), count)
            self.assertEqual(centres[0] - ring.DOT / 2, ring.card_width(count) - centres[-1] - ring.DOT / 2)
        self.assertEqual(ring.DESKTOP_MAX, client.DESKTOP_MAX)

    def test_icons(self):
        self.assertEqual(ring.icon_names("volume", 0, False), ["audio-volume-muted-symbolic"])
        self.assertEqual(ring.icon_names("volume", 20, False), ["audio-volume-low-symbolic"])
        self.assertEqual(ring.icon_names("volume", 50, False), ["audio-volume-medium-symbolic"])
        self.assertEqual(ring.icon_names("volume", 90, False), ["audio-volume-high-symbolic"])
        self.assertEqual(ring.icon_names("volume", 90, True), ["audio-volume-muted-symbolic"])
        self.assertEqual(ring.icon_names("mic", 90, True)[0], "microphone-disabled-symbolic")
        self.assertEqual(ring.icon_names("brightness", 5, False)[0], "display-brightness-symbolic")

    def test_arc_from_the_top_clockwise(self):
        self.assertAlmostEqual(ring.arc_end(0), -math.pi / 2)
        self.assertAlmostEqual(ring.arc_end(25), 0)
        self.assertAlmostEqual(ring.arc_end(100), 3 * math.pi / 2)
        self.assertAlmostEqual(ring.arc_end(130), 3 * math.pi / 2)

    def test_slide_is_eased_out(self):
        self.assertEqual(ring.slide(20, 60, 0), (20, False))
        self.assertEqual(ring.slide(20, 60, ring.SLIDE_MS), (60, True))
        self.assertGreater(ring.slide(20, 60, ring.SLIDE_MS / 3)[0], 40)

    def test_what_a_screen_reader_says(self):
        self.assertEqual(ring.description("volume", 45, False), "Volume 45%")
        self.assertEqual(ring.description("volume", 45, True), "Volume 45%, muted")
        self.assertEqual(ring.description("mic", 0, True), "Microphone muted")

    def test_the_menu_gives_it_its_fades(self):
        with mock.patch.object(fm, "OSD_CODE", os.path.join(PACKAGE, "usr/share/flickos/menu/osd.py")):
            module = fm.load_osd()
        self.assertIs(module.fade_opacity, fm.fade_opacity)
        self.assertEqual((module.FADE_IN_MS, module.FADE_OUT_MS), (fm.FADE_IN_MS, fm.FADE_OUT_MS))
        self.assertTrue(hasattr(module, "Ring"))


if __name__ == "__main__":
    unittest.main()
