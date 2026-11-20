"""Tests for a kit package (docs/design/flickos-dev.md, ADR-001 and ADR-002),
the same file in every flickos-kit-* package: it learns which kit it is from
its folder. Checks what Software reads (the metainfo), that the kit depends only
on the base kit and on Debian packages, and that none of its members starts
something by itself (INT-9). A kit whose copy is older takes this one at its
next version. Run: python3 -m unittest discover -s tests
"""

import os
import re
import unittest
import xml.etree.ElementTree as ET

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = os.path.basename(PACKAGE) if os.path.basename(PACKAGE).startswith("flickos-kit-") else None
KIT = NAME[len("flickos-kit-"):] if NAME else None
SHARE = os.path.join(PACKAGE, "usr/share")
METAINFO = os.path.join(SHARE, "metainfo", f"io.github.dvbondoy.flickos.kits.{KIT}.metainfo.xml")
# The kits that aren't developer kits (flickos-dev.md, Q15; Study, Q16; the
# security kits, flickos-security.md, ADR-S01): they show under another
# category, and don't need the developer basics.
SECURITY = ("network", "web-testing", "passwords", "forensics", "reversing", "wireless")
CATEGORY = {"classroom": "classroom", "study": "classroom",
            **dict.fromkeys(SECURITY, "security")}.get(KIT, "development")
# What a security kit's package description says (ADR-S05); Software shows the
# same words on its page.
PERMISSION = "Use these tools only on computers and networks you own or have permission to test."

# Debian packages that start or schedule something when they are installed
# (phase 0 item 8, 2026-11-15, found by installing every member in a trixie
# container with systemd). A kit leaves them out, or ships the drop-ins that
# keep the unit off (netavark: flickos-kit-containers). Add to it when a new
# member does.
STARTS = {
    "man-db": "man-db.timer and cron jobs",
    "docker.io": "a daemon that runs all the time",
    "docker-ce": "a daemon that runs all the time",
    "tor": "its service",
    "clamav-freshclam": "its update service",
    "chkrootkit": "a timer",
    "lynis": "a timer",
    "rkhunter": "cron jobs",
    # flickos-security.md, phase 0 S3 and section 4
    "smartmontools": "smartd",
    "guymager": "smartd, through smartmontools",
    "suricata": "its service",
    "auditd": "its service",
}
# The kit with the units kept off by a drop-in, and the units.
GUARDED = {"podman": ("netavark-dhcp-proxy.socket", "netavark-dhcp-proxy.service", "netavark-firewalld-reload.service")}
FLAG = "/etc/flickos/kits/netavark-on"


def depends():
    """The names in the first Depends of debian/control, without versions."""
    text = open(os.path.join(PACKAGE, "debian/control"), encoding="utf-8").read()
    text = re.sub(r"(?m)^#.*\n", "", text)
    field = re.search(r"(?ms)^Depends:(.*?)(?=^\S|\Z)", text).group(1)
    return [re.sub(r"\(.*?\)", "", item).strip() for item in field.split(",") if item.strip()]


class KitTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(KIT, "run from a flickos-kit-* package")
        self.root = ET.parse(METAINFO).getroot()

    def test_metainfo_is_a_kit(self):
        """An add-on of the Tool Kits window that Software shows under Developer Tools."""
        self.assertEqual(self.root.get("type"), "addon")
        self.assertEqual(self.root.findtext("id"), f"io.github.dvbondoy.flickos.kits.{KIT}")
        self.assertEqual(self.root.findtext("extends"), "flickos-kits.desktop")
        custom = {v.get("key"): v.text for v in self.root.findall("custom/value")}
        self.assertEqual(custom, {"FlickOS::kit": KIT, "FlickOS::kit-category": CATEGORY})
        for tag in ("name", "summary", "description", "icon", "project_license", "metadata_license"):
            self.assertTrue(self.root.find(tag) is not None, tag)
        self.assertEqual(self.root.findtext("project_license"), "GPL-3.0-or-later")

    def test_metainfo_text(self):
        """Names in Title Case, summaries short and without a final period (HIG TXT)."""
        summary = self.root.findtext("summary")
        self.assertLessEqual(len(summary), 60)
        self.assertFalse(summary.endswith("."))
        self.assertTrue(self.root.findtext("name")[0].isupper())

    def test_depends(self):
        """The base kit (for a developer kit but itself) and Debian's packages only: no FlickOS program, no ${} but misc."""
        names = depends()
        self.assertIn("${misc:Depends}", names)
        names.remove("${misc:Depends}")
        if KIT != "base" and CATEGORY == "development":
            self.assertIn("flickos-kit-base", names)
        for name in names:
            if name.startswith("flickos-"):
                self.assertEqual(name, "flickos-kit-base", f"{NAME} depends on {name}")
                self.assertEqual(CATEGORY, "development", f"{NAME} depends on {name}")
            else:
                self.assertRegex(name, r"^[a-z0-9][a-z0-9.+-]*$")

    def test_security_kit(self):
        """A security kit is named for its kind of work and says the permission sentence (ADR-S01, ADR-S05)."""
        if CATEGORY != "security":
            self.skipTest("not a security kit")
        self.assertNotRegex(KIT, r"security|pentest|hack")
        text = open(os.path.join(PACKAGE, "debian/control"), encoding="utf-8").read()
        description = re.search(r"(?ms)^Description: (.*)", text).group(1)
        self.assertIn(PERMISSION, " ".join(description.split()))
        self.assertTrue(description.startswith("FlickOS security kit: "))
        self.assertEqual(self.root.findtext("icon"), "security-high")

    def test_members_start_nothing(self):
        """No member is on the list of packages that start or schedule something."""
        for name in depends():
            self.assertNotIn(name, STARTS, f"{name} starts {STARTS.get(name)}: leave it out (ADR-001)")

    def test_guarded_units(self):
        """podman's netavark units stay off until the Tool Kits window creates the flag file."""
        names = depends()
        for member, units in GUARDED.items():
            dropins = {
                unit: os.path.join(PACKAGE, "usr/lib/systemd/system", unit + ".d/flickos-kit.conf") for unit in units
            }
            if member not in names:
                for path in dropins.values():
                    self.assertFalse(os.path.exists(path), f"{path} without {member}")
                continue
            for unit, path in dropins.items():
                with open(path, encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
                self.assertEqual(lines, ["[Unit]", f"ConditionPathExists={FLAG}"], unit)


if __name__ == "__main__":
    unittest.main()
