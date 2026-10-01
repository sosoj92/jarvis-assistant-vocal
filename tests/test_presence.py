import unittest
from unittest import mock

from tools import presence


class PresenceTests(unittest.TestCase):
    def setUp(self):
        presence._THREAD = None
        presence._ETAT.update({"actif": True, "present": None, "absent_depuis": None})

    @mock.patch("tools.presence.threading.Thread")
    @mock.patch("tools.presence.reglage")
    def test_disabled_presence_does_not_start_thread(self, reglage, thread):
        reglage.side_effect = lambda key, default=None: {
            "presence.ip": "telephone.local",
            "presence.actif": False,
        }.get(key, default)

        presence.demarrer_presence()

        thread.assert_not_called()

    @mock.patch("tools.presence.threading.Thread")
    @mock.patch("tools.presence.reglage")
    def test_presence_thread_is_not_started_twice(self, reglage, thread):
        reglage.side_effect = lambda key, default=None: {
            "presence.ip": "telephone.local",
            "presence.actif": True,
        }.get(key, default)
        thread.return_value.is_alive.return_value = True

        presence.demarrer_presence()
        presence.demarrer_presence()

        thread.assert_called_once()
        thread.return_value.start.assert_called_once()

    @mock.patch("tools.presence.demarrer_presence")
    @mock.patch("tools.presence.definir")
    def test_reactivation_starts_service(self, definir, demarrer):
        self.assertEqual(
            presence.detection_presence(True),
            "Detection de presence activee.",
        )
        definir.assert_called_once_with("presence.actif", True)
        demarrer.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
