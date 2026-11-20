"""Tests for flickos-classroom-view. They run on the developer's own desktop,
so every outside path is a temporary folder or a stand-in: XDG folders, /proc,
the system's settings file, and the commands the agent runs (grim,
flickos-lock, notify-send, xdg-open, wayvnc, the strip) are fakes on PATH or
paths to them (WAYVNC, STRIP: never the real wayvnc, which would serve the
developer's own screen). The network is 127.0.0.1 only, mDNS off; nothing
reaches the real session or the panel."""

import importlib.machinery
import importlib.util
import json
import os
import queue
import contextlib
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader("flickos_classroom", os.path.join(PACKAGE, "usr/bin/flickos-classroom-view"))
_spec = importlib.util.spec_from_loader("flickos_classroom", _loader)
fc = importlib.util.module_from_spec(_spec)
_loader.exec_module(fc)

FAKE = """#!/bin/sh
printf '%s\\n' "$(basename "$0") $*" >> "{log}"
"""
# grim: a 640x360 grey PPM on stdout.
FAKE_GRIM = """#!/usr/bin/python3
import sys
sys.stdout.buffer.write(b"P6 640 360 255\\n" + bytes([90, 100, 110]) * (640 * 360))
"""


# wayvnc: logs its arguments, listens on the Unix socket it is given (last
# argument), greets the one client as an RFB server would and echoes the rest.
FAKE_WAYVNC = """#!/usr/bin/python3
import socket, sys
with open("{log}", "a") as f:
    f.write("wayvnc " + " ".join(sys.argv[1:]) + "\\n")
server = socket.socket(socket.AF_UNIX)
server.bind(sys.argv[-1])
server.listen(1)
conn, _ = server.accept()
conn.sendall(b"RFB 003.008\\n")
while True:
    data = conn.recv(65536)
    if not data:
        break
    conn.sendall(data)
"""
# The strip: shown at once, Stop "pressed" when the trigger file appears.
FAKE_STRIP = """#!/bin/sh
printf '%s\\n' "strip $*" >> "{log}"
echo shown
while [ ! -e "{trigger}" ]; do sleep 0.05; done
exit 3
"""
JPEG = b"\xff\xd8\xff\xe0" + b"frame" * 20


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="classroom-test-")
        self.addCleanup(self.remove_tmp)
        env = {}
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
            path = os.path.join(self.tmp, name.lower())
            os.makedirs(path, mode=0o700)
            env[name] = path
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.calls = os.path.join(self.tmp, "calls.log")
        for name in ("flickos-lock", "notify-send", "xdg-open", "flickos-layout"):
            self.script(name, FAKE.format(log=self.calls))
        self.script("grim", FAKE_GRIM)
        self.script("pkill", FAKE.format(log=self.calls))          # never the real one
        env["PATH"] = self.bin + os.pathsep + "/usr/bin:/bin"
        env["WAYLAND_DISPLAY"] = None               # never the developer's session
        env["LABWC_PID"] = None                     # nor its labwc (the agent ends with it)
        self.old_env = {k: os.environ.get(k) for k in env}
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.addCleanup(self.restore_env)
        self.proc = os.path.join(self.tmp, "proc")
        os.makedirs(self.proc)
        with open(os.path.join(self.proc, "cmdline"), "w") as f:
            f.write("BOOT_IMAGE=/vmlinuz quiet\n")
        self.saved = {n: getattr(fc, n) for n in ("PROC", "SYSTEM_CONF", "HISTORY_CONF", "LAB_DIR", "LAB_RUN",
                                                  "SEAT_FILE", "SESSIONS_DIR", "USER_RUNTIME", "LAB_PEERS",
                                                  "SYSTEMCTL", "WAYVNC", "STRIP")}
        fc.PROC = self.proc
        fc.SYSTEM_CONF = os.path.join(self.tmp, "etc", "classroom.conf")
        fc.HISTORY_CONF = os.path.join(self.tmp, "etc", "history.conf")
        # A lab computer's places (ADR-011): never the build host's /etc or /run.
        fc.LAB_DIR = os.path.join(self.tmp, "etc", "flickos", "classroom")
        fc.LAB_RUN = os.path.join(self.tmp, "run-lab")
        fc.SEAT_FILE = os.path.join(self.tmp, "seat0")
        fc.SESSIONS_DIR = os.path.join(self.tmp, "sessions")
        fc.USER_RUNTIME = os.path.join(self.tmp, "run-user", "{uid}")
        fc.SYSTEMCTL = os.path.join(self.bin, "systemctl")
        fc.WAYVNC = os.path.join(self.bin, "no-wayvnc")             # vnc_fakes() gives a fake one
        fc.STRIP = [os.path.join(self.bin, "no-strip")]
        self.script("systemctl", FAKE.format(log=self.calls))
        self.addCleanup(lambda: [setattr(fc, n, v) for n, v in self.saved.items()])

    def remove_tmp(self):
        """Detached fakes (notify-send, xdg-open) may still be writing their line."""
        for _ in range(20):
            try:
                shutil.rmtree(self.tmp)
                return
            except OSError:
                time.sleep(0.1)
        shutil.rmtree(self.tmp)

    def restore_env(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def script(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def logged(self):
        try:
            with open(self.calls) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def vnc_fakes(self, strip=True):
        """A fake wayvnc and strip; self.trigger "presses" the strip's Stop."""
        fc.WAYVNC = os.path.join(self.bin, "wayvnc")
        self.script("wayvnc", FAKE_WAYVNC.format(log=self.calls))
        self.trigger = os.path.join(self.tmp, "press-stop")
        self.script("strip", FAKE_STRIP.format(log=self.calls, trigger=self.trigger) if strip
                    else "#!/bin/sh\nexit 1\n")
        fc.STRIP = [os.path.join(self.bin, "strip")]

    def greeted(self, tls, extra):
        """The RFB greeting through the pipe, then an echo of what we send."""
        data = extra
        while not data.endswith(b"\n"):
            data += tls.recv(100)
        self.assertEqual(data, b"RFB 003.008\n")
        tls.sendall(b"pointer and keys")
        echo = b""
        while len(echo) < 16:
            echo += tls.recv(100)
        self.assertEqual(echo, b"pointer and keys")

    def wait_for(self, check, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = check()
            if value:
                return value
            time.sleep(0.05)
        self.fail("timed out")


class SettingsTest(Base):
    def test_off_by_default(self):
        self.assertEqual(fc.load_settings()["sharing"], "off")

    def test_system_then_user(self):
        os.makedirs(os.path.dirname(fc.SYSTEM_CONF))
        with open(fc.SYSTEM_CONF, "w") as f:
            f.write("[Classroom]\nsharing = on\n")
        self.assertEqual(fc.load_settings()["sharing"], "on")
        fc.save_setting("sharing", "off")
        self.assertEqual(fc.load_settings()["sharing"], "off")
        fc.save_setting("sharing", None)
        self.assertEqual(fc.load_settings()["sharing"], "on")

    def test_broken_file_means_defaults(self):
        os.makedirs(os.path.dirname(fc.user_conf()), exist_ok=True)
        with open(fc.user_conf(), "wb") as f:
            f.write(b"\xff\xfe[Classroom\nsharing=maybe")
        self.assertEqual(fc.load_settings()["sharing"], "off")

    def test_change_is_recorded(self):
        fc.save_setting("sharing", "on")
        path = os.path.join(os.environ["XDG_STATE_HOME"], "flickos", "history.jsonl")
        with open(path) as f:
            entry = json.loads(f.readline())
        self.assertEqual((entry["owner"], entry["key"], entry["old"], entry["new"]),
                         ("flickos-classroom-view", "sharing", "off", "on"))

    def test_run_exits_at_once_while_off(self):
        start = time.monotonic()
        self.assertEqual(fc.main(["student", "run"]), 0)
        self.assertLess(time.monotonic() - start, 1)
        self.assertFalse(os.path.exists(os.path.join(os.environ["XDG_RUNTIME_DIR"], "flickos", "classroom")))

    def test_never_in_the_live_session(self):
        fc.save_setting("sharing", "on")
        with open(os.path.join(self.proc, "cmdline"), "w") as f:
            f.write("boot=live quiet\n")
        self.assertEqual(fc.main(["student", "run"]), 0)
        self.assertEqual(fc.main(["student", "on"]), 1)

    def test_on_and_off(self):
        """on starts the agent and has the panel add the button; off stops
        it and drops the button (flickos-layout reload-panel, in a session only)."""
        started = []
        real = fc.start_agent
        fc.start_agent = lambda: started.append(True)
        self.addCleanup(setattr, fc, "start_agent", real)
        os.environ["WAYLAND_DISPLAY"] = "wayland-test"
        self.assertEqual(fc.main(["student", "on"]), 0)
        self.assertEqual((fc.load_settings()["sharing"], started), ("on", [True]))
        self.assertEqual(fc.main(["student", "off"]), 0)
        self.assertEqual(fc.load_settings()["sharing"], "off")
        self.assertEqual(self.logged(), ["flickos-layout reload-panel"] * 2)
        del os.environ["WAYLAND_DISPLAY"]
        self.assertEqual(fc.main(["student", "on"]), 0)
        self.assertEqual(len(self.logged()), 2)        # outside a session: no panel to reload

    def test_panel_never_empty_while_on(self):
        """ADR-004: the button shows whenever sharing is on, the agent's file or not."""
        import io
        import contextlib as cl
        def panel():
            out = io.StringIO()
            with cl.redirect_stdout(out):
                fc.main(["student", "panel"])
            return out.getvalue()
        self.assertEqual(panel(), "")                       # off: nothing, hidden
        fc.save_setting("sharing", "on")
        self.assertEqual(json.loads(panel())["alt"], "on")  # on, no agent yet
        run_dir = os.path.join(os.environ["XDG_RUNTIME_DIR"], "flickos", "classroom")
        os.makedirs(run_dir)
        with open(os.path.join(run_dir, fc.PANEL_FILE), "w") as f:
            f.write(json.dumps(fc.panel_json("looking", "Ms Cruz")))
        self.assertEqual(json.loads(panel())["alt"], "looking")

    def test_wrong_arguments(self):
        with open(os.devnull, "w") as null:
            old, sys.stderr = sys.stderr, null
            try:
                self.assertEqual(fc.main(["student"]), 2)
            finally:
                sys.stderr = old


class TextTest(unittest.TestCase):
    def test_urls(self):
        self.assertTrue(fc.url_allowed("https://example.org/a?b=c"))
        self.assertTrue(fc.url_allowed("HTTP://example.org"))
        for url in ("file:///etc/passwd", "javascript:alert(1)", "https://a b", "https://x\n",
                    "ftp://x", "https://" + "a" * fc.MAX_URL):
            self.assertFalse(fc.url_allowed(url), url)

    def test_clean_text(self):
        self.assertEqual(fc.clean_text("a\x1b[31mb\tc", 50), "a [31mb c")
        self.assertEqual(len(fc.clean_text("x" * 999, fc.MAX_MESSAGE)), fc.MAX_MESSAGE)

    def test_code(self):
        for _ in range(50):
            code = fc.new_code()
            self.assertEqual(len(code), fc.CODE_DIGITS)
            self.assertLess(fc.code_number(code), 2 ** fc.PAIR_BITS)
        for bad in ("12345", "1234567", "12a456", ""):
            with self.assertRaises(fc.ClassroomError):
                fc.code_number(bad)

    def test_panel_states(self):
        for state in fc.PANEL_STATES:
            out = fc.panel_json(state, "Ms Cruz")
            self.assertEqual(out["alt"], state)
            self.assertEqual(out["text"], " ")             # a space: base.css draws the icon
        self.assertIn("Ms Cruz", fc.panel_json("looking", "Ms Cruz")["tooltip"])


class DemoFrameTest(unittest.TestCase):
    def ppm(self, width, height):
        return f"P6 {width} {height} 255\n".encode() + bytes([120, 130, 140]) * (width * height)

    def size(self, jpeg):
        from PIL import Image
        import io
        return Image.open(io.BytesIO(jpeg)).size

    def test_own_size_up_to_1920(self):
        self.assertEqual(self.size(fc.demo_jpeg(self.ppm(1366, 768), slow=False)), (1366, 768))
        self.assertEqual(self.size(fc.demo_jpeg(self.ppm(1920, 1080), slow=False)), (1920, 1080))
        self.assertEqual(self.size(fc.demo_jpeg(self.ppm(3840, 1080), slow=False)), (1920, 540))   # two screens

    def test_slow_network_1280(self):
        """Q13."""
        self.assertEqual(self.size(fc.demo_jpeg(self.ppm(1920, 1080), slow=True)), (1280, 720))
        self.assertEqual(self.size(fc.demo_jpeg(self.ppm(1024, 600), slow=True)), (1024, 600))

    def test_slow_switch_does_not_flap(self):
        """Q13: 1280 wide once a frame took over 1 s; full size only under 0.5 s."""
        console = unittest.mock.Mock(demo={"took": {}, "slow": False})
        steps = [("a", 0.8, False), ("b", 1.5, True), ("b", 0.8, True), ("a", 0.3, True), ("b", 0.4, False)]
        for ident, seconds, slow in steps:
            fc.Console.demo_took(console, ident, seconds)
            self.assertEqual(console.demo["slow"], slow, (ident, seconds))

    def test_channel_carries_a_frame_from_the_teacher(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        fc.Channel(a).send({"verb": "demo-frame", "size": len(JPEG)}, JPEG)
        fc.Channel(a).send({"verb": "ping"})
        channel = fc.Channel(b)
        self.assertEqual(channel.receive(), ({"verb": "demo-frame", "size": len(JPEG)}, JPEG))
        self.assertEqual(channel.receive(), ({"verb": "ping"}, b""))


class MdnsTest(unittest.TestCase):
    def test_query_and_answer(self):
        self.assertTrue(fc.is_query_for_us(fc.mdns_query()))
        answer = fc.mdns_answer("student-ab12", 47100, {"v": 1, "name": "Ana Cruz", "pairing": "1"})
        self.assertFalse(fc.is_query_for_us(answer))
        found = fc.parse_answer(answer)
        self.assertEqual((found["id"], found["port"], found["name"], found["pairing"]),
                         ("student-ab12", 47100, "Ana Cruz", "1"))

    def test_garbage(self):
        for data in (b"", b"\x00" * 5, b"\x00\x00\x84\x00\x00\x00\x00\x01" + b"\xc0\x0c" * 20, os.urandom(64)):
            self.assertIsNone(fc.parse_answer(data))
            self.assertFalse(fc.is_query_for_us(data))


class MdnsEveryNetworkTest(unittest.TestCase):
    """Two networks (Wi-Fi and a cable, found with two VMs): the group is
    joined, and sent to, on each; a network that comes later is joined then.
    A stand-in socket: nothing reaches the real network."""

    class FakeSocket:
        def __init__(self):
            self.calls = []

        def setsockopt(self, level, option, value):
            self.calls.append(("opt", option, value))

        def sendto(self, data, where):
            self.calls.append(("send", data, where))

    def test_joins_and_sends_on_each(self):
        networks = ["10.0.2.15", "10.47.0.7"]
        mdns = fc.Mdns.__new__(fc.Mdns)
        mdns.addresses, mdns.joined, mdns.sock = (lambda: list(networks)), set(), self.FakeSocket()
        mdns.refresh()
        joins = [c[2][4:] for c in mdns.sock.calls if c[1] == fc.socket.IP_ADD_MEMBERSHIP]
        self.assertEqual(sorted(fc.socket.inet_ntoa(j) for j in joins), networks)
        mdns.sock.calls.clear()
        mdns.send(b"query")
        sends = [c for c in mdns.sock.calls if c[0] == "send"]
        self.assertEqual(len(sends), 2)
        self.assertEqual({fc.socket.inet_ntoa(c[2]) for c in mdns.sock.calls if c[1] == fc.socket.IP_MULTICAST_IF},
                         set(networks))
        networks.append("192.168.1.20")                     # Wi-Fi after login
        mdns.sock.calls.clear()
        mdns.refresh()
        self.assertEqual(len([c for c in mdns.sock.calls if c[1] == fc.socket.IP_ADD_MEMBERSHIP]), 1)

    def test_addresses_without_loopback(self):
        self.assertNotIn("127.0.0.1", fc.ipv4_addresses())


class PairingProofTest(unittest.TestCase):
    """prove_code over a socket pair, no TLS: the bit-by-bit proof alone."""

    def run_pair(self, teacher_code, student_code, teacher_fps=("t", "s"), student_fps=("t", "s")):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        results = {}

        def student():
            results["student"] = fc.prove_code(fc.Channel(b), student_code, *student_fps, teacher_side=False)
        thread = threading.Thread(target=student)
        thread.start()
        results["teacher"] = fc.prove_code(fc.Channel(a), teacher_code, *teacher_fps, teacher_side=True)
        thread.join(10)
        return results

    def test_same_code(self):
        self.assertEqual(self.run_pair("482913", "482913"), {"teacher": True, "student": True})

    def test_wrong_code(self):
        self.assertEqual(self.run_pair("482913", "482912"), {"teacher": False, "student": False})

    def test_someone_in_the_middle(self):
        """The same code, but the two sides saw different certificates."""
        self.assertEqual(self.run_pair("111111", "111111", ("t", "s"), ("t", "m")),
                         {"teacher": False, "student": False})


class NetworkTest(Base):
    """An agent on 127.0.0.1 and the console's halves: pairing, then a session."""

    def setUp(self):
        super().setUp()
        self.run_dir = os.path.join(os.environ["XDG_RUNTIME_DIR"], "flickos", "classroom")
        os.makedirs(self.run_dir, mode=0o700)
        self.student = fc.identity(fc.STUDENT_DIR)
        self.teacher = fc.identity(fc.TEACHER_DIR)
        self.agent = self.start_agent()

    def start_agent(self):
        agent = fc.Agent(self.student, self.run_dir, port=0, mdns=False, host="127.0.0.1")
        agent.start()
        self.addCleanup(agent.stop)
        return agent

    def pair(self, student_code, teacher_code):
        answer = {}
        thread = threading.Thread(target=lambda: answer.setdefault("a", self.agent.start_pairing(student_code)))
        thread.start()
        self.wait_for(self.agent.pairing_open)
        result = fc.pair_student(self.teacher, "Ms Cruz", teacher_code, "127.0.0.1", self.agent.port)
        return result, thread, answer

    def test_identities(self):
        self.assertTrue(self.student.id.startswith("student-"))
        self.assertNotEqual(self.student.fingerprint, self.teacher.fingerprint)
        mode = stat.S_IMODE(os.stat(self.student.key).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(fc.identity(fc.STUDENT_DIR).fingerprint, self.student.fingerprint)   # made once

    def test_pairing(self):
        result, thread, answer = self.pair("123456", "123456")
        thread.join(10)
        self.assertIsNotNone(result)
        ident, name, pem = result
        self.assertEqual(ident, self.student.id)
        self.assertEqual(fc.fingerprint(fc.ssl.PEM_cert_to_DER_cert(pem)), self.student.fingerprint)
        self.assertEqual(answer["a"], ("paired", "Ms Cruz"))
        self.assertEqual([t["name"] for t in self.agent.teachers], ["Ms Cruz"])
        self.assertFalse(self.agent.pairing_open())
        with open(os.path.join(self.run_dir, fc.PANEL_FILE)) as f:
            self.assertEqual(json.load(f)["alt"], "open")

    def test_wrong_code_three_times(self):
        answer = {}
        thread = threading.Thread(target=lambda: answer.setdefault("a", self.agent.start_pairing("123456")))
        thread.start()
        self.wait_for(self.agent.pairing_open)
        for _ in range(fc.PAIR_TRIES):
            self.assertIsNone(fc.pair_student(self.teacher, "Ms Cruz", "654321", "127.0.0.1", self.agent.port))
        thread.join(10)
        self.assertEqual(answer["a"][0], "failed")
        self.assertEqual(self.agent.teachers, [])

    def test_no_pairing_unless_asked(self):
        self.assertIsNone(fc.pair_student(self.teacher, "Ms Cruz", "123456", "127.0.0.1", self.agent.port))
        self.assertEqual(self.agent.teachers, [])

    def paired_link(self):
        result, thread, _ = self.pair("000777", "000777")
        thread.join(10)
        ident, name, pem = result
        events = queue.Queue()
        link = fc.Link(self.teacher, {"id": ident, "name": name, "pem": pem},
                       lambda _i: ("127.0.0.1", self.agent.port), lambda *e: events.put(e[1:]))
        link.start()
        self.addCleanup(link.stop)
        return link, events

    def next_event(self, events, kind, seconds=10, verb=None):
        """The next event of kind; for "done", the answer to verb (the console
        asks for thumbnails as it connects, and that is answered too)."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                got, value = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if got == kind and (verb is None or value.get("verb") == verb):
                return value
        self.fail(f"no {kind} event")

    def test_session_verbs(self):
        link, events = self.paired_link()
        self.next_event(events, "online")
        frame = self.next_event(events, "frame")
        self.assertTrue(frame.startswith(b"\xff\xd8"))                      # a JPEG
        self.assertLess(len(frame), 20000)
        self.wait_for(lambda: self.agent.looking)
        with open(os.path.join(self.run_dir, fc.PANEL_FILE)) as f:
            self.assertEqual(json.load(f)["alt"], "looking")

        link.send({"verb": "message", "text": "Page 12, please", "seconds": 30})
        self.assertTrue(self.next_event(events, "done", verb="message")["ok"])
        self.wait_for(lambda: any(line.startswith("notify-send") and "Page 12, please" in line
                                  for line in self.logged()))

        link.send({"verb": "open-url", "url": "file:///etc/passwd"})
        self.assertFalse(self.next_event(events, "done", verb="open-url")["ok"])
        link.send({"verb": "open-url", "url": "https://example.org/lesson"})
        self.assertTrue(self.next_event(events, "done", verb="open-url")["ok"])
        self.wait_for(lambda: "xdg-open https://example.org/lesson" in self.logged())

        link.send({"verb": "lock", "message": "Eyes up"})
        self.assertTrue(self.next_event(events, "done", verb="lock")["ok"])
        release = os.path.join(self.run_dir, fc.RELEASE_FILE)
        self.assertTrue(os.path.exists(release))
        self.assertIn(f"flickos-lock lock --class-message Eyes up --release {release}", self.logged())
        self.assertEqual(self.agent.state(), "locked")
        link.send({"verb": "unlock"})
        self.assertTrue(self.next_event(events, "done", verb="unlock")["ok"])
        self.assertFalse(os.path.exists(release))

        link.send({"verb": "run", "command": "rm -rf ~"})
        done = self.next_event(events, "done", verb="run")
        self.assertEqual((done["ok"], done["error"]), (False, "unknown"))

    def test_view_session(self):
        """ADR-012: a connection of its own; wayvnc view-only on a socket in
        the runtime folder, with the strip (ADR-015), gone with the teacher."""
        self.vnc_fakes()
        link, events = self.paired_link()
        self.next_event(events, "online")
        tls, extra = fc.open_screen(self.teacher, link.student, "127.0.0.1", self.agent.port, control=False)
        self.greeted(tls, extra)
        self.assertEqual(self.agent.state(), "viewed")
        with open(os.path.join(self.run_dir, fc.PANEL_FILE)) as f:
            self.assertEqual(json.load(f)["tooltip"], "Ms Cruz is viewing this screen")
        sock = os.path.join(self.run_dir, fc.VNC_SOCKET)
        self.assertIn(f"wayvnc -C {self.run_dir}/vnc.conf -S {self.run_dir}/vnc-control.sock -d -r -u {sock}",
                      self.logged())
        self.assertIn("strip --text Ms Cruz is viewing this screen --stop", self.logged())
        self.assertEqual(self.agent.session.channel is not None, True)   # the main session goes on
        tls.close()
        self.wait_for(lambda: self.agent.vnc is None)
        self.assertFalse(os.path.exists(sock))
        self.assertEqual(self.agent.state(), "looking")

    def test_control_and_the_students_stop(self):
        self.vnc_fakes()
        link, events = self.paired_link()
        self.next_event(events, "online")
        tls, extra = fc.open_screen(self.teacher, link.student, "127.0.0.1", self.agent.port, control=True)
        self.greeted(tls, extra)
        self.assertEqual(self.agent.state(), "controlled")
        line = next(l for l in self.logged() if l.startswith("wayvnc"))
        self.assertNotIn(" -d", line)                                   # input allowed
        open(self.trigger, "w").close()                                 # the student presses Stop
        event = self.next_event(events, "event")
        self.assertEqual((event["what"], event["control"]), ("stopped", True))
        self.wait_for(lambda: self.agent.vnc is None)
        tls.settimeout(5)
        self.assertEqual(tls.recv(100), b"")                            # the teacher's view ends

    def test_no_strip_no_session(self):
        self.vnc_fakes(strip=False)
        link, events = self.paired_link()
        self.next_event(events, "online")
        with self.assertRaises(fc.ClassroomError) as caught:
            fc.open_screen(self.teacher, link.student, "127.0.0.1", self.agent.port, control=False)
        self.assertIn("strip", str(caught.exception))
        self.assertFalse(any(l.startswith("wayvnc") for l in self.logged()))
        self.assertEqual(self.agent.state(), "looking")

    def test_no_wayvnc(self):
        link, events = self.paired_link()
        self.next_event(events, "online")
        with self.assertRaises(fc.ClassroomError) as caught:
            fc.open_screen(self.teacher, link.student, "127.0.0.1", self.agent.port, control=True)
        self.assertIn("wayvnc isn't installed", str(caught.exception))

    def test_view_is_not_a_verb_of_the_main_session(self):
        link, events = self.paired_link()
        self.next_event(events, "online")
        link.send({"verb": "control"})
        done = self.next_event(events, "done", verb="control")
        self.assertEqual((done["ok"], done["error"]), (False, "on a connection of its own"))

    def demo_on(self, link, events):
        # The fake flickos-lock leaves no class mark: make one, or watch_lock ends the lock.
        lock_dir = os.path.join(os.path.dirname(self.run_dir), "lock")
        os.makedirs(lock_dir, exist_ok=True)
        open(os.path.join(lock_dir, "class"), "w").close()
        link.send({"verb": "demo", "on": True})
        self.assertTrue(self.next_event(events, "done", verb="demo")["ok"])

    def test_demo(self):
        """ADR-014: the class lock with the teacher's frames."""
        link, events = self.paired_link()
        self.next_event(events, "online")
        self.demo_on(link, events)
        demo = os.path.join(self.run_dir, fc.DEMO_FILE)
        release = os.path.join(self.run_dir, fc.RELEASE_FILE)
        self.assertIn(f"flickos-lock lock --class-message {fc.DEMO_MESSAGE} --release {release} "
                      f"--class-image {demo}", self.logged())
        self.assertEqual(self.agent.state(), "demo")
        self.assertTrue(link.offer_frame(JPEG))
        done = self.next_event(events, "frame-done")
        self.assertTrue(done["ok"])
        self.assertGreaterEqual(done["seconds"], 0)
        with open(demo, "rb") as f:
            self.assertEqual(f.read(), JPEG)
        self.assertEqual(stat.S_IMODE(os.stat(demo).st_mode), 0o600)
        link.offer_frame(b"<script>")                                    # only a JPEG
        self.assertFalse(self.next_event(events, "frame-done")["ok"])
        link.send({"verb": "demo", "on": False})
        self.assertTrue(self.next_event(events, "done", verb="demo")["ok"])
        self.assertFalse(os.path.exists(demo))
        self.assertFalse(os.path.exists(release))
        self.assertEqual(self.agent.state(), "looking")

    def test_demo_frame_without_a_demo(self):
        link, events = self.paired_link()
        self.next_event(events, "online")
        link.offer_frame(JPEG)
        self.assertFalse(self.next_event(events, "frame-done")["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, fc.DEMO_FILE)))

    def test_demo_frames_never_queue(self):
        """The newest frame replaces one not sent yet; the last always arrives."""
        link, events = self.paired_link()
        self.next_event(events, "online")
        self.demo_on(link, events)
        frames = [JPEG + bytes([n]) for n in range(20)]
        for frame in frames:
            link.offer_frame(frame)
        demo = os.path.join(self.run_dir, fc.DEMO_FILE)

        def last_arrived():
            with contextlib.suppress(OSError), open(demo, "rb") as f:
                return f.read() == frames[-1]
        self.wait_for(last_arrived)
        sent = 0
        while not events.empty():
            sent += events.get()[0] == "frame-done"
        self.assertLess(sent, len(frames))

    def test_stopping_lets_the_lock_go(self):
        link, events = self.paired_link()
        self.next_event(events, "online")
        link.send({"verb": "lock", "message": ""})
        self.assertTrue(self.next_event(events, "done", verb="lock")["ok"])
        self.agent.stop()
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, fc.RELEASE_FILE)))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, fc.PANEL_FILE)))

    def test_another_teacher_is_refused(self):
        self.paired_link()
        stranger_home = os.path.join(self.tmp, "stranger")
        os.environ["XDG_DATA_HOME"] = stranger_home
        stranger = fc.identity(fc.TEACHER_DIR)
        events = queue.Queue()
        student = {"id": self.student.id, "name": "x", "pem": self.student.pem}
        link = fc.Link(stranger, student, lambda _i: ("127.0.0.1", self.agent.port), lambda *e: events.put(e[1:]))
        link.start()
        self.addCleanup(link.stop)
        self.next_event(events, "offline")

    def test_another_student_is_refused(self):
        """The console checks the student's certificate against the paired one."""
        link, events = self.paired_link()
        self.next_event(events, "online")
        link.stop()
        events = queue.Queue()
        other = {"id": "student-x", "name": "x", "pem": self.teacher.pem}    # not the student's certificate
        link = fc.Link(self.teacher, other, lambda _i: ("127.0.0.1", self.agent.port), lambda *e: events.put(e[1:]))
        link.start()
        self.addCleanup(link.stop)
        self.assertIn("another computer", self.next_event(events, "offline"))


class TeachersTest(Base):
    """ADR-016: several teachers on one computer, one connected at a time; a
    second takes over unless the first is busy (Q14)."""

    def setUp(self):
        super().setUp()
        self.run_dir = os.path.join(os.environ["XDG_RUNTIME_DIR"], "flickos", "classroom")
        os.makedirs(self.run_dir, mode=0o700)
        saved = fc.RETRY_SECONDS
        self.addCleanup(lambda: setattr(fc, "RETRY_SECONDS", saved))
        fc.RETRY_SECONDS = 0.2
        self.student = fc.identity(fc.STUDENT_DIR)
        self.cruz = fc.identity(fc.TEACHER_DIR)
        self.lee = fc.identity("teacher", os.path.join(self.tmp, "lee"))
        self.agent = self.start_agent()

    def start_agent(self):
        agent = fc.Agent(self.student, self.run_dir, port=0, mdns=False, host="127.0.0.1")
        agent.start()
        self.addCleanup(agent.stop)
        return agent

    def pair(self, teacher, name, code):
        thread = threading.Thread(target=lambda: self.agent.start_pairing(code))
        thread.start()
        self.wait_for(self.agent.pairing_open)
        result = fc.pair_student(teacher, name, code, "127.0.0.1", self.agent.port)
        thread.join(10)
        self.assertIsNotNone(result)
        return {"id": result[0], "name": result[1], "pem": result[2]}

    def link(self, teacher, student):
        events = queue.Queue()
        link = fc.Link(teacher, student, lambda _i: ("127.0.0.1", self.agent.port), lambda *e: events.put(e[1:]))
        link.start()
        self.addCleanup(link.stop)
        return link, events

    def next_event(self, events, kind, seconds=10, verb=None):
        return NetworkTest.next_event(self, events, kind, seconds, verb)

    def both(self):
        student = self.pair(self.cruz, "Ms Cruz", "111111")
        self.pair(self.lee, "Mr Lee", "222222")
        return student

    def test_both_kept_and_trusted(self):
        student = self.both()
        self.assertEqual(sorted(t["name"] for t in self.agent.teachers), ["Mr Lee", "Ms Cruz"])
        folder = os.path.join(self.student.folder, fc.TEACHERS_DIR)
        self.assertEqual(sorted(os.listdir(folder)), sorted(f"{fc.fingerprint(t.der)}.{ext}"
                                                           for t in (self.cruz, self.lee) for ext in ("json", "pem")))
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o700)
        _link, events = self.link(self.lee, student)
        self.next_event(events, "online")
        self.assertEqual(self.agent.session.teacher["name"], "Mr Lee")

    def test_the_second_takes_over(self):
        student = self.both()
        cruz, cruz_events = self.link(self.cruz, student)
        self.next_event(cruz_events, "online")
        lee, lee_events = self.link(self.lee, student)
        self.next_event(lee_events, "online")
        self.assertEqual(self.next_event(cruz_events, "taken-over"), "Mr Lee")
        self.wait_for(lambda: cruz.paused and not cruz.channel)
        self.assertEqual(self.agent.session.teacher["name"], "Mr Lee")
        time.sleep(0.6)                                  # three retries' time: Ms Cruz's console stays away
        self.assertEqual(self.agent.session.teacher["name"], "Mr Lee")
        link_message = {"verb": "message", "text": "Hello from Mr Lee", "seconds": 10}
        lee.send(link_message)
        self.assertTrue(self.next_event(lee_events, "done", verb="message")["ok"])
        self.wait_for(lambda: any("From Mr Lee Hello from Mr Lee" in line for line in self.logged()))
        cruz.resume()                                    # Ms Cruz clicked the tile
        self.next_event(cruz_events, "online")
        self.assertEqual(self.next_event(lee_events, "taken-over"), "Ms Cruz")

    def test_busy_while_the_other_locked(self):
        student = self.both()
        cruz, cruz_events = self.link(self.cruz, student)
        self.next_event(cruz_events, "online")
        cruz.send({"verb": "lock", "message": "Eyes up"})
        self.assertTrue(self.next_event(cruz_events, "done", verb="lock")["ok"])
        _lee, lee_events = self.link(self.lee, student)
        self.assertEqual(self.next_event(lee_events, "busy"), "Ms Cruz")
        self.assertEqual(self.agent.session.teacher["name"], "Ms Cruz")
        with open(os.path.join(self.run_dir, fc.PANEL_FILE)) as f:
            self.assertEqual(json.load(f)["tooltip"], "Ms Cruz locked this screen for the class")
        cruz.send({"verb": "unlock"})
        self.assertTrue(self.next_event(cruz_events, "done", verb="unlock")["ok"])
        self.next_event(lee_events, "online")            # free again: Mr Lee's console gets in
        self.assertEqual(self.next_event(cruz_events, "taken-over"), "Mr Lee")

    def test_view_only_for_the_connected_teacher(self):
        self.vnc_fakes()
        student = self.both()
        _cruz, cruz_events = self.link(self.cruz, student)
        self.next_event(cruz_events, "online")
        with self.assertRaisesRegex(fc.ClassroomError, "Ms Cruz is connected to it"):
            fc.open_screen(self.lee, student, "127.0.0.1", self.agent.port, control=False)
        tls, extra = fc.open_screen(self.cruz, student, "127.0.0.1", self.agent.port, control=False)
        self.greeted(tls, extra)
        self.assertIn("strip --text Ms Cruz is viewing this screen --stop", self.logged())
        tls.close()
        self.wait_for(lambda: self.agent.vnc is None)

    def test_forget_one(self):
        student = self.both()
        lee = fc.fingerprint(self.lee.der)
        with self.assertRaises(fc.ClassroomError):
            fc.forget_teachers(self.student.folder, "zz")              # no such fingerprint
        self.assertEqual(fc.forget_teachers(self.student.folder, lee[:12]), ["Mr Lee"])
        self.agent.reload_teachers()
        self.assertEqual([t["name"] for t in self.agent.teachers], ["Ms Cruz"])
        _lee, lee_events = self.link(self.lee, student)
        self.next_event(lee_events, "offline")                          # refused at the handshake
        _cruz, cruz_events = self.link(self.cruz, student)
        self.next_event(cruz_events, "online")

    def test_privacy_names_what_is_sent(self):
        """PRIVACY.md names every verb, every discovery field and every field
        of the hello a teacher's computer gets."""
        with open(os.path.join(PACKAGE, "PRIVACY.md"), encoding="utf-8") as f:
            text = f.read()
        student = self.both()
        _link, events = self.link(self.cruz, student)
        hello = self.next_event(events, "online")
        fields = {*fc.VERBS, *self.agent.mdns_fields(), "id", "port", *hello} - {"hello", "ping", "type"}
        for field in sorted(fields):
            with self.subTest(field=field):
                self.assertIn(f"`{field}`", text)

    def test_at_most_sixteen(self):
        saved = fc.MAX_TEACHERS
        self.addCleanup(lambda: setattr(fc, "MAX_TEACHERS", saved))
        fc.MAX_TEACHERS = 1
        self.pair(self.cruz, "Ms Cruz", "111111")
        self.assertEqual(self.agent.start_pairing("222222"), ("failed", fc.TEACHERS_FULL))

    def test_the_one_teacher_of_before_moves(self):
        """1.0~test8 kept one teacher.pem; the agent moves it to teachers/."""
        self.agent.stop()
        with open(os.path.join(self.student.folder, "teacher.pem"), "w") as f:
            f.write(self.cruz.pem)
        with open(os.path.join(self.student.folder, "teacher.json"), "w") as f:
            json.dump({"name": "Ms Cruz", "since": "2026-11-17T10:00:00"}, f)
        self.assertEqual([t["name"] for t in fc.load_teachers(self.student.folder)], ["Ms Cruz"])
        agent = self.start_agent()
        self.assertFalse(os.path.exists(os.path.join(self.student.folder, "teacher.pem")))
        self.assertEqual([(t["name"], t["since"]) for t in agent.teachers], [("Ms Cruz", "2026-11-17T10:00:00")])

    def test_notice_again_where_it_changed(self):
        """Q15: a lab computer shows the changed LAB_NOTICE once more; a
        student's own computer, whose notice didn't change, doesn't."""
        noticed = os.path.join(self.tmp, "noticed")
        shown = lambda: sum("notify-send" in line for line in self.logged())
        fc.show_notice(noticed, lab=False)
        self.wait_for(lambda: shown() == 1)
        fc.show_notice(noticed, lab=False)
        with open(noticed, "w") as f:
            f.write("2026-11-17T09:00:00\n")                # written by 1.0~test8
        fc.show_notice(noticed, lab=False)
        fc.show_notice(noticed, lab=True)
        self.wait_for(lambda: shown() == 2)
        fc.show_notice(noticed, lab=True)
        time.sleep(0.3)
        self.assertEqual(shown(), 2)
        self.assertIn("This is a school lab computer", "".join(self.logged()))


class ClassesTest(Base):
    """ADR-017: classes kept beside students.json, attendance only when asked."""

    def test_classes(self):
        folder = os.path.join(self.tmp, "teacher")
        os.makedirs(folder)
        classes = fc.Classes(folder)
        self.assertEqual((classes.names(), classes.current), ([], None))
        self.assertEqual(classes.create("  7A Maths ", ["s1", "s2"]), "7A Maths")
        classes.create("8B Science")
        with self.assertRaisesRegex(fc.ClassroomError, "already"):
            classes.create("7A Maths")
        with self.assertRaisesRegex(fc.ClassroomError, "needs a name"):
            classes.create("\t")
        classes.choose("7A Maths")
        classes.put("8B Science", ["s2", "s3"])
        classes.take("7A Maths", ["s1"])
        classes.rename("7A Maths", "7A Algebra")
        again = fc.Classes(folder)                       # kept, with the class shown
        self.assertEqual(again.names(), ["7A Algebra", "8B Science"])
        self.assertEqual(again.current, "7A Algebra")
        self.assertEqual(again.members("8B Science"), {"s2", "s3"})
        again.forget_student("s2")
        self.assertEqual((again.members("7A Algebra"), again.members("8B Science")), (set(), {"s3"}))
        again.delete("7A Algebra")
        self.assertIsNone(fc.Classes(folder).current)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(folder, "classes.json")).st_mode), 0o600)
        with open(os.path.join(folder, "classes.json"), "w") as f:
            f.write("[not a dict")
        self.assertEqual(fc.Classes(folder).names(), [])  # a broken file is an empty one

    def test_attendance(self):
        rows = [("Ben", "", False), ("lab-07", "Ana Cruz", True), ("Cara", "", True)]
        text, table = fc.attendance("7A Maths", rows, 1795000000)
        self.assertIn(": 2 of 3 here", text.splitlines()[0])
        self.assertTrue(text.splitlines()[0].startswith("7A Maths, "))
        here = text.split("Here:\n", 1)[1].split("\n\n", 1)[0].splitlines()
        self.assertEqual(here, ["Cara", "lab-07 (Ana Cruz)"])
        self.assertEqual(text.split("Absent:\n", 1)[1].splitlines(), ["Ben"])
        lines = table.splitlines()
        self.assertEqual(lines[0], "Name,Account,Status,Class,Time")
        self.assertEqual(lines[1].split(",")[:4], ["Cara", "", "here", "7A Maths"])
        self.assertEqual(lines[3].split(",")[:3], ["Ben", "", "absent"])
        nobody = fc.attendance("X", [("Ben", "", False)], 0)[0]
        self.assertIn("Here:\nnobody\n", nobody)

    def test_fingerprint_to_read(self):
        self.assertEqual(fc.grouped("ab" * 32, groups=3), "AB:AB:AB")


class LabTest(Base):
    """A lab computer (ADR-011): the administrator's commands, and the
    service passing a teacher's session to the seat's agent."""

    def setUp(self):
        super().setUp()
        self.root = unittest.mock.patch.object(fc.os, "geteuid", return_value=0)

    def lab_on(self):
        with self.root:
            self.assertEqual(self.quiet("lab", "on"), 0)

    def quiet(self, *args):
        with open(os.devnull, "w") as null:
            old, sys.stderr, sys.stdout = (sys.stderr, sys.stdout), null, null
            try:
                return fc.main(list(args))
            finally:
                sys.stderr, sys.stdout = old

    def test_notice_says_what_is_true(self):
        """The first-run notice: a lab computer's student can't turn it off."""
        self.assertIn("at any time", fc.NOTICE)
        self.assertNotIn("turn", fc.LAB_NOTICE.lower().replace("turns red", ""))
        self.assertIn("the name of the account logged in", fc.LAB_NOTICE)      # Q15
        with open(_loader.path, encoding="utf-8") as f:
            self.assertIn("LAB_NOTICE if lab else NOTICE", f.read())

    def test_only_root(self):
        self.assertEqual(self.quiet("lab", "on"), 1)
        self.assertFalse(fc.lab_mode())

    def test_on_and_off(self):
        self.lab_on()
        self.assertTrue(fc.lab_mode())
        self.assertIn(f"systemctl enable --now {fc.LAB_SERVICE}", self.logged())
        key = os.path.join(fc.LAB_DIR, "key.pem")
        self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(fc.LAB_DIR).st_mode), 0o755)
        # Every account shares, and can't change it or pair on its own.
        fc.save_setting("sharing", "off")
        self.assertEqual(fc.load_settings()["sharing"], "on")
        for args in (["student", "off"], ["student", "on"], ["student", "forget"],
                     ["student", "pair", "--code", "123456"]):
            self.assertEqual(self.quiet(*args), 1, args)
        with self.root:
            self.assertEqual(self.quiet("lab", "off"), 0)
        self.assertFalse(fc.lab_mode())
        self.assertIn(f"systemctl disable --now {fc.LAB_SERVICE}", self.logged())
        self.assertEqual(fc.load_settings()["sharing"], "off")      # the user's own choice again

    def test_service_only_in_lab_mode(self):
        with self.root:
            self.assertEqual(fc.main(["lab", "run"]), 0)             # not a lab computer: exits at once

    def start_lab(self):
        """The service on 127.0.0.1, the seat's agent, a paired console."""
        self.lab_on()
        os.makedirs(fc.LAB_RUN)
        service = fc.Agent(fc.identity("lab", fc.LAB_DIR), fc.LAB_RUN, port=0, mdns=False, host="127.0.0.1",
                           mode="lab-service")
        service.start()
        self.addCleanup(service.stop)
        teacher = fc.identity(fc.TEACHER_DIR)
        thread = threading.Thread(target=lambda: service.start_pairing("246810"))
        thread.start()
        self.wait_for(service.pairing_open)
        ident, name, pem = fc.pair_student(teacher, "Ms Cruz", "246810", "127.0.0.1", service.port)
        thread.join(10)
        self.assertEqual(ident, service.me.id)
        self.assertEqual([t["name"] for t in fc.lab_teachers()], ["Ms Cruz"])
        kept = os.path.join(fc.LAB_DIR, fc.TEACHERS_DIR, fc.fingerprint(teacher.der) + ".json")
        self.assertEqual(stat.S_IMODE(os.stat(kept).st_mode), 0o644)      # every account shows its name
        events = queue.Queue()
        link = fc.Link(teacher, {"id": ident, "name": name, "pem": pem},
                       lambda _i: ("127.0.0.1", service.port), lambda *e: events.put(e[1:]))
        return service, link, events

    def user_agent(self):
        uid = os.getuid()
        with open(fc.SEAT_FILE, "w") as f:
            f.write(f"IS_SEAT0=1\nACTIVE=3\nACTIVE_UID={uid}\n")
        run_dir = os.path.join(fc.USER_RUNTIME.format(uid=uid), "flickos", "classroom")
        os.makedirs(run_dir)
        fc.LAB_PEERS = (uid,)                   # the test is the "service"; really root only
        agent = fc.Agent(None, run_dir, mode="lab-user")
        agent.start()
        self.addCleanup(agent.stop)
        return agent, run_dir

    def test_session_through_the_service(self):
        service, link, events = self.start_lab()
        agent, run_dir = self.user_agent()
        link.start()
        self.addCleanup(link.stop)
        self.assertEqual(NetworkTest.next_event(self, events, "online")["type"], "hello")
        self.assertTrue(NetworkTest.next_event(self, events, "frame").startswith(b"\xff\xd8"))
        link.send({"verb": "message", "text": "Lab time", "seconds": 10})
        self.assertTrue(NetworkTest.next_event(self, events, "done", verb="message")["ok"])
        self.wait_for(lambda: any("From Ms Cruz Lab time" in line for line in self.logged()))
        with open(os.path.join(run_dir, fc.PANEL_FILE)) as f:
            panel = json.load(f)
        self.assertEqual(panel["alt"], "looking")
        self.assertIn("Ms Cruz", panel["tooltip"])

    def test_lab_view_and_control_through_the_service(self):
        """Q10: on a lab computer the student can stop control, not a view."""
        self.vnc_fakes()
        service, link, events = self.start_lab()
        agent, run_dir = self.user_agent()
        link.start()
        self.addCleanup(link.stop)
        NetworkTest.next_event(self, events, "online")
        tls, extra = fc.open_screen(link.me, link.student, "127.0.0.1", service.port, control=False)
        self.greeted(tls, extra)
        self.assertEqual(agent.state(), "viewed")
        self.assertIn("strip --text Ms Cruz is viewing this screen", self.logged())   # no --stop
        tls.close()
        self.wait_for(lambda: agent.vnc is None)
        tls, extra = fc.open_screen(link.me, link.student, "127.0.0.1", service.port, control=True)
        self.greeted(tls, extra)
        self.assertIn("strip --text Ms Cruz is controlling this computer --stop", self.logged())
        tls.close()
        self.wait_for(lambda: agent.vnc is None)

    def test_two_teachers_through_the_service(self):
        """ADR-016 on a lab computer: the service says which teacher it passes
        on, and `lab forget FP` ends that teacher's connection at once."""
        self.vnc_fakes()
        service, _link, _events = self.start_lab()                # Ms Cruz
        lee = fc.identity("teacher", os.path.join(self.tmp, "lee"))
        thread = threading.Thread(target=lambda: service.start_pairing("135790"))
        thread.start()
        self.wait_for(service.pairing_open)
        ident, name, pem = fc.pair_student(lee, "Mr Lee", "135790", "127.0.0.1", service.port)
        thread.join(10)
        self.assertEqual(sorted(t["name"] for t in fc.lab_teachers()), ["Mr Lee", "Ms Cruz"])
        agent, run_dir = self.user_agent()
        self.assertEqual(len(agent.teachers), 2)                   # the session's agent reads the names
        events = queue.Queue()
        student = {"id": ident, "name": name, "pem": pem}
        link = fc.Link(lee, student, lambda _i: ("127.0.0.1", service.port), lambda *e: events.put(e[1:]))
        link.start()
        self.addCleanup(link.stop)
        NetworkTest.next_event(self, events, "online")
        self.assertEqual(agent.session.teacher["name"], "Mr Lee")
        tls, extra = fc.open_screen(lee, student, "127.0.0.1", service.port, control=False)
        self.greeted(tls, extra)
        self.assertIn("strip --text Mr Lee is viewing this screen", self.logged())
        tls.close()
        self.wait_for(lambda: agent.vnc is None)
        with self.root:
            self.assertEqual(self.quiet("lab", "forget", fc.fingerprint(lee.der)[:12]), 0)
        self.assertEqual([t["name"] for t in fc.lab_teachers()], ["Ms Cruz"])
        NetworkTest.next_event(self, events, "offline")           # cut, and refused from now on
        self.wait_for(lambda: agent.session is None)

    def test_nobody_at_the_screen(self):
        _service, link, events = self.start_lab()
        link.start()
        self.addCleanup(link.stop)
        self.assertEqual(NetworkTest.next_event(self, events, "absent"), "nobody")

    def test_login_screen_is_nobody(self):
        """After a logout the seat is the login screen's (found in the VMs):
        its system user has no agent, and the teacher should read why."""
        _service, link, events = self.start_lab()
        os.makedirs(fc.SESSIONS_DIR)
        with open(fc.SEAT_FILE, "w") as f:
            f.write("ACTIVE=5\nACTIVE_UID=101\n")
        with open(os.path.join(fc.SESSIONS_DIR, "5"), "w") as f:
            f.write("UID=101\nUSER=_greetd\nCLASS=greeter\n")
        self.assertIsNone(fc.seat_uid())
        link.start()
        self.addCleanup(link.stop)
        self.assertEqual(NetworkTest.next_event(self, events, "absent"), "nobody")
        with open(os.path.join(fc.SESSIONS_DIR, "5"), "w") as f:
            f.write("UID=1000\nCLASS=user\n")
        self.assertEqual(fc.seat_uid(), 101)

    def test_agent_not_running(self):
        _service, link, events = self.start_lab()
        with open(fc.SEAT_FILE, "w") as f:
            f.write(f"ACTIVE_UID={os.getuid()}\n")
        link.start()
        self.addCleanup(link.stop)
        self.assertEqual(NetworkTest.next_event(self, events, "absent"), "not running")

    def test_only_root_reaches_the_seats_agent(self):
        agent, run_dir = self.user_agent()
        fc.LAB_PEERS = (0,)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        sock.connect(os.path.join(run_dir, fc.LAB_SOCKET))
        sock.settimeout(5)
        sock.sendall(b'{"verb":"hello"}\n')
        try:
            answer = sock.recv(100)
        except ConnectionResetError:            # closed with our line unread
            answer = b""
        self.assertEqual(answer, b"")           # closed without an answer

    def test_forget(self):
        service, _link, _events = self.start_lab()
        with self.root:
            self.assertEqual(self.quiet("lab", "forget"), 0)
        self.assertEqual(fc.lab_teachers(), [])
        self.assertEqual(service.teachers, [])


class UpgradeTest(Base):
    """An upgrade replaces the program: a session's agent starts again on the
    new one (a lab computer's agent kept test2's protocol after an upgrade to
    test3 and closed every View), but never in the middle of a class lock or
    a view; and it ends with its desktop."""

    def setUp(self):
        super().setUp()
        saved = (fc.PROGRAM, fc.PROGRAM_CHECK_SECONDS)
        self.addCleanup(lambda: setattr(fc, "PROGRAM", saved[0]) or setattr(fc, "PROGRAM_CHECK_SECONDS", saved[1]))
        fc.PROGRAM = os.path.join(self.tmp, "flickos-classroom-view")
        with open(fc.PROGRAM, "w") as f:
            f.write("old\n")
        fc.PROGRAM_CHECK_SECONDS = 0.05
        run_dir = os.path.join(os.environ["XDG_RUNTIME_DIR"], "flickos", "classroom")
        os.makedirs(run_dir, mode=0o700)
        self.agent = fc.Agent(fc.identity(fc.STUDENT_DIR), run_dir, port=0, mdns=False, host="127.0.0.1")
        self.agent.start()
        self.addCleanup(self.agent.stop)

    def upgrade(self):
        """As dpkg does: a new file renamed over the old one."""
        with open(fc.PROGRAM + ".dpkg-new", "w") as f:
            f.write("new\n")
        os.replace(fc.PROGRAM + ".dpkg-new", fc.PROGRAM)

    def test_unchanged_runs_on(self):
        time.sleep(0.3)
        self.assertFalse(self.agent.stopping.is_set())

    def test_upgraded_starts_again(self):
        self.upgrade()
        self.wait_for(self.agent.stopping.is_set)
        self.assertTrue(self.agent.restart)

    def test_ends_with_its_desktop(self):
        """A logout leaves the agent running (Debian keeps a user's
        processes); it stops when its labwc is gone, and doesn't start again."""
        self.agent.stop()
        labwc = os.path.join(self.proc, "4242")
        os.makedirs(labwc)
        with open(os.path.join(labwc, "comm"), "w") as f:
            f.write("labwc\n")
        with unittest.mock.patch.dict(os.environ, {"LABWC_PID": "4242"}):
            agent = fc.Agent(fc.identity(fc.STUDENT_DIR), self.agent.run_dir, port=0, mdns=False, host="127.0.0.1")
            agent.start()
        self.addCleanup(agent.stop)
        time.sleep(0.3)
        self.assertFalse(agent.stopping.is_set())
        with open(os.path.join(labwc, "comm"), "w") as f:
            f.write("bash\n")                # the number taken by another program
        self.wait_for(agent.stopping.is_set)
        self.assertFalse(agent.restart)

    def test_no_labwc_known_runs_on(self):
        self.assertTrue(fc.desktop_running(""))
        self.assertFalse(fc.desktop_running("999999"))

    def test_waits_for_the_class_lock(self):
        with self.agent.lock:
            self.agent.locked = True
        self.upgrade()
        time.sleep(0.3)
        self.assertFalse(self.agent.stopping.is_set())
        with self.agent.lock:
            self.agent.locked = False
        self.wait_for(self.agent.stopping.is_set)
        self.assertTrue(self.agent.restart)


class PackagingTest(unittest.TestCase):
    def test_students_get_no_teachers_window(self):
        """A student's computer has no Classroom in its menu and no gtk-vnc:
        flickos-classroom-teacher brings both, and the program itself."""
        def read(name):
            with open(os.path.join(PACKAGE, "debian", name), encoding="utf-8") as f:
                return f.read()
        control = read("control")
        stanzas = {}
        for stanza in control.split("\n\n"):
            lines = [l for l in stanza.splitlines() if not l.startswith("#")]
            name = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("Package:")), None)
            if name:
                stanzas[name] = "\n".join(lines)
        self.assertEqual(set(stanzas), {"flickos-classroom-view", "flickos-classroom-teacher"})
        self.assertNotIn("gtk-vnc", stanzas["flickos-classroom-view"])
        self.assertIn("gir1.2-gtk-vnc-2.0", stanzas["flickos-classroom-teacher"])
        self.assertIn("flickos-classroom-view (= ${binary:Version})", stanzas["flickos-classroom-teacher"])
        self.assertNotIn("applications", read("flickos-classroom-view.install"))
        self.assertIn("flickos-classroom-teacher.desktop", read("flickos-classroom-teacher.install"))

    def test_lab_service_comes_back_after_an_upgrade(self):
        """dh_installsystemd --no-start stops the service in the preinst of
        every upgrade and starts it nowhere: a lab computer went unreachable
        after updating to 1.0~test3. --no-enable alone starts nothing on a
        computer that isn't a lab (deb-systemd-invoke starts enabled units only)."""
        with open(os.path.join(PACKAGE, "debian", "rules"), encoding="utf-8") as f:
            line = next(l for l in f if l.lstrip().startswith("dh_installsystemd"))
        self.assertIn("--no-enable", line)
        self.assertNotIn("--no-start", line)
        self.assertNotIn("--no-restart-after-upgrade", line)


class StudentsTest(Base):
    def test_store(self):
        folder = os.path.join(self.tmp, "t")
        os.makedirs(folder)
        students = fc.Students(folder)
        students.add("student-2", "Ben", "PEM2")
        students.add("student-1", "ana", "PEM1")
        students.add("student-2", "Ben Reyes", "PEM2b")
        again = fc.Students(folder)
        self.assertEqual([s["name"] for s in again.items], ["ana", "Ben Reyes"])
        again.forget("student-1")
        self.assertEqual([s["id"] for s in fc.Students(folder).items], ["student-2"])
        self.assertEqual(stat.S_IMODE(os.stat(students.path).st_mode), 0o600)

    def test_broken_file(self):
        folder = os.path.join(self.tmp, "t")
        os.makedirs(folder)
        with open(os.path.join(folder, "students.json"), "w") as f:
            f.write('[{"id": 1}, "x", {"id": "s", "name": "n", "pem": "p"}')
        self.assertEqual(fc.Students(folder).items, [])


class PanelSignalTest(Base):
    def test_only_a_waybar_that_catches_it(self):
        """A waybar without the button would die of the signal: never sent to it."""
        for pid, cgt in (("1001", "0"), ("1002", hex(1 << (fc.signal.SIGRTMIN + fc.PANEL_SIGNAL - 1))[2:])):
            folder = os.path.join(self.proc, pid)
            os.makedirs(folder)
            with open(os.path.join(folder, "comm"), "w") as f:
                f.write("waybar\n")
            with open(os.path.join(folder, "status"), "w") as f:
                f.write(f"Name:\twaybar\nSigCgt:\t{cgt}\n")
        sent = []
        real = fc.os.kill
        fc.os.kill = lambda pid, sig: sent.append((pid, sig))
        try:
            fc.signal_panel()
        finally:
            fc.os.kill = real
        self.assertEqual(sent, [(1002, fc.signal.SIGRTMIN + fc.PANEL_SIGNAL)])


if __name__ == "__main__":
    unittest.main()
