"""Tests for usr/bin/flickos-upgrade, the 2.x to 3.0 upgrade
(docs/design/flickos-upgrade.md, phases 1–3). Every outside path (apt's
sources, dpkg's status, /proc, /sys, apt-get itself) is in a temporary folder;
apt-get is a stand-in script that answers from files the test writes.
Run: python3 -m unittest discover -s tests"""

import contextlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
KEYRING_SOURCES = os.path.join(PACKAGE, "../flickos-archive-keyring/etc/apt/sources.list.d/flickos.sources")
RELEASE_FILE = os.path.join(PACKAGE, "../flickos-branding/usr/lib/flickos-release")


def tree_debian():
    """FLICKOS_DEBIAN of this tree: the keyring's sources are the old
    release's (what the tool reads) only on its branch. None where
    flickos-branding isn't next to this package (the package build's copy)."""
    try:
        with open(RELEASE_FILE, encoding="utf-8") as f:
            for line in f:
                if line.startswith("FLICKOS_DEBIAN="):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return None
_loader = importlib.machinery.SourceFileLoader("flickos_upgrade", os.path.join(PACKAGE, "usr/bin/flickos-upgrade"))
fu = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fu)

# Lines as apt-get -s printed them for 2.4 on forky (design, P1).
SIMULATION = """\
NOTE: This is only a simulation!
Inst labwc [0.8.3-1] (0.20.3-1 Debian:testing [amd64])
Inst base-files [13.8] (14.1 Debian:testing [amd64])
Inst python3 [3.13.5-1] (3.14.7-3 Debian:testing [amd64]) []
Inst gcc-16-base (16.1.0-3 Debian:testing [amd64])
Remv evince [48.1-3+deb13u1]
Remv libkpmcore12 [24.12.3-1]
Conf labwc (0.20.3-1 Debian:testing [amd64])
Conf zip (3.0-16 Debian:testing [amd64])
"""
SUMMARY = """\
Need to get 992 MB of archives.
After this operation, 1012 MB of additional disk space will be used.
Abort.
"""

# flickos-archive-keyring's file as 2.x ships it (the real one, when this
# package is built next to it, is checked in SourcesTest too).
FLICKOS_SOURCES = """\
# FlickOS package repository (comment lines as in the real file).
Types: deb
URIs: https://dvbondoy.github.io/flickos-apt
Suites: trixie trixie-community
Components: main
Signed-By: /usr/share/keyrings/flickos-archive-keyring.asc
"""

DESKTOP = """\
Package: flickos-desktop
Status: install ok installed
Version: 1.45
Depends: labwc (>= 0.8), waybar | sfwbar, flick-tiler, python3

"""


def status(*extra):
    """A dpkg status file: flickos-desktop, then NAME VERSION pairs."""
    text = DESKTOP
    for name, version in extra:
        text += f"Package: {name}\nStatus: install ok installed\nVersion: {version}\nInstalled-Size: 1000\n\n"
    text += "Package: gone\nStatus: deinstall ok config-files\nVersion: 1\n\n"
    return text


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="flickos-upgrade-test-")
        self.addCleanup(shutil.rmtree, self.root)
        for name, value in (("ROOT", self.root), ("APT_ETC", self.root + "/etc/apt"),
                            ("DPKG_STATUS", self.root + "/var/lib/dpkg/status"),
                            ("PROC", self.root + "/proc"), ("SYS", self.root + "/sys"),
                            ("APT_GET", self.root + "/bin/apt-get"), ("STAGE", self.root + "/var/lib/flickos/upgrade"),
                            ("LOG", self.root + "/var/log/flickos/upgrade.log"),
                            ("EXTENDED_STATES", self.root + "/var/lib/apt/extended_states"),
                            # Never the host's flickos-recovery (its restore points).
                            ("RECOVERY", self.root + "/usr/bin/flickos-recovery"), ("_recovery", None)):
            patcher = mock.patch.object(fu, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        write(self.root + "/var/lib/dpkg/status", status(("labwc", "0.8.3-1"), ("evince", "48.1-3")))
        write(self.root + "/proc/cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=x ro quiet\n")
        write(self.root + "/proc/self/mounts", "/dev/sda2 / ext4 rw 0 0\n")
        write(self.root + "/etc/apt/sources.list",
              "# Debian's\ndeb http://deb.debian.org/debian trixie main contrib non-free-firmware\n"
              "deb http://security.debian.org/debian-security trixie-security main\n"
              "deb-src http://deb.debian.org/debian trixie main\n")
        write(self.root + "/etc/apt/sources.list.d/flickos.sources", FLICKOS_SOURCES)
        write(self.root + "/etc/apt/sources.list.d/docker.list",
              "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian trixie stable\n")
        write(self.root + "/etc/apt/sources.list.d/old.sources",
              "Types: deb\nURIs: http://deb.debian.org/debian\nSuites: bookworm\nComponents: main\nEnabled: no\n")
        self.answers = os.path.join(self.root, "answers")
        os.makedirs(self.answers)
        self.answer(simulate=SIMULATION, summary=SUMMARY, upgrade="", update_fails_for="", update_warns_for="",
                    download_rc="0",
                    dist="", unlink="", full_rc="", install_rc="0", minimal_rc="0", audit="",
                    policy=POLICY_GONE, remove_sim="Remv evince [48.1-3]\n",
                    autoremove_sim="Remv libpython3.13 [3.13.5-1]\nRemv python3.13 [3.13.5-1]\n")
        # The stand-in apt-get: logs its arguments, answers from the files.
        write(self.root + "/bin/apt-get", f"""#!/bin/sh
A={self.answers}
echo "$*" >> $A/log
case " $* " in
  *" --no-download "*)
    # The install (phase 3): a status line on APT::Status-Fd (never stdout),
    # an output line, the answer's exit.
    fd=$(echo "$*" | sed -n 's/.*APT::Status-Fd=\\([0-9]*\\).*/\\1/p')
    [ -n "$fd" ] && [ "$fd" != 1 ] && echo "pmstatus:labwc:50.0:Installing labwc" > /proc/self/fd/$fd
    echo "Unpacking labwc (0.20.3-1) over (0.8.3-1) ..."
    case " $* " in
      *" full-upgrade "*)
        [ -n "$(cat $A/dist)" ] && touch "$(cat $A/dist)"
        [ -n "$(cat $A/unlink)" ] && rm -f "$(cat $A/unlink)"     # greetd's postinst, finding D
        rc=$(head -n 1 $A/full_rc); sed -i 1d $A/full_rc; exit ${{rc:-0}} ;;
      *" install "*) exit $(cat $A/install_rc) ;;
      *) exit $(cat $A/minimal_rc) ;;
    esac ;;
  *" update "*)
    parts=$(echo "$*" | sed -n 's/.*Dir::Etc::sourceparts=\\([^ ]*\\).*/\\1/p')
    fails=$(cat $A/update_fails_for)
    if [ -n "$fails" ] && grep -q "$fails" "$parts"/*.sources; then
        echo "E: The repository 'x $fails Release' does not have a Release file."; exit 100
    fi
    # apt exits 0 when a source only can't be reached (finding I).
    warns=$(cat $A/update_warns_for)
    if [ -n "$warns" ] && grep -q "$warns" "$parts"/*.sources; then
        echo "W: Failed to fetch http://$warns/debian/dists/forky/InRelease  Temporary failure resolving '$warns'"
        echo "W: Some index files failed to download. They have been ignored, or old ones used instead."
    fi
    exit 0 ;;
  *" --assume-no"*) cat $A/summary; exit 1 ;;
  *" --download-only "*) echo "Get:1 http://deb.debian.org/debian forky/main amd64 labwc 0.20.3-1"; exit $(cat $A/download_rc) ;;
  *" -s full-upgrade"*) cat $A/simulate ;;
  *" -s install "*) exit 0 ;;
  *" -s remove "*) cat $A/remove_sim ;;
  *" -s autoremove"*) cat $A/autoremove_sim ;;
  *" upgrade"*) cat $A/upgrade ;;
esac
""")
        os.chmod(self.root + "/bin/apt-get", 0o755)
        self.scratch = os.path.join(self.root, "scratch")
        patcher = mock.patch.object(fu.shutil, "disk_usage", return_value=mock.Mock(free=50 * 1000 ** 3))
        patcher.start()
        self.addCleanup(patcher.stop)

    def answer(self, **files):
        for name, text in files.items():
            write(os.path.join(self.answers, name), text)

    def apt_log(self):
        with open(os.path.join(self.answers, "log"), encoding="utf-8") as f:
            return f.read()


class OfferTest(Fixture):
    """ADR-003: offered once OPEN and the new release's FlickOS suites verify."""

    def offer(self, **kwargs):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.root + "/cache"}):
            return fu.offer(**kwargs)

    def test_closed_uses_no_network(self):
        self.assertEqual(self.offer(), {"offered": False, "why": "closed"})
        self.assertFalse(os.path.exists(os.path.join(self.answers, "log")))

    def test_force(self):
        self.assertEqual(self.offer(force=True), {"offered": True, "why": "force"})

    def test_open_and_published(self):
        with mock.patch.object(fu, "OPEN", True):
            self.assertEqual(self.offer(), {"offered": True, "why": None})
        parts = self.root + "/cache/flickos-upgrade/offer/parts/upgrade.sources"
        with open(parts, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Suites: forky forky-community", text)
        self.assertNotIn("deb.debian.org", text)       # only FlickOS's own suites
        self.assertIn(" update", self.apt_log())

    def test_open_but_not_published(self):
        self.answer(update_fails_for="forky-community")
        with mock.patch.object(fu, "OPEN", True):
            self.assertEqual(self.offer(), {"offered": False, "why": "not-published"})

    def test_never_in_the_live_session(self):
        write(self.root + "/proc/cmdline", "boot=live quiet\n")
        self.assertEqual(self.offer(force=True)["why"], "live")


class SourcesTest(Fixture):
    def test_entries_are_classified(self):
        kinds = {(entry["uris"][0], entry["suites"][0], entry["types"][0]): entry["kind"]
                 for entry in fu.read_sources()}
        self.assertEqual(kinds[("http://deb.debian.org/debian", "trixie", "deb")], "debian")
        self.assertEqual(kinds[("http://deb.debian.org/debian", "trixie", "deb-src")], "debian")
        self.assertEqual(kinds[("http://security.debian.org/debian-security", "trixie-security", "deb")], "debian")
        self.assertEqual(kinds[("https://dvbondoy.github.io/flickos-apt", "trixie", "deb")], "flickos")
        # Another maker's repository on a "trixie" suite stays where it is.
        self.assertEqual(kinds[("https://download.docker.com/linux/debian", "trixie", "deb")], "other")
        # A disabled stanza isn't a source.
        self.assertFalse(any("bookworm" in entry["suites"] for entry in fu.read_sources()))

    @unittest.skipUnless(os.path.isfile(KEYRING_SOURCES), "flickos-archive-keyring isn't next to this package")
    @unittest.skipUnless(tree_debian() == fu.TARGET["from"], "the keyring's sources are the new release's here")
    def test_the_real_flickos_sources(self):
        with open(KEYRING_SOURCES, encoding="utf-8") as f:
            entries = fu.parse_deb822(f.read(), KEYRING_SOURCES)
        self.assertEqual([(e["suites"], fu.classify(e)) for e in entries],
                         [(["trixie", "trixie-community"], "flickos")])

    def test_switch_moves_only_debian_and_flickos(self):
        text = fu.switched_sources(fu.read_sources())
        self.assertIn("URIs: http://deb.debian.org/debian\nSuites: forky\n", text)
        self.assertIn("Suites: forky-security", text)
        self.assertIn("Suites: forky forky-community", text)
        self.assertIn("URIs: https://download.docker.com/linux/debian\nSuites: trixie\n", text)
        self.assertIn("Architectures: amd64", text)
        self.assertNotIn("bookworm", text)

    def test_flickos_can_stay(self):
        text = fu.switched_sources(fu.read_sources(), move_flickos=False)
        self.assertIn("Suites: trixie trixie-community", text)
        self.assertIn("URIs: http://deb.debian.org/debian\nSuites: forky\n", text)

    def test_switch_suite(self):
        self.assertEqual(fu.switch_suite("trixie"), "forky")
        self.assertEqual(fu.switch_suite("trixie-updates"), "forky-updates")
        self.assertEqual(fu.switch_suite("trixie-community"), "forky-community")
        self.assertEqual(fu.switch_suite("trixiefoo"), "trixiefoo")
        self.assertEqual(fu.switch_suite("stable"), "stable")


class ParseTest(unittest.TestCase):
    def test_simulation(self):
        upgraded, new, removed = fu.parse_simulation(SIMULATION)
        self.assertEqual(upgraded, [{"name": "labwc", "old": "0.8.3-1", "new": "0.20.3-1"},
                                    {"name": "base-files", "old": "13.8", "new": "14.1"},
                                    {"name": "python3", "old": "3.13.5-1", "new": "3.14.7-3"}])
        self.assertEqual(new, [{"name": "gcc-16-base", "old": "", "new": "16.1.0-3"}])
        self.assertEqual([item["name"] for item in removed], ["evince", "libkpmcore12"])

    def test_sizes(self):
        self.assertEqual(fu.parse_sizes(SUMMARY), (992 * 1000 ** 2, 1012 * 1000 ** 2))
        self.assertEqual(fu.parse_sizes("Need to get 1,234 kB/5,678 kB of archives.\n"
                                        "After this operation, 2.5 MB disk space will be freed.\n"),
                         (1234000, -2500000))
        self.assertEqual(fu.parse_sizes("nothing\n"), (0, 0))

    def test_protected(self):
        protected = fu.protected_set({"flickos-desktop": {"Depends": "labwc (>= 0.8), waybar | sfwbar, flick-tiler"}})
        self.assertEqual(protected, {"flickos-desktop", "labwc", "waybar", "flick-tiler"})
        for name in ("labwc", "flickos-menu", "flick-tiler", "flickos-desktop"):
            self.assertTrue(fu.is_protected(name, protected), name)
        self.assertFalse(fu.is_protected("evince", protected))


class CheckTest(Fixture):
    def test_ready(self):
        self.assertEqual(fu.check(), [])

    def codes(self):
        return [problem["code"] for problem in fu.check()]

    def test_live_session(self):
        write(self.root + "/proc/cmdline", "boot=live components quiet\n")
        self.assertEqual(self.codes(), ["live"])

    def test_battery(self):
        supplies = self.root + "/sys/class/power_supply"
        write(supplies + "/BAT0/type", "Battery\n")
        write(supplies + "/AC/type", "Mains\n")
        write(supplies + "/AC/online", "0\n")
        self.assertEqual(self.codes(), ["battery"])
        write(supplies + "/AC/online", "1\n")
        self.assertEqual(self.codes(), [])

    def test_a_mouse_battery_is_not_the_computer(self):
        write(self.root + "/sys/class/power_supply/hid-mouse/type", "Battery\n")
        write(self.root + "/sys/class/power_supply/hid-mouse/scope", "Device\n")
        self.assertEqual(self.codes(), [])

    def test_test_versions(self):
        write(self.root + "/var/lib/dpkg/status", status(("flickos-style-glass", "1.0~test3")))
        problems = fu.check()
        self.assertEqual([p["code"] for p in problems], ["test-packages"])
        self.assertEqual(problems[0]["packages"], ["flickos-style-glass"])

    def test_no_desktop(self):
        write(self.root + "/var/lib/dpkg/status", "Package: labwc\nStatus: install ok installed\nVersion: 1\n\n")
        self.assertEqual(self.codes(), ["no-desktop"])


class PlanTest(Fixture):
    def plan(self, **kwargs):
        return fu.plan(scratch=self.scratch, **kwargs)

    def test_ready_plan(self):
        result = self.plan()
        self.assertTrue(result["ready"], result["problems"])
        self.assertEqual((result["upgraded"], result["new"]), (3, 1))
        self.assertEqual([item["name"] for item in result["removed"]], ["evince", "libkpmcore12"])
        self.assertEqual(result["replacements"], [{"old": "evince", "new": "papers"}])
        self.assertEqual(result["third_party"], ["https://download.docker.com/linux/debian"])
        self.assertEqual((result["download"], result["disk"]), (992 * 1000 ** 2, 1012 * 1000 ** 2))
        self.assertFalse(result["restore_point"])
        self.assertEqual(result["needed"], 992 * 1000 ** 2 + 1012 * 1000 ** 2 + fu.MARGIN)
        json.dumps(result)   # the page reads it

    def test_apt_runs_in_the_scratch_folder_only(self):
        self.plan()
        log = self.apt_log()
        self.assertIn(f"Dir::State={self.scratch}/state", log)
        self.assertIn(f"Dir::Cache={self.scratch}/cache", log)
        self.assertIn(f"Dir::State::status={self.root}/var/lib/dpkg/status", log)
        with open(os.path.join(self.scratch, "apt.conf"), encoding="utf-8") as f:
            self.assertIn("#clear DPkg::Pre-Install-Pkgs;", f.read())
        with open(os.path.join(self.scratch, "parts/upgrade.sources"), encoding="utf-8") as f:
            self.assertIn("Suites: forky forky-community", f.read())
        # Nothing but the simulation and the summary's --assume-no.
        for line in log.splitlines():
            self.assertTrue(" -s " in f" {line} " or "--assume-no" in line or line.endswith(" update"), line)

    def test_removing_flickos_refuses(self):
        self.answer(simulate=SIMULATION + "Remv flickos-menu [1.36]\nRemv waybar [0.12.0-1]\n")
        result = self.plan()
        self.assertFalse(result["ready"])
        self.assertEqual(result["refused"], ["flickos-menu", "waybar"])
        self.assertIn("removes-flickos", [p["code"] for p in result["problems"]])

    def test_a_source_that_fails_quietly_stops_the_plan(self):
        # Finding I: apt-get update exits 0 when Debian's mirror can't be
        # reached; the plan then saw FlickOS's packages alone.
        self.answer(update_warns_for="deb.debian.org")
        result = self.plan()
        self.assertFalse(result["ready"])
        self.assertEqual([p["code"] for p in result["problems"]], ["lists"])
        self.assertIn("Temporary failure resolving", result["problems"][0]["errors"][0])
        self.assertIn("APT::Update::Error-Mode=any", self.apt_log())

    def test_debian_not_moving_stops_the_plan(self):
        self.answer(simulate="Inst flickos-desktop [1.40] (1.46 FlickOS:forky [all])\n")
        result = self.plan()
        self.assertFalse(result["ready"])
        self.assertEqual([p["code"] for p in result["problems"]], ["no-new-debian"])

    def test_too_little_space(self):
        with mock.patch.object(fu.shutil, "disk_usage", return_value=mock.Mock(free=10 ** 9)):
            result = self.plan()
        self.assertEqual([p["code"] for p in result["problems"]], ["space"])
        self.assertEqual(result["problems"][0]["restore_points"], [])
        self.assertNotIn("restore points", result["problems"][0]["text"])

    def test_too_little_space_names_the_restore_points(self):
        # Finding E: back from the upgrade, the newer system kept as "before
        # putting back" holds the most.
        rec = FakeRecovery(self.root + "/.snapshots")
        rec.points = {"2026-11-22_17-40-02": {"reason": "flickos-upgrade", "keep": True},
                      "2026-11-22_17-56-16": {"reason": "before putting back 2026-11-22_17-40-02",
                                              "restored": "2026-11-22_17-40-02"}}
        with mock.patch.object(fu, "_recovery", rec), \
                mock.patch.object(fu.shutil, "disk_usage", return_value=mock.Mock(free=10 ** 9)):
            problem = self.plan()["problems"][0]
        self.assertEqual(problem["restore_points"],
                         [{"name": "2026-11-22_17-40-02", "description": "Before FlickOS 3.0", "put_back": False},
                          {"name": "2026-11-22_17-56-16", "description": "Before putting back a restore point",
                           "put_back": True}])
        self.assertIn("Deleting restore points frees space (2 kept", problem["text"])
        self.assertIn("\u201cBefore putting back a restore point\u201d: the system you went back from",
                      problem["text"])
        rec.problem = "ext4"
        with mock.patch.object(fu, "_recovery", rec):
            self.assertEqual(fu.deletable_restore_points(), [])

    def test_restore_point_space_on_btrfs(self):
        write(self.root + "/proc/self/mounts", "/dev/sda2 / btrfs rw,subvol=/@ 0 0\n")
        result = self.plan()
        self.assertTrue(result["restore_point"])
        # labwc (upgraded) and evince (removed) stay in the restore point: 1000 KiB each.
        self.assertEqual(result["needed"], 992 * 1000 ** 2 + 1012 * 1000 ** 2 + 2 * 1000 * 1024 + fu.MARGIN)

    def test_flickos_not_published(self):
        self.answer(update_fails_for="forky-community")
        result = self.plan()
        self.assertEqual([p["code"] for p in result["problems"]], ["lists"])
        self.assertIn("does not have a Release file", result["problems"][0]["errors"][0])

    def test_force_keeps_flickos_on_the_old_release(self):
        self.answer(update_fails_for="forky-community")
        result = self.plan(force=True)
        self.assertTrue(result["flickos_kept"])
        self.assertTrue(result["ready"], result["problems"])
        with open(os.path.join(self.scratch, "parts/upgrade.sources"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Suites: trixie trixie-community", text)
        self.assertIn("URIs: http://deb.debian.org/debian\nSuites: forky\n", text)

    def test_force_only_tells_about_test_versions(self):
        write(self.root + "/var/lib/dpkg/status", status(("flickos-control", "1.86~test1"), ("evince", "48.1-3")))
        self.assertEqual([p["code"] for p in self.plan()["problems"]], ["test-packages"])
        result = self.plan(force=True)
        self.assertTrue(result["ready"], result["problems"])
        self.assertEqual([w["code"] for w in result["warnings"]], ["test-packages"])

    def test_pending_updates(self):
        self.answer(upgrade="Inst labwc [0.8.3-1] (0.8.3-1+deb13u1 Debian:13.3/stable [amd64])\n")
        result = self.plan()
        problem = [p for p in result["problems"] if p["code"] == "updates-pending"]
        self.assertEqual(problem[0]["packages"], ["labwc"])

    def test_no_debian_sources(self):
        os.remove(self.root + "/etc/apt/sources.list")
        result = self.plan()
        self.assertEqual([p["code"] for p in result["problems"]], ["no-debian-sources"])

    def test_command_line(self):
        with mock.patch.object(fu, "cache_dir", return_value=self.scratch), \
             mock.patch("sys.stdout") as out:
            self.assertEqual(fu.main(["plan", "--json"]), 0)
        printed = "".join(call.args[0] for call in out.write.call_args_list)
        self.assertTrue(json.loads(printed)["ready"])
        with mock.patch("sys.stdout"):
            write(self.root + "/proc/cmdline", "boot=live\n")
            self.assertEqual(fu.main(["check"]), 1)


class SwitchTest(Fixture):
    """The sources switch (ADR-008), which phase 3's install applies."""

    def read(self, path):
        with open(self.root + path, encoding="utf-8") as f:
            return f.read()

    def test_changes(self):
        changes = {path[len(self.root):]: (old, new) for path, old, new in fu.switch_changes()}
        self.assertEqual(sorted(changes), ["/etc/apt/sources.list", "/etc/apt/sources.list.d/debian.sources",
                                           "/etc/apt/sources.list.d/flickos.sources"])
        old, new = changes["/etc/apt/sources.list.d/debian.sources"]
        self.assertIsNone(old)
        self.assertIn("URIs: http://deb.debian.org/debian\nSuites: forky\n", new)
        self.assertIn("Suites: forky-security", new)
        self.assertIn("Types: deb-src", new)
        old, new = changes["/etc/apt/sources.list"]
        self.assertIn("# Debian's\n", new)
        self.assertEqual(new.count(fu.MOVED), 3)
        self.assertNotIn("\ndeb ", "\n" + new)
        # FlickOS's file word for word: what 3.0's keyring ships.
        self.assertEqual(changes["/etc/apt/sources.list.d/flickos.sources"][1],
                         FLICKOS_SOURCES.replace("trixie", "forky"))

    def test_apply_and_undo(self):
        before = {name: self.read("/etc/apt/" + name) for name in
                  ("sources.list", "sources.list.d/flickos.sources", "sources.list.d/docker.list")}
        changes = fu.switch_changes()
        fu.apply_switch(changes)
        self.assertIn("Suites: forky forky-community", self.read("/etc/apt/sources.list.d/flickos.sources"))
        self.assertEqual(self.read("/etc/apt/sources.list.d/docker.list"), before["sources.list.d/docker.list"])
        backup = fu.backup_path(self.root + "/etc/apt/sources.list")
        with open(backup, encoding="utf-8") as f:
            self.assertEqual(f.read(), before["sources.list"])
        # The switched sources read back as the new release's.
        kinds = {(e["kind"], tuple(e["suites"])) for e in fu.read_sources()}
        self.assertIn(("debian", ("forky",)), kinds)
        self.assertNotIn(("debian", ("trixie",)), kinds)
        fu.undo_switch(changes)
        for name, text in before.items():
            self.assertEqual(self.read("/etc/apt/" + name), text)
        self.assertFalse(os.path.exists(self.root + "/etc/apt/sources.list.d/debian.sources"))

    def test_an_existing_debian_sources_is_switched_in_place(self):
        write(self.root + "/etc/apt/sources.list", "# empty, as deb822 installs leave it\n")
        write(self.root + "/etc/apt/sources.list.d/debian.sources",
              "# Debian\nTypes: deb\nURIs: http://deb.debian.org/debian\nSuites: trixie trixie-updates\n"
              "Components: main\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\n")
        changes = {path[len(self.root):]: new for path, _old, new in fu.switch_changes()}
        self.assertNotIn("/etc/apt/sources.list", changes)
        self.assertIn("# Debian\nTypes: deb\nURIs: http://deb.debian.org/debian\nSuites: forky forky-updates\n",
                      changes["/etc/apt/sources.list.d/debian.sources"])

    @unittest.skipUnless(os.path.isfile(KEYRING_SOURCES), "flickos-archive-keyring isn't next to this package")
    def test_the_real_flickos_sources_switch(self):
        with open(KEYRING_SOURCES, encoding="utf-8") as f:
            text = fu.switch_text(f.read(), KEYRING_SOURCES)
        self.assertIn("Suites: forky forky-community", text)
        self.assertNotIn("trixie", text)


class StageTest(Fixture):
    """prepare and discard (ADR-010): everything goes into STAGE."""

    def state(self):
        return fu.read_state()

    def test_prepare_stages_and_changes_nothing_else(self):
        sources = {}
        for name in ("sources.list", "sources.list.d/flickos.sources"):
            with open(self.root + "/etc/apt/" + name, encoding="utf-8") as f:
                sources[name] = f.read()
        with mock.patch("sys.stdout"):
            result = fu.prepare()
        self.assertTrue(result["ready"], result["problems"])
        state = self.state()
        self.assertEqual(state["step"], "staged")
        self.assertEqual((state["upgraded"], state["new"]), (3, 1))
        self.assertEqual(state["replacements"], [{"old": "evince", "new": "papers"}])
        log = self.apt_log()
        stage = self.root + "/var/lib/flickos/upgrade"
        downloads = [line for line in log.splitlines() if "--download-only" in line]
        self.assertEqual(len(downloads), 2)
        self.assertTrue(downloads[0].endswith("--download-only --yes full-upgrade"))
        self.assertTrue(downloads[1].endswith("--download-only --yes install papers"))
        self.assertTrue(all(f"Dir::Cache={stage}/apt/cache" in line for line in downloads))
        for name, text in sources.items():
            with open(self.root + "/etc/apt/" + name, encoding="utf-8") as f:
                self.assertEqual(f.read(), text, name)
        with open(self.root + "/var/log/flickos/upgrade.log", encoding="utf-8") as f:
            self.assertIn("Get:1 http://deb.debian.org/debian forky/main", f.read())

    def test_prepare_tells_the_page(self):
        with mock.patch("sys.stdout") as out:
            fu.prepare()
        printed = "".join(call.args[0] for call in out.write.call_args_list)
        events = [json.loads(line[len(fu.PROGRESS):]) for line in printed.splitlines()
                  if line.startswith(fu.PROGRESS)]
        self.assertEqual(events[0], {"step": "planning"})

    def test_a_refused_plan_downloads_nothing(self):
        self.answer(simulate=SIMULATION + "Remv flickos-menu [1.36]\n")
        result = fu.prepare()
        self.assertFalse(result["ready"])
        self.assertNotIn("--download-only", self.apt_log())
        self.assertEqual(self.state(), {})

    def test_a_failed_download(self):
        self.answer(download_rc="100")
        with mock.patch("sys.stdout"):
            result = fu.prepare()
        self.assertEqual([p["code"] for p in result["problems"]], ["download"])
        self.assertEqual(self.state()["step"], "failed")

    def test_discard(self):
        with mock.patch("sys.stdout"):
            fu.prepare()
        fu.discard()
        self.assertEqual(os.listdir(self.root + "/var/lib/flickos/upgrade"), ["lock"])
        self.assertEqual(self.state(), {})

    def test_not_while_installing(self):
        fu.write_state({"step": "installing"})
        with self.assertRaises(RuntimeError):
            fu.prepare()
        with self.assertRaises(RuntimeError):
            fu.discard()

    def test_one_at_a_time(self):
        with fu.stage_lock():
            with self.assertRaises(RuntimeError):
                with fu.stage_lock():
                    pass

    def test_status(self):
        with mock.patch("sys.stdout") as out:
            self.assertEqual(fu.main(["status", "--json"]), 0)
        self.assertEqual(json.loads(out.write.call_args_list[0].args[0]), {})


class FakeRecovery:
    """flickos-recovery's functions flickos-upgrade uses, on a dict."""

    class Refused(Exception):
        pass

    def __init__(self, snapshots):
        self.SNAPSHOTS = snapshots
        self.points, self.calls, self.problem, self.refuse = {}, [], None, None
        self.n = 0

    def layout_problem(self):
        return self.problem

    def enabled(self):
        return True

    def load_state(self):
        return {"good_boot": "boot-1"}

    def boot_id(self):
        return "boot-1"

    def restore_points(self):
        return sorted(self.points.items())

    def describe(self, info):
        return "Before putting back a restore point" if info.get("restored") else "Before FlickOS 3.0"

    def create(self, reason, details=None, session=None):
        if self.refuse:
            raise self.Refused(self.refuse)
        newest = self.restore_points()[-1][1] if self.points else {}
        if session and newest.get("session") == session:       # flickos-recovery's own rule
            raise self.Refused(f"the same run of {reason} as the newest restore point: none made")
        self.n += 1
        name = f"2026-11-22_00-00-0{self.n}"
        self.points[name] = dict({"reason": reason, "session": session, "created": self.n}, **(details or {}))
        self.calls.append(("create", name))
        return name

    def restore(self, name):
        self.n += 1
        before = f"2026-11-22_00-00-0{self.n}"
        self.points[before] = {"restored": name, "created": self.n}
        self.calls.append(("restore", name))
        return before

    def delete(self, name):
        del self.points[name]
        self.calls.append(("delete", name))

    def update_menu(self):
        pass

    @contextlib.contextmanager
    def locked(self):
        yield

    def write_json(self, path, data):
        self.points[os.path.basename(path)[:-5]] = data

    def commit(self, path):
        pass


class InstallFixture(Fixture):
    """Phase 3: the restart into the install and the install itself. dpkg,
    apt-config, Plymouth and the restart are stand-ins too."""

    def setUp(self):
        super().setUp()
        bin_ = self.root + "/bin"
        write(bin_ + "/dpkg", f"#!/bin/sh\necho \"$*\" >> {self.answers}/dpkg-log\n"
                              f"[ \"$1\" = --audit ] && cat {self.answers}/audit\nexit 0\n")
        write(bin_ + "/apt-config", "#!/bin/sh\ncat <<'X'\n" + HOOKS + "X\n")
        write(bin_ + "/apt-cache", f"#!/bin/sh\ncat {self.answers}/policy\n")
        write(bin_ + "/reboot", f"#!/bin/sh\necho reboot >> {self.answers}/reboot\n")
        write(bin_ + "/plymouth", f"#!/bin/sh\necho \"$*\" >> {self.answers}/plymouth\n")
        # flickos-branding's grub-install-device (finding J): logs that it ran.
        write(bin_ + "/grub-install-device", f"#!/bin/sh\necho ran >> {self.answers}/grub-device\n"
                                             "echo 'grub-install-device: grub-pc installs GRUB on /dev/vda'\n")
        for name in ("dpkg", "apt-config", "apt-cache", "reboot", "plymouth", "grub-install-device"):
            os.chmod(os.path.join(bin_, name), 0o755)
        self.rec = FakeRecovery(self.root + "/.snapshots")
        for name, value in (("TRIGGER", self.root + "/system-update"), ("APT_LISTS", self.root + "/var/lib/apt/lists"),
                            ("ETC", self.root + "/etc"), ("DPKG", bin_ + "/dpkg"),
                            ("DISPLAY_MANAGER_LINK", self.root + "/etc/systemd/system/display-manager.service"),
                            ("DEFAULT_DISPLAY_MANAGER", self.root + "/etc/X11/default-display-manager"),
                            ("APT_CONFIG", bin_ + "/apt-config"), ("APT_CACHE", bin_ + "/apt-cache"),
                            ("PLYMOUTH", bin_ + "/plymouth"), ("GRUB_INSTALL_DEVICE", bin_ + "/grub-install-device"),
                            ("REBOOT", (bin_ + "/reboot",)), ("_recovery", self.rec)):
            patcher = mock.patch.object(fu, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.boot("boot-1")
        write(self.root + "/var/lib/apt/lists/deb.debian.org_debian_dists_trixie_InRelease", "old")
        write(self.root + "/var/lib/apt/lists/lock", "")
        os.makedirs(self.root + "/etc/default")
        quiet = mock.patch("sys.stdout")
        quiet.start()
        self.addCleanup(quiet.stop)
        fu.prepare()
        # What prepare's apt-get would have fetched.
        write(self.root + "/var/lib/flickos/upgrade/apt/state/lists/deb.debian.org_debian_dists_forky_InRelease", "new")
        self.stage = self.root + "/var/lib/flickos/upgrade"
        self.trigger = self.root + "/system-update"

    def boot(self, boot_id):
        write(self.root + "/proc/sys/kernel/random/boot_id", boot_id + "\n")

    def read(self, path):
        with open(self.root + path, encoding="utf-8") as f:
            return f.read()

    def calls(self, name):
        path = os.path.join(self.answers, name)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()

    def installs(self):
        return [line for line in self.apt_log().splitlines()
                if "--no-download" in line or re.search(r"Dpkg::Use-Pty=0 (auto)?remove", line)]


# apt-cache policy for a package the new release dropped (P3: evince on forky).
POLICY_GONE = """evince:
  Installed: 48.1-3+deb13u1
  Candidate: 48.1-3+deb13u1
  Version table:
 *** 48.1-3+deb13u1 100
        100 /var/lib/dpkg/status
"""
POLICY_KEPT = POLICY_GONE.replace("        100 /var/lib/dpkg/status",
                                  "        500 http://deb.debian.org/debian forky/main amd64 Packages\n"
                                  "        100 /var/lib/dpkg/status")

HOOKS = '''DPkg::Pre-Install-Pkgs "";
DPkg::Pre-Install-Pkgs:: "/usr/sbin/dpkg-preconfigure --apt || true";
DPkg::Pre-Install-Pkgs:: "/usr/bin/flickos-recovery apt-hook 2>/dev/null || { [ $? -eq 100 ] && exit 1; cat >/dev/null; }";
'''


class ScheduleTest(InstallFixture):
    def test_install_links_the_trigger(self):
        fu.schedule()
        self.assertEqual(os.readlink(self.trigger), self.stage)
        state = fu.read_state()
        self.assertEqual(state["step"], "scheduled")
        self.assertTrue(state["restore_point"])
        self.assertTrue(state["good_start"])

    def test_no_restore_point_needs_consent(self):
        self.rec.problem = "/ isn't btrfs"
        with self.assertRaises(RuntimeError):
            fu.schedule()
        self.assertFalse(os.path.lexists(self.trigger))
        fu.schedule(no_way_back=True)
        self.assertFalse(fu.read_state()["restore_point"])
        with open(fu.LOG, encoding="utf-8") as f:
            self.assertIn("installing without one, as the user confirmed", f.read())

    def test_nothing_staged(self):
        fu.discard()
        with self.assertRaises(RuntimeError):
            fu.schedule()

    def test_cancel(self):
        fu.schedule()
        fu.cancel()
        self.assertFalse(os.path.lexists(self.trigger))
        self.assertEqual(fu.read_state()["step"], "staged")

    def test_not_again_while_scheduled(self):
        fu.schedule()
        with self.assertRaises(RuntimeError):
            fu.prepare()
        fu.discard()
        self.assertFalse(os.path.lexists(self.trigger))

    def test_another_programs_trigger_is_left_alone(self):
        os.symlink("/var/cache/PackageKit", self.trigger)
        self.assertEqual(fu.offline(), 0)
        self.assertEqual(os.readlink(self.trigger), "/var/cache/PackageKit")
        self.assertEqual(self.calls("reboot"), [])
        fu.discard()
        self.assertTrue(os.path.lexists(self.trigger))

    def test_never_the_real_restart_in_a_test(self):
        with mock.patch.object(fu, "REBOOT", fu.SYSTEM_REBOOT):
            with self.assertRaises(RuntimeError):
                fu.offline()


class InstallTest(InstallFixture):
    def test_the_install(self):
        self.answer(dist=self.root + "/etc/default/grub.dpkg-dist")
        fu.schedule()
        self.assertEqual(fu.main(["offline"]), 0)
        self.assertFalse(os.path.lexists(self.trigger))
        self.assertEqual(self.calls("reboot"), ["reboot"])
        # The restore point, marked for flickos-recovery (P6).
        (name, info), = self.rec.restore_points()
        self.assertEqual(info["reason"], "Before FlickOS 3.0")
        self.assertEqual((info["upgrade"], info["keep"], info["good"], info["session"]),
                         ("3.0", True, True, "flickos-upgrade:boot-1"))
        # The switch, and the staged lists in place of the old ones.
        self.assertIn("forky", self.read("/etc/apt/sources.list.d/debian.sources"))
        self.assertIn("Suites: forky forky-community", self.read("/etc/apt/sources.list.d/flickos.sources"))
        self.assertEqual(sorted(os.listdir(self.root + "/var/lib/apt/lists")),
                         ["deb.debian.org_debian_dists_forky_InRelease", "lock"])
        # apt: minimal, full, the replacement; from the stage; no recovery hook.
        runs = self.installs()
        # The replacement, then the old package the new release dropped (the plan said removed).
        self.assertEqual([run.split()[-1] for run in runs],
                         ["--without-new-pkgs", "full-upgrade", "papers", "evince", "autoremove"])
        self.assertIn(" remove evince", runs[-2])
        self.assertTrue(all(f"Dir::Cache::archives={self.stage}/apt/cache/archives/" in run for run in runs[:3]))
        self.assertTrue(all("--force-confold" in run for run in runs[:3]))
        self.assertTrue(all("-o FlickOS::Upgrade=3.0" in run for run in runs))     # History's mark
        self.assertTrue(all("APT::Status-Fd=" in run for run in runs[:3]))      # the splash's progress
        self.assertFalse(any("APT::Status-Fd=1 " in run for run in runs))    # dpkg needs its stdout
        state = fu.read_state()
        self.assertEqual(state["step"], "installed")
        self.assertEqual(state["restore_point_name"], name)
        self.assertEqual(state["kept_files"], ["/etc/default/grub.dpkg-dist"])
        self.assertEqual(state["replacements"], [{"old": "evince", "new": "papers"}])
        # What autoremove took: gone from dpkg's status (the fixture never had them).
        self.assertEqual(state["autoremoved"], ["libpython3.13", "python3.13"])
        self.assertEqual(sorted(os.listdir(self.stage)), ["lock", "state.json"])
        log = self.read("/var/log/flickos/upgrade.log")
        self.assertIn("Unpacking labwc", log)
        self.assertNotIn("pmstatus", log)
        # The splash: a message with the whole install's percentage.
        splash = self.calls("plymouth")
        self.assertIn("display-message --text=Installing FlickOS 3.0: 22 %. Don't turn off the computer.",
                      splash)                                   # 50 % of the first run (0–45)
        self.assertIn("system-update --progress=70", splash)     # 50 % of the full one (45–95)
        self.assertEqual(splash[-2], "display-message --text=FlickOS 3.0 is installed. Restarting…")

    def test_an_old_package_that_stays_in_the_new_release_stays(self):
        self.answer(policy=POLICY_KEPT)
        fu.schedule()
        fu.offline()
        self.assertEqual(self.installs()[-2].split()[-1], "papers")

    def test_an_old_package_whose_removal_takes_more_stays(self):
        self.answer(remove_sim="Remv evince [48.1-3]\nRemv my-pdf-tool [1.0]\n")
        fu.schedule()
        fu.offline()
        self.assertEqual(self.installs()[-2].split()[-1], "papers")
        self.assertIn("evince kept: removing it would remove more", self.read("/var/log/flickos/upgrade.log"))

    def test_autoremove_never_takes_flickos(self):
        self.answer(autoremove_sim="Remv python3.13 [3.13.5-1]\nRemv flick-tiler [1.20]\n")
        fu.schedule()
        fu.offline()
        self.assertNotIn("autoremove", self.installs()[-1])
        self.assertIn("autoremove left out: it would remove flick-tiler",
                      self.read("/var/log/flickos/upgrade.log"))
        self.assertEqual(fu.read_state()["step"], "installed")

    def test_autoremove_only_after_a_full_upgrade_that_worked(self):
        self.answer(full_rc="100\n100\n")
        fu.schedule()
        fu.offline()
        self.assertFalse(any("autoremove" in run for run in self.installs()))

    def login_screen(self):
        os.makedirs(self.root + "/etc/systemd/system", exist_ok=True)
        write(self.root + "/usr/lib/systemd/system/greetd.service", "[Unit]\n")
        os.symlink("/usr/lib/systemd/system/greetd.service", self.root + "/etc/systemd/system/display-manager.service")

    def test_the_login_screen_is_kept(self):
        self.login_screen()
        fu.schedule()
        self.assertEqual(fu.offline(), 0)
        self.assertEqual(self.read("/etc/X11/default-display-manager"), "/usr/sbin/greetd\n")
        self.assertEqual(os.readlink(self.root + "/etc/systemd/system/display-manager.service"),
                         "/usr/lib/systemd/system/greetd.service")

    def test_grub_pc_is_told_its_disk_before_the_install(self):
        # Finding J: on BIOS, grub-pc's upgrade stopped without its install device.
        fu.schedule()
        self.assertEqual(fu.offline(), 0)
        self.assertEqual(self.read("/answers/grub-device"), "ran\n")
        self.assertIn("grub-pc installs GRUB on /dev/vda", self.read("/var/log/flickos/upgrade.log"))

    def test_a_removed_login_screen_link_is_put_back(self):
        self.login_screen()
        self.answer(unlink=self.root + "/etc/systemd/system/display-manager.service")
        fu.schedule()
        self.assertEqual(fu.offline(), 0)
        self.assertEqual(os.readlink(self.root + "/etc/systemd/system/display-manager.service"),
                         "/usr/lib/systemd/system/greetd.service")
        self.assertIn("login screen's link was removed", self.read("/var/log/flickos/upgrade.log"))

    def test_a_gone_login_screen_is_a_failure(self):
        self.login_screen()
        os.unlink(self.root + "/usr/lib/systemd/system/greetd.service")
        self.answer(unlink=self.root + "/etc/systemd/system/display-manager.service")
        fu.schedule()
        self.assertEqual(fu.offline(), 1)
        self.assertEqual(self.rec.calls[-1][0], "restore")

    def test_no_login_screen_link_writes_nothing(self):
        fu.schedule()
        fu.offline()
        self.assertFalse(os.path.exists(self.root + "/etc/X11/default-display-manager"))

    def test_the_hooks_without_flickos_recovery(self):
        conf = fu.apt_install_conf()
        with open(conf, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("#clear DPkg::Pre-Install-Pkgs;", text)
        self.assertIn('DPkg::Pre-Install-Pkgs:: "/usr/sbin/dpkg-preconfigure --apt || true";', text)
        self.assertNotIn("flickos-recovery", text.split("\n", 1)[1])

    def test_flickos_kept_on_the_old_release(self):
        state = fu.read_state()
        state["flickos_kept"] = True
        fu.write_state(state)
        fu.schedule()
        fu.offline()
        self.assertIn("Suites: trixie trixie-community", self.read("/etc/apt/sources.list.d/flickos.sources"))
        self.assertIn("forky", self.read("/etc/apt/sources.list.d/debian.sources"))

    def test_a_failure_puts_the_restore_point_back(self):
        self.answer(full_rc="100\n100\n")
        fu.schedule()
        self.assertEqual(fu.offline(), 1)
        self.assertEqual(self.calls("reboot"), ["reboot"])
        point = [n for n, i in self.rec.restore_points() if i.get("upgrade")][0]
        self.assertIn(("restore", point), self.rec.calls)
        self.assertIn("--configure -a", self.calls("dpkg-log"))
        before = [i for n, i in self.rec.restore_points() if i.get("restored") == point][0]
        self.assertIn("full-upgrade stopped (100)", before["upgrade_failed"])
        # The next start is the restored system: its state.json says
        # "installing" from the start before.
        self.boot("boot-2")
        state = fu.status()
        self.assertEqual(state["step"], "returned")
        self.assertIn("full-upgrade", state["back"]["failed"])

    def test_a_second_try_of_the_full_upgrade(self):
        self.answer(full_rc="100\n0\n")
        fu.schedule()
        self.assertEqual(fu.offline(), 0)
        self.assertEqual(fu.read_state()["step"], "installed")

    def test_a_broken_result_is_a_failure(self):
        self.answer(audit="The following packages are only half configured:\n labwc\n")
        fu.schedule()
        self.assertEqual(fu.offline(), 1)
        self.assertEqual(self.rec.calls[-1][0], "restore")

    def test_no_restore_point_changes_nothing(self):
        self.rec.refuse = "only 1.0 GiB free"
        sources = self.read("/etc/apt/sources.list")
        fu.schedule()
        self.assertEqual(fu.offline(), 1)
        self.assertEqual(self.installs(), [])
        self.assertEqual(self.read("/etc/apt/sources.list"), sources)
        state = fu.read_state()
        self.assertEqual(state["step"], "failed")
        self.assertIn("1.0 GiB", state["error"])
        self.assertEqual(self.calls("reboot"), ["reboot"])

    def test_a_failed_switch_is_undone(self):
        sources = self.read("/etc/apt/sources.list")
        shutil.rmtree(self.stage + "/apt/state/lists")
        fu.schedule()
        fu.offline()
        self.assertEqual(self.read("/etc/apt/sources.list"), sources)
        self.assertFalse(os.path.exists(self.root + "/etc/apt/sources.list.d/debian.sources"))
        self.assertIn("deb.debian.org_debian_dists_trixie_InRelease", os.listdir(self.root + "/var/lib/apt/lists"))
        self.assertEqual(self.installs(), [])
        self.assertEqual(self.rec.restore_points(), [])     # its restore point deleted again
        self.assertEqual(fu.read_state()["step"], "failed")

    def test_without_a_way_back_it_stops_halfway(self):
        self.rec.problem = "/ isn't btrfs"
        self.answer(full_rc="100\n100\n")
        fu.schedule(no_way_back=True)
        fu.offline()
        self.assertEqual(self.rec.calls, [])
        self.boot("boot-2")
        self.assertEqual(fu.status()["step"], "interrupted")
        # Installing again goes on: no new restore point, dpkg first.
        fu.schedule()
        self.answer(full_rc="")
        os.unlink(os.path.join(self.answers, "dpkg-log"))
        self.assertEqual(fu.offline(), 0)
        self.assertEqual(self.calls("dpkg-log")[0], "--configure -a")
        self.assertEqual(fu.read_state()["step"], "installed")

    def test_a_second_try_after_going_back_gets_its_own_restore_point(self):
        fu.schedule()
        fu.offline()
        point = fu.read_state()["restore_point_name"]
        self.rec.restore(point)
        # The put-back system: the stage as it was when the restore point was taken.
        fu.write_state({"step": "staged", "target": fu.TARGET, "restore_point": True})
        write(self.stage + "/apt/state/lists/deb.debian.org_debian_dists_forky_InRelease", "new")
        self.boot("boot-3")
        fu.schedule()
        self.assertEqual(fu.offline(), 0)
        self.assertEqual(fu.read_state()["step"], "installed")
        sessions = [info.get("session") for _name, info in self.rec.restore_points() if info.get("upgrade")]
        self.assertEqual(sessions, ["flickos-upgrade:boot-1", "flickos-upgrade:boot-3"])

    def test_put_back_by_the_user(self):
        fu.schedule()
        fu.offline()
        point = fu.read_state()["restore_point_name"]
        self.rec.restore(point)
        # The put-back system: state.json from the moment the restore point was taken.
        fu.write_state({"step": "installing", "boot": "boot-1"})
        self.boot("boot-3")
        state = fu.status()
        self.assertEqual(state["step"], "returned")
        self.assertIsNone(state["back"]["failed"])
        self.assertIsNone(fu.notify_text(state))
        # The stage is old by now: download again.
        with self.assertRaises(RuntimeError):
            fu.schedule()


class NotifyTest(InstallFixture):
    def notify(self):
        sent = []

        def run(argv, **_kwargs):
            sent.append(argv)
            return mock.Mock(stdout="", returncode=0)
        with mock.patch.object(fu, "NOTED", self.root + "/home/.local/state/flickos/upgrade-noted"), \
                mock.patch.object(fu.shutil, "which", return_value="/usr/bin/notify-send"), \
                mock.patch.object(fu, "notifications_ready", return_value=True), \
                mock.patch.object(fu.subprocess, "run", side_effect=run):
            fu.notify()
        return [argv[-2:] for argv in sent]

    def test_nothing_before_the_install(self):
        self.assertEqual(self.notify(), [])

    def test_installed_once(self):
        self.answer(dist=self.root + "/etc/default/grub.dpkg-dist")
        fu.schedule()
        fu.offline()
        (title, body), = self.notify()
        self.assertEqual(title, "FlickOS 3.0 is installed")
        self.assertIn("1 settings file you had changed", body)
        self.assertEqual(self.notify(), [])

    def test_interrupted_at_every_login(self):
        fu.write_state({"step": "installing", "boot": "boot-0"})
        self.assertEqual(self.notify()[0][0], "The upgrade to FlickOS 3.0 didn't finish")
        self.assertEqual(len(self.notify()), 1)

    def test_failed_and_put_back(self):
        self.answer(full_rc="100\n100\n")
        fu.schedule()
        fu.offline()
        self.boot("boot-2")
        (title, _body), = self.notify()
        self.assertEqual(title, "The upgrade to FlickOS 3.0 failed")


class HelperTest(Fixture):
    """control-helper upgrade loads /usr/bin/flickos-upgrade (here, the
    package's own) and runs prepare or discard."""

    def setUp(self):
        super().setUp()
        loader = importlib.machinery.SourceFileLoader(
            "control_helper_upgrade", os.path.join(PACKAGE, "usr/libexec/flickos/control-helper"))
        self.helper = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(self.helper)
        patcher = mock.patch.object(self.helper, "UPGRADE_PROGRAM", os.path.join(PACKAGE, "usr/bin/flickos-upgrade"))
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"FLICKOS_UPGRADE_ROOT": self.root,
                                           "FLICKOS_UPGRADE_APT_GET": self.root + "/bin/apt-get",
                                           "XDG_CACHE_HOME": self.root + "/cache"})
        env.start()
        self.addCleanup(env.stop)

    def test_prepare_and_discard(self):
        with mock.patch("sys.stdout") as out:
            self.assertEqual(self.helper.cmd_upgrade(["prepare"]), 0)
        printed = "".join(call.args[0] for call in out.write.call_args_list)
        last = [line for line in printed.splitlines() if line.startswith(self.helper.UPGRADE_RESULT)][-1]
        self.assertTrue(json.loads(last[len(self.helper.UPGRADE_RESULT):])["ready"])
        self.assertTrue(os.path.exists(self.root + "/var/lib/flickos/upgrade/state.json"))
        with mock.patch("sys.stdout"):
            self.assertEqual(self.helper.cmd_upgrade(["discard"]), 0)
        self.assertFalse(os.path.exists(self.root + "/var/lib/flickos/upgrade/state.json"))

    def test_only_its_arguments(self):
        for args in ([], ["prepare", "--yes"], ["install", "--yes"], ["offline"], ["discard", "x"]):
            with self.assertRaises(self.helper.HelperError):
                self.helper.cmd_upgrade(args)


if __name__ == "__main__":
    unittest.main()
