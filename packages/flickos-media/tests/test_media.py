"""Tests for usr/bin/flickos-media. Run: python3 -m unittest discover -s tests

No display, network or sound: settings and History go to temporary XDG
folders, the follower runs against a stand-in playerctl, and the strip's
drawing is tested through its pure parts."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import math
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
PROGRAM = os.path.join(PACKAGE, "usr/bin/flickos-media")
LAYOUTS_COMMON = os.path.join(PACKAGE, "..", "flickos-layouts", "usr/share/flickos/layouts/common")

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_media", PROGRAM)
fm = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fm)


class TempHome(unittest.TestCase):
    """Temporary XDG folders and system files; nothing of the build host's."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.runtime = os.path.join(root, "run")
        os.makedirs(self.runtime, mode=0o700)
        env = {"XDG_CONFIG_HOME": os.path.join(root, "config"), "XDG_STATE_HOME": os.path.join(root, "state"),
               "XDG_RUNTIME_DIR": self.runtime, "HOME": os.path.join(root, "home")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("WAYLAND_DISPLAY", None)
        self.system = os.path.join(root, "media.conf")
        # No pw-dump or busctl of the build host's: every player is believed.
        for name, value in (("SYSTEM_CONF", self.system), ("HISTORY_CONF", os.path.join(root, "history.conf")),
                            ("PW_DUMP", os.path.join(root, "no-pw-dump")),
                            ("BUSCTL", os.path.join(root, "no-busctl"))):
            patcher = mock.patch.object(fm, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def history(self):
        path = os.path.join(os.environ["XDG_STATE_HOME"], "flickos", "history.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    @contextlib.contextmanager
    def quiet(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            yield err


class SettingsTest(TempHome):
    def test_defaults_without_files(self):
        self.assertEqual(fm.load_settings(), ({"controls": "off", "spectrum": "off", "spectrum-layer": "behind",
                                              "spectrum-shape": "strip", "spectrum-colors": "style"},
                                              frozenset()))

    def test_conffile_holds_the_built_in_defaults(self):
        with mock.patch.object(fm, "SYSTEM_CONF", os.path.join(PACKAGE, "etc/xdg/flickos/media.conf")):
            values, user = fm.load_settings()
        self.assertEqual(values, {key: default for key, (_n, _a, default) in fm.SETTINGS.items()})
        self.assertEqual(user, frozenset())
        with open(os.path.join(PACKAGE, "etc/xdg/flickos/media.conf")) as conf:
            lines = conf.read().splitlines()
        for name, _allowed, default in fm.SETTINGS.values():
            self.assertIn(f"{name}={default}", lines)                # each one written out

    def test_user_file_wins_and_keys_ignore_case(self):
        self.write(self.system, "[Media]\nControls=on\nSpectrum=on\n")
        self.write(fm.user_conf(), "[Media]\nspectrum=OFF\n")
        values, user = fm.load_settings()
        self.assertEqual((values["controls"], values["spectrum"]), ("on", "off"))
        self.assertEqual(user, {"spectrum"})

    def test_broken_files_mean_defaults(self):
        self.write(self.system, "Controls=on\n[Media\n")
        self.write(fm.user_conf(), "[Media]\nSpectrum=loud\n")
        with self.quiet() as err:
            self.assertEqual(fm.load_settings()[0]["spectrum"], "off")
        self.assertIn("Spectrum=loud", err.getvalue())

    def test_set_saves_records_and_default_removes(self):
        with mock.patch.object(fm, "tell_follower") as told:
            fm.change_setting("spectrum", "on")
            told.assert_called_once()
        self.assertEqual(fm.settings_state()["spectrum"], {"value": "on", "default": False})
        fm.change_setting("spectrum", "default")
        self.assertFalse(os.path.exists(fm.user_conf()))      # nothing left in it
        self.assertEqual(fm.settings_state()["spectrum"], {"value": "off", "default": True})
        self.assertEqual([(e["owner"], e["key"], e["old"], e["new"]) for e in self.history()],
                         [("flickos-media", "spectrum", "off", "on"),
                          ("flickos-media", "spectrum", "on", "default")])

    def test_controls_reloads_the_panel_only_when_it_changes(self):
        with mock.patch.object(fm, "reload_panel") as reload, mock.patch.object(fm, "tell_follower") as told:
            fm.change_setting("controls", "on")
            fm.change_setting("controls", "on")
            self.assertEqual(reload.call_count, 1)
            told.assert_not_called()

    def test_reload_panel_only_inside_the_session(self):
        with mock.patch.object(fm.subprocess, "run") as run:
            fm.reload_panel()                     # no WAYLAND_DISPLAY
            run.assert_not_called()

    def test_wrong_value_is_refused_and_nothing_saved(self):
        with self.assertRaises(fm.MediaError):
            fm.change_setting("spectrum-layer", "middle")
        self.assertFalse(os.path.exists(fm.user_conf()))

    def test_toggle(self):
        out = io.StringIO()
        with mock.patch.object(fm, "tell_follower"), contextlib.redirect_stdout(out):
            self.assertEqual(fm.main(["toggle", "spectrum-layer"]), 0)
            self.assertEqual(fm.main(["toggle", "spectrum-layer"]), 0)
        self.assertEqual(out.getvalue(), "top\nbehind\n")
        with mock.patch.object(fm, "tell_follower") as told, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fm.main(["toggle", "spectrum-colors"]), 0)
        told.assert_called_once()
        self.assertEqual(out.getvalue(), "rainbow\n")

    def test_history_off(self):
        self.write(os.path.join(os.environ["XDG_CONFIG_HOME"], "flickos", "history"), "[History]\nEnabled=no\n")
        with mock.patch.object(fm, "tell_follower"):
            fm.change_setting("spectrum", "on")
        self.assertEqual(self.history(), [])

    def test_cli_errors(self):
        with self.quiet() as err:
            self.assertEqual(fm.main(["set", "spectrum", "maybe"]), 1)
        self.assertIn("flickos-media: spectrum: on, off or default", err.getvalue())
        with self.quiet(), self.assertRaises(SystemExit) as raised:
            fm.main(["set", "volume", "on"])
        self.assertEqual(raised.exception.code, 2)


class PlayersTest(unittest.TestCase):
    def line(self, *fields):
        return fm.SEP.join(fields) + "\n"

    def test_parse_line(self):
        self.assertEqual(fm.parse_line(self.line("vlc", "Playing", "Artist", "Song", "file:///m/x.ogg")),
                         ("vlc", {"status": "Playing", "artist": "Artist", "title": "Song"}))
        self.assertIsNone(fm.parse_line("\n"))
        self.assertIsNone(fm.parse_line("only\x1ftwo\n"))

    def test_untagged_file_shows_its_name(self):
        line = self.line("vlc.instance42", "Playing", "", "", "file:///home/u/Music/My%20Song.mp3")
        self.assertEqual(fm.parse_line(line)[1]["title"], "My Song")
        self.assertEqual(fm.file_title("file:///m/.hidden"), ".hidden")
        self.assertEqual(fm.file_title("https://example.org/stream.mp3"), "")
        self.assertEqual(fm.file_title(""), "")

    def test_players_are_told_apart_by_instance(self):
        # playerName is "vlc" for both of VLC's names and "firefox" for every
        # Firefox window; drop_duplicates and app_name need the instance.
        self.assertTrue(fm.FOLLOW_FORMAT.startswith("{{playerInstance}}" + fm.SEP))

    def test_vlc_counts_once(self):
        players = {"vlc": {}, "vlc.instance42": {}, "firefox.instance_1_9": {}}
        self.assertEqual(set(fm.drop_duplicates(players)), {"vlc.instance42", "firefox.instance_1_9"})

    def test_shown_player(self):
        players = {"a": {"status": "Paused"}, "b": {"status": "Playing"}, "c": {"status": "Paused"}}
        self.assertEqual(fm.shown_player(players, ["a", "b", "c"]), "b")       # playing wins
        players["b"]["status"] = "Paused"
        self.assertEqual(fm.shown_player(players, ["a", "b", "c"]), "c")       # else the newest change
        self.assertIsNone(fm.shown_player({}, ["gone"]))
        players["c"]["status"] = "Stopped"
        self.assertEqual(fm.shown_player(players, ["a", "b", "c"]), "b")       # stopped: not shown
        self.assertIsNone(fm.shown_player({"a": {"status": "Stopped"}}, ["a"]))

    def test_silent_player_counts_as_stopped(self):
        players = {"firefox.instance_1_9": {"status": "Playing"}, "vlc": {"status": "Playing"},
                   "mpv": {"status": "Paused"}}
        silent = {"gone": 1.0}
        sounding = {"firefox.instance_1_9": False, "vlc": None}
        heard, again = fm.heard_players(players, sounding, silent, 100.0)
        self.assertEqual(heard, players)                      # not yet: a stream may be on its way
        self.assertEqual(again, 100.0 + fm.SILENT_SECONDS)
        self.assertEqual(silent, {"firefox.instance_1_9": 100.0})   # a gone player is forgotten
        heard, again = fm.heard_players(players, sounding, silent, 100.0 + fm.SILENT_SECONDS)
        self.assertEqual(heard["firefox.instance_1_9"]["status"], "Stopped")
        self.assertEqual(heard["vlc"]["status"], "Playing")   # not known: believed
        self.assertEqual(heard["mpv"]["status"], "Paused")
        self.assertIsNone(again)
        self.assertEqual(players["firefox.instance_1_9"]["status"], "Playing")   # not changed in place
        heard, again = fm.heard_players(players, {"firefox.instance_1_9": True}, silent, 200.0)
        self.assertEqual(heard["firefox.instance_1_9"]["status"], "Playing")
        self.assertEqual(silent, {})                          # its sound came: the time starts again


class SoundTest(unittest.TestCase):
    """Which process plays: a fake /proc and a stand-in pw-dump."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proc = os.path.join(self.tmp.name, "proc")
        patcher = mock.patch.object(fm, "PROC", self.proc)
        patcher.start()
        self.addCleanup(patcher.stop)

    def process(self, pid, parent, exe):
        folder = os.path.join(self.proc, str(pid))
        os.makedirs(folder)
        with open(os.path.join(folder, "stat"), "w", encoding="utf-8") as f:
            f.write(f"{pid} (a (strange) name) S {parent} 1 1\n")
        os.symlink(exe, os.path.join(folder, "exe"))

    def test_makes_sound(self):
        self.process(100, 1, "/usr/lib/chromium/chromium")
        self.process(150, 100, "/usr/lib/chromium/chromium")      # its audio service
        self.process(200, 1, "/usr/lib/firefox-esr/firefox-esr (deleted)")
        self.process(300, 1, "/usr/bin/bwrap")                    # a sandboxed app, other PIDs inside
        self.assertEqual(fm.process_binary(200), "firefox-esr")
        self.assertEqual(fm.parent_pid(150), 100)
        self.assertEqual(fm.parent_pid(999), 0)
        self.assertTrue(fm.makes_sound(200, [((200, 990), "firefox-esr")]))
        self.assertTrue(fm.makes_sound(100, [((150,), "")]))      # a child's stream
        self.assertFalse(fm.makes_sound(150, [((100,), "")]))     # not a parent's
        self.assertTrue(fm.makes_sound(300, [((2,), "bwrap")]))   # the same program
        self.assertFalse(fm.makes_sound(200, [((150, 990), "chromium"), ((), "")]))
        self.assertFalse(fm.makes_sound(200, []))

    def sandboxed(self, pid, instance):
        root = os.path.join(self.proc, str(pid), "root")
        os.makedirs(root)
        with open(os.path.join(root, ".flatpak-info"), "w", encoding="utf-8") as f:
            f.write(f"[Application]\nname=com.example.App\n\n[Instance]\ninstance-id={instance}\n")

    def test_flatpak(self):
        """A Flatpak's MPRIS name is its xdg-dbus-proxy's; its PulseAudio
        stream has the PID inside the sandbox and pipewire-pulse's."""
        self.process(1090, 1, "/usr/bin/pipewire")
        self.process(400, 1, "/usr/bin/xdg-dbus-proxy")
        self.sandboxed(400, "7")
        self.process(410, 1, "/app/extra/share/spotify/spotify")
        self.sandboxed(410, "7")
        self.process(430, 1, "/app/bin/other")                    # another app's sandbox
        self.sandboxed(430, "8")
        self.assertEqual(fm.sandbox_id(410), "7")
        self.assertIsNone(fm.sandbox_id(1090))
        self.assertEqual(fm.sandbox_processes(400), {400, 410})
        self.assertEqual(fm.sandbox_processes(1090), {1090})
        self.assertTrue(fm.makes_sound(400, [((2, 1090), "spotify")]))
        self.assertTrue(fm.makes_sound(400, [((410,), "")]))      # a PipeWire client: the host's PID
        self.assertFalse(fm.makes_sound(400, [((2, 1090), "other")]))
        self.assertFalse(fm.makes_sound(400, [((430,), "")]))

    def test_audio_watch(self):
        def node(key, client, kind=fm.AUDIO_OUTPUT):
            return {"id": key, "type": "PipeWire:Interface:Node",
                    "info": {"state": "running", "props": {"media.class": kind, "client.id": client}}}

        def client(key, pid, binary):
            return {"id": key, "type": "PipeWire:Interface:Client",
                    "info": {"props": {"application.process.id": pid, "pipewire.sec.pid": 990,
                                       "application.process.binary": binary}}}

        first = [client(66, 14245, "firefox-esr"), client(73, 500, "cava"), node(79, 73, "Stream/Input/Audio"),
                 node(80, 66), {"id": 81, "type": "PipeWire:Interface:Port", "info": {"change-mask": ["params"]}}]
        later = [{"id": 80, "info": None}]
        dumps = []
        for number, objects in enumerate((first, later)):
            dumps.append(os.path.join(self.tmp.name, f"dump{number}"))
            with open(dumps[-1], "w", encoding="utf-8") as f:
                # As pw-dump prints them: indented, so only an array's own end is "]" alone.
                f.write(json.dumps(objects, indent=2) + "\n")
        stand_in = os.path.join(self.tmp.name, "pw-dump")
        with open(stand_in, "w", encoding="utf-8") as f:
            # The first array in two pieces, then the second a moment later.
            f.write(f'#!/bin/sh\n[ "$1" = --monitor ] || exit 1\nhead -c 300 "{dumps[0]}"\nsleep 0.2\n'
                    f'tail -c +301 "{dumps[0]}"\nsleep 0.3\ncat "{dumps[1]}"\nexec sleep 60\n')
        os.chmod(stand_in, 0o755)
        with mock.patch.object(fm, "PW_DUMP", stand_in):
            watch = fm.AudioWatch()
        self.addCleanup(watch.stop)
        arrays = []
        deadline = time.monotonic() + 5
        while len(arrays) < 2 and time.monotonic() < deadline:
            if select.select([watch], [], [], 1)[0] and watch.read():
                arrays.append(watch.streams())
        self.assertEqual(arrays, [[((14245, 990), "firefox-esr")], []])   # cava listens: not an output
        self.assertTrue(watch.ready)
        process = watch.process
        watch.stop()
        self.assertIsNotNone(process.poll())

    def test_lines_keep_nothing_back(self):
        reader, writer = os.pipe()
        with os.fdopen(reader, "rb") as pipe, os.fdopen(writer, "wb", buffering=0) as end:
            lines = fm.Lines(pipe)
            end.write(b"one\ntwo\nthr")
            self.assertEqual(lines.read(), [b"one", b"two"])       # both at once: none left waiting
            end.write(b"ee\n")
            self.assertEqual(lines.read(), [b"three"])
            end.close()
            self.assertIsNone(lines.read())

    def test_panel_json(self):
        hidden = fm.panel_json({}, None, "off", "behind")
        self.assertEqual(set(hidden), {"title", *fm.BUTTONS})
        self.assertTrue(all(value == {"text": ""} for value in hidden.values()))
        players = {"firefox.instance_1_9": {"status": "Playing", "artist": "", "title": "A" * 60}}
        shown = fm.panel_json(players, "firefox.instance_1_9", "on", "top")
        self.assertEqual(len(shown["title"]["text"]), fm.TITLE_CHARS)
        self.assertTrue(shown["title"]["text"].endswith("…"))
        self.assertIn("Firefox · Playing", shown["title"]["tooltip"])
        self.assertEqual(shown["play"]["tooltip"], "Pause")
        self.assertEqual(shown["spectrum"]["class"], ["on", "top"])
        self.assertIn("Right click: behind windows", shown["spectrum"]["tooltip"])
        ring = fm.panel_json(players, "firefox.instance_1_9", "on", "top", "radial")["spectrum"]
        self.assertEqual(ring["class"], ["on", "behind"])            # the ring is never over windows
        self.assertIn("middle of the screen", ring["tooltip"])
        self.assertNotIn("Right click", ring["tooltip"])
        players["firefox.instance_1_9"]["status"] = "Paused"
        self.assertEqual(fm.panel_json(players, "firefox.instance_1_9", "off", "behind")["play"]["tooltip"], "Play")

    def test_scroll_frame(self):
        self.assertEqual(fm.scroll_frame("Short", 99), "Short")         # fits: never scrolls
        words = "Artist — A rather long song title"
        loop = words + fm.SCROLL_GAP
        for step in range(fm.SCROLL_HOLD + 1):
            self.assertEqual(fm.scroll_frame(words, step), words[:fm.TITLE_CHARS])   # held at the start
        self.assertEqual(fm.scroll_frame(words, fm.SCROLL_HOLD + 1), words[1:fm.TITLE_CHARS + 1])
        self.assertEqual(fm.scroll_frame(words, fm.SCROLL_HOLD + len(loop)), words[:fm.TITLE_CHARS])
        end = fm.scroll_frame(words, fm.SCROLL_HOLD + len(words))
        self.assertTrue(end.startswith(fm.SCROLL_GAP) and end.endswith(words[:fm.TITLE_CHARS - len(fm.SCROLL_GAP)]))
        self.assertTrue(all(len(fm.scroll_frame(words, step)) == fm.TITLE_CHARS for step in range(100)))

    def test_title_without_words_is_the_app(self):
        players = {"spotify": {"status": "Paused", "artist": "", "title": ""}}
        self.assertEqual(fm.panel_json(players, "spotify", "off", "behind")["title"]["text"], "Spotify")


class PanelTest(TempHome):
    def test_panel_edge(self):
        path = os.path.join(self.runtime, fm.WAYBAR_CONFIG)
        self.assertEqual(fm.panel_edge(), "bottom")                       # no panel generated
        bars = [{"position": "bottom", "modules-left": ["clock"]},
                {"position": "top", "modules-right": [fm.TITLE_MODULE, "tray"]}]
        self.write(path, "// Generated by flickos-layout\n" + json.dumps(bars))
        self.assertEqual(fm.panel_edge(), "top")
        self.write(path, "// broken\n[{")
        self.assertEqual(fm.panel_edge(), "bottom")

    def test_follower_writes_files_and_prints_the_title(self):
        folder = fm.runtime_dir()
        follower = fm.Follower(folder)
        follower.waybar = None
        out = io.StringIO()
        with mock.patch.object(follower, "want_strip") as strip, contextlib.redirect_stdout(out):
            follower.on_line(fm.SEP.join(("vlc", "Playing", "Artist", "Song", "")) + "\n")
        self.assertEqual(json.loads(out.getvalue())["text"], "Artist — Song")
        with open(os.path.join(folder, "panel", "play.json"), encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["class"], "playing")
        with open(os.path.join(folder, "player"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "vlc\n")
        strip.assert_called_with(False, "behind", "strip", "style", at_once=True)   # spectrum off
        self.assertEqual(fm.follower_pid(), None)      # the PID isn't a flickos-media follow

    def test_long_title_scrolls_through_once_per_track(self):
        follower = fm.Follower(fm.runtime_dir())
        follower.waybar = None
        song = "A rather long song title that goes on"
        through = fm.SCROLL_HOLD + len(song + fm.SCROLL_GAP)     # steps back to the start
        out = io.StringIO()
        with mock.patch.object(follower, "want_strip"), contextlib.redirect_stdout(out):
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", song, "")) + "\n")
            self.assertIsNotNone(follower.scroll_at)
            self.assertLessEqual(follower.timeout(), fm.SCROLL_SECONDS)
            for _ in range(fm.SCROLL_HOLD + 2):
                follower.scroll()
            follower.on_line(fm.SEP.join(("vlc", "Paused", "", song, "")) + "\n")
            self.assertIsNone(follower.scroll_at)               # paused: still
            self.assertIsNone(follower.timeout())
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", song, "")) + "\n")
            self.assertIsNotNone(follower.scroll_at)            # cut short: from the start again
            for _ in range(through):
                follower.scroll()
            self.assertIsNone(follower.scroll_at)               # once through: done
            follower.on_line(fm.SEP.join(("vlc", "Paused", "", song, "")) + "\n")
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", song, "")) + "\n")
            self.assertIsNone(follower.scroll_at)               # not again for this track
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", "Short", "")) + "\n")
            self.assertIsNone(follower.scroll_at)               # fits: no timer
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", song + " II", "")) + "\n")
            self.assertIsNotNone(follower.scroll_at)            # another track: once more
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        texts = [line["text"] for line in lines]
        # The held steps print nothing new; then one character a step.
        self.assertEqual(texts[:3], [song[:fm.TITLE_CHARS], song[1:fm.TITLE_CHARS + 1],
                                     song[2:fm.TITLE_CHARS + 2]])
        self.assertEqual(lines[0]["class"], ["playing", "scrolling"])
        self.assertEqual(texts[3], fm.short(song))              # paused: its start, with …
        done = texts.index(fm.short(song), 4)                   # through once: the same
        self.assertEqual(lines[done]["class"], "playing")
        # The step that comes back to the start shows it still, with …
        self.assertEqual(texts[done - 1], fm.scroll_frame(song, through - 1))
        self.assertIn("Short", texts)

    def test_second_follower_prints_only(self):
        folder = fm.runtime_dir()
        first, second = fm.Follower(folder), fm.Follower(folder)
        self.assertTrue(first.lead())
        self.addCleanup(first.leader.close)
        out = io.StringIO()
        with mock.patch.object(second, "want_strip") as strip, contextlib.redirect_stdout(out):
            second.update()
        self.assertEqual(json.loads(out.getvalue()), {"text": ""})
        strip.assert_not_called()

    def test_spectrum_starts_while_playing_and_stops_after_a_pause(self):
        folder = fm.runtime_dir()
        follower = fm.Follower(folder)
        follower.waybar = None
        self.write(fm.user_conf(), "[Media]\nSpectrum=on\n")
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(fm.subprocess, "Popen", return_value=process) as popen, \
                contextlib.redirect_stdout(io.StringIO()):
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", "Song", "")) + "\n")
            self.assertEqual(popen.call_args.args[0][1:], ["strip", "--edge", "bottom", "--shape", "strip"])
            follower.on_line(fm.SEP.join(("vlc", "Paused", "", "Song", "")) + "\n")
            self.assertIsNotNone(follower.stop_at)               # stopped STOP_SECONDS later
            process.terminate.assert_not_called()
            self.write(fm.user_conf(), "[Media]\nSpectrum=on\nSpectrumLayer=top\n")
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", "Song", "")) + "\n")
            process.send_signal.assert_called_once_with(signal.SIGUSR1)   # moved, not restarted
            self.assertIsNone(follower.stop_at)
            self.write(fm.user_conf(), "[Media]\nSpectrum=off\n")
            follower.update()
            process.terminate.assert_called_once()               # off: at once

    def test_a_player_without_sound_goes_away(self):
        """Firefox says Playing for a video Discord took off the page."""
        follower = fm.Follower(fm.runtime_dir())
        follower.waybar = None
        self.addCleanup(lambda: follower.leader and follower.leader.close())
        self.write(fm.user_conf(), "[Media]\nSpectrum=on\n")
        audio = mock.Mock(ready=True)
        audio.streams.return_value = [((14245, 990), "firefox-esr")]
        follower.audio = audio                     # as pw-dump would have it
        clock = [100.0]
        out = io.StringIO()
        with mock.patch.object(fm, "player_pid", return_value=14245) as pid, \
                mock.patch.object(fm, "makes_sound", side_effect=lambda p, streams: bool(streams)), \
                mock.patch.object(fm.time, "monotonic", lambda: clock[0]), \
                mock.patch.object(follower, "want_strip") as strip, contextlib.redirect_stdout(out):
            follower.on_line(fm.SEP.join(("firefox.instance_1_9", "Playing", "", "Video", "")) + "\n")
            self.assertEqual(json.loads(out.getvalue().splitlines()[-1])["text"], "Video")
            self.assertIsNone(follower.heard_at)
            audio.streams.return_value = []         # the page took it away
            follower.update()
            self.assertEqual(follower.timeout(), fm.SILENT_SECONDS)
            self.assertEqual(json.loads(out.getvalue().splitlines()[-1])["text"], "Video")   # not yet
            clock[0] += fm.SILENT_SECONDS
            follower.update()
            self.assertEqual(json.loads(out.getvalue().splitlines()[-1]), {"text": ""})
            self.assertIsNone(follower.heard_at)
            strip.assert_called_with(False, "behind", "strip", "style", at_once=False)
            follower.on_line(fm.SEP.join(("firefox.instance_1_9", "Playing", "", "Video", "")) + "\n")
            self.assertEqual(json.loads(out.getvalue().splitlines()[-1]), {"text": ""})   # still silent
            audio.streams.return_value = [((14245, 990), "firefox-esr")]
            follower.update()
            self.assertEqual(json.loads(out.getvalue().splitlines()[-1])["text"], "Video")   # its sound is back
        pid.assert_called_once_with("firefox.instance_1_9")   # asked once per player
        with open(os.path.join(fm.runtime_dir(), "panel", "play.json"), encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["class"], "playing")

    def test_pw_dump_runs_only_while_a_player_says_playing(self):
        follower = fm.Follower(fm.runtime_dir())
        follower.waybar = None
        self.addCleanup(lambda: follower.leader and follower.leader.close())
        watch = mock.Mock(ready=False)
        with mock.patch.object(fm.shutil, "which", return_value="/usr/bin/pw-dump"), \
                mock.patch.object(fm, "AudioWatch", return_value=watch) as start, \
                mock.patch.object(follower, "want_strip"), contextlib.redirect_stdout(io.StringIO()):
            follower.on_line(fm.SEP.join(("vlc", "Paused", "", "Song", "")) + "\n")
            start.assert_not_called()
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", "Song", "")) + "\n")
            start.assert_called_once()
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", "Song II", "")) + "\n")
            start.assert_called_once()
            watch.stop.assert_not_called()
            follower.on_line(fm.SEP.join(("vlc", "Paused", "", "Song II", "")) + "\n")
            watch.stop.assert_called_once()
            self.assertIsNone(follower.audio)

    def test_without_pw_dump_every_player_is_believed(self):
        follower = fm.Follower(fm.runtime_dir())
        follower.waybar = None
        self.addCleanup(lambda: follower.leader and follower.leader.close())
        out = io.StringIO()
        with mock.patch.object(follower, "want_strip"), contextlib.redirect_stdout(out):
            follower.on_line(fm.SEP.join(("vlc", "Playing", "", "Song", "")) + "\n")
        self.assertTrue(follower.audio_broken)
        self.assertEqual(json.loads(out.getvalue())["text"], "Song")

    def test_catches_signal(self):
        old = signal.signal(signal.SIGUSR2, lambda *_: None)
        try:
            self.assertTrue(fm.catches_signal(os.getpid(), signal.SIGUSR2))
        finally:
            signal.signal(signal.SIGUSR2, old)
        self.assertFalse(fm.catches_signal(os.getpid(), signal.SIGRTMIN + fm.PANEL_SIGNAL))


class FollowerProcessTest(TempHome):
    """The real follower against a stand-in playerctl that never prints."""

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp.name, "bin")
        self.write(os.path.join(self.bin, "playerctl"), "#!/bin/sh\n"
                   'case "$*" in *--follow*) exec sleep 60 ;; esac\nexit 0\n')
        os.chmod(os.path.join(self.bin, "playerctl"), 0o755)
        self.env = dict(os.environ, PATH=f"{self.bin}:/usr/bin")

    def test_ends_when_waybar_closes_its_pipe(self):
        """A quiet player must not keep it running after a panel reload."""
        reader, writer = os.pipe()
        process = subprocess.Popen([sys.executable, PROGRAM, "follow"], stdout=writer, env=self.env,
                                   stderr=subprocess.DEVNULL)
        os.close(writer)
        with os.fdopen(reader, "rb") as pipe:
            self.assertEqual(json.loads(pipe.readline()), {"text": ""})
        self.assertEqual(process.wait(10), 0)

    def test_ends_with_sigterm_and_takes_playerctl_along(self):
        process = subprocess.Popen([sys.executable, PROGRAM, "follow"], stdout=subprocess.PIPE, env=self.env,
                                   stderr=subprocess.PIPE)
        self.assertEqual(json.loads(process.stdout.readline()), {"text": ""})
        pid_file = os.path.join(self.runtime, "flickos", "media", "follow.pid")
        with open(pid_file, encoding="utf-8") as f:
            self.assertEqual(int(f.read()), process.pid)
        children = subprocess.run(["pgrep", "-P", str(process.pid)], capture_output=True, text=True).stdout.split()
        process.terminate()
        self.assertEqual(process.wait(10), 0)
        process.stdout.close()
        # In the panel's log: why the media buttons stopped changing.
        self.assertEqual(process.stderr.read().decode(), "flickos-media: follow ended: SIGTERM\n")
        process.stderr.close()
        self.assertFalse(os.path.exists(pid_file))
        deadline = time.monotonic() + 5
        while children and time.monotonic() < deadline and os.path.exists(f"/proc/{children[0]}"):
            time.sleep(0.05)
        for child in children:
            self.assertFalse(os.path.exists(f"/proc/{child}/cmdline") and
                             b"sleep" in open(f"/proc/{child}/cmdline", "rb").read())


class StripTest(unittest.TestCase):
    def test_cava_config(self):
        text = fm.cava_config()
        for line in (f"bars = {fm.BARS}", f"framerate = {fm.FRAMERATE}", f"sleep_timer = {fm.SLEEP_SECONDS}",
                     "method = pipewire", "method = raw", "data_format = binary", "bit_format = 8bit",
                     "channels = mono"):
            self.assertIn(line + "\n", text)

    def test_bar_rectangles(self):
        self.assertEqual(fm.bar_rectangles(bytes(4), 400, 48, "bottom"), [])
        bottom = fm.bar_rectangles(bytes([0, 255, 0, 51]), 400, 48, "bottom")
        self.assertEqual(len(bottom), 2)
        x, y, w, h = bottom[0]
        self.assertEqual((y, h), (0.0, 48.0))                # full height, from the panel up
        self.assertGreater(x, 100) and self.assertLess(x + w, 200)
        self.assertAlmostEqual(bottom[1][1] + bottom[1][3], 48.0)
        top = fm.bar_rectangles(bytes([1]), 10, 48, "top")
        self.assertEqual(top[0][1], 0.0)                     # from the top bar down
        self.assertEqual(top[0][3], 2.0)                     # never thinner than 2 px

    def test_ring_spokes(self):
        self.assertEqual(fm.ring_spokes(bytes(4), 400), [])
        spokes = fm.ring_spokes(bytes([255, 0, 0, 1]), 400)
        self.assertEqual(len(spokes), 4)                     # two bars, mirrored
        inner, middle = 400 * fm.RING_INNER, 200
        def radius(point):
            return math.hypot(point[0] - middle, point[1] - middle)
        loud, mirrored = spokes[0], spokes[1]
        self.assertAlmostEqual(radius(loud[0]), inner)
        self.assertAlmostEqual(radius(loud[1]), middle)      # full: to the square's edge
        self.assertTrue(all(y < middle for _x, y in loud))   # the lowest bar is at the top
        for (x, y), (mx, my) in zip(loud, reversed(mirrored)):
            self.assertAlmostEqual(x - middle, middle - mx)  # left mirrors right
            self.assertAlmostEqual(y, my)
        self.assertAlmostEqual(radius(spokes[2][1]), inner + 2.0)   # never shorter than 2 px
        self.assertTrue(all(0 <= c <= 400 for spoke in spokes for point in spoke for c in point))
        self.assertEqual(fm.radial_size(1366, 768), 384)

    def test_rainbow(self):
        def hue(turn):
            import colorsys
            return colorsys.rgb_to_hsv(*fm.rainbow_color(turn))[0]
        self.assertAlmostEqual(hue(0), 0.5)                  # cyan at the top: the lowest notes
        self.assertAlmostEqual(hue(0.5), 0.0)                # red at the bottom
        self.assertAlmostEqual(hue(0.25), 0.75)              # clockwise: violet on the right
        self.assertEqual(fm.rainbow_color(1), fm.rainbow_color(0))
        sectors = fm.rainbow_sectors(400, 8)
        self.assertEqual(len(sectors), 8)
        corners, colors = sectors[0]
        self.assertEqual((corners[0], corners[3]), ((200, 200), (200, 200)))    # from the middle
        self.assertAlmostEqual(corners[1][0], 200)          # the first edge straight up
        self.assertLess(corners[1][1], 0)                   # past the square's edge
        self.assertGreater(corners[2][0], 200)              # the second clockwise from it
        self.assertEqual(colors[:2], (fm.rainbow_color(0),) * 2)
        self.assertEqual(colors[2:], (fm.rainbow_color(1 / 8),) * 2)
        self.assertEqual(sectors[-1][1][2], fm.rainbow_color(0))    # round to where it started
        for corners, _colors in sectors:                    # every slice reaches past the corners
            for x, y in corners[1:3]:
                self.assertGreater(math.hypot(x - 200, y - 200) * math.cos(math.pi / 8), 200 * math.sqrt(2))

    def test_colors_change_tells_the_strip(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        follower = fm.Follower(folder.name)
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(fm.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(fm, "panel_edge", return_value="bottom"):
            follower.want_strip(True, "behind", "radial", "style")
            follower.want_strip(True, "behind", "radial", "style")
            process.send_signal.assert_not_called()
            follower.want_strip(True, "behind", "radial", "rainbow")
        process.send_signal.assert_called_once_with(signal.SIGUSR1)     # drawn anew, not restarted
        self.assertEqual(popen.call_count, 1)

    def test_shape_change_restarts_the_strip(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        follower = fm.Follower(folder.name)
        first, second = mock.Mock(), mock.Mock()
        first.poll.return_value = second.poll.return_value = None
        with mock.patch.object(fm.subprocess, "Popen", side_effect=[first, second]) as popen, \
                mock.patch.object(fm, "panel_edge", return_value="bottom"):
            follower.want_strip(True, "behind", "strip")
            follower.want_strip(True, "top", "radial")
        first.terminate.assert_called_once()
        first.send_signal.assert_not_called()
        self.assertEqual(popen.call_args.args[0][-2:], ["--shape", "radial"])
        with mock.patch.object(fm.subprocess, "Popen") as popen:
            follower.want_strip(True, "behind", "radial")    # the layer doesn't move the ring
        popen.assert_not_called()
        second.send_signal.assert_not_called()


class PanelModulesTest(unittest.TestCase):
    """flickos-layouts' modules match this program (skipped in build.sh's copy)."""

    def setUp(self):
        self.path = os.path.join(LAYOUTS_COMMON, "modules.jsonc")
        if not os.path.isfile(self.path):
            self.skipTest("flickos-layouts isn't next to this package")

    def test_modules(self):
        with open(self.path, encoding="utf-8") as f:
            text = "".join(line for line in f if not line.lstrip().startswith("//"))
        modules = json.loads(text)
        self.assertEqual(modules[fm.TITLE_MODULE]["exec"], "flickos-media follow")
        # A follower that ended for any reason is started again.
        self.assertGreater(modules[fm.TITLE_MODULE]["restart-interval"], 0)
        for button in fm.BUTTONS:
            module = modules[f"custom/media-{button}"]
            self.assertIn(f"flickos/media/panel/{button}.json", module["exec"])
            self.assertEqual(module["signal"], fm.PANEL_SIGNAL)
            self.assertEqual(module["interval"], "once")
        self.assertEqual(modules["custom/media-spectrum"]["on-click"], "flickos-media toggle spectrum")
        self.assertEqual(modules["custom/media-spectrum"]["on-click-right"], "flickos-media toggle spectrum-layer")
        self.assertNotIn(fm.PANEL_SIGNAL, [m.get("signal") for name, m in modules.items()
                                           if not name.startswith("custom/media-")])

    def test_icon_names(self):
        with open(os.path.join(LAYOUTS_COMMON, "base.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIn('-gtk-icontheme("flickos-spectrum-symbolic")', css)
        self.assertTrue(os.path.isfile(os.path.join(
            PACKAGE, "usr/share/icons/hicolor/scalable/actions/flickos-spectrum-symbolic.svg")))


if __name__ == "__main__":
    unittest.main()
