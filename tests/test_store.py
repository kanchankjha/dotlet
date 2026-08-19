from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dotlet.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "dotlet.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_user_authentication(self) -> None:
        self.assertFalse(self.store.has_users())
        self.store.set_password("admin", "long-test-password")
        self.assertTrue(self.store.has_users())
        self.assertTrue(self.store.authenticate("admin", "long-test-password"))
        self.assertFalse(self.store.authenticate("admin", "wrong-password"))

    def test_zone_record_and_serial_lifecycle(self) -> None:
        zone_id = self.store.add_zone("example.test", 300, "ns1.example.test", "hostmaster.example.test", "admin")
        zones, _, _ = self.store.snapshot()
        original_serial = zones[0].serial
        record_id = self.store.add_record(zone_id, "www", "AAAA", "2001:db8::5", "", "admin")
        zones, records, _ = self.store.snapshot()
        self.assertGreater(zones[0].serial, original_serial)
        self.assertEqual(records[0].value, "2001:db8::5")
        self.store.delete_record(record_id, "admin")
        self.assertEqual(self.store.snapshot()[1], [])

    def test_settings_normalize_networks(self) -> None:
        self.store.update_settings(True, "192.0.2.9/24 2001:db8::1/64", "admin")
        settings = self.store.snapshot()[2]
        self.assertEqual(settings["recursion"], "yes")
        self.assertEqual(settings["trusted_networks"], "192.0.2.0/24\n2001:db8::/64")


if __name__ == "__main__":
    unittest.main()
