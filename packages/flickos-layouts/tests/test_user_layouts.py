"""Tests for users' own layouts (docs/design/flickos-ricing.md, phase 5 step
5b): the lookup, waybar only, `layout new`, `check --layout`, doctor, state,
explain and watch. Run: python3 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
from unittest import mock

from test_engine import PACKAGE, EngineTest, fl, read

LAYOUTS = os.path.join(PACKAGE, "usr/share/flickos/layouts")

COMMON_MODULES = """{
    "custom/launcher": {"format": " "},
    "custom/recording": {"exec": "true", "signal": 10},
    "custom/desktop": {"format": " "},
    "custom/tiler": {"exec": "true", "signal": 8},
    "clock": {}, "wireplumber": {}, "battery": {}, "tray": {}
}
"""
# A FlickOS layout as they are written: an include and an @import into common/.
FULL_BAR = """// Full: everything FlickOS's layouts have.
{"name": "bar", "position": "bottom", "include": "../common/modules.jsonc",
 "modules-left": ["custom/launcher"], "modules-center": ["clock", "custom/recording"],
 "modules-right": ["custom/tiler", "tray", "wireplumber", "battery", "custom/desktop"]}
"""


class UserLayoutTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.write("layouts/common/modules.jsonc", COMMON_MODULES)
        self.write("layouts/common/base.css", "#clock { color: @fg_color; }\n")
        self.flickos_layout("full", FULL_BAR, "Menu=bottom-left\nQuick=bottom-right\n")
        self.user_dir = self.path("home/.local/share/flickos/layouts")

    def flickos_layout(self, layout_id, bar, extra=""):
        self.write(f"layouts/{layout_id}/layout.ini", f"[Layout]\nName={layout_id.title()}\nOrder=10\n"
                                                      f"Waybar=waybar.jsonc\nStyle=style.css\n{extra}")
        self.write(f"layouts/{layout_id}/waybar.jsonc", bar)
        self.write(f"layouts/{layout_id}/style.css", '@import url("../common/base.css");\n')

    def user_layout(self, layout_id, ini="", bar=None, css=None):
        """A user's layout: a copy of Full with absolute paths, plus ini lines."""
        folder = os.path.join(self.user_dir, layout_id)
        common = os.path.join(self.layouts_dir, "common")
        self.write(f"home/.local/share/flickos/layouts/{layout_id}/layout.ini",
                   f"[Layout]\nName=Mine {layout_id}\nWaybar=waybar.jsonc\nStyle=style.css\n"
                   f"Menu=bottom-left\nQuick=bottom-right\n{ini}")
        self.write(f"home/.local/share/flickos/layouts/{layout_id}/waybar.jsonc",
                   bar if bar is not None else FULL_BAR.replace("../common", common))
        self.write(f"home/.local/share/flickos/layouts/{layout_id}/style.css",
                   css if css is not None else f'@import url("{common}/base.css");\n')
        return folder

    def layouts(self, users=None):
        with self.quiet():
            return fl.layouts(users)

    def main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            status = fl.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def problems(self, layout_id):
        with self.quiet():
            return [(p.level, p.message) for p in fl.layout_problems(layout_id)]

    def assert_problem(self, layout_id, level, text):
        found = self.problems(layout_id)
        self.assertTrue(any(lv == level and text in message for lv, message in found), found)


class LookupTest(UserLayoutTest):

    def test_users_after_flickos(self):
        folder = self.user_layout("mine")
        found = self.layouts()
        self.assertEqual(list(found), ["full", "mine"])
        self.assertTrue(found["mine"].user)
        self.assertFalse(found["full"].user)
        self.assertEqual(found["mine"].folder, folder)

    def test_another_package_through_xdg_data_dirs(self):
        self.write("data/flickos/layouts/pkg/layout.ini", "[Layout]\nName=Pkg\nWaybar=w.jsonc\nStyle=s.css\n")
        found = self.layouts()
        self.assertIn("pkg", found)
        self.assertFalse(found["pkg"].user)

    def test_a_users_layout_hides_flickos_one(self):
        self.user_layout("full")
        found = self.layouts()
        self.assertTrue(found["full"].user)
        self.assertEqual(fl.hidden_layouts(), [("full", os.path.join(self.layouts_dir, "full"))])
        with self.quiet():
            self.assertTrue(any("Your layout full hides" in w for w in fl.doctor_warnings()))

    def test_plain_session_leaves_them_out(self):
        self.user_layout("mine")
        with mock.patch.dict(os.environ, {"FLICKOS_PLAIN": "1"}):
            self.assertNotIn("mine", self.layouts())
            self.assertEqual(fl.hidden_layouts(), [])
            self.assertIn("mine", self.layouts(users=True))

    def test_waybar_only(self):
        self.user_layout("docked", "Dock=dock.config\nDockStyle=dock.css\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            layout = fl.layouts()["docked"]
        self.assertIsNone(layout.dock)
        self.assertIsNone(layout.dock_style)
        self.assertIn("waybar only", err.getvalue())
        self.assert_problem("docked", "error", "Dock= isn't read: your own layouts are waybar only")

    def test_deleted_layout_in_use_falls_back(self):
        self.user_layout("mine")
        self.write("home/.config/flickos/layout", "mine\n")
        self.assertEqual(fl.resolve_layout(self.layouts()).id, "mine")
        os.remove(os.path.join(self.user_dir, "mine/layout.ini"))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fl.resolve_layout(fl.layouts()).id, "full")
        self.assertIn("unknown layout 'mine'", err.getvalue())

    def test_state_says_whose(self):
        folder = self.user_layout("mine")
        with self.quiet():
            choices = {c["id"]: c for c in fl.state()["layout"]["choices"]}
        self.assertEqual((choices["mine"]["user"], choices["mine"]["folder"]), (True, folder))
        self.assertFalse(choices["full"]["user"])

    def test_chooser_says_yours(self):
        self.user_layout("mine")
        found = self.layouts()
        self.assertEqual(fl.item_comment(found["mine"]), "Yours")
        self.assertNotIn("Yours", fl.item_comment(found["full"]))

    def test_explain_labels_them_yours(self):
        folder = self.user_layout("mine")
        layout = self.layouts()["mine"]
        ctx = {"styles": {}, "root": self.root, "layout": layout, "addons": {}}
        self.assertEqual(fl.explain_label(os.path.join(folder, "style.css"), ctx), "the Mine mine layout, yours")
        self.assertEqual(fl.explain_label(os.path.join(folder, "extra.css"), ctx), "the Mine mine layout, yours")

    def test_the_generated_panel_uses_them(self):
        self.user_layout("mine")
        with self.quiet():
            fl.update_waybar(self.root, self.layouts()["mine"], self.style())
        bar = fl.load_jsonc(f"{self.root}/waybar/config.jsonc")[0]
        self.assertEqual(bar["include"], [os.path.join(self.layouts_dir, "common/modules.jsonc")])
        self.assertIn(os.path.join(self.user_dir, "mine/style.css"), read(f"{self.root}/waybar/style.css"))


class NewTest(UserLayoutTest):

    def test_copy_of_a_flickos_layout(self):
        status, out, err = self.main("layout", "new", "mybar", "--from", "full", "--name", "My Bar")
        self.assertEqual((status, err), (0, ""))
        folder = os.path.join(self.user_dir, "mybar")
        self.assertEqual(out.strip(), folder)
        common = os.path.join(self.layouts_dir, "common")
        self.assertIn(f'"include": "{common}/modules.jsonc"', read(f"{folder}/waybar.jsonc"))
        self.assertIn(f'@import url("{common}/base.css");', read(f"{folder}/style.css"))
        ini = read(f"{folder}/layout.ini")
        for line in ("Name=My Bar", "Comment=Based on Full", "Menu=bottom-left", "Quick=bottom-right"):
            self.assertIn(line + "\n", ini)
        self.assertNotIn("Preview=", ini)
        found = self.layouts()
        self.assertTrue(found["mybar"].user)
        self.assertEqual(self.problems("mybar"), [])          # the copy passes check

    def test_from_the_layout_in_use(self):
        self.flickos_layout("other", FULL_BAR, "Menu=bottom-left\n")
        self.write("home/.config/flickos/layout", "other\n")
        self.main("layout", "new", "mine")
        self.assertIn("Comment=Based on Other", read(os.path.join(self.user_dir, "mine/layout.ini")))

    def test_dock_and_desktops_left_out(self):
        self.flickos_layout("docked", FULL_BAR, "Dock=dock.config\nDockStyle=dock.css\nDesktops=4\n"
                                                "Pinned=a.desktop\n")
        self.write("layouts/docked/dock.config", "#Api2\nbar { pager {} }\n")
        self.write("layouts/docked/dock.css", "\n")
        status, _out, err = self.main("layout", "new", "mine", "--from", "docked")
        self.assertEqual(status, 0)
        self.assertIn("dock is left out", err)
        self.assertIn("desktops are left out", err)
        ini = read(os.path.join(self.user_dir, "mine/layout.ini"))
        self.assertNotRegex(ini, r"(?m)^(Dock|DockStyle|Desktops|Pinned)=")
        self.assertIn('add\n# "flickos/desktops"', ini)

    def test_desktops_kept_with_the_buttons(self):
        self.flickos_layout("desks", FULL_BAR.replace('["custom/launcher"]', '["custom/launcher", "flickos/desktops"]'),
                            "Desktops=4\n")
        self.main("layout", "new", "mine", "--from", "desks")
        self.assertIn("Desktops=4\n", read(os.path.join(self.user_dir, "mine/layout.ini")))

    def test_refusals(self):
        self.user_layout("taken")
        for args, text in ((("full",), "exists already"), (("taken",), "exists already"),
                           (("Bad Id",), "can't be a layout id"), (("x", "--from", "nope"), "unknown layout")):
            status, out, err = self.main("layout", "new", *args)
            self.assertEqual((status, out), (1, ""), args)
            self.assertIn(text, err)


class ShippedCopyTest(EngineTest):
    """layout new from each of FlickOS's real layouts: the copy passes check."""

    def test_copies_of_flickos_layouts(self):
        with mock.patch.object(fl, "LAYOUTS_DIR", LAYOUTS):
            for source in ("redmond", "cupertino", "traditional"):
                with self.subTest(layout=source), self.quiet():
                    self.assertEqual(fl.main(["layout", "new", f"my-{source}", "--from", source]), 0)
                    self.assertEqual([str(p) for p in fl.layout_problems(f"my-{source}")], [])
                    copy = fl.layouts()[f"my-{source}"]
                    self.assertIsNone(copy.dock)
                    self.assertEqual(copy.desktops, 1)
                    bars = fl.load_bars(copy)
                    self.assertTrue(all(os.path.isabs(p) for bar in bars for p in bar.get("include", [])))


class CheckTest(UserLayoutTest):

    def test_clean_layout(self):
        self.user_layout("mine")
        self.assertEqual(self.main("check", "--layout", "mine")[:2], (0, ""))

    def test_unknown(self):
        status, _out, err = self.main("check", "--layout", "nope")
        self.assertEqual(status, 1)
        self.assertIn("unknown layout 'nope'", err)

    def test_errors(self):
        self.user_layout("broken", bar="[{]")
        self.assert_problem("broken", "error", "")
        self.assertEqual(self.main("check", "--layout", "broken")[0], 1)
        self.user_layout("noinclude", bar='{"include": "nope.jsonc"}')
        self.assert_problem("noinclude", "error", "nope.jsonc not found")
        self.user_layout("noimport", css='@import url("../common/base.css");\n')
        self.assert_problem("noimport", "error", "@import ../common/base.css: no such file")
        self.write("home/.local/share/flickos/layouts/noname/layout.ini", "[Layout]\nWaybar=w.jsonc\n")
        self.assert_problem("noname", "error", "Name= is missing")

    def test_colors_written_out(self):
        folder = self.user_layout("colors", css="/* #ffffff in a comment */\n#clock {\n  color: #ff0000;\n"
                                                "  background: rgba(0, 0, 0, 0.5);\n}\n#battery { color: @fg_color; }\n")
        with self.quiet():
            found = [(p.path, p.line, p.level) for p in fl.layout_problems("colors")]
        css = os.path.join(folder, "style.css")
        self.assertEqual(found, [(css, 3, "warning"), (css, 4, "warning")])

    def test_what_a_bar_lacks(self):
        bar = '{"position": "top", "modules-left": ["clock", "custom/mine"], "modules-right": ["clock"]}'
        self.user_layout("bare", "Desktops=3\n", bar=bar)
        for text in ("custom/mine is in a bar but defined nowhere", "no custom/launcher", "no tray",
                     "no custom/recording", "no custom/desktop", "Quick=bottom-right, but no bottom bar",
                     "Desktops=3 without flickos/desktops"):
            self.assert_problem("bare", "warning", text)

    def test_dock_apps_button_counts(self):
        """A FlickOS layout whose dock runs DOCK_LAUNCHER needs no apps button in a bar."""
        bar = FULL_BAR.replace('"modules-left": ["custom/launcher"]', '"modules-left": []')
        self.flickos_layout("docked", bar, "Menu=top-left\nQuick=bottom-right\nDock=dock.config\nDockStyle=dock.css\n")
        self.write("layouts/docked/dock.css", "\n")
        self.write("layouts/docked/dock.config", '#Api2\nbar {\n  taskbar { }\n}\n')
        self.assert_problem("docked", "warning", "no custom/launcher")
        self.write("layouts/docked/dock.config",
                   '#Api2\nbar {\n  button { action[LeftClick] = Exec("flickos/launcher") }\n}\n')
        self.assertEqual(self.problems("docked"), [])

    def test_corners(self):
        self.user_layout("corner", bar=FULL_BAR.replace('"bottom"', '"top"').replace("../common",
                                                                                  self.layouts_dir + "/common"))
        self.assert_problem("corner", "warning", "Menu=bottom-left, but the apps button is in the top bar")
        self.assert_problem("corner", "warning", "Quick=bottom-right, but no bottom bar")

    def test_signal_clash(self):
        bar = FULL_BAR.replace("../common", self.layouts_dir + "/common").replace(
            '"modules-left": ["custom/launcher"]', '"modules-left": ["custom/launcher", "custom/mine"], '
                                                   '"custom/mine": {"exec": "date", "signal": 9}')
        self.user_layout("clash", bar=bar)
        self.assert_problem("clash", "warning", "custom/mine uses signal 9, which the phone button use")

    def test_desktop_buttons_count_as_a_switcher(self):
        bar = FULL_BAR.replace("../common", self.layouts_dir + "/common").replace(
            '["custom/launcher"]', '["custom/launcher", "flickos/desktops"]')
        self.user_layout("desks", "Desktops=4\n", bar=bar)
        self.assertEqual(self.problems("desks"), [])

    def test_check_everything_includes_layouts(self):
        self.user_layout("bare", bar='{"modules-left": ["clock"]}')
        with self.quiet():
            messages = [p.message for p in fl.all_problems()]
        self.assertTrue(any("no tray" in m for m in messages))


class WatchTest(UserLayoutTest):

    def actions(self, *relative, chosen_layout=fl.DEFAULT_CHOICE):
        with self.quiet():
            available = fl.styles()
            layout = fl.resolve_layout(fl.layouts())
        paths = {os.path.join(self.user_dir, r) for r in relative}
        return fl.watch_actions(paths, fl.resolve_style(available), available, fl.DEFAULT_CHOICE, layout,
                                chosen_layout)

    def test_the_layout_in_use(self):
        self.user_layout("mine")
        self.user_layout("other")
        self.write("home/.config/flickos/layout", "mine\n")
        self.assertEqual(self.actions("mine/waybar.jsonc", "mine/style.css"), [("panel", "mine")])
        self.assertEqual(self.actions("mine/layout.ini"), [("layout", "mine")])
        self.assertEqual(self.actions("mine/style.css", "mine/layout.ini"), [("layout", "mine")])
        self.assertEqual(self.actions("other/waybar.jsonc"), [("check-layout", "other")])

    def test_the_chosen_layout_while_broken(self):
        """A layout.ini that doesn't load leaves it out; fixing it applies it."""
        self.user_layout("mine")
        self.write("home/.local/share/flickos/layouts/mine/layout.ini", "[Layout]\nWaybar=waybar.jsonc\n")
        self.write("home/.config/flickos/layout", "mine\n")
        self.assertEqual(self.actions("mine/layout.ini", chosen_layout="mine"), [("layout", "mine")])


class WatchApplyTest(UserLayoutTest):

    def setUp(self):
        super().setUp()
        self.user_layout("mine")
        self.write("home/.config/flickos/layout", "mine\n")
        self.said = []
        for name, value in (("watch_say", self.said.append), ("reload_panel_programs", lambda l, s: ["panel"])):
            patcher = mock.patch.object(fl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_panel_reloads(self):
        with mock.patch.object(fl, "apply_choice") as apply:
            fl.watch_apply("panel", "mine")
        apply.assert_not_called()
        self.assertEqual(self.said, ["mine: panel reloaded"])

    def test_new_desktop_buttons_restart_the_panel(self):
        """The supervisor follows the desktops only if it started with buttons."""
        def reload(layout, style):
            fl.update_desktop_files(self.root, 4)
            return ["panel"]
        with mock.patch.object(fl, "reload_panel_programs", reload), \
                mock.patch.object(fl, "apply_choice", return_value=0) as apply:
            fl.watch_apply("panel", "mine")
        apply.assert_called_once_with(layout_id="mine")
        self.assertEqual(self.said, ["mine: applied"])

    def test_errors_stop_it(self):
        self.write("home/.local/share/flickos/layouts/mine/waybar.jsonc", "[{]")
        with mock.patch.object(fl, "apply_choice") as apply:
            fl.watch_apply("layout", "mine")
        apply.assert_not_called()
        self.assertEqual(self.said[-1], "mine: not applied, fix the errors above")

    def test_check_another(self):
        self.user_layout("other", bar='{"modules-left": ["clock"]}')
        fl.watch_apply("check-layout", "other")
        self.assertTrue(any("no tray" in line for line in self.said))
        self.assertEqual(self.said[-1], "other: no errors (not the layout in use)")


if __name__ == "__main__":
    import unittest
    unittest.main()
