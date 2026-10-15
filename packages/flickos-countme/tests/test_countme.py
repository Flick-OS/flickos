"""Tests for usr/bin/flickos-countme and countme-helper. Run: python3 -m unittest discover -s tests"""

import argparse
import contextlib
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(PACKAGE, path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


cm = load("flickos_countme", "usr/bin/flickos-countme")
helper = load("countme_helper", "usr/libexec/flickos/countme-helper")

DAY = datetime.date(2026, 9, 24)          # a Thursday in 2026-W39


class Tree(unittest.TestCase):
    """A temporary /etc/flickos/countme, release file, /proc and state dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.conf = os.path.join(root, "countme")
        self.state = os.path.join(root, "state")
        os.mkdir(self.state)
        os.mkdir(os.path.join(root, "proc"))
        self.write("release", 'FLICKOS_NAME="FlickOS"\nFLICKOS_VERSION="2.0"\n')
        self.cmdline("BOOT_IMAGE=/vmlinuz root=UUID=x quiet splash")
        for name, value in (("CONF", self.conf), ("RELEASE", os.path.join(root, "release")),
                            ("PROC", os.path.join(root, "proc")), ("STATE_DIR", self.state),
                            ("URL", "https://count.example/v1/countme")):
            patcher = mock.patch.object(cm, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(cm, "today_utc", lambda: DAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, text):
        with open(os.path.join(self.tmp.name, name), "w", encoding="utf-8") as f:
            f.write(text)

    def cmdline(self, text):
        self.write("proc/cmdline", text + "\n")

    def run_cmd(self, dry_run=False, sender=None):
        sent = []
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cm.cmd_run(argparse.Namespace(dry_run=dry_run), sender=sender or sent.append)
        self.assertEqual(code, 0)
        return sent, out.getvalue() + err.getvalue()


class AgeTest(unittest.TestCase):
    def test_buckets(self):
        for days, age in ((0, 1), (6, 1), (7, 2), (27, 2), (28, 3), (167, 3), (168, 4), (2000, 4)):
            self.assertEqual(cm.age_bucket(DAY - datetime.timedelta(days=days), DAY), age, days)

    def test_only_the_first_count_is_the_install(self):
        self.assertEqual(cm.age_bucket(DAY - datetime.timedelta(days=2), DAY, first=False), 2)
        self.assertEqual(cm.age_bucket(DAY - datetime.timedelta(days=200), DAY, first=False), 4)

    def test_install_date_in_the_future_is_first_week(self):
        self.assertEqual(cm.age_bucket(DAY + datetime.timedelta(days=3), DAY), 1)

    def test_iso_week(self):
        self.assertEqual(cm.week_of(DAY), "2026-W39")
        self.assertEqual(cm.week_of(datetime.date(2027, 1, 1)), "2026-W53")


class ConfTest(Tree):
    def test_missing_file_means_enabled(self):
        self.assertTrue(cm.enabled(cm.read_conf()))

    def test_parse_and_disable(self):
        self.write("countme", '# comment\nEnabled="no"\nInstalled=2026-09-01\n\nnonsense\n')
        conf = cm.read_conf()
        self.assertFalse(cm.enabled(conf))
        self.assertEqual(cm.install_date(conf), datetime.date(2026, 9, 1))

    def test_bad_install_date_ignored(self):
        self.write("countme", "Installed=yesterday\n")
        self.assertIsNone(cm.install_date(cm.read_conf()))

    def test_version(self):
        self.assertEqual(cm.flickos_version(), "2.0")

    def test_request_has_only_version_and_age(self):
        url = cm.request_url("https://count.example/v1/countme", "2.0", 3)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query, {"version": ["2.0"], "age": ["3"]})


class RunTest(Tree):
    def test_sends_once_a_week(self):
        self.write("countme", "Installed=2026-09-20\n")
        sent, out = self.run_cmd()
        self.assertEqual(sent, ["https://count.example/v1/countme?version=2.0&age=1"])
        self.assertIn("2026-W39", out)
        sent, out = self.run_cmd()
        self.assertEqual(sent, [])
        self.assertIn("Already counted", out)

    def test_next_week_is_not_the_install_again(self):
        self.write("countme", "Installed=2026-09-23\n")
        self.run_cmd()
        with mock.patch.object(cm, "today_utc", lambda: DAY + datetime.timedelta(days=7)):
            sent, _ = self.run_cmd()
        self.assertEqual(sent, ["https://count.example/v1/countme?version=2.0&age=2"])

    def test_failure_not_recorded(self):
        def fail(_url):
            raise cm.CountmeError("not sent: offline")

        _, out = self.run_cmd(sender=fail)
        self.assertIn("tried again", out)
        self.assertIsNone(cm.read_state(cm.LAST_WEEK))
        sent, _ = self.run_cmd()
        self.assertEqual(len(sent), 1)

    def test_live_session_sends_and_writes_nothing(self):
        self.cmdline("BOOT_IMAGE=/live/vmlinuz boot=live components quiet")
        sent, out = self.run_cmd()
        self.assertEqual(sent, [])
        self.assertIn("live session", out)
        self.assertEqual(os.listdir(self.state), [])

    def test_disabled(self):
        self.write("countme", "Enabled=no\n")
        sent, out = self.run_cmd()
        self.assertEqual(sent, [])
        self.assertIn("turned off", out)

    def test_no_server(self):
        with mock.patch.object(cm, "URL", ""):
            sent, out = self.run_cmd()
        self.assertEqual(sent, [])
        self.assertIn("no server", out)

    def test_url_override(self):
        self.write("countme", "Url=http://127.0.0.1:8787/v1/countme\n")
        with mock.patch.object(cm, "URL", ""):
            sent, _ = self.run_cmd()
        self.assertEqual(sent, ["http://127.0.0.1:8787/v1/countme?version=2.0&age=1"])

    def test_first_run_date_used_without_installed(self):
        self.run_cmd()
        self.assertEqual(cm.read_state(cm.FIRST_RUN), DAY.isoformat())
        with mock.patch.object(cm, "today_utc", lambda: DAY + datetime.timedelta(days=30)):
            sent, _ = self.run_cmd()
        self.assertEqual(sent, ["https://count.example/v1/countme?version=2.0&age=3"])

    def test_dry_run_sends_and_writes_nothing(self):
        sent, out = self.run_cmd(dry_run=True)
        self.assertEqual(sent, [])
        self.assertIn("Would send: GET https://count.example/v1/countme?version=2.0&age=1", out)
        self.assertEqual(os.listdir(self.state), [])

    def test_run_without_state_dir_says_how(self):
        with mock.patch.object(cm, "STATE_DIR", os.path.join(self.tmp.name, "missing")):
            with self.assertRaisesRegex(cm.CountmeError, "systemctl start flickos-countme"):
                self.run_cmd()
            sent, out = self.run_cmd(dry_run=True)
        self.assertEqual(sent, [])
        self.assertIn("Would send:", out)

    def test_status_json(self):
        self.write("countme", "Enabled=no\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cm.cmd_status(None)
        state = json.loads(out.getvalue())
        self.assertEqual((state["enabled"], state["sending"], state["reason"]), (False, False, "turned off"))
        self.assertEqual(state["this_week"], "2026-W39")
        self.assertIsNone(state["last_week"])


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = os.path.join(self.tmp.name, "flickos", "countme")

    def read(self):
        with open(self.conf, encoding="utf-8") as f:
            return f.read()

    def test_creates_file(self):
        helper.change("Enabled", "no", self.conf)
        self.assertTrue(self.read().startswith("#"))
        self.assertFalse(cm.enabled(cm.read_conf(self.conf)))

    def test_keeps_other_lines(self):
        os.makedirs(os.path.dirname(self.conf))
        with open(self.conf, "w", encoding="utf-8") as f:
            f.write("# mine\nInstalled=2026-01-01\nEnabled=no\nEnabled=no\n")
        helper.change("Enabled", "yes", self.conf)
        self.assertEqual(self.read(), "# mine\nInstalled=2026-01-01\nEnabled=yes\n")

    def test_verbs(self):
        self.assertEqual(set(helper.VERBS), {"on", "off", "installed"})
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(helper.main(["nonsense"]), 2)
            self.assertEqual(helper.main([]), 2)

    def test_policy_has_an_action_per_toggle_verb(self):
        with open(os.path.join(PACKAGE, "usr/share/polkit-1/actions/org.flickos.countme.policy"),
                  encoding="utf-8") as f:
            policy = f.read()
        for verb in ("on", "off"):
            self.assertIn(f'<annotate key="org.freedesktop.policykit.exec.argv1">{verb}</annotate>', policy)


if __name__ == "__main__":
    unittest.main()
