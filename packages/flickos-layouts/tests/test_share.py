"""Tests for sharing and trying a style: `export`, `import` and `try`
(docs/design/flickos-ricing.md, phase 4a; spike Q9 and Q12).
Run: python3 -m unittest discover -s tests
"""

import gzip
import io
import json
import os
import shutil
import tarfile
from unittest import mock

from test_engine import fl, read
from test_user_styles import UserStyleTest

MINE = "Name=Mine\nInherits=dark\nGtkTheme=Arc-Darker\nIconTheme=Numix\nColorScheme=prefer-dark\n"
OTHER = "Name=Other\nInherits=light\nGtkTheme=Adwaita\nIconTheme=Adwaita\nColorScheme=prefer-light\n"
MINE_VALUES = {"gtk-theme": "Arc-Darker", "icon-theme": "Numix", "color-scheme": "prefer-dark"}
OTHER_VALUES = {"gtk-theme": "Adwaita", "icon-theme": "Adwaita", "color-scheme": "prefer-light"}


class ShareTest(UserStyleTest):

    def setUp(self):
        super().setUp()
        for name, value in (("run_quiet", mock.Mock()), ("restart_wallpaper", mock.Mock())):
            patcher = mock.patch.object(fl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.gsettings.update({"gtk-theme": "Arc-Dark", "icon-theme": "Numix-Circle", "color-scheme": "prefer-dark"})
        self.user_style("mine", MINE)
        self.user_style("other", OTHER)
        self.write("home/.config/flickos/layout", "plain\n")

    def session(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")

    def login(self):
        """What flickos-session does before labwc."""
        for key in ("WAYLAND_DISPLAY", "LABWC_PID"):
            os.environ.pop(key, None)
        self.assertEqual(self.main("prepare")[0], 0)
        self.session()

    def values(self):
        return {key: self.gsettings.get(key) for key in fl.TRY_KEYS}

    def record(self):
        return os.path.join(self.home, ".local/state/flickos", fl.TRY_RECORD)

    def history(self):
        path = os.path.join(self.home, ".local/state/flickos/history.jsonl")
        return [json.loads(line) for line in read(path).splitlines()] if os.path.exists(path) else []


class TryTest(ShareTest):
    """try and the login that ends it (spike Q12, design T1)."""

    def setUp(self):
        super().setUp()
        self.session()
        self.assertEqual(self.main("style", "set", "mine")[0], 0)
        self.assertEqual(self.values(), MINE_VALUES)

    def test_try_applies_without_saving(self):
        status, out, _err = self.main("try", "other")
        self.assertEqual(status, 0)
        self.assertIn("until you log out", out)
        self.assertEqual(self.values(), OTHER_VALUES)
        self.assertEqual(read(fl.choice_path("style")), "mine\n")
        self.assertEqual(fl.resolve_style(self.styles()).id, "other")
        self.assertEqual(json.loads(read(self.record()))["before"], MINE_VALUES)

    def test_login_ends_try_with_runtime_folder_kept(self):
        """logind keeps the runtime folder across a quick re-login (Q12a)."""
        self.main("try", "other")
        self.login()
        self.assertEqual(self.values(), MINE_VALUES)
        self.assertFalse(os.path.exists(self.record()))
        self.assertFalse(os.path.exists(fl.try_path()))
        self.assertEqual(fl.resolve_style(self.styles()).id, "mine")

    def test_login_after_runtime_folder_and_tried_style_are_gone(self):
        """The tried style's themes are no longer a style's: only the record knows (Q12b)."""
        self.main("try", "other")
        shutil.rmtree(self.root)
        shutil.rmtree(os.path.join(self.user_dir, "other"))
        self.login()
        self.assertEqual(self.values(), MINE_VALUES)

    def test_key_changed_during_try_is_kept(self):
        self.main("try", "other")
        self.gsettings["gtk-theme"] = "Emacs"          # nwg-look during the try
        self.login()
        self.assertEqual(self.values(), dict(MINE_VALUES, **{"gtk-theme": "Emacs"}))

    def test_theme_chosen_before_is_left_alone(self):
        self.gsettings["gtk-theme"] = "Raleigh"        # not a style's theme
        self.main("try", "other")
        self.assertEqual(self.gsettings["gtk-theme"], "Raleigh")
        self.login()
        self.assertEqual(self.values(), dict(MINE_VALUES, **{"gtk-theme": "Raleigh"}))

    def test_second_try_keeps_the_first_before(self):
        self.main("try", "other")
        self.main("try", "light")
        self.assertEqual(self.gsettings["gtk-theme"], "Arc")
        self.login()
        self.assertEqual(self.values(), MINE_VALUES)

    def test_set_while_trying_keeps_it(self):
        self.main("try", "other")
        self.assertEqual(self.main("style", "set", "other")[0], 0)
        self.assertFalse(os.path.exists(self.record()))
        self.login()
        self.assertEqual(self.values(), OTHER_VALUES)
        self.assertEqual([(e["old"], e["new"]) for e in self.history() if e["key"] == "style"],
                         [("default", "mine"), ("mine", "other")])

    def test_try_end(self):
        self.main("try", "other")
        status, out, _err = self.main("try", "--end")
        self.assertEqual((status, out), (0, "Style 'Mine' again.\n"))
        self.assertEqual(self.values(), MINE_VALUES)
        self.assertFalse(os.path.exists(self.record()))
        self.assertEqual(self.main("try", "--end")[1], "Not trying a style.\n")

    def test_try_records_nothing_in_history(self):
        self.main("try", "other")
        self.main("try", "--end")
        self.assertEqual([e["new"] for e in self.history()], ["mine"])

    def test_refusals(self):
        self.user_style("broken", "Name=Broken\nInherits=nothing\n")
        self.assertIn("errors", self.main("try", "broken")[2])
        self.assertIn("no such style", self.main("try", "nothing")[2])
        self.assertEqual(self.main("try")[0], 2)
        os.environ["FLICKOS_PLAIN"] = "1"
        self.assertIn("plain session", self.main("try", "other")[2])
        del os.environ["FLICKOS_PLAIN"]
        for key in ("WAYLAND_DISPLAY", "LABWC_PID"):
            del os.environ[key]
        self.assertIn("on the desktop", self.main("try", "other")[2])
        self.assertFalse(os.path.exists(self.record()))

    def test_plain_session_ignores_a_try(self):
        self.main("try", "other")
        os.environ["FLICKOS_PLAIN"] = "1"
        self.assertEqual(fl.resolve_style(self.styles()).id, "dark")     # mine's FlickOS ancestor

    def test_shown_while_trying(self):
        self.main("try", "other")
        state = json.loads(self.main("state")[1])
        self.assertEqual((state["style"]["current"], state["trying"]), ("other", "other"))
        self.assertIn("You are trying the style other", " ".join(state["warnings"]))
        self.assertIn("trying it until you log out", self.main("explain", "style")[1])
        found = self.styles()
        self.assertTrue(fl.item_comment(found["other"]).endswith(f"· {fl.YOURS} · {fl.TRYING}"))
        self.assertNotIn(fl.TRYING, fl.item_comment(found["mine"]))
        self.main("try", "--end")
        self.assertIsNone(json.loads(self.main("state")[1])["trying"])


class ArchiveTest(ShareTest):
    """import refuses every trick of spike Q9 before anything is kept."""

    GOOD = {"style.ini": "[Style]\nName=Nice\nInherits=dark\nWaybar=waybar-colors.css\nFoot=foot.ini\n",
            "waybar-colors.css": "@define-color selected_bg_color #b5480c;\n",
            "foot.ini": "[colors]\nregular4=b5480c\n"}

    def archive(self, files=None, extra=(), top="nice", name="nice.tar.gz"):
        """GOOD with files over it (None leaves one out), then extra (TarInfo, bytes|None)."""
        content = dict(self.GOOD, **(files or {}))
        path = self.path(name)
        with tarfile.open(path, "w:gz") as tar:
            folder = tarfile.TarInfo(top)
            folder.type = tarfile.DIRTYPE
            tar.addfile(folder)
            for file_name, text in content.items():
                if text is not None:
                    data = text.encode()
                    tar.addfile(self.member(f"{top}/{file_name}", len(data)), io.BytesIO(data))
            for member, data in extra:
                tar.addfile(member, io.BytesIO(data) if data is not None else None)
        return path

    @staticmethod
    def member(name, size=0, kind=tarfile.REGTYPE, **extra):
        member = tarfile.TarInfo(name)
        member.type, member.size = kind, size
        for key, value in extra.items():
            setattr(member, key, value)
        return member

    def refused(self, path, *words):
        """Import refuses path; words are in what it printed (check's problems on stdout)."""
        status, out, err = self.main("import", path)
        self.assertEqual(status, 1, err)
        for word in words:
            self.assertIn(word, out + err)
        self.assertEqual(sorted(os.listdir(self.user_dir)), ["mine", "other"])     # nothing left, no scratch
        return out + err

    def test_good_archive(self):
        status, out, _err = self.main("import", self.archive())
        self.assertEqual(status, 0)
        self.assertIn("flickos-layout try nice", out)
        self.assertEqual(sorted(os.listdir(os.path.join(self.user_dir, "nice"))),
                         ["foot.ini", "style.ini", "waybar-colors.css"])
        self.assertEqual(self.styles()["nice"].parent, "dark")
        self.assertEqual(self.history(), [])

    def test_keys_that_run_programs(self):
        for name, text, word in (
                ("foot.ini", "[main]\nshell=sh -c x\n", "shell in [main]"),
                ("foot.ini", "[key-bindings]\npipe-visible=[sh] Control+Print\n", "pipe-visible"),
                ("foot.ini", "[url]\nlaunch=sh -c x\n", "launch in [url]"),
                ("foot.ini", "include=/etc/passwd\n", "include="),
                ("waybar-colors.css", "@define-color selected_bg_color url(/etc/shadow);\n", "isn't a color"),
                ("waybar-colors.css", "* { background-image: url(\"/etc/shadow\"); }\n", "only @define-color")):
            with self.subTest(word):
                said = self.refused(self.archive({name: text}), word, "has errors")
                self.assertIn(f"nice.tar.gz:nice/{name}:", said)          # the archive's path, not the scratch one

    def test_mako_and_fuzzel_commands(self):
        for name, text, word in (("mako.conf", "on-button-left=exec rm -rf ~\n", "on-button-left"),
                                 ("mako.conf", "border-color=#b5480c\n[app-name=x]\non-notify=exec x\n", "on-notify"),
                                 ("fuzzel.ini", "[main]\nterminal=foot -e x\n", "terminal"),
                                 ("fuzzel.ini", "[main]\nlaunch-prefix=sh -c\n", "launch-prefix")):
            with self.subTest(word):
                files = {name: text, "style.ini": self.GOOD["style.ini"] + f"{name.split('.')[0].title()}={name}\n"}
                self.assertIn(word, self.main("import", self.archive(files))[1])
                self.refused(self.archive(files))

    def test_archive_tricks(self):
        for extra, files, word in (
                ([(self.member("nice/foot.ini", kind=tarfile.SYMTYPE, linkname="/etc/passwd"), None)],
                 {"foot.ini": None}, "a link"),
                ([(self.member("nice/foot.ini", kind=tarfile.LNKTYPE, linkname="nice/style.ini"), None)],
                 {"foot.ini": None}, "a link"),
                ([(self.member("nice/../evil.ini", 3), b"x=1")], {}, "one folder"),
                ([(self.member("/tmp/evil.ini", 3), b"x=1")], {}, "one folder"),
                ([(self.member("nice/sub/foot.ini", 3), b"x=1")], {}, "one folder"),
                ([(self.member("nice/mako.conf", kind=tarfile.CHRTYPE, devmajor=1, devminor=3), None)], {},
                 "special file"),
                ([(self.member("nice/mako.conf", kind=tarfile.FIFOTYPE), None)], {}, "special file"),
                ([(self.member("nice/install.sh", 3), b"x=1")], {}, "not one of a style's files"),
                ([(self.member("other/style.ini", 3), b"x=1")], {}, "more than one folder"),
                ([(self.member("nice/foot.ini", 3), b"x=1")], {}, "twice"),
                ([(self.member("nice/wallpaper.png", 3), b"png"), (self.member("nice/wallpaper.jpg", 3), b"jpg")],
                 {}, "second wallpaper")):
            with self.subTest(word):
                self.refused(self.archive(files, extra), word)
        self.assertFalse(os.path.exists("/tmp/evil.ini"))

    def test_sizes_from_the_headers(self):
        """A header that declares 1 GB is refused before anything is read."""
        for name, limit in (("foot.ini", fl.IMPORT_MAX_TEXT), ("wallpaper.png", fl.IMPORT_MAX_WALLPAPER)):
            with self.subTest(name):
                data = gzip.compress(self.member("nice", kind=tarfile.DIRTYPE).tobuf()
                                     + self.member(f"nice/{name}", 1 << 30).tobuf() + b"\0" * 1024)
                path = self.write(f"{name}.tar.gz", "")
                with open(path, "wb") as f:
                    f.write(data)
                self.refused(path, f"at most {limit}")

    def test_unpacked_size_limit(self):
        """tarfile reads a pax header whole (1 MB gzip -> 1.2 GB in the spike):
        the archive is unpacked with a limit first."""
        pax = self.member("././@PaxHeader", 8192, kind=tarfile.XHDTYPE).tobuf()
        path = self.path("bomb.tar.gz")
        with open(path, "wb") as f:
            f.write(gzip.compress(pax + b"\0" * 8192))
        with mock.patch.object(fl, "IMPORT_MAX_BYTES", 4096):
            self.refused(path, "unpacks to more than")
        self.refused(self.write("hello.tar.gz", "hello\n"), "isn't a style archive")
        self.refused(self.path("missing.tar.gz"), "not imported")

    def test_xz_and_plain_tar(self):
        with open(self.archive(), "rb") as f:
            plain = gzip.decompress(f.read())
        for name, data in (("nice.tar", plain), ("nice.tar.xz", __import__("lzma").compress(plain))):
            with self.subTest(name):
                path = self.path(name)
                with open(path, "wb") as f:
                    f.write(data)
                self.assertEqual(self.main("import", path, "--replace")[0], 0)

    def test_file_keys_must_name_archive_files(self):
        for line in ("Foot=/etc/passwd", "Waybar=../../x.css", "Wallpaper=/etc/shadow"):
            with self.subTest(line):
                key = line.split("=")[0]
                ini = "\n".join(l for l in self.GOOD["style.ini"].splitlines() if not l.startswith(key + "="))
                self.refused(self.archive({"style.ini": ini + "\n" + line + "\n"}), "isn't one of the style's own")

    def test_ids(self):
        self.refused(self.archive(top="dark"), "one of FlickOS's styles")
        self.refused(self.archive(top="Bad Id"), "can't be a style id")
        self.refused(self.archive({"style.ini": None}), "no style.ini")
        self.refused(self.archive(top="mine"), "--replace")
        self.assertEqual(self.main("import", self.archive(top="mine"), "--replace")[0], 0)
        self.assertEqual(self.styles()["mine"].name, "Nice")
        self.assertEqual(sorted(os.listdir(self.user_dir)), ["mine", "other"])

    def test_warnings_ask(self):
        """Low contrast is a warning: kept only when the user says so."""
        files = {"waybar-colors.css": "@define-color fg_color #3a3e4c;\n"}
        with mock.patch.object(fl.sys.stdin, "isatty", return_value=False):
            self.assertIn("--yes", self.refused(self.archive(files)))
        with mock.patch.object(fl.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="n") as ask:
            self.refused(self.archive(files))
        ask.assert_called_once_with("Keep it? [y/N] ")
        with mock.patch.object(fl.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="y"):
            self.assertEqual(self.main("import", self.archive(files))[0], 0)
        self.assertEqual(self.main("import", self.archive(files), "--replace", "--yes")[0], 0)


class ExportTest(ShareTest):

    def chain(self):
        """child (wallpaper, one foot color) on base (themes, colors) on dark."""
        self.user_style("base", "Name=Base\nInherits=dark\nGtkTheme=Arc-Darker\nPackages=arc-theme\n"
                                "Waybar=waybar-colors.css\nFoot=foot.ini\n",
                        waybar_colors_css="@define-color selected_bg_color #b5480c;\n",
                        foot_ini="[colors]\nregular4=b5480c\nbackground=202020\n")
        self.user_style("child", "Name=Child\nComment=Mine on Base\nInherits=base\nFoot=foot.ini\n"
                                 "Wallpaper=wallpaper.png\n", foot_ini="[colors]\nbackground=101010\n")
        with open(os.path.join(self.user_dir, "child/wallpaper.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)

    def export(self, style_id="child", *more):
        out = self.path(f"{style_id}.tar.gz")
        status, printed, err = self.main("export", style_id, out, *more)
        self.assertEqual(status, 0, err)
        self.assertEqual(printed, out + "\n")
        with tarfile.open(out) as tar:
            return out, {m.name: (tar.extractfile(m).read().decode(errors="replace") if m.isfile() else None)
                         for m in tar.getmembers()}

    def test_only_what_the_users_styles_set(self):
        """FlickOS's keys stay inherited, so Dark's updates still reach it."""
        self.chain()
        _out, files = self.export()
        self.assertEqual(sorted(files), ["child", "child/foot.ini", "child/style.ini", "child/wallpaper.png",
                                         "child/waybar-colors.css"])
        self.assertEqual(files["child/style.ini"],
                         "[Style]\nName=Child\nComment=Mine on Base\nInherits=dark\nGtkTheme=Arc-Darker\n"
                         "Packages=arc-theme\nWaybar=waybar-colors.css\nFoot=foot.ini\nWallpaper=wallpaper.png\n")
        self.assertEqual(files["child/foot.ini"], "[colors]\nregular4=b5480c\nbackground=101010\n")
        self.assertEqual(files["child/waybar-colors.css"], "@define-color selected_bg_color #b5480c;\n")

    def test_starter_exports_style_ini_alone(self):
        """style new's files set nothing yet: no empty color files."""
        self.assertEqual(self.main("style", "new", "fresh", "--from", "dark")[0], 0)
        _out, files = self.export("fresh")
        self.assertEqual(sorted(files), ["fresh", "fresh/style.ini"])
        self.assertNotIn("Foot=", files["fresh/style.ini"])

    def test_round_trip(self):
        self.chain()
        out, _files = self.export()
        before = self.styles()["child"]
        colors = {kind: fl.merged_ini(fl.palette_chain(before, kind)) for kind in ("foot", "fuzzel", "mako")}
        css = fl.merged_css(fl.palette_chain(before, "waybar"))
        shutil.rmtree(os.path.join(self.user_dir, "child"))
        self.assertEqual(self.main("import", out)[0], 0)
        after = self.styles()["child"]
        self.assertEqual({kind: fl.merged_ini(fl.palette_chain(after, kind)) for kind in colors}, colors)
        self.assertEqual(fl.merged_css(fl.palette_chain(after, "waybar")), css)
        self.assertEqual((after.gtk_theme, after.icon_theme, after.parent), (before.gtk_theme, before.icon_theme,
                                                                             "dark"))
        self.assertEqual(fl.style_problems("child"), [])

    def test_refusals(self):
        self.chain()
        self.assertIn("everyone's already", self.main("export", "dark")[2])
        self.assertIn("isn't one of your own", self.main("export", "nothing")[2])
        out = self.write("taken.tar.gz", "keep me")
        self.assertIn("exists already", self.main("export", "child", out)[2])
        self.assertEqual(read(out), "keep me")
        self.user_style("broken", "Name=Broken\nInherits=nothing\n")
        self.assertIn("not exported", self.main("export", "broken", self.path("b.tar.gz"))[2])
        self.assertFalse(os.path.exists(self.path("b.tar.gz")))

    def test_default_file_name(self):
        self.chain()
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            self.assertEqual(self.main("export", "child")[1], "child.tar.gz\n")
        finally:
            os.chdir(cwd)
        self.assertTrue(os.path.isfile(self.path("child.tar.gz")))
