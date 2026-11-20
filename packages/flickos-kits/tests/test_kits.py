"""Tests for usr/bin/flickos-kits. Run: python3 -m unittest discover -s tests

They point every outside program (dpkg-query, git, flickos-software, rustup,
wl-copy) at stand-ins and $HOME at a temporary folder: they run on the
developer's own desktop and must never touch the real ~/.gitconfig or ~/.ssh.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_kits", os.path.join(PACKAGE, "usr/bin/flickos-kits"))
fk = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fk)


def result(stdout="", returncode=0, stderr=""):
    return types.SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def fake_dpkg(installed, versions=None):
    """A run() that answers dpkg-query -W for these package names (and their
    versions, 1.0-1 unless versions says)."""
    def run(args, **_kw):
        form = args[3]
        wanted = args[4:]
        if form.endswith("${Version}\n"):
            return result("".join(f"{'ii ' if p in installed else 'un '}\t{p}\t{(versions or {}).get(p, '1.0-1')}\n"
                                  for p in wanted))
        lines = [f"{'ii ' if p in installed else 'un '}\t{p}\n" for p in wanted]
        return result("".join(lines))
    return run


class QuietHome(unittest.TestCase):
    """HOME and XDG_* in a temporary folder, and no real runtime folder."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = mock.patch.dict(os.environ, {"HOME": self.home, "XDG_CONFIG_HOME": self.home + "/.config",
                                               "XDG_RUNTIME_DIR": self.home + "/run"})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(fk, "PROC", self.home + "/proc")
        patcher.start()
        self.addCleanup(patcher.stop)
        # Never the developer's terminal: a command that asks there (env new and
        # remove without --yes) would wait for an answer and hang the build.
        patcher = mock.patch.object(fk.sys, "stdin", io.StringIO(""))
        patcher.start()
        self.addCleanup(patcher.stop)


class TablesTest(unittest.TestCase):
    def test_kit_names_are_unique_and_in_categories(self):
        names = [k[0] for k in fk.KITS]
        self.assertEqual(len(names), len(set(names)))
        categories = {c[0] for c in fk.CATEGORIES}
        self.assertTrue(all(k[1] in categories for k in fk.KITS))

    def test_kits_match_the_kit_packages(self):
        """The window's words are the metainfo's, and each kit package exists (next to this one in the source tree)."""
        packages = os.path.join(PACKAGE, "..")
        if not os.path.isdir(os.path.join(packages, "flickos-kit-base")):
            self.skipTest("not in the source tree")
        for name, _category, title, summary in fk.KITS:
            path = os.path.join(packages, fk.PACKAGE.format(name), "usr/share/metainfo",
                                fk.APP.format(name) + ".metainfo.xml")
            root = ET.parse(path).getroot()
            self.assertEqual((root.findtext("name"), root.findtext("summary")), (title, summary), name)

    def test_steps_name_programs(self):
        self.assertEqual([s[0] for s in fk.STEPS], ["git", "ssh", "rust", "ports", "dhcp", "capture", "test-adapter"])

    def test_the_permission_sentence_is_softwares(self):
        """flickos-security.md ADR-S05: the same words in Software and here."""
        path = os.path.join(PACKAGE, "../flickos-software/usr/bin/flickos-software")
        if not os.path.exists(path):
            self.skipTest("not in the source tree")
        with open(path, encoding="utf-8") as f:
            software = re.search(r'^PERMISSION = "([^"]*)"', f.read(), re.M).group(1)
        self.assertEqual(fk.PERMISSION, software)

    def test_the_security_kits_are_folded(self):
        self.assertEqual([k[0] for k in fk.KITS if k[1] == "security"],
                         ["network", "web-testing", "passwords", "forensics", "reversing", "wireless"])
        self.assertEqual(fk.FOLDED, ("security",))


class InstalledTest(unittest.TestCase):
    def test_installed_packages(self):
        run = fake_dpkg({"flickos-kit-base"})
        self.assertEqual(fk.installed_packages(["flickos-kit-base", "flickos-kit-web"], run), {"flickos-kit-base"})
        self.assertEqual(fk.installed_packages([], run), set())

    def test_rows_in_the_tables_order(self):
        rows = fk.kit_rows(fake_dpkg({"flickos-kit-python"}))
        self.assertEqual([r[0] for r in rows], fk.kit_names())
        self.assertEqual([r[0] for r in rows if r[4]], ["python"])

    def test_missing_dpkg_is_a_message(self):
        def broken(*_a, **_k):
            raise OSError("no dpkg-query")
        with self.assertRaisesRegex(fk.KitsError, "couldn't read what is installed"):
            fk.installed_packages(["x"], broken)


class ListTest(QuietHome):
    def run_main(self, argv, installed=("flickos-kit-base",)):
        out = io.StringIO()
        with mock.patch.object(fk.subprocess, "run", fake_dpkg(set(installed))), contextlib.redirect_stdout(out):
            code = fk.main(argv)
        return code, out.getvalue()

    def test_list_lines(self):
        code, out = self.run_main(["list"])
        lines = [line.split("\t") for line in out.splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual([line[0] for line in lines], fk.kit_names())
        self.assertEqual({line[0]: line[1] for line in lines}["base"], "yes")
        self.assertEqual({line[0]: line[1] for line in lines}["web"], "no")
        self.assertTrue(all(len(line) == 4 for line in lines))

    def test_list_json(self):
        _code, out = self.run_main(["list", "--json", "--category", "development"])
        kits = json.loads(out)
        self.assertEqual([k["id"] for k in kits], [k[0] for k in fk.KITS if k[1] == "development"])
        self.assertEqual(kits[0]["package"], "flickos-kit-base")
        self.assertTrue(kits[0]["installed"])
        _code, out = self.run_main(["list", "--json", "--category", "classroom"])
        self.assertEqual([k["id"] for k in json.loads(out)], ["classroom", "study"])   # Q15, Q16: not developer kits

    def test_an_unknown_kit_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            fk.main(["install", "nope"])
        self.assertEqual(raised.exception.code, 2)


class PlanTest(unittest.TestCase):
    def test_plan_runs_software_with_the_kits_app_id(self):
        calls = []

        def run(args, **_kw):
            calls.append(args)
            return result(json.dumps({"packages": ["a", "b"], "size": 5}))
        plan = fk.get_plan("python", False, run)
        self.assertEqual(plan["packages"], ["a", "b"])
        self.assertEqual(calls[0][1:], ["plan", "--json", "io.github.dvbondoy.flickos.kits.python"])
        fk.get_plan("python", True, run)
        self.assertIn("--remove", calls[1])

    def test_a_refused_plan_says_why(self):
        run = lambda *_a, **_k: result("", 1, "flickos-software: Python isn't in FlickOS's package lists for this computer.\n")
        with self.assertRaisesRegex(fk.KitsError, "^Python isn't in FlickOS's package lists"):
            fk.get_plan("python", False, run)

    def test_unreadable_plan(self):
        with self.assertRaisesRegex(fk.KitsError, "can't be read"):
            fk.get_plan("web", False, lambda *_a, **_k: result("not json"))

    def test_plan_words(self):
        one, names = fk.plan_words({"packages": ["x"], "size": 3_000_000, "download": 1_000_000}, False)
        self.assertEqual(one, "This adds 1 package, which takes 3.0 MB. About 1.0 MB is downloaded.")
        many, names = fk.plan_words({"removes": ["b", "a"], "size": 150_000_000}, True)
        self.assertEqual(many, "This removes 2 packages and frees 150 MB.")
        self.assertEqual(names, ["a", "b"])

    def test_human_size(self):
        self.assertEqual([fk.human_size(n) for n in (0, 999, 1500, 2_500_000, 150_000_000, 1_400_000_000)],
                         ["0 B", "999 B", "2 kB", "2.5 MB", "150 MB", "1.4 GB"])


class ChangeTest(unittest.TestCase):
    @staticmethod
    def popen(lines, code, stderr=""):
        def start(args, **_kw):
            start.args = args
            return types.SimpleNamespace(stdout=iter(lines), stderr=io.StringIO(stderr), wait=lambda: code)
        return start

    def test_install_passes_events_through(self):
        events = []
        start = self.popen([json.dumps({"event": "progress", "percent": 40}) + "\n", "noise\n",
                            json.dumps({"event": "done"}) + "\n"], 0)
        self.assertEqual(fk.change("web", False, events.append, start), 0)
        self.assertEqual([e["event"] for e in events], ["progress", "done"])
        self.assertEqual(start.args[1:], ["install", "--json", "io.github.dvbondoy.flickos.kits.web"])

    def test_failure_reports_the_message(self):
        events = []
        start = self.popen([], 1, "flickos-software: The password was wrong.\n")
        self.assertEqual(fk.change("web", True, events.append, start), 1)
        self.assertEqual(events[-1], {"event": "failed", "message": "The password was wrong."})
        self.assertEqual(start.args[1], "remove")

    def test_unknown_kit(self):
        with self.assertRaises(fk.KitsError):
            fk.change("nope", False, lambda e: None)

    def test_missing_software(self):
        def broken(*_a, **_k):
            raise FileNotFoundError("no such file")
        with self.assertRaisesRegex(fk.KitsError, "can't run"):
            fk.change("web", False, lambda e: None, broken)


class GitTest(QuietHome):
    def test_values_and_unset(self):
        def run(args, **_kw):
            return result("Jon\n" if args[-1] == "user.name" else "", 0 if args[-1] == "user.name" else 1)
        self.assertEqual(fk.git_values(run), ("Jon", ""))

    def test_set_runs_git_config_global(self):
        calls = []
        fk.set_git("Jon", "jon@example.org", lambda args, **_k: calls.append(args) or result())
        self.assertEqual(calls, [["git", "config", "--global", "user.name", "Jon"],
                                 ["git", "config", "--global", "user.email", "jon@example.org"]])

    def test_empty_and_multiline_values_are_refused(self):
        run = mock.Mock()
        for name, email in (("", "a@b"), ("Jon", ""), ("Jon\nX", "a@b")):
            with self.assertRaises(fk.KitsError):
                fk.set_git(name, email, run)
        run.assert_not_called()

    def test_a_failing_git_says_why(self):
        with self.assertRaisesRegex(fk.KitsError, "^error: could not lock config file"):
            fk.set_git("Jon", "a@b", lambda *_a, **_k: result("", 255, "error: could not lock config file\n"))

    def test_setup_git_prints_and_sets_only_what_is_given(self):
        calls = []

        def run(args, **_kw):
            calls.append(args)
            return result("Old\n") if "--get" in args else result()
        out = io.StringIO()
        with mock.patch.object(fk.subprocess, "run", run), contextlib.redirect_stdout(out):
            self.assertEqual(fk.main(["setup", "git"]), 0)
            self.assertEqual(out.getvalue(), "Old\tOld\n")
            calls.clear()
            self.assertEqual(fk.main(["setup", "git", "--email", "new@example.org"]), 0)
        sets = [c for c in calls if "--get" not in c]
        self.assertEqual(sets, [["git", "config", "--global", "user.name", "Old"],
                                ["git", "config", "--global", "user.email", "new@example.org"]])


class SshTest(QuietHome):
    def make_key(self, name="id_ed25519"):
        os.makedirs(self.home + "/.ssh")
        with open(f"{self.home}/.ssh/{name}.pub", "w") as f:
            f.write("ssh-ed25519 AAAA test\n")

    def test_no_key(self):
        self.assertIsNone(fk.public_key_path())
        with self.assertRaisesRegex(fk.KitsError, "no SSH key"):
            fk.copy_public_key()

    def test_any_known_key_counts_and_is_not_replaced(self):
        self.make_key("id_rsa")
        self.assertEqual(fk.public_key_path(), self.home + "/.ssh/id_rsa.pub")
        with mock.patch.object(fk.subprocess, "call") as call, self.assertRaisesRegex(fk.KitsError, "key already"):
            fk.cmd_setup_ssh(types.SimpleNamespace(copy=False))
        call.assert_not_called()

    def test_making_a_key_runs_ssh_keygen_in_the_users_home(self):
        with mock.patch.object(fk.subprocess, "call", return_value=0) as call:
            self.assertEqual(fk.cmd_setup_ssh(types.SimpleNamespace(copy=False)), 0)
        call.assert_called_once_with(["ssh-keygen", "-t", "ed25519", "-f", self.home + "/.ssh/id_ed25519"])
        self.assertEqual(os.stat(self.home + "/.ssh").st_mode & 0o777, 0o700)

    def test_copy_uses_wl_copy(self):
        self.make_key()
        calls = []
        path = fk.copy_public_key(lambda name: "/usr/bin/" + name,
                                  lambda args, **kw: calls.append((args, kw["input"])) or result())
        self.assertEqual(path, self.home + "/.ssh/id_ed25519.pub")
        self.assertEqual(calls, [(["wl-copy"], b"ssh-ed25519 AAAA test\n")])

    def test_copy_without_wl_copy(self):
        self.make_key()
        with self.assertRaisesRegex(fk.KitsError, "wl-copy isn't installed"):
            fk.copy_public_key(lambda name: None)

    def test_terminal_command(self):
        self.assertEqual(fk.terminal_command(["rustup"], lambda n: "/x"), ["xdg-terminal-exec", "rustup"])
        with self.assertRaisesRegex(fk.KitsError, "no terminal"):
            fk.terminal_command(["rustup"], lambda n: None)


class SnapshotTest(QuietHome):
    def test_no_steps_without_a_kit(self):
        state = fk.snapshot(fake_dpkg(set()), lambda name: "/usr/bin/" + name)
        self.assertEqual(state["steps"], {})
        self.assertFalse(any(r[4] for r in state["kits"]))

    def test_steps_that_apply(self):
        def run(args, **kw):
            if args[0] == "dpkg-query":
                return fake_dpkg({"flickos-kit-base"})(args, **kw)
            if args[0] == "git":
                return result("Jon\n")
            return result("", 1)            # rustup: no toolchain
        programs = {"git", "rustup"}        # no ssh-keygen
        state = fk.snapshot(run, lambda name: "/usr/bin/" + name if name in programs else None)
        self.assertEqual(state["steps"], {"git": ("Jon", "Jon"), "rust": ""})

    def test_doctor_prints_each_state(self):
        state = {"kits": [("base", "development", "Developer Basics", "x", True)],
                 "steps": {"git": ("Jon", ""), "ssh": "/h/.ssh/id.pub", "rust": ""}}
        out = io.StringIO()
        with mock.patch.object(fk, "snapshot", return_value=state), mock.patch.object(fk, "control_value"), \
                contextlib.redirect_stdout(out):
            fk.control_value.return_value = None
            fk.cmd_doctor(None)
        lines = [line.split("\t") for line in out.getvalue().splitlines()]
        self.assertEqual(lines, [["kit base", "ok", ""], ["git", "missing", "Jon <>"],
                                 ["ssh", "ok", "/h/.ssh/id.pub"], ["rust", "missing", ""]])


def fake_control(values, fail=()):
    """A run() for flickos-control: `system KEY` prints values[KEY], `system KEY VALUE` records the call."""
    calls = []

    def run(args, **_kw):
        calls.append(args)
        if args[0] != fk.CONTROL:
            return result("", 1)
        key = args[2]
        if len(args) == 3:
            return result(values[key] + "\n") if key in values else result("", 1, "flickos-control: not here\n")
        if key in fail:
            return result("", 1, "flickos-control: control-helper: ufw is not installed\n")
        return result()
    run.calls = calls
    return run


class ControlTest(unittest.TestCase):
    """The two steps that change the computer go through flickos-control."""

    def test_control_value(self):
        run = fake_control({"firewall.local-ports": "8000/tcp"})
        self.assertEqual(fk.control_value("firewall.local-ports", run), "8000/tcp")
        self.assertIsNone(fk.control_value("containers.dhcp", run))

    def test_run_control_passes_the_value_and_reports_the_owners_message(self):
        run = fake_control({}, fail=("containers.dhcp",))
        fk.run_control("firewall.local-ports", "8000/tcp", run)
        self.assertEqual(run.calls, [[fk.CONTROL, "system", "firewall.local-ports", "8000/tcp"]])
        with self.assertRaisesRegex(fk.KitsError, "^ufw is not installed$"):
            fk.run_control("containers.dhcp", "on", run)

    def test_ports_value(self):
        self.assertEqual(fk.ports_value("8000/tcp  3000/udp,5000:5010/tcp"), "8000/tcp,3000/udp,5000:5010/tcp")
        self.assertEqual(fk.ports_value("   "), "off")
        for bad in ("8000", "http/tcp", "8000/tcp;ls", "8000/icmp"):
            with self.assertRaises(fk.KitsError, msg=bad):
                fk.ports_value(bad)

    def test_setup_ports_and_dhcp(self):
        run = fake_control({"firewall.local-ports": "off", "containers.dhcp": "off"})
        out = io.StringIO()
        with mock.patch.object(fk, "run_program", run), mock.patch.object(fk.subprocess, "run", run), \
                contextlib.redirect_stdout(out):
            self.assertEqual(fk.main(["setup", "ports"]), 0)
            self.assertEqual(fk.main(["setup", "ports", "8000/tcp", "3000/tcp"]), 0)
            self.assertEqual(fk.main(["setup", "ports", "off"]), 0)
            self.assertEqual(fk.main(["setup", "dhcp"]), 0)
            self.assertEqual(fk.main(["setup", "dhcp", "on"]), 0)
        self.assertEqual(out.getvalue(), "off\noff\n")
        changes = [c[2:] for c in run.calls if len(c) == 4]
        self.assertEqual(changes, [["firewall.local-ports", "8000/tcp,3000/tcp"], ["firewall.local-ports", "off"],
                                   ["containers.dhcp", "on"]])

    def test_a_bad_port_never_reaches_control(self):
        run = fake_control({})
        with mock.patch.object(fk.subprocess, "run", run), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fk.main(["setup", "ports", "http/tcp"]), 1)
        self.assertEqual(run.calls, [])

    def test_unavailable_settings_say_so(self):
        run = fake_control({})
        with mock.patch.object(fk.subprocess, "run", run), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fk.main(["setup", "ports"]), 1)
            self.assertEqual(fk.main(["setup", "dhcp"]), 1)
        self.assertIn("ufw", err.getvalue())
        self.assertIn("netavark", err.getvalue())

    def test_snapshot_shows_the_steps_that_apply(self):
        control = fake_control({"firewall.local-ports": "8000/tcp", "containers.dhcp": "off"})

        def run(args, **kw):
            if args[0] == "dpkg-query":
                return fake_dpkg({"flickos-kit-base", "flickos-kit-containers"})(args, **kw)
            if args[0] == fk.CONTROL:
                return control(args, **kw)
            return result("", 1)
        state = fk.snapshot(run, lambda name: "/usr/bin/" + name if name == fk.CONTROL else None)
        self.assertEqual(state["steps"], {"ports": "8000/tcp", "dhcp": "off"})

    def test_dhcp_needs_the_containers_kit(self):
        control = fake_control({"firewall.local-ports": "off", "containers.dhcp": "off"})

        def run(args, **kw):
            if args[0] == "dpkg-query":
                return fake_dpkg({"flickos-kit-base"})(args, **kw)
            return control(args, **kw)
        state = fk.snapshot(run, lambda name: "/usr/bin/" + name if name == fk.CONTROL else None)
        self.assertEqual(state["steps"], {"ports": "off"})

    def test_doctor_lines(self):
        state = {"kits": [], "steps": {"ports": "8000/tcp", "dhcp": "off"}}
        out = io.StringIO()
        with mock.patch.object(fk, "snapshot", return_value=state), mock.patch.object(fk, "control_value"), \
                contextlib.redirect_stdout(out):
            fk.control_value.return_value = "off"
            fk.cmd_doctor(None)
        self.assertEqual([line.split("\t") for line in out.getvalue().splitlines()],
                         [["ports", "ok", "8000/tcp"], ["dhcp", "off", ""]])


NMCLI = ("GENERAL.DEVICE:wlp3s0\nGENERAL.TYPE:wifi\nGENERAL.STATE:100 (connected)\n"
         "GENERAL.DBUS-PATH:/org/freedesktop/NetworkManager/Devices/3\nGENERAL.VENDOR:Qualcomm Atheros\n"
         "GENERAL.PRODUCT:AR9485 Wireless Network Adapter (AW-NE186H)\nGENERAL.PATH:pci-0000\\:03\\:00.0\n\n"
         "GENERAL.DEVICE:lo\nGENERAL.TYPE:loopback\nGENERAL.STATE:100 (connected (externally))\n"
         "GENERAL.DBUS-PATH:/org/freedesktop/NetworkManager/Devices/1\nGENERAL.VENDOR:\nGENERAL.PRODUCT:\n"
         "GENERAL.PATH:\n\n"
         "GENERAL.DEVICE:wlxec086b1e453b\nGENERAL.TYPE:wifi\nGENERAL.STATE:30 (disconnected)\n"
         "GENERAL.DBUS-PATH:/org/freedesktop/NetworkManager/Devices/5\n"
         "GENERAL.VENDOR:Qualcomm Atheros Communications\nGENERAL.PRODUCT:AR9271 802.11n\n"
         "GENERAL.PATH:pci-0000\\:00\\:1d.0-usb-0\\:1.3\\:1.0\n")
ADDRESSES = {"/org/freedesktop/NetworkManager/Devices/3": "40:e2:30:cd:53:3e",
             "/org/freedesktop/NetworkManager/Devices/5": "EC:08:6B:1E:45:3B"}
BUILT_IN = {"device": "wlp3s0", "address": "40:E2:30:CD:53:3E",
            "label": "Qualcomm AR9485 Wireless Network Adapter (AW-NE186H)", "active": True}
TEST_ADAPTER = {"device": "wlxec086b1e453b", "address": "EC:08:6B:1E:45:3B",
                "label": "Qualcomm AR9271 802.11n, USB", "active": False}


def fake_network(args, **_kw):
    """nmcli device show and busctl's PermHwAddress for a laptop with a second, USB adapter."""
    if args[0] == "nmcli":
        return result(NMCLI)
    if args[0] == "busctl":
        address = ADDRESSES.get(args[4])
        return result(json.dumps({"type": "s", "data": address})) if address else result("", 1)
    return result("", 1)


class SecurityStepsTest(QuietHome):
    """flickos-security.md phase 2: packet capture (ADR-S02) and the wireless test adapter (ADR-S08)."""

    def test_wifi_adapters(self):
        self.assertEqual(fk.wifi_adapters(fake_network), [BUILT_IN, TEST_ADAPTER])
        self.assertEqual(fk.wifi_adapters(lambda *_a, **_k: result("", 8, "NetworkManager is not running")), [])

        def broken(*_a, **_k):
            raise OSError("no nmcli")
        self.assertEqual(fk.wifi_adapters(broken), [])

    def test_adapter_address(self):
        adapters = [BUILT_IN, TEST_ADAPTER]
        self.assertEqual(fk.adapter_address("wlxec086b1e453b", adapters), TEST_ADAPTER["address"])
        self.assertEqual(fk.adapter_address("ec:08:6b:1e:45:3b", adapters), TEST_ADAPTER["address"])
        with self.assertRaisesRegex(fk.KitsError, "no Wi-Fi adapter named wlan9"):
            fk.adapter_address("wlan9", adapters)

    def test_capture_active_reads_this_sessions_groups(self):
        with mock.patch.object(fk.grp, "getgrnam", return_value=types.SimpleNamespace(gr_gid=142)):
            self.assertTrue(fk.capture_active([27, 142]))
            self.assertFalse(fk.capture_active([27]))
        with mock.patch.object(fk.grp, "getgrnam", side_effect=KeyError("wireshark")):
            self.assertFalse(fk.capture_active([142]))

    def test_snapshot(self):
        control = fake_control({"firewall.local-ports": "off", "packet-capture": "on",
                                "wireless.test-adapter": "off"})

        def run(args, **kw):
            if args[0] == "dpkg-query":
                return fake_dpkg({"flickos-kit-network", "flickos-kit-wireless"})(args, **kw)
            if args[0] == fk.CONTROL:
                return control(args, **kw)
            return fake_network(args, **kw)
        programs = {fk.CONTROL, "dumpcap", "aircrack-ng"}
        with mock.patch.object(fk, "capture_active", return_value=False):
            state = fk.snapshot(run, lambda name: "/usr/bin/" + name if name in programs else None)
        self.assertEqual(state["steps"], {"ports": "off", "capture": ("on", False),
                                          "test-adapter": {"set": "off", "adapters": [BUILT_IN, TEST_ADAPTER]}})

    def test_setup_commands(self):
        control = fake_control({"packet-capture": "off", "wireless.test-adapter": "off"})

        def run(args, **kw):
            return control(args, **kw) if args[0] == fk.CONTROL else fake_network(args, **kw)
        out = io.StringIO()
        with mock.patch.object(fk, "run_program", run), mock.patch.object(fk.subprocess, "run", run), \
                contextlib.redirect_stdout(out):
            self.assertEqual(fk.main(["setup", "capture"]), 0)
            self.assertEqual(fk.main(["setup", "capture", "on"]), 0)
            self.assertEqual(fk.main(["setup", "test-adapter"]), 0)
            self.assertEqual(fk.main(["setup", "test-adapter", "wlxec086b1e453b"]), 0)
            self.assertEqual(fk.main(["setup", "test-adapter", "off"]), 0)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(fk.main(["setup", "test-adapter", "wlan9"]), 1)
        self.assertIn("no Wi-Fi adapter named wlan9", err.getvalue())
        self.assertEqual(out.getvalue(), "off\noff\n")
        changes = [c[2:] for c in control.calls if len(c) == 4]
        self.assertEqual(changes, [["packet-capture", "on"], ["wireless.test-adapter", TEST_ADAPTER["address"]],
                                   ["wireless.test-adapter", "off"]])

    def test_doctor(self):
        def lines(steps, kits=(), outside="off"):
            state = {"kits": list(kits), "steps": steps}
            out = io.StringIO()
            with mock.patch.object(fk, "snapshot", return_value=state), \
                    mock.patch.object(fk, "control_value", return_value=outside), \
                    mock.patch.object(fk, "wifi_adapters", return_value=[TEST_ADAPTER]), \
                    contextlib.redirect_stdout(out):
                fk.cmd_doctor(None)
            return [line.split("\t") for line in out.getvalue().splitlines()]
        adapters = [BUILT_IN, TEST_ADAPTER]
        self.assertEqual(lines({"capture": ("on", False)}), [["capture", "next login", "until then: sg wireshark -c wireshark"]])
        self.assertEqual(lines({"capture": ("on", True)}), [["capture", "ok", ""]])
        self.assertEqual(lines({"capture": ("off", False)}), [["capture", "off", ""]])
        self.assertEqual(lines({"test-adapter": {"set": "off", "adapters": adapters}}), [["test-adapter", "none", ""]])
        self.assertEqual(lines({"test-adapter": {"set": TEST_ADAPTER["address"], "adapters": adapters}}),
                         [["test-adapter", "ok", "EC:08:6B:1E:45:3B wlxec086b1e453b"]])
        self.assertEqual(lines({"test-adapter": {"set": "00:11:22:33:44:55", "adapters": adapters}}),
                         [["test-adapter", "absent", "00:11:22:33:44:55"]])
        # Set, then the wireless kit was removed: the setting stays, and doctor says so.
        self.assertEqual(lines({}, outside=TEST_ADAPTER["address"]),
                         [["test-adapter", "set without the wireless kit", TEST_ADAPTER["address"]]])
        self.assertEqual(lines({}, outside="off"), [])


APT_PLAN = ("Reading package lists...\nThe following NEW packages will be installed:\n  netexec responder\n"
            "Need to get 0 B/123 MB of archives.\nAfter this operation, 1,234 MB of additional disk space will be used.\n"
            "E: Trivial Only specified but this is not a trivial operation.\n")


def podman_list(*envs):
    return json.dumps([{"Names": [name], "State": state, "Created": 1700000000, "ImageID": "1a2b3c",
                        "Labels": {fk.ENV_LABEL: category, fk.ENV_KITS_LABEL: kits, fk.ENV_EXTRAS_LABEL: extras,
                                   "manager": "distrobox"}}
                       for name, category, kits, extras, state in envs])


class EnvTest(QuietHome):
    """Environments (flickos-dev.md 8c, flickos-security.md ADR-S03): podman and
    distrobox are stand-ins, so nothing is pulled or made."""

    def setUp(self):
        super().setUp()
        self.calls = []
        self.listing = podman_list(("kali", "security", "network,passwords", "exploitation", "running"))
        self.plan_out = APT_PLAN
        self.failing = set()
        self.image_users = ""

    def fake(self, args, **_kw):
        self.calls.append(list(args))
        if args[:2] == ["podman", "ps"] and "--quiet" in args:     # who uses an image
            return result(self.image_users, 125 if "podman" in self.failing else 0)
        if args[:2] == ["podman", "ps"]:
            return result(self.listing)
        if args[:2] == ["podman", "run"]:
            return result(self.plan_out, 1)
        if args[0] == "apt-cache":
            depends = {"flickos-kit-python": "flickos-kit-base, python3-venv, python3-dev, ${misc:Depends}",
                       "flickos-kit-base": "git, build-essential | gcc, gdb"}
            return result(f"Package: {args[-1]}\nDepends: {depends[args[-1]]}\n") if args[-1] in depends \
                else result("", 100)
        return result("", 1 if args[0] in self.failing else 0, "distrobox: it broke\n" if args[0] in self.failing else "")

    def test_tables(self):
        self.assertEqual(set(fk.ENV_LISTS), {k[0] for k in fk.KITS if k[1] == "security"})
        for image in fk.ENV_IMAGES.values():
            self.assertRegex(image, r"^docker\.io/[a-z0-9]+/[a-z0-9-]+:[a-z0-9.-]+$")   # named in full
        self.assertEqual(fk.ENV_IMAGES["security"], "docker.io/kalilinux/kali-rolling:latest")
        for short, whole in fk.ENV_LISTS.values():
            self.assertTrue(short and whole)
            self.assertTrue(all(name.startswith("kali-tools-") for name in whole))

    def test_packages(self):
        self.assertEqual(fk.env_packages(["network", "passwords"], run=self.fake),
                         ["netexec", "responder", "enum4linux", "wordlists", "seclists"])
        self.assertEqual(fk.env_packages(["network"], whole=True, extras=["exploitation"], run=self.fake),
                         ["kali-tools-information-gathering", "kali-tools-sniffing-spoofing",
                          "metasploit-framework", "exploitdb"])
        # A developer kit: its Depends from apt, other kits' expanded, the first of a choice.
        self.assertEqual(fk.env_packages(["python"], run=self.fake),
                         ["git", "build-essential", "gdb", "python3-venv", "python3-dev"])
        for kits, words in ((["network", "python"], "different environments"), (["containers"], "no environment"),
                            (["classroom"], "no environment"), ([], "at least one kit")):
            with self.assertRaisesRegex(fk.KitsError, words, msg=kits):
                fk.env_packages(kits, run=self.fake)
        with self.assertRaisesRegex(fk.KitsError, "no extra"):
            fk.env_packages(["python"], extras=["exploitation"], run=self.fake)

    def test_plan_asks_the_image(self):
        plan = fk.env_plan(["network", "passwords"], run=self.fake)
        self.assertEqual(plan, {"image": "docker.io/kalilinux/kali-rolling:latest", "download": 123_000_000,
                                "disk": 1_234_000_000,
                                "packages": ["netexec", "responder", "enum4linux", "wordlists", "seclists"]})
        call = self.calls[-1]
        self.assertEqual(call[:5], ["podman", "run", "--rm", "--pull=missing", "docker.io/kalilinux/kali-rolling:latest"])
        self.assertIn("--trivial-only", call[-7])
        self.assertEqual(call[-5:], plan["packages"])
        self.plan_out = "E: Unable to locate package netexec\n"
        with self.assertRaisesRegex(fk.KitsError, "has no package netexec"):
            fk.env_plan(["network"], run=self.fake)

    def test_apt_size(self):
        self.assertEqual(fk.apt_size("Need to get 53.2 MB of archives.\n"
                                     "After this operation, 2 kB of additional disk space will be used."),
                         (53_200_000, 2000))
        self.assertEqual(fk.apt_size("nothing"), (None, None))

    def test_list(self):
        envs = fk.environments(self.fake)
        self.assertEqual(envs, [{"name": "kali", "category": "security", "kits": ["network", "passwords"],
                                 "extras": ["exploitation"], "running": True, "created": 1700000000,
                                 "image": "1a2b3c", "updated": 1700000000}])
        self.assertIn(f"label={fk.ENV_LABEL}", self.calls[0])
        fk.mark_updated("kali", 1800000000)
        self.assertEqual(fk.environments(self.fake)[0]["updated"], 1800000000)
        self.assertTrue(fk.state_path().startswith(self.home))
        self.listing = json.dumps([{"Names": ["mine"], "State": "exited", "Labels": {"manager": "distrobox"}}])
        self.assertEqual(fk.environments(self.fake), [])          # the user's own distrobox isn't ours

    def test_create_is_rootless_labelled_and_without_its_own_menu_entry(self):
        fk.create_environment("kali", ["network"], extras=["exploitation"], run=self.fake)
        create, install, stop = self.calls[-3:]
        self.assertEqual(create[:9], ["distrobox", "create", "--yes", "--no-entry", "--name", "kali", "--image",
                                      "docker.io/kalilinux/kali-rolling:latest", "--additional-flags"])
        self.assertNotIn("--root", create)
        self.assertIn(f"--label {fk.ENV_LABEL}=security", create[-1])
        self.assertIn(f"--label {fk.ENV_EXTRAS_LABEL}=exploitation", create[-1])
        self.assertEqual(install[:5], ["distrobox", "enter", "kali", "--", "sh"])
        self.assertTrue(install[-1].endswith("netexec responder enum4linux metasploit-framework exploitdb"))
        self.assertLess(install[-1].index("/etc/kali-motd/disable-minimal-warning"),
                        install[-1].index("apt-get update"))       # Kali's minimal-install warning
        self.assertEqual(stop, ["distrobox", "stop", "--yes", "kali"])
        self.assertIn("kali", fk.read_state())

    def test_a_development_environment_has_no_kali_setup(self):
        fk.create_environment("box", ["python"], run=self.fake)
        self.assertNotIn("kali-motd", self.calls[-2][-1])

    def test_a_failing_step_stops_there(self):
        self.failing = {"distrobox"}
        with self.assertRaisesRegex(fk.KitsError, "distrobox create --yes failed"):
            fk.create_environment("kali", ["network"], run=self.fake)
        self.assertEqual(len([c for c in self.calls if c[0] == "distrobox"]), 1)
        self.assertNotIn("kali", fk.read_state())

    def test_remove_takes_the_image_only_when_nothing_uses_it(self):
        fk.remove_environment("kali", self.fake)
        self.assertEqual(self.calls[-2], ["podman", "ps", "--all", "--quiet", "--filter", "ancestor=1a2b3c"])
        self.assertEqual(self.calls[-1], ["podman", "rmi", "1a2b3c"])
        self.calls.clear()
        self.image_users = "9f8e7d\n"                       # the user's own distrobox, say
        fk.remove_environment("kali", self.fake)
        self.assertNotIn(["podman", "rmi", "1a2b3c"], self.calls)
        self.calls.clear()
        self.image_users, self.failing = "", {"podman"}     # podman can't say: the image stays
        fk.remove_unused_image("1a2b3c", self.fake)
        self.assertNotIn(["podman", "rmi", "1a2b3c"], self.calls)

    def test_update_stop_remove_database(self):
        fk.update_environment("kali", self.fake)
        self.assertIn("full-upgrade", self.calls[-2][-1])
        self.assertEqual(self.calls[-1], ["distrobox", "stop", "--yes", "kali"])
        fk.start_database("kali", self.fake)
        self.assertIn("msfdb init", self.calls[-1][-1])
        fk.remove_environment("kali", self.fake)
        self.assertIn(["distrobox", "rm", "--force", "--yes", "kali"], self.calls[-3:])
        self.assertNotIn("kali", fk.read_state())
        with self.assertRaisesRegex(fk.KitsError, "no environment named nope"):
            fk.update_environment("nope", self.fake)
        self.listing = podman_list(("plain", "security", "network", "", "exited"))
        with self.assertRaisesRegex(fk.KitsError, "no Metasploit"):
            fk.start_database("plain", self.fake)

    def test_export(self):
        local = os.path.join(self.home, ".local/bin")
        which = lambda name: {"nmap": "/usr/bin/nmap", "mine": os.path.join(local, "mine")}.get(name)
        fk.export_command("kali", "burpsuite", menu=True, run=self.fake, which=which)
        script = self.calls[-1][-1]
        self.assertIn("distrobox-export --bin", script)
        self.assertIn(f"p=$(PATH={fk.ENV_SYSTEM_PATH} command -v burpsuite)", script)   # never ~/.local/bin's
        self.assertNotIn(".local", fk.ENV_SYSTEM_PATH)
        self.assertNotIn("--app", script)                    # Kali ships no entry: ours instead
        path = fk.app_entry_path("kali", "burpsuite")
        self.assertEqual(path, os.path.join(self.home, ".local/share/applications/kali-burpsuite.desktop"))
        with open(path) as f:
            entry = f.read()
        self.assertIn("Name=Burp Suite (on kali)\n", entry)
        self.assertRegex(entry, r"Exec=.*kali ")            # distrobox rm's pattern finds it
        fk.export_command("kali", "mine", menu=True, run=self.fake, which=which)
        self.assertIn("distrobox-export --app mine", self.calls[-1][-1])
        self.assertIn("has no menu entry for it", self.calls[-1][-1])   # a terminal program's (msfconsole)
        with self.assertRaisesRegex(fk.KitsError, "this computer has nmap too"):
            fk.export_command("kali", "nmap", run=self.fake, which=which)
        with self.assertRaisesRegex(fk.KitsError, "isn't a command"):
            fk.export_command("kali", "a;b", run=self.fake, which=which)

    def test_names(self):
        self.assertEqual(fk.check_env_name("kali-2"), "kali-2")
        self.assertEqual(fk.free_name("kali", set()), "kali")
        self.assertEqual(fk.free_name("kali", {"kali", "kali-2"}), "kali-3")
        for bad in ("", "Kali", "-x", "a b", "a" * 41, "kali\n"):
            with self.assertRaises(fk.KitsError, msg=bad):
                fk.check_env_name(bad)

    def test_commands(self):
        out = io.StringIO()
        with mock.patch.object(fk, "run_program", self.fake), mock.patch.object(fk.subprocess, "run", self.fake), \
                mock.patch.object(fk, "environments_available", return_value=True), contextlib.redirect_stdout(out):
            self.assertEqual(fk.main(["env", "list"]), 0)
            self.assertEqual(fk.main(["env", "new", "kali2", "--kit", "network", "--yes"]), 0)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(fk.main(["env", "new", "kali", "--kit", "network", "--yes"]), 1)
                self.assertEqual(fk.main(["env", "remove", "kali"]), 1)      # no terminal to ask in, no --yes
        self.assertIn("named kali already", err.getvalue())
        self.assertTrue(out.getvalue().startswith("kali\tsecurity\tnetwork,passwords\trunning\t"))
        self.assertIn("1.2 GB on disk", out.getvalue())
        self.assertIn("Kali's own image", out.getvalue())
        self.assertNotIn(["distrobox", "rm", "--force", "--yes", "kali"], self.calls)
        with mock.patch.object(fk, "environments_available", return_value=False), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fk.main(["env", "list"]), 1)
        self.assertIn("flickos-kits install containers", err.getvalue())

    def test_snapshot_lists_environments_once_a_kit_is_installed(self):
        def run(args, **kw):
            if args[0] == "dpkg-query":
                return fake_dpkg({"flickos-kit-network", "flickos-kit-containers"})(args, **kw)
            return self.fake(args, **kw)
        programs = {"distrobox", "podman"}
        state = fk.snapshot(run, lambda name: "/usr/bin/" + name if name in programs else None)
        self.assertEqual([e["name"] for e in state["envs"]], ["kali"])
        self.assertIsNone(fk.snapshot(run, lambda name: None)["envs"])


HELPER = os.path.join(PACKAGE, "../flickos-control/usr/libexec/flickos/control-helper")
MISE_LS = {"node": [{"version": "26.13.1", "requested_version": "lts", "installed": True, "active": True}],
           "aqua:ffuf/ffuf": [{"version": "2.3.0", "requested_version": "2.3.0", "installed": True}],
           "mine:own-tool": [{"version": "1", "requested_version": "latest", "installed": True}]}


class VersionsTest(QuietHome):
    """Newer versions (flickos-dev.md 8a, 8b): makers' repositories through
    flickos-control, the account's own versions through mise. No real mise,
    dpkg or flickos-control runs."""

    def setUp(self):
        super().setUp()
        self.calls = []
        self.values = {"upstream.mise": "on", "upstream.rapid7": "off"}
        self.mise_out = result(json.dumps(MISE_LS))
        self.dpkg = fake_dpkg({"nodejs", "mise", "ffuf"}, {"nodejs": "20.19.2+dfsg-1", "mise": "2026.11.8",
                                                          "ffuf": "2.1.0-1+b2"})

    def fake(self, args, **kw):
        self.calls.append((list(args), kw.get("env")))
        if args[0] == "dpkg-query":
            return self.dpkg(args)
        if args[0] == fk.CONTROL:
            return result(self.values[args[2]] + "\n") if len(args) == 3 else result()
        if args[:2] == ["mise", "ls"]:
            return self.mise_out
        return result()

    def test_tables(self):
        names = [t[0] for t in fk.USER_TOOLS]
        self.assertEqual(len(names), len(set(names)))
        for name, title, kit, check, spec, _debian in fk.USER_TOOLS:
            self.assertIn(kit, fk.kit_names(), name)
            self.assertIn(check, fk.CHECKS, name)
            self.assertIn(spec, ("latest", "lts"), name)
            self.assertNotIn("@", name)
        for entry_id, (package, _title, _about, category, download, size) in fk.UPSTREAMS.items():
            self.assertIn(category, (None, *(c[0] for c in fk.CATEGORIES)), entry_id)
            self.assertLess(download, size)

    @unittest.skipUnless(os.path.exists(HELPER), "flickos-control is not next to this package")
    def test_the_makers_are_flickos_controls(self):
        loader = importlib.machinery.SourceFileLoader("control_helper_for_kits", HELPER)
        helper = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(helper)
        self.assertEqual(set(fk.UPSTREAMS), set(helper.UPSTREAMS))
        for entry_id, entry in fk.UPSTREAMS.items():
            self.assertEqual((entry[0],), helper.UPSTREAMS[entry_id]["packages"], entry_id)

    def test_plain_version(self):
        for full, plain in (("20.19.2+dfsg-1", "20.19.2"), ("1:2.3-4", "2.3"), ("2026.11.8", "2026.11.8"),
                            ("6.5.11~20261118055722~1rapid7-1", "6.5.11")):
            self.assertEqual(fk.plain_version(full), plain)

    def test_mise_tools_reads_offline(self):
        self.assertEqual(fk.mise_tools(self.fake), {"node": ("26.13.1", "lts"), "aqua:ffuf/ffuf": ("2.3.0", "2.3.0"),
                                                    "mine:own-tool": ("1", "latest")})
        self.assertEqual(self.calls[-1][0], ["mise", "ls", "--global", "--json"])
        self.assertEqual(self.calls[-1][1]["MISE_OFFLINE"], "1")
        self.mise_out = result("", 1, "mise ERROR config.toml: invalid\n")
        with self.assertRaisesRegex(fk.KitsError, "invalid"):
            fk.mise_tools(self.fake)
        self.mise_out = result("{not json")
        with self.assertRaises(fk.KitsError):
            fk.mise_tools(self.fake)
        self.mise_out = result("{}")
        self.assertEqual(fk.mise_tools(self.fake), {})

    def test_which_kits_offer_what(self):
        self.assertEqual(fk.shown_upstreams({"base"}), [])
        self.assertEqual(fk.shown_upstreams({"web"}), ["mise"])
        self.assertEqual(fk.shown_upstreams({"passwords"}), ["rapid7"])
        self.assertEqual(fk.shown_upstreams({"network", "base"}), ["mise", "rapid7"])
        with_pipx = fk.tool_rows({"network", "web-testing"}, lambda name: "/usr/bin/uv" if name == "uv" else None)
        without = fk.tool_rows({"network", "web-testing"}, lambda name: None)
        self.assertIn("pipx:impacket", [t[0] for t in with_pipx])
        self.assertEqual([t[0] for t in without], [t[0] for t in with_pipx if not t[0].startswith("pipx:")])
        self.assertEqual({t[2] for t in without}, {"web-testing"})

    def test_versions(self):
        state = fk.versions({"web", "web-testing"}, self.fake, lambda name: "/usr/bin/mise" if name == "mise" else None)
        self.assertEqual(state["upstreams"], {"mise": "on", "rapid7": "off"})     # web-testing is security
        self.assertEqual(state["packages"], {"mise": "2026.11.8", "nodejs": "20.19.2", "ffuf": "2.1.0"})
        self.assertIn(("node", "26.13.1"), [(k, v[0]) for k, v in state["mine"].items()])
        self.assertFalse(state["on_path"])
        self.assertIsNone(state["updated"])
        self.assertIsNone(state["error"])
        node = fk.user_tool("node")
        self.assertEqual(fk.tool_line(node, state["mine"], state["packages"]),
                         ("yours", "26.13.1 (lts), over the computer's 20.19.2"))
        self.assertEqual(fk.tool_line(fk.user_tool("bun"), state["mine"], state["packages"]), ("none", ""))
        self.assertEqual(fk.tool_line(fk.user_tool("cmake"), {}, {"cmake": "3.31.6"}), ("computer", "3.31.6"))
        # Without mise installed: no list is read; a failing mise is a message, not a crash.
        state = fk.versions({"web"}, self.fake, lambda name: None)
        self.assertIsNone(state["mine"])
        self.mise_out = result("", 1, "mise: broken\n")
        state = fk.versions({"web"}, self.fake, lambda name: "/usr/bin/" + name)
        self.assertEqual((state["mine"], state["error"]), ({}, "mise: broken"))
        # Only offered once a kit with tools is installed: snapshot leaves it out with none.
        self.assertIsNone(fk.snapshot(fake_dpkg(set()), lambda name: None)["versions"])

    def test_user_tool(self):
        for name in ("node", "Node.js", "nuclei", "aqua:projectdiscovery/nuclei", "sqlmap", "IMPACKET"):
            self.assertIn(fk.user_tool(name), fk.USER_TOOLS)
        self.assertEqual(fk.user_tool("nuclei")[0], "aqua:projectdiscovery/nuclei")
        with self.assertRaises(fk.KitsError):
            fk.user_tool("rustc")

    def test_use_update_and_back(self):
        node = fk.user_tool("node")
        fk.use_tool(node, run=self.fake)
        fk.use_tool(fk.user_tool("ffuf"), "latest", run=self.fake)
        fk.use_tool(node, "26.13.1", run=self.fake)
        fk.use_tool(node, "system", run=self.fake)
        fk.update_tools(self.fake)
        self.assertEqual([c[0] for c in self.calls], [["mise", "use", "--global", "node@lts"],
                                                      ["mise", "use", "--global", "aqua:ffuf/ffuf@latest"],
                                                      ["mise", "use", "--global", "node@26.13.1"],
                                                      ["mise", "unuse", "--global", "node"],
                                                      ["mise", "upgrade"]])
        self.assertTrue(all(c[1]["MISE_YES"] == "1" for c in self.calls))
        self.assertIsNotNone(fk.read_state("versions.json")["updated"])
        for bad in ("--global", "1.0 2", "", "a" * 50):
            with self.assertRaises(fk.KitsError):
                fk.use_tool(node, bad, run=self.fake)
        self.assertEqual(len(self.calls), 5)
        with self.assertRaisesRegex(fk.KitsError, "^mise: Checksum mismatch$"):
            fk.use_tool(node, run=lambda args, **kw: result("", 1, "mise ERROR\nChecksum mismatch\n"))

        def missing(args, **kw):
            raise FileNotFoundError(args[0])
        with self.assertRaisesRegex(fk.KitsError, "version maker mise on"):
            fk.use_tool(node, run=missing)

    def test_shims_on_path(self):
        shims = os.path.join(self.home, ".local/share/mise/shims")
        self.assertEqual(fk.shims_folder(), shims)
        with mock.patch.dict(os.environ, {"PATH": f"{shims}:/usr/bin:/bin"}):
            self.assertTrue(fk.shims_on_path())
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            self.assertFalse(fk.shims_on_path())

    def test_commands(self):
        # The commands use shutil.which itself: a stand-in mise on PATH (never run: subprocess.run is the fake).
        folder = os.path.join(self.home, "bin")
        os.makedirs(folder)
        with open(os.path.join(folder, "mise"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(folder, "mise"), 0o755)
        out = io.StringIO()
        with mock.patch.object(fk.subprocess, "run", self.fake), mock.patch.dict(os.environ, {"PATH": folder}), \
                contextlib.redirect_stdout(out):
            self.dpkg = fake_dpkg({"flickos-kit-web", "flickos-kit-passwords", "nodejs", "mise"},
                                  {"nodejs": "20.19.2+dfsg-1", "mise": "2026.11.8"})
            self.assertEqual(fk.main(["version", "list"]), 0)
            self.assertEqual(fk.main(["version", "maker", "rapid7"]), 0)
            self.assertEqual(fk.main(["version", "maker", "rapid7", "on"]), 0)
            self.assertEqual(fk.main(["version", "use", "deno"]), 0)
            self.assertEqual(fk.main(["version", "use", "deno", "system"]), 0)
        lines = [line.split("\t") for line in out.getvalue().splitlines()]
        self.assertIn(["maker", "mise", "on", "2026.11.8"], lines)
        self.assertIn(["maker", "rapid7", "off", ""], lines)
        self.assertIn(["tool", "node", "web", "yours", "26.13.1 (lts), over the computer's 20.19.2", "signature"],
                      lines)
        self.assertIn(["tool", "deno", "web", "none", "", "checksum"], lines)
        self.assertIn(["off"], lines)
        self.assertIn([fk.CONTROL, "system", "upstream.rapid7", "on"], [c[0] for c in self.calls])
        self.assertIn(["Deno: your own version, from mise."], lines)
        self.assertIn(["Deno: the computer's version again."], lines)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                fk.main(["version", "maker", "nodesource", "on"])
            self.assertEqual(fk.main(["version", "use", "rustc"]), 1)

    def test_doctor_lines(self):
        state = {"kits": [("web", "development", "Node.js and npm", "x", True)], "steps": {},
                 "versions": {"upstreams": {"mise": "on"}, "packages": {"mise": "2026.11.8", "nodejs": "20.19.2"},
                              "tools": fk.tool_rows({"web"}), "mine": {"node": ("26.13.1", "lts")},
                              "error": None, "on_path": False, "updated": None}}
        out = io.StringIO()
        with mock.patch.object(fk, "snapshot", return_value=state), \
                mock.patch.object(fk, "control_value", return_value=None), contextlib.redirect_stdout(out):
            fk.cmd_doctor(None)
        lines = [line.split("\t") for line in out.getvalue().splitlines()]
        self.assertEqual(lines[1:], [["maker mise", "on", "2026.11.8"],
                                     ["version Node.js", "yours", "26.13.1 (lts), over the computer's 20.19.2"],
                                     ["version path", "next login",
                                      f"{fk.shims_folder()} is on PATH from your next login"]])


    def test_doctor_says_when_another_copy_comes_first(self):
        tools = fk.tool_rows({"web", "web-testing", "forensics"})
        shims = fk.shims_folder()
        os.makedirs(shims)
        for command in ("node", "deno", "httpx", "vol"):
            open(os.path.join(shims, command), "w").close()
        nvm = os.path.join(self.home, ".nvm/versions/node/v22/bin/node")
        local = os.path.join(self.home, ".local/bin/httpx")      # Python's httpx, say
        found = {"node": nvm, "deno": os.path.join(shims, "deno"), "httpx": local, "vol": None}
        state = {"kits": [], "steps": {},
                 "versions": {"upstreams": {"mise": "on"}, "packages": {}, "tools": tools,
                              "mine": {t: ("1", "latest") for t in ("node", "deno", "aqua:projectdiscovery/httpx",
                                                                    "pipx:volatility3", "pipx:impacket")},
                              "error": None, "on_path": True, "updated": None}}
        out = io.StringIO()
        with mock.patch.object(fk, "snapshot", return_value=state), \
                mock.patch.object(fk, "control_value", return_value=None), contextlib.redirect_stdout(out):
            fk.cmd_doctor(None, which=found.get)
        lines = [line.split("\t") for line in out.getvalue().splitlines() if "not first" in line]
        self.assertEqual(lines, [["version Node.js", "not first", f"{nvm} comes before yours on this PATH "
                                  "(a shell startup file?)"],
                                 ["version httpx", "not first", f"{local} comes before yours on this PATH "
                                  "(a shell startup file?)"]])
        self.assertEqual(fk.tool_command(("pipx:volatility3",)), "vol")
        self.assertIsNone(fk.comes_first(("pipx:impacket",), which=found.get))
        self.assertIsNone(fk.comes_first(("bun",), which=lambda c: "/usr/bin/bun"))   # no shim: nothing hidden
        state["versions"]["on_path"] = False                   # the next-login line says it already
        out = io.StringIO()
        with mock.patch.object(fk, "snapshot", return_value=state), \
                mock.patch.object(fk, "control_value", return_value=None), contextlib.redirect_stdout(out):
            fk.cmd_doctor(None, which=found.get)
        self.assertNotIn("not first", out.getvalue())


class SessionTest(QuietHome):
    def test_live_system(self):
        self.assertFalse(fk.live_system())
        os.makedirs(self.home + "/proc")
        with open(self.home + "/proc/cmdline", "w") as f:
            f.write("BOOT_IMAGE=/live/vmlinuz boot=live quiet\n")
        self.assertTrue(fk.live_system())

    def test_one_window_per_session(self):
        with fk.single_instance() as first:
            self.assertTrue(first)
            with fk.single_instance() as second:
                self.assertFalse(second)
        with fk.single_instance() as again:
            self.assertTrue(again)

    def test_a_second_window_only_says_so(self):
        out = io.StringIO()
        with mock.patch.object(fk, "window") as window, contextlib.redirect_stdout(out), \
                mock.patch.object(fk, "single_instance") as lock:
            lock.return_value.__enter__.return_value = False
            self.assertEqual(fk.cmd_window(types.SimpleNamespace(kit=None)), 0)
        window.assert_not_called()
        self.assertEqual(out.getvalue(), "Tool Kits is already open.\n")


class DesktopFileTest(unittest.TestCase):
    def test_desktop_file(self):
        with open(os.path.join(PACKAGE, "usr/share/applications/flickos-kits.desktop"), encoding="utf-8") as f:
            entries = dict(line.rstrip("\n").split("=", 1) for line in f if "=" in line and not line.startswith("#"))
        self.assertEqual(entries["Name"], "Tool Kits")
        self.assertEqual(entries["Exec"], "flickos-kits window")
        self.assertTrue(entries["Categories"].startswith("Development;"))
        self.assertIn("System", entries["Categories"])


PO = os.path.join(PACKAGE, "po")


def po_list(name):
    """The file names in po/POTFILES or po/LINGUAS, comments left out."""
    with open(os.path.join(PO, name), encoding="utf-8") as f:
        return [line.split("#", 1)[0].strip() for line in f if line.split("#", 1)[0].strip()]


@unittest.skipUnless(shutil.which("xgettext") and shutil.which("msgfmt"), "gettext is not installed")
class TranslationTest(unittest.TestCase):
    def test_template_is_current(self):
        """po/flickos-kits.pot has every marked string and no others. Same
        xgettext options as tools/update-po.sh, which fixes this."""
        files = po_list("POTFILES")
        with tempfile.TemporaryDirectory() as folder:
            new = os.path.join(folder, "new.pot")
            python = [f for f in files if not f.endswith(".desktop")]
            desktop = [f for f in files if f.endswith(".desktop")]
            subprocess.run(["xgettext", "--language=Python", "--from-code=UTF-8", "--keyword=N_",
                            "--output=" + new, *python], cwd=PACKAGE, check=True)
            subprocess.run(["xgettext", "--language=Desktop", "--join-existing",
                            "--output=" + new, *desktop], cwd=PACKAGE, check=True)
            shipped = os.path.join(PO, "flickos-kits.pot")
            for definitions, reference in ((shipped, new), (new, shipped)):
                result_ = subprocess.run(["msgcmp", "--use-untranslated", definitions, reference],
                                         capture_output=True, text=True)
                self.assertEqual(result_.returncode, 0, f"run tools/update-po.sh flickos-kits\n{result_.stderr}")

    def test_every_language_has_a_file_that_compiles(self):
        languages = po_list("LINGUAS")
        files = sorted(name[:-3] for name in os.listdir(PO) if name.endswith(".po"))
        self.assertEqual(sorted(languages), files, "po/LINGUAS and the po/*.po files differ")
        for lang in languages:
            with self.subTest(lang=lang):
                subprocess.run(["msgfmt", "--check", "--output-file=/dev/null",
                                os.path.join(PO, lang + ".po")], check=True)


if __name__ == "__main__":
    unittest.main()
