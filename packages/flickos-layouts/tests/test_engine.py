"""Tests for usr/bin/flickos-layout. Run: python3 -m unittest discover -s tests"""

import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
FIXTURE_RCXML = os.path.join(HERE, "fixtures", "rc.xml")

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_layout", os.path.join(PACKAGE, "usr/bin/flickos-layout"))
fl = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fl)
# Never ask the build host's flickos-phone whether the phone connection is on.
fl.PHONE = os.path.join(HERE, "no-flickos-phone")
# EngineTest replaces these with a fake settings store.
REAL_GSETTINGS_GET, REAL_GSETTINGS_SET = fl.gsettings_get, fl.gsettings_set
REAL_GSETTINGS_DEFAULT, REAL_GSETTINGS_RESET = fl.gsettings_default, fl.gsettings_reset


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class EngineTest(unittest.TestCase):
    """Temporary HOME, XDG_RUNTIME_DIR, system config dir and layouts dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flickos-layout-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.path("home")
        self.runtime = self.path("run")
        self.sysconf = self.path("etc/xdg")
        self.layouts_dir = self.path("layouts")
        for folder in (self.home, self.runtime, self.layouts_dir, self.path("no-proc")):
            os.makedirs(folder)
        self.write("etc/xdg/labwc/rc.xml", read(FIXTURE_RCXML))
        self.base_foot = self.write("etc/xdg/flickos/foot/foot.ini", "[colors]\nbackground=383c4a\n")
        self.base_fuzzel = self.write("etc/xdg/flickos/fuzzel/fuzzel.ini", "[colors]\nbackground=383c4aee\n")
        self.base_mako = self.write("share/flickos/mako/config", "background-color=#383c4aee\n")
        self.make_style("dark", order=10)

        env = mock.patch.dict(os.environ, {
            "HOME": self.home,
            "XDG_RUNTIME_DIR": self.runtime,
            "XDG_CONFIG_DIRS": self.sysconf,
            # Never the build host's styles in /usr/share/flickos/styles.
            "XDG_DATA_DIRS": self.path("data"),
        })
        env.start()
        self.addCleanup(env.stop)
        # A terminal started from the panel or the dock has the panel's
        # FLICKOS_LAYOUT/FLICKOS_STYLE (panel_environment).
        for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "WAYLAND_DISPLAY",
                    "LABWC_PID", "FLICKOS_PLAIN",
                    "FLICKOS_LAYOUT", "FLICKOS_STYLE"):
            os.environ.pop(key, None)
        # gsettings: a dict instead of dconf. Empty means gsettings isn't available.
        # Defaults (vendor overrides) are only in gsettings_defaults.
        self.gsettings = {}
        self.gsettings_defaults = {}
        for name, value in (("LAYOUTS_DIR", self.layouts_dir),
                            ("STYLES_DIR", self.path("styles")),
                            ("SYSTEM_CONF", self.path("etc/xdg/flickos/layouts.conf")),
                            ("HISTORY_CONF", self.path("etc/xdg/flickos/history.conf")),
                            # Never the build host's add-ons.
                            ("ADDONS_DIR", self.path("addons")),
                            ("DEFAULT_LAYOUT", "flickos"),
                            ("DEFAULT_STYLE", "dark"),
                            ("BASE_STYLE", "dark"),
                            ("BASE_FOOT", self.base_foot),
                            ("BASE_FUZZEL", self.base_fuzzel),
                            ("BASE_MAKO", self.base_mako),
                            ("GSETTINGS", self.path("no-gsettings")),
                            # No processes: set --live must never find, signal or
                            # stop the build host's waybar, dock or start menu.
                            ("PROC", self.path("no-proc")),
                            ("gsettings_get", self.gsettings.get),
                            ("gsettings_set", self.gsettings.__setitem__),
                            ("gsettings_default", self.gsettings_defaults.get),
                            ("gsettings_reset", self.gsettings_reset),
                            # Every theme counts as installed; StyleFallbackTest says which aren't.
                            ("theme_installed", lambda kind, name: True),
                            ("DPKG_QUERY", self.path("no-dpkg-query")),
                            # No GTK child: CssCheckTest puts a stand-in here.
                            ("CSS_CHECKER", self.path("no-check-css")),
                            ("CSS_RESULTS", {})):
            patcher = mock.patch.object(fl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The start menu is the default apps button while flickos-menu is
        # installed. Whether the build host has it must not change the files
        # tests expect, so it isn't, except in StartMenuTest.
        installed = fl.installed
        patcher = mock.patch.object(fl, "installed", lambda program: program != "flickos-menu" and installed(program))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.root = os.path.join(self.runtime, "flickos")
        self.overlay_rcxml = os.path.join(self.root, "xdg/labwc/rc.xml")
        self.panel_log = os.path.join(self.root, fl.PANEL_LOG)
        self.addCleanup(self.close_log)

    def gsettings_reset(self, key):
        self.gsettings[key] = self.gsettings_defaults[key]

    def close_log(self):
        """A panel log opened by a test must not stay open for the next one."""
        if fl.LOG_STREAM is not None:
            fl.LOG_STREAM.close()
            fl.LOG_STREAM = None

    def path(self, relative):
        return os.path.join(self.tmp, relative)

    def write(self, relative, text):
        path = self.path(relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def make_layout(self, layout_id, order=50, titlebar=None, extra=""):
        lines = ["[Layout]", f"Name={layout_id.title()}", f"Comment=The {layout_id} layout",
                 f"Order={order}", "Waybar=waybar.jsonc", "Style=style.css"]
        if titlebar is not None:
            lines.append(f"TitlebarLayout={titlebar}")
        self.write(f"layouts/{layout_id}/layout.ini", "\n".join(lines) + "\n" + extra)
        self.write(f"layouts/{layout_id}/waybar.jsonc", "{}\n")
        self.write(f"layouts/{layout_id}/style.css", "\n")

    def make_style(self, style_id, order=50, gtk="Arc-Dark", icons="Numix-Circle", labwc="FlickOS-Arc-Dark",
                   scheme="prefer-dark", extra=""):
        self.write(f"styles/{style_id}/style.ini", "\n".join([
            "[Style]", f"Name={style_id.title()}", f"Comment=The {style_id} style", f"Order={order}",
            f"GtkTheme={gtk}", f"IconTheme={icons}", f"LabwcTheme={labwc}", f"ColorScheme={scheme}",
            "Waybar=waybar-colors.css", "Foot=foot.ini", "Fuzzel=fuzzel.ini", "Mako=mako.conf"]) + "\n" + extra)
        self.write(f"styles/{style_id}/waybar-colors.css", "@define-color fg_color #d3dae3;\n")
        for name in ("foot.ini", "fuzzel.ini", "mako.conf"):
            self.write(f"styles/{style_id}/{name}", f"# {style_id}\n")

    def make_light_style(self):
        self.make_style("light", order=20, gtk="Arc", icons="Numix-Circle-Light", labwc="FlickOS-Arc",
                        scheme="default")

    def set_system_default(self, layout_id, key="Layout"):
        self.write("etc/xdg/flickos/layouts.conf", f"[Defaults]\n{key}={layout_id}\n")

    def set_user_choice(self, layout_id, kind="layout"):
        self.write(f"home/.config/flickos/{kind}", layout_id + "\n")

    def layout(self, layout_id):
        return fl.layouts()[layout_id]

    def style(self, style_id="dark"):
        return fl.styles()[style_id]

    def prepare(self, layout_id, style_id="dark"):
        return fl.prepare(self.layout(layout_id), self.style(style_id), fl.labwc_themes(fl.styles()))

    def quiet(self):
        stack = contextlib.ExitStack()
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        return stack


class RcxmlOverlayTest(EngineTest):

    def generate(self, titlebar="close,iconify,max:"):
        self.make_layout("mac", titlebar=titlebar)
        with self.quiet():
            self.assertTrue(self.prepare("mac"))
        return ET.parse(self.overlay_rcxml).getroot()

    def test_injects_into_existing_theme_and_keeps_other_settings(self):
        root = self.generate()
        themes = root.findall("theme")
        self.assertEqual(len(themes), 1)
        self.assertEqual(themes[0].findtext("titlebar/layout"), "close,iconify,max:")
        self.assertEqual(themes[0].findtext("name"), "FlickOS-Arc-Dark")
        self.assertEqual(themes[0].findtext("cornerRadius"), "6")
        self.assertIsNotNone(root.find("keyboard/default"))

    def test_creates_theme_and_titlebar_when_missing(self):
        self.write("etc/xdg/labwc/rc.xml", "<?xml version=\"1.0\"?>\n<labwc_config><keyboard/></labwc_config>\n")
        root = self.generate()
        self.assertEqual(root.findtext("theme/titlebar/layout"), "close,iconify,max:")

    def test_replaces_existing_layout(self):
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><theme><name>X</name><titlebar>"
                   "<layout>icon:iconify,max,close</layout><showTitle>no</showTitle>"
                   "</titlebar></theme></labwc_config>\n")
        root = self.generate()
        self.assertEqual([e.text for e in root.iter("layout")], ["close,iconify,max:"])
        self.assertEqual(root.findtext("theme/name"), "X")
        self.assertEqual(root.findtext("theme/titlebar/showTitle"), "no")

    def test_updates_attribute_form(self):
        self.write("etc/xdg/labwc/rc.xml", '<labwc_config><theme><titlebar layout="icon:close"/></theme></labwc_config>\n')
        root = self.generate()
        titlebar = root.find("theme/titlebar")
        self.assertEqual(titlebar.get("layout"), "close,iconify,max:")
        self.assertIsNone(titlebar.find("layout"))

    def test_changes_last_theme_element(self):
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><theme><name>A</name></theme>"
                   "<theme><cornerRadius>2</cornerRadius></theme></labwc_config>\n")
        root = self.generate()
        themes = root.findall("theme")
        self.assertIsNone(themes[0].find("titlebar"))
        self.assertEqual(themes[1].findtext("titlebar/layout"), "close,iconify,max:")

    def test_escaped_ampersands_and_comments_survive(self):
        self.generate()
        text = read(self.overlay_rcxml)
        self.assertIn('"$f" &amp;&amp; notify-send', text)
        self.assertNotIn("&&", text)
        self.assertIn("Load labwc's built-in bindings", text)
        commands = [e.text for e in ET.parse(self.overlay_rcxml).getroot().iter("command")]
        self.assertTrue(any("&& notify-send" in c for c in commands))

    def test_malformed_base_removes_overlay(self):
        self.generate()
        self.assertTrue(os.path.exists(self.overlay_rcxml))
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><theme>\n")
        with self.quiet() as _, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertTrue(self.prepare("mac"))
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        self.assertIn("cannot read", err.getvalue())

    def test_overlay_dir_is_skipped_when_finding_base(self):
        self.generate()
        link = self.path("overlay-link")
        os.symlink(os.path.join(self.root, "xdg"), link)
        for first in (os.path.join(self.root, "xdg"), link):
            os.environ["XDG_CONFIG_DIRS"] = f"{first}:{self.sysconf}"
            self.assertEqual(fl.find_base_rcxml(self.root), os.path.join(self.sysconf, "labwc/rc.xml"))

    def test_regenerating_from_overlay_path_does_not_nest_comments(self):
        self.generate()
        os.environ["XDG_CONFIG_DIRS"] = f"{self.root}/xdg:{self.sysconf}"
        self.generate()
        self.assertEqual(read(self.overlay_rcxml).count("Generated by flickos-layout"), 1)

    def test_no_overlay_needed_removes_file(self):
        self.generate()
        self.make_layout("plain")
        with self.quiet():
            self.assertTrue(self.prepare("plain"))
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "xdg")))

    def desktops_layout(self, count="4"):
        self.make_layout("desks", extra=f"Desktops={count}\n")
        with self.quiet():
            self.assertTrue(self.prepare("desks"))
        return ET.parse(self.overlay_rcxml).getroot() if os.path.exists(self.overlay_rcxml) else None

    def test_desktops_named_with_keys(self):
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><desktops number=\"2\"/><keyboard><default />"
                   "<keybind key=\"W-C-Left\"><action name=\"Close\"/></keybind></keyboard></labwc_config>\n")
        root = self.desktops_layout()
        desktops = root.findall("desktops")
        self.assertEqual(len(desktops), 1)
        self.assertEqual(desktops[0].get("number"), "4")
        self.assertEqual([name.text for name in desktops[0].iter("name")], ["1", "2", "3", "4"])
        binds = {b.get("key"): [(a.get("name"), a.get("to"), a.get("wrap")) for a in b.findall("action")]
                 for b in root.iter("keybind")}
        self.assertEqual(binds, {key: [(name, to, None if to.isdigit() else "no")]
                                 for key, name, to in fl.desktop_keys(4)})
        self.assertEqual(binds["W-3"], [("GoToDesktop", "3", None)])
        self.assertEqual(binds["W-S-4"], [("SendToDesktop", "4", None)])
        self.assertNotIn("W-5", binds)
        self.assertIsNotNone(root.find("keyboard/default"))

    def test_one_desktop_needs_no_overlay(self):
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><keyboard><default /></keyboard></labwc_config>\n")
        self.assertIsNotNone(self.desktops_layout())
        self.assertIsNone(self.desktops_layout("1"))

    def test_invalid_desktops_are_ignored(self):
        for value in ("0", "10", "four"):
            self.make_layout("bad", extra=f"Desktops={value}\n")
            with self.quiet(), contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(self.layout("bad").desktops, 1)
            self.assertIn("invalid Desktops=", err.getvalue())

    def test_invalid_titlebar_layout_is_ignored(self):
        self.make_layout("bad", titlebar="close,maximize")
        with self.quiet():
            self.assertIsNone(self.layout("bad").titlebar_layout)
        self.assertTrue(fl.valid_titlebar_layout("close,iconify,max:"))
        self.assertTrue(fl.valid_titlebar_layout("icon:iconify,max,close"))
        self.assertFalse(fl.valid_titlebar_layout("close"))

    def test_prepare_without_runtime_dir_fails(self):
        del os.environ["XDG_RUNTIME_DIR"]
        self.make_layout("plain")
        with self.quiet():
            self.assertFalse(self.prepare("plain"))


class ResolutionTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_layout("flickos", order=10)
        self.make_layout("redmond", order=20)
        self.make_layout("cupertino", order=30)

    def resolve(self):
        with self.quiet():
            return fl.resolve_layout(fl.layouts()).id

    def test_builtin_default(self):
        self.assertEqual(self.resolve(), "flickos")

    def test_system_default_beats_builtin(self):
        self.set_system_default("redmond")
        self.assertEqual(self.resolve(), "redmond")

    def test_user_choice_beats_system_default(self):
        self.set_system_default("redmond")
        self.set_user_choice("cupertino")
        self.assertEqual(self.resolve(), "cupertino")

    def test_xdg_config_home_is_respected(self):
        os.environ["XDG_CONFIG_HOME"] = self.path("cfg")
        self.write("cfg/flickos/layout", "redmond\n")
        self.assertEqual(self.resolve(), "redmond")

    def test_unknown_user_choice_falls_back_to_system_default(self):
        self.set_system_default("redmond")
        self.set_user_choice("nonexistent")
        self.assertEqual(self.resolve(), "redmond")

    def test_unknown_system_default_falls_back_to_builtin(self):
        self.set_system_default("nonexistent")
        self.assertEqual(self.resolve(), "flickos")

    def test_missing_builtin_falls_back_to_first_by_order(self):
        shutil.rmtree(os.path.join(self.layouts_dir, "flickos"))
        self.assertEqual(self.resolve(), "redmond")

    def test_no_layouts_is_an_error(self):
        for name in os.listdir(self.layouts_dir):
            shutil.rmtree(os.path.join(self.layouts_dir, name))
        with self.assertRaises(fl.LayoutError):
            fl.resolve_layout(fl.layouts())

    def test_list_order_and_broken_layouts_skipped(self):
        self.write("layouts/broken/layout.ini", "[Layout]\nName=Broken\n")
        self.write("layouts/common/modules.jsonc", "{}\n")
        with self.quiet():
            self.assertEqual(list(fl.layouts()), ["flickos", "redmond", "cupertino"])

    def test_relative_and_absolute_paths(self):
        self.write("layouts/abs/layout.ini", "[Layout]\nName=Abs\nWaybar=/usr/share/flickos/waybar/config.jsonc\nStyle=style.css\n")
        layout = self.layout("abs")
        self.assertEqual(layout.waybar, "/usr/share/flickos/waybar/config.jsonc")
        self.assertEqual(layout.style, os.path.join(self.layouts_dir, "abs/style.css"))


class DoctorTest(EngineTest):

    def test_clean_home_has_no_warnings(self):
        self.assertEqual(fl.doctor_warnings(), [])

    def test_user_waybar_config(self):
        self.write("home/.config/waybar/config.jsonc", "{}")
        [warning] = fl.doctor_warnings()
        self.assertIn("waybar/config.jsonc", warning)

    def test_user_rcxml(self):
        self.write("home/.config/labwc/rc.xml", "<labwc_config/>")
        [warning] = fl.doctor_warnings()
        self.assertIn("window buttons", warning)

    def test_user_autostart(self):
        self.write("home/.config/labwc/autostart", "swaybg -i foo.jpg &\n")
        [warning] = fl.doctor_warnings()
        self.assertIn(fl.FLICKOS_AUTOSTART, warning)
        # Phase 2: any user autostart keeps labwc from merging; Startup Applications is the way.
        self.write("home/.config/labwc/autostart", f"{fl.FLICKOS_AUTOSTART}\nswaybg -i foo.jpg &\n")
        [warning] = fl.doctor_warnings()
        self.assertIn("Startup Applications", warning)
        self.assertNotIn("doesn't run", warning)

    def test_session_without_overlay(self):
        os.environ["LABWC_PID"] = "1"
        [warning] = fl.doctor_warnings()
        self.assertIn("log out", warning)
        os.makedirs(os.path.join(self.root, "xdg"))
        os.environ["XDG_CONFIG_DIRS"] = f"{self.root}/xdg:{self.sysconf}"
        self.assertEqual(fl.doctor_warnings(), [])

    def test_doctor_exit_code(self):
        with self.quiet():
            self.assertEqual(fl.main(["doctor"]), 0)
        self.write("home/.config/labwc/rc.xml", "<labwc_config/>")
        with self.quiet():
            self.assertEqual(fl.main(["doctor"]), 1)


class CommandTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_layout("flickos", order=10)
        self.make_layout("mac", order=20, titlebar="close,iconify,max:")

    def output(self, *args):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            status = fl.main(list(args))
        return status, out.getvalue()

    def test_state_is_list_current_and_doctor_in_one(self):
        self.write("home/.config/waybar/config", "{}")
        self.assertEqual(self.output("set", "mac")[0], 0)
        status, text = self.output("state")
        self.assertEqual(status, 0)
        state = json.loads(text)
        for kind, words in (("layout", []), ("style", ["style"]), ("clicks", ["clicks"]),
                            ("launcher", ["launcher"]), ("menu-style", ["menu-style"]), ("clock", ["clock"])):
            listed = self.output(*words, "list")[1]
            # Styles add their folder at the end (TXT-7).
            self.assertEqual("".join(f"{c['id']}\t{c['name']}\t{c['comment']}"
                                     + (f"\t{c['folder']}" if kind == "style" else "") + "\n"
                                     for c in state[kind]["choices"]), listed, kind)
            self.assertEqual(state[kind]["current"] + "\n", self.output(*words, "current")[1], kind)
        self.assertEqual(state["layout"]["current"], "mac")
        self.assertEqual(state["warnings"], self.output("doctor")[1].splitlines())
        self.assertTrue(any("waybar/config" in warning for warning in state["warnings"]))

    def test_set_saves_choice_and_overlay_outside_session(self):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fl.main(["set", "mac"]), 0)
        self.assertIn("next login", out.getvalue())
        self.assertEqual(read(self.path("home/.config/flickos/layout")), "mac\n")
        self.assertTrue(os.path.exists(self.overlay_rcxml))
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["current"])
        self.assertEqual(out.getvalue(), "mac\n")
        with self.quiet():
            self.assertEqual(fl.main(["set", "flickos"]), 0)
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_set_unknown_id_changes_nothing(self):
        with self.quiet():
            self.assertEqual(fl.main(["set", "nope"]), 1)
        self.assertFalse(os.path.exists(self.path("home/.config/flickos/layout")))

    def test_set_live_reconfigures_and_restarts_panel(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-0", LABWC_PID="1")
        with mock.patch.object(fl.subprocess, "run") as run, \
                mock.patch.object(fl, "restart_panel") as restart, self.quiet():
            self.assertEqual(fl.main(["set", "mac"]), 0)
        self.assertEqual([c.args[0] for c in run.call_args_list], [["labwc", "--reconfigure"]])
        restart.assert_called_once()
        layout, style, command, dock = restart.call_args.args
        self.assertEqual((layout.id, style.id), ("mac", "dark"))
        self.assertEqual(command, ["waybar", "-c", f"{self.root}/waybar/config.jsonc",
                                   "-s", f"{self.root}/waybar/style.css"])
        self.assertIsNone(dock)

    def make_dock(self, layout_id="mac"):
        """Give layout_id a dock (Dock=, DockStyle=)."""
        ini = f"layouts/{layout_id}/layout.ini"
        self.write(ini, read(self.path(ini)) + "Dock=dock.config\nDockStyle=dock.css\n")
        self.write(f"layouts/{layout_id}/dock.config", "#Api2\nbar { }\n")
        self.write(f"layouts/{layout_id}/dock.css", "grid#dock { }\n")

    def test_set_live_replaces_the_dock(self):
        self.make_dock()
        os.environ.update(WAYLAND_DISPLAY="wayland-0", LABWC_PID="1")
        dock_config = f"{self.root}/dock/sfwbar.config"
        with mock.patch.object(fl.subprocess, "run"), mock.patch.object(fl, "restart_panel") as restart, self.quiet():
            self.assertEqual(fl.main(["set", "mac"]), 0)
            self.assertEqual(restart.call_args.args[3], ["sfwbar", "-f", dock_config])
            self.assertTrue(os.path.exists(dock_config))
            self.assertEqual(fl.main(["set", "flickos"]), 0)
            self.assertIsNone(restart.call_args.args[3])
        self.assertFalse(os.path.exists(dock_config))

    def test_set_with_broken_dock_changes_the_panel_and_fails(self):
        self.make_dock()
        os.remove(os.path.join(self.layouts_dir, "mac/dock.css"))
        os.environ.update(WAYLAND_DISPLAY="wayland-0", LABWC_PID="1")
        with mock.patch.object(fl.subprocess, "run"), mock.patch.object(fl, "restart_panel") as restart, self.quiet():
            self.assertEqual(fl.main(["set", "mac"]), 1)
        _, _, command, dock = restart.call_args.args
        self.assertEqual(command[0], "waybar")
        self.assertIsNone(dock)

    def test_set_with_broken_panel_saves_choice_and_fails(self):
        os.remove(os.path.join(self.layouts_dir, "mac/waybar.jsonc"))
        with self.quiet():
            self.assertEqual(fl.main(["set", "mac"]), 1)
        self.assertEqual(read(self.path("home/.config/flickos/layout")), "mac\n")

    def test_list(self):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["list"])
        self.assertEqual(out.getvalue(), "flickos\tFlickos\tThe flickos layout\nmac\tMac\tThe mac layout\n")

    def run_panel(self):
        """Run `panel` without really starting anything: returns the (command,
        environment) it hands to the supervisor, and collects the programs it
        starts on the side (notifications, dock) in self.started."""
        with mock.patch.object(fl, "supervise", return_value=0) as panel, \
                mock.patch.object(fl, "start_supervised") as start, self.quiet():
            self.assertEqual(fl.main(["panel"]), 0)
        self.started = start.call_args_list
        self.mako_command = self.started[0].args[0]
        return panel.call_args.args[0], panel.call_args.args[1]

    def test_panel_runs_generated_files(self):
        args, env = self.run_panel()
        self.assertEqual(len(self.started), 1)  # no dock
        config, style = f"{self.root}/waybar/config.jsonc", f"{self.root}/waybar/style.css"
        self.assertEqual(args, ["waybar", "-c", config, "-s", style])
        self.assertEqual((env["FLICKOS_LAYOUT"], env["FLICKOS_STYLE"]), ("flickos", "dark"))
        self.assertEqual(fl.load_jsonc(config), [{}])
        self.assertEqual(self.mako_command, ["mako", "-c", f"{self.root}/mako/config"])
        self.assertIn(f'@import url("{os.path.join(self.layouts_dir, "flickos/style.css")}");', read(style))

    def test_panel_starts_the_dock(self):
        self.make_dock()
        self.set_user_choice("mac")
        args, env = self.run_panel()
        self.assertEqual(args[0], "waybar")
        mako, dock = self.started
        self.assertEqual(dock.args[0], ["sfwbar", "-f", f"{self.root}/dock/sfwbar.config"])
        self.assertEqual(dock.args[1]["FLICKOS_LAYOUT"], "mac")

    def test_panel_starts_without_a_broken_dock(self):
        self.make_dock()
        self.set_user_choice("mac")
        os.remove(os.path.join(self.layouts_dir, "mac/dock.config"))
        args, env = self.run_panel()
        self.assertEqual(args, ["waybar", "-c", f"{self.root}/waybar/config.jsonc", "-s", f"{self.root}/waybar/style.css"])
        self.assertEqual(len(self.started), 1)

    def test_panel_falls_back_without_runtime_dir(self):
        del os.environ["XDG_RUNTIME_DIR"]
        args, env = self.run_panel()
        self.assertEqual(args, ["waybar", "-c", fl.FALLBACK_WAYBAR, "-s", fl.FALLBACK_STYLE])
        self.assertEqual(self.mako_command, ["mako", "-c", self.base_mako])

    def test_panel_falls_back_on_error(self):
        os.remove(os.path.join(self.layouts_dir, "flickos/style.css"))
        args, env = self.run_panel()
        self.assertEqual(args, ["waybar", "-c", fl.FALLBACK_WAYBAR, "-s", fl.FALLBACK_STYLE])
        self.assertNotIn("FLICKOS_LAYOUT", env)
        self.assertEqual(self.mako_command, ["mako", "-c", f"{self.root}/mako/config"])

    def test_panel_uses_user_waybar_config(self):
        self.write("home/.config/waybar/config", "{}")
        args, env = self.run_panel()
        self.assertEqual(args, ["waybar"])
        self.assertEqual(self.mako_command, ["mako", "-c", f"{self.root}/mako/config"])


class ProcessTest(EngineTest):

    def fake_process(self, pid, comm, args, environ=b"", state="S"):
        self.write(f"proc/{pid}/comm", comm + "\n")
        self.write(f"proc/{pid}/stat", f"{pid} ({comm}) {state} 1 2 3\n")
        with open(self.path(f"proc/{pid}/cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in args) + b"\0")
        with open(self.path(f"proc/{pid}/environ"), "wb") as f:
            f.write(environ)

    def test_waybar_config_arg(self):
        self.assertEqual(fl.waybar_config_arg(["-c", "/a", "-s", "/b"]), "/a")
        self.assertEqual(fl.waybar_config_arg(["--config", "/a"]), "/a")
        self.assertEqual(fl.waybar_config_arg(["--config=/a"]), "/a")
        self.assertEqual(fl.waybar_config_arg(["-c/a"]), "/a")
        self.assertIsNone(fl.waybar_config_arg(["-s", "/b"]))
        self.assertIsNone(fl.waybar_config_arg(["-c"]))

    def test_only_flickos_waybars_are_managed(self):
        self.write("proc/self/comm", "python3\n")
        self.fake_process(100, "waybar", ["waybar", "-c", "/usr/share/flickos/waybar/config.jsonc", "-s", "x"])
        self.fake_process(101, "waybar", ["waybar"])
        self.fake_process(102, "waybar", ["waybar", "-c", f"{self.home}/.config/waybar/config"])
        self.fake_process(103, "waybar", ["/usr/bin/waybar", "--config", f"{self.root}/waybar/config.jsonc"])
        self.fake_process(104, "foot", ["foot", "-c", "/usr/share/flickos/waybar/config.jsonc"])
        self.fake_process(105, "waybar", ["waybar", "-c", "/usr/share/flickos-other/config.jsonc"])
        with mock.patch.object(fl, "PROC", self.path("proc")):
            self.assertEqual(fl.managed_waybars(), [100, 103])

    def test_only_flickos_docks_are_managed(self):
        self.fake_process(110, "sfwbar", ["sfwbar", "-f", f"{self.root}/dock/sfwbar.config"])
        self.fake_process(111, "sfwbar", ["sfwbar"])
        self.fake_process(112, "sfwbar", ["sfwbar", "-f", f"{self.home}/.config/sfwbar/sfwbar.config"])
        self.fake_process(113, "sfwbar", ["/usr/bin/sfwbar", "--config", f"{self.root}/dock/sfwbar.config"])
        self.fake_process(114, "waybar", ["waybar", "-f", f"{self.root}/dock/sfwbar.config"])
        with mock.patch.object(fl, "PROC", self.path("proc")):
            self.assertEqual(fl.managed_docks(), [110, 113])
        del os.environ["XDG_RUNTIME_DIR"]
        self.assertEqual(fl.managed_docks(), [])

    def test_environ_and_state(self):
        self.fake_process(200, "waybar (x)", ["waybar"], environ=b"A=1\0B=x=y\0", state="Z")
        self.fake_process(201, "waybar", ["waybar"])
        with mock.patch.object(fl, "PROC", self.path("proc")):
            self.assertEqual(fl.process_environ(200), {"A": "1", "B": "x=y"})
            self.assertFalse(fl.running(200))
            self.assertTrue(fl.running(201))
            self.assertFalse(fl.running(999))

    def test_restart_panel_uses_old_environment(self):
        self.make_layout("flickos")
        self.fake_process(300, "waybar", ["waybar", "-c", "/usr/share/flickos/waybar/config.jsonc"],
                          environ=b"WAYLAND_DISPLAY=wayland-1\0FLICKOS_LAYOUT=old\0")
        with mock.patch.object(fl, "PROC", self.path("proc")), \
                mock.patch.object(fl, "stop") as stop, \
                mock.patch.object(fl.subprocess, "run") as run:
            self.assertTrue(fl.restart_panel(self.layout("flickos"), self.style(), ["waybar", "-c", "new"]))
        stop.assert_called_once_with([300])
        self.assertEqual(run.call_args.args[0],
                         ["setsid", "-f", fl.SELF, "supervise", "--", "waybar", "-c", "new"])
        env = run.call_args.kwargs["env"]
        self.assertEqual(env, {"WAYLAND_DISPLAY": "wayland-1", "FLICKOS_LAYOUT": "flickos", "FLICKOS_STYLE": "dark"})

    def test_restart_panel_replaces_the_dock(self):
        self.make_layout("flickos")
        self.fake_process(310, "waybar", ["waybar", "-c", "/usr/share/flickos/waybar/config.jsonc"])
        self.fake_process(311, "sfwbar", ["sfwbar", "-f", f"{self.root}/dock/sfwbar.config"])
        with mock.patch.object(fl, "PROC", self.path("proc")), \
                mock.patch.object(fl, "stop") as stop, \
                mock.patch.object(fl.subprocess, "run") as run:
            self.assertTrue(fl.restart_panel(self.layout("flickos"), self.style(), ["waybar"], ["sfwbar", "-f", "d"]))
            stop.assert_called_once_with([310, 311])
            supervised = ["setsid", "-f", fl.SELF, "supervise", "--"]
            self.assertEqual([c.args[0] for c in run.call_args_list],
                             [supervised + ["waybar"], supervised + ["sfwbar", "-f", "d"]])
            run.reset_mock()
            fl.restart_panel(self.layout("flickos"), self.style(), ["waybar"])
            self.assertEqual([c.args[0] for c in run.call_args_list], [supervised + ["waybar"]])

    def test_restart_panel_without_flickos_waybar_does_nothing(self):
        self.make_layout("flickos")
        os.makedirs(self.path("proc"))
        with mock.patch.object(fl, "PROC", self.path("proc")), \
                mock.patch.object(fl.subprocess, "run") as run:
            self.assertFalse(fl.restart_panel(self.layout("flickos"), self.style(), ["waybar"]))
        run.assert_not_called()


class SuperviseTest(EngineTest):
    """Panel, dock and notifications run under supervise(): it restarts one
    that fails and leaves one that was stopped on purpose alone."""

    def setUp(self):
        super().setUp()
        # No waiting between restarts, and give up sooner.
        for name, value in (("RESTART_SECONDS", 0.0), ("RESTART_SECONDS_MAX", 0.0), ("RESTART_LIMIT", 2)):
            patcher = mock.patch.object(fl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.counter = self.path("runs")

    def script(self, body):
        """A command that records the run, then does body."""
        return ["sh", "-c", f"echo run >> {shlex.quote(self.counter)}; {body}"]

    def runs(self):
        return len(read(self.counter).splitlines()) if os.path.exists(self.counter) else 0

    def test_a_failing_program_is_restarted_until_the_limit(self):
        with self.quiet():
            self.assertEqual(fl.supervise(self.script("exit 1"), dict(os.environ)), 1)
        self.assertEqual(self.runs(), fl.RESTART_LIMIT + 1)

    def test_a_clean_exit_is_not_restarted(self):
        self.assertEqual(fl.supervise(self.script("exit 0"), dict(os.environ)), 0)
        self.assertEqual(self.runs(), 1)

    def test_a_stopped_program_is_not_restarted(self):
        # `set` stops the old panel with SIGTERM before starting the new one.
        self.assertEqual(fl.supervise(self.script("kill -TERM $$"), dict(os.environ)), 0)
        self.assertEqual(self.runs(), 1)

    def test_nothing_is_restarted_once_the_session_is_gone(self):
        env = dict(os.environ, WAYLAND_DISPLAY="wayland-gone")
        self.assertEqual(fl.supervise(self.script("exit 1"), env), 0)
        self.assertEqual(self.runs(), 1)

    def test_a_failure_inside_the_session_is_restarted(self):
        open(os.path.join(self.runtime, "wayland-9"), "w").close()
        with self.quiet():
            fl.supervise(self.script("exit 1"), dict(os.environ, WAYLAND_DISPLAY="wayland-9"))
        self.assertEqual(self.runs(), fl.RESTART_LIMIT + 1)

    def test_output_and_restarts_go_to_the_panel_log(self):
        stream = fl.open_log()
        with self.quiet():
            fl.supervise(self.script("echo trouble >&2; exit 1"), dict(os.environ), stream)
        log = read(self.panel_log)
        self.assertIn("trouble", log)
        self.assertIn("sh stopped (status 1)", log)
        self.assertIn("giving up", log)

    def test_the_panel_log_is_truncated_when_it_grew_too_large(self):
        os.makedirs(self.root, exist_ok=True)
        with open(self.panel_log, "w", encoding="utf-8") as f:
            f.write("x" * (fl.PANEL_LOG_BYTES + 1))
        fl.open_log()
        fl.log_line("new")
        self.assertNotIn("x", read(self.panel_log))
        self.assertTrue(read(self.panel_log).endswith("flickos-layout: new\n"))

    def test_start_supervised_runs_the_program_under_this_one(self):
        with mock.patch.object(fl, "start_detached") as start:
            fl.start_supervised(["waybar", "-c", "x"], {})
        self.assertEqual(start.call_args.args[0], [fl.SELF, "supervise", "--", "waybar", "-c", "x"])

    def test_supervise_command_runs_the_rest_of_the_line(self):
        with mock.patch.object(fl, "supervise", return_value=0) as run:
            self.assertEqual(fl.main(["supervise", "--", "waybar", "-c", "x"]), 0)
        self.assertEqual(run.call_args.args[0], ["waybar", "-c", "x"])
        with self.quiet():
            self.assertEqual(fl.main(["supervise"]), 2)


class ClicksTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_layout("plain")

    def root_binds(self, path):
        context = next(c for c in ET.parse(path).getroot().iter("context") if c.get("name") == "Root")
        return {b.get("button"): fl.bind_actions(b) for b in context.findall("mousebind")}

    def test_fixture_has_the_default_clicks(self):
        default = fl.CLICKS[fl.DEFAULT_CLICKS]
        self.assertEqual(self.root_binds(FIXTURE_RCXML), {"Left": fl.CLICK_ACTIONS[default.left],
                                                          "Right": fl.CLICK_ACTIONS[default.right]})

    def test_default_clicks_need_no_overlay(self):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS[fl.DEFAULT_CLICKS])
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_other_clicks_replace_the_desktop_bindings(self):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS["left-launcher"])
        self.assertEqual(self.root_binds(self.overlay_rcxml), {"Left": fl.CLICK_ACTIONS["launcher"],
                                                               "Right": fl.CLICK_ACTIONS["menu"]})
        overlay = read(self.overlay_rcxml)
        self.assertEqual(overlay.count('<mousebind button="Left"'), 1)
        self.assertIn("<keybind key=\"W-Return\">", overlay)
        self.assertIn("<default />", overlay)

    def test_mouse_section_created_with_labwc_defaults(self):
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><theme><name>X</name></theme></labwc_config>\n")
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS["both-menu"])
        mouse = ET.parse(self.overlay_rcxml).getroot().find("mouse")
        self.assertIsNotNone(mouse.find("default"))
        self.assertEqual(self.root_binds(self.overlay_rcxml), {"Left": fl.CLICK_ACTIONS["menu"],
                                                               "Right": fl.CLICK_ACTIONS["menu"]})

    def test_resolution_and_commands(self):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["clicks", "current"])
        self.assertEqual(out.getvalue(), "right-menu\n")
        self.set_system_default("both-menu", key="Clicks")
        self.assertEqual(fl.resolve_clicks().id, "both-menu")
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fl.main(["clicks", "set", "left-launcher"]), 0)
        self.assertIn("Desktop clicks 'Launcher on left click' saved", out.getvalue())
        self.assertEqual(read(self.path("home/.config/flickos/clicks")), "left-launcher\n")
        self.assertEqual(self.root_binds(self.overlay_rcxml)["Left"], fl.CLICK_ACTIONS["launcher"])
        with self.quiet():
            self.assertEqual(fl.main(["clicks", "set", "nope"]), 1)
            self.assertEqual(fl.main(["set", "--clicks", "right-menu"]), 0)
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["clicks", "list"])
        self.assertEqual([line.split("\t")[0] for line in out.getvalue().splitlines()], list(fl.CLICKS))

    def test_set_needs_something_to_set(self):
        with self.quiet():
            self.assertEqual(fl.main(["set"]), 2)


class ClockTest(EngineTest):
    """The panel clock's hours: 24h (the layouts' own formats) or 12h."""

    BARS = ('[{"include": "../common/modules.jsonc", "modules-right": ["clock"]},'
            ' {"modules-center": ["clock"], "clock": {"format": "{:%H:%M\\n%d/%m/%Y}", "format-alt": "{:%H:%M:%S}",'
            ' "tooltip-format": "<tt>{calendar}</tt>"}},'
            ' {"modules-left": ["clock"]}, {"modules-left": ["tray"]}]\n')

    def setUp(self):
        super().setUp()
        self.make_layout("plain")
        self.write("layouts/plain/waybar.jsonc", self.BARS)
        self.write("layouts/common/modules.jsonc", '{"clock": {"format": "{:%a %d %b  %H:%M}"}}\n')

    def bars(self):
        with self.quiet():
            fl.waybar_command(self.layout("plain"), self.style())
        return fl.load_jsonc(os.path.join(self.root, "waybar/config.jsonc"))

    def test_twelve_hour(self):
        self.assertEqual(fl.twelve_hour("{:%a %d %b  %H:%M}"), "{:%a %d %b  %I:%M %p}")
        self.assertEqual(fl.twelve_hour("{:%H:%M:%S\n%d/%m}"), "{:%I:%M:%S %p\n%d/%m}")
        self.assertEqual(fl.twelve_hour("{:%d/%m/%Y}"), "{:%d/%m/%Y}")

    def test_24h_leaves_the_layouts_formats(self):
        bars = self.bars()
        self.assertNotIn("clock", bars[0])
        self.assertEqual(bars[1]["clock"]["format"], "{:%H:%M\n%d/%m/%Y}")

    def test_12h(self):
        self.set_user_choice("12h", kind="clock")
        bars = self.bars()
        self.assertEqual(bars[0]["clock"], {"format": "{:%a %d %b  %I:%M %p}"})     # from the include
        self.assertEqual(bars[1]["clock"], {"format": "{:%I:%M %p\n%d/%m/%Y}", "format-alt": "{:%I:%M:%S %p}",
                                            "tooltip-format": "<tt>{calendar}</tt>"})
        self.assertEqual(bars[2]["clock"], {"format": "{:%I:%M %p}"})    # waybar's own format
        self.assertNotIn("clock", bars[3])                                  # no clock on that bar

    def test_today_in_the_selection_colors(self):
        self.write("styles/dark/waybar-colors.css", "@define-color bg_color #383c4a;\n"
                   "@define-color selected_bg_color #5294e2;\n@define-color selected_fg_color #ffffff;\n")
        self.write("layouts/common/modules.jsonc", '{"clock": {"format": "{:%H:%M}",'
                   ' "calendar": {"mode": "year", "format": {"weeks": "W{}"}}}}\n')
        today = "<span background='#5294e2' foreground='#ffffff'><b>{}</b></span>"
        bars = self.bars()
        self.assertEqual(bars[0]["clock"], {"calendar": {"format": {"today": today}}})    # waybar merges the include
        self.assertEqual(bars[1]["clock"]["calendar"], {"format": {"today": today}})
        self.assertEqual(bars[1]["clock"]["format"], "{:%H:%M\n%d/%m/%Y}")
        self.assertNotIn("clock", bars[3])

    def test_today_of_a_layout_wins(self):
        self.write("styles/dark/waybar-colors.css",
                   "@define-color selected_bg_color #5294e2;\n@define-color selected_fg_color #ffffff;\n")
        self.write("layouts/common/modules.jsonc", '{"clock": {"calendar": {"format": {"today": "<u>{}</u>"}}}}\n')
        self.write("layouts/plain/waybar.jsonc", '[{"include": "../common/modules.jsonc", "modules-left": ["clock"]},'
                   ' {"modules-left": ["clock"], "clock": {"calendar": {"format": {"today": "<i>{}</i>"}}}}]\n')
        bars = self.bars()
        self.assertNotIn("clock", bars[0])                                      # the include's
        self.assertEqual(bars[1]["clock"], {"calendar": {"format": {"today": "<i>{}</i>"}}})   # the bar's own

    def test_calendar_today(self):
        self.assertIsNone(fl.calendar_today(self.style()))                     # no selection colors
        self.write("styles/dark/waybar-colors.css", "@define-color bg_color #000000;\n"
                   "@define-color selected_bg_color rgba(255, 255, 255, 0.5);\n"
                   "@define-color selected_fg_color #ffffff;\n")
        self.assertEqual(fl.calendar_today(self.style()),                      # as shown over the tooltip
                         "<span background='#808080' foreground='#ffffff'><b>{}</b></span>")
        self.write("styles/dark/waybar-colors.css",
                   "@define-color selected_bg_color @accent;\n@define-color selected_fg_color #ffffff;\n")
        self.assertIsNone(fl.calendar_today(self.style()))

    def test_commands(self):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["clock", "list"])
            fl.main(["clock", "current"])
        self.assertEqual(out.getvalue(), "24h\t24-hour\t13:45\n12h\t12-hour\t1:45 PM\n24h\n")
        with self.quiet():
            self.assertEqual(fl.main(["clock", "set", "12h"]), 0)
            self.assertEqual(fl.main(["clock", "set", "13h"]), 1)
        self.assertEqual(read(os.path.join(self.home, ".config/flickos/clock")), "12h\n")
        self.assertEqual(fl.resolve_clock().id, "12h")
        self.set_system_default("12h", key="Clock")
        os.unlink(os.path.join(self.home, ".config/flickos/clock"))
        self.assertEqual(fl.resolve_clock().id, "12h")


class StartMenuTest(EngineTest):
    """The apps button's start menu (flickos-menu): on by default while it is
    installed, and the overlay points at it; while off nothing of it exists."""

    BARS = '[{"modules-left": ["custom/launcher", "wlr/taskbar"], "custom/launcher": {"format": "Apps"}},' \
           ' {"modules-left": ["clock"]}]\n'

    def setUp(self):
        super().setUp()
        self.make_layout("plain", extra="Menu=bottom-left\n")
        self.write("layouts/plain/waybar.jsonc", self.BARS)
        self.make_layout("nomenu")
        self.installed = True
        patcher = mock.patch.object(fl, "installed", lambda program: self.installed or program != "flickos-menu")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.anchor = os.path.join(self.root, fl.MENU_ANCHOR)

    def prepare_now(self, layout_id="plain"):
        with self.quiet():
            self.assertTrue(fl.prepare(self.layout(layout_id), self.style(), fl.labwc_themes(fl.styles()),
                                       fl.resolve_clicks(), fl.resolve_launcher(), fl.resolve_menu_style()))

    def launcher_bar(self):
        with self.quiet():
            fl.waybar_command(self.layout("plain"), self.style())
        return fl.load_jsonc(os.path.join(self.root, "waybar/config.jsonc"))

    def menu_keybinds(self):
        top = ET.parse(self.overlay_rcxml).getroot()
        return {b.get("key"): (b.get("onRelease"), [a.findtext("command") for a in b.findall("action")])
                for k in top.findall("keyboard") for b in k.findall("keybind") if b.get("key") in fl.MENU_KEYS}

    def root_binds(self):
        context = next(c for c in ET.parse(self.overlay_rcxml).getroot().iter("context") if c.get("name") == "Root")
        return {b.get("button"): fl.bind_actions(b) for b in context.findall("mousebind")}

    def test_layouts_menu_corner(self):
        self.assertEqual(self.layout("plain").menu, "bottom-left")
        self.assertIsNone(self.layout("nomenu").menu)
        self.make_layout("odd", extra="Menu=middle\n")
        with self.quiet():
            self.assertIsNone(self.layout("odd").menu)

    def test_layouts_menu_style(self):
        self.assertEqual(self.layout("plain").menu_style, "classic")    # the default
        self.make_layout("grid", extra="Menu=top-left\nMenuStyle=grid\n")
        self.make_layout("odd", extra="Menu=top-left\nMenuStyle=ribbon\n")
        with self.quiet():
            self.assertEqual(self.layout("grid").menu_style, "grid")
            self.assertEqual(self.layout("odd").menu_style, "classic")

    def test_users_menu_style(self):
        """A menu style chosen for all layouts wins over the layout's own."""
        self.make_layout("grid", extra="Menu=top-left\nMenuStyle=grid\n")
        self.set_user_choice("menu", kind="launcher")
        self.assertEqual(fl.resolve_menu_style().id, fl.FOLLOW_LAYOUT)     # the default
        self.set_user_choice("categories", kind="menu-style")
        self.prepare_now("grid")
        self.assertEqual(read(self.anchor), "top-left\ncategories\n")      # the layout's corner, the user's style
        self.prepare_now()
        self.assertEqual(read(self.anchor), "bottom-left\ncategories\n")
        self.set_user_choice("layout", kind="menu-style")
        self.prepare_now("grid")
        self.assertEqual(read(self.anchor), "top-left\ngrid\n")

    def test_menu_style_commands(self):
        self.set_system_default("plain")
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["menu-style", "list"])
        self.assertEqual([line.split("\t")[0] for line in out.getvalue().splitlines()],
                         ["layout", "classic", "categories", "grid"])
        self.assertEqual(set(fl.MENU_STYLE_CHOICES) - {fl.FOLLOW_LAYOUT}, set(fl.MENU_STYLES))
        with self.quiet():
            self.assertEqual(fl.main(["menu-style", "set", "ribbon"]), 1)
        self.assertFalse(os.path.exists(self.path("home/.config/flickos/menu-style")))
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fl.main(["menu-style", "set", "grid"]), 0)
        self.assertIn("Start menu style 'Grid' saved", out.getvalue())
        self.assertEqual(read(self.path("home/.config/flickos/menu-style")), "grid\n")
        self.assertEqual(read(self.anchor), "bottom-left\ngrid\n")     # the menu is on by default
        with self.quiet():
            self.assertEqual(fl.main(["set", "--launcher", "fuzzel"]), 0)
            self.assertEqual(fl.main(["set", "--menu-style", "categories"]), 0)
        self.assertFalse(os.path.exists(self.anchor))     # the style is kept while the menu is off
        with self.quiet():
            self.assertEqual(fl.main(["set", "--launcher", "menu", "--menu-style", "grid"]), 0)
        self.assertEqual(read(self.anchor), "bottom-left\ngrid\n")
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["menu-style", "current"])
        self.assertEqual(out.getvalue(), "grid\n")
        with self.quiet():
            self.assertEqual(fl.main(["set", "--menu-style", "layout"]), 0)
        self.assertEqual(read(self.anchor), "bottom-left\nclassic\n")

    def test_system_menu_style(self):
        self.write("etc/xdg/flickos/layouts.conf", "[Defaults]\nMenuStyle=grid\n")
        self.assertEqual(fl.resolve_menu_style().id, "grid")
        self.write("etc/xdg/flickos/layouts.conf", "[Defaults]\nMenuStyle=ribbon\n")
        with self.quiet():
            self.assertEqual(fl.resolve_menu_style().id, fl.FOLLOW_LAYOUT)

    def test_menu_style_goes_with_the_corner(self):
        self.make_layout("grid", extra="Menu=top-left\nMenuStyle=grid\n")
        self.set_user_choice("menu", kind="launcher")
        self.prepare_now("grid")
        self.assertEqual(read(self.anchor), "top-left\ngrid\n")
        mtime = os.stat(self.anchor).st_mtime_ns
        self.prepare_now("grid")
        self.assertEqual(os.stat(self.anchor).st_mtime_ns, mtime)      # unchanged: not written again
        self.prepare_now()
        self.assertEqual(read(self.anchor), "bottom-left\nclassic\n")

    def test_on_by_default(self):
        self.assertEqual(fl.resolve_launcher().id, "menu")
        self.prepare_now()
        self.assertEqual(read(self.anchor), "bottom-left\nclassic\n")
        self.assertEqual(self.menu_keybinds(), {key: ("yes", [fl.MENU_SUPER]) for key in fl.MENU_KEYS})
        self.assertEqual(self.launcher_bar()[0]["custom/launcher"]["on-click"], fl.MENU_TOGGLE)

    def test_off(self):
        self.set_user_choice("fuzzel", kind="launcher")
        self.assertEqual(fl.resolve_launcher().id, "fuzzel")
        self.prepare_now()
        self.assertFalse(os.path.exists(self.anchor))
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        bars = self.launcher_bar()
        self.assertEqual(bars[0]["custom/launcher"], {"format": "Apps"})
        self.assertNotIn("custom/launcher", bars[1])

    def test_off_generates_the_same_files_as_before(self):
        """Choosing the app launcher must leave every generated file as it was
        without the option (prepare without a launcher)."""
        self.set_user_choice("left-launcher", kind="clicks")
        self.set_user_choice("fuzzel", kind="launcher")
        self.prepare_now()
        with_choice = read(self.overlay_rcxml)
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style(), fl.labwc_themes(fl.styles()), fl.resolve_clicks())
        self.assertEqual(read(self.overlay_rcxml), with_choice)
        self.assertNotIn("flickos-menu", with_choice)

    def test_on(self):
        self.set_user_choice("menu", kind="launcher")
        self.prepare_now()
        self.assertEqual(read(self.anchor), "bottom-left\nclassic\n")
        self.assertEqual(self.menu_keybinds(), {key: ("yes", [fl.MENU_SUPER]) for key in fl.MENU_KEYS})
        default = fl.CLICKS[fl.DEFAULT_CLICKS]
        self.assertEqual(self.root_binds(), {"Left": fl.MENU_CLICK_ACTIONS[default.left],
                                             "Right": fl.MENU_CLICK_ACTIONS[default.right]})
        bars = self.launcher_bar()
        self.assertEqual(bars[0]["custom/launcher"], {"format": "Apps", "on-click": fl.MENU_TOGGLE,
                                                      "tooltip-format": fl.MENU_TOOLTIP})
        self.assertNotIn("custom/launcher", bars[1])    # a bar without the apps button stays as it is
        overlay = read(self.overlay_rcxml)
        self.assertIn('<keybind key="W-Return">', overlay)     # the system rc.xml's keys stay

    def test_on_with_other_clicks(self):
        self.set_user_choice("menu", kind="launcher")
        self.set_user_choice("left-launcher", kind="clicks")
        self.prepare_now()
        self.assertEqual(self.root_binds(), {"Left": fl.MENU_CLICK_ACTIONS["launcher"],
                                             "Right": fl.MENU_CLICK_ACTIONS["menu"]})

    def test_on_twice_keeps_one_binding_per_key(self):
        self.set_user_choice("menu", kind="launcher")
        self.prepare_now()
        self.prepare_now()
        top = ET.parse(self.overlay_rcxml).getroot()
        keys = [b.get("key") for k in top.findall("keyboard") for b in k.findall("keybind")]
        self.assertEqual(sorted(k for k in keys if k in fl.MENU_KEYS), sorted(fl.MENU_KEYS))

    def test_layout_without_a_corner(self):
        self.set_user_choice("menu", kind="launcher")
        self.prepare_now("nomenu")
        self.assertFalse(os.path.exists(self.anchor))
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_turning_it_off_removes_everything(self):
        self.set_user_choice("menu", kind="launcher")
        self.prepare_now()
        self.set_user_choice("fuzzel", kind="launcher")
        self.prepare_now()
        self.assertFalse(os.path.exists(self.anchor))
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        self.assertEqual(self.launcher_bar()[0]["custom/launcher"], {"format": "Apps"})

    def test_chosen_but_not_installed(self):
        self.installed = False
        self.set_user_choice("menu", kind="launcher")
        with self.quiet() as _, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fl.resolve_launcher().id, "fuzzel")
        self.assertIn("flickos-menu is not installed", err.getvalue())
        self.prepare_now()
        self.assertFalse(os.path.exists(self.anchor))

    def test_default_but_not_installed(self):
        """Without flickos-menu the app launcher is the default, quietly, also
        when the system default is the start menu."""
        self.installed = False
        self.set_system_default("menu", key="Launcher")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fl.resolve_launcher().id, "fuzzel")
        self.assertEqual(err.getvalue(), "")
        self.prepare_now()
        self.assertFalse(os.path.exists(self.anchor))
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_launcher_commands(self):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["launcher", "list"])
        self.assertEqual([line.split("\t")[0] for line in out.getvalue().splitlines()], ["fuzzel", "menu"])
        self.installed = False
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["launcher", "list"])
        self.assertEqual([line.split("\t")[0] for line in out.getvalue().splitlines()], ["fuzzel"])
        with self.quiet():
            self.assertEqual(fl.main(["launcher", "set", "menu"]), 1)     # not installed
        self.installed = True
        self.set_system_default("plain")
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fl.main(["launcher", "set", "menu"]), 0)
        self.assertIn("Apps button 'Start menu' saved", out.getvalue())
        self.assertEqual(read(self.path("home/.config/flickos/launcher")), "menu\n")
        self.assertEqual(read(self.anchor), "bottom-left\nclassic\n")
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["launcher", "current"])
        self.assertEqual(out.getvalue(), "menu\n")
        with self.quiet():
            self.assertEqual(fl.main(["set", "--launcher", "fuzzel"]), 0)
        self.assertFalse(os.path.exists(self.anchor))

    def test_system_default(self):
        self.set_system_default("fuzzel", key="Launcher")
        self.assertEqual(fl.resolve_launcher().id, "fuzzel")
        self.set_user_choice("menu", kind="launcher")
        self.assertEqual(fl.resolve_launcher().id, "menu")

    def test_set_live_starts_and_stops_the_daemon(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-0", LABWC_PID="1")
        self.set_system_default("plain")
        with mock.patch.object(fl.subprocess, "run"), mock.patch.object(fl, "restart_panel"), \
                mock.patch.object(fl, "sync_menu") as sync, self.quiet():
            fl.main(["launcher", "set", "menu"])
            sync.assert_called_with(True)
            fl.main(["set", "nomenu"])
            sync.assert_called_with(False)
            fl.main(["set", "plain"])
            sync.assert_called_with(True)
            fl.main(["launcher", "set", "fuzzel"])
            sync.assert_called_with(False)

    def test_sync_menu(self):
        with mock.patch.object(fl, "start_supervised") as start, mock.patch.object(fl, "stop") as stop, \
                mock.patch.object(fl, "managed_waybars", return_value=[]):
            with mock.patch.object(fl, "managed_menus", return_value=[]):
                fl.sync_menu(True)
                start.assert_called_once()
                self.assertEqual(start.call_args.args[0], ["flickos-menu", "daemon"])
                fl.sync_menu(False)
                stop.assert_not_called()
            start.reset_mock()
            with mock.patch.object(fl, "managed_menus", return_value=[42]), \
                    mock.patch.object(fl.os, "kill") as kill:
                fl.sync_menu(True)      # running: told to get the new layout's style ready
                start.assert_not_called()
                kill.assert_called_once_with(42, fl.signal.SIGWINCH)
                fl.sync_menu(False)
                stop.assert_called_once_with([42])

    def test_panel_starts_the_daemon_only_while_on(self):
        self.set_system_default("plain")

        def started():
            with mock.patch.object(fl, "supervise", return_value=0), \
                    mock.patch.object(fl, "start_supervised") as start, self.quiet():
                self.assertEqual(fl.main(["panel"]), 0)
            self.close_log()        # `panel` opens it once per process; this runs it twice
            return [c.args[0] for c in start.call_args_list], start.call_args_list

        self.set_user_choice("fuzzel", kind="launcher")
        self.prepare_now()
        commands, _ = started()
        self.assertNotIn(["flickos-menu", "daemon"], commands)
        self.set_user_choice("menu", kind="launcher")
        self.prepare_now()
        commands, calls = started()
        self.assertIn(["flickos-menu", "daemon"], commands)
        env = calls[commands.index(["flickos-menu", "daemon"])].args[1]
        self.assertNotIn("FLICKOS_LAYOUT", env)

    def test_only_menu_daemons_are_managed(self):
        for pid, comm, args in ((400, "flickos-menu", ["/usr/bin/python3", "/usr/bin/flickos-menu", "daemon"]),
                                (401, "flickos-menu", ["/usr/bin/python3", "/usr/bin/flickos-menu", "list"]),
                                (402, "python3", ["/usr/bin/python3", "/usr/bin/flickos-menu", "daemon"]),
                                (403, "flickos-menu", ["/usr/bin/python3", "/usr/bin/flickos-menu", "daemon",
                                                       "--request", "toggle"])):
            self.write(f"proc/{pid}/comm", comm + "\n")
            with open(self.path(f"proc/{pid}/cmdline"), "wb") as f:
                f.write(b"\0".join(a.encode() for a in args) + b"\0")
        with mock.patch.object(fl, "PROC", self.path("proc")):
            self.assertEqual(fl.managed_menus(), [400, 403])

    def test_commands_reach_the_daemon_without_python(self):
        """Clicks and the Super key signal the daemon with pkill; the Python
        command is only the fallback when no daemon runs."""
        self.assertTrue(fl.MENU_TOGGLE.startswith("pkill -USR1 "))
        self.assertIn("pkill -USR2 ", fl.MENU_SUPER)
        self.assertTrue(fl.MENU_SUPER.startswith("sh -c '"))     # labwc runs Execute without a shell
        for actions in fl.MENU_CLICK_ACTIONS.values():
            self.assertTrue(all(value.startswith("sh -c '") for name, value in actions if name == "Execute"))
        self.assertEqual(set(fl.MENU_CLICK_ACTIONS), set(fl.CLICK_ACTIONS))


class QuickSettingsTest(EngineTest):
    """Quick Settings (flickos-menu's second window): off by default, offered
    while flickos-menu is installed; while on, the overlay points the volume
    and battery icons, Super+A and desktop clicks at it. While off nothing of
    it exists (docs/design/flickos-quick-settings.md, ADR-003)."""

    BARS = ('[{"modules-left": ["custom/launcher"], "modules-right": ["tray", "wireplumber", "battery", "clock"],'
            ' "wireplumber": {"format": " ", "on-click": "pavucontrol"}}]\n')

    def setUp(self):
        super().setUp()
        self.make_layout("plain", extra="Menu=bottom-left\nQuick=bottom-right\n")
        self.write("layouts/plain/waybar.jsonc", self.BARS)
        self.make_layout("noquick", extra="Menu=bottom-left\n")
        self.installed = True
        patcher = mock.patch.object(fl, "installed", lambda program: self.installed or program != "flickos-menu")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.quick = os.path.join(self.root, fl.MENU_QUICK)
        self.anchor = os.path.join(self.root, fl.MENU_ANCHOR)
        self.set_system_default("plain")

    def prepare_now(self, layout_id="plain"):
        with self.quiet():
            self.assertTrue(fl.prepare(self.layout(layout_id), self.style(), fl.labwc_themes(fl.styles()),
                                       fl.resolve_clicks(), fl.resolve_launcher(), fl.resolve_menu_style(),
                                       fl.resolve_quick_settings()))

    def bar(self):
        with self.quiet():
            fl.waybar_command(self.layout("plain"), self.style())
        return fl.load_jsonc(os.path.join(self.root, "waybar/config.jsonc"))[0]

    def keybinds(self):
        top = ET.parse(self.overlay_rcxml).getroot()
        return [(b.get("key"), [a.findtext("command") or a.get("name") for a in b.findall("action")])
                for k in top.findall("keyboard") for b in k.findall("keybind") if b.get("key") == fl.QUICK_KEY]

    def root_binds(self):
        context = next(c for c in ET.parse(self.overlay_rcxml).getroot().iter("context") if c.get("name") == "Root")
        return {b.get("button"): fl.bind_actions(b) for b in context.findall("mousebind")}

    def test_layouts_corner(self):
        self.assertEqual(self.layout("plain").quick, "bottom-right")
        self.assertIsNone(self.layout("noquick").quick)
        self.make_layout("odd", extra="Quick=bottom-left\n")
        with self.quiet():
            self.assertIsNone(self.layout("odd").quick)

    def test_off_by_default(self):
        self.assertEqual(fl.resolve_quick_settings().id, "off")
        self.set_user_choice("fuzzel", kind="launcher")
        self.prepare_now()
        self.assertFalse(os.path.exists(self.quick))
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        self.assertNotIn(fl.QUICK_GROUP, self.bar())

    def test_off_generates_the_same_files_as_before(self):
        """Off must leave every generated file as it was without the choice
        (prepare without it), with and without the start menu."""
        for launcher in ("menu", "fuzzel"):
            with self.subTest(launcher=launcher):
                self.set_user_choice(launcher, kind="launcher")
                self.set_user_choice("left-launcher", kind="clicks")
                self.set_user_choice("off", kind="quick-settings")
                self.prepare_now()
                with_choice = read(self.overlay_rcxml)
                bar = self.bar()
                with self.quiet():
                    fl.prepare(self.layout("plain"), self.style(), fl.labwc_themes(fl.styles()), fl.resolve_clicks(),
                               fl.resolve_launcher(), fl.resolve_menu_style())
                self.assertEqual(read(self.overlay_rcxml), with_choice)
                self.assertEqual(self.bar(), bar)
                self.assertNotIn(fl.QUICK_KEY, with_choice)
                self.assertFalse(os.path.exists(self.quick))

    def test_on(self):
        self.set_user_choice("on", kind="quick-settings")
        self.prepare_now()
        self.assertEqual(read(self.quick), "bottom-right\n")
        self.assertEqual(self.keybinds(), [(fl.QUICK_KEY, [fl.QUICK_KEY_COMMAND])])
        bar = self.bar()
        self.assertEqual(bar["modules-right"], ["tray", fl.QUICK_GROUP, "clock"])
        self.assertEqual(bar["wireplumber"], {"format": " ", "on-click": fl.QUICK_TOGGLE,
                                              "on-click-right": fl.QUICK_MIXER})
        self.assertEqual(bar["battery"], {"on-click": fl.QUICK_TOGGLE})
        self.assertIn('<keybind key="W-Return">', read(self.overlay_rcxml))     # the system rc.xml's keys stay

    def test_on_without_the_start_menu(self):
        """Desktop clicks close Quick Settings; the launcher click is fuzzel's."""
        self.set_user_choice("fuzzel", kind="launcher")
        self.set_user_choice("on", kind="quick-settings")
        self.prepare_now()
        self.assertFalse(os.path.exists(self.anchor))
        default = fl.CLICKS[fl.DEFAULT_CLICKS]
        self.assertEqual(self.root_binds(), {"Left": fl.QUICK_CLICK_ACTIONS[default.left],
                                             "Right": fl.QUICK_CLICK_ACTIONS[default.right]})
        self.set_user_choice("left-launcher", kind="clicks")
        self.prepare_now()
        self.assertEqual(self.root_binds()["Left"], fl.QUICK_CLICK_ACTIONS["launcher"])
        self.assertIn("fuzzel", fl.QUICK_CLICK_ACTIONS["launcher"][0][1])
        self.assertIn("WINCH", fl.QUICK_CLICK_ACTIONS["launcher"][0][1])
        self.assertNotIn(fl.MENU_KEYS[0], read(self.overlay_rcxml))

    def test_replaces_the_systems_super_a(self):
        """labwc's defaults bind Super+A to ToggleMaximize; one binding is left."""
        rcxml = read(self.path("etc/xdg/labwc/rc.xml"))
        self.write("etc/xdg/labwc/rc.xml", rcxml.replace(
            "</keyboard>", '<keybind key="W-a"><action name="ToggleMaximize" /></keybind>\n</keyboard>', 1))
        self.set_user_choice("on", kind="quick-settings")
        self.prepare_now()
        self.prepare_now()
        self.assertEqual(self.keybinds(), [(fl.QUICK_KEY, [fl.QUICK_KEY_COMMAND])])

    def test_layout_without_a_corner(self):
        self.set_user_choice("fuzzel", kind="launcher")
        self.set_user_choice("on", kind="quick-settings")
        self.prepare_now("noquick")
        self.assertFalse(os.path.exists(self.quick))
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_turning_it_off_removes_everything(self):
        self.set_user_choice("on", kind="quick-settings")
        self.prepare_now()
        self.set_user_choice("off", kind="quick-settings")
        self.prepare_now()
        self.assertFalse(os.path.exists(self.quick))
        self.assertEqual(self.keybinds(), [])
        self.assertNotIn(fl.QUICK_GROUP, self.bar())

    def test_not_installed(self):
        self.installed = False
        self.set_user_choice("on", kind="quick-settings")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fl.resolve_quick_settings().id, "off")
        self.assertIn("flickos-menu is not installed", err.getvalue())
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["quick-settings", "list"])
        self.assertEqual([line.split("\t")[0] for line in out.getvalue().splitlines()], ["off"])

    def test_commands(self):
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["quick-settings", "list"])
        self.assertEqual([line.split("\t")[0] for line in out.getvalue().splitlines()], ["off", "on"])
        with self.quiet():
            self.assertEqual(fl.main(["quick-settings", "set", "maybe"]), 1)
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fl.main(["quick-settings", "set", "on"]), 0)
        self.assertIn("Quick Settings 'On' saved", out.getvalue())
        self.assertEqual(read(self.path("home/.config/flickos/quick-settings")), "on\n")
        self.assertEqual(read(self.quick), "bottom-right\n")
        with self.quiet(), contextlib.redirect_stdout(io.StringIO()) as out:
            fl.main(["quick-settings", "current"])
        self.assertEqual(out.getvalue(), "on\n")
        with self.quiet():
            self.assertEqual(fl.main(["quick-settings", "set", "default"]), 0)
        self.assertFalse(os.path.exists(self.quick))
        self.assertFalse(os.path.exists(self.path("home/.config/flickos/quick-settings")))

    def test_system_default(self):
        self.write("etc/xdg/flickos/layouts.conf", "[Defaults]\nLayout=plain\nQuickSettings=on\n")
        self.assertEqual(fl.resolve_quick_settings().id, "on")
        self.set_user_choice("off", kind="quick-settings")
        self.assertEqual(fl.resolve_quick_settings().id, "off")

    def test_state_and_history(self):
        with self.quiet():
            state = fl.state()
        self.assertEqual(state["quick-settings"]["current"], "off")
        self.assertEqual([c["id"] for c in state["quick-settings"]["choices"]], ["off", "on"])
        with self.quiet():
            fl.main(["quick-settings", "set", "on"])
        entries = [json.loads(line) for line in read(self.path("home/.local/state/flickos/history.jsonl"))
                   .splitlines()]
        self.assertEqual([(e["owner"], e["key"], e["old"], e["new"]) for e in entries],
                         [("flickos-layout", "quick-settings", "default", "on")])

    def test_set_live_starts_and_stops_the_daemon(self):
        """The daemon runs while the start menu or Quick Settings is on."""
        os.environ.update(WAYLAND_DISPLAY="wayland-0", LABWC_PID="1")
        with mock.patch.object(fl.subprocess, "run"), mock.patch.object(fl, "restart_panel"), \
                mock.patch.object(fl, "sync_menu") as sync, self.quiet():
            fl.main(["launcher", "set", "fuzzel"])
            sync.assert_called_with(False)
            fl.main(["quick-settings", "set", "on"])
            sync.assert_called_with(True)
            fl.main(["set", "noquick"])
            sync.assert_called_with(False)
            fl.main(["set", "plain"])
            sync.assert_called_with(True)
            fl.main(["quick-settings", "set", "off"])
            sync.assert_called_with(False)

    def test_panel_starts_the_daemon_for_quick_settings_alone(self):
        self.set_user_choice("fuzzel", kind="launcher")
        self.set_user_choice("on", kind="quick-settings")
        self.prepare_now()
        with mock.patch.object(fl, "supervise", return_value=0), \
                mock.patch.object(fl, "start_supervised") as start, self.quiet():
            self.assertEqual(fl.main(["panel"]), 0)
        self.assertIn(["flickos-menu", "daemon"], [c.args[0] for c in start.call_args_list])

    def test_commands_reach_the_daemon_without_python(self):
        """The click writes the request word, then signals; labwc runs Execute
        without a shell, waybar with one."""
        self.assertTrue(fl.QUICK_TOGGLE.startswith('printf quick > "$XDG_RUNTIME_DIR/flickos/menu/request"; '
                                                   'pkill -USR1 '))
        self.assertTrue(fl.QUICK_TOGGLE.endswith(" || flickos-menu quick"))
        self.assertEqual(fl.QUICK_KEY_COMMAND, "sh -c '" + fl.QUICK_TOGGLE + "'")
        self.assertNotIn("'", fl.QUICK_TOGGLE)
        self.assertEqual(set(fl.QUICK_CLICK_ACTIONS), set(fl.CLICK_ACTIONS))


class TilerFragmentTest(EngineTest):
    """flick-tiler's fragment in $XDG_RUNTIME_DIR/flickos/tiler/labwc.xml."""

    FRAGMENT = """<labwc_config>
  <!-- Generated by flick-tiler. -->
  <core><gap>8</gap></core>
  <regions><region name="ft1" x="0%" y="0%" width="100%" height="100%" /></regions>
  <windowRules><windowRule identifier="*"><action name="SnapToRegion" region="ft2" /></windowRule></windowRules>
  <keyboard>
    <keybind key="W-j"><action name="Execute"><command>flick-tiler focus next</command></action></keybind>
    <keybind key="W-e"><action name="Execute"><command>other</command></action></keybind>
  </keyboard>
</labwc_config>
"""

    def setUp(self):
        super().setUp()
        self.make_layout("plain")

    def prepare_plain(self):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS[fl.DEFAULT_CLICKS])

    def test_fragment_is_merged(self):
        self.write("run/flickos/tiler/labwc.xml", self.FRAGMENT)
        self.prepare_plain()
        top = ET.parse(self.overlay_rcxml).getroot()
        self.assertEqual(top.findtext("core/gap"), "8")
        self.assertEqual([r.get("name") for r in top.iter("region")], ["ft1"])
        self.assertEqual(top.find("windowRules/windowRule/action").get("region"), "ft2")
        keyboards = top.findall("keyboard")
        self.assertEqual(len(keyboards), 1)
        binds = [b for b in keyboards[0].findall("keybind") if b.get("key") == "W-e"]
        self.assertEqual([b.findtext("action/command") for b in binds], ["other"])
        self.assertIsNotNone(keyboards[0].find("default"))
        self.assertIn("W-Return", [b.get("key") for b in keyboards[0].findall("keybind")])

    def test_without_fragment_no_overlay(self):
        self.write("run/flickos/tiler/labwc.xml", self.FRAGMENT)
        self.prepare_plain()
        os.unlink(self.path("run/flickos/tiler/labwc.xml"))
        self.prepare_plain()
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_broken_fragment_is_ignored(self):
        self.write("run/flickos/tiler/labwc.xml", "<labwc_config>")
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS[fl.DEFAULT_CLICKS])
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_reconfigure_reloads_labwc_in_session(self):
        self.write("run/flickos/tiler/labwc.xml", self.FRAGMENT)
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        with self.quiet(), mock.patch.object(fl, "run_quiet") as run:
            self.assertEqual(fl.main(["reconfigure"]), 0)
        run.assert_called_once_with(["labwc", "--reconfigure"])
        self.assertTrue(os.path.exists(self.overlay_rcxml))


class AddonTest(EngineTest):
    """Add-ons: ~/.config/flickos/addons/NAME/ and ADDONS_DIR/NAME/."""

    LABWC = """<labwc_config>
  <keyboard>
    <keybind key="W-grave" description="Search your trail">
      <action name="Execute" command="trail pick" />
    </keybind>
    <keybind key="W-m"><action name="Execute"><command>trail mark</command></action></keybind>
  </keyboard>
</labwc_config>
"""
    WAYBAR = """// the add-on's button
{
    "custom/trail": {"exec": "trail status --waybar", "return-type": "json"},
    "clock": {"format": "{:%H}"}
}
"""

    def setUp(self):
        super().setUp()
        self.make_layout("plain")
        self.write("layouts/plain/waybar.jsonc", '[{"modules-right": ["clock", "custom/tiler", "tray"]}]\n')
        self.user_addons = os.path.join(self.home, ".config", fl.ADDONS_HOME)
        self.descriptions = os.path.join(self.root, fl.SHORTCUT_DESCRIPTIONS)

    def addon(self, name, files, system=False):
        base = self.path("addons") if system else os.path.relpath(self.user_addons, self.tmp)
        os.makedirs(self.path(f"{base}/{name}"), exist_ok=True)
        for filename, text in files.items():
            self.write(f"{base}/{name}/{filename}", text)
        return self.path(f"{base}/{name}")

    def prepare_plain(self):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS[fl.DEFAULT_CLICKS])

    def panel(self, **kwargs):
        with self.quiet():
            fl.update_waybar(self.root, self.layout("plain"), self.style(), found=fl.addons(), **kwargs)
        return fl.load_jsonc(f"{self.root}/waybar/config.jsonc")[0], read(f"{self.root}/waybar/style.css")

    def test_nothing_without_addons(self):
        """HIG INT-9: no overlay, no descriptions, the panel as it was."""
        os.makedirs(self.user_addons)
        self.prepare_plain()
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        self.assertFalse(os.path.exists(self.descriptions))
        bar, css = self.panel()
        self.assertEqual(bar["modules-right"], ["clock", "custom/tiler", "tray"])
        self.assertEqual(css.count("@import"), 2)

    def test_keybinds_merged_without_description(self):
        self.addon("trail", {"labwc.xml": self.LABWC})
        self.prepare_plain()
        binds = {b.get("key"): b for b in ET.parse(self.overlay_rcxml).getroot().iter("keybind")}
        self.assertEqual(binds["W-grave"].find("action").get("command"), "trail pick")
        self.assertNotIn(fl.ADDON_DESCRIPTION, binds["W-grave"].attrib)   # labwc would log an error
        self.assertIn("W-m", binds)
        self.assertEqual(json.loads(read(self.descriptions)), {"trail pick": "Search your trail"})

    def test_desktop_keys_win(self):
        """An add-on can't take a key the desktop binds, nor change other settings."""
        self.addon("greedy", {"labwc.xml": """<labwc_config>
  <core><gap>40</gap></core>
  <libinput><device category="touchpad"><tap>no</tap></device></libinput>
  <keyboard>
    <repeatRate>1</repeatRate>
    <keybind key="Return-W" description="Mine"><action name="Execute" command="mine" /></keybind>
    <keybind key="W-S-grave"><action name="Execute" command="ok" /></keybind>
  </keyboard>
  <windowRules><windowRule identifier="mine"><action name="Maximize" /></windowRule></windowRules>
</labwc_config>
"""})
        self.prepare_plain()
        top = ET.parse(self.overlay_rcxml).getroot()
        commands = [b.findtext("action/command") or b.find("action").get("command")
                    for b in top.iter("keybind") if fl.key_id(b.get("key")) == fl.key_id("W-Return")]
        self.assertEqual(len(commands), 1)
        self.assertNotEqual(commands[0], "mine")
        self.assertIn("W-S-grave", [b.get("key") for b in top.iter("keybind")])
        self.assertIsNone(top.find("core/gap"))
        self.assertIsNone(top.find("libinput"))
        self.assertIsNone(top.find("keyboard/repeatRate"))
        self.assertEqual(top.find("windowRules/windowRule").get("identifier"), "mine")

    def test_removing_addon_removes_its_files(self):
        folder = self.addon("trail", {"labwc.xml": self.LABWC})
        self.prepare_plain()
        shutil.rmtree(folder)
        self.prepare_plain()
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        self.assertFalse(os.path.exists(self.descriptions))

    def test_user_addon_wins(self):
        """An empty user folder turns off the system add-on of that name."""
        self.addon("trail", {"labwc.xml": self.LABWC}, system=True)
        self.addon("other", {"style.css": "\n"}, system=True)
        self.addon("trail", {})
        self.addon("Not An Id", {"labwc.xml": self.LABWC})
        found = fl.addons()
        self.assertEqual(list(found), ["other", "trail"])
        self.assertEqual(found["trail"], os.path.join(self.user_addons, "trail"))
        self.prepare_plain()
        self.assertFalse(os.path.exists(self.overlay_rcxml))

    def test_broken_labwc_is_left_out(self):
        self.addon("broken", {"labwc.xml": "<labwc_config>"})
        self.addon("trail", {"labwc.xml": self.LABWC})
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS[fl.DEFAULT_CLICKS])
        self.assertIn("add-on broken", stderr.getvalue())
        self.assertIn("W-grave", [b.get("key") for b in ET.parse(self.overlay_rcxml).getroot().iter("keybind")])

    def test_panel_button_and_style(self):
        style = self.addon("trail", {"waybar.jsonc": self.WAYBAR, "style.css": "#custom-trail {}\n"})
        bar, css = self.panel(phone=True)
        # After the phone's button, before the tiling button; only custom/ modules.
        self.assertEqual(bar["modules-right"], ["clock", fl.PHONE_MODULE, "custom/trail", "custom/tiler", "tray"])
        self.assertEqual(bar["custom/trail"]["exec"], "trail status --waybar")
        self.assertNotIn("clock", bar)
        imports = [line for line in css.splitlines() if line.startswith("@import")]
        self.assertEqual(imports[-1], f'@import url("{style}/style.css");')

    def test_broken_waybar_keeps_panel(self):
        self.addon("broken", {"waybar.jsonc": "[1, 2"})
        bar, _css = self.panel()
        self.assertEqual(bar["modules-right"], ["clock", "custom/tiler", "tray"])

    def test_addons_command(self):
        folder = self.addon("trail", {"labwc.xml": self.LABWC, "style.css": "\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(fl.main(["addons"]), 0)
        self.assertEqual(out.getvalue(), f"trail\t{folder}\tlabwc.xml,style.css\n")


class ControlFragmentTest(EngineTest):
    """flickos-control's input settings: control/labwc.xml and control/environment."""

    FRAGMENT = """<labwc_config>
  <!-- Generated by flickos-control. -->
  <libinput>
    <device category="touchpad"><tap>no</tap><naturalScroll>yes</naturalScroll></device>
    <device category="non-touch"><leftHanded>yes</leftHanded></device>
  </libinput>
  <keyboard><repeatRate>40</repeatRate><numlock>yes</numlock></keyboard>
</labwc_config>
"""

    def setUp(self):
        super().setUp()
        self.make_layout("plain")
        self.overlay_environment = os.path.join(self.root, "xdg/labwc/environment")

    def prepare_plain(self):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS[fl.DEFAULT_CLICKS])

    def test_libinput_and_keyboard_options_are_merged(self):
        self.write("run/flickos/control/labwc.xml", self.FRAGMENT)
        self.prepare_plain()
        top = ET.parse(self.overlay_rcxml).getroot()
        devices = top.findall("libinput/device")
        self.assertEqual([d.get("category") for d in devices], ["touchpad", "non-touch"])
        self.assertEqual(devices[0].findtext("tap"), "no")
        keyboard = top.findall("keyboard")[-1]
        self.assertEqual(keyboard.findtext("repeatRate"), "40")
        self.assertEqual(keyboard.findtext("numlock"), "yes")
        # The system rc.xml's keybinds are untouched.
        self.assertIn("W-Return", [b.get("key") for b in top.iter("keybind")])

    def test_devices_come_after_the_system_ones(self):
        """labwc uses the last category of a type: an administrator's own
        touchpad category stays but loses to the user's."""
        rcxml = self.path("etc/xdg/labwc/rc.xml")
        with open(rcxml, encoding="utf-8") as f:
            text = f.read()
        text = text.replace("</labwc_config>", "<libinput><device category=\"touchpad\"><tap>yes</tap></device>"
                                               "<device category=\"Magic Mouse\"><pointerSpeed>0.5</pointerSpeed>"
                                               "</device></libinput></labwc_config>")
        self.write("etc/xdg/labwc/rc.xml", text)
        self.write("run/flickos/control/labwc.xml", self.FRAGMENT)
        self.prepare_plain()
        top = ET.parse(self.overlay_rcxml).getroot()
        self.assertEqual(len(top.findall("libinput")), 1)
        self.assertEqual([d.get("category") for d in top.findall("libinput/device")],
                         ["touchpad", "Magic Mouse", "touchpad", "non-touch"])

    def test_magnifier_options_are_set(self):
        """flickos-control's zoom settings replace the system rc.xml's
        <magnifier> values; the ones it doesn't set stay."""
        rcxml = self.path("etc/xdg/labwc/rc.xml")
        with open(rcxml, encoding="utf-8") as f:
            text = f.read()
        text = text.replace("</labwc_config>", "<magnifier><width>-1</width><height>-1</height>"
                                               "<increment>0.5</increment></magnifier></labwc_config>")
        self.write("etc/xdg/labwc/rc.xml", text)
        self.write("run/flickos/control/labwc.xml", "<labwc_config><magnifier><width>400</width>"
                                                     "<height>400</height><useFilter>no</useFilter>"
                                                     "</magnifier></labwc_config>")
        self.prepare_plain()
        top = ET.parse(self.overlay_rcxml).getroot()
        self.assertEqual(len(top.findall("magnifier")), 1)
        self.assertEqual({o.tag: o.text for o in top.find("magnifier")},
                         {"width": "400", "height": "400", "increment": "0.5", "useFilter": "no"})

    def test_control_then_tiler(self):
        self.write("run/flickos/control/labwc.xml", self.FRAGMENT)
        self.write("run/flickos/tiler/labwc.xml", TilerFragmentTest.FRAGMENT)
        self.prepare_plain()
        top = ET.parse(self.overlay_rcxml).getroot()
        self.assertEqual(top.findtext("core/gap"), "8")
        self.assertEqual(len(top.findall("libinput/device")), 2)
        self.assertEqual(top.findall("keyboard")[-1].findtext("repeatRate"), "40")
        self.assertIn("W-j", [b.get("key") for b in top.iter("keybind")])

    def test_broken_control_fragment_keeps_tiling(self):
        self.write("run/flickos/control/labwc.xml", "<labwc_config>")
        self.write("run/flickos/tiler/labwc.xml", TilerFragmentTest.FRAGMENT)
        with self.quiet() as _, mock.patch.object(fl, "warn") as warn:
            fl.prepare(self.layout("plain"), self.style(), clicks=fl.CLICKS[fl.DEFAULT_CLICKS])
        self.assertIn("mouse, touchpad and keyboard", warn.call_args.args[0])
        self.assertEqual(ET.parse(self.overlay_rcxml).getroot().findtext("core/gap"), "8")

    def test_environment_has_the_system_lines_first(self):
        self.write("etc/xdg/labwc/environment", "XCURSOR_THEME=Adwaita\nXCURSOR_SIZE=24")
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=de\nXKB_DEFAULT_VARIANT=\n")
        self.prepare_plain()
        with open(self.overlay_environment, encoding="utf-8") as f:
            lines = [line for line in f.read().splitlines() if not line.startswith("#")]
        self.assertEqual(lines, ["XCURSOR_THEME=Adwaita", "XCURSOR_SIZE=24",
                                 "XKB_DEFAULT_LAYOUT=de", "XKB_DEFAULT_VARIANT="])
        # Only the environment: no rc.xml overlay is needed for it.
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        os.unlink(self.path("run/flickos/control/environment"))
        self.prepare_plain()
        self.assertFalse(os.path.exists(self.overlay_environment))

    def test_environment_d_of_the_system_folder_is_included(self):
        self.write("etc/xdg/labwc/environment.d/10-cursor.env", "XCURSOR_SIZE=32\n")
        self.write("etc/xdg/labwc/environment.d/notes.txt", "ignored\n")
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=fr\n")
        self.prepare_plain()
        with open(self.overlay_environment, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("XCURSOR_SIZE=32\nXKB_DEFAULT_LAYOUT=fr\n", text)
        self.assertNotIn("ignored", text)

    def test_doctor_warns_about_a_user_environment_only_with_a_layout(self):
        self.write("home/.config/labwc/environment", "FOO=1\n")
        self.assertEqual(fl.doctor_warnings(), [])
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=de\n")
        [warning] = fl.doctor_warnings()
        self.assertIn("keyboard layout", warning)


class WallpaperTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_layout("plain")
        self.make_layout("pretty", extra="Wallpaper=wallpaper.jpg\n")
        self.image = self.write("layouts/pretty/wallpaper.jpg", "jpeg")
        self.default = self.write("backgrounds/default.jpg", "jpeg")
        self.make_style("pictured", extra="Wallpaper=wallpaper.png\n")
        self.style_image = self.write("styles/pictured/wallpaper.png", "png")
        self.which = {"waypaper": "/usr/bin/waypaper"}
        for name, value in (("DEFAULT_WALLPAPER", self.default),
                            ("WALLPAPER_SWAP_SECONDS", 0)):
            patcher = mock.patch.object(fl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(fl.shutil, "which", self.which.get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def waypaper_config(self, text):
        return self.write("home/.config/waypaper/config.ini", text)

    def test_layout_then_default(self):
        self.assertEqual(self.layout("pretty").wallpaper, self.image)
        self.assertEqual(fl.wallpaper(self.layout("pretty")),
                         ("layout", self.image, ["swaybg", "-i", self.image, "-m", "fill", "-c", "#383c4a"]))
        self.assertEqual(fl.wallpaper(self.layout("plain"))[:2], ("default", self.default))
        self.assertEqual(fl.wallpaper(None)[:2], ("default", self.default))
        os.remove(self.default)
        self.assertEqual(fl.wallpaper(self.layout("plain")), ("default", None, ["swaybg", "-c", "#383c4a"]))

    def test_layout_then_style(self):
        pictured = fl.styles()["pictured"]
        self.assertEqual(pictured.wallpaper, self.style_image)
        self.assertIsNone(fl.styles()["dark"].wallpaper)
        self.assertEqual(fl.wallpaper(self.layout("plain"), pictured),
                         ("style", self.style_image,
                          ["swaybg", "-i", self.style_image, "-m", "fill", "-c", "#383c4a"]))
        self.assertEqual(fl.wallpaper(self.layout("pretty"), pictured)[:2], ("layout", self.image))
        self.assertEqual(fl.wallpaper(self.layout("plain"), fl.styles()["dark"])[:2], ("default", self.default))
        own = self.write("home/.config/flickos/wallpaper", "jpeg")
        self.assertEqual(fl.wallpaper(self.layout("plain"), pictured)[:2], ("user", own))

    def test_user_choices_win(self):
        own = self.write("home/.config/flickos/wallpaper", "jpeg")
        self.assertEqual(fl.wallpaper(self.layout("pretty"))[:2], ("user", own))
        mine = self.write("home/Pictures/mine.jpg", "jpeg")
        self.waypaper_config("[Settings]\nwallpaper = ~/Pictures/mine.jpg\n    ~/other.jpg\nmonitors = All\n")
        self.assertEqual(fl.wallpaper(self.layout("pretty")), ("waypaper", mine, ["waypaper", "--restore"]))

    def test_waypaper_state_file(self):
        self.waypaper_config("[Settings]\nuse_xdg_state = True\nwallpaper = ~/old.jpg\n")
        state = self.write("home/.local/state/waypaper/state.ini", "[State]\nwallpaper = /x/new.jpg\n")
        self.assertEqual(fl.waypaper_choice(), ("/x/new.jpg", state))

    def test_waypaper_choice_ignored_when_unusable(self):
        self.waypaper_config("[Settings]\nwallpaper =\n")
        self.assertIsNone(fl.waypaper_choice())
        self.waypaper_config("[Settings]\nwallpaper = /gone.jpg\n")
        self.assertEqual(fl.wallpaper(self.layout("pretty"))[0], "layout")
        self.write("home/Pictures/mine.jpg", "jpeg")
        self.waypaper_config("[Settings]\nwallpaper = ~/Pictures/mine.jpg\n")
        del self.which["waypaper"]
        self.assertEqual(fl.wallpaper(self.layout("pretty"))[0], "layout")
        self.waypaper_config("not an ini file")
        with self.quiet():
            self.assertIsNone(fl.waypaper_choice())

    def run_wallpaper(self):
        calls = []

        def fake_exec(file, args):
            calls.append(args)
            raise SystemExit(0)

        with mock.patch.object(fl.os, "execvp", fake_exec), self.quiet():
            try:
                status = fl.main(["wallpaper"])
            except SystemExit:
                status = None
        return status, calls

    def test_command_shows_the_layout_wallpaper(self):
        self.set_user_choice("pretty")
        status, calls = self.run_wallpaper()
        self.assertEqual(calls, [["swaybg", "-i", self.image, "-m", "fill", "-c", "#383c4a"]])

    def test_command_restores_waypaper_or_falls_back(self):
        self.set_user_choice("pretty")
        self.write("home/Pictures/mine.jpg", "jpeg")
        self.waypaper_config("[Settings]\nwallpaper = ~/Pictures/mine.jpg\n")
        with mock.patch.object(fl.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            status, calls = self.run_wallpaper()
        self.assertEqual((status, calls), (0, []))
        self.assertEqual(run.call_args.args[0], ["waypaper", "--restore"])
        with mock.patch.object(fl.subprocess, "run", return_value=mock.Mock(returncode=1)):
            status, calls = self.run_wallpaper()
        self.assertEqual(calls, [["swaybg", "-i", self.image, "-m", "fill", "-c", "#383c4a"]])

    def test_command_shows_the_style_wallpaper(self):
        self.set_user_choice("plain")
        self.set_user_choice("pictured", "style")
        status, calls = self.run_wallpaper()
        self.assertEqual(calls, [["swaybg", "-i", self.style_image, "-m", "fill", "-c", "#383c4a"]])
        self.write("home/Pictures/mine.jpg", "jpeg")
        self.waypaper_config("[Settings]\nwallpaper = ~/Pictures/mine.jpg\n")
        with mock.patch.object(fl.subprocess, "run", return_value=mock.Mock(returncode=1)):
            status, calls = self.run_wallpaper()
        self.assertEqual(calls, [["swaybg", "-i", self.style_image, "-m", "fill", "-c", "#383c4a"]])

    def test_command_without_layouts(self):
        shutil.rmtree(self.layouts_dir)
        status, calls = self.run_wallpaper()
        self.assertEqual(calls[0][:3], ["swaybg", "-i", self.default])

    def fake_swaybg(self, pid, image):
        self.write(f"proc/{pid}/comm", "swaybg\n")
        self.write(f"proc/{pid}/stat", f"{pid} (swaybg) S 1\n")
        self.write(f"proc/{pid}/environ", "WAYLAND_DISPLAY=wayland-1\0")
        with open(self.path(f"proc/{pid}/cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in ["swaybg", "-i", image, "-m", "fill"]) + b"\0")

    def test_restart_replaces_only_flickos_wallpapers(self):
        self.fake_swaybg(400, self.default)
        self.fake_swaybg(401, os.path.join(self.layouts_dir, "plain/other.jpg"))
        self.fake_swaybg(402, f"{self.home}/mine.jpg")
        self.fake_swaybg(403, self.style_image)
        with mock.patch.object(fl, "PROC", self.path("proc")):
            self.assertEqual(fl.managed_wallpapers(), [400, 401, 403])
            with mock.patch.object(fl, "stop") as stop, mock.patch.object(fl.subprocess, "run") as run:
                self.assertTrue(fl.restart_wallpaper(self.layout("pretty")))
        self.assertEqual(run.call_args.args[0], ["setsid", "-f", "swaybg", "-i", self.image, "-m", "fill",
                                                 "-c", "#383c4a"])
        self.assertEqual(run.call_args.kwargs["env"], {"WAYLAND_DISPLAY": "wayland-1"})
        stop.assert_called_once_with([400, 401, 403])

    def test_restart_replaces_a_user_style_or_layout_wallpaper(self):
        # Shown while a user's own style or layout was in use: a later set must
        # still replace it, also once that folder is gone.
        self.fake_swaybg(400, f"{self.home}/.local/share/flickos/styles/mine/wallpaper.png")
        self.fake_swaybg(401, f"{self.home}/.local/share/flickos/layouts/mine/wallpaper.jpg")
        self.fake_swaybg(402, f"{self.home}/.local/share/elsewhere.png")
        with mock.patch.object(fl, "PROC", self.path("proc")):
            self.assertEqual(fl.managed_wallpapers(), [400, 401])

    def test_restart_keeps_the_users_wallpaper(self):
        self.fake_swaybg(400, self.default)
        self.write("home/.config/flickos/wallpaper", "jpeg")
        with mock.patch.object(fl, "PROC", self.path("proc")), mock.patch.object(fl, "stop") as stop:
            self.assertFalse(fl.restart_wallpaper(self.layout("pretty")))
        stop.assert_not_called()

    def test_set_live_switches_wallpaper_only_for_a_new_layout_or_style(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-0", LABWC_PID="1")
        with mock.patch.object(fl.subprocess, "run"), mock.patch.object(fl, "restart_panel"), \
                mock.patch.object(fl, "restart_wallpaper") as restart, self.quiet():
            fl.main(["set", "pretty"])
            fl.main(["clicks", "set", "both-menu"])
            fl.main(["style", "set", "pictured"])
        self.assertEqual([(c.args[0].id, c.args[1].id) for c in restart.call_args_list],
                         [("pretty", "dark"), ("pretty", "pictured")])

    def test_doctor_reports_own_wallpaper(self):
        self.assertEqual(fl.doctor_warnings(), [])
        self.write("home/.config/flickos/wallpaper", "jpeg")
        self.assertIn("layouts and styles don't change it", fl.doctor_warnings()[0])
        self.write("home/Pictures/mine.jpg", "jpeg")
        config = self.waypaper_config("[Settings]\nwallpaper = ~/Pictures/mine.jpg\n")
        warnings = fl.doctor_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn(config, warnings[0])


class FilesTest(EngineTest):

    def test_write_atomic_replaces_and_leaves_no_temp_files(self):
        target = self.path("out/file")
        fl.write_atomic(target, "one\n")
        fl.write_atomic(target, "two\n")
        self.assertEqual(read(target), "two\n")
        self.assertEqual(os.listdir(self.path("out")), ["file"])

    def test_lock_is_exclusive(self):
        with fl.locked():
            with open(os.path.join(self.root, "layout.lock")) as other:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(os.path.join(self.root, "layout.lock")) as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_lock_gives_up_after_the_timeout(self):
        """A run that hangs while holding the lock must not keep the panel
        (or anything else autostart starts) waiting for the whole session."""
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        with open(os.path.join(self.root, "layout.lock"), "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with contextlib.redirect_stderr(io.StringIO()) as err, fl.locked(timeout=0):
                pass
        self.assertIn("carrying on without the lock", err.getvalue())

    def test_runtime_dir_permissions(self):
        self.make_layout("plain")
        with self.quiet():
            self.prepare("plain")
        self.assertEqual(os.stat(self.root).st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()


class HistoryTest(EngineTest):
    """Changes are recorded for Settings > History (flickos-control), in the
    format flickos-control reads (docs/design/flickos-history.md, ADR-002)."""

    def setUp(self):
        super().setUp()
        self.make_layout("flickos", order=10)
        self.make_layout("cupertino", order=20)
        self.history = os.path.join(self.home, ".local/state/flickos/history.jsonl")

    def entries(self):
        try:
            with open(self.history, encoding="utf-8") as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def run_quiet(self, *argv):
        with self.quiet():
            return fl.main(list(argv))

    def test_a_change_is_recorded(self):
        self.assertEqual(self.run_quiet("set", "cupertino"), 0)
        [entry] = self.entries()
        self.assertEqual({key: entry[key] for key in ("v", "owner", "key", "old", "new")},
                         {"v": 1, "owner": "flickos-layout", "key": "layout", "old": "default", "new": "cupertino"})
        self.assertRegex(entry["id"], r"^[0-9]+$")
        self.assertRegex(entry["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual(os.stat(self.history).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(self.history)).st_mode & 0o777, 0o700)

    def test_default_removes_the_choice_and_is_recorded(self):
        self.run_quiet("set", "cupertino")
        self.assertEqual(self.run_quiet("set", "default"), 0)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config/flickos/layout")))
        self.assertEqual(fl.resolve_layout(fl.layouts()).id, "flickos")
        self.assertEqual([(e["old"], e["new"]) for e in self.entries()],
                         [("default", "cupertino"), ("cupertino", "default")])
        self.assertEqual(self.run_quiet("clock", "set", "default"), 0)      # nothing to change, nothing recorded
        self.assertEqual(len(self.entries()), 2)

    def test_only_changes_that_show_are_recorded(self):
        self.run_quiet("set", "flickos")                    # the default, saved as a choice
        self.run_quiet("clock", "set", "24h")
        self.assertEqual(self.entries(), [])
        self.run_quiet("set", "cupertino", "--clicks", "both-menu")
        self.assertEqual([(e["key"], e["old"], e["new"]) for e in self.entries()],
                         [("layout", "flickos", "cupertino"), ("clicks", "default", "both-menu")])

    def test_off(self):
        self.write("etc/xdg/flickos/history.conf", "[History]\nEnabled=no\n")
        self.run_quiet("set", "cupertino")
        self.assertEqual(self.entries(), [])
        self.write("home/.config/flickos/history", "[History]\nEnabled=yes\n")    # the user's wins
        self.run_quiet("set", "flickos")
        self.assertEqual(len(self.entries()), 1)

    def test_a_history_that_cant_be_written_never_stops_the_change(self):
        self.write("home/.local/state/flickos", "a file where the folder should be\n")
        with self.quiet(), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fl.main(["set", "cupertino"]), 0)
        self.assertIn("history can't be written", err.getvalue())
        self.assertEqual(fl.resolve_layout(fl.layouts()).id, "cupertino")

    def test_trimmed_to_the_newest_half(self):
        with mock.patch.object(fl, "HISTORY_BYTES", 2000):
            for number in range(40):
                fl.record("clock", "24h", f"x{number}")
        entries = self.entries()
        self.assertLess(os.path.getsize(self.history), 2000)
        self.assertEqual(entries[-1]["new"], "x39")
        self.assertEqual([e["new"] for e in entries], [f"x{n}" for n in range(40 - len(entries), 40)])


class PhonePopupLayoutTest(EngineTest):
    """The phone popup's corner file, and the click that falls back to the menu."""

    def setUp(self):
        super().setUp()
        self.make_layout("plain", extra="Menu=bottom-left\nQuick=bottom-right\n")
        self.make_layout("noquick", extra="Menu=bottom-left\n")
        self.set_system_default("plain")

    def test_corner_only_while_the_phone_and_the_menu_are_there(self):
        layout, noquick = self.layout("plain"), self.layout("noquick")
        with mock.patch.object(fl, "phone_on", return_value=True), \
                mock.patch.object(fl.shutil, "which", return_value="/usr/bin/flickos-menu"):
            self.assertEqual(fl.phone_corner(layout), "bottom-right")
            self.assertIsNone(fl.phone_corner(noquick))
        with mock.patch.object(fl, "phone_on", return_value=False), \
                mock.patch.object(fl.shutil, "which", return_value="/usr/bin/flickos-menu"):
            self.assertIsNone(fl.phone_corner(layout))
        with mock.patch.object(fl, "phone_on", return_value=True), \
                mock.patch.object(fl.shutil, "which", return_value=None):
            self.assertIsNone(fl.phone_corner(layout))

    def test_file_starts_the_daemon_on_its_own(self):
        root = fl.runtime_root()
        os.makedirs(root, mode=0o700, exist_ok=True)
        self.assertFalse(fl.menu_daemon_wanted(root))
        fl.update_phone(root, "top-right")
        self.assertTrue(fl.phone_popup_on(root))
        self.assertTrue(fl.menu_daemon_wanted(root))
        self.assertEqual(read(os.path.join(root, fl.MENU_PHONE)), "top-right\n")
        fl.update_phone(root, "top-right")          # unchanged, so it is not rewritten
        self.assertEqual(read(os.path.join(root, fl.MENU_PHONE)), "top-right\n")
        fl.update_phone(root, None)
        self.assertFalse(fl.phone_popup_on(root))
        self.assertFalse(os.path.exists(os.path.join(root, fl.MENU_PHONE)))

    def test_click_falls_back_to_the_menu(self):
        self.assertNotIn("'", fl.PHONE_TOGGLE)
        self.assertIn('printf phone > "$XDG_RUNTIME_DIR/flickos/menu/request"', fl.PHONE_TOGGLE)
        self.assertTrue(fl.PHONE_TOGGLE.endswith("|| flickos-phone menu"))
