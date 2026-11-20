"""Tests for usr/bin/flickos-menu. Run: python3 -m unittest discover -s tests"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
SCRIPT = os.path.join(PACKAGE, "usr/bin/flickos-menu")

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_menu", SCRIPT)
fm = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fm)
QUICK = os.path.join(PACKAGE, "usr/share/flickos/menu/quick.py")
_loader = importlib.machinery.SourceFileLoader("flickos_menu_quick", QUICK)
fq = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fq)
PHONE_PY = os.path.join(PACKAGE, "usr/share/flickos/menu/phone.py")
_loader = importlib.machinery.SourceFileLoader("flickos_menu_phone", PHONE_PY)
fph = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fph)


class PhoneLinkTest(unittest.TestCase):
    """Phone's desktop file stays installed. The menu re-reads apps when the
    daemon's link appears or goes, which is the only thing TryExec watches."""

    def test_the_link_makes_the_index_stale(self):
        runtime = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, runtime)
        link = os.path.join(runtime, "flickos", "bin", fm.PHONE_LINK)
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}):
            self.assertFalse(fm.phone_link_up())
            self.assertTrue(fm.phone_link_stale(None))
            self.assertFalse(fm.phone_link_stale(False))
            os.makedirs(os.path.dirname(link))
            os.symlink("/bin/true", link)
            self.assertTrue(fm.phone_link_up())
            self.assertTrue(fm.phone_link_stale(False))
            self.assertFalse(fm.phone_link_stale(True))


def app(desktop_id, name, generic="", keywords=(), executable="", categories=()):
    return fm.App(desktop_id, name, generic, keywords, executable, categories)


APPS = [
    app("firefox-esr.desktop", "Firefox ESR", "Web Browser", ("internet", "web"), "/usr/lib/firefox-esr/firefox-esr",
        ("Network", "WebBrowser")),
    app("libreoffice-writer.desktop", "LibreOffice Writer", "Word Processor", ("text", "document"), "libreoffice",
        ("Office", "WordProcessor")),
    app("foot.desktop", "Foot", "Terminal", ("shell", "prompt"), "foot", ("System", "TerminalEmulator")),
    app("pcmanfm.desktop", "File Manager PCManFM", "File Manager", (), "pcmanfm", ("GTK", "System", "FileManager")),
    app("vlc.desktop", "VLC media player", "Media player", ("video", "movie"), "vlc", ("AudioVideo", "Player")),
    app("org.xfce.mousepad.desktop", "Mousepad", "Text Editor", ("notepad",), "mousepad", ("Utility", "TextEditor")),
    app("flickos-control.desktop", "Settings", "", (), "flickos-control", ("Settings", "DesktopSettings")),
    app("odd.desktop", "Odd Tool", "", (), "odd", ("X-Unknown",)),
]


class PictureTest(unittest.TestCase):
    def test_settings_picture_comes_before_face(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(fm, "PICTURES", folder):
            self.assertIsNone(fm.picture_file("jo", folder))
            face = os.path.join(folder, ".face")
            open(face, "w", encoding="utf-8").close()
            self.assertEqual(fm.picture_file("jo", folder), face)
            chosen = os.path.join(folder, "jo")
            open(chosen, "w", encoding="utf-8").close()
            self.assertEqual(fm.picture_file("jo", folder), chosen)


    def test_a_new_picture_replaces_the_cached_one(self):
        menu = fm.Menu.__new__(fm.Menu)
        menu.view, menu.picture_timer = mock.Mock(), 7
        menu.icons = {(fm.PICTURES + "/jo", 32, 1): "old", ("firefox-esr", 32, 1): "kept"}
        self.assertFalse(menu.show_picture())       # once, not again
        self.assertEqual(menu.icons, {("firefox-esr", 32, 1): "kept"})
        self.assertIsNone(menu.picture_timer)
        menu.view.show_picture.assert_called_once_with()


class TooltipTest(unittest.TestCase):
    def test_tooltip_has_the_whole_name_then_the_description(self):
        self.assertEqual(fm.app_tooltip("Firefox ESR", "Browse the Web"), "<b>Firefox ESR</b>\nBrowse the Web")

    def test_tooltip_escapes_markup_and_skips_a_missing_description(self):
        self.assertEqual(fm.app_tooltip("Tom & Jerry <2>", None), "<b>Tom &amp; Jerry &lt;2&gt;</b>")


class Environment(unittest.TestCase):
    """A temporary HOME, XDG_CONFIG_HOME, XDG_CONFIG_DIRS and runtime folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.system = os.path.join(self.dir, "etc-xdg")
        self.live = os.path.join(self.dir, "etc-xdg-live")
        os.makedirs(os.path.join(self.system, "flickos"))
        self.runtime = os.path.join(self.dir, "run")
        self.root = os.path.join(self.runtime, "flickos")
        os.makedirs(os.path.join(self.root, "menu"))
        env = {"HOME": self.dir, "XDG_CONFIG_HOME": os.path.join(self.dir, "config"),
               "XDG_CONFIG_DIRS": self.system, "XDG_RUNTIME_DIR": self.runtime}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def system_conf(self, pinned, folder=None):
        self.write(os.path.join(folder or self.system, "flickos", "menu.conf"), f"[Menu]\nPinned={pinned}\n")


class SectionTest(unittest.TestCase):
    def test_first_listed_category_wins(self):
        self.assertEqual(fm.section_for(["Network", "WebBrowser"]), "Internet")
        self.assertEqual(fm.section_for(["GTK", "Utility", "TextEditor"]), "Accessories")
        self.assertEqual(fm.section_for(["Settings", "System"]), "Settings")
        self.assertEqual(fm.section_for(["System", "Settings"]), "System")
        self.assertEqual(fm.section_for(["AudioVideo", "Player"]), "Multimedia")

    def test_unknown_categories_are_other(self):
        self.assertEqual(fm.section_for(["X-Unknown", ""]), "Other")
        self.assertEqual(fm.section_for([]), "Other")

    def test_by_section_keeps_section_order_and_sorts_apps(self):
        groups = fm.by_section(APPS)
        names = [name for name, _icon, _apps in groups]
        self.assertEqual(names, ["Accessories", "Internet", "Multimedia", "Office", "Settings", "System", "Other"])
        system = dict((name, apps) for name, _icon, apps in groups)["System"]
        self.assertEqual([a.id for a in system], ["pcmanfm.desktop", "foot.desktop"])

    def test_every_section_has_an_icon(self):
        for name, icon, categories in fm.SECTIONS:
            self.assertTrue(icon and categories, name)


class SearchTest(unittest.TestCase):
    def ids(self, query):
        return [a.id for a in fm.search(APPS, query)]

    def test_name_start_beats_word_start_beats_inside(self):
        apps = [app("a.desktop", "Profile Editor"), app("b.desktop", "Fire Starter"),
                app("c.desktop", "Wildfire")]
        self.assertEqual([a.id for a in fm.search(apps, "fi")], ["b.desktop", "a.desktop", "c.desktop"])

    def test_generic_name_keywords_and_program(self):
        self.assertEqual(self.ids("browser"), ["firefox-esr.desktop"])
        self.assertEqual(self.ids("notepad"), ["org.xfce.mousepad.desktop"])
        self.assertEqual(self.ids("pcmanfm"), ["pcmanfm.desktop"])
        self.assertIn("foot.desktop", self.ids("terminal"))

    def test_every_word_must_match(self):
        self.assertEqual(self.ids("libre writer"), ["libreoffice-writer.desktop"])
        self.assertEqual(self.ids("libre vlc"), [])

    def test_case_and_empty_query(self):
        self.assertEqual(self.ids("FIREFOX"), ["firefox-esr.desktop"])
        self.assertEqual(self.ids("   "), [])

    def test_limit(self):
        apps = [app(f"a{i}.desktop", f"App {i}") for i in range(100)]
        self.assertEqual(len(fm.search(apps, "app")), fm.MAX_RESULTS)
        self.assertEqual(len(fm.search(apps, "app", limit=None)), 100)     # the grid shows every match

    def test_fast_on_a_thousand_apps(self):
        apps = [app(f"app{i}.desktop", f"Application number {i}", "Generic tool", ("alpha", "beta"),
                    f"/usr/bin/app{i}", ("Utility",)) for i in range(1000)]
        for query in ("a", "app", "number 9", "tool", "zzz"):
            took = []
            for _ in range(5):              # the fastest run: a busy build host slows any one
                started = time.perf_counter()
                fm.search(apps, query)
                took.append((time.perf_counter() - started) * 1000)
            self.assertLess(min(took), 5, query)


class PinnedTest(Environment):
    def test_default_without_any_file(self):
        self.assertEqual(fm.pinned_ids(), list(fm.DEFAULT_PINNED))

    def test_system_file_in_xdg_config_dirs(self):
        self.system_conf("a.desktop; b.desktop;;a.desktop")
        self.assertEqual(fm.pinned_ids(), ["a.desktop", "b.desktop"])

    def test_first_system_file_wins(self):
        self.system_conf("installed.desktop")
        self.system_conf("flickos-install.desktop;installed.desktop", folder=self.live)
        os.environ["XDG_CONFIG_DIRS"] = f"{self.live}:{self.system}"
        self.assertEqual(fm.pinned_ids(), ["flickos-install.desktop", "installed.desktop"])

    def test_pin_and_unpin_write_the_users_file(self):
        self.system_conf("a.desktop;b.desktop")
        self.assertTrue(fm.pin("c.desktop"))
        self.assertFalse(fm.pin("c.desktop"))
        self.assertTrue(fm.unpin("a.desktop"))
        self.assertFalse(fm.unpin("a.desktop"))
        self.assertEqual(fm.pinned_ids(), ["b.desktop", "c.desktop"])
        self.system_conf("x.desktop")    # the user's list replaces the system's now
        self.assertEqual(fm.pinned_ids(), ["b.desktop", "c.desktop"])
        folder = os.path.dirname(fm.user_file())
        self.assertEqual(sorted(os.listdir(folder)), ["menu"])     # no temporary files left

    def test_unpinning_everything_keeps_an_empty_list(self):
        self.system_conf("a.desktop")
        fm.unpin("a.desktop")
        self.assertEqual(fm.pinned_ids(), [])

    def test_broken_user_file_falls_back(self):
        self.system_conf("a.desktop")
        self.write(fm.user_file(), "not an ini file\n")
        with mock.patch.object(fm, "warn"):
            self.assertEqual(fm.pinned_ids(), ["a.desktop"])


class PromptTest(Environment):
    """The prompt style's rules (ADR-022), without GTK."""

    def test_size(self):
        self.assertEqual(fm.parse_size("7x5"), (7, 5))
        self.assertEqual(fm.parse_size("12X1"), (8, 2))     # kept to 5–8 columns and 2 rows at least
        self.assertEqual(fm.parse_size("3x3"), (5, 3))
        for value in (None, "", "big", "6x", "x4", "6x4x2"):
            self.assertEqual(fm.parse_size(value), fm.PROMPT_SIZE, value)

    def test_category_names_find_their_apps(self):
        ids = lambda apps: [a.id for a in apps]
        self.assertEqual(ids(fm.category_matches(APPS, "sys")), ["pcmanfm.desktop", "foot.desktop"])   # A–Z: File Manager, Foot
        self.assertEqual(ids(fm.category_matches(APPS, "  Multimedia ")), ["vlc.desktop"])
        self.assertEqual(ids(fm.category_matches(APPS, "oth")), ["odd.desktop"])
        self.assertEqual(fm.category_matches(APPS, "sy"), [], "two letters are too few")
        self.assertEqual(fm.category_matches(APPS, "systems"), [])
        self.assertEqual(ids(fm.category_matches(APPS, "sys", skip={"foot.desktop"})), ["pcmanfm.desktop"])
        # The shown (translated) name finds them too; the English one still does.
        german = {"Internet": "Netzwerk"}.get
        self.assertEqual(ids(fm.category_matches(APPS, "netz", lambda n: german(n, n))), ["firefox-esr.desktop"])
        self.assertEqual(ids(fm.category_matches(APPS, "inter", lambda n: german(n, n))), ["firefox-esr.desktop"])

    def test_tips_take_turns_with_the_hint(self):
        tips = ["one", "two", "three"]
        shown = [fm.tip_for(count, tips) for count in range(8)]
        self.assertEqual(shown, [None, "one", None, "two", None, "three", None, "one"])
        self.assertIsNone(fm.tip_for(fm.TIP_SHOWS, tips))
        self.assertIsNone(fm.tip_for(fm.TIP_SHOWS + 1, tips), "no tips after TIP_SHOWS")
        self.assertIsNone(fm.tip_for(1, []))

    def test_tips_follow_what_the_menu_has(self):
        bare = " ".join(fm.prompt_tips((), pins=False))
        for absent in ("Ctrl", "=", ">", "/"):
            self.assertNotIn(absent, bare)
        self.assertIn("“games”", bare)
        full = " ".join(fm.prompt_tips(("=", ">", "/"), pins=True))
        for present in ("Ctrl", "=15*3", "Start with >", "Start with /", "F1"):
            self.assertIn(present, full)

    def test_tip_count_file(self):
        path = os.path.join(self.dir, "state", "flickos", "menu-tips")
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.dir, "state")}):
            self.assertEqual(fm.state_file(fm.TIPS_FILE), path)
        self.assertEqual(fm.read_tip_count(path), 0)
        self.write(path, "5\n")
        self.assertEqual(fm.read_tip_count(path), 5)
        self.write(path, "-3")
        self.assertEqual(fm.read_tip_count(path), 0)
        self.write(path, "junk")
        with mock.patch.object(fm, "warn") as warned:
            self.assertEqual(fm.read_tip_count(path), fm.TIP_SHOWS, "a broken file: no more tips")
        warned.assert_called_once()

    def test_help_lists_what_works_here(self):
        rows = fm.help_rows(("=",), pins=False)
        keys = [row[0] for row in rows if row is not None]
        self.assertEqual(keys[:2], ["games", "=15*3"])
        for absent in ("/name", ">command", "?word", "Ctrl+1–6"):
            self.assertNotIn(absent, keys)
        self.assertEqual(rows.count(None), 1, "one line between typing and keys")
        keys = [row[0] for row in fm.help_rows(("=", "/", ">", "?"), pins=True) if row is not None]
        for present in ("/name", ">command", "?word", "Ctrl+1–6", "→", "↑", "Ctrl+P"):
            self.assertIn(present, keys)

    def test_rows_fit_the_screen(self):
        other, tile = 300, 82
        self.assertEqual(fm.rows_that_fit(4, 768 - 64, tile, other), 4)
        self.assertEqual(fm.rows_that_fit(4, 600 - 64, tile, other), 2)
        self.assertEqual(fm.rows_that_fit(4, 200, tile, other), fm.PROMPT_MIN_ROWS)
        self.assertEqual(fm.rows_that_fit(3, 2000, tile, other), 3)     # never more than asked
        self.assertEqual(fm.rows_that_fit(4, 700, 0, other), 4)         # nothing measured yet

    def test_pin_keys(self):
        self.assertEqual([fm.pin_number(str(n)) for n in range(1, 7)], list(range(6)))
        for text in ("0", "7", "9", "a", "", "12", "\x00"):
            self.assertIsNone(fm.pin_number(text), repr(text))

    def test_settings_keep_each_other(self):
        self.system_conf("a.desktop;b.desktop")
        fm.save_user_settings(Hidden="x.desktop", Size="7x3")
        self.assertEqual(fm.pinned_ids(), ["a.desktop", "b.desktop"])   # no Pinned= yet: the system's
        fm.pin("c.desktop")
        settings = fm.read_user_settings()
        self.assertEqual(settings["Hidden"], "x.desktop")
        self.assertEqual(settings["Size"], "7x3")
        self.assertEqual(settings["Pinned"], "a.desktop;b.desktop;c.desktop")
        fm.save_user_settings(Size=None)
        self.assertNotIn("Size", fm.read_user_settings())
        self.assertEqual(fm.pinned_ids(), ["a.desktop", "b.desktop", "c.desktop"])

    def test_settings_without_a_file(self):
        self.assertEqual(fm.read_user_settings(), {})

    def test_is_open(self):
        foot = app("foot.desktop", "Terminal")
        self.assertTrue(fm.is_open(foot, {"foot"}))
        self.assertFalse(fm.is_open(foot, {"geany"}))
        self.assertFalse(fm.is_open(foot, None))
        self.assertFalse(fm.is_open(foot, set()))

    def serve(self, reply):
        """A stand-in for flick-tiler's control socket that answers once."""
        import socket
        import threading
        path = os.path.join(self.root, fm.TILER_CONTROL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        asked = []

        def answer():
            conn, _ = server.accept()
            with conn:
                asked.append(conn.recv(4096))
                conn.sendall(reply)
            server.close()

        thread = threading.Thread(target=answer)
        thread.start()
        self.addCleanup(thread.join, 2)
        return asked

    def test_open_apps_from_the_tiler(self):
        asked = self.serve(b'{"text": " ", "app_ids": ["Geany", "foot"]}\n')
        self.assertEqual(fm.open_app_ids(self.root), {"geany", "foot"})
        self.assertEqual(asked, [b"open-apps\n"])

    def test_an_older_tiler_marks_nothing(self):
        self.serve(b'{"error": "unknown command: open-apps"}\n')
        self.assertIsNone(fm.open_app_ids(self.root))

    def test_no_tiler(self):
        self.assertIsNone(fm.open_app_ids(self.root))
        self.assertIsNone(fm.open_app_ids(None))


class PromptPinTest(Environment):
    """Pinning, moving, replacing and hiding in the prompt style (ADR-022)."""

    # The user's list: x isn't installed, g is the seventh, so shown is a–f.
    IDS = ["a", "x", "b", "c", "d", "e", "f", "g"]
    SHOWN = ["a", "b", "c", "d", "e", "f"]

    def test_place_a_new_pin(self):
        self.assertEqual(fm.place_pin(["a", "b"], ["a", "b"], "n", 2), ["a", "b", "n"])
        self.assertEqual(fm.place_pin(["a", "b"], ["a", "b"], "n", 0), ["n", "a", "b"])
        self.assertEqual(fm.place_pin([], [], "n", 0), ["n"])
        # After the last pin that shows: an uninstalled pin behind it stays behind.
        self.assertEqual(fm.place_pin(["a", "x"], ["a"], "n", 1), ["a", "n", "x"])

    def test_move_keeps_the_others_in_place(self):
        self.assertEqual(fm.move_pin(self.IDS, self.SHOWN, "b", -1), ["b", "a", "x", "c", "d", "e", "f", "g"])
        self.assertEqual(fm.move_pin(self.IDS, self.SHOWN, "e", 1), ["a", "x", "b", "c", "d", "f", "e", "g"])
        self.assertIsNone(fm.move_pin(self.IDS, self.SHOWN, "a", -1))
        self.assertIsNone(fm.move_pin(self.IDS, self.SHOWN, "f", 1))
        self.assertIsNone(fm.move_pin(self.IDS, self.SHOWN, "g", -1))    # the seventh doesn't show

    def test_replace_takes_the_place(self):
        self.assertEqual(fm.replace_pin(self.IDS, "c", "n"), ["a", "x", "b", "n", "d", "e", "f", "g"])
        # A pin past the sixth moved into the row leaves its old place.
        self.assertEqual(fm.replace_pin(self.IDS, "c", "g"), ["a", "x", "b", "g", "d", "e", "f"])

    def test_pins_after_the_sixth_stay_in_the_list(self):
        ids = fm.replace_pin(self.IDS, "a", "n")
        self.assertIn("g", ids)
        self.assertIn("x", ids)

    def test_hidden(self):
        self.assertEqual(fm.hidden_ids({}), [])
        self.assertEqual(fm.hidden_ids({"Hidden": "a.desktop; b.desktop;;a.desktop"}), ["a.desktop", "b.desktop"])
        fm.save_user_settings(Hidden="a.desktop", Pinned="p.desktop")
        fm.save_user_settings(Hidden=None)
        self.assertEqual(fm.read_user_settings(), {"Pinned": "p.desktop"})

    def test_system_hidden_is_the_default_and_the_users_list_replaces_it(self):
        self.assertEqual(fm.effective_hidden(), [])
        self.write(os.path.join(self.system, "flickos", "menu.conf"),
                   "[Menu]\nPinned=p.desktop\nHidden=a.desktop;b.desktop\n")
        self.assertEqual(fm.effective_hidden(), ["a.desktop", "b.desktop"])
        fm.save_user_settings(Hidden="c.desktop")
        self.assertEqual(fm.effective_hidden(), ["c.desktop"])
        # Showing everything is written empty: absent would bring the system's back.
        fm.save_user_settings(Hidden="")
        self.assertEqual(fm.effective_hidden(), [])
        fm.save_user_settings(Hidden=None)
        self.assertEqual(fm.effective_hidden(), ["a.desktop", "b.desktop"])

    def test_size_steps(self):
        self.assertEqual(fm.step_size((6, 4), 1), (7, 5))
        self.assertEqual(fm.step_size((8, 6), 1), (8, 7))      # columns stop at 8, the screen stops rows
        self.assertEqual(fm.step_size((5, 2), -1), (5, 2))
        self.assertEqual(fm.size_text((7, 5)), "7x5")
        self.assertEqual(fm.parse_size(fm.size_text((7, 5))), (7, 5))

    def test_snap_to_whole_tiles(self):
        self.assertEqual(fm.snap(16 + 6 * 78 + 30, 16, 78, 5, 8), 6)   # less than half a tile more
        self.assertEqual(fm.snap(16 + 6 * 78 + 40, 16, 78, 5, 8), 7)   # more than half
        self.assertEqual(fm.snap(100, 16, 78, 5, 8), 5)
        self.assertEqual(fm.snap(5000, 16, 78, 5, 8), 8)
        self.assertEqual(fm.snap(500, 16, 0, 5, 8), 5)


class PromptKeysTest(unittest.TestCase):
    """The prompt's own keys (ADR-022, phase 17)."""

    def test_completion(self):
        self.assertEqual(fm.completion("fi", "Firefox ESR"), "refox ESR")
        self.assertEqual(fm.completion("FIRE", "Firefox ESR"), "fox ESR")      # folded, the typed case kept
        self.assertEqual(fm.completion("Firefox ESR", "Firefox ESR"), "")     # nothing left to add
        self.assertEqual(fm.completion("writer", "LibreOffice Writer"), "")   # not where the name starts
        self.assertEqual(fm.completion("", "Firefox"), "")
        self.assertEqual(fm.completion("  ", "  Firefox"), "")

    def test_chips_that_fit_on_one_line(self):
        self.assertEqual(fm.chips_that_fit([80, 100, 90, 90], 300, 6), 3)
        self.assertEqual(fm.chips_that_fit([80, 100, 90, 90], 400, 6), 4)
        self.assertEqual(fm.chips_that_fit([80, 100], 186, 6), 2, "exactly the width")
        self.assertEqual(fm.chips_that_fit([500], 300, 6), 1, "Home shows whatever its width")
        self.assertEqual(fm.chips_that_fit([], 300, 6), 0)

    def test_the_prompts_folders_in_their_order(self):
        """Downloads before Documents: the order the chips have room for."""
        dirs = {"DOWNLOAD": "/home/u/Downloads", "DOCUMENTS": "/home/u/Documents", "VIDEOS": None}
        self.assertEqual([path for _label, path in fm.places("/home/u", dirs, isdir=lambda p: True,
                                                              order=fm.PROMPT_PLACES)],
                         ["/home/u", "/home/u/Downloads", "/home/u/Documents"])
        self.assertEqual(set(fm.PROMPT_PLACES), set(fm.PLACES), "the same folders as the other styles")

    def test_folders_found_by_typing(self):
        """A folder's English word finds it whatever its name in the user's
        language, and its own name does too."""
        rows = [fp.Row("path", "Home", "/home", keys=fm.FOLDER_WORDS["HOME"] + " u", path="/home/u"),
                fp.Row("path", "Lataukset", "~", keys=fm.FOLDER_WORDS["DOWNLOAD"] + " Lataukset",
                       path="/home/u/Lataukset"),
                fp.Row("path", "Asiakirjat", "~", keys=fm.FOLDER_WORDS["DOCUMENTS"] + " Asiakirjat",
                       path="/home/u/Asiakirjat")]
        found = lambda text: [row.name for row in fp.match_rows(rows, text, fm.PROMPT_FOLDER_ROWS)]
        self.assertEqual(found("down"), ["Lataukset"])
        self.assertEqual(found("doc"), ["Asiakirjat"])
        self.assertEqual(found("lata"), ["Lataukset"])
        self.assertEqual(found("home"), ["Home"])
        self.assertEqual(found("zzz"), [])

    def test_the_lines_mark(self):
        """The logo's ›, a prefix's own sign, and $ for `>`, which would look
        like the › (ADR-020)."""
        self.assertEqual(fm.prefix_symbol(None), "›")
        self.assertEqual(fm.prefix_symbol("/"), "/")
        self.assertEqual(fm.prefix_symbol("="), "=")
        self.assertEqual(fm.prefix_symbol(">"), "$")

    def test_search_to_keep(self):
        self.assertEqual(fm.search_to_keep("  fire "), "fire")
        for text in ("", "   ", "> sudo rm", "=2+2", "/invoice", "?ls"):
            self.assertIsNone(fm.search_to_keep(text), text)


class PromptDetailsTest(Environment):
    """New apps, the restart dot and drives (ADR-022, phase 18)."""

    def test_first_run_marks_nothing_new(self):
        record, changed = fm.update_seen(None, ["a", "b"], 100)
        self.assertTrue(changed)
        self.assertEqual(record, {"seen": ["a", "b"], "new": {}})

    def test_an_app_installed_later_is_new_for_three_days(self):
        record, _ = fm.update_seen(None, ["a"], 100)
        record, changed = fm.update_seen(record, ["a", "b"], 101)
        self.assertTrue(changed)
        self.assertEqual(record["new"], {"b": 101})
        self.assertEqual(fm.update_seen(record, ["a", "b"], 103)[0]["new"], {"b": 101})
        self.assertEqual(fm.update_seen(record, ["a", "b"], 104)[0]["new"], {})

    def test_starting_it_or_removing_it_ends_new(self):
        record = {"seen": ["a", "b"], "new": {"b": 101}}
        self.assertEqual(fm.update_seen(record, ["a", "b"], 101, started={"b"})[0]["new"], {})
        removed, changed = fm.update_seen(record, ["a"], 101)
        self.assertTrue(changed)
        self.assertEqual(removed, {"seen": ["a"], "new": {}})

    def test_nothing_to_write_when_nothing_changed(self):
        record = {"seen": ["a", "b"], "new": {"b": 101}}
        self.assertFalse(fm.update_seen(record, ["b", "a"], 102)[1])

    def test_record_file(self):
        path = os.path.join(self.dir, "state", "flickos", "menu-seen.json")
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.dir, "state")}):
            self.assertEqual(fm.state_file(), path)
        self.assertIsNone(fm.read_seen(path))
        self.write(path, '{"seen": ["a"], "new": {}}')
        self.assertEqual(fm.read_seen(path), {"seen": ["a"], "new": {}})
        for broken in ("not json", '["a"]', '{"seen": "a"}'):
            self.write(path, broken)
            with mock.patch.object(fm, "warn"):
                self.assertIsNone(fm.read_seen(path), broken)

    def test_restart_needed(self):
        flag = os.path.join(self.dir, "reboot-required")
        self.assertFalse(fm.restart_needed(flag))
        self.write(flag, "")
        self.assertTrue(fm.restart_needed(flag))
        self.assertTrue(fm.REBOOT_REQUIRED.endswith("/run/reboot-required"))

    def test_removable(self):
        self.assertTrue(fm.is_removable("/media/jon/KINGSTON"))
        self.assertTrue(fm.is_removable("/run/media/jon/USB"))
        for path in ("/", "/home", "/boot/efi", "/mnt/data", "", None, "/mediaplayer"):
            self.assertFalse(fm.is_removable(path), path)


class RuntimeTest(Environment):
    def anchor(self, text):
        self.write(os.path.join(self.root, fm.ANCHOR), text)

    def test_anchor(self):
        self.assertIsNone(fm.read_anchor(self.root))
        self.anchor("bottom-left\n")
        self.assertEqual(fm.read_anchor(self.root), "bottom-left")
        self.anchor("bottom-center\n")     # Eleven's apps button is in the middle
        self.assertEqual(fm.read_anchor(self.root), "bottom-center")
        self.anchor("middle\n")
        self.assertIsNone(fm.read_anchor(self.root))
        self.assertIsNone(fm.read_anchor(None))

    def test_menu_style(self):
        self.assertIsNone(fm.read_menu(self.root))
        self.anchor("top-left\ngrid\n")
        self.assertEqual(fm.read_menu(self.root), ("top-left", "grid"))
        self.anchor("bottom-left\n")     # flickos-layouts before MenuStyle=
        self.assertEqual(fm.read_menu(self.root), ("bottom-left", "classic"))
        self.anchor("bottom-left\nribbon\n")     # a style this version doesn't know
        self.assertEqual(fm.read_menu(self.root), ("bottom-left", "classic"))
        self.anchor("nowhere\ngrid\n")
        self.assertIsNone(fm.read_menu(self.root))
        self.assertEqual(fm.read_anchor(self.root), None)

    def test_arrow(self):
        self.assertIsNone(fm.read_arrow(self.root))
        self.anchor("bottom-left\nclassic\n")   # a layout without MenuArrow=
        self.assertIsNone(fm.read_arrow(self.root))
        self.anchor("bottom-left\nclassic\n23\n")
        self.assertEqual(fm.read_arrow(self.root), 23)
        self.assertEqual(fm.read_menu(self.root), ("bottom-left", "classic"))
        self.anchor("bottom-left\nclassic\nleft\n")
        self.assertIsNone(fm.read_arrow(self.root))
        self.assertIsNone(fm.read_arrow(None))

    def test_arrow_follows_the_floating_panel(self):
        self.anchor("bottom-left\nclassic\n23 32\n")
        self.assertEqual(fm.read_arrow(self.root), 23)      # the panel doesn't float
        state = os.path.join(self.root, fm.PANEL_STATE)
        os.makedirs(os.path.dirname(state))
        with open(state, "w", encoding="utf-8"):
            pass
        self.assertEqual(fm.read_arrow(self.root), 32)
        with open(state, "w", encoding="utf-8") as f:
            f.write('@import url("panel-full.css");\n')    # a window fills the screen
        self.assertEqual(fm.read_arrow(self.root), 23)

    def test_arrow_fits_in_the_gap(self):
        self.assertLess(fm.ARROW_HEIGHT, fm.POPUP_GAP)

    def test_every_style_has_a_view(self):
        self.assertEqual(tuple(fm.VIEWS), fm.MENU_STYLES)
        self.assertIn(fm.DEFAULT_MENU_STYLE, fm.MENU_STYLES)

    def test_daemon_pid_checks_the_process_name(self):
        proc = os.path.join(self.dir, "proc")
        self.write(os.path.join(proc, "4242", "comm"), "flickos-menu\n")
        self.write(os.path.join(proc, "4343", "comm"), "bash\n")
        self.assertIsNone(fm.daemon_pid(self.root, proc))
        self.write(os.path.join(self.root, fm.PID_FILE), "4242\n")
        self.assertEqual(fm.daemon_pid(self.root, proc), 4242)
        self.write(os.path.join(self.root, fm.PID_FILE), "4343\n")     # a reused pid
        self.assertIsNone(fm.daemon_pid(self.root, proc))
        self.write(os.path.join(self.root, fm.PID_FILE), "junk\n")
        self.assertIsNone(fm.daemon_pid(self.root, proc))

    def test_menu_off_runs_fuzzel_and_starts_no_daemon(self):
        with mock.patch.object(fm.os, "execvp") as execvp, mock.patch.object(fm.os, "execv") as execv, \
                mock.patch.object(fm.os, "kill") as kill:
            fm.client("toggle", self.root)
            execvp.assert_called_once_with("sh", fm.FALLBACK_LAUNCHER)
            execvp.reset_mock()
            fm.client("super", self.root)
            execvp.assert_called_once()
            execvp.reset_mock()
            self.assertEqual(fm.client("hide", self.root), 0)
            self.assertEqual(fm.client("show", self.root), 0)
            execvp.assert_not_called()
            execv.assert_not_called()
            kill.assert_not_called()

    def test_menu_on_signals_the_daemon(self):
        self.anchor("top-left\n")
        signals = fm.request_signals()
        with mock.patch.object(fm, "daemon_pid", return_value=77), mock.patch.object(fm.os, "kill") as kill, \
                mock.patch.object(fm.os, "execv") as execv:
            for request in ("toggle", "super", "hide"):
                kill.reset_mock()
                fm.client(request, self.root)
                kill.assert_called_once_with(77, signals[request])
            kill.reset_mock()
            fm.client("show", self.root)
            kill.assert_called_once_with(77, signals["toggle"])
            self.assertEqual(fm.take_request(self.root), "show")
            self.assertIsNone(fm.take_request(self.root))
            execv.assert_not_called()

    def test_menu_on_without_daemon_becomes_the_daemon(self):
        self.anchor("bottom-left\n")
        with mock.patch.object(fm, "daemon_pid", return_value=None), mock.patch.object(fm.os, "execv") as execv:
            fm.client("toggle", self.root)
            execv.assert_called_once_with(fm.SELF, [fm.SELF, "daemon", "--request", "toggle"])
            execv.reset_mock()
            self.assertEqual(fm.client("hide", self.root), 0)
            execv.assert_not_called()

    def test_lock_holds_the_pid(self):
        lock = fm.take_lock(self.root)
        self.addCleanup(lock.close)
        with open(os.path.join(self.root, fm.PID_FILE), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), str(os.getpid()))
        # flock is per open file: a second open of the same file is refused.
        self.assertIsNone(fm.take_lock(self.root))

    def test_live_session(self):
        cmdline = os.path.join(self.dir, "cmdline")
        self.write(cmdline, "BOOT_IMAGE=/live/vmlinuz boot=live components quiet\n")
        self.assertTrue(fm.is_live(cmdline))
        self.write(cmdline, "BOOT_IMAGE=/vmlinuz root=UUID=x ro quiet\n")
        self.assertFalse(fm.is_live(cmdline))
        self.assertFalse(fm.is_live(os.path.join(self.dir, "missing")))


class PlacesTest(unittest.TestCase):
    def test_existing_folders_after_home(self):
        dirs = {"DOCUMENTS": "/home/u/Documents", "PICTURES": "/home/u/Pictures", "MUSIC": None,
                "VIDEOS": "/home/u", "DOWNLOAD": "/home/u/Downloads"}
        exists = {"/home/u/Documents", "/home/u/Downloads"}
        self.assertEqual(fm.places("/home/u", dirs, isdir=lambda p: p in exists),
                         [("Home", "/home/u"), ("Documents", "/home/u/Documents"),
                          ("Downloads", "/home/u/Downloads")])

    def test_trash_icon_shows_whether_it_is_empty(self):
        self.assertEqual(fm.trash_icon(0), "user-trash")
        self.assertEqual(fm.trash_icon(3), "user-trash-full")

    def test_locations_are_gvfs_places_with_trash_among_them(self):
        uris = [uri for _label, _icon, uri in fm.LOCATIONS]
        self.assertEqual(uris, ["recent:///", "trash:///"])
        self.assertIn(fm.TRASH, uris)


class SuperTapTest(unittest.TestCase):
    def test_quick_tap(self):
        tap = fm.SuperTap()
        tap.update(True, False, 1000)
        tap.update(False, False, 1150)
        self.assertTrue(tap.is_tap(1160))

    def test_hold_is_not_a_tap(self):
        tap = fm.SuperTap()
        tap.update(True, False, 1000)
        tap.update(False, False, 1000 + fm.TAP_MS + 50)
        self.assertFalse(tap.is_tap(1000 + fm.TAP_MS + 60))

    def test_request_before_the_release_arrives(self):
        tap = fm.SuperTap()
        tap.update(True, False, 1000)
        self.assertTrue(tap.is_tap(1100))

    def test_with_another_modifier_is_not_a_tap(self):
        tap = fm.SuperTap()
        tap.update(True, False, 1000)
        tap.update(True, True, 1050)
        tap.update(True, False, 1080)
        tap.update(False, False, 1100)
        self.assertFalse(tap.is_tap(1110))

    def test_a_new_press_starts_over(self):
        tap = fm.SuperTap()
        tap.update(True, True, 1000)            # Super+Ctrl+..., no request from labwc
        tap.update(False, False, 3000)
        tap.update(True, False, 5000)
        tap.update(False, False, 5100)
        self.assertTrue(tap.is_tap(5110))

    def test_without_modifier_state_any_request_counts(self):
        self.assertTrue(fm.SuperTap().is_tap(1000))

    def test_stale_release(self):
        tap = fm.SuperTap()
        tap.update(True, False, 1000)
        tap.update(False, False, 3000)
        self.assertTrue(tap.is_tap(3000 + fm.TAP_STALE_MS + 1))

    def test_below_the_shortcut_sheet(self):
        # flickos-shortcuts shows its sheet after HOLD_MS (700): never both.
        self.assertLess(fm.TAP_MS, 700)


class PowerTest(unittest.TestCase):
    def test_no_lock_in_the_live_session(self):
        self.assertEqual([item[0] for item in fm.power_items(live=False)],
                         ["lock", "logout", "restart", "shutdown"])
        self.assertEqual([item[0] for item in fm.power_items(live=True)], ["logout", "restart", "shutdown"])

    def test_what_closes_the_apps_asks_for_a_second_click(self):
        ids = {item[0] for item in fm.POWER}
        self.assertEqual(set(fm.CONFIRM), {"logout", "restart", "shutdown"})
        self.assertLessEqual(set(fm.CONFIRM), ids)
        for item_id, text in fm.CONFIRM.items():
            self.assertTrue(text.startswith("Click again to "), text)

    def test_second_click_runs(self):
        step = fm.TwoStep()
        self.assertEqual(step.click("shutdown"), "arm")
        self.assertEqual(step.armed, "shutdown")
        self.assertEqual(step.click("shutdown"), "run")
        self.assertIsNone(step.armed)
        self.assertEqual(step.click("shutdown"), "arm")     # starts over

    def test_lock_runs_at_once_and_disarms(self):
        step = fm.TwoStep()
        self.assertEqual(step.click("lock"), "run")
        step.click("restart")
        self.assertEqual(step.click("lock"), "run")
        self.assertIsNone(step.armed)

    def test_another_button_is_armed_instead(self):
        step = fm.TwoStep()
        step.click("restart")
        self.assertEqual(step.click("shutdown"), "arm")
        self.assertEqual(step.armed, "shutdown")
        self.assertEqual(step.click("restart"), "arm")

    def test_disarm(self):
        step = fm.TwoStep()
        step.click("logout")
        step.disarm()
        self.assertEqual(step.click("logout"), "arm")

    def test_run_starts_the_command(self):
        """Menu.run (the power buttons, Settings, the phone popup's buttons)
        with the system's GLib: PyGObject 3.58's GLib.spawn_async raised
        AssertionError for the flags it had, and nothing ran."""
        try:
            from gi.repository import Gio, GLib
        except ImportError:
            self.skipTest("python3-gi is not installed")
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            done = os.path.join(folder, "done")
            menu = SimpleNamespace(Gio=Gio, GLib=GLib, hide=lambda: None, hide_quick=lambda: None,
                                   hide_phone=lambda: None)
            fm.Menu.run(menu, ["sh", "-c", 'echo out; echo err >&2; touch "$0"', done])
            deadline = time.monotonic() + 5
            while not os.path.exists(done) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(os.path.exists(done))
            with mock.patch.object(fm, "warn") as warn:
                fm.Menu.run(menu, [os.path.join(folder, "missing")])
            warn.assert_called_once()


class FastPathTest(Environment):
    def test_requests_import_no_gtk(self):
        """toggle/super/hide/show must stay a plain Python start: no gi, no argparse."""
        code = ("import sys, runpy; sys.argv = ['flickos-menu', 'hide']\n"
                "try:\n    runpy.run_path(%r, run_name='__main__')\n"
                "except SystemExit:\n    pass\n"
                "print(' '.join(m for m in ('gi', 'argparse', 'configparser') if m in sys.modules))" % SCRIPT)
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(done.stdout.strip(), "")

    def test_usage(self):
        done = subprocess.run([sys.executable, SCRIPT, "nonsense"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)


class QuickClientTest(Environment):
    """Quick Settings' requests: `quick` reaches the daemon through the
    request file and SIGUSR1; the daemon runs while either window is on."""

    def quick(self, text="bottom-right\n"):
        self.write(os.path.join(self.root, fm.QUICK), text)

    def test_corner(self):
        self.assertIsNone(fm.read_quick(self.root))
        self.quick("top-right\n")
        self.assertEqual(fm.read_quick(self.root), "top-right")
        self.quick("bottom-left\n")     # not a corner of the status icons
        self.assertIsNone(fm.read_quick(self.root))
        self.assertIsNone(fm.read_quick(None))

    def test_off_does_nothing(self):
        self.write(os.path.join(self.root, fm.ANCHOR), "bottom-left\n")
        with mock.patch.object(fm.os, "execvp") as execvp, mock.patch.object(fm.os, "execv") as execv, \
                mock.patch.object(fm.os, "kill") as kill:
            self.assertEqual(fm.client("quick", self.root), 0)
            execvp.assert_not_called()
            execv.assert_not_called()
            kill.assert_not_called()

    def test_on_signals_the_daemon_with_its_word(self):
        self.quick()
        signals = fm.request_signals()
        with mock.patch.object(fm, "daemon_pid", return_value=77), mock.patch.object(fm.os, "kill") as kill, \
                mock.patch.object(fm.os, "execv") as execv:
            self.assertEqual(fm.client("quick", self.root), 0)
            kill.assert_called_once_with(77, signals["toggle"])
            self.assertEqual(fm.take_request(self.root), "quick")
            execv.assert_not_called()

    def test_on_without_daemon_becomes_the_daemon(self):
        """The panel's click wrote its word before pkill found no daemon: the
        new daemon gets the request, and the word is gone so the apps button's
        next plain SIGUSR1 opens the start menu."""
        self.quick()
        self.write(os.path.join(self.root, fm.REQUEST_FILE), "quick\n")
        with mock.patch.object(fm, "daemon_pid", return_value=None), mock.patch.object(fm.os, "execv") as execv:
            fm.client("quick", self.root)
            execv.assert_called_once_with(fm.SELF, [fm.SELF, "daemon", "--request", "quick"])
        self.assertIsNone(fm.take_request(self.root))

    def test_start_menu_off_quick_on(self):
        """The apps button is fuzzel, but hide still reaches the daemon (a
        desktop click closes Quick Settings)."""
        self.quick()
        with mock.patch.object(fm.os, "execvp") as execvp, mock.patch.object(fm, "daemon_pid", return_value=77), \
                mock.patch.object(fm.os, "kill") as kill:
            fm.client("toggle", self.root)
            execvp.assert_called_once_with("sh", fm.FALLBACK_LAUNCHER)
            self.assertEqual(fm.client("hide", self.root), 0)
            kill.assert_called_once_with(77, fm.request_signals()["hide"])

    def test_fast_path_knows_quick(self):
        self.assertIn("quick", fm.REQUESTS)
        self.assertIn("quick", fm.FILE_REQUESTS)


class PhoneClientTest(Environment):
    """The phone popup's requests, the same path as Quick Settings: the word
    `phone` in the request file, then SIGUSR1."""

    def phone(self, text="bottom-right\n"):
        self.write(os.path.join(self.root, fm.PHONE), text)

    def test_corner(self):
        self.assertIsNone(fm.read_phone(self.root))
        self.phone("top-right\n")
        self.assertEqual(fm.read_phone(self.root), "top-right")
        self.phone("bottom-left\n")        # not a corner of the phone button
        self.assertIsNone(fm.read_phone(self.root))
        self.assertIsNone(fm.read_phone(None))

    def test_off_does_nothing(self):
        with mock.patch.object(fm.os, "execv") as execv, mock.patch.object(fm.os, "kill") as kill:
            self.assertEqual(fm.client("phone", self.root), 0)
            execv.assert_not_called()
            kill.assert_not_called()

    def test_on_signals_the_daemon_with_its_word(self):
        self.phone()
        with mock.patch.object(fm, "daemon_pid", return_value=77), mock.patch.object(fm.os, "kill") as kill, \
                mock.patch.object(fm.os, "execv") as execv:
            self.assertEqual(fm.client("phone", self.root), 0)
            kill.assert_called_once_with(77, fm.request_signals()["toggle"])
            self.assertEqual(fm.take_request(self.root), "phone")
            execv.assert_not_called()

    def test_on_without_daemon_becomes_the_daemon(self):
        self.phone()
        with mock.patch.object(fm.os, "execv") as execv:
            self.assertEqual(fm.client("phone", self.root), 1)
            execv.assert_called_once_with(fm.SELF, [fm.SELF, "daemon", "--request", "phone"])

    def test_phone_alone_keeps_the_daemon(self):
        """The apps button is fuzzel, and a desktop click still reaches the daemon."""
        self.phone()
        with mock.patch.object(fm.os, "execvp") as execvp, mock.patch.object(fm, "daemon_pid", return_value=77), \
                mock.patch.object(fm.os, "kill") as kill:
            fm.client("toggle", self.root)
            execvp.assert_called_once_with("sh", fm.FALLBACK_LAUNCHER)
            self.assertEqual(fm.client("hide", self.root), 0)
            kill.assert_called_once_with(77, fm.request_signals()["hide"])

    def test_fast_path_imports_no_gtk(self):
        code = ("import sys, runpy; sys.argv = ['flickos-menu', 'phone']\n"
                "try:\n    runpy.run_path(%r, run_name='__main__')\n"
                "except SystemExit:\n    pass\n"
                "print(' '.join(m for m in ('gi', 'argparse', 'configparser') if m in sys.modules))" % SCRIPT)
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(done.stdout.strip(), "")


class PhoneLogicTest(unittest.TestCase):
    """What the popup draws, without GTK. Tiles come from actions; a command
    that isn't flickos-phone is not run."""

    def test_phone_line(self):
        self.assertEqual(fph.phone_line(None), ("No phone paired", "Add one in Phone Settings"))
        self.assertEqual(fph.phone_line({"name": "Pixel", "connected": True, "battery": [80, True]}),
                         ("Pixel", "Connected · 80 %, charging"))
        self.assertEqual(fph.phone_line({"name": "Pixel", "connected": False}), ("Pixel", "Not connected"))

    def test_tiles_are_the_shown_actions_and_nothing_else(self):
        rows = [
            {"id": "files", "label": "Send Files to Phone…", "icon": "document-send", "shown": True,
             "command": ["flickos-phone", "send", "--choose", "--notify"]},
            {"id": "screen", "label": "Show Phone Screen", "icon": "video-display", "shown": False,
             "command": ["flickos-phone-screen"]},
            {"id": "evil", "label": "Run this", "icon": "phone", "shown": True, "command": ["sh", "-c", "rm"]},
            {"id": "odd", "label": "No", "shown": True, "command": "flickos-phone"},
        ]
        tiles = fph.action_tiles(rows)
        self.assertEqual([tile["id"] for tile in tiles], ["files"])
        self.assertEqual(tiles[0]["command"][0], "flickos-phone")
        shown = dict(rows[1], shown=True)
        self.assertEqual(fph.action_tiles([shown])[0]["command"], ["flickos-phone-screen"])
        # The short words when flickos-phone sends them, else the label.
        self.assertEqual(tiles[0]["label"], "Send Files to Phone…")
        self.assertEqual(fph.action_tiles([dict(shown, short="Show Screen")])[0]["label"], "Show Screen")

    def test_tile_icons_are_symbolic_first(self):
        have = {"document-send-symbolic", "document-send", "folder", "phone-symbolic"}
        self.assertEqual(fph.tile_icon("document-send", have.__contains__), "document-send-symbolic")
        self.assertEqual(fph.tile_icon("folder", have.__contains__), "folder")
        self.assertEqual(fph.tile_icon("odd", have.__contains__), "phone-symbolic")
        self.assertEqual(fph.tile_icon("odd", set().__contains__), "application-x-executable")

    def test_several_phones_name_the_one_the_actions_go_to(self):
        state = {"phones": [{"id": "a", "connected": False}, {"id": "b", "connected": True}]}
        self.assertEqual(fph.action_target(state, None), "b")
        self.assertEqual(fph.action_target(state, "a"), "a")
        self.assertIsNone(fph.action_target({"phones": [{"id": "a"}]}, None))

    def test_ringing_and_mute(self):
        self.assertEqual(fph.ringing_rows({}), [])
        self.assertEqual(fph.ringing_rows({"ringing": [{"id": "a", "name": "Pixel", "caller": "Ada"}]}),
                         [{"id": "a", "name": "Pixel", "caller": "Ada"}])
        self.assertEqual(fph.mute_command("a"), ["flickos-phone", "mute", "--to", "a"])

    def test_what_the_phone_plays_stays_hidden_until_it_is_sent(self):
        self.assertIsNone(fph.playing_row({}))
        self.assertIsNone(fph.playing_row({"playing": {"title": "", "artist": ""}}))
        row = fph.playing_row({"playing": {"id": "a", "title": "Song", "artist": "Ada", "playing": True}})
        self.assertEqual((row["title"], row["playing"]), ("Song", True))
        self.assertEqual(fph.player_command("pause", "a"), ["flickos-phone", "player", "pause", "--to", "a"])
        self.assertEqual(fph.player_command("next", ""), ["flickos-phone", "player", "next"])

    def test_newest_three_received(self):
        items = [{"kind": "text", "value": f"t{n}", "device": "Pixel"} for n in range(5)]
        items.append({"kind": "file", "value": "/tmp/gone.jpg", "exists": False})
        rows = fph.popup_received(items)
        self.assertEqual(len(rows), fph.POPUP_RECEIVED)
        self.assertEqual(rows[0][0], "gone.jpg")
        self.assertIsNone(rows[0][3])
        self.assertEqual(rows[0][1], "no longer there")         # as the Phone window says it, last
        self.assertEqual(rows[1][0], "t4")
        self.assertEqual(rows[1][2:], ("Copy", ["wl-copy", "--", "t4"], ["text-x-generic"]))
        page = fph.received_entry({"kind": "page", "value": "https://www.a.org/x"})
        self.assertEqual(page[0], "a.org/x")
        self.assertEqual(page[3], ["xdg-open", "https://www.a.org/x"])
        self.assertEqual(page[4][0], "text-html")
        photo = fph.received_entry({"kind": "file", "value": "/tmp/a.jpg", "openable": True})
        self.assertEqual(photo[4][:2], ["image-jpeg", "image-x-generic"])
        self.assertEqual(fph.received_icons({"kind": "file", "value": "/tmp/blob"}), ["application-octet-stream", "unknown"])
        # An address an app registered with flickos-phone ("app" in its details): opened in that app.
        app = fph.received_entry({"kind": "text", "value": "storyapp://return?v=1&d=x\n", "app": "Story",
                                  "device": "Pixel"})
        self.assertEqual(app[:4], ("For Story", "Pixel", "Open", ["xdg-open", "storyapp://return?v=1&d=x"]))

    def test_watch_folds_into_the_state(self):
        state = {"phones": [{"id": "a", "name": "Pixel", "connected": True}], "received": [], "ringing": []}
        fph.apply_event(state, {"event": "call", "id": "a", "state": "ringing", "caller": "Ada"})
        self.assertEqual(state["ringing"], [{"id": "a", "name": "Pixel", "caller": "Ada"}])
        fph.apply_event(state, {"event": "call", "id": "a", "state": "ended", "caller": ""})
        self.assertEqual(state["ringing"], [])
        fph.apply_event(state, {"event": "playing", "id": "a", "title": "Song", "artist": "Ada", "playing": True})
        self.assertEqual(state["playing"]["title"], "Song")
        fph.apply_event(state, {"event": "playing", "id": "a", "title": "", "artist": ""})
        self.assertIsNone(state["playing"])
        fph.apply_event(state, {"event": "received", "item": {"kind": "text", "value": "hi"}})
        self.assertEqual(state["received"][-1]["value"], "hi")
        fph.apply_event(state, {"event": "battery", "id": "a", "battery": [41, True]})
        self.assertEqual(state["phones"][0]["battery"], [41, True])
        fph.apply_event(state, {"event": "disconnected", "id": "a"})
        self.assertFalse(state["phones"][0]["connected"])
        self.assertIsNone(state["phones"][0]["battery"])

    def test_why_it_is_closed(self):
        self.assertEqual(fph.closed_text({"live": True, "enabled": True}), "Not available in the live session.")
        self.assertIn("off", fph.closed_text({"enabled": False}))
        self.assertEqual(fph.closed_text({"enabled": True, "running": True}), "")


class PhoneCodeTest(unittest.TestCase):
    def test_loaded_only_when_asked(self):
        """The start menu alone never compiles the phone popup."""
        self.assertFalse(hasattr(fm, "PhonePopup"))
        with mock.patch.object(fm, "PHONE_CODE", PHONE_PY):
            self.assertTrue(hasattr(fm.load_phone(), "PhonePopup"))

    def test_phone_uses_no_gtk_before_the_window(self):
        with open(PHONE_PY, encoding="utf-8") as f:
            head = f.read().split("class PhonePopup:")[0]
        self.assertNotIn("gi.repository", head)


class Sys(unittest.TestCase):
    """A fake /sys."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sys = self.tmp.name

    def write(self, relative, text):
        path = os.path.join(self.sys, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        return path

    def connector(self, name, enabled=True):
        """A DRM connector (card1-eDP-1) and its enabled state."""
        self.write(f"devices/drm/card1/{name}/enabled", "enabled" if enabled else "disabled")
        os.makedirs(os.path.join(self.sys, "class/drm"), exist_ok=True)
        os.symlink(os.path.join(self.sys, f"devices/drm/card1/{name}"), os.path.join(self.sys, "class/drm", name))

    def light(self, name, kind, brightness=50, top=100, connector=None):
        folder = f"class/backlight/{name}"
        self.write(f"{folder}/type", kind)
        self.write(f"{folder}/brightness", str(brightness))
        self.write(f"{folder}/max_brightness", str(top))
        if connector:
            os.symlink(os.path.join(self.sys, f"devices/drm/card1/{connector}"),
                       os.path.join(self.sys, folder, "device"))

    def battery(self, name, **files):
        files.setdefault("type", "Battery")
        for key, value in files.items():
            self.write(f"class/power_supply/{name}/{key}", str(value))
        return os.path.join(self.sys, "class/power_supply", name)


class HardwareTest(Sys):
    def test_wifi_devices(self):
        self.write("class/net/lo/type", "772")
        self.write("class/net/enp2s0/type", "1")
        self.write("class/net/wlp3s0/type", "1")
        os.makedirs(os.path.join(self.sys, "class/net/wlp3s0/wireless"))
        self.write("class/net/wlx00/phy80211/name", "phy1")
        self.assertEqual(fq.wifi_devices(self.sys), ["wlp3s0", "wlx00"])
        self.assertEqual(fq.wifi_devices(os.path.join(self.sys, "missing")), [])

    def test_backlight_of_a_screen_that_is_on(self):
        self.connector("card1-eDP-1")
        self.light("intel_backlight", "raw", connector="card1-eDP-1")
        self.assertEqual(fq.backlight(self.sys)[0], "intel_backlight")

    def test_no_backlight_while_its_screen_is_off(self):
        """The laptop's own screen turned off, an HDMI monitor on (phase 0, S2)."""
        self.connector("card1-eDP-1", enabled=False)
        self.connector("card1-HDMI-A-1")
        self.light("intel_backlight", "raw", connector="card1-eDP-1")
        self.assertIsNone(fq.backlight(self.sys))

    def test_firmware_backlight_first(self):
        self.connector("card1-eDP-1")
        self.light("intel_backlight", "raw", connector="card1-eDP-1")
        self.light("acpi_video0", "firmware")
        self.assertEqual(fq.backlight(self.sys)[0], "acpi_video0")

    def test_firmware_backlight_follows_the_built_in_screens(self):
        self.light("acpi_video0", "firmware")
        self.assertEqual(fq.backlight(self.sys)[0], "acpi_video0")      # nothing to ask: on
        self.connector("card1-LVDS-1", enabled=False)
        self.assertIsNone(fq.backlight(self.sys))

    def test_backlight_the_user_cant_change(self):
        """Without brightness-udev's rule the file is root's: no slider."""
        self.light("acpi_video0", "firmware")
        self.assertIsNone(fq.backlight(self.sys, access=lambda path, mode: False))

    def test_desktop_without_backlight(self):
        self.assertIsNone(fq.backlight(self.sys))
        self.light("odd", "unknown")
        self.assertIsNone(fq.backlight(self.sys))

    def test_brightness_percent(self):
        self.light("intel_backlight", "raw", brightness=937, top=937)
        self.assertEqual(fq.brightness_percent(os.path.join(self.sys, "class/backlight/intel_backlight")), 100)
        self.light("half", "raw", brightness=468, top=937)
        self.assertEqual(fq.brightness_percent(os.path.join(self.sys, "class/backlight/half")), 50)
        self.assertIsNone(fq.brightness_percent(os.path.join(self.sys, "missing")))

    def test_batteries_not_a_mouses(self):
        self.battery("BAT0", capacity=80, status="Discharging")
        self.battery("hidpp_battery_0", scope="Device", capacity=50, status="Discharging")
        self.write("class/power_supply/AC0/type", "Mains")
        self.assertEqual([os.path.basename(p) for p in fq.batteries(self.sys)], ["BAT0"])


class BatteryTest(Sys):
    def state(self, *folders):
        return fq.battery_state(list(folders))

    def test_discharging_with_time_left(self):
        bat = self.battery("BAT0", capacity=82, status="Discharging", energy_now=31000000, power_now=10000000,
                           energy_full=38000000)
        state = self.state(bat)
        self.assertEqual(fq.battery_text(state), "82%, 3:06 left")
        self.assertEqual(fq.battery_icon(state), "battery-level-80-symbolic")

    def test_charging_with_charge_and_current(self):
        bat = self.battery("BAT0", capacity=50, status="Charging", charge_now=2000000, charge_full=4000000,
                           current_now=-2000000)
        state = self.state(bat)
        self.assertEqual(fq.battery_text(state), "50%, charging, full in 1:00")
        self.assertEqual(fq.battery_icon(state), "battery-level-50-charging-symbolic")

    def test_full_plugged_and_unknown(self):
        self.assertEqual(fq.battery_text(self.state(self.battery("A", capacity=100, status="Full"))),
                         "100%, fully charged")
        self.assertEqual(fq.battery_icon(self.state(self.battery("A", capacity=100, status="Full"))),
                         "battery-level-100-charged-symbolic")
        self.assertEqual(fq.battery_text(self.state(self.battery("B", capacity=79, status="Not charging"))),
                         "79%, plugged in")
        self.assertEqual(fq.battery_text(self.state(self.battery("C", capacity=5, status="Unknown"))), "5%")

    def test_no_rate_no_time(self):
        bat = self.battery("BAT0", capacity=40, status="Discharging", energy_now=1, energy_full=2, power_now=0)
        self.assertEqual(fq.battery_text(self.state(bat)), "40%")

    def test_two_batteries_together(self):
        """A ThinkPad's two: one level, one time, discharging if either is."""
        one = self.battery("BAT0", capacity=100, status="Unknown", energy_now=20000000, energy_full=20000000,
                           power_now=0)
        two = self.battery("BAT1", capacity=0, status="Discharging", energy_now=0, energy_full=20000000,
                           power_now=10000000)
        percent, status, hours = self.state(one, two)
        self.assertEqual((percent, status, hours), (50, "Discharging", 2.0))

    def test_without_capacity(self):
        self.assertIsNone(self.state(self.battery("BAT0", status="Unknown")))
        self.assertIsNone(self.state())


class OwnersTest(unittest.TestCase):
    """Reading the owners' answers and the commands that change them (ADR-005)."""

    def test_nmcli_escapes(self):
        self.assertEqual(fq.nmcli_fields(r"wlp3s0:wifi:connected:Cafe\: 2nd floor"),
                         ["wlp3s0", "wifi", "connected", "Cafe: 2nd floor"])
        self.assertEqual(fq.nmcli_fields(r"a\\b:c"), ["a\\b", "c"])

    def test_wifi(self):
        devices = ("wlp3s0:wifi:connected:MikroTik-8B3942\nlo:loopback:connected (externally):lo\n"
                   "p2p-dev-wlp3s0:wifi-p2p:disconnected:\nenp2s0:ethernet:unavailable:\n")
        self.assertEqual(fq.parse_wifi("enabled\n", devices), (True, "MikroTik-8B3942"))
        self.assertEqual(fq.parse_wifi("disabled\n", devices), (False, "Off"))
        self.assertEqual(fq.parse_wifi("enabled\n", "wlp3s0:wifi:disconnected:\n"), (True, "Not connected"))
        self.assertEqual(fq.parse_wifi("enabled\n", "wlp3s0:wifi:connecting (configuring):Home\n"),
                         (True, "Connecting…"))

    def test_control(self):
        text = ("night-light.enabled\tno\tuser\nnight-light.temperature\t4000\tdefault\n"
                "notifications.do-not-disturb\tyes\tuser\n")
        values = fq.parse_control(text)
        self.assertEqual((values["night-light.enabled"], values["notifications.do-not-disturb"]), ("no", "yes"))
        self.assertEqual(set(fq.CONTROL_KEYS.values()) - set(values), set())

    def test_tiler(self):
        off = '{"text": " ", "alt": "off", "class": ["off", "monocle"], "ratio": 55, "gap": 8}'
        on = '{"text": " ", "alt": "master-stack", "class": ["on", "master-stack"]}'
        modes = fq.parse_modes("master-stack\tMaster and stack\ncolumns\tColumns\n")
        self.assertEqual(fq.parse_tiler(off, modes), (False, "Off"))
        self.assertEqual(fq.parse_tiler(on, modes), (True, "Master and stack"))
        self.assertEqual(fq.parse_tiler(on), (True, "Master stack"))       # before the names are read

    def test_phone(self):
        phone = {"id": "e", "name": "HMD CREST", "connected": False}
        state = {"enabled": True, "live": False, "phones": [phone]}
        self.assertEqual(fq.parse_phone(json.dumps(state)), (True, True, "Not connected"))
        phone["connected"] = True
        self.assertEqual(fq.parse_phone(json.dumps(state)), (True, True, "HMD CREST"))
        state["enabled"] = False
        self.assertEqual(fq.parse_phone(json.dumps(state)), (True, False, "Off"))
        self.assertFalse(fq.parse_phone(json.dumps(dict(state, phones=[])))[0])       # none paired: no tile
        self.assertFalse(fq.parse_phone(json.dumps(dict(state, live=True)))[0])

    def test_volume(self):
        self.assertEqual(fq.parse_volume("Volume: 0.41\n"), (41, False))
        self.assertEqual(fq.parse_volume("Volume: 1.00 [MUTED]\n"), (100, True))
        with self.assertRaises(ValueError):
            fq.parse_volume("")
        self.assertEqual(fq.volume_icon(41, True), "audio-volume-muted-symbolic")
        self.assertEqual(fq.volume_icon(0, False), "audio-volume-muted-symbolic")
        self.assertEqual(fq.volume_icon(20, False), "audio-volume-low-symbolic")
        self.assertEqual(fq.volume_icon(50, False), "audio-volume-medium-symbolic")
        self.assertEqual(fq.volume_icon(90, False), "audio-volume-high-symbolic")

    def test_change_commands(self):
        """The owners' own commands, as the keys and Settings run them."""
        self.assertEqual(fq.change_command("wifi", False), ["nmcli", "radio", "wifi", "off"])
        self.assertEqual(fq.change_command("dnd", True),
                         ["flickos-control", "set", "notifications.do-not-disturb", "yes"])
        self.assertEqual(fq.change_command("night", False), ["flickos-control", "set", "night-light.enabled", "no"])
        self.assertEqual(fq.change_command("tiler", True), ["flick-tiler", "on"])
        self.assertEqual(fq.change_command("phone", False), ["flickos-phone", "set", "enabled", "no"])
        self.assertEqual(fq.change_command("volume", 55), ["wpctl", "set-volume", "-l", "1.0", fq.SINK, "55%"])
        self.assertEqual(fq.change_command("mute", None), ["wpctl", "set-mute", fq.SINK, "toggle"])
        self.assertEqual(fq.change_command("brightness", 30, "intel_backlight"),
                         ["brightnessctl", "-q", "-d", "intel_backlight", "set", "30%"])
        for key, *_ in fq.QUICK_TILES:
            self.assertEqual(fq.change_command(key, True)[0], fq.TILE_PROGRAMS[key])
            self.assertIn(fq.TILE_READS[key], fq.QUICK_READS)
        with self.assertRaises(ValueError):
            fq.change_command("bluetooth", True)

    def test_error_line(self):
        self.assertEqual(fq.error_line("flickos-control: error: no such key\n"), "no such key")
        self.assertEqual(fq.error_line("Warning\nError: Connection activation failed.\n"),
                         "Connection activation failed.")
        self.assertEqual(fq.error_line(""), "")


class TilesTest(Sys):
    def which(self, missing=()):
        return lambda program: None if program in missing else f"/usr/bin/{program}"

    def test_everything(self):
        os.makedirs(os.path.join(self.sys, "class/net/wlp3s0/wireless"))
        self.assertEqual(fq.quick_tiles(self.which(), self.sys, phone_paired=True),
                         ["wifi", "dnd", "night", "tiler", "phone"])

    def test_left_out_when_they_cant_be_used(self):
        """No Wi-Fi device, no paired phone, the live session, a missing owner (WIN-9)."""
        self.assertEqual(fq.quick_tiles(self.which(), self.sys), ["dnd", "night", "tiler"])
        self.assertEqual(fq.quick_tiles(self.which(), self.sys, live=True, phone_paired=True),
                         ["dnd", "night", "tiler"])
        self.assertEqual(fq.quick_tiles(self.which(("flickos-control", "flickos-phone")), self.sys,
                                        phone_paired=True), ["tiler"])


class CoalescerTest(unittest.TestCase):
    def test_one_in_flight_newest_wins(self):
        started = []
        slider = fq.Coalescer(lambda value, done: started.append((value, done)))
        for value in (10, 20, 30, 40):      # a drag
            slider.set(value)
        self.assertEqual([value for value, _ in started], [10])
        started[0][1](True, "")
        self.assertEqual([value for value, _ in started], [10, 40])
        started[1][1](True, "")
        self.assertFalse(slider.busy)
        self.assertEqual(len(started), 2)       # nothing newer

    def test_back_to_the_value_on_its_way(self):
        started = []
        slider = fq.Coalescer(lambda value, done: started.append((value, done)))
        slider.set(10)
        slider.set(20)
        slider.set(10)
        started[0][1]()
        self.assertEqual(len(started), 1)


class QuickCodeTest(unittest.TestCase):
    def test_loaded_only_when_asked(self):
        """The start menu alone never compiles Quick Settings' code."""
        self.assertFalse(hasattr(fm, "QuickSettings"))
        with mock.patch.object(fm, "QUICK_CODE", QUICK):
            self.assertTrue(hasattr(fm.load_quick(), "QuickSettings"))

    def test_quick_uses_no_gtk_before_the_window(self):
        """The helpers above the window import nothing but the standard library."""
        with open(QUICK, encoding="utf-8") as f:
            head = f.read().split("class QuickSettings:")[0]
        self.assertNotIn("gi.repository", head)


class StyleTest(unittest.TestCase):
    def test_only_theme_colors(self):
        """The Dark and Light styles recolor the menu through the GTK theme."""
        import re
        with open(os.path.join(PACKAGE, "usr/share/flickos/menu/style.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", css))


class GapTest(unittest.TestCase):
    def test_every_popup_has_the_same_gap(self):
        import re
        for name in ("quick.py", "phone.py"):
            with open(os.path.join(PACKAGE, "usr/share/flickos/menu", name), encoding="utf-8") as f:
                self.assertEqual(int(re.search(r"^POPUP_GAP = (\d+)", f.read(), re.M).group(1)), fm.POPUP_GAP, name)


class FadeCurveTest(unittest.TestCase):
    def test_ends(self):
        self.assertEqual(fm.fade_opacity(0.0, 1.0, 0, 100, True), (0.0, False))
        self.assertEqual(fm.fade_opacity(0.0, 1.0, 100, 100, True), (1.0, True))
        self.assertEqual(fm.fade_opacity(1.0, 0.0, 250, 80, False), (0.0, True))     # late frame
        self.assertEqual(fm.fade_opacity(0.4, 1.0, 0, 0, True), (1.0, True))

    def test_fade_in_is_fast_at_first_and_fade_out_slow(self):
        # One 60 Hz frame into the fade in, it is already well visible
        # (docs/design/flickos-fades.md, ADR-003); a fade out starts gently.
        self.assertGreater(fm.fade_opacity(0.0, 1.0, 16.7, fm.FADE_IN_MS, True)[0], 0.4)
        self.assertGreater(fm.fade_opacity(1.0, 0.0, 16.7, fm.FADE_OUT_MS, False)[0], 0.98)

    def test_from_where_it_was(self):
        value, _ = fm.fade_opacity(0.5, 1.0, 50, 100, True)
        self.assertTrue(0.5 < value < 1.0)


class FakeWindow:
    def __init__(self):
        self.shown = False
        self.opacity = 1.0
        self.maps = 0
        self.ticks = {}
        self.region = None

    def get_visible(self):
        return self.shown

    def show(self):
        if not self.shown:
            self.maps += 1
        self.shown = True

    def hide(self):
        self.shown = False

    def add_tick_callback(self, callback):
        key = len(self.ticks) + 1
        self.ticks[key] = callback
        return key

    def remove_tick_callback(self, key):
        del self.ticks[key]

    def input_shape_combine_region(self, region):
        self.region = region


class FakeGtk:
    """What Fader needs of Gtk and GtkLayerShell."""

    def __init__(self):
        self.animations = True
        self.keyboard = {}
        gtk = self

        class Widget:
            @staticmethod
            def get_opacity(window):
                return window.opacity

            @staticmethod
            def set_opacity(window, value):
                window.opacity = value

        class Settings:
            @staticmethod
            def get_default():
                return mock.Mock(props=mock.Mock(gtk_enable_animations=gtk.animations))

        class LayerShell:
            KeyboardMode = mock.Mock(ON_DEMAND="on-demand", NONE="none")

            @staticmethod
            def set_keyboard_mode(window, mode):
                gtk.keyboard[window] = mode

        self.Widget, self.Settings, self.LayerShell = Widget, Settings, LayerShell


class FaderTest(unittest.TestCase):
    def setUp(self):
        self.gtk = FakeGtk()
        self.window = FakeWindow()
        self.fader = fm.Fader((self.gtk, self.gtk.LayerShell), self.window)

    def frames(self, *times_ms):
        """Run the window's tick callbacks at these frame times."""
        for ms in times_ms:
            for key, callback in list(self.window.ticks.items()):
                if not callback(self.window, mock.Mock(get_frame_time=lambda ms=ms: ms * 1000)):
                    self.window.ticks.pop(key, None)


    def test_input_region(self):
        """With an arrow, the window's clicks are the region's, except while
        a fade out has taken them away."""
        self.window.region = "unset"
        self.fader.update_input()
        self.assertIsNone(self.window.region)   # the whole window
        self.fader.input_region = lambda: "frame and arrow"
        self.fader.update_input()
        self.assertEqual(self.window.region, "frame and arrow")
        self.fader.fading_out = True
        self.window.region = "empty"
        self.fader.update_input()
        self.assertEqual(self.window.region, "empty")

    def test_fades_in_from_zero_and_stops_ticking(self):
        self.fader.show()
        self.assertTrue(self.window.shown)
        self.assertEqual(self.window.opacity, 0.0)
        self.frames(0, 17, 33)
        self.assertTrue(0.0 < self.window.opacity < 1.0)
        self.frames(100)
        self.assertEqual(self.window.opacity, 1.0)
        self.assertEqual(self.window.ticks, {})
        self.assertIsNone(self.fader.tick)

    def test_a_fade_out_takes_no_input_then_hides(self):
        self.fader.show()
        self.frames(0, 100)
        self.fader.hide()
        self.assertFalse(self.fader.visible())          # a toggle now shows it again
        self.assertTrue(self.window.shown)
        self.assertEqual(self.gtk.keyboard[self.window], "none")
        self.fader.hide()                               # focus-out during the fade: nothing new
        self.assertEqual(len(self.window.ticks), 1)
        self.frames(200, 280)
        self.assertFalse(self.window.shown)
        self.assertEqual(self.gtk.keyboard[self.window], "on-demand")
        self.assertIsNone(self.window.region)

    def test_showing_during_a_fade_out_maps_it_again(self):
        # labwc gives the keyboard to a layer surface only when it is mapped.
        self.fader.show()
        self.frames(0, 100)
        self.fader.hide()
        self.frames(200, 250)
        reached = self.window.opacity
        self.assertTrue(0.0 < reached < 1.0)
        self.fader.show()
        self.assertEqual(self.window.maps, 2)
        self.assertTrue(self.fader.visible())
        self.assertEqual(self.gtk.keyboard[self.window], "on-demand")
        self.assertIsNone(self.window.region)
        self.assertEqual(self.window.opacity, reached)
        self.frames(300, 400)
        self.assertEqual(self.window.opacity, 1.0)
        self.assertTrue(self.window.shown)

    def test_showing_a_shown_window_changes_nothing(self):
        self.fader.show()
        self.frames(0, 100)
        self.fader.show()
        self.assertEqual(self.window.maps, 1)
        self.assertEqual(self.window.ticks, {})

    def test_without_animations_at_once(self):
        self.gtk.animations = False
        self.fader.show()
        self.assertEqual((self.window.shown, self.window.opacity, self.window.ticks), (True, 1.0, {}))
        self.fader.hide()
        self.assertFalse(self.window.shown)
        self.assertEqual(self.window.ticks, {})

    def test_full_screen_never_fades(self):
        fader = fm.Fader((self.gtk, self.gtk.LayerShell), self.window, enabled=False)
        fader.show()
        self.assertEqual((self.window.opacity, self.window.ticks), (1.0, {}))

    def test_hide_now_during_a_fade_out(self):
        self.fader.show()
        self.frames(0, 100)
        self.fader.hide()
        self.fader.hide_now()
        self.assertFalse(self.window.shown)
        self.assertEqual(self.window.ticks, {})
        self.assertEqual(self.gtk.keyboard[self.window], "on-demand")
        self.assertEqual(self.window.opacity, 1.0)
        self.assertFalse(self.fader.fading_out)

    def test_grid_does_not_fade(self):
        self.assertFalse(fm.GridView.fades)
        self.assertTrue(fm.ClassicView.fades and fm.CategoriesView.fades)


class GridClickTest(unittest.TestCase):
    """The grid closes on the release of a background click, never the press:
    unmapped between the two, GDK kept the press's grab and every later click
    on a tile came to the window and closed the menu. A click or Enter brings
    an open app forward; a middle click, Ctrl+click or Ctrl+Enter starts
    another copy."""

    CTRL = 4    # Gdk.ModifierType.CONTROL_MASK

    def setUp(self):
        from types import SimpleNamespace
        self.tile, self.hides, self.launched, self.state = SimpleNamespace(app="foot"), [], [], 0
        view = self.view = SimpleNamespace(
            flow=SimpleNamespace(get_child_at_pos=lambda x, y: self.tile if y < 100 else None,
                                 get_selected_children=lambda: [self.tile]),
            Gtk=SimpleNamespace(get_event_widget=lambda event: event.widget,
                                get_current_event_state=lambda: (True, self.state)),
            Gdk=SimpleNamespace(ModifierType=SimpleNamespace(CONTROL_MASK=self.CTRL),
                                KEY_Return=1, KEY_KP_Enter=2, KEY_ISO_Enter=3),
            menu=SimpleNamespace(hide=lambda: self.hides.append(True),
                                 launch=lambda app, focus=False: self.launched.append((app, focus))),
            background_press=False, middle_press=None)
        view.tile_at = lambda event: fm.GridView.tile_at(view, event)
        view.in_power_corner = lambda event: event.widget == "power"
        view.on_activate = lambda new_window=False: fm.GridView.on_activate(view, new_window)

    def event(self, widget, y=50, button=1):
        from types import SimpleNamespace
        return SimpleNamespace(widget=widget, x=10, y=y, button=button)

    def click(self, event):
        pressed = fm.GridView.on_press(self.view, None, event)
        hides = len(self.hides)
        released = fm.GridView.on_release(self.view, None, event)
        return pressed, hides, released

    def test_background_closes_on_release(self):
        self.assertEqual(self.click(self.event("window")), (True, 0, True))
        self.assertEqual(self.hides, [True])

    def test_tile_left_to_the_flow_box(self):
        self.assertEqual(self.click(self.event(self.view.flow)), (False, 0, False))
        self.assertEqual((self.hides, self.launched), ([], []))

    def test_power_buttons_keep_their_clicks(self):
        self.assertEqual(self.click(self.event("power")), (False, 0, False))
        self.assertEqual(self.hides, [])

    def test_space_between_tiles_closes(self):
        self.assertEqual(self.click(self.event(self.view.flow, y=200)), (True, 0, True))
        self.assertEqual(self.hides, [True])

    def test_pointer_selects_the_tile_it_is_over(self):
        from types import SimpleNamespace
        selected = []
        tile = SimpleNamespace(is_selected=lambda: tile in selected)
        self.tile = tile
        self.view.flow.select_child = selected.append
        self.assertFalse(fm.GridView.on_pointer(self.view, None, self.event(None)))
        fm.GridView.on_pointer(self.view, None, self.event(None))       # once only
        fm.GridView.on_pointer(self.view, None, self.event(None, y=200))  # between tiles: kept
        self.assertEqual(selected, [tile])

    def test_click_and_enter_bring_an_open_app_forward(self):
        fm.GridView.on_tile_activated(self.view, None, self.tile)
        fm.GridView.on_activate(self.view)
        self.assertEqual(self.launched, [("foot", True), ("foot", True)])

    def test_ctrl_click_and_ctrl_enter_start_another_copy(self):
        from types import SimpleNamespace
        self.state = self.CTRL
        fm.GridView.on_tile_activated(self.view, None, self.tile)
        self.assertTrue(fm.GridView.on_new_window_key(self.view, None, SimpleNamespace(keyval=1, state=self.CTRL)))
        self.assertFalse(fm.GridView.on_new_window_key(self.view, None, SimpleNamespace(keyval=1, state=0)))
        self.assertEqual(self.launched, [("foot", False), ("foot", False)])

    def test_middle_click_starts_another_copy(self):
        self.assertEqual(self.click(self.event(self.view.flow, button=2)), (True, 0, True))
        self.assertEqual((self.launched, self.hides), ([("foot", False)], []))
        # Let go elsewhere: nothing.
        fm.GridView.on_press(self.view, None, self.event(self.view.flow, button=2))
        self.assertTrue(fm.GridView.on_release(self.view, None, self.event(self.view.flow, y=200, button=2)))
        self.assertEqual(len(self.launched), 1)

    def test_other_buttons_and_lone_releases_do_nothing(self):
        self.assertEqual(self.click(self.event("window", button=3)), (False, 0, False))
        self.assertFalse(fm.GridView.on_release(self.view, None, self.event("window")))
        self.assertFalse(fm.GridView.on_release(self.view, None, self.event(self.view.flow, button=2)))
        self.assertEqual((self.hides, self.launched), ([], []))


class OpenWindowTest(unittest.TestCase):
    """The grid asks flick-tiler's daemon (focus-app) before starting an app."""

    def test_window_ids(self):
        from types import SimpleNamespace
        info = SimpleNamespace(get_startup_wm_class=lambda: "Code")
        self.assertEqual(fm.window_ids(fm.App("com.microsoft.VSCode.desktop", "Code", info=info)),
                         ["com.microsoft.VSCode", "Code"])
        info = SimpleNamespace(get_startup_wm_class=lambda: "My App")    # one line of words
        self.assertEqual(fm.window_ids(fm.App("foot.desktop", "Foot", info=info)), ["foot"])
        self.assertEqual(fm.window_ids(fm.App("firefox-esr.desktop", "Firefox", info=None)), ["firefox-esr"])

    def serve(self, reply):
        """A fake daemon answering one request; returns the root and what it read."""
        import socket
        import threading
        root = tempfile.mkdtemp(prefix="flickos-menu-test-")
        self.addCleanup(shutil.rmtree, root)
        os.makedirs(os.path.join(root, "tiler"))
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(os.path.join(root, fm.TILER_CONTROL))
        server.listen(1)
        self.addCleanup(server.close)
        seen = []

        def answer():
            conn, _ = server.accept()
            with conn:
                seen.append(conn.recv(4096).decode())
                conn.sendall(reply)

        thread = threading.Thread(target=answer)
        thread.start()
        self.addCleanup(thread.join)
        return root, seen

    def test_found(self):
        root, seen = self.serve(b'{"text": "", "found": true}\n')
        self.assertTrue(fm.focus_open_window(root, ["foot", "Foot"]))
        self.assertEqual(seen, ["focus-app foot Foot\n"])

    def test_not_found_or_an_older_daemon(self):
        for reply in (b'{"found": false}\n', b'{"error": "unknown command: focus-app"}\n', b"[]\n", b"no\n"):
            root, _ = self.serve(reply)
            self.assertFalse(fm.focus_open_window(root, ["foot"]))

    def test_no_daemon(self):
        root = tempfile.mkdtemp(prefix="flickos-menu-test-")
        self.addCleanup(shutil.rmtree, root)
        self.assertFalse(fm.focus_open_window(root, ["foot"]))
        self.assertFalse(fm.focus_open_window(None, ["foot"]))


PO = os.path.join(PACKAGE, "po")


def po_list(name):
    """The file names in po/POTFILES or po/LINGUAS, comments left out."""
    with open(os.path.join(PO, name), encoding="utf-8") as f:
        return [line.split("#", 1)[0].strip() for line in f if line.split("#", 1)[0].strip()]


PROVIDERS_PY = os.path.join(PACKAGE, "usr/share/flickos/menu/providers.py")
PROVIDERS = os.path.join(PACKAGE, "usr/share/flickos/menu/providers")
with mock.patch.object(fm, "PROVIDERS_CODE", PROVIDERS_PY):
    fp = fm.load_providers()


def everything(_name):
    return "/usr/bin/x"


class ProvidersCodeTest(unittest.TestCase):
    def test_loaded_only_by_the_prompt_style(self):
        """The classic, categories and grid styles never compile it."""
        self.assertFalse(hasattr(fm, "LiveSearch"))
        source = open(SCRIPT, encoding="utf-8").read()
        callers = [line for line in source.splitlines() if "load_providers()" in line and "def " not in line]
        self.assertEqual(len(callers), 1)
        self.assertIn("finder = self.finder = load_providers()", callers[0])

    def test_no_gtk(self):
        with open(PROVIDERS_PY, encoding="utf-8") as f:
            self.assertNotIn("gi.repository", f.read())

    def test_the_menu_gives_it_score(self):
        self.assertIs(fp.score, fm.score)


class ProviderFileTest(unittest.TestCase):
    def write(self, data):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, "test.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        return folder, path

    def test_tasks(self):
        tasks = fp.read_provider(os.path.join(PROVIDERS, "tasks.json"), which=everything)
        self.assertEqual(tasks.kind, "index")
        self.assertIsNone(tasks.prefix)
        names = [row.name for row in tasks.rows]
        self.assertIn("Restart Panel", names)
        self.assertEqual(len(names), len(set(names)))

    def test_tasks_that_end_the_session_ask_twice(self):
        """Log out, restart and shut down: the power buttons' commands, each
        with a second Enter (ADR-018)."""
        tasks = fp.read_provider(os.path.join(PROVIDERS, "tasks.json"), which=everything)
        power = {tuple(command) for item_id, _text, _icon, command in fm.POWER if item_id in fm.CONFIRM}
        asking = {tuple(row.command) for row in tasks.rows if row.confirm}
        self.assertEqual(asking, power)
        for row in tasks.rows:
            if row.command[0] in ("systemctl", "labwc"):
                self.assertTrue(row.confirm, row.name)

    def test_tasks_run_commands_that_exist(self):
        """flickos-layout's subcommands and flickos-control's page (the
        packages beside this one, when they are there)."""
        tasks = fp.read_provider(os.path.join(PROVIDERS, "tasks.json"), which=everything)
        packages = os.path.dirname(PACKAGE)
        sources = {"flickos-layout": "flickos-layouts/usr/bin/flickos-layout",
                   "flick-tiler": "flick-tiler/usr/bin/flick-tiler",
                   "flickos-control": "flickos-control/usr/bin/flickos-control",
                   "flickos-screenshot": "flickos-screenshot/usr/bin/flickos-screenshot"}
        for row in tasks.rows:
            source = sources.get(row.command[0])
            if source is None or not os.path.isfile(os.path.join(packages, source)):
                continue
            with open(os.path.join(packages, source), encoding="utf-8") as f:
                code = f.read()
            word = row.command[-1]
            with self.subTest(row=row.name):
                self.assertTrue(f'"{word}"' in code or f"'{word}'" in code, f"{row.command} isn't in {source}")

    def test_files(self):
        """`/` only for now (Q5), on fdfind, in the home folder."""
        files = fp.read_provider(os.path.join(PROVIDERS, "files.json"), which=everything)
        self.assertEqual((files.kind, files.prefix, files.output), ("live", "/", "paths"))
        self.assertEqual(files.command[0], "fdfind")
        self.assertEqual(files.command[-1], "--", "the text can't be read as an option")
        self.assertIn("--print0", files.command)

    def test_a_missing_program_leaves_it_out(self):
        files = fp.read_provider(os.path.join(PROVIDERS, "files.json"), which=lambda name: None)
        self.assertIsNone(files)
        tasks = fp.read_provider(os.path.join(PROVIDERS, "tasks.json"),
                                 which=lambda name: None if name == "flick-tiler" else "/usr/bin/x")
        self.assertNotIn("flick-tiler", [row.command[0] for row in tasks.rows])
        self.assertTrue(tasks.rows)

    def test_bad_files_are_left_out_with_a_warning(self):
        good = {"name": "Good", "kind": "index", "rows": [{"name": "Hello", "command": ["true"]}]}
        bad = [
            "{", [], {"name": "X", "kind": "plugin"},
            {"name": "X", "kind": "index", "prefix": "=", "rows": []},   # the calculator's own
            {"name": "X", "kind": "index", "prefix": ">", "rows": []},
            {"name": "X", "kind": "index", "limit": 0, "rows": []},
            {"name": "X", "kind": "index", "rows": [{"name": "Y", "command": "rm -rf ~"}]},
            {"name": "X", "kind": "live", "command": ["fdfind"], "output": "html"},
            {"name": "X", "kind": "index"},
        ]
        for data in bad:
            with self.subTest(data=data):
                folder, path = self.write(data)
                shutil.copy(path, os.path.join(folder, "zz.json"))
                with open(os.path.join(folder, "aa.json"), "w", encoding="utf-8") as f:
                    json.dump(good, f)
                with mock.patch.object(fp, "warn") as warned:
                    found = fp.read_providers(folder, which=everything)
                self.assertEqual([provider.name for provider in found], ["Good"])
                self.assertEqual(warned.call_count, 2, warned.call_args_list)  # test.json and zz.json

    def test_no_folder(self):
        self.assertEqual(fp.read_providers("/nonexistent/providers"), [])

    def test_translated_rows_keep_their_english_words(self):
        folder, path = self.write({"name": "T", "kind": "index", "domain": "x",
                                   "rows": [{"name": "Restart Panel", "keys": "panel", "command": ["true"]}]})
        provider = fp.read_provider(path, translator=lambda domain: lambda text: text.upper(), which=everything)
        row = provider.rows[0]
        self.assertEqual(row.name, "RESTART PANEL")
        self.assertEqual(fp.match_rows(provider.rows, "panel", 5), [row])
        self.assertEqual(fp.match_rows(provider.rows, "restart", 5), [row], "the English name finds it")

    def test_matching(self):
        tasks = fp.read_provider(os.path.join(PROVIDERS, "tasks.json"), which=everything)
        self.assertEqual(fp.match_rows(tasks.rows, "restart panel", 5)[0].name, "Restart Panel")
        self.assertEqual(fp.match_rows(tasks.rows, "reboot", 5)[0].name, "Restart")
        self.assertEqual(fp.match_rows(tasks.rows, "screenshot", 1)[0].name, "Screenshot of an Area")
        self.assertEqual(fp.match_rows(tasks.rows, "", 5), [])
        self.assertLessEqual(len(fp.match_rows(tasks.rows, "e", 3)), 3)

    def test_rows_of_programs_are_only_commands(self):
        """A provider's row runs its argument list: it can't ask for the
        terminal path (`>`, the user's shell), whatever it prints."""
        rows = fp.parse_rows(['{"name": "Sneaky", "kind": "terminal", "command": ["true"]}',
                              'not json', '{"name": "No command"}', '',
                              '{"name": "Fine", "command": ["true"], "icon": "x"}'], which=everything)
        self.assertEqual([(row.name, row.kind) for row in rows], [("Sneaky", "command"), ("Fine", "command")])

    def test_prefixes(self):
        files = fp.Provider("f", "Files", "live", prefix="/")
        self.assertEqual(fp.active_prefixes([files]), {"=", ">", "/"})
        self.assertEqual(fp.active_prefixes([], terminal=False), {"="})
        self.assertEqual(fp.split_prefix("/budget", {"/"}), ("/", "budget"))
        self.assertEqual(fp.split_prefix("?ls", {"/"}), (None, "?ls"), "no provider: plain text")
        self.assertEqual(fp.split_prefix("", {"/"}), (None, ""))


class PathRowTest(unittest.TestCase):
    def test_paths_with_spaces_newlines_and_folders(self):
        data = b"/home/u/budget 2026.ods\0/home/u/odd\nname.txt\0/home/u/Budgets/\0/srv/x\0/home/u/part"
        rows, rest = fp.parse_paths(data, "/home/u")
        self.assertEqual(rest, b"/home/u/part")
        self.assertEqual([(row.name, row.detail, row.value) for row in rows],
                         [("budget 2026.ods", "~", "file"), ("odd name.txt", "~", "file"),
                          ("Budgets", "~", "folder"), ("x", "/srv", "file")])
        self.assertEqual(rows[1].path, "/home/u/odd\nname.txt", "the path itself is kept")
        self.assertEqual(rows[2].path, "/home/u/Budgets")

    def test_short_folder(self):
        self.assertEqual(fp.short_folder("/home/u/a/b.txt", "/home/u/"), "~/a")
        self.assertEqual(fp.short_folder("/home/user2/b.txt", "/home/u"), "/home/user2")

    def test_late_rows_never_move_the_selection(self):
        self.assertEqual(fp.merge_late(0, ["a"], ["b"]), 0)
        self.assertEqual(fp.merge_late(-1, [], ["b"]), -1, "an app stays chosen")
        self.assertEqual(fp.merge_late(None, ["a", "b"], ["c"]), 2, "nothing chosen: the first new row")
        self.assertIsNone(fp.merge_late(None, [], []))


class CalculatorTest(unittest.TestCase):
    def answer(self, text, decimal=".", percent_of=False):
        value = fp.calculate(text, decimal, percent_of)
        return None if value is None else fp.format_answer(value, decimal)

    def test_sums(self):
        self.assertEqual(self.answer("15*3"), "45")
        self.assertEqual(self.answer("(4+6)/2"), "5")
        self.assertEqual(self.answer("10/3"), "3.33333333333")
        self.assertEqual(self.answer("0.1+0.2"), "0.3")
        self.assertEqual(self.answer("2^10"), "1024")
        self.assertEqual(self.answer("2**0.5"), "1.41421356237")
        self.assertEqual(self.answer("7 × 6 ÷ 2"), "21")
        self.assertEqual(self.answer("-3 * -3"), "9")
        self.assertEqual(self.answer("240 * 15%"), "36")
        self.assertEqual(self.answer("2**100"), "1.26765060023e+30")

    def test_percent_of_only_after_the_prefix(self):
        self.assertEqual(self.answer("15% of 240", percent_of=True), "36")
        self.assertIsNone(self.answer("15% of 240"))

    def test_searches_are_not_sums(self):
        for text in ("2048", "7zip", "-5", "firefox", "", "  ", "(3)", "1e5"):
            with self.subTest(text=text):
                self.assertIsNone(self.answer(text))
        self.assertEqual(self.answer("2048", percent_of=True), "2048", "after = a number is its own answer")

    def test_no_code_and_no_hang(self):
        for text in ("__import__('os').system('true')", "9**9**9", "2**99999", "(10**999)**999", "1/0", "0**-1",
                     "(-8)**(1/3)", "10.0**400", "x+1", "1;2", "lambda: 1", "[1]*9", "1+", "(" * 150 + "1"):
            with self.subTest(text=text):
                started = time.monotonic()
                self.assertIsNone(self.answer(text, percent_of=True))
                self.assertLess(time.monotonic() - started, 0.1)
        self.assertIsNone(self.answer("1+" * 150 + "1"), "longer than CALC_MAX_LENGTH")

    def test_big_numbers(self):
        self.assertEqual(self.answer("2**4000"), "1.31820409343e+1204")
        self.assertEqual(self.answer("-(2**4000)"), "-1.31820409343e+1204")

    def test_the_users_decimal_sign(self):
        self.assertEqual(self.answer("1,5*2", ","), "3")
        self.assertEqual(self.answer("1/4", ","), "0,25")
        self.assertIsNone(self.answer("1.5*2", ","), "a point where the sign is a comma: unclear")
        self.assertIsNone(self.answer("1,500*2"), "a comma where the sign is a point: unclear")


class FakeTimers:
    def __init__(self):
        self.timers, self.next = {}, 1

    def add(self, ms, callback):
        self.timers[self.next] = (ms, callback)
        self.next += 1
        return self.next - 1

    def remove(self, timer):
        del self.timers[timer]

    def fire(self, ms):
        for timer, (length, callback) in list(self.timers.items()):
            if length == ms and timer in self.timers:
                del self.timers[timer]
                callback()


class FakeProcess:
    def __init__(self, argv, cwd, on_data, on_end):
        self.argv, self.cwd, self.on_data, self.on_end = argv, cwd, on_data, on_end
        self.stopped = False

    def stop(self):
        self.stopped = True


class LiveSearchTest(unittest.TestCase):
    def setUp(self):
        self.timers = FakeTimers()
        self.processes, self.got = [], []
        self.provider = fp.Provider("files.json", "Files", "live", prefix="/", limit=3,
                                    command=["fdfind", "--print0", "--"], output="paths")

        def spawn(*args):
            self.processes.append(FakeProcess(*args))
            return self.processes[-1]

        self.live = fp.LiveSearch(self.provider, lambda rows, done: self.got.append(([r.name for r in rows], done)),
                                  spawn, self.timers.add, self.timers.remove, "/home/u")

    def test_no_process_before_the_pause(self):
        self.live.typed("budget")
        self.assertEqual(self.processes, [])
        self.assertTrue(self.live.running)
        self.timers.fire(fp.LIVE_PAUSE_MS)
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(self.processes[0].argv[-1], "budget")
        self.assertEqual(self.processes[0].argv[:len(fp.LOW_PRIORITY)], fp.LOW_PRIORITY)
        self.assertEqual(self.processes[0].cwd, "/home/u")

    def test_short_text_starts_nothing(self):
        self.live.typed("bu")
        self.assertFalse(self.live.running)
        self.assertEqual(self.timers.timers, {})

    def test_the_next_key_kills_it_and_its_rows_never_show(self):
        self.live.typed("budget")
        self.timers.fire(fp.LIVE_PAUSE_MS)
        first = self.processes[0]
        self.live.typed("budgets")
        self.assertTrue(first.stopped)
        first.on_data(b"/home/u/budget.ods\0")
        first.on_end()
        self.assertEqual(self.got, [])
        self.timers.fire(fp.LIVE_PAUSE_MS)
        self.processes[1].on_data(b"/home/u/budgets.ods\0/home/u/bud")
        self.processes[1].on_data(b"gets/\0")
        self.processes[1].on_end()
        self.assertEqual(self.got, [(["budgets.ods"], False), (["budgets"], False), ([], True)])

    def test_the_limit_of_rows(self):
        self.live.typed("doc")
        self.timers.fire(fp.LIVE_PAUSE_MS)
        self.processes[0].on_data(b"/a/1\0/a/2\0/a/3\0/a/4\0")
        self.assertEqual(self.got, [(["1", "2", "3"], False), ([], True)])
        self.assertTrue(self.processes[0].stopped)
        self.assertEqual(self.timers.timers, {}, "the time limit ends with it")

    def test_the_time_limit(self):
        self.live.typed("doc")
        self.timers.fire(fp.LIVE_PAUSE_MS)
        with mock.patch.object(fp, "warn"):
            self.timers.fire(fp.LIVE_LIMIT_MS)
        self.assertTrue(self.processes[0].stopped)
        self.assertEqual(self.got, [([], True)])

    def test_a_program_that_cant_start(self):
        def spawn(*args):
            raise OSError("no such file")
        live = fp.LiveSearch(self.provider, lambda rows, done: self.got.append((rows, done)), spawn,
                             self.timers.add, self.timers.remove, "/home/u")
        live.typed("doc")
        with mock.patch.object(fp, "warn"):
            self.timers.fire(fp.LIVE_PAUSE_MS)
        self.assertEqual(self.got, [([], True)])
        self.assertFalse(live.running)

    def test_rows_output(self):
        provider = fp.Provider("m.json", "Manuals", "live", prefix="?", limit=5, command=["true"], output="rows")
        live = fp.LiveSearch(provider, lambda rows, done: self.got.append(([r.name for r in rows], done)),
                             lambda *args: self.processes.append(FakeProcess(*args)) or self.processes[-1],
                             self.timers.add, self.timers.remove, "/home/u")
        live.typed("ls(1)")
        self.timers.fire(fp.LIVE_PAUSE_MS)
        with mock.patch.object(fp, "installed", return_value=True):
            self.processes[0].on_data(b'{"name": "ls", "command": ["man", "ls"]}\n{"name": "lsb')
            self.processes[0].on_data(b'lk", "command": ["man", "lsblk"]}')
            self.processes[0].on_end()
        self.assertEqual(self.got, [(["ls"], False), (["lsblk"], False), ([], True)])

    def test_the_text_is_one_argument(self):
        """Quotes, spaces and $() reach the program as typed, as one argument."""
        text = """it's "a" $(touch nope) `x` ; | *"""
        provider = fp.Provider("p.json", "P", "live", command=[sys.executable, "-I", "-c",
                                                                 "import sys; print(sys.argv[-1], end='')"])
        argv = fp.live_command(provider, text)
        self.assertEqual(argv[-1], text)
        done = subprocess.run(argv, capture_output=True, text=True, check=True, cwd=tempfile.gettempdir())
        self.assertEqual(done.stdout, text)


class ProgramIndexTest(unittest.TestCase):
    def test_rows_once_it_ends(self):
        timers, got = FakeTimers(), []
        processes = []
        provider = fp.Provider("p.json", "Projects", "index", program=["projects"])
        fp.ProgramIndex(provider, lambda p, rows: got.append([r.name for r in rows]),
                        lambda *args: processes.append(FakeProcess(*args)) or processes[-1],
                        timers.add, timers.remove, "/home/u")
        self.assertEqual(processes[0].argv[-1], "projects")
        with mock.patch.object(fp, "installed", return_value=True):
            processes[0].on_data(b'{"name": "FlickOS", "command": ["code", "FlickOS"]}\n')
            processes[0].on_end()
        self.assertEqual(got, [["FlickOS"]])
        self.assertEqual([row.name for row in provider.rows], ["FlickOS"])
        self.assertEqual(timers.timers, {})


def gio_or_none():
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        return None
    return GLib, Gio


@unittest.skipIf(gio_or_none() is None, "needs PyGObject")
class LiveSearchGioTest(unittest.TestCase):
    """A real process: a stand-in provider that sleeps never delays a
    keystroke, and one that prints arrives in the main loop."""

    def run_loop(self, until, seconds=3):
        GLib = self.GLib
        loop = GLib.MainLoop()
        GLib.timeout_add(seconds * 1000, loop.quit)

        def check():
            if until():
                loop.quit()
                return False
            return True
        GLib.timeout_add(10, check)
        loop.run()

    def setUp(self):
        self.GLib, self.Gio = gio_or_none()
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)

    def search(self, command, output="rows"):
        got = []
        provider = fp.Provider("stand-in.json", "Stand-in", "live", limit=5, command=command, output=output)
        live = fp.LiveSearch(provider, lambda rows, done: got.append(([r.name for r in rows], done)),
                             fp.gio_spawner(self.GLib, self.Gio), self.GLib.timeout_add, self.GLib.source_remove,
                             self.home)
        return live, got

    def test_a_sleeping_provider_never_delays_a_key(self):
        live, got = self.search(["sh", "-c", "sleep 5; echo late"])
        started = time.monotonic()
        live.typed("abc")
        self.assertLess(time.monotonic() - started, 0.016)
        self.run_loop(lambda: live.process is not None)
        self.assertIsNotNone(live.process, "started after the pause")
        process = live.process.process
        started = time.monotonic()
        live.typed("abcd")                  # the next key: the sleeper is killed
        self.assertLess(time.monotonic() - started, 0.016)
        self.run_loop(lambda: process.get_if_exited() or process.get_if_signaled(), 2)
        self.assertTrue(process.get_if_signaled(), "killed")
        live.stop()
        self.assertEqual(got, [])

    def test_paths_arrive(self):
        open(os.path.join(self.home, "budget 2026.ods"), "w").close()
        live, got = self.search(["sh", "-c", 'printf "%s/budget 2026.ods\\0" "$PWD"; true'], output="paths")
        live.typed("budget")
        self.run_loop(lambda: got and got[-1][1])
        self.assertEqual(got, [(["budget 2026.ods"], False), ([], True)])


class TerminalTest(unittest.TestCase):
    def run_script(self, text):
        """The script xdg-terminal-exec would run, here in sh with no rc files."""
        argv = fp.terminal_command(text, "/bin/sh", "Press Enter to close this window.")
        self.assertEqual(argv[:4], ["xdg-terminal-exec", "sh", "-c", fp.TERMINAL_SCRIPT])
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home)
        return subprocess.run(argv[1:], input="\n", capture_output=True, text=True, timeout=10,
                              env={"PATH": "/usr/bin:/bin", "HOME": home}, cwd=home)

    def test_pipes_and_quotes_reach_the_shell_unchanged(self):
        done = self.run_script("""printf '%s\\n' "a b" 'c|d' | wc -l""")
        self.assertEqual(done.stdout.split("\n")[0].strip(), "2")
        self.assertIn("Press Enter to close this window.", done.stdout)
        self.assertEqual(done.returncode, 0)

    def test_a_failure_shows_its_status(self):
        self.assertIn("[3]", self.run_script("exit 3").stdout)

    def test_the_users_shell(self):
        self.assertEqual(fp.user_shell({"SHELL": "/bin/sh"}), "/bin/sh")
        self.assertTrue(os.path.isabs(fp.user_shell({"SHELL": "zsh"})), "not a path: the account's")


@unittest.skipUnless(shutil.which("xgettext") and shutil.which("msgfmt"), "gettext is not installed")
class TranslationTest(unittest.TestCase):
    def test_template_is_current(self):
        """po/flickos-menu.pot has every marked string and no others. Same
        xgettext options as tools/update-po.sh, which fixes this."""
        with tempfile.TemporaryDirectory() as folder:
            new = os.path.join(folder, "new.pot")
            subprocess.run(["xgettext", "--language=Python", "--from-code=UTF-8", "--keyword=N_",
                            "--output=" + new, *po_list("POTFILES")], cwd=PACKAGE, check=True)
            # The providers' text (tasks.json), as update-po.sh adds it.
            extra = os.path.join(folder, "extra.pot")
            with open(extra, "w", encoding="utf-8") as f:
                subprocess.run([os.path.join(PO, "extract")], stdout=f, check=True)
            subprocess.run(["msgcat", "--use-first", "--output-file=" + new, new, extra], check=True)
            shipped = os.path.join(PO, "flickos-menu.pot")
            for definitions, reference in ((shipped, new), (new, shipped)):
                result = subprocess.run(["msgcmp", "--use-untranslated", definitions, reference],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0,
                                 f"run tools/update-po.sh flickos-menu\n{result.stderr}")

    def test_every_language_has_a_file_that_compiles(self):
        languages = po_list("LINGUAS")
        files = sorted(name[:-3] for name in os.listdir(PO) if name.endswith(".po"))
        self.assertEqual(sorted(languages), files, "po/LINGUAS and the po/*.po files differ")
        for lang in languages:
            with self.subTest(lang=lang):
                subprocess.run(["msgfmt", "--check", "--output-file=/dev/null",
                                os.path.join(PO, lang + ".po")], check=True)

    def test_translation_is_shown_and_keys_stay(self):
        """A translation under the prefix reaches the menu and the two files it
        loads; section keys and the output of `list` stay English."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        po = os.path.join(root, "xx.po")
        with open(po, "w", encoding="utf-8") as f:
            f.write('msgid ""\nmsgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n'
                    'msgid "Start Menu"\nmsgstr "Stärt"\n\n'
                    'msgid "Off"\nmsgstr "Öff"\n\n'
                    'msgid "Not connected"\nmsgstr "Nöt"\n')
        share = os.path.join(root, "usr/share")
        mo = os.path.join(share, "locale/xx/LC_MESSAGES/flickos-menu.mo")
        os.makedirs(os.path.dirname(mo))
        subprocess.run(["msgfmt", "--output-file=" + mo, po], check=True)
        # The prefix's quick.py and phone.py are the package's own.
        os.makedirs(os.path.join(share, "flickos"))
        os.symlink(os.path.join(PACKAGE, "usr/share/flickos/menu"), os.path.join(share, "flickos/menu"))

        with mock.patch.dict(os.environ, {"FLICKOS_MENU_PREFIX": root, "LANGUAGE": "xx"}):
            loader = importlib.machinery.SourceFileLoader("flickos_menu_xx", SCRIPT)
            menu = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
            loader.exec_module(menu)
            self.assertIsNone(menu._translation, "nothing loaded before the first text")
            self.assertEqual(menu._("Start Menu"), "Stärt")
            self.assertEqual(menu.section_for(["Utility"]), "Accessories", "the key stays English")
            quick, phone = menu.load_quick(), menu.load_phone()
            self.assertEqual(quick.parse_wifi("disabled", ""), (False, "Öff"))
            self.assertEqual(phone.phone_line({"name": "Pixel", "connected": False}), ("Pixel", "Nöt"))
        self.assertEqual(fq.parse_wifi("disabled", ""), (False, "Off"), "loaded on its own: English")

    def test_no_function_hides_the_translation(self):
        """A function that binds _ (`for _ in`, `_ok, _ = …`) and calls _()
        would fail only when that window is drawn."""
        import ast
        scopes = (ast.FunctionDef, ast.Lambda, ast.ClassDef, ast.ListComp, ast.SetComp, ast.DictComp,
                  ast.GeneratorExp)
        for path in po_list("POTFILES"):
            with open(os.path.join(PACKAGE, path), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for function in ast.walk(tree):
                if not isinstance(function, (ast.FunctionDef, ast.Lambda)):
                    continue
                arguments = function.args
                binds = "_" in [a.arg for a in arguments.posonlyargs + arguments.args + arguments.kwonlyargs
                                + [arguments.vararg, arguments.kwarg] if a]
                calls = False
                nodes = list(ast.iter_child_nodes(function))
                while nodes:
                    node = nodes.pop()
                    if isinstance(node, scopes):
                        continue
                    binds = binds or (isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, ast.Store))
                    calls = calls or (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_")
                    nodes.extend(ast.iter_child_nodes(node))
                self.assertFalse(binds and calls, f"{path}:{function.lineno} binds _ and calls _()")

    def test_a_click_imports_no_gettext(self):
        """The fast path (client) shows no text, so it never loads the translation."""
        code = ("import importlib.machinery, importlib.util, sys; sys.dont_write_bytecode = True; "
                f"l = importlib.machinery.SourceFileLoader('m', {SCRIPT!r}); "
                "m = importlib.util.module_from_spec(importlib.util.spec_from_loader('m', l)); l.exec_module(m); "
                "print('gettext' in sys.modules)")
        result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
