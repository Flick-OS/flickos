"""Tests for flickos-layout explain (docs/design/flickos-ricing.md ADR-011,
step 1d). Run: python3 -m unittest discover -s tests"""

import os
from unittest import mock

from test_engine import fl
from test_user_styles import UserStyleTest


class ExplainTest(UserStyleTest):

    def setUp(self):
        super().setUp()
        self.set_user_choice("plain")
        self.gsettings.update({"gtk-theme": "Arc-Dark", "icon-theme": "Numix-Circle", "color-scheme": "prefer-dark"})

    def explain(self, program=None):
        return "\n".join(fl.explain(program))

    def prepare_now(self, style="dark"):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.styles()[style], fl.labwc_themes(fl.styles()))
            fl.update_waybar(self.root, self.layout("plain"), self.styles()[style])
            fl.update_mako(self.root, self.styles()[style])

    def test_every_program_once_in_order(self):
        lines = fl.explain()
        names = [line[:fl.EXPLAIN_WIDTH].strip() for line in lines if not line.startswith(" ")]
        self.assertEqual(names, list(fl.EXPLAIN_PROGRAMS))
        self.assertEqual([line.split()[0] for line in fl.explain("dock")][:1], ["dock"])

    def test_style(self):
        self.orange()
        self.set_user_choice("dark-orange", "style")
        self.assertIn("style     Dark Orange (dark-orange), yours, inherits dark", self.explain("style"))

    def test_labwc_flickos_files(self):
        text = self.explain("labwc")
        self.assertIn(f"rc.xml: {self.path('etc/xdg/labwc/rc.xml')}", text)
        self.assertNotIn("()", text)

    def test_labwc_users_rcxml_replaces_flickos(self):
        self.write("home/.config/labwc/rc.xml", "<labwc_config><theme><name>Mine</name></theme></labwc_config>")
        text = self.explain("labwc")
        self.assertIn("rc.xml: ~/.config/labwc/rc.xml (yours: it replaces FlickOS's", text)
        self.assertIn("window theme Mine: not installed", text)

    def test_labwc_merging(self):
        """Phase 2's marker: every rc.xml, least important first."""
        self.write("home/.config/labwc/rc.xml", "<labwc_config/>")
        self.write("run/flickos/labwc-merge", "")
        lines = fl.explain("labwc")
        self.assertIn("merges every rc.xml", lines[0])
        self.assertTrue(lines[1].strip().startswith(self.path("etc/xdg/labwc/rc.xml")))
        self.assertTrue(lines[2].strip().startswith("~/.config/labwc/rc.xml (yours)"))

    def test_labwc_plain_session(self):
        with mock.patch.dict(os.environ, {"FLICKOS_PLAIN": "1"}):
            self.prepare_now()
            text = self.explain("labwc")
        self.assertIn(f"plain session: labwc -C {self.root}/plain/labwc, FlickOS's files only:", text)
        self.assertIn(f"rc.xml -> {self.path('etc/xdg/labwc/rc.xml')}", text)

    def test_panel(self):
        self.orange()
        self.prepare_now("dark-orange")
        text = self.explain("panel")
        self.assertIn("(generated for the Plain layout)", text)
        self.assertLess(text.index("styles/dark/waybar-colors.css (Dark style's colors)"),
                        text.index("dark-orange/waybar-colors.css (Dark Orange style's colors, yours)"))
        self.assertIn("layouts/plain/style.css (the Plain layout)", text)

    def test_panel_not_generated_and_users_own(self):
        self.assertIn("not generated yet", self.explain("panel"))
        self.write("home/.config/waybar/config", "{}")
        self.assertIn("~/.config/waybar/config (yours: layouts and styles don't change the panel)",
                      self.explain("panel"))

    def test_dock(self):
        self.assertIn("none: the Plain layout has no dock", self.explain("dock"))

    def test_foot_users_config(self):
        self.write("home/.config/foot/foot.ini", f"include={self.path('nowhere.ini')}\nfont=monospace:size=12\n")
        text = self.explain("foot")
        self.assertIn("~/.config/foot/foot.ini (yours)", text)
        self.assertIn(f"  {self.path('nowhere.ini')} (missing)", text)
        self.assertIn(f"styles don't change its colors: include={self.root}/style/foot.ini", text)
        self.prepare_now()
        self.write("home/.config/foot/foot.ini", f"include={self.root}/style/foot.ini\n")
        text = self.explain("foot")
        self.assertIn("styles/dark/foot.ini (Dark style's colors)", text)
        self.assertNotIn("styles don't change", text)

    def test_mako(self):
        self.prepare_now()
        text = self.explain("mako")
        self.assertIn(f"{self.root}/mako/config (generated for this login)", text)
        self.assertIn("styles/dark/mako.conf (Dark style's colors)", text)

    def test_gtk(self):
        text = self.explain("gtk")
        self.assertIn("theme Arc-Dark (the Dark style's)", text)
        self.gsettings["gtk-theme"] = "Nordic"
        self.assertIn("theme Nordic (chosen in Appearance: styles don't change it)", self.explain("gtk"))

    def test_wallpaper(self):
        with mock.patch.object(fl, "DEFAULT_WALLPAPER", self.path("no-wallpaper.jpg")):     # not the host's
            self.assertIn("a plain color (FlickOS's default)", self.explain("wallpaper"))

    def test_command(self):
        status, out, _err = self.main("explain", "gtk")
        self.assertEqual(status, 0)
        self.assertTrue(out.startswith("gtk       theme Arc-Dark"))
