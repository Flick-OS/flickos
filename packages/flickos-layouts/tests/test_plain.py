"""Tests for the plain session (FLICKOS_PLAIN=1, docs/design/flickos-ricing.md
ADR-010, step 1c). Run: python3 -m unittest discover -s tests"""

import json
import os
from unittest import mock

from test_engine import fl, read
from test_user_styles import UserStyleTest


class PlainTest(UserStyleTest):

    def setUp(self):
        super().setUp()
        self.orange()
        self.set_user_choice("dark-orange", "style")
        self.plain = os.path.join(self.root, "plain/labwc")

    def go_plain(self):
        patcher = mock.patch.dict(os.environ, {"FLICKOS_PLAIN": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare_now(self):
        with self.quiet():
            self.assertTrue(fl.prepare(self.layout("plain"), fl.resolve_style(fl.styles()),
                                       fl.labwc_themes(fl.styles())))

    def test_users_styles_are_left_out(self):
        self.go_plain()
        self.assertEqual(list(self.styles()), ["dark", "light"])
        self.assertEqual(fl.resolve_style(self.styles()).id, "dark")     # dark-orange's ancestor

    def test_two_levels_down_to_flickos_ancestor(self):
        self.user_style("deeper", "Name=Deeper\nInherits=dark-orange\n")
        self.user_style("lighter", "Name=Lighter\nInherits=light\n")
        self.set_user_choice("deeper", "style")
        self.go_plain()
        self.assertEqual(fl.resolve_style(self.styles()).id, "dark")
        self.set_user_choice("lighter", "style")
        self.assertEqual(fl.resolve_style(self.styles()).id, "light")

    def test_users_addons_waybar_and_mako_are_ignored(self):
        self.write("home/.config/flickos/addons/clock2/style.css", "\n")
        self.write("home/.config/waybar/config", "{}")
        self.write("home/.config/mako/config", "font=x\n")
        self.assertIn("clock2", fl.addons())
        self.go_plain()
        self.assertNotIn("clock2", fl.addons())
        self.assertIsNone(fl.user_waybar_config())
        self.assertIsNone(fl.user_mako_config())

    def test_choices_cannot_change(self):
        self.go_plain()
        status, _out, err = self.main("style", "set", "light")
        self.assertEqual(status, 1)
        self.assertIn("the plain session doesn't change your choices", err)
        self.assertEqual(read(self.path("home/.config/flickos/style")), "dark-orange\n")

    def test_links_to_the_system_files(self):
        self.write("etc/xdg/labwc/menu.xml", "<openbox_menu/>")
        self.write("etc/xdg/labwc/autostart", "true\n")
        self.write("home/.config/labwc/rc.xml", "<labwc_config/>")        # the user's: never linked
        self.go_plain()
        self.prepare_now()
        links = {name: os.readlink(os.path.join(self.plain, name)) for name in sorted(os.listdir(self.plain))}
        self.assertEqual(links, {"autostart": self.path("etc/xdg/labwc/autostart"),
                                 "menu.xml": self.path("etc/xdg/labwc/menu.xml"),
                                 "rc.xml": self.path("etc/xdg/labwc/rc.xml")})

    def test_links_follow_the_overlay(self):
        """Q10: the overlay rc.xml comes and goes with the layout and style."""
        self.make_layout("mac", titlebar="close,iconify,max:")
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=de\n")
        self.go_plain()
        with self.quiet():
            fl.prepare(self.layout("mac"), self.style("dark"), fl.labwc_themes(fl.styles()))
        self.assertEqual(os.readlink(os.path.join(self.plain, "rc.xml")), self.overlay_rcxml)
        self.assertEqual(os.readlink(os.path.join(self.plain, "environment")),
                         os.path.join(self.root, "xdg/labwc/environment"))
        self.prepare_now()          # the plain layout needs no overlay rc.xml
        self.assertEqual(os.readlink(os.path.join(self.plain, "rc.xml")), self.path("etc/xdg/labwc/rc.xml"))

    def test_normal_session_deletes_the_folder(self):
        self.go_plain()
        self.prepare_now()
        self.assertTrue(os.path.isdir(self.plain))
        os.environ.pop("FLICKOS_PLAIN")
        self.prepare_now()
        self.assertFalse(os.path.exists(os.path.join(self.root, "plain")))

    def test_state_and_doctor(self):
        self.assertFalse(json.loads(self.main("state")[1])["plain"])
        self.go_plain()
        state = json.loads(self.main("state")[1])
        self.assertTrue(state["plain"])
        self.assertEqual(state["style"]["current"], "dark")
        self.assertEqual(len(state["warnings"]), 1)
        self.assertIn("This is the plain session", state["warnings"][0])
