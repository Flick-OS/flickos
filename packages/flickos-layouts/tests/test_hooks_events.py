"""The hooks' events flickos-layout fires (docs/design/flickos-hooks.md): `changed`
(ADR-007) and `screens`. fire() itself is held to its contract by flickos-hooks'
tests, which read every copy of it."""

import inspect
import unittest
from unittest import mock

from test_engine import fl as M

ALLOWED = [*M.CHANGED_CHOICES, "pinned.redmond"]
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


class LayoutHooksTest(unittest.TestCase):
    def test_every_choice_apply_choice_records_is_allowed(self):
        source = inspect.getsource(M.apply_choice)
        chosen = source[source.index("chosen = {"):source.index("resolvers = {")]
        import re
        kinds = re.findall(r'\("([a-z-]+)", [a-z_]+_id\)', chosen)
        self.assertEqual(sorted(kinds), sorted(M.CHANGED_CHOICES))

    def test_screens_fires_from_the_panels_supervisor(self):
        source = inspect.getsource(M.supervise)
        watch = source[source.index("def screens_changed():"):source.index("restart_child(\"the screens changed\")")]
        self.assertIn('fire("screens")', watch)
        self.assertEqual(M.RESTART_ON_SCREENS, ("waybar",))     # one supervisor: fired once

    def test_watch_fires_after_each_apply(self):
        self.assertIn("fire_changed()", inspect.getsource(M.cmd_watch))


if __name__ == "__main__":
    unittest.main()
