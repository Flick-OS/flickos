"""Tests for users' own styles: lookup, Inherits=, missing themes, the
stable palette files, `style new` and `check` (docs/design/flickos-ricing.md,
phase 1, step 1a). Run: python3 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import re
from unittest import mock

from test_engine import EngineTest, fl, read

DARK_WAYBAR = ("/* Dark palette */\n@define-color bg_color #383c4a;\n@define-color base_color #404552;\n"
               "@define-color fg_color #d3dae3;\n@define-color selected_bg_color #5294e2;\n"
               "@define-color selected_fg_color #ffffff;\n")
DARK_FOOT = "[colors]\nbackground=383c4a\nforeground=d3dae3\nregular4=5294e2\n"
DARK_FUZZEL = "[main]\nicon-theme=Numix-Circle\n[colors]\nbackground=383c4aee\ntext=d3dae3ff\n"
DARK_MAKO = "background-color=#383c4aee\ntext-color=#d3dae3\n\n[urgency=critical]\nborder-color=#fc4138\n"


class UserStyleTest(EngineTest):
    """A Dark with real palette keys, a Light, and helpers for users' styles."""

    def setUp(self):
        super().setUp()
        self.write("styles/dark/waybar-colors.css", DARK_WAYBAR)
        self.write("styles/dark/foot.ini", DARK_FOOT)
        self.write("styles/dark/fuzzel.ini", DARK_FUZZEL)
        self.write("styles/dark/mako.conf", DARK_MAKO)
        self.make_light_style()
        self.make_layout("plain")
        self.user_dir = self.path("home/.local/share/flickos/styles")

    def user_style(self, style_id, ini, **files):
        """A style in the user's folder: style.ini lines, then files by name."""
        self.write(f"home/.local/share/flickos/styles/{style_id}/style.ini", "[Style]\n" + ini)
        for name, text in files.items():
            # waybar_colors_css -> waybar-colors.css, w_css -> w.css
            base, extension = name.rsplit("_", 1)
            self.write(f"home/.local/share/flickos/styles/{style_id}/{base.replace('_', '-')}.{extension}", text)
        return os.path.join(self.user_dir, style_id)

    def orange(self):
        """dark-orange: inherits Dark, sets one panel color and one terminal color."""
        return self.user_style("dark-orange", "Name=Dark Orange\nInherits=dark\nWaybar=waybar-colors.css\n"
                                              "Foot=foot.ini\n",
                               waybar_colors_css="@define-color selected_bg_color #b5480c;\n",
                               foot_ini="[colors]\nregular4=b5480c\n")

    def main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            status = fl.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def styles(self):
        with self.quiet():
            return fl.styles()


class LookupTest(UserStyleTest):

    def test_users_style_is_listed(self):
        folder = self.orange()
        found = self.styles()
        self.assertEqual(list(found), ["dark", "light", "dark-orange"])
        self.assertTrue(found["dark-orange"].user)
        self.assertFalse(found["dark"].user)
        self.assertEqual(found["dark-orange"].folder, folder)

    def test_users_folder_wins(self):
        """ADR-001: a user's folder with FlickOS's id hides FlickOS's."""
        self.user_style("light", "Name=My Light\nInherits=dark\n")
        found = self.styles()
        self.assertEqual(found["light"].name, "My Light")
        self.assertTrue(found["light"].user)

    def test_xdg_data_dirs_folder(self):
        """An administrator's styles in /usr/local/share/flickos/styles."""
        self.write("data/flickos/styles/site/style.ini", "[Style]\nName=Site\nInherits=dark\n")
        found = self.styles()
        self.assertIn("site", found)
        self.assertFalse(found["site"].user)

    def test_source_tree_styles_before_installed_ones(self):
        """FLICKOS_LAYOUT_PREFIX: the tree's styles, not /usr/share's."""
        self.write("data/flickos/styles/dark/style.ini", "[Style]\nName=Installed Dark\nInherits=light\n")
        self.assertEqual(self.styles()["dark"].name, "Installed Dark")
        with mock.patch.object(fl, "PREFIX", "/tree"):
            self.assertEqual(self.styles()["dark"].name, "Dark")

    def test_system_styles_without_xdg_data_dirs(self):
        """The XDG default then; the build host's /usr/share may hold style
        packages (flickos-style-seven), so only the order of ours is tested."""
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": ""}):
            self.assertEqual(fl.system_data_dirs(), ["/usr/local/share", "/usr/share"])
            self.assertEqual(list(self.styles())[:2], ["dark", "light"])

    def test_list_and_state(self):
        folder = self.orange()
        status, out, _err = self.main("style", "list")
        self.assertEqual(status, 0)
        self.assertIn(f"dark-orange\tDark Orange\tThe dark style\t{folder}\n", out)
        state = json.loads(self.main("state")[1])
        choice = next(c for c in state["style"]["choices"] if c["id"] == "dark-orange")
        self.assertEqual((choice["user"], choice["folder"], choice["parent"]), (True, folder, "dark"))
        dark = next(c for c in state["style"]["choices"] if c["id"] == "dark")
        self.assertEqual((dark["user"], dark["parent"]), (False, None))


class InheritsTest(UserStyleTest):

    def test_keys_and_chains_from_the_parent(self):
        folder = self.orange()
        style, dark = self.styles()["dark-orange"], self.styles()["dark"]
        self.assertEqual((style.gtk_theme, style.icon_theme, style.labwc_theme, style.color_scheme),
                         (dark.gtk_theme, dark.icon_theme, dark.labwc_theme, dark.color_scheme))
        self.assertEqual(style.chain["waybar"], [dark.waybar, os.path.join(folder, "waybar-colors.css")])
        self.assertEqual(style.chain["foot"], [dark.foot, os.path.join(folder, "foot.ini")])
        self.assertEqual(style.chain["mako"], [dark.mako])
        self.assertEqual(style.waybar, os.path.join(folder, "waybar-colors.css"))
        self.assertEqual(style.parent, "dark")

    def test_two_levels(self):
        self.orange()
        self.user_style("deep", "Name=Deep\nInherits=dark-orange\nGtkTheme=Other\nFuzzel=fuzzel.ini\n",
                        fuzzel_ini="[colors]\ntext=ffffffff\n")
        style = self.styles()["deep"]
        self.assertEqual(len(style.chain["waybar"]), 2)
        self.assertEqual(len(style.chain["fuzzel"]), 2)
        self.assertEqual(style.gtk_theme, "Other")

    def test_comment_and_order(self):
        self.user_style("plainer", "Name=Plainer\nInherits=light\n")
        style = self.styles()["plainer"]
        self.assertEqual((style.comment, style.order), ("The light style", 20))

    def test_missing_parent_and_circle_are_broken(self):
        self.user_style("orphan", "Name=Orphan\nInherits=nothing\n")
        self.user_style("one", "Name=One\nInherits=two\n")
        self.user_style("two", "Name=Two\nInherits=one\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            found = fl.styles()
        self.assertEqual(list(found), ["dark", "light"])
        self.assertIn("Inherits=nothing, which isn't installed", err.getvalue())
        self.assertIn("goes round in a circle", err.getvalue())

    def test_without_inherits_every_key_is_needed(self):
        self.user_style("lonely", "Name=Lonely\nGtkTheme=Arc-Dark\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertNotIn("lonely", fl.styles())
        self.assertIn("lonely/style.ini: Waybar= is missing", err.getvalue())


class GeneratedFilesTest(UserStyleTest):

    def setUp(self):
        super().setUp()
        self.folder = self.orange()
        self.style = self.styles()["dark-orange"]
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style, fl.labwc_themes(fl.styles()))

    def includes(self, path):
        return re.findall(r"^include=(.*)$", read(path), re.M)

    def test_foot_and_fuzzel_overlay(self):
        self.assertEqual(self.includes(os.path.join(self.root, "xdg/foot/foot.ini")),
                         [self.base_foot, self.path("styles/dark/foot.ini"), os.path.join(self.folder, "foot.ini")])
        self.assertEqual(self.includes(os.path.join(self.root, "xdg/fuzzel/fuzzel.ini")),
                         [self.base_fuzzel, self.path("styles/dark/fuzzel.ini")])

    def test_mako(self):
        with self.quiet():
            path = fl.update_mako(self.root, self.style)
        self.assertEqual(self.includes(path), [self.base_mako, self.path("styles/dark/mako.conf")])

    def test_panel_css_imports_the_chain(self):
        with self.quiet():
            fl.update_waybar(self.root, self.layout("plain"), self.style)
        css = read(os.path.join(self.root, "waybar/style.css"))
        imports = re.findall(r'@import url\("(.*)"\);', css)
        self.assertEqual(imports[:3], [self.path("styles/dark/waybar-colors.css"),
                                       os.path.join(self.folder, "waybar-colors.css"),
                                       self.path("layouts/plain/style.css")])

    def test_dock_has_both_palettes_users_last(self):
        self.make_layout("docked", extra="Dock=dock.config\nDockStyle=dock.css\n")
        self.write("layouts/docked/dock.config", "#Api2\nlayout {}\n")
        self.write("layouts/docked/dock.css", "button {}\n")
        with self.quiet():
            fl.update_dock(self.root, self.layout("docked"), self.style)
        text = read(os.path.join(self.root, "dock/sfwbar.config"))
        self.assertLess(text.index("#5294e2"), text.index("#b5480c"))

    def test_chooser_colors_merge_the_chain(self):
        colors = fl.palette_colors(fl.palette_chain(self.style, "waybar"))
        self.assertEqual(colors["selected_bg_color"], tuple(int(v, 16) / 255 for v in ("b5", "48", "0c")))
        self.assertEqual(colors["bg_color"], tuple(int(v, 16) / 255 for v in ("38", "3c", "4a")))

    def test_stable_palettes(self):
        """ADR-003: foot's and fuzzel's colors of the style in use, always."""
        self.assertEqual(self.includes(os.path.join(self.root, "style/foot.ini")),
                         [self.path("styles/dark/foot.ini"), os.path.join(self.folder, "foot.ini")])
        self.assertEqual(self.includes(os.path.join(self.root, "style/fuzzel.ini")),
                         [self.path("styles/dark/fuzzel.ini")])
        self.assertFalse(os.path.exists(os.path.join(self.root, "style/mako.conf")))

    def test_stable_palettes_for_dark_too(self):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.styles()["dark"], fl.labwc_themes(fl.styles()))
        self.assertEqual(self.includes(os.path.join(self.root, "style/foot.ini")),
                         [self.path("styles/dark/foot.ini")])
        self.assertFalse(os.path.exists(os.path.join(self.root, "xdg/foot/foot.ini")))


class FallbackTest(UserStyleTest):
    """ADR-009: a theme that isn't installed becomes the parent's."""

    def missing(self, *names):
        patcher = mock.patch.object(fl, "theme_installed", lambda kind, name: name not in names)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_falls_back_to_the_parent(self):
        self.missing("Nordic", "Papirus")
        self.user_style("nordic", "Name=Nordic\nInherits=light\nGtkTheme=Nordic\nIconTheme=Papirus\n")
        style = self.styles()["nordic"]
        self.assertEqual((style.gtk_theme, style.icon_theme), ("Arc", "Numix-Circle-Light"))
        self.assertEqual(fl.style_fallback_messages(style), [
            "style nordic: the GTK theme Nordic isn't installed, so windows use Arc",
            "style nordic: the icon theme Papirus isn't installed, so icons come from Numix-Circle-Light"])

    def test_without_parent_falls_back_to_dark(self):
        self.missing("Nordic")
        self.user_style("solo", "Name=Solo\nGtkTheme=Nordic\nIconTheme=Numix-Circle\nLabwcTheme=FlickOS-Arc\n"
                                "ColorScheme=default\nWaybar=w.css\nFoot=f.ini\nFuzzel=f.ini\nMako=m.conf\n")
        self.assertEqual(self.styles()["solo"].gtk_theme, "Arc-Dark")

    def test_warns_only_about_the_style_in_use(self):
        self.missing("Nordic")
        self.user_style("nordic", "Name=Nordic\nInherits=dark\nGtkTheme=Nordic\n")
        self.assertNotIn("Nordic", self.main("prepare")[2])
        self.set_user_choice("nordic", "style")
        status, _out, err = self.main("prepare")
        self.assertEqual(status, 0)
        self.assertIn("the GTK theme Nordic isn't installed, so windows use Arc-Dark", err)
        self.assertIn("Style nordic: the GTK theme Nordic isn't installed, so windows use Arc-Dark.",
                      fl.doctor_warnings())

    def test_missing_theme_with_nothing_to_fall_back_to(self):
        self.missing("Arc-Dark")
        dark = self.styles()["dark"]
        self.assertEqual(dark.gtk_theme, "Arc-Dark")
        self.assertEqual(fl.style_fallback_messages(dark), ["style dark: the GTK theme Arc-Dark isn't installed"])


class StyleNewTest(UserStyleTest):

    def test_makes_an_inheriting_starter(self):
        status, out, _err = self.main("style", "new", "mine", "--from", "dark", "--name", "My Style")
        folder = os.path.join(self.user_dir, "mine")
        self.assertEqual((status, out), (0, folder + "\n"))
        self.assertEqual(sorted(os.listdir(folder)),
                         ["foot.ini", "fuzzel.ini", "mako.conf", "style.ini", "waybar-colors.css"])
        style = self.styles()["mine"]
        self.assertEqual((style.name, style.parent, style.comment), ("My Style", "dark", "Based on Dark"))
        self.assertIn("/* @define-color selected_bg_color #5294e2; */", read(os.path.join(folder, "waybar-colors.css")))
        foot = read(os.path.join(folder, "foot.ini"))
        self.assertIn("[colors]\n# background=383c4a\n", foot)
        self.assertIn("[urgency=critical]\n# border-color=#fc4138\n", read(os.path.join(folder, "mako.conf")))

    def test_starter_changes_nothing_and_passes_check(self):
        self.main("style", "new", "mine", "--from", "dark")
        mine, dark = self.styles()["mine"], self.styles()["dark"]
        self.assertEqual(fl.palette_colors(fl.palette_chain(mine, "waybar")),
                         fl.palette_colors(fl.palette_chain(dark, "waybar")))
        self.assertEqual(self.main("check", "mine")[:2], (0, ""))

    def test_uncommenting_one_line_sets_it(self):
        self.main("style", "new", "mine", "--from", "dark")
        path = os.path.join(self.user_dir, "mine/waybar-colors.css")
        text = read(path).replace("/* @define-color selected_bg_color #5294e2; */",
                                  "@define-color selected_bg_color #b5480c;")
        self.write(path, text)
        self.assertEqual(self.main("check", "mine")[:2], (0, ""))
        colors = fl.palette_colors(fl.palette_chain(self.styles()["mine"], "waybar"))
        self.assertEqual(colors["selected_bg_color"], tuple(int(v, 16) / 255 for v in ("b5", "48", "0c")))

    def test_inherits_the_style_in_use_by_default(self):
        self.set_user_choice("light", "style")
        self.main("style", "new", "mine")
        self.assertEqual(self.styles()["mine"].parent, "light")

    def test_refusals(self):
        self.assertEqual(self.main("style", "new", "dark")[0], 1)
        self.assertIn("exists already", self.main("style", "new", "dark")[2])
        self.assertEqual(self.main("style", "new", "Bad Name")[0], 1)
        self.assertEqual(self.main("style", "new", "mine", "--from", "nothing")[0], 1)
        self.assertFalse(os.path.exists(os.path.join(self.user_dir, "mine")))


class CheckStyleTest(UserStyleTest):

    def check(self, *args):
        status, out, _err = self.main("check", *args)
        return status, out.splitlines()

    def test_good_style_prints_nothing(self):
        self.orange()
        self.assertEqual(self.check("dark-orange"), (0, []))
        self.assertEqual(self.check("dark"), (0, []))

    def test_unknown_style(self):
        self.assertEqual(self.main("check", "nothing")[0], 1)

    def test_waybar_palette_holds_only_colors(self):
        folder = self.user_style("bad", "Name=Bad\nInherits=dark\nWaybar=w.css\n",
                                 w_css="/* fine */\n@define-color fg_color #fff;\n@define-color mystery #123456;\n"
                                       "@define-color bg_color url(/etc/shadow);\n* { color: red; }\n")
        status, lines = self.check("bad")
        path = os.path.join(folder, "w.css")
        self.assertEqual(status, 1)
        self.assertIn(f"{path}:3: error: mystery isn't one of the panel's colors "
                      "(base_color, bg_color, fg_color, selected_bg_color, selected_fg_color)", lines)
        self.assertIn(f"{path}:4: error: url(/etc/shadow) isn't a color (#rrggbb)", lines)
        self.assertIn(f"{path}:5: error: only @define-color lines may be here, not '* {{ color: red; }}'", lines)

    def test_ini_palettes_hold_only_the_keys(self):
        """ADR-006: foot's shell=, mako's on-button-left= or an include= could run anything."""
        folder = self.user_style("bad", "Name=Bad\nInherits=dark\nFoot=f.ini\nMako=m.conf\n",
                                 f_ini="[colors]\nbackground=000000\n[main]\nshell=/bin/evil\ninclude=/tmp/x\n",
                                 m_conf="on-button-left=exec evil\n")
        status, lines = self.check("bad")
        self.assertEqual(status, 1)
        foot, mako = os.path.join(folder, "f.ini"), os.path.join(folder, "m.conf")
        self.assertIn(f"{foot}:4: error: shell in [main] isn't one of the style's keys for foot; only colors "
                      "may be here", lines)
        self.assertIn(f"{foot}:5: error: include= isn't allowed in a style's colors", lines)
        self.assertIn(f"{mako}:1: error: on-button-left isn't one of the style's keys for mako; only colors "
                      "may be here", lines)

    def test_missing_palette_file(self):
        folder = self.user_style("bad", "Name=Bad\nInherits=dark\nFoot=nowhere.ini\n")
        self.assertIn(f"{folder}/style.ini: error: Foot=nowhere.ini: no such file", self.check("bad")[1])

    def test_wallpaper(self):
        self.write("home/outside.png", "")
        folder = self.user_style("bad", "Name=Bad\nInherits=dark\nWallpaper=../../../../outside.png\n")
        self.assertIn(f"{folder}/style.ini: error: Wallpaper=../../../../outside.png is outside the style's folder",
                      self.check("bad")[1])
        self.user_style("bad", "Name=Bad\nInherits=dark\nWallpaper=wall.gif\n", wall_gif="")
        self.assertIn(f"{folder}/style.ini: error: Wallpaper=wall.gif: no PNG or JPEG file there",
                      self.check("bad")[1])
        self.user_style("bad", "Name=Bad\nInherits=dark\nWallpaper=wall.png\n", wall_png="")
        self.assertEqual(self.check("bad"), (0, []))

    def test_packages(self):
        folder = self.user_style("pkg", "Name=Pkg\nInherits=dark\nPackages=papirus-icon-theme;Bad Name\n")
        with mock.patch.object(fl, "package_installed", lambda name: False):
            status, lines = self.check("pkg")
        self.assertEqual(status, 1)
        self.assertIn(f"{folder}/style.ini: warning: package papirus-icon-theme isn't installed "
                      "(sudo apt install papirus-icon-theme)", lines)
        self.assertIn(f"{folder}/style.ini: error: Packages=Bad Name isn't a package name", lines)

    def test_missing_theme_is_a_warning(self):
        folder = self.user_style("nordic", "Name=Nordic\nInherits=dark\nGtkTheme=Nordic\n")
        with mock.patch.object(fl, "theme_installed", lambda kind, name: name != "Nordic"):
            self.assertEqual(self.check("nordic"), (0, [f"{folder}/style.ini: warning: the GTK theme Nordic isn't "
                                                        "installed, so windows use Arc-Dark"]))

    def test_contrast(self):
        folder = self.user_style("grey", "Name=Grey\nInherits=dark\nWaybar=w.css\nFoot=f.ini\n",
                                 w_css="@define-color fg_color #505050;\n@define-color selected_fg_color #6a9fe8;\n",
                                 f_ini="[colors]\nforeground=404040\n")
        status, lines = self.check("grey")
        self.assertEqual(status, 0)
        self.assertEqual(len([line for line in lines if "hard to read" in line]), 4, lines)
        self.assertTrue(any(line.startswith(f"{folder}/w.css: warning: fg_color on bg_color is ") for line in lines))
        self.assertTrue(any(line.startswith(f"{folder}/f.ini: warning: the terminal's foreground") for line in lines))

    def test_panel_text_on_the_panel(self):
        """fg_color on wm_bg, the bar itself (the Seven spike found it untested)."""
        self.write("styles/dark/waybar-colors.css", DARK_WAYBAR + "@define-color wm_bg #2f343f;\n")
        folder = self.user_style("murky", "Name=Murky\nInherits=dark\nWaybar=w.css\n",
                                 w_css="@define-color wm_bg #3a3a3a;\n@define-color fg_color #e0e0e0;\n"
                                       "@define-color bg_color #e0e0e0;\n")
        self.assertIn(f"{folder}/w.css: warning: fg_color on bg_color is 1.0:1, below 4.5:1: hard to read (HIG A11Y-6)",
                      self.check("murky")[1])
        self.user_style("murky", "Name=Murky\nInherits=dark\nWaybar=w.css\n",
                        w_css="@define-color wm_bg #c8c8c8;\n@define-color fg_color #e0e0e0;\n")
        self.assertTrue(any("fg_color on wm_bg is 1.3:1, below 4.5:1" in line for line in self.check("murky")[1]))

    def test_see_through_panel(self):
        """A see-through wm_bg is tested over black and white wallpapers, at the
        alpha the panel draws (its own times PANEL_ALPHA)."""
        self.write("styles/dark/waybar-colors.css", DARK_WAYBAR + "@define-color wm_bg #2f343f;\n")
        self.user_style("frost", "Name=Frost\nInherits=dark\nWaybar=w.css\n",
                        w_css="@define-color wm_bg rgba(255, 255, 255, 0.4);\n@define-color fg_color #ffffff;\n")
        self.assertTrue(any("fg_color on wm_bg is" in line and "over a white wallpaper" in line
                            for line in self.check("frost")[1]))
        self.user_style("frost", "Name=Frost\nInherits=dark\nWaybar=w.css\n",
                        w_css="@define-color wm_bg rgba(14, 42, 76, 0.82);\n@define-color fg_color #ffffff;\n")
        self.assertFalse(any("wm_bg" in line for line in self.check("frost")[1]))

    def test_see_through_colors_are_read(self):
        self.assertEqual(fl.css_color("#abc"), (0xaa / 255, 0xbb / 255, 0xcc / 255, 1.0))
        self.assertEqual(fl.css_color("#ff000080"), (1.0, 0.0, 0.0, 0x80 / 255))
        self.assertEqual(fl.css_color("rgba(255, 0, 0, 0.5)"), (1.0, 0.0, 0.0, 0.5))
        self.assertEqual(fl.css_color("rgb(100%, 0%, 50%)"), (1.0, 0.0, 0.5, 1.0))
        for value in ("@wm_bg", "red", "#12345", "rgba(1, 2)", "alpha(@x, 0.5)"):
            self.assertIsNone(fl.css_color(value), value)
        path = self.write("p.css", "/* @define-color old #000000; */\n@define-color wm_bg rgba(0, 0, 255, 0.5);\n")
        self.assertEqual(fl.palette_rgba(path), {"wm_bg": (0.0, 0.0, 1.0, 0.5)})
        self.assertEqual(fl.palette_colors(path), {"wm_bg": (0.0, 0.0, 1.0)})

    def test_panel_alpha_is_base_css(self):
        base = os.path.join(os.path.dirname(__file__), "..", "usr/share/flickos/layouts/common/base.css")
        self.assertIn(f"alpha(@wm_bg, {fl.PANEL_ALPHA})", read(base))

    def test_broken_inherits(self):
        folder = self.user_style("orphan", "Name=Orphan\nInherits=nothing\n")
        self.assertEqual(self.check("orphan"),
                         (1, [f"{folder}/style.ini: error: Inherits=nothing, which isn't installed"]))


class CheckEverythingTest(UserStyleTest):

    def check(self):
        status, out, _err = self.main("check")
        return status, out.splitlines()

    def test_nothing_of_the_users_prints_nothing(self):
        self.assertEqual(self.check(), (0, []))

    def test_only_users_styles(self):
        self.write("styles/light/foot.ini", "[colors]\nshell=x\n")    # FlickOS's own: not the user's business
        self.orange()
        self.assertEqual(self.check(), (0, []))

    def test_broken_labwc_xml(self):
        path = self.write("home/.config/labwc/rc.xml", "<labwc_config>\n  <keyboard>\n</labwc_config>\n")
        status, lines = self.check()
        self.assertEqual(status, 1)
        self.assertIn(f"{path}:3: error: not well-formed XML (mismatched tag): labwc ignores the whole file and "
                      "uses its own defaults, without FlickOS's keys", lines)

    def test_unknown_section_and_numbers(self):
        path = self.write("home/.config/labwc/rc.xml",
                          "<labwc_config>\n  <frobnicate/>\n  <core><gap>lots</gap></core>\n"
                          "  <theme><cornerRadius>8</cornerRadius><font><size>x</size></font></theme>\n"
                          "</labwc_config>\n")
        status, lines = self.check()
        self.assertEqual(status, 1)
        self.assertEqual(lines[:3], [f"{path}:2: warning: <frobnicate> isn't a labwc setting: labwc ignores it",
                                     f"{path}:3: error: <gap> is 'lots', not a number: labwc reads it as 0",
                                     f"{path}:4: error: <size> is 'x', not a number: labwc reads it as 0"])

    def test_other_labwc_files_only_well_formed(self):
        self.write("home/.config/labwc/menu.xml", "<openbox_menu><menu id='x'><frob/></menu></openbox_menu>\n")
        self.assertEqual(self.check(), (0, []))

    def test_addons(self):
        self.write("home/.config/flickos/addons/clock2/labwc.xml", "<labwc_config><core/></labwc_config>")
        self.write("home/.config/flickos/addons/clock2/waybar.jsonc", "{ broken")
        status, lines = self.check()
        self.assertEqual(status, 1)
        home = self.path("home/.config/flickos/addons")
        self.assertTrue(any(line.startswith(f"{home}: warning: ") and "<core> left out" in line for line in lines),
                        lines)
        self.assertTrue(any(line.startswith(f"{home}/clock2/waybar.jsonc: error: ") for line in lines), lines)

    def test_includes(self):
        foot = self.write("home/.config/foot/foot.ini", "include=/nowhere/foot.ini\ninclude=relative.ini\n")
        mako = self.write("home/.config/mako/config", "include=~/nowhere.conf\n")
        lines = self.check()[1]
        self.assertIn(f"{foot}:1: warning: include=/nowhere/foot.ini: no such file", lines)
        self.assertIn(f"{foot}:2: error: include=relative.ini: foot takes only an absolute path or one starting "
                      "with ~/", lines)
        self.assertIn(f"{mako}:1: error: include=~/nowhere.conf: no such file, and mako doesn't start without it: "
                      "no notifications", lines)

    def test_doctor_warnings_come_last(self):
        self.write("home/.config/labwc/rc.xml", "<labwc_config/>\n")
        lines = self.check()[1]
        self.assertTrue(lines[-1].startswith("warning: ") and "rc.xml replaces FlickOS's" in lines[-1], lines)


class StyleSetRefusesTest(UserStyleTest):

    def setUp(self):
        super().setUp()
        self.make_layout("flickos", order=10)

    def test_style_with_errors_is_refused(self):
        self.user_style("bad", "Name=Bad\nInherits=dark\nFoot=f.ini\n", f_ini="[main]\nshell=/bin/evil\n")
        status, _out, err = self.main("style", "set", "bad")
        self.assertEqual(status, 1)
        self.assertIn("shell in [main] isn't one of the style's keys", err)
        self.assertIn("style bad not applied: it has errors (flickos-layout check bad)", err)
        self.assertFalse(os.path.exists(self.path("home/.config/flickos/style")))
        self.assertEqual(self.main("set", "flickos", "--style", "bad")[0], 1)

    def test_broken_style_is_refused_with_the_reason(self):
        self.user_style("orphan", "Name=Orphan\nInherits=nothing\n")
        status, _out, err = self.main("style", "set", "orphan")
        self.assertEqual(status, 1)
        self.assertIn("Inherits=nothing, which isn't installed", err)

    def test_good_users_style_applies(self):
        self.orange()
        self.assertEqual(self.main("style", "set", "dark-orange")[0], 0)
        self.assertEqual(read(self.path("home/.config/flickos/style")), "dark-orange\n")
        self.assertEqual(self.main("style", "current")[1], "dark-orange\n")
        self.assertEqual(self.main("style", "set", "default")[0], 0)
        self.assertEqual(self.main("style", "current")[1], "dark\n")


class ChooserTest(UserStyleTest):
    """Step 1b: users' styles in the chooser."""

    def test_users_style_says_so(self):
        self.orange()
        found = self.styles()
        self.assertEqual(fl.item_comment(found["dark-orange"]), "The dark style · Yours")
        self.assertEqual(fl.item_comment(found["dark"]), "The dark style")

    def test_fuzzel_list(self):
        self.orange()
        with mock.patch.object(fl.subprocess, "run") as run:
            run.return_value.stdout = ""
            fl.fuzzel_menu("Style", self.styles().values(), "dark")
        lines = run.call_args.kwargs["input"].splitlines()
        self.assertEqual([line.split("\0")[0] for line in lines],
                         ["Dark (current): The dark style", "Light: The light style",
                          "Dark Orange: The dark style · Yours"])


class StateDefaultTest(UserStyleTest):
    """Step 1b: state names the defaults, for Settings' Back to FlickOS's Look."""

    def test_defaults(self):
        self.orange()
        self.set_user_choice("dark-orange", "style")
        state = json.loads(self.main("state")[1])
        self.assertEqual((state["style"]["current"], state["style"]["default"]), ("dark-orange", "dark"))
        self.assertEqual(state["layout"]["default"], "plain")   # the built-in default isn't installed here

    def test_system_default(self):
        self.write("etc/xdg/flickos/layouts.conf", "[Defaults]\nStyle=light\n")
        self.assertEqual(json.loads(self.main("state")[1])["style"]["default"], "light")
