"""The hooks' events flickos-screenshot fires (docs/design/flickos-hooks.md): `changed`
(ADR-007), `screenshot` and `recording`. fire() itself is held to its contract by flickos-hooks'
tests, which read every copy of it."""

import inspect
import unittest
from unittest import mock

from test_screenshot import fs as M

ALLOWED = list(M.INI_KEYS)
NOT_ALLOWED = ["unknown"]


class ChangedTest(unittest.TestCase):
    """record() queues a change for `changed`, with History off too, and
    fire_changed() fires it with History's owner, key and values once the
    change is applied: when the command is done, never from record()."""

    def setUp(self):
        M.CHANGED.clear()
        self.addCleanup(M.CHANGED.clear)
        self.fire = mock.patch.object(M, "fire").start()
        self.addCleanup(mock.patch.stopall)

    def record(self, key, old, new):
        with mock.patch.object(M, "history_enabled", return_value=False):
            M.record(key, old, new)

    def test_fired_once_applied_with_history_off(self):
        key = ALLOWED[0]
        self.record(key, "old", "new")
        self.fire.assert_not_called()                   # not before it is applied
        M.fire_changed()
        self.fire.assert_called_once_with("changed", owner=M.HISTORY_OWNER, key=key, old="old", new="new")
        M.fire_changed()
        self.assertEqual(self.fire.call_count, 1)       # once

    def test_in_the_order_made(self):
        self.record(ALLOWED[0], "a", "b")
        self.record(ALLOWED[-1], "c", "d")
        M.fire_changed()
        self.assertEqual([c.kwargs["new"] for c in self.fire.call_args_list], ["b", "d"])

    def test_no_change_fires_nothing(self):
        self.record(ALLOWED[0], "same", "same")
        M.fire_changed()
        self.fire.assert_not_called()

    def test_the_allow_list(self):
        for key in ALLOWED:
            self.assertTrue(M.changed_key(key), key)
        for key in NOT_ALLOWED:
            self.assertFalse(M.changed_key(key), key)
            self.record(key, "a", "b")
        M.fire_changed()
        self.fire.assert_not_called()

    def test_main_fires_when_the_command_is_done(self):
        self.assertIn("finally:\n        fire_changed()", inspect.getsource(M.main))


class FileEventsTest(unittest.TestCase):
    def test_a_saved_screenshot_fires_with_its_file(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "run"))
            shot = os.path.join(tmp, "run", "shot.png")
            with open(shot, "wb") as f:
                f.write(b"png")
            with mock.patch.object(M, "fire") as fire, mock.patch.object(M, "copy_picture", return_value=True), \
                    mock.patch.object(M, "notify"), mock.patch("sys.stdout"):
                self.assertEqual(M.finish(shot, folder=os.path.join(tmp, "pictures")), 0)
            (event,), values = fire.call_args
            self.assertEqual(event, "screenshot")
            self.assertTrue(os.path.isfile(values["file"]))
            self.assertEqual(os.path.dirname(values["file"]), os.path.join(tmp, "pictures"))

    def test_a_copy_only_or_unsaved_screenshot_fires_nothing(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "shot.png")
            with open(shot, "wb") as f:
                f.write(b"png")
            with mock.patch.object(M, "fire") as fire, mock.patch.object(M, "copy_picture", return_value=True), \
                    mock.patch.object(M, "notify"):
                M.finish(shot, copy_only=True)
            fire.assert_not_called()

    def test_a_recording_fires_when_saved_not_when_broken(self):
        source = inspect.getsource(M.run_recording)
        self.assertLess(source.index("record-broken"), source.index('fire("recording", file=path)'))
        self.assertLess(source.index('fire("recording", file=path)'), source.index('"recorded-full"'))

    def test_the_bars_sound_fires_before_the_recorder_replaces_it(self):
        source = inspect.getsource(M.cmd_bar)
        self.assertLess(source.index("fire_changed()"), source.index("os.execv("))


if __name__ == "__main__":
    unittest.main()
