"""Keys moved for keyboards that lack them (docs/design/flickos-keys.md)."""

import os
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from test_engine import PACKAGE, EngineTest, fl, read

W = frozenset({"Super"})
WS = frozenset({"Super", "Shift"})
# Plain levels (keycode: symbols), as keymap_symbols gives them, of the keys
# that matter: 10 the 1 key, 19 0, 20 the key right of 0, 21 the next one,
# 34/35 right of P, 56 B, 61 the key left of right Shift.
US = {10: ("1",), 19: ("0",), 20: ("minus",), 21: ("equal",), 34: ("bracketleft",),
      35: ("bracketright",), 56: ("b",), 61: ("slash",)}
FI = {10: ("1",), 19: ("0",), 20: ("plus",), 21: ("dead_acute",), 34: ("aring",),
      35: ("dead_diaeresis",), 56: ("b",), 61: ("minus",)}
DE = {10: ("1",), 19: ("0",), 20: ("ssharp",), 21: ("dead_acute",), 34: ("udiaeresis",),
      35: ("plus",), 56: ("b",), 61: ("minus",)}
FR = {10: ("ampersand",), 19: ("agrave",), 20: ("parenright",), 21: ("equal",), 34: ("dead_circumflex",),
      35: ("dollar",), 56: ("b",), 61: ("exclam",)}
TR = {10: ("1",), 19: ("0",), 20: ("asterisk",), 21: ("minus",), 34: ("gbreve",),
      35: ("udiaeresis",), 56: ("b",), 61: ("period",)}
RU = {10: ("1",), 19: ("0",), 20: ("minus",), 21: ("equal",), 34: ("Cyrillic_ha",),
      35: ("Cyrillic_hardsign",), 56: ("Cyrillic_i",), 61: ("period",)}
# FlickOS's keys in rc.xml order: zoom (flickos-settings) before the tiler's ratio.
KEYS = [(W, "equal"), (W, "minus"), (W, "0"), (W, "b"), (W, "bracketleft"), (W, "bracketright"),
        (W, "1"), (W, "KP_Add")]


class MovedKeysTest(unittest.TestCase):
    """moved_keys: ADR-002 and ADR-006 without libxkbcommon."""

    def moves(self, *layouts, keys=KEYS):
        return fl.moved_keys(keys, list(layouts), US)

    def test_us_moves_nothing(self):
        self.assertEqual(self.moves(US), ({}, []))

    def test_finnish_by_place_and_equal_by_its_stand_in(self):
        moves, kept = self.moves(FI)
        self.assertEqual(moves, {(W, "equal"): "plus", (W, "bracketleft"): "aring",
                                 (W, "bracketright"): "dead_diaeresis"})
        self.assertEqual(kept, [])

    def test_a_symbol_on_any_layout_stays(self):
        # labwc finds [ on the us layout whichever layout is active
        self.assertEqual(self.moves(US, FI), ({}, []))
        self.assertEqual(self.moves(FI, US), ({}, []))

    def test_german_zoom_keeps_plus_and_the_ratio_pair_stays(self):
        moves, kept = self.moves(DE)
        self.assertEqual(moves, {(W, "equal"): "plus"})
        self.assertEqual(kept, [((W, "bracketright"), "taken", (W, "plus")),
                                ((W, "bracketleft"), "pair", (W, "bracketright"))])

    def test_half_a_pair_moves_alone_when_the_other_is_unbound(self):
        moves, kept = self.moves(DE, keys=[(W, "equal"), (WS, "bracketleft")])
        self.assertEqual(moves, {(W, "equal"): "plus", (WS, "bracketleft"): "udiaeresis"})
        self.assertEqual(kept, [])

    def test_pairs_go_by_modifiers(self):
        moves, kept = self.moves(DE, keys=[(W, "equal"), (W, "bracketleft"), (W, "bracketright"),
                                           (WS, "bracketleft"), (WS, "bracketright")])
        self.assertEqual(moves, {(W, "equal"): "plus", (WS, "bracketleft"): "udiaeresis",
                                 (WS, "bracketright"): "plus"})
        self.assertEqual([key for key, _why, _other in kept], [(W, "bracketright"), (W, "bracketleft")])

    def test_french_digits(self):
        moves, _kept = self.moves(FR)
        self.assertEqual(moves[(W, "1")], "ampersand")
        self.assertEqual(moves[(W, "0")], "agrave")
        self.assertNotIn((W, "equal"), moves)

    def test_equal_by_place_where_taken_stays(self):
        moves, kept = self.moves(TR)
        self.assertNotIn((W, "equal"), moves)
        self.assertIn(((W, "equal"), "taken", (W, "minus")), kept)

    def test_letters_on_a_cyrillic_only_keymap(self):
        moves, _kept = self.moves(RU)
        self.assertEqual(moves[(W, "b")], "Cyrillic_i")

    def test_a_key_already_bound_is_taken(self):
        moves, kept = self.moves(FI, keys=[(W, "aring"), (W, "bracketleft")])
        self.assertEqual(moves, {})
        self.assertEqual(kept, [((W, "bracketleft"), "taken", (W, "aring"))])

    def test_no_key_in_that_place(self):
        moves, kept = self.moves({10: ("1",)}, keys=[(W, "bracketleft")])
        self.assertEqual((moves, kept), ({}, [((W, "bracketleft"), "none", None)]))

    def test_keys_not_on_a_us_keyboard_stay(self):
        self.assertEqual(self.moves(FI, keys=[(W, "KP_Add"), (W, "XF86AudioMute")]), ({}, []))


class KeyboardNamesTest(EngineTest):
    """keyboard_names: labwc's keymap (ADR-003)."""

    def test_default_without_files_is_us(self):
        names = fl.keyboard_names(self.root)
        self.assertEqual(names["layout"], "")
        self.assertTrue(fl.us_keyboard(names))

    def test_debian_keyboard_file(self):
        self.write("etc/default/keyboard", 'XKBMODEL="pc105"\nXKBLAYOUT="fi"\nXKBVARIANT=""\n')
        names = fl.keyboard_names(self.root)
        self.assertEqual((names["model"], names["layout"], names["variant"]), ("pc105", "fi", ""))
        self.assertFalse(fl.us_keyboard(names))

    def test_settings_before_the_system(self):
        self.write("etc/default/keyboard", 'XKBLAYOUT="fi"\nXKBVARIANT="nodeadkeys"\n')
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=de\nXKB_DEFAULT_VARIANT=\n")
        names = fl.keyboard_names(self.root)
        self.assertEqual((names["layout"], names["variant"]), ("de", ""))

    def test_users_labwc_environment_first_but_not_in_the_plain_session(self):
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=de\n")
        self.write("home/.config/labwc/environment", "# mine\nXKB_DEFAULT_LAYOUT=fr\n")
        self.assertEqual(fl.keyboard_names(self.root)["layout"], "fr")
        with mock.patch.dict(os.environ, {"FLICKOS_PLAIN": "1"}):
            self.assertEqual(fl.keyboard_names(self.root)["layout"], "de")

    def test_system_labwc_environment(self):
        self.write("etc/xdg/labwc/environment", "XCURSOR_SIZE=24\nXKB_DEFAULT_LAYOUT=se\n")
        self.assertEqual(fl.keyboard_names(self.root)["layout"], "se")

    def test_us_keyboard(self):
        self.assertTrue(fl.us_keyboard({"layout": "us", "variant": ""}))
        self.assertFalse(fl.us_keyboard({"layout": "us", "variant": "dvorak"}))
        self.assertFalse(fl.us_keyboard({"layout": "us,fi"}))

    def test_the_session_exports_the_same_names(self):
        path = os.path.join(PACKAGE, "..", "flickos-settings", "usr", "bin", "flickos-session")
        if not os.path.isfile(path):
            self.skipTest("flickos-settings is not next to flickos-layouts")
        session = read(path)
        for _name, variable, debian in fl.KEYBOARD_VARIABLES:
            if debian:
                self.assertIn(f'{variable}="$(. /etc/default/keyboard; echo "${{{debian}:-}}")"', session)


@unittest.skipUnless(fl.xkb(), "libxkbcommon is not installed")
class MoveKeysTest(EngineTest):
    """The overlay rc.xml with libxkbcommon's real keymaps."""

    def setUp(self):
        super().setUp()
        self.make_layout("plain")
        self.write("run/flickos/tiler/labwc.xml", """<labwc_config><keyboard>
  <keybind key="W-bracketleft"><action name="Execute"><command>flick-tiler ratio -5</command></action></keybind>
  <keybind key="W-bracketright"><action name="Execute"><command>flick-tiler ratio +5</command></action></keybind>
  <keybind key="W-S-[" ><action name="Execute"><command>shifted</command></action></keybind>
</keyboard></labwc_config>
""")

    def prepare_now(self):
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style())

    def keys(self):
        return [b.get("key") for b in ET.parse(self.overlay_rcxml).getroot().iter("keybind")]

    def report(self):
        return fl.key_report(self.root)

    def test_us_moves_nothing_and_writes_no_report(self):
        self.prepare_now()
        self.assertIn("W-bracketleft", self.keys())
        self.assertIsNone(self.report())

    def test_finnish(self):
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=fi\n")
        self.prepare_now()
        keys = self.keys()
        self.assertIn("W-aring", keys)
        self.assertIn("W-dead_diaeresis", keys)
        self.assertIn("W-S-aring", keys)          # the key's own spelling is kept around it
        self.assertNotIn("W-bracketleft", keys)
        self.assertIn("W-b", keys)                # on a plain level: stays
        report = self.report()
        self.assertEqual(report["keyboard"], "fi")
        self.assertIn({"key": "W-bracketleft", "to": "W-aring", "text": "Super+[", "to_text": "Super+Å"},
                      report["moved"])
        self.assertEqual(report["kept"], [])
        self.assertIn("  Super+[ is Super+Å", "\n".join(fl.explain("labwc")))

    def test_back_to_us_removes_the_report(self):
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=fi\n")
        self.prepare_now()
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=us\n")
        self.prepare_now()
        self.assertIn("W-bracketleft", self.keys())
        self.assertFalse(os.path.exists(os.path.join(self.root, fl.KEYS_REPORT)))

    def test_german_says_why_in_doctor(self):
        self.write("etc/xdg/labwc/rc.xml", read(self.path("etc/xdg/labwc/rc.xml")).replace(
            "<keyboard>", '<keyboard><keybind key="W-equal"><action name="ZoomIn" /></keybind>', 1))
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=de\n")
        self.prepare_now()
        keys = self.keys()
        self.assertIn("W-plus", keys)
        self.assertIn("W-bracketleft", keys)
        self.assertIn("W-bracketright", keys)
        lines = fl.labwc_warnings(self.root)
        self.assertIn("Super+] doesn't work with the keyboard layout de and wasn't moved: the key in its place "
                      "is already Super++.", lines)
        self.assertIn("Super+[ doesn't work with the keyboard layout de and wasn't moved: Super+] couldn't "
                      "move, and the two go together.", lines)

    def test_an_overlay_only_for_the_keys(self):
        os.unlink(self.path("run/flickos/tiler/labwc.xml"))
        self.write("etc/xdg/labwc/rc.xml", "<labwc_config><keyboard>"
                   '<keybind key="W-bracketleft"><action name="ZoomOut" /></keybind>'
                   "</keyboard></labwc_config>\n")
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style())
        self.assertFalse(os.path.exists(self.overlay_rcxml))
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=fi\n")
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style())
        self.assertEqual(self.keys(), ["W-aring"])

    def test_unknown_layout_moves_nothing(self):
        self.write("run/flickos/control/environment", "XKB_DEFAULT_LAYOUT=no-such-layout\n")
        with self.quiet():
            fl.prepare(self.layout("plain"), self.style())
        self.assertIn("W-bracketleft", self.keys())

    def test_key_text(self):
        lib = fl.xkb()[0]
        self.assertEqual(fl.key_text(lib, (WS, "aring")), "Super+Shift+Å")
        self.assertEqual(fl.key_text(lib, (W, "dead_acute")), "Super+´")
        self.assertEqual(fl.key_text(lib, (W, "Cyrillic_i")), "Super+И")
        self.assertEqual(fl.key_text(lib, (W, "ampersand")), "Super+&")
        self.assertEqual(fl.key_text(lib, (W, "Return")), "Super+Return")

    def test_parse_key_follows_labwc(self):
        lib = fl.xkb()[0]
        self.assertEqual(fl.parse_key(lib, "W-B")[0], (W, "b"))
        self.assertEqual(fl.parse_key(lib, "Mod4-S-[")[0], (WS, "bracketleft"))
        self.assertEqual(fl.parse_key(lib, "W-ö")[0], (W, "odiaeresis"))
        self.assertIsNone(fl.parse_key(lib, "W-a-b"))
        self.assertIsNone(fl.parse_key(lib, "W-nosuchkey"))


class DeadKeysTest(unittest.TestCase):

    def test_same_table_as_flickos_shortcuts(self):
        path = os.path.join(PACKAGE, "..", "flickos-shortcuts", "usr", "bin", "flickos-shortcuts")
        if not os.path.isfile(path):
            self.skipTest("flickos-shortcuts is not next to flickos-layouts")
        text = read(path)
        for name, mark in fl.DEAD_KEYS.items():
            self.assertIn(f'"{name}": "{mark}"', text)
        self.assertIn('KEYS_REPORT = os.path.join("keys", "moved.json")', text)
        self.assertEqual(fl.KEYS_REPORT, os.path.join("keys", "moved.json"))


if __name__ == "__main__":
    unittest.main()
