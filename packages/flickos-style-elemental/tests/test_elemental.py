"""Tests for the Elemental style package: its metainfo makes it a style with
a layout in Software, its files are complete, its layout has its own bar and
dock look over Cupertino's dock, and (when the other packages are next to
this one, as in the source tree) flickos-layout's `check` passes the style
and the layout, the dock generates, and its window theme has the keys
FlickOS's own have.
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
STYLE = os.path.join(SHARE, "flickos/styles/elemental")
LAYOUT = os.path.join(SHARE, "flickos/layouts/elemental")
THEME = os.path.join(SHARE, "themes/Elemental/labwc")
METAINFO = os.path.join(SHARE, "metainfo/io.github.dvbondoy.flickos.styles.Elemental.metainfo.xml")
LAYOUTS = os.path.join(PACKAGE, "../flickos-layouts")
CUPERTINO = os.path.join(LAYOUTS, "usr/share/flickos/layouts/cupertino")
ARC_THEMERC = os.path.join(PACKAGE, "../flickos-settings/usr/share/themes/FlickOS-Arc/labwc/themerc")
# Every button labwc 0.8 draws, in every state it looks for.
BUTTONS = ("close", "iconify", "max", "max_toggled", "shade", "shade_toggled", "desk", "desk_toggled")
STATES = ("-active", "-inactive", "_hover-active", "_hover-inactive")
# The Debian icon theme's name, its package's, and the words for it: the
# only places the desktop Elemental recalls may be named (ADR-017).
ICON_THEME_NAMES = re.compile(r"elementary-icon-theme|=elementary$|elementary icons", re.MULTILINE)


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

    def test_addon_of_the_layout_chooser(self):
        self.assertEqual(self.root.get("type"), "addon")
        self.assertEqual(self.root.findtext("extends"), "flickos-layout.desktop")
        self.assertEqual(self.root.findtext("id") + ".metainfo.xml", os.path.basename(METAINFO))

    def test_names_the_style_and_the_layout(self):
        """ADR-014: Software's Use sets both."""
        values = {v.get("key"): v.text for v in self.root.findall("custom/value")}
        self.assertEqual(values, {"FlickOS::style": "elemental", "FlickOS::layout": "elemental"})
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/styles")), ["elemental"])
        self.assertEqual(os.listdir(os.path.join(SHARE, "flickos/layouts")), ["elemental"])

    def test_no_other_systems_name(self):
        """ADR-013 and ADR-017: named by allusion; no other desktop's name or
        its parts' names anywhere. The Debian icon theme keeps its name."""
        marks = re.compile(r"elementary|\b(pantheon|wingpanel|plank|odin|juno|loki|freya|hera|horus|jolnir)\b",
                           re.IGNORECASE)
        for folder, _dirs, files in os.walk(PACKAGE):
            for name in files:
                if name.endswith((".png", ".pyc")) or name == os.path.basename(__file__):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                    found = marks.search(ICON_THEME_NAMES.sub("", f.read()))
                self.assertIsNone(found, os.path.join(folder, name))


class FilesTest(unittest.TestCase):

    def setUp(self):
        self.style = ini(os.path.join(STYLE, "style.ini"), "Style")
        self.layout = ini(os.path.join(LAYOUT, "layout.ini"), "Layout")

    def test_style_files_exist(self):
        for key in ("Waybar", "Foot", "Fuzzel", "Mako", "Wallpaper"):
            self.assertTrue(os.path.isfile(os.path.join(STYLE, self.style[key])), key)
        self.assertEqual(self.style["LabwcTheme"], "Elemental")

    def test_themes_and_font_come_from_the_depends(self):
        control = text(os.path.join(PACKAGE, "debian/control"))
        self.assertEqual((self.style["GtkTheme"], self.style["IconTheme"]), ("Adwaita", "elementary"))
        for package in ("gnome-themes-extra-data", "elementary-icon-theme", "fonts-inter-variable", "sfwbar"):
            self.assertIn(package, control)
        for css in ("style.css", "dock.css"):
            self.assertIn('"Inter Variable"', text(os.path.join(LAYOUT, css)), css)
        self.assertIn("icon-theme=elementary", text(os.path.join(STYLE, self.style["Fuzzel"])))

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

    def test_centered_titles(self):
        self.assertIn("window.label.text.justify: center", text(os.path.join(THEME, "themerc")))

    def test_close_left_maximize_right(self):
        """ADR-017: the desktop it recalls has only these two buttons."""
        self.assertEqual(self.layout["TitlebarLayout"], "close:max")
        self.assertTrue(os.path.isfile(os.path.join(LAYOUT, self.layout["Preview"])))

    def test_layout_files(self):
        """Its own bar and look; the dock's behavior is Cupertino's, so its fixes reach this layout."""
        for key in ("Waybar", "Style", "DockStyle"):
            self.assertTrue(os.path.isfile(os.path.join(LAYOUT, self.layout[key])), key)
        self.assertEqual(self.layout["Dock"], "../cupertino/dock.config")
        waybar = text(os.path.join(LAYOUT, self.layout["Waybar"]))
        self.assertIn('"include": "../common/modules.jsonc"', waybar)
        self.assertIn('"custom/launcher": { "format": "Applications" }', waybar)
        # The 12-hour clock (flickos-layout clock set 12h) rewrites %H:%M.
        self.assertRegex(waybar, r'"clock": \{ "format": "\{:%a, %b %e  %H:%M\}" \}')

    def test_bar_drawn_as_check_tests_it(self):
        """check tests wm_bg at its alpha times base.css's 0.85 (PANEL_ALPHA):
        the bar must not be drawn lighter."""
        css = text(os.path.join(LAYOUT, self.layout["Style"]))
        self.assertEqual(re.findall(r"background: alpha\(@wm_bg, ([0-9.]+)\)", css), ["0.85"])

    @unittest.skipUnless(os.path.isdir(CUPERTINO), "flickos-layouts is not next to this package")
    def test_dock_and_corners_are_cupertinos(self):
        """The dock config is Cupertino's file; pins, menu and Quick Settings
        corners can't be shared by reference, so they stay Cupertino's."""
        cupertino = ini(os.path.join(CUPERTINO, "layout.ini"), "Layout")
        self.assertEqual(os.path.basename(self.layout["Dock"]), cupertino["Dock"])
        self.assertTrue(os.path.isfile(os.path.join(CUPERTINO, cupertino["Dock"])))
        for key in ("Pinned", "Menu", "MenuStyle", "Quick"):
            self.assertEqual(self.layout[key], cupertino[key], key)
        self.assertNotEqual(self.layout["TitlebarLayout"], cupertino["TitlebarLayout"])

    def test_installed(self):
        installed = text(os.path.join(PACKAGE, "debian/install"))
        for folder in ("flickos/styles/elemental", "flickos/layouts/elemental", "themes/Elemental/labwc",
                       "metainfo"):
            self.assertIn(f"usr/share/{folder}/", installed)


@unittest.skipUnless(os.path.isdir(LAYOUTS), "flickos-layouts is not next to this package")
class CheckTest(unittest.TestCase):
    """flickos-layout's own check, with this package installed as it would be:
    its files next to flickos-layouts' common/ and cupertino/ in one share
    folder, and a stand-in for the icon theme the package depends on (the
    build host need not have it)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.share = os.path.join(cls.tmp, "share")
        shutil.copytree(SHARE, cls.share)
        for name in ("common", "cupertino"):     # the dock's config is Cupertino's
            shutil.copytree(os.path.join(LAYOUTS, "usr/share/flickos/layouts", name),
                            os.path.join(cls.share, "flickos/layouts", name))
        icons = os.path.join(cls.tmp, "depends/icons/elementary")
        os.makedirs(icons)
        with open(os.path.join(icons, "index.theme"), "w", encoding="utf-8") as f:
            f.write("[Icon Theme]\nName=elementary\n")

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
        """Contrast included: white text on the see-through bar over a white wallpaper."""
        done = self.run_layout("check", "elemental")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_layout_check_passes(self):
        done = self.run_layout("check", "--layout", "elemental")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_listed_after_flickos_own(self):
        styles = [line.split("\t")[0] for line in self.run_layout("style", "list").stdout.splitlines()]
        layouts = [line.split("\t")[0] for line in self.run_layout("list").stdout.splitlines()]
        self.assertGreater(styles.index("elemental"), max(styles.index("dark"), styles.index("light")))
        self.assertGreater(layouts.index("elemental"), layouts.index("traditional"))

    def test_buttons_and_dock(self):
        """The tree's flickos-layout reads Cupertino's files through the
        layout, generates its dock, and gives GTK's windows the same buttons."""
        path = os.path.join(LAYOUTS, "usr/bin/flickos-layout")
        loader = importlib.machinery.SourceFileLoader("flickos_layout_for_elemental", path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        fl = importlib.util.module_from_spec(spec)
        loader.exec_module(fl)
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, self.env(home), clear=True):
            style = fl.styles()["elemental"]
            layout = fl.layouts()["elemental"]
            fl.update_dock(home, layout, style, menu=True)
            config = text(os.path.join(home, "dock/sfwbar.config"))
        self.assertEqual(fl.gtk_button_layout(layout.titlebar_layout), "close:maximize")
        self.assertTrue(os.path.isfile(layout.waybar))
        self.assertIsNone(fl.DOCK_PINS.search(config))
        self.assertIn("@define-color wm_bg rgba(0, 0, 0, 0.65)", config)
        self.assertIn("background-color: alpha(@fg_color, 0.6);", config)     # the light dock

    def test_panel_alpha(self):
        """The 0.85 the bar is drawn at is check's PANEL_ALPHA."""
        path = os.path.join(LAYOUTS, "usr/bin/flickos-layout")
        self.assertRegex(text(path), r"(?m)^PANEL_ALPHA = 0\.85$")


if __name__ == "__main__":
    unittest.main()
