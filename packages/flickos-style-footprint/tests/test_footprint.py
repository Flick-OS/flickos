"""Tests for the Footprint style package: its metainfo makes it a style with a
layout in Software, its files are complete, its dock is on the left in the
bottom layer, and (when the other packages are next to this one, as in the
source tree) flickos-layout's `check` passes the style and the layout, the
dock generates with both placeholders filled, and its window theme has the
keys FlickOS's own have.
Run: python3 -m unittest discover -s tests
"""

import configparser
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARE = os.path.join(PACKAGE, "usr/share")
STYLE = os.path.join(SHARE, "flickos/styles/footprint")
LAYOUT = os.path.join(SHARE, "flickos/layouts/footprint")
THEME = os.path.join(SHARE, "themes/Footprint/labwc")
METAINFO = os.path.join(SHARE, "metainfo/io.github.dvbondoy.flickos.styles.Footprint.metainfo.xml")
LAYOUTS = os.path.join(PACKAGE, "../flickos-layouts")
ARC_THEMERC = os.path.join(PACKAGE, "../flickos-settings/usr/share/themes/FlickOS-Arc/labwc/themerc")
# Every button labwc 0.8 draws, in every state it looks for.
BUTTONS = ("close", "iconify", "max", "max_toggled", "shade", "shade_toggled", "desk", "desk_toggled")
STATES = ("-active", "-inactive", "_hover-active", "_hover-inactive")


def themerc_keys(path):
    with open(path, encoding="utf-8") as f:
        return {line.split(":", 1)[0].strip() for line in f if line.strip() and not line.startswith("#")}


def ini(path, section):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return parser[section]


def text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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
        self.assertEqual((values["FlickOS::style"], values["FlickOS::layout"]), ("footprint", "footprint"))
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/styles")), ["footprint"])
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/layouts")), ["footprint"])

    def test_no_other_systems_name(self):
        """ADR-013 and ADR-016: named by allusion; no other desktop's name
        anywhere. Debian package names (gnome-themes-extra-data) are allowed."""
        marks = re.compile(r"(?<![\w-])(gnome|ubuntu)(?![\w-])", re.IGNORECASE)
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
        self.control = text(os.path.join(PACKAGE, "debian/control"))

    def test_style_files_exist(self):
        for key in ("Waybar", "Foot", "Fuzzel", "Mako", "Wallpaper"):
            self.assertTrue(os.path.isfile(os.path.join(STYLE, self.style[key])), key)
        self.assertEqual(self.style["LabwcTheme"], "Footprint")

    def test_themes_and_font_come_from_the_depends(self):
        self.assertEqual((self.style["GtkTheme"], self.style["IconTheme"]), ("Adwaita-dark", "Adwaita"))
        for package in ("gnome-themes-extra-data", "adwaita-icon-theme", "adwaita-icon-theme-legacy",
                        "fonts-cantarell"):
            self.assertIn(package, self.control)
        for css in ("style.css", "dock.css"):
            self.assertIn("Cantarell", text(os.path.join(LAYOUT, css)), css)

    def test_depends_on_the_dock_launcher(self):
        """flickos-layouts 1.61 fills in Exec("flickos/launcher"), and 1.62's
        check takes it as the apps button."""
        self.assertIn("flickos-layouts (>= 1.62)", self.control)

    def test_window_theme_has_every_button(self):
        names = set(os.listdir(THEME))
        for button in BUTTONS:
            for state in STATES:
                self.assertIn(f"{button}{state}.svg", names)
        self.assertEqual(len(names), len(BUTTONS) * len(STATES) + 1)

    @unittest.skipUnless(os.path.isfile(ARC_THEMERC), "flickos-settings is not next to this package")
    def test_themerc_has_flickos_keys(self):
        """tools/check-palette.py wants the same keys in every FlickOS window theme."""
        self.assertEqual(themerc_keys(os.path.join(THEME, "themerc")), themerc_keys(ARC_THEMERC))

    def test_centered_titles(self):
        self.assertIn("window.label.text.justify: center", text(os.path.join(THEME, "themerc")))

    def test_layout_files(self):
        for key in ("Waybar", "Style", "Preview", "Dock", "DockStyle"):
            self.assertTrue(os.path.isfile(os.path.join(LAYOUT, self.layout[key])), key)
        waybar = text(os.path.join(LAYOUT, self.layout["Waybar"]))
        # Installed next to flickos-layouts' layouts: FlickOS's shared modules.
        self.assertIn('"include": "../common/modules.jsonc"', waybar)
        self.assertIn('"flickos/desktops"', waybar)
        self.assertEqual(self.layout["Desktops"], "4")
        self.assertEqual((self.layout["Menu"], self.layout["MenuStyle"]), ("top-left", "grid"))

    def test_dock_on_the_left_below_the_top_bar(self):
        """ADR-016: the bottom layer, so the top bar keeps the whole width."""
        dock = text(os.path.join(LAYOUT, self.layout["Dock"]))
        self.assertRegex(dock, r'\n  edge = "left"\n')
        self.assertRegex(dock, r'\n  layer = "bottom"\n')
        self.assertIn('pins = "flickos/pinned"', dock)
        self.assertIn('Exec("flickos/launcher")', dock)
        self.assertNotRegex(dock, r"(?m)^#CSS")

    def test_installed(self):
        installed = text(os.path.join(PACKAGE, "debian/install"))
        for folder in ("flickos/styles/footprint", "flickos/layouts/footprint", "themes/Footprint/labwc",
                       "metainfo"):
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

    def env(self, home):
        return {"HOME": home, "PATH": "/usr/bin:/bin", "XDG_DATA_DIRS": f"{self.share}:/usr/share",
                "FLICKOS_LAYOUT_PREFIX": os.path.abspath(LAYOUTS)}

    def run_layout(self, *args):
        with tempfile.TemporaryDirectory() as home:
            return subprocess.run([sys.executable, os.path.join(LAYOUTS, "usr/bin/flickos-layout"), *args],
                                  capture_output=True, text=True, env=self.env(home), check=False)

    def test_style_check_passes(self):
        done = self.run_layout("check", "footprint")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_layout_check_passes(self):
        done = self.run_layout("check", "--layout", "footprint")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_listed_after_flickos_own(self):
        styles = [line.split("\t")[0] for line in self.run_layout("style", "list").stdout.splitlines()]
        layouts = [line.split("\t")[0] for line in self.run_layout("list").stdout.splitlines()]
        self.assertGreater(styles.index("footprint"), max(styles.index("dark"), styles.index("light")))
        self.assertGreater(layouts.index("footprint"), layouts.index("traditional"))

    def test_dock_generates(self):
        """The tree's flickos-layout fills in both placeholders."""
        path = os.path.join(LAYOUTS, "usr/bin/flickos-layout")
        loader = importlib.machinery.SourceFileLoader("flickos_layout_for_footprint", path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        fl = importlib.util.module_from_spec(spec)
        loader.exec_module(fl)
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, self.env(home), clear=True):
            style = fl.styles()["footprint"]
            layout = fl.layouts()["footprint"]
            fl.update_dock(home, layout, style, menu=True)
            config = text(os.path.join(home, "dock/sfwbar.config"))
        self.assertIsNone(fl.DOCK_PINS.search(config))
        self.assertIsNone(fl.DOCK_LAUNCHER_EXEC.search(config))
        self.assertIn("flickos-menu toggle", config)
        self.assertLess(config.index("@define-color wm_bg #000000"), config.index("grid#taskbar_popup_grid"))


if __name__ == "__main__":
    unittest.main()
