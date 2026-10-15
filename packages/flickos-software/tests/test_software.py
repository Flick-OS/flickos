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
        }
        for name, value in patches.items():
            patcher = mock.patch.object(fs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.cache, "LANGUAGE": "", "LC_ALL": "",
                                           "LC_MESSAGES": "", "LANG": "C.UTF-8",
                                           "XDG_RUNTIME_DIR": os.path.join(self.root, "run")})
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
        self.assertEqual(counts, {"debian": 5, "flickos": 0, "community": 1, "flathub": 4, "apps": 7})
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
        for command in ("show", "search", "list", "info", "index", "refresh", "plan", "install", "remove"):
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
        self.assertEqual(set(fs.SOURCES), set(fs.SOURCE_NAMES))
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


if __name__ == "__main__":
    unittest.main()
