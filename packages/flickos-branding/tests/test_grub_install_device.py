"""Tests for usr/libexec/flickos/grub-install-device (finding J). Run:
python3 -m unittest discover -s tests

Every outside command is a stand-in on PATH, and /sys and /dev/disk/by-id
are temporary folders: nothing reads or changes the build host's debconf."""

import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "usr/libexec/flickos/grub-install-device")


class GrubInstallDevice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.bin, self.sys, self.by_id = (os.path.join(root, d) for d in ("bin", "sys", "by-id"))
        for folder in (self.bin, self.sys, self.by_id):
            os.mkdir(folder)
        self.set_log = os.path.join(root, "set-selections")
        self.stand_ins(status="install ok installed", answer="", mount="/dev/vda1[/@]",
                       ancestors="/dev/vda1 part\n/dev/vda disk\n")

    def stand_ins(self, status, answer, mount, ancestors):
        """dpkg-query, debconf-show, findmnt, lsblk answering as given;
        debconf-set-selections logs what it is told."""
        shown = f"* grub-pc/install_devices: {answer}" if answer else "  grub-pc/install_devices:"
        scripts = {
            "dpkg-query": f"echo -n '{status}'" if status else "exit 1",
            "debconf-show": f"printf '%s\\n' '  grub-pc/install_devices_empty: false' '{shown}'",
            "findmnt": f"[ \"$3\" = / ] && echo '{mount}' || exit 1",
            "lsblk": f"printf '{ancestors}'",
            "debconf-set-selections": f"cat >> {self.set_log}",
        }
        for name, body in scripts.items():
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(f"#!/bin/sh\n{body}\n")
            os.chmod(path, 0o755)

    def run_script(self):
        result = subprocess.run(["sh", SCRIPT], capture_output=True, text=True,
                                env={"PATH": f"{self.bin}:/usr/bin:/bin", "GRUB_DEVICE_SYS": self.sys,
                                     "GRUB_DEVICE_BY_ID": self.by_id})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def told(self):
        try:
            with open(self.set_log) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def test_tells_grub_pc_the_disk_under_the_system(self):
        self.assertIn("/dev/vda", self.run_script())
        self.assertEqual(self.told(), "grub-pc grub-pc/install_devices multiselect /dev/vda\n")

    def test_a_half_configured_grub_pc_too(self):
        # The state its failed upgrade leaves: then dpkg --configure -a finishes it.
        self.stand_ins(status="install ok half-configured", answer="", mount="/dev/vda1",
                       ancestors="/dev/vda1 part\n/dev/vda disk\n")
        self.run_script()
        self.assertEqual(self.told(), "grub-pc grub-pc/install_devices multiselect /dev/vda\n")

    def test_through_luks_to_the_disk(self):
        self.stand_ins(status="install ok installed", answer="", mount="/dev/mapper/luks-1[/@]",
                       ancestors="/dev/mapper/luks-1 crypt\n/dev/sda2 part\n/dev/sda disk\n")
        self.run_script()
        self.assertEqual(self.told(), "grub-pc grub-pc/install_devices multiselect /dev/sda\n")

    def test_a_stable_name_when_there_is_one(self):
        os.symlink("/dev/vda", os.path.join(self.by_id, "virtio-disk0"))
        os.symlink("/dev/vda1", os.path.join(self.by_id, "virtio-disk0-part1"))
        self.run_script()
        self.assertEqual(self.told(), "grub-pc grub-pc/install_devices multiselect "
                         f"{self.by_id}/virtio-disk0\n")

    def test_nothing_when_answered_on_uefi_or_without_grub_pc(self):
        self.stand_ins(status="install ok installed", answer="/dev/sdb", mount="/dev/vda1",
                       ancestors="/dev/vda1 part\n/dev/vda disk\n")
        self.run_script()
        self.stand_ins(status="deinstall ok config-files", answer="", mount="/dev/vda1",
                       ancestors="/dev/vda1 part\n/dev/vda disk\n")
        self.run_script()
        self.stand_ins(status="install ok installed", answer="", mount="/dev/vda1",
                       ancestors="/dev/vda1 part\n/dev/vda disk\n")
        os.makedirs(os.path.join(self.sys, "firmware/efi"))
        self.run_script()
        self.assertEqual(self.told(), "")


if __name__ == "__main__":
    unittest.main()
