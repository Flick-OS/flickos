"""Tests for the Eleven style package: its metainfo makes it a style with a
layout in Software, its files are complete, its layout is one bottom panel
with the apps button in the middle, in named colors only, and (when the other packages are next to this one, as
in the source tree) flickos-layout's `check` passes the style and the
layout, and its window theme has the keys FlickOS's own have.
Run: python3 -m unittest discover -s tests
"""

import configparser
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARE = os.path.join(PACKAGE, "usr/share")
STYLE = os.path.join(SHARE, "flickos/styles/eleven")
LAYOUT = os.path.join(SHARE, "flickos/layouts/eleven")
THEME = os.path.join(SHARE, "themes/Eleven/labwc")
METAINFO = os.path.join(SHARE, "metainfo/io.github.dvbondoy.flickos.styles.Eleven.metainfo.xml")
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
    """What Software reads: an add-on of the layout chooser naming its style."""

    def setUp(self):
        self.root = ET.parse(METAINFO).getroot()

    def test_screenshots(self):
        """Software's two screenshots, at the apt repository's address, and (in
        the source tree) the files repo/upload.sh publishes there, as
        tools/make-style-shots.sh takes them."""
        shots = self.root.findall("screenshots/screenshot")
        self.assertEqual([shot.findtext("image") for shot in shots],
                         [f"https://dvbondoy.github.io/flickos-apt/screenshots/eleven/{n}.png" for n in (1, 2)])
        self.assertTrue(all(shot.findtext("caption") for shot in shots))
        folder = os.path.join(PACKAGE, "../../repo/screenshots")
        if not os.path.isdir(folder):
            self.skipTest("not in the source tree")
        for n in (1, 2):
            with open(os.path.join(folder, "eleven", f"{n}.png"), "rb") as f:
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
        self.assertEqual(values, {"FlickOS::style": "eleven", "FlickOS::layout": "eleven"})
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/styles")), ["eleven"])
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/layouts")), ["eleven"])

    def test_no_other_systems_name(self):
        """ADR-013 and ADR-019: named by allusion; not the name of the system
        it recalls, its maker, its design language, materials, wallpaper,
        fonts or terminal anywhere (lowercase "windows" is the ordinary
        word)."""
        marks = re.compile(r"\b(Windows|Microsoft|Win11|Fluent|Mica|Acrylic|Bloom|Segoe|Selawik|Cascadia|"
                           r"Campbell|Sun Valley|Cortana|Copilot)\b", re.IGNORECASE)
        ordinary = re.compile(r"\bwindows\b")
        for folder, _dirs, files in os.walk(PACKAGE):
            for name in files:
                if name.endswith((".png", ".pyc")) or name == os.path.basename(__file__):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                    found = marks.search(ordinary.sub("", f.read()))
                self.assertIsNone(found, os.path.join(folder, name))


class FilesTest(unittest.TestCase):

    def setUp(self):
        self.style = ini(os.path.join(STYLE, "style.ini"), "Style")
        self.layout = ini(os.path.join(LAYOUT, "layout.ini"), "Layout")

    def test_style_files_exist(self):
        for key in ("Waybar", "Foot", "Fuzzel", "Mako", "Wallpaper"):
            self.assertTrue(os.path.isfile(os.path.join(STYLE, self.style[key])), key)
        self.assertEqual(self.style["LabwcTheme"], "Eleven")

    def test_themes_come_from_the_depends(self):
        control = text(os.path.join(PACKAGE, "debian/control"))
        self.assertEqual((self.style["GtkTheme"], self.style["IconTheme"]), ("Adwaita-dark", "Adwaita"))
        for package in ("gnome-themes-extra-data", "adwaita-icon-theme", "adwaita-icon-theme-legacy",
                        "fonts-open-sans"):
            self.assertIn(package, control)
        self.assertIn("icon-theme=Adwaita", text(os.path.join(STYLE, self.style["Fuzzel"])))
        self.assertIn('font-family: "Open Sans"', text(os.path.join(LAYOUT, "style.css")))

    def test_window_theme_has_every_button(self):
        names = set(os.listdir(THEME))
        for button in BUTTONS:
            for state in STATES:
                path = os.path.join(THEME, f"{button}{state}.svg")
                self.assertEqual(ET.parse(path).getroot().tag, "{http://www.w3.org/2000/svg}svg", path)
        self.assertEqual(len(names), len(BUTTONS) * len(STATES) + 1)

    @unittest.skipUnless(os.path.isfile(ARC_THEMERC), "flickos-settings is not next to this package")
    def test_themerc_has_flickos_keys(self):
        """tools/check-palette.py wants the same keys in every FlickOS window theme."""
        self.assertEqual(themerc_keys(os.path.join(THEME, "themerc")), themerc_keys(ARC_THEMERC))

    def test_titles_on_the_left(self):
        self.assertIn("window.label.text.justify: left", text(os.path.join(THEME, "themerc")))

    def test_buttons_fill_their_slot(self):
        """Flat buttons up to the window's corner: each SVG is the button's
        size, and nothing pads the title bar around them."""
        themerc = text(os.path.join(THEME, "themerc"))
        width = re.search(r"window.button.width: (\d+)", themerc).group(1)
        height = re.search(r"window.button.height: (\d+)", themerc).group(1)
        for line in ("window.titlebar.padding.width: 0", "window.button.spacing: 0"):
            self.assertIn(line, themerc)
        for name in os.listdir(THEME):
            if name.endswith(".svg"):
                root = ET.parse(os.path.join(THEME, name)).getroot()
                self.assertEqual((root.get("width"), root.get("height")), (width, height), name)

    def test_layout_files(self):
        """One bottom bar, labwc's own button order, no dock; the apps button
        in the middle, so the menu opens above the middle."""
        for key in ("Waybar", "Style", "Preview"):
            self.assertTrue(os.path.isfile(os.path.join(LAYOUT, self.layout[key])), key)
        for key in ("TitlebarLayout", "Dock", "DockStyle", "Desktops", "Wallpaper"):
            self.assertNotIn(key, self.layout)
        self.assertEqual((self.layout["Menu"], self.layout["Quick"]), ("bottom-center", "bottom-right"))
        waybar = text(os.path.join(LAYOUT, self.layout["Waybar"]))
        self.assertIn('"include": "../common/modules.jsonc"', waybar)
        self.assertIn('"position": "bottom"', waybar)
        self.assertIn('"modules-center": ["custom/launcher", "wlr/taskbar"]', waybar)
        # The weather at the left end, two lines, only while it is on.
        self.assertIn('"modules-left": ["flickos/weather"]', waybar)
        self.assertIn('"custom/weather": { "format": "{alt}"', waybar)
        # The 12-hour clock (flickos-layout clock set 12h) rewrites %H:%M.
        self.assertIn('"clock": { "format": "{:%H:%M\\n%x}"', waybar)

    def test_window_list_is_icons_only(self):
        """waybar 0.12 doesn't shorten titles: a window list with them pushes
        the status and clock off the bar (docs/07-troubleshooting.md)."""
        waybar = text(os.path.join(LAYOUT, self.layout["Waybar"]))
        self.assertNotIn("{title}", re.sub(r'"tooltip-format": "[^"]*"', "", waybar))

    def test_css_named_colors_only(self):
        """The layout follows any style: no written-out color in its CSS."""
        css = re.sub(r"/\*.*?\*/", "", text(os.path.join(LAYOUT, self.layout["Style"])), flags=re.S)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", css))
        self.assertIn('@import url("../common/base.css");', css)

    def test_installed(self):
        installed = text(os.path.join(PACKAGE, "debian/install"))
        for folder in ("flickos/styles/eleven", "flickos/layouts/eleven", "themes/Eleven/labwc",
                       "metainfo"):
            self.assertIn(f"usr/share/{folder}/", installed)


@unittest.skipUnless(os.path.isdir(LAYOUTS), "flickos-layouts is not next to this package")
class CheckTest(unittest.TestCase):
    """flickos-layout's own check, with this package installed as it would be:
    its files next to flickos-layouts' common/ in one share folder, and
    stand-ins for the GTK and icon themes the package depends on (the build
    host need not have them)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.share = os.path.join(cls.tmp, "share")
        shutil.copytree(SHARE, cls.share)
        shutil.copytree(os.path.join(LAYOUTS, "usr/share/flickos/layouts/common"),
                        os.path.join(cls.share, "flickos/layouts/common"))
        os.makedirs(os.path.join(cls.tmp, "depends/themes/Adwaita-dark/gtk-3.0"))
        icons = os.path.join(cls.tmp, "depends/icons/Adwaita")
        os.makedirs(icons)
        with open(os.path.join(icons, "index.theme"), "w", encoding="utf-8") as f:
            f.write("[Icon Theme]\nName=Adwaita\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def env(self, home):
        return {"HOME": home, "PATH": "/usr/bin:/bin",
                "XDG_DATA_DIRS": f"{self.share}:{self.tmp}/depends:/usr/share",
                "FLICKOS_LAYOUT_PREFIX": os.path.abspath(LAYOUTS)}

    def run_layout(self, *args):
        with tempfile.TemporaryDirectory() as home:
            return subprocess.run([sys.executable, os.path.join(LAYOUTS, "usr/bin/flickos-layout"), *args],
                                  capture_output=True, text=True, env=self.env(home), check=False)

    def test_style_check_passes(self):
        """Contrast included: white text on the see-through panel and on the
        accent."""
        done = self.run_layout("check", "eleven")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_layout_check_passes(self):
        done = self.run_layout("check", "--layout", "eleven")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_listed_after_flickos_own(self):
        styles = [line.split("\t")[0] for line in self.run_layout("style", "list").stdout.splitlines()]
        layouts = [line.split("\t")[0] for line in self.run_layout("list").stdout.splitlines()]
        self.assertGreater(styles.index("eleven"), max(styles.index("dark"), styles.index("light")))
        self.assertGreater(layouts.index("eleven"), layouts.index("traditional"))

    def test_loads(self):
        """The tree's flickos-layout reads the style and the layout, with
        labwc's default buttons for GTK's windows too."""
        path = os.path.join(LAYOUTS, "usr/bin/flickos-layout")
        loader = importlib.machinery.SourceFileLoader("flickos_layout_for_eleven", path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        fl = importlib.util.module_from_spec(spec)
        loader.exec_module(fl)
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, self.env(home), clear=True):
            style = fl.styles()["eleven"]
            layout = fl.layouts()["eleven"]
        self.assertEqual(style.name, "Eleven")
        self.assertEqual(layout.menu, "bottom-center")
        self.assertFalse(layout.titlebar_layout)
        self.assertTrue(os.path.isfile(layout.waybar))
        self.assertIsNone(layout.dock)


if __name__ == "__main__":
    unittest.main()
