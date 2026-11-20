"""Tests for usr/bin/flickos-welcome. Run: python3 -m unittest discover -s tests"""

import importlib.machinery
import io
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_welcome", os.path.join(PACKAGE, "usr/bin/flickos-welcome"))
fw = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fw)

SHIPPED_CONF = os.path.join(PACKAGE, "etc/xdg/flickos/welcome.conf")
SHIPPED_MARKER = os.path.join(PACKAGE, "etc/skel/.config/flickos/welcome")


def everything(name):
    """shutil.which that finds every program."""
    return "/usr/bin/" + name


def nothing(_name):
    return None


def setUpModule():
    # Not the build host's /etc/xdg/flickos/welcome.conf (Enabled=no there
    # would change what first-run does); tests pass their own path.
    for name in ("SYSTEM_CONF", "SITE_CONF"):
        patcher = mock.patch.object(fw, name, "/nonexistent/welcome.conf")
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


class ConfTest(unittest.TestCase):
    def test_shipped_conf_is_read(self):
        enabled, links = fw.read_conf(SHIPPED_CONF)
        self.assertTrue(enabled)
        self.assertEqual(links["project"], "https://github.com/Flick-OS/flickos")

    def test_shipped_addresses_are_real(self):
        """A card only ever opens an address from the conffile, and a placeholder
        or a typo would send people somewhere FlickOS doesn't control."""
        _enabled, links = fw.read_conf(SHIPPED_CONF)
        for key, url in links.items():
            if url:
                self.assertRegex(url, r"^https://[a-z0-9.-]+\.[a-z]{2,}(/|$)", key)

    def test_donate_address_matches_the_installer(self):
        """welcome.conf and the installer's branding.desc must not drift apart."""
        branding = os.path.join(os.path.dirname(PACKAGE),
                                "flickos-installer/etc/calamares/branding/flickos/branding.desc")
        if not os.path.exists(branding):
            self.skipTest("flickos-installer is not next to this package")
        with open(branding, encoding="utf-8") as f:
            match = re.search(r'^\s*donateUrl:\s*"([^"]*)"', f.read(), re.M)
        self.assertIsNotNone(match, "branding.desc no longer has donateUrl")
        _enabled, links = fw.read_conf(SHIPPED_CONF)
        self.assertEqual(links["donate"], match.group(1))

    def test_code_default_has_no_payment_address(self):
        """With no conffile at all, no donate card: a payment address belongs in
        the conffile a machine can change, never baked into the program."""
        self.assertEqual(fw.DEFAULT_LINKS["donate"], "")

    def test_missing_file_is_the_default(self):
        enabled, links = fw.read_conf(os.path.join(tempfile.gettempdir(), "no-such-welcome.conf"))
        self.assertTrue(enabled)
        self.assertEqual(links, fw.DEFAULT_LINKS)

    def test_enabled_no(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("[Welcome]\nEnabled=no\n")
        self.addCleanup(os.unlink, f.name)
        enabled, _links = fw.read_conf(f.name)
        self.assertFalse(enabled)

    def test_broken_file_is_the_default(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("this is not ini\n[[[\n")
        self.addCleanup(os.unlink, f.name)
        with open(os.devnull, "w", encoding="utf-8") as quiet, \
             mock.patch.object(fw.sys, "stderr", new=quiet):
            enabled, links = fw.read_conf(f.name)
        self.assertTrue(enabled)
        self.assertEqual(links, fw.DEFAULT_LINKS)

    def write_conf(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write(text)
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_site_file_goes_over_the_system_one_key_by_key(self):
        system = self.write_conf("[Welcome]\nEnabled=yes\n[Links]\ndonate=https://example.org/a\ndocs=https://example.org/h\n")
        site = self.write_conf("[Welcome]\nEnabled=no\n[Links]\ndonate=\n")
        with mock.patch.object(fw, "SYSTEM_CONF", system), mock.patch.object(fw, "SITE_CONF", site):
            enabled, links = fw.read_conf()
        self.assertFalse(enabled)
        self.assertEqual(links["donate"], "")
        self.assertEqual(links["docs"], "https://example.org/h")

    def test_broken_site_file_leaves_the_system_one(self):
        system = self.write_conf("[Welcome]\nEnabled=no\n")
        site = self.write_conf("this is not ini\n[[[\n")
        with mock.patch.object(fw, "SYSTEM_CONF", system), mock.patch.object(fw, "SITE_CONF", site), \
             mock.patch.object(fw, "warn") as warn:
            enabled, _links = fw.read_conf()
        self.assertFalse(enabled)
        warn.assert_called()


class CardsTest(unittest.TestCase):
    def test_every_card_id_is_unique(self):
        ids = [card[0] for card in fw.CARDS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_shown_when_everything_is_installed(self):
        links = dict(fw.DEFAULT_LINKS, donate="https://example.invalid/give")
        shown = [card[0] for card in fw.cards(links, which=everything, found=set(fw.WHEN))]
        self.assertEqual(shown, [card[0] for card in fw.CARDS])

    def test_when_cards_wait_for_their_check(self):
        shown = [card[0] for card in fw.cards(fw.DEFAULT_LINKS, which=everything)]
        self.assertNotIn("windows", shown)
        shown = [card[0] for card in fw.cards(fw.DEFAULT_LINKS, which=everything, found={"windows"})]
        self.assertEqual(shown[0], "windows")

    def test_check_needs_a_non_empty_list(self):
        def answer(code, out):
            return lambda *_a, **_k: subprocess.CompletedProcess([], code, out, "")
        self.assertTrue(fw.check("windows", run=answer(0, '[{"device": "/dev/sda3"}]')))
        self.assertFalse(fw.check("windows", run=answer(0, "[]")))
        self.assertFalse(fw.check("windows", run=answer(1, '[{"device": "/dev/sda3"}]')))
        self.assertFalse(fw.check("windows", run=answer(0, "not json")))

        def missing(*_a, **_k):
            raise FileNotFoundError("flickos-switch")
        self.assertFalse(fw.check("windows", run=missing))

    def test_pending_only_with_the_program(self):
        self.assertEqual(fw.pending(which=everything), ["windows"])
        self.assertEqual(fw.pending(which=nothing), [])

    def test_card_without_its_program_is_left_out(self):
        def only_xdg(name):
            return "/usr/bin/xdg-open" if name == "xdg-open" else None
        shown = [card[0] for card in fw.cards(fw.DEFAULT_LINKS, which=only_xdg)]
        self.assertNotIn("layout", shown)
        self.assertNotIn("settings", shown)
        self.assertIn("docs", shown)

    def test_empty_link_is_left_out(self):
        shown = [card[0] for card in fw.cards(fw.DEFAULT_LINKS, which=everything)]
        self.assertNotIn("donate", shown)
        self.assertIn("support", shown)

    def test_link_cards_need_xdg_open(self):
        def no_xdg(name):
            return None if name == "xdg-open" else "/usr/bin/" + name
        shown = [card[0] for card in fw.cards(fw.DEFAULT_LINKS, which=no_xdg)]
        self.assertNotIn("docs", shown)
        self.assertIn("layout", shown)

    def test_a_link_card_opens_the_address_from_the_conf(self):
        links = dict(fw.DEFAULT_LINKS, donate="https://example.invalid/give")
        actions = {card[0]: card[4] for card in fw.cards(links, which=everything)}
        self.assertEqual(actions["donate"], ["xdg-open", "https://example.invalid/give"])


class FirstRunTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.home})
        patch.start()
        self.addCleanup(patch.stop)
        os.makedirs(os.path.join(self.home, "flickos"), exist_ok=True)

    def markers(self, *names):
        for name in names:
            with open(fw.marker_path(name), "w", encoding="utf-8") as f:
                f.write("# marker\n")

    def test_nothing_without_a_marker(self):
        with mock.patch.object(fw, "cmd_show") as show:
            self.assertEqual(fw.cmd_first_run(None), 0)
        show.assert_not_called()

    def test_opens_at_every_login_and_consumes_the_chooser_marker(self):
        self.markers(fw.MARKER, fw.LAYOUT_MARKER)
        with mock.patch.object(fw, "live_system", return_value=False), \
             mock.patch.object(fw, "cmd_show", return_value=0) as show:
            self.assertEqual(fw.cmd_first_run(None), 0)
            self.assertEqual(fw.cmd_first_run(None), 0)
        self.assertEqual(show.call_count, 2, "shown on startup is the default")
        self.assertTrue(os.path.exists(fw.marker_path(fw.MARKER)))
        self.assertFalse(os.path.exists(fw.marker_path(fw.LAYOUT_MARKER)),
                         "the chooser this window replaces must not open either")

    def test_do_not_show_on_startup(self):
        self.markers(fw.MARKER)
        self.assertEqual(fw.main(["startup", "set", "off"]), 0)
        with mock.patch.object(fw, "live_system", return_value=False), \
             mock.patch.object(fw, "cmd_show") as show:
            self.assertEqual(fw.cmd_first_run(None), 0)
        show.assert_not_called()

    def test_startup_current_and_set(self):
        def current():
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(fw.main(["startup", "current"]), 0)
            return out.getvalue().strip()

        self.assertEqual(current(), "off", "an account without the marker")
        self.assertEqual(fw.main(["startup", "set", "on"]), 0)
        self.assertEqual(current(), "on")
        self.assertEqual(fw.main(["startup", "set", "off"]), 0)
        self.assertEqual(current(), "off")
        self.assertEqual(fw.main(["startup", "set", "default"]), 0)
        self.assertEqual(current(), fw.STARTUP_DEFAULT)
        self.assertEqual(fw.main(["startup", "set", "off"]), 0)
        self.assertEqual(fw.main(["startup", "set", "off"]), 0, "already off is fine")

    def test_set_on_creates_the_folder(self):
        shutil.rmtree(os.path.join(self.home, "flickos"))
        self.assertEqual(fw.main(["startup", "set", "on"]), 0)
        self.assertTrue(fw.startup_enabled())
        self.assertEqual(os.listdir(os.path.join(self.home, "flickos")), [fw.MARKER],
                         "no temporary file left behind")

    def test_startup_set_rejects_other_values(self):
        with open(os.devnull, "w", encoding="utf-8") as quiet, \
             mock.patch.object(fw.sys, "stderr", new=quiet), \
             self.assertRaises(SystemExit) as exit_:
            fw.main(["startup", "set", "maybe"])
        self.assertEqual(exit_.exception.code, 2)

    def test_never_in_the_live_session(self):
        self.markers(fw.MARKER, fw.LAYOUT_MARKER)
        with mock.patch.object(fw, "live_system", return_value=True), \
             mock.patch.object(fw, "cmd_show") as show:
            self.assertEqual(fw.cmd_first_run(None), 0)
        show.assert_not_called()
        self.assertFalse(os.path.exists(fw.marker_path(fw.MARKER)))
        self.assertFalse(os.path.exists(fw.marker_path(fw.LAYOUT_MARKER)))

    def test_not_when_turned_off(self):
        self.markers(fw.MARKER)
        with mock.patch.object(fw, "read_conf", return_value=(False, fw.DEFAULT_LINKS)), \
             mock.patch.object(fw, "live_system", return_value=False), \
             mock.patch.object(fw, "cmd_show") as show:
            self.assertEqual(fw.cmd_first_run(None), 0)
        show.assert_not_called()
        self.assertFalse(os.path.exists(fw.marker_path(fw.MARKER)))


class SingleInstanceTest(unittest.TestCase):
    def test_second_window_is_refused_while_one_is_open(self):
        with tempfile.TemporaryDirectory() as runtime, \
                mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}):
            with fw.single_instance() as first:
                self.assertTrue(first)
                with fw.single_instance() as second:
                    self.assertFalse(second)
            with fw.single_instance() as again:
                self.assertTrue(again, "closing the window frees the lock")

    def test_show_opens_no_window_while_one_is_open(self):
        with tempfile.TemporaryDirectory() as runtime, \
                mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}), \
                mock.patch.object(fw, "cards", return_value=[("docs", "Docs", "help-browser", "", ["true"])]), \
                mock.patch.object(fw, "window", return_value=0) as window:
            with fw.single_instance():
                self.assertEqual(fw.cmd_show(None), 0)
            window.assert_not_called()
            self.assertEqual(fw.cmd_show(None), 0)
            window.assert_called_once()


PO = os.path.join(PACKAGE, "po")


def po_list(name):
    """The file names in po/POTFILES or po/LINGUAS, comments left out."""
    with open(os.path.join(PO, name), encoding="utf-8") as f:
        return [line.split("#", 1)[0].strip() for line in f if line.split("#", 1)[0].strip()]


@unittest.skipUnless(shutil.which("xgettext") and shutil.which("msgfmt"), "gettext is not installed")
class TranslationTest(unittest.TestCase):
    def test_template_is_current(self):
        """po/flickos-welcome.pot has every marked string and no others. Same
        xgettext options as tools/update-po.sh, which fixes this."""
        files = po_list("POTFILES")
        with tempfile.TemporaryDirectory() as folder:
            new = os.path.join(folder, "new.pot")
            python = [f for f in files if not f.endswith(".desktop")]
            desktop = [f for f in files if f.endswith(".desktop")]
            subprocess.run(["xgettext", "--language=Python", "--from-code=UTF-8", "--keyword=N_",
                            "--output=" + new, *python], cwd=PACKAGE, check=True)
            subprocess.run(["xgettext", "--language=Desktop", "--join-existing",
                            "--output=" + new, *desktop], cwd=PACKAGE, check=True)
            shipped = os.path.join(PO, "flickos-welcome.pot")
            for definitions, reference in ((shipped, new), (new, shipped)):
                result = subprocess.run(["msgcmp", "--use-untranslated", definitions, reference],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0,
                                 f"run tools/update-po.sh flickos-welcome\n{result.stderr}")

    def test_every_language_has_a_file_that_compiles(self):
        languages = po_list("LINGUAS")
        files = sorted(name[:-3] for name in os.listdir(PO) if name.endswith(".po"))
        self.assertEqual(sorted(languages), files, "po/LINGUAS and the po/*.po files differ")
        for lang in languages:
            with self.subTest(lang=lang):
                subprocess.run(["msgfmt", "--check", "--output-file=/dev/null",
                                os.path.join(PO, lang + ".po")], check=True)

    def test_translation_is_shown_and_ids_stay(self):
        """A translation installed under the prefix replaces the window's text;
        what other programs read (card ids, startup on/off) stays."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        po = os.path.join(root, "xx.po")
        with open(po, "w", encoding="utf-8") as f:
            f.write('msgid ""\nmsgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n'
                    'msgid "Welcome to FlickOS"\nmsgstr "Wëlcome"\n\n'
                    'msgid "Connect to Wi-Fi"\nmsgstr "Wï-Fi"\n')
        mo = os.path.join(root, "usr/share/locale/xx/LC_MESSAGES/flickos-welcome.mo")
        os.makedirs(os.path.dirname(mo))
        subprocess.run(["msgfmt", "--output-file=" + mo, po], check=True)

        environment = {"FLICKOS_WELCOME_PREFIX": root, "LANGUAGE": "xx", "XDG_CONFIG_HOME": root}
        with mock.patch.dict(os.environ, environment):
            loader = importlib.machinery.SourceFileLoader(
                "flickos_welcome_xx", os.path.join(PACKAGE, "usr/bin/flickos-welcome"))
            translated = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
            loader.exec_module(translated)
            self.assertEqual(translated._(translated.TITLE), "Wëlcome")
            shown = {card[0]: card[1] for card in translated.cards(translated.DEFAULT_LINKS, which=everything)}
            self.assertEqual(shown["network"], "Wï-Fi")
            self.assertEqual(shown["docs"], "Read the documentation", "untranslated text stays English")
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(translated.main(["startup", "current"]), 0)
            self.assertEqual(out.getvalue(), "off\n")


class ShippedFilesTest(unittest.TestCase):
    def test_marker_is_shipped(self):
        self.assertTrue(os.path.exists(SHIPPED_MARKER))

    def test_marker_name_matches_the_program(self):
        self.assertEqual(os.path.basename(SHIPPED_MARKER), fw.MARKER)

    def test_layout_marker_name_matches_flickos_layouts(self):
        """flickos-layouts ships this marker; the names must not drift apart."""
        other = os.path.join(os.path.dirname(PACKAGE),
                             "flickos-layouts/etc/skel/.config/flickos", fw.LAYOUT_MARKER)
        if not os.path.isdir(os.path.dirname(other)):
            self.skipTest("flickos-layouts is not next to this package")
        self.assertTrue(os.path.exists(other), f"flickos-layouts no longer ships {fw.LAYOUT_MARKER}")


if __name__ == "__main__":
    unittest.main()
