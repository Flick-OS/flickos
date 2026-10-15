"""Tests for usr/bin/flickos-phone. Run: python3 -m unittest discover -s tests

Nothing here touches the build host: every XDG folder, the system config,
/proc and the firewall's config are temporary, NetworkManager, notifications
and the clipboard are faked, and the phone is a fake one on 127.0.0.1 with a
free port (never 1716, never a broadcast).
"""

import base64
import contextlib
import dataclasses
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_phone", os.path.join(PACKAGE, "usr/bin/flickos-phone"))
fp = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fp)

_ROOT = tempfile.TemporaryDirectory(prefix="flickos-phone-test-")
fp.SYSTEM_CONF = os.path.join(_ROOT.name, "phone.conf")
fp.HISTORY_CONF = os.path.join(_ROOT.name, "history.conf")
fp.UFW_CONF = os.path.join(_ROOT.name, "ufw.conf")
fp.MACHINE_INFO = os.path.join(_ROOT.name, "machine-info")
fp.DMI_CHASSIS = os.path.join(_ROOT.name, "chassis_type")
fp.PROC = os.path.join(_ROOT.name, "proc")
fp.OPEN_SCHEMES = os.path.join(_ROOT.name, "open-schemes")
os.makedirs(fp.PROC)
with open(os.path.join(fp.PROC, "cmdline"), "w") as _f:
    _f.write("BOOT_IMAGE=/vmlinuz quiet\n")
for _name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
    os.environ[_name] = os.path.join(_ROOT.name, _name.lower())
    os.makedirs(os.environ[_name], exist_ok=True)
os.environ.pop("WAYLAND_DISPLAY", None)
# Nothing shows on the build host's screen or clipboard, and nothing starts.
_REAL_NOTIFY = fp.notify       # its argv test runs it with subprocess.run mocked
fp.notify = lambda *args, **kwargs: None
fp.copy_text = lambda text: None
fp.spawn = lambda argv: None
fp.choose_files = lambda: []
# Never signal the build host's waybar or regenerate its panel.
fp.signal_panel = lambda: None
fp.reload_panel = lambda: None


def make_cert(folder, device_id):
    key, cert = os.path.join(folder, device_id + ".key"), os.path.join(folder, device_id + ".pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                    "-noenc", "-keyout", key, "-out", cert, "-days", "10",
                    "-subj", f"/O=KDE/OU=KDE Connect/CN={device_id}"], check=True, capture_output=True)
    with open(cert) as f:
        der = ssl.PEM_cert_to_DER_cert(f.read())
    return cert, key, der


def openssl_spki(cert):
    pub = subprocess.run(["openssl", "x509", "-in", cert, "-pubkey", "-noout"], check=True,
                         capture_output=True).stdout
    return subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"], input=pub, check=True,
                          capture_output=True).stdout


class Isolated(unittest.TestCase):
    """Fresh settings, data, state and history for each test."""

    def setUp(self):
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            shutil.rmtree(os.environ[name], ignore_errors=True)
            os.makedirs(os.environ[name])
        for path in (fp.SYSTEM_CONF, fp.HISTORY_CONF, fp.UFW_CONF, fp.MACHINE_INFO, fp.DMI_CHASSIS):
            if os.path.exists(path):
                os.unlink(path)

    def history(self):
        path = os.path.join(os.environ["XDG_STATE_HOME"], "flickos", "history.jsonl")
        try:
            with open(path) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []


class CertificateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="flickos-phone-certs-")
        cls.a_id, cls.b_id = uuid.uuid4().hex, uuid.uuid4().hex
        cls.a = make_cert(cls.tmp, cls.a_id)
        cls.b = make_cert(cls.tmp, cls.b_id)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_fields_match_openssl(self):
        for (cert, _, der), device_id in ((self.a, self.a_id), (self.b, self.b_id)):
            name, spki = fp.cert_fields(der)
            self.assertEqual(name, device_id)
            self.assertEqual(spki, openssl_spki(cert))

    def test_verification_key(self):
        # kdeconnect-kde: sha256(larger key + smaller key + timestamp), 8 hex digits, capitals.
        a, b = openssl_spki(self.a[0]), openssl_spki(self.b[0])
        big, small = max(a, b), min(a, b)
        expected = hashlib.sha256(big + small + b"1790489975").hexdigest()[:8].upper()
        self.assertEqual(fp.verification_key(self.a[2], self.b[2], 1790489975), expected)
        self.assertEqual(fp.verification_key(self.b[2], self.a[2], 1790489975), expected)
        self.assertNotEqual(fp.verification_key(self.a[2], self.b[2], 1790489976), expected)
        self.assertRegex(expected, r"^[0-9A-F]{8}$")

    def test_host_key_is_the_certificate_key(self):
        """The phone's SSH host key is its certificate's public key. The blob
        and the fingerprint are what OpenSSH itself computes."""
        rsa_id = uuid.uuid4().hex
        rsa_key = os.path.join(self.tmp, rsa_id + ".key")
        rsa_cert = os.path.join(self.tmp, rsa_id + ".pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-noenc", "-keyout", rsa_key,
                        "-out", rsa_cert, "-days", "10", "-subj", f"/CN={rsa_id}"],
                       check=True, capture_output=True)
        with open(rsa_cert) as handle:
            rsa_der = ssl.PEM_cert_to_DER_cert(handle.read())
        for der, kind in ((self.a[2], "ecdsa-sha2-nistp256"), (rsa_der, "ssh-rsa")):
            blob = fp.ssh_public_blob(fp.cert_fields(der)[1])
            path = os.path.join(self.tmp, kind + ".pub")
            with open(path, "w") as handle:
                handle.write(f"{kind} {base64.b64encode(blob).decode()} phone\n")
            shown = subprocess.run(["ssh-keygen", "-l", "-f", path], check=True, capture_output=True, text=True)
            self.assertIn(fp.host_fingerprint(blob), shown.stdout)
            self.assertEqual(fp.parse_keyscan(f"127.0.0.1 {kind} {base64.b64encode(blob).decode()}\n"), [blob])
        self.assertNotEqual(fp.ssh_public_blob(fp.cert_fields(self.a[2])[1]),
                            fp.ssh_public_blob(fp.cert_fields(self.b[2])[1]))
        # A comment and a hashed line are not keys. A different key doesn't match.
        text = "# 127.0.0.1:1740 SSH-2.0-test\n|1|abc ecdsa-sha2-nistp256 AAAA\n"
        self.assertEqual(fp.parse_keyscan(text), [])

    def test_sftp_offer_keeps_only_the_offered_folders(self):
        body = {"port": 1740, "user": "kdeconnect", "password": "once",
                "ip": "10.9.9.9", "path": "/",
                "multiPaths": ["/storage/emulated/0", "/storage/emulated/0/DCIM", "../etc", "relative", "/ok/../no"],
                "pathNames": ["All files"]}
        offer = fp.sftp_offer(body, "127.0.0.1", "phoneid")
        self.assertEqual(offer["host"], "127.0.0.1")
        self.assertEqual([(f["path"], f["name"]) for f in offer["folders"]],
                         [("/storage/emulated/0", "All files"), ("/storage/emulated/0/DCIM", "DCIM")])
        # A JSON string, as an older app sent, and a single path when that's all there is.
        body["multiPaths"] = json.dumps(["/storage/emulated/0"])
        body["pathNames"] = json.dumps(["Internal"])
        self.assertEqual(fp.sftp_offer(body, "::1", "phoneid")["folders"],
                         [{"path": "/storage/emulated/0", "name": "Internal"}])
        self.assertEqual(fp.sftp_uri("::1", 1740, "kdeconnect", "/a b"),
                         "sftp://kdeconnect@[::1]:1740/a%20b")
        self.assertNotIn("once", fp.sftp_uri("127.0.0.1", 1740, "kdeconnect", "/storage/emulated/0"))
        for broken in ({**body, "password": "has\nline"}, {**body, "user": "a b"}, {**body, "port": 0},
                       {**body, "port": True}, {"errorMessage": "Permissions missing: filesystem access"}):
            with self.assertRaises(fp.PhoneError):
                fp.sftp_offer(broken, "127.0.0.1", "phoneid")
        with self.assertRaises(fp.PhoneError) as caught:
            fp.sftp_offer({"errorMessage": "Permissions missing: filesystem access"}, "127.0.0.1", "x")
        self.assertIn("Allow file access", str(caught.exception))
        self.assertNotIn("Permissions missing", str(caught.exception))

    def test_mount_accepts_only_the_paired_fingerprint(self):
        blob = fp.ssh_public_blob(fp.cert_fields(self.a[2])[1])
        fingerprint = fp.host_fingerprint(blob)
        wrong = fp.MountDialogue(fingerprint, "secret")
        reply = wrong.feed('The identity sent by the remote computer is "SHA256:nope".\n'
                           "[1] Log In Anyway\n[2] Cancel Login\nChoice: ")
        self.assertTrue(wrong.failed)
        self.assertEqual(reply, "2\n")
        self.assertNotIn("secret", reply)
        right = fp.MountDialogue(fingerprint, "secret")
        # The prompt can arrive in pieces, and the password only after the key matched.
        self.assertEqual(right.feed("remote computer is \"" + fingerprint[:12]), "")
        self.assertEqual(right.feed(fingerprint[12:] + "\".\nChoice: "), "1\n")
        self.assertEqual(right.feed("Password: "), "secret\n")
        known = fp.MountDialogue(fingerprint, "secret")
        self.assertEqual(known.feed("Password: "), "secret\n")
        self.assertFalse(known.failed)

    def test_garbage_is_not_a_certificate(self):
        for data in (b"", b"\x30", b"\x30\x05abc", b"\x30\x84\xff\xff\xff\xff", self.a[2][:40]):
            with self.assertRaises(fp.ProtocolError):
                fp.cert_fields(data)


class IdentityTest(Isolated):
    def test_made_once_private(self):
        first = fp.ensure_identity()
        self.assertRegex(first.id, r"^[0-9a-f]{32}$")
        self.assertEqual(fp.cert_fields(first.der)[0], first.id)
        self.assertEqual(os.stat(first.key).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(fp.data_dir()).st_mode & 0o777, 0o700)
        self.assertEqual(fp.ensure_identity(), first)

    def test_identity_packet_checks(self):
        good = {"type": "kdeconnect.identity", "body": {"deviceId": "a" * 32, "deviceName": "Pixel (7)!",
                                                       "protocolVersion": 8}}
        self.assertEqual(fp.check_identity(good)["deviceName"], "Pixel 7")
        for change in ({"type": "kdeconnect.ping"}, {"body": {"deviceId": "../x", "protocolVersion": 8}},
                       {"body": {"deviceId": "a" * 32, "protocolVersion": 7}},
                       {"body": {"deviceId": "a" * 32}}):
            bad = dict(good, **change)
            with self.subTest(change=change), self.assertRaises(fp.ProtocolError):
                fp.check_identity(bad)
        unnamed = {"type": "kdeconnect.identity", "body": {"deviceId": "b" * 32, "protocolVersion": 8}}
        self.assertEqual(fp.check_identity(unnamed)["deviceName"], "Phone")

    def test_names(self):
        self.assertEqual(fp.clean_name('Jon\'s "ThinkPad" (x220).'), "Jons ThinkPad x220")
        self.assertEqual(len(fp.clean_name("x" * 50)), 32)
        with open(fp.MACHINE_INFO, "w") as f:
            f.write('PRETTY_HOSTNAME="Jon\'s Laptop"\n')
        self.assertEqual(fp.computer_name(), "Jons Laptop")
        self.assertEqual(fp.device_name(fp.Settings(name="Den")), "Den")
        with open(fp.DMI_CHASSIS, "w") as f:
            f.write("10\n")
        self.assertEqual(fp.device_type(), "laptop")
        with open(fp.DMI_CHASSIS, "w") as f:
            f.write("3\n")
        self.assertEqual(fp.device_type(), "desktop")


class IncomingTest(Isolated):
    def test_icon_cache_keeps_the_newest(self):
        folder = os.path.dirname(fp.icon_cache_path("x"))
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        for n in range(5):
            path = fp.icon_cache_path(f"{n:032x}")
            with open(path, "wb") as f:
                f.write(b"x")
            os.utime(path, (1000 + n, 1000 + n))
        fp.prune_icons(keep=3)
        self.assertEqual(sorted(os.listdir(folder)), [f"{n:032x}" for n in (2, 3, 4)])

        """Someone else's text can't restyle a notification (mako reads the
        body as Pango markup), and text starting with - isn't an option."""
        self.assertEqual(fp.plain_body('<span size="xx-large">Bank</span> & co'),
                         '&lt;span size="xx-large"&gt;Bank&lt;/span&gt; &amp; co')
        runs = []

        class Now:
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()

        with mock.patch.object(fp.threading, "Thread", Now), \
                mock.patch.object(fp.subprocess, "run",
                                  side_effect=lambda argv, **_kw: runs.append(argv) or mock.Mock(stdout="")):
            _REAL_NOTIFY("-t", "<b>hi</b>")
        argv = runs[0]
        self.assertEqual(argv[argv.index("--") + 1:], ["-t", "&lt;b&gt;hi&lt;/b&gt;"])

    def test_addresses(self):
        self.assertEqual(fp.clean_address(" https://a.org/x?a=1&amp;b=2 "), "https://a.org/x?a=1&b=2")
        self.assertTrue(fp.web_address("https://a.org/x"))
        for url in ("file:///etc/passwd", "javascript:alert(1)", "tel:123", "https://", "http//a.org"):
            self.assertFalse(fp.web_address(url), url)
        self.assertEqual(fp.short_address("https://www.howtogeek.com/stop?utm_source=facebook"),
                         "howtogeek.com/stop")
        self.assertLessEqual(len(fp.short_address("https://a.org/" + "x" * 100)), 60)

    def test_file_names(self):
        self.assertEqual(fp.clean_filename("../.evil.txt"), "evil.txt")
        self.assertEqual(fp.clean_filename("..\\..\\win.ini"), "win.ini")
        self.assertEqual(fp.clean_filename("/etc/passwd"), "passwd")
        self.assertEqual(fp.clean_filename("a\nb\x00c.jpg"), "abc.jpg")
        self.assertEqual(fp.clean_filename("..."), "file")
        self.assertEqual(fp.clean_filename(""), "file")
        self.assertLessEqual(len(fp.clean_filename("é" * 300 + ".jpg").encode()), 200)
        self.assertTrue(fp.clean_filename("é" * 300 + ".jpg").endswith(".jpg"))

    def test_free_name_never_overwrites(self):
        folder = tempfile.mkdtemp(dir=_ROOT.name)
        self.assertEqual(fp.free_name(folder, "a.jpg"), os.path.join(folder, "a.jpg"))
        open(os.path.join(folder, "a.jpg"), "w").close()
        open(os.path.join(folder, "a (2).jpg"), "w").close()
        self.assertEqual(fp.free_name(folder, "a.jpg"), os.path.join(folder, "a (3).jpg"))

    def test_openable(self):
        for name in ("a.jpg", "b.pdf", "c.odt", "d.mp4", "e.txt", "f.docx"):
            self.assertTrue(fp.openable(name), name)
        for name in ("run.sh", "app.desktop", "x.exe", "y.py", "noext", "z.jar"):
            self.assertFalse(fp.openable(name), name)

    def test_received_details(self):
        folder = tempfile.mkdtemp(dir=_ROOT.name)
        photo, script = os.path.join(folder, "a.jpg"), os.path.join(folder, "run.sh")
        for path in (photo, script):
            open(path, "w").close()
        details = [fp.received_details({"kind": "file", "value": path})
                   for path in (photo, script, os.path.join(folder, "gone.jpg"))]
        self.assertEqual([(d["exists"], d["openable"]) for d in details], [(True, True), (True, False),
                                                                          (False, False)])
        text = fp.received_details({"kind": "text", "value": '"Linux"\n https://a.org/#:~:text=Linux'})
        self.assertEqual(text["address"], "https://a.org/#:~:text=Linux")
        self.assertEqual(fp.received_details({"kind": "text", "value": "no link"})["address"], "")

    def test_addresses_of_registered_schemes(self):
        """A text that is one address of a scheme a package registered opens
        in that app on a click; anything else stays text to copy."""
        os.makedirs(fp.OPEN_SCHEMES, exist_ok=True)
        self.addCleanup(shutil.rmtree, fp.OPEN_SCHEMES)
        with open(os.path.join(fp.OPEN_SCHEMES, "storyapp"), "w") as f:
            f.write("Story\n")
        with open(os.path.join(fp.OPEN_SCHEMES, "blank"), "w") as f:
            f.write(" \n")
        with open(os.path.join(fp.OPEN_SCHEMES, "file"), "w") as f:
            f.write("Files\n")
        address = "storyapp://return?v=1&d=" + "A" * 1000
        self.assertEqual(fp.app_address(address), ("Story", address))
        self.assertEqual(fp.app_address(f"\n{address} \n"), ("Story", address))
        self.assertEqual(fp.app_address("StoryApp://return?v=1"), ("Story", "StoryApp://return?v=1"))
        for text in (f"see {address}", f"{address} {address}", "flicknotes://continue?v=1", "storyapp:",
                     "blank://x", "file:///etc/passwd", "https://a.org/x", "Story", "",
                     "storyapp://return?d=" + "A" * fp.MAX_ARG_BYTES):
            self.assertIsNone(fp.app_address(text), text[:40])
        details = fp.received_details({"kind": "text", "value": address})
        self.assertEqual(details["app"], "Story")
        self.assertEqual(fp.received_details({"kind": "clipboard", "value": address})["app"], "")
        self.assertEqual(fp.received_details({"kind": "text", "value": "hello"})["app"], "")
        title, _note, actions = fp.received_actions(details)
        self.assertEqual(title, "For Story")
        self.assertEqual(actions[0], ("Open", "Open in Story", ["xdg-open", address]))
        self.assertEqual([action[0] for action in actions], ["Open", "Copy"])
        # The package was removed meanwhile: the window's details say so.
        self.assertEqual(fp.received_actions(dict(details, app=""))[2][0][0], "Copy")
        entries = fp.menu_entries([], [{"kind": "text", "value": address}], control=False)
        self.assertEqual(entries, [("Open in Story", ("run", ["xdg-open", address]))])

    def test_a_registered_address_is_opened_only_on_a_click(self):
        os.makedirs(fp.OPEN_SCHEMES, exist_ok=True)
        self.addCleanup(shutil.rmtree, fp.OPEN_SCHEMES)
        with open(os.path.join(fp.OPEN_SCHEMES, "storyapp"), "w") as f:
            f.write("Story\n")
        address = "storyapp://return?v=1&d=abc"
        daemon, link = mock.Mock(), mock.Mock()
        link.name = "Pixel"         # Mock(name=…) names the mock, not the attribute
        notes = []
        with mock.patch.object(fp, "notify", side_effect=lambda *a: notes.append(a)), \
                mock.patch.object(fp, "spawn") as spawn:
            fp.Daemon.on_share(daemon, link, {"body": {"text": address}})
            daemon.note_received.assert_called_once_with("text", "Pixel", address)
            spawn.assert_not_called()
            title, body, action, on_click = notes[0]
            self.assertEqual((title, body, action), ("For Story from Pixel", "Click to open it in Story.", "Open"))
            on_click()
            spawn.assert_called_once_with(["xdg-open", address])
            fp.Daemon.on_share(daemon, link, {"body": {"text": "hello"}})
            self.assertEqual(notes[1][:3], ("Text from Pixel", "hello", "Copy"))

    def test_received_list_is_short_and_recent(self):
        now = 1_800_000_000
        fp.add_received("page", "Pixel", "https://old.org", now=now - 8 * 86400)
        for n in range(25):
            fp.add_received("text", "Pixel", f"t{n}", now=now + n)
        items = fp.read_received(now=now + 30)
        self.assertEqual(len(items), fp.RECEIVED_ITEMS)
        self.assertEqual(items[-1]["value"], "t24")
        self.assertNotIn("https://old.org", [i["value"] for i in items])
        self.assertEqual(os.stat(fp.received_path()).st_mode & 0o777, 0o600)


class SettingsTest(Isolated):
    def test_defaults_and_system(self):
        self.assertEqual(fp.load_settings(), fp.Settings())
        with open(fp.SYSTEM_CONF, "w") as f:
            f.write("[Phone]\nEnabled=yes\nName=Den PC\n")
        self.assertEqual(fp.load_settings(), fp.Settings(enabled=True, name="Den PC"))

    def test_save_records_and_default(self):
        fp.save_settings(enabled=True)
        fp.save_settings(name="Kitchen")
        fp.save_settings(networks=("n1", "n2"))
        fp.save_settings(name=None)
        self.assertEqual(fp.load_settings(), fp.Settings(enabled=True, networks=("n1", "n2")))
        changes = [(e["owner"], e["key"], e["old"], e["new"]) for e in self.history()]
        self.assertEqual(changes, [("flickos-phone", "enabled", "no", "yes"),
                                   ("flickos-phone", "name", "default", "Kitchen"),
                                   ("flickos-phone", "networks", "", "n1 n2"),
                                   ("flickos-phone", "name", "Kitchen", "default")])
        fp.save_settings(enabled=True)      # no change, no record
        self.assertEqual(len(self.history()), 4)

    def test_history_off(self):
        with open(fp.HISTORY_CONF, "w") as f:
            f.write("[History]\nEnabled=no\n")
        fp.save_settings(enabled=True)
        self.assertEqual(self.history(), [])

    def test_cli_set_and_get(self):
        with mock.patch.object(fp, "request", return_value=None), \
                mock.patch.object(fp, "start_daemon") as start, mock.patch("sys.stdout"), \
                mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["set", "enabled", "yes"]), 0)
            start.assert_called_once()          # nothing answered: start it
            self.assertTrue(fp.load_settings().enabled)
            self.assertTrue(os.path.exists(os.path.join(fp.data_dir(), "cert.pem")))
            fp.add_received("text", "Pixel", "hello")
            self.assertEqual(fp.main(["set", "enabled", "no"]), 0)
            self.assertFalse(os.path.exists(fp.received_path()))
            self.assertEqual(fp.main(["set", "enabled", "maybe"]), 1)

    def test_set_networks(self):
        with mock.patch.object(fp, "request", return_value=None), mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["set", "networks", "a-1 b-2 a-1"]), 0)
            self.assertEqual(fp.load_settings().networks, ("a-1", "b-2"))
            self.assertEqual(fp.main(["set", "networks", ""]), 0)
            self.assertEqual(fp.load_settings().networks, ())
            self.assertEqual(fp.main(["set", "networks", "x;rm"]), 1)
            self.assertEqual(fp.main(["set", "networks", "default"]), 0)
        self.assertEqual([(e["key"], e["old"], e["new"]) for e in self.history()],
                         [("networks", "", "a-1 b-2"), ("networks", "a-1 b-2", "")])

    def test_not_in_the_live_session(self):
        live = os.path.join(_ROOT.name, "live-proc")
        os.makedirs(live, exist_ok=True)
        with open(os.path.join(live, "cmdline"), "w") as f:
            f.write("boot=live quiet\n")
        with mock.patch.object(fp, "PROC", live), mock.patch("sys.stderr"):
            self.assertTrue(fp.live_session())
            self.assertEqual(fp.main(["set", "enabled", "yes"]), 1)
            self.assertEqual(fp.run_daemon(), 0)
        self.assertFalse(fp.load_settings().enabled)

    def test_daemon_does_nothing_while_off(self):
        self.assertEqual(fp.run_daemon(), 0)
        self.assertFalse(os.path.exists(os.path.join(fp.runtime_dir(), "control")))

    def test_networks_from_nmcli(self):
        text = ("ac7fc867-7f5e-46ed-af9e-539f89ba1dc7:802-11-wireless\n"
                "b9391831-3b14-4d80-a5c4-5f13fcc8bdcf:loopback\n"
                "0f1e2d3c-0000-0000-0000-000000000000:802-3-ethernet\n"
                "11111111-0000-0000-0000-000000000000:vpn\n")
        self.assertEqual(fp.parse_active(text), ["ac7fc867-7f5e-46ed-af9e-539f89ba1dc7",
                                                 "0f1e2d3c-0000-0000-0000-000000000000"])

    def test_port_taken(self):
        with socket.socket() as other:
            other.bind(("127.0.0.1", 0))
            other.listen(1)
            self.assertTrue(fp.port_taken(other.getsockname()[1]))
        self.assertFalse(fp.port_taken(0))

    def test_file_manager_action(self):
        """Send to Phone in Thunar is flickos-settings' custom action."""
        import xml.etree.ElementTree as ET
        uca = os.path.join(os.path.dirname(PACKAGE), "flickos-settings/etc/xdg/flickos/Thunar/uca.xml")
        if not os.path.exists(uca):
            self.skipTest("flickos-settings is not next to this package")
        actions = {a.findtext("name"): a for a in ET.parse(uca).getroot()}
        action = actions["Send to Phone"]
        self.assertEqual(action.findtext("command"), "flickos-phone send --notify %F")
        self.assertIsNone(action.find("directories"))       # files only

    def test_on_link_follows_the_daemon(self):
        fp.make_on_link("/usr/bin/flickos-phone")
        path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "flickos", "bin", "flickos-phone-on")
        self.assertEqual(os.readlink(path), "/usr/bin/flickos-phone")
        fp.make_on_link("/usr/bin/flickos-phone")          # again: replaced, not an error
        fp.remove_on_link()
        self.assertFalse(os.path.lexists(path))
        fp.remove_on_link()                                 # already gone
        fp.make_on_link("/usr/bin/flickos-phone")           # left by a daemon that died
        with mock.patch.object(fp, "request", return_value=None), mock.patch("sys.stdout"):
            fp.main(["set", "enabled", "no"])
        self.assertFalse(os.path.lexists(path))

    def test_send_notify(self):
        folder = tempfile.mkdtemp(dir=_ROOT.name)
        photo = os.path.join(folder, "photo.jpg")
        open(photo, "w").close()
        notes = []

        def run(argv, **kwargs):
            notes.append(argv)
            return subprocess.CompletedProcess(argv, 0, "7\n", "")

        with mock.patch.object(fp.subprocess, "run", run), mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            with mock.patch.object(fp, "request", return_value={"ok": True, "name": "Pixel"}):
                self.assertEqual(fp.main(["send", "--notify", photo]), 0)
            with mock.patch.object(fp, "request", return_value=None):
                self.assertEqual(fp.main(["send", "--notify", photo]), 1)
            with mock.patch.object(fp, "request", side_effect=TimeoutError("timed out")):
                self.assertEqual(fp.main(["send", "--notify", photo]), 1)
            # Cancelled in the Phone window: all of it is not sent, some of it is said.
            with mock.patch.object(fp, "request", return_value={"ok": True, "name": "Pixel",
                                                                "cancelled": ["photo.jpg"]}) as asked:
                self.assertEqual(fp.main(["send", "--notify", photo]), 1)
                self.assertIsNone(asked.call_args.kwargs["timeout"])        # a large file takes its time
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    self.assertEqual(fp.main(["send", "--text", "hi", photo]), 0)
                self.assertEqual(out.getvalue(), "Sent to Pixel, except photo.jpg (cancelled).\n")
        titles = [[a for a in argv if not a.startswith("-") and a != "notify-send"] for argv in notes]
        self.assertEqual(titles[:2], [["Sending to your phone…", "photo.jpg"], ["Sent to Pixel", "photo.jpg"]])
        self.assertIn("--replace-id=7", notes[1])
        self.assertEqual(titles[3], ["Not sent to your phone",
                                     "The phone connection is off: turn it on in Settings > Phone."])
        self.assertEqual(titles[5], ["Not sent to your phone", "Timed out."])
        self.assertEqual(titles[7], ["Not sent to your phone", "Cancelled."])
        fp.save_settings(enabled=True)
        self.assertEqual(fp.not_running_reason(), "the phone connection isn't running")
        live = os.path.join(_ROOT.name, "live-proc")
        os.makedirs(live, exist_ok=True)
        with open(os.path.join(live, "cmdline"), "w") as f:
            f.write("boot=live quiet\n")
        with mock.patch.object(fp, "PROC", live):
            self.assertEqual(fp.not_running_reason(), "phones can't connect in the live session")
        self.assertEqual(fp.sent_names([{"kind": "file", "value": f"/a/{n}"} for n in "abcde"]),
                         "a, b, c and 2 more")

    def test_panel_status(self):
        self.assertEqual(fp.panel_status(), {"text": ""})          # off: waybar hides the button
        fp.save_settings(enabled=True)
        with mock.patch.object(fp, "request", return_value=None):
            status = fp.panel_status()
        self.assertEqual((status["alt"], status["class"]), ("waiting", ["waiting"]))
        self.assertIn("isn't running", status["tooltip"])
        connected = {"running": True, "connected": [{"id": "a", "name": "Pixel", "paired": True},
                                                    {"id": "b", "name": "Stranger", "paired": False}]}
        with mock.patch.object(fp, "request", return_value=connected):
            status = fp.panel_status()
        self.assertEqual(status["alt"], "connected")
        self.assertTrue(status["tooltip"].startswith("Connected to Pixel\n"))

    def test_menu_entries(self):
        folder = tempfile.mkdtemp(dir=_ROOT.name)
        photo, script = os.path.join(folder, "a.jpg"), os.path.join(folder, "run.sh")
        for path in (photo, script):
            open(path, "w").close()
        received = [{"kind": "text", "value": "old"}] + [
            {"kind": "page", "value": "https://www.a.org/x?utm=1"},
            {"kind": "file", "value": photo}, {"kind": "file", "value": script},
            {"kind": "file", "value": os.path.join(folder, "gone.jpg")},
            {"kind": "clipboard", "value": "  " + "y" * 80 + "\nsecond line"}]
        entries = fp.menu_entries(["Pixel"], received, control=True)
        labels = [label for label, _ in entries]
        self.assertEqual(labels[:5], ["Send Files to Phone…", "Send Text to Phone…", "Send Clipboard to Phone",
                                      "Send Screenshot to Phone", "Ring My Phone"])
        self.assertNotIn("Browse Phone", labels)
        self.assertEqual(labels[-1], "Phone Settings")
        self.assertEqual(labels[5:-1], ["Copy \u201c" + "y" * 49 + "…\u201d", "Show run.sh in Folder",
                                        "Open a.jpg", "Open a.org/x"])
        self.assertEqual(entries[5][1], ("copy", "  " + "y" * 80 + "\nsecond line"))
        self.assertEqual(entries[6][1], ("run", ["xdg-open", folder]))
        # Without grim, no screenshot entry.
        self.assertNotIn("Send Screenshot to Phone",
                         [label for label, _ in fp.menu_entries(["Pixel"], [], True, screenshot=False)])
        # Not connected: nothing to send to; without flickos-control no settings entry.
        self.assertEqual(fp.menu_entries([], [], control=False), [])
        # Show Phone Screen only with the add-on's command, and only while connected.
        self.assertNotIn("Show Phone Screen", labels)
        entries = fp.menu_entries(["Pixel"], [], False, screen=["flickos-phone-screen", "--to", "a"])
        self.assertEqual(entries[-2], ("Show Phone Screen", ("run", ["flickos-phone-screen", "--to", "a"])))
        # The same add-on's second screen, with the same phone.
        self.assertEqual(entries[-1], ("Use as Second Screen", ("run", [
            "flickos-phone-screen", "second-screen", "on", "--notify", "--to", "a"])))
        self.assertEqual(fp.menu_entries([], [], False, screen=["flickos-phone-screen"]), [])
        # Browse Phone only while the file manager can open a network folder, and only while connected.
        browsed = fp.menu_entries(["Pixel"], [], False, screenshot=False, files=True)
        self.assertEqual(browsed[-1], ("Browse Phone", ("browse",)))
        self.assertNotIn("Browse Phone", [label for label, _ in fp.menu_entries([], [], False, files=True)])

    def test_action_list_is_the_menus_list(self):
        rows = fp.action_list(True, screenshot=True, files=False, screen=None)
        shown = [row["label"] for row in rows if row["shown"]]
        self.assertEqual(shown, ["Send Files to Phone…", "Send Text to Phone…", "Send Clipboard to Phone",
                                 "Send Screenshot to Phone", "Ring My Phone"])
        # The tiles' words, without "to Phone": the window and the popup are the phone's.
        self.assertEqual([row["short"] for row in rows if row["shown"]],
                         ["Send Files…", "Send Text…", "Send Clipboard", "Send Screenshot", "Ring Phone"])
        self.assertTrue(all(row["short"] for row in rows))
        self.assertFalse(next(row for row in rows if row["id"] == "screen")["shown"])
        shot = next(row for row in rows if row["id"] == "screenshot")
        self.assertEqual(shot["icon"], "applets-screenshooter")
        self.assertIn("--notify", shot["command"])
        chosen = fp.action_list(True, device_id="abc", screenshot=False, files=True, screen=["flickos-phone-screen"])
        self.assertEqual(next(row for row in chosen if row["id"] == "files")["command"][-2:], ["--to", "abc"])
        screen = next(row for row in chosen if row["id"] == "screen")
        self.assertEqual(screen["command"], ["flickos-phone-screen", "--to", "abc"])
        self.assertTrue(screen["shown"])
        hidden = fp.action_list(False, screenshot=True, files=True, screen=["flickos-phone-screen"])
        self.assertTrue(rows and not any(row["shown"] for row in hidden))
        # The second screen: one of its two actions, by the add-on's file in the runtime folder.
        def second(**kwargs):
            rows = fp.action_list(True, screen=["flickos-phone-screen"], **kwargs)
            return [(row["id"], row["command"]) for row in rows if row["shown"] and row["id"].startswith("second")]
        self.assertEqual(second(), [("second-screen", ["flickos-phone-screen", "second-screen", "on", "--notify"])])
        self.assertEqual(second(device_id="abc"), [
            ("second-screen", ["flickos-phone-screen", "second-screen", "on", "--notify", "--to", "abc"])])
        marker = os.path.join(os.environ["XDG_RUNTIME_DIR"], fp.SECOND_SCREEN_FILE)
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w"):
            pass
        self.addCleanup(os.unlink, marker)
        self.assertTrue(fp.second_screen_on())
        self.assertEqual(second(device_id="abc"), [
            ("second-screen-stop", ["flickos-phone-screen", "second-screen", "off", "--notify", "--to", "abc"])])
        self.assertEqual(second(second_on=False)[0][0], "second-screen")
        self.assertFalse([row for row in fp.action_list(True, screen=None) if row["id"].startswith("second")
                          and row["shown"]])
        self.assertEqual([row["id"] for row in rows], [action.id for action in fp.ACTIONS])

    def test_phone_line_and_received_actions(self):
        self.assertEqual(fp.phone_line(None), ("No phone paired", "Add one in Phone Settings"))
        self.assertEqual(fp.phone_line({"name": "Pixel", "connected": False}), ("Pixel", "Not connected"))
        self.assertEqual(fp.phone_line({"name": "Pixel", "connected": True, "battery": [80, True]}),
                         ("Pixel", "Connected · 80 %, charging"))
        title, _note, actions = fp.received_actions({"kind": "page", "value": "https://www.a.org/x"})
        self.assertEqual((title, actions[0][0], actions[0][2]), ("a.org/x", "Open", ["xdg-open", "https://www.a.org/x"]))
        title, note, actions = fp.received_actions({"kind": "file", "value": "/tmp/gone.jpg", "exists": False})
        self.assertEqual((title, note, actions), ("gone.jpg", "no longer there", []))
        _title, note, actions = fp.received_actions({"kind": "clipboard", "value": "see https://a.org/x"})
        self.assertEqual(note, "Clipboard")
        self.assertEqual([action[0] for action in actions], ["Copy", "Open"])

    def test_apply_watch(self):
        state = {"phones": [{"id": "a", "name": "Pixel", "connected": False, "battery": None, "paired": "t"}],
                 "received": []}
        fp.apply_watch(state, {"event": "connected", "phone": {"id": "a", "name": "Pixel", "address": "1.2.3.4",
                                                               "battery": [40, False]}})
        self.assertEqual((state["phones"][0]["connected"], state["phones"][0]["battery"]), (True, [40, False]))
        fp.apply_watch(state, {"event": "battery", "id": "a", "battery": [41, True]})
        self.assertEqual(state["phones"][0]["battery"], [41, True])
        fp.apply_watch(state, {"event": "received", "item": {"kind": "text", "value": "hi"}})
        self.assertEqual(state["received"][-1]["value"], "hi")
        fp.apply_watch(state, {"event": "disconnected", "id": "a"})
        self.assertFalse(state["phones"][0]["connected"])
        self.assertIsNone(state["phones"][0]["battery"])
        fp.apply_watch(state, {"event": "forgotten", "id": "a"})
        self.assertEqual(state["phones"], [])
        fp.apply_watch(state, {"event": "connected", "phone": {"id": "b", "name": "Other", "address": "",
                                                               "battery": None}})
        self.assertEqual(state["phones"][0]["id"], "b")
        fp.apply_watch(state, {"event": "call", "id": "b", "state": "ringing", "caller": "Ada"})
        self.assertEqual(state["ringing"], [{"id": "b", "name": "Other", "caller": "Ada"}])
        fp.apply_watch(state, {"event": "call", "id": "b", "state": "ended", "caller": ""})
        self.assertEqual(state["ringing"], [])
        moving = {"event": "transfer", "id": "t", "direction": "out", "name": "a.jpg", "device": "Other",
                  "done": 10, "size": 100, "state": "moving"}
        fp.apply_watch(state, moving)
        fp.apply_watch(state, {**moving, "done": 50})
        self.assertEqual(state["transfers"], [{key: value for key, value in moving.items() if key != "event"}
                                              | {"done": 50}])
        fp.apply_watch(state, {**moving, "state": "cancelled"})
        self.assertEqual(state["transfers"], [])
        fp.apply_watch(state, {"event": "playing", "id": "b", "title": "Song", "artist": "Ada", "playing": True})
        self.assertEqual(state["playing"]["title"], "Song")
        fp.apply_watch(state, {"event": "playing", "id": "b", "title": "", "artist": ""})
        self.assertIsNone(state["playing"])

    def test_actions_command(self):
        with mock.patch.object(fp, "request", return_value={"connected": [
                {"id": "abc", "paired": True, "name": "Pixel"}]}), \
                mock.patch.object(fp.shutil, "which", side_effect=lambda name: "/usr/bin/" + name), \
                mock.patch.object(fp, "files_available", return_value=True), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fp.main(["actions", "--json", "--to", "abc"]), 0)
        rows = json.loads(out.getvalue())
        # Everything but Stop Second Screen, while the second screen is off.
        self.assertEqual([row["id"] for row in rows if not row["shown"]], ["second-screen-stop"])
        self.assertEqual(rows[0]["command"][-2:], ["--to", "abc"])
        out.truncate(0)
        out.seek(0)
        with mock.patch.object(fp, "request", return_value=None), \
                mock.patch.object(fp.shutil, "which", return_value=None), \
                mock.patch.object(fp, "files_available", return_value=False), \
                mock.patch("sys.stdout", out):
            self.assertEqual(fp.main(["actions", "--json"]), 0)
        self.assertTrue(all(row["shown"] is False for row in json.loads(out.getvalue())))

    def test_popup_rows_look_like_the_window(self):
        """flickos-menu's popup keeps copies of the phone's line and the
        received rows' icons (ADR-012: it doesn't import flickos-phone)."""
        path = os.path.join(PACKAGE, "..", "flickos-menu", "usr/share/flickos/menu/phone.py")
        if not os.path.exists(path):
            self.skipTest("flickos-menu isn't next to this package (packages/build.sh builds a copy)")
        loader = importlib.machinery.SourceFileLoader("flickos_menu_phone_test", path)
        popup = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(popup)
        items = [{"kind": "page", "value": "https://a.org/"}, {"kind": "text", "value": "hi"},
                 {"kind": "clipboard", "value": "x"}, {"kind": "file", "value": "/d/a.JPG"},
                 {"kind": "file", "value": "/d/a.mp4"}, {"kind": "file", "value": "/d/blob"}]
        for item in items:
            self.assertEqual(popup.received_icons(item), fp.received_icons(item), item)
        for phone in (None, {"name": "Pixel", "connected": False},
                      {"name": "Pixel", "connected": True, "battery": [55, True]}):
            self.assertEqual(popup.phone_line(phone), fp.phone_line(phone), phone)
        # A registered app's address: the same title and click in both.
        app = {"kind": "text", "value": "storyapp://return?v=1&d=x", "app": "Story"}
        title, _note, actions = fp.received_actions(app)
        entry = popup.received_entry(app)
        self.assertEqual((entry[0], entry[2], entry[3]), (title, actions[0][0], actions[0][2]))

    def test_window_module_does_not_load_gtk(self):
        path = os.path.join(PACKAGE, "usr/share/flickos/phone/window.py")
        before = "gi.repository.Gtk" in sys.modules
        loader = importlib.machinery.SourceFileLoader("flickos_phone_window_test", path)
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        self.assertTrue(callable(module.run))
        self.assertEqual(set(module.BUTTON_MNEMONIC), {action.id for action in fp.ACTIONS})
        # Unique with _Settings and _Phone Settings, ignoring case (GTK does), and the same words.
        self.assertEqual(module.SETTINGS_BUTTON, "_Phone Settings")
        letters = [label[label.index("_") + 1].lower() for label in module.BUTTON_MNEMONIC.values()] + ["s", "p"]
        self.assertEqual(len(letters), len(set(letters)))
        labels = {action.id: action.short for action in fp.ACTIONS}
        for action_id, label in module.BUTTON_MNEMONIC.items():
            self.assertEqual(label.replace("_", ""), labels[action_id])
        # The buttons' icons: the -symbolic one, else the name, else the phone.
        self.assertEqual(module.button_icon("folder", {"folder", "folder-symbolic"}.__contains__), "folder-symbolic")
        self.assertEqual(module.button_icon("video-display", {"video-display"}.__contains__), "video-display")
        self.assertEqual(module.button_icon("x", {"phone"}.__contains__), "phone")
        self.assertEqual(module.button_icon("x", set().__contains__), "application-x-executable")
        # A transfer row's second line, and flickos-phone's errors as sentences.
        size = lambda n: f"{n} B"
        item = {"direction": "out", "device": "Pixel", "done": 5, "size": 9, "state": "moving"}
        self.assertEqual(module.transfer_text(item, size), "To Pixel · 5 B of 9 B")
        self.assertEqual(module.transfer_text({**item, "direction": "in"}, size), "From Pixel · 5 B of 9 B")
        self.assertEqual(module.transfer_text({**item, "state": "waiting"}, size), "Waiting for Pixel to fetch it")
        self.assertEqual(module.sentence("flickos-phone: cancelled\n"), "Cancelled.")
        self.assertEqual(module.sentence("flickos-phone: a.jpg: no free port to offer it on"),
                         "a.jpg: no free port to offer it on.")
        self.assertEqual(module.sentence("Sent to Pixel."), "Sent to Pixel.")
        # Only pictures still there get a thumbnail.
        self.assertEqual(module.picture_path({"kind": "file", "value": "/d/a.jpg"}), "/d/a.jpg")
        self.assertIsNone(module.picture_path({"kind": "file", "value": "/d/a.jpg", "exists": False}))
        self.assertIsNone(module.picture_path({"kind": "file", "value": "/d/a.pdf"}))
        self.assertIsNone(module.picture_path({"kind": "text", "value": "a.jpg"}))
        # Dropped on the window: local files and web addresses as they are, other text as text.
        drop = module.drop_command
        send = ["flickos-phone", "send"]
        self.assertEqual(drop(["file:///home/u/My%20Photo.jpg", "file://localhost/tmp/a b.txt"], "",
                              web_address=fp.web_address),
                         send + ["--", "/home/u/My Photo.jpg", "/tmp/a b.txt"])
        self.assertEqual(drop(["https://example.org/x", "sftp://phone/DCIM/a.jpg", "trash:///b"], "", "a",
                              fp.web_address), send + ["--to", "a", "--", "https://example.org/x"])
        self.assertIsNone(drop(["sftp://phone/DCIM/a.jpg"], "", web_address=fp.web_address))
        self.assertEqual(drop([], " https://example.org/ \n", web_address=fp.web_address),
                         send + ["--", "https://example.org/"])
        self.assertEqual(drop([], "-n two\nlines", web_address=fp.web_address), send + ["--text=-n two\nlines"])
        self.assertIsNone(drop([], "  \n", web_address=fp.web_address))
        # What starts with "-" still reaches send as text and as a file.
        parsed = []
        with mock.patch.object(fp, "cmd_send", lambda opts: parsed.append(opts) or 0):
            self.assertEqual(fp.main(drop([], "-n two", web_address=fp.web_address)[1:]), 0)
            self.assertEqual(fp.main(drop(["file:///tmp/-x"], "", web_address=fp.web_address)[1:]), 0)
        self.assertEqual((parsed[0].text, parsed[0].things), ("-n two", []))
        self.assertEqual((parsed[1].text, parsed[1].things), (None, ["/tmp/-x"]))
        self.assertEqual("gi.repository.Gtk" in sys.modules, before)
        with open(os.path.join(PACKAGE, "usr/share/applications/flickos-phone.desktop"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn(f"TryExec={fp.ON_LINK}\n", text)
        self.assertIn("Exec=flickos-phone window\n", text)
        self.assertIn("Name=Phone\n", text)

    def test_menu_runs_the_choice(self):
        fp.save_settings(enabled=True)
        fp.add_received("text", "Pixel", "hello")
        connected = {"connected": [{"id": "a", "name": "Pixel", "paired": True}]}
        for answer, expect in (("0\n", "choose"), ("1\n", "type_text"), ("2\n", "clipboard"), ("5\n", "screen"),
                               ("6\n", "second"), ("7\n", "copy"), ("\n", None)):
            fuzzel = subprocess.CompletedProcess([], 0, answer, "")
            copied, sent, spawned = [], [], []
            with mock.patch.object(fp.shutil, "which", return_value="/usr/bin/x"), \
                    mock.patch.object(fp, "files_available", return_value=False), \
                    mock.patch.object(fp, "request", return_value=connected), \
                    mock.patch.object(fp.subprocess, "run", return_value=fuzzel) as run, \
                    mock.patch.object(fp, "copy_text", copied.append), \
                    mock.patch.object(fp, "spawn", spawned.append), \
                    mock.patch.object(fp, "cmd_send", lambda opts: sent.append(opts) or 0):
                self.assertEqual(fp.main(["menu"]), 0)
            self.assertEqual(run.call_args.args[0][:3], ["fuzzel", "--dmenu", "--index"])
            self.assertIn("--prompt", run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][run.call_args.args[0].index("--prompt") + 1], "Pixel: ")
            if expect in ("choose", "type_text", "clipboard"):
                self.assertTrue(getattr(sent[0], expect) and sent[0].notify)
                self.assertEqual([flag for flag in ("choose", "type_text", "clipboard", "screenshot")
                                  if getattr(sent[0], flag)],
                                 [expect])
            elif expect == "copy":
                self.assertEqual(copied, ["hello"])
            elif expect == "screen":            # one phone connected: that one
                self.assertEqual(spawned, [["flickos-phone-screen", "--to", "a"]])
            elif expect == "second":
                self.assertEqual(spawned, [["flickos-phone-screen", "second-screen", "on", "--notify", "--to", "a"]])
            else:
                self.assertEqual((copied, sent, spawned), ([], [], []))

    def test_choose_files(self):
        folder = tempfile.mkdtemp(dir=_ROOT.name)
        photo = os.path.join(folder, "a.jpg")
        open(photo, "w").close()
        sent = []

        def request(data, timeout=0):
            sent.append(data["items"])
            return {"ok": True, "name": "Pixel"}

        with mock.patch.object(fp, "choose_files", return_value=[photo]), \
                mock.patch.object(fp, "request", request), mock.patch("sys.stdout"):
            self.assertEqual(fp.main(["send", "--choose"]), 0)
        self.assertEqual(sent, [[{"kind": "file", "value": photo}]])
        # Cancelled: nothing is sent and nothing is said.
        with mock.patch.object(fp, "choose_files", return_value=[]), \
                mock.patch.object(fp, "request", request), mock.patch.object(fp, "progress_note") as note:
            self.assertEqual(fp.main(["send", "--choose", "--notify"]), 0)
        self.assertEqual(len(sent), 1)
        note.assert_not_called()

    def test_type_text(self):
        sent = []

        def request(data, timeout=0):
            sent.append(data["items"])
            return {"ok": True, "name": "Pixel"}

        for fuzzel, expect in ((subprocess.CompletedProcess([], 0, "  meet at 5  \n", ""), [{"kind": "text",
                                                                                      "value": "meet at 5"}]),
                               (subprocess.CompletedProcess([], 2, "", ""), None),       # Escape
                               (subprocess.CompletedProcess([], 0, "   \n", ""), None)):  # nothing typed
            sent.clear()
            with mock.patch.object(fp.shutil, "which", return_value="/usr/bin/fuzzel"), \
                    mock.patch.object(fp.subprocess, "run", return_value=fuzzel) as run, \
                    mock.patch.object(fp, "request", request), mock.patch("sys.stdout"):
                self.assertEqual(fp.main(["send", "--type-text"]), 0)
            self.assertEqual(run.call_args.args[0][:3], ["fuzzel", "--dmenu", "--prompt-only"])
            self.assertEqual(sent, [expect] if expect else [])

    def test_screenshot(self):
        sent, shots = [], []

        def run(argv, **kwargs):
            shots.append(argv[1])
            open(argv[1], "w").close()
            return subprocess.CompletedProcess(argv, 0, "", "")

        def request(data, timeout=0):
            sent.append(data["items"])
            self.assertTrue(os.path.isfile(data["items"][0]["value"]))     # there while it's sent
            return {"ok": True, "name": "Pixel"}

        with mock.patch.object(fp, "SCREENSHOT_DELAY", 0), \
                mock.patch.object(fp.shutil, "which", return_value="/usr/bin/grim"), \
                mock.patch.object(fp.subprocess, "run", run), mock.patch.object(fp, "request", request), \
                mock.patch("sys.stdout"):
            self.assertEqual(fp.main(["send", "--screenshot"]), 0)
        self.assertEqual(sent[0][0]["kind"], "file")
        self.assertTrue(os.path.basename(shots[0]).startswith("Screenshot "))
        self.assertTrue(shots[0].startswith(fp.runtime_dir()))
        self.assertFalse(os.path.exists(shots[0]))                          # deleted afterwards
        with mock.patch.object(fp, "SCREENSHOT_DELAY", 0), \
                mock.patch.object(fp.shutil, "which", return_value=None), mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["send", "--screenshot"]), 1)

    def test_clipboard_address_goes_as_a_page(self):
        sent = []

        def request(data, timeout=0):
            sent.append(data["items"])
            return {"ok": True, "name": "Pixel"}

        with mock.patch.object(fp, "request", request), mock.patch("sys.stdout"):
            for text in ("https://www.debian.org/\n", "see https://a.org", "https://a.org\nand more"):
                with mock.patch.object(fp, "clipboard_text", return_value=text):
                    fp.main(["send", "--clipboard"])
        self.assertEqual(sent, [[{"kind": "url", "value": "https://www.debian.org/"}],
                                [{"kind": "clipboard", "value": "see https://a.org"}],
                                [{"kind": "clipboard", "value": "https://a.org\nand more"}]])

    def test_turning_on_or_off_reloads_the_panel(self):
        with mock.patch.object(fp, "request", return_value=None), mock.patch.object(fp, "start_daemon"), \
                mock.patch.object(fp, "reload_panel") as reload, mock.patch("sys.stdout"):
            fp.main(["set", "enabled", "yes"])
            fp.main(["set", "enabled", "yes"])          # no change: the panel stays
            fp.main(["set", "enabled", "no"])
        self.assertEqual(reload.call_count, 2)

    def test_firewall(self):
        self.assertFalse(fp.firewall_on())
        with open(fp.UFW_CONF, "w") as f:
            f.write("# comment\nENABLED=yes\nLOGLEVEL=low\n")
        self.assertTrue(fp.firewall_on())

    def test_notification_settings(self):
        self.assertFalse(fp.load_settings().notifications)
        self.assertEqual(fp.load_settings().notification_apps, ())
        self.assertNotIn(fp.NOTIFICATION_IN, fp.capabilities(fp.load_settings())[0])
        on = fp.Settings(notifications=True)
        incoming, outgoing = fp.capabilities(on)
        self.assertEqual(incoming[-1], fp.NOTIFICATION_IN)
        self.assertEqual(outgoing[-1], fp.NOTIFICATION_OUT)
        self.assertNotIn("kdeconnect.notification.reply", incoming + outgoing)
        # The base lists stay as they are: the feature is added, not edited in.
        self.assertNotIn(fp.NOTIFICATION_IN, fp.INCOMING)
        self.assertEqual(fp.clean_app_name("  Messages\n "), "Messages")
        self.assertEqual(fp.notification_text({"title": "Ada", "text": "Hello"}), "Ada\nHello")
        self.assertEqual(fp.notification_text({"title": "Ada", "text": "Ada"}), "Ada")
        self.assertTrue(fp.notification_text({"text": "x" * 500}).endswith("…"))
        out = io.StringIO()
        with mock.patch.object(fp, "request", return_value=None), mock.patch("sys.stdout", out):
            self.assertEqual(fp.main(["set", "notifications", "yes"]), 0)
            self.assertEqual(fp.main(["get", "notifications"]), 0)
            self.assertEqual(fp.main(["notifications", "allow", "Messages"]), 0)
            self.assertEqual(fp.main(["notifications", "allow", "Mail"]), 0)
            out.seek(0)
            out.truncate()
            self.assertEqual(fp.main(["notifications", "list"]), 0)
            text = out.getvalue()
            self.assertEqual(fp.main(["set", "notifications", "default"]), 0)
            self.assertEqual(fp.main(["set", "notification-apps", "default"]), 0)
        self.assertFalse(fp.load_settings().notifications)
        self.assertEqual(fp.load_settings().notification_apps, ())
        self.assertIn("Messages\tyes", text)
        self.assertIn("Mail\tyes", text)
        changes = [(entry["key"], entry["old"], entry["new"]) for entry in self.history()]
        self.assertIn(("notifications", "no", "yes"), changes)
        self.assertIn(("notifications", "yes", "no"), changes)
        self.assertEqual([change for change in changes if change[0] == "notification-apps"],
                         [("notification-apps", "", "Messages"),
                          ("notification-apps", "Messages", "Messages\nMail"),
                          ("notification-apps", "Messages\nMail", "")])
        proc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, proc)
        os.makedirs(os.path.join(proc, "7"))
        with open(os.path.join(proc, "7", "comm"), "w") as f:
            f.write("swaylock\n")
        self.assertTrue(fp.screen_locked(proc))
        with open(os.path.join(proc, "7", "comm"), "w") as f:
            f.write("bash\n")
        with mock.patch.object(fp, "locked_hint", return_value=False):
            self.assertFalse(fp.screen_locked(proc))
        with mock.patch.object(fp, "locked_hint", return_value=True):
            self.assertTrue(fp.screen_locked(proc))
        proc = mock.Mock()
        proc.flickos_closed = False
        fp._shown["9"] = proc
        self.addCleanup(fp._shown.pop, "9", None)
        with mock.patch.object(fp.subprocess, "run") as run:
            fp.close_notification("9")
        self.assertTrue(proc.flickos_closed)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "gdbus")
        self.assertIn("org.freedesktop.Notifications.CloseNotification", argv)
        self.assertEqual(argv[-1], "9")

    def test_call_settings(self):
        self.assertFalse(fp.load_settings().calls)
        self.assertNotIn(fp.CALL_IN, fp.capabilities(fp.load_settings())[0])
        incoming, outgoing = fp.capabilities(fp.Settings(calls=True))
        self.assertEqual(incoming[-1], fp.CALL_IN)
        self.assertEqual(outgoing[-1], fp.CALL_OUT)
        self.assertNotIn("kdeconnect.telephony.request", incoming + outgoing)
        self.assertNotIn(fp.CALL_IN, fp.INCOMING)
        self.assertEqual(fp.caller_text({"contactName": " Ada ", "phoneNumber": "555"}), "Ada\n555")
        self.assertEqual(fp.caller_text({"contactName": "555", "phoneNumber": "555"}), "555")
        self.assertEqual(fp.caller_text({}), "Unknown number")
        self.assertTrue(fp.packet_flag(True))
        self.assertTrue(fp.packet_flag(" true "))
        self.assertFalse(fp.packet_flag("false"))
        self.assertFalse(fp.packet_flag(1))
        out = io.StringIO()
        with mock.patch.object(fp, "request", return_value=None), mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["set", "calls", "yes"]), 0)
            self.assertEqual(fp.main(["get", "calls"]), 0)
            self.assertEqual(fp.main(["set", "calls", "maybe"]), 1)
            self.assertEqual(fp.main(["set", "calls", "default"]), 0)
        self.assertEqual(out.getvalue(), "yes\n")
        self.assertFalse(fp.load_settings().calls)
        self.assertEqual([(e["key"], e["old"], e["new"]) for e in self.history() if e["key"] == "calls"],
                         [("calls", "no", "yes"), ("calls", "yes", "no")])
        fp._playerctl_missing = False
        self.addCleanup(setattr, fp, "_playerctl_missing", False)

        def run(argv, **kwargs):
            self.ran = argv
            if argv[1:] == ["--all-players", "--format", "{{playerInstance}}\t{{status}}", "status"]:
                return subprocess.CompletedProcess(argv, 0, "firefox.instance1\tPlaying\nbad name\tPlaying\n"
                                                    "mpv\tPaused\nvlc\tPlaying\n", "")
            if argv[:3] == ["playerctl", "--player", "vlc"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            raise AssertionError(argv)

        with mock.patch.object(fp.subprocess, "run", side_effect=run), mock.patch("sys.stderr"):
            self.assertEqual(fp.playing_players(), ["firefox.instance1", "vlc"])
            self.assertTrue(fp.control_player("vlc", "pause"))
            self.assertFalse(fp.control_player("bad name", "pause"))
            self.assertFalse(fp.control_player("vlc", "stop"))
        self.assertEqual(self.ran, ["playerctl", "--player", "vlc", "pause"])
        with mock.patch.object(fp.subprocess, "run", side_effect=FileNotFoundError), mock.patch("sys.stderr"):
            self.assertEqual(fp.playing_players(), [])
        self.assertTrue(fp._playerctl_missing)
        self.assertEqual(fp.playing_players(), [])

    def test_phone_players(self):
        """What the phone plays (ADR-018): cleaned, and the popup shows one."""
        self.assertEqual(fp.phone_player_name("  Spotify\n "), "Spotify")
        self.assertEqual(fp.phone_player_name(5), "")
        self.assertEqual(len(fp.phone_player_name("x" * 500)), fp.APP_NAME_LIMIT)
        player = fp.PhonePlayer("Spotify")
        fp.update_phone_player(player, {"title": "Song\n", "artist": "Ada", "isPlaying": True, "volume": 60})
        self.assertEqual((player.title, player.artist, player.playing, player.volume), ("Song", "Ada", True, 60))
        # A missing or broken field keeps its value: "true" isn't a boolean, 101 isn't a percent.
        fp.update_phone_player(player, {"isPlaying": "true", "volume": 101, "title": None})
        self.assertEqual((player.title, player.playing, player.volume), ("Song", True, 60))
        empty = fp.PhonePlayer("Clock")
        paused_new = fp.PhonePlayer("Podcasts", title="Talk", changed=5)
        playing_old = fp.PhonePlayer("Spotify", title="Song", playing=True, changed=1)
        self.assertIsNone(fp.shown_player([empty]))
        self.assertIs(fp.shown_player([empty, paused_new, playing_old]), playing_old)
        self.assertIs(fp.shown_player([empty, paused_new]), paused_new)

    def test_media_settings(self):
        self.assertFalse(fp.load_settings().media)
        self.assertNotIn(fp.MEDIA_IN, fp.capabilities(fp.load_settings())[0])
        self.assertNotIn(fp.MEDIA_OUT, fp.capabilities(fp.load_settings())[1])
        incoming, outgoing = fp.capabilities(fp.Settings(media=True))
        self.assertEqual((incoming[-1], outgoing[-1]), (fp.MEDIA_IN, fp.MEDIA_OUT))
        self.assertNotIn(fp.MEDIA_IN, fp.INCOMING)
        out = io.StringIO()
        with mock.patch.object(fp, "request", return_value=None), mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["set", "media", "yes"]), 0)
            self.assertEqual(fp.main(["get", "media"]), 0)
            self.assertEqual(fp.main(["set", "media", "maybe"]), 1)
            self.assertEqual(fp.main(["set", "media", "default"]), 0)
        self.assertEqual(out.getvalue(), "yes\n")
        self.assertFalse(fp.load_settings().media)
        self.assertEqual([(e["key"], e["old"], e["new"]) for e in self.history() if e["key"] == "media"],
                         [("media", "no", "yes"), ("media", "yes", "no")])
        text = ("vlc\x1fVLC media player\x1fPlaying\x1f0.4\x1f5000000\x1f180000000"
                "\x1fAda\x1fA song\x1fThe album\x1ffile:///tmp/cover.png\n"
                "vlc\x1fVLC media player\x1fPaused\x1f\x1f0\x1f\x1f\x1f\x1f\x1f\n"
                "mpv\x1fmpv\x1fPlaying\x1f1\x1f0\x1f1000\x1fAda\x1fLine\nTwo\x1fAlbum\x1f\n"
                "playerctld\x1fPlayerctld\x1fPlaying\x1f1\x1f0\x1f1\x1f\x1f\x1f\x1f\n"
                "bad name\x1fBad\x1fPlaying\x1f1\x1f0\x1f1\x1f\x1f\x1f\x1f\n"
                "No players found\n")
        players = fp.parse_media(text)
        self.assertEqual([player.name for player in players],
                         ["VLC media player", "VLC media player [2]", "mpv"])
        first = players[0]
        self.assertEqual((first.instance, first.title, first.artist, first.album, first.playing,
                          first.volume, first.position, first.length, first.art_url),
                         ("vlc", "A song", "Ada", "The album", True, 40, 5000, 180000,
                          "file:///tmp/cover.png"))
        self.assertTrue(first.body()["canSeek"])
        self.assertNotIn("volume", players[1].body())
        self.assertEqual(players[2].title, "Line Two")
        twice = ("vlc\x1fvlc\x1fPlaying\x1f1\x1f0\x1f1\x1f\x1fSong\x1f\x1f\n"
                 "vlc.instance42\x1fvlc\x1fPlaying\x1f1\x1f0\x1f1\x1f\x1fSong\x1f\x1f\n")
        self.assertEqual([(p.instance, p.name) for p in fp.parse_media(twice)], [("vlc.instance42", "vlc")])
        self.assertFalse(players[1].changed_from(players[1], 2000))
        moved = fp.dataclasses.replace(first, position=first.position + 2000)
        self.assertFalse(moved.changed_from(first, 2000))
        sought = fp.dataclasses.replace(first, position=50000)
        self.assertTrue(sought.changed_from(first, 2000))
        self.assertIsNone(fp.art_file("https://example/a.png"))
        self.assertIsNone(fp.art_file("file://other/tmp/a.png"))
        self.assertEqual(fp.art_file("file:///tmp/cover.png"), "/tmp/cover.png")
        self.assertEqual(fp.art_file("file:///tmp/my%20cover.png"), "/tmp/my cover.png")
        self.assertEqual(fp.offset_arg(-1.5), "1.500-")
        self.assertIsNone(fp.offset_arg(0))
        self.assertIsNone(fp.whole_number(True, 0, 100))
        self.assertIsNone(fp.whole_number(200, 0, 100))
        self.assertEqual(fp.clean_art_url("data:image/png;base64,aaaa"), "")
        commands = []
        with mock.patch.object(fp, "media_command", side_effect=lambda *args: commands.append(args) or True):
            fp.apply_media(first, {"action": "Pause", "setVolume": 10, "SetPosition": 5000,
                                   "Seek": -2000000, "setLoopStatus": "Track", "setShuffle": False})
            fp.apply_media(first, {"action": "OpenUri", "setVolume": True, "setLoopStatus": "Everything"})
        self.assertEqual(commands, [
            ("vlc", "pause"), ("vlc", "loop", "Track"), ("vlc", "shuffle", "Off"),
            ("vlc", "volume", "0.10"), ("vlc", "position", "2.000-"), ("vlc", "position", "5.000")])
        fp._playerctl_missing = False
        self.addCleanup(setattr, fp, "_playerctl_missing", False)
        with mock.patch.object(fp.subprocess, "run", side_effect=FileNotFoundError), mock.patch("sys.stderr"):
            self.assertEqual(fp.media_players(), [])
        self.assertTrue(fp._playerctl_missing)

    def test_command_settings(self):
        self.assertEqual(fp.load_settings().commands, ())
        self.assertNotIn(fp.COMMAND_IN, fp.capabilities(fp.load_settings())[0])
        self.assertNotIn(fp.COMMAND_OUT, fp.capabilities(fp.load_settings())[1])
        self.assertNotIn(fp.COMMAND_IN, fp.INCOMING)
        command = fp.Command("11111111-1111-1111-1111-111111111111", "Hello", "echo secret-token")
        incoming, outgoing = fp.capabilities(fp.Settings(commands=(command,)))
        self.assertEqual((incoming[-1], outgoing[-1]), (fp.COMMAND_IN, fp.COMMAND_OUT))
        packet = fp.commands_packet((command,))
        self.assertNotIn("secret-token", packet["commandList"])
        self.assertIn("Hello", packet["commandList"])
        self.assertIs(packet["canAddCommand"], False)
        self.assertLess(len(packet["commandList"]), 200)
        full = tuple(fp.Command(str(uuid.UUID(int=i)), f"Name {i}", "true") for i in range(fp.MAX_COMMANDS))
        self.assertLess(len(fp.commands_packet(full)["commandList"]), 8000)
        out = io.StringIO()
        with mock.patch.object(fp, "request", return_value=None), mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["commands", "add", "Hello", "echo secret-token"]), 0)
            self.assertEqual(fp.main(["commands", "add", "--", "Flags", "-n one"]), 0)
            self.assertEqual(fp.main(["commands", "add", "Hello", "echo again"]), 1)
            self.assertEqual(fp.main(["commands", "add", "x" * (fp.COMMAND_NAME + 1), "true"]), 1)
            self.assertEqual(fp.main(["commands", "add", "Lines", "echo\nhi"]), 1)
            out.seek(0)
            out.truncate()
            self.assertEqual(fp.main(["commands", "list"]), 0)
            listed = out.getvalue()
            out.seek(0)
            out.truncate()
            self.assertEqual(fp.main(["get", "commands"]), 0)
            stored = out.getvalue().strip()
        commands = fp.load_settings().commands
        self.assertEqual([(item.name, item.command) for item in commands],
                         [("Hello", "echo secret-token"), ("Flags", "-n one")])
        self.assertIn("secret-token", listed)
        self.assertNotIn("secret-token", fp.commands_packet(commands)["commandList"])
        self.assertEqual(json.loads(stored)[0]["key"], commands[0].key)
        with mock.patch.object(fp, "request", return_value=None), mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["set", "commands", "default"]), 0)
            self.assertEqual(fp.load_settings().commands, ())
            self.assertEqual(fp.main(["set", "commands", stored]), 0)
        restored = fp.load_settings().commands
        self.assertEqual([(item.key, item.name, item.command) for item in restored],
                         [(item.key, item.name, item.command) for item in commands])
        with mock.patch.object(fp, "request", return_value=None), mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["commands", "remove", restored[0].key]), 0)
            self.assertEqual(fp.main(["commands", "remove", restored[0].key]), 1)
            self.assertEqual(fp.main(["set", "commands", "not json"]), 1)
        self.assertEqual([item.name for item in fp.load_settings().commands], ["Flags"])
        with open(fp.user_conf(), "w", encoding="utf-8") as handle:
            handle.write("[Phone]\nCommands=not-a-list\n")
        with mock.patch("sys.stderr"):
            self.assertEqual(fp.load_settings().commands, ())
        changes = [(entry["key"], entry["old"], entry["new"]) for entry in self.history()
                   if entry["key"] == "commands"]
        self.assertEqual(changes[0][0], "commands")
        self.assertEqual(changes[0][1], "")
        self.assertIn("Hello", changes[0][2])
        self.assertIn("secret-token", changes[0][2])


# --- A fake phone -----------------------------------------------------------------

class FakePhone:
    """Does what the KDE Connect app does, on 127.0.0.1."""

    def __init__(self, folder, device_id=None, cert=None):
        self.id = device_id or uuid.uuid4().hex
        self.cert, self.key, self.der = cert or make_cert(folder, self.id)
        self.name = "Fake Phone"
        # The computer asks every paired phone for its players when it
        # connects (ADR-018). read() skips that unless a test wants it.
        self.media_requests = False

    def connect(self, port, target):
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        sock.sendall(fp.packet("kdeconnect.identity", {
            "deviceId": self.id, "deviceName": self.name, "protocolVersion": 8,
            "targetDeviceId": target, "targetProtocolVersion": 8}))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert, self.key)
        # The app asks for the client's certificate but takes any (Qt's QueryPeer);
        # ssl can't, so the fake doesn't ask. The daemon's side is the same.
        ctx.verify_mode = ssl.CERT_NONE
        self.tls = ctx.wrap_socket(sock, server_side=True)
        self.tls.sendall(fp.packet("kdeconnect.identity", {
            "deviceId": self.id, "deviceName": self.name, "deviceType": "phone", "protocolVersion": 8,
            "incomingCapabilities": [], "outgoingCapabilities": []}))
        self.reader = fp.LineReader(self.tls, 1 << 20)
        return self.reader.packet()["body"]

    def send(self, ptype, body, **extra):
        self.tls.sendall(fp.packet(ptype, body, **extra))

    def read(self):
        while True:
            data = self.reader.packet()
            if self.media_requests or data.get("type") != fp.PHONE_MEDIA_OUT \
                    or data.get("body") != {"requestPlayerList": True}:
                return data

    def fetch(self, port, cert=None):
        """Fetch a file the computer offers, as the app does (TLS client)."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.load_cert_chain(*(cert or (self.cert, self.key)))
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw, \
                ctx.wrap_socket(raw) as tls:
            data = b""
            while chunk := tls.recv(65536):
                data += chunk
        return data

    def close(self):
        if getattr(self, "tls", None) is not None:
            self.tls.close()


class DaemonTest(Isolated):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(dir=_ROOT.name)
        self.downloads = os.path.join(self.tmp, "Downloads")
        self.notes = []
        for name, value in (("notify", lambda title, body, action=None, on_click=None:
                             self.notes.append((title, body, action, on_click))),
                            ("downloads_dir", lambda: self.downloads),
                            # Never the build host's playerctl (test_media_follower fakes one).
                            ("follow_players", lambda: None)):
            patcher = mock.patch.object(fp, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.identity = fp.ensure_identity()
        self.active = ["home"]
        fp.save_settings(enabled=True, networks=("home",))
        self.daemon = fp.Daemon(self.identity, fp.load_settings(), bind="127.0.0.1", tcp_port=0,
                                payload_ports=(0,), udp=False, networks=lambda: list(self.active))
        self.thread = threading.Thread(target=self.daemon.run, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.wait(lambda: self.daemon.tcp is not None)
        self.phone = FakePhone(self.tmp)
        self.addCleanup(self.phone.close)

    def stop(self):
        self.daemon.stopping.set()
        self.daemon.wake()
        self.thread.join(5)

    def wait(self, condition, seconds=5):
        deadline = time.monotonic() + seconds
        while not condition():
            if time.monotonic() > deadline:
                self.fail("timed out")
            time.sleep(0.02)

    def port(self):
        return self.daemon.tcp.getsockname()[1]

    def connect(self, phone=None):
        phone = phone or self.phone
        ours = phone.connect(self.port(), self.identity.id)
        self.wait(lambda: phone.id in self.daemon.links)
        return ours

    def socketpair(self):
        ours, theirs = socket.socketpair()
        self.addCleanup(ours.close)
        self.addCleanup(theirs.close)
        return ours, theirs

    def pair(self, answer="yes"):
        """Run `pair` through a socket pair, the phone asks, answer."""
        ours, theirs = self.socketpair()
        thread = threading.Thread(target=self.daemon.pair_session, args=(theirs,), daemon=True)
        thread.start()
        waiting = fp.read_json(ours, 5)
        self.phone.send("kdeconnect.pair", {"pair": True, "timestamp": int(time.time())})
        request = fp.read_json(ours, 5)
        fp.reply(ours, {"answer": answer})
        done = fp.read_json(ours, 5)
        answer_packet = self.phone.read()
        thread.join(5)
        return waiting, request, done, answer_packet

    def test_handshake(self):
        ours = self.connect()
        self.assertEqual(ours["deviceId"], self.identity.id)
        self.assertEqual(ours["protocolVersion"], 8)
        self.assertEqual(ours["incomingCapabilities"], fp.INCOMING)
        self.assertEqual(ours["outgoingCapabilities"], fp.OUTGOING)
        # Only what moving things, the battery, ringing, browsing the phone's
        # files and what it plays need: nothing that lets the phone control the computer.
        self.assertEqual(sorted(set(fp.INCOMING) | set(fp.OUTGOING)),
                         ["kdeconnect.battery", "kdeconnect.clipboard", "kdeconnect.findmyphone.request",
                          "kdeconnect.mpris", "kdeconnect.mpris.request", "kdeconnect.ping", "kdeconnect.sftp", "kdeconnect.sftp.request",
                          "kdeconnect.share.request"])
        # What the phone plays (ADR-018) goes this way only: the phone sends
        # mpris and is asked with mpris.request. The other way round is the
        # media setting (ADR-016).
        self.assertIn(fp.PHONE_MEDIA_IN, fp.INCOMING)
        self.assertNotIn(fp.MEDIA_IN, fp.INCOMING)
        self.assertNotIn(fp.MEDIA_OUT, fp.OUTGOING)
        link = self.daemon.links[self.phone.id]
        self.assertFalse(link.paired)
        self.assertEqual(link.name, "Fake Phone")

    def test_link_keeps_alive(self):
        # A phone that leaves the network sends nothing: keepalive ends the link.
        self.connect()
        tls = self.daemon.links[self.phone.id].tls
        self.assertEqual(tls.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE), 1)
        self.assertEqual([tls.getsockopt(socket.IPPROTO_TCP, option) for option in
                          (socket.TCP_KEEPIDLE, socket.TCP_KEEPINTVL, socket.TCP_KEEPCNT)],
                         list(fp.KEEPALIVE))

    def test_answers_broadcast(self):
        self.assertFalse(self.daemon.answers_broadcast(self.identity.id))
        self.assertTrue(self.daemon.answers_broadcast(self.phone.id))
        # Connected but not paired: it may be pairing, a new link would lose the request.
        self.connect()
        self.assertFalse(self.daemon.answers_broadcast(self.phone.id))
        # Paired: a phone that broadcasts has no link, whatever we still hold.
        self.pair()
        self.assertTrue(self.daemon.answers_broadcast(self.phone.id))

    def test_nothing_before_pairing(self):
        self.connect()
        self.phone.send("kdeconnect.share.request", {"url": "https://example.org/"})
        self.phone.send("kdeconnect.clipboard", {"content": "secret"})
        # Without `pair` running, a pair request is refused.
        self.phone.send("kdeconnect.pair", {"pair": True, "timestamp": int(time.time())})
        self.assertEqual(self.phone.read()["body"], {"pair": False})
        self.assertEqual(self.notes, [])
        self.assertEqual(fp.read_received(), [])

    def test_wrong_certificate_name(self):
        # Its certificate names another device.
        other = FakePhone(self.tmp, device_id=uuid.uuid4().hex, cert=make_cert(self.tmp, uuid.uuid4().hex))
        self.addCleanup(other.close)
        with self.assertRaises((OSError, EOFError, fp.ProtocolError)):
            other.connect(self.port(), self.identity.id)
            other.read()
        self.assertNotIn(other.id, self.daemon.links)

    def test_pairing(self):
        self.connect()
        waiting, request, done, answer_packet = self.pair()
        self.assertEqual(waiting["event"], "waiting")
        self.assertEqual(request["event"], "request")
        self.assertEqual(request["name"], "Fake Phone")
        self.assertRegex(request["key"], r"^[0-9A-F]{8}$")
        self.assertEqual(done["event"], "paired")
        self.assertEqual(answer_packet["body"], {"pair": True})
        self.assertTrue(self.daemon.links[self.phone.id].paired)
        self.assertEqual(fp.paired_der(self.phone.id), self.phone.der)
        self.assertIn(self.phone.id, fp.load_devices())
        self.assertIn(("device." + self.phone.id, "absent", "Fake Phone"),
                      [(e["key"], e["old"], e["new"]) for e in self.history()])
        self.assertIsNone(self.daemon.pairing)

    def test_verification_key_is_the_phones(self):
        self.connect()
        ours, theirs = self.socketpair()
        threading.Thread(target=self.daemon.pair_session, args=(theirs,), daemon=True).start()
        fp.read_json(ours, 5)
        stamp = int(time.time())
        self.phone.send("kdeconnect.pair", {"pair": True, "timestamp": stamp})
        request = fp.read_json(ours, 5)
        self.assertEqual(request["key"], fp.verification_key(self.phone.der, self.identity.der, stamp))
        fp.reply(ours, {"answer": "no"})
        self.assertEqual(fp.read_json(ours, 5)["event"], "refused")
        self.assertEqual(self.phone.read()["body"], {"pair": False})
        self.assertFalse(self.daemon.links[self.phone.id].paired)
        self.assertEqual(fp.load_devices(), {})

    def test_old_clock_refused(self):
        self.connect()
        ours, theirs = self.socketpair()
        threading.Thread(target=self.daemon.pair_session, args=(theirs,), daemon=True).start()
        fp.read_json(ours, 5)
        self.phone.send("kdeconnect.pair", {"pair": True, "timestamp": int(time.time()) - 7200})
        self.assertEqual(self.phone.read()["body"], {"pair": False})
        ours.close()

    def offer_payload(self, blob):
        """A port the daemon can fetch blob from, as the phone's icon transfer."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def serve():
            try:
                conn, _ = server.accept()
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(self.phone.cert, self.phone.key)
                ctx.verify_mode = ssl.CERT_NONE
                tls = ctx.wrap_socket(conn, server_side=True)
                try:
                    tls.sendall(blob)
                    tls.shutdown(socket.SHUT_RDWR)
                finally:
                    tls.close()
            except OSError:
                pass
            finally:
                server.close()

        threading.Thread(target=serve, daemon=True).start()
        return port

    def paired(self):
        self.connect()
        self.pair()
        self.notes.clear()

    def test_receiving(self):
        self.paired()
        self.phone.send("kdeconnect.share.request", {"url": "https://a.org/x?a=1&amp;b=2"})
        self.phone.send("kdeconnect.share.request", {"text": '"quote"\n https://a.org/#:~:text=quote'})
        self.phone.send("kdeconnect.share.request", {"url": "file:///etc/passwd"})
        self.phone.send("kdeconnect.ping", {})
        self.wait(lambda: len(self.notes) == 4)
        titles = [n[0] for n in self.notes]
        self.assertEqual(titles, ["Page from Fake Phone", "Text from Fake Phone", "Text from Fake Phone",
                                  "Ping from Fake Phone"])
        self.assertEqual(self.notes[0][1:3], ("a.org/x", "Open"))
        self.assertEqual(self.notes[1][2], "Copy")
        items = fp.read_received()
        self.assertEqual([(i["kind"], i["value"]) for i in items],
                         [("page", "https://a.org/x?a=1&b=2"), ("text", '"quote"\n https://a.org/#:~:text=quote'),
                          ("text", "file:///etc/passwd")])

    def test_clipboard(self):
        self.paired()
        copied = []
        with mock.patch.object(fp, "copy_text", copied.append):
            self.phone.send("kdeconnect.clipboard", {"content": "from the phone"})
            self.wait(lambda: copied)
        self.assertEqual(copied, ["from the phone"])

    def test_sent_text_coming_back_is_dropped(self):
        # The phone puts text it gets onto its clipboard, and its clipboard sync
        # sends it straight back: that isn't something from the phone.
        self.paired()
        copied = []
        self.daemon.send_items(None, [{"kind": "text", "value": "meet at 5"}])
        self.assertEqual(self.phone.read()["body"], {"text": "meet at 5"})
        with mock.patch.object(fp, "copy_text", copied.append):
            self.phone.send("kdeconnect.clipboard", {"content": "meet at 5\n"})
            self.phone.send("kdeconnect.clipboard", {"content": "copied later"})
            self.wait(lambda: copied)
        self.assertEqual(copied, ["copied later"])
        self.assertEqual([i["value"] for i in fp.read_received()], ["copied later"])
        # Long after, the same text is the phone's own again.
        with mock.patch.object(fp.time, "monotonic", return_value=time.monotonic() + fp.ECHO_SECONDS):
            self.assertFalse(self.daemon.is_echo(self.phone.id, "meet at 5"))

    def offer(self, data, name):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        self.phone.send("kdeconnect.share.request", {"filename": name, "numberOfFiles": 1,
                                                     "totalPayloadSize": len(data)},
                        payloadSize=len(data), payloadTransferInfo={"port": port})
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.phone.cert, self.phone.key)
        server.settimeout(5)
        conn, _ = server.accept()
        with ctx.wrap_socket(conn, server_side=True) as tls:
            tls.sendall(data)
        server.close()

    def test_receiving_files(self):
        self.paired()
        data = os.urandom(300_000)
        self.offer(data, "../.evil.jpg")
        self.wait(lambda: len(self.notes) == 1)
        self.offer(b"again", "../.evil.jpg")
        self.wait(lambda: len(self.notes) == 2)
        with open(os.path.join(self.downloads, "evil.jpg"), "rb") as f:
            self.assertEqual(f.read(), data)
        with open(os.path.join(self.downloads, "evil (2).jpg"), "rb") as f:
            self.assertEqual(f.read(), b"again")
        self.assertEqual(sorted(os.listdir(self.downloads)), ["evil (2).jpg", "evil.jpg"])
        self.assertEqual(self.notes[0][:3], ("evil.jpg from Fake Phone", "Saved in Downloads.", "Open"))
        self.assertFalse(os.stat(os.path.join(self.downloads, "evil.jpg")).st_mode & 0o111)
        self.offer(b"#!/bin/sh\n", "run.sh")
        self.wait(lambda: len(self.notes) == 3)
        self.assertEqual(self.notes[2][2], "Show in Folder")

    def test_no_space(self):
        self.paired()
        usage = shutil.disk_usage(_ROOT.name)
        with mock.patch.object(fp.shutil, "disk_usage", return_value=usage._replace(free=fp.FREE_MARGIN)):
            self.phone.send("kdeconnect.share.request", {"filename": "big.iso"},
                            payloadSize=10, payloadTransferInfo={"port": 9})
            self.wait(lambda: self.notes)
        self.assertIn("wasn't saved", self.notes[0][0])
        self.assertFalse(os.path.exists(self.downloads) and os.listdir(self.downloads))

    def test_sending(self):
        self.paired()
        name = self.daemon.send_items(None, [{"kind": "url", "value": "https://debian.org"},
                                             {"kind": "clipboard", "value": "copied"}])
        self.assertEqual(name, "Fake Phone")
        self.assertEqual(self.phone.read()["body"], {"url": "https://debian.org"})
        clip = self.phone.read()
        self.assertEqual((clip["type"], clip["body"]), ("kdeconnect.clipboard", {"content": "copied"}))

    def test_sending_a_file_pinned_and_retried(self):
        self.paired()
        path = os.path.join(self.tmp, "wallpaper.jpg")
        data = os.urandom(200_000)
        with open(path, "wb") as f:
            f.write(data)
        result = {}
        thread = threading.Thread(target=lambda: result.update(
            name=self.daemon.send_items(None, [{"kind": "file", "value": path}])), daemon=True)
        events = []
        with mock.patch("sys.stderr"), mock.patch.object(self.daemon, "notify_watchers", events.append):
            thread.start()
            first = self.phone.read()
            self.assertEqual(first["body"]["filename"], "wallpaper.jpg")
            self.assertEqual(first["payloadSize"], len(data))
            # Someone else's certificate on the payload port: refused.
            stranger = make_cert(self.tmp, uuid.uuid4().hex)
            with self.assertRaises((ssl.SSLError, OSError)):
                self.phone.fetch(first["payloadTransferInfo"]["port"], cert=stranger[:2])
            # The offer is made once more, and the phone fetches it.
            second = self.phone.read()
            self.assertEqual(second["body"]["filename"], "wallpaper.jpg")
            self.assertEqual(self.phone.fetch(second["payloadTransferInfo"]["port"]), data)
            thread.join(10)
        self.assertEqual(result, {"name": "Fake Phone"})
        # The window saw it: waiting, waiting again for the second offer, then done, all of it.
        transfers = [event for event in events if event["event"] == "transfer"]
        self.assertEqual([event["state"] for event in transfers][:2], ["waiting", "waiting"])
        self.assertEqual((transfers[-1]["state"], transfers[-1]["done"], transfers[-1]["size"]),
                         ("done", len(data), len(data)))
        self.assertEqual(len({event["id"] for event in transfers}), 1)
        self.assertEqual(self.daemon.transfers, {})

    def test_sending_a_file_waits_until_the_phone_has_it(self):
        # A small file fits in the send buffer whole, so sendall returns at
        # once. A phone that resets before its TCP acknowledged every byte
        # didn't get it: offered again, not "sent".
        self.paired()
        path = os.path.join(self.tmp, "note.txt")
        data = b"a few bytes"
        with open(path, "wb") as f:
            f.write(data)
        real, first = fp.unacknowledged, []

        def unacknowledged(sock):
            if not first:
                first.append(sock)
            return 1 if sock is first[0] else real(sock)

        def fetch_and_reset(port):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.load_cert_chain(self.phone.cert, self.phone.key)
            raw = socket.create_connection(("127.0.0.1", port), timeout=10)
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            with ctx.wrap_socket(raw) as tls:
                got = b""
                while len(got) < len(data):
                    got += tls.recv(65536)
            return got                  # closed with linger 0: a reset

        result = {}
        thread = threading.Thread(target=lambda: result.update(
            name=self.daemon.send_items(None, [{"kind": "file", "value": path}])), daemon=True)
        with mock.patch("sys.stderr") as stderr, mock.patch.object(fp, "unacknowledged", unacknowledged):
            thread.start()
            offer = self.phone.read()
            self.assertEqual(fetch_and_reset(offer["payloadTransferInfo"]["port"]), data)
            again = self.phone.read()
            self.assertEqual(again["body"]["filename"], "note.txt")
            self.assertEqual(self.phone.fetch(again["payloadTransferInfo"]["port"]), data)
            thread.join(10)
        self.assertEqual(result, {"name": "Fake Phone"})
        self.assertIn("trying again", "".join(str(call) for call in stderr.mock_calls))

    def test_sending_a_file_gives_up_after_its_tries(self):
        self.paired()
        path = os.path.join(self.tmp, "note.txt")
        with open(path, "wb") as f:
            f.write(b"x")
        stranger = make_cert(self.tmp, uuid.uuid4().hex)
        errors = []

        def send():
            try:
                self.daemon.send_items(None, [{"kind": "file", "value": path}])
            except fp.PhoneError as error:
                errors.append(str(error))

        thread = threading.Thread(target=send, daemon=True)
        with mock.patch("sys.stderr"):
            thread.start()
            for _ in range(fp.SEND_TRIES):
                offer = self.phone.read()
                with self.assertRaises((ssl.SSLError, OSError)):
                    self.phone.fetch(offer["payloadTransferInfo"]["port"], cert=stranger[:2])
            thread.join(10)
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("note.txt: "))
        self.assertEqual(self.daemon.transfers, {})

    def test_sending_a_file_can_be_cancelled(self):
        self.paired()
        path = os.path.join(self.tmp, "big.iso")
        with open(path, "wb") as f:
            f.write(b"x" * 1000)
        result, cancelled, events = {}, [], []
        items = [{"kind": "file", "value": path}, {"kind": "text", "value": "after"}]
        thread = threading.Thread(target=lambda: result.update(
            name=self.daemon.send_items(None, items, cancelled)), daemon=True)
        with mock.patch.object(self.daemon, "notify_watchers", events.append):
            thread.start()
            self.assertEqual(self.phone.read()["body"]["filename"], "big.iso")      # offered, not fetched
            self.wait(lambda: self.daemon.transfers)
            self.assertEqual([row["state"] for row in self.daemon.status()["transfers"]], ["waiting"])
            transfer_id = next(iter(self.daemon.transfers))
            self.assertEqual(self.daemon.cancel_transfer(transfer_id), "big.iso")
            thread.join(5)
            # Not offered again; the rest still goes.
            self.assertEqual(self.phone.read()["body"], {"text": "after"})
        self.assertEqual((result, cancelled), ({"name": "Fake Phone"}, ["big.iso"]))
        self.assertEqual([event["state"] for event in events if event["event"] == "transfer"],
                         ["waiting", "cancelled"])
        self.assertEqual(self.daemon.transfers, {})
        with self.assertRaises(fp.PhoneError):
            self.daemon.cancel_transfer(transfer_id)

    def test_sending_a_file_can_be_cancelled_while_it_moves(self):
        self.paired()
        path = os.path.join(self.tmp, "video.mp4")
        with open(path, "wb") as f:
            f.write(b"x" * 1_000_000)
        result, cancelled, got = {}, [], []
        moving = threading.Event()
        real = self.daemon.transfer_moved

        def moved(transfer, count):
            real(transfer, count)
            moving.set()
            # Hold here until Cancel, so the whole file can't fit in the socket buffers first.
            deadline = time.monotonic() + 5
            while not transfer.cancelled and time.monotonic() < deadline:
                time.sleep(0.01)

        def fetch(port):
            with contextlib.suppress(OSError, ssl.SSLError):
                got.append(self.phone.fetch(port))

        thread = threading.Thread(target=lambda: result.update(
            name=self.daemon.send_items(None, [{"kind": "file", "value": path}], cancelled)), daemon=True)
        with mock.patch.object(self.daemon, "transfer_moved", moved):
            thread.start()
            offer = self.phone.read()
            threading.Thread(target=fetch, args=(offer["payloadTransferInfo"]["port"],), daemon=True).start()
            self.assertTrue(moving.wait(5))
            self.daemon.cancel_transfer(next(iter(self.daemon.transfers)))
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual((result, cancelled), ({"name": "Fake Phone"}, ["video.mp4"]))
        self.assertTrue(all(len(data) < 1_000_000 for data in got))

    def test_receiving_can_be_cancelled(self):
        self.paired()
        events = []
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(5)
        self.addCleanup(server.close)
        size = 1_000_000
        with mock.patch.object(self.daemon, "notify_watchers", events.append):
            self.phone.send("kdeconnect.share.request", {"filename": "big.iso", "numberOfFiles": 1,
                                                         "totalPayloadSize": size},
                            payloadSize=size, payloadTransferInfo={"port": server.getsockname()[1]})
            conn, _ = server.accept()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(self.phone.cert, self.phone.key)
            tls = ctx.wrap_socket(conn, server_side=True)
            try:
                tls.sendall(b"x" * 100_000)         # then stalls, as a slow phone would
                self.wait(lambda: any(t.done for t in list(self.daemon.transfers.values())))
                self.daemon.cancel_transfer(next(iter(self.daemon.transfers)))
                self.wait(lambda: not self.daemon.transfers)
            finally:
                with contextlib.suppress(OSError):
                    tls.close()
        states = [event["state"] for event in events if event["event"] == "transfer"]
        self.assertEqual((states[0], states[-1]), ("waiting", "cancelled"))
        self.assertEqual(events[0]["direction"], "in")
        self.assertEqual(self.notes, [])                # the user cancelled: no "wasn't saved"
        self.assertEqual(os.listdir(self.downloads), [])  # no .part left behind

    def test_send_needs_a_paired_phone(self):
        with self.assertRaises(fp.PhoneError):
            self.daemon.send_items(None, [{"kind": "url", "value": "https://a.org"}])
        self.connect()
        with self.assertRaises(fp.PhoneError):
            self.daemon.send_items(None, [{"kind": "url", "value": "https://a.org"}])

    def test_reconnect_stays_paired_other_cert_does_not(self):
        self.paired()
        self.phone.close()
        self.wait(lambda: self.phone.id not in self.daemon.links)
        self.connect()
        self.assertTrue(self.daemon.links[self.phone.id].paired)
        self.phone.close()
        self.wait(lambda: self.phone.id not in self.daemon.links)
        impostor = FakePhone(self.tmp, device_id=self.phone.id)
        self.addCleanup(impostor.close)
        impostor.connect(self.port(), self.identity.id)
        self.wait(lambda: self.phone.id in self.daemon.links)
        self.assertFalse(self.daemon.links[self.phone.id].paired)

    def test_forget_and_unpair_from_phone(self):
        self.paired()
        self.assertEqual(self.daemon.forget(self.phone.id), "Fake Phone")
        self.assertEqual(self.phone.read()["body"], {"pair": False})
        self.assertEqual(fp.load_devices(), {})
        self.pair()
        self.phone.send("kdeconnect.pair", {"pair": False})
        self.wait(lambda: not self.daemon.links[self.phone.id].paired)
        self.assertEqual(fp.load_devices(), {})

    def test_listens_only_on_its_networks(self):
        self.active[:] = ["cafe"]
        self.daemon.recheck()
        self.wait(lambda: self.daemon.tcp is None)
        # `pair` opens it on any network, and pairing adds the network.
        ours, theirs = self.socketpair()
        threading.Thread(target=self.daemon.pair_session, args=(theirs,), daemon=True).start()
        fp.read_json(ours, 5)
        self.wait(lambda: self.daemon.tcp is not None)
        self.connect()
        self.phone.send("kdeconnect.pair", {"pair": True, "timestamp": int(time.time())})
        fp.read_json(ours, 5)
        fp.reply(ours, {"answer": "yes"})
        self.assertEqual(fp.read_json(ours, 5)["event"], "paired")
        self.assertEqual(fp.load_settings().networks, ("home", "cafe"))
        self.wait(lambda: self.daemon.allowed)

    def test_unpaired_limit(self):
        phones = []
        for _ in range(fp.MAX_UNPAIRED):
            phone = FakePhone(self.tmp)
            self.addCleanup(phone.close)
            self.connect(phone)
            phones.append(phone)
        extra = FakePhone(self.tmp)
        self.addCleanup(extra.close)
        with self.assertRaises((OSError, EOFError, fp.ProtocolError, ssl.SSLError)):
            extra.connect(self.port(), self.identity.id)
            extra.read()
        self.assertEqual(self.daemon.unpaired, fp.MAX_UNPAIRED)
        for phone in phones:
            phone.close()
        self.wait(lambda: self.daemon.unpaired == 0)

    def control_socket(self):
        """The daemon's control socket, as run_daemon makes it."""
        os.makedirs(fp.runtime_dir(), exist_ok=True)
        path = fp.control_path()
        if os.path.exists(path):
            os.unlink(path)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(4)
        self.addCleanup(server.close)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        self.daemon.selector.register(server, fp.selectors.EVENT_READ, "control")
        self.daemon.wake()

    def test_pair_json_through_the_control_socket(self):
        self.control_socket()
        self.connect()
        out = io.StringIO()
        result = {}

        def run():
            with mock.patch("sys.stdout", out), mock.patch("sys.stdin", io.StringIO("yes\n")):
                result["code"] = fp.main(["pair", "--json"])

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.wait(lambda: self.daemon.pairing is not None)
        stamp = int(time.time())
        self.phone.send("kdeconnect.pair", {"pair": True, "timestamp": stamp})
        thread.join(10)
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([e["event"] for e in events], ["waiting", "request", "paired"])
        self.assertEqual(events[1]["key"], fp.verification_key(self.phone.der, self.identity.der, stamp))
        self.assertEqual(result["code"], 0)
        self.assertEqual(self.phone.read()["body"], {"pair": True})

    def test_watch_reports_the_phone(self):
        self.control_socket()
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(conn.close)
        conn.connect(fp.control_path())
        fp.reply(conn, {"command": "watch"})
        self.paired()
        event = fp.read_json(conn, 5)
        self.assertEqual(event["event"], "connected")
        self.assertEqual(event["phone"]["id"], self.phone.id)
        self.assertEqual(event["phone"]["name"], "Fake Phone")
        self.phone.send("kdeconnect.share.request", {"text": "hello"})
        event = fp.read_json(conn, 5)
        self.assertEqual((event["event"], event["item"]["value"]), ("received", "hello"))
        self.phone.send("kdeconnect.battery", {"currentCharge": 80, "isCharging": True})
        event = fp.read_json(conn, 5)
        self.assertEqual(event, {"event": "battery", "id": self.phone.id, "battery": [80, True]})
        self.phone.close()
        event = fp.read_json(conn, 5)
        self.assertEqual(event, {"event": "disconnected", "id": self.phone.id})

    def test_watch_refuses_past_the_limit(self):
        self.control_socket()
        held = []
        for _ in range(fp.MAX_WATCHERS):
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.connect(fp.control_path())
            fp.reply(conn, {"command": "watch"})
            held.append(conn)
            self.addCleanup(conn.close)
            self.wait(lambda count=len(held): len(self.daemon.watchers) >= count)
        extra = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(extra.close)
        extra.connect(fp.control_path())
        fp.reply(extra, {"command": "watch"})
        self.assertIn("too many", fp.read_json(extra, 5)["error"])

    def test_cancelled_pair_closes_the_window(self):
        self.active[:] = ["cafe"]
        self.daemon.recheck()
        self.wait(lambda: self.daemon.tcp is None)
        ours, theirs = self.socketpair()
        threading.Thread(target=self.daemon.pair_session, args=(theirs,), daemon=True).start()
        fp.read_json(ours, 5)
        self.wait(lambda: self.daemon.tcp is not None)
        ours.close()                        # the page's Cancel, or Ctrl+C
        self.wait(lambda: self.daemon.pairing is None, seconds=3)
        self.wait(lambda: self.daemon.tcp is None)

    def test_state(self):
        self.control_socket()
        self.paired()
        fp.add_received("page", "Fake Phone", "https://a.org/")
        out = io.StringIO()
        with mock.patch.object(fp, "active_networks", return_value=["home"]), \
                mock.patch.object(fp, "network_names", return_value={"home": "Home Wi-Fi"}), \
                mock.patch("sys.stdout", out):
            self.assertEqual(fp.main(["state"]), 0)
        state = json.loads(out.getvalue())
        self.assertTrue(state["enabled"] and state["running"] and state["listening"])
        self.assertEqual(state["phones"], [{"id": self.phone.id, "name": "Fake Phone",
                                            "paired": state["phones"][0]["paired"], "connected": True,
                                            "address": "127.0.0.1", "battery": None}])
        self.assertEqual(state["networks"], [{"uuid": "home", "name": "Home Wi-Fi", "active": True}])
        self.assertEqual(state["received"][0]["value"], "https://a.org/")
        self.assertFalse(state["live"])
        self.assertFalse(state["notifications"])
        self.assertEqual(state["notification_apps"], [])
        self.assertFalse(state["calls"])
        self.assertEqual(state["ringing"], [])
        self.assertFalse(state["media"])
        self.assertEqual(state["commands"], [])

    def test_mute(self):
        self.control_socket()
        self.paired()
        self.daemon.settings.calls = True
        shown = []
        with mock.patch.object(fp, "screen_locked", return_value=False), \
                mock.patch.object(fp, "post_notification", side_effect=lambda *args, **kwargs: shown.append(args) or "1"), \
                mock.patch.object(fp, "playing_players", return_value=[]), \
                mock.patch.object(fp, "control_player", return_value=True):
            self.phone.send("kdeconnect.telephony", {"event": "ringing", "contactName": "Ada", "phoneNumber": "555"})
            self.wait(lambda: self.daemon.calls.get(self.phone.id) == "ringing")
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(fp.main(["mute"]), 0)
        self.assertEqual(self.phone.read()["type"], fp.CALL_OUT)
        self.assertEqual(out.getvalue(), "Muted Fake Phone's ringer.\n")
        state_out = io.StringIO()
        with mock.patch("sys.stdout", state_out):
            self.assertEqual(fp.main(["state"]), 0)
        ringing = json.loads(state_out.getvalue())["ringing"]
        self.assertEqual(ringing[0]["id"], self.phone.id)
        self.assertEqual(ringing[0]["caller"].splitlines()[0], "Ada")

    def test_watch_reports_a_ringing_phone(self):
        self.control_socket()
        self.paired()
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(conn.close)
        conn.connect(fp.control_path())
        fp.reply(conn, {"command": "watch"})
        self.wait(lambda: self.daemon.watchers)
        self.daemon.settings.calls = True
        with mock.patch.object(fp, "screen_locked", return_value=False), \
                mock.patch.object(fp, "post_notification", return_value="1"), \
                mock.patch.object(fp, "playing_players", return_value=[]), \
                mock.patch.object(fp, "control_player", return_value=True):
            self.phone.send("kdeconnect.telephony", {"event": "ringing", "contactName": "Ada"})
            event = fp.read_json(conn, 5)
            self.assertEqual((event["event"], event["state"], event["id"]), ("call", "ringing", self.phone.id))
            self.assertEqual(event["caller"], "Ada")
            self.phone.send("kdeconnect.telephony", {"event": "talking", "isCancel": "true"})
            event = fp.read_json(conn, 5)
        self.assertEqual(event, {"event": "call", "id": self.phone.id, "state": "ended", "caller": ""})

    def test_ring(self):
        self.control_socket()
        self.paired()
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(fp.main(["ring"]), 0)
        self.assertEqual(self.phone.read()["type"], "kdeconnect.findmyphone.request")
        self.assertEqual(out.getvalue(), "Fake Phone is ringing.\n")

    def test_browse(self):
        self.control_socket()
        self.paired()

        def reply():
            packet = self.phone.read()
            self.assertEqual((packet["type"], packet["body"]), (fp.SFTP_OUT, {"startBrowsing": True}))
            self.phone.send(fp.SFTP_IN, {
                "ip": "10.1.2.3", "port": "1740", "user": "kdeconnect", "password": "one-time-secret",
                "path": "/", "multiPaths": ["/storage/emulated/0", "/storage/emulated/0/DCIM/Camera"],
                "pathNames": ["All files", "Camera pictures"]})

        threading.Thread(target=reply, daemon=True).start()
        opened, out = [], io.StringIO()
        # Never the build host's gvfs: a build container has none.
        with mock.patch.object(fp, "files_available", return_value=True), \
                mock.patch.object(fp, "open_phone_files", lambda offer: opened.append(offer) or "Camera pictures"), \
                mock.patch("sys.stdout", out):
            self.assertEqual(fp.main(["browse"]), 0)
        self.assertEqual(opened[0]["host"], "127.0.0.1")       # the connection, not the packet's ip
        self.assertEqual(opened[0]["port"], 1740)
        self.assertEqual([folder["name"] for folder in opened[0]["folders"]], ["All files", "Camera pictures"])
        self.assertNotIn("one-time-secret", out.getvalue())
        self.assertEqual(out.getvalue(), "Opened Camera pictures on Fake Phone.\n")
        # Nothing asked: a login pushed by the phone is ignored.
        self.phone.send(fp.SFTP_IN, {"port": 1740, "user": "kdeconnect", "password": "nope", "path": "/"})
        time.sleep(0.05)
        self.assertEqual(self.notes, [])

    def test_browse_says_why_the_phone_refused(self):
        self.control_socket()
        self.paired()

        def reply():
            self.phone.read()
            self.phone.send(fp.SFTP_IN, {"errorMessage": "Permissions missing: filesystem access"})

        threading.Thread(target=reply, daemon=True).start()
        err = io.StringIO()
        with mock.patch.object(fp, "files_available", return_value=True), mock.patch("sys.stderr", err):
            self.assertEqual(fp.main(["browse"]), 1)
        self.assertIn("Allow file access", err.getvalue())
        self.assertNotIn("Permissions missing", err.getvalue())
        self.assertNotIn("one-time", err.getvalue())

    def test_browse_checks_the_key_before_mounting(self):
        der = self.phone.der
        blob = fp.ssh_public_blob(fp.cert_fields(der)[1])
        other = fp.ssh_public_blob(fp.cert_fields(self.identity.der)[1])
        offer = {"id": self.phone.id, "name": "Fake Phone", "host": "127.0.0.1", "port": 1740,
                 "user": "kdeconnect", "password": "secret",
                 "folders": [{"path": "/storage/emulated/0", "name": "All files"}]}
        mounted = []
        with mock.patch.object(fp, "files_available", return_value=True), \
                mock.patch.object(fp, "paired_der", return_value=der), \
                mock.patch.object(fp, "scan_host_keys", return_value=[other]), \
                mock.patch.object(fp, "drive_mount", lambda *args: mounted.append(args)):
            with self.assertRaises(fp.PhoneError) as caught:
                fp.open_phone_files(offer)
        self.assertEqual(str(caught.exception), fp.NOT_THE_PHONE)
        self.assertEqual(mounted, [])
        with mock.patch.object(fp, "files_available", return_value=True), \
                mock.patch.object(fp, "paired_der", return_value=der), \
                mock.patch.object(fp, "scan_host_keys", return_value=[blob]), \
                mock.patch.object(fp, "drive_mount", lambda *args: mounted.append(args)), \
                mock.patch.object(fp, "open_mounted_folder") as opened:
            self.assertEqual(fp.open_phone_files(offer), "All files")
        argv, dialogue, _seconds = mounted[0]
        self.assertEqual(argv, ["gio", "mount", "sftp://kdeconnect@127.0.0.1:1740/storage/emulated/0"])
        self.assertNotIn("secret", " ".join(argv))
        self.assertEqual(dialogue.fingerprint, fp.host_fingerprint(blob))
        self.assertEqual(dialogue.password, "secret")
        opened.assert_called_once_with("sftp://kdeconnect@127.0.0.1:1740/storage/emulated/0")

    def test_the_file_manager_opens_the_mounted_folder(self):
        uri = "sftp://kdeconnect@127.0.0.1:1740/storage/emulated/0"
        with mock.patch.object(fp.shutil, "which", return_value="/usr/bin/gio"), \
                mock.patch.object(fp.subprocess, "run",
                                  return_value=subprocess.CompletedProcess(["gio"], 0)) as run:
            fp.open_mounted_folder(uri)
        self.assertEqual(run.call_args.args[0], ["gio", "open", uri])
        self.assertNotIn("xdg-open", run.call_args.args[0])
        failed = subprocess.CompletedProcess(["gio"], 1, stderr="no handler")
        with mock.patch.object(fp.shutil, "which", return_value="/usr/bin/gio"), \
                mock.patch.object(fp.subprocess, "run", return_value=failed), \
                mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(fp.PhoneError):
                fp.open_mounted_folder(uri)

    def test_mount_answers_gio_on_a_terminal(self):
        folder = tempfile.mkdtemp(dir=_ROOT.name)
        gio = os.path.join(folder, "gio")
        out = os.path.join(folder, "answers")
        with open(gio, "w") as handle:
            handle.write(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "sys.stdout.write(os.environ['PROMPT'])\n"
                "sys.stdout.write('Choice: ')\n"
                "sys.stdout.flush()\n"
                "choice = sys.stdin.readline()\n"
                "if choice.strip() != '1':\n"
                "    open(os.environ['ANSWERS'], 'w').write(choice)\n"
                "    sys.exit(1)\n"
                "sys.stdout.write('Password: ')\n"
                "sys.stdout.flush()\n"
                "open(os.environ['ANSWERS'], 'w').write(choice + sys.stdin.readline())\n")
        os.chmod(gio, 0o755)
        fingerprint = "SHA256:matched"
        env = dict(os.environ)
        env["PATH"] = folder + os.pathsep + env.get("PATH", "")
        env["PROMPT"] = f'The identity sent by the remote computer is "{fingerprint}".\n'
        env["ANSWERS"] = out
        with mock.patch.dict(os.environ, env, clear=False):
            fp.drive_mount([gio, "mount", "sftp://kdeconnect@127.0.0.1:1740/storage"],
                           fp.MountDialogue(fingerprint, "s3cret"), 5)
        with open(out) as handle:
            self.assertEqual(handle.read(), "1\ns3cret\n")
        # A different fingerprint is refused, and the password is not sent.
        # The stand-in is stopped as soon as the answer is no, so it may not
        # have recorded the choice; it must not have recorded the password.
        refused = os.path.join(folder, "refused")
        env["PROMPT"] = 'The identity sent by the remote computer is "SHA256:nope".\n'
        env["ANSWERS"] = refused
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(fp.PhoneError) as caught:
                fp.drive_mount([gio, "mount", "sftp://x"], fp.MountDialogue(fingerprint, "s3cret"), 5)
        self.assertEqual(str(caught.exception), fp.NOT_THE_PHONE)
        recorded = ""
        if os.path.exists(refused):
            with open(refused) as handle:
                recorded = handle.read()
        self.assertNotIn("s3cret", recorded)

    def test_ping(self):
        self.control_socket()
        self.paired()
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(fp.main(["ping", "Turn on Wireless debugging"]), 0)
            self.assertEqual(fp.main(["ping"]), 0)
        first, second = self.phone.read(), self.phone.read()
        self.assertEqual((first["type"], first["body"]), ("kdeconnect.ping", {"message": "Turn on Wireless debugging"}))
        self.assertEqual(second["body"], {})
        self.assertEqual(out.getvalue(), "Sent to Fake Phone.\n" * 2)

    def test_battery(self):
        self.control_socket()
        self.connect()
        self.phone.send("kdeconnect.battery", {"currentCharge": 50, "isCharging": False})   # not paired yet
        self.pair()
        for body in ({"currentCharge": "80"}, {"currentCharge": 180}, {"currentCharge": True},
                     {"currentCharge": 80, "isCharging": True}):
            self.phone.send("kdeconnect.battery", body)
        self.wait(lambda: self.daemon.links[self.phone.id].battery is not None)
        self.assertEqual(self.daemon.links[self.phone.id].battery, (80, True))
        fp.save_settings(enabled=True)
        status = fp.panel_status()
        self.assertTrue(status["tooltip"].startswith("Connected to Fake Phone · 80 %, charging\n"))
        self.assertEqual(fp.battery_text([15, False]), " · 15 %")
        self.assertEqual(fp.battery_text(None), "")

    def test_phone_notifications_are_capped(self):
        """Past MAX_PHONE_NOTES the oldest closes here, and isn't cancelled on the phone."""
        self.paired()
        shown, closed = [], []

        def post(summary, body, icon=None, replace=None, on_close=None):
            shown.append(summary)
            return str(len(shown))

        with mock.patch.object(fp, "screen_locked", return_value=False), \
                mock.patch.object(fp, "MAX_PHONE_NOTES", 2), \
                mock.patch.object(fp, "post_notification", side_effect=post), \
                mock.patch.object(fp, "close_notification", side_effect=closed.append):
            self.daemon.settings.notifications = True
            self.daemon.settings.notification_apps = ("Messages",)
            for n in range(3):
                self.phone.send("kdeconnect.notification", {
                    "id": f"m{n}", "appName": "Messages", "title": "Ada", "text": f"Hello {n}"})
            self.wait(lambda: len(shown) == 3 and closed)
            self.assertEqual(closed, ["1"])
            self.assertEqual(sorted(self.daemon.phone_notes.values()), ["2", "3"])
            self.phone.send("kdeconnect.ping", {"message": "after"})
            self.wait(lambda: any(note[1] == "after" for note in self.notes))
            self.phone.tls.settimeout(0.2)
            with self.assertRaises((TimeoutError, OSError)):
                self.phone.read()                   # no cancel went to the phone
            self.phone.tls.settimeout(None)

    def test_phone_notifications(self):
        self.paired()
        shown, closed = [], []

        def post(summary, body, icon=None, replace=None, on_close=None):
            shown.append((summary, body, icon, replace, on_close))
            return str(len(shown))

        locked = mock.Mock(return_value=False)
        with mock.patch.object(fp, "screen_locked", locked), \
                mock.patch.object(fp, "post_notification", side_effect=post), \
                mock.patch.object(fp, "close_notification", side_effect=closed.append):
            self.daemon.settings.notifications = True
            # Not allowed yet: the message stays off the screen, the app is remembered,
            # and one note says where to allow it.
            self.phone.send("kdeconnect.notification", {
                "id": "m1", "appName": " Messages ", "title": "Ada", "text": "Hello there",
                "isClearable": True})
            self.wait(lambda: any(note[0] == "Messages" for note in self.notes))
            self.assertEqual(self.notes[0][1:3], (fp.HINT_BODY, "Phone Settings"))
            self.assertNotIn("Hello", self.notes[0][1])
            self.assertEqual(fp.read_seen_apps(), ["Messages"])
            self.phone.send("kdeconnect.notification", {
                "id": "m2", "appName": "Messages", "title": "Ada", "text": "Again"})
            self.phone.send("kdeconnect.ping", {})
            self.wait(lambda: any(note[0].startswith("Ping") for note in self.notes))
            self.assertEqual([note[0] for note in self.notes if note[0] == "Messages"], ["Messages"])
            self.assertEqual(shown, [])
            # Allowed: it shows, with the app's name. Dismissing it dismisses it on the phone.
            self.daemon.settings.notification_apps = ("Messages",)
            self.phone.send("kdeconnect.notification", {
                "id": "m3", "appName": "Messages", "title": "Ada", "text": "Hello there",
                "isClearable": True})
            self.wait(lambda: shown and shown[-1][0] == "Messages")
            self.assertEqual(shown[-1][1], "Ada\nHello there")
            self.assertIsNone(shown[-1][2])
            shown[-1][4]()
            cancel = self.phone.read()
            self.assertEqual((cancel["type"], cancel["body"]), (fp.NOTIFICATION_OUT, {"cancel": "m3"}))
            # The phone dismissing one closes it here.
            self.phone.send("kdeconnect.notification", {
                "id": "m4", "appName": "Messages", "title": "Now", "text": "Playing", "isClearable": True})
            self.wait(lambda: any(item[1] == "Now\nPlaying" for item in shown))
            self.phone.send("kdeconnect.notification", {"id": "m4", "isCancel": True})
            self.wait(lambda: closed == ["2"])
            # Dismissing one the phone won't clear does not ask the phone to.
            self.phone.send("kdeconnect.notification", {
                "id": "m5", "appName": "Messages", "title": "Now", "text": "Playing", "isClearable": False})
            self.wait(lambda: sum(item[1] == "Now\nPlaying" for item in shown) == 2)
            link = self.daemon.links[self.phone.id]
            sent = []
            real_send = link.send
            link.send = lambda ptype, body, **extra: sent.append((ptype, body))
            shown[-1][4]()
            self.assertEqual(sent, [])
            link.send = real_send
            # A silent update of one we aren't showing is not a new alert. During a sync it is.
            before = len(shown)
            self.phone.send("kdeconnect.notification", {
                "id": "old", "appName": "Messages", "text": "Secret", "silent": True})
            self.phone.send("kdeconnect.ping", {"message": "after silent"})
            self.wait(lambda: any(note[1] == "after silent" for note in self.notes))
            self.assertEqual(len(shown), before)
            self.assertFalse(any("Secret" in item[1] for item in shown))
            self.daemon.links[self.phone.id].sync_until = time.monotonic() + 30
            self.phone.send("kdeconnect.notification", {
                "id": "old", "appName": "Messages", "text": "Secret", "silent": True})
            self.wait(lambda: any(item[1] == "Secret" for item in shown))
            # Nothing while the screen is locked, not even the "allow this app" note.
            locked.return_value = True
            self.phone.send("kdeconnect.notification", {
                "id": "mail", "appName": "Mail", "title": "Boss", "text": "Confidential"})
            self.phone.send("kdeconnect.ping", {"message": "locked"})
            self.wait(lambda: any(note[1] == "locked" for note in self.notes))
            self.assertNotIn("Mail", [note[0] for note in self.notes])
            self.assertFalse(any("Confidential" in item[1] for item in shown))
            self.assertIn("Mail", fp.read_seen_apps())

    def test_notification_icon(self):
        self.paired()
        blob = fp.IMAGE_PNG + b"icon-bytes"
        digest = hashlib.md5(blob).hexdigest()
        port = self.offer_payload(blob)
        shown = []
        with mock.patch.object(fp, "screen_locked", return_value=False), \
                mock.patch.object(fp, "post_notification",
                                  side_effect=lambda *args, **kwargs: shown.append((args, kwargs)) or "1"):
            self.daemon.settings.notifications = True
            self.daemon.settings.notification_apps = ("Messages",)
            self.phone.send("kdeconnect.notification",
                            {"id": "i", "appName": "Messages", "text": "Hi", "payloadHash": digest},
                            payloadSize=len(blob), payloadTransferInfo={"port": port})
            self.wait(lambda: shown)
        self.assertEqual(shown[0][0][2], fp.icon_cache_path(digest))
        with open(fp.icon_cache_path(digest), "rb") as f:
            self.assertEqual(f.read(), blob)

    def test_notification_capability_and_reconnect(self):
        self.control_socket()
        self.daemon.settings = fp.Settings(enabled=True, networks=("home",), notifications=True)
        ours = self.connect()
        self.assertIn(fp.NOTIFICATION_IN, ours["incomingCapabilities"])
        self.assertIn(fp.NOTIFICATION_OUT, ours["outgoingCapabilities"])
        self.assertNotIn("kdeconnect.notification.reply", ours["incomingCapabilities"] + ours["outgoingCapabilities"])
        # Not paired yet, so it does not ask for the current notifications.
        self.phone.tls.settimeout(0.2)
        with self.assertRaises((OSError, TimeoutError, fp.ProtocolError)):
            self.phone.read()
        self.phone.tls.settimeout(None)
        self.pair()
        self.assertEqual(self.phone.read()["body"], {"request": True})
        # Turning it off drops the link, so the phone connects again without the capability.
        fp.save_settings(notifications=False)
        self.assertEqual(fp.request({"command": "reload"})["ok"], True)
        self.wait(lambda: self.phone.id not in self.daemon.links)
        self.phone.close()
        ours = self.connect()
        self.assertNotIn(fp.NOTIFICATION_IN, ours["incomingCapabilities"])

    def test_calls(self):
        self.paired()
        shown, closed = [], []
        players = {"firefox": "Playing", "mpv": "Paused"}
        commands = []

        def post(summary, body, icon=None, replace=None, on_close=None, action=None, on_action=None):
            shown.append((summary, body, action, on_action, replace))
            return str(len(shown))

        def playing():
            return [name for name, status in players.items() if status == "Playing"]

        def control(name, command):
            commands.append((name, command))
            players[name] = "Paused" if command == "pause" else "Playing"
            return True

        locked = mock.Mock(return_value=False)
        with mock.patch.object(fp, "screen_locked", locked), \
                mock.patch.object(fp, "post_notification", side_effect=post), \
                mock.patch.object(fp, "close_notification", side_effect=closed.append), \
                mock.patch.object(fp, "playing_players", side_effect=playing), \
                mock.patch.object(fp, "control_player", side_effect=control):
            self.daemon.settings.calls = False
            self.phone.send("kdeconnect.telephony", {"event": "ringing", "contactName": "Ada"})
            self.phone.send("kdeconnect.ping", {"message": "before"})
            self.wait(lambda: any(note[1] == "before" for note in self.notes))
            self.assertEqual(shown, [])
            self.assertEqual(commands, [])
            self.daemon.settings.calls = True
            self.phone.send("kdeconnect.telephony",
                            {"event": "ringing", "contactName": "Ada", "phoneNumber": "555"})
            self.wait(lambda: shown)
            self.assertEqual(shown[-1][:3], ("Incoming call", "Ada\n555", "Mute"))
            self.assertEqual(commands, [("firefox", "pause")])
            self.assertEqual(players["mpv"], "Paused")
            shown[-1][3]()
            mute = self.phone.read()
            self.assertEqual((mute["type"], mute["body"]), (fp.CALL_OUT, {}))
            # Answered: the ringer notification goes, and the music stays paused.
            self.phone.send("kdeconnect.telephony", {"event": "talking"})
            self.wait(lambda: closed == ["1"])
            self.assertEqual(commands, [("firefox", "pause")])
            # The Android app sends isCancel as the string "true".
            self.phone.send("kdeconnect.telephony", {"event": "talking", "isCancel": "true"})
            self.wait(lambda: ("firefox", "play") in commands)
            self.assertNotIn(("mpv", "play"), commands)
            # A call this computer made: pause, and no notification.
            before = len(shown)
            self.phone.send("kdeconnect.telephony", {"event": "talking", "phoneNumber": "555"})
            self.phone.send("kdeconnect.ping", {"message": "outgoing"})
            self.wait(lambda: any(note[1] == "outgoing" for note in self.notes))
            self.assertEqual(len(shown), before)
            self.assertIn(("firefox", "pause"), commands)
            self.phone.send("kdeconnect.telephony", {"event": "talking", "isCancel": True})
            self.wait(lambda: commands.count(("firefox", "play")) == 2)
            # Nothing on the lock screen, but what is playing still pauses.
            locked.return_value = True
            self.phone.send("kdeconnect.telephony",
                            {"event": "ringing", "contactName": "Boss", "phoneNumber": "1"})
            self.phone.send("kdeconnect.ping", {"message": "locked"})
            self.wait(lambda: any(note[1] == "locked" for note in self.notes))
            self.assertFalse(any("Boss" in item[1] for item in shown))
            self.assertEqual(commands[-1], ("firefox", "pause"))
            # A missed call ends it. No second notification.
            self.phone.send("kdeconnect.telephony",
                            {"event": "ringing", "isCancel": "true", "contactName": "Boss"})
            self.phone.send("kdeconnect.telephony",
                            {"event": "missedCall", "contactName": "Boss", "phoneNumber": "1"})
            self.phone.send("kdeconnect.ping", {"message": "missed"})
            self.wait(lambda: any(note[1] == "missed" for note in self.notes))
            self.assertFalse(any("Boss" in item[1] for item in shown))
            self.assertEqual(commands[-1], ("firefox", "play"))
            # A text message is not a call.
            self.phone.send("kdeconnect.telephony",
                            {"event": "sms", "contactName": "Ada", "messageBody": "secret"})
            self.phone.send("kdeconnect.ping", {"message": "after sms"})
            self.wait(lambda: any(note[1] == "after sms" for note in self.notes))
            self.assertFalse(any("secret" in item[1] for item in shown))
            self.assertEqual(commands[-1], ("firefox", "play"))

    def test_call_capability_and_reconnect(self):
        self.control_socket()
        self.daemon.settings = fp.Settings(enabled=True, networks=("home",), calls=True)
        ours = self.connect()
        self.assertIn(fp.CALL_IN, ours["incomingCapabilities"])
        self.assertIn(fp.CALL_OUT, ours["outgoingCapabilities"])
        self.assertNotIn("kdeconnect.telephony.request",
                         ours["incomingCapabilities"] + ours["outgoingCapabilities"])
        self.pair()
        fp.save_settings(calls=False)
        self.assertEqual(fp.request({"command": "reload"})["ok"], True)
        self.wait(lambda: self.phone.id not in self.daemon.links)
        self.phone.close()
        ours = self.connect()
        self.assertNotIn(fp.CALL_IN, ours["incomingCapabilities"])

    def test_call_ends_when_the_phone_goes(self):
        self.paired()
        commands = []
        with mock.patch.object(fp, "screen_locked", return_value=True), \
                mock.patch.object(fp, "playing_players", return_value=["firefox"]), \
                mock.patch.object(fp, "control_player",
                                  side_effect=lambda name, command: commands.append((name, command)) or True):
            self.daemon.settings.calls = True
            self.phone.send("kdeconnect.telephony", {"event": "ringing", "contactName": "Ada"})
            self.wait(lambda: commands == [("firefox", "pause")])
            self.phone.close()
            self.wait(lambda: ("firefox", "play") in commands)
        self.assertNotIn(self.phone.id, self.daemon.calls)

    def test_media(self):
        self.paired()
        cover = os.path.join(self.tmp, "cover.png")
        blob = b"\x89PNG\r\n\x1a\n" + b"x" * 16
        with open(cover, "wb") as handle:
            handle.write(blob)
        url = "file://" + cover
        other = os.path.join(self.tmp, "secret.txt")
        with open(other, "wb") as handle:
            handle.write(b"secret")
        player = fp.Player("vlc", "VLC", "Song", "Ada", "Album", url, 180000, 1000, True, 40)
        commands = []
        locked = mock.Mock(return_value=False)

        def command(*args):
            commands.append(args)
            return True

        with mock.patch.object(fp, "media_players", return_value=[player]), \
                mock.patch.object(fp, "media_command", side_effect=command), \
                mock.patch.object(fp, "screen_locked", locked):
            self.daemon.settings.media = False
            self.phone.send(fp.MEDIA_IN, {"player": "VLC", "action": "Pause"})
            self.phone.send("kdeconnect.ping", {"message": "before media"})
            self.wait(lambda: any(note[1] == "before media" for note in self.notes))
            self.assertEqual(commands, [])
            self.daemon.settings.media = True
            self.daemon.sync_media(self.daemon.links[self.phone.id])
            self.assertEqual(self.phone.read()["body"],
                             {"playerList": ["VLC"], "supportAlbumArtPayload": True})
            state = self.phone.read()["body"]
            self.assertEqual((state["title"], state["artist"], state["pos"], state["volume"],
                              state["isPlaying"], state["albumArtUrl"]),
                             ("Song", "Ada", 1000, 40, True, url))
            self.phone.send(fp.MEDIA_IN, {"player": "VLC", "action": "Play", "setVolume": 80,
                                          "Seek": 3000000, "requestNowPlaying": True})
            answer = self.phone.read()["body"]
            self.assertEqual(commands, [("vlc", "play"), ("vlc", "volume", "0.80"),
                                        ("vlc", "position", "3.000+")])
            self.assertEqual(answer["title"], "Song")
            before = len(commands)
            self.phone.send(fp.MEDIA_IN, {"player": "Nope", "action": "Pause"})
            self.assertEqual(self.phone.read()["body"]["playerList"], ["VLC"])
            self.assertEqual(len(commands), before)
            # A cover larger than the limit, and a file that isn't the cover, are not sent.
            with mock.patch.object(fp, "ART_BYTES", 4):
                self.phone.send(fp.MEDIA_IN, {"player": "VLC", "albumArtUrl": url})
                self.phone.send(fp.MEDIA_IN, {"requestPlayerList": True})
                self.assertIn("playerList", self.phone.read()["body"])
            self.phone.send(fp.MEDIA_IN, {"player": "VLC", "albumArtUrl": "file://" + other})
            self.phone.send(fp.MEDIA_IN, {"player": "VLC", "albumArtUrl": url})
            offer = self.phone.read()
            self.assertEqual(offer["body"]["transferringAlbumArt"], True)
            self.assertEqual(offer["body"]["albumArtUrl"], url)
            self.assertEqual(self.phone.fetch(offer["payloadTransferInfo"]["port"]), blob)
            locked.return_value = True
            before = len(commands)
            self.phone.send(fp.MEDIA_IN, {"player": "VLC", "action": "Pause", "setVolume": 1})
            self.phone.send(fp.MEDIA_IN, {"requestPlayerList": True})
            self.assertEqual(self.phone.read()["body"]["playerList"], ["VLC"])
            self.assertEqual(len(commands), before)
            self.phone.tls.settimeout(0.2)
            self.daemon.poll_media()
            with self.assertRaises((TimeoutError, OSError)):
                self.phone.read()
            self.phone.tls.settimeout(None)

    def test_media_follower(self):
        """Players are read when playerctl --follow prints, not on a timer, and
        the follower runs only while media is on and a paired phone is here."""
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, write_end)
        follower = mock.Mock()
        follower.stdout = os.fdopen(read_end, "rb")
        started = []
        player = fp.Player("vlc", "VLC", "Song", "Ada", "Album", "", 180000, 1000, True, 40)
        players = [player]
        with mock.patch.object(fp, "follow_players", side_effect=lambda: started.append(1) or follower), \
                mock.patch.object(fp, "media_players", side_effect=lambda: list(players)):
            self.paired()
            self.daemon.wake()
            time.sleep(0.2)
            self.assertEqual(started, [])                   # media is off
            self.daemon.settings.media = True
            self.daemon.sync_media(self.daemon.links[self.phone.id])
            self.assertEqual(self.phone.read()["body"]["playerList"], ["VLC"])
            self.assertEqual(self.phone.read()["body"]["title"], "Song")
            self.daemon.wake()
            self.wait(lambda: started == [1])
            players[0] = dataclasses.replace(player, title="Next Song", playing=False)
            os.write(write_end, b"vlc\x1fPaused\n")
            changed = self.phone.read()["body"]
            self.assertEqual((changed["title"], changed["isPlaying"]), ("Next Song", False))
            self.phone.close()
            self.wait(lambda: follower.terminate.called)
            self.assertIsNone(self.daemon.media_follower)

    def test_media_capability_and_reconnect(self):
        self.control_socket()
        self.daemon.settings = fp.Settings(enabled=True, networks=("home",), media=True)
        with mock.patch.object(fp, "media_players", return_value=[]):
            ours = self.connect()
            self.assertIn(fp.MEDIA_IN, ours["incomingCapabilities"])
            self.assertIn(fp.MEDIA_OUT, ours["outgoingCapabilities"])
            self.pair()
            self.assertEqual(self.phone.read()["body"],
                             {"playerList": [], "supportAlbumArtPayload": True})
            fp.save_settings(media=False)
            self.assertEqual(fp.request({"command": "reload"})["ok"], True)
            self.wait(lambda: self.phone.id not in self.daemon.links)
        self.phone.close()
        ours = self.connect()
        self.assertNotIn(fp.MEDIA_IN, ours["incomingCapabilities"])
        self.assertNotIn(fp.MEDIA_OUT, ours["outgoingCapabilities"])

    def started(self):
        ran = []

        def popen(argv, **kwargs):
            ran.append((argv, kwargs))
            return mock.Mock()

        return ran, popen

    def test_commands(self):
        self.paired()
        command = fp.Command("11111111-1111-1111-1111-111111111111", "Hello", "echo secret-token")
        self.daemon.settings = fp.dataclasses.replace(self.daemon.settings, commands=(command,))
        self.phone.send(fp.COMMAND_IN, {"requestCommandList": True, "command": "echo pwned", "setup": True})
        packet = self.phone.read()
        self.assertEqual(packet["type"], fp.COMMAND_OUT)
        self.assertNotIn("secret-token", packet["body"]["commandList"])
        self.assertNotIn("pwned", packet["body"]["commandList"])
        self.assertIs(packet["body"]["canAddCommand"], False)
        ran, popen = self.started()
        with mock.patch.object(fp.subprocess, "Popen", side_effect=popen), \
                mock.patch.object(fp, "screen_locked", return_value=False), mock.patch("sys.stderr"):
            self.phone.send(fp.COMMAND_IN, {"key": command.key, "command": "echo pwned"})
            self.wait(lambda: ran)
            self.phone.send(fp.COMMAND_IN, {"key": "no-such-key", "command": "echo pwned"})
            self.phone.send(fp.COMMAND_IN, {"setup": True, "command": "echo pwned"})
            self.phone.send("kdeconnect.ping", {"message": "after commands"})
            self.wait(lambda: any(note[1] == "after commands" for note in self.notes))
        self.assertEqual(len(ran), 1)
        argv, kwargs = ran[0]
        self.assertEqual(argv, ["/bin/sh", "-c", "echo secret-token"])
        self.assertIs(kwargs.get("shell", False), False)
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["cwd"], os.path.expanduser("~"))
        ran.clear()
        with mock.patch.object(fp.subprocess, "Popen", side_effect=popen), \
                mock.patch.object(fp, "screen_locked", return_value=True):
            self.phone.send(fp.COMMAND_IN, {"key": command.key})
            self.phone.send("kdeconnect.ping", {"message": "while locked"})
            self.wait(lambda: any(note[1] == "while locked" for note in self.notes))
        self.assertEqual(ran, [])

    def test_command_before_pairing_does_not_run(self):
        self.connect()
        command = fp.Command("11111111-1111-1111-1111-111111111111", "Hello", "echo secret-token")
        self.daemon.settings = fp.dataclasses.replace(self.daemon.settings, commands=(command,))
        ran, popen = self.started()
        with mock.patch.object(fp.subprocess, "Popen", side_effect=popen), \
                mock.patch.object(fp, "screen_locked", return_value=False):
            self.phone.send(fp.COMMAND_IN, {"key": command.key, "command": "echo pwned"})
            self.pair()
            self.assertEqual(ran, [])
            # Pairing sent the names. Read that, then ask to run.
            self.assertEqual(self.phone.read()["type"], fp.COMMAND_OUT)
            self.phone.send(fp.COMMAND_IN, {"key": command.key})
            self.wait(lambda: ran)
        self.assertEqual(ran[0][0], ["/bin/sh", "-c", "echo secret-token"])

    def test_phone_media(self):
        """The phone's players (ADR-018): asked for on connect, each new one
        asked what it plays, the popup's row in state and on watch, and
        `player` sends the action to the player the row shows."""
        self.control_socket()
        self.phone.media_requests = True
        self.paired()
        self.assertEqual(self.phone.read()["body"], {"requestPlayerList": True})
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(conn.close)
        conn.connect(fp.control_path())
        fp.reply(conn, {"command": "watch"})
        self.wait(lambda: self.daemon.watchers)
        conn.settimeout(5)
        lines = conn.makefile("rb")     # two lines can come in one read

        def line():
            return json.loads(lines.readline())

        self.phone.send(fp.PHONE_MEDIA_IN, {"playerList": ["Spotify", "Podcasts", "", 7, "Spotify"],
                                            "supportAlbumArtPayload": True})
        asked = [self.phone.read() for _ in range(2)]
        self.assertEqual([(packet["type"], packet["body"]) for packet in asked],
                         [(fp.PHONE_MEDIA_OUT, {"player": name, "requestNowPlaying": True, "requestVolume": True})
                          for name in ("Spotify", "Podcasts")])
        self.phone.send(fp.PHONE_MEDIA_IN, {"player": "Podcasts", "title": "Talk", "artist": "",
                                            "isPlaying": False, "volume": 50})
        self.assertEqual(line(), {"event": "playing", "id": self.phone.id, "player": "Podcasts",
                                                 "title": "Talk", "artist": "", "playing": False})
        self.phone.send(fp.PHONE_MEDIA_IN, {"player": "Spotify", "title": "Song", "artist": "Ada",
                                            "isPlaying": True, "albumArtUrl": "kdeconnect:/artUri?album=x"})
        event = line()
        self.assertEqual((event["player"], event["title"], event["playing"]), ("Spotify", "Song", True))
        # The same again changes nothing, so no line.
        self.phone.send(fp.PHONE_MEDIA_IN, {"player": "Spotify", "title": "Song", "artist": "Ada", "isPlaying": True})
        self.phone.send(fp.PHONE_MEDIA_IN, {"player": "Spotify", "title": "Song", "artist": "Ada", "isPlaying": False})
        self.assertEqual(line()["playing"], False)
        state_out = io.StringIO()
        with mock.patch("sys.stdout", state_out):
            self.assertEqual(fp.main(["state"]), 0)
        self.assertEqual(json.loads(state_out.getvalue())["playing"],
                         {"id": self.phone.id, "player": "Spotify", "title": "Song", "artist": "Ada", "playing": False})
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(fp.main(["player", "play"]), 0)
            self.assertEqual(fp.main(["player", "next", "--to", self.phone.id]), 0)
            self.assertEqual(fp.main(["player", "volume", "30"]), 0)
            self.assertEqual(fp.main(["player", "volume", "300"]), 1)
            self.assertEqual(fp.main(["player", "pause", "30"]), 1)
            self.assertEqual(fp.main(["player", "next", "--to", "nope"]), 1)
        self.assertEqual([self.phone.read()["body"] for _ in range(3)],
                         [{"player": "Spotify", "action": "Play"}, {"player": "Spotify", "action": "Next"},
                          {"player": "Spotify", "setVolume": 30}])
        self.assertEqual(out.getvalue().splitlines()[0], "Asked Spotify on Fake Phone to play.")
        # A list without Spotify drops it; Podcasts is shown again.
        self.phone.send(fp.PHONE_MEDIA_IN, {"playerList": ["Podcasts"]})
        self.assertEqual(line()["player"], "Podcasts")
        # The phone going away empties the row, after the line that says it went.
        self.phone.close()
        self.assertEqual(line()["event"], "disconnected")
        self.assertEqual(line(), {"event": "playing", "id": self.phone.id, "player": "",
                                                 "title": "", "artist": "", "playing": False})
        self.assertIsNone(self.daemon.status()["playing"])

    def test_phone_media_limits(self):
        """At most PHONE_PLAYERS per phone, and nothing to control says so."""
        self.control_socket()
        self.paired()
        with self.assertRaises(fp.PhoneError):
            fp.request({"command": "player", "action": "play"})
        with mock.patch.object(fp, "PHONE_PLAYERS", 2):
            self.phone.send(fp.PHONE_MEDIA_IN, {"playerList": ["A", "B", "C"]})
            self.phone.send(fp.PHONE_MEDIA_IN, {"player": "D", "title": "Not kept"})
            self.phone.send("kdeconnect.ping", {"message": "after"})
            self.wait(lambda: any(note[1] == "after" for note in self.notes))
        self.assertEqual(sorted(self.daemon.phone_media[self.phone.id]), ["A", "B"])
        with self.assertRaises(fp.PhoneError):
            fp.request({"command": "player", "action": "rm -rf"})

    def test_command_capability_and_reconnect(self):
        self.control_socket()
        self.paired()
        self.phone.close()
        ours = self.connect()
        self.assertNotIn(fp.COMMAND_IN, ours["incomingCapabilities"])
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["commands", "add", "Hello", "echo secret-token"]), 0)
        self.wait(lambda: self.phone.id not in self.daemon.links)
        self.phone.close()
        ours = self.connect()
        self.assertIn(fp.COMMAND_IN, ours["incomingCapabilities"])
        self.assertIn(fp.COMMAND_OUT, ours["outgoingCapabilities"])
        listed = self.phone.read()
        self.assertEqual(listed["type"], fp.COMMAND_OUT)
        self.assertNotIn("secret-token", listed["body"]["commandList"])
        self.assertIn("Hello", listed["body"]["commandList"])
        # A further command is sent on the link that is already up.
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(fp.main(["commands", "add", "Goodbye", "true"]), 0)
        self.assertIn(self.phone.id, self.daemon.links)
        updated = self.phone.read()
        self.assertEqual(updated["type"], fp.COMMAND_OUT)
        shown = json.loads(updated["body"]["commandList"])
        self.assertEqual({item["name"] for item in shown.values()}, {"Hello", "Goodbye"})
        self.assertEqual({item["command"] for item in shown.values()}, {"Hello", "Goodbye"})
        self.assertNotIn("secret-token", updated["body"]["commandList"])

    def test_status(self):
        self.connect()
        status = self.daemon.status()
        self.assertTrue(status["listening"])
        self.assertEqual(status["connected"], [{"id": self.phone.id, "name": "Fake Phone", "paired": False,
                                                "address": "127.0.0.1", "battery": None}])


def tearDownModule():
    _ROOT.cleanup()


if __name__ == "__main__":
    unittest.main()
