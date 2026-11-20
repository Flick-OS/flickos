"""Tests for usr/libexec/flickos/greeter-window and the greeter script.
Run: python3 -m unittest discover -s tests

No display, no greetd, no root: every path greeter-window reads is under a
temporary FLICKOS_GREETER_PREFIX, greetd is a fake on a socketpair."""

import ast
import contextlib
import importlib.machinery
import importlib.util
import inspect
import io
import json
import os
import pwd
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
PACKAGES = os.path.dirname(PACKAGE)
ROOT = tempfile.mkdtemp(prefix="flickos-greeter-test.")

sys.dont_write_bytecode = True


def load(name, path, prefix=None):
    loader = importlib.machinery.SourceFileLoader(name, path)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    with mock.patch.dict(os.environ, {"FLICKOS_GREETER_PREFIX": prefix} if prefix else {}):
        loader.exec_module(module)
    return module


gw = load("greeter_window", os.path.join(PACKAGE, "usr/libexec/flickos/greeter-window"), ROOT)


def tearDownModule():
    shutil.rmtree(ROOT, ignore_errors=True)


def entry(name, uid, gecos="", shell="/bin/bash"):
    return pwd.struct_passwd((name, "x", uid, uid, gecos, f"/home/{name}", shell))


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(text)


class FakeGreetd:
    """greetd on the other end of a socketpair: answers each request with the
    next reply of a script, and records the requests."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        ours, theirs = socket.socketpair()
        self.client = gw.Greetd(sock=ours)
        self.sock = theirs
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def read(self, size):
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def serve(self):
        while True:
            head = self.read(4)
            if head is None:
                return
            size, = struct.unpack("=I", head)
            self.requests.append(json.loads(self.read(size)))
            reply = json.dumps(self.replies.pop(0)).encode()
            self.sock.sendall(struct.pack("=I", len(reply)) + reply)

    def close(self):
        self.client.sock.close()
        self.sock.close()


def run(conversation, greetd, answers=()):
    """Drive a conversation as the window does; returns the events."""
    answers, events = list(answers), []
    request = conversation.first()
    while request is not None:
        following, event = conversation.reply(request, greetd.call(request))
        if event:
            events.append(event)
        if following is None and conversation.waiting:
            following = conversation.answer(answers.pop(0))
        request = following
    return events


SECRET = {"type": "auth_message", "auth_message_type": "secret", "auth_message": "Password: "}
SUCCESS = {"type": "success"}
FLICKOS = ("flickos", *gw.SESSIONS["flickos"])


class ProtocolTest(unittest.TestCase):
    def test_encoding_both_ways(self):
        fake = FakeGreetd([{"type": "success", "note": "é"}])
        self.assertEqual(fake.client.call({"type": "create_session", "username": "jön"}),
                         {"type": "success", "note": "é"})
        self.assertEqual(fake.requests, [{"type": "create_session", "username": "jön"}])
        fake.close()

    def test_a_closed_connection_is_an_error(self):
        ours, theirs = socket.socketpair()
        theirs.close()
        with self.assertRaises((gw.GreeterError, OSError)):
            gw.Greetd(sock=ours).call({"type": "cancel_session"})
        ours.close()

    def test_no_socket_no_window(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(gw.GreeterError, "GREETD_SOCK"):
                gw.Greetd()


class ConversationTest(unittest.TestCase):
    def converse(self, replies, answers=(), session=FLICKOS, password="secret"):
        fake = FakeGreetd(replies)
        conversation = gw.Conversation("jon", password, session)
        events = run(conversation, fake.client, answers)
        fake.close()
        return events, fake.requests

    def test_right_password_starts_the_session(self):
        events, requests = self.converse([SECRET, SUCCESS, SUCCESS])
        self.assertEqual(events, [("started",)])
        self.assertEqual(requests[0], {"type": "create_session", "username": "jon"})
        self.assertEqual(requests[1], {"type": "post_auth_message_response", "response": "secret"})
        self.assertEqual(requests[2], {"type": "start_session", "cmd": ["flickos-session"],
                                       "env": ["XDG_SESSION_TYPE=wayland", "XDG_SESSION_DESKTOP=flickos",
                                               "XDG_CURRENT_DESKTOP=labwc:wlroots"]})

    def test_wrong_password_cancels_and_says_so(self):
        """greetd answers that cancel with an error that still clears it (G1)."""
        events, requests = self.converse([
            SECRET, {"type": "error", "error_type": "auth_error", "description": "pam_authenticate: AUTH_ERR"},
            {"type": "error", "error_type": "error",
             "description": "unable to send message: Connection refused (os error 111)"}])
        self.assertEqual(events, [("wrong",)])
        self.assertEqual(requests[-1], {"type": "cancel_session"})

    def test_expired_password_is_told_apart(self):
        events, requests = self.converse([
            SECRET,
            {"type": "auth_message", "auth_message_type": "error",
             "auth_message": "You are required to change your password immediately (administrator enforced)."},
            {"type": "error", "error_type": "auth_error", "description": "pam_acct_mgmt: NEW_AUTHTOK_REQD"},
            SUCCESS])
        self.assertEqual(events[0][0], "info")
        self.assertEqual(events[1], ("expired",))
        self.assertEqual(requests[2], {"type": "post_auth_message_response"})
        self.assertEqual(requests[-1], {"type": "cancel_session"})

    def test_other_account_refusals(self):
        events, _requests = self.converse([
            SECRET, {"type": "error", "error_type": "auth_error", "description": "pam_acct_mgmt: ACCT_EXPIRED"},
            SUCCESS])
        self.assertEqual(events, [("denied",)])

    def test_prompts_after_the_password_are_asked(self):
        events, requests = self.converse([
            SECRET,
            {"type": "auth_message", "auth_message_type": "visible", "auth_message": "Code: "},
            {"type": "auth_message", "auth_message_type": "secret", "auth_message": "PIN: "},
            SUCCESS, SUCCESS], answers=["123456", "4321"])
        self.assertEqual(events, [("ask", "visible", "Code: "), ("ask", "secret", "PIN: "), ("started",)])
        self.assertEqual([r.get("response") for r in requests[1:4]], ["secret", "123456", "4321"])

    def test_a_first_prompt_that_isnt_secret_is_asked(self):
        """The typed password only ever answers a secret prompt."""
        events, requests = self.converse([
            {"type": "auth_message", "auth_message_type": "visible", "auth_message": "Token: "},
            SECRET, SUCCESS, SUCCESS], answers=["t0k"])
        self.assertEqual(events[0], ("ask", "visible", "Token: "))
        self.assertEqual([r.get("response") for r in requests[1:3]], ["t0k", "secret"])

    def test_info_messages_go_on(self):
        events, requests = self.converse([
            {"type": "auth_message", "auth_message_type": "info", "auth_message": "Hello"}, SECRET, SUCCESS, SUCCESS])
        self.assertEqual(events, [("info", "Hello"), ("started",)])
        self.assertEqual(requests[1], {"type": "post_auth_message_response"})

    def test_a_refused_session_is_an_error(self):
        events, requests = self.converse([
            SECRET, SUCCESS, {"type": "error", "error_type": "error", "description": "no such command"}, SUCCESS])
        self.assertEqual(events, [("error", "no such command")])
        self.assertEqual(requests[-1], {"type": "cancel_session"})

    def test_the_command_is_the_sessions_never_what_was_typed(self):
        session = ("sway", "Sway", "sway --unsupported-gpu", "sway", "sway")
        _events, requests = self.converse([SECRET, SUCCESS, SUCCESS], session=session, password="$(rm -rf /)")
        self.assertEqual(requests[-1]["cmd"], ["sway", "--unsupported-gpu"])
        self.assertIn("XDG_CURRENT_DESKTOP=sway", requests[-1]["env"])

    def test_a_cancel_ends_it(self):
        conversation = gw.Conversation("jon", "x", FLICKOS)
        request = conversation.cancel()
        self.assertEqual(request, {"type": "cancel_session"})
        self.assertEqual(conversation.reply(request, {"type": "error"}), (None, None))
        self.assertTrue(conversation.finished)

    def test_pam_text_without_a_translation_is_unchanged(self):
        with mock.patch.object(gw.gettext, "dgettext", lambda domain, text: text):
            self.assertEqual(gw.pam_text("Password: "), "Password: ")


class UsersTest(unittest.TestCase):
    def test_who_is_listed(self):
        entries = [entry("root", 0, "root"), entry("_greetd", 101, "", "/usr/sbin/nologin"),
                   entry("zed", 1000, "Zed Ant,,,"), entry("maria", 1002, "Maria Santos"),
                   entry("noshell", 1003, "No Shell", "/usr/sbin/nologin"),
                   entry("nofalse", 1004, "False", "/bin/false"),
                   entry("anna", 1001, ""), entry("nobody", 65534, "nobody", "/bin/sh")]
        listed = gw.users(entries, (1000, 60000))
        self.assertEqual([e.pw_name for e in listed], ["anna", "maria", "zed"])
        self.assertEqual([gw.display_name(e) for e in listed], ["anna", "Maria Santos", "Zed Ant"])
        self.assertEqual(gw.initial(listed[2]), "Z")

    def test_login_defs(self):
        path = os.path.join(ROOT, "etc/login.defs")
        write(path, "# comment\nUID_MIN\t\t 2000\nUID_MAX 3000\nGID_MIN 2000\n")
        self.assertEqual(gw.login_defs(path), (2000, 3000))
        write(path, "UID_MIN lots\n")
        self.assertEqual(gw.login_defs(path), gw.UID_RANGE)
        self.assertEqual(gw.login_defs(os.path.join(ROOT, "missing")), gw.UID_RANGE)

    def test_pictures_only_from_accountsservice(self):
        self.assertTrue(gw.ICONS_DIR.startswith(ROOT))
        write(os.path.join(gw.ICONS_DIR, "maria"), "png")
        self.assertEqual(gw.picture_file("maria"), os.path.join(gw.ICONS_DIR, "maria"))
        self.assertIsNone(gw.picture_file("nobody-here"))


class SessionsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(dir=ROOT)

    def desktop(self, name, text):
        write(os.path.join(self.folder, name), "[Desktop Entry]\n" + text)

    def test_the_list(self):
        self.desktop("flickos.desktop", "Name=FlickOS\nExec=flickos-session\n")
        self.desktop("labwc.desktop", "Name=labwc\nExec=labwc\n")
        self.desktop("sway.desktop", "Name=Sway\nExec=sway %U\nDesktopNames=sway;\n")
        self.desktop("away.desktop", "Name=Away\nExec=away\nHidden=true\n")
        self.desktop("nod.desktop", "Name=Nod\nExec=nod\nNoDisplay=true\n")
        self.desktop("gone.desktop", "Name=Gone\nExec=gone\nTryExec=/no/such/program\n")
        self.desktop("empty.desktop", "Name=Empty\n")
        write(os.path.join(self.folder, "broken.desktop"), "no section\n")
        write(os.path.join(self.folder, "readme.txt"), "not a session\n")
        found = gw.sessions(self.folder)
        self.assertEqual([s[0] for s in found], ["flickos", "flickos-plain", "sway"])
        self.assertEqual(found[1][1:3], ("FlickOS (Plain Session)", "flickos-session-plain"))
        self.assertEqual(found[2], ("sway", "Sway", "sway", "sway", "sway"))

    def test_no_folder_still_has_flickos(self):
        self.assertEqual([s[0] for s in gw.sessions(os.path.join(self.folder, "missing"))],
                         ["flickos", "flickos-plain"])

    def test_a_session_that_went_away_falls_back_to_flickos(self):
        found = gw.sessions(self.folder)
        self.assertEqual(gw.find_session(found, "flickos-plain")[0], "flickos-plain")
        self.assertEqual(gw.find_session(found, "gnome")[0], "flickos")
        self.assertEqual(gw.find_session(found, None)[0], "flickos")

    def test_desktop_names_without_current_desktop(self):
        request = gw.session_request(("x", "X", "x-session", "x", ""))
        self.assertEqual(request["env"], ["XDG_SESSION_TYPE=wayland", "XDG_SESSION_DESKTOP=x"])


class StateTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=ROOT), "flickos", "state")

    def test_missing_or_broken_means_nothing_remembered(self):
        empty = {"last": None, "sessions": {}, "zoom": 100}
        self.assertEqual(gw.read_state(self.path), empty)
        for text in ("{", "[]", '{"last": 3, "sessions": [1], "zoom": 125}', '{"zoom": "200"}'):
            write(self.path, text)
            self.assertEqual(gw.read_state(self.path), empty, text)

    def test_remembered_atomically_in_a_private_folder(self):
        gw.remember("maria", "flickos-plain", 100, self.path)
        gw.remember("jon", "flickos", 200, self.path)
        self.assertEqual(gw.read_state(self.path),
                         {"last": "jon", "sessions": {"maria": "flickos-plain", "jon": "flickos"}, "zoom": 200})
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.path)).st_mode), 0o700)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["state"])

    def test_the_window_remembers_only_after_the_session_started(self):
        """remember() is called in one place: on greetd's success for start_session."""
        source = inspect.getsource(gw.LoginScreen.show_event)
        with open(gw.__file__, encoding="utf-8") as f:
            self.assertEqual(f.read().count("remember("), 2)       # its def and this call
        block = source[source.index('elif kind == "started":'):source.index("remember(")]
        self.assertNotIn("elif", block[len('elif kind == "started":'):])


class ScreensTest(unittest.TestCase):
    def drm(self, connectors):
        folder = tempfile.mkdtemp(dir=ROOT)
        for name, status, size in connectors:
            write(os.path.join(folder, name, "status"), status + "\n")
            edid = bytearray(128)
            if size:
                edid[21], edid[22] = size
            write(os.path.join(folder, name, "edid"), bytes(edid), "wb")
        write(os.path.join(folder, "version"), "drm\n")
        return folder

    def test_builtin_sizes_from_edid(self):
        folder = self.drm([("card1-eDP-1", "connected", (35, 19)), ("card1-HDMI-A-1", "connected", (53, 30)),
                           ("card0-LVDS-1", "disconnected", (30, 20)), ("card1-DSI-1", "connected", None)])
        self.assertEqual(gw.builtin_sizes(folder), [(350, 190)])
        self.assertEqual(gw.builtin_sizes(os.path.join(folder, "missing")), [])

    def test_the_card_goes_on_the_builtin_screen(self):
        """The maintainer's laptop and monitor (G2): GDK's mm match EDID's cm."""
        sizes = [(530, 300), (350, 190)]
        self.assertEqual(gw.choose_monitor(sizes, [(350, 190)]), 1)
        self.assertEqual(gw.choose_monitor(sizes, [(344, 194)]), 1)        # within MM_TOLERANCE
        self.assertEqual(gw.choose_monitor(sizes, []), 0)                   # a desktop computer
        self.assertEqual(gw.choose_monitor([(350, 190), (350, 190)], [(350, 190)]), 0)   # same size: first
        self.assertEqual(gw.choose_monitor([(0, 0)], [(350, 190)]), 0)

    def test_positions_in_the_window(self):
        monitors = [(0, 0, 1366, 768), (1366, 0, 1920, 1080)]
        self.assertEqual(gw.card_position(monitors, 0, (400, 500)), (483, 134))
        self.assertEqual(gw.card_position(monitors, 1, (400, 500)), (1366 + 760, 290))
        self.assertEqual(gw.card_position(monitors, 0, (2000, 1000)), (0, 0))
        self.assertEqual(gw.bottom_position(monitors, 1, (100, 40)),
                         (1366 + gw.MARGIN, 1080 - 40 - gw.MARGIN))
        # A layout that doesn't start at 0,0: the window starts at its corner.
        self.assertEqual(gw.card_position([(-1920, 0, 1920, 1080), (0, 0, 1366, 768)], 1, (400, 500)),
                         (1920 + 483, 134))

    def test_left_and_right(self):
        """ADR-015: the card's middle at a quarter or three quarters of its
        screen's width, never closer than MARGIN to the edge."""
        monitors = [(0, 0, 1366, 768), (1366, 0, 1920, 1080)]
        self.assertEqual(gw.card_position(monitors, 1, (400, 500), "left"), (1366 + 280, 290))
        self.assertEqual(gw.card_position(monitors, 1, (400, 500), "right"), (1366 + 1240, 290))
        self.assertEqual(gw.card_position(monitors, 0, (400, 500), "center"), gw.card_position(monitors, 0, (400, 500)))
        # Wider than a quarter (300% zoom on a small screen): kept on the screen.
        self.assertEqual(gw.card_position([(0, 0, 1366, 768)], 0, (800, 500), "left"), (gw.MARGIN, 134))
        self.assertEqual(gw.card_position([(0, 0, 1366, 768)], 0, (800, 500), "right"),
                         (1366 - 800 - gw.MARGIN, 134))
        self.assertEqual(gw.card_position([(0, 0, 1366, 768)], 0, (2000, 500), "right"), (0, 134))
        self.assertEqual(gw.card_position(monitors, 0, (400, 500), "nowhere"), (483, 134))

    def test_the_corner_is_on_the_cards_screen(self):
        monitors = [(0, 0, 1366, 768), (1366, 0, 1920, 1080)]
        self.assertEqual(gw.corner_position(monitors, 0, (100, 40)),
                         (1366 - 100 - gw.MARGIN, 768 - 40 - gw.MARGIN))
        self.assertEqual(gw.corner_position(monitors, 1, (100, 40)),
                         (1366 + 1920 - 100 - gw.MARGIN, 1080 - 40 - gw.MARGIN))
        self.assertEqual(gw.corner_position([(0, 0, 50, 20)], 0, (100, 40)), (0, 0))


class ConfigTest(unittest.TestCase):
    """ADR-014, ADR-015: Background= and Position=, the later file winning."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(dir=ROOT)
        self.default = os.path.join(self.folder, "greeter.conf")
        self.chosen = os.path.join(self.folder, "greeter")

    def test_nothing_is_the_default(self):
        self.assertEqual(gw.read_config((self.default, self.chosen)),
                         {"background": None, "position": "center"})

    def test_the_shipped_conffile_sets_nothing(self):
        path = os.path.join(PACKAGE, "etc/xdg/flickos/greeter.conf")
        self.assertEqual(gw.read_config((path,)), {"background": None, "position": "center"})

    def test_the_choice_wins(self):
        write(self.default, "# defaults\nPosition=left\nBackground=/usr/share/backgrounds/flickos/redmond.jpg\n")
        write(self.chosen, "Position=right\n")
        self.assertEqual(gw.read_config((self.default, self.chosen)),
                         {"background": "/usr/share/backgrounds/flickos/redmond.jpg", "position": "right"})
        write(self.chosen, 'Background="/var/lib/flickos-control/login-screen/background.jpg"\n')
        self.assertEqual(gw.read_config((self.default, self.chosen))["background"],
                         "/var/lib/flickos-control/login-screen/background.jpg")

    def test_values_that_cant_be(self):
        write(self.chosen, "Position=top\nBackground=pictures/me.jpg\nnonsense\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gw.read_config((self.chosen,)), {"background": None, "position": "center"})
        self.assertIn("Position=top", err.getvalue())

    def test_a_broken_file_is_the_default(self):
        write(self.chosen, b"Position=\xff\n", "wb")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gw.read_config((self.chosen,)), {"background": None, "position": "center"})

    def test_the_background_file(self):
        """Under the prefix; only a readable PNG or JPEG, else the Dark wallpaper."""
        self.assertEqual(gw.background_file({"background": None}), gw.WALLPAPER)
        write(os.path.join(ROOT, "srv/me.jpg"), b"\xff\xd8\xff\xe0rest", "wb")
        write(os.path.join(ROOT, "srv/me.png"), b"\x89PNG\r\n\x1a\nrest", "wb")
        write(os.path.join(ROOT, "srv/me.svg"), "<svg/>")
        self.assertEqual(gw.background_file({"background": "/srv/me.jpg"}), os.path.join(ROOT, "srv/me.jpg"))
        self.assertEqual(gw.background_file({"background": "/srv/me.png"}), os.path.join(ROOT, "srv/me.png"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gw.background_file({"background": "/srv/me.svg"}), gw.WALLPAPER)
            self.assertEqual(gw.background_file({"background": "/srv/gone.jpg"}), gw.WALLPAPER)
            self.assertEqual(gw.background_file({"background": "/srv"}), gw.WALLPAPER)
        self.assertIn("not a PNG or JPEG", err.getvalue())
        self.assertIn("gone.jpg", err.getvalue())


class ClockTest(unittest.TestCase):
    def test_hours_from_the_locale(self):
        self.assertEqual(gw.clock_format("%r"), gw.CLOCK_FORMATS["12h"])            # en_US
        self.assertEqual(gw.clock_format("%I:%M:%S %p"), gw.CLOCK_FORMATS["12h"])
        self.assertEqual(gw.clock_format("%l:%M"), gw.CLOCK_FORMATS["12h"])
        self.assertEqual(gw.clock_format("%T"), gw.CLOCK_FORMATS["24h"])            # en_GB, de_DE
        self.assertEqual(gw.clock_format("%H:%M:%S"), gw.CLOCK_FORMATS["24h"])
        self.assertEqual(gw.clock_format(""), gw.CLOCK_FORMATS["24h"])


class ZoomTest(unittest.TestCase):
    def test_steps(self):
        self.assertEqual(gw.next_zoom(100, 1), 150)
        self.assertEqual(gw.next_zoom(300, 1), 300)
        self.assertEqual(gw.next_zoom(100, -1), 100)
        self.assertEqual(gw.next_zoom(200, -1), 150)
        self.assertEqual(gw.next_zoom(300, 0), 100)

    def test_the_whole_window_grows(self):
        self.assertEqual(gw.zoom_css(150), ".flickos-greeter { font-size: 150%; }\n")

    def test_every_key_steps(self):
        self.assertEqual(sorted(set(gw.ZOOM_KEYS.values())), [-1, 0, 1])


class PowerTest(unittest.TestCase):
    def test_two_clicks_run_it(self):
        step = gw.TwoStep()
        self.assertEqual(step.click("shutdown"), "arm")
        self.assertEqual(step.armed, "shutdown")
        self.assertEqual(step.click("shutdown"), "run")
        self.assertIsNone(step.armed)

    def test_the_other_button_arms_instead_of_running(self):
        step = gw.TwoStep()
        step.click("shutdown")
        self.assertEqual(step.click("restart"), "arm")
        self.assertEqual(step.armed, "restart")
        step.disarm()
        self.assertEqual(step.click("restart"), "arm")

    def test_every_item_asks_and_has_its_words(self):
        for key, _text, icon, method in gw.POWER:
            self.assertIn(key, gw.CONFIRM)
            self.assertTrue(icon.endswith("-symbolic"), icon)
            self.assertIn(method, ("PowerOff", "Reboot"))
            for word in ("going", "blocked", "failed"):
                self.assertIn(f"{word} {key}", gw.TEXT)

    def test_who_blocks_a_shutdown(self):
        """Only a block inhibitor of shutdown refuses (G3); delay ones wait."""
        delay = ("shutdown:sleep", "UPower", "Pause", "delay", 0, 10)
        sleep = ("sleep", "Player", "Playing", "block", 1000, 11)
        block = ("idle:shutdown", "Backup", "Copying files", "block", 1001, 12)
        self.assertEqual(gw.blocked_by([delay, sleep, block]), ("Backup", "Copying files"))
        self.assertIsNone(gw.blocked_by([delay, sleep]))
        self.assertIsNone(gw.blocked_by([]))

    def test_blocked_words_take_who_and_why(self):
        for key in ("blocked restart", "blocked shutdown"):
            self.assertIn("Backup", gw.TEXT[key].format(who="Backup", why="x"))


EVDEV = """<xkbConfigRegistry version="1.1">
  <layoutList>
    <layout>
      <configItem><name>us</name><shortDescription>en</shortDescription>
        <description>English (US)</description></configItem>
      <variantList>
        <variant><configItem><name>dvorak</name><description>English (Dvorak)</description></configItem></variant>
      </variantList>
    </layout>
    <layout>
      <configItem><name>de</name><shortDescription>de</shortDescription>
        <description>German</description></configItem>
    </layout>
  </layoutList>
  <optionList>
    <group allowMultipleSelection="true">
      <configItem><name>grp</name><description>Switching to another layout</description></configItem>
      <option><configItem><name>grp:alt_shift_toggle</name><description>Alt+Shift</description></configItem></option>
    </group>
  </optionList>
</xkbConfigRegistry>
"""


class KeyboardTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=ROOT), "evdev.xml")
        write(self.path, EVDEV)
        patcher = mock.patch.object(gw.gettext, "dgettext", lambda domain, text: text)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_layout_needs_no_label(self):
        self.assertEqual(gw.keyboard("us", "", "", self.path), ([], ""))
        self.assertEqual(gw.keyboard("", "", "", self.path), ([], ""))

    def test_names_from_the_rules(self):
        self.assertEqual(gw.keyboard("us,de", "", "ctrl:nocaps,grp:alt_shift_toggle", self.path),
                         ([("EN", "English (US)"), ("DE", "German")], "Alt+Shift"))

    def test_a_variant_keeps_its_layouts_short_name(self):
        self.assertEqual(gw.keyboard("us,us", ",dvorak", "", self.path)[0],
                         [("EN", "English (US)"), ("EN", "English (Dvorak)")])

    def test_what_the_rules_dont_know_shows_as_written(self):
        self.assertEqual(gw.keyboard("us,xx", ",nope", "grp:odd_key", self.path),
                         ([("EN", "English (US)"), ("XX", "xx")], "odd_key"))

    def test_no_rules_still_shows_the_layouts(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gw.keyboard("us,de", "", "grp:alt_shift_toggle", self.path + ".missing"),
                             ([("US", "us"), ("DE", "de")], "alt_shift_toggle"))
            write(self.path, "<broken")
            self.assertEqual(gw.keyboard("us,de", "", "", self.path)[0], [("US", "us"), ("DE", "de")])

    def test_names_are_translated_by_xkeyboard_config(self):
        with mock.patch.object(gw.gettext, "dgettext", lambda domain, text: f"{domain}:{text}"):
            self.assertEqual(gw.keyboard("us,de", "", "grp:alt_shift_toggle", self.path)[1],
                             "xkeyboard-config:Alt+Shift")

    def test_the_switch_key_moves_the_label_at_once(self):
        """GDK has the old group on the switch key's own event (G6)."""
        self.assertEqual(gw.group_after("ISO_Next_Group", 0, 0, 2), 1)
        self.assertEqual(gw.group_after("ISO_Next_Group", 1, 1, 2), 0)
        self.assertEqual(gw.group_after("ISO_Prev_Group", 0, 0, 3), 2)
        self.assertEqual(gw.group_after("ISO_First_Group", 2, 2, 3), 0)
        self.assertEqual(gw.group_after("ISO_Last_Group", 0, 0, 3), 2)

    def test_any_other_key_corrects_it(self):
        self.assertEqual(gw.group_after("a", 0, 1, 2), 1)
        self.assertEqual(gw.group_after("a", 1, 0, 2), 0)
        self.assertEqual(gw.group_after("a", 1, 112, 2), 1)    # not a group: stays as shown


class CheckTest(unittest.TestCase):
    def test_check_prints_layouts(self):
        path = os.path.join(tempfile.mkdtemp(dir=ROOT), "evdev.xml")
        write(path, EVDEV)
        out = io.StringIO()
        environment = {"XKB_DEFAULT_LAYOUT": "us,de", "XKB_DEFAULT_VARIANT": "",
                       "XKB_DEFAULT_OPTIONS": "grp:alt_shift_toggle"}
        with mock.patch.object(gw, "load_gtk", lambda: None), mock.patch.object(gw, "XKB_RULES", path), \
                mock.patch.object(gw.gettext, "dgettext", lambda domain, text: text), \
                mock.patch.object(gw.pwd, "getpwall", lambda: []), mock.patch.dict(os.environ, environment), \
                contextlib.redirect_stdout(out):
            self.assertEqual(gw.main(["--check"]), 0)
        lines = out.getvalue().splitlines()
        self.assertIn("layout\tDE\tGerman", lines)
        self.assertIn("switch\tAlt+Shift", lines)

    def test_check_prints_users_and_sessions(self):
        out = io.StringIO()
        with mock.patch.object(gw, "load_gtk", lambda: None), \
                mock.patch.dict(os.environ, {"XKB_DEFAULT_LAYOUT": "us"}), \
                mock.patch.object(gw.pwd, "getpwall", lambda: [entry("maria", 1002, "Maria Santos")]), \
                contextlib.redirect_stdout(out):
            self.assertEqual(gw.main(["--check"]), 0)
        lines = out.getvalue().splitlines()
        self.assertIn("user\tmaria\tMaria Santos", lines)
        self.assertIn("session\tflickos\tFlickOS\tflickos-session", lines)
        self.assertIn("session\tflickos-plain\tFlickOS (Plain Session)\tflickos-session-plain", lines)
        self.assertIn(f"background\t{gw.WALLPAPER}", lines)
        self.assertIn("position\tcenter", lines)

    def test_check_prints_the_choices(self):
        folder = tempfile.mkdtemp(dir=ROOT)
        chosen = os.path.join(folder, "greeter")
        write(chosen, "Position=right\nBackground=/srv/me.jpg\n")
        write(os.path.join(ROOT, "srv/me.jpg"), b"\xff\xd8\xff\xe0rest", "wb")
        out = io.StringIO()
        with mock.patch.object(gw, "load_gtk", lambda: None), mock.patch.object(gw, "CONF_FILES", (chosen,)), \
                mock.patch.dict(os.environ, {"XKB_DEFAULT_LAYOUT": "us"}), \
                mock.patch.object(gw.pwd, "getpwall", lambda: []), contextlib.redirect_stdout(out):
            self.assertEqual(gw.main(["--check"]), 0)
        lines = out.getvalue().splitlines()
        self.assertIn(f"background\t{ROOT}/srv/me.jpg", lines)
        self.assertIn("position\tright", lines)

    def test_without_greetd_it_exits_1(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(err):
            self.assertEqual(gw.main([]), 1)
        self.assertIn("flickos-greeter: GREETD_SOCK is not set", err.getvalue())

    def test_paths_follow_the_prefix(self):
        for path in (gw.LOGIN_DEFS, gw.SESSIONS_DIR, gw.ICONS_DIR, gw.DRM_DIR, gw.WALLPAPER, gw.STYLE,
                     gw.STATE, gw.LOCALE_DIR, gw.XKB_RULES, *gw.CONF_FILES):
            self.assertTrue(path.startswith(ROOT + "/"), path)


class StyleTest(unittest.TestCase):
    def test_the_fallback_shows_the_same_wallpaper(self):
        with open(os.path.join(PACKAGE, "usr/share/flickos/greeter/gtkgreet.css"), encoding="utf-8") as f:
            self.assertIn(f'url("file://{gw.WALLPAPER[len(ROOT):]}")', f.read())

    def test_card_alpha_and_selectors(self):
        with open(os.path.join(PACKAGE, "usr/share/flickos/greeter/style.css"), encoding="utf-8") as f:
            css = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)
        self.assertIn(f"alpha(@theme_bg_color, {gw.CARD_ALPHA})", css)
        for selector in re.findall(r"([^{}]+)\{", css):
            for part in selector.split(","):
                self.assertTrue(part.strip().startswith(".flickos-greeter"), part)
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,8}\b")          # theme colors only


class LockCopiesTest(unittest.TestCase):
    """Code copied from flickos-lock (ADR-002), compared while both are in the tree."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(PACKAGES, "flickos-lock", "usr", "bin", "flickos-lock")
        if not os.path.exists(path):
            raise unittest.SkipTest("flickos-lock isn't in this tree")
        cls.lock = load("flickos_lock_for_greeter", path)

    def test_same_display_name(self):
        self.assertEqual(inspect.getsource(gw.display_name), inspect.getsource(self.lock.display_name))

    def test_same_look(self):
        for name in ("CLOCK_FORMATS", "DIM", "CARD_ALPHA", "PICTURE_PIXELS", "REVEAL_SECONDS", "LOGIND",
                     "ZOOM_STEPS"):
            self.assertEqual(getattr(gw, name), getattr(self.lock, name), name)
        self.assertEqual(gw.DATE_FORMAT, self.lock.DATE_FORMAT)
        for key in ("show", "hide", "caps", "wrong", "checking"):
            self.assertEqual(gw.TEXT[key], self.lock.TEXT[key], key)


    def test_same_zoom(self):
        self.assertEqual(inspect.getsource(gw.next_zoom), inspect.getsource(self.lock.next_zoom))


class MenuCopiesTest(unittest.TestCase):
    """The two-click power buttons, copied from flickos-menu (ADR-009)."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(PACKAGES, "flickos-menu", "usr", "bin", "flickos-menu")
        if not os.path.exists(path):
            raise unittest.SkipTest("flickos-menu isn't in this tree")
        cls.menu = load("flickos_menu_for_greeter", path)

    def test_same_two_steps(self):
        self.assertEqual(gw.CONFIRM_SECONDS, self.menu.CONFIRM_SECONDS)
        for method in ("click", "disarm"):
            self.assertEqual(inspect.getsource(getattr(gw.TwoStep, method)),
                             inspect.getsource(getattr(self.menu.TwoStep, method)))

    def test_same_words(self):
        names = {item[0]: item[1] for item in self.menu.POWER}
        for key, text, _icon, _method in gw.POWER:
            self.assertEqual(text, names[key])
            self.assertEqual(gw.CONFIRM[key], self.menu.CONFIRM[key])


def po_list(name):
    """The lines of po/POTFILES or po/LINGUAS, without comments."""
    with open(os.path.join(PACKAGE, "po", name), encoding="utf-8") as f:
        return [line.split("#")[0].strip() for line in f if line.split("#")[0].strip()]


class TranslationTest(unittest.TestCase):
    def test_template_is_current(self):
        """po/flickos-greeter.pot has every marked string and no others. Same
        xgettext options as tools/update-po.sh, which fixes this."""
        with tempfile.TemporaryDirectory() as folder:
            new = os.path.join(folder, "new.pot")
            subprocess.run(["xgettext", "--language=Python", "--from-code=UTF-8", "--keyword=N_",
                            "--output=" + new, *po_list("POTFILES")], cwd=PACKAGE, check=True)
            shipped = os.path.join(PACKAGE, "po", "flickos-greeter.pot")
            for definitions, reference in ((shipped, new), (new, shipped)):
                result = subprocess.run(["msgcmp", "--use-untranslated", definitions, reference],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f"run tools/update-po.sh flickos-greeter\n{result.stderr}")

    def test_every_language_has_a_file_that_compiles(self):
        languages = po_list("LINGUAS")
        po = os.path.join(PACKAGE, "po")
        self.assertEqual(sorted(languages), sorted(name[:-3] for name in os.listdir(po) if name.endswith(".po")),
                         "po/LINGUAS and the po/*.po files differ")
        for lang in languages:
            with self.subTest(lang=lang):
                subprocess.run(["msgfmt", "--check", "--output-file=/dev/null",
                                os.path.join(po, lang + ".po")], check=True)

    def test_translation_is_shown_and_values_stay(self):
        """A translation under the prefix replaces what people read; what
        programs read (--check's ids and commands) stays."""
        root = tempfile.mkdtemp(dir=ROOT)
        po = os.path.join(root, "xx.po")
        write(po, 'msgid ""\nmsgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n'
                  'msgid "Shut Down"\nmsgstr "Shüt Döwn"\n\n'
                  'msgid "FlickOS (Plain Session)"\nmsgstr "FlickOS (Pläin)"\n')
        mo = os.path.join(root, "usr/share/locale/xx/LC_MESSAGES/flickos-greeter.mo")
        os.makedirs(os.path.dirname(mo))
        subprocess.run(["msgfmt", "--output-file=" + mo, po], check=True)
        with mock.patch.dict(os.environ, {"LANGUAGE": "xx"}):
            translated = load("greeter_window_xx", os.path.join(PACKAGE, "usr/libexec/flickos/greeter-window"), root)
        self.assertEqual(translated._(translated.POWER[1][1]), "Shüt Döwn")
        self.assertEqual(translated._(translated.TEXT["wrong"]), "Wrong password. Try again.")
        out = io.StringIO()
        with mock.patch.object(translated, "load_gtk", lambda: None), \
                mock.patch.object(translated.pwd, "getpwall", lambda: []), \
                mock.patch.dict(os.environ, {"XKB_DEFAULT_LAYOUT": "us"}), contextlib.redirect_stdout(out):
            self.assertEqual(translated.main(["--check"]), 0)
        self.assertIn("session\tflickos-plain\tFlickOS (Pläin)\tflickos-session-plain", out.getvalue())

    def test_no_function_binds_the_translator(self):
        """`for _ in` or `_ok, _ = …` makes every _() in that function fail,
        only when that window is drawn."""
        with open(gw.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for function in ast.walk(tree):
            if isinstance(function, (ast.FunctionDef, ast.Lambda)):
                stores = [n for n in ast.walk(function) if isinstance(n, ast.Name) and n.id == "_"
                          and isinstance(n.ctx, ast.Store)]
                arguments = [a for a in ast.walk(function) if isinstance(a, ast.arg) and a.arg == "_"]
                self.assertEqual(stores + arguments, [], getattr(function, "name", "a lambda"))


class RecoveryTest(unittest.TestCase):
    def test_recovery_counts_this_login_screen(self):
        """A login screen flickos-recovery doesn't know makes every start look failed."""
        path = os.path.join(PACKAGES, "flickos-recovery", "usr", "bin", "flickos-recovery")
        if not os.path.exists(path):
            self.skipTest("flickos-recovery isn't in this tree")
        with open(path, encoding="utf-8") as f:
            line = next(l for l in f if l.startswith("GOOD_PROCESSES"))
        self.assertIn('"greeter-window"', line)
        self.assertIn('"gtkgreet"', line)              # the fallback


class ScriptTest(unittest.TestCase):
    """The greeter script's fallback, with stand-ins for systemd-cat, cage,
    gtkgreet and greeter-window."""

    def run_script(self, window_status, keyboard=None):
        folder = tempfile.mkdtemp(dir=ROOT)
        bin_dir = os.path.join(folder, "bin")
        os.makedirs(bin_dir)
        stand_ins = {
            "systemd-cat": '#!/bin/sh\nwhile [ "${1#-}" != "$1" ]; do shift; done\nexec "$@"\n',
            "cage": '#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n',
            "gtkgreet": '#!/bin/sh\necho "gtkgreet $*"\n',
        }
        for name, text in stand_ins.items():
            write(os.path.join(bin_dir, name), text)
            os.chmod(os.path.join(bin_dir, name), 0o755)
        window = os.path.join(folder, "greeter-window")
        write(window, f'#!/bin/sh\necho "window $GTK_THEME $NO_AT_BRIDGE"\n'
                      f'echo "options=$XKB_DEFAULT_OPTIONS" >&2\nexit {window_status}\n')
        os.chmod(window, 0o755)
        with open(os.path.join(PACKAGE, "usr/libexec/flickos/greeter"), encoding="utf-8") as f:
            script = f.read()
        self.assertIn("/usr/libexec/flickos/greeter-window\n", script)
        script = script.replace("/usr/libexec/flickos/greeter-window\n", window + "\n")
        keyboard_file = os.path.join(folder, "keyboard")      # never the build host's
        write(keyboard_file, keyboard or "")
        self.assertIn("/etc/default/keyboard", script)
        script_path = os.path.join(folder, "greeter")
        write(script_path, script.replace("/etc/default/keyboard", keyboard_file))
        return subprocess.run(["sh", script_path], capture_output=True, text=True, timeout=30,
                              env={"PATH": bin_dir + ":/usr/bin:/bin", "HOME": folder})

    def test_a_login_needs_no_fallback(self):
        result = self.run_script(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "window FlickOS-Arc-Dark 1\n")

    def options(self, keyboard):
        result = self.run_script(0, keyboard)
        return next(l for l in result.stderr.splitlines() if l.startswith("options="))[len("options="):]

    def test_two_layouts_always_have_a_switch_key(self):
        """Only an XKB option changes the layout in cage (ADR-009)."""
        self.assertEqual(self.options('XKBLAYOUT="us,de"\n'), "grp:alt_shift_toggle")
        self.assertEqual(self.options('XKBLAYOUT="us,de"\nXKBOPTIONS="ctrl:nocaps"\n'),
                         "ctrl:nocaps,grp:alt_shift_toggle")

    def test_a_chosen_switch_key_stays(self):
        self.assertEqual(self.options('XKBLAYOUT="us,de"\nXKBOPTIONS="grp:win_space_toggle"\n'),
                         "grp:win_space_toggle")

    def test_one_layout_gets_no_switch_key(self):
        self.assertEqual(self.options('XKBLAYOUT="de"\nXKBOPTIONS="ctrl:nocaps,compose:ralt"\n'),
                         "ctrl:nocaps,compose:ralt")

    def test_a_failing_window_brings_up_gtkgreet(self):
        result = self.run_script(1)
        self.assertEqual(result.stdout.splitlines()[0], "window FlickOS-Arc-Dark 1")
        self.assertRegex(result.stdout.splitlines()[1],
                         r"^gtkgreet --command flickos-session --style /usr/share/flickos/greeter/gtkgreet.css$")


if __name__ == "__main__":
    unittest.main()
