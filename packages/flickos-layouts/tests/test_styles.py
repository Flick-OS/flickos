"""Tests for Dark/Light styles (flickos-layout style). Run: python3 -m unittest discover -s tests

Checks that need flickos-settings' files (base configs, labwc themes) are in
tools/check-palette.py, because packages build separately.
"""

import configparser
import contextlib
import io
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from test_engine import (PACKAGE, REAL_GSETTINGS_DEFAULT, REAL_GSETTINGS_GET, REAL_GSETTINGS_RESET,
                         REAL_GSETTINGS_SET, EngineTest, fl, read)

STYLES = os.path.join(PACKAGE, "usr/share/flickos/styles")
EXPECTED = ["dark", "light"]


class StyleOverlayTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_light_style()
        self.make_layout("plain")
        self.make_layout("mac", titlebar="close,iconify,max:")
        self.foot = os.path.join(self.root, "xdg/foot/foot.ini")
        self.fuzzel = os.path.join(self.root, "xdg/fuzzel/fuzzel.ini")

    def includes(self, path):
        return re.findall(r"^include=(.*)$", read(path), re.M)

    def test_light_style_overlay(self):
        with self.quiet():
            self.assertTrue(self.prepare("plain", "light"))
        root = ET.parse(self.overlay_rcxml).getroot()
        self.assertEqual(root.findtext("theme/name"), "FlickOS-Arc")
        self.assertIsNone(root.find("theme/titlebar"))
        self.assertEqual(self.includes(self.foot), [self.base_foot, self.path("styles/light/foot.ini")])
        self.assertEqual(self.includes(self.fuzzel), [self.base_fuzzel, self.path("styles/light/fuzzel.ini")])
        for path in self.includes(self.foot) + self.includes(self.fuzzel):
            self.assertTrue(os.path.isabs(path) and os.path.isfile(path), path)

    def test_light_style_and_titlebar_layout(self):
        with self.quiet():
            self.prepare("mac", "light")
        root = ET.parse(self.overlay_rcxml).getroot()
        self.assertEqual(root.findtext("theme/name"), "FlickOS-Arc")
        self.assertEqual(root.findtext("theme/titlebar/layout"), "close,iconify,max:")

    def test_dark_style_removes_style_files(self):
        with self.quiet():
            self.prepare("plain", "light")
            self.prepare("plain", "dark")
        for path in (self.overlay_rcxml, self.foot, self.fuzzel):
            self.assertFalse(os.path.exists(path), path)

    def test_administrator_window_theme_is_kept(self):
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><theme><name>Custom</name></theme></labwc_config>\n")
        with self.quiet():
            self.prepare("plain", "light")
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        with self.quiet():
            self.prepare("mac", "light")
        self.assertEqual(ET.parse(self.overlay_rcxml).getroot().findtext("theme/name"), "Custom")

    def test_attribute_theme_name(self):
        self.write("etc/xdg/labwc/rc.xml", '<labwc_config><theme name="FlickOS-Arc-Dark"/></labwc_config>\n')
        with self.quiet():
            self.prepare("plain", "light")
        self.assertEqual(ET.parse(self.overlay_rcxml).getroot().find("theme").get("name"), "FlickOS-Arc")

    def test_window_icons_follow_the_style(self):
        with self.quiet():
            self.prepare("plain", "light")
        self.assertEqual(ET.parse(self.overlay_rcxml).getroot().findtext("theme/icon"), "Numix-Circle-Light")

    def test_window_icons_follow_the_users_icon_theme(self):
        self.gsettings["icon-theme"] = "Papirus"
        with self.quiet():
            self.prepare("plain", "dark")
        self.assertEqual(ET.parse(self.overlay_rcxml).getroot().findtext("theme/icon"), "Papirus")

    def test_administrator_icon_theme_is_kept(self):
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><theme><name>FlickOS-Arc-Dark</name>"
                   "<icon>Custom</icon></theme></labwc_config>\n")
        self.gsettings["icon-theme"] = "Papirus"
        with self.quiet():
            self.prepare("plain", "light")
        self.assertEqual(ET.parse(self.overlay_rcxml).getroot().findtext("theme/icon"), "Custom")

    def test_missing_palette_removes_file(self):
        with self.quiet():
            self.prepare("plain", "light")
        os.remove(self.path("styles/light/foot.ini"))
        with self.quiet(), contextlib.redirect_stderr(io.StringIO()) as err:
            self.prepare("plain", "light")
        self.assertFalse(os.path.exists(self.foot))
        self.assertTrue(os.path.exists(self.fuzzel))
        self.assertIn("default colors", err.getvalue())

    def test_mako_config(self):
        path = fl.update_mako(self.root, self.style("light"))
        self.assertEqual(path, os.path.join(self.root, "mako/config"))
        self.assertEqual(self.includes(path), [self.base_mako, self.path("styles/light/mako.conf")])
        os.remove(self.base_mako)
        with self.assertRaises(fl.LayoutError):
            fl.update_mako(self.root, self.style("light"))


class StyleLoadingTest(EngineTest):

    def test_resolution(self):
        self.make_light_style()
        with self.quiet():
            self.assertEqual(fl.resolve_style(fl.styles()).id, "dark")
            self.set_system_default("light", key="Style")
            self.assertEqual(fl.resolve_style(fl.styles()).id, "light")
            self.set_user_choice("dark", kind="style")
            self.assertEqual(fl.resolve_style(fl.styles()).id, "dark")
            self.set_user_choice("nonexistent", kind="style")
            self.assertEqual(fl.resolve_style(fl.styles()).id, "light")

    def test_broken_styles_skipped(self):
        self.make_light_style()
        self.write("styles/light/style.ini", read(self.path("styles/light/style.ini")).replace(
            "ColorScheme=default", "ColorScheme=dark"))
        self.write("styles/nofoot/style.ini", "[Style]\nName=No foot\nGtkTheme=A\nIconTheme=B\nLabwcTheme=C\n"
                   "ColorScheme=default\nWaybar=w.css\nFuzzel=f.ini\nMako=m.conf\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(list(fl.styles()), ["dark"])
        self.assertIn("ColorScheme=", err.getvalue())
        self.assertIn("Foot= is missing", err.getvalue())


class GSettingsTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_light_style()
        self.gsettings.update({"gtk-theme": "Arc-Dark", "icon-theme": "Numix-Circle", "color-scheme": "prefer-dark"})

    def test_switches_flickos_themes(self):
        self.assertEqual(fl.style_gsettings(self.style("light"), fl.styles()), [])
        self.assertEqual(self.gsettings, {"gtk-theme": "Arc", "icon-theme": "Numix-Circle-Light",
                                          "color-scheme": "default"})
        fl.style_gsettings(self.style("dark"), fl.styles())
        self.assertEqual(self.gsettings, {"gtk-theme": "Arc-Dark", "icon-theme": "Numix-Circle",
                                          "color-scheme": "prefer-dark"})

    def test_custom_theme_is_kept(self):
        self.gsettings["gtk-theme"] = "Adwaita"
        kept = fl.style_gsettings(self.style("light"), fl.styles())
        self.assertEqual(kept, [("gtk-theme", "Adwaita")])
        self.assertEqual(self.gsettings["gtk-theme"], "Adwaita")
        self.assertEqual(self.gsettings["icon-theme"], "Numix-Circle-Light")

    def test_doctor_reports_custom_theme(self):
        self.assertEqual(fl.doctor_warnings(), [])
        self.gsettings["icon-theme"] = "Papirus"
        [warning] = fl.doctor_warnings()
        self.assertIn("'Papirus'", warning)

    def test_real_gsettings_quoting(self):
        with mock.patch.object(fl.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="'it\\'s'\n", stderr="")
            self.assertEqual(REAL_GSETTINGS_GET("gtk-theme"), "it's")
            self.assertTrue(REAL_GSETTINGS_SET("gtk-theme", "it's"))
            self.assertEqual(run.call_args.args[0][-3:], [fl.INTERFACE_SCHEMA, "gtk-theme", "'it\\'s'"])
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="No such key")
            self.assertIsNone(REAL_GSETTINGS_GET("gtk-theme"))
            with self.quiet():
                self.assertFalse(REAL_GSETTINGS_SET("gtk-theme", "x"))
        with mock.patch.object(fl.subprocess, "run", side_effect=OSError):
            self.assertIsNone(REAL_GSETTINGS_GET("gtk-theme"))

    def test_real_gsettings_button_layout(self):
        with mock.patch.object(fl.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="'appmenu:close'\n", stderr="")
            self.assertEqual(REAL_GSETTINGS_DEFAULT("button-layout"), "appmenu:close")
            self.assertEqual(run.call_args.args[0][-3:], ["get", "org.gnome.desktop.wm.preferences", "button-layout"])
            self.assertEqual(run.call_args.kwargs["env"]["GSETTINGS_BACKEND"], "memory")
            self.assertTrue(REAL_GSETTINGS_RESET("button-layout"))
            self.assertEqual(run.call_args.args[0][-3:], ["reset", "org.gnome.desktop.wm.preferences", "button-layout"])


class ButtonLayoutTest(EngineTest):
    """button-layout: the window buttons of windows that draw their own title bar."""

    DEFAULT = "appmenu:minimize,maximize,close"
    MAC = "close,minimize,maximize:"

    def setUp(self):
        super().setUp()
        self.make_layout("flickos", order=10)
        self.make_layout("mac", order=20, titlebar="close,iconify,max:")
        self.gsettings_defaults["button-layout"] = self.DEFAULT
        self.gsettings["button-layout"] = self.DEFAULT

    def main(self, *args):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()):
            return fl.main(list(args))

    def test_gtk_button_layout(self):
        self.assertEqual(fl.gtk_button_layout("close,iconify,max:"), self.MAC)
        self.assertEqual(fl.gtk_button_layout("icon:iconify,max,close"), "icon:minimize,maximize,close")
        self.assertEqual(fl.gtk_button_layout("shade,menu:desk,close"), "menu:close")

    def test_layout_set_switches_buttons(self):
        self.assertEqual(self.main("set", "mac"), 0)
        self.assertEqual(self.gsettings["button-layout"], self.MAC)
        self.assertEqual(self.main("set", "flickos"), 0)
        self.assertEqual(self.gsettings["button-layout"], self.DEFAULT)

    def test_custom_buttons_are_kept(self):
        self.gsettings["button-layout"] = ":close"
        self.assertEqual(fl.layout_gsettings(self.layout("mac"), fl.layouts()), ":close")
        self.assertEqual(self.gsettings["button-layout"], ":close")
        [warning] = fl.doctor_warnings()
        self.assertIn("':close'", warning)

    def test_style_set_leaves_buttons_alone(self):
        self.make_light_style()
        self.gsettings["button-layout"] = self.MAC
        self.assertEqual(self.main("style", "set", "light"), 0)
        self.assertEqual(self.gsettings["button-layout"], self.MAC)

    def test_without_gsettings(self):
        self.gsettings.clear()
        self.assertIsNone(fl.layout_gsettings(self.layout("mac"), fl.layouts()))
        self.assertEqual(self.gsettings, {})
        self.assertEqual(fl.doctor_warnings(), [])


class StyleCommandTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_light_style()
        self.make_layout("flickos", order=10)
        self.make_layout("mac", order=20, titlebar="close,iconify,max:")
        self.gsettings.update({"gtk-theme": "Arc-Dark", "icon-theme": "Numix-Circle", "color-scheme": "prefer-dark"})

    def main(self, *args):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            status = fl.main(list(args))
        return status, out.getvalue()

    def test_list_and_current(self):
        self.assertEqual(self.main("style", "list"),
                         (0, f"dark\tDark\tThe dark style\t{self.path('styles/dark')}\n"
                             f"light\tLight\tThe light style\t{self.path('styles/light')}\n"))
        self.assertEqual(self.main("style", "current"), (0, "dark\n"))

    def test_style_set_outside_session(self):
        status, out = self.main("style", "set", "light")
        self.assertEqual(status, 0)
        self.assertEqual(out, "Style 'Light' saved. It applies at next login.\n")
        self.assertEqual(read(self.path("home/.config/flickos/style")), "light\n")
        self.assertFalse(os.path.exists(self.path("home/.config/flickos/layout")))
        self.assertEqual(self.gsettings["gtk-theme"], "Arc")
        # The icon theme is set before the overlay, which takes it for window icons.
        self.assertEqual(ET.parse(self.overlay_rcxml).getroot().findtext("theme/icon"), "Numix-Circle-Light")
        self.assertTrue(os.path.exists(os.path.join(self.root, "xdg/foot/foot.ini")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "mako/config")))
        self.assertEqual(self.main("style", "current"), (0, "light\n"))

        self.assertEqual(self.main("style", "set", "dark")[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "xdg/foot/foot.ini")))
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_style_set_live(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-0", LABWC_PID="1")
        with mock.patch.object(fl.subprocess, "run") as run, mock.patch.object(fl, "restart_panel") as restart:
            status, out = self.main("style", "set", "light")
        self.assertEqual((status, out), (0, "Style 'Light' applied.\n"))
        self.assertEqual([c.args[0] for c in run.call_args_list], [["labwc", "--reconfigure"], ["makoctl", "reload"]])
        layout, style, _, _ = restart.call_args.args
        self.assertEqual((layout.id, style.id), ("flickos", "light"))

    def test_layout_set_leaves_gtk_settings_alone(self):
        self.gsettings["gtk-theme"] = "Arc"
        os.environ.update(WAYLAND_DISPLAY="wayland-0", LABWC_PID="1")
        with mock.patch.object(fl.subprocess, "run") as run, mock.patch.object(fl, "restart_panel"):
            self.assertEqual(self.main("set", "mac")[0], 0)
        self.assertEqual(self.gsettings["gtk-theme"], "Arc")
        self.assertEqual([c.args[0] for c in run.call_args_list], [["labwc", "--reconfigure"]])

    def test_set_layout_and_style(self):
        status, out = self.main("set", "mac", "--style", "light")
        self.assertEqual((status, out), (0, "Layout 'Mac' and style 'Light' saved. They apply at next login.\n"))
        self.assertEqual(read(self.path("home/.config/flickos/style")), "light\n")
        self.assertEqual(read(self.path("home/.config/flickos/layout")), "mac\n")

    def test_unknown_style_changes_nothing(self):
        self.assertEqual(self.main("set", "mac", "--style", "nope")[0], 1)
        self.assertEqual(self.main("style", "set", "nope")[0], 1)
        self.assertFalse(os.path.exists(self.path("home/.config/flickos")))
        self.assertEqual(self.gsettings["gtk-theme"], "Arc-Dark")

    def test_doctor_user_color_configs(self):
        self.write("home/.config/foot/foot.ini", "")
        self.write("home/.config/mako/config", "")
        warnings = fl.doctor_warnings()
        self.assertEqual(len(warnings), 2)
        self.assertIn("terminal", warnings[0])
        self.assertIn("notifications", warnings[1])

    def test_panel_uses_user_mako_config(self):
        self.write("home/.config/mako/config", "")
        with mock.patch.object(fl, "supervise", return_value=0), \
                mock.patch.object(fl, "start_supervised") as start, self.quiet():
            self.assertEqual(fl.main(["panel"]), 0)
        self.assertEqual(start.call_args.args[0], ["mako"])


def ini_keys(path):
    """{section: set of keys} of a foot, fuzzel or mako file (keys before a section: "main")."""
    keys, section = {}, "main"
    for line in read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        keys.setdefault(section, set()).add(line.split("=", 1)[0].strip())
    return keys


class ShippedStylesTest(unittest.TestCase):

    def setUp(self):
        # Only the package's styles: no user's or build host's folders, and
        # the themes count as installed (CI has none of them).
        empty = tempfile.mkdtemp(prefix="flickos-layout-test-")
        self.addCleanup(os.rmdir, empty)
        with mock.patch.object(fl, "STYLES_DIR", STYLES), mock.patch.object(fl, "theme_installed", lambda k, n: True), \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": empty, "XDG_DATA_DIRS": empty}), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.styles = fl.styles()
        self.warnings = err.getvalue()

    def test_expected_styles_without_warnings(self):
        self.assertEqual(list(self.styles), EXPECTED)
        self.assertEqual(self.warnings, "")

    def test_defaults(self):
        self.assertEqual((fl.DEFAULT_STYLE, fl.BASE_STYLE), ("dark", "dark"))
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(PACKAGE, "etc/xdg/flickos/layouts.conf"))
        self.assertEqual(ini["Defaults"]["Style"], fl.DEFAULT_STYLE)

    def test_themes(self):
        dark, light = self.styles["dark"], self.styles["light"]
        self.assertEqual((dark.gtk_theme, dark.icon_theme, dark.labwc_theme, dark.color_scheme),
                         ("Arc-Dark", "Numix-Circle", "FlickOS-Arc-Dark", "prefer-dark"))
        self.assertEqual((light.gtk_theme, light.icon_theme, light.labwc_theme, light.color_scheme),
                         ("Arc", "Numix-Circle-Light", "FlickOS-Arc", "default"))

    def test_palette_files_exist(self):
        for style in self.styles.values():
            for path in (style.waybar, style.foot, style.fuzzel, style.mako):
                self.assertTrue(os.path.isabs(path) and os.path.isfile(path), path)

    def test_every_style_has_a_linked_wallpaper(self):
        with open(os.path.join(PACKAGE, "debian/links"), encoding="utf-8") as f:
            links = dict(line.split() for line in f if line.strip())
        for style in self.styles.values():
            self.assertTrue(style.wallpaper and os.path.isfile(style.wallpaper), style.id)
            with open(style.wallpaper, "rb") as f:
                self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n", f"{style.wallpaper}: not a PNG")
            installed = os.path.relpath(style.wallpaper, PACKAGE)
            self.assertEqual(links.get(installed), f"usr/share/backgrounds/flickos/flickos-{style.id}.png")
        self.assertEqual(len(links), len(self.styles))

    def test_same_keys_in_every_style(self):
        dark, light = self.styles["dark"], self.styles["light"]
        names = lambda path: re.findall(r"@define-color\s+([\w-]+)", read(path))
        self.assertEqual(names(dark.waybar), names(light.waybar))
        for attribute in ("foot", "fuzzel", "mako"):
            with self.subTest(component=attribute):
                self.assertEqual(ini_keys(getattr(dark, attribute)), ini_keys(getattr(light, attribute)))

    def test_fuzzel_icon_theme_matches_style(self):
        for style in self.styles.values():
            ini = configparser.ConfigParser(interpolation=None)
            ini.read(style.fuzzel)
            self.assertEqual(ini["main"]["icon-theme"], style.icon_theme)


if __name__ == "__main__":
    unittest.main()
