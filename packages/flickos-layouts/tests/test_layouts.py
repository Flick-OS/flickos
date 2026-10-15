"""Tests for the shipped layouts and panel generation. Run: python3 -m unittest discover -s tests"""

import configparser
import contextlib
import io
import json
import os
import re
import shlex
import shutil
import unittest
from unittest import mock

from test_engine import PACKAGE, EngineTest, fl, read

LAYOUTS = os.path.join(PACKAGE, "usr/share/flickos/layouts")
STYLES = os.path.join(PACKAGE, "usr/share/flickos/styles")
EXPECTED = ["redmond", "cupertino", "traditional"]
BAR_MODULE_KEYS = ("modules-left", "modules-center", "modules-right")
LAUNCHER = "custom/launcher"
TASKBAR = "wlr/taskbar"
SHOW_DESKTOP = "custom/desktop"
RECORDING = "custom/recording"


def shipped_layouts():
    with mock.patch.object(fl, "layout_dirs", lambda users=None: [LAYOUTS]), \
            contextlib.redirect_stderr(io.StringIO()) as err:
        found = fl.layouts()
    return found, err.getvalue()


def bar_modules(bar):
    return [m for key in BAR_MODULE_KEYS for m in bar.get(key, [])]


def palette_names():
    """Color names defined by every style's waybar palette."""
    palettes = [os.path.join(STYLES, name, "waybar-colors.css") for name in sorted(os.listdir(STYLES))]
    return set.intersection(*(set(re.findall(r"@define-color\s+([\w-]+)", read(p))) for p in palettes))


class JsoncTest(unittest.TestCase):

    def test_comments_removed_outside_strings(self):
        text = '{\n  // comment "x"\n  "url": "http://a//b", /* block\n */ "q": "say \\"//hi\\" /*no*/"\n}\n'
        self.assertEqual(json.loads(fl.strip_jsonc(text)), {"url": "http://a//b", "q": 'say "//hi" /*no*/'})

    def test_unterminated_block_comment(self):
        with self.assertRaises(ValueError):
            fl.strip_jsonc("{} /* open")


class ShippedLayoutsTest(unittest.TestCase):

    def setUp(self):
        self.layouts, self.warnings = shipped_layouts()

    def test_expected_layouts_in_order_without_warnings(self):
        self.assertEqual(list(self.layouts), EXPECTED)
        self.assertEqual(self.warnings, "")

    def test_default_layout(self):
        self.assertEqual(fl.DEFAULT_LAYOUT, "redmond")
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(PACKAGE, "etc/xdg/flickos/layouts.conf"))
        self.assertEqual(ini["Defaults"]["Layout"], fl.DEFAULT_LAYOUT)

    def test_default_clicks(self):
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(PACKAGE, "etc/xdg/flickos/layouts.conf"))
        self.assertEqual(ini["Defaults"]["Clicks"], fl.DEFAULT_CLICKS)
        self.assertIn(fl.DEFAULT_CLICKS, fl.CLICKS)
        for clicks in fl.CLICKS.values():
            self.assertTrue(fl.LAYOUT_ID.match(clicks.id), clicks.id)
            self.assertIn(clicks.left, fl.CLICK_ACTIONS)
            self.assertIn(clicks.right, fl.CLICK_ACTIONS)

    def test_default_launcher(self):
        """The start menu is the default apps button; the app launcher when
        flickos-menu isn't installed."""
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(PACKAGE, "etc/xdg/flickos/layouts.conf"))
        self.assertEqual(ini["Defaults"]["Launcher"], fl.DEFAULT_LAUNCHER)
        self.assertEqual(fl.DEFAULT_LAUNCHER, "menu")
        self.assertEqual(fl.FALLBACK_LAUNCHER, "fuzzel")

    def test_default_menu_style(self):
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(PACKAGE, "etc/xdg/flickos/layouts.conf"))
        self.assertEqual(ini["Defaults"]["MenuStyle"], fl.DEFAULT_MENU_STYLE_CHOICE)
        self.assertEqual(fl.DEFAULT_MENU_STYLE_CHOICE, fl.FOLLOW_LAYOUT)

    def test_start_menu_corner_matches_the_apps_button(self):
        """Every layout has a start menu corner, on the side of the bar with the
        apps button (a bottom bar opens it bottom-left, a top bar top-left)."""
        for layout in self.layouts.values():
            with self.subTest(layout=layout.id):
                bar = next(b for b in fl.load_bars(layout) if LAUNCHER in bar_modules(b))
                self.assertIn(LAUNCHER, bar.get("modules-left", []))
                self.assertEqual(layout.menu, f"{bar.get('position', 'top')}-left")

    def test_default_quick_settings(self):
        """Quick Settings is off by default (HIG INT-9)."""
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(PACKAGE, "etc/xdg/flickos/layouts.conf"))
        self.assertEqual(ini["Defaults"]["QuickSettings"], fl.DEFAULT_QUICK_SETTINGS)
        self.assertEqual(fl.DEFAULT_QUICK_SETTINGS, "off")

    def test_quick_settings_corner_matches_the_status_icons(self):
        """Every layout has a Quick Settings corner, at the right end of the
        bar with the volume and battery icons."""
        for layout in self.layouts.values():
            with self.subTest(layout=layout.id):
                bar = next(b for b in fl.load_bars(layout) if "wireplumber" in bar_modules(b))
                for module in fl.QUICK_MODULES:
                    self.assertIn(module, bar.get("modules-right", []))
                self.assertEqual(layout.quick, f"{bar.get('position', 'top')}-right")

    def test_start_menu_styles(self):
        """Each layout has its own kind of start menu."""
        self.assertEqual({layout.id: layout.menu_style for layout in self.layouts.values()},
                         {"redmond": "classic", "traditional": "categories", "cupertino": "grid"})
        self.assertEqual(self.warnings, "")

    def test_layouts_show_the_style_wallpaper(self):
        """The layouts' own photos (until 1.37) stay a choice in waypaper, at
        the paths it has always shown them."""
        for layout in self.layouts.values():
            self.assertIsNone(layout.wallpaper, layout.id)
            path = os.path.join(PACKAGE, f"usr/share/backgrounds/flickos/{layout.id}.jpg")
            with open(path, "rb") as f:
                self.assertEqual(f.read(3), b"\xff\xd8\xff", f"{path}: not a JPEG")

    def test_titlebar_layouts_valid(self):
        for layout_id in EXPECTED:
            ini = configparser.ConfigParser(interpolation=None)
            ini.read(os.path.join(LAYOUTS, layout_id, "layout.ini"))
            value = ini["Layout"].get("TitlebarLayout")
            if value is not None:
                self.assertTrue(fl.valid_titlebar_layout(value), layout_id)
        self.assertEqual(self.layouts["cupertino"].titlebar_layout, "close,iconify,max:")
        self.assertIsNone(self.layouts["redmond"].titlebar_layout)

    def test_bars_parse_and_includes_exist(self):
        for layout in self.layouts.values():
            with self.subTest(layout=layout.id):
                bars = fl.load_bars(layout)
                for bar in bars:
                    for path in bar.get("include", []):
                        self.assertTrue(os.path.isabs(path) and os.path.isfile(path), path)
                self.assertEqual(len({bar.get("name") for bar in bars}), len(bars), "bar names must differ")

    def test_one_tray_and_one_launcher(self):
        for layout in self.layouts.values():
            modules = [m for bar in fl.load_bars(layout) for m in bar_modules(bar)]
            with self.subTest(layout=layout.id):
                self.assertEqual(modules.count("tray"), 1)
                self.assertEqual(modules.count(LAUNCHER), 1)

    def test_show_desktop_is_at_the_right_edge(self):
        """Last in modules-right of one bar: the pointer pushed into the
        corner hits it."""
        for layout in self.layouts.values():
            with self.subTest(layout=layout.id):
                bars = fl.load_bars(layout)
                self.assertEqual(sum(bar_modules(bar).count(SHOW_DESKTOP) for bar in bars), 1)
                self.assertIn(SHOW_DESKTOP, [bar.get("modules-right", [None])[-1] for bar in bars])
        modules = fl.load_jsonc(os.path.join(LAYOUTS, "common", "modules.jsonc"))
        self.assertEqual(modules[SHOW_DESKTOP]["on-click"], "flick-tiler show-desktop")

    def test_window_lists_show_icons_only(self):
        """waybar 0.12 doesn't ellipsize taskbar titles, so a window list with
        titles grows with every window: it pushes the modules after it off the
        bar, or runs past the bar's edge. Titles are only in the tooltip."""
        for layout in self.layouts.values():
            for bar in fl.load_bars(layout):
                if TASKBAR not in bar_modules(bar):
                    continue
                settings = {}
                for path in bar.get("include", []):
                    settings.update(fl.load_jsonc(path).get(TASKBAR, {}))
                settings.update(bar.get(TASKBAR, {}))
                with self.subTest(layout=layout.id, bar=bar.get("name")):
                    self.assertNotRegex(settings.get("format", "{icon}"), r"\{(title|name)\b")

    def test_recording_next_to_the_clock(self):
        """flickos-screenshot's recording button is in every layout, once, in
        the bar that holds the clock, and hidden while nothing records."""
        for layout in self.layouts.values():
            with self.subTest(layout=layout.id):
                bars = fl.load_bars(layout)
                self.assertEqual(sum(bar_modules(bar).count(RECORDING) for bar in bars), 1)
                self.assertIn(RECORDING, next(bar_modules(bar) for bar in bars if "clock" in bar_modules(bar)))
        modules = fl.load_jsonc(os.path.join(LAYOUTS, "common", "modules.jsonc"))
        recording = modules[RECORDING]
        self.assertEqual(recording["exec"], 'cat "$XDG_RUNTIME_DIR/flickos/screenshot/panel.json" 2>/dev/null')
        self.assertEqual(recording["on-click"], "flickos-screenshot stop")
        self.assertEqual(recording["signal"], 10)       # flickos-screenshot's PANEL_SIGNAL
        others = [modules[name]["signal"] for name in modules if name != RECORDING and "signal" in modules[name]]
        self.assertNotIn(10, others)

    def test_referenced_modules_defined(self):
        for layout in self.layouts.values():
            for bar in fl.load_bars(layout):
                defined = set(bar)
                for path in bar.get("include", []):
                    defined |= set(fl.load_jsonc(path))
                for module in bar_modules(bar):
                    with self.subTest(layout=layout.id, bar=bar.get("name"), module=module):
                        self.assertTrue(module in (fl.PINNED_MODULE, fl.DESKTOPS_MODULE) or module in defined)

    def test_pinned_only_where_a_bar_or_dock_shows_them(self):
        for layout in self.layouts.values():
            uses = any(fl.PINNED_MODULE in bar_modules(bar) for bar in fl.load_bars(layout))
            uses |= bool(layout.dock and fl.DOCK_PINS.search(read(layout.dock)))
            self.assertEqual(uses, bool(layout.pinned), layout.id)

    def test_docks(self):
        docks = [layout for layout in self.layouts.values() if layout.dock]
        self.assertEqual([layout.id for layout in docks], ["cupertino", "traditional"])
        for layout in docks:
            with self.subTest(layout=layout.id):
                config = read(layout.dock)
                self.assertTrue(config.startswith("#Api2\n"))
                self.assertNotRegex(config, r"(?m)^#CSS")
                self.assertTrue(os.path.isfile(layout.dock_style))

    def test_desktops_only_with_a_switcher(self):
        """More than one desktop only where something shows them: a pager in
        the layout's sfwbar bar, or desktop buttons (flickos/desktops) in a
        waybar bar."""
        for layout in self.layouts.values():
            with self.subTest(layout=layout.id):
                pager = bool(layout.dock and re.search(r"(?m)^\s*pager\b", read(layout.dock)))
                buttons = any(fl.DESKTOPS_MODULE in bar_modules(bar) for bar in fl.load_bars(layout))
                self.assertEqual(layout.desktops > 1, pager or buttons)
        self.assertEqual(self.layouts["traditional"].desktops, 4)

    def css_files(self):
        files = [os.path.join(LAYOUTS, "common/base.css")]
        files += [layout.style for layout in self.layouts.values()]
        return files + [layout.dock_style for layout in self.layouts.values() if layout.dock]

    def test_css_imports_exist(self):
        for path in self.css_files():
            for target in re.findall(r'@import\s+url\("([^"]+)"\)', read(path)):
                self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(path), target)), f"{path}: {target}")

    def test_css_uses_only_palette_color_names(self):
        names = palette_names()
        self.assertIn("wm_bg", names)
        for path in self.css_files():
            text = re.sub(r"/\*.*?\*/", "", read(path), flags=re.S)
            declarations = " ".join(re.findall(r"\{([^}]*)\}", text))
            with self.subTest(css=os.path.relpath(path, LAYOUTS)):
                self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(", declarations), [])
                used = set(re.findall(r"@([\w-]+)", declarations))
                self.assertEqual(used - names, set())


class DockTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.data = self.path("share")
        os.environ["XDG_DATA_DIRS"] = self.data
        os.environ["XDG_DATA_HOME"] = self.path("home/.local/share")
        self.theme("hicolor", {"48x48/apps": "Size=48\nType=Threshold"})
        self.theme("Adwaita", {"scalable/apps": "Size=16\nMinSize=8\nMaxSize=512\nType=Scalable"},
                   inherits="hicolor")
        self.theme("Numix", {"16/apps": "Size=16", "48/apps": "Size=48"}, inherits="Adwaita,hicolor")
        self.theme("Circle", {"48/apps": "Size=48\nType=Scalable\nMinSize=8\nMaxSize=512",
                              "48@2x/apps": "Size=48\nScale=2\nType=Scalable"}, inherits="Numix")

    def theme(self, name, directories, inherits=None):
        lines = ["[Icon Theme]", f"Name={name}", "Directories=" + ",".join(directories)]
        if inherits:
            lines.append(f"Inherits={inherits}")
        for directory, keys in directories.items():
            lines += ["", f"[{directory}]", keys]
        self.write(f"share/icons/{name}/index.theme", "\n".join(lines) + "\n")

    def icon(self, theme, directory, name):
        return self.write(f"share/icons/{theme}/{directory}/{name}", "<svg/>")

    def app(self, desktop_id, extra="", name=None, icon=None):
        lines = ["[Desktop Entry]", "Type=Application", f"Name={name or desktop_id}", "Exec=true %U"]
        if icon:
            lines.append(f"Icon={icon}")
        text = "\n".join(lines) + "\n" + extra + "\n[Desktop Action new]\nName=New\nIcon=wrong\n"
        return self.write(f"share/applications/{desktop_id}", text)

    def test_icon_theme_order(self):
        finder = fl.IconFinder("Circle")
        self.assertEqual(finder.themes, ["Circle", "Numix", "Adwaita", "hicolor"])
        self.assertEqual(fl.IconFinder("Missing").themes, ["Numix", "Adwaita", "hicolor"])

    def test_icon_lookup(self):
        numix_big = self.icon("Numix", "48/apps", "web.svg")
        self.icon("Numix", "16/apps", "web.svg")
        self.icon("Circle", "48@2x/apps", "web.svg")
        circle = self.icon("Circle", "48/apps", "term.svg")
        hicolor = self.icon("hicolor", "48x48/apps", "only-hicolor.png")
        adwaita = self.icon("Adwaita", "scalable/apps", "only-hicolor.svg")
        pixmap = self.write("share/pixmaps/old.xpm", "")
        finder = fl.IconFinder("Circle")
        self.assertEqual(finder.find("web"), numix_big)  # the @2x copy is skipped
        self.assertEqual(finder.find("term.svg"), circle)
        self.assertEqual(finder.find("only-hicolor"), adwaita)  # hicolor is searched last
        os.remove(adwaita)
        self.assertEqual(finder.find("only-hicolor"), hicolor)
        self.assertEqual(finder.find("old"), pixmap)
        self.assertEqual(finder.find(pixmap), pixmap)
        self.assertIsNone(finder.find("/nonexistent/icon.png"))
        self.assertIsNone(finder.find("nothing"))

    def test_pinned_apps_skip_missing_and_hidden(self):
        self.icon("Circle", "48/apps", "web.svg")
        self.app("web.desktop", name="Web & <Browser>", icon="web")
        self.app("hidden.desktop", "Hidden=true")
        self.app("tryexec.desktop", "TryExec=/nonexistent/program")
        self.app("link.desktop", "Type=Link")
        self.app("noicon.desktop")
        self.write("home/.local/share/applications/Org.Mine.desktop", "[Desktop Entry]\nName=Mine\n")
        self.write("share/applications/broken.desktop", "not an ini file\n")
        ids = ["web.desktop", "missing.desktop", "hidden.desktop", "tryexec.desktop", "link.desktop",
               "broken.desktop", "noicon.desktop", "Org.Mine.desktop"]
        with self.quiet():
            apps = fl.pinned_apps(ids, fl.IconFinder("Circle"))
        self.assertEqual([a.desktop_id for a in apps], ["web.desktop", "noicon.desktop", "Org.Mine.desktop"])
        self.assertEqual(apps[0].icon, self.path("share/icons/Circle/48/apps/web.svg"))
        self.assertIsNone(apps[1].icon)
        self.assertEqual([a.css_class for a in apps], ["app-web", "app-noicon", "app-org-mine"])
        self.assertEqual(apps[2].path, self.path("home/.local/share/applications/Org.Mine.desktop"))

    def test_css_classes_unique(self):
        self.app("a.b.desktop")
        self.app("a-b.desktop")
        with self.quiet():
            apps = fl.pinned_apps(["a.b.desktop", "a-b.desktop"], fl.IconFinder())
        self.assertEqual([a.css_class for a in apps], ["app-a-b", "app-a-b-2"])

    def test_icon_theme_asked_only_when_needed(self):
        with mock.patch.object(fl, "current_icon_theme", return_value="Circle") as theme:
            self.assertEqual(fl.pinned_apps(["missing.desktop"]), [])
            theme.assert_not_called()
            self.app("x.desktop")
            fl.pinned_apps(["x.desktop"])
            theme.assert_called_once()

    def test_current_icon_theme(self):
        self.assertIsNone(fl.current_icon_theme())
        self.gsettings["icon-theme"] = "Numix-Circle"
        self.assertEqual(fl.current_icon_theme(), "Numix-Circle")

    def make_dock_layout(self):
        self.write("layouts/dock/layout.ini", "[Layout]\nName=Dock\nWaybar=waybar.jsonc\nStyle=style.css\n"
                   "Pinned=web.desktop; missing.desktop ;o'dd.desktop\n")
        self.write("layouts/common/modules.jsonc", '{"clock": {}}\n')
        self.write("layouts/dock/style.css", "\n")
        self.write("layouts/dock/waybar.jsonc", """// comment
[{"name": "top", "include": "../common/modules.jsonc", "modules-left": ["clock"]},
 {"name": "dock", "modules-center": ["flickos/pinned", "custom/sep"], "custom/sep": {"format": " "}}]
""")
        self.icon("Circle", "48/apps", "web.svg")
        self.app("web.desktop", name="Web {x} & co", icon="web")
        self.app("o'dd.desktop", name="Odd", icon="nothing")

    def test_generated_panel_files(self):
        self.make_dock_layout()
        with mock.patch.object(fl, "current_icon_theme", return_value="Circle"), self.quiet():
            command = fl.update_waybar(self.root, self.layout("dock"), self.style())
        config, style = f"{self.root}/waybar/config.jsonc", f"{self.root}/waybar/style.css"
        self.assertEqual(command, ["waybar", "-c", config, "-s", style])

        top, dock = fl.load_jsonc(config)
        self.assertEqual(top["include"], [os.path.join(self.layouts_dir, "common/modules.jsonc")])
        self.assertNotIn("custom/pin#app-web", top)
        self.assertEqual(dock["modules-center"], ["custom/pin#app-web", "custom/pin#app-o-dd", "custom/sep"])
        web = dock["custom/pin#app-web"]
        self.assertEqual(web["tooltip-format"], "Web {{x}} &amp; co")
        self.assertEqual(web["on-click"], "gio launch " + self.path("share/applications/web.desktop"))
        self.assertEqual(dock["custom/pin#app-o-dd"]["on-click"],
                         "gio launch '" + self.path("share/applications/o'\"'\"'dd.desktop") + "'")

        css = read(style)
        imports = re.findall(r'@import url\("([^"]+)"\);', css)
        self.assertEqual(imports, [self.style().waybar, os.path.join(self.layouts_dir, "dock/style.css")])
        self.assertIn(f'#custom-pin.app-web {{ background-image: url("{self.path("share/icons/Circle/48/apps/web.svg")}"); }}', css)
        self.assertNotIn("app-o-dd", css)  # no icon found

    def test_no_pinned_apps_leaves_placeholder_out(self):
        self.make_dock_layout()
        shutil.rmtree(self.path("share/applications"))
        with mock.patch.object(fl, "current_icon_theme", return_value=None), self.quiet():
            fl.update_waybar(self.root, self.layout("dock"), self.style())
        _, dock = fl.load_jsonc(f"{self.root}/waybar/config.jsonc")
        self.assertEqual(dock["modules-center"], ["custom/sep"])

    def test_broken_layout_raises(self):
        self.make_dock_layout()
        self.write("layouts/dock/waybar.jsonc", "[{]")
        with self.assertRaises(fl.LayoutError):
            fl.update_waybar(self.root, self.layout("dock"), self.style())
        self.write("layouts/dock/waybar.jsonc", '{"include": "nope.jsonc"}')
        with self.assertRaises(fl.LayoutError):
            fl.update_waybar(self.root, self.layout("dock"), self.style())
        self.write("layouts/dock/waybar.jsonc", '[1]')
        with self.assertRaises(fl.LayoutError):
            fl.update_waybar(self.root, self.layout("dock"), self.style())

    def test_missing_palette_raises(self):
        self.make_dock_layout()
        os.remove(self.style().waybar)
        with self.assertRaises(fl.LayoutError):
            fl.update_waybar(self.root, self.layout("dock"), self.style())

    def make_sfwbar_layout(self):
        self.write("layouts/sf/layout.ini", "[Layout]\nName=Sf\nWaybar=waybar.jsonc\nStyle=style.css\n"
                   "Dock=dock.config\nDockStyle=dock.css\n"
                   'Pinned=web.desktop;missing.desktop;hidden.desktop;q"x.desktop\n')
        self.write("layouts/sf/waybar.jsonc", "{}\n")
        self.write("layouts/sf/style.css", "\n")
        self.write("layouts/sf/dock.config",
                   '#api2\n# comment\nbar {\n  taskbar {\n    pins = "flickos/pinned";\n    icons = true\n  }\n}\n')
        self.write("layouts/sf/dock.css", "grid#dock { color: @fg_color; }\n")
        self.app("web.desktop")
        self.app("hidden.desktop", "Hidden=true")
        self.app('q"x.desktop')

    def test_generated_dock(self):
        self.make_sfwbar_layout()
        with self.quiet():
            command = fl.update_dock(self.root, self.layout("sf"), self.style())
        target = f"{self.root}/dock/sfwbar.config"
        self.assertEqual(command, ["sfwbar", "-f", target])
        config, css = read(target).split("\n#CSS\n")
        self.assertTrue(config.startswith("#Api2\n# Generated by flickos-layout"))
        self.assertEqual(config.lower().count("#api2"), 1)
        self.assertIn('\n    pins = "web", "q\\"x"\n    icons = true\n', config)
        self.assertLess(css.index("@define-color fg_color"), css.index("grid#dock"))

    def test_dock_without_installed_pins_leaves_pins_out(self):
        self.make_sfwbar_layout()
        shutil.rmtree(self.path("share/applications"))
        with self.quiet():
            fl.update_dock(self.root, self.layout("sf"), self.style())
        config = read(f"{self.root}/dock/sfwbar.config")
        self.assertNotIn("pins", config)
        self.assertIn("    icons = true", config)

    def test_layout_without_dock_removes_it(self):
        self.make_sfwbar_layout()
        self.make_layout("plain")
        with self.quiet():
            fl.update_dock(self.root, self.layout("sf"), self.style())
            self.assertIsNone(fl.update_dock(self.root, self.layout("plain"), self.style()))
        self.assertFalse(os.path.exists(f"{self.root}/dock/sfwbar.config"))

    def test_broken_dock_raises(self):
        self.make_sfwbar_layout()
        self.write("layouts/sf/dock.config", "#Api2\nbar { }\n#CSS\n* { }\n")
        with self.assertRaises(fl.LayoutError):
            fl.update_dock(self.root, self.layout("sf"), self.style())
        self.write("layouts/sf/dock.config", "#Api2\nbar { }\n")
        os.remove(self.path("layouts/sf/dock.css"))
        with self.assertRaises(fl.LayoutError):
            fl.update_dock(self.root, self.layout("sf"), self.style())

    def dock_launcher(self, **options):
        """The command the generated dock's Exec("flickos/launcher") runs,
        split as sfwbar splits it (g_shell_parse_argv, no shell)."""
        self.write("layouts/sf/dock.config",
                   '#Api2\nbar ":end" {\n  button {\n    action[LeftClick] = Exec( "flickos/launcher" )\n  }\n}\n')
        with self.quiet():
            fl.update_dock(self.root, self.layout("sf"), self.style(), **options)
        config = read(f"{self.root}/dock/sfwbar.config")
        self.assertNotIn(fl.DOCK_LAUNCHER, config)
        found = re.search(r'action\[LeftClick\] = Exec\("((?:[^"\\]|\\.)*)"\)\n', config)
        self.assertIsNotNone(found, config)
        return shlex.split(re.sub(r"\\(.)", r"\1", found.group(1)))

    def test_dock_launcher_opens_the_apps_buttons_program(self):
        self.make_sfwbar_layout()
        self.assertEqual(self.dock_launcher(menu=True), ["sh", "-c", fl.MENU_TOGGLE])
        fuzzel = self.dock_launcher()
        modules = fl.load_jsonc(os.path.join(LAYOUTS, "common/modules.jsonc"))
        self.assertEqual(fuzzel, ["sh", "-c", modules["custom/launcher"]["on-click"]])
        self.assertEqual(self.dock_launcher(menu=False), fuzzel)

    def test_dock_command_follows_the_start_menu(self):
        """dock_command opens the start menu while prepare wrote MENU_ANCHOR."""
        self.make_sfwbar_layout()
        self.write("layouts/sf/dock.config", '#Api2\nbar {\n  button { action = Exec("flickos/launcher") }\n}\n')
        target = f"{self.root}/dock/sfwbar.config"
        with self.quiet():
            fl.dock_command(self.layout("sf"), self.style())
            self.assertNotIn("flickos-menu", read(target))
            os.makedirs(os.path.dirname(os.path.join(self.root, fl.MENU_ANCHOR)), exist_ok=True)
            with open(os.path.join(self.root, fl.MENU_ANCHOR), "w", encoding="utf-8") as f:
                f.write("top-left\n")
            fl.dock_command(self.layout("sf"), self.style())
        self.assertIn(fl.MENU_TOGGLE.replace('"', '\\"'), read(target))

    def test_dock_without_launcher_unchanged(self):
        self.make_sfwbar_layout()
        with self.quiet():
            fl.update_dock(self.root, self.layout("sf"), self.style(), menu=True)
        self.assertNotIn("Exec", read(f"{self.root}/dock/sfwbar.config"))

    def test_dock_needs_a_style(self):
        self.write("layouts/nostyle/layout.ini", "[Layout]\nName=N\nWaybar=w\nStyle=s\nDock=dock.config\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertNotIn("nostyle", fl.layouts())
        self.assertIn("DockStyle= is missing", err.getvalue())


class ShippedPanelTest(EngineTest):
    """Generate the real layouts' panels from the package tree."""

    def test_every_shipped_layout_generates(self):
        with mock.patch.object(fl, "LAYOUTS_DIR", LAYOUTS), mock.patch.object(fl, "STYLES_DIR", STYLES), \
                mock.patch.object(fl, "current_icon_theme", return_value=None), self.quiet():
            for layout in fl.layouts().values():
                fl.update_waybar(self.root, layout, self.style())
                bars = fl.load_jsonc(f"{self.root}/waybar/config.jsonc")
                self.assertTrue(all(fl.PINNED_MODULE not in bar_modules(bar) for bar in bars), layout.id)
                if fl.update_dock(self.root, layout, self.style()):
                    self.assertIsNone(fl.DOCK_PINS.search(read(f"{self.root}/dock/sfwbar.config")), layout.id)

    def test_phone_button_only_while_on(self):
        """The phone button comes just before the tiling button in every
        layout, and only with phone (HIG INT-9: nothing points at it while off)."""
        with mock.patch.object(fl, "LAYOUTS_DIR", LAYOUTS), mock.patch.object(fl, "STYLES_DIR", STYLES), \
                mock.patch.object(fl, "current_icon_theme", return_value=None), self.quiet():
            for layout in fl.layouts().values():
                for phone in (False, True):
                    fl.update_waybar(self.root, layout, self.style(), phone=phone)
                    bars = fl.load_jsonc(f"{self.root}/waybar/config.jsonc")
                    modules = [m for bar in bars for m in bar_modules(bar)]
                    self.assertEqual(modules.count(fl.PHONE_MODULE), int(phone), layout.id)
                    if phone:
                        self.assertEqual(modules[modules.index(fl.PHONE_MODULE) + 1], "custom/tiler", layout.id)

    def test_phone_popup_click_in_every_layout(self):
        """The phone button opens the popup while it is on, in every layout,
        and keeps the fuzzel menu while it isn't (HIG INT-9)."""
        with mock.patch.object(fl, "LAYOUTS_DIR", LAYOUTS), mock.patch.object(fl, "STYLES_DIR", STYLES), \
                mock.patch.object(fl, "current_icon_theme", return_value=None), self.quiet():
            for layout in fl.layouts().values():
                self.assertIn(layout.quick, fl.QUICK_ANCHORS, layout.id)
                fl.update_waybar(self.root, layout, self.style(), phone=True, popup=True)
                bars = fl.load_jsonc(f"{self.root}/waybar/config.jsonc")
                phone = next(bar[fl.PHONE_MODULE] for bar in bars if isinstance(bar.get(fl.PHONE_MODULE), dict))
                self.assertEqual(phone["on-click"], fl.PHONE_TOGGLE, layout.id)
                self.assertEqual(phone["on-click-right"], fl.PHONE_TOGGLE, layout.id)
                self.assertEqual(phone["exec"], "flickos-phone status --panel", layout.id)
                fl.update_waybar(self.root, layout, self.style(), phone=True, popup=False)
                text = read(f"{self.root}/waybar/config.jsonc")
                self.assertNotIn(fl.PHONE_TOGGLE, text, layout.id)
                self.assertIn(fl.PHONE_MODULE, text, layout.id)

    def test_quick_settings_only_while_on(self):
        """With quick, every layout's volume and battery icons are one group
        where they were, and each opens Quick Settings; without, the panel
        is as it was (HIG INT-9)."""
        with mock.patch.object(fl, "LAYOUTS_DIR", LAYOUTS), mock.patch.object(fl, "STYLES_DIR", STYLES), \
                mock.patch.object(fl, "current_icon_theme", return_value=None), self.quiet():
            for layout in fl.layouts().values():
                with self.subTest(layout=layout.id):
                    fl.update_waybar(self.root, layout, self.style())
                    before = read(f"{self.root}/waybar/config.jsonc")
                    self.assertNotIn(fl.QUICK_GROUP, before)
                    self.assertNotIn("flickos-menu quick", before)
                    original = next(b for b in fl.load_bars(layout) if "wireplumber" in bar_modules(b))
                    fl.update_waybar(self.root, layout, self.style(), quick=True)
                    bars = fl.load_jsonc(f"{self.root}/waybar/config.jsonc")
                    bar = next(b for b in bars if fl.QUICK_GROUP in bar_modules(b))
                    right = original["modules-right"]
                    self.assertEqual(bar["modules-right"],
                                     right[:right.index("wireplumber")] + [fl.QUICK_GROUP]
                                     + right[right.index("battery") + 1:])
                    self.assertEqual(bar[fl.QUICK_GROUP], {"orientation": "horizontal",
                                                           "modules": ["wireplumber", "battery"]})
                    self.assertEqual(bar["wireplumber"]["on-click"], fl.QUICK_TOGGLE)
                    self.assertEqual(bar["wireplumber"]["on-click-right"], fl.QUICK_MIXER)
                    self.assertEqual(bar["battery"]["on-click"], fl.QUICK_TOGGLE)
                    # The included settings' tooltips, with what a click does.
                    self.assertTrue(bar["wireplumber"]["tooltip-format"].startswith("Volume {volume}%\n"))
                    self.assertIn("Super+A", bar["battery"]["tooltip-format"])

    def test_every_layout_has_room_for_addons(self):
        """An add-on's button goes after the phone's, before the tiling button."""
        with mock.patch.object(fl, "LAYOUTS_DIR", LAYOUTS), mock.patch.object(fl, "STYLES_DIR", STYLES), \
                mock.patch.object(fl, "current_icon_theme", return_value=None), self.quiet():
            for layout in fl.layouts().values():
                bars = fl.load_bars(layout)
                fl.use_phone(bars)
                self.assertIsNotNone(fl.insert_module(bars, "custom/addon"), layout.id)
                modules = [m for bar in bars for m in bar_modules(bar)]
                i = modules.index("custom/addon")
                self.assertEqual(modules[i - 1:i + 2], [fl.PHONE_MODULE, "custom/addon", "custom/tiler"], layout.id)

    def test_addons_cant_replace_desktop_modules(self):
        """An add-on's custom/tiler or custom/phone is left out in every layout."""
        folder = self.path("addons/greedy")
        self.write("addons/greedy/waybar.jsonc", json.dumps({
            "custom/tiler": {"exec": "mine"}, fl.PHONE_MODULE: {"exec": "mine"}, "custom/mine": {"exec": "ok"}}))
        with mock.patch.object(fl, "LAYOUTS_DIR", LAYOUTS), mock.patch.object(fl, "STYLES_DIR", STYLES), \
                mock.patch.object(fl, "current_icon_theme", return_value=None), self.quiet():
            for layout in fl.layouts().values():
                bars = fl.load_bars(layout)
                fl.use_addons(bars, {"greedy": folder})
                self.assertNotIn("mine", json.dumps([bar.get("custom/tiler") for bar in bars]), layout.id)
                modules = [m for bar in bars for m in bar_modules(bar)]
                self.assertNotIn(fl.PHONE_MODULE, modules, layout.id)
                self.assertIn("custom/mine", modules, layout.id)

    def test_phone_module_settings(self):
        modules = fl.load_jsonc(os.path.join(LAYOUTS, "common", "modules.jsonc"))
        phone = modules[fl.PHONE_MODULE]
        self.assertEqual(phone["exec"], "flickos-phone status --panel")
        self.assertEqual(phone["on-click"], "flickos-phone menu")
        self.assertEqual(phone["signal"], 9)            # flickos-phone's PANEL_SIGNAL
        self.assertNotEqual(phone["signal"], modules["custom/tiler"]["signal"])

    def test_phone_on_asks_flickos_phone(self):
        answer = lambda out, code=0: mock.Mock(return_value=mock.Mock(stdout=out, returncode=code))
        with mock.patch.object(fl.shutil, "which", return_value="/usr/bin/flickos-phone"), \
                mock.patch.object(fl, "live_system", return_value=False):
            with mock.patch.object(fl.subprocess, "run", answer("yes\n")) as run:
                self.assertTrue(fl.phone_on())
            self.assertEqual(run.call_args.args[0], [fl.PHONE, "get", "enabled"])
            with mock.patch.object(fl.subprocess, "run", answer("no\n")):
                self.assertFalse(fl.phone_on())
            with mock.patch.object(fl.subprocess, "run", side_effect=OSError("gone")):
                self.assertFalse(fl.phone_on())
        with mock.patch.object(fl, "live_system", return_value=True), \
                mock.patch.object(fl.subprocess, "run", answer("yes\n")):
            self.assertFalse(fl.phone_on())
        self.assertFalse(fl.phone_on())                 # no flickos-phone (the tests' PHONE)


if __name__ == "__main__":
    unittest.main()


class InterfaceTest(unittest.TestCase):
    """HIG VIS-11: the names users' own layouts use stay. Renaming one breaks
    their panels without a word: keep the old name for two releases, and
    change this list together with the rule (docs/hig/06-visual-style.md)."""

    MODULES = ("custom/launcher", "custom/desktop", "custom/tiler", "custom/phone", "custom/recording",
               "wlr/taskbar", "clock", "wireplumber", "battery", "tray")
    SIGNALS = {"custom/tiler": 8, "custom/phone": 9, "custom/recording": 10}
    # Classes FlickOS's buttons set, as base.css styles them.
    CLASSES = ("#custom-tiler.off", "#custom-phone.waiting", "#custom-recording.recording", "#custom-desk.active")

    def test_shared_files(self):
        for name in ("modules.jsonc", "base.css"):
            self.assertTrue(os.path.isfile(os.path.join(LAYOUTS, "common", name)), name)
        self.assertEqual(fl.LAYOUTS_DIR, fl.PREFIX + "/usr/share/flickos/layouts")

    def test_modules_and_signals(self):
        modules = fl.load_jsonc(os.path.join(LAYOUTS, "common/modules.jsonc"))
        for name in self.MODULES:
            self.assertIn(name, modules, "VIS-11: a module users' layouts use")
        for name, number in self.SIGNALS.items():
            self.assertEqual(modules[name]["signal"], number, name)
        self.assertEqual(fl.DESKTOPS_SIGNAL, 11)
        self.assertEqual(fl.PANEL_SIGNALS.keys(), {8, 9, 10, 11})

    def test_placeholders_and_groups(self):
        self.assertEqual((fl.PINNED_MODULE, fl.PIN_MODULE), ("flickos/pinned", "custom/pin"))
        self.assertEqual((fl.DESKTOPS_MODULE, fl.DESK_MODULE), ("flickos/desktops", "custom/desk"))
        self.assertEqual(fl.QUICK_GROUP, "group/quick")

    def test_classes_styled(self):
        css = read(os.path.join(LAYOUTS, "common/base.css"))
        for selector in self.CLASSES + ("#quick",):
            self.assertIn(selector, css, "VIS-11: base.css styles it")
