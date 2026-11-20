"""Tests for flickos-theme: the themes build.sh compiled into build/ exist,
parse, and carry FlickOS's changes. Nothing outside the package folder is read."""

import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
THEMES = os.path.join(PKG, "build", "usr", "share", "themes")
NAMES = ("FlickOS-Arc-Dark", "FlickOS-Arc")
PARTS = ("gtk-3.0", "gtk-4.0")
# Named by arc-theme's CSS but not in its gresource either (checked against
# Debian's arc-theme 20221218-1, GTK 3 and 4, Arc and Arc-Dark): a thumbnail
# frame, and GTK 4's text selection handles and slider marks. The stock themes
# draw without them.
UPSTREAM_MISSING = ("assets/thumbnail-frame", "assets/text-select-", "assets/slider-horz-scale-has-marks-above")


def sources(gtk):
    root = os.path.join(PKG, "src", gtk, "sass")
    for name in sorted(os.listdir(root)):
        with open(os.path.join(root, name), encoding="utf-8") as handle:
            yield name, handle.read()


class BuiltTheme(unittest.TestCase):
    def test_every_theme_has_both_parts(self):
        for name in NAMES:
            for part in PARTS:
                for file in ("gtk.css", "gtk-dark.css", "gtk.gresource"):
                    self.assertTrue(os.path.isfile(os.path.join(THEMES, name, part, file)),
                                    f"{name}/{part}/{file}")

    def test_gresource_holds_the_stylesheets_and_assets(self):
        for name, sheets in (("FlickOS-Arc-Dark", {"gtk-main-dark.css"}),
                             ("FlickOS-Arc", {"gtk-main-dark.css", "gtk-main.css"})):
            for part in PARTS:
                out = subprocess.run(["gresource", "list", os.path.join(THEMES, name, part, "gtk.gresource")],
                                     check=True, capture_output=True, text=True).stdout.split()
                have = {os.path.basename(path) for path in out if path.endswith(".css")}
                self.assertEqual(have, sheets, f"{name}/{part}")
                self.assertEqual(len([p for p in out if "/assets/" in p]), 168, f"{name}/{part}")

    def test_gtk_css_imports_what_the_gresource_has(self):
        for name in NAMES:
            for part in PARTS:
                folder = os.path.join(THEMES, name, part)
                listing = subprocess.run(["gresource", "list", os.path.join(folder, "gtk.gresource")],
                                         check=True, capture_output=True, text=True).stdout.split()
                for file in ("gtk.css", "gtk-dark.css"):
                    with open(os.path.join(folder, file), encoding="utf-8") as handle:
                        first = handle.readline().strip()
                    m = re.fullmatch(r'@import url\("resource://(/[^"]+)"\);', first)
                    self.assertTrue(m, f"{name}/{part}/{file}: {first}")
                    self.assertIn(m.group(1), listing)

    def test_light_theme_is_light_and_dark_preference_is_dark(self):
        def imported(name, file):
            with open(os.path.join(THEMES, name, "gtk-3.0", file), encoding="utf-8") as handle:
                return handle.readline()
        self.assertIn("gtk-main-dark.css", imported("FlickOS-Arc-Dark", "gtk.css"))
        self.assertIn("gtk-main.css", imported("FlickOS-Arc", "gtk.css"))
        self.assertIn("gtk-main-dark.css", imported("FlickOS-Arc", "gtk-dark.css"))

    def test_every_asset_a_stylesheet_names_is_in_the_gresource(self):
        for name in NAMES:
            for part in PARTS:
                path = os.path.join(THEMES, name, part, "gtk.gresource")
                listing = subprocess.run(["gresource", "list", path], check=True,
                                         capture_output=True, text=True).stdout.split()
                for sheet in [p for p in listing if p.endswith(".css")]:
                    css = subprocess.run(["gresource", "extract", path, sheet], check=True,
                                         capture_output=True, text=True).stdout
                    wanted = {a for a in re.findall(r'url\("(assets/[^"]+)"\)', css)
                              if not a.startswith(UPSTREAM_MISSING)}
                    self.assertTrue(wanted, f"{name}/{part}{sheet} uses no assets")
                    base = sheet.rsplit("/", 1)[0] + "/"
                    for asset in wanted:
                        self.assertIn(base + asset, listing, f"{name}/{part}: {asset}")

    def test_gtk3_stylesheets_parse(self):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gio, Gtk
        except (ImportError, ValueError):
            self.skipTest("GTK 3 is not available")
        for name in NAMES:
            folder = os.path.join(THEMES, name, "gtk-3.0")
            Gio.Resource.load(os.path.join(folder, "gtk.gresource"))._register()
            for file in ("gtk.css", "gtk-dark.css"):
                errors = []
                provider = Gtk.CssProvider()
                provider.connect("parsing-error", lambda _p, section, error: errors.append(
                    f"{section.get_start_line() + 1}: {error.message}"))
                provider.load_from_path(os.path.join(folder, file))
                self.assertEqual(errors, [], f"{name}/{file}")
                self.assertGreater(len(provider.to_string()), 100000)

    def test_flickos_corners_are_in_the_built_css(self):
        for name in NAMES:
            with open(os.path.join(THEMES, name, "gtk-3.0", "gtk.css"), encoding="utf-8") as handle:
                frame = handle.read()
            self.assertIn("decoration", frame)
        listing = subprocess.run(["gresource", "extract",
                                  os.path.join(THEMES, "FlickOS-Arc", "gtk-3.0", "gtk.gresource"),
                                  "/org/flickos/theme/light/gtk-3.0/gtk-main.css"],
                                 check=True, capture_output=True, text=True).stdout
        self.assertIn("border-radius: 8px", listing)
        self.assertIn("border-radius: 6px", listing)


class Source(unittest.TestCase):
    def test_header_height_and_sidebar_variables_are_defined_once(self):
        for gtk in ("gtk-3.0", "gtk-4.0"):
            colors = dict(sources(gtk))["_colors.scss"]
            self.assertEqual(len(re.findall(r"^\$header_height:", colors, re.M)), 1, gtk)
        colors = dict(sources("gtk-3.0"))["_colors.scss"]
        for variable in ("side_bg", "side_fg", "side_border"):
            self.assertIn(f"${variable}:", colors)

    def test_changes_are_marked(self):
        for gtk in ("gtk-3.0", "gtk-4.0"):
            marked = sum(text.count("FlickOS:") for _name, text in sources(gtk))
            self.assertGreater(marked, 20, gtk)


if __name__ == "__main__":
    unittest.main()
