"""Tests for labwc merging the user's files (docs/design/flickos-ricing.md,
ADR-003, phase 2). Run: python3 -m unittest discover -s tests"""

import os
from unittest import mock

from test_engine import EngineTest, fl


class MergeTest(EngineTest):

    def setUp(self):
        super().setUp()
        self.make_layout("plain")
        self.write("etc/xdg/labwc/menu.xml", '<openbox_menu><menu id="root-menu" label=""/>'
                                             '<menu id="office-menu" label="Office"/></openbox_menu>')
        self.marker = os.path.join(self.root, fl.MERGE_MARKER)

    def decision(self):
        return fl.merge_decision(self.root)[:2]

    def prepare_now(self):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style("dark"), fl.labwc_themes(fl.styles()))

    def labwc_file(self, name, text):
        return self.write(f"home/.config/labwc/{name}", text)

    def test_no_files_of_the_users(self):
        self.assertEqual(self.decision(), (True, None))

    def test_small_rcxml_is_merged(self):
        self.labwc_file("rc.xml", "<labwc_config><core><gap>40</gap></core></labwc_config>")
        self.assertEqual(self.decision(), (True, None))

    def test_full_copy(self):
        self.labwc_file("rc.xml", "<?xml version='1.0'?>\n<!--\n  FlickOS labwc defaults. Reference: …\n-->\n"
                                  "<labwc_config><keyboard><default /></keyboard></labwc_config>")
        self.assertEqual(self.decision(), (False, "copy"))      # before <default />

    def test_default(self):
        self.labwc_file("rc.xml", "<labwc_config><mouse><default/></mouse></labwc_config>")
        self.assertEqual(self.decision(), (False, "default"))

    def test_default_in_a_comment_doesnt_count(self):
        self.labwc_file("rc.xml", "<labwc_config><!-- <default /> was here --></labwc_config>")
        self.assertEqual(self.decision(), (True, None))

    def test_broken_rcxml_is_still_merged(self):
        """Spike Q11: under -m labwc skips only a file it can't read."""
        self.labwc_file("rc.xml", "<labwc_config><keyboard>")
        self.assertEqual(self.decision(), (True, None))

    def test_menu_with_flickos_ids(self):
        self.labwc_file("menu.xml", "<openbox_menu><menu id='root-menu' label=''/></openbox_menu>")
        self.assertEqual(self.decision(), (False, "menu"))
        self.labwc_file("menu.xml", "<openbox_menu><menu id='my-menu' label='Mine'/></openbox_menu>")
        self.assertEqual(self.decision(), (True, None))

    def test_autostart(self):
        self.labwc_file("autostart", f"{fl.FLICKOS_AUTOSTART}\n")
        self.assertEqual(self.decision(), (False, "autostart"))

    def test_live_and_plain(self):
        with mock.patch.object(fl, "live_system", return_value=True):
            self.assertEqual(self.decision(), (False, "live"))
        with mock.patch.dict(os.environ, {"FLICKOS_PLAIN": "1"}):
            self.assertEqual(self.decision(), (False, "plain"))

    def test_marker_written_at_login(self):
        self.prepare_now()
        self.assertTrue(os.path.exists(self.marker))
        self.labwc_file("rc.xml", "<labwc_config><keyboard><default /></keyboard></labwc_config>")
        self.prepare_now()
        self.assertFalse(os.path.exists(self.marker))

    def test_marker_kept_inside_the_session(self):
        """labwc's -m can't change until the next login."""
        self.prepare_now()
        self.labwc_file("autostart", "true\n")
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0", "LABWC_PID": "1"}):
            self.prepare_now()
            self.assertTrue(os.path.exists(self.marker))
            self.assertIn("labwc stops merging them with FlickOS's after you log out and in",
                          " ".join(fl.doctor_warnings()))

    def test_default_added_while_merging(self):
        """labwc's own keys replace FlickOS's at the next reload: say how to get them back now."""
        self.prepare_now()
        self.labwc_file("rc.xml", "<labwc_config><keyboard><default /></keyboard></labwc_config>")
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0", "LABWC_PID": "1"}):
            self.assertIn(fl.DEFAULT_WHILE_MERGING, " ".join(fl.doctor_warnings()))
        self.labwc_file("autostart", "true\n")
        os.remove(os.path.join(self.home, ".config/labwc/rc.xml"))
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0", "LABWC_PID": "1"}):
            self.assertNotIn(fl.DEFAULT_WHILE_MERGING, " ".join(fl.doctor_warnings()))

    def test_doctor_quiet_while_merging(self):
        self.labwc_file("rc.xml", "<labwc_config/>")
        self.labwc_file("environment", "FOO=1\n")
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=de\n")
        self.prepare_now()
        self.assertEqual(fl.doctor_warnings(), [])

    def test_doctor_explains_default(self):
        self.labwc_file("rc.xml", "<labwc_config><keyboard><default /></keyboard></labwc_config>")
        self.prepare_now()
        [warning] = fl.doctor_warnings()
        self.assertIn("has <default />", warning)
        self.assertIn("Delete the <default /> lines, then log out and in", warning)

    def test_doctor_explains_copy_and_menu(self):
        self.labwc_file("rc.xml", "<!-- FlickOS labwc defaults. -->\n<labwc_config/>")
        self.prepare_now()
        self.assertIn("is a copy of FlickOS's rc.xml", fl.doctor_warnings()[0])
        os.unlink(self.path("home/.config/labwc/rc.xml"))
        self.labwc_file("menu.xml", "<openbox_menu><menu id='office-menu'/></openbox_menu>")
        self.prepare_now()
        [warning] = fl.doctor_warnings()
        self.assertIn("uses menu ids that FlickOS's menu has (office-menu)", warning)

    def test_explain(self):
        self.prepare_now()
        self.assertIn("merges every rc.xml", "\n".join(fl.explain("labwc")))
        self.labwc_file("rc.xml", "<labwc_config><keyboard><default /></keyboard></labwc_config>")
        self.prepare_now()
        self.assertIn("not merging: your rc.xml has <default />", "\n".join(fl.explain("labwc")))
        with mock.patch.object(fl, "live_system", return_value=True):
            self.assertIn("not merging: the live session", "\n".join(fl.explain("labwc")))
