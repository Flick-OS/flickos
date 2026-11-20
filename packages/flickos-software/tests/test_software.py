"""Tests for usr/bin/flickos-software. Run: python3 -m unittest discover -s tests"""

import contextlib
import gzip
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_software", os.path.join(PACKAGE, "usr/bin/flickos-software"))
fs = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fs)

LANG = "{http://www.w3.org/XML/1998/namespace}lang"

FLATHUB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flathub">
  <component type="desktop-application">
    <id>org.gimp.GIMP</id>
    <name>GNU Image Manipulation Program</name>
    <name xml:lang="de">GNU-Bildbearbeitung</name>
    <summary>High-end image creation and manipulation</summary>
    <summary xml:lang="de">Bilder erstellen</summary>
    <description><p>GIMP is an acronym.</p><ul><li>Layers</li><li>Brushes</li></ul></description>
    <description xml:lang="de"><p>GIMP ist eine Abkürzung.</p></description>
    <developer><name>The GIMP team</name><name xml:lang="de">Das GIMP-Team</name></developer>
    <project_license>GPL-3.0+</project_license>
    <launchable type="desktop-id">org.gimp.GIMP.desktop</launchable>
    <provides><id>gimp.desktop</id></provides>
    <icon type="cached" width="128" height="128">org.gimp.GIMP.png</icon>
    <icon type="cached" width="64" height="64">org.gimp.GIMP.png</icon>
    <icon type="cached" width="64" height="64" scale="2">org.gimp.GIMP.png</icon>
    <icon type="stock">org.gimp.GIMP</icon>
    <icon type="remote" width="128" height="128">https://dl.flathub.org/media/gimp.png</icon>
    <url type="homepage">https://www.gimp.org/</url>
    <categories><category>Graphics</category><category>2DGraphics</category></categories>
    <keywords><keyword>photoshop</keyword><keyword xml:lang="de">bild</keyword></keywords>
    <screenshots>
      <screenshot type="default">
        <caption>Editing a photo</caption>
        <image type="source" width="1920" height="1080">https://dl.flathub.org/shot-orig.png</image>
        <image type="thumbnail" width="624" height="351">https://dl.flathub.org/shot-624.png</image>
        <image type="thumbnail" width="752" height="423">https://dl.flathub.org/shot-752.png</image>
        <image type="thumbnail" width="752" height="423" scale="2">https://dl.flathub.org/shot-752x2.png</image>
      </screenshot>
    </screenshots>
    <releases>
      <release version="3.3.0" timestamp="1800000000" type="development"/>
      <release version="3.2.6" timestamp="1788998400" type="stable"/>
      <release version="3.2.5" timestamp="1780000000"/>
    </releases>
    <bundle type="flatpak" runtime="org.gnome.Platform/x86_64/51">app/org.gimp.GIMP/x86_64/stable</bundle>
  </component>
  <component type="desktop-application">
    <id>org.videolan.VLC</id>
    <name>VLC</name>
    <summary>Play videos</summary>
    <icon type="remote" width="128" height="128">https://dl.flathub.org/media/vlc.png</icon>
    <categories><category>AudioVideo</category></categories>
    <bundle type="flatpak">app/org.videolan.VLC/x86_64/stable</bundle>
  </component>
  <component type="desktop-application">
    <id>org.mozilla.firefox</id>
    <name>Firefox</name>
    <summary>Fast, private browsing</summary>
    <categories><category>Network</category></categories>
    <bundle type="flatpak">app/org.mozilla.firefox/x86_64/stable</bundle>
  </component>
  <component type="desktop-application">
    <id>io.example.Only</id>
    <name>Only On Flathub</name>
    <summary>A Flathub app</summary>
    <categories><category>Game</category></categories>
    <bundle type="flatpak">app/io.example.Only/x86_64/stable</bundle>
  </component>
  <component type="runtime">
    <id>org.gnome.Platform</id>
    <name>GNOME runtime</name>
    <bundle type="flatpak">runtime/org.gnome.Platform/x86_64/51</bundle>
  </component>
  <component type="desktop-application">
    <id>io.example.NoBundle</id>
    <name>No bundle</name>
  </component>
</components>
"""


def debian_row(app_id, name, pkg, cats=("Utility",), launch=None, icons=None, summary="",
               origin="debian-trixie-main"):
    return ({"id": app_id, "name": name, "summary": summary or f"{name} summary", "icons": icons or [f"stock:{pkg}"],
             "cats": list(cats), "kw": [], "launch": launch if launch is not None else [f"{pkg}.desktop"],
             "provides": [], "pkg": pkg, "origin": origin},
            {"desc": [f"{name} from Debian."], "shots": [{"url": f"https://appstream.debian.org/{pkg}.png",
                                                           "caption": ""}],
             "dev": "Debian", "license": "GPL-2.0+", "home": "", "version": "1.0", "date": 0})


DEBIAN = [
    debian_row("org.gimp.GIMP", "GIMP", "gimp", ("Graphics",), ["gimp.desktop"],
               ["stock:gimp", "url:https://appstream.debian.org/gimp.png"]),
    debian_row("org.videolan.vlc", "VLC", "vlc", ("AudioVideo",), ["vlc.desktop"]),
    debian_row("firefox-esr.desktop", "Firefox ESR", "firefox-esr", ("Network",)),
    debian_row("org.xfce.mousepad", "Mousepad", "mousepad", ("Utility",), summary="Simple text editor"),
    debian_row("org.example.editor", "Editor", "editor", ("Development",), summary="Text editor for code"),
    # From FlickOS's community repository (repo/conf/dep11.py's origin).
    debian_row("io.example.Tally", "Tally", "tally", ("Office",), summary="Count things",
               origin="flickos-trixie-community-main"),
]

# dpkg-query's lines (DPKG_QUERY): status, name, version, Depends.
DPKG_LINES = (
    "ii \tvlc\t3.0.21-0+deb13u1\tvlc-bin (= 3.0.21-0+deb13u1), vlc-plugin-base\n"
    "rc \tmousepad\t0.6.3-1\t\n"
    "ii \tflickos-desktop\t1.30\tflickos-settings (>= 1.31), labwc, waybar | sfwbar, mate-polkit, firefox-esr\n"
    "hi \tfirefox-esr\t140.3.0esr-1\t\n"
)


class OtherArchTest(unittest.TestCase):
    """Wine's 32-bit part (OTHER_ARCH, flickos-switch ADR-004)."""

    def test_wine_comes_with_both_parts(self):
        extra, missing = fs.other_parts("wine", {"libwine": "10.0"})
        self.assertEqual(missing, ["wine64", "wine32:i386"])
        self.assertEqual(fs.other_parts("wine", {"wine64": "10.0"})[1], ["wine32:i386"])
        self.assertEqual(fs.other_parts("wine", {"wine64": "10.0", "wine32": "10.0"}), (extra, []))
        self.assertEqual(fs.other_parts("gimp", {}), (None, []))

    def test_parts_of_an_architecture_that_is_off_are_left_out(self):
        extra = fs.OTHER_ARCH["wine"]
        asked = []

        def resolve(name, arch):
            asked.append((name, arch))
            return [f"{name};1;{arch or 'amd64'};debian"]

        self.assertEqual(fs.resolve_parts(extra, ["wine64", "wine32:i386"], [], resolve), ["wine64;1;amd64;debian"])
        self.assertEqual(fs.resolve_parts(extra, ["wine64", "wine32:i386"], ["i386"], resolve),
                         ["wine64;1;amd64;debian", "wine32;1;i386;debian"])
        self.assertEqual(asked, [("wine64", None), ("wine64", None), ("wine32", "i386")])

    def test_turns_off_only_when_nothing_of_the_architecture_is_left(self):
        extra = fs.OTHER_ARCH["wine"]
        removing = ["wine;1;all;debian", "wine32;1;i386;debian", "libc6;2;i386;debian"]
        self.assertTrue(fs.turns_off(extra, ["i386"], {"wine32:i386"}, removing))
        self.assertFalse(fs.turns_off(extra, ["i386"], {"wine32:i386", "steam:i386"}, removing))
        self.assertFalse(fs.turns_off(extra, [], {"wine32:i386"}, removing))
        self.assertFalse(fs.turns_off(extra, ["i386"], None, removing))
        self.assertFalse(fs.turns_off(None, ["i386"], set(), removing))

    def test_asked_for(self):
        lines = ("ii \twine32:i386\ti386\nii \tlibc6:i386\ti386\nrc \tlibgl1:i386\ti386\nii \twine64\tamd64\n"
                 "un \tlibx:i386\ti386\n")
        manual = "wine64\nwine32:i386\nlibgl1:i386\n"
        with mock.patch.object(fs, "DPKG_ARCHES", [sys.executable, "-c", f"print({lines!r}, end='')"]), \
                mock.patch.object(fs, "APT_MANUAL", [sys.executable, "-c", f"print({manual!r}, end='')"]):
            self.assertEqual(fs.asked_for("i386"), {"wine32:i386"})
        with mock.patch.object(fs, "DPKG_ARCHES", ["/nonexistent/dpkg-query"]):
            self.assertIsNone(fs.asked_for("i386"))

    def test_control_setting(self):
        extra = fs.OTHER_ARCH["wine"]
        with mock.patch.object(fs.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            fs.control_setting(extra, "on", "Wine", "installed")
        self.assertEqual(run.call_args.args[0], ["flickos-control", "system", "i386", "on"])
        refused = "flickos-control: Error executing command as another user: Not authorized\n"
        with mock.patch.object(fs.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", refused)):
            with self.assertRaisesRegex(fs.SoftwareError, "^Wine wasn't installed: the password wasn't given"):
                fs.control_setting(extra, "on", "Wine", "installed")
        other = "flickos-control: control-helper: 32-bit packages are still installed (steam:i386)\n"
        with mock.patch.object(fs.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", other)):
            with self.assertRaisesRegex(fs.SoftwareError, r"couldn't be turned off \(control-helper: 32-bit"):
                fs.control_setting(extra, "off", "Wine", "removed")

    def wine_plan(self, **fields):
        plan = {"source": "debian", "action": "install", "app": "Wine", "package": "wine",
                "packages": ["wine", "wine64", "libwine"], "removes": [], "protected": [], "items": [],
                "size": 745_000_000, "download": 109_000_000, "adds": None, "only_parts": False, "turns_off": False}
        plan.update(fields)
        return fs.plan_words(plan)

    def test_plan_words_wine_before_32_bit_programs_are_allowed(self):
        adds = {"what": "support for 32-bit programs", "on": False, "size": 803_000_000, "download": 164_000_000}
        self.assertEqual(self.wine_plan(adds=adds),
                         "Needs 745.0 MB of disk space, with 2 other packages (109.0 MB to download). It comes "
                         "with support for 32-bit programs, which most Windows programs need: about 803.0 MB more "
                         "(164.0 MB to download). Installing it asks for your password twice: once to allow "
                         "32-bit programs, once to install.")
        self.assertEqual(self.wine_plan(adds=adds, only_parts=True, packages=[], size=0, download=0),
                         "Wine is installed without support for 32-bit programs, which most Windows programs "
                         "need. Adding it needs about 803.0 MB of disk space (164.0 MB to download) and asks for "
                         "your password twice: once to allow 32-bit programs, once to install them.")

    def test_plan_words_wine_once_32_bit_programs_are_allowed(self):
        adds = {"what": "support for 32-bit programs", "on": True, "size": 0, "download": 0}
        self.assertIn("packages (109.0 MB to download). That includes support for 32-bit programs, which most "
                      "Windows programs need. Debian apps are installed", self.wine_plan(adds=adds))
        self.assertTrue(self.wine_plan(adds=adds, only_parts=True).endswith(
            "Adding it needs 745.0 MB of disk space (109.0 MB to download). It asks for your password."))

    def test_plan_words_wine_removed(self):
        words = self.wine_plan(action="remove", removes=["wine", "wine64", "wine32"], packages=["wine", "wine64",
                               "wine32"], turns_off=True)
        self.assertTrue(words.endswith("Removing asks for your password, then again to turn off support for "
                                       "32-bit programs."))


class Env(unittest.TestCase):
    """A fake system and home under a temporary folder; nothing from the host."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.cache = os.path.join(self.root, "cache")
        patches = {
            "DPKG_QUERY": [sys.executable, "-c", f"print({DPKG_LINES!r}, end='')"],
            "SWCATALOG_YAML": os.path.join(self.root, "var/lib/swcatalog/yaml"),
            "SWCATALOG_CACHE": os.path.join(self.root, "var/cache/swcatalog/cache"),
            "FLATPAK_SYSTEM": os.path.join(self.root, "var/lib/flatpak"),
            "FLATHUB_CATALOG": os.path.join(self.root, "var/lib/flatpak/appstream/flathub/x86_64/active"),
            "FEATURED_FILE": os.path.join(PACKAGE, "usr/share/flickos/software/featured.json"),
            "FEATURED_URL": "http://127.0.0.1:9/nothing",       # never the real one
            "STORE_CATALOG_URL": "http://127.0.0.1:9/{release}",
            "FLICKOS_RELEASE": os.path.join(self.root, "usr/lib/flickos-release"),
            "OS_RELEASE": os.path.join(self.root, "etc/os-release"),
            "PURCHASES_FILE": os.path.join(self.root, "var/lib/flickos-control/purchases.json"),
            "CMDLINE": os.path.join(self.root, "proc/cmdline"),
            "SYSTEM_CONF": os.path.join(self.root, "etc/xdg/flickos/software.conf"),
            "HISTORY_CONF": os.path.join(self.root, "etc/xdg/flickos/history.conf"),
        }
        for name, value in patches.items():
            patcher = mock.patch.object(fs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.cache, "LANGUAGE": "", "LC_ALL": "",
                                           "LC_MESSAGES": "", "LANG": "C.UTF-8",
                                           "XDG_RUNTIME_DIR": os.path.join(self.root, "run"),
                                           "XDG_CONFIG_HOME": os.path.join(self.root, "config"),
                                           "XDG_STATE_HOME": os.path.join(self.root, "state")})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)

    def write(self, path, text, mode="w"):
        path = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(text)
        return path

    def flathub(self):
        """The fixture catalog where flatpak keeps Flathub's, and the remote."""
        self.write("var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz",
                   gzip.compress(FLATHUB_XML.encode()), "wb")
        self.write("var/lib/flatpak/repo/config", '[core]\nrepo_version=1\n\n[remote "flathub"]\nurl=https://dl.flathub.org/repo/\n')
        return fs.flathub_catalog()

    def flathub_rows(self, langs=("C",)):
        return list(fs.flathub_apps(self.flathub(), list(langs)))

    def built(self):
        flathub = self.flathub_rows()
        with mock.patch.object(fs.shutil, "which", lambda name: "/usr/bin/" + name):
            counts = fs.build_index(debian=iter(DEBIAN), flathub=iter(flathub))
            catalog = fs.Catalog()
            catalog.load()
            catalog.read_installed()
        self.addCleanup(catalog.close)
        return counts, catalog


class TextTest(unittest.TestCase):
    def test_languages(self):
        with mock.patch.dict(os.environ, {"LANGUAGE": "de_AT:fr", "LC_ALL": "", "LC_MESSAGES": "",
                                          "LANG": "pt_BR.UTF-8"}):
            self.assertEqual(fs.languages(), ["de_AT", "de", "fr", "pt_BR", "pt"])
        with mock.patch.dict(os.environ, {"LANGUAGE": "", "LC_ALL": "C", "LANG": "en_PH.UTF-8"}):
            self.assertEqual(fs.languages(), [])

    def test_best_picks_language_then_untranslated(self):
        import xml.etree.ElementTree as ET
        names = ET.fromstring('<c><name>Plain</name><name xml:lang="de">Deutsch</name>'
                              '<name xml:lang="pt-BR">Brasil</name></c>').findall("name")
        self.assertEqual(fs.best(names, ["de_AT", "de"]).text, "Deutsch")
        self.assertEqual(fs.best(names, ["pt_BR", "pt"]).text, "Brasil")
        self.assertEqual(fs.best(names, ["fr"]).text, "Plain")
        self.assertIsNone(fs.best(names[1:], ["fr"]))

    def test_description_markup(self):
        text = "<p>One\n  two.</p><ul><li>a</li><li>b</li></ul><ol><li>x</li></ol><p><em>Bold</em> move</p>"
        self.assertEqual(fs.description_paragraphs(text), ["One two.", "• a", "• b", "1. x", "Bold move"])
        self.assertEqual(fs.description_paragraphs("<p>broken"), ["broken"])
        self.assertEqual(fs.description_paragraphs(None), [])

    def test_fold(self):
        self.assertEqual(fs.fold("Écran ÇA"), "ecran ca")

    def test_runtime_names(self):
        self.assertEqual(fs.runtime_name("runtime/org.gnome.Platform/x86_64/50"), "the GNOME runtime")
        self.assertEqual(fs.runtime_name("runtime/org.freedesktop.Platform.GL.default/x86_64/25.08"),
                         "graphics drivers")
        self.assertEqual(fs.runtime_name("runtime/org.freedesktop.Platform/x86_64/25.08"),
                         "the Freedesktop runtime")
        self.assertIsNone(fs.runtime_name("runtime/org.gnome.Platform.Locale/x86_64/50"))
        self.assertIsNone(fs.runtime_name("app/org.gimp.GIMP/x86_64/stable"))

    def test_plan_words_debian(self):
        plan = {"source": "debian", "action": "install", "app": "GIMP", "package": "gimp",
                "packages": ["gimp", "gimp-data", "libgegl"], "removes": [], "protected": [], "items": [],
                "size": 170_000_000, "download": 30_000_000}
        self.assertEqual(fs.plan_words(plan), "Needs 170.0 MB of disk space, with 2 other packages "
                         "(30.0 MB to download). Debian apps are installed for the whole system and need "
                         "your password.")
        plan["packages"] = ["gimp", "gimp-data"]
        self.assertIn("with 1 other package (", fs.plan_words(plan))

    def test_plan_words_community(self):
        plan = {"source": "community", "action": "install", "app": "Tally", "package": "tally",
                "packages": ["tally"], "removes": [], "protected": [], "items": [], "size": 120_000, "download": 40_000}
        self.assertEqual(fs.plan_words(plan), "Needs 120.0 kB of disk space (40.0 kB to download). FlickOS Community "
                                              "apps are installed for the whole system and need your password.")

    def test_plan_words_flathub(self):
        plan = {"source": "flathub", "action": "install", "app": "Mines", "packages": [], "removes": [],
                "protected": [], "size": 3_000_000_000, "download": 1_100_000_000,
                "items": [{"name": "graphics drivers"}, {"name": "graphics drivers"},
                          {"name": "the GNOME runtime"}, {"name": None}]}
        self.assertEqual(fs.plan_words(plan), "Needs up to 1.1 GB to download and 3.0 GB of disk space, including "
                         "graphics drivers and the GNOME runtime.")

    def test_plan_words_remove_and_protected(self):
        plan = {"source": "debian", "action": "remove", "app": "VLC", "package": "vlc",
                "packages": ["vlc", "vlc-bin", "libvlc5"], "removes": ["vlc", "vlc-bin", "libvlc5"],
                "protected": [], "items": [], "size": 59_000_000, "download": 0}
        self.assertEqual(fs.plan_words(plan), "Removing it frees 59.0 MB. It also removes 2 packages that "
                         "only VLC used. Removing asks for your password.")
        plan["protected"] = ["flickos-desktop"]
        self.assertIn("part of the FlickOS desktop (flickos-desktop)", fs.plan_words(plan))


class FlathubCatalogTest(Env):
    def test_only_apps_with_an_app_bundle(self):
        ids = [row["id"] for row, _page in self.flathub_rows()]
        self.assertEqual(ids, ["org.gimp.GIMP", "org.videolan.VLC", "org.mozilla.firefox", "io.example.Only"])

    def test_row_and_page(self):
        row, page = self.flathub_rows()[0]
        self.assertEqual(row["name"], "GNU Image Manipulation Program")
        self.assertEqual(row["ref"], "app/org.gimp.GIMP/x86_64/stable")
        # The theme's icon, then the 64 px file (scale 1), no download while a file is there.
        self.assertEqual(row["icons"], ["stock:org.gimp.GIMP", "flathub:64x64/org.gimp.GIMP.png"])
        self.assertEqual(row["kw"], ["photoshop"])
        self.assertEqual(row["launch"], ["org.gimp.GIMP.desktop"])
        self.assertEqual(row["provides"], ["gimp.desktop"])
        self.assertEqual(page["desc"], ["GIMP is an acronym.", "• Layers", "• Brushes"])
        self.assertEqual(page["shots"], [{"url": "https://dl.flathub.org/shot-752.png", "caption": "Editing a photo"}])
        self.assertEqual(page["dev"], "The GIMP team")
        self.assertEqual((page["version"], page["date"]), ("3.2.6", 1788998400))   # not the development one
        self.assertEqual(page["home"], "https://www.gimp.org/")

    def test_translated(self):
        row, page = self.flathub_rows(["de_DE", "de"])[0]
        self.assertEqual(row["name"], "GNU-Bildbearbeitung")
        self.assertEqual(row["kw"], ["bild"])
        self.assertEqual(page["desc"], ["GIMP ist eine Abkürzung."])
        self.assertEqual(page["dev"], "Das GIMP-Team")

    def test_download_icon_only_without_a_file(self):
        row, _page = self.flathub_rows()[1]
        self.assertEqual(row["icons"], ["url:https://dl.flathub.org/media/vlc.png"])


class DebianCatalogTest(unittest.TestCase):
    def test_component_through_libappstream(self):
        """debian_component() with a stand-in for libappstream's objects."""
        kinds = types.SimpleNamespace(STOCK="stock", CACHED="cached", REMOTE="remote")
        AppStream = types.SimpleNamespace(IconKind=kinds, LaunchableKind=types.SimpleNamespace(DESKTOP_ID="d"),
                                          UrlKind=types.SimpleNamespace(HOMEPAGE="home"))

        def icon(kind, name=None, filename=None, url=None):
            return types.SimpleNamespace(get_kind=lambda: kind, get_name=lambda: name,
                                         get_filename=lambda: filename, get_url=lambda: url)

        image = lambda width, url: types.SimpleNamespace(get_width=lambda: width, get_url=lambda: url,
                                                         get_scale=lambda: 1)
        shot = types.SimpleNamespace(get_images_all=lambda: [image(1248, "big"), image(752, "mid"), image(224, "small")],
                                     get_caption=lambda: "Main window")
        release = types.SimpleNamespace(get_version=lambda: "3.0.4", get_timestamp=lambda: 1747440000)
        releases = types.SimpleNamespace(get_size=lambda: 1, index_safe=lambda i: release)
        component = types.SimpleNamespace(
            get_id=lambda: "org.gimp.GIMP", get_name=lambda: "GIMP", get_summary=lambda: "Edit  photos",
            get_icons=lambda: [icon("remote", url="https://appstream.debian.org/gimp.png"),
                               icon("cached", filename="/var/lib/swcatalog/icons/gimp.png"),
                               icon("stock", name="gimp")],
            get_categories=lambda: ["Graphics"], get_keywords=lambda: ["photoshop"],
            get_launchable=lambda kind: types.SimpleNamespace(get_entries=lambda: ["gimp.desktop"]),
            get_screenshots_all=lambda: [shot], get_releases_plain=lambda: releases,
            get_developer=lambda: types.SimpleNamespace(get_name=lambda: "The GIMP team"),
            get_description=lambda: "<p>GIMP is <em>free</em>.</p>", get_project_license=lambda: "GPL-3.0+",
            get_url=lambda kind: "https://www.gimp.org/", get_pkgname=lambda: "gimp",
            get_origin=lambda: "debian-trixie-main")
        row, page = fs.debian_component(AppStream, component)
        self.assertEqual(row["icons"], ["stock:gimp", "file:/var/lib/swcatalog/icons/gimp.png",
                                        "url:https://appstream.debian.org/gimp.png"])
        self.assertEqual(row["summary"], "Edit photos")
        self.assertEqual(row["pkg"], "gimp")
        self.assertEqual(page["shots"], [{"url": "mid", "caption": "Main window"}])
        self.assertEqual(page["desc"], ["GIMP is free."])
        self.assertEqual((page["version"], page["dev"]), ("3.0.4", "The GIMP team"))
        self.assertEqual(row["origin"], "debian-trixie-main")

    def test_origin_names_the_apt_source(self):
        self.assertEqual(fs.apt_source("debian-trixie-main"), "debian")
        self.assertEqual(fs.apt_source(""), "debian")
        self.assertEqual(fs.apt_source(None), "debian")
        self.assertEqual(fs.apt_source("flickos-trixie-main"), "flickos")
        self.assertEqual(fs.apt_source("flickos-trixie-community-main"), "community")
        self.assertEqual(fs.apt_source("flickos-forky-community-main"), "community")
        self.assertEqual(fs.apt_source("flickos-trixie-store-main"), "store")
        self.assertEqual(fs.apt_source("flickos-forky-store-main"), "store")


class MergeTest(Env):
    def test_one_app_per_program(self):
        apps = {app["id"]: app for app in fs.merge({"debian": [(row, 0) for row, _ in DEBIAN],
                                                    "flathub": [(row, 1) for row, _ in self.flathub_rows()]})}
        # by provides/launchable, by ID without case, by SAME_APPS
        self.assertEqual(set(apps["org.gimp.GIMP"]["src"]), {"debian", "flathub"})
        self.assertEqual(set(apps["org.videolan.vlc"]["src"]), {"debian", "flathub"})
        self.assertEqual(apps["firefox-esr.desktop"]["src"]["flathub"]["id"], "org.mozilla.firefox")
        self.assertEqual(set(apps["io.example.Only"]["src"]), {"flathub"})
        self.assertNotIn("org.videolan.VLC", apps)
        # Debian's name, and Flathub's icon file before Debian's (dead) download.
        self.assertEqual(apps["org.gimp.GIMP"]["name"], "GIMP")
        self.assertEqual(apps["org.gimp.GIMP"]["icons"], ["stock:gimp", "stock:org.gimp.GIMP",
                                                          "flathub:64x64/org.gimp.GIMP.png",
                                                          "url:https://appstream.debian.org/gimp.png"])

    def test_an_app_in_debian_and_the_community_repository(self):
        community = debian_row("org.videolan.vlc", "VLC (community)", "vlc-community", ("AudioVideo",), ["vlc.desktop"],
                               origin="flickos-trixie-community-main")[0]
        apps = fs.merge({"debian": [(row, 0) for row, _ in DEBIAN], "community": [(community, 1)],
                         "flathub": [(row, 2) for row, _ in self.flathub_rows()]})
        vlc = next(app for app in apps if app["id"] == "org.videolan.vlc")
        self.assertEqual(set(vlc["src"]), {"debian", "community", "flathub"})
        self.assertEqual(vlc["name"], "VLC")                    # Debian names it
        self.assertEqual(vlc["src"]["community"]["pkg"], "vlc-community")

    def test_sorted_by_name(self):
        apps = fs.merge({"debian": [(row, 0) for row, _ in DEBIAN], "flathub": [(row, 1) for row, _ in self.flathub_rows()]})
        names = [app["name"] for app in apps]
        self.assertEqual(names, sorted(names, key=fs.fold))


class CatalogTest(Env):
    def test_build_and_load(self):
        counts, catalog = self.built()
        self.assertEqual(counts, {"debian": 5, "store": 0, "flickos": 0, "community": 1, "flathub": 4, "apps": 7})
        self.assertEqual(set(catalog.find("tally")["src"]), {"community"})
        # flatpak as built() had it, never the build host's (CI has none).
        with mock.patch.object(fs.shutil, "which", lambda name: "/usr/bin/" + name):
            self.assertFalse(catalog.stale())
        app = catalog.find("org.gimp.GIMP")
        other = fs.Catalog()
        other.load()
        self.addCleanup(other.close)
        self.assertEqual(catalog.page(app, "debian")["desc"], ["GIMP from Debian."])
        self.assertEqual(catalog.page(app, "flathub")["version"], "3.2.6")
        # every alias finds it: Flathub ID, desktop ID, package
        for name in ("ORG.GIMP.GIMP", "gimp.desktop", "gimp", "org.gimp.GIMP.desktop"):
            self.assertIs(catalog.find(name), app, name)
        self.assertIsNone(catalog.find("nothing"))

    def test_rebuilt_index_keeps_the_open_pages(self):
        """A window keeps its pages file open while a child writes a new index."""
        _counts, catalog = self.built()
        app = catalog.find("vlc")
        with mock.patch.object(fs.shutil, "which", lambda name: "/usr/bin/" + name):
            fs.build_index(debian=iter(DEBIAN[1:]), flathub=iter(self.flathub_rows()))
            fs.build_index(debian=iter(DEBIAN[2:]), flathub=iter(self.flathub_rows()))
        self.assertEqual(catalog.page(app, "debian")["desc"], ["VLC from Debian."])
        pages = [n for n in os.listdir(os.path.join(self.cache, "flickos/software")) if n.startswith("pages-")]
        self.assertEqual(len(pages), 1)     # the open one was deleted and still reads

    def test_stale_when_a_catalog_changes(self):
        _counts, catalog = self.built()
        self.write("var/lib/swcatalog/yaml/main.yml.gz", "x")
        os.utime(os.path.join(self.root, "var/lib/swcatalog/yaml/main.yml.gz"), (2_000_000_000, 2_000_000_000))
        self.assertTrue(catalog.stale())

    def test_search_ranks_names_first(self):
        _counts, catalog = self.built()
        self.assertEqual([a["name"] for a in catalog.search(["vlc"])], ["VLC"])
        found = [a["name"] for a in catalog.search(["text", "editor"])]
        self.assertEqual(found, ["Editor", "Mousepad"])        # name before summary
        self.assertEqual([a["name"] for a in catalog.search(["EDITOR"])][:1], ["Editor"])
        self.assertEqual(catalog.search(["photoshop"])[0]["name"], "GIMP")    # Flathub's keywords too
        self.assertEqual(catalog.search([" "]), [])

    def test_categories_and_shelves(self):
        _counts, catalog = self.built()
        self.assertEqual([a["name"] for a in catalog.category("games")], ["Only On Flathub"])
        self.assertEqual([a["name"] for a in catalog.category("graphics")], ["GIMP"])
        featured = fs.parse_featured(json.dumps({"v": 1, "shelves": [
            {"id": "flickos", "name": "Made for FlickOS", "apps": ["io.example.Tally", {"id": "gimp"}, "nothing"]},
            {"id": "empty", "name": "Nothing here", "apps": ["nothing"]},
            {"id": "start", "name": "Apps to start with",
             "apps": ["org.gimp.GIMP", "gimp.desktop", "org.videolan.VLC"] + ["nothing"] * 20}]}))
        shelves = [(i, n, [a["name"] for a in apps]) for i, n, apps in catalog.shelves(featured)]
        self.assertEqual(shelves, [("flickos", "Made for FlickOS", ["Tally", "GIMP"]),
                                   ("start", "Apps to start with", ["GIMP", "VLC"])])
        many = fs.parse_featured(json.dumps({"v": 1, "shelves": [
            {"id": "a", "name": "A", "apps": [a["id"] for a in catalog.apps]}]}))
        with mock.patch.object(fs, "SHELF_APPS", 3):
            self.assertEqual(len(catalog.shelves(many)[0][2]), 3)
        counts = catalog.category_counts()
        self.assertEqual(counts, {c[0]: len(catalog.category(c[0])) for c in fs.CATEGORIES})
        with self.assertRaises(fs.SoftwareError):
            catalog.category("nope")

    def test_installed(self):
        self.write("var/lib/flatpak/app/io.example.Only/current", "")
        self.write("var/lib/flatpak/app/org.half.Gone/x86_64/stable/files", "")    # no "current": not installed
        _counts, catalog = self.built()
        self.assertEqual(catalog.flatpaks, {"io.example.Only"})
        self.assertEqual(set(catalog.packages), {"vlc", "flickos-desktop", "firefox-esr"})
        self.assertEqual(catalog.installed_from(catalog.find("vlc")), "debian")
        self.assertEqual(catalog.installed_from(catalog.find("io.example.Only")), "flathub")
        self.assertIsNone(catalog.installed_from(catalog.find("mousepad")))    # config files only
        self.assertEqual([a["name"] for a in catalog.installed()], ["Firefox ESR", "Only On Flathub", "VLC"])

    def test_protected(self):
        _counts, catalog = self.built()
        for package in ("flickos-settings", "flick-tiler", "labwc", "waybar", "sfwbar", "firefox-esr"):
            self.assertTrue(catalog.is_protected(package), package)
        self.assertFalse(catalog.is_protected("vlc"))

    def test_flickos_apps_can_be_removed(self):
        # Notes is a FlickOS package, but an app the user chose (not the desktop);
        # an app the desktop Depends on stays protected.
        rows = [debian_row("io.github.dvbondoy.flickos.Notes", "Notes", "flickos-notes", ("Office",),
                           origin="flickos-trixie-main"),
                debian_row("io.github.dvbondoy.flickos.Settings", "Settings", "flickos-settings",
                           origin="flickos-trixie-main")]
        with mock.patch.object(fs.shutil, "which", lambda name: None):
            fs.build_index(debian=iter(DEBIAN + rows), flathub=iter(()))
            catalog = fs.Catalog()
            self.assertTrue(catalog.is_protected("flickos-notes"))     # no index: not known as an app
            catalog.load()
            catalog.read_installed()
        self.addCleanup(catalog.close)
        self.assertFalse(catalog.is_protected("flickos-notes"))
        self.assertTrue(catalog.is_protected("flickos-settings"))
        self.assertTrue(catalog.is_protected("flickos-installer"))      # FlickOS's, not an app

    def test_installed_from_the_community_repository(self):
        _counts, catalog = self.built()
        tally = catalog.find("io.example.Tally")
        self.assertIsNone(catalog.installed_from(tally))
        catalog.packages["tally"] = "1.0"
        self.assertEqual(catalog.installed_from(tally), "community")
        self.assertIn(tally, catalog.installed())
        self.assertEqual(fs.choose_source(catalog, tally), "community")

    def test_source_choice(self):
        _counts, catalog = self.built()
        gimp = catalog.find("gimp")
        self.assertEqual(fs.choose_source(catalog, gimp), "debian")           # ADR-002: Debian first
        self.assertEqual(fs.choose_source(catalog, gimp, "flathub"), "flathub")
        self.assertEqual(fs.choose_source(catalog, catalog.find("io.example.Only")), "flathub")
        with self.assertRaises(fs.SoftwareError):
            fs.choose_source(catalog, catalog.find("io.example.Only"), "debian")

    def test_broken_index(self):
        os.makedirs(os.path.join(self.cache, "flickos/software"))
        self.write("cache/flickos/software/index.json", "{")
        with self.assertRaises(fs.SoftwareError):
            fs.Catalog().load()
        with self.assertRaises(fs.SoftwareError):
            fs.Catalog(os.path.join(self.root, "nowhere")).load()


PHOTOSHOP = {"id": "photoshop", "name": "Adobe Photoshop", "by": "name",
             "similar": [{"app": "org.gimp.GIMP", "why": "Edits photos."}, {"app": "gimp.desktop", "why": "Again."},
                         {"app": "org.not.Here", "why": "Not in the catalog."}, {"app": "org.videolan.VLC"}],
             "web": {"name": "Photoshop on the web", "url": "https://photoshop.example"}}
SWITCH_PACKAGE = os.path.join(os.path.dirname(PACKAGE), "flickos-switch")


class WindowsAnswerTest(Env):
    """A search's answer about a Windows program (flickos-switch lookup)."""

    def setUp(self):
        super().setUp()
        _counts, self.catalog = self.built()

    def answer(self, entries, found=()):
        return fs.windows_answer(entries, self.catalog, set(found))

    def test_similar_apps_then_the_web(self):
        sentence, rows = self.answer([PHOTOSHOP])
        self.assertEqual(sentence, "Adobe Photoshop is a Windows program and isn't made for FlickOS.")
        self.assertEqual([(kind, what if kind == "web" else what["id"], text) for kind, what, text in rows],
                         [("app", "org.gimp.GIMP", "Edits photos."),         # once, missing ones left out
                          ("app", "org.videolan.vlc", "VLC summary"),        # no why: its summary
                          ("web", "Photoshop on the web", "https://photoshop.example")])

    def test_note_and_web_address(self):
        entry = dict(PHOTOSHOP, similar=[], note="Use the web.", web={"name": "X", "url": "http://x"})
        self.assertEqual(self.answer([entry]),
                         ("Adobe Photoshop is a Windows program and isn't made for FlickOS. Use the web.", []))

    def test_group(self):
        group = {"id": "antivirus", "name": "antivirus software", "group": True, "by": "words",
                 "note": "Windows antivirus programs don't work on FlickOS."}
        self.assertEqual(self.answer([group])[0], "Windows antivirus programs don't work on FlickOS.")
        del group["note"]
        self.assertEqual(self.answer([group])[0], "Antivirus software for Windows doesn't work on FlickOS.")

    def test_linux_version_only_when_the_search_missed_it(self):
        vlc = {"id": "vlc", "name": "VLC media player", "by": "name",
               "linux": {"app": "org.videolan.VLC", "source": "flathub"}}
        sentence, rows = self.answer([vlc])
        self.assertEqual((sentence, rows[0][1]["id"]), ("VLC media player is made for FlickOS too.", "org.videolan.vlc"))
        self.assertIsNone(self.answer([vlc], found={"org.videolan.vlc"}))
        # then the next entry
        self.assertEqual(self.answer([vlc, PHOTOSHOP], found={"org.videolan.vlc"})[0][:5], "Adobe")
        missing = dict(vlc, linux={"app": "com.not.Here", "source": "flathub"})
        self.assertIsNone(self.answer([missing]))

    def test_matches_by_words_only_when_few(self):
        word = dict(PHOTOSHOP, by="words")
        self.assertIsNotNone(self.answer([word, dict(word, id="b")]))
        self.assertIsNone(self.answer([dict(word, id=str(n)) for n in range(fs.WORD_MATCHES + 1)]))
        # a match by name still shows among many by words
        many = [dict(word, id=str(n)) for n in range(5)] + [dict(PHOTOSHOP, name="Named")]
        self.assertEqual(self.answer(many)[0][:5], "Named")

    def test_nonsense_is_ignored(self):
        self.assertIsNone(self.answer([]))
        self.assertIsNone(self.answer([None, 3, {"id": "x"}, {"name": 5}]))
        sentence, rows = self.answer([dict(PHOTOSHOP, similar=[None, "x", {"app": 3}], web="x")])
        self.assertEqual(rows, [])

    @unittest.skipUnless(os.path.exists(os.path.join(SWITCH_PACKAGE, "usr/bin/flickos-switch")),
                         "flickos-switch's source isn't next to this package")
    def test_flickos_switch_lookup(self):
        """What flickos-switch's lookup --json prints is understood (its
        source tree, never the installed one)."""
        env = dict(os.environ, FLICKOS_SWITCH_PREFIX=SWITCH_PACKAGE)
        out = subprocess.run([sys.executable, os.path.join(SWITCH_PACKAGE, "usr/bin/flickos-switch"), "lookup",
                              "--json", "--", "photoshop"], env=env, capture_output=True, text=True, check=True)
        sentence, rows = self.answer(json.loads(out.stdout))
        self.assertIn("Adobe Photoshop", sentence)
        self.assertEqual([row[1]["id"] for row in rows], ["org.gimp.GIMP"])     # the fixture's only one


WHATSAPP_ID = "2610e1f6-3341-4b70-8cd2-a59d40ce0881"
KNOWN = [   # flickos-switch webapp list --json --known
    {"id": WHATSAPP_ID, "name": "WhatsApp", "start": "https://web.whatsapp.com", "hosts": ["web.whatsapp.com"],
     "icon": "/p/taskbartabs/icons/w.png", "launcher": f"firefox-esr.webapp-{WHATSAPP_ID}.desktop",
     "profile": "/p", "container": 0, "entry": "whatsapp", "windows": "WhatsApp", "made": True},
    {"id": "77", "name": "Mine", "start": "https://mine.example/start", "hosts": ["mine.example"], "icon": None,
     "launcher": None, "profile": "/p", "container": 0, "entry": None, "windows": None, "made": True},
    {"id": None, "name": "Photoshop on the web", "start": "https://photoshop.example",
     "hosts": ["photoshop.example"], "icon": None, "launcher": None, "profile": None, "container": 0,
     "entry": "photoshop", "windows": "Adobe Photoshop", "made": False},
]


class WebAppsTest(Env):
    """Web apps (flickos-switch phase 3b): rows from webapp list --known."""

    def test_rows(self):
        rows = fs.web_rows(KNOWN)
        self.assertEqual([r["id"] for r in rows], ["web:77", "web:whatsapp", "web:photoshop"])  # made first
        mine, whatsapp, photoshop = rows
        self.assertEqual(whatsapp["icons"], ["file:/p/taskbartabs/icons/w.png", "stock:web-browser"])
        self.assertEqual(whatsapp["src"], {"web": {"url": "https://web.whatsapp.com", "webapp": WHATSAPP_ID,
                                                   "launch": [f"firefox-esr.webapp-{WHATSAPP_ID}.desktop"]}})
        self.assertEqual(photoshop["icons"], ["stock:web-browser"])
        self.assertEqual(photoshop["src"]["web"]["webapp"], None)
        self.assertEqual(photoshop["summary"], "The web version of Adobe Photoshop.")
        self.assertEqual(mine["summary"], "A web app of mine.example.")
        self.assertEqual(mine["cats"], [fs.WEB_CATEGORY])

    def test_odd_rows_are_left_out(self):
        odd = [None, "x", {"name": "No start"}, {"name": "", "start": "https://a.example"},
               dict(KNOWN[2], entry=None),                     # not made and from no list entry
               dict(KNOWN[2], entry="../etc"), dict(KNOWN[1], made="yes", entry=None),
               dict(KNOWN[2], start="https://[::1"), KNOWN[2], dict(KNOWN[2], name="Again")]
        self.assertEqual([r["name"] for r in fs.web_rows(odd)], ["Photoshop on the web"])
        self.assertEqual(fs.web_rows({"not": "a list"}), [])
        relative = fs.web_rows([dict(KNOWN[0], icon="icons/w.png", launcher="w")])[0]
        self.assertEqual((relative["icons"], relative["src"]["web"]["launch"]), (["stock:web-browser"], []))

    def test_catalog_sees_them(self):
        _counts, catalog = self.built()
        catalog.prepare_search()
        indexed = len(catalog.apps)
        catalog.set_web(fs.web_rows(KNOWN))
        self.assertEqual(catalog.find("WEB:WhatsApp")["name"], "WhatsApp")
        self.assertEqual([a["id"] for a in catalog.search(["photoshop"])], ["web:photoshop", "org.gimp.GIMP"])
        self.assertEqual([a["id"] for a in catalog.search(["web", "app"])][:3],
                         ["web:77", "web:whatsapp", "web:photoshop"])
        self.assertEqual([a["id"] for a in catalog.category("web")], ["web:77", "web:whatsapp", "web:photoshop"])
        installed = [a["name"] for a in catalog.installed()]
        self.assertEqual(installed, sorted(installed, key=fs.fold))     # web apps among the others
        self.assertIn("WhatsApp", installed)
        self.assertNotIn("Photoshop on the web", installed)
        self.assertEqual(catalog.installed_from(catalog.find("web:77")), "web")
        self.assertEqual(fs.choose_source(catalog, catalog.find("web:photoshop")), "web")
        # Read again: the new rows replace the old ones; the index's stay.
        catalog.set_web(fs.web_rows(KNOWN[:1]))
        self.assertIsNone(catalog.find("web:photoshop"))
        self.assertIsNone(catalog.find("web:77"))
        self.assertEqual(len(catalog.apps), indexed + 1)
        self.assertEqual(catalog.find("vlc")["id"], "org.videolan.vlc")
        self.assertEqual([a["id"] for a in catalog.search(["photoshop"])], ["org.gimp.GIMP"])

    def test_windows_answer_offers_the_web_app(self):
        _counts, catalog = self.built()
        sentence, rows = fs.windows_answer([PHOTOSHOP], catalog, set())
        self.assertEqual(rows[-1][0], "web")                # no web apps: the browser
        catalog.set_web(fs.web_rows(KNOWN))
        sentence, rows = fs.windows_answer([PHOTOSHOP], catalog, set())
        self.assertEqual(rows[-1], ("app", catalog.find("web:photoshop"), fs.WEB_WHY))

    def test_web_address(self):
        for typed, url in (("outlook.live.com/mail/", "https://outlook.live.com/mail/"),
                           (" http://example.org ", "http://example.org"),
                           ("https://claude.ai", "https://claude.ai")):
            self.assertEqual(fs.web_address(typed), url)
        for bad in ("", "gmail", "file:///etc/passwd", "javascript:alert(1)", "-new-instance", "a b.example",
                    "https://", "https://[::1", "ftp://example.org", "https://.example"):
            self.assertIsNone(fs.web_address(bad), bad)

    @unittest.skipUnless(os.path.exists(os.path.join(SWITCH_PACKAGE, "usr/bin/flickos-switch")),
                         "flickos-switch's source isn't next to this package")
    def test_flickos_switch_known(self):
        """What flickos-switch's webapp list --json --known prints is
        understood (its source tree, a home with no Firefox)."""
        env = dict(os.environ, FLICKOS_SWITCH_PREFIX=SWITCH_PACKAGE, HOME=self.root,
                   XDG_CONFIG_HOME=os.path.join(self.root, "config"), XDG_DATA_HOME=os.path.join(self.root, "data"))
        out = subprocess.run([sys.executable, os.path.join(SWITCH_PACKAGE, "usr/bin/flickos-switch"), "webapp",
                              "list", "--json", "--known"], env=env, capture_output=True, text=True, check=True)
        rows = {r["id"]: r for r in fs.web_rows(json.loads(out.stdout))}
        self.assertEqual(rows["web:teams"]["src"]["web"], {"url": "https://teams.microsoft.com", "webapp": None,
                                                           "launch": []})
        self.assertFalse(any(r["src"]["web"]["webapp"] for r in rows.values()))


SEVEN_ID = "io.github.dvbondoy.flickos.styles.Seven"


def style_row():
    """A FlickOS style package as debian_component() makes it (ADR-006)."""
    row, page = debian_row(SEVEN_ID, "Seven", "flickos-style-seven", (fs.STYLE_CATEGORY,), [],
                           ["stock:preferences-desktop-theme"], origin="flickos-trixie-main")
    row["style"] = "seven"
    return row, page


class StyleTest(Env):
    """Styles: add-ons of the layout chooser, shown under Styles only."""

    def built_with_style(self):
        with mock.patch.object(fs.shutil, "which", lambda name: None):
            fs.build_index(debian=iter(DEBIAN + [style_row()]), flathub=iter(()))
            catalog = fs.Catalog()
            catalog.load()
            catalog.read_installed()
        self.addCleanup(catalog.close)
        return catalog

    @staticmethod
    def addon(extends, style):
        return types.SimpleNamespace(get_extends=lambda: extends, get_custom_value=lambda key: style
                                     if key == fs.STYLE_KEY else None)

    def test_style_of(self):
        self.assertEqual(fs.style_of(self.addon(["flickos-layout.desktop"], "seven")), "seven")
        self.assertIsNone(fs.style_of(self.addon(["org.gnome.Shell"], "seven")))      # another program's add-on
        self.assertIsNone(fs.style_of(self.addon(["flickos-layout.desktop"], None)))
        self.assertIsNone(fs.style_of(self.addon(["flickos-layout.desktop"], "../dark")))

    def test_community_styles_are_their_own_package(self):
        def component(origin, package):
            return types.SimpleNamespace(get_origin=lambda: origin, get_pkgname=lambda: package)
        self.assertTrue(fs.own_style(component("flickos-trixie-community-main", "nordish"), "nordish"))
        self.assertFalse(fs.own_style(component("flickos-trixie-community-main", "nordish"), "dark"))
        self.assertTrue(fs.own_style(component("flickos-trixie-main", "flickos-style-seven"), "seven"))

    def test_component_of_a_style(self):
        kinds = types.SimpleNamespace(STOCK="stock", CACHED="cached", REMOTE="remote")
        AppStream = types.SimpleNamespace(IconKind=kinds, LaunchableKind=types.SimpleNamespace(DESKTOP_ID="d"),
                                          UrlKind=types.SimpleNamespace(HOMEPAGE="home"))
        component = types.SimpleNamespace(
            get_id=lambda: SEVEN_ID, get_name=lambda: "Seven", get_summary=lambda: "Light windows",
            get_icons=lambda: [types.SimpleNamespace(get_kind=lambda: "stock",
                                                     get_name=lambda: "preferences-desktop-theme")],
            get_categories=lambda: ["Settings"], get_keywords=lambda: [], get_launchable=lambda kind: None,
            get_screenshots_all=lambda: [], get_releases_plain=lambda: None, get_developer=lambda: None,
            get_description=lambda: "", get_project_license=lambda: "GPL-3.0-or-later",
            get_url=lambda kind: "https://github.com/dvbondoy/FlickOS", get_pkgname=lambda: "flickos-style-seven",
            get_origin=lambda: "flickos-trixie-main", get_custom_value=lambda key: None)
        row, _page = fs.debian_component(AppStream, component, "seven")
        self.assertEqual((row["cats"], row["style"], row["launch"]), ([fs.STYLE_CATEGORY], "seven", []))
        self.assertNotIn("layout", row)
        component.get_custom_value = lambda key: "aye3" if key == fs.LAYOUT_KEY else None
        row, _page = fs.debian_component(AppStream, component, "seven")
        self.assertEqual(row["layout"], "aye3")

    def test_layout_of(self):
        def component(origin, layout):
            return types.SimpleNamespace(get_origin=lambda: origin,
                                         get_custom_value=lambda key: layout if key == fs.LAYOUT_KEY else None)
        self.assertEqual(fs.layout_of(component("flickos-trixie-main", "aye3")), "aye3")
        self.assertIsNone(fs.layout_of(component("flickos-trixie-main", None)))
        self.assertIsNone(fs.layout_of(component("flickos-trixie-main", "../redmond")))
        self.assertIsNone(fs.layout_of(component("flickos-trixie-community-main", "mybar")))   # layouts are code

    def test_styles_category_only(self):
        catalog = self.built_with_style()
        seven = catalog.find(SEVEN_ID)
        self.assertEqual((seven["style"], list(seven["src"])), ("seven", ["flickos"]))
        self.assertEqual(catalog.category("styles"), [seven])
        for category_id, *_ in fs.CATEGORIES[:-1]:
            self.assertNotIn(seven, catalog.category(category_id), category_id)
        self.assertEqual(catalog.category_counts()["styles"], 1)
        self.assertNotIn("style", catalog.find("vlc"))

    def test_a_styles_layout(self):
        """ADR-014: Use sets the layout a style package brings too; Try only the style."""
        row, page = style_row()
        row["layout"] = "seven-bar"
        with mock.patch.object(fs.shutil, "which", lambda name: None):
            fs.build_index(debian=iter(DEBIAN + [(row, page)]), flathub=iter(()))
            catalog = fs.Catalog()
            catalog.load()
        self.addCleanup(catalog.close)
        seven = catalog.find(SEVEN_ID)
        self.assertEqual(seven["layout"], "seven-bar")
        self.assertEqual(fs.use_args(seven, "use"), ("set", "seven-bar", "--style", "seven"))
        self.assertEqual(fs.use_args(seven, "try"), ("try", "seven"))
        self.assertEqual(fs.use_args({"style": "seven"}, "use"), ("style", "set", "seven"))

    def test_style_packages_can_be_removed(self):
        catalog = self.built_with_style()
        self.assertFalse(catalog.is_protected("flickos-style-seven"))
        for package in ("flickos-layouts", "flickos-settings", "flick-tiler"):
            self.assertTrue(catalog.is_protected(package), package)

    def test_styles_shelf(self):
        catalog = self.built_with_style()
        shelves = catalog.shelves(fs.read_featured())
        self.assertIn(("styles", "Styles for your desktop", [catalog.find(SEVEN_ID)]), shelves)

    def test_run_layout(self):
        fake = self.write("bin/flickos-layout", "#!/bin/sh\n[ \"$1\" = style ] && { echo dark; exit 0; }\n"
                                                "echo 'flickos-layout: style x is broken' >&2\n"
                                                "echo 'flickos-layout: style x can not be tried' >&2; exit 1\n")
        os.chmod(fake, 0o755)
        with mock.patch.object(fs, "LAYOUT", fake):
            self.assertEqual(fs.run_layout("style", "current"), "dark\n")
            with self.assertRaisesRegex(fs.SoftwareError, "^style x can not be tried$"):
                fs.run_layout("try", "x")


KIT_ID = "io.github.dvbondoy.flickos.kits.python"


def kit_row(name="python", title="Python", category="X-FlickOS-Development"):
    """A FlickOS kit as debian_component() makes it (flickos-dev.md, ADR-002)."""
    row, page = debian_row(f"io.github.dvbondoy.flickos.kits.{name}", title, f"flickos-kit-{name}", (category,), [],
                           ["stock:applications-development"], origin="flickos-trixie-main")
    row["kit"] = name
    return row, page


class KitTest(Env):
    """Kits: add-ons of the Tool Kits window, shown under Developer Tools only."""

    def built_with_kit(self, *extra):
        with mock.patch.object(fs.shutil, "which", lambda name: None):
            fs.build_index(debian=iter(DEBIAN + [kit_row()] + list(extra)), flathub=iter(()))
            catalog = fs.Catalog()
            catalog.load()
            catalog.read_installed()
        self.addCleanup(catalog.close)
        return catalog

    @staticmethod
    def addon(extends="flickos-kits.desktop", kit="python", category="development", package="flickos-kit-python",
              origin="flickos-trixie-main"):
        values = {fs.KIT_KEY: kit, fs.KIT_CATEGORY_KEY: category}
        return types.SimpleNamespace(get_extends=lambda: [extends], get_custom_value=values.get,
                                     get_pkgname=lambda: package, get_origin=lambda: origin)

    def test_kit_of(self):
        self.assertEqual(fs.kit_of(self.addon()), "python")
        self.assertIsNone(fs.kit_of(self.addon(extends="flickos-layout.desktop")))   # a style's, not a kit's
        self.assertIsNone(fs.kit_of(self.addon(category="gaming")))                  # a category Software doesn't know
        self.assertIsNone(fs.kit_of(self.addon(category=None)))
        self.assertIsNone(fs.kit_of(self.addon(kit="../python")))
        self.assertIsNone(fs.kit_of(self.addon(package="other")))                    # the package is flickos-kit-NAME
        self.assertIsNone(fs.kit_of(self.addon(origin="flickos-trixie-community-main")))   # kits are FlickOS's own

    def test_component_of_a_kit(self):
        kinds = types.SimpleNamespace(STOCK="stock", CACHED="cached", REMOTE="remote")
        AppStream = types.SimpleNamespace(IconKind=kinds, LaunchableKind=types.SimpleNamespace(DESKTOP_ID="d"),
                                          UrlKind=types.SimpleNamespace(HOMEPAGE="home"))
        component = types.SimpleNamespace(
            get_id=lambda: KIT_ID, get_name=lambda: "Python", get_summary=lambda: "pip and pipx",
            get_icons=lambda: [], get_categories=lambda: [], get_keywords=lambda: [], get_launchable=lambda kind: None,
            get_screenshots_all=lambda: [], get_releases_plain=lambda: None, get_developer=lambda: None,
            get_description=lambda: "", get_project_license=lambda: "GPL-3.0-or-later",
            get_url=lambda kind: "https://flickos.org/", get_pkgname=lambda: "flickos-kit-python",
            get_origin=lambda: "flickos-trixie-main",
            get_custom_value=lambda key: "development" if key == fs.KIT_CATEGORY_KEY else None)
        row, _page = fs.debian_component(AppStream, component, None, "python")
        self.assertEqual((row["cats"], row["kit"], row["launch"]), (["X-FlickOS-Development"], "python", []))
        self.assertNotIn("style", row)

    def test_developer_tools_category_only(self):
        catalog = self.built_with_kit()
        python = catalog.find(KIT_ID)
        self.assertEqual((python["kit"], list(python["src"])), ("python", ["flickos"]))
        self.assertEqual(catalog.category("developer-tools"), [python])
        for category_id, *_ in fs.CATEGORIES:
            if category_id != "developer-tools":
                self.assertNotIn(python, catalog.category(category_id), category_id)
        self.assertEqual(catalog.category_counts()["developer-tools"], 1)
        self.assertNotIn("kit", catalog.find("vlc"))

    def test_classroom_kit_is_under_education(self):
        """Q15: a kit of the "classroom" category shows under Education, not Developer Tools."""
        self.assertEqual(fs.kit_of(self.addon(kit="classroom", category="classroom", package="flickos-kit-classroom")),
                         "classroom")
        catalog = self.built_with_kit(kit_row("classroom", "Classroom", "X-FlickOS-Classroom"))
        classroom = catalog.find("io.github.dvbondoy.flickos.kits.classroom")
        self.assertEqual(classroom["kit"], "classroom")
        self.assertIn(classroom, catalog.category("education"))
        self.assertNotIn(classroom, catalog.category("developer-tools"))
        self.assertEqual(catalog.category_counts()["developer-tools"], 1)

    def test_security_kits_are_under_security_tools(self):
        """flickos-security.md ADR-S01: a kit of the "security" category shows under Security Tools only."""
        self.assertEqual(fs.kit_of(self.addon(kit="network", category="security", package="flickos-kit-network")),
                         "network")
        catalog = self.built_with_kit(kit_row("network", "Network Analysis", "X-FlickOS-Security"))
        network = catalog.find("io.github.dvbondoy.flickos.kits.network")
        self.assertEqual(network["kit"], "network")
        self.assertEqual(catalog.category("security-tools"), [network])
        for category_id, *_ in fs.CATEGORIES:
            if category_id != "security-tools":
                self.assertNotIn(network, catalog.category(category_id), category_id)
        self.assertEqual(catalog.category_counts()["developer-tools"], 1)

    def test_permission_sentence(self):
        """ADR-S05: the same sentence on Security Tools and on each security kit's page, nowhere else."""
        self.assertEqual(fs.CATEGORY_NOTES, {"security-tools": fs.PERMISSION})
        catalog = self.built_with_kit(kit_row("network", "Network Analysis", "X-FlickOS-Security"))
        self.assertEqual(fs.kit_note(catalog.find("io.github.dvbondoy.flickos.kits.network")), fs.PERMISSION)
        self.assertIsNone(fs.kit_note(catalog.find(KIT_ID)))
        self.assertIsNone(fs.kit_note(catalog.find("vlc")))
        out = io.StringIO()
        with mock.patch.object(fs.shutil, "which", lambda name: None), contextlib.redirect_stdout(out):
            self.assertEqual(fs.main(["info", "io.github.dvbondoy.flickos.kits.network"]), 0)
        self.assertIn(f"note\t{fs.PERMISSION}\n", out.getvalue())

    def test_no_security_shelf(self):
        """ADR-S01: no shelf of the front page names a security kit."""
        security = {f"io.github.dvbondoy.flickos.kits.{name}"
                    for name in ("network", "web-testing", "passwords", "forensics", "reversing", "wireless")}
        for shelf in fs.read_featured():
            self.assertFalse({app["id"] for app in shelf["apps"]} & security, shelf["id"])

    def test_kit_packages_can_be_removed(self):
        catalog = self.built_with_kit()
        self.assertFalse(catalog.is_protected("flickos-kit-python"))
        for package in ("flickos-layouts", "flickos-kits", "flickos-settings"):
            self.assertTrue(catalog.is_protected(package), package)

    def test_set_up_opens_the_tool_kits_window_on_the_kit(self):
        self.assertEqual(fs.kit_setup_argv({"kit": "python"}), ["flickos-kits", "window", "--kit", "python"])

    def test_kits_shelf(self):
        catalog = self.built_with_kit()
        shelves = catalog.shelves(fs.read_featured())
        self.assertIn(("kits", "Tools for developers", [catalog.find(KIT_ID)]), shelves)


class CommandTest(Env):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fs.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_search_and_list(self):
        self.built()
        with mock.patch.object(fs.shutil, "which", lambda name: "/usr/bin/" + name):
            code, out, _err = self.run_main("search", "vlc")
            self.assertEqual((code, out), (0, "org.videolan.vlc\tdebian,flathub\tdebian\tVLC\tVLC summary\n"))
            code, out, _err = self.run_main("list")
            self.assertIn("games\tGames\t1\n", out)
            code, out, _err = self.run_main("list", "--installed")
            self.assertEqual([line.split("\t")[0] for line in out.splitlines()],
                             ["firefox-esr.desktop", "org.videolan.vlc"])
            code, out, _err = self.run_main("info", "gimp")
            self.assertIn("source\tdebian\n", out)
            self.assertIn("package\tgimp\n", out)
            code, out, _err = self.run_main("info", "tally")
            self.assertIn("source\tcommunity\n", out)
            self.assertIn("package\ttally\n", out)
            code, out, _err = self.run_main("list", "--shelves")
            self.assertEqual(code, 0)
            self.assertIn("start\torg.gimp.GIMP\tGIMP\n", out)      # the package's copy
            code, _out, err = self.run_main("info", "nothing")
            self.assertEqual(code, 1)
            self.assertTrue(err.startswith("flickos-software: no app nothing"))

    def test_no_command_is_show(self):
        with mock.patch.object(fs, "cmd_show", return_value=0) as show:
            self.assertEqual(fs.main(["--search", "gimp"]), 0)
            self.assertEqual(show.call_args[0][0].search, "gimp")
            fs.main([])
            self.assertIsNone(show.call_args[0][0].search)

    def test_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            fs.main(["list", "--category", "nope"])
        self.assertEqual(caught.exception.code, 2)

    def test_docstring_lists_every_command(self):
        """HIG CODE-2: the docstring is the manual."""
        for command in ("show", "search", "list", "info", "index", "refresh", "plan", "install", "remove", "paid"):
            self.assertRegex(fs.__doc__, rf"\n  (\(none\), )?{command}\b", command)

    def test_change_output_is_json_lines(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            output = fs.Output(True)
            output.emit("progress", status="download", percent=5, cancel=True)
            output.emit("progress", status="download", percent=5, cancel=True)    # the same again: once
            output.emit("done")
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(lines, [{"event": "progress", "status": "download", "percent": 5, "cancel": True},
                                 {"event": "done"}])

    def test_fetch_needed(self):
        with mock.patch.object(fs.shutil, "which", lambda name: "/usr/bin/" + name):
            self.assertEqual(fs.fetch_needed(), ["debian"])           # no Flathub remote: never Flathub
            self.flathub()
            self.write("var/lib/swcatalog/yaml/main.yml.gz", "x")
            self.assertEqual(fs.fetch_needed(), [])
            old = 1_000_000_000
            os.utime(os.path.join(self.root, "var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz"),
                     (old, old))
            self.assertEqual(fs.fetch_needed(), ["flathub"])
        with mock.patch.object(fs.shutil, "which", lambda name: None):
            self.assertEqual(fs.fetch_needed(), [])                   # flatpak not installed


class Server(http.server.BaseHTTPRequestHandler):
    """Serves Server.body at every address (featured.json's fetch)."""
    body = b""
    requests = []

    def do_GET(self):
        Server.requests.append((self.path, dict(self.headers)))
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args):
        pass


class FeaturedTest(Env):
    def setUp(self):
        super().setUp()
        self.package_copy = self.write("usr/share/flickos/software/featured.json", json.dumps(
            {"v": 1, "shelves": [{"id": "start", "name": "From the package", "apps": ["gimp"]}]}))
        patcher = mock.patch.object(fs, "FEATURED_FILE", self.package_copy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_parse(self):
        shelves = fs.parse_featured('{"v": 1, "shelves": [{"id": "a", "name": " Made  for FlickOS ", '
                                    '"apps": ["x", {"id": "y", "price": "$12"}, {"price": 1}, 7, ""]}], "later": 1}')
        self.assertEqual(shelves, [{"id": "a", "name": "Made for FlickOS",
                                    "apps": [{"id": "x"}, {"id": "y", "price": "$12"}]}])
        for broken in ("{", "[]", '{"v": 2, "shelves": []}', '{"v": 1}', '{"v": 1, "shelves": [{"id": "a"}]}',
                       '{"v": 1, "shelves": [{"id": "a", "name": "A", "apps": "x"}]}'):
            with self.subTest(broken), self.assertRaises(ValueError):
                fs.parse_featured(broken)

    def test_the_fetched_copy_wins_and_a_broken_one_is_left_out(self):
        self.assertEqual(fs.read_featured()[0]["name"], "From the package")
        self.write("cache/flickos/software/featured.json",
                   '{"v": 1, "shelves": [{"id": "start", "name": "Fetched", "apps": []}]}')
        self.assertEqual(fs.read_featured()[0]["name"], "Fetched")
        self.write("cache/flickos/software/featured.json", '{"v": 99}')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fs.read_featured()[0]["name"], "From the package")
        self.assertIn("left out", err.getvalue())
        os.unlink(self.package_copy)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fs.read_featured(), [])

    def test_fetch(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/v1/featured.json"
        Server.requests.clear()
        self.assertTrue(fs.featured_stale())
        Server.body = b'{"v": 1, "shelves": [{"id": "flickos", "name": "Made for FlickOS", "apps": ["tally"]}]}'
        self.assertTrue(fs.fetch_featured(url=url))
        self.assertFalse(fs.featured_stale())
        self.assertEqual(fs.read_featured()[0]["apps"], [{"id": "tally"}])
        self.assertFalse(fs.fetch_featured(url=url))            # the same: not changed
        # ADR-009: nothing about the user, not even a query.
        self.assertEqual({path for path, _headers in Server.requests}, {"/v1/featured.json"})
        self.assertEqual(Server.requests[0][1]["User-Agent"], "FlickOS-Software")
        Server.body = b'{"v": 2}'
        with self.assertRaises(ValueError):
            fs.fetch_featured(url=url)
        self.assertEqual(fs.read_featured()[0]["apps"], [{"id": "tally"}])    # the old one stays
        Server.body = b"x" * (fs.FEATURED_BYTES + 1)
        with self.assertRaises(ValueError):
            fs.fetch_featured(url=url)


PAID = {"io.example.Tally": {"price": " $5 ", "buy": "https://tally.example/buy"},
        "gimp": {"price": "$12", "buy": "https://flickos.org/apps/buy?product=gimp", "product": "gimp"}}


class PaidTest(Env):
    """Phase 3a: prices from featured.json, and the setting that hides them."""

    def featured(self, paid):
        return json.dumps({"v": 1, "shelves": [{"id": "flickos", "name": "Made for FlickOS",
                                                "apps": ["io.example.Tally", "gimp", "vlc"]}], "paid": paid})

    def test_parse_leaves_out_odd_entries(self):
        odd = {"a": {"buy": "https://x.example/"}, "b": {"price": "$1", "buy": "http://x.example/"},
               "c": {"price": "$1", "buy": "https:///nohost"}, "d": {"price": "$1", "buy": "https://x.example/ a"},
               "e": {"price": "$1", "buy": "https://x.example/", "product": "Not Ours"},
               "f": {"price": "x" * (fs.PRICE_CHARS + 1), "buy": "https://x.example/"}, "g": "$1"}
        with contextlib.redirect_stderr(io.StringIO()) as err:
            paid = fs.parse_paid(self.featured(dict(PAID, **odd)))
        self.assertEqual(paid, {"io.example.Tally": {"price": "$5", "buy": "https://tally.example/buy", "product": None},
                                "gimp": dict(PAID["gimp"])})
        self.assertEqual(err.getvalue().count("left out"), len(odd))
        self.assertEqual(fs.parse_paid(self.featured({})), {})
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fs.parse_paid(self.featured([1])), {})
        # The shelves still read when the prices are odd.
        self.assertEqual(len(fs.parse_featured(self.featured([1]))), 1)

    def test_package_copy_has_no_price(self):
        """Nothing changes for anyone until a deploy adds a paid entry."""
        with open(os.path.join(PACKAGE, "usr/share/flickos/software/featured.json")) as f:
            self.assertEqual(fs.parse_paid(f.read()), {})

    def test_prices_attach_and_the_setting_hides(self):
        _counts, catalog = self.built()
        catalog.prepare_search()
        catalog.set_paid(fs.parse_paid(self.featured(PAID)))
        tally, gimp, vlc = (catalog.find(name) for name in ("tally", "gimp", "vlc"))
        self.assertEqual(tally["paid"]["price"], "$5")
        self.assertFalse(catalog.locked(tally))            # another developer's: Install and Buy…
        self.assertTrue(catalog.locked(gimp))               # the store's: Buy… until bought
        catalog.bought = frozenset({"gimp"})
        self.assertFalse(catalog.locked(gimp))
        catalog.bought = frozenset()
        shelf = lambda: [a["name"] for a in catalog.shelves(catalog.featured or fs.parse_featured(
            self.featured(PAID)))[0][2]]
        self.assertEqual(shelf(), ["Tally", "GIMP", "VLC"])
        catalog.show_paid = False
        self.assertEqual(shelf(), ["VLC"])
        self.assertEqual(catalog.search(["tally"]), [])
        self.assertEqual(catalog.category("graphics"), [])
        self.assertEqual(catalog.category_counts()["graphics"], 0)
        self.assertIs(catalog.find("tally"), tally)         # its page still opens from a link
        catalog.packages["gimp"] = "3.0"                    # installed: shows again
        self.assertEqual([a["name"] for a in catalog.category("graphics")], ["GIMP"])
        del catalog.packages["gimp"]
        catalog.bought = frozenset({"gimp"})                # bought: shows again
        self.assertEqual(shelf(), ["GIMP", "VLC"])
        # New prices replace the old ones; no price, no Paid.
        catalog.set_paid({})
        self.assertNotIn("paid", tally)
        self.assertEqual(catalog.search(["tally"]), [tally])

    def test_setting_files_and_history(self):
        self.assertEqual(fs.paid_setting(), ("on", False))
        self.write("etc/xdg/flickos/software.conf", "[Software]\nPaid=off\n")
        self.assertEqual(fs.paid_setting(), ("off", False))
        self.assertEqual(fs.set_paid("on"), "on")
        self.assertEqual(fs.paid_setting(), ("on", True))
        with open(os.path.join(self.root, "config/flickos/software")) as f:
            self.assertIn("Paid=on", f.read())
        self.assertEqual(fs.set_paid("default"), "off")
        self.assertFalse(os.path.exists(os.path.join(self.root, "config/flickos/software")))
        self.assertEqual(fs.set_paid("off"), "off")         # the same as before: not recorded
        self.write("config/flickos/software", "[Software]\nPaid=maybe\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fs.paid_setting(), ("off", False))
        self.assertIn("left out", err.getvalue())
        with self.assertRaises(fs.SoftwareError):
            fs.set_paid("maybe")
        with open(os.path.join(self.root, "state/flickos/history.jsonl")) as f:
            entries = [json.loads(line) for line in f]
        self.assertEqual([(e["owner"], e["key"], e["old"], e["new"]) for e in entries],
                         [("flickos-software", "paid", "off", "on"), ("flickos-software", "paid", "on", "default")])
        self.write("etc/xdg/flickos/history.conf", "[History]\nEnabled=no\n")
        os.unlink(os.path.join(self.root, "config/flickos/software"))
        fs.set_paid("on")
        with open(os.path.join(self.root, "state/flickos/history.jsonl")) as f:
            self.assertEqual(len(f.readlines()), 2)

    def test_commands(self):
        self.built()
        featured = self.write("cache/flickos/software/featured.json", self.featured(PAID))
        os.utime(featured)
        run = CommandTest.run_main
        with mock.patch.object(fs.shutil, "which", lambda name: "/usr/bin/" + name):
            self.assertEqual(run(self, "paid", "current")[:2], (0, "on\n"))
            code, out, _err = run(self, "info", "gimp")
            self.assertIn("price\t$12\nbuy\thttps://flickos.org/apps/buy?product=gimp\nproduct\tgimp\n", out)
            self.assertIn("Tally", run(self, "search", "tally")[1])
            self.assertEqual(run(self, "paid", "set", "off")[0], 0)
            self.assertEqual(run(self, "paid", "current")[1], "off\n")
            self.assertEqual(run(self, "search", "tally")[1], "")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fs.main(["paid", "set", "maybe"])

    def test_conffile(self):
        with open(os.path.join(PACKAGE, "etc/xdg/flickos/software.conf")) as f:
            text = f.read()
        self.assertIn(f"[{fs.SECTION}]", text)
        self.assertRegex(text, rf"\n{fs.PAID_NAME}={fs.PAID_DEFAULT}\n")
        self.assertEqual(fs.read_choice(os.path.join(PACKAGE, "etc/xdg/flickos/software.conf")), fs.PAID_DEFAULT)

    def test_paid_words(self):
        self.assertIn("checkout", fs.paid_words({"price": "$12", "buy": "https://x.example/", "product": "notes"}))
        self.assertIn("a key from the developer", fs.paid_words({"price": "$5", "buy": "https://x.example/",
                                                                 "product": None}))


class PackageTest(unittest.TestCase):
    def test_featured_json(self):
        """The package's copy, which the store's Worker also serves."""
        with open(os.path.join(PACKAGE, "usr/share/flickos/software/featured.json")) as f:
            shelves = fs.parse_featured(f.read())
        ids = [shelf["id"] for shelf in shelves]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "flickos")                     # Made for FlickOS (design ADR-004)
        for shelf in shelves:
            self.assertLessEqual(len(shelf["apps"]), fs.SHELF_APPS, shelf["id"])

    def test_sources(self):
        self.assertEqual(set(fs.SOURCES) | {fs.WEB}, set(fs.SOURCE_NAMES))
        self.assertEqual(fs.SOURCES[-1], "flathub")            # ADR-002: the apt sources first
        self.assertEqual(fs.APT_SOURCES, fs.SOURCES[:-1])

    def test_desktop_file(self):
        """HIG INT-1 and WIN-4: standard keys, the window's title is its Name."""
        with open(os.path.join(PACKAGE, "usr/share/applications/flickos-software.desktop")) as f:
            text = f.read()
        for key in ("Type=Application", f"Name={fs.TITLE}", "Exec=flickos-software", f"Icon={fs.ICON}",
                    "Categories=", "Comment=", "Keywords="):
            self.assertIn(key, text)

    def test_icons_target_exists(self):
        """The apt setting turns on a target the appstream package defines."""
        with open(os.path.join(PACKAGE, "etc/apt/apt.conf.d/50flickos-software")) as f:
            target = re.search(r"IndexTargets::deb::([\w-]+)::DefaultEnabled", f.read()).group(1)
        shipped = "/etc/apt/apt.conf.d/50appstream"
        if not os.path.exists(shipped):
            self.skipTest("appstream is not installed here")
        with open(shipped) as f:
            self.assertRegex(f.read(), rf"deb::{target}\s*{{")
        self.assertLess("50appstream", "50flickos-software")    # read after it

    def test_update_script(self):
        script = os.path.join(PACKAGE, "usr/libexec/flickos/software-update")
        subprocess.run(["sh", "-n", script], check=True)
        with open(script) as f:
            text = f.read()
        # flickos-control's Updates page writes these two
        self.assertIn("APT::Periodic::Update-Package-Lists", text)
        self.assertIn("APT::Periodic::Unattended-Upgrade", text)
        with open(os.path.join(PACKAGE, "debian/flickos-software.flickos-software-update.service")) as f:
            self.assertIn("ConditionKernelCommandLine=!boot=live", f.read())

    def test_categories(self):
        ids = [c[0] for c in fs.CATEGORIES]
        self.assertEqual(len(ids), len(set(ids)))



# The store's catalog (phase 3b): repo/conf/dep11.py's output for a store app.
STORE_YAML = """---
File: DEP-11
Version: '1.0'
Origin: flickos-trixie-store-main
---
Type: desktop-application
ID: io.github.dvbondoy.flickos.Notes
Package: flickos-notes
Name:
  C: Notes
Summary:
  C: Notes and checklists in plain Markdown files
Description:
  C: <p>Write notes and checklists.</p>
Icon:
  stock: accessories-notes
Categories:
- Office
---
Type: addon
ID: io.example.addon
Package: flickos-notes
Name:
  C: Not an app
Summary:
  C: Left out
"""


def notes_row(origin, summary):
    return debian_row("io.github.dvbondoy.flickos.Notes", "Notes", "flickos-notes", ("Office",),
                      ["io.github.dvbondoy.flickos.Notes.desktop"], summary=summary, origin=origin)


NOTES_PAID = {"io.github.dvbondoy.flickos.Notes": {"price": "$12", "buy": "https://flickos.org/apps/buy?product=notes",
                                                   "product": "notes"}}


class StoreEnv(Env):
    """Env with a release name, and an index with store rows (no tests of its own)."""

    def setUp(self):
        super().setUp()
        self.write("usr/lib/flickos-release", 'FLICKOS_NAME="FlickOS"\nFLICKOS_DEBIAN="trixie"\n')

    def serve(self, body):
        Server.body = body
        Server.requests.clear()
        server = http.server.HTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}/v1/catalog/{{release}}/Components-amd64.yml.gz"

    def store_built(self, rows):
        with mock.patch.object(fs.shutil, "which", lambda name: "/usr/bin/" + name):
            fs.build_index(debian=iter(DEBIAN + rows), flathub=iter(()))
            catalog = fs.Catalog()
            catalog.load()
            catalog.read_installed()
        self.addCleanup(catalog.close)
        catalog.prepare_search()
        return catalog


class StoreTest(StoreEnv):
    """Phase 3b: the store's catalog, its apps, and Notes sold over its free version."""

    def test_fetch(self):
        url = self.serve(gzip.compress(STORE_YAML.encode()))
        folder = os.path.join(self.cache, "flickos/software")
        with mock.patch.object(fs, "STORE_CATALOG_URL", url):
            self.assertTrue(fs.store_catalog_stale())
            self.assertTrue(fs.fetch_store_catalog())
            path = os.path.join(folder, fs.STORE_CATALOG)
            with open(path, "rb") as f:
                self.assertEqual(gzip.decompress(f.read()).decode(), STORE_YAML)
            self.assertFalse(fs.store_catalog_stale())
            # The release's address, nothing about the user (ADR-009).
            self.assertEqual(Server.requests[0][0], "/v1/catalog/trixie/Components-amd64.yml.gz")
            self.assertEqual(Server.requests[0][1]["User-Agent"], "FlickOS-Software")
            # The same file again: not rewritten, so the index's stamp stays.
            stamp = fs.stamps()["store"]
            os.utime(path, (1, 1))
            self.assertFalse(fs.fetch_store_catalog())
            self.assertEqual(os.stat(path).st_mtime, 1)
            self.assertNotEqual(fs.stamps()["store"], stamp)        # (the test's utime)
            # Only a store's DEP-11 file replaces it.
            for body in (b"not gzip", gzip.compress(STORE_YAML.replace("-store-", "-community-").encode()),
                         gzip.compress(b"<components/>"), gzip.compress(b"x" * (fs.STORE_CATALOG_BYTES + 1))):
                Server.body = body
                with self.assertRaises(ValueError):
                    fs.fetch_store_catalog()
            self.assertEqual(os.stat(path).st_mtime, 1)
        # No release known: nothing asked.
        os.unlink(os.path.join(self.root, "usr/lib/flickos-release"))
        with self.assertRaises(ValueError):
            fs.fetch_store_catalog()
        self.write("etc/os-release", 'ID=debian\nVERSION_CODENAME=forky\n')
        self.assertEqual(fs.flickos_release(), "forky")

    def test_fetch_shop_only_when_old(self):
        with mock.patch.object(fs, "fetch_featured", return_value=True) as featured, \
                mock.patch.object(fs, "fetch_store_catalog", side_effect=OSError("503")) as store, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fs.fetch_shop(), {"featured": True, "store": False})
            self.assertIn("The FlickOS Store's apps weren't updated: 503", err.getvalue())
            self.write("cache/flickos/software/featured.json", "{}")
            self.write("cache/flickos/software/" + fs.STORE_CHECKED, "")
            self.assertEqual(fs.fetch_shop(), {"featured": False, "store": False})
            self.assertEqual((featured.call_count, store.call_count), (1, 1))
            fs.fetch_shop(force=True)
            self.assertEqual((featured.call_count, store.call_count), (2, 2))

    @unittest.skipUnless(importlib.util.find_spec("gi"), "no PyGObject")
    def test_libappstream_reads_the_fetched_file(self):
        import gi
        try:
            gi.require_version("AppStream", "1.0")
            from gi.repository import AppStream
        except (ValueError, ImportError):
            self.skipTest("no libappstream")
        self.assertEqual(fs.store_components(AppStream), [])            # nothing fetched yet
        self.write("cache/flickos/software/" + fs.STORE_CATALOG, gzip.compress(STORE_YAML.encode()), "wb")
        components = fs.store_components(AppStream)
        self.assertEqual([(c.get_id(), c.get_origin(), c.get_pkgname()) for c in components],
                         [("io.github.dvbondoy.flickos.Notes", "flickos-trixie-store-main", "flickos-notes")])
        row, page = fs.debian_component(AppStream, components[0])
        self.assertEqual((row["icons"], row["cats"]), (["stock:accessories-notes"], ["Office"]))
        self.assertEqual(fs.apt_source(row["origin"]), "store")
        self.assertEqual(page["desc"], ["Write notes and checklists."])
        self.write("cache/flickos/software/" + fs.STORE_CATALOG, b"broken", "wb")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fs.store_components(AppStream), [])
        self.assertIn("left out", err.getvalue())

    def test_stamp(self):
        before = fs.stamps()
        self.write("cache/flickos/software/" + fs.STORE_CATALOG, b"x", "wb")
        self.assertNotEqual(fs.stamps(), before)

    def test_notes_over_its_free_version(self):
        store = notes_row("flickos-trixie-store-main", "From the store")
        free = notes_row("flickos-trixie-main", "Free of charge")
        catalog = self.store_built([free, store])
        notes = catalog.find("flickos-notes")
        self.assertEqual(set(notes["src"]), {"store", "flickos"})
        self.assertEqual(notes["summary"], "From the store")           # the store names it
        # No price: the free version only, as before the store.
        self.assertEqual(catalog.sources(notes), ["flickos"])
        self.assertEqual(fs.choose_source(catalog, notes), "flickos")
        self.assertFalse(catalog.hidden(notes))
        # On sale, not installed: the store only (Q12), Buy….
        catalog.set_paid(NOTES_PAID)
        self.assertEqual(catalog.sources(notes), ["store"])
        self.assertEqual(fs.choose_source(catalog, notes), "store")
        self.assertTrue(catalog.locked(notes))
        # The free version installed: it stays (Open, Remove), the store's page and Buy… for the newer one.
        catalog.packages["flickos-notes"] = "0.4"
        self.assertEqual(catalog.installed_from(notes), "flickos")
        self.assertEqual(catalog.sources(notes), ["store", "flickos"])
        self.assertEqual(fs.choose_source(catalog, notes), "store")
        # Bought (phase 3c): installed from the store.
        catalog.bought = frozenset({"notes"})
        self.assertEqual(catalog.installed_from(notes), "store")
        self.assertFalse(catalog.locked(notes))

    def test_a_store_app_without_a_price_is_left_out(self):
        catalog = self.store_built([notes_row("flickos-trixie-store-main", "From the store")])
        notes = catalog.find("io.github.dvbondoy.flickos.Notes")
        self.assertEqual(catalog.sources(notes), [])
        self.assertTrue(catalog.hidden(notes))
        self.assertEqual(catalog.search(["notes"]), [])
        self.assertNotIn(notes, catalog.category("office"))
        catalog.set_paid(NOTES_PAID)
        self.assertEqual(catalog.search(["notes"]), [notes])
        self.assertEqual(fs.choose_source(catalog, notes), "store")
        catalog.set_paid({})
        catalog.packages["flickos-notes"] = "1.0"           # bought and installed, the price gone: still shown
        self.assertEqual(catalog.installed_from(notes), "store")
        self.assertFalse(catalog.hidden(notes))

    def test_install_refused_until_bought(self):
        self.store_built([notes_row("flickos-trixie-store-main", "From the store")])
        featured = self.write("cache/flickos/software/featured.json", json.dumps(
            {"v": 1, "shelves": [], "paid": NOTES_PAID}))
        os.utime(featured)
        code, out, err = CommandTest.run_main(self, "install", "--json", "io.github.dvbondoy.flickos.Notes")
        self.assertEqual(code, 1)
        self.assertIn("sold in the FlickOS Store: buy it first", out)
        code, out, _err = CommandTest.run_main(self, "info", "flickos-notes")
        self.assertIn("sources\tstore\nsource\tstore\n", out)


CONTROL_PROGRAM = os.path.join(os.path.dirname(PACKAGE), "flickos-control", "usr/bin/flickos-control")
KEY = "abcd-efgh-ijkl-mnop-qrst-uvwx-yz23-4567-abcd-efgh-ijkl-mnop-qrst"


class BoughtTest(StoreEnv):
    """Phase 3c: what the key bought (flickos-control's purchases file), Add Key… and Buy…'s claim."""

    def purchases(self, status="valid", products=("notes",)):
        self.write("var/lib/flickos-control/purchases.json", json.dumps(
            {"v": 1, "key": "qrst", "status": status, "products": list(products), "packages": [],
             "checked": "2026-11-09T10:00:00+08:00"}))

    def test_read_purchases(self):
        self.assertEqual(fs.read_purchases(), (frozenset(), False))         # no key
        self.purchases(products=("notes", "phone-screen", "Bad Name", 7))
        self.assertEqual(fs.read_purchases(), (frozenset({"notes", "phone-screen"}), False))
        self.purchases(status="revoked", products=())
        self.assertEqual(fs.read_purchases(), (frozenset(), True))
        for text in ("{", "[]", '{"v": 2, "status": "valid", "products": ["notes"]}',
                     '{"v": 1, "status": "valid", "products": "notes"}'):
            self.write("var/lib/flickos-control/purchases.json", text)
            self.assertEqual(fs.read_purchases(), (frozenset(), False), text)

    def test_key_shape_is_flickos_controls(self):
        for text in (KEY, KEY.upper(), KEY.replace("-", " "), KEY[:-1], KEY.replace("a", "8"), "x" * 52, ""):
            self.assertEqual(fs.key_shaped(text), text.strip() not in (KEY[:-1], KEY.replace("a", "8"), ""), text)
        if not os.path.exists(CONTROL_PROGRAM):
            self.skipTest("flickos-control is not next to this package")
        loader = importlib.machinery.SourceFileLoader("flickos_control_for_software", CONTROL_PROGRAM)
        fc = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(fc)
        for text in (KEY, KEY.upper(), KEY.replace("-", " "), KEY[:-1], KEY.replace("a", "8"), "x" * 52, ""):
            self.assertEqual(fs.key_shaped(text), fc.normal_key(text) is not None, text)
        self.assertEqual(fc.PURCHASES_FILE, "/var/lib/flickos-control/purchases.json")
        with open(os.path.join(PACKAGE, "usr/bin/flickos-software")) as f:
            self.assertIn('PURCHASES_FILE = PREFIX + "/var/lib/flickos-control/purchases.json"', f.read())

    def test_claim_address_and_live(self):
        code = "c" * 32
        self.assertEqual(fs.claim_address("https://flickos.org/apps/buy?product=notes", code),
                         "https://flickos.org/apps/buy?product=notes#claim=" + code)
        self.assertEqual(fs.claim_address("https://x.example/buy#old", code), "https://x.example/buy#claim=" + code)
        self.assertFalse(fs.live_session())
        self.write("proc/cmdline", "BOOT_IMAGE=/live/vmlinuz boot=live components quiet\n")
        self.assertTrue(fs.live_session())

    def test_a_bought_app_installs_from_the_store(self):
        catalog = self.store_built([notes_row("flickos-trixie-store-main", "From the store")])
        catalog.set_paid(NOTES_PAID)
        notes = catalog.find("flickos-notes")
        self.assertTrue(catalog.locked(notes))
        self.purchases()
        catalog.read_installed()
        self.assertEqual(catalog.bought, frozenset({"notes"}))
        self.assertFalse(catalog.locked(notes))
        self.assertEqual(fs.choose_source(catalog, notes), "store")
        # `install` goes ahead from the store's apt source.
        featured = self.write("cache/flickos/software/featured.json", json.dumps(
            {"v": 1, "shelves": [], "paid": NOTES_PAID}))
        os.utime(featured)
        with mock.patch.object(fs, "apt_change") as change:
            code, _out, _err = CommandTest.run_main(self, "install", "--json", "flickos-notes")
        self.assertEqual(code, 0)
        self.assertEqual(change.call_args.args[-1], "store")

    def test_page_words(self):
        paid = NOTES_PAID["io.github.dvbondoy.flickos.Notes"]
        catalog = types.SimpleNamespace(bought=frozenset(), key_off=False)
        self.assertIn("Add Key… adds its key", fs.paid_words(paid, catalog))
        self.assertIn("after installing FlickOS", fs.paid_words(paid, catalog, live=True))
        self.assertNotIn("Add Key…", fs.paid_words(paid, catalog, live=True))
        catalog.key_off = True
        self.assertIn("was turned off", fs.paid_words(paid, catalog))
        catalog.bought = frozenset({"notes"})
        self.assertTrue(fs.paid_words(paid, catalog).startswith("Bought ($12)."))
        other = {"price": "$5", "buy": "https://x.example/", "product": None}
        self.assertIn("a key from the developer", fs.paid_words(other, catalog))

    def test_output_lines(self):
        self.assertEqual(fs.output_lines("Waiting for your payment…\nBought with this key: Notes.\n",
                                         "flickos-control: This key isn't valid.\ncontrol-helper: x\n"),
                         ["Waiting for your payment…", "Bought with this key: Notes.", "This key isn't valid.", "x"])


# --- Files from outside (ADR-012) ----------------------------------------------------

BUNDLE_METADATA = """[Application]
name=org.example.Game
runtime=org.freedesktop.Platform/x86_64/24.08
command=game

[Context]
shared=network;
sockets=wayland;pulseaudio;
devices=all;
filesystems=xdg-download:ro;
"""

FLATHUB_REF = """[Flatpak Ref]
Name=org.example.Game
Branch=stable
Title=org.example.Game from flathub
IsRuntime=false
Url=https://dl.flathub.org/repo/
SuggestRemoteName=flathub
GPGKey=bm90IGEga2V5
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
"""


class FilesTest(Env):
    """What a double-clicked file is and needs: never the host's packages or Flatpak."""

    def setUp(self):
        super().setUp()
        for name, value in (("foreign_architectures", lambda: []), ("native_architecture", lambda: "amd64"),
                            ("live_session", lambda path=None: False)):
            patcher = mock.patch.object(fs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def deb(self, name="spikepkg", version="1.0", arch="all", depends="", size="12"):
        folder = os.path.join(self.root, f"deb-{name}-{version}-{arch}")
        os.makedirs(os.path.join(folder, "DEBIAN"))
        control = (f"Package: {name}\nVersion: {version}\nArchitecture: {arch}\nMaintainer: Test <t@example.org>\n"
                   f"Installed-Size: {size}\nHomepage: https://example.org/\n"
                   + (f"Depends: {depends}\n" if depends else "") + "Description: a test package\n more words\n")
        with open(os.path.join(folder, "DEBIAN", "control"), "w") as f:
            f.write(control)
        path = folder + ".deb"
        subprocess.run(["dpkg-deb", "--build", folder, path], check=True, capture_output=True)
        return path

    def catalog(self, packages=None, protected=()):
        return types.SimpleNamespace(
            packages=packages or {}, apps=[], loaded=False, protected=set(protected),
            is_protected=lambda p: p in protected or p.startswith(fs.PROTECTED_PREFIXES))

    def test_kinds(self):
        self.assertEqual(fs.file_kind(self.deb()), "deb")
        self.write("a.flatpakref", FLATHUB_REF)
        self.assertEqual(fs.file_kind(os.path.join(self.root, "a.flatpakref")), "ref")
        self.write("﻿b.flatpakrepo", "\n[Flatpak Repo]\nUrl=https://x.example/\n")
        self.assertEqual(fs.file_kind(os.path.join(self.root, "﻿b.flatpakrepo")), "repo")
        self.write("c.flatpak", b"\x00\x01binary".decode("latin-1"))
        self.assertEqual(fs.file_kind(os.path.join(self.root, "c.flatpak")), "bundle")
        self.write("notes.txt", "hello")
        with self.assertRaisesRegex(fs.SoftwareError, "isn't a Debian package or a Flatpak file"):
            fs.file_kind(os.path.join(self.root, "notes.txt"))
        with self.assertRaisesRegex(fs.SoftwareError, "can't be read"):
            fs.file_kind(os.path.join(self.root, "missing.deb"))

    def test_inspect_deb(self):
        item = fs.inspect_file(self.deb("spikepkg", "1.2-3", size="2048"))
        self.assertIsNone(item["refused"])
        self.assertEqual((item["kind"], item["name"], item["version"], item["arch"]),
                         ("deb", "spikepkg", "1.2-3", "all"))
        self.assertEqual((item["size"], item["summary"]), (2048 * 1024, "a test package"))
        self.assertEqual(item["homepage"], "https://example.org/")
        # Another architecture is refused in words; a broken file too.
        item = fs.inspect_file(self.deb("other", arch="arm64"))
        self.assertIn("is for arm64 computers; this one runs amd64", item["refused"])
        broken = os.path.join(self.root, "broken.deb")
        with open(broken, "wb") as f:
            f.write(b"!<arch>\nnot really")
        self.assertIn("isn't a valid Debian package", fs.inspect_file(broken)["refused"])

    def test_inspect_ref(self):
        path = self.write("game.flatpakref", FLATHUB_REF) or os.path.join(self.root, "game.flatpakref")
        item = fs.inspect_file(path)
        self.assertIsNone(item["refused"])
        self.assertTrue(item["flathub"])
        self.assertEqual((item["app_id"], item["ref"], item["name"]),
                         ("org.example.Game", "app/org.example.Game/x86_64/stable", "Game"))
        # Another source needs a signing key and an https address; a runtime isn't an app.
        other = FLATHUB_REF.replace("https://dl.flathub.org/repo/", "https://apps.example.org/repo/")
        item = fs.inspect_file(self.write("o.flatpakref", other.replace("GPGKey=bm90IGEga2V5\n", "")) or
                               os.path.join(self.root, "o.flatpakref"))
        self.assertIn("no signing key", item["refused"])
        item = fs.inspect_file(self.write("p.flatpakref", other) or os.path.join(self.root, "p.flatpakref"))
        self.assertIsNone(item["refused"])
        self.assertFalse(item["flathub"])
        self.assertEqual(item["host"], "apps.example.org")
        http = other.replace("https://", "http://")
        self.assertIn("isn't an https address", fs.inspect_file(
            self.write("h.flatpakref", http) or os.path.join(self.root, "h.flatpakref"))["refused"])
        runtime = FLATHUB_REF.replace("IsRuntime=false", "IsRuntime=true")
        self.assertIn("is a runtime", fs.inspect_file(
            self.write("r.flatpakref", runtime) or os.path.join(self.root, "r.flatpakref"))["refused"])
        # The ref's own name can't smuggle anything into a ref string.
        evil = FLATHUB_REF.replace("Name=org.example.Game", "Name=../../etc")
        self.assertIn("isn't a valid Flatpak link file", fs.inspect_file(
            self.write("e.flatpakref", evil) or os.path.join(self.root, "e.flatpakref"))["refused"])

    def test_inspect_repo(self):
        text = "[Flatpak Repo]\nTitle=Example Apps\nUrl=https://apps.example.org/repo/\nComment=Games\nGPGKey=abc\n"
        item = fs.inspect_file(self.write("a.flatpakrepo", text) or os.path.join(self.root, "a.flatpakrepo"))
        self.assertIsNone(item["refused"])
        self.assertEqual((item["name"], item["host"], item["summary"]), ("Example Apps", "apps.example.org", "Games"))
        item = fs.inspect_file(self.write("b.flatpakrepo", text.replace("GPGKey=abc\n", "")) or
                               os.path.join(self.root, "b.flatpakrepo"))
        self.assertIn("no signing key", item["refused"])

    def test_permission_words(self):
        words, risky = fs.permission_words(BUNDLE_METADATA)
        self.assertEqual(words, ["Use the network", "Play and record sound",
                                 "Use all devices, such as game controllers and cameras",
                                 "Read your Downloads folder"])
        self.assertFalse(risky)         # devices and read-only folders don't change the button
        words, risky = fs.permission_words("[Context]\nfilesystems=home;~/Games;\n")
        self.assertEqual(words, ["Read and write your home folder", "Read and write the folder ~/Games"])
        self.assertTrue(risky)
        words, risky = fs.permission_words("[Context]\nfilesystems=home:ro;\n[Session Bus Policy]\n"
                                           "org.freedesktop.Flatpak=talk\norg.freedesktop.secrets=talk\n")
        self.assertEqual(words, ["Read your home folder", "Start programs outside the sandbox",
                                 "Use your saved passwords"])
        self.assertTrue(risky)
        self.assertEqual(fs.permission_words("[Context]\nsockets=session-bus;\n")[1], True)
        self.assertEqual(fs.permission_words("not a key file"), ([], False))

    def test_plan_debs(self):
        good = fs.inspect_file(self.deb("goodpkg", "2.0"))
        same = fs.inspect_file(self.deb("havepkg", "1.0"))
        older = fs.inspect_file(self.deb("oldpkg", "0.9"))
        named = fs.inspect_file(self.deb("flickos-evil", "1.0"))
        catalog = self.catalog({"havepkg": "1.0", "oldpkg": "1.0"})
        ids = ["goodpkg;2.0;all;+manual:local", "oldpkg;0.9;all;+manual:local", "libhelper;1.5;amd64;+auto:debian-stable-main"]
        details = mock.Mock(get_size=lambda: 5000, get_download_size=lambda: 2000)
        plan = {}
        pk = mock.Mock()
        pk_run = mock.Mock(return_value=mock.Mock(get_details_array=lambda: [details]))
        with mock.patch.object(fs, "deb_simulation", return_value=({"installing": ids}, pk, mock.Mock())), \
                mock.patch.object(fs, "pk_run", pk_run):
            fs.plan_debs([good, same, older, named], catalog, plan)
        self.assertEqual(same["refused"], "havepkg 1.0 is already installed.")
        self.assertIn("only FlickOS's own packages use", named["refused"])
        self.assertIsNone(good["refused"])
        self.assertTrue(any("older than the installed version (1.0)" in n for n in older["notes"]))
        self.assertEqual(plan["deb"]["packages"], ["libhelper"])
        self.assertEqual((plan["deb"]["size"], plan["deb"]["download"]), (5000, 2000))
        self.assertEqual(pk_run.call_args.args[-1], ["libhelper;1.5;amd64;+auto:debian-stable-main"])
        # A package that would remove the desktop is refused, with the names.
        item = fs.inspect_file(self.deb("clashpkg"))
        plan = {}
        with mock.patch.object(fs, "deb_simulation", return_value=({"installing": ["clashpkg;1.0;all;x:local"],
                                                                    "removing": ["flickos-desktop;1;all;x"]},
                                                                   pk, mock.Mock())):
            fs.plan_debs([item], self.catalog(), plan)
        self.assertIn("would remove part of the FlickOS desktop (flickos-desktop)", item["refused"])

    def test_plan_debs_finds_the_broken_file(self):
        good = fs.inspect_file(self.deb("goodpkg"))
        bad = fs.inspect_file(self.deb("badpkg", depends="nothing-here"))

        def simulate(paths):
            if any("badpkg" in p for p in paths):
                raise fs.PackageKitFailed("The following packages have unmet dependencies:\n  badpkg: Depends: x")
            return {"installing": ["goodpkg;1.0;all;+manual:local"]}, mock.Mock(), mock.Mock()

        plan = {}
        with mock.patch.object(fs, "deb_simulation", side_effect=simulate):
            fs.plan_debs([good, bad], self.catalog(), plan)
        self.assertIsNone(good["refused"])
        self.assertIn("badpkg can't be installed: The following packages have unmet dependencies: badpkg: Depends: x",
                      bad["refused"])
        self.assertIsNone(plan.get("error"))

    def test_plan_words(self):
        item = {"kind": "deb", "size": 3000, "download": 0, "refused": None, "risky": False}
        plan = {"items": [item], "deb": {"packages": ["a", "b"], "removes": [], "size": 1000, "download": 500},
                "flatpak": None, "error": None, "live": False}
        words = fs.files_plan_words(plan, lambda n: f"{n} B")
        self.assertIn("Needs 4000 B of disk space (500 B to download or copy).", words)
        self.assertIn("It brings 2 other packages from Debian.", words)
        self.assertIn("Debian packages ask for your password.", words)
        plan["live"] = True
        self.assertIn("This is the live session", fs.files_plan_words(plan, str))
        bundle = {"kind": "bundle", "size": 100, "download": 80, "refused": None, "risky": False}
        plan = {"items": [bundle], "deb": None, "flatpak": {"runtimes": ["the GNOME runtime"], "size": 900,
                                                            "download": 400}, "error": None, "live": False}
        words = fs.files_plan_words(plan, lambda n: f"{n} B")
        self.assertIn("Needs 1000 B of disk space (480 B to download or copy).", words)
        self.assertIn("It also needs the GNOME runtime from Flathub.", words)
        self.assertIn("Installing from a Flatpak file asks for your password.", words)

    def test_spool(self):
        first, second = os.path.join(self.root, "one.deb"), os.path.join(self.root, "two.flatpak")
        fs.spool_files([first])
        fs.spool_files([second])
        folder = fs.spool_folder()
        with open(os.path.join(folder, "99999999999999999999-ab.tmp"), "w") as f:       # not renamed yet
            f.write("/half")
        self.assertEqual(fs.take_spool(), [first, second])
        self.assertEqual(fs.take_spool(), [])
        self.assertEqual(os.listdir(folder), ["99999999999999999999-ab.tmp"])

    def test_open_reaches_the_open_window(self):
        path = os.path.join(self.root, "x.deb")
        with fs.single_instance() as first:
            self.assertTrue(first)
            code = fs.cmd_open(types.SimpleNamespace(files=[path]))
        self.assertEqual(code, 0)
        self.assertEqual(fs.take_spool(), [path])

    def test_commands(self):
        deb = self.deb("cmdpkg", "3.0")
        code, out, _err = CommandTest.run_main(self, "info", "--file", deb)
        self.assertEqual(code, 0)
        self.assertIn("name\tcmdpkg\n", out)
        self.assertIn("kind\tdeb\n", out)
        with mock.patch.object(fs, "open_catalog", return_value=self.catalog()), \
                mock.patch.object(fs, "deb_simulation",
                                  return_value=({"installing": ["cmdpkg;3.0;all;+manual:local"]}, mock.Mock(),
                                                mock.Mock())):
            code, out, _err = CommandTest.run_main(self, "plan", "--json", "--file", deb,
                                                   "--file", os.path.join(self.root, "nothing.txt"))
        self.assertEqual(code, 0)
        plan = json.loads(out)
        self.assertEqual([i["kind"] for i in plan["items"]], ["deb", None])
        self.assertIn("can't be read", plan["items"][1]["refused"])
        # --file means install only; and some app or file is needed.
        code, _out, err = CommandTest.run_main(self, "remove", "--file", deb)
        self.assertEqual(code, 1)
        self.assertIn("install only", err)
        code, _out, err = CommandTest.run_main(self, "plan")
        self.assertIn("needs an app or --file", err)

    def test_install_reports_each_file(self):
        good = self.deb("goodpkg", "1.0")
        lines = io.StringIO()
        out = fs.Output(True)
        with mock.patch.object(fs, "open_catalog", return_value=self.catalog()), \
                mock.patch.object(fs, "deb_simulation",
                                  return_value=({"installing": ["goodpkg;1.0;all;+manual:local"]}, mock.Mock(),
                                                mock.Mock())), \
                mock.patch.object(fs, "installed_packages", return_value=({"goodpkg": "1.0"}, set())), \
                mock.patch.object(fs, "packagekit", return_value=(mock.Mock(), mock.Mock())), \
                mock.patch.object(fs, "run_cancellable", lambda work: None), \
                contextlib.redirect_stdout(lines):
            failed = fs.files_change([good, os.path.join(self.root, "readme.txt")], out)
        events = [json.loads(line) for line in lines.getvalue().splitlines()]
        status = {os.path.basename(e["path"]): e["status"] for e in events if e["event"] == "item"}
        self.assertEqual(status, {"readme.txt": "error", "deb-goodpkg-1.0-all.deb": "done"})
        self.assertEqual(failed, 1)

    def test_nothing_usable(self):
        out = fs.Output(True)
        with mock.patch.object(fs, "open_catalog", return_value=self.catalog()), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(fs.SoftwareError, "None of the files can be installed"):
                fs.files_change([os.path.join(self.root, "nothing.txt")], out)

    def test_desktop_file_and_defaults(self):
        desktop = os.path.join(PACKAGE, "usr/share/applications/flickos-software-open.desktop")
        with open(desktop, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Exec=flickos-software open %F", text)        # all the selected files in one start
        self.assertIn("NoDisplay=true", text)
        types_ = re.search(r"^MimeType=(.*)$", text, re.M).group(1).strip(";").split(";")
        self.assertEqual(sorted(types_), ["application/vnd.debian.binary-package", "application/vnd.flatpak",
                                          "application/vnd.flatpak.ref", "application/vnd.flatpak.repo"])
        settings = os.path.join(os.path.dirname(PACKAGE), "flickos-settings/etc/xdg/flickos/mimeapps.list")
        if os.path.exists(settings):        # the package tree may be built alone
            with open(settings, encoding="utf-8") as f:
                defaults = f.read()
            for mime in types_:
                self.assertIn(f"{mime}=flickos-software-open.desktop", defaults)

    @unittest.skipUnless(subprocess.run(["which", "flatpak"], capture_output=True).returncode == 0,
                         "flatpak isn't installed")
    def test_bundle(self):
        try:
            import gi
            gi.require_version("Flatpak", "1.0")
            from gi.repository import Flatpak  # noqa: F401
        except (ImportError, ValueError):
            self.skipTest("libflatpak isn't available")
        app = os.path.join(self.root, "app")
        for folder in ("files/bin", "export/share"):
            os.makedirs(os.path.join(app, folder))
        with open(os.path.join(app, "metadata"), "w") as f:
            f.write(BUNDLE_METADATA)
        repo, bundle = os.path.join(self.root, "repo"), os.path.join(self.root, "game.flatpak")
        for command in (["build-export", "--no-update-summary", repo, app, "stable"],
                        ["build-bundle", repo, bundle, "org.example.Game", "stable"]):
            built = subprocess.run(["flatpak", *command], capture_output=True, text=True)
            if built.returncode != 0:
                self.skipTest(f"flatpak {command[0]} failed: {built.stderr.strip()[:80]}")
        item = fs.inspect_file(bundle)
        self.assertIsNone(item["refused"])
        self.assertEqual((item["kind"], item["app_id"], item["name"], item["ref"]),
                         ("bundle", "org.example.Game", "Game", "app/org.example.Game/x86_64/stable"))
        self.assertEqual(item["runtime_ref"], "runtime/org.freedesktop.Platform/x86_64/24.08")
        self.assertIn("Use the network", item["permissions"])
        self.assertFalse(item["risky"])
        self.assertTrue(any("won't update by itself" in n for n in item["notes"]))


if __name__ == "__main__":
    unittest.main()
