"""Windows programs (phase 2a of docs/design/flickos-switch.md): what a .exe,
.msi, .msix or .lnk says it is, read without running it; the Windows apps
list (apps.json next to this file); the window a double-click opens.

flickos-switch loads this file only for identify, open and lookup, so the
files window doesn't compile it (a script in /usr/bin has no .pyc). It sets
_ (its translation) and Builders (its window builders) before this runs.

Reading files from strangers (downloads): nothing in a file is run, loaded
or passed to a shell. Every offset and length read from one is checked
against the file's size before it is used, and a Reader stops at a budget
(PE_BUDGET, MSI_BUDGET), so a broken or hostile file ends as "unknown",
never as an error, a hang or a large read.
"""

import fnmatch
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import zipfile

# flickos-switch sets these before the file runs; alone (tests), English
# and no window builders.
_ = globals().get("_", str)
Builders = globals().get("Builders", object)


def N_(text):
    return text


PREFIX = os.environ.get("FLICKOS_SWITCH_PREFIX", "")
APPS_LIST = PREFIX + "/usr/share/flickos/switch/apps.json"
APP_ID = "flickos-switch-open"      # Wayland app id: flickos-switch-open.desktop
ICON = "application-x-executable"

PE_BUDGET = 1024 * 1024             # bytes read from a PE file at most
MSI_BUDGET = 16 * 1024 * 1024       # and from an .msi
MANIFEST_LIMIT = 1024 * 1024        # an .msix's AppxManifest.xml
VERSION_LIMIT = 64 * 1024           # a VS_VERSIONINFO block
MAX_SECTIONS = 96                   # what Windows' loader accepts
MAX_ENTRIES = 512                   # entries in one resource directory
STREAM_LIMIT = 64 * 1024            # an .msi's SummaryInformation stream
LNK_INFO_LIMIT = 64 * 1024

RT_VERSION = 16
RESOURCE_DIRECTORY = 2
SECURITY_DIRECTORY = 4
MACHINES = {0x14C: 32, 0x8664: 64, 0xAA64: 64}
VERSION_KEYS = {"ProductName": "product", "CompanyName": "maker",
                "FileDescription": "description", "OriginalFilename": "original"}
CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CFB_END = 0xFFFFFFFA                # sector numbers from here on are markers
# The root storage's class of an .msi (Windows Installer package), as stored.
MSI_CLSID = bytes.fromhex("84100c0000000000c000000000000046")
# SummaryInformation's properties Windows Installer uses: Subject is the
# product, Author its maker.
SUMMARY = {3: "product", 4: "maker", 2: "description"}
LNK_CLSID = bytes.fromhex("0114020000000000c000000000000046")
MSIX_MANIFESTS = ("AppxManifest.xml", "AppxMetadata/AppxBundleManifest.xml")

# /usr/lib/wine/wine is wine32's loader: Wine with its 32-bit part, which
# every Windows installer needs (phase 0 item 3).
WINE_32 = "/usr/lib/wine/wine"
WINE_APP = "org.winehq.wine"        # Wine in Software (Debian's AppStream)
FIREFOX = "firefox-esr"             # web versions open in it as web apps (phase 3)

# File name words that say nothing about the program (search words).
NOISE = re.compile(r"^(setup|install|installer|web|full|offline|online|latest|stable|release|"
                   r"x64|x86|x86_64|amd64|arm64|win|win32|win64|windows|64bit|32bit|64|32|"
                   r"v?\d[\d.]*[a-z]?|en|en-us|user|msi|exe)$")


class Unreadable(Exception):
    """The file isn't what it seemed, or reading it would go past a limit."""


class Reader:
    """Reads from a file at offsets checked against its size, up to a budget."""

    def __init__(self, f, size, budget):
        self.f, self.size, self.budget = f, size, budget

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.size:
            raise Unreadable(f"{length} bytes at {offset} are past the end")
        if length > self.budget:
            raise Unreadable("read limit reached")
        self.budget -= length
        self.f.seek(offset)
        data = self.f.read(length)
        if len(data) != length:
            raise Unreadable("the file got shorter")
        return data

    def unpack(self, fmt, offset):
        return struct.unpack(fmt, self.read(offset, struct.calcsize(fmt)))


# --- .exe (PE) ----------------------------------------------------------------

def pe_info(reader):
    """Bits, the version information's strings and whether it is signed."""
    if reader.read(0, 2) != b"MZ":
        return None
    pe, = reader.unpack("<I", 0x3C)
    if reader.read(pe, 4) != b"PE\0\0":
        return None
    machine, count, _time, _symbols, _symbol_count, optional_size = reader.unpack("<HHIIIH", pe + 4)
    if count > MAX_SECTIONS or optional_size > 4096:
        raise Unreadable("implausible headers")
    optional = reader.read(pe + 24, optional_size)
    if len(optional) < 2:
        raise Unreadable("no optional header")
    magic, = struct.unpack_from("<H", optional, 0)
    first = {0x10B: 96, 0x20B: 112}.get(magic)
    if first is None:
        raise Unreadable("unknown optional header")
    info = {"kind": "exe", "bits": MACHINES.get(machine), "signed": False}

    def directory(index):
        at = first + 8 * index
        if at + 8 > len(optional):
            return 0, 0
        return struct.unpack_from("<II", optional, at)

    info["signed"] = directory(SECURITY_DIRECTORY)[1] > 0
    sections = []
    table = reader.read(pe + 24 + optional_size, 40 * count)
    for i in range(count):
        vsize, rva, raw_size, raw_offset = struct.unpack_from("<IIII", table, 40 * i + 8)
        sections.append((rva, max(vsize, raw_size), raw_offset, raw_size))

    def offset_of(rva, length):
        for start, size, raw, raw_size in sections:
            if start <= rva and rva + length <= start + size and rva - start + length <= raw_size:
                return raw + rva - start
        raise Unreadable("address outside the sections")

    resource_rva, resource_size = directory(RESOURCE_DIRECTORY)
    if resource_rva and resource_size:
        try:
            info.update(version_resource(reader, offset_of(resource_rva, 16), offset_of))
        except (Unreadable, struct.error, UnicodeDecodeError):
            pass            # a cut-off download still tells its bits
    return info


def version_resource(reader, base, offset_of):
    """Type 16 (RT_VERSION), its first name, its first language: the
    VS_VERSIONINFO block's strings. Three fixed levels, so no loop."""
    def entries(at):
        named, ids = reader.unpack("<HH", at + 12)
        if named + ids > MAX_ENTRIES:
            raise Unreadable("too many resources")
        table = reader.read(at + 16, 8 * (named + ids))
        return [struct.unpack_from("<II", table, 8 * i) for i in range(named + ids)]

    for ident, target in entries(base):
        if ident != RT_VERSION or not target & 0x80000000:
            continue
        for _name, names in entries(base + (target & 0x7FFFFFFF))[:1]:
            if not names & 0x80000000:
                return {}
            for _lang, data in entries(base + (names & 0x7FFFFFFF))[:1]:
                if data & 0x80000000:
                    return {}
                rva, size = reader.unpack("<II", base + data)
                size = min(size, VERSION_LIMIT)
                return version_strings(reader.read(offset_of(rva, size), size))
    return {}


def version_strings(block):
    """The strings of the first StringTable in a VS_VERSIONINFO block.
    wType and wValueLength are set inconsistently by the tools that write
    installers (NSIS marks text binary), so it goes by the keys: a string's
    value is UTF-16 up to its NUL or the end of its block."""
    found = {}

    def walk(at, end, depth):
        if depth > 3:
            return
        while at + 6 <= end:
            length, value_length, _kind = struct.unpack_from("<HHH", block, at)
            if length < 6:
                return
            stop = min(at + length, end)
            key_end = at + 6
            while key_end + 2 <= stop and block[key_end:key_end + 2] != b"\0\0":
                key_end += 2
            key = block[at + 6:key_end].decode("utf-16-le", "replace")
            value_at = (key_end + 2 + 3) & ~3
            if key in VERSION_KEYS and value_length and value_at < stop:
                raw = block[value_at:stop]
                raw = raw[:len(raw) // 2 * 2]
                text = raw.decode("utf-16-le", "replace").split("\0")[0].strip()
                if text:
                    found.setdefault(VERSION_KEYS[key], text)
            if key == "VS_VERSION_INFO":
                walk((value_at + value_length + 3) & ~3, stop, depth + 1)
            elif key == "StringFileInfo" or (len(key) == 8 and all(c in "0123456789abcdefABCDEF" for c in key)):
                walk(value_at, stop, depth + 1)
            at = (at + length + 3) & ~3

    walk(0, len(block), 0)
    return found


# --- .msi (OLE compound file) ----------------------------------------------------

class Compound:
    """The streams of an OLE compound file, read sector by sector."""

    def __init__(self, reader):
        self.reader = reader
        header = reader.read(0, 512)
        if header[:8] != CFB_MAGIC:
            raise Unreadable("not a compound file")
        shift, = struct.unpack_from("<H", header, 30)
        if shift not in (9, 12):
            raise Unreadable("unknown sector size")
        self.size = 1 << shift
        self.per = self.size // 4
        self.dir_start, = struct.unpack_from("<I", header, 48)
        self.mini_cutoff, = struct.unpack_from("<I", header, 56)
        self.minifat_start, _count, difat_start, difat_count = struct.unpack_from("<IIII", header, 60)
        self.difat = [n for n in struct.unpack_from("<109I", header, 76) if n < CFB_END]
        seen = set()
        while difat_start < CFB_END and difat_count > 0:
            if difat_start in seen:
                raise Unreadable("a loop in the sector table")
            seen.add(difat_start)
            more = struct.unpack(f"<{self.per}I", self.sector(difat_start))
            self.difat += [n for n in more[:-1] if n < CFB_END]
            difat_start, difat_count = more[-1], difat_count - 1
        self.fat_sectors = {}
        self.root_chain = None

    def sector(self, number):
        return self.reader.read((number + 1) * self.size, self.size)

    def next_in(self, table_sectors, cache, number):
        """The sector after number in a FAT (or the mini FAT)."""
        index = number // self.per
        if index >= len(table_sectors):
            raise Unreadable("sector outside the table")
        if index not in cache:
            cache[index] = struct.unpack(f"<{self.per}I", self.sector(table_sectors[index]))
        return cache[index][number % self.per]

    def chain(self, start, table=None, cache=None):
        """Sector numbers of a stream from start, stopping at a loop."""
        table = self.difat if table is None else table
        cache = self.fat_sectors if cache is None else cache
        seen = []
        while start < CFB_END:
            if start in seen:
                raise Unreadable("a loop in a stream")
            seen.append(start)
            start = self.next_in(table, cache, start)
        return seen

    def entries(self):
        """(name, class, start, length) of each directory entry."""
        for number in self.chain(self.dir_start):
            data = self.sector(number)
            for at in range(0, self.size, 128):
                name_length, = struct.unpack_from("<H", data, at + 64)
                name = data[at:at + max(0, min(name_length, 64) - 2)].decode("utf-16-le", "replace")
                clsid = data[at + 80:at + 96]
                start, length = struct.unpack_from("<IQ", data, at + 116)
                yield name, clsid, start, length

    def read_stream(self, start, length, root):
        if length > STREAM_LIMIT:
            raise Unreadable("stream too long")
        if length >= self.mini_cutoff:
            return b"".join(self.sector(n) for n in self.chain(start))[:length]
        # A small stream lives in the mini stream (the root's chain), in 64-byte sectors.
        if self.root_chain is None:
            self.root_chain = self.chain(root[2])
        minifat = self.chain(self.minifat_start)
        out = b""
        for mini in self.chain(start, minifat, {}):
            at = mini * 64
            index = at // self.size
            if index >= len(self.root_chain):
                raise Unreadable("mini sector outside the mini stream")
            data = self.sector(self.root_chain[index])
            out += data[at % self.size:at % self.size + 64]
            if len(out) >= length:
                break
        return out[:length]


def msi_info(reader):
    """Product, maker and whether it is signed, from SummaryInformation."""
    if reader.read(0, 8) != CFB_MAGIC:
        return None
    compound = Compound(reader)
    entries = list(compound.entries())
    if not entries or entries[0][1] != MSI_CLSID:
        return None             # a compound file, but not an installer (an old .doc)
    info = {"kind": "msi", "signed": any(name == "\x05DigitalSignature" for name, *_ in entries)}
    for name, _clsid, start, length in entries:
        if name == "\x05SummaryInformation":
            info.update(summary(compound.read_stream(start, length, entries[0])))
            break
    return info


def summary(stream):
    """Strings of a property set stream (MS-OLEPS), in its code page."""
    try:
        offset, = struct.unpack_from("<I", stream, 44)
        count, = struct.unpack_from("<I", stream, offset + 4)
        props, codepage = {}, "cp1252"
        for i in range(min(count, 64)):
            pid, at = struct.unpack_from("<II", stream, offset + 8 + 8 * i)
            kind, = struct.unpack_from("<I", stream, offset + at)
            if pid == 1 and kind == 2:
                page, = struct.unpack_from("<H", stream, offset + at + 4)
                codepage = "utf-8" if page == 65001 else f"cp{page}"
            elif kind == 30 and pid in SUMMARY:
                length, = struct.unpack_from("<I", stream, offset + at + 4)
                props[pid] = stream[offset + at + 8:offset + at + 8 + min(length, 1024)]
    except struct.error:
        return {}
    out = {}
    for pid, raw in props.items():
        raw = raw.split(b"\0")[0]
        try:
            text = raw.decode(codepage, "replace")
        except LookupError:
            text = raw.decode("latin-1")
        if text.strip():
            out[SUMMARY[pid]] = text.strip()
    return out


# --- .lnk (Shell Link) ------------------------------------------------------------

def lnk_info(reader):
    """Where a Windows shortcut pointed."""
    header = reader.read(0, 0x4C) if reader.size >= 0x4C else b""
    if header[:4] != b"\x4c\0\0\0" or header[4:20] != LNK_CLSID:
        return None
    flags, = struct.unpack_from("<I", header, 0x14)
    info = {"kind": "lnk"}
    at = 0x4C
    if flags & 0x1:                     # HasLinkTargetIDList
        size, = reader.unpack("<H", at)
        at += 2 + size
    if flags & 0x2:                     # HasLinkInfo
        size, = reader.unpack("<I", at)
        if size > LNK_INFO_LIMIT:
            raise Unreadable("link info too long")
        block = reader.read(at, size)
        info.update(link_target(block))
        at += size
    unicode = bool(flags & 0x80)
    for flag, key in ((0x4, "description"), (0x8, "relative")):
        if flags & flag:
            count, = reader.unpack("<H", at)
            width = 2 if unicode else 1
            raw = reader.read(at + 2, count * width)
            text = raw.decode("utf-16-le" if unicode else "cp1252", "replace")
            if text:
                info[key] = text
            at += 2 + count * width
    if "target" not in info and "relative" in info:
        info["target"] = info["relative"]
    info.pop("relative", None)
    return info


def link_target(block):
    """LocalBasePath + CommonPathSuffix of a LinkInfo block (MS-SHLLINK)."""
    try:
        header_size, = struct.unpack_from("<I", block, 4)
        base_at, = struct.unpack_from("<I", block, 16)
        suffix_at, = struct.unpack_from("<I", block, 24)
        if header_size >= 0x24:
            base_u, suffix_u = struct.unpack_from("<II", block, 28)
            if base_u:
                base = block[base_u:].decode("utf-16-le", "replace").split("\0")[0]
                suffix = block[suffix_u:].decode("utf-16-le", "replace").split("\0")[0] if suffix_u else ""
                return {"target": base + suffix} if base else {}
    except struct.error:
        return {}
    def ansi(at):
        return block[at:].split(b"\0")[0].decode("cp1252", "replace") if 0 < at < len(block) else ""
    base = ansi(base_at)
    return {"target": base + ansi(suffix_at)} if base else {}


# --- .msix (a zip with a manifest) -------------------------------------------------

def msix_info(path):
    """Name and maker from an .msix (or .appx, or a bundle's) manifest."""
    try:
        with zipfile.ZipFile(path) as package:
            names = set(package.namelist())
            manifest = next((m for m in MSIX_MANIFESTS if m in names), None)
            if not manifest:
                return None
            with package.open(manifest) as f:
                data = f.read(MANIFEST_LIMIT + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError):
        return None
    if len(data) > MANIFEST_LIMIT:
        raise Unreadable("manifest too long")
    # No document type, so no entities to expand; then expat reads it.
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise Unreadable("manifest with a document type")
    from xml.etree import ElementTree
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise Unreadable("manifest isn't XML")
    info = {"kind": "msix"}
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "Identity" and "name" not in info:
            info["name"] = element.get("Name", "")
            publisher = element.get("Publisher", "")
            cn = re.search(r"CN=([^,]+)", publisher)
            if cn:
                info.setdefault("maker", cn.group(1).strip().strip('"'))
            info["bits"] = {"x86": 32, "x64": 64, "arm64": 64}.get(element.get("ProcessorArchitecture", ""))
        elif tag in ("DisplayName", "PublisherDisplayName") and element.text:
            text = element.text.strip()
            if text and not text.startswith("ms-resource:"):
                info["product" if tag == "DisplayName" else "maker"] = text
    info.setdefault("product", info.pop("name", "") or None)
    info.pop("name", None)
    return {k: v for k, v in info.items() if v is not None}


def identify(path):
    """What a file says it is: {"kind": exe, msi, msix, lnk or unknown, ...}.
    Raises OSError only when the file can't be opened. Only a regular file is
    opened: a FIFO would block the open."""
    if not stat.S_ISREG(os.stat(path).st_mode):
        return {"kind": "unknown"}
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        magic = f.read(8)
        info = None
        try:
            if magic[:2] == b"MZ":
                info = pe_info(Reader(f, size, PE_BUDGET))
            elif magic == CFB_MAGIC:
                info = msi_info(Reader(f, size, MSI_BUDGET))
            elif magic[:4] == b"\x4c\0\0\0":
                info = lnk_info(Reader(f, size, LNK_INFO_LIMIT * 2))
        except (Unreadable, struct.error, UnicodeDecodeError):
            info = None
    if magic[:4] == b"PK\x03\x04":
        try:
            info = msix_info(path)
        except Unreadable:
            info = None
    return info or {"kind": "unknown"}


# --- The list ----------------------------------------------------------------------

def load_list(path=None):
    """The Windows apps list's entries; none when it is missing or broken."""
    try:
        with open(path or APPS_LIST, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("id") and e.get("name")]


def plain_name(filename):
    """A downloaded file's name, without the " (1)" a second download adds."""
    name = os.path.basename(filename).casefold()
    return re.sub(r" ?\(\d+\)(?=\.[^.]+$)", "", name)


def maker_matches(entry, maker):
    maker = (maker or "").casefold()
    return bool(maker) and any(m.casefold() in maker for m in entry.get("makers", []))


def match(info, filename, entries):
    """The list entry a file is, or None. Its name (a shell pattern) with its
    maker, or its product with its maker when the file was renamed; a name
    alone only when the file has no maker (VLC's installer)."""
    if info.get("kind") not in ("exe", "msi", "msix"):
        return None
    name = plain_name(filename)
    maker = info.get("maker")
    for entry in entries:
        if any(fnmatch.fnmatchcase(name, p.casefold()) for p in entry.get("files", [])):
            if not maker or not entry.get("makers") or maker_matches(entry, maker):
                return entry
    product = (info.get("product") or "").casefold()
    if product and maker:
        for entry in entries:
            if maker_matches(entry, maker) and any(p.casefold() in product for p in entry.get("products", [])):
                return entry
    return None


def phrase(text):
    """Text to compare: case, spaces and dashes aside ("7 Zip" is "7-zip")."""
    return " ".join(w for w in re.split(r"[\s\-]+", text.casefold()) if w)


def lookup(words, entries):
    """Entries whose name, a product or one of the words is what was typed:
    "photoshop", "ms word", "excel" (not "photo", which starts too many).
    Those named by their name or a product first; each a copy with "by":
    "name" or "words" (Software shows matches by words only when there are
    few: "excel" is one program's, "music" many's)."""
    query = phrase(" ".join(words))
    if not query:
        return []
    by_name, by_words = [], []
    for entry in entries:
        if query in {phrase(t) for t in [entry["name"], *entry.get("products", [])]}:
            by_name.append(dict(entry, by="name"))
        elif query in {phrase(t) for t in entry.get("words", [])}:
            by_words.append(dict(entry, by="words"))
    return by_name + by_words


def translated(entry):
    """An entry with its sentences in the user's language (po/extract's list),
    for lookup --json."""
    entry = dict(entry)
    if entry.get("group"):
        entry["name"] = _(entry["name"])
    if entry.get("web"):
        entry["web"] = dict(entry["web"], name=_(entry["web"]["name"]))
    if entry.get("similar"):
        entry["similar"] = [dict(s, why=_(s["why"])) if s.get("why") else s for s in entry["similar"]]
    if entry.get("note"):
        entry["note"] = _(entry["note"])
    return entry


def search_words(info, filename):
    """What to search Software for: the product, or the file's name without
    setup, versions and the like."""
    product = info.get("product") or ""
    if product and "install" not in product.casefold() and "setup" not in product.casefold():
        return product
    stem = os.path.splitext(plain_name(filename))[0]
    words = [w for w in re.split(r"[\s_.\-()]+", stem) if w and not NOISE.match(w)]
    return " ".join(words[:3]) or stem


def wine_state(path=None, root=None):
    """missing, 64-bit (no 32-bit part) or ready."""
    if not shutil.which("wine", path=path):
        return "missing"
    return "ready" if os.path.exists((PREFIX if root is None else root) + WINE_32) else "64-bit"


def answer(info, entry, wine):
    """What the window offers, in order: [(action, value)], action one of
    install, web, similar, search, wine-run, wine-get (ADR-003). wine-get's
    value is "32-bit" when Wine is there without the part this file needs."""
    kind = info.get("kind")
    if kind == "lnk":
        return []
    actions = []
    if entry and entry.get("linux"):
        return [("install", entry["linux"])]
    if entry:
        if entry.get("web"):
            actions.append(("web", entry["web"]))
        actions += [("similar", s) for s in entry.get("similar", [])]
    else:
        actions.append(("search", None))
    if kind in ("exe", "msi") and not (entry and entry.get("wine") == "no"):
        runs = wine == "ready" or (wine == "64-bit" and info.get("bits") == 64)
        if runs:
            actions.append(("wine-run", None))
        else:
            actions.append(("wine-get", "32-bit" if wine == "64-bit" else None))
    return actions


def wine_command(info, path):
    if info.get("kind") == "msi":
        return ["wine", "msiexec", "/i", path]
    return ["wine", "start", "/unix", path]


# --- Commands ---------------------------------------------------------------------

def cmd_identify(opts):
    entries = load_list()
    results = []
    for path in opts.files:
        info = identify(path)
        entry = match(info, path, entries)
        info["match"] = entry["id"] if entry else None
        results.append((path, info))
    if opts.json:
        print(json.dumps({path: info for path, info in results}, indent=2, ensure_ascii=False))
    else:
        for path, info in results:
            bits = info.get("bits")
            print("\t".join([info["kind"], str(bits) if bits else "-", info.get("product", "-"),
                             info.get("maker", "-"), info.get("description", "-"),
                             info.get("original", "-") if info["kind"] != "lnk" else info.get("target", "-"),
                             "signed" if info.get("signed") else "-", info["match"] or "-", path]))
    return 0


def cmd_lookup(opts):
    found = lookup(opts.words, load_list())
    if opts.json:
        print(json.dumps([translated(e) for e in found], indent=2, ensure_ascii=False))
    else:
        for entry in found:
            linux = entry.get("linux")
            print("\t".join([entry["id"], entry["name"],
                             f"{linux['source']}:{linux['app']}" if linux else "-",
                             entry.get("web", {}).get("url", "-")]))
    return 0


def cmd_open(opts):
    path = os.path.abspath(opts.file)
    info = identify(path)
    entry = match(info, path, load_list())
    return OpenWindow.run(path, info, entry)


# --- The window -------------------------------------------------------------------

def headline(info, entry, filename):
    """The window's sentences: what the file is, the list's note, and what
    follows."""
    text = _headline(info, entry, filename)
    if entry and entry.get("note"):
        text += " " + _(entry["note"])
    return text


def _headline(info, entry, filename):
    kind = info.get("kind")
    if kind == "lnk":
        target = info.get("target")
        if target:
            return _("{file} is a shortcut copied from Windows. It pointed to {target}. "
                     "Windows shortcuts don't work on FlickOS.").format(file=filename, target=target)
        return _("{file} is a shortcut copied from Windows. Windows shortcuts don't work on FlickOS.").format(
            file=filename)
    if kind == "unknown":
        return _("FlickOS can't read {file}. It may be a Windows program or a damaged download.").format(
            file=filename)
    if entry and entry.get("group"):
        # Translators: {name} is a kind of program, such as "antivirus software".
        return _("{file} is {name} for Windows.").format(file=filename, name=_(entry["name"]))
    if entry and entry.get("linux"):
        return _("{file} installs {name}, a Windows program. {name} is also made for FlickOS.").format(
            file=filename, name=entry["name"])
    if entry:
        return _("{file} installs {name}, a Windows program that isn't made for FlickOS.").format(
            file=filename, name=entry["name"])
    product, maker = info.get("product"), info.get("maker")
    said = ""
    if product and maker:
        said = " " + _("It says it is {product}, by {maker}.").format(product=product, maker=maker)
    elif product:
        said = " " + _("It says it is {product}.").format(product=product)
    return _("FlickOS can't run Windows programs like {file} directly.").format(file=filename) + said


class OpenWindow(Builders):
    """The answer to a double-click on a Windows program (ADR-003)."""

    @classmethod
    def run(cls, path, info, entry):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import GLib
            GLib.set_prgname(APP_ID)
            from gi.repository import Gio, Gtk
        except (ImportError, ValueError) as error:
            print(f"flickos-switch: can't open the window ({error})", file=sys.stderr)
            return 1
        ok, _argv = Gtk.init_check(sys.argv)
        if not ok:
            print("flickos-switch: can't open the window: no display", file=sys.stderr)
            return 1
        import locale
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass
        window = cls(Gtk, Gio, GLib, path, info, entry)
        window.win.show_all()
        Gtk.main()
        return 0

    def __init__(self, Gtk, Gio, GLib, path, info, entry):
        self.Gtk, self.Gio, self.GLib = Gtk, Gio, GLib
        self.path, self.info, self.entry = path, info, entry
        self.win = Gtk.Window(title=_("Windows Program"), icon_name=ICON)
        self.win.connect("destroy", lambda _w: Gtk.main_quit())
        self.win.connect("key-press-event", self.on_key)
        self.stack = Gtk.Stack()
        self.win.add(self.stack)
        self.fill()

    def on_key(self, _win, event):
        from gi.repository import Gdk
        if event.keyval == Gdk.KEY_Escape:
            self.win.destroy()
            return True
        return False

    def fill(self):
        Gtk = self.Gtk
        filename = os.path.basename(self.path)
        box = self.page("answer")
        box.pack_start(self.heading(filename), False, False, 0)
        box.pack_start(self.label(headline(self.info, self.entry, filename)), False, False, 0)
        actions = answer(self.info, self.entry, wine_state())
        if actions:
            frame, listbox = self.framed_list()
            for action, value in actions:
                self.add_action(listbox, action, value, filename)
            box.pack_start(frame, False, False, 0)
        self.buttons(box, self.button(_("_Close"), self.win.destroy))
        self.win.set_default_size(560, 170 + 64 * len(actions))

    def add_action(self, listbox, action, value, filename):
        name = self.entry["name"] if self.entry else None
        if action == "install":
            title = _("Install {name}").format(name=name)
            self.row(listbox, title, _("Opens Software on its page."),
                     self.button(_("_Install"), lambda: self.software("--app", value["app"]), suggested=True))
        elif action == "web" and shutil.which(FIREFOX):
            self.row(listbox, _(value["name"]),
                     _("Opens in Firefox. To keep it as a web app, press the button at the right "
                       "of the address bar."),
                     self.button(_("_Open"), lambda: self.webapp(value["url"], name)))
        elif action == "web":
            self.row(listbox, _(value["name"]), _("Opens in the web browser. Nothing to install."),
                     self.button(_("_Open"), lambda: self.web(value["url"])))
        elif action == "similar":
            title = self.app_name(value)
            self.row(listbox, title, _(value["why"]) if value.get("why") else None,
                     self.button(_("_View"), lambda: self.software("--app", value["app"])))
        elif action == "search":
            words = search_words(self.info, filename)
            self.row(listbox, _("Search Software for “{words}”").format(words=words),
                     _("Many Windows programs have a version for FlickOS, or an app that does the same."),
                     self.button(_("_Search"), lambda: self.software("--search", words), suggested=True))
        elif action == "wine-run":
            self.row(listbox, _("Try with Wine"), _("Many Windows programs don't work with Wine."),
                     self.button(_("_Try"), self.wine))
        elif action == "wine-get" and value == "32-bit":
            self.row(listbox, _("Try with Wine"),
                     _("This program needs Wine's 32-bit part. Software can add it."),
                     self.button(_("_Get Wine"), lambda: self.software("--app", WINE_APP)))
        elif action == "wine-get":
            self.row(listbox, _("Try with Wine"),
                     _("Wine runs some Windows programs. Software can install it."),
                     self.button(_("_Get Wine"), lambda: self.software("--app", WINE_APP)))

    def app_name(self, similar):
        """An app's name for its row: the list's, else its ID's last part."""
        return similar.get("name") or similar["app"].rsplit(".", 1)[-1].replace("-", " ").title()

    def detached(self, args, env=None):
        """Start args on its own (CODE-7), then close the window."""
        try:
            subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, env=env)
        except OSError as error:
            dialog = self.Gtk.MessageDialog(transient_for=self.win, modal=True,
                                            message_type=self.Gtk.MessageType.ERROR,
                                            buttons=self.Gtk.ButtonsType.CLOSE,
                                            text=_("Couldn't start {program}.").format(program=args[0]))
            dialog.format_secondary_text(error.strerror or str(error))
            dialog.run()
            dialog.destroy()
            return
        self.win.destroy()

    def software(self, how, value):
        self.detached(["flickos-software", "show", how, value])

    def web(self, url):
        self.detached(["xdg-open", url])

    def webapp(self, url, name):
        """Firefox's web apps (phase 3): flickos-switch webapp add."""
        self.detached(["flickos-switch", "webapp", "add", url, "--name", name])

    def wine(self):
        env = dict(os.environ, WINEDEBUG="-all")
        self.detached(wine_command(self.info, self.path), env)
