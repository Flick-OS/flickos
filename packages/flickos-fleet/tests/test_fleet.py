"""Tests for flickos-fleet. They run on the developer's own desktop, so every
outside path (the site folder, the state, /proc, the owners' commands) is a
temporary folder or a stand-in: never the build host's /etc or sessions."""

import configparser
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGES = os.path.dirname(PACKAGE)
CONTROL_PACKAGE = os.path.join(PACKAGES, "flickos-control")
LAYOUTS_PACKAGE = os.path.join(PACKAGES, "flickos-layouts")
TILER_PACKAGE = os.path.join(PACKAGES, "flick-tiler")

_loader = importlib.machinery.SourceFileLoader("flickos_fleet", os.path.join(PACKAGE, "usr/bin/flickos-fleet"))
_spec = importlib.util.spec_from_loader("flickos_fleet", _loader)
ff = importlib.util.module_from_spec(_spec)
_loader.exec_module(ff)
REAL_SESSIONS = ff.sessions         # FleetTest replaces ff.sessions with a stand-in


def done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class FakeOwners:
    """The owners' commands as the agent runs them: lists, `get`, `system`,
    countme, and the session commands, recorded in calls."""

    def __init__(self, site_dir):
        self.site_dir = site_dir
        self.calls = []
        self.system = {"firewall": "off", "timezone": "Asia/Manila"}
        self.countme = True
        self.refuse = set()             # control keys `get` won't show as "site"
        self.tiler_gap = None           # what flick-tiler status says; None: what's written
        self.installed = {"flickos-desktop", "labwc", "gimp", "libgimp"}
        self.desktop_depends = "labwc (>= 0.8), flickos-settings | flickos-settings-alt"
        self.extra_removed = {}         # package -> what else apt's simulation removes with it
        self.audit = ""                 # dpkg --audit's output: an interrupted install

    def read_site(self, name):
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(self.site_dir, name), encoding="utf-8")
        return ini

    def __call__(self, argv, env=None, input_text=None, timeout=None):
        self.calls.append(list(argv))
        name, args = os.path.basename(argv[0]), argv[1:]
        if name == "flickos-layout":
            lists = {("list",): "redmond\tRedmond\nflickos\tFlickOS\n",
                     ("style", "list"): "dark\tDark\nlight\tLight\n",
                     ("clock", "list"): "24h\t24-hour\t13:45\n12h\t12-hour\t1:45 PM\n"}
            if tuple(args) in lists:
                return done(lists[tuple(args)])
            return done()
        if name == "flick-tiler":
            if args == ["modes"]:
                return done("master-stack\tMaster and stack\ngrid\tGrid\n")
            if args == ["status"]:
                gap = self.tiler_gap
                if gap is None:
                    gap = self.read_site("tiler.conf").getint("Tiler", "Gap", fallback=8)
                return done(json.dumps({"gap": gap}))
        if name == "flickos-control":
            if args == ["get"]:
                ini = self.read_site("input.conf")
                lines = []
                for key, section, option in (("touchpad.tap", "Touchpad", "Tap"),
                                             ("touchpad.pointer-speed", "Touchpad", "PointerSpeed")):
                    source = "site" if ini.has_option(section, option) and key not in self.refuse else "default"
                    lines.append(f"{key}\t{ini.get(section, option, fallback='')}\t{source}")
                stderr = "".join(f"flickos-control: {self.site_dir}/input.conf: {key}: give a number\n"
                                 for key in self.refuse)
                return done("\n".join(lines) + "\n", stderr=stderr)
            if args[:1] == ["system"] and len(args) == 2:
                return done(self.system.get(args[1], "") + "\n")
            if args[:1] == ["system"] and len(args) == 3:
                if args[2] == "bad":
                    return done(returncode=1, stderr="flickos-control: give on or off, not 'bad'\n")
                self.system[args[1]] = args[2]
                return done()
        if name == "dpkg-query":
            if "${Depends}" in args:
                return done(self.desktop_depends)
            names = [a for a in args if not a.startswith("-") and not a.startswith("$")]
            names = [n for n in names if n != "${Package}\t${db:Status-Status}\n"]
            if "${Version}" in args:
                return done("1.0~test1")
            if any("${Version}\t" in a for a in args):        # the inventory's list
                return done("".join(f"{n}\t1.0\tinstalled\n" for n in sorted(self.installed)
                                    if n.startswith("flickos-")))
            return done("".join(f"{n}\tinstalled\n" for n in names if n in self.installed))
        if name == "dpkg":
            return done(self.audit if args == ["--audit"] else "")
        if name == "apt-get":
            words = [a for a in args if not a.startswith("-") and "=" not in a and a not in ("DPkg::Lock::Timeout=600",)]
            words = [w for w in words if w not in ("Dpkg::Options::=--force-confdef",
                                                   "Dpkg::Options::=--force-confold")]
            if "-s" in args:
                verb, names = words[0], words[1:]
                if any(n.startswith("missing") for n in names):
                    return done(returncode=100, stderr="E: Unable to locate package missing\n")
                if verb == "install":
                    removed = set().union(*(self.extra_removed.get(n, set()) for n in names)) if names else set()
                    return done("".join(f"Remv {r}\n" for r in sorted(removed)) +
                                "".join(f"Inst {n} (1.0 Debian)\n" for n in names))
                if verb == "remove":
                    removed = set(names).union(*(self.extra_removed.get(n, set()) for n in names))
                    return done("".join(f"Remv {r} [1.0]\n" for r in sorted(removed)))
                if verb == "dist-upgrade":
                    return done("Inst a [1] (2)\nInst b [1] (2)\nConf a (2)\n")
            if words and words[0] == "install":
                self.installed |= set(words[1:])
            if words and words[0] == "remove":
                self.installed -= set(words[1:])
            return done()
        if name == "apt-mark":
            return done("linux-image-amd64\n")
        if name == "flickos-countme" and args == ["status"]:
            return done(json.dumps({"enabled": self.countme}))
        if name == "countme-helper":
            self.countme = args == ["on"]
            return done()
        return done()

    def commands(self, name):
        return [call[1:] for call in self.calls if os.path.basename(call[0]) == name]


class FleetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-fleet-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.site = os.path.join(self.tmp, "site")
        self.owners = FakeOwners(self.site)
        for name, value in (("SITE_DIR", self.site), ("STATE_DIR", os.path.join(self.tmp, "state")),
                            ("PROC", os.path.join(self.tmp, "proc")),
                            ("COUNTME_HELPER", os.path.join(self.tmp, "countme-helper")),
                            ("run", self.owners), ("sessions", lambda: [])):
            patcher = mock.patch.object(ff, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def apply(self, values, dry_run=False):
        return ff.apply_policy({"version": 1, "values": values}, dry_run=dry_run)

    def site_text(self, name):
        with open(os.path.join(self.site, name), encoding="utf-8") as f:
            return f.read()

    def site_ini(self, name):
        return self.owners.read_site(name)

    def write_policy(self, values, version=1):
        path = os.path.join(self.tmp, "policy.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": version, "values": values}, f)
        return path


class PolicyTest(FleetTest):
    def test_parse(self):
        self.assertEqual(ff.parse_policy('{"version": 3, "values": {"style": "light"}}'),
                         {"version": 3, "values": {"style": "light"}})
        for text in ("not json", "[]", '{"values": []}', '{"version": -1, "values": {}}',
                     '{"version": true, "values": {}}'):
            with self.subTest(text=text), self.assertRaises(ff.FleetError):
                ff.parse_policy(text)

    def test_a_policy_too_big_is_refused(self):
        path = self.write_policy({"menu.pins": ["a.desktop"] * 10000})
        with self.assertRaises(ff.FleetError):
            ff.read_policy(path)

    def test_kinds(self):
        for key, kind in (("style", "layouts"), ("touchpad.tap", "control"), ("idle.lock-after", "control"),
                          ("tiler.gap", "tiler"), ("welcome.links", "welcome"), ("menu.pins", "menu"),
                          ("firewall", "system"), ("countme", "countme"), ("history.enabled", None),
                          ("rm -rf /", None), ("touchpad", None), ("packages.install", "packages"),
                          ("packages.purge", None)):
            with self.subTest(key=key):
                self.assertEqual(ff.kind_of(key), kind)

    def test_unknown_keys_are_reported_never_run(self):
        report, failed = self.apply({"shell": "rm -rf /", "style": "light"})
        self.assertEqual(set(failed), {"shell"})
        self.assertIn("shell: failed: this agent doesn't know this key", report)
        self.assertFalse(any("rm" in " ".join(call) for call in self.owners.calls))


class SiteTest(FleetTest):
    def test_layout_values_are_checked_against_the_owners_lists(self):
        report, failed = self.apply({"style": "light", "layout": "nope", "clock": "12h"})
        self.assertEqual(list(failed), ["layout"])
        self.assertIn("isn't one of: flickos, redmond", failed["layout"])
        ini = self.site_ini("layouts.conf")
        self.assertEqual(dict(ini["Defaults"]), {"style": "light", "clock": "12h"})
        self.assertTrue(self.site_text("layouts.conf").startswith("# Written by flickos-fleet"))
        self.assertIn("site layouts.conf: written", report)

    def test_control_keys_go_in_the_owners_format_and_refused_ones_come_out(self):
        self.owners.refuse = {"touchpad.pointer-speed"}
        _report, failed = self.apply({"touchpad.tap": False, "touchpad.pointer-speed": 5})
        self.assertEqual(list(failed), ["touchpad.pointer-speed"])
        self.assertIn("give a number", failed["touchpad.pointer-speed"])
        self.assertEqual(dict(self.site_ini("input.conf")["Touchpad"]), {"tap": "no"})

    def test_a_file_left_empty_by_refusals_is_not_kept(self):
        self.owners.refuse = {"touchpad.pointer-speed"}
        self.apply({"touchpad.pointer-speed": 5})
        self.assertFalse(os.path.exists(os.path.join(self.site, "input.conf")))
        self.assertEqual(ff.read_state()["files"], [])

    def test_tiler_gap_is_checked_by_flick_tiler(self):
        _report, failed = self.apply({"tiler.mode": "grid", "tiler.gap": 12})
        self.assertEqual(failed, {})
        self.assertEqual(dict(self.site_ini("tiler.conf")["Tiler"]), {"mode": "grid", "gap": "12"})
        self.owners.tiler_gap = 40
        _report, failed = self.apply({"tiler.mode": "spiral", "tiler.gap": 400})
        self.assertEqual(set(failed), {"tiler.mode", "tiler.gap"})
        self.assertIn("it uses 40", failed["tiler.gap"])
        self.assertFalse(os.path.exists(os.path.join(self.site, "tiler.conf")))

    def test_welcome_and_menu(self):
        _report, failed = self.apply({"welcome.enabled": False,
                                      "welcome.links": {"donate": "", "docs": "https://school.example/help"},
                                      "menu.pins": ["firefox-esr.desktop", "org.gnome.Calculator.desktop"]})
        self.assertEqual(failed, {})
        welcome = self.site_ini("welcome.conf")
        self.assertEqual(welcome.get("Welcome", "Enabled"), "no")
        self.assertEqual(dict(welcome["Links"]), {"donate": "", "docs": "https://school.example/help"})
        self.assertEqual(self.site_ini("menu.conf").get("Menu", "Pinned"),
                         "firefox-esr.desktop;org.gnome.Calculator.desktop")

    def test_bad_welcome_and_menu_values(self):
        _report, failed = self.apply({"welcome.enabled": "maybe",
                                      "welcome.links": {"docs": "http://insecure.example"},
                                      "menu.pins": ["../../etc/passwd"]})
        self.assertEqual(set(failed), {"welcome.enabled", "welcome.links", "menu.pins"})
        self.assertEqual(os.listdir(self.site) if os.path.isdir(self.site) else [], [])

    def test_values_never_break_out_of_their_line(self):
        _report, failed = self.apply({"touchpad.tap": "no\n[Touchpad]\nTap=yes"})
        self.assertIn("touchpad.tap", failed)
        self.assertFalse(os.path.exists(os.path.join(self.site, "input.conf")))

    def test_a_key_gone_from_the_policy_leaves_the_file_and_an_empty_file_goes(self):
        self.apply({"style": "light", "clock": "12h", "tiler.mode": "grid"})
        report, _failed = self.apply({"style": "light"})
        self.assertEqual(dict(self.site_ini("layouts.conf")["Defaults"]), {"style": "light"})
        self.assertFalse(os.path.exists(os.path.join(self.site, "tiler.conf")))
        self.assertIn("site tiler.conf: removed", report)
        self.assertEqual(ff.read_state()["files"], ["layouts.conf"])

    def test_a_site_file_not_ours_is_left_alone(self):
        os.makedirs(self.site)
        with open(os.path.join(self.site, "layouts.conf"), "w") as f:
            f.write("[Defaults]\nStyle=dark\n")     # a variant's package, or an admin by hand
        _report, failed = self.apply({"style": "light", "touchpad.tap": False})
        self.assertIn("wasn't written by flickos-fleet", failed["style"])
        self.assertEqual(self.site_text("layouts.conf"), "[Defaults]\nStyle=dark\n")
        self.assertTrue(os.path.exists(os.path.join(self.site, "input.conf")))

    def test_dry_run_changes_nothing(self):
        report, _failed = self.apply({"style": "light", "firewall": "on"}, dry_run=True)
        self.assertEqual(report, ["site layouts.conf: would be written", "firewall: would change off -> on"])
        self.assertFalse(os.path.exists(self.site))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state")))
        self.assertEqual(self.owners.system["firewall"], "off")

    def test_nothing_changed_runs_nothing_in_sessions(self):
        with mock.patch.object(ff, "in_sessions") as sessions:
            self.apply({"style": "light"})
            self.apply({"style": "light"})
        self.assertEqual(sessions.call_count, 1)

    def test_sessions_apply_the_owners_that_changed(self):
        with mock.patch.object(ff, "in_sessions") as sessions:
            self.apply({"style": "light"})
            self.assertEqual(sessions.call_args.args[0], [["flickos-layout", "apply-defaults"]])
            self.apply({"style": "light", "touchpad.tap": False})
            self.assertEqual(sessions.call_args.args[0], [["flickos-control", "apply-defaults"],
                                                          ["flickos-layout", "apply-defaults"]])


class SystemTest(FleetTest):
    def test_only_values_that_differ_are_changed(self):
        report, failed = self.apply({"firewall": "on", "timezone": "Asia/Manila"})
        self.assertEqual(failed, {})
        self.assertEqual(report, ["firewall: off -> on"])
        sets = [args for args in self.owners.commands("flickos-control") if len(args) == 3]
        self.assertEqual(sets, [["system", "firewall", "on"]])

    def test_the_owners_refusal_is_reported(self):
        _report, failed = self.apply({"firewall": "bad"})
        self.assertEqual(failed, {"firewall": "flickos-control: give on or off, not 'bad'"})

    def test_keys_that_need_a_person_are_not_system_keys(self):
        _report, failed = self.apply({"autologin": "on", "i386": "on"})
        self.assertEqual(set(failed), {"autologin", "i386"})
        self.assertEqual(self.owners.commands("flickos-control"), [])

    def test_countme(self):
        self.assertEqual(self.apply({"countme": "off"})[1], {})
        self.assertFalse(self.owners.countme)
        self.owners.calls.clear()
        self.assertEqual(self.apply({"countme": False})[1], {})
        self.assertEqual(self.owners.commands("countme-helper"), [])        # already off
        self.assertIn("countme", self.apply({"countme": "sometimes"})[1])


class SessionsTest(FleetTest):
    def make_process(self, pid, comm, uid, environ):
        folder = os.path.join(self.tmp, "proc", str(pid))
        os.makedirs(folder)
        with open(os.path.join(folder, "comm"), "w") as f:
            f.write(comm + "\n")
        with open(os.path.join(folder, "status"), "w") as f:
            f.write(f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        with open(os.path.join(folder, "environ"), "wb") as f:
            f.write(b"\0".join(f"{k}={v}".encode() for k, v in environ.items()) + b"\0")

    def test_found_by_labwc_and_a_program_it_started(self):
        uid = os.getuid()
        self.make_process(100, "labwc", uid, {"HOME": "/home/x"})
        self.make_process(101, "waybar", uid, {"LABWC_PID": "100", "WAYLAND_DISPLAY": "wayland-0",
                                               "XDG_RUNTIME_DIR": "/run/user/1000", "SECRET_TOKEN": "x",
                                               "LC_TIME": "en_GB.UTF-8", "FLICKOS_LAYOUT": "redmond"})
        self.make_process(200, "labwc", 0, {})            # root's labwc: never a session
        self.make_process(300, "bash", uid, {"LABWC_PID": "999", "WAYLAND_DISPLAY": "w"})
        found = REAL_SESSIONS()       # setUp put a stand-in in ff.sessions
        self.assertEqual(len(found), 1)
        user, env = found[0]
        self.assertEqual(user, __import__("pwd").getpwuid(uid).pw_name)
        self.assertEqual(env, {"LABWC_PID": "100", "WAYLAND_DISPLAY": "wayland-0",
                               "XDG_RUNTIME_DIR": "/run/user/1000", "LC_TIME": "en_GB.UTF-8",
                               "FLICKOS_LAYOUT": "redmond"})

    def test_commands_run_as_the_user_in_a_user_scope(self):
        with mock.patch.object(ff, "sessions", return_value=[("pupil", {"WAYLAND_DISPLAY": "wayland-0",
                                                                          "LABWC_PID": "100"})]):
            ff.in_sessions([["flickos-layout", "apply-defaults"]], [])
        self.assertEqual(self.owners.calls, [["runuser", "-u", "pupil", "--", "env", "-i", "LABWC_PID=100",
                                              "WAYLAND_DISPLAY=wayland-0", "systemd-run", "--user", "--scope",
                                              "--quiet", "--", "flickos-layout", "apply-defaults"]])



class CheckCommandTest(FleetTest):
    def main(self, *args):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            status = ff.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def test_needs_root_unless_dry_run(self):
        path = self.write_policy({"style": "light"})
        with mock.patch.object(ff, "running_as_root", return_value=False):
            status, _out, err = self.main("check", path)
            self.assertEqual(status, 1)
            self.assertIn("run it as root", err)
            self.assertEqual(self.main("check", "--dry-run", path)[:2], (0, "site layouts.conf: would be written\n"))

    def test_check_applies_and_says_what_failed(self):
        path = self.write_policy({"style": "light", "firewall": "bad"})
        with mock.patch.object(ff, "running_as_root", return_value=True):
            status, out, _err = self.main("check", path)
        self.assertEqual(status, 1)
        self.assertEqual(out, "site layouts.conf: written\nfirewall: failed: flickos-control: give on or off, "
                              "not 'bad'\n")
        self.assertEqual(ff.read_state()["failed"], {"firewall": "flickos-control: give on or off, not 'bad'"})
        with mock.patch.object(ff, "running_as_root", return_value=True):
            self.assertEqual(self.main("check", self.write_policy({"style": "light"}))[:2],
                             (0, "Nothing changed.\n"))

    def test_a_broken_policy_file(self):
        path = os.path.join(self.tmp, "broken.json")
        with open(path, "w") as f:
            f.write("{")
        status, _out, err = self.main("check", "--dry-run", path)
        self.assertEqual(status, 1)
        self.assertIn("not JSON", err)


class PackagesTest(FleetTest):
    def apt_runs(self):
        return [args for args in self.owners.commands("apt-get") if "-s" not in args]

    def test_only_missing_packages_are_installed(self):
        report, failed = self.apply({"packages.install": ["gimp", "inkscape"]})
        self.assertEqual(failed, {})
        self.assertEqual(report, ["packages.install: installed inkscape"])
        run = self.apt_runs()[-1]
        self.assertEqual(run[-2:], ["install", "inkscape"])
        for option in ("DPkg::Lock::Timeout=600", "Dpkg::Options::=--force-confold", "-y"):
            self.assertIn(option, run)
        self.owners.calls.clear()
        self.assertEqual(self.apply({"packages.install": ["gimp", "inkscape"]}), ([], {}))
        self.assertEqual(self.apt_runs(), [])

    def test_names_are_checked(self):
        _report, failed = self.apply({"packages.install": ["gimp; rm -rf /"], "packages.remove": "gimp"})
        self.assertEqual(set(failed), {"packages.install", "packages.remove"})
        self.assertEqual(self.apt_runs(), [])

    def test_live_packages_are_never_installed(self):
        self.assertIn("live session", self.apply({"packages.install": ["calamares"]})[1]["packages.install"])

    def test_an_install_that_would_remove_something_is_refused(self):
        self.owners.extra_removed = {"inkscape": {"labwc"}}
        failed = self.apply({"packages.install": ["inkscape"]})[1]
        self.assertIn("would remove labwc", failed["packages.install"])
        self.assertEqual(self.apt_runs(), [])

    def test_unknown_package_updates_the_lists_once(self):
        failed = self.apply({"packages.install": ["missing-app"]})[1]
        self.assertIn("Unable to locate package", failed["packages.install"])
        self.assertIn(["-q", "update"], self.owners.commands("apt-get"))

    def test_remove_only_installed_and_never_what_flickos_needs(self):
        report, failed = self.apply({"packages.remove": ["gimp", "not-installed"]})
        self.assertEqual((report, failed), (["packages.remove: removed gimp"], {}))
        failed = self.apply({"packages.remove": ["labwc"]})[1]
        self.assertIn("labwc, which FlickOS needs", failed["packages.remove"])
        self.owners.installed.add("flickos-settings")
        self.owners.installed.add("vlc")
        self.owners.extra_removed = {"vlc": {"flickos-settings"}}
        self.assertIn("flickos-settings", self.apply({"packages.remove": ["vlc"]})[1]["packages.remove"])

    def test_a_remove_that_takes_other_packages_is_refused(self):
        self.owners.installed.add("libreoffice-core")
        self.owners.extra_removed = {"libreoffice-core": {"libreoffice-writer"}}
        failed = self.apply({"packages.remove": ["libreoffice-core"]})[1]
        self.assertIn("would also take libreoffice-writer", failed["packages.remove"])
        self.assertIn("libreoffice-core", self.owners.installed)

    def test_an_interrupted_dpkg_is_repaired_first(self):
        self.owners.audit = "The following packages are only half configured\n"
        self.apply({"packages.install": ["inkscape"]})
        self.assertIn(["--configure", "-a"], self.owners.commands("dpkg"))
        self.assertTrue(any(args[-2:] == ["-f", "install"] for args in self.apt_runs()))

    def test_dry_run(self):
        report, _failed = self.apply({"packages.install": ["inkscape"], "packages.remove": ["gimp"]}, dry_run=True)
        self.assertEqual(report, ["packages.install: would install inkscape", "packages.remove: would remove gimp"])
        self.assertEqual(self.apt_runs(), [])


class FakeServer:
    """The service's three requests (ADR-010), on 127.0.0.1."""

    def __init__(self):
        self.requests = []
        self.org = "Northfield School"
        self.seats = 3
        self.codes = {"ABCD-1234"}
        self.token = "t0ken-of-this-computer-0123456789"
        self.policy = None              # {"version": N, "values": {...}}
        self.answer = None              # (status, body) for the next check-in instead
        self.interval = 1800
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body=None, headers=()):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def handle_any(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                server.requests.append((self.command, self.path, dict(self.headers), body))
                self.reply(*server.answer_for(self.command, self.path, self.headers, body))

            do_GET = do_POST = handle_any

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def answer_for(self, method, path, headers, body):
        if path.startswith("/v1/join/"):
            code = path.rsplit("/", 1)[1]
            if code not in self.codes:
                return 404, {"error": "unknown code"}
            return (409, {"error": "no seat"}) if self.seats == 0 else (200, {"org": self.org, "seats_left": 2})
        if path == "/v1/join":
            return 200, {"computer": "c-17", "token": self.token, "org": self.org, "interval": self.interval}
        if headers.get("Authorization") != f"Bearer {self.token}":
            return 401, {"error": "unknown token"}
        if path == "/v1/checkin":
            if self.answer:
                return self.answer
            if self.policy and body.get("policy") != self.policy["version"]:
                return 200, {"policy": self.policy, "interval": self.interval}
            return 304, None
        if path == "/v1/leave":
            return 204, None
        return 404, None


class ServerTest(FleetTest):
    def setUp(self):
        super().setUp()
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        with open(os.path.join(self.tmp, "machine-id"), "w") as f:
            f.write("0123456789abcdef0123456789abcdef\n")
        proc = os.path.join(self.tmp, "proc")
        os.makedirs(proc)
        for name, text in (("uptime", "3600.5 7000.1\n"), ("cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=x quiet\n"),
                           ("meminfo", "MemTotal:        2020000 kB\n"),
                           ("cpuinfo", "processor\t: 0\nmodel name\t: Intel(R) Core(TM) i3-5005U\n")):
            with open(os.path.join(proc, name), "w") as f:
                f.write(text)
        for name, value in (("CONF", os.path.join(self.tmp, "etc/flickos/fleet")),
                            ("MACHINE_ID", os.path.join(self.tmp, "machine-id")),
                            ("RELEASE", os.path.join(self.tmp, "flickos-release")),
                            ("DMI", os.path.join(self.tmp, "dmi")),
                            ("POWER_SUPPLY", os.path.join(self.tmp, "power_supply")),
                            ("UPGRADE_STAMP", os.path.join(self.tmp, "upgrade-stamp")),
                            ("SERVER", self.server.url), ("running_as_root", lambda: True)):
            patcher = mock.patch.object(ff, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with open(ff.RELEASE, "w") as f:
            f.write('FLICKOS_VERSION="2.3"\nFLICKOS_DEBIAN=trixie\n')

    def main(self, *args, stdin_tty=False, answer="y"):
        stdin = io.StringIO(answer + "\n")
        stdin.isatty = lambda: stdin_tty
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err, mock.patch("sys.stdin", stdin):
            status = ff.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def join(self):
        status, out, err = self.main("join", "ABCD-1234", "--yes")
        self.assertEqual(status, 0, err)
        return out

    def checkins(self):
        return [r for r in self.server.requests if r[1] == "/v1/checkin"]

    def test_join_asks_shows_the_organization_and_keeps_the_token_to_root(self):
        out = self.join()
        self.assertIn("This computer will be managed by Northfield School.", out)
        self.assertIn("now managed by Northfield School", out)
        self.assertEqual([r[:2] for r in self.server.requests], [("GET", "/v1/join/ABCD-1234"), ("POST", "/v1/join")])
        body = self.server.requests[1][3]
        self.assertEqual(body["machine"], __import__("hashlib").sha256(b"0123456789abcdef0123456789abcdef").hexdigest())
        self.assertEqual((body["code"], body["flickos"], body["agent"]), ("ABCD-1234", "2.3", "1.0~test1"))
        self.assertEqual(body["inventory"]["memory_mb"], 1972)
        self.assertNotIn("uptime", body)
        self.assertEqual(os.stat(ff.CONF).st_mode & 0o777, 0o600)
        self.assertEqual(ff.read_conf(), {"Token": self.server.token, "Computer": "c-17", "Org": "Northfield School"})
        self.assertEqual(self.owners.commands("systemctl"), [["enable", "--now", "flickos-fleet.timer"],
                                                             ["start", "--no-block", "flickos-fleet.service"]])

    def test_join_with_another_server_keeps_it(self):
        with mock.patch.object(ff, "SERVER", "https://fleet.flickos.org"):
            self.assertEqual(self.main("join", "ABCD-1234", "--yes", "--server", self.server.url)[0], 0)
        self.assertEqual(ff.read_conf()["Server"], self.server.url)

    def test_join_asks_on_a_terminal_and_never_without_one(self):
        status, out, _err = self.main("join", "ABCD-1234", stdin_tty=True, answer="n")
        self.assertEqual(status, 1)
        self.assertTrue(out.endswith("Join? [y/N] Not joined.\n"), out)
        status, _out, err = self.main("join", "ABCD-1234")
        self.assertEqual(status, 1)
        self.assertIn("--yes", err)
        self.assertFalse(os.path.exists(ff.CONF))
        self.assertEqual([r[1] for r in self.server.requests], ["/v1/join/ABCD-1234"] * 2)

    def test_join_refusals(self):
        self.server.seats = 0
        self.assertIn("seats are in use", self.main("join", "ABCD-1234", "--yes")[2])
        self.assertIn("unknown or has expired", self.main("join", "WXYZ-9999", "--yes")[2])
        self.assertIn("isn't a join code", self.main("join", "../../x", "--yes")[2])
        with mock.patch.object(ff, "running_as_root", lambda: False):
            self.assertIn("run it as root", self.main("join", "ABCD-1234", "--yes")[2])
        with open(os.path.join(self.tmp, "proc", "cmdline"), "w") as f:
            f.write("boot=live quiet\n")
        self.assertIn("live session", self.main("join", "ABCD-1234", "--yes")[2])
        self.assertFalse(os.path.exists(ff.CONF))

    def test_lookup_needs_no_root_and_changes_nothing(self):
        with mock.patch.object(ff, "running_as_root", lambda: False):
            status, out, _err = self.main("lookup", "ABCD-1234")
            self.assertEqual((status, json.loads(out)), (0, {"org": "Northfield School"}))
            self.assertIn("unknown or has expired", self.main("lookup", "WXYZ-9999")[2])
        self.assertFalse(os.path.exists(ff.CONF))
        self.join()
        self.assertIn("already managed", self.main("lookup", "ABCD-1234")[2])

    def test_join_twice_is_refused(self):
        self.join()
        self.assertIn("already managed by Northfield School", self.main("join", "ABCD-1234", "--yes")[2])

    def test_only_https_servers(self):
        for url in ("http://fleet.example.org", "ftp://127.0.0.1", "https://"):
            with self.subTest(url=url), self.assertRaises(ff.FleetError):
                ff.check_server(url)
        self.assertEqual(ff.check_server("https://fleet.flickos.org/"), "https://fleet.flickos.org")

    def test_run_before_join_does_nothing(self):
        self.assertEqual(self.main("run")[0], 0)
        self.assertEqual(self.server.requests, [])

    def test_run_applies_a_new_policy_and_says_what_failed(self):
        self.join()
        self.server.policy = {"version": 4, "values": {"style": "light", "firewall": "bad"}}
        status, out, _err = self.main("run")
        self.assertEqual(status, 0)
        self.assertIn("site layouts.conf: written", out)
        state = ff.read_state()
        self.assertEqual((state["policy"], list(state["failed"])), (4, ["firewall"]))
        method, path, headers, body = self.checkins()[0]
        self.assertEqual(headers["Authorization"], f"Bearer {self.server.token}")
        self.assertNotIn(self.server.token, path)
        self.assertEqual((body["policy"], body["uptime"]), (0, 3600))
        self.assertNotIn("inventory", body)             # sent at join, today
        # The next check-in is due after the interval: an early timer run sends nothing.
        self.assertEqual(self.main("run")[0], 0)
        self.assertEqual(len(self.checkins()), 1)
        status, out, _err = self.main("run", "--now")
        self.assertEqual((status, out), (0, ""))         # 304: the policy is applied already
        self.assertEqual(self.checkins()[1][3]["failed"], {"firewall": "flickos-control: give on or off, not 'bad'"})
        self.assertEqual(self.checkins()[1][3]["policy"], 4)

    def test_the_inventory_goes_once_a_day(self):
        self.join()
        state = ff.read_state()
        state["inventory"] = "2026-01-01"
        ff.write_state(state)
        self.main("run")
        self.main("run", "--now")
        bodies = [r[3] for r in self.checkins()]
        self.assertIn("inventory", bodies[0])
        self.assertNotIn("inventory", bodies[1])
        inventory = bodies[0]["inventory"]
        self.assertEqual(sorted(inventory), sorted(ff.INVENTORY_FIELDS))
        self.assertEqual((inventory["cpu"], inventory["pending_updates"], inventory["held"]),
                         ("Intel(R) Core(TM) i3-5005U", 2, ["linux-image-amd64"]))
        self.assertEqual(sorted(bodies[0]), sorted([*ff.CHECKIN_FIELDS, "policy", "failed", "inventory"]))

    def test_a_longer_interval_is_kept_never_a_shorter_one(self):
        self.join()
        self.server.interval = 60
        self.main("run")
        state = ff.read_state()
        self.assertEqual(state["next"] - state["last"], ff.INTERVAL_MIN)
        self.server.answer = (200, {"interval": 7200})      # no policy: only the interval changes
        self.main("run", "--now")
        state = ff.read_state()
        self.assertEqual(state["next"] - state["last"], 7200)
        self.server.answer = None                           # 304, no body: the interval stays
        self.main("run", "--now")
        state = ff.read_state()
        self.assertEqual(state["next"] - state["last"], 7200)

    def test_removed_on_the_dashboard_leaves(self):
        self.join()
        self.server.policy = {"version": 1, "values": {"style": "light"}}
        self.main("run")
        self.assertTrue(os.path.exists(os.path.join(self.site, "layouts.conf")))
        self.server.answer = (410, {"leave": True})
        status, out, _err = self.main("run", "--now")
        self.assertEqual(status, 0)
        self.assertIn("left Northfield School", out)
        self.assertFalse(os.path.exists(ff.CONF))
        self.assertFalse(os.path.exists(os.path.join(self.site, "layouts.conf")))
        self.assertIn(["disable", "--now", "flickos-fleet.timer"], self.owners.commands("systemctl"))
        self.assertNotIn("/v1/leave", [r[1] for r in self.server.requests])

    def test_answers_that_say_not_now(self):
        self.join()
        for status, words in ((401, "join again"), (402, "subscription has ended"), (409, "copy of another")):
            with self.subTest(status=status):
                self.server.answer = (status, {})
                code, _out, err = self.main("run", "--now")
                self.assertEqual(code, 1)
                self.assertIn(words, err)
                state = ff.read_state()
                self.assertGreater(state["next"], __import__("time").time() + ff.RETRY_SECONDS - 60)
                self.assertTrue(os.path.exists(ff.CONF))        # nothing is undone

    def test_a_server_that_is_down(self):
        self.join()
        self.server.close()
        code, _out, err = self.main("run", "--now")
        self.assertEqual(code, 1)
        self.assertIn("can't reach", err)

    def test_redirects_are_refused(self):
        """A redirect would take the token along: never followed."""
        self.join()
        real = self.server.answer_for
        self.server.answer_for = lambda method, path, *rest: (
            (302, None, [("Location", self.server.url + "/steal")]) if path == "/v1/checkin" else
            real(method, path, *rest))
        code, _out, err = self.main("run", "--now")
        self.assertEqual(code, 1)
        self.assertIn("answered 302", err)
        self.assertNotIn("/steal", [r[1] for r in self.server.requests])

    def test_leave_tells_the_server_and_works_without_it(self):
        self.join()
        self.server.policy = {"version": 1, "values": {"touchpad.tap": False}}
        self.main("run")
        with mock.patch.object(ff, "in_sessions") as sessions:
            status, out, _err = self.main("leave")
        self.assertEqual(status, 0)
        self.assertEqual(self.server.requests[-1][:2], ("POST", "/v1/leave"))
        self.assertEqual(sessions.call_args.args[0], [["flickos-control", "apply-defaults"],
                                                      ["flickos-layout", "apply-defaults"]])
        self.assertFalse(os.path.exists(os.path.join(self.site, "input.conf")))
        self.assertEqual(ff.read_state(), {"v": 1, "files": [], "failed": {}})
        self.join()
        self.server.close()
        self.assertEqual(self.main("leave")[0], 0)
        self.assertFalse(os.path.exists(ff.CONF))
        self.assertEqual(self.main("leave")[1], "This computer isn't managed by an organization.\n")

    def test_status(self):
        self.assertEqual(self.main("status")[1], "This computer isn't managed by an organization.\n")
        self.join()
        self.server.policy = {"version": 2, "values": {"firewall": "bad"}}
        self.main("run")
        out = self.main("status")[1]
        self.assertIn("Managed by: Northfield School\n", out)
        self.assertIn("Policy version: 2\n", out)
        self.assertIn("Failed: firewall:", out)
        data = json.loads(self.main("status", "--json")[1])
        self.assertEqual((data["joined"], data["org"], data["policy"]), (True, "Northfield School", 2))

    def test_privacy_md_lists_every_field_sent(self):
        with open(os.path.join(PACKAGE, "PRIVACY.md"), encoding="utf-8") as f:
            text = f.read()
        for field in (*ff.CHECKIN_FIELDS, *ff.INVENTORY_FIELDS, "policy", "failed"):
            with self.subTest(field=field):
                self.assertIn(f"`{field}`", text)
        self.join()
        self.server.policy = {"version": 1, "values": {}}
        state = ff.read_state()
        state["inventory"] = "2026-01-01"
        ff.write_state(state)
        self.main("run")
        sent = set(self.checkins()[0][3]) | set(self.checkins()[0][3]["inventory"])
        self.assertEqual(sent - {"inventory"}, {*ff.CHECKIN_FIELDS, *ff.INVENTORY_FIELDS, "policy", "failed"})

    def test_a_name_from_the_server_is_printed_safely(self):
        self.server.org = "Evil\x1b[2J School\nInc"
        out = self.join()
        self.assertIn("managed by Evil[2J SchoolInc.", out)
        self.assertNotIn("\x1b", out)



@unittest.skipUnless(all(os.path.isdir(p) for p in (CONTROL_PACKAGE, LAYOUTS_PACKAGE, TILER_PACKAGE)),
                     "flickos-control, flickos-layouts and flick-tiler are not next to this package")
class RealOwnersTest(unittest.TestCase):
    """The file formats are an interface (ADR-004): the real owners, from the
    source tree, read what the agent writes, and refuse what they should."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-fleet-owners-")
        self.addCleanup(shutil.rmtree, self.tmp)
        root = os.path.join(self.tmp, "root")
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        for name, package, variable, prefix in (
                ("flickos-control", CONTROL_PACKAGE, "FLICKOS_CONTROL_PREFIX", root),
                ("flick-tiler", TILER_PACKAGE, "FLICK_TILER_PREFIX", root),
                ("flickos-layout", LAYOUTS_PACKAGE, "FLICKOS_LAYOUT_PREFIX", LAYOUTS_PACKAGE)):
            program = os.path.join(package, "usr/bin", name)
            with open(os.path.join(bin_dir, name), "w") as f:
                f.write(f'#!/bin/sh\nexport {variable}="{prefix}" PYTHONDONTWRITEBYTECODE=1\n'
                        f'exec "{sys.executable}" "{program}" "$@"\n')
            os.chmod(os.path.join(bin_dir, name), 0o755)
        self.site = os.path.join(root, "etc/xdg/flickos-site/flickos")
        for name, value in (("SITE_DIR", self.site), ("STATE_DIR", os.path.join(self.tmp, "state")),
                            ("OWNER_PATH", bin_dir + ":/usr/bin:/bin"), ("sessions", lambda: []),
                            ("CONTROL", os.path.join(bin_dir, "flickos-control")),
                            ("LAYOUT", os.path.join(bin_dir, "flickos-layout")),
                            ("TILER", os.path.join(bin_dir, "flick-tiler"))):
            patcher = mock.patch.object(ff, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_owners_take_good_values_and_refuse_bad_ones(self):
        report, failed = ff.apply_policy({"version": 1, "values": {
            "style": "light", "clock": "12h", "layout": "no-such-layout",
            "touchpad.tap": False, "touchpad.pointer-speed": 5, "idle.lock-after": 600,
            "tiler.mode": "grid", "tiler.gap": 12}})
        self.assertEqual(set(failed), {"layout", "touchpad.pointer-speed"}, report)
        self.assertIn("give a number from -1 to 1", failed["touchpad.pointer-speed"])
        with open(os.path.join(self.site, "input.conf"), encoding="utf-8") as f:
            self.assertNotIn("PointerSpeed", f.read())
        self.assertEqual(sorted(ff.read_state()["files"]),
                         ["idle.conf", "input.conf", "layouts.conf", "tiler.conf"])


if __name__ == "__main__":
    unittest.main()
