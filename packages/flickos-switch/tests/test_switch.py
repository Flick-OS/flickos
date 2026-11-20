"""Tests for usr/bin/flickos-switch. Run: python3 -m unittest discover -s tests

No root, udisks2 or display: a Windows disk is a temporary folder laid out
as the spike's fake disk, and NTFS attributes (which a tmpfs doesn't have)
come from a dictionary through read_attributes(). Every outside path
(home, XDG folders, /proc, $XDG_RUNTIME_DIR) points into temporary folders.
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
PO = os.path.join(PACKAGE, "po")

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_switch", os.path.join(PACKAGE, "usr/bin/flickos-switch"))
fs = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fs)

OLD = 1577880000
NEWER = 1717243200
REPARSE = fs.REPARSE_POINT
HIDDEN_SYSTEM = fs.HIDDEN | fs.SYSTEM


class FakeDisk:
    """A Windows C: in a temporary folder, with NTFS attributes by path."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="fake-c-")
        self.attributes = {}

    def file(self, path, data=b"x", date=NEWER, attributes=None, size=None):
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            if size is not None:
                f.truncate(size)          # a hole: no blocks on disk
            else:
                f.write(data)
        os.utime(full, (date, date))
        if attributes is not None:
            self.attributes[full] = attributes
        return full

    def folder(self, path, attributes=None):
        full = os.path.join(self.root, path)
        os.makedirs(full, exist_ok=True)
        if attributes is not None:
            self.attributes[full] = attributes
        return full

    def read_attributes(self, path):
        return self.attributes.get(path)

    def cleanup(self):
        for folder, dirs, _files in os.walk(self.root):
            for name in dirs:
                os.chmod(os.path.join(folder, name), 0o755)
        shutil.rmtree(self.root, ignore_errors=True)


def windows_disk():
    """The spike's fake C: (make-fake-windows.py's table, the parts that matter)."""
    disk = FakeDisk()
    disk.file("Windows/System32/ntoskrnl.exe", b"MZ")
    disk.file("hiberfil.sys", b"wake" + b"\0" * 60, attributes=HIDDEN_SYSTEM)
    disk.file("Users/desktop.ini", b"[.ShellClassInfo]", attributes=HIDDEN_SYSTEM)
    disk.file("Users/Default/NTUSER.DAT", b"regf", attributes=fs.HIDDEN)
    disk.file("Users/Public/Documents/desktop.ini", b"ini", attributes=HIDDEN_SYSTEM)
    disk.folder("Users/All Users", attributes=REPARSE | HIDDEN_SYSTEM)
    # Jon: ordinary folders.
    disk.file("Users/Jon/NTUSER.DAT", b"regf", attributes=HIDDEN_SYSTEM)
    disk.file("Users/Jon/Desktop/desktop.ini", b"ini", attributes=HIDDEN_SYSTEM)
    disk.file("Users/Jon/Desktop/Shopping list.txt", b"milk\r\n", date=NEWER)
    disk.file("Users/Jon/Desktop/Google Chrome.lnk", b"L\0\0\0")
    disk.file("Users/Jon/Documents/Résumé 2025.docx", b"PK" + b"r" * 100, date=NEWER)
    disk.file("Users/Jon/Documents/Taxes/2024/receipt.pdf", b"%PDF" + b"p" * 200, date=OLD)
    disk.folder("Users/Jon/Documents/My Music", attributes=REPARSE | HIDDEN_SYSTEM)
    disk.file("Users/Jon/Pictures/Holiday/IMG_0001.jpg", b"\xff\xd8" + b"j" * 300, date=OLD)
    disk.file("Users/Jon/Pictures/Holiday/Thumbs.db", b"t", attributes=HIDDEN_SYSTEM)
    disk.file("Users/Jon/Pictures/家族.jpg", b"\xff\xd8" + b"k" * 50)
    disk.folder("Users/Jon/My Documents", attributes=REPARSE | HIDDEN_SYSTEM)
    disk.file("Users/Jon/AppData/Local/Google/Chrome/User Data/Default/Bookmarks", json.dumps(
        {"roots": {"bookmark_bar": {"children": [{"type": "url", "name": "Gmail",
                                                   "url": "https://mail.google.com/"}]},
                   "other": {"children": []}}}).encode(), attributes=None)
    # Maria: OneDrive's folder backup.
    disk.file("Users/Maria/NTUSER.DAT", b"regf", attributes=HIDDEN_SYSTEM)
    disk.file("Users/Maria/Documents/desktop.ini", b"ini", attributes=HIDDEN_SYSTEM)
    disk.file("Users/Maria/OneDrive/Documents/Notes.txt", b"kept", attributes=REPARSE | 0x20)
    disk.file("Users/Maria/OneDrive/Documents/Budget.xlsx", size=3 * 1024 * 1024, attributes=REPARSE | 0x20)
    disk.file("Users/Maria/OneDrive/Documents/Tiny.txt", size=100, attributes=REPARSE | 0x20)
    disk.file("Users/Maria/OneDrive/Pictures/Beach.jpg", b"\xff\xd8" + b"b" * 5000, attributes=REPARSE | 0x20)
    disk.file("Users/Maria/OneDrive/Pictures/Recalled.jpg", b"\0" * 10,
              attributes=REPARSE | fs.RECALL_ON_DATA_ACCESS)
    return disk


class DiskTest(unittest.TestCase):
    """Tests with a fake disk, a temporary home and XDG folders."""

    def setUp(self):
        self.disk = windows_disk()
        self.addCleanup(self.disk.cleanup)
        self.home = tempfile.mkdtemp(prefix="home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        patches = [
            mock.patch.object(fs, "read_attributes", self.disk.read_attributes),
            mock.patch.object(fs, "user_dir", lambda _xdg, fallback: os.path.join(self.home, fallback)),
            mock.patch.object(fs, "PROC", "/nonexistent/proc"),
            mock.patch.dict(os.environ, {"HOME": self.home, "XDG_RUNTIME_DIR": self.home}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def path(self, rel):
        return os.path.join(self.disk.root, rel)


class FindingTest(DiskTest):
    def test_windows_is_recognized(self):
        self.assertTrue(fs.is_windows(self.disk.root))
        self.assertFalse(fs.is_windows(self.path("Users")))

    def test_accounts_leave_out_public_default_and_junctions(self):
        self.assertEqual(list(fs.accounts(self.disk.root)), ["Jon", "Maria"])

    def test_names_match_without_case(self):
        self.assertEqual(fs.child(self.disk.root, "WINDOWS"), self.path("Windows"))
        self.assertIsNone(fs.child(self.disk.root, "Missing"))

    def test_hibernation(self):
        self.assertFalse(fs.hibernated(self.disk.root))
        with open(self.path("hiberfil.sys"), "r+b") as f:
            f.write(b"HIBR")
        self.assertTrue(fs.hibernated(self.disk.root))

    def test_junctions_are_never_opened(self):
        opened = []
        real = os.scandir

        def scandir(path):
            opened.append(path)
            return real(path)

        with mock.patch.object(fs.os, "scandir", scandir):
            list(fs.walk(self.path("Users/Jon/Documents")))
        self.assertNotIn(self.path("Users/Jon/Documents/My Music"), opened)
        self.assertIn(self.path("Users/Jon/Documents/Taxes/2024"), opened)

    def test_links_are_skipped(self):
        os.symlink(self.path("Users/Jon/Pictures"), self.path("Users/Jon/Documents/Pics"))
        paths = [p for p, _s, _k in fs.walk(self.path("Users/Jon/Documents"))]
        self.assertFalse(any("Pics" in p for p in paths))

    def test_kinds(self):
        kinds = {os.path.relpath(p, self.disk.root): k for p, _s, k in fs.walk(self.path("Users"))}
        self.assertEqual(kinds["Users/Jon/Desktop/desktop.ini"], "system")
        self.assertEqual(kinds["Users/Jon/Pictures/Holiday/Thumbs.db"], "system")
        self.assertEqual(kinds["Users/Jon/Desktop/Google Chrome.lnk"], "shortcut")
        self.assertEqual(kinds["Users/Jon/Documents/Résumé 2025.docx"], "copy")
        self.assertEqual(kinds["Users/Maria/OneDrive/Documents/Notes.txt"], "copy", "kept on disk")
        self.assertEqual(kinds["Users/Maria/OneDrive/Pictures/Beach.jpg"], "copy", "kept on disk")
        self.assertEqual(kinds["Users/Maria/OneDrive/Documents/Budget.xlsx"], "cloud", "no data")
        self.assertEqual(kinds["Users/Maria/OneDrive/Documents/Tiny.txt"], "cloud", "small, all zeros")
        self.assertEqual(kinds["Users/Maria/OneDrive/Pictures/Recalled.jpg"], "cloud", "recall attribute")

    def test_small_kept_file_without_blocks_is_copied(self):
        """NTFS keeps small files in its file table: no blocks, real contents."""
        path = self.path("Users/Maria/OneDrive/Documents/Notes.txt")
        st = mock.Mock(st_size=4, st_blocks=0)
        self.assertFalse(fs.cloud_only(path, REPARSE, st))

    def test_unreadable_folder_is_reported_not_fatal(self):
        locked = self.disk.folder("Users/Jon/Documents/Locked")
        os.chmod(locked, 0)
        if os.access(locked, os.R_OK):
            self.skipTest("running as root")
        found = list(fs.walk(self.path("Users/Jon/Documents")))
        self.assertTrue(any(k.startswith("unreadable") for _p, _s, k in found))
        self.assertTrue(any(k == "copy" for _p, _s, k in found))

    def test_scan(self):
        result = fs.scan_root(self.disk.root)
        maria = next(a for a in result["accounts"] if a["account"] == "Maria")
        folders = {f["folder"]: f for f in maria["folders"]}
        self.assertEqual(folders["Documents"]["files"], 1)
        self.assertEqual(folders["Documents"]["cloud"], 2)
        self.assertEqual(folders["Pictures"]["files"], 1)
        self.assertEqual(folders["Pictures"]["cloud"], 1)
        jon = next(a for a in result["accounts"] if a["account"] == "Jon")
        jon_folders = {f["folder"]: f for f in jon["folders"]}
        self.assertEqual(jon_folders["Documents"]["files"], 2)
        self.assertEqual(jon_folders["Desktop"]["shortcut"], 1)
        self.assertEqual(jon["bookmarks"], 1)
        self.assertEqual(maria["bookmarks"], 0)

    def test_not_windows_is_an_error(self):
        with self.assertRaises(fs.SwitchError):
            fs.scan_root(self.path("Users"))

    def test_onedrive_for_business_folder(self):
        self.disk.file("Users/Jon/OneDrive - Contoso/Documents/Plan.docx", b"PK")
        found = fs.sources(self.path("Users/Jon"), "Documents")
        self.assertEqual(len(found), 2)


class CopyTest(DiskTest):
    def copy(self, account="Maria", folders=("Documents", "Pictures"), **kw):
        events = []
        copier = fs.Copier(self.disk.root, account, list(folders), report=events.append, **kw)
        return copier.run(), events

    def test_copies_into_xdg_folders_and_keeps_dates(self):
        summary, _events = self.copy("Jon", ["Documents", "Pictures"])
        receipt = os.path.join(self.home, "Documents/Taxes/2024/receipt.pdf")
        self.assertTrue(os.path.isfile(receipt))
        self.assertEqual(int(os.stat(receipt).st_mtime), OLD)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "Pictures/家族.jpg")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "Pictures/Holiday/Thumbs.db")))
        self.assertEqual(summary["copied"], 4)

    def test_onedrive_merges_and_cloud_files_are_listed(self):
        summary, _events = self.copy()
        self.assertTrue(os.path.isfile(os.path.join(self.home, "Documents/Notes.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "Documents/Budget.xlsx")))
        self.assertEqual(summary["cloud"], 3)
        self.assertIn("Documents/Budget.xlsx", summary["cloud_files"])

    def test_second_copy_finds_everything_there(self):
        self.copy()
        summary, _events = self.copy()
        self.assertEqual(summary["copied"], 0)
        self.assertEqual(summary["same"], 2)

    def test_a_different_file_is_never_overwritten(self):
        self.copy()
        mine = os.path.join(self.home, "Documents/Notes.txt")
        with open(mine, "w") as f:
            f.write("my own notes")
        self.copy()
        with open(mine) as f:
            self.assertEqual(f.read(), "my own notes")
        copied = os.path.join(self.home, "Documents/Notes (from Windows).txt")
        self.assertTrue(os.path.isfile(copied))
        summary, _events = self.copy()
        self.assertEqual(summary["copied"], 0, "the (from Windows) copy is found again")

    def test_numbered_names(self):
        folder = tempfile.mkdtemp(dir=self.home)
        st = os.stat(self.path("Users/Maria/OneDrive/Documents/Notes.txt"))
        for name in ("a.txt", "a (from Windows).txt"):
            with open(os.path.join(folder, name), "w") as f:
                f.write("other")
        target, state = fs.target_for(os.path.join(folder, "a.txt"), st)
        self.assertEqual((os.path.basename(target), state), ("a (from Windows 2).txt", "new"))

    def test_source_is_never_written(self):
        for folder, dirs, files in os.walk(self.disk.root):
            for name in files:
                os.chmod(os.path.join(folder, name), 0o444)
            os.chmod(folder, 0o555)
        summary, _events = self.copy("Jon", ["Documents", "Pictures", "Desktop"], bookmarks=True)
        self.assertEqual(summary["failed"], [])
        self.assertGreater(summary["copied"], 0)

    def test_unreadable_file_is_listed_and_the_rest_copied(self):
        os.chmod(self.path("Users/Jon/Documents/Résumé 2025.docx"), 0)
        if os.access(self.path("Users/Jon/Documents/Résumé 2025.docx"), os.R_OK):
            self.skipTest("running as root")
        summary, events = self.copy("Jon", ["Documents"])
        self.assertEqual(summary["copied"], 1)
        self.assertEqual(len(summary["failed"]), 1)
        self.assertTrue(any(e["event"] == "failed" for e in events))
        self.assertFalse(any(name.endswith(".part") for _f, _d, names in os.walk(self.home) for name in names))

    def test_not_enough_space(self):
        fake = mock.Mock(f_bavail=1, f_frsize=1)
        with mock.patch.object(fs.os, "statvfs", lambda _p: fake):
            with self.assertRaises(fs.SwitchError):
                self.copy("Jon", ["Documents"])
        self.assertFalse(os.path.exists(os.path.join(self.home, "Documents")))

    def test_stop_ends_after_the_current_file(self):
        copier = fs.Copier(self.disk.root, "Jon", ["Documents", "Pictures"])
        events = []

        def report(event):
            events.append(event)
            if event["event"] == "file":
                copier.stop = True

        copier.report = report
        summary = copier.run()
        self.assertTrue(summary["stopped"])
        self.assertEqual(summary["copied"], 1)

    def test_live_copies_into_files_from_windows(self):
        drive = tempfile.mkdtemp(dir=self.home)
        summary, _events = self.copy("Jon", ["Documents"], to=drive)
        self.assertTrue(os.path.isfile(os.path.join(drive, "Files from Windows/Jon/Documents/Taxes/2024/receipt.pdf")))
        self.assertEqual(summary["destination"], os.path.join(drive, "Files from Windows", "Jon"))

    def test_fat_refuses_large_files_before_copying(self):
        drive = tempfile.mkdtemp(dir=self.home)
        with mock.patch.object(fs, "filesystem_type", lambda _p: "vfat"), \
                mock.patch.object(fs, "FAT_LIMIT", 150):
            summary, _events = self.copy("Jon", ["Documents"], to=drive)
        self.assertEqual(summary["too_big"], ["Documents/Taxes/2024/receipt.pdf"])
        self.assertEqual(summary["copied"], 1)

    def test_bookmarks(self):
        summary, _events = self.copy("Jon", ["Desktop"], bookmarks=True)
        path = os.path.join(self.home, "Documents", fs.BOOKMARKS_FILE)
        self.assertEqual(summary["bookmarks"], path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('<A HREF="https://mail.google.com/">Gmail</A>', text)
        again, _events = self.copy("Jon", ["Desktop"], bookmarks=True)
        self.assertEqual(again["bookmarks"], path, "the same file isn't written twice")

    def test_events(self):
        _summary, events = self.copy("Jon", ["Documents"])
        self.assertEqual(events[0]["event"], "plan")
        self.assertEqual(events[0]["files"], 2)
        self.assertEqual(events[-1]["event"], "done")
        self.assertEqual(events[-2]["done"], events[0]["bytes"])
        json.dumps(events)

    def test_unknown_account_and_folder(self):
        with self.assertRaises(fs.SwitchError):
            fs.Copier(self.disk.root, "Nobody", ["Documents"])
        with self.assertRaises(fs.SwitchError):
            fs.Copier(self.disk.root, "Jon", ["AppData"])


class BookmarksTest(unittest.TestCase):
    def test_folders_escaping_and_only_web_addresses(self):
        data = {"roots": {"bookmark_bar": {"children": [
            {"type": "folder", "name": "News & <more>", "children": [
                {"type": "url", "name": "A \"quote\"", "url": "https://example.com/?a=1&b=2",
                 "date_added": "13300000000000000"}]},
            {"type": "url", "name": "Script", "url": "javascript:alert(1)"}]},
            "other": {"children": []}}}
        text = fs.bookmarks_html([("Chrome (Jon)", data)])
        self.assertIn("<H3>Chrome (Jon)</H3>", text)
        self.assertIn("<H3>Bookmarks bar</H3>", text)
        self.assertIn("News &amp; &lt;more&gt;", text)
        self.assertIn('HREF="https://example.com/?a=1&amp;b=2" ADD_DATE="1655526400"', text)
        self.assertNotIn("javascript", text)
        self.assertNotIn("Other bookmarks", text, "empty roots are left out")


class UdisksTest(unittest.TestCase):
    def objects(self):
        def block(device, kind, size=100, drive="/org/freedesktop/UDisks2/drives/ssd", **extra):
            return dict({"Device": list(device.encode()) + [0], "IdType": kind, "Size": size,
                         "Drive": drive, "IdLabel": "", "HintIgnore": False,
                         "CryptoBackingDevice": "/"}, **extra)

        prefix = "/org/freedesktop/UDisks2/block_devices/"
        return {
            "/org/freedesktop/UDisks2/drives/ssd": {fs.DRIVE: {"Vendor": "Samsung", "Model": "SSD 860",
                                                               "Removable": False}},
            prefix + "sda1": {fs.BLOCK: block("/dev/sda1", "vfat"), fs.FILESYSTEM: {"MountPoints": []}},
            prefix + "sda3": {fs.BLOCK: block("/dev/sda3", "ntfs", 250), fs.FILESYSTEM: {"MountPoints": []},
                              fs.PARTITION: {"Type": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"}},
            prefix + "sda4": {fs.BLOCK: block("/dev/sda4", "ntfs", 5), fs.FILESYSTEM: {"MountPoints": []},
                              fs.PARTITION: {"Type": "de94bba4-06d1-4d40-a16a-bfd50179d6ac"}},
            prefix + "sdb1": {fs.BLOCK: block("/dev/sdb1", "BitLocker", 500),
                              fs.ENCRYPTED: {"CleartextDevice": "/"}},
            prefix + "sdc1": {fs.BLOCK: block("/dev/sdc1", "BitLocker", 400),
                              fs.ENCRYPTED: {"CleartextDevice": prefix + "dm_2d0"}},
            prefix + "dm_2d0": {fs.BLOCK: block("/dev/dm-0", "ntfs", 400, CryptoBackingDevice=prefix + "sdc1"),
                                fs.FILESYSTEM: {"MountPoints": [list(b"/media/jon/W") + [0]]}},
            prefix + "sdd1": {fs.BLOCK: block("/dev/sdd1", "ntfs", HintIgnore=True),
                              fs.FILESYSTEM: {"MountPoints": []}},
        }

    def test_candidates(self):
        found = {e["device"]: e for e in fs.windows_partitions(self.objects())}
        self.assertEqual(sorted(found), ["/dev/sda3", "/dev/sdb1", "/dev/sdc1"])
        self.assertEqual(found["/dev/sda3"]["state"], "ready")
        self.assertEqual(found["/dev/sda3"]["drive"], "Samsung SSD 860")
        self.assertEqual(found["/dev/sdb1"]["state"], "locked")
        self.assertEqual(found["/dev/sdc1"]["state"], "mounted")
        self.assertEqual(found["/dev/sdc1"]["mount"], "/media/jon/W")

    def test_resolve(self):
        entry = fs.resolve(self.objects(), "/dev/sda3")
        self.assertEqual(entry["object"], "/org/freedesktop/UDisks2/block_devices/sda3")
        with self.assertRaises(fs.SwitchError):
            fs.resolve(self.objects(), "/dev/sda1")

    def test_messages(self):
        error = mock.Mock(message="GDBus.Error:org.freedesktop.UDisks2.Error.NotAuthorizedCanObtain: Not authorized")
        self.assertEqual(fs.dbus_message(error), fs._("Permission to use the disk was refused or cancelled."))
        error = mock.Mock(message="GDBus.Error:org.freedesktop.UDisks2.Error.Failed: Error mounting: "
                                  "wrong fs type, bad option, bad superblock")
        self.assertIn("Shift", fs.dbus_message(error))
        error = mock.Mock(message="GDBus.Error:org.freedesktop.UDisks2.Error.Busy: Device is busy")
        self.assertEqual(fs.dbus_message(error), "Device is busy")

    def test_remembered_mounts(self):
        runtime = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, runtime, True)
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}):
            fs.remember("mounted", "/org/freedesktop/UDisks2/block_devices/sda3")
            self.assertEqual(list(fs.remembered("mounted")), ["/org/freedesktop/UDisks2/block_devices/sda3"])
            self.assertEqual(fs.remembered("unlocked"), {})

    def test_release_undoes_only_what_it_did(self):
        runtime = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, runtime, True)
        udisks = mock.Mock()
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}):
            fs.remember("mounted", "/x/dm_2d0")
            fs.remember("unlocked", "/x/sdc1")
            self.assertEqual(fs.release(udisks), [])
            self.assertEqual(fs.remembered("mounted"), {})
        udisks.unmount.assert_called_once_with("/x/dm_2d0")
        udisks.lock.assert_called_once_with("/x/sdc1")


class SystemTest(unittest.TestCase):
    def test_filesystem_type_from_mountinfo(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "proc/self"))
        with open(os.path.join(root, "proc/self/mountinfo"), "w") as f:
            f.write("22 1 8:2 / / rw - ext4 /dev/sda2 rw\n"
                    "40 22 8:17 / /media/jon/MY\\040STICK rw - vfat /dev/sdb1 rw\n")
        with mock.patch.object(fs, "PROC", os.path.join(root, "proc")):
            self.assertEqual(fs.filesystem_type("/media/jon/MY STICK/Files"), "vfat")
            self.assertEqual(fs.filesystem_type("/home/jon"), "ext4")

    def test_live_session(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "proc"))
        with open(os.path.join(root, "proc/cmdline"), "w") as f:
            f.write("BOOT_IMAGE=/live/vmlinuz boot=live components quiet\n")
        with mock.patch.object(fs, "PROC", os.path.join(root, "proc")):
            self.assertTrue(fs.live_system())
        with mock.patch.object(fs, "PROC", "/nonexistent"):
            self.assertFalse(fs.live_system())

    def test_copy_needs_a_folder(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as raised:
            fs.main(["copy", "/dev/sda3", "Jon"])
        self.assertEqual(raised.exception.code, 2)

    def test_before_install_asks_only_with_windows(self):
        asked = []

        def ask():
            asked.append(True)
            return "copy"

        self.assertEqual(fs.before_install([], ask), "continue")
        self.assertEqual(asked, [])
        self.assertEqual(fs.before_install([{"device": "/dev/sda3"}], ask), "copy")
        self.assertEqual(asked, [True])

    def test_before_install_continues_without_udisks(self):
        def broken():
            raise fs.SwitchError("The disk service isn't running.")

        with mock.patch.object(fs, "UDisks", broken), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(fs.main(["before-install"]), 0)
        self.assertEqual(out.getvalue(), "continue\n")

    def test_folders_are_the_xdg_ones(self):
        self.assertEqual([x for _n, x, _f in fs.FOLDERS],
                         ["DESKTOP", "DOCUMENTS", "DOWNLOAD", "MUSIC", "PICTURES", "VIDEOS"])


class WebAppsTest(unittest.TestCase):
    """Firefox's web apps (phase 3): profiles.ini and Taskbar Tabs' list in a
    temporary home, stand-ins for firefox-esr and notify-send on a PATH of
    their own that write their arguments to a file."""

    APP = {"id": "2610e1f6-3341-4b70-8cd2-a59d40ce0881", "scopes": [{"hostname": "web.whatsapp.com"}],
           "userContextId": 0, "startUrl": "https://web.whatsapp.com", "name": "WhatsApp",
           "shortcutRelativePath": "firefox-esr.webapp-2610e1f6-3341-4b70-8cd2-a59d40ce0881.desktop"}

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.config = os.path.join(self.home, ".config")
        self.data = os.path.join(self.home, ".local/share")
        self.bin = os.path.join(self.home, "bin")
        self.calls = os.path.join(self.home, "calls")
        os.makedirs(self.bin)
        for name in ("firefox-esr", "notify-send"):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(f'#!/bin/sh\nprintf "%s|" {name} "$@" >> "{self.calls}"\necho >> "{self.calls}"\n')
            os.chmod(path, 0o755)
        env = mock.patch.dict(os.environ, {"HOME": self.home, "XDG_CONFIG_HOME": self.config,
                                           "XDG_DATA_HOME": self.data, "PATH": self.bin})
        env.start()
        self.addCleanup(env.stop)

    def folder(self, ini, where=".mozilla/firefox"):
        folder = os.path.join(self.home, where)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "profiles.ini"), "w") as f:
            f.write(ini)
        return folder

    def profile(self, folder, name, apps=None, version=1):
        path = os.path.join(folder, name)
        os.makedirs(os.path.join(path, "taskbartabs", "icons"), exist_ok=True)
        if apps is not None:
            with open(os.path.join(path, fs.TASKBAR_TABS), "w") as f:
                json.dump({"version": version, "taskbarTabs": apps}, f)
        return path

    def launcher(self, app):
        os.makedirs(os.path.join(self.data, "applications"), exist_ok=True)
        open(os.path.join(self.data, "applications", app["shortcutRelativePath"]), "w").close()

    def called(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls) as f:
            return [line.rstrip("|\n").split("|") for line in f if line.strip()]

    def wait_calls(self, count):
        import time
        for _ in range(200):
            if len(self.called()) >= count:
                break
            time.sleep(0.02)
        return self.called()

    def run_main(self, *args):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = fs.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_install_sections_win_over_default(self):
        """profiles.ini as Debian's firefox-esr leaves it next to an older
        Firefox's profile: the Install section names the one ESR uses."""
        folder = self.folder("[Profile1]\nName=default\nIsRelative=1\nPath=old.default\nDefault=1\n\n"
                             "[Profile0]\nName=default-esr\nIsRelative=1\nPath=new.default-esr\n\n"
                             "[Install3B6073811A6ABF12]\nDefault=new.default-esr\nLocked=1\n")
        self.profile(folder, "old.default")
        esr = self.profile(folder, "new.default-esr")
        self.assertEqual(fs.firefox_profiles(folder), [esr])

    def test_default_profile_without_install_sections(self):
        folder = self.folder("[Profile0]\nName=a\nIsRelative=1\nPath=a\n\n"
                             "[Profile1]\nName=b\nIsRelative=0\nPath=" + os.path.join(self.home, "elsewhere")
                             + "\nDefault=1\n")
        self.profile(folder, "a")
        elsewhere = self.profile(self.home, "elsewhere")
        self.assertEqual(fs.firefox_profiles(folder), [elsewhere])

    def test_missing_profile_and_broken_ini(self):
        folder = self.folder("[Install1]\nDefault=gone\n")
        self.assertEqual(fs.firefox_profiles(folder), [])
        folder = self.folder("not an ini file\n[", where="broken")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(fs.firefox_profiles(folder), [])

    def test_both_folders(self):
        self.assertEqual(fs.firefox_folders(), [])
        legacy = self.folder("[Install1]\nDefault=p\n")
        xdg = self.folder("[Install1]\nDefault=q\n", where=".config/mozilla/firefox")
        self.assertEqual(fs.firefox_folders(), [legacy, xdg])

    def test_reads_firefox_list(self):
        folder = self.folder("[Install1]\nDefault=p\n")
        profile = self.profile(folder, "p", [self.APP])
        self.launcher(self.APP)
        icon = os.path.join(profile, "taskbartabs", "icons", self.APP["id"] + ".png")
        open(icon, "w").close()
        self.assertEqual(fs.webapps(), [{
            "id": self.APP["id"], "name": "WhatsApp", "start": "https://web.whatsapp.com",
            "hosts": ["web.whatsapp.com"], "icon": icon, "launcher": self.APP["shortcutRelativePath"],
            "profile": profile, "container": 0}])

    def test_launcher_gone_and_odd_entries(self):
        folder = self.folder("[Install1]\nDefault=p\n")
        odd = [{"id": "../../etc", "startUrl": "https://a.example"}, {"name": "no id"}, "text",
               dict(self.APP, shortcutRelativePath="../x.desktop", name=None)]
        self.profile(folder, "p", odd)
        apps = fs.webapps()
        self.assertEqual(len(apps), 1)
        self.assertIsNone(apps[0]["launcher"])
        self.assertIsNone(apps[0]["icon"])
        self.assertEqual(apps[0]["name"], "web.whatsapp.com")

    def test_broken_or_newer_list_gives_none(self):
        folder = self.folder("[Install1]\nDefault=p\n[Install2]\nDefault=q\n")
        self.profile(folder, "p", [self.APP], version=2)
        broken = self.profile(folder, "q")
        with open(os.path.join(broken, fs.TASKBAR_TABS), "w") as f:
            f.write("{not json")
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(fs.webapps(), [])
        self.assertIn("newer", err.getvalue())

    def test_list_command(self):
        code, out, _err = self.run_main("webapp", "list", "--json")
        self.assertEqual((code, json.loads(out)), (0, []))
        folder = self.folder("[Install1]\nDefault=p\n")
        self.profile(folder, "p", [self.APP])
        code, out, _err = self.run_main("webapp", "list")
        self.assertEqual(out, f"{self.APP['id']}\tWhatsApp\thttps://web.whatsapp.com\n")

    def apps_list(self, entries):
        path = os.path.join(self.home, "apps.json")
        with open(path, "w") as f:
            json.dump(entries, f)
        patch = mock.patch.object(fs, "APPS_LIST", path)
        patch.start()
        self.addCleanup(patch.stop)

    LIST = [{"id": "whatsapp", "name": "WhatsApp",
             "web": {"name": "WhatsApp on the web", "url": "https://web.whatsapp.com"}},
            {"id": "teams", "name": "Microsoft Teams",
             "web": {"name": "Teams on the web", "url": "https://teams.microsoft.com"}},
            {"id": "old", "name": "Old Site", "web": {"name": "Old on the web", "url": "http://old.example"}},
            {"id": "photoshop", "name": "Adobe Photoshop"}]

    def test_known_adds_the_lists_web_versions(self):
        """Software's list (phase 3b): Firefox's web apps first, matched to the
        list's entry by host; the list's other web versions not made; http://
        left out."""
        self.apps_list(self.LIST)
        folder = self.folder("[Install1]\nDefault=p\n")
        profile = self.profile(folder, "p", [self.APP, dict(self.APP, id="77", name="Mine",
                                                            scopes=[{"hostname": "mine.example"}],
                                                            startUrl="https://mine.example")])
        code, out, _err = self.run_main("webapp", "list", "--json", "--known")
        known = json.loads(out)
        self.assertEqual([(k["id"], k["entry"], k["windows"], k["made"]) for k in known], [
            (self.APP["id"], "whatsapp", "WhatsApp", True), ("77", None, None, True),
            (None, "teams", "Microsoft Teams", False)])
        self.assertEqual(known[0]["profile"], profile)
        self.assertEqual(known[2], {"id": None, "name": "Teams on the web", "start": "https://teams.microsoft.com",
                                    "hosts": ["teams.microsoft.com"], "icon": None, "launcher": None,
                                    "profile": None, "container": 0, "entry": "teams",
                                    "windows": "Microsoft Teams", "made": False})
        code, out, _err = self.run_main("webapp", "list", "--known")
        self.assertEqual(out.splitlines()[-1], "-\tTeams on the web\thttps://teams.microsoft.com")
        code, out, _err = self.run_main("webapp", "list", "--json")
        self.assertNotIn("made", json.loads(out)[0])

    def test_known_without_firefox_or_list(self):
        self.apps_list(self.LIST)
        self.assertEqual([v["entry"] for v in fs.web_versions()], ["whatsapp", "teams"])
        self.assertEqual([k["made"] for k in fs.known_webapps([], fs.web_versions())], [False, False])
        self.apps_list({"not": "a list"})
        self.assertEqual(fs.web_versions(), [])
        self.assertEqual(fs.web_versions(os.path.join(self.home, "missing.json")), [])

    def test_web_address(self):
        for good in ("https://outlook.live.com/mail/", "http://example.org"):
            self.assertEqual(fs.web_address(good), good)
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "-new-instance", "outlook.com",
                    "https://", "https://a b.example", "https://[::1"):
            with self.assertRaises(fs.SwitchError, msg=bad):
                fs.web_address(bad)

    def test_add_opens_firefox_and_says_which_button(self):
        code, out, _err = self.run_main("webapp", "add", "https://outlook.live.com/mail/", "--name", "Outlook")
        self.assertEqual((code, out), (0, ""))
        calls = self.wait_calls(2)
        self.assertIn(["firefox-esr", "-new-window", "https://outlook.live.com/mail/"], calls)
        notice = next(c for c in calls if c[0] == "notify-send")
        self.assertEqual(notice[-2], "Keep Outlook as a web app")
        self.assertTrue(notice[-1].startswith("Press the button at the right of Firefox's address bar"))

    def test_add_opens_the_web_app_firefox_has(self):
        folder = self.folder("[Install1]\nDefault=p\n")
        profile = self.profile(folder, "p", [self.APP])
        code, out, _err = self.run_main("webapp", "add", "https://WEB.whatsapp.com/")
        self.assertEqual(out, f"{self.APP['id']}\tWhatsApp\n")
        self.assertEqual(self.wait_calls(1), [["firefox-esr", "-taskbar-tab", self.APP["id"], "-new-window",
                                               "https://web.whatsapp.com", "-profile", profile,
                                               "-container", "0"]])

    def test_add_without_notifications_prints_the_hint(self):
        os.unlink(os.path.join(self.bin, "notify-send"))
        code, out, _err = self.run_main("webapp", "add", "https://claude.ai")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("Keep claude.ai as a web app: Press the button"))

    def test_add_needs_firefox_and_a_web_address(self):
        code, _out, err = self.run_main("webapp", "add", "file:///etc/passwd")
        self.assertEqual(code, 1)
        os.unlink(os.path.join(self.bin, "firefox-esr"))
        code, _out, err = self.run_main("webapp", "add", "https://claude.ai")
        self.assertEqual(code, 1)
        self.assertIn("firefox-esr is not installed", err)
        self.assertEqual(self.called(), [])

    def test_remove_opens_the_web_app(self):
        folder = self.folder("[Install1]\nDefault=p\n")
        self.profile(folder, "p", [self.APP])
        code, _out, _err = self.run_main("webapp", "remove", self.APP["id"])
        self.assertEqual(code, 0)
        calls = self.wait_calls(2)
        self.assertIn(["firefox-esr", "-taskbar-tab", self.APP["id"]], [c[:3] for c in calls])
        self.assertIn("Remove WhatsApp", next(c for c in calls if c[0] == "notify-send"))
        code, _out, err = self.run_main("webapp", "remove", "0000")
        self.assertEqual(code, 1)
        self.assertIn("no web app 0000", err)


def po_list(name):
    with open(os.path.join(PO, name), encoding="utf-8") as f:
        return [line.split("#")[0].strip() for line in f if line.split("#")[0].strip()]


@unittest.skipUnless(shutil.which("xgettext") and shutil.which("msgcmp") and shutil.which("msgcat"),
                     "gettext is not installed")
class TranslationTest(unittest.TestCase):
    def test_template_is_current(self):
        """po/flickos-switch.pot has every marked string and no others (the
        same xgettext options as tools/update-po.sh, which fixes this)."""
        files = po_list("POTFILES")
        with tempfile.TemporaryDirectory() as folder:
            new = os.path.join(folder, "new.pot")
            python = [f for f in files if not f.endswith(".desktop")]
            desktop = [f for f in files if f.endswith(".desktop")]
            subprocess.run(["xgettext", "--language=Python", "--from-code=UTF-8", "--keyword=N_",
                            "--output=" + new, *python], cwd=PACKAGE, check=True)
            subprocess.run(["xgettext", "--language=Desktop", "--join-existing",
                            "--output=" + new, *desktop], cwd=PACKAGE, check=True)
            # The Windows apps list's text, as update-po.sh adds it.
            extra = os.path.join(folder, "extra.pot")
            with open(extra, "w", encoding="utf-8") as f:
                subprocess.run([os.path.join(PO, "extract")], stdout=f, check=True)
            subprocess.run(["msgcat", "--use-first", "--output-file=" + new, new, extra], check=True)
            shipped = os.path.join(PO, "flickos-switch.pot")
            for definitions, reference in ((shipped, new), (new, shipped)):
                result = subprocess.run(["msgcmp", "--use-untranslated", definitions, reference],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f"run tools/update-po.sh flickos-switch\n{result.stderr}")


class ShippedFilesTest(unittest.TestCase):
    def test_desktop_file(self):
        path = os.path.join(PACKAGE, "usr/share/applications", fs.APP_ID + ".desktop")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Exec=flickos-switch files\n", text)
        self.assertIn("Name=Bring Files from Windows\n", text)

    def test_program_is_executable(self):
        mode = os.stat(os.path.join(PACKAGE, "usr/bin/flickos-switch")).st_mode
        self.assertTrue(mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
