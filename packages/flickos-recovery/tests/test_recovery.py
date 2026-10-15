"""Tests for usr/bin/flickos-recovery. Run: python3 -m unittest discover -s tests"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(PACKAGE, path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


rp = load("flickos_recovery", "usr/bin/flickos-recovery")
helper = load("recovery_helper", "usr/libexec/flickos/recovery-helper")

BTRFS_LAYOUT = """\
22 1 0:25 /@ / rw,noatime shared:1 - btrfs /dev/vda2 rw,compress=zstd:1,subvol=/@
23 22 0:25 /@home /home rw,noatime shared:2 - btrfs /dev/vda2 rw,subvol=/@home
24 22 0:25 /@snapshots SNAPSHOTS rw,noatime shared:3 - btrfs /dev/vda2 rw,subvol=/@snapshots
"""
EXT4 = "22 1 8:2 / / rw,noatime shared:1 - ext4 /dev/sda2 rw\n"

# apt's version 3 list: the configuration, an empty line, then one line per
# package: name, old version, arch, multi-arch, direction, new version, arch,
# multi-arch, then the .deb or an action.
V3 = """\
VERSION 3
APT::Architecture=amd64

sl - - none < 5.02-1 amd64 none /var/cache/apt/archives/sl_5.02-1_amd64.deb
sl - - none < 5.02-1 amd64 none **CONFIGURE**
libreoffice-core 4:25.2.1 amd64 same < 4:25.2.2 amd64 same /var/cache/apt/archives/libreoffice-core.deb
vlc 3.0.21 amd64 none > - - none **REMOVE**
"""


class Tree(unittest.TestCase):
    """A temporary /proc, /.snapshots, configuration and log, and a fake btrfs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.proc = os.path.join(root, "proc")
        self.snapshots = os.path.join(root, "snapshots")
        os.makedirs(os.path.join(self.proc, "self"))
        os.makedirs(os.path.join(self.proc, "sys/kernel/random"))
        os.mkdir(self.snapshots)
        with open(os.path.join(self.proc, "sys/kernel/random/boot_id"), "w") as f:
            f.write("boot-1\n")
        self.free = (50 * 1024 ** 3, 100 * 1024 ** 3)
        self.btrfs_calls = []
        for name, value in (("PROC", self.proc), ("SNAPSHOTS", self.snapshots),
                            ("LOCK", os.path.join(self.snapshots, ".flickos-recovery.lock")),
                            ("CONF", os.path.join(self.snapshots, ".flickos-recovery.conf")),
                            ("LOG", os.path.join(root, "recovery.log")),
                            ("EXTENDED_STATES", os.path.join(root, "extended_states")),
                            ("GRUB_STUB", os.path.join(root, "no-grub-stub")),
                            ("STATE_JSON", os.path.join(self.snapshots, ".flickos-start.json")),
                            ("STATE_CFG", os.path.join(self.snapshots, ".flickos-start.cfg")),
                            ("GRUB_ACCESS", os.path.join(self.snapshots, ".flickos-grub.json")),
                            ("BOOTED_FILE", os.path.join(root, "restore-point-boot")),
                            # Never the installed helper: run by a user, need_root()
                            # would exec pkexec on the build host and ask for a password.
                            ("HELPER", os.path.join(root, "no-recovery-helper")),
                            ("btrfs", self.fake_btrfs), ("free_space", lambda: self.free)):
            patcher = mock.patch.object(rp, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mounts(BTRFS_LAYOUT)
        # log() also prints to stderr: keep the test output clean.
        patcher = mock.patch.object(sys, "stderr", io.StringIO())
        self.stderr = patcher.start()
        self.addCleanup(patcher.stop)

    def mounts(self, text):
        with open(os.path.join(self.proc, "self/mountinfo"), "w") as f:
            f.write(text.replace("SNAPSHOTS", self.snapshots))

    def fake_btrfs(self, *argv):
        self.btrfs_calls.append(argv)
        if argv[:2] == ("filesystem", "sync"):
            return
        if argv[:3] == ("subvolume", "snapshot", "-r"):
            os.mkdir(argv[4])
        elif argv[:2] == ("subvolume", "delete"):
            os.rmdir(argv[2])
        else:
            raise AssertionError(f"unexpected btrfs {argv}")

    def names(self):
        return [name for name, _ in rp.restore_points()]

    def log_text(self):
        with open(rp.LOG) as f:
            return f.read()


class Parsing(unittest.TestCase):
    def test_changes_reads_installs_upgrades_and_removals(self):
        self.assertEqual(rp.changes(io.StringIO(V3)),
                         {"install": ["sl"], "upgrade": ["libreoffice-core"], "remove": ["vlc"]})

    def test_changes_skips_the_configuration_dump(self):
        self.assertEqual(rp.changes(io.StringIO("VERSION 3\nA::B=c d e f g h i j\n\n")),
                         {"install": [], "upgrade": [], "remove": []})

    def test_asked_for_takes_the_names_from_an_apt_command_line(self):
        self.assertEqual(rp.asked_for("apt install -y sl cowsay"), ("install", ["sl", "cowsay"]))
        self.assertEqual(rp.asked_for("apt-get purge vlc"), ("remove", ["vlc"]))
        self.assertEqual(rp.asked_for("apt install ./sl_5.02-1_amd64.deb"), ("install", ["sl"]))

    def test_asked_for_skips_option_values(self):
        line = ("apt-get -y -q -o DPkg::Lock::Timeout=600 -o Dpkg::Options::=--force-confdef "
                "-o Dpkg::Options::=--force-confold install sl")
        self.assertEqual(rp.asked_for(line), ("install", ["sl"]))
        self.assertEqual(rp.asked_for("apt -t trixie-backports install foo"), ("install", ["foo"]))
        self.assertEqual(rp.asked_for("apt-get -c apt.conf --option=A=b -oC=d purge vlc"), ("remove", ["vlc"]))

    def test_asked_for_takes_the_command_from_the_first_word(self):
        self.assertIsNone(rp.asked_for("apt-get download install"))
        self.assertIsNone(rp.asked_for("apt-get -o APT::Get::Purge=remove upgrade"))

    def test_asked_for_knows_nothing_without_named_packages(self):
        self.assertIsNone(rp.asked_for("apt upgrade"))
        self.assertIsNone(rp.asked_for("apt-get dist-upgrade -y"))
        self.assertIsNone(rp.asked_for("automatic updates"))


class Describe(unittest.TestCase):
    def say(self, **info):
        return rp.describe({"created": 0, **info}, set()).rsplit(",", 1)[0]

    def test_names_the_packages_the_user_asked_for(self):
        self.assertEqual(self.say(reason="apt install sl", packages={"install": ["sl", "libfoo1"]}),
                         "Before installing sl")

    def test_shortens_long_lists(self):
        self.assertEqual(self.say(reason="apt install a b c d"), "Before installing a, b and 2 more")

    def test_automatic_updates_and_upgrades(self):
        self.assertEqual(self.say(reason="automatic updates", packages={"upgrade": ["x"]}),
                         "Before automatic updates")
        self.assertEqual(self.say(reason="Software (PackageKit)", packages={"upgrade": ["x"]}),
                         "Before installing updates")

    def test_leaves_out_what_apt_installed_only_as_needed(self):
        auto = {"libgdbm6t64", "perl", "perl-modules-5.40"}
        self.assertEqual(rp.describe({"created": 0, "reason": "Software (PackageKit)",
                                      "packages": {"install": ["cowsay", "libgdbm6t64", "perl",
                                                               "perl-modules-5.40"]}}, auto).rsplit(",", 1)[0],
                         "Before installing cowsay")

    def test_reads_apts_marks(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("Package: perl\nArchitecture: amd64\nAuto-Installed: 1\n\n"
                    "Package: cowsay\nArchitecture: all\nAuto-Installed: 0\n")
        self.addCleanup(os.remove, f.name)
        with mock.patch.object(rp, "EXTENDED_STATES", f.name):
            self.assertEqual(rp.auto_installed(), {"perl"})

    def test_software_installs_and_removals(self):
        self.assertEqual(self.say(reason="Software (PackageKit)", packages={"install": ["gimp"]}),
                         "Before installing gimp")
        self.assertEqual(self.say(reason="Software (PackageKit)", packages={"remove": ["gimp"]}),
                         "Before removing gimp")
        self.assertEqual(self.say(reason="Software (PackageKit)",
                                  packages={"install": ["a"], "remove": ["b"]}),
                         "Before a software change")

    def test_a_restore_point_made_by_hand_keeps_its_reason(self):
        self.assertEqual(self.say(reason="before my experiment"), "before my experiment")


class Layout(Tree):
    def test_btrfs_layout_has_no_problem(self):
        self.assertIsNone(rp.layout_problem())

    def test_nothing_in_a_chroot(self):
        # The installer runs apt in a chroot of the new system: its mountinfo
        # shows the layout, but / isn't PID 1's root.
        os.makedirs(os.path.join(self.proc, "1"))
        os.symlink(self.tmp.name, os.path.join(self.proc, "1", "root"))
        self.assertIn("chroot", rp.layout_problem())
        with self.assertRaises(rp.Refused):
            rp.create("apt-get install grub-efi")
        os.remove(os.path.join(self.proc, "1", "root"))
        os.symlink("/", os.path.join(self.proc, "1", "root"))
        self.assertIsNone(rp.layout_problem())

    def test_ext4_has_a_problem(self):
        self.mounts(EXT4)
        self.assertIn("isn't the @ subvolume", rp.layout_problem())

    def test_snapshots_must_be_mounted(self):
        self.mounts(BTRFS_LAYOUT.splitlines()[0] + "\n")
        self.assertIn("@snapshots", rp.layout_problem())

    def test_the_last_mount_at_a_place_counts(self):
        self.mounts(BTRFS_LAYOUT + "30 22 0:40 / / rw - overlay overlay rw\n")
        self.assertEqual(rp.findmnt("/"), ("overlay", "/"))
        self.assertIsNotNone(rp.layout_problem())


class Create(Tree):
    def test_takes_a_read_only_snapshot_with_its_reason(self):
        name = rp.create("apt install sl", {"packages": {"install": ["sl"]}}, "100:5")
        # Committed at once: a power cut early in the upgrade must not lose it.
        self.assertEqual(self.btrfs_calls, [("subvolume", "snapshot", "-r", "/",
                                             os.path.join(self.snapshots, name)),
                                            ("filesystem", "sync", self.snapshots)])
        info = dict(rp.restore_points())[name]
        self.assertEqual((info["reason"], info["session"], info["boot"]), ("apt install sl", "100:5", "boot-1"))
        self.assertIn("created " + name, self.log_text())

    def test_one_restore_point_per_run_of_a_program(self):
        rp.create("automatic updates", session="7:9")
        with self.assertRaises(rp.Refused):
            rp.create("automatic updates", session="7:9")
        rp.create("automatic updates", session="8:1")
        self.assertEqual(len(self.names()), 2)

    def test_two_in_one_second_get_different_names(self):
        with mock.patch.object(rp.datetime, "datetime") as dt:
            dt.now.return_value.strftime.return_value = "2026-10-10_12-00-00"
            a, b = rp.create("one"), rp.create("two")
        self.assertEqual((a, b), ("2026-10-10_12-00-00", "2026-10-10_12-00-00-2"))

    def test_keeps_only_the_newest(self):
        for i in range(rp.KEEP + 2):
            os.mkdir(os.path.join(self.snapshots, f"2026-01-0{i + 1}_00-00-00"))
            with open(os.path.join(self.snapshots, f"2026-01-0{i + 1}_00-00-00.json"), "w") as f:
                json.dump({"reason": "old", "created": 0}, f)
        new = rp.create("by hand")
        self.assertEqual(len(self.names()), rp.KEEP)
        self.assertEqual(self.names()[-1], new)
        self.assertNotIn("2026-01-01_00-00-00", self.names())
        self.assertNotIn("2026-01-03_00-00-00", self.names())

    def test_never_touches_snapshots_that_are_not_restore_points(self):
        os.mkdir(os.path.join(self.snapshots, "2000-01-01_my-own"))
        for _ in range(rp.KEEP + 1):
            rp.create("by hand")
        self.assertTrue(os.path.isdir(os.path.join(self.snapshots, "2000-01-01_my-own")))
        with self.assertRaises(rp.Refused):
            rp.delete("2000-01-01_my-own")

    def test_none_while_the_disk_is_nearly_full(self):
        self.free = (int(9.5 * 1024 ** 3), 100 * 1024 ** 3)     # less than 10 %
        with self.assertRaises(rp.Refused) as why:
            rp.create("by hand")
        self.assertIn("GiB free", str(why.exception))
        self.free = (int(1.5 * 1024 ** 3), 10 * 1024 ** 3)      # 15 %, but under 2 GiB
        with self.assertRaises(rp.Refused):
            rp.create("by hand")
        self.assertEqual(self.names(), [])

    def test_nothing_on_ext4(self):
        self.mounts(EXT4)
        with self.assertRaises(rp.Refused):
            rp.create("by hand")
        self.assertEqual(self.btrfs_calls, [])

    def test_nothing_while_turned_off(self):
        rp.set_setting("enabled", "no")
        with self.assertRaises(rp.Refused) as why:
            rp.create("by hand")
        self.assertIn("turned off", str(why.exception))


class Settings(Tree):
    def test_on_by_default(self):
        self.assertEqual(rp.get("enabled"), ("yes", "default"))

    def test_set_and_back_to_default(self):
        rp.set_setting("enabled", "no")
        self.assertEqual(rp.get("enabled"), ("no", "system"))
        rp.set_setting("enabled", "default")
        self.assertEqual(rp.get("enabled"), ("yes", "default"))

    def test_nothing_to_set_on_ext4(self):
        self.mounts(EXT4)
        with self.assertRaises(rp.Refused):
            rp.set_setting("enabled", "no")

    def test_kept_while_running_from_a_restore_point(self):
        # In @snapshots, not /etc: neither the memory layer nor putting back loses it.
        self.assertTrue(rp.CONF.startswith(self.snapshots + "/"))

    def test_refuses_unknown_keys_and_values(self):
        with self.assertRaises(rp.Refused):
            rp.set_setting("enabled", "maybe")
        with self.assertRaises(rp.Refused):
            rp.set_setting("colour", "red")


class Hook(Tree):
    def run_hook(self, text=V3):
        stream = io.StringIO(text)
        self.assertEqual(rp.apt_hook(stream), 0)
        self.assertEqual(stream.read(), "")     # apt's whole list was read
        return stream

    def test_makes_a_restore_point_saying_what_changed(self):
        with mock.patch.object(rp, "front_end", lambda: ("apt install sl", "42:7")):
            self.run_hook()
        (name, info), = rp.restore_points()
        self.assertEqual(info["changes"], {"install": 1, "upgrade": 1, "remove": 1})
        self.assertEqual(rp.describe(info).rsplit(",", 1)[0], "Before installing sl")
        self.assertIn("hook took", self.log_text())

    def test_silent_on_ext4_and_while_off(self):
        self.mounts(EXT4)
        self.run_hook()
        self.mounts(BTRFS_LAYOUT)
        rp.set_setting("enabled", "no")
        self.run_hook()
        self.assertEqual(self.btrfs_calls, [])
        self.assertNotIn("hook took", self.log_text())

    def test_never_fails_apt(self):
        def broken(*argv):
            raise subprocess.CalledProcessError(1, ["btrfs", *argv])
        with mock.patch.object(rp, "btrfs", broken), \
                mock.patch.object(rp, "front_end", lambda: ("apt upgrade", "1:1")):
            self.run_hook()
        self.assertIn("apt goes on without a restore point", self.log_text())

    def test_reads_the_rest_of_the_list_when_parsing_fails(self):
        with mock.patch.object(rp, "changes", mock.Mock(side_effect=ValueError("bad"))):
            self.run_hook()


class FrontEnd(Tree):
    """A fake process tree: the hook's parent is dpkg's apt, under PROGRAMS."""

    def tree(self, *chain):
        """CHAIN: command lines from the hook's parent outwards."""
        pids = list(range(100, 100 + len(chain)))
        for i, argv in enumerate(chain):
            d = os.path.join(self.proc, str(pids[i]))
            os.mkdir(d)
            with open(os.path.join(d, "cmdline"), "wb") as f:
                f.write(b"\0".join(a.encode() for a in argv) + b"\0")
            parent = pids[i + 1] if i + 1 < len(chain) else 1
            fields = ["S", str(parent)] + ["0"] * 17 + [str(5000 + i)]
            with open(os.path.join(d, "stat"), "w") as f:
                f.write(f"{pids[i]} ({os.path.basename(argv[0])}) {' '.join(fields)}\n")
        patcher = mock.patch.object(rp.os, "getppid", lambda: pids[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_apt_names_its_command_line(self):
        self.tree(["sh", "-c", "hook"], ["apt", "install", "sl"], ["bash"])
        self.assertEqual(rp.front_end(), ("apt install sl", "101:5001"))

    def test_automatic_updates_use_the_outermost_run(self):
        self.tree(["sh"], ["/usr/bin/python3", "/usr/bin/unattended-upgrade"],
                  ["/usr/bin/python3", "/usr/bin/unattended-upgrade"], ["systemd"])
        self.assertEqual(rp.front_end(), ("automatic updates", "102:5002"))

    def test_packagekit_uses_the_nearest_transaction(self):
        self.tree(["sh"], ["/usr/libexec/packagekitd"], ["/usr/libexec/packagekitd"], ["systemd"])
        self.assertEqual(rp.front_end(), ("Software (PackageKit)", "101:5001"))

    def test_unknown_program(self):
        self.tree(["sh"], ["dpkg", "-i", "x.deb"])
        self.assertEqual(rp.front_end(), ("unknown", None))


class CommandLine(Tree):
    def run_main(self, *argv, root=True):
        out = io.StringIO()
        with mock.patch.object(rp.os, "geteuid", lambda: 0 if root else 1000), \
                contextlib.redirect_stdout(out):
            code = rp.main(list(argv))
        return code, out.getvalue()

    def test_list_prints_name_and_description(self):
        self.run_main("create", "before my experiment")
        code, out = self.run_main("list")
        self.assertEqual(code, 0)
        name, what = out.strip().split("\t")
        self.assertTrue(what.startswith("before my experiment, "))

    def test_list_on_ext4_says_why(self):
        self.mounts(EXT4)
        self.assertEqual(self.run_main("list")[0], 1)
        self.assertIn("no restore points on this system", self.stderr.getvalue())

    def test_changes_need_root(self):
        self.assertEqual(self.run_main("create", root=False)[0], 1)
        self.assertEqual(self.run_main("set", "enabled", "no", root=False)[0], 1)
        self.assertEqual(self.names(), [])

    def test_state_is_json_for_the_settings_page(self):
        self.run_main("create", "by hand")
        state = json.loads(self.run_main("state")[1])
        self.assertTrue(state["available"] and state["enabled"])
        self.assertEqual(len(state["points"]), 1)
        self.assertEqual(state["min_free_bytes"], 10 * 1024 ** 3)

    def test_get_prints_key_value_source(self):
        self.assertEqual(self.run_main("get")[1], "enabled\tyes\tdefault\nauto-recover\tyes\tdefault\n")

    def test_delete_all(self):
        self.run_main("create", "a")
        self.run_main("create", "b")
        self.assertEqual(self.run_main("delete", "--all")[0], 0)
        self.assertEqual(self.names(), [])


class AptConfig(unittest.TestCase):
    """apt picks the version 3 list by the command's first word."""

    def command(self):
        with open(os.path.join(PACKAGE, "etc/apt/apt.conf.d/80flickos-recovery")) as f:
            text = f.read()
        return text, text.split('Pre-Install-Pkgs { "', 1)[1].split('"; };', 1)[0]

    def test_version_3_key_matches_the_command(self):
        text, command = self.command()
        self.assertIn(f"DPkg::Tools::Options::{command.split()[0]}::Version \"3\";", text)

    def sh(self, program):
        """Run the configured line through sh as apt does, with PROGRAM
        (a shell script body, or None for a missing program) in place."""
        _, command = self.command()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "flickos-recovery")
            if program is not None:
                with open(path, "w") as f:
                    f.write("#!/bin/sh\n" + program + "\n")
                os.chmod(path, 0o755)
            line = command.replace("/usr/bin/flickos-recovery", path)
            done = subprocess.run(["sh", "-c", line], input="VERSION 3\n\n" + "x\n" * 50000,
                                  capture_output=True, text=True)
        return done.returncode

    def test_apt_goes_on_when_the_program_is_gone_or_fails(self):
        self.assertEqual(self.sh(None), 0)
        self.assertEqual(self.sh("cat >/dev/null; exit 1"), 0)
        self.assertEqual(self.sh("exit 0"), 0)

    def test_apt_stops_when_the_hook_refuses(self):
        self.assertEqual(self.sh("cat >/dev/null; exit 100"), 1)

    @unittest.skipUnless(shutil.which("apt-config"), "apt-config not installed")
    def test_apt_parses_it(self):
        out = subprocess.run(["apt-config", "-c", os.path.join(PACKAGE, "etc/apt/apt.conf.d/80flickos-recovery"),
                              "dump", "DPkg::Pre-Install-Pkgs"], capture_output=True, text=True)
        self.assertIn("flickos-recovery apt-hook", out.stdout)



class PutBack(Tree):
    """restore and settle, on a fake top level: @ and @snapshots as folders."""

    def setUp(self):
        super().setUp()
        self.top = os.path.join(self.tmp.name, "top")
        os.makedirs(os.path.join(self.top, "@"))
        os.rmdir(self.snapshots)
        os.symlink(self.snapshots, os.path.join(self.top, "@snapshots"))
        os.makedirs(self.snapshots)
        self.grub = []

        @contextlib.contextmanager
        def top_level(device):
            self.assertEqual(device, "/dev/vda2")
            yield self.top

        def grub(device):
            self.grub.append(device)
            self.btrfs_calls.append(("grub-install",))

        for name, value in (("top_level", top_level), ("reinstall_bootloader", grub)):
            patcher = mock.patch.object(rp, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(rp.subprocess, "run")      # btrfs filesystem sync
        patcher.start()
        self.addCleanup(patcher.stop)
        self.point = rp.create("apt install sl")

    def fake_btrfs(self, *argv):
        if argv[:2] == ("subvolume", "snapshot") and argv[2] != "-r":
            self.btrfs_calls.append(argv)
            os.mkdir(argv[3])
        elif argv[:2] == ("property", "set") or argv[:2] == ("filesystem", "sync"):
            self.btrfs_calls.append(argv)
        else:
            super().fake_btrfs(*argv)

    def boot(self, boot_id):
        with open(os.path.join(self.proc, "sys/kernel/random/boot_id"), "w") as f:
            f.write(boot_id + "\n")

    def test_swaps_the_system_and_keeps_the_old_one(self):
        with open(os.path.join(self.top, "@", "marker"), "w") as f:
            f.write("the system before")
        before = rp.restore(self.point)
        self.assertTrue(os.path.exists(os.path.join(self.snapshots, before, "marker")))
        self.assertFalse(os.path.exists(os.path.join(self.top, "@", "marker")))
        self.assertIn(("subvolume", "snapshot", os.path.join(self.top, "@snapshots", self.point),
                       os.path.join(self.top, "@")), self.btrfs_calls)
        self.assertEqual(self.grub, ["/dev/vda2"])
        # The swap is committed before GRUB is installed again.
        calls = self.btrfs_calls
        self.assertLess(calls.index(("filesystem", "sync", self.top)), calls.index(("grub-install",)))
        info = dict(rp.restore_points())[before]
        self.assertEqual(info["restored"], self.point)
        self.assertEqual(rp.describe(info, set()).rsplit(",", 1)[0], "Before putting back a restore point")
        self.assertEqual(rp.pending()["before"], before)

    def test_undoes_the_swap_when_grub_fails(self):
        with open(os.path.join(self.top, "@", "marker"), "w") as f:
            f.write("the system before")

        def broken(device):
            raise subprocess.CalledProcessError(1, ["grub-install"])
        with mock.patch.object(rp, "reinstall_bootloader", broken), self.assertRaises(rp.Refused):
            rp.restore(self.point)
        self.assertTrue(os.path.exists(os.path.join(self.top, "@", "marker")))
        self.assertIsNone(rp.pending())
        self.assertEqual(self.names(), [self.point])

    def test_apt_and_a_second_restore_wait_for_the_restart(self):
        rp.restore(self.point)
        stream = io.StringIO(V3)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(rp.apt_hook(stream), rp.REFUSE_APT)
        self.assertEqual(stream.read(), "")
        self.assertIn("restart the computer", out.getvalue())
        with self.assertRaises(rp.Refused):
            rp.restore(self.point)
        with self.assertRaises(rp.Refused):
            rp.create("by hand")

    def test_settle_after_the_restart(self):
        before = rp.restore(self.point)
        with self.assertRaises(rp.Refused):
            rp.settle()                     # the same start
        self.boot("boot-2")
        self.assertEqual(rp.settle(), 0)
        self.assertIn(("property", "set", "-ts", os.path.join(self.snapshots, before), "ro", "true"),
                      self.btrfs_calls)
        self.assertIsNone(rp.pending())
        self.assertEqual(rp.settle(), 0)    # nothing pending: nothing to do

    def test_list_works_before_the_restart(self):
        rp.restore(self.point)
        # / now shows the old @ under its new name in @snapshots.
        self.mounts(BTRFS_LAYOUT.replace("/@ / ", "/@snapshots/x / "))
        self.assertIsNone(rp.layout_problem())
        self.boot("boot-2")
        self.assertIsNotNone(rp.layout_problem())

    def test_the_next_change_settles_when_the_service_did_not(self):
        before = rp.restore(self.point)
        self.boot("boot-2")
        with mock.patch.object(rp.os, "geteuid", lambda: 0):
            rp.create("apt install cowsay")
        self.assertIsNone(rp.pending())
        self.assertIn(("property", "set", "-ts", os.path.join(self.snapshots, before), "ro", "true"),
                      self.btrfs_calls)

    def test_apt_goes_on_after_the_restart(self):
        rp.restore(self.point)
        self.boot("boot-2")
        self.assertIsNone(rp.restart_pending())


class Plan(Tree):
    HISTORY = """
Start-Date: 2026-10-09  10:00:00
Commandline: apt install old
Install: old:amd64 (1.0)
End-Date: 2026-10-09  10:00:05

Start-Date: 2026-10-10  12:00:00
Commandline: apt install sl
Install: sl:amd64 (5.02-1+b1), libfoo1:amd64 (1.0, automatic)
End-Date: 2026-10-10  12:00:05

Start-Date: 2026-10-10  13:00:00
Commandline: /usr/bin/unattended-upgrade
Upgrade: libreoffice-core:amd64 (4:25.2.1, 4:25.2.2), vlc:amd64 (3.0.20, 3.0.21)
Remove: cowsay:all (3.03)
End-Date: 2026-10-10  13:01:00
"""

    def test_lists_what_apt_did_since_the_restore_point(self):
        path = os.path.join(self.tmp.name, "history.log")
        with open(path, "w") as f:
            f.write(self.HISTORY)
        import datetime
        since = datetime.datetime(2026, 10, 10, 11, 0).timestamp()
        with mock.patch.object(rp, "HISTORY", path):
            entries = rp.history_entries(since)
        self.assertEqual([e["command"] for e in entries], ["apt install sl", "/usr/bin/unattended-upgrade"])
        self.assertEqual(entries[0]["install"], ["sl"])     # libfoo1 came along: automatic
        self.assertEqual(entries[1]["upgrade"], ["libreoffice-core", "vlc"])
        self.assertEqual(entries[1]["remove"], ["cowsay"])

    def test_plan_names_the_restore_point(self):
        name = rp.create("apt install sl")
        with mock.patch.object(rp, "HISTORY", os.path.join(self.tmp.name, "none")):
            plan = rp.plan(name)
        self.assertEqual((plan["name"], plan["changes"]), (name, []))
        with self.assertRaises(rp.Refused):
            rp.plan("2000-01-01_00-00-00")


class Helper(unittest.TestCase):
    def test_accepts_only_known_verbs_and_checked_arguments(self):
        ok = {("create",): ["create"], ("create", "before my test"): ["create", "before my test"],
              ("restore", "2026-10-10_12-00-00"): ["restore", "2026-10-10_12-00-00"],
              ("restore", "2026-10-10_12-00-00-2"): ["restore", "2026-10-10_12-00-00-2"],
              ("delete", "--all"): ["delete", "--all"],
              ("enabled", "no"): ["set", "enabled", "no"],
              ("auto-recover", "no"): ["set", "auto-recover", "no"],
              ("keep",): ["start", "keep"], ("try-again",): ["start", "try-again"]}
        for argv, expected in ok.items():
            self.assertEqual(helper.command(list(argv)), expected, argv)
        for argv in ([], ["settle"], ["restore", "../../etc"], ["restore", "2026-10-10_12-00-00", "x"],
                     ["delete", "my-own"], ["enabled", "maybe"], ["create", "--all"],
                     ["create", "a\nb"], ["create", "x" * 101], ["list"]):
            self.assertIsNone(helper.command(argv), argv)

    def test_runs_the_program_as_root(self):
        with mock.patch.object(helper.os, "geteuid", lambda: 0), \
                mock.patch.object(helper.os, "execv") as execv:
            helper.main(["restore", "2026-10-10_12-00-00"])
        execv.assert_called_once_with(helper.PROGRAM, [helper.PROGRAM, "restore", "2026-10-10_12-00-00"])

    def test_refuses_without_root(self):
        with mock.patch.object(helper.os, "geteuid", lambda: 1000), \
                mock.patch.object(helper.os, "execv") as execv, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(helper.main(["create"]), 1)
        execv.assert_not_called()


class Pkexec(Tree):
    def test_a_user_goes_through_pkexec(self):
        with mock.patch.object(rp.os, "geteuid", lambda: 1000), \
                mock.patch.object(rp.os.path, "exists", lambda p: p == rp.HELPER or os.access(p, os.F_OK)), \
                mock.patch.object(rp.shutil, "which", lambda name: "/usr/bin/pkexec"), \
                mock.patch.object(rp.os, "execvp") as execvp:
            rp.main(["restore", "2026-10-10_12-00-00"])
            execvp.assert_called_once_with("pkexec", ["pkexec", rp.HELPER, "restore", "2026-10-10_12-00-00"])
            execvp.reset_mock()
            rp.main(["set", "enabled", "no"])
            execvp.assert_called_once_with("pkexec", ["pkexec", rp.HELPER, "enabled", "no"])



class BootMenu(Tree):
    def point(self, name, kernels=("6.12.111+deb13-amd64",), reason="apt install sl"):
        boot = os.path.join(self.snapshots, name, "boot")
        os.makedirs(boot)
        for k in kernels:
            for f in (f"vmlinuz-{k}", f"initrd.img-{k}"):
                open(os.path.join(boot, f), "w").close()
        with open(os.path.join(self.snapshots, name + ".json"), "w") as f:
            json.dump({"reason": reason, "created": 0}, f)

    def test_one_entry_per_restore_point_newest_first(self):
        self.point("2026-10-10_10-00-00")
        self.point("2026-10-10_11-00-00", kernels=("6.12.100+deb13-amd64", "6.12.111+deb13-amd64"),
                   reason="apt install cowsay")
        entries = rp.menu_entries("insmod btrfs\nsearch --fs-uuid --set=root X\n", " quiet splash", "X")
        self.assertEqual(len(entries), 2)
        self.assertIn("--id rp-2026-10-10_11-00-00", entries[0])
        self.assertIn("'Before installing cowsay, ", entries[0])
        self.assertIn("linux /@snapshots/2026-10-10_11-00-00/boot/vmlinuz-6.12.111+deb13-amd64 root=UUID=X ro "
                      "rootflags=subvol=@snapshots/2026-10-10_11-00-00 quiet splash", entries[0])
        self.assertIn("initrd /@snapshots/2026-10-10_11-00-00/boot/initrd.img-6.12.111+deb13-amd64", entries[0])
        self.assertIn("\tsearch --fs-uuid --set=root X\n", entries[0])

    def test_a_restore_point_without_a_kernel_has_no_entry(self):
        os.makedirs(os.path.join(self.snapshots, "2026-10-10_10-00-00", "boot"))
        with open(os.path.join(self.snapshots, "2026-10-10_10-00-00.json"), "w") as f:
            json.dump({}, f)
        self.assertEqual(rp.menu_entries("", "", "X"), [])

    def test_quotes_survive_grub(self):
        self.assertEqual(rp.grub_quote("Ann's point"), "'Ann'\\''s point'")

    def test_write_grub_writes_and_commits(self):
        self.point("2026-10-10_10-00-00")
        target = os.path.join(self.tmp.name, "flickos-recovery.cfg")

        def fake_run(argv, **kw):
            out = {"--target=device": "/dev/vda2\n", "--target=fs_uuid": "X\n"}.get(argv[1] if len(argv) > 1 else "")
            if out is None:     # the grub-mkconfig_lib script
                out = "insmod btrfs\n@@CMDLINE  quiet splash\n"
            return subprocess.CompletedProcess(argv, 0, out, "")
        with mock.patch.object(rp.subprocess, "run", fake_run):
            rp.write_grub(target)
        with open(target) as f:
            text = f.read()
        self.assertTrue(text.startswith("# Written by flickos-recovery"))
        self.assertIn("rootflags=subvol=@snapshots/2026-10-10_10-00-00 quiet splash", text)
        self.assertIn(("filesystem", "sync", self.tmp.name), self.btrfs_calls)


class StartedFromARestorePoint(Tree):
    """The initramfs put a memory layer over restore point NAME."""

    def setUp(self):
        super().setUp()
        rp.create("apt install sl")
        self.name = self.names()[0]
        lower = rp.LOWER
        self.mounts(BTRFS_LAYOUT.replace("/@ / ", f"/@snapshots/{self.name} {lower} ")
                    + "40 1 0:50 / / rw - overlay overlay rw\n")
        with open(rp.BOOTED_FILE, "w") as f:
            f.write(self.name + "\n")

    def test_the_layout_counts(self):
        self.assertIsNone(rp.layout_problem())
        self.assertEqual(rp.state()["booted"], self.name)

    def test_no_restore_point_while_nothing_is_kept(self):
        with self.assertRaises(rp.Refused) as why:
            rp.create("apt install cowsay")
        self.assertIn("nothing changed now is kept", str(why.exception))

    def test_keep_puts_it_back_from_the_device_under_the_layer(self):
        self.assertEqual(rp.mount_source(rp.LOWER), "/dev/vda2")


class GrubStub(unittest.TestCase):
    """/etc/grub.d/42_flickos-recovery: the submenu on the btrfs layout only."""

    def run_stub(self, findmnt_output):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "findmnt"), "w") as f:
                f.write(f"#!/bin/sh\nprintf '%s\\n' '{findmnt_output}'\n")
            os.chmod(os.path.join(tmp, "findmnt"), 0o755)
            env = {**os.environ, "PATH": tmp + ":" + os.environ["PATH"]}
            return subprocess.run(["sh", os.path.join(PACKAGE, "etc/grub.d/42_flickos-recovery")],
                                  capture_output=True, text=True, env=env, check=True).stdout

    def test_btrfs_layout(self):
        out = self.run_stub("btrfs  /@snapshots")
        self.assertIn("submenu 'Restore points'", out)
        self.assertIn('source "${prefix}/flickos-recovery.cfg"', out)

    def test_nothing_elsewhere(self):
        self.assertEqual(self.run_stub(""), "")
        self.assertEqual(self.run_stub("btrfs /snapshots"), "")



class Counter(Tree):
    """The start counter (ADR-005) and what GRUB reads."""

    def setUp(self):
        super().setUp()
        with open(rp.GRUB_ACCESS, "w") as f:
            json.dump({"access": "insmod btrfs\n", "cmdline": " quiet", "uuid": "X"}, f)

    def boot(self, boot_id):
        with open(os.path.join(self.proc, "sys/kernel/random/boot_id"), "w") as f:
            f.write(boot_id + "\n")

    def good_point(self, reason="apt install sl"):
        """A restore point taken by the hook in a start that had worked."""
        state = rp.load_state()
        state["good_boot"] = rp.boot_id()
        rp.save_state(state)
        name = rp.create(reason, session="1:1")
        os.makedirs(os.path.join(self.snapshots, name, "boot"))
        for f in ("vmlinuz-6.12", "initrd.img-6.12"):
            open(os.path.join(self.snapshots, name, "boot", f), "w").close()
        return name

    def cfg(self):
        with open(rp.STATE_CFG) as f:
            return f.read()

    def started(self, boot_id, booted=None):
        self.boot(boot_id)
        if booted:
            with open(rp.BOOTED_FILE, "w") as f:
                f.write(booted + "\n")
        elif os.path.exists(rp.BOOTED_FILE):
            os.remove(rp.BOOTED_FILE)
        rp.start_begin()
        return rp.load_state()

    def test_counts_each_start_once(self):
        self.assertEqual(self.started("b2")["failed"], 1)
        rp.start_begin()                            # the same start again: no
        self.assertEqual(rp.load_state()["failed"], 1)
        self.assertEqual(self.started("b3")["failed"], 2)
        self.assertIn("set flickos_start_failed=2", self.cfg())
        self.assertIn(("filesystem", "sync", self.snapshots), self.btrfs_calls)

    def test_the_login_screen_up_a_few_seconds_resets_it(self):
        self.started("b2")
        clock = iter(range(0, 100))
        with mock.patch.object(rp, "running", lambda names: True), \
                mock.patch.object(rp.time, "monotonic", lambda: next(clock)):
            rp.start_good_watch(sleep=lambda s: None)
        state = rp.load_state()
        self.assertEqual((state["failed"], state["good_boot"]), (0, "b2"))

    def test_only_good_restore_points_are_candidates(self):
        good = self.good_point()
        self.started("b2")                          # this start hasn't worked yet...
        bad = rp.create("automatic updates", session="2:2")       # ...so this one is good: no
        self.assertFalse(dict(rp.restore_points())[bad]["good"])
        rp.create("by hand")                        # no session: made by hand
        self.assertEqual(rp.newest_good(), good)

    def test_the_recovery_entry_only_after_failed_starts(self):
        good = self.good_point()
        self.started("b2")
        self.assertNotIn("menuentry", self.cfg())
        self.started("b3")
        cfg = self.cfg()
        self.assertIn(f"set flickos_start_rp={good}", cfg)
        self.assertIn("--id flickos-recover", cfg)
        self.assertIn(f"rootflags=subvol=@snapshots/{good}", cfg)
        self.assertIn("set flickos_start_auto=yes", cfg)

    def test_recovering_never_twice_and_back_to_normal(self):
        good = self.good_point()
        self.started("b2")
        self.started("b3")                          # 2 failed: GRUB starts the restore point
        state = self.started("b4", booted=good)
        self.assertEqual((state["mode"], state["failed"]), ("recovering", 1))
        state = self.started("b5", booted=good)     # that start failed too
        self.assertEqual((state["mode"], state["failed"]), ("recovering", 2))
        self.assertIn("set flickos_start_mode=recovering", self.cfg())    # GRUB waits now
        state = self.started("b6")                  # the user chose the normal entry
        self.assertEqual((state["mode"], state["failed"]), ("normal", 1))

    def test_try_again_and_keep(self):
        good = self.good_point()
        self.started("b2")
        self.started("b3")
        self.started("b4", booted=good)
        with mock.patch.object(rp.os, "geteuid", lambda: 0), contextlib.redirect_stdout(io.StringIO()):
            rp.start_command("try-again")
            state = rp.load_state()
            self.assertEqual((state["mode"], state["failed"]), ("normal", 0))
            with mock.patch.object(rp, "restore", return_value="before") as restore:
                rp.start_command("keep")
        restore.assert_called_once_with(good)

    def test_auto_recover_off_reaches_grub(self):
        rp.set_setting("auto-recover", "no")
        self.assertIn("set flickos_start_auto=no", self.cfg())



class Notify(Tree):
    def test_after_failed_starts_says_why(self):
        title, body = rp.notify_text("2026-10-10_05-29-25", {"reason": "apt install sl", "created": 0},
                                     {"mode": "recovering", "rp": "2026-10-10_05-29-25"})
        self.assertEqual(title, "FlickOS started from a restore point")
        self.assertIn("because the last starts failed", body)
        self.assertIn("\u201cBefore installing sl, ", body)
        self.assertIn("Click to choose", body)

    def test_started_by_hand(self):
        title, body = rp.notify_text("x", {"reason": "Made in Settings & more", "created": 0},
                                     {"mode": "normal", "rp": "y"})
        self.assertEqual(title, "Running from a restore point")
        self.assertIn("Made in Settings &amp; more", body)      # mako reads bodies as markup
        self.assertNotIn("Click to choose", body)

    def test_nothing_unless_started_from_one(self):
        with mock.patch.object(rp.subprocess, "run") as run:
            self.assertEqual(rp.notify(), 0)
        run.assert_not_called()

    def test_waits_for_flickos_mako_then_opens_settings_on_a_click(self):
        rp.create("apt install sl")
        name = self.names()[0]
        with open(rp.BOOTED_FILE, "w") as f:
            f.write(name)
        ready = iter([False, False, True])
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv[0])
            return subprocess.CompletedProcess(argv, 0, "default\n", "")
        with mock.patch.object(rp, "notifications_ready", lambda: next(ready)), \
                mock.patch.object(rp.shutil, "which", lambda n: "/usr/bin/" + n), \
                mock.patch.object(rp.subprocess, "run", fake_run), \
                mock.patch.object(rp.subprocess, "Popen") as popen:
            rp.notify(sleep=lambda s: None)
        self.assertEqual(calls, ["notify-send"])
        self.assertEqual(popen.call_args.args[0], ["flickos-control", "--page", "recovery"])


if __name__ == "__main__":
    unittest.main()
