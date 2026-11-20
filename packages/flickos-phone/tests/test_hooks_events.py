"""The hooks' events flickos-phone fires (docs/design/flickos-hooks.md): `changed`
(ADR-007), `phone-connected` and `phone-disconnected`. fire() itself is held to its contract by flickos-hooks'
tests, which read every copy of it."""

import inspect
import unittest
from unittest import mock

from test_phone import fp as M

ALLOWED = [*(name.replace("_", "-") for name in M.KEYS), "device.abc"]
NOT_ALLOWED = ["notification_apps", "unknown"]


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


class PhoneEventsTest(unittest.TestCase):
    def test_connected_and_disconnected(self):
        fake = mock.Mock()
        link = mock.Mock(id="abc", name="x", address="10.0.0.2", battery=None)
        link.name = "Sofia's phone; rm -rf"
        with mock.patch.object(M, "fire") as fire:
            M.Daemon.watch_connected(fake, link)
            M.Daemon.watch_disconnected(fake, "abc")
        self.assertEqual(fire.call_args_list, [
            mock.call("phone-connected", phone_id="abc", phone_name="Sofia's phone; rm -rf"),
            mock.call("phone-disconnected", phone_id="abc")])

    def test_pairing_changes_fire_in_the_daemon(self):
        for method in ("unpair", "accept_pairing", "forget"):
            self.assertIn("fire_changed()", inspect.getsource(getattr(M.Daemon, method)), method)


if __name__ == "__main__":
    unittest.main()
