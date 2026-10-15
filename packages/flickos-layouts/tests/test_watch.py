"""Tests for `flickos-layout watch` (docs/design/flickos-ricing.md, phase 3):
which changes need what, the inotify reader, the refusals and the reloads.
Run: python3 -m unittest discover -s tests
"""

import fcntl
import os
import shutil
import signal
from unittest import mock

from test_engine import fl, read
from test_user_styles import UserStyleTest


class WatchTest(UserStyleTest):

    def setUp(self):
        super().setUp()
        self.config = os.path.join(self.home, ".config")

    def actions(self, *relative, chosen=fl.DEFAULT_CHOICE):
        available = self.styles()
        with self.quiet():
            current = fl.resolve_style(available)
        return fl.watch_actions({os.path.join(self.home, p) for p in relative}, current, available, chosen)

    def use(self, style_id):
        self.write("home/.config/flickos/style", style_id + "\n")

    def fake_process(self, pid, comm, args):
        self.write(f"proc/{pid}/comm", comm + "\n")
        self.write(f"proc/{pid}/stat", f"{pid} ({comm}) S 1 2 3\n")
        with open(self.path(f"proc/{pid}/cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in args) + b"\0")
        self.write(f"proc/{pid}/environ", "")


class ActionsTest(WatchTest):
    """watch_actions: what a batch of saves needs, decided without doing it."""

    STYLES = ".local/share/flickos/styles"

    def test_palette_of_style_in_use(self):
        self.orange()
        self.use("dark-orange")
        self.assertEqual(self.actions(f"{self.STYLES}/dark-orange/waybar-colors.css"),
                         [("palette", "dark-orange")])

    def test_style_ini_applies_style_again(self):
        """style.ini may name other themes, a wallpaper or another parent."""
        self.orange()
        self.use("dark-orange")
        self.assertEqual(self.actions(f"{self.STYLES}/dark-orange/style.ini",
                                      f"{self.STYLES}/dark-orange/foot.ini"),
                         [("style", "dark-orange")])

    def test_parents_palette_reloads_child_in_use(self):
        self.user_style("base", "Name=Base\nInherits=dark\nWaybar=waybar-colors.css\n",
                        waybar_colors_css="@define-color bg_color #202020;\n")
        self.user_style("child", "Name=Child\nInherits=base\n")
        self.use("child")
        self.assertEqual(self.actions(f"{self.STYLES}/base/waybar-colors.css"), [("palette", "child")])

    def test_other_style_is_only_checked(self):
        self.orange()
        self.user_style("mine", "Name=Mine\nInherits=dark\n")
        self.assertEqual(self.actions(f"{self.STYLES}/mine/style.ini", f"{self.STYLES}/mine/foot.ini"),
                         [("check", "mine")])

    def test_deleted_style_is_not_checked(self):
        self.assertEqual(self.actions(f"{self.STYLES}/gone/style.ini", f"{self.STYLES}/gone"), [])

    def test_chosen_style_with_errors_is_applied_once_fixed(self):
        """A chosen style that doesn't resolve isn't the one in use: its fix
        must still apply it."""
        self.user_style("broken", "Name=Broken\nInherits=nothing\n")
        self.use("broken")
        self.assertEqual(self.actions(f"{self.STYLES}/broken/style.ini", chosen="broken"),
                         [("style", "broken")])

    def test_other_folders(self):
        self.assertEqual(self.actions(".config/flickos/addons/mine/labwc.xml", ".config/labwc/rc.xml",
                                      ".config/labwc/menu.xml", ".config/mako/config", ".config/foot/foot.ini",
                                      ".config/fuzzel/fuzzel.ini"),
                         [("addons", None), ("new-windows", "foot"), ("new-windows", "fuzzel"),
                          ("labwc", None), ("mako", None)])

    def test_style_actions_come_before_checks(self):
        self.orange()
        self.user_style("mine", "Name=Mine\nInherits=dark\n")
        self.use("dark-orange")
        self.assertEqual(self.actions(f"{self.STYLES}/mine/foot.ini", ".config/mako/config",
                                      f"{self.STYLES}/dark-orange/foot.ini"),
                         [("palette", "dark-orange"), ("mako", None), ("check", "mine")])

    def test_editor_files_are_ignored(self):
        for name in (".foot.ini.swp", "foot.ini~", "#foot.ini#", "4913", ".goutputstream-X1"):
            self.assertTrue(fl.watch_ignored(f"/x/{name}"), name)
        self.assertFalse(fl.watch_ignored("/x/foot.ini"))

    def test_targets(self):
        self.assertEqual(fl.watch_targets(),
                         [self.user_dir, fl.user_layouts_dir(), f"{self.config}/flickos/addons", f"{self.config}/flickos/tweaks",
                          f"{self.config}/labwc", f"{self.config}/foot", f"{self.config}/fuzzel",
                          f"{self.config}/mako"])


class InotifyTest(WatchTest):
    """The ctypes inotify reader on a temporary folder."""

    def setUp(self):
        super().setUp()
        self.inotify = fl.Inotify()
        self.addCleanup(self.inotify.close)

    def batch(self):
        return self.inotify.read_batch(quiet_ms=50)

    def test_write_rename_and_new_folder(self):
        top = self.path("watched")
        os.makedirs(f"{top}/a")
        self.inotify.watch([top])
        self.write("watched/a/foot.ini", "x")
        os.rename(self.write("watched/a/.tmp-123", "y"), f"{top}/a/fuzzel.ini")
        self.assertEqual(self.batch(), {f"{top}/a/foot.ini", f"{top}/a/fuzzel.ini"})
        os.makedirs(f"{top}/b")
        self.assertEqual(self.batch(), {f"{top}/b"})
        self.write("watched/b/style.ini", "z")          # a new folder is watched at once
        self.assertEqual(self.batch(), {f"{top}/b/style.ini"})

    def test_missing_folder_watched_through_parent(self):
        target = self.path("parent/styles")
        os.makedirs(self.path("parent"))
        self.inotify.watch([target])
        self.assertEqual(list(self.inotify.folders.values()), [self.path("parent")])
        self.write("parent/other.txt", "x")              # the parent alone, not its files' folders
        self.assertEqual(self.batch(), {self.path("parent/other.txt")})
        os.makedirs(f"{target}/mine")
        self.write("parent/styles/mine/style.ini", "x")  # saved before the watch begins
        self.assertIn(target, self.batch())
        self.assertEqual(self.inotify.watch([target]), {f"{target}/mine", f"{target}/mine/style.ini"})
        self.write("parent/styles/mine/foot.ini", "x")
        self.assertEqual(self.batch(), {f"{target}/mine/foot.ini"})

    def test_deleted_folder_is_watched_again(self):
        top = self.path("watched")
        os.makedirs(top)
        self.inotify.watch([top])
        shutil.rmtree(top)
        self.batch()
        self.assertNotIn(top, self.inotify.folders.values())
        os.makedirs(top)
        self.inotify.watch([top])
        self.write("watched/x.ini", "x")
        self.assertEqual(self.batch(), {f"{top}/x.ini"})


class CommandTest(WatchTest):

    def test_refused_outside_session(self):
        status, _out, err = self.main("watch")
        self.assertEqual(status, 1)
        self.assertIn("terminal", err)

    def test_refused_in_plain_session(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1", FLICKOS_PLAIN="1")
        status, _out, err = self.main("watch")
        self.assertEqual(status, 1)
        self.assertIn("plain session", err)

    def test_one_watch_per_session(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, fl.WATCH_LOCK), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            status, _out, err = self.main("watch")
        self.assertEqual(status, 1)
        self.assertIn("already watching", err)

    def test_prints_folders_then_stops_on_ctrl_c(self):
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        os.makedirs(f"{self.config}/labwc")
        with mock.patch.object(fl.Inotify, "read_batch", side_effect=KeyboardInterrupt):
            status, out, _err = self.main("watch")
        self.assertEqual(status, 0)
        # styles and add-ons through ~/.local/share and ~/.config, labwc itself; foot,
        # fuzzel and mako through ~/.config too
        self.assertRegex(out, r"watching 3 folders: ")


class ReloadTest(WatchTest):
    """What watch does: regenerate, then signal FlickOS's panel programs."""

    def setUp(self):
        super().setUp()
        os.environ.update(WAYLAND_DISPLAY="wayland-1", LABWC_PID="1")
        self.write("proc/self/comm", "python3\n")
        for name, value in (("PROC", self.path("proc")), ("restart_wallpaper", mock.Mock())):
            patcher = mock.patch.object(fl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.orange()
        self.use("dark-orange")
        self.write("home/.config/flickos/layout", "plain\n")

    def apply(self, action, argument):
        with self.quiet(), mock.patch.object(fl, "run_quiet") as run, mock.patch.object(fl.os, "kill") as kill, \
                mock.patch.object(fl, "watch_say") as say:
            fl.watch_apply(action, argument)
        return [c.args[0] for c in run.call_args_list], [c.args for c in kill.call_args_list], \
            [c.args[0] for c in say.call_args_list]

    def test_palette_reloads_running_panel_and_mako(self):
        self.fake_process(100, "waybar", ["waybar", "-c", f"{self.root}/waybar/config.jsonc"])
        self.fake_process(101, "waybar", ["waybar"])           # the user's own: left alone
        self.fake_process(102, "mako", ["mako", "-c", f"{self.root}/mako/config"])
        runs, kills, said = self.apply("palette", "dark-orange")
        self.assertEqual(kills, [(100, signal.SIGUSR2)])
        self.assertEqual(runs, [["makoctl", "reload"]])
        self.assertIn(os.path.join(self.user_dir, "dark-orange/waybar-colors.css"),
                      read(f"{self.root}/waybar/style.css"))
        self.assertEqual(said, ["dark-orange: panel, notifications, new foot and fuzzel windows use it"])

    def test_no_makoctl_without_mako(self):
        """makoctl would start a plain mako through D-Bus activation."""
        runs, kills, _said = self.apply("palette", "dark-orange")
        self.assertEqual((runs, kills), ([], []))

    def test_errors_stop_the_reload(self):
        self.fake_process(100, "waybar", ["waybar", "-c", f"{self.root}/waybar/config.jsonc"])
        self.write("home/.local/share/flickos/styles/dark-orange/waybar-colors.css",
                   "@define-color not_a_palette_key #b5480c;\n")
        runs, kills, said = self.apply("palette", "dark-orange")
        self.assertEqual((runs, kills), ([], []))
        self.assertIn("not_a_palette_key", "\n".join(said))
        self.assertEqual(said[-1], "dark-orange: not applied, fix the errors above")

    def test_style_ini_reloads_labwc_and_wallpaper(self):
        self.fake_process(100, "waybar", ["waybar", "-c", f"{self.root}/waybar/config.jsonc"])
        runs, kills, said = self.apply("style", "dark-orange")
        self.assertEqual(runs, [["labwc", "--reconfigure"]])
        self.assertEqual(kills, [(100, signal.SIGUSR2)])
        fl.restart_wallpaper.assert_called_once()
        self.assertFalse(os.path.exists(fl.choice_path("style") + ".new"))
        self.assertTrue(said[-1].startswith("dark-orange: themes, window borders, panel"))

    def test_style_ini_saves_no_choice(self):
        """The default style in use stays the default (state's `default`)."""
        os.remove(fl.choice_path("style"))
        self.write("home/.local/share/flickos/styles/dark/style.ini", "[Style]\nName=My Dark\nInherits=dark\n")
        self.apply("style", "dark")
        self.assertFalse(os.path.exists(fl.choice_path("style")))

    def test_check_only(self):
        self.user_style("mine", "Name=Mine\nInherits=dark\n")
        runs, kills, said = self.apply("check", "mine")
        self.assertEqual((runs, kills), ([], []))
        self.assertEqual(said, ["mine: no errors (not the style in use)"])

    def test_labwc_reload_says_when_merging_changes(self):
        self.write("run/flickos/labwc-merge", "")
        self.write("home/.config/labwc/rc.xml", "<labwc_config><default /></labwc_config>\n")
        runs, _kills, said = self.apply("labwc", None)
        self.assertEqual(runs, [["labwc", "--reconfigure"]])
        self.assertIn("next login", said[-2])
        self.assertEqual(said[-1], fl.DEFAULT_WHILE_MERGING)

    def test_addons_reconfigure(self):
        self.write("home/.config/flickos/addons/mine/labwc.xml",
                   '<labwc_config><keyboard><keybind key="W-F9"><action name="Execute" command="true"/>'
                   '</keybind></keyboard></labwc_config>\n')
        runs, _kills, said = self.apply("addons", None)
        self.assertEqual(runs, [["labwc", "--reconfigure"]])
        self.assertIn("W-F9", read(self.overlay_rcxml))
        self.assertEqual(said[-1], "add-ons: keys and window rules reloaded")
