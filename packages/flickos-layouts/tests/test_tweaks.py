"""Tests for the panel's tweaks and the check of users' CSS
(docs/design/flickos-ricing.md, phase 7, ADR-015): the tweaks imported last
and copied into the dock, a file GTK can't read left out (waybar would
stop), the cache, check, watch, explain, doctor, state, `tweaks new` and
the starter's selectors against every shipped layout's rules.
Run: python3 -m unittest discover -s tests
"""

import contextlib
import dataclasses
import glob
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from unittest import mock

from test_engine import PACKAGE, EngineTest, fl, read

CHECKER = os.path.join(PACKAGE, "usr/libexec/flickos/check-css")
SHIPPED = sorted(glob.glob(os.path.join(PACKAGE, "usr/share/flickos/layouts/*/*.css"))
                 + glob.glob(os.path.join(PACKAGE, "../flickos-style-seven/usr/share/flickos/layouts/*/*.css"))
                 + glob.glob(os.path.join(PACKAGE, "../flickos-style-aye3/usr/share/flickos/layouts/*/*.css"))
                 + glob.glob(os.path.join(PACKAGE, "../flickos-style-footprint/usr/share/flickos/layouts/*/*.css"))
                 + glob.glob(os.path.join(PACKAGE, "../flickos-style-elemental/usr/share/flickos/layouts/*/*.css"))
                 + glob.glob(os.path.join(PACKAGE, "../flickos-style-experience/usr/share/flickos/layouts/*/*.css"))
                 + glob.glob(os.path.join(PACKAGE, "../flickos-style-eleven/usr/share/flickos/layouts/*/*.css"))
                 + glob.glob(os.path.join(PACKAGE, "../flickos-style-tortuga/usr/share/flickos/layouts/*/*.css")))
SFWBAR_FILES = ("dock.css", "windowlist.css")
SFWBAR_SELECTORS = ("window#sfwbar", "grid#dock", "taskbar_popup")

# A stand-in for check-css: a file (or one it imports) with BROKEN in it
# fails at line 1, column 5; every run is logged.
FAKE_CHECKER = r'''#!/usr/bin/python3
import json, os, re, sys
with open(os.environ["CHECK_CSS_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
def broken(path, seen):
    if path in seen or not os.path.isfile(path):
        return None
    seen.add(path)
    text = open(path).read()
    if "BROKEN" in text:
        return path
    for target in re.findall(r'@import url\("([^"]+)"\)', text):
        found = broken(os.path.join(os.path.dirname(path), target), seen)
        if found:
            return found
    return None
for path in sys.argv[1:]:
    where = broken(path, set())
    result = {"path": path}
    if where:
        result["error"] = {"file": where, "line": 1, "column": 5, "message": "'BROKEN' is not a valid property name"}
    print(json.dumps(result))
'''


def uncommented(starter):
    """The starter with every example on: the lines that hold only a comment mark deleted."""
    return "".join(line for line in starter.splitlines(True) if line.rstrip("\n") not in ("/*", "*/"))


def rules(text):
    """[(selector, {property})] of a CSS file without nesting."""
    text = fl.CSS_COMMENT.sub("", text)
    found = []
    for selectors, body in re.findall(r"([^{}@;]+)\{([^{}]*)\}", text):
        properties = {part.split(":", 1)[0].strip() for part in body.split(";") if ":" in part}
        for selector in selectors.split(","):
            found.append((" ".join(selector.split()), properties))
    return found


def specificity(selector):
    """(ids, classes and pseudo-classes, types) of one selector."""
    simple = re.sub(r"\s*[>+~]\s*", " ", selector)
    ids = len(re.findall(r"#[\w-]+", simple))
    classes = len(re.findall(r"\.[\w-]+|:[\w-]+", simple))
    types = len(re.findall(r"(?:^|\s)[a-zA-Z][\w-]*", simple))
    return ids, classes, types


def subject(selector):
    return selector.split()[-1]


def same_subject(example, shipped):
    """Whether a shipped rule's subject may be the element an example's is."""
    mine, theirs = subject(example), subject(shipped)
    if mine == "*":
        return True
    ids = set(re.findall(r"#[\w-]+", mine))
    if ids:
        return bool(ids & set(re.findall(r"#[\w-]+", theirs)))
    tag = re.match(r"[a-zA-Z][\w-]*", mine)
    return bool(tag) and re.match(r"[a-zA-Z][\w-]*", theirs) is not None and \
        re.match(r"[a-zA-Z][\w-]*", theirs).group(0) == tag.group(0)


class TweaksTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_layout("plain")
        self.write("layouts/plain/waybar.jsonc", '[{"modules-right": ["clock", "custom/tiler", "tray"]}]\n')
        self.user_addons = os.path.join(self.home, ".config", fl.ADDONS_HOME)
        self.tweaks = os.path.join(self.home, ".config", fl.TWEAKS_HOME, fl.TWEAKS_STYLE)
        self.checker = self.write("bin/check-css", FAKE_CHECKER)
        os.chmod(self.checker, 0o755)
        self.log = self.path("check-css.log")
        for patcher in (mock.patch.object(fl, "CSS_CHECKER", self.checker),
                        mock.patch.dict(os.environ, {"CHECK_CSS_LOG": self.log})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def addon(self, name, files, system=False):
        base = self.path("addons") if system else self.user_addons
        for filename, text in files.items():
            self.write(os.path.relpath(os.path.join(base, name, filename), self.tmp), text)
        return os.path.join(base, name)

    def runs(self):
        """The checker's runs so far: [[path]]."""
        try:
            return [line.split() for line in read(self.log).splitlines()]
        except FileNotFoundError:
            return []

    def forget(self):
        """A new run of flickos-layout: only the cache file remembers."""
        fl.CSS_RESULTS.clear()

    def imports(self, css):
        return re.findall(r'@import url\("([^"]+)"\);', css)

    def panel_warnings(self, **kwargs):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            fl.update_waybar(self.root, self.layout("plain"), self.style(), found=fl.addons(), **kwargs)
        return read(f"{self.root}/waybar/style.css"), err.getvalue()

    def style(self):
        return fl.styles()["dark"]


class FloatingPanelTest(TweaksTest):
    """A layout's Floating= CSS, while floating-panel is on."""

    def floating_layout(self):
        path = os.path.join(self.tmp, "floating.css")
        with open(path, "w", encoding="utf-8") as f:
            f.write("window#waybar { background: transparent; }\n")
        full = os.path.join(self.tmp, "floating-full.css")
        with open(full, "w", encoding="utf-8") as f:
            f.write("window#waybar > box { margin: 0; }\n")
        return dataclasses.replace(self.layout("plain"), floating=path, floating_full=full)

    def update(self, layout, floating):
        with contextlib.redirect_stderr(io.StringIO()):
            fl.update_waybar(self.root, layout, self.style(), floating=floating)
        return read(f"{self.root}/waybar/style.css"), read(f"{self.root}/waybar/config.jsonc")

    def state(self):
        return f"{self.root}/waybar/{fl.PANEL_STATE}"

    def test_off_generates_nothing(self):
        layout = self.floating_layout()
        css, config = self.update(layout, False)
        self.assertNotIn(layout.floating, self.imports(css))
        self.assertNotIn("reload_style_on_change", config)
        self.assertFalse(os.path.exists(self.state()))

    def test_a_layout_without_it_stays_as_it_is(self):
        css, config = self.update(self.layout("plain"), True)
        self.assertNotIn("reload_style_on_change", config)
        self.assertFalse(os.path.exists(self.state()))

    def test_on_imports_the_css_then_the_state_that_changes_it(self):
        layout = self.floating_layout()
        css, config = self.update(layout, True)
        self.assertEqual(self.imports(css)[-2:], [layout.floating, self.state()])
        self.assertIn('"reload_style_on_change": true', config)
        self.assertEqual(read(self.state()), "")

    def test_on_writes_the_full_look_beside_the_state(self):
        layout = self.floating_layout()
        self.update(layout, True)
        self.assertEqual(self.imports(read(f"{self.root}/waybar/{fl.PANEL_FULL}")), [layout.floating_full])

    def test_on_keeps_the_height_of_the_bar(self):
        layout = self.floating_layout()
        self.assertEqual(json.loads(self.update(layout, True)[1].split("\n", 1)[1])[0].get("height"),
                         json.loads(self.update(layout, False)[1].split("\n", 1)[1])[0].get("height"))

    def test_a_new_panel_keeps_the_state_the_tiler_wrote(self):
        layout = self.floating_layout()
        self.update(layout, True)
        fl.write_atomic(self.state(), "/* full */\n")
        self.update(layout, True)
        self.assertEqual(read(self.state()), "/* full */\n")

    def test_turning_it_off_removes_the_state(self):
        layout = self.floating_layout()
        self.update(layout, True)
        self.update(layout, False)
        self.assertFalse(os.path.exists(self.state()))
        self.assertFalse(os.path.exists(f"{self.root}/waybar/{fl.PANEL_FULL}"))


class FloatingChoiceTest(TweaksTest):
    """The choice, and which layouts offer it."""

    def layout_folder(self, keys):
        folder = os.path.join(self.tmp, "keys")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "layout.ini"), "w", encoding="utf-8") as f:
            f.write(f"[Layout]\nName=Keys\nWaybar=w.jsonc\nStyle=s.css\n{keys}")
        return folder

    def test_off_by_default(self):
        self.assertEqual(fl.resolve_floating_panel().id, "off")

    def test_redmond_alone_floats(self):
        shipped = os.path.join(PACKAGE, "usr/share/flickos/layouts")
        for folder in glob.glob(f"{shipped}/*/layout.ini"):
            layout = fl.load_layout(os.path.dirname(folder))
            self.assertEqual(layout.floating is not None, layout.id == "redmond", layout.id)

    def test_redmonds_files_are_there(self):
        layout = fl.load_layout(os.path.join(PACKAGE, "usr/share/flickos/layouts/redmond"))
        self.assertTrue(os.path.isfile(layout.floating))
        self.assertTrue(os.path.isfile(layout.floating_full))

    def test_needs_both_files(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            layout = fl.load_layout(self.layout_folder("Floating=f.css\n"))
        self.assertIsNone(layout.floating)
        self.assertIn("FloatingFull", err.getvalue())

    def test_a_users_layout_cant_float(self):
        with contextlib.redirect_stderr(io.StringIO()):
            layout = fl.load_layout(self.layout_folder("Floating=f.css\nFloatingFull=g.css\n"), user=True)
        self.assertIsNone(layout.floating)
        self.assertIsNone(layout.floating_full)

    def test_state_says_whether_the_layout_offers_it(self):
        with contextlib.redirect_stderr(io.StringIO()):
            found = fl.state()
        self.assertEqual(found["floating-panel"]["current"], "off")
        self.assertIn("offered", found["floating-panel"])

    def test_set_saves_and_records_it(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fl.apply_choice(floating_id="on"), 0)
            self.assertEqual(fl.resolve_floating_panel().id, "on")
            self.assertEqual(fl.apply_choice(floating_id="default"), 0)
        self.assertEqual(fl.resolve_floating_panel().id, "off")

    def test_a_layout_can_float_by_default(self):
        """FloatingDefault=on: the choice is on until someone says otherwise."""
        layout = fl.load_layout(self.layout_folder("Floating=f.css\nFloatingFull=g.css\nFloatingDefault=on\n"))
        self.assertTrue(layout.floating_default)
        self.assertEqual(fl.resolve_floating_panel(layout).id, "on")

    def test_floating_by_default_needs_the_css(self):
        layout = fl.load_layout(self.layout_folder("FloatingDefault=on\n"))
        self.assertFalse(layout.floating_default)
        self.assertEqual(fl.resolve_floating_panel(layout).id, "off")

    def test_the_users_choice_beats_the_layouts_default(self):
        layout = fl.load_layout(self.layout_folder("Floating=f.css\nFloatingFull=g.css\nFloatingDefault=on\n"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fl.apply_choice(floating_id="off"), 0)
        self.assertEqual(fl.resolve_floating_panel(layout).id, "off")

    def test_no_layout_of_flickos_own_floats_by_default(self):
        """ADR-003 of the floating panel: it would reshape everyone's panel at an update."""
        shipped = os.path.join(PACKAGE, "usr/share/flickos/layouts")
        for folder in glob.glob(f"{shipped}/*/layout.ini"):
            self.assertFalse(fl.load_layout(os.path.dirname(folder)).floating_default, folder)

    def test_an_unknown_choice_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fl.apply_choice(floating_id="sideways"), 1)


class PanelTest(TweaksTest):

    def test_nothing_runs_without_css_of_the_users(self):
        """PERF: no child for users who have none."""
        self.addon("sys", {"style.css": "#clock { color: @fg_color; }\n"}, system=True)
        css, err = self.panel_warnings()
        self.assertEqual(self.runs(), [])
        self.assertEqual(err, "")
        self.assertNotIn("tweaks", css)

    def test_tweaks_imported_last(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "#clock { padding: 0 9px; }\n")
        self.addon("mine", {"style.css": "#clock { color: @fg_color; }\n"})
        css, err = self.panel_warnings()
        self.assertEqual(err, "")
        self.assertEqual(self.imports(css)[-1], self.tweaks)
        self.assertEqual(self.imports(css)[-2], os.path.join(self.user_addons, "mine/style.css"))
        self.assertTrue(css.rstrip().endswith(f'@import url("{self.tweaks}");'))
        self.assertEqual(self.runs(), [[os.path.join(self.user_addons, "mine/style.css"), self.tweaks]])

    def test_broken_tweaks_left_out(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "#clock { BROKEN: 1px; }\n")
        css, err = self.panel_warnings()
        self.assertNotIn(self.tweaks, css)
        self.assertIn(f"{fl.shown_path(self.tweaks)}:1:5: 'BROKEN' is not a valid property name", err)
        self.assertIn("left out of the panel", err)

    def test_broken_import_named(self):
        """The error is in the file it is in, and says who imported it."""
        self.write(os.path.relpath(self.tweaks, self.tmp), '@import url("more.css");\n')
        more = self.write(os.path.relpath(os.path.join(os.path.dirname(self.tweaks), "more.css"), self.tmp),
                          "BROKEN\n")
        css, err = self.panel_warnings()
        self.assertNotIn(self.tweaks, css)
        self.assertIn(f"{fl.shown_path(more)}:1:5: 'BROKEN' is not a valid property name "
                      f"(imported by {fl.shown_path(self.tweaks)})", err)

    def test_users_addon_css_left_out_systems_unchecked(self):
        mine = self.addon("mine", {"style.css": "BROKEN\n"})
        self.addon("sys", {"style.css": "#clock { color: @fg_color; }\n"}, system=True)
        css, _err = self.panel_warnings()
        self.assertNotIn(os.path.join(mine, "style.css"), self.imports(css))
        self.assertIn(self.path("addons/sys/style.css"), self.imports(css))
        self.assertEqual(self.runs(), [[os.path.join(mine, "style.css")]])

    def test_users_layout_css_replaced_by_base(self):
        self.write("layouts/common/base.css", "* { border: none; }\n")
        folder = os.path.join(self.home, ".local/share/flickos/layouts/mine")
        self.write(os.path.relpath(folder, self.tmp) + "/layout.ini",
                   "[Layout]\nName=Mine\nWaybar=waybar.jsonc\nStyle=style.css\n")
        self.write(os.path.relpath(folder, self.tmp) + "/waybar.jsonc", '[{"modules-right": ["clock"]}]\n')
        self.write(os.path.relpath(folder, self.tmp) + "/style.css", "BROKEN\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            fl.update_waybar(self.root, fl.layouts()["mine"], self.style())
        css = read(f"{self.root}/waybar/style.css")
        self.assertNotIn(os.path.join(folder, "style.css"), css)
        self.assertEqual(self.imports(css), [self.style().waybar, os.path.join(self.layouts_dir, "common/base.css")])
        self.assertIn("left out of the panel", err.getvalue())

    def test_flickos_layout_css_unchecked(self):
        self.write("layouts/plain/style.css", "BROKEN\n")
        self.panel_warnings()
        self.assertEqual(self.runs(), [])

    def test_plain_session_leaves_tweaks_out(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "#clock { padding: 0; }\n")
        with mock.patch.dict(os.environ, {"FLICKOS_PLAIN": "1"}):
            css, _err = self.panel_warnings()
            self.assertIsNone(fl.tweaks_css())
        self.assertNotIn(self.tweaks, css)
        self.assertEqual(self.runs(), [])

    def test_checker_missing_uses_it_unchecked(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "#clock { padding: 0; }\n")
        with mock.patch.object(fl, "CSS_CHECKER", self.path("missing")):
            css, err = self.panel_warnings()
        self.assertEqual(self.imports(css)[-1], self.tweaks)
        self.assertEqual(err, "")


class CacheTest(TweaksTest):

    def setUp(self):
        super().setUp()
        self.write(os.path.relpath(self.tweaks, self.tmp), '@import url("more.css");\n#clock { padding: 0; }\n')
        self.more = self.write(os.path.relpath(os.path.join(os.path.dirname(self.tweaks), "more.css"), self.tmp),
                               "#tray { padding: 0; }\n")

    def check(self):
        self.forget()
        return fl.css_errors([self.tweaks])

    def test_passed_files_not_parsed_again(self):
        self.assertEqual(self.check(), {})
        self.assertEqual(self.check(), {})
        self.assertEqual(len(self.runs()), 1)
        cache = json.loads(read(os.path.join(self.home, ".cache", fl.CSS_CHECKED)))
        self.assertEqual(list(cache), [self.tweaks])

    def test_a_change_in_an_import_parses_again(self):
        self.check()
        self.write(os.path.relpath(self.more, self.tmp), "#tray { padding: 1px; }\n")
        self.check()
        self.assertEqual(len(self.runs()), 2)

    def test_a_gtk_update_parses_again(self):
        self.check()
        with mock.patch.object(fl, "gtk_version", return_value="libgtk-3.so.0.9999.0"):
            self.check()
        self.assertEqual(len(self.runs()), 2)

    def test_failures_not_kept(self):
        self.check()
        self.write(os.path.relpath(self.more, self.tmp), "BROKEN\n")
        self.assertEqual(list(self.check()), [self.tweaks])
        self.assertEqual(list(self.check()), [self.tweaks])
        self.assertEqual(len(self.runs()), 3)
        cache = json.loads(read(os.path.join(self.home, ".cache", fl.CSS_CHECKED)))
        self.assertEqual(cache, {})

    def test_one_run_asks_once(self):
        """The panel and the dock in one run: one child."""
        self.write(os.path.relpath(self.more, self.tmp), "BROKEN\n")
        fl.css_errors([self.tweaks])
        fl.css_errors([self.tweaks])
        self.assertEqual(len(self.runs()), 1)


class DockTweaksTest(TweaksTest):

    def setUp(self):
        super().setUp()
        self.write("layouts/sf/layout.ini", "[Layout]\nName=Sf\nWaybar=waybar.jsonc\nStyle=style.css\n"
                   "Dock=dock.config\nDockStyle=dock.css\n")
        self.write("layouts/sf/waybar.jsonc", "{}\n")
        self.write("layouts/sf/style.css", "\n")
        self.write("layouts/sf/dock.config", "#api2\nbar {\n  taskbar {}\n}\n")
        self.write("layouts/sf/dock.css", "grid#dock { color: @fg_color; }\n")

    def dock_css(self):
        with contextlib.redirect_stderr(io.StringIO()):
            fl.update_dock(self.root, fl.layouts()["sf"], self.style())
        return read(f"{self.root}/dock/sfwbar.config").split("\n#CSS\n")[1]

    def test_tweaks_after_the_docks_css(self):
        self.write(os.path.relpath(self.tweaks, self.tmp),
                   '@import url("more.css");\ngrid#dock { background-image: url("dot.png"); }\n')
        self.write(os.path.relpath(os.path.join(os.path.dirname(self.tweaks), "more.css"), self.tmp), "\n")
        css = self.dock_css()
        folder = os.path.dirname(self.tweaks)
        self.assertLess(css.index("grid#dock { color: @fg_color; }"), css.index(f"/* Your tweaks: {self.tweaks} */"))
        self.assertIn(f'@import url("{folder}/more.css");', css)
        self.assertIn(f'background-image: url("{folder}/dot.png")', css)

    def test_broken_tweaks_not_in_the_dock(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "BROKEN\n")
        self.assertNotIn("BROKEN", self.dock_css())

    def test_explain_dock(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "grid#dock { margin: 0; }\n")
        self.set_user_choice("sf")
        self.dock_css()
        self.assertIn("(your tweaks)", "\n".join(fl.explain("dock")))


class ToolsTest(TweaksTest):

    def test_check_names_the_line(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "BROKEN\n")
        with contextlib.redirect_stderr(io.StringIO()):
            problems = [str(p) for p in fl.all_problems()]
        self.assertIn(f"{self.tweaks}:1: error: column 5: 'BROKEN' is not a valid property name; waybar would stop, "
                      "so the panel leaves this file out", problems)

    def test_check_layout_of_the_users(self):
        folder = os.path.join(self.home, ".local/share/flickos/layouts/mine")
        self.write(os.path.relpath(folder, self.tmp) + "/layout.ini",
                   "[Layout]\nName=Mine\nWaybar=waybar.jsonc\nStyle=style.css\n")
        self.write(os.path.relpath(folder, self.tmp) + "/waybar.jsonc", '[{"modules-right": ["clock"]}]\n')
        self.write(os.path.relpath(folder, self.tmp) + "/style.css", "BROKEN\n")
        with contextlib.redirect_stderr(io.StringIO()):
            errors = [p for p in fl.layout_problems("mine") if p.level == "error"]
        self.assertEqual([(p.path, p.line) for p in errors], [(os.path.join(folder, "style.css"), 1)])
        self.assertIn("FlickOS's base.css in its place", errors[0].message)

    def test_check_users_addon(self):
        mine = self.addon("mine", {"style.css": "BROKEN\n"})
        self.assertEqual([(p.path, p.level) for p in fl.addon_problems()], [(os.path.join(mine, "style.css"), "error")])

    def test_doctor_and_state(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "BROKEN\n")
        with contextlib.redirect_stderr(io.StringIO()):
            found = fl.state()
        self.assertTrue(found["tweaks"])
        self.assertTrue(any("is left out of the panel" in w and "tweaks/style.css" in w for w in found["warnings"]))
        os.remove(self.tweaks)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(fl.state()["tweaks"])

    def test_explain_panel(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "#clock { padding: 0; }\n")
        self.set_user_choice("plain")
        self.panel_warnings()
        self.assertIn(f"{fl.shown_path(self.tweaks)} (your tweaks)", "\n".join(fl.explain("panel")))
        self.write(os.path.relpath(self.tweaks, self.tmp), "BROKEN\n")
        self.panel_warnings()
        self.assertIn("(your tweaks: left out", "\n".join(fl.explain("panel")))

    def test_watch_action(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "\n")
        style = self.style()
        actions = fl.watch_actions({self.tweaks}, style, {"dark": style})
        self.assertEqual(actions, [("tweaks", None)])

    def test_watch_keeps_the_panel_on_an_error(self):
        self.write(os.path.relpath(self.tweaks, self.tmp), "BROKEN\n")
        with mock.patch.object(fl, "reload_panel_programs") as reload, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            fl.watch_apply("tweaks", None)
        reload.assert_not_called()
        self.assertIn("the panel is as it was", out.getvalue())
        self.write(os.path.relpath(self.tweaks, self.tmp), "#clock { padding: 0; }\n")
        self.forget()
        with mock.patch.object(fl, "reload_panel_programs", return_value=["panel"]) as reload, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            fl.watch_apply("tweaks", None)
        reload.assert_called_once()
        self.assertIn("tweaks: panel reloaded", out.getvalue())


class TweaksNewTest(TweaksTest):

    def new(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = fl.main(["tweaks", "new", *args])
        return status, out.getvalue(), err.getvalue()

    def test_writes_the_starter_once(self):
        status, out, _err = self.new()
        self.assertEqual((status, out), (0, self.tweaks + "\n"))
        self.assertEqual(read(self.tweaks), fl.tweaks_starter())
        self.write(os.path.relpath(self.tweaks, self.tmp), "mine\n")
        status, _out, err = self.new()
        self.assertEqual(status, 1)
        self.assertIn("--force", err)
        self.assertEqual(read(self.tweaks), "mine\n")
        self.assertEqual(self.new("--force")[0], 0)
        self.assertEqual(read(self.tweaks), fl.tweaks_starter())

    def test_starter_changes_nothing_until_edited(self):
        """Every example is commented out."""
        self.assertEqual(rules(fl.tweaks_starter()), [])

    def test_examples_uncommented_are_rules(self):
        """As the header says: delete the two lines that hold only a mark."""
        text = uncommented(fl.tweaks_starter())
        self.assertEqual(len(rules(text)), sum(selector.count(",") + 1 for _t, selector, _d in fl.TWEAKS_EXAMPLES))


class StarterSelectorsTest(unittest.TestCase):
    """Each example wins over every shipped layout's own rule for the same
    property on the same element (the spike: `* { font-size }` lost to
    Redmond's #clock and Cupertino's window#waybar.topbar *). Tweaks come
    last, so as strong is enough."""

    def test_examples_win(self):
        self.assertTrue(SHIPPED)
        shipped = []
        for path in SHIPPED:
            program = "sfwbar" if os.path.basename(path) in SFWBAR_FILES else "waybar"
            shipped += [(program, path, selector, properties) for selector, properties in rules(read(path))]
        checked = 0
        for title, selectors, declarations in fl.TWEAKS_EXAMPLES:
            properties = {line.split(":", 1)[0].strip() for line in declarations}
            for selector in (" ".join(s.split()) for s in selectors.split(",")):
                program = "sfwbar" if any(word in selector for word in SFWBAR_SELECTORS) else "waybar"
                for their_program, path, theirs, their_properties in shipped:
                    if their_program != program or not properties & their_properties \
                            or not same_subject(selector, theirs):
                        continue
                    checked += 1
                    self.assertGreaterEqual(specificity(selector), specificity(theirs),
                                            f"{title}: {selector} loses to {theirs} in {path}")
        self.assertGreater(checked, 5)

    def test_specificity(self):
        self.assertEqual(specificity("window#waybar.topbar *"), (1, 1, 1))
        self.assertEqual(specificity("#clock"), (1, 0, 0))
        self.assertEqual(specificity("button#taskbar_popup:hover image"), (1, 1, 2))
        self.assertEqual(specificity("*"), (0, 0, 0))


def gtk_checker_works():
    try:
        done = subprocess.run([CHECKER, os.devnull], capture_output=True, text=True, timeout=30, check=False)
    except OSError:
        return False
    return done.stdout.strip() == json.dumps({"path": os.devnull})


@unittest.skipUnless(gtk_checker_works(), "GTK 3's introspection data isn't installed")
class GtkCheckerTest(unittest.TestCase):
    """check-css itself, with GTK's parser."""

    def check(self, files):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name, text in files.items():
                path = os.path.join(folder, name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                paths.append(path)
            done = subprocess.run([CHECKER, *paths], capture_output=True, text=True, timeout=30, check=True,
                                  env={"PATH": "/usr/bin:/bin", "HOME": folder, "XDG_RUNTIME_DIR": folder})
            results = [json.loads(line) for line in done.stdout.splitlines()]
            for result in results:
                result["path"] = os.path.basename(result["path"])
                if "error" in result:
                    result["error"]["file"] = os.path.basename(result["error"]["file"])
            return results

    def test_errors_where_they_are(self):
        results = self.check({"ok.css": "#clock { color: @no_such_color; }\n",
                              "typo.css": "#clock {\n  frobnicate: 3px; }\n",
                              "imports.css": '@import url("typo.css");\n'})
        typo = {"file": "typo.css", "line": 2, "column": 12, "message": "'frobnicate' is not a valid property name"}
        self.assertEqual(results, [{"path": "ok.css"}, {"path": "typo.css", "error": typo},
                                   {"path": "imports.css", "error": typo}])

    def test_the_starter_with_every_example(self):
        """What a user gets by uncommenting everything loads in waybar."""
        text = uncommented(fl.tweaks_starter())
        self.assertEqual(self.check({"starter.css": fl.tweaks_starter(), "all.css": text}),
                         [{"path": "starter.css"}, {"path": "all.css"}])

    def test_shipped_layouts_load(self):
        """FlickOS's own CSS passes the parser waybar uses (other packages'
        import common/, which is next to them only once installed)."""
        for path in (path for path in SHIPPED if path.startswith(os.path.join(PACKAGE, "usr/"))):
            with self.subTest(path=path):
                done = subprocess.run([CHECKER, path], capture_output=True, text=True, timeout=30, check=True)
                self.assertEqual(json.loads(done.stdout), {"path": path})


if __name__ == "__main__":
    unittest.main()
