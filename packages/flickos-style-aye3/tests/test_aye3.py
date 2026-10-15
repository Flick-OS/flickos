"""Tests for the Aye3 style package: its metainfo makes it a style with a
layout in Software, its files are complete, and (when the other packages are
next to this one, as in the source tree) flickos-layout's `check` passes the
style and the layout, and its window theme has the keys FlickOS's own have.
Run: python3 -m unittest discover -s tests
"""

import configparser
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARE = os.path.join(PACKAGE, "usr/share")
STYLE = os.path.join(SHARE, "flickos/styles/aye3")
LAYOUT = os.path.join(SHARE, "flickos/layouts/aye3")
THEME = os.path.join(SHARE, "themes/Aye3/labwc")
METAINFO = os.path.join(SHARE, "metainfo/io.github.dvbondoy.flickos.styles.Aye3.metainfo.xml")
LAYOUTS = os.path.join(PACKAGE, "../flickos-layouts")
ARC_THEMERC = os.path.join(PACKAGE, "../flickos-settings/usr/share/themes/FlickOS-Arc/labwc/themerc")


def themerc_keys(path):
    with open(path, encoding="utf-8") as f:
        return {line.split(":", 1)[0].strip() for line in f if line.strip() and not line.startswith("#")}


def ini(path, section):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return parser[section]


class MetainfoTest(unittest.TestCase):
    """What Software reads: an add-on of the layout chooser naming its style and layout."""

    def setUp(self):
        self.root = ET.parse(METAINFO).getroot()

    def test_addon_of_the_layout_chooser(self):
        self.assertEqual(self.root.get("type"), "addon")
        self.assertEqual(self.root.findtext("extends"), "flickos-layout.desktop")
        self.assertEqual(self.root.findtext("id") + ".metainfo.xml", os.path.basename(METAINFO))

    def test_names_the_style_and_the_layout(self):
        """ADR-014: Software's Use sets both."""
        values = {v.get("key"): v.text for v in self.root.findall("custom/value")}
        self.assertEqual((values["FlickOS::style"], values["FlickOS::layout"]), ("aye3", "aye3"))
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/styles")), ["aye3"])
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/layouts")), ["aye3"])

    def test_no_other_systems_name(self):
        """ADR-013: named by allusion; no other system's name anywhere."""
        marks = re.compile(r"\bi3(wm|bar|status|-wm|-gaps)?\b", re.IGNORECASE)
        for folder, _dirs, files in os.walk(PACKAGE):
            for name in files:
                if name.endswith((".png", ".pyc")) or name == os.path.basename(__file__):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                    self.assertIsNone(marks.search(f.read()), os.path.join(folder, name))


class FilesTest(unittest.TestCase):

    def setUp(self):
        self.style = ini(os.path.join(STYLE, "style.ini"), "Style")
        self.layout = ini(os.path.join(LAYOUT, "layout.ini"), "Layout")

    def test_style_files_exist(self):
        for key in ("Waybar", "Foot", "Fuzzel", "Mako", "Wallpaper"):
            self.assertTrue(os.path.isfile(os.path.join(STYLE, self.style[key])), key)
        self.assertEqual(self.style["LabwcTheme"], "Aye3")

    def test_themes_come_from_the_depends(self):
        with open(os.path.join(PACKAGE, "debian/control"), encoding="utf-8") as f:
            control = f.read()
        self.assertEqual((self.style["GtkTheme"], self.style["IconTheme"]), ("Arc-Dark", "Numix"))
        self.assertIn("arc-theme", control)
        self.assertIn("numix-icon-theme", control)

    def test_window_theme_draws_labwcs_buttons(self):
        """No button files: labwc's built-in ones in the themerc's colors."""
        self.assertEqual(os.listdir(THEME), ["themerc"])

    @unittest.skipUnless(os.path.isfile(ARC_THEMERC), "flickos-settings is not next to this package")
    def test_themerc_has_flickos_keys(self):
        """tools/check-palette.py wants the same keys in every FlickOS window theme."""
        self.assertEqual(themerc_keys(os.path.join(THEME, "themerc")), themerc_keys(ARC_THEMERC))

    def test_layout_files(self):
        for key in ("Waybar", "Style", "Preview"):
            self.assertTrue(os.path.isfile(os.path.join(LAYOUT, self.layout[key])), key)
        self.assertNotIn("Dock", self.layout)
        with open(os.path.join(LAYOUT, self.layout["Waybar"]), encoding="utf-8") as f:
            waybar = f.read()
        # Installed next to flickos-layouts' layouts: FlickOS's shared modules.
        self.assertIn('"include": "../common/modules.jsonc"', waybar)
        self.assertIn('"flickos/desktops"', waybar)
        self.assertEqual(self.layout["Desktops"], "4")

    def test_installed(self):
        with open(os.path.join(PACKAGE, "debian/install"), encoding="utf-8") as f:
            installed = f.read()
        for folder in ("flickos/styles/aye3", "flickos/layouts/aye3", "themes/Aye3/labwc", "metainfo"):
            self.assertIn(f"usr/share/{folder}/", installed)


@unittest.skipUnless(os.path.isdir(LAYOUTS), "flickos-layouts is not next to this package")
class CheckTest(unittest.TestCase):
    """flickos-layout's own check, with this package installed as it would be:
    its files next to flickos-layouts' common/ in one share folder."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.share = os.path.join(cls.tmp, "share")
        shutil.copytree(SHARE, cls.share)
        shutil.copytree(os.path.join(LAYOUTS, "usr/share/flickos/layouts/common"),
                        os.path.join(cls.share, "flickos/layouts/common"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_layout(self, *args):
        with tempfile.TemporaryDirectory() as home:
            env = {"HOME": home, "PATH": "/usr/bin:/bin", "XDG_DATA_DIRS": f"{self.share}:/usr/share",
                   "FLICKOS_LAYOUT_PREFIX": os.path.abspath(LAYOUTS)}
            return subprocess.run([sys.executable, os.path.join(LAYOUTS, "usr/bin/flickos-layout"), *args],
                                  capture_output=True, text=True, env=env, check=False)

    def test_style_check_passes(self):
        done = self.run_layout("check", "aye3")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_layout_check_passes(self):
        done = self.run_layout("check", "--layout", "aye3")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_listed_after_flickos_own(self):
        styles = [line.split("\t")[0] for line in self.run_layout("style", "list").stdout.splitlines()]
        layouts = [line.split("\t")[0] for line in self.run_layout("list").stdout.splitlines()]
        self.assertGreater(styles.index("aye3"), max(styles.index("dark"), styles.index("light")))
        self.assertGreater(layouts.index("aye3"), layouts.index("traditional"))


if __name__ == "__main__":
    unittest.main()
