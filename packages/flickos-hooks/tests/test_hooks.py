"""Tests for usr/bin/flickos-hooks. Run: python3 -m unittest discover -s tests

Every test runs with HOME, XDG_CONFIG_HOME and XDG_RUNTIME_DIR in a temporary
folder and no FLICKOS_* variable: never the build host's hooks, log or session.
The hooks are small shell scripts written into that folder."""

import contextlib
import glob
import io
import importlib.machinery
import importlib.util
import os
import re
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
PACKAGES = os.path.dirname(PACKAGE)
PROGRAM = os.path.join(PACKAGE, "usr/bin/flickos-hooks")

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_hooks", PROGRAM)
fh = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fh)


class TempSession(unittest.TestCase):
    """A session in a temporary folder, with no FLICKOS_* variable."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="flickos-hooks-test-")
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.config, self.runtime, self.home = (os.path.join(root, name) for name in ("config", "run", "home"))
        for folder in (self.config, self.runtime, self.home):
            os.makedirs(folder, mode=0o700)
        env = {key: value for key, value in os.environ.items() if not key.startswith(("FLICKOS_", "XDG_"))}
        env.update(HOME=self.home, XDG_CONFIG_HOME=self.config, XDG_RUNTIME_DIR=self.runtime)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Quick limits: a test of a timeout must not take 35 s.
        for name, value in (("HOOK_SECONDS", 1), ("KILL_SECONDS", 1), ("LOCK_SECONDS", 0.3)):
            patch = mock.patch.object(fh, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def hook(self, event, name, body="", mode=0o755):
        """Write a hook that runs body (shell) and return its path."""
        path = os.path.join(self.config, "flickos", "hooks", event + ".d", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, mode)
        return path

    def out(self, name):
        return os.path.join(self.home, name)

    def read(self, name):
        with open(self.out(name), encoding="utf-8") as f:
            return f.read()

    def log(self):
        with open(os.path.join(self.runtime, "flickos", fh.LOG_FILE), encoding="utf-8") as f:
            return f.read()

    def main(self, *argv):
        """(exit code, stdout, stderr) of main(argv)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fh.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class RunTest(TempSession):
    def test_runs_every_hook_in_name_order(self):
        self.hook("locked", "20-second", f'echo second >> {self.out("order")}')
        self.hook("locked", "10-first", f'echo first >> {self.out("order")}')
        self.hook("locked", "30-third.sh", f'echo third >> {self.out("order")}')
        self.assertEqual(self.main("run", "locked")[0], 0)
        self.assertEqual(self.read("order"), "first\nsecond\nthird\n")

    def test_a_failing_hook_does_not_stop_the_rest(self):
        self.hook("locked", "10-fails", "echo oops; exit 3")
        self.hook("locked", "20-works", f"touch {self.out('works')}")
        self.main("run", "locked")
        self.assertTrue(os.path.exists(self.out("works")))
        log = self.log()
        self.assertRegex(log, r"locked 10-fails: started")
        self.assertRegex(log, r"locked 10-fails: exit 3 in ")
        self.assertIn("oops\n", log)
        self.assertRegex(log, r"locked 20-works: exit 0 in ")

    def test_what_a_hook_sees(self):
        self.hook("woke", "10-env", f'pwd > {self.out("pwd")}; env | sort > {self.out("env")}; '
                                    f'cat > {self.out("stdin")}')
        env = {"FLICKOS_IDLE": "1", "FLICKOS_LAYOUT": "redmond", "FLICKOS_PHONE_NAME": "not an woke value",
               "WAYLAND_DISPLAY": "wayland-9", "KEEP_ME": "yes"}
        with mock.patch.dict(os.environ, env):
            self.main("run", "woke")
        seen = dict(line.split("=", 1) for line in self.read("env").splitlines() if "=" in line)
        self.assertEqual(seen["FLICKOS_EVENT"], "woke")
        self.assertEqual(seen["FLICKOS_HOOK"], "1")
        self.assertEqual(seen["WAYLAND_DISPLAY"], "wayland-9")
        self.assertEqual(seen["KEEP_ME"], "yes")
        self.assertEqual({key for key in seen if key.startswith("FLICKOS_")}, {"FLICKOS_EVENT", "FLICKOS_HOOK"})
        self.assertEqual(os.path.realpath(self.read("pwd").strip()), os.path.realpath(self.home))
        self.assertEqual(self.read("stdin"), "")

    def test_values_the_event_carries_arrive_and_others_do_not(self):
        event = {"phone-test": (("PHONE_ID", "PHONE_NAME"), "x")}
        with mock.patch.dict(fh.EVENTS, event):
            self.hook("phone-test", "10-env", f'env | sort > {self.out("env")}')
            with mock.patch.dict(os.environ, {"FLICKOS_PHONE_ID": "abc", "FLICKOS_PHONE_NAME": "Jon's $(phone)",
                                              "FLICKOS_SECRET": "no"}):
                self.main("run", "phone-test")
        seen = dict(line.split("=", 1) for line in self.read("env").splitlines() if "=" in line)
        self.assertEqual(seen["FLICKOS_PHONE_ID"], "abc")
        self.assertEqual(seen["FLICKOS_PHONE_NAME"], "Jon's $(phone)")
        self.assertNotIn("FLICKOS_SECRET", seen)

    def test_not_executable_is_logged_and_not_run(self):
        self.hook("locked", "10-not-executable", f"touch {self.out('ran')}", mode=0o644)
        self.main("run", "locked")
        self.assertFalse(os.path.exists(self.out("ran")))
        self.assertIn("10-not-executable: not run, not executable (chmod +x ", self.log())

    def test_ignored_files(self):
        for name in (".hidden", "10-backup~", "10-old.bak", "10-conf.dpkg-new", "10-conf.dpkg-old"):
            self.hook("locked", name, f"touch {self.out('ran')}")
        os.mkdir(os.path.join(self.config, "flickos", "hooks", "locked.d", "a-folder"))
        self.main("run", "locked")
        self.assertFalse(os.path.exists(self.out("ran")))
        self.assertEqual({state for _name, _path, state in fh.find_hooks("locked")}, {"ignored"})

    def test_a_symlink_to_a_script_is_a_hook(self):
        target = self.hook("elsewhere", "script", f"touch {self.out('ran')}")
        folder = os.path.join(self.config, "flickos", "hooks", "locked.d")
        os.makedirs(folder)
        os.symlink(target, os.path.join(folder, "10-link"))
        self.main("run", "locked")
        self.assertTrue(os.path.exists(self.out("ran")))

    def test_a_script_without_a_shebang_is_a_message(self):
        path = os.path.join(self.config, "flickos", "hooks", "locked.d", "10-binary")
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as f:
            f.write(b"\x00\x01 not a program")
        os.chmod(path, 0o755)
        self.main("run", "locked")
        self.assertIn("10-binary: couldn't start", self.log())

    def test_nothing_without_hooks(self):
        self.assertEqual(self.main("run", "locked")[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "flickos")))      # not even a log

    def test_unknown_event(self):
        code, _out, err = self.main("run", "lunch")
        self.assertEqual(code, 2)
        self.assertIn("no event called lunch", err)

    def test_not_in_the_plain_session_and_not_from_a_hook(self):
        self.hook("locked", "10-ran", f"touch {self.out('ran')}")
        for variable in ("FLICKOS_PLAIN", "FLICKOS_HOOK"):
            with self.subTest(variable), mock.patch.dict(os.environ, {variable: "1"}):
                self.assertEqual(self.main("run", "locked")[0], 0)
                self.assertFalse(os.path.exists(self.out("ran")))

    def test_hooks_do_not_start_hooks(self):
        """A hook runs with FLICKOS_HOOK, so the fire() of a program it runs does nothing."""
        self.hook("locked", "10-nested", f'env | grep -q "^FLICKOS_HOOK=1$" && touch {self.out("marked")}')
        self.main("run", "locked")
        self.assertTrue(os.path.exists(self.out("marked")))

    def test_a_hook_that_hangs_is_stopped_with_its_children(self):
        self.hook("locked", "10-hangs", f"sleep 30 & echo $! > {self.out('child')}; wait")
        self.hook("locked", "20-after", f"touch {self.out('after')}")
        started = time.monotonic()
        self.main("run", "locked")
        self.assertLess(time.monotonic() - started, 5)
        self.assertRegex(self.log(), r"10-hangs: stopped after 1 s")
        self.assertTrue(os.path.exists(self.out("after")))
        child = int(self.read("child"))
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)

    def test_a_hook_that_ignores_sigterm_is_killed(self):
        self.hook("locked", "10-stubborn", "trap '' TERM; while :; do :; done")
        started = time.monotonic()
        self.main("run", "locked")
        self.assertLess(time.monotonic() - started, 5)
        self.assertRegex(self.log(), r"10-stubborn: stopped after 1 s")

    def test_a_hook_killed_by_a_signal_is_said_so(self):
        self.hook("locked", "10-killed", "kill -9 $$")
        self.main("run", "locked")
        self.assertIn("10-killed: killed by signal 9", self.log())

    def test_a_running_event_makes_the_next_wait_then_drop(self):
        self.hook("locked", "10-ran", f"touch {self.out('ran')}")
        with fh.event_lock("locked") as got:
            self.assertTrue(got)
            self.assertEqual(self.main("run", "locked")[0], 0)
        self.assertFalse(os.path.exists(self.out("ran")))
        self.assertIn("dropped: the last locked hooks were still running", self.log())
        self.main("run", "locked")
        self.assertTrue(os.path.exists(self.out("ran")))

    def test_a_burst_is_dropped_with_one_line(self):
        self.hook("locked", "10-count", f"echo x >> {self.out('count')}")
        with mock.patch.object(fh, "BURST_LIMIT", 3):
            for _ in range(7):
                self.main("run", "locked")
        self.assertEqual(self.read("count").count("x"), 3)
        self.assertEqual(self.log().count("dropped: more than 3 a minute"), 1)

    def test_burst_count_by_time(self):
        with mock.patch.object(fh, "BURST_LIMIT", 2), mock.patch.object(fh, "BURST_WINDOW", 60):
            self.assertEqual(fh.too_often("locked", now=1000), (False, False))
            self.assertEqual(fh.too_often("locked", now=1010), (False, False))
            self.assertEqual(fh.too_often("locked", now=1020), (True, True))
            self.assertEqual(fh.too_often("locked", now=1030), (True, False))       # said once
            self.assertEqual(fh.too_often("locked", now=1065), (False, False))      # 1000 aged out
            self.assertEqual(fh.too_often("woke", now=1065), (False, False))       # events count apart

    def test_the_log_is_private_and_starts_again_when_big(self):
        self.hook("locked", "10-a", "echo hello")
        self.main("run", "locked")
        path = os.path.join(self.runtime, "flickos", fh.LOG_FILE)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with mock.patch.object(fh, "LOG_BYTES", 10):
            self.main("run", "locked")
        self.assertEqual(self.log().count("10-a: started"), 1)

    def test_needs_a_session(self):
        self.hook("locked", "10-a", "true")
        with mock.patch.dict(os.environ):
            del os.environ["XDG_RUNTIME_DIR"]
            code, _out, err = self.main("run", "locked")
        self.assertEqual(code, 1)
        self.assertIn("XDG_RUNTIME_DIR isn't set", err)


class ReadingTest(TempSession):
    def test_events_is_a_tab_separated_table(self):
        code, out, _err = self.main("events")
        self.assertEqual(code, 0)
        rows = [line.split("\t") for line in out.splitlines()]
        self.assertEqual([row[0] for row in rows], list(fh.EVENTS))
        self.assertTrue(all(len(row) == 3 and row[2] for row in rows))
        self.assertEqual(list(fh.EVENTS), ["locked", "unlocked", "woke", "screens", "phone-connected",
                                           "phone-disconnected", "changed", "screenshot", "recording"])  # promised

    def test_every_value_of_every_event_is_an_upper_case_name(self):
        for event, (values, _meaning) in fh.EVENTS.items():
            for name in values:
                self.assertRegex(name, r"^[A-Z][A-Z0-9_]*$", event)

    def test_list_shows_states_and_typos(self):
        self.hook("locked", "10-ready", "true")
        self.hook("locked", "20-not-executable", "true", mode=0o644)
        self.hook("locked", "30~", "true")
        self.hook("lock", "10-typo", "true")            # no event called lock
        code, out, _err = self.main("list")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["locked\t10-ready\tready", "locked\t20-not-executable\tnot executable",
                                            "locked\t30~\tignored", "lock\t-\tno such event"])

    def test_list_with_no_hooks_says_so_on_stderr(self):
        code, out, err = self.main("list")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("no hooks in", err)

    def test_log(self):
        code, out, err = self.main("log")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("no hooks have run", err)
        self.hook("locked", "10-a", "echo hello")
        self.main("run", "locked")
        self.assertIn("locked 10-a: started", self.main("log")[1])


class TestCommandTest(TempSession):
    def test_runs_hooks_and_reports(self):
        self.hook("locked", "10-ok", f"touch {self.out('ok')}")
        code, _out, err = self.main("test", "locked")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.out("ok")))
        self.assertIn("running 10-ok", err)
        self.assertIn("10-ok: exit 0", err)

    def test_a_failing_hook_is_exit_1(self):
        self.hook("locked", "10-fails", "exit 1")
        self.hook("locked", "20-ok", f"touch {self.out('ok')}")
        self.assertEqual(self.main("test", "locked")[0], 1)
        self.assertTrue(os.path.exists(self.out("ok")))

    def test_not_executable_is_exit_1(self):
        self.hook("locked", "10-no", "true", mode=0o644)
        code, _out, err = self.main("test", "locked")
        self.assertEqual(code, 1)
        self.assertIn("10-no: not run, not executable", err)

    def test_values_and_the_environment_are_those_of_run(self):
        event = {"phone-test": (("PHONE_ID",), "x")}
        with mock.patch.dict(fh.EVENTS, event):
            self.hook("phone-test", "10-env", f'echo "$FLICKOS_EVENT $FLICKOS_PHONE_ID $FLICKOS_HOOK" > {self.out("seen")}')
            with mock.patch.dict(os.environ, {"FLICKOS_IDLE": "1"}):
                self.assertEqual(self.main("test", "phone-test", "PHONE_ID=a b")[0], 0)
        self.assertEqual(self.read("seen"), "phone-test a b 1\n")

    def test_works_in_the_plain_session_and_logs_nothing(self):
        self.hook("locked", "10-ok", f"touch {self.out('ok')}")
        with mock.patch.dict(os.environ, {"FLICKOS_PLAIN": "1"}):
            self.assertEqual(self.main("test", "locked")[0], 0)
        self.assertTrue(os.path.exists(self.out("ok")))
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "flickos")))

    def test_usage_errors_are_exit_2(self):
        self.assertEqual(self.main("test", "lunch")[0], 2)
        code, _out, err = self.main("test", "locked", "NOPE=1")
        self.assertEqual(code, 2)
        self.assertIn("locked has no value called NOPE", err)
        self.assertEqual(self.main("test", "locked", "FLICKOS_X")[0], 2)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            fh.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_no_hooks(self):
        code, _out, err = self.main("test", "locked")
        self.assertEqual(code, 0)
        self.assertIn("no hooks for locked", err)


class PackageTest(unittest.TestCase):
    def test_the_docstring_lists_every_command(self):
        for command in ("events", "list", "test", "log", "run"):
            self.assertRegex(fh.__doc__, rf"\n  {command}\b")

    @unittest.skipUnless(os.path.isdir(os.path.join(PACKAGES, "flickos-lock")), "not in a FlickOS checkout")
    def test_every_fire_is_the_same_contract(self):
        """Programs carry a fire() of their own (ADR-004): the same folder, the
        same marks, setsid -f, `flickos-hooks run EVENT`. A copy that drifts
        would break hooks for one owner only."""
        found = 0
        for path in sorted(glob.glob(os.path.join(PACKAGES, "*", "usr", "*", "*"))):
            if not os.path.isfile(path) or os.path.basename(path) == "flickos-hooks":
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if "def fire(" not in text:
                continue
            found += 1
            fire = text[text.index("def fire("):]
            end = re.search(r"\n(?=\S)", fire)         # the next unindented line ends the function
            fire = fire[:end.start()] if end else fire
            for needle in (fh.PLAIN_MARK, fh.HOOK_MARK, '"flickos", "hooks"', '".d"', '"setsid", "-f"',
                           '"flickos-hooks", "run"', "XDG_CONFIG_HOME"):
                self.assertIn(needle, fire, f"{path}: {needle}")
        self.assertGreaterEqual(found, 1)


if __name__ == "__main__":
    unittest.main()
