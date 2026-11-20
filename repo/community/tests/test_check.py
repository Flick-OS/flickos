"""Tests for repo/community/check.py and build.py: one test package per rule
(built with dpkg-deb in a temp folder), and app files, pinned tags and diffs
in temp git repositories. apt's origins are faked: nothing reads the
computer's sources. Run: python3 -m unittest discover -s repo/community/tests"""
import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import build    # noqa: E402
import check    # noqa: E402

# Package -> {(origin, label)} as apt would report it.
ORIGINS = {
    "python3": {("Debian", "Debian")},
    "dpkg": {("Debian", "Debian")},
    "ufw": {("Debian", "Debian")},
    "flickos-settings": {("FlickOS", "FlickOS")},
    "sfwbar": {("FlickOS", "FlickOS")},
    "hello": {("Debian", "Debian")},
    "code": {("code stable", "code stable")},
    "good-app": {("FlickOS", "FlickOS Community")},     # already published: an update
    "flickos-layouts": {("FlickOS", "FlickOS")},
    "greybird-gtk-theme": {("Debian", "Debian")},
}

METAINFO = """\
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>io.example.TestApp</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>Test App</name>
  <summary>A test app for the community checks</summary>
  <developer id="io.example"><name>Example</name></developer>
  <description><p>It says hello to whoever starts it, and nothing else.</p></description>
  <launchable type="desktop-id">{name}.desktop</launchable>
  <url type="homepage">https://example.org/</url>
  <content_rating type="oars-1.1"/>
  <releases><release version="1.0" date="2026-10-08"/></releases>
</component>
"""


def make_deb(folder, name, change=None, control=""):
    """A package with a program, desktop file, metainfo and doc; change(root)
    breaks something first. Returns the .deb's path."""
    root = os.path.join(folder, "build", name)
    for sub in ("DEBIAN", "usr/bin", "usr/share/applications", "usr/share/metainfo", f"usr/share/doc/{name}"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    with open(os.path.join(root, "usr/bin", name), "w") as f:
        f.write("#!/bin/sh\necho hello\n")
    os.chmod(os.path.join(root, "usr/bin", name), 0o755)
    with open(os.path.join(root, "usr/share/applications", f"{name}.desktop"), "w") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName=Test App\nExec={name}\nIcon=utilities-terminal\nCategories=Utility;\n")
    with open(os.path.join(root, "usr/share/metainfo/io.example.TestApp.metainfo.xml"), "w") as f:
        f.write(METAINFO.format(name=name))
    with open(os.path.join(root, f"usr/share/doc/{name}/copyright"), "w") as f:
        f.write("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                "Files: *\nCopyright: 2026 Example\nLicense: GPL-3+\n")
    with open(os.path.join(root, "DEBIAN/control"), "w") as f:
        f.write(textwrap.dedent(f"""\
            Package: {name}
            Version: 1.0
            Architecture: all
            Maintainer: Example <dev@example.org>
            Depends: python3
            """) + control + "Section: utils\nPriority: optional\nDescription: test app\n It says hello.\n")
    if change:
        change(root)
    deb = os.path.join(folder, f"{name}.deb")
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", root, deb], check=True, capture_output=True)
    return deb


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode is not None:
        os.chmod(path, mode)


def symlink(target, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.symlink(target, path)


def addon(name, **files):
    """A change that gives the package an add-on: files maps a file name of
    its folder (labwc_xml for labwc.xml, …) to the text."""
    def change(root):
        for key, text in files.items():
            write(os.path.join(root, "usr/share/flickos/addons", name, key.replace("_", ".")), text)
    return change


def bar(**settings):
    """A waybar.jsonc with one panel button."""
    return "{\n  // a comment\n  \"custom/button\": " + json.dumps(settings) + "\n}\n"


def keys(command, extra=""):
    """A labwc.xml with one keybind that runs command."""
    return (f'<labwc_config><keyboard><keybind key="W-F9" description="Test">'
            f'<action name="Execute" command="{command}"/>{extra}</keybind></keyboard></labwc_config>\n')


def rule(action):
    """A labwc.xml with a window rule that has an action."""
    return f'<labwc_config><windowRules><windowRule identifier="x">{action}</windowRule></windowRules></labwc_config>\n'


def setuid_helper(root):
    write(os.path.join(root, "usr/lib/bad-setuid/helper"), "#!/bin/sh\n", 0o755)
    os.chmod(os.path.join(root, "usr/lib/bad-setuid/helper"), 0o4755)


# name -> (change, extra control lines, the rule its problem names)
BAD = {
    "bad-postinst": (lambda r: write(f"{r}/DEBIAN/postinst", "#!/bin/sh\nset -e\n", 0o755), "", "scripts:"),
    "bad-triggers": (lambda r: write(f"{r}/DEBIAN/triggers", "activate-noawait ldconfig\n"), "", "scripts:"),
    "bad-sudoers": (lambda r: write(f"{r}/etc/sudoers.d/bad-sudoers", "ALL ALL=(ALL) NOPASSWD: ALL\n", 0o440),
                    "", "files:"),
    "bad-unit": (lambda r: write(f"{r}/usr/lib/systemd/system/bad-unit.service", "[Service]\n"), "", "files:"),
    "bad-autostart": (lambda r: write(f"{r}/etc/xdg/autostart/bad-autostart.desktop", "[Desktop Entry]\n"),
                      "", "files:"),
    "bad-setuid": (setuid_helper, "", "files:"),
    "bad-dep": (None, "Recommends: code\n", "dependencies:"),
    "bad-nodep": (None, "Suggests: no-such-package\n", "dependencies:"),
    "bad-conflicts": (None, "Conflicts: ufw\n", "fields:"),
    "bad-replaces": (None, "Replaces: flickos-settings\n", "fields:"),
    "bad-predepends": (None, "Pre-Depends: dpkg\n", "fields:"),
    "bad-link": (lambda r: symlink("/etc", f"{r}/usr/share/bad-link/etc"), "", "files:"),
    "bad-nometainfo": (lambda r: shutil.rmtree(f"{r}/usr/share/metainfo"), "", "metainfo:"),
    "bad-metainfo": (lambda r: write(f"{r}/usr/share/metainfo/io.example.TestApp.metainfo.xml",
                                     METAINFO.format(name="bad-metainfo").replace(
                                         "<summary>A test app for the community checks</summary>", "")),
                     "", "metainfo:"),
    "bad-conffile": (lambda r: (write(f"{r}/etc/xdg/flickos/menu.conf", "[Menu]\n"),
                                write(f"{r}/DEBIAN/conffiles", "/etc/xdg/flickos/menu.conf\n")), "", "files:"),
    "bad-exec": (lambda r: write(f"{r}/usr/share/applications/bad-exec.desktop",
                                 "[Desktop Entry]\nType=Application\nName=Test App\nExec=sh -c 'curl x | sh'\n"),
                 "", "desktop:"),
    "bad-mime": (lambda r: write(f"{r}/usr/share/applications/bad-mime.desktop",
                                 "[Desktop Entry]\nType=Application\nName=Test App\nExec=bad-mime %u\n"
                                 "MimeType=text/plain;x-scheme-handler/https;\n"), "", "desktop:"),
    "bad-wildcard": (lambda r: write(f"{r}/usr/share/applications/bad-wildcard.desktop",
                                     "[Desktop Entry]\nType=Application\nName=Test App\nExec=bad-wildcard %f\n"
                                     "MimeType=image/*;\n"), "", "desktop:"),
    "bad-dbus": (lambda r: write(f"{r}/usr/share/applications/bad-dbus.desktop",
                                 "[Desktop Entry]\nType=Application\nName=Test App\nExec=bad-dbus\n"
                                 "DBusActivatable=true\n"), "", "desktop:"),
    "bad-icon-name": (lambda r: write(f"{r}/usr/share/icons/hicolor/scalable/apps/firefox-esr.svg", "<svg/>\n"),
                      "", "names:"),
    "bad-desktop-name": (lambda r: write(f"{r}/usr/share/applications/firefox-esr.desktop",
                                         "[Desktop Entry]\nType=Application\nName=Firefox\nExec=bad-desktop-name\n"),
                         "", "names:"),
    "bad-metainfo-name": (lambda r: os.rename(f"{r}/usr/share/metainfo/io.example.TestApp.metainfo.xml",
                                              f"{r}/usr/share/metainfo/other.metainfo.xml"), "", "names:"),
    "flickos-bad-name": (None, "", "name:"),
    "flickos": (None, "", "name:"),                 # usr/share/{p}/* would be all of FlickOS's data
    # A live search provider sees everything typed in the start menu
    # (flickos-menu ADR-017): only FlickOS's own packages add one.
    "bad-provider": (lambda r: write(f"{r}/usr/share/flickos/menu/providers/bad-provider.json", "{}\n"), "",
                     "files:"),
    # An add-on is loaded into the panel and labwc at every login, so what it
    # starts runs without anyone asking (hooks design, ADR-009).
    "bad-addon-exec": (addon("bad-addon-exec", waybar_jsonc=bar(exec="touch /tmp/x", interval=5)), "", "addon:"),
    "bad-addon-execif": (addon("bad-addon-execif", waybar_jsonc=bar(**{"exec-if": "true"})), "", "addon:"),
    "bad-addon-twice": (addon("bad-addon-twice", waybar_jsonc='{"custom/b": {"exec": "a", "exec": "b"}}'), "", "addon:"),
    "bad-addon-click": (addon("bad-addon-click", waybar_jsonc=bar(**{"on-click": "sh -c 'curl x | sh'"})),
                        "", "addon:"),
    "bad-addon-chain": (addon("bad-addon-chain", waybar_jsonc=bar(**{"on-scroll-up": "bad-addon-chain && evil"})),
                        "", "addon:"),
    "bad-addon-subst": (addon("bad-addon-subst", waybar_jsonc=bar(**{"on-click": "bad-addon-subst $(evil)"})),
                        "", "addon:"),
    "bad-addon-relative": (addon("bad-addon-relative", waybar_jsonc=bar(**{"on-click": "usr/bin/bad-addon-relative"})),
                           "", "addon:"),
    "bad-addon-actions": (addon("bad-addon-actions", waybar_jsonc=bar(**{"menu-actions": {"a": "evil"}})),
                          "", "addon:"),
    "bad-addon-list": (addon("bad-addon-list", waybar_jsonc=bar(**{"on-click": ["bad-addon-list"]})), "", "addon:"),
    "bad-addon-json": (addon("bad-addon-json", waybar_jsonc="{ nope"), "", "addon:"),
    "bad-addon-rule": (addon("bad-addon-rule", labwc_xml=rule(
        '<action name="Execute" command="/usr/bin/bad-addon-rule"/>')), "", "addon:"),
    "bad-addon-rule-case": (addon("bad-addon-rule-case", labwc_xml=rule('<action name="eXeCute"><command>x</command></action>')),
                            "", "addon:"),
    "bad-addon-rule-exit": (addon("bad-addon-rule-exit", labwc_xml=rule('<action name="Exit"/>')), "", "addon:"),
    "bad-addon-key": (addon("bad-addon-key", labwc_xml=keys("firefox")), "", "addon:"),
    "bad-addon-key-child": (addon("bad-addon-key-child", labwc_xml=(
        '<labwc_config><keyboard><keybind key="W-F9"><action name="Execute"><command>evil</command></action>'
        '</keybind></keyboard></labwc_config>')), "", "addon:"),
    "bad-addon-key-none": (addon("bad-addon-key-none", labwc_xml=(
        '<labwc_config><keyboard><keybind key="W-F9"><action name="Execute"/></keybind></keyboard>'
        '</labwc_config>')), "", "addon:"),
    "bad-addon-xml": (addon("bad-addon-xml", labwc_xml="<labwc_config>"), "", "addon:"),
    "bad-addon-extra": (addon("bad-addon-extra", style_css="", run_sh="#!/bin/sh\n"), "", "addon:"),
    "bad-addon-link": (lambda r: (write(f"{r}/usr/share/bad-addon-link/k.xml", "<labwc_config/>\n"),
                                  symlink("../../../bad-addon-link/k.xml",
                                          f"{r}/usr/share/flickos/addons/bad-addon-link/labwc.xml")), "", "addon:"),
    "hello": (None, "", "name:"),                   # Debian's
    "sfwbar": (None, "", "name:"),                  # FlickOS's, without the prefix
}


class ChecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="community-test-")
        cls.debs = {"good-app": make_deb(cls.folder, "good-app")}
        cls.debs["good-config"] = make_deb(cls.folder, "good-config", lambda r: (
            write(f"{r}/etc/xdg/flickos/good-config.conf", "[GoodConfig]\n"),
            write(f"{r}/etc/xdg/good-config/defaults.ini", "[a]\n"),
            write(f"{r}/DEBIAN/conffiles", "/etc/xdg/flickos/good-config.conf\n/etc/xdg/good-config/defaults.ini\n"),
            write(f"{r}/usr/share/good-config/main.py", "print()\n"),
            symlink("../share/good-config/main.py", f"{r}/usr/bin/good-config-run"),
            write(f"{r}/usr/share/icons/hicolor/scalable/apps/io.example.TestApp.svg", "<svg/>\n")))
        # The allowed variants: a desktop file named by the ID, a program in
        # usr/lib/NAME, a -symbolic icon, ordinary types and its own scheme.
        cls.debs["good-variants"] = make_deb(cls.folder, "good-variants", lambda r: (
            os.remove(f"{r}/usr/share/applications/good-variants.desktop"),
            write(f"{r}/usr/share/applications/io.example.TestApp.desktop",
                  "[Desktop Entry]\nType=Application\nName=Test App\nExec=/usr/lib/good-variants/run %U\n"
                  "TryExec=good-variants\nMimeType=text/plain;x-scheme-handler/testapp;\n"),
            write(f"{r}/usr/lib/good-variants/run", "#!/bin/sh\n", 0o755),
            write(f"{r}/usr/share/icons/hicolor/symbolic/apps/io.example.TestApp-symbolic.svg", "<svg/>\n"),
            write(f"{r}/usr/share/icons/hicolor/48x48/apps/good-variants-tray.png", "png\n")))
        # An add-on that starts only its own program, from a button, a key and
        # a window rule that changes the window.
        cls.debs["good-addon"] = make_deb(cls.folder, "good-addon", addon(
            "good-addon",
            waybar_jsonc=bar(format="http://example.org // not a comment", **{
                "on-click": "good-addon --toggle", "on-click-right": "/usr/bin/good-addon --menu",
                "on-scroll-up": "good-addon --up"}),
            labwc_xml=('<labwc_config><keyboard><keybind key="W-F9" description="Open Good Addon">'
                       '<action name="Execute" command="good-addon --open"/></keybind>'
                       '<keybind key="W-F10"><action name="Execute"><command>/usr/bin/good-addon</command></action>'
                       '</keybind><keybind key="W-F11"><action name="Exit"/></keybind></keyboard>'
                       '<windowRules><windowRule identifier="good-addon"><action name="Maximize"/>'
                       '</windowRule></windowRules></labwc_config>\n'),
            style_css="#custom-button { color: @fg_color; }\n"))
        for name, (change, control, _rule) in BAD.items():
            cls.debs[name] = make_deb(cls.folder, name, change, control)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder)

    def setUp(self):
        patcher = mock.patch.object(check, "origins", side_effect=lambda name: ORIGINS.get(name, set()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_good_packages_pass(self):
        for name in ("good-app", "good-config", "good-variants", "good-addon"):
            with self.subTest(name):
                self.assertEqual(check.check(self.debs[name], skip_lintian=True), (name, []))

    def test_each_rule_catches_its_package_and_only_its_rule(self):
        for name, (_change, _control, rule) in BAD.items():
            with self.subTest(name):
                package, problems = check.check(self.debs[name], skip_lintian=True)
                self.assertEqual(package, name)
                self.assertTrue(problems)
                self.assertEqual({p.split()[0] for p in problems}, {rule}, problems)

    def test_addon_problems_say_what_is_wrong(self):
        wanted = {
            "bad-addon-exec": "waybar.jsonc: custom/button.exec runs a program at every login",
            "bad-addon-execif": "custom/button.exec-if runs a program",
            "bad-addon-twice": "custom/b.exec runs a program",
            "bad-addon-click": "custom/button.on-click doesn't run just one of the package's own programs",
            "bad-addon-chain": "on-scroll-up doesn't run just one",
            "bad-addon-subst": "on-click doesn't run just one",
            "bad-addon-relative": "on-click doesn't run just one",
            "bad-addon-actions": "menu-actions doesn't run just one",
            "bad-addon-list": "on-click doesn't run just one",
            "bad-addon-json": "waybar.jsonc can't be read",
            "bad-addon-rule": "a window rule's action 'Execute'",
            "bad-addon-rule-case": "a window rule's action 'eXeCute'",
            "bad-addon-rule-exit": "a window rule's action 'Exit'",
            "bad-addon-key": "Execute 'firefox' doesn't run just one",
            "bad-addon-key-child": "Execute 'evil' doesn't run just one",
            "bad-addon-key-none": "Execute '' doesn't run just one",
            "bad-addon-xml": "labwc.xml can't be read",
            "bad-addon-extra": "run.sh: an add-on's folder holds only",
            "bad-addon-link": "is a link",
        }
        for name, words in wanted.items():
            with self.subTest(name):
                _package, problems = check.check(self.debs[name], skip_lintian=True)
                self.assertTrue(any(words in p for p in problems), problems)

    def test_own_program_means_one_plain_command(self):
        programs = {"usr/bin/tally", "usr/lib/tally/run"}
        for good in ("tally", "tally --toggle -x 1", "/usr/bin/tally", "//usr/bin/tally", "/usr/lib/tally/run --a=b"):
            self.assertTrue(check.runs_own_program(good, programs), good)
        for bad in ("", "  ", "other", "tally; evil", "tally && evil", "tally | evil", "tally $HOME", "tally `evil`",
                    "tally 'a b'", 'tally "x"', "tally *", "tally > f", "tally\nevil", "usr/bin/tally",
                    "./tally", "/usr/bin/../bin/tally", "/usr/bin/other", "X=1 tally", "~/tally", None):
            self.assertFalse(check.runs_own_program(bad, programs), bad)

    def test_main_exit_code(self):
        with mock.patch("sys.stdout"):
            self.assertEqual(check.main(["--skip-lintian", self.debs["good-app"]]), 0)
            self.assertEqual(check.main(["--skip-lintian", self.debs["good-app"], self.debs["bad-dep"]]), 1)

    def test_allowed_paths(self):
        self.assertTrue(check.allowed("usr/share/tally/x/y.py", "tally", strict=True))
        self.assertTrue(check.allowed("usr/bin/tally-cli", "tally", strict=True))
        self.assertFalse(check.allowed("usr/bin/other", "tally", strict=True))
        self.assertTrue(check.allowed("etc/xdg", "tally"))              # on the way
        self.assertFalse(check.allowed("etc", "tally", strict=True))    # a link's target can't be above
        self.assertFalse(check.allowed("usr/lib/systemd", "tally"))
        self.assertFalse(check.allowed("usr/share/flickos/menu/providers/tally.json", "tally"))


STYLE_METAINFO = """\
<?xml version="1.0" encoding="UTF-8"?>
<component type="addon">
  <id>io.example.styles.{title}</id>
  <extends>flickos-layout.desktop</extends>
  <name>{title}</name>
  <summary>Orange accents on Dark</summary>
  <description><p>Dark with an orange accent and its own title bars.</p></description>
  <icon type="stock">preferences-desktop-theme</icon>
  <url type="homepage">https://example.org/</url>
  <developer id="io.example"><name>Example</name></developer>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <custom><value key="FlickOS::style">{style}</value></custom>
</component>
"""
FLICKOS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def make_style_deb(folder, name, change=None, style=None):
    """A style package: style folder, window theme and add-on metainfo, all
    named after it; change(root) breaks something first."""
    root = os.path.join(folder, "build", name)
    title = name.title().replace("-", "")
    write(os.path.join(root, "usr/share/flickos/styles", name, "style.ini"),
          f"[Style]\nName={title}\nInherits=dark\nWaybar=waybar-colors.css\nLabwcTheme={name}\n")
    write(os.path.join(root, "usr/share/flickos/styles", name, "waybar-colors.css"),
          "@define-color selected_bg_color #d9600b;\n")
    write(os.path.join(root, "usr/share/themes", name, "labwc/themerc"), "window.active.title.bg.color: #d9600b\n")
    write(os.path.join(root, "usr/share/themes", name, "labwc/close-active.svg"), "<svg/>\n")
    write(os.path.join(root, f"usr/share/metainfo/io.example.styles.{title}.metainfo.xml"),
          STYLE_METAINFO.format(title=title, style=name if style is None else style))
    write(os.path.join(root, f"usr/share/doc/{name}/copyright"),
          "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
          "Files: *\nCopyright: 2026 Example\nLicense: GPL-3+\n")
    write(os.path.join(root, "DEBIAN/control"), textwrap.dedent(f"""\
        Package: {name}
        Version: 1.0
        Architecture: all
        Maintainer: Example <dev@example.org>
        Depends: flickos-layouts (>= 1.53), greybird-gtk-theme
        Section: x11
        Priority: optional
        Description: test style
         Orange accents.
        """))
    if change:
        change(root)
    deb = os.path.join(folder, f"{name}.deb")
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", root, deb], check=True, capture_output=True)
    return deb


def replace_in(path, old, new):
    with open(path) as f:
        text = f.read()
    write(path, text.replace(old, new))


# name -> (change, FlickOS::style or None for the name, words its problem has)
BAD_STYLES = {
    "bad-style-value": (None, "dark", "it must be the package's name"),
    "bad-style-nometa": (lambda r: shutil.rmtree(f"{r}/usr/share/metainfo"), None, "no add-on metainfo"),
    "bad-style-extra": (lambda r: write(f"{r}/usr/share/flickos/styles/bad-style-extra/run.sh", "#!/bin/sh\n"),
                        None, "a style's folder holds only"),
    "bad-style-theme": (lambda r: write(f"{r}/usr/share/themes/bad-style-theme/labwc/notes.txt", "x\n"),
                        None, "a window theme holds only"),
    "bad-style-gtk": (lambda r: write(f"{r}/usr/share/themes/bad-style-gtk/gtk-3.0/gtk.css", "x\n"),
                      None, "outside the package's own paths"),
    "bad-style-only-theme": (lambda r: shutil.rmtree(f"{r}/usr/share/flickos"), None, "comes with a style"),
    "bad-style-key": (lambda r: write(f"{r}/usr/share/flickos/styles/bad-style-key/foot.ini",
                                      "[main]\nshell=sh -c 'curl x | sh'\n") or replace_in(
                          f"{r}/usr/share/flickos/styles/bad-style-key/style.ini", "Waybar=", "Foot=foot.ini\nWaybar="),
                      None, "error: shell"),
    "bad-style-contrast": (lambda r: write(f"{r}/usr/share/flickos/styles/bad-style-contrast/waybar-colors.css",
                                           "@define-color selected_bg_color #f27835;\n"), None, "below 3:1"),
    "bad-style-layout": (lambda r: replace_in(f"{r}/usr/share/metainfo/io.example.styles.BadStyleLayout.metainfo.xml",
                                              '<value key="FlickOS::style">',
                                              '<value key="FlickOS::layout">mybar</value><value key="FlickOS::style">'),
                         None, "a community style can't bring one"),
    "bad-style-wmtheme": (lambda r: replace_in(f"{r}/usr/share/flickos/styles/bad-style-wmtheme/style.ini",
                                               "LabwcTheme=bad-style-wmtheme", "LabwcTheme=Nowhere"),
                          None, "Nowhere"),
}


@unittest.skipUnless(os.path.isfile(check.LAYOUT), "not in a FlickOS checkout")
class StyleChecksTest(unittest.TestCase):
    """Style packages (ricing design, phase 4c), checked with this
    checkout's flickos-layout over fake installed themes."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="community-style-test-")
        cls.share = os.path.join(cls.folder, "share")
        write(os.path.join(cls.share, "themes/Arc-Dark/gtk-3.0/gtk.css"), "")
        write(os.path.join(cls.share, "icons/Numix-Circle/index.theme"), "[Icon Theme]\n")
        cls.debs = {"good-style": make_style_deb(cls.folder, "good-style")}
        for name, (change, style, _words) in BAD_STYLES.items():
            cls.debs[name] = make_style_deb(cls.folder, name, change, style)
        cls.debs["dark"] = make_style_deb(cls.folder, "dark")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder)

    def setUp(self):
        for patcher in (mock.patch.object(check, "origins", side_effect=lambda name: ORIGINS.get(name, set())),
                        mock.patch.object(check, "SYSTEM_SHARE", self.share)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_good_style_passes(self):
        self.assertEqual(check.check(self.debs["good-style"], skip_lintian=True), ("good-style", []))

    def test_each_style_rule(self):
        for name, (_change, _style, words) in BAD_STYLES.items():
            with self.subTest(name):
                _package, problems = check.check(self.debs[name], skip_lintian=True)
                self.assertTrue(any(words in p for p in problems), problems)

    def test_flickos_style_names_are_refused(self):
        _package, problems = check.check(self.debs["dark"], skip_lintian=True)
        self.assertIn("style: dark is one of FlickOS's styles", problems)

    def test_a_missing_theme_fails(self):
        with mock.patch.object(check, "SYSTEM_SHARE", "/nonexistent"):
            _package, problems = check.check(self.debs["good-style"], skip_lintian=True)
        self.assertTrue(any("Arc-Dark" in p for p in problems), problems)

    def test_apps_are_not_styles(self):
        app = make_deb(self.folder, "plain-app")
        self.assertFalse(check.is_style([path for _m, path, _t in check.members(app)]))
        self.assertTrue(check.is_style([path for _m, path, _t in check.members(self.debs["good-style"])]))

    def test_packages_to_install(self):
        self.assertEqual(check.style_packages(self.debs["good-style"]),
                         [*check.FLICKOS_THEME_PACKAGES, "greybird-gtk-theme"])

    def test_review_names_the_style(self):
        facts = build.package_facts(self.debs["good-style"])
        self.assertTrue(any("Inherits=dark" in fact and "LabwcTheme=good-style" in fact for fact in facts), facts)


class TreeTest(unittest.TestCase):
    """check.py's copies of FlickOS's lists, against this checkout."""

    @unittest.skipUnless(os.path.isdir(os.path.join(FLICKOS, "packages")), "not in a FlickOS checkout")
    def test_flickos_styles(self):
        found = {os.path.basename(path) for path in
                 glob.glob(os.path.join(FLICKOS, "packages/*/usr/share/flickos/styles/*"))}
        self.assertEqual(found, set(check.FLICKOS_STYLES))

    @unittest.skipUnless(os.path.isfile(check.LAYOUT), "not in a FlickOS checkout")
    def test_style_files_are_what_import_takes(self):
        with open(check.LAYOUT, encoding="utf-8") as f:
            text = f.read()
        names = []
        for constant in ("IMPORT_TEXT_FILES", "IMPORT_WALLPAPERS"):
            names += re.findall(r'"([^"]+)"', re.search(rf"^{constant} = \((.*)\)$", text, re.M).group(1))
        self.assertEqual(tuple(names), check.STYLE_FILES)

    @unittest.skipUnless(os.path.isfile(check.LAYOUT), "not in a FlickOS checkout")
    def test_add_ons_are_what_flickos_layout_reads(self):
        with open(check.LAYOUT, encoding="utf-8") as f:
            text = f.read()
        files = tuple(re.search(rf'^{constant} = "([^"]+)"', text, re.M).group(1)
                      for constant in ("ADDON_LABWC", "ADDON_WAYBAR", "ADDON_STYLE"))
        self.assertEqual(files, check.ADDON_FILES)
        self.assertIn('ADDONS_DIR = PREFIX + "/' + check.ADDONS.rstrip("/") + '"', text)

    @unittest.skipUnless(os.path.isfile(check.LAYOUT), "not in a FlickOS checkout")
    def test_jsonc_is_stripped_as_flickos_layout_does(self):
        loader = importlib.machinery.SourceFileLoader("flickos_layout_for_test", check.LAYOUT)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        layout = importlib.util.module_from_spec(spec)
        loader.exec_module(layout)
        for text in ('{"a": 1} // end', '/* x */ {"u": "http://a/b", "q": "\\" // no"}', '{\n // c\n "b": 2 }',
                     '{"a": /* inline */ 3}'):
            self.assertEqual(check.strip_jsonc(text), layout.strip_jsonc(text), text)
        for text in ("/* never closed",):
            with self.assertRaises(ValueError):
                check.strip_jsonc(text)
            with self.assertRaises(ValueError):
                layout.strip_jsonc(text)

    @unittest.skipUnless(os.path.isdir(os.path.join(FLICKOS, "packages")), "not in a FlickOS checkout")
    def test_theme_packages(self):
        wanted = set()
        for package in ("flickos-settings", "flickos-style-seven"):
            with open(os.path.join(FLICKOS, "packages", package, "debian/control"), encoding="utf-8") as f:
                wanted |= set(re.findall(r"\b((?:arc|numix)[a-z-]*-theme[a-z-]*)", f.read()))
        self.assertEqual(wanted, set(check.FLICKOS_THEME_PACKAGES))

    @unittest.skipUnless(os.path.isdir(os.path.join(FLICKOS, "packages", "flickos-software")), "no flickos-software")
    def test_software_reads_the_same_add_ons(self):
        with open(os.path.join(FLICKOS, "packages/flickos-software/usr/bin/flickos-software"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn(f'STYLE_EXTENDS = "{check.STYLE_EXTENDS}"', text)
        self.assertIn(f'STYLE_KEY = "{check.STYLE_KEY}"', text)


class PolicyTest(unittest.TestCase):
    def test_policy_parsing(self):
        policy = textwrap.dedent("""\
            Package files:
             100 /var/lib/dpkg/status
                 release a=now
             500 https://dvbondoy.github.io/flickos-apt trixie-community/main amd64 Packages
                 release o=FlickOS,a=trixie-community,n=trixie-community,l=FlickOS Community,c=main,b=amd64
             500 http://deb.debian.org/debian trixie/main amd64 Packages
                 release v=13.1,o=Debian,a=stable,n=trixie,l=Debian,c=main,b=amd64
            """)
        package = textwrap.dedent("""\
            tally:
              Installed: (none)
              Version table:
                 1.0 500
                    500 https://dvbondoy.github.io/flickos-apt trixie-community/main amd64 Packages
            """)
        answers = {("apt-cache", "policy"): policy, ("apt-cache", "policy", "tally"): package}
        with mock.patch.object(check, "_SOURCES", None), \
                mock.patch.object(check, "run", side_effect=lambda argv: mock.Mock(stdout=answers.get(tuple(argv), ""))):
            self.assertEqual(check.origins("tally"), {("FlickOS", "FlickOS Community")})
            self.assertEqual(check.origins("nothing"), set())


def git(folder, *args):
    return subprocess.run(["git", "-C", folder, *args], check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}).stdout.strip()


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="community-build-test-")
        self.addCleanup(shutil.rmtree, self.folder)
        self.source = os.path.join(self.folder, "tally")
        os.makedirs(self.source)
        git(self.source, "init", "-q", "-b", "main")
        write(os.path.join(self.source, "tally"), "one\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "-q", "-m", "one")
        git(self.source, "tag", "v1.0")
        self.first = git(self.source, "rev-parse", "HEAD")
        write(os.path.join(self.source, "tally"), "two\n")
        git(self.source, "commit", "-q", "-am", "two")
        self.second = git(self.source, "rev-parse", "HEAD")

    def app(self, **changes):
        app = {"git": self.source, "tag": "v1.0", "commit": self.first, "version": "1.0"}
        app.update(changes)
        return app

    def test_parse_app(self):
        text = f"# Tally\ngit = https://example.org/tally.git\ntag = v1.0\ncommit = {self.first}\nversion = 1.0\n"
        self.assertEqual(build.parse_app("tally", text),
                         {"git": "https://example.org/tally.git", "tag": "v1.0", "commit": self.first, "version": "1.0"})
        for name, broken, words in (
                ("flickos-tally", text, "not a package name"),
                ("Tally", text, "not a package name"),
                ("tally", text.replace("version = 1.0\n", ""), "version missing"),
                ("tally", text + "branch = main\n", "expected one of"),
                ("tally", text + "tag = v2\n", "twice"),
                ("tally", text.replace(self.first, "abc123"), "40-digit"),
                ("tally", text.replace("https://example.org/tally.git", "/home/me/tally"), "https://")):
            with self.subTest(words):
                with self.assertRaisesRegex(build.BuildError, words):
                    build.parse_app(name, broken)
        self.assertEqual(build.parse_app("tally", text.replace("https://example.org/tally.git", "/srv/tally"),
                                         allow_local=True)["git"], "/srv/tally")

    def test_a_pinned_tag_is_checked_out(self):
        checkout = os.path.join(self.folder, "checkout")
        build.fetch_source(self.app(), checkout)
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), self.first)
        with open(os.path.join(checkout, "tally")) as f:
            self.assertEqual(f.read(), "one\n")

    def test_a_moved_tag_is_refused(self):
        git(self.source, "tag", "-f", "v1.0", self.second)
        with self.assertRaisesRegex(build.BuildError, "moved tag"):
            build.fetch_source(self.app(), os.path.join(self.folder, "checkout"))
        with self.assertRaisesRegex(build.BuildError, "isn't in"):
            build.fetch_source(self.app(tag="v9"), os.path.join(self.folder, "checkout2"))

    def test_diffs(self):
        checkout = os.path.join(self.folder, "checkout")
        build.fetch_source(self.app(), checkout)
        full, words = build.source_diff(checkout, None, self.first)
        self.assertIn("+one", full)
        self.assertIn("A new app", words)
        full, words = build.source_diff(checkout, self.first, self.second)
        self.assertIn("-one\n+two", full)
        self.assertIn(self.first[:12], words)
        self.assertNotIn("ancestor", words)
        self.assertEqual(build.source_diff(checkout, self.first, self.first)[0], "")
        git(self.source, "checkout", "-q", "--orphan", "rewritten")
        git(self.source, "commit", "-q", "-m", "rewritten")
        rewritten = git(self.source, "rev-parse", "HEAD")
        git(checkout, "fetch", "-q", self.source, "rewritten")
        self.assertIn("isn't an ancestor", build.source_diff(checkout, self.second, rewritten)[1])

    def test_unreviewable_source_is_refused(self):
        tree = os.path.join(self.folder, "tree")
        write(os.path.join(tree, "app.py"), "print('hi')\n")
        write(os.path.join(tree, "icon.png"), "\x89PNG\0\0")
        symlink("app.py", os.path.join(tree, "bin/app"))
        self.assertEqual(build.source_problems(tree), [])
        write(os.path.join(tree, ".gitmodules"), "[submodule]\n")
        write(os.path.join(tree, "lib/helper.so"), "\x7fELF\0\0")
        write(os.path.join(tree, "lib/cache.pyc"), "\0\0\0")
        symlink("/etc/passwd", os.path.join(tree, "passwd"))
        symlink("../../outside", os.path.join(tree, "lib/up"))
        problems = build.source_problems(tree)
        self.assertEqual(len(problems), 5, problems)
        self.assertTrue(all(p.startswith("source: ") for p in problems))
        self.assertTrue(any("helper.so is a binary file" in p for p in problems))
        self.assertTrue(any("submodules" in p for p in problems))

    def test_things_to_look_at(self):
        write(os.path.join(self.source, "net.py"), "import os\nimport urllib.request\nx = 1\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "-q", "-m", "net")
        third = git(self.source, "rev-parse", "HEAD")
        checkout = os.path.join(self.folder, "checkout")
        build.fetch_source(self.app(), checkout)
        git(checkout, "fetch", "-q", self.source, "main")
        # an update: only what it adds, with the new file's line numbers
        added = build.added_lines(checkout, self.second, third)
        self.assertEqual(added, [("net.py", 1, "import os"), ("net.py", 2, "import urllib.request"), ("net.py", 3, "x = 1")])
        found = build.look_at(added)
        self.assertEqual(found, {"network": [("net.py", 2, "import urllib.request")]})
        # a new app: the whole tree at its commit
        self.assertIn(("tally", 1, "one"), build.added_lines(checkout, None, self.first))
        found = build.look_at([("a.js", 1, "x" * 2000), ("b.py", 9, "subprocess.run(['sudo', 'cp', '.bashrc'])"),
                               ("c.py", 2, "data = '" + "QUJD" * 40 + "'")])
        self.assertEqual(set(found), {"unreadable (a line over 1,000 characters)", "runs commands", "privileges",
                                      "starts programs", "hidden data"})
        full, short = build.review_text(found, ["menu entry a.desktop: Name=`A`"])
        self.assertIn("b.py:9: subprocess.run", full)
        self.assertIn("- `menu entry a.desktop: Name='A'`", short)
        self.assertEqual(build.review_text({}, [])[1][-1], "- Nothing the patterns know about was added.")
        self.assertEqual(build.look_at([("s.metainfo.xml", 4, "<extends>flickos-layout.desktop</extends>")]), {})
        self.assertIn("starts programs", build.look_at([("x.py", 1, "open('~/.config/autostart/x.desktop')")]))

    def test_the_build_user_must_be_offline(self):
        with mock.patch.object(build.subprocess, "run", return_value=mock.Mock(returncode=0)):
            with self.assertRaisesRegex(build.BuildError, "wouldn't be offline"):
                build.check_offline("builder")
        with mock.patch.object(build.subprocess, "run", return_value=mock.Mock(returncode=1)) as probe:
            build.check_offline("builder")
        self.assertEqual(probe.call_args[0][0][:4], ["runuser", "-u", "builder", "--"])

    def test_withdrawn_package(self):
        deb = build.withdrawn_deb("tally", "1.1", "it  sent  files away", os.path.join(self.folder, "out"))
        fields = check.control_fields(deb)
        self.assertEqual((fields["Package"], fields["Version"]), ("tally", "1.1+withdrawn1"))
        self.assertNotIn("Depends", fields)
        self.assertEqual(subprocess.run(["dpkg", "--compare-versions", "1.1+withdrawn1", "gt", "1.1"]).returncode, 0)
        files = [path for mode, path, _ in check.members(deb) if mode[0] == "-"]
        self.assertEqual(files, ["usr/share/doc/tally/README.withdrawn"])
        self.assertEqual(check.control_names(deb), {"control"})
        out = subprocess.run(["dpkg-deb", "--fsys-tarfile", deb], capture_output=True).stdout
        self.assertIn(b"withdrawn from FlickOS's community repository: it sent files away.", out)

    def test_changed_lists_only_package_names(self):
        apps = os.path.join(self.folder, "apps")
        write(os.path.join(apps, "tally"), "")
        write(os.path.join(apps, ".gitkeep"), "")
        write(os.path.join(apps, "x';rm -rf"), "")
        with mock.patch.object(build, "APPS_DIR", apps):
            self.assertEqual(build.changed(""), ["tally"])
            self.assertEqual(build.changed("0" * 40), ["tally"])


if __name__ == "__main__":
    unittest.main()
