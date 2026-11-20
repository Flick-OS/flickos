"""Translations of usr/bin/flickos-control (docs/12-translating.md).
Run: python3 -m unittest discover -s tests"""

import ast
import datetime
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
SCRIPT = os.path.join(PACKAGE, "usr/bin/flickos-control")
PO = os.path.join(PACKAGE, "po")

sys.dont_write_bytecode = True

# A made-up language xx: a page, its group, a History label and its words, a
# plural, the search words of one page and an About label.
XX_PO = r'''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

msgid "Users"
msgstr "Üsers"

msgid "Accounts and security"
msgstr "Äccounts"

msgid "Tap to click"
msgstr "Täp"

msgid "{setting}: {value}"
msgstr "{setting} = {value}"

msgid "on"
msgstr "än"

msgid "Was {value}"
msgstr "Wär {value}"

msgid "{count} minute"
msgid_plural "{count} minutes"
msgstr[0] "{count} Minüte"
msgstr[1] "{count} Minüten"

msgid "firewall ufw security ports incoming local network development server dev devices reach open port"
msgstr "brandmauer"

msgid "Computer"
msgstr "Cömputer"
'''


def load(name, environment):
    """A fresh copy of the program, loaded with environment set."""
    with mock.patch.dict(os.environ, environment):
        loader = importlib.machinery.SourceFileLoader(name, SCRIPT)
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
    return module


def po_list(name):
    """The file names in po/POTFILES or po/LINGUAS, comments left out."""
    with open(os.path.join(PO, name), encoding="utf-8") as f:
        return [line.split("#", 1)[0].strip() for line in f if line.split("#", 1)[0].strip()]


@unittest.skipUnless(shutil.which("xgettext") and shutil.which("msgfmt"), "gettext is not installed")
class TranslationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="flickos-control-test-po-")
        po = os.path.join(cls.root, "xx.po")
        with open(po, "w", encoding="utf-8") as f:
            f.write(XX_PO)
        mo = os.path.join(cls.root, "usr/share/locale/xx/LC_MESSAGES/flickos-control.mo")
        os.makedirs(os.path.dirname(mo))
        subprocess.run(["msgfmt", "--check", "--output-file=" + mo, po], check=True)
        cls.fc = load("flickos_control_xx", {"FLICKOS_CONTROL_PREFIX": cls.root, "LANGUAGE": "xx"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, True)

    def test_template_is_current(self):
        """po/flickos-control.pot has every marked string and no others. Same
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
            shipped = os.path.join(PO, "flickos-control.pot")
            for definitions, reference in ((shipped, new), (new, shipped)):
                result = subprocess.run(["msgcmp", "--use-untranslated", definitions, reference],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0,
                                 f"run tools/update-po.sh flickos-control\n{result.stderr}")

    def test_every_language_has_a_file_that_compiles(self):
        languages = po_list("LINGUAS")
        files = sorted(name[:-3] for name in os.listdir(PO) if name.endswith(".po"))
        self.assertEqual(sorted(languages), files, "po/LINGUAS and the po/*.po files differ")
        for lang in languages:
            with self.subTest(lang=lang):
                subprocess.run(["msgfmt", "--check", "--output-file=/dev/null",
                                os.path.join(PO, lang + ".po")], check=True)

    def test_tables_are_translated_and_ids_stay(self):
        """The tables are translated when the program starts; their ids and
        the values the commands take stay."""
        fc = self.fc
        users = next(page for page in fc.PAGES if page.id == "users")
        self.assertEqual((users.name, users.group), ("Üsers", "Äccounts"))
        self.assertEqual(next(page for page in fc.PAGES if page.id == "login").name, "Login Screen",
                         "untranslated text stays English")
        self.assertEqual(fc.HISTORY_LABELS[(fc.HISTORY_OWNER, "touchpad.tap")], "Täp")
        self.assertEqual(fc.normalize(fc.SETTINGS["touchpad.tap"], "on"), "yes")
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fc.main(["list"]), 0)
        self.assertIn("users\tÜsers\n", out.getvalue())

    def test_history_words(self):
        fc = self.fc
        change = fc.Change("1", datetime.datetime.now().astimezone(), fc.HISTORY_OWNER, "touchpad.tap", "no", "yes")
        self.assertEqual(fc.describe(change, {}), ("Täp = än", "Wär off"))
        self.assertEqual(fc.duration_name(60), "1 Minüte")
        self.assertEqual(fc.duration_name(300), "5 Minüten")

    def test_search_finds_both_languages(self):
        fc = self.fc
        words = fc.search_words("firewall")
        self.assertIn("brandmauer", words)
        self.assertIn("ufw", words, "the English words are searched as well")
        self.assertEqual(fc.search_words("privacy"), fc.SEARCH_KEYWORDS["privacy"], "not translated: English once")
        self.assertEqual(fc.search_words("nothing"), "", "no words: not the translation's header")

    def test_bug_reports_stay_english(self):
        """About's labels are translated on the page only: Copy System Info and
        `about` go into bug reports."""
        fc = self.fc
        self.assertEqual(fc._("Computer"), "Cömputer")
        with mock.patch.object(fc, "command_output", return_value=""):
            labels = [label for label, _value in fc.system_info()]
        self.assertIn("Computer", labels)
        self.assertNotIn("Cömputer", labels)

    def test_english_without_a_translation(self):
        fc = load("flickos_control_none", {"FLICKOS_CONTROL_PREFIX": self.root, "LANGUAGE": "yy"})
        self.assertEqual(fc.TITLE, "Settings")
        self.assertEqual(fc.duration_name(300), "5 minutes")

    def test_a_broken_translation_is_english(self):
        """`prepare` runs at login before labwc: a broken .mo must not stop it."""
        mo = os.path.join(self.root, "usr/share/locale/zz/LC_MESSAGES/flickos-control.mo")
        os.makedirs(os.path.dirname(mo))
        with open(mo, "wb") as f:
            f.write(b"\xde\x12\x04\x95 not a catalog")
        fc = load("flickos_control_broken", {"FLICKOS_CONTROL_PREFIX": self.root, "LANGUAGE": "zz"})
        self.assertEqual(fc.TITLE, "Settings")

    def test_nothing_hides_the_translation(self):
        """Nothing binds _ (`for _ in`, `prefix, _, rest = …`, `lambda _:`): in a
        function that also calls _(), that fails only when its page is drawn."""
        with open(SCRIPT, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        # The program's own `_ = _translation.gettext`.
        own = {target for node in tree.body if isinstance(node, ast.Assign) for target in node.targets}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, ast.Store) and node not in own:
                self.fail(f"line {node.lineno} binds _: name it _skip")
            if isinstance(node, ast.arg) and node.arg == "_":
                self.fail(f"line {node.lineno} has an argument _: name it _skip")


@unittest.skipUnless(os.path.exists("/usr/share/locale/de/LC_MESSAGES/iso_639-3.mo"),
                     "iso-codes' German translation is not installed")
class OtherProjectsTest(unittest.TestCase):
    """Names of languages and countries come from iso-codes' translations."""

    def test_locale_name_in_the_language(self):
        fc = load("flickos_control_iso", {"FLICKOS_CONTROL_PREFIX": "/nonexistent"})
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "de_DE"), "w", encoding="utf-8") as f:
                f.write('LC_IDENTIFICATION\nlanguage   "German"\nterritory  "Germany"\nEND LC_IDENTIFICATION\n')
            with mock.patch.dict(os.environ, {"LANGUAGE": "de"}):
                self.assertEqual(fc.locale_name("de_DE.UTF-8", folder), "Deutsch (Deutschland)")


if __name__ == "__main__":
    unittest.main()
