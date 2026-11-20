"""Tests for the Seven style package: its metainfo makes it a style with a
layout in Software, its files are complete, its layout is one bottom panel
in named colors only, and (when the other packages are next to this one, as
in the source tree) flickos-layout's `check` passes the style and the
layout, and its window theme has the keys FlickOS's own have.
Run: python3 -m unittest discover -s tests
"""

import configparser
import os
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARE = os.path.join(PACKAGE, "usr/share")
STYLE = os.path.join(SHARE, "flickos/styles/seven")
THEME = os.path.join(SHARE, "themes/Seven/labwc")
LAYOUT = os.path.join(SHARE, "flickos/layouts/seven")
METAINFO = os.path.join(SHARE, "metainfo/io.github.dvbondoy.flickos.styles.Seven.metainfo.xml")
LAYOUTS = os.path.join(PACKAGE, "../flickos-layouts")
ARC_THEMERC = os.path.join(PACKAGE, "../flickos-settings/usr/share/themes/FlickOS-Arc/labwc/themerc")
BUTTONS = ("close", "iconify", "max", "max_toggled", "shade", "shade_toggled", "desk", "desk_toggled")


def text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def themerc_keys(path):
    with open(path, encoding="utf-8") as f:
        return {line.split(":", 1)[0].strip() for line in f if line.strip() and not line.startswith("#")}


class MetainfoTest(unittest.TestCase):
    """What Software reads: an add-on of the layout chooser naming its style."""

    def setUp(self):
        self.root = ET.parse(METAINFO).getroot()

    def test_screenshots(self):
        """Software's two screenshots, at the apt repository's address, and (in
        the source tree) the files repo/upload.sh publishes there, as
        tools/make-style-shots.sh takes them."""
        shots = self.root.findall("screenshots/screenshot")
        self.assertEqual([shot.findtext("image") for shot in shots],
                         [f"https://dvbondoy.github.io/flickos-apt/screenshots/seven/{n}.png" for n in (1, 2)])
        self.assertTrue(all(shot.findtext("caption") for shot in shots))
        folder = os.path.join(PACKAGE, "../../repo/screenshots")
        if not os.path.isdir(folder):
            self.skipTest("not in the source tree")
        for n in (1, 2):
            with open(os.path.join(folder, "seven", f"{n}.png"), "rb") as f:
                head = f.read(24)
            self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", head[16:24]), (1366, 768))

    def test_addon_of_the_layout_chooser(self):
        self.assertEqual(self.root.get("type"), "addon")
        self.assertEqual(self.root.findtext("extends"), "flickos-layout.desktop")
        self.assertEqual(self.root.findtext("id") + ".metainfo.xml", os.path.basename(METAINFO))

    def test_names_the_style_and_the_layout(self):
        """ADR-014: Software's Use sets both."""
        values = {v.get("key"): v.text for v in self.root.findall("custom/value")}
        self.assertEqual(values, {"FlickOS::style": "seven", "FlickOS::layout": "seven"})
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/styles")), ["seven"])
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/layouts")), ["seven"])

    def test_no_other_systems_name(self):
        """ADR-013: named by allusion; no other system's trademarks anywhere
        (lowercase "windows" is the ordinary word)."""
        marks = re.compile(r"\b(Windows|Microsoft|Aero|Vista|Luna)\b")
        for folder, _dirs, files in os.walk(PACKAGE):
            for name in files:
                if name.endswith((".png", ".pyc")) or name == os.path.basename(__file__):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                    self.assertIsNone(marks.search(f.read()), os.path.join(folder, name))


class FilesTest(unittest.TestCase):

    def setUp(self):
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(STYLE, "style.ini"), encoding="utf-8")
        self.style = ini["Style"]

    def test_style_files_exist(self):
        for key in ("Waybar", "Foot", "Fuzzel", "Mako", "Wallpaper"):
            self.assertTrue(os.path.isfile(os.path.join(STYLE, self.style[key])), key)
        self.assertEqual(self.style["LabwcTheme"], "Seven")

    def test_themes_come_from_the_depends(self):
        with open(os.path.join(PACKAGE, "debian/control"), encoding="utf-8") as f:
            control = f.read()
        self.assertEqual((self.style["GtkTheme"], self.style["IconTheme"]), ("Arc", "Numix"))
        self.assertIn("arc-theme", control)
        self.assertIn("numix-icon-theme", control)

    def test_every_button_in_every_state(self):
        for name in BUTTONS:
            for state in ("-active", "-inactive", "_hover-active", "_hover-inactive"):
                path = os.path.join(THEME, f"{name}{state}.svg")
                self.assertEqual(ET.parse(path).getroot().tag, "{http://www.w3.org/2000/svg}svg", path)

    @unittest.skipUnless(os.path.isfile(ARC_THEMERC), "flickos-settings is not next to this package")
    def test_themerc_has_flickos_keys(self):
        """tools/check-palette.py wants the same keys in every FlickOS window theme."""
        self.assertEqual(themerc_keys(os.path.join(THEME, "themerc")), themerc_keys(ARC_THEMERC))


class LayoutTest(unittest.TestCase):
    """Redmond's arrangement in Seven's look."""

    def setUp(self):
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(LAYOUT, "layout.ini"), encoding="utf-8")
        self.layout = ini["Layout"]

    def test_layout_files(self):
        """One bottom bar, labwc's own button order, no dock."""
        for key in ("Waybar", "Style", "Preview"):
            self.assertTrue(os.path.isfile(os.path.join(LAYOUT, self.layout[key])), key)
        for key in ("TitlebarLayout", "Dock", "DockStyle", "Desktops", "Wallpaper"):
            self.assertNotIn(key, self.layout)
        self.assertEqual((self.layout["Menu"], self.layout["MenuStyle"], self.layout["Quick"]),
                         ("bottom-left", "classic", "bottom-right"))
        waybar = text(os.path.join(LAYOUT, self.layout["Waybar"]))
        self.assertIn('"include": "../common/modules.jsonc"', waybar)
        self.assertIn('"position": "bottom"', waybar)
        # The 12-hour clock (flickos-layout clock set 12h) rewrites %H:%M.
        self.assertIn('"clock": { "format": "{:%H:%M\\n%d/%m/%Y}", "justify": "center" }', waybar)

    def test_window_list_is_icons_only(self):
        """waybar 0.12 doesn't shorten titles: a window list with them pushes
        the status and clock off the bar (docs/07-troubleshooting.md)."""
        waybar = text(os.path.join(LAYOUT, self.layout["Waybar"]))
        self.assertNotIn("{title}", re.sub(r'"tooltip-format": "[^"]*"', "", waybar))
        self.assertNotIn("flickos/pinned", re.sub(r"//.*", "", waybar))

    def test_css_named_colors_only(self):
        """The layout follows any style: no written-out color in its CSS."""
        css = re.sub(r"/\*.*?\*/", "", text(os.path.join(LAYOUT, self.layout["Style"])), flags=re.S)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", css))
        self.assertIn('@import url("../common/base.css");', css)

    def test_bar_never_lighter_than_check_tests_it(self):
        """check tests wm_bg at base.css's alpha (PANEL_ALPHA): the layout
        doesn't set the bar's own background, its glass only darkens."""
        css = text(os.path.join(LAYOUT, self.layout["Style"]))
        bar = re.search(r"window#waybar\.seven \{([^}]*)\}", css).group(1)
        self.assertNotRegex(bar, r"(?m)^\s*background(-color)?:")
        self.assertIn("alpha(@wm_bg, 0.5)", bar)

    def test_installed(self):
        installed = text(os.path.join(PACKAGE, "debian/install"))
        for folder in ("flickos/styles/seven", "flickos/layouts/seven", "themes/Seven/labwc", "metainfo"):
            self.assertIn(f"usr/share/{folder}/", installed)


@unittest.skipUnless(os.path.isdir(LAYOUTS), "flickos-layouts is not next to this package")
class CheckTest(unittest.TestCase):
    """flickos-layout's own check, with this package installed as it would be:
    its files next to flickos-layouts' common/ in one share folder, and
    stand-ins for the themes the package depends on (the build host need not
    have them)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.share = os.path.join(cls.tmp, "share")
        shutil.copytree(SHARE, cls.share)
        shutil.copytree(os.path.join(LAYOUTS, "usr/share/flickos/layouts/common"),
                        os.path.join(cls.share, "flickos/layouts/common"))
        os.makedirs(os.path.join(cls.tmp, "depends/themes/Arc/gtk-3.0"))
        icons = os.path.join(cls.tmp, "depends/icons/Numix")
        os.makedirs(icons)
        with open(os.path.join(icons, "index.theme"), "w", encoding="utf-8") as f:
            f.write("[Icon Theme]\nName=Numix\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_layout(self, *args):
        with tempfile.TemporaryDirectory() as home:
            env = {"HOME": home, "PATH": "/usr/bin:/bin", "XDG_DATA_DIRS": f"{self.share}:{self.tmp}/depends:/usr/share",
                   "FLICKOS_LAYOUT_PREFIX": os.path.abspath(LAYOUTS)}
            return subprocess.run([sys.executable, os.path.join(LAYOUTS, "usr/bin/flickos-layout"), *args],
                                  capture_output=True, text=True, env=env, check=False)

    def test_check_passes(self):
        done = self.run_layout("check", "seven")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_layout_check_passes(self):
        done = self.run_layout("check", "--layout", "seven")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_layout_listed_after_flickos_own(self):
        layouts = [line.split("\t")[0] for line in self.run_layout("list").stdout.splitlines()]
        self.assertGreater(layouts.index("seven"), layouts.index("traditional"))

    def test_listed_after_dark_and_light(self):
        """After FlickOS's own (another style package, Aye3, may come after it)."""
        listed = [line.split("\t")[0] for line in self.run_layout("style", "list").stdout.splitlines()]
        self.assertGreater(listed.index("seven"), max(listed.index("dark"), listed.index("light")))


if __name__ == "__main__":
    unittest.main()
