"""Tests for the bought apps' key (flickos-control purchases and the helper's
purchases-* verbs; docs/design/flickos-store.md, ADR-004). A stand-in store
on 127.0.0.1 answers like server/store/store.js; every system file is in a
temporary folder. Run: python3 -m unittest discover -s tests"""

import base64
import datetime
import gzip
import http.server
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import test_control as tc

fc, helper = tc.fc, tc.helper

KEY = "abcd-efgh-ijkl-mnop-qrst-uvwx-yz23-4567-abcd-efgh-ijkl-mnop-qrst"
OTHER_KEY = "zzzz-yyyy-xxxx-wwww-vvvv-uuuu-tttt-ssss-rrrr-qqqq-pppp-oooo-nnnn"
REAL_STORE_PACKAGES = helper.store_packages


class StandInStore:
    """Answers (status, JSON) from `answers` by path, and keeps the requests:
    (method, path, Authorization header, body)."""

    def __init__(self, test):
        self.answers, self.requests = {}, []
        store = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else ""
                store.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
                status, data = store.answers.get(self.path, (404, {"status": "not found"}))
                text = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(text)))
                self.end_headers()
                self.wfile.write(text)

            do_GET = do_POST = answer

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def logins(self):
        return [base64.b64decode(auth.split()[1]).decode() if auth else None for _, _, auth, _ in self.requests]


def valid(*products):
    return 200, {"status": "valid", "products": list(products), "packages": [f"flickos-{p}" for p in products]}


class PurchasesHelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-control-purchases-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.store = StandInStore(self)
        release = os.path.join(self.tmp, "flickos-release")
        with open(release, "w") as f:
            f.write('FLICKOS_NAME="FlickOS"\nFLICKOS_DEBIAN="trixie"\n')
        self.paths = {name: os.path.join(self.tmp, *parts) for name, parts in (
            ("STORE_AUTH", ("auth.conf.d", "flickos-store.conf")),
            ("STORE_SOURCES", ("sources.list.d", "flickos-store.sources")),
            ("STORE_PINS", ("preferences.d", "flickos-store")),
            ("PURCHASES_FILE", ("lib", "purchases.json")))}
        self.available = {"flickos-notes", "flickos-write", "flickos-phone-screen"}
        self.updates = []
        for name, value in (*self.paths.items(), ("STORE_URL", self.store.url), ("FLICKOS_RELEASE", release),
                            ("OS_RELEASE", "/nonexistent"), ("live_system", lambda: False),
                            ("store_packages", lambda: set(self.available)),
                            ("update_store_lists", lambda: self.updates.append(True))):
            patcher = mock.patch.object(helper, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        root = mock.patch.object(helper.os, "geteuid", return_value=0)
        root.start()
        self.addCleanup(root.stop)

    def run_helper(self, *args, stdin=""):
        with mock.patch("sys.stdin", io.StringIO(stdin)), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            status = helper.main(list(args))
        return status, out.getvalue() + err.getvalue()

    def read(self, name):
        with open(self.paths[name]) as f:
            return f.read()

    def test_keys_as_typed(self):
        self.assertEqual(helper.normal_key(KEY), KEY)
        self.assertEqual(helper.normal_key(" " + KEY.upper().replace("-", "") + "\n"), KEY)
        self.assertEqual(helper.normal_key(KEY.replace("-", " ")), KEY)
        for text in ("", KEY[:-1], KEY + "a", KEY.replace("a", "0"), KEY.replace("b", "1"), KEY + "\nmachine x",
                     "x" * 52 + "!", None):
            self.assertIsNone(helper.normal_key(text), text)
        self.assertTrue(helper.KEY_PATTERN.match(KEY))
        # flickos-control checks the same way before it asks for the password.
        for text in (KEY, KEY.upper(), KEY[:-1], KEY.replace("a", "8"), "x" * 52, KEY + "\nmachine x"):
            self.assertEqual(fc.normal_key(text), helper.normal_key(text), text)
        with self.assertRaises(helper.HelperError):
            helper.read_key(io.StringIO("\n"))
        with self.assertRaises(helper.HelperError):
            helper.read_key(io.StringIO("a" * 500 + "\n"))
        self.assertEqual(helper.read_key(io.StringIO(KEY + "\n")), KEY)

    def test_same_store_as_flickos_control(self):
        self.assertEqual(fc.STORE_URL, "https://store.flickos.org")
        self.assertEqual(fc.PURCHASES_FILE, "/var/lib/flickos-control/purchases.json")
        with open(os.path.join(tc.PACKAGE, "usr/libexec/flickos/control-helper")) as f:
            text = f.read()
        self.assertIn(f'STORE_URL = "{fc.STORE_URL}"', text)
        self.assertIn(f'PURCHASES_FILE = "{fc.PURCHASES_FILE}"', text)
        for name in ("KEY_REFUSED", "KEY_TURNED_OFF", "KEY_CHARS"):
            self.assertEqual(getattr(fc, name), getattr(helper, name), name)
        # The apt hook runs the check only while the login file is there.
        with open(os.path.join(tc.PACKAGE, "etc/apt/apt.conf.d/61flickos-purchases")) as f:
            hook = f.read()
        self.assertIn("[ -e /etc/apt/auth.conf.d/flickos-store.conf ]", hook)
        self.assertIn("/usr/libexec/flickos/control-helper purchases-check || true", hook)
        self.assertIn("APT::Update::Post-Invoke {", hook)

    def test_add_a_first_key(self):
        self.store.answers["/v1/key"] = valid("notes")
        status, out = self.run_helper("purchases-add", stdin=KEY.upper() + "\n")
        self.assertEqual(status, 0, out)
        self.assertIn("Bought with this key: Notes.", out)
        self.assertNotIn(KEY, out)
        # The key goes in the login, never in the address.
        self.assertEqual([(m, p) for m, p, _, _ in self.store.requests], [("GET", "/v1/key")])
        self.assertEqual(self.store.logins(), [f"key:{KEY}"])
        self.assertEqual(self.read("STORE_AUTH"),
                         f"{helper.STORE_MARK}\nmachine {self.store.url}/apt login key password {KEY}\n")
        self.assertEqual(os.stat(self.paths["STORE_AUTH"]).st_mode & 0o777, 0o600)
        self.assertIn(f"URIs: {self.store.url}/apt\nSuites: trixie-store\nComponents: main\n"
                      "Signed-By: /usr/share/keyrings/flickos-archive-keyring.asc\n", self.read("STORE_SOURCES"))
        purchases = json.loads(self.read("PURCHASES_FILE"))
        self.assertEqual({k: purchases[k] for k in ("v", "key", "status", "products", "packages")},
                         {"v": 1, "key": "qrst", "status": "valid", "products": ["notes"],
                          "packages": ["flickos-notes"]})
        self.assertNotIn(KEY[:-5], self.read("PURCHASES_FILE"))
        self.assertEqual(os.stat(self.paths["PURCHASES_FILE"]).st_mode & 0o777, 0o644)
        self.assertEqual(self.updates, [True])
        # The store's other apps keep their installed version.
        self.assertIn("Package: flickos-phone-screen flickos-write\nPin: release o=FlickOS,l=FlickOS Store\n"
                      "Pin-Priority: -1\n", self.read("STORE_PINS"))
        # flickos-control reads the file without a password.
        with mock.patch.object(fc, "PURCHASES_FILE", self.paths["PURCHASES_FILE"]):
            self.assertEqual(fc.purchases_value(), "qrst")

    def test_https_login_has_no_protocol(self):
        with mock.patch.object(helper, "STORE_URL", "https://store.flickos.org"):
            self.assertEqual(helper.store_auth_text(KEY).splitlines()[1],
                             f"machine store.flickos.org/apt login key password {KEY}")
        for word in ("machine", "login", "password", "default", "macdef"):
            self.assertNotIn(word, helper.STORE_MARK.split())

    def test_a_refused_key_writes_nothing(self):
        self.store.answers["/v1/key"] = (401, {"status": "unknown"})
        status, out = self.run_helper("purchases-add", stdin=KEY + "\n")
        self.assertEqual(status, 1)
        self.assertIn(helper.KEY_REFUSED, out)
        status, out = self.run_helper("purchases-add", stdin="not a key\n")
        self.assertEqual((status, len(self.store.requests)), (1, 1))     # refused before asking
        self.assertIn(helper.KEY_REFUSED, out)
        for args in (["purchases-add", KEY], ["purchases-remove", "x"], ["purchases-check", "x"]):
            self.assertEqual(self.run_helper(*args, stdin=KEY + "\n")[0], 1, args)
        self.assertFalse(any(os.path.exists(path) for path in self.paths.values()))
        self.assertEqual(self.updates, [])

    def test_answers_that_arent_the_stores(self):
        for answer in ({"status": "valid", "products": ["notes"], "packages": ["flickos-notes\nPin: x"]},
                       {"status": "valid", "products": ["../x"], "packages": []},
                       {"status": "valid", "products": "notes", "packages": []}, {}):
            self.store.answers["/v1/key"] = (200, answer)
            status, out = self.run_helper("purchases-add", stdin=KEY + "\n")
            self.assertEqual(status, 1, answer)
            self.assertIn("The FlickOS store answered 200", out)
        self.assertFalse(os.path.exists(self.paths["STORE_AUTH"]))

    def test_unreachable_and_live(self):
        with mock.patch.object(helper, "STORE_URL", "http://127.0.0.1:9"):
            status, out = self.run_helper("purchases-add", stdin=KEY + "\n")
        self.assertEqual(status, 1)
        self.assertIn(helper.STORE_UNREACHABLE, out)
        with mock.patch.object(helper, "live_system", lambda: True):
            status, out = self.run_helper("purchases-add", stdin=KEY + "\n")
        self.assertEqual(status, 1)
        self.assertIn("live session", out)
        self.assertEqual(self.store.requests, [])

    def test_a_second_key_is_linked(self):
        self.store.answers["/v1/key"] = valid("notes")
        self.assertEqual(self.run_helper("purchases-add", stdin=KEY + "\n")[0], 0)
        self.store.answers["/v1/link"] = valid("notes", "write")
        status, out = self.run_helper("purchases-add", stdin=OTHER_KEY + "\n")
        self.assertEqual(status, 0, out)
        self.assertIn("Notes, Write. It was added to the key already on this computer.", out)
        method, path, auth, body = self.store.requests[-1]
        self.assertEqual((method, path, auth, json.loads(body)),
                         ("POST", "/v1/link", None, {"key": KEY, "add": OTHER_KEY}))
        self.assertIn(f"password {KEY}\n", self.read("STORE_AUTH"))          # the computer's key stays
        self.assertEqual(json.loads(self.read("PURCHASES_FILE"))["products"], ["notes", "write"])
        self.assertIn("Package: flickos-phone-screen\n", self.read("STORE_PINS"))
        # A new key that isn't valid.
        self.store.answers["/v1/link"] = (401, {"status": "add-invalid"})
        self.assertEqual(self.run_helper("purchases-add", stdin=OTHER_KEY + "\n")[0], 1)
        # The computer's key was turned off: the new one replaces it.
        self.store.answers["/v1/link"] = (409, {"status": "replace"})
        self.store.answers["/v1/key"] = valid("write")
        status, out = self.run_helper("purchases-add", stdin=OTHER_KEY + "\n")
        self.assertEqual(status, 0, out)
        self.assertNotIn("added to the key already", out)
        self.assertIn(f"password {OTHER_KEY}\n", self.read("STORE_AUTH"))
        self.assertEqual(self.store.logins()[-1], f"key:{OTHER_KEY}")
        self.assertEqual(json.loads(self.read("PURCHASES_FILE"))["key"], "nnnn")

    def test_the_check(self):
        self.store.answers["/v1/key"] = valid("notes", "write", "phone-screen")
        self.assertEqual(self.run_helper("purchases-add", stdin=KEY + "\n")[0], 0)
        self.assertFalse(os.path.exists(self.paths["STORE_PINS"]))       # it holds every app
        asked = len(self.store.requests)
        # Within a day: no request.
        self.assertEqual(self.run_helper("purchases-check"), (0, ""))
        self.assertEqual(len(self.store.requests), asked)
        # The day after: a linked key's app was refunded.
        self.store.answers["/v1/key"] = valid("notes", "phone-screen")
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            helper.check_purchases(KEY, now=datetime.datetime.now().astimezone() + datetime.timedelta(hours=21))
        self.assertEqual(len(self.store.requests), asked + 1)
        self.assertIn("Package: flickos-write\n", self.read("STORE_PINS"))
        # The key turned off: every app is pinned, the files stay, one notice.
        self.store.answers["/v1/key"] = (401, {"status": "revoked"})
        status, out = self.run_helper("purchases-check", "--now")
        self.assertEqual((status, out.strip()), (0, helper.KEY_TURNED_OFF))
        self.assertIn("Package: flickos-notes flickos-phone-screen flickos-write\n", self.read("STORE_PINS"))
        self.assertEqual(json.loads(self.read("PURCHASES_FILE"))["status"], "revoked")
        self.assertTrue(os.path.exists(self.paths["STORE_AUTH"]))
        self.assertEqual(self.run_helper("purchases-check", "--now"), (0, ""))     # said once
        # No answer (offline, the store down) changes nothing.
        before = self.read("PURCHASES_FILE"), self.read("STORE_PINS")
        self.store.answers["/v1/key"] = (503, {})
        self.assertEqual(self.run_helper("purchases-check", "--now")[0], 0)
        with mock.patch.object(helper, "STORE_URL", "http://127.0.0.1:9"):
            self.assertEqual(self.run_helper("purchases-check", "--now")[0], 0)
        self.assertEqual((self.read("PURCHASES_FILE"), self.read("STORE_PINS")), before)
        # A new app in the store's lists is pinned at the next update, without a request.
        self.store.answers["/v1/key"] = valid("notes", "write", "phone-screen")
        self.assertEqual(self.run_helper("purchases-check", "--now")[0], 0)
        self.assertFalse(os.path.exists(self.paths["STORE_PINS"]))
        self.available.add("flickos-trail")
        asked = len(self.store.requests)
        self.assertEqual(self.run_helper("purchases-check")[0], 0)
        self.assertEqual(len(self.store.requests), asked)
        self.assertIn("Package: flickos-trail\n", self.read("STORE_PINS"))

    def test_remove(self):
        self.store.answers["/v1/key"] = valid("notes")
        self.assertEqual(self.run_helper("purchases-add", stdin=KEY + "\n")[0], 0)
        status, out = self.run_helper("purchases-remove")
        self.assertEqual(status, 0)
        self.assertIn("stay installed", out)
        self.assertFalse(any(os.path.exists(path) for path in self.paths.values()))
        self.assertEqual(self.run_helper("purchases-remove"), (0, "There is no key on this computer.\n"))
        # Without a key the check only deletes stale pins.
        os.makedirs(os.path.dirname(self.paths["STORE_PINS"]), exist_ok=True)
        with open(self.paths["STORE_PINS"], "w") as f:
            f.write(helper.pins_text({"flickos-notes"}))
        self.assertEqual(self.run_helper("purchases-check"), (0, ""))
        self.assertFalse(os.path.exists(self.paths["STORE_PINS"]))
        self.assertEqual(len(self.store.requests), 1)

    def test_files_that_arent_flickos(self):
        os.makedirs(os.path.dirname(self.paths["STORE_AUTH"]))
        with open(self.paths["STORE_AUTH"], "w") as f:
            f.write("machine store.flickos.org login me password mine\n")
        self.store.answers["/v1/key"] = valid("notes")
        status, out = self.run_helper("purchases-add", stdin=KEY + "\n")
        self.assertEqual(status, 1)
        self.assertIn("isn't FlickOS's", out)
        self.assertEqual(self.run_helper("purchases-remove")[0], 1)
        with open(self.paths["STORE_AUTH"]) as f:
            self.assertEqual(f.read(), "machine store.flickos.org login me password mine\n")

    def test_store_packages_from_apts_lists(self):
        lists = os.path.join(self.tmp, "lists")
        os.makedirs(lists)
        packages = os.path.join(lists, "store_dists_trixie-store_main_binary-amd64_Packages")
        with gzip.open(packages + ".gz", "wt") as f:
            f.write("Package: flickos-notes\nVersion: 1.0\n\nPackage: flickos-write\nVersion: 1.0\n\n"
                    "Package: Bad;Name\n")
        apt_get = os.path.join(self.tmp, "apt-get")
        with open(apt_get, "w") as f:
            f.write(f'#!/bin/sh\nprintf "%s|" "$@" > {self.tmp}/args\necho {packages}\n'
                    f'echo {lists}/missing_Packages\n')
        apt_helper = os.path.join(self.tmp, "apt-helper")
        with open(apt_helper, "w") as f:
            f.write('#!/bin/sh\n[ "$1" = cat-file ] && exec zcat "$2"\n')
        for path in (apt_get, apt_helper):
            os.chmod(path, 0o755)
        with mock.patch.object(helper, "APT_GET", apt_get), mock.patch.object(helper, "APT_HELPER", apt_helper):
            self.assertEqual(REAL_STORE_PACKAGES(), {"flickos-notes", "flickos-write"})
        with open(os.path.join(self.tmp, "args")) as f:
            self.assertEqual(f.read(), "indextargets|--format|$(FILENAME)|Created-By: Packages|Origin: FlickOS|"
                                       "Label: FlickOS Store|")

    @unittest.skipUnless(shutil.which("apt-cache"), "apt is not installed")
    def test_apt_reads_the_files(self):
        """The pins and the sources entry as apt parses them: no error or warning."""
        etc = os.path.join(self.tmp, "etc")
        for name in ("preferences.d", "sources.list.d", "apt.conf.d"):
            os.makedirs(os.path.join(etc, name))
        with open(os.path.join(etc, "preferences.d", "flickos-store"), "w") as f:
            f.write(helper.pins_text({"flickos-notes", "flickos-write"}))
        with open(os.path.join(etc, "sources.list.d", "flickos-store.sources"), "w") as f:
            f.write(helper.store_sources_text("trixie"))
        state = os.path.join(self.tmp, "state")
        os.makedirs(os.path.join(state, "lists", "partial"))
        status = os.path.join(self.tmp, "status")
        open(status, "w").close()
        config = os.path.join(self.tmp, "apt.conf")
        with open(config, "w") as f:
            f.write(f'Dir::Etc "{etc}";\nDir::Etc::sourcelist "/dev/null";\nDir::State "{state}";\n'
                    f'Dir::State::status "{status}";\nDir::Cache "{self.tmp}/cache";\n')
        # A pin without its priority is an error of apt-cache policy (tried).
        result = subprocess.run(["apt-cache", "policy"], env=dict(os.environ, APT_CONFIG=config),
                                capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        result = subprocess.run(["apt-get", "update", "--print-uris"], env=dict(os.environ, APT_CONFIG=config),
                                capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn(f"'{self.store.url}/apt/dists/trixie-store/InRelease'", result.stdout)


class PurchasesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-control-purchases-")
        self.addCleanup(shutil.rmtree, self.tmp)
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                                           "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
                                           "XDG_CONFIG_DIRS": os.path.join(self.tmp, "xdg")})
        env.start()
        self.addCleanup(env.stop)
        self.file = os.path.join(self.tmp, "purchases.json")
        for name, value in (("PURCHASES_FILE", self.file), ("live_session", lambda: False),
                            ("SYSTEM_CONF_DIR", os.path.join(self.tmp, "etc")), ("SITE_CONF_DIR", os.path.join(self.tmp, "site"))):
            patcher = mock.patch.object(fc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def entries(self):
        return [(e["owner"], e["key"], e["old"], e["new"]) for e in fc.read_history()]

    def purchases(self, key="qrst", status="valid", products=("notes",)):
        with open(self.file, "w") as f:
            json.dump({"v": 1, "key": key, "status": status, "products": list(products),
                       "packages": [f"flickos-{p}" for p in products], "checked": "2026-11-09T10:00:00+08:00"}, f)

    def run_main(self, *args, stdin="", helper_status=0):
        """fc.main with a stand-in pkexec helper that writes PURCHASES_FILE."""
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs.get("input")))
            if helper_status == 0 and command[-1] == "purchases-add":
                self.purchases()
            elif helper_status == 0 and command[-1] == "purchases-remove":
                os.unlink(self.file)
            return subprocess.CompletedProcess(command, helper_status, "Done.\n" if helper_status == 0 else "",
                                               "" if helper_status == 0 else "control-helper: no\n")

        with mock.patch.object(fc.subprocess, "run", side_effect=fake_run), \
                mock.patch("sys.stdin", io.StringIO(stdin)), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            status = fc.main(["purchases", *args])
        return status, out.getvalue() + err.getvalue(), calls

    def test_list(self):
        self.assertEqual(self.run_main("list")[:2], (0, "No key on this computer.\n"))
        self.purchases(products=("notes", "phone-screen"))
        status, out, calls = self.run_main("list")
        self.assertEqual((status, calls), (0, []))
        self.assertEqual(out, "key\t…qrst\nstatus\tvalid\nproducts\tNotes, Phone Screen\n"
                              "checked\t2026-11-09T10:00:00+08:00\n")

    def test_add_and_undo(self):
        status, out, calls = self.run_main("add", "--stdin", stdin=KEY.upper() + "\n")
        self.assertEqual(status, 0, out)
        # The key on the helper's standard input, never in its arguments.
        self.assertEqual(calls, [(["pkexec", fc.HELPER, "purchases-add"], KEY + "\n")])
        self.assertEqual(self.entries(), [("flickos-control", "purchases", "none", "qrst")])
        change = fc.shape_history(fc.read_history())[0]
        self.assertTrue(change.undoable)
        self.assertEqual(fc.undo_commands(change), [[*fc.SELF, "purchases", "remove"]])
        self.assertEqual(fc.describe(change, {})[0], "Key for bought apps: key ending in qrst")
        self.assertEqual(fc.current_value(change), "qrst")
        self.assertFalse(fc.restorable(change))         # it needs the password
        with open(fc.history_path()) as f:
            self.assertNotIn(KEY[:-4], f.read())
        status, _, calls = self.run_main("remove")
        self.assertEqual((status, calls), (0, [(["pkexec", fc.HELPER, "purchases-remove"], None)]))
        self.assertEqual(self.entries()[-1], ("flickos-control", "purchases", "qrst", "none"))
        # A removed key isn't kept, so its removal can't be undone.
        self.assertFalse(fc.can_undo(fc.Change("1", None, "flickos-control", "purchases", "qrst", "none")))

    def test_add_refused_before_the_password(self):
        status, out, calls = self.run_main("add", "--stdin", stdin="1234\n")
        self.assertEqual((status, calls), (1, []))
        self.assertIn(fc.KEY_REFUSED, out)
        with mock.patch.object(fc, "live_session", lambda: True):
            status, out, calls = self.run_main("add", "--stdin", stdin=KEY + "\n")
        self.assertEqual((status, calls), (1, []))
        status, out, calls = self.run_main("add", "--stdin", stdin=KEY + "\n", helper_status=126)
        self.assertEqual(status, 1)
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.run_main("list", "--stdin")[0], 2)

    def test_claim(self):
        answers = [(None, {}), (200, {"status": "pending"}),
                   (200, {"status": "ready", "key": KEY.upper(), "products": ["notes"]})]
        posts, sleeps = [], []

        def post(path, body):
            posts.append((path, body))
            return answers.pop(0)

        self.assertEqual(fc.claim_key("c" * 32, sleep=sleeps.append, post=post), KEY)
        self.assertEqual(posts, [("/v1/claim", {"claim": "c" * 32})] * 3)
        self.assertEqual(sleeps, [fc.CLAIM_SECONDS] * 2)
        with self.assertRaisesRegex(fc.ControlError, "refunded"):
            fc.claim_key("c" * 32, sleep=sleeps.append, post=lambda *_: (410, {"status": "refunded"}))
        # The buy page in the browser collected it first (the store's claim race).
        with self.assertRaisesRegex(fc.ControlError, "already handed out, to the buy page"):
            fc.claim_key("c" * 32, sleep=sleeps.append, post=lambda *_: (409, {"status": "collected"}))
        with self.assertRaisesRegex(fc.ControlError, "No payment arrived"):
            fc.claim_key("c" * 32, wait=0, sleep=sleeps.append, post=lambda *_: (200, {"status": "pending"}))
        # A key the helper didn't take is shown, since the store hands it out once.
        with mock.patch.object(fc, "claim_key", return_value=KEY):
            status, out, calls = self.run_main("claim", "--stdin", stdin="c" * 32 + "\n", helper_status=126)
        self.assertEqual(status, 1)
        self.assertIn("Waiting for your payment…", out)
        self.assertIn(f"Keep it, and add it later with Add Key…: {KEY}", out)
        self.assertEqual(calls, [(["pkexec", fc.HELPER, "purchases-add"], KEY + "\n")])
        with mock.patch.object(fc, "claim_key", return_value=KEY):
            status, out, _ = self.run_main("claim", "--stdin", stdin="c" * 32 + "\n")
        self.assertEqual(status, 0)
        self.assertNotIn(KEY, out)
        for args, stdin in ((("claim",), "c" * 32), (("claim", "--stdin"), "short")):
            self.assertEqual(self.run_main(*args, stdin=stdin)[0], 2)

    def test_claim_asks_the_store(self):
        store = StandInStore(self)
        store.answers["/v1/claim"] = (200, {"status": "ready", "key": KEY, "products": ["notes"]})
        with mock.patch.object(fc, "STORE_URL", store.url):
            self.assertEqual(fc.claim_key("c" * 32, sleep=lambda _s: None), KEY)
        self.assertEqual(store.requests, [("POST", "/v1/claim", None, json.dumps({"claim": "c" * 32}))])

    def test_notice_of_a_turned_off_key(self):
        sent = []
        with mock.patch.object(fc, "notifications_running", return_value=True), \
                mock.patch.object(fc.shutil, "which", return_value="/usr/bin/notify-send"), \
                mock.patch.object(fc.subprocess, "run", side_effect=lambda c, **_: sent.append(c)):
            fc.purchases_notice()               # no key
            self.purchases()
            fc.purchases_notice()               # a valid key
            self.purchases(status="revoked")
            fc.purchases_notice()
            fc.purchases_notice()               # once per key
            self.purchases(key="nnnn", status="revoked")
            fc.purchases_notice()
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0][-1], fc.KEY_TURNED_OFF)

    def test_settings_search_finds_the_row(self):
        words = fc.SEARCH_KEYWORDS["updates"].split()
        for word in ("purchase", "key", "buy", "bought"):
            self.assertIn(word, words)


if __name__ == "__main__":
    unittest.main()
