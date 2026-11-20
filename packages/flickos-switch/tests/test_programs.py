"""Tests for Windows programs (usr/share/flickos/switch/programs.py, phase 2a).
Run: python3 -m unittest discover -s tests

No network, display or Wine: every .exe, .msi, .msix and .lnk is built here
with struct and zipfile, then cut short and damaged, and Wine's state comes
from a fake PATH and root.
"""

import contextlib
import fnmatch
import importlib.machinery
import importlib.util
import io
import json
import os
import random
import re
import struct
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
LIST = os.path.join(PACKAGE, "usr/share/flickos/switch/apps.json")

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_switch_for_programs",
                                               os.path.join(PACKAGE, "usr/bin/flickos-switch"))
fs = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fs)
fs.PROGRAMS_CODE = os.path.join(PACKAGE, "usr/share/flickos/switch/programs.py")
p = fs.load_programs()
p.APPS_LIST = LIST

# Software's sources (flickos-software's SOURCES).
SOURCES = {"debian", "flickos", "community", "flathub"}
KEYS = {"id", "name", "group", "files", "makers", "products", "words", "linux", "web", "similar", "note", "wine"}


# --- Files built for the tests -------------------------------------------------------

def pad4(data):
    return data + b"\0" * (-len(data) % 4)


def vs_block(key, value=b"", children=b"", text=False):
    """A VS_VERSIONINFO node: wLength, wValueLength, wType, key, value, children."""
    head = struct.calcsize("<HHH") + len(key.encode("utf-16-le")) + 2
    body = b"\0" * (-head % 4) + pad4(value) + children
    length = len(value) // 2 if text else len(value)
    total = head + len(body)
    return struct.pack("<HHH", total, length, 1 if text else 0) + key.encode("utf-16-le") + b"\0\0" + body


def version_info(strings):
    table = b"".join(pad4(vs_block(k, v.encode("utf-16-le") + b"\0\0", text=True)) for k, v in strings.items())
    language = vs_block("040904b0", children=table, text=True)
    file_info = vs_block("StringFileInfo", children=pad4(language), text=True)
    fixed = struct.pack("<13I", 0xFEEF04BD, *[0] * 12)
    return vs_block("VS_VERSION_INFO", fixed, children=pad4(file_info))


def resource_section(rva, version):
    """Type 16 → name 1 → language 0x409 → the version block."""
    def directory(ident, target):
        return struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1) + struct.pack("<II", ident, target)
    tree = (directory(16, 0x80000018) + directory(1, 0x80000030) + directory(0x409, 0x48)
            + struct.pack("<IIII", rva + 0x58, len(version), 0, 0))
    return tree + version


def write_pe(path, strings=None, bits=32, rsrc_at=0x400, signed=False):
    machine, magic, first = (0x14C, 0x10B, 96) if bits == 32 else (0x8664, 0x20B, 112)
    optional = bytearray(first + 16 * 8)
    struct.pack_into("<H", optional, 0, magic)
    struct.pack_into("<I", optional, first - 4, 16)
    rva = 0x1000
    rsrc = resource_section(rva, version_info(strings)) if strings is not None else b""
    if strings is not None:
        struct.pack_into("<II", optional, first + 16, rva, len(rsrc))
    if signed:
        struct.pack_into("<II", optional, first + 32, 0x9000, 0x100)
    dos = bytearray(0x80)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, len(optional), 0x102)
    section = b".rsrc\0\0\0" + struct.pack("<IIII", max(len(rsrc), 1), rva, max(len(rsrc), 1), rsrc_at) + b"\0" * 16
    with open(path, "wb") as f:
        f.write(bytes(dos) + coff + bytes(optional) + section)
        f.seek(rsrc_at)             # past the headers: a hole when far away
        f.write(rsrc or b"\0")
    return path


MSI_CLSID = bytes.fromhex("84100c0000000000c000000000000046")
END, FREE, FATSECT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD


def property_set(props, codepage=1252):
    """A SummaryInformation stream: {pid: text}."""
    values = [(1, struct.pack("<IhH", 2, codepage, 0))]
    for pid, text in props.items():
        raw = text.encode("utf-8" if codepage == 65001 else f"cp{codepage}") + b"\0"
        values.append((pid, struct.pack("<II", 30, len(raw)) + pad4(raw)))
    at = 8 + 8 * len(values)
    pairs, data = b"", b""
    for pid, value in values:
        pairs += struct.pack("<II", pid, at + len(data))
        data += value
    section = struct.pack("<II", 8 + len(pairs) + len(data), len(values)) + pairs + data
    return struct.pack("<HHI16sI", 0xFFFE, 0, 0, b"\0" * 16, 1) + b"\xe0\x85\x9f\xf2\xf9\x4f\x68\x10\xab\x91\x08\x00\x2b\x27\xb3\xd9" \
        + struct.pack("<I", 48) + section


def dir_entry(name, kind, start, size, clsid=b"\0" * 16):
    raw = name.encode("utf-16-le") + b"\0\0"
    entry = bytearray(128)
    entry[:len(raw)] = raw
    struct.pack_into("<HBB", entry, 64, len(raw), kind, 1)
    struct.pack_into("<III", entry, 68, FREE, FREE, FREE)
    entry[80:96] = clsid
    struct.pack_into("<IQ", entry, 116, start, size)
    return bytes(entry)


def write_msi(path, props, clsid=MSI_CLSID, mini=True, loop=False, signed=False):
    """A compound file with SummaryInformation: in the mini stream (small,
    as Windows Installer writes it), or as a regular stream."""
    stream = property_set(props)
    sectors = []
    if mini:
        ministream = stream + b"\0" * (-len(stream) % 64)
        count = len(ministream) // 64
        minifat = [i + 1 for i in range(count - 1)] + [END]
        minifat_sector = struct.pack(f"<{128}I", *(minifat + [FREE] * (128 - len(minifat))))
        root_sectors = [ministream[i:i + 512] for i in range(0, len(ministream), 512)]
        # 0 FAT, 1 directory, 2 mini FAT, 3.. the mini stream
        fat = [FATSECT, 1 if loop else END, END] + [4 + i for i in range(len(root_sectors) - 1)] + [END]
        root = dir_entry("Root Entry", 5, 3, len(ministream), clsid)
        summary = dir_entry("\x05SummaryInformation", 2, 0, len(stream))
        sectors = [None, None, minifat_sector] + root_sectors
        minifat_start, minifat_count = 2, 1
    else:
        stream = stream + b"\0" * (4096 - len(stream))
        data_sectors = [stream[i:i + 512] for i in range(0, len(stream), 512)]
        fat = [FATSECT, 1 if loop else END] + [3 + i for i in range(len(data_sectors) - 1)] + [END]
        root = dir_entry("Root Entry", 5, END, 0, clsid)
        summary = dir_entry("\x05SummaryInformation", 2, 2, len(stream))
        sectors = [None, None] + data_sectors
        minifat_start, minifat_count = END, 0
    entries = [root, summary]
    if signed:
        entries.append(dir_entry("\x05DigitalSignature", 2, END, 0))
    directory = b"".join(entries)
    directory += b"\0" * (512 - len(directory))
    sectors[0] = struct.pack("<128I", *(fat + [FREE] * (128 - len(fat))))
    sectors[1] = directory
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIII", header, 40, 0, 1, 1, 0, 4096, minifat_start, minifat_count, END)
    struct.pack_into("<I", header, 72, 0)
    struct.pack_into("<109I", header, 76, *([0] + [FREE] * 108))
    with open(path, "wb") as f:
        f.write(bytes(header) + b"".join(s + b"\0" * (512 - len(s)) for s in sectors))
    return path


MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Identity Name="MSTeams" Publisher="CN=Microsoft Corporation, O=Microsoft Corporation, C=US"
            Version="25.1.0.0" ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>Microsoft Teams</DisplayName>
    <PublisherDisplayName>Microsoft Corporation</PublisherDisplayName>
  </Properties>
</Package>
"""


def write_msix(path, manifest=MANIFEST, name="AppxManifest.xml"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, manifest)
        z.writestr("Teams.exe", b"MZ")
    return path


LNK_CLSID = bytes.fromhex("0114020000000000c000000000000046")


def write_lnk(path, target="C:\\Users\\Ann\\Documents\\Report.docx", description=None):
    flags = 0x2 | (0x4 | 0x80 if description else 0)
    header = struct.pack("<I16sII", 0x4C, LNK_CLSID, flags, 0x20) + b"\0" * 24 + struct.pack("<IIIHHII", 0, 0, 1, 0, 0, 0, 0)
    volume = struct.pack("<IIII", 0x11, 3, 0, 0x10) + b"\0"
    base = target.encode("cp1252") + b"\0"
    at = 0x1C
    info = struct.pack("<IIIIIII", 0, 0x1C, 1, at, at + len(volume), 0, at + len(volume) + len(base))
    info += volume + base + b"\0"
    info = struct.pack("<I", len(info)) + info[4:]
    extra = b""
    if description:
        extra = struct.pack("<H", len(description)) + description.encode("utf-16-le")
    with open(path, "wb") as f:
        f.write(header + info + extra)
    return path


class Files(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def path(self, name):
        return os.path.join(self.folder.name, name)


# --- Reading ---------------------------------------------------------------------------

class IdentifyTest(Files):
    def test_exe(self):
        path = write_pe(self.path("SpotifySetup.exe"), {"ProductName": "Spotify", "CompanyName": "Spotify Ltd",
                                                        "FileDescription": "Spotify", "OriginalFilename": "Setup.exe"},
                        bits=64, signed=True)
        info = p.identify(path)
        self.assertEqual(info, {"kind": "exe", "bits": 64, "signed": True, "product": "Spotify",
                                "maker": "Spotify Ltd", "description": "Spotify", "original": "Setup.exe"})

    def test_exe_without_version_information(self):
        info = p.identify(write_pe(self.path("vlc-3.0.21-win64.exe")))
        self.assertEqual(info, {"kind": "exe", "bits": 32, "signed": False})

    def test_version_block_far_in_is_found_reading_little(self):
        """Chrome's and Discord's version blocks are past their payload
        (160 MB in, for Discord): it seeks there and reads under 1 MB."""
        path = write_pe(self.path("DiscordSetup.exe"), {"ProductName": "Discord", "CompanyName": "Discord Inc."},
                        rsrc_at=160 * 1024 * 1024)
        read = []
        real = p.Reader.read

        def counting(reader, offset, length):
            read.append(length)
            return real(reader, offset, length)

        with mock.patch.object(p.Reader, "read", counting):
            info = p.identify(path)
        self.assertEqual(info["product"], "Discord")
        self.assertLess(sum(read), p.PE_BUDGET)

    def test_msi_in_mini_stream_and_regular(self):
        for mini in (True, False):
            path = write_msi(self.path(f"node-{mini}.msi"), {3: "Node.js", 4: "Node.js Foundation", 2: "Installation Database"},
                             mini=mini, signed=True)
            self.assertEqual(p.identify(path), {"kind": "msi", "signed": True, "product": "Node.js",
                                                "maker": "Node.js Foundation", "description": "Installation Database"})

    def test_other_compound_files_are_unknown(self):
        """An old .doc is a compound file too, with another class."""
        path = write_msi(self.path("letter.doc"), {3: "Letter"}, clsid=b"\x06\x09\x02\0" + b"\0" * 12)
        self.assertEqual(p.identify(path), {"kind": "unknown"})

    def test_msix(self):
        info = p.identify(write_msix(self.path("MSTeams-x64.msix")))
        self.assertEqual(info, {"kind": "msix", "product": "Microsoft Teams", "maker": "Microsoft Corporation", "bits": 64})

    def test_msix_bundle_and_resource_names(self):
        manifest = MANIFEST.replace("<DisplayName>Microsoft Teams", "<DisplayName>ms-resource:AppName")
        info = p.identify(write_msix(self.path("Teams.msixbundle"), manifest, "AppxMetadata/AppxBundleManifest.xml"))
        self.assertEqual(info["product"], "MSTeams")
        self.assertEqual(info["kind"], "msix")

    def test_msix_with_entities_is_refused(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE p [<!ENTITY a "aaaaaaaaaa">'
                '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><Package><Identity Name="&b;"/></Package>')
        self.assertEqual(p.identify(write_msix(self.path("bomb.msix"), bomb)), {"kind": "unknown"})

    def test_a_plain_zip_is_unknown(self):
        path = self.path("photos.zip")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("a.jpg", b"x")
        self.assertEqual(p.identify(path), {"kind": "unknown"})

    def test_lnk(self):
        info = p.identify(write_lnk(self.path("Report.lnk"), description="My report"))
        self.assertEqual(info, {"kind": "lnk", "target": "C:\\Users\\Ann\\Documents\\Report.docx",
                                "description": "My report"})

    def test_text_and_empty_files_are_unknown(self):
        for name, data in (("notes.exe", b"hello"), ("empty.exe", b""), ("x.msi", b"MZ")):
            with open(self.path(name), "wb") as f:
                f.write(data)
            self.assertEqual(p.identify(self.path(name)), {"kind": "unknown"}, name)

    def test_only_regular_files_are_opened(self):
        fifo = self.path("pipe.exe")
        os.mkfifo(fifo)
        self.assertEqual(p.identify(fifo), {"kind": "unknown"})       # no wait for a writer
        self.assertEqual(p.identify(self.folder.name), {"kind": "unknown"})

    def test_missing_file_raises(self):
        with self.assertRaises(OSError):
            p.identify(self.path("gone.exe"))


class BrokenFilesTest(Files):
    """Downloads cut short or damaged end as a result, never an error or a
    hang: every prefix of each kind, and bytes changed at random."""

    def samples(self):
        yield write_pe(self.path("a.exe"), {"ProductName": "A", "CompanyName": "B"}, bits=64)
        yield write_msi(self.path("a.msi"), {3: "A", 4: "B"})
        yield write_msi(self.path("b.msi"), {3: "A", 4: "B"}, mini=False)
        yield write_lnk(self.path("a.lnk"), description="d")
        yield write_msix(self.path("a.msix"))

    def check(self, path):
        started = time.monotonic()
        info = p.identify(path)
        self.assertIn(info["kind"], ("exe", "msi", "msix", "lnk", "unknown"))
        self.assertLess(time.monotonic() - started, 1)

    def test_cut_short(self):
        for sample in self.samples():
            with open(sample, "rb") as f:
                data = f.read()
            cut = self.path("cut")
            for length in range(0, len(data), 7):
                with open(cut, "wb") as f:
                    f.write(data[:length])
                self.check(cut)

    def test_damaged(self):
        rng = random.Random(4)
        for sample in self.samples():
            with open(sample, "rb") as f:
                data = f.read()
            damaged = self.path("damaged")
            for _ in range(300):
                changed = bytearray(data)
                for _ in range(rng.randint(1, 8)):
                    at = rng.randrange(len(changed))
                    changed[at] = rng.choice((0, 0xFF, 0x80, rng.randrange(256)))
                with open(damaged, "wb") as f:
                    f.write(changed)
                self.check(damaged)

    def test_loops_and_huge_numbers(self):
        self.check(write_msi(self.path("loop.msi"), {3: "A"}, loop=True))
        self.check(write_msi(self.path("loop2.msi"), {3: "A"}, loop=True, mini=False))
        path = write_pe(self.path("big.exe"), {"ProductName": "A"})
        with open(path, "r+b") as f:
            f.seek(0x80 + 6)
            f.write(struct.pack("<H", 0xFFFF))          # sections
        self.assertEqual(p.identify(path), {"kind": "unknown"})
        with open(path, "r+b") as f:
            f.seek(0x3C)
            f.write(struct.pack("<I", 0xFFFFFFF0))      # PE header past the end
        self.assertEqual(p.identify(path), {"kind": "unknown"})


# --- The list ----------------------------------------------------------------------------

class ListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(LIST, encoding="utf-8") as f:
            cls.entries = json.load(f)

    def test_shape(self):
        ids = set()
        for e in self.entries:
            with self.subTest(e.get("id")):
                self.assertLessEqual(set(e), KEYS)
                self.assertRegex(e["id"], r"^[a-z0-9][a-z0-9-]*$")
                self.assertNotIn(e["id"], ids)
                ids.add(e["id"])
                self.assertTrue(e["name"].strip())
                self.assertTrue(e.get("files") or e.get("products"), "nothing to match")
                for key in ("files", "makers", "products", "words"):
                    self.assertIsInstance(e.get(key, []), list)
                    self.assertTrue(all(isinstance(v, str) and v.strip() for v in e.get(key, [])))
                for app in [e.get("linux")] + e.get("similar", []):
                    if app:
                        self.assertIn(app["source"], SOURCES)
                        self.assertTrue(app["app"] and app["name"])
                for s in e.get("similar", []):
                    self.assertTrue(s.get("why", "").endswith("."), s)
                if e.get("web"):
                    self.assertTrue(e["web"]["url"].startswith("https://"))
                    self.assertTrue(e["web"]["name"])
                self.assertIn(e.get("wine", "maybe"), ("maybe", "no"))
                if e.get("note"):
                    self.assertTrue(e["note"].endswith("."))
                if e.get("group"):
                    self.assertTrue(e.get("note"), "a group says why")
                    self.assertEqual(e["name"], e["name"].lower(), "a group's name follows \"is\"")
                self.assertTrue(e.get("linux") or e.get("web") or e.get("similar") or e.get("note"),
                                "an entry offers something")

    def test_patterns_name_something(self):
        """A pattern alone matches a file without version information, so it
        has to say more than "*.exe"."""
        for e in self.entries:
            for pattern in e.get("files", []):
                with self.subTest(e["id"], pattern=pattern):
                    stem = re.sub(r"\.(exe|msi|msix|msixbundle|zip|7z)$", "", pattern, flags=re.I)
                    self.assertRegex(pattern, r"\.(exe|msi|msix|msixbundle|zip|7z)$")
                    self.assertGreaterEqual(len(re.sub(r"[*?\[\]]", "", stem)), 2)

    def test_patterns_find_one_entry(self):
        """No two entries claim the same typical file names."""
        names = {"SpotifySetup.exe": "spotify", "ChromeSetup.exe": "chrome", "DiscordSetup.exe": "discord",
                 "SteamSetup.exe": "steam", "vlc-3.0.21-win64.exe": "vlc", "7z2409-x64.exe": "7-zip",
                 "OfficeSetup.exe": "microsoft-office", "Firefox Setup 159.0.1.exe": "firefox",
                 "npp.8.7.1.Installer.x64.exe": "notepad-plus-plus", "MBSetup.exe": "antivirus",
                 "td-setup-win-x64-7.3.3.exe": "telegram", "VSCodeUserSetup-x64-1.144.1.exe": "vscode"}
        for name, expected in names.items():
            found = [e["id"] for e in self.entries
                     if any(fnmatch.fnmatchcase(name.casefold(), pat.casefold()) for pat in e.get("files", []))]
            self.assertEqual(found, [expected], name)

    def test_load_list_survives_a_broken_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            f.write("[{")
            f.flush()
            self.assertEqual(p.load_list(f.name), [])
        self.assertEqual(p.load_list("/nonexistent/apps.json"), [])


ENTRIES = [
    {"id": "spotify", "name": "Spotify", "files": ["SpotifySetup*.exe"], "makers": ["Spotify"],
     "products": ["Spotify"], "words": ["music"], "linux": {"app": "com.spotify.Client", "source": "flathub", "name": "Spotify"}},
    {"id": "vlc", "name": "VLC", "files": ["vlc-*-win64.exe"], "makers": ["VideoLAN"], "products": ["VLC"],
     "linux": {"app": "org.videolan.VLC", "source": "flathub", "name": "VLC"}},
    {"id": "photoshop", "name": "Adobe Photoshop", "files": ["Photoshop_Set-Up*.exe"], "makers": ["Adobe"],
     "products": ["Photoshop"], "words": ["photo editor"],
     "similar": [{"app": "org.gimp.GIMP", "source": "flathub", "name": "GIMP", "why": "Edits photos."}], "wine": "no"},
    {"id": "notepad-plus-plus", "name": "Notepad++", "files": ["npp.*.exe"], "makers": ["Don HO"], "products": ["Notepad++"],
     "web": {"name": "N on the web", "url": "https://example.org"},
     "similar": [{"app": "org.kde.kate", "source": "flathub", "name": "Kate", "why": "Edits text."}]},
    {"id": "antivirus", "name": "antivirus software", "group": True, "files": ["MBSetup*.exe"], "makers": ["Malwarebytes"],
     "products": ["antivirus"], "note": "No antivirus needed.", "wine": "no"},
]


class MatchTest(unittest.TestCase):
    def test_name_and_maker(self):
        info = {"kind": "exe", "maker": "Spotify Ltd", "product": "Spotify"}
        self.assertEqual(p.match(info, "/home/a/Downloads/SpotifySetup.exe", ENTRIES)["id"], "spotify")
        self.assertEqual(p.match(info, "SpotifySetup (1).exe", ENTRIES)["id"], "spotify")
        self.assertEqual(p.match(info, "SPOTIFYSETUP.EXE", ENTRIES)["id"], "spotify")

    def test_renamed_file_by_product_and_maker(self):
        info = {"kind": "exe", "maker": "Adobe Inc.", "product": "Adobe Photoshop 2026"}
        self.assertEqual(p.match(info, "download.exe", ENTRIES)["id"], "photoshop")

    def test_name_with_another_maker_is_not_it(self):
        info = {"kind": "exe", "maker": "Evil Corp", "product": "Spotify"}
        self.assertIsNone(p.match(info, "SpotifySetup.exe", ENTRIES))

    def test_name_alone_without_version_information(self):
        self.assertEqual(p.match({"kind": "exe", "bits": 32}, "vlc-3.0.21-win64.exe", ENTRIES)["id"], "vlc")

    def test_product_without_maker_is_not_enough(self):
        self.assertIsNone(p.match({"kind": "exe", "product": "Spotify"}, "x.exe", ENTRIES))

    def test_only_programs(self):
        for kind in ("lnk", "unknown"):
            self.assertIsNone(p.match({"kind": kind}, "SpotifySetup.exe", ENTRIES))

    def test_lookup(self):
        self.assertEqual([e["id"] for e in p.lookup(["Photo", "editor"], ENTRIES)], ["photoshop"])
        self.assertEqual([e["id"] for e in p.lookup(["music"], ENTRIES)], ["spotify"])
        self.assertEqual(p.lookup([" "], ENTRIES), [])

    def test_lookup_matches_what_was_typed(self):
        entries = [{"id": "pw", "name": "1Password", "words": ["password manager"]},
                   {"id": "office", "name": "Microsoft Office", "words": ["ms word", "excel"]},
                   {"id": "zip", "name": "7-Zip", "words": []}]
        self.assertEqual([e["id"] for e in p.lookup(["MS ", " Word"], entries)], ["office"])
        self.assertEqual([e["id"] for e in p.lookup(["microsoft", "office"], entries)], ["office"])
        self.assertEqual([e["id"] for e in p.lookup(["7", "zip"], entries)], ["zip"])
        for words in (["word"], ["micro"], ["password"], ["office", "excel"]):
            self.assertEqual(p.lookup(words, entries), [], words)

    def test_lookup_names_before_words(self):
        entries = [{"id": "a", "name": "Player", "words": ["music box"]},
                   {"id": "b", "name": "Music-Box", "products": ["MusicBox"]}]
        found = p.lookup(["music box"], entries)
        self.assertEqual([(e["id"], e["by"]) for e in found], [("b", "name"), ("a", "words")])
        self.assertNotIn("by", entries[0])      # copies

    def test_lookup_json_is_translated(self):
        entry = {"id": "x", "name": "antivirus software", "group": True, "note": "Note.",
                 "web": {"name": "X on the web", "url": "https://x"},
                 "similar": [{"app": "a", "why": "Why."}, {"app": "b"}]}
        with mock.patch.object(p, "_", lambda text: text.upper()):
            out = p.translated(entry)
        self.assertEqual((out["name"], out["note"], out["web"]["name"], out["web"]["url"]),
                         ("ANTIVIRUS SOFTWARE", "NOTE.", "X ON THE WEB", "https://x"))
        self.assertEqual(out["similar"], [{"app": "a", "why": "WHY."}, {"app": "b"}])
        self.assertEqual(entry["note"], "Note.")
        with mock.patch.object(p, "_", lambda text: text.upper()):
            self.assertEqual(p.translated({"id": "s", "name": "Spotify"})["name"], "Spotify")

    def test_lookup_in_the_real_list(self):
        entries = p.load_list(LIST)
        for words, expected in ((["photoshop"], "photoshop"), (["ms", "word"], "microsoft-office"),
                                (["fortnite"], "epic-games"), (["avast"], "antivirus"), (["excel"], "microsoft-office"),
                                (["notepad++"], "notepad-plus-plus"), (["Adobe", "Photoshop"], "photoshop")):
            self.assertIn(expected, [e["id"] for e in p.lookup(words, entries)], words)

    def test_search_words(self):
        self.assertEqual(p.search_words({"product": "Foo Editor"}, "x.exe"), "Foo Editor")
        self.assertEqual(p.search_words({"product": "Foo Installer"}, "FooEdit-Setup-2.3.1-x64.exe"), "fooedit")
        self.assertEqual(p.search_words({}, "My Cool App v2 (1).exe"), "my cool app")
        self.assertEqual(p.search_words({}, "setup.exe"), "setup")


class AnswerTest(unittest.TestCase):
    def entry(self, ident):
        return next(e for e in ENTRIES if e["id"] == ident)

    def test_linux_version_is_the_only_answer(self):
        self.assertEqual(p.answer({"kind": "exe"}, self.entry("spotify"), "ready"),
                         [("install", self.entry("spotify")["linux"])])

    def test_known_without_linux_version(self):
        entry = self.entry("notepad-plus-plus")
        self.assertEqual([a for a, _v in p.answer({"kind": "exe", "bits": 32}, entry, "missing")],
                         ["web", "similar", "wine-get"])

    def test_wine_no_leaves_wine_out(self):
        self.assertEqual([a for a, _v in p.answer({"kind": "exe"}, self.entry("photoshop"), "ready")], ["similar"])

    def test_unknown(self):
        self.assertEqual([a for a, _v in p.answer({"kind": "exe", "bits": 32}, None, "ready")], ["search", "wine-run"])

    def test_wine_needs_its_32_bit_part_for_32_bit_programs(self):
        self.assertEqual(p.answer({"kind": "exe", "bits": 32}, None, "64-bit")[-1], ("wine-get", "32-bit"))
        self.assertEqual(p.answer({"kind": "exe", "bits": 32}, None, "missing")[-1], ("wine-get", None))
        self.assertEqual(p.answer({"kind": "exe", "bits": 64}, None, "64-bit")[-1][0], "wine-run")
        self.assertEqual(p.answer({"kind": "msi"}, None, "64-bit")[-1][0], "wine-get")

    def test_no_wine_for_store_packages_and_shortcuts(self):
        self.assertEqual([a for a, _v in p.answer({"kind": "msix"}, None, "ready")], ["search"])
        self.assertEqual(p.answer({"kind": "lnk"}, None, "ready"), [])

    def test_wine_commands(self):
        self.assertEqual(p.wine_command({"kind": "exe"}, "/d/a b.exe"), ["wine", "start", "/unix", "/d/a b.exe"])
        self.assertEqual(p.wine_command({"kind": "msi"}, "/d/a.msi"), ["wine", "msiexec", "/i", "/d/a.msi"])

    def test_headlines(self):
        cases = [({"kind": "exe"}, self.entry("spotify"), "is also made for FlickOS"),
                 ({"kind": "exe"}, self.entry("photoshop"), "isn't made for FlickOS"),
                 ({"kind": "exe"}, self.entry("antivirus"), "MBSetup.exe is antivirus software for Windows. No antivirus"),
                 ({"kind": "exe", "product": "Foo", "maker": "Bar"}, None, "It says it is Foo, by Bar."),
                 ({"kind": "lnk", "target": "C:\\x.docx"}, None, "It pointed to C:\\x.docx."),
                 ({"kind": "unknown"}, None, "can't read")]
        for info, entry, expected in cases:
            self.assertIn(expected, p.headline(info, entry, "MBSetup.exe"))


class WineStateTest(unittest.TestCase):
    def test_states(self):
        with tempfile.TemporaryDirectory() as root:
            bin_dir = os.path.join(root, "bin")
            os.makedirs(bin_dir)
            self.assertEqual(p.wine_state(path=bin_dir, root=root), "missing")
            wine = os.path.join(bin_dir, "wine")
            with open(wine, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(wine, 0o755)
            self.assertEqual(p.wine_state(path=bin_dir, root=root), "64-bit")
            os.makedirs(os.path.join(root, "usr/lib/wine"))
            open(os.path.join(root, "usr/lib/wine/wine"), "w").close()
            self.assertEqual(p.wine_state(path=bin_dir, root=root), "ready")


class CommandsTest(Files):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(fs, "PROGRAMS_CODE", fs.PROGRAMS_CODE), \
                mock.patch.dict(os.environ, {"FLICKOS_SWITCH_PREFIX": PACKAGE}):
            status = fs.main(list(args))
        return status, out.getvalue()

    def test_identify_json_names_the_entry(self):
        path = write_pe(self.path("SpotifySetup.exe"), {"ProductName": "Spotify", "CompanyName": "Spotify Ltd"})
        status, out = self.run_main("identify", "--json", path)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)[path]["match"], "spotify")

    def test_identify_lines(self):
        path = write_lnk(self.path("Report.lnk"))
        status, out = self.run_main("identify", path)
        self.assertEqual(out.split("\t")[:2], ["lnk", "-"])
        self.assertIn("C:\\Users\\Ann\\Documents\\Report.docx", out)

    def test_lookup(self):
        status, out = self.run_main("lookup", "spotify")
        self.assertEqual(status, 0)
        self.assertEqual(out, "spotify\tSpotify\tflathub:com.spotify.Client\t-\n")


class ShippedFilesTest(unittest.TestCase):
    def test_open_desktop_file(self):
        with open(os.path.join(PACKAGE, "usr/share/applications", p.APP_ID + ".desktop"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Exec=flickos-switch open %f\n", text)
        self.assertIn("NoDisplay=true\n", text)
        types = re.search(r"^MimeType=(.*)$", text, re.M).group(1).rstrip(";").split(";")
        self.assertEqual(set(types), {"application/x-msdownload", "application/vnd.microsoft.portable-executable",
                                      "application/x-ms-dos-executable", "application/x-msi", "application/msix",
                                      "application/msixbundle", "application/x-ms-shortcut"})


if __name__ == "__main__":
    unittest.main()
