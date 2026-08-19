from __future__ import annotations

import tempfile
import unittest
import sqlite3
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
        self.store.update_settings(
            True,
            "192.0.2.9/24 2001:db8::1/64",
            "admin",
            auto_sync=True,
            sync_interfaces="eth0, wlan0",
            sync_ipv4=True,
            sync_ipv6=False,
        )
        settings = self.store.snapshot()[2]
        self.assertEqual(settings["recursion"], "yes")
        self.assertEqual(settings["trusted_networks"], "192.0.2.0/24\n2001:db8::/64")
        self.assertEqual(settings["auto_sync"], "yes")
        self.assertEqual(settings["sync_interfaces"], "eth0 wlan0")
        self.assertEqual(settings["sync_ipv6"], "no")

    def test_interface_sync_manages_primary_nameserver_addresses(self) -> None:
        zone_id = self.store.add_zone("home.arpa", 300, "ns1.home.arpa", "hostmaster.home.arpa", "admin")
        self.store.add_record(zone_id, "ns1", "A", "192.0.2.5", None, "admin")
        self.assertEqual(self.store.sync_primary_addresses(["192.0.2.5", "192.0.2.10", "2001:db8::10"]), 2)
        _, records, _ = self.store.snapshot()
        automatic = [record for record in records if record.managed_by == "interface-sync"]
        self.assertEqual({(record.type, record.value) for record in automatic}, {("A", "192.0.2.10"), ("AAAA", "2001:db8::10")})
        self.assertEqual(self.store.sync_primary_addresses(["192.0.2.20"]), 3)
        _, records, _ = self.store.snapshot()
        self.assertIn("192.0.2.5", {record.value for record in records})
        self.assertEqual(
            {(record.type, record.value) for record in records if record.managed_by == "interface-sync"},
            {("A", "192.0.2.20")},
        )

    def test_existing_database_receives_managed_by_migration(self) -> None:
        legacy = Path(self.temp.name) / "legacy.db"
        with sqlite3.connect(legacy) as db:
            db.execute(
                "CREATE TABLE records (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, type TEXT NOT NULL, value TEXT NOT NULL, ttl INTEGER, "
                "UNIQUE(zone_id, name, type, value))"
            )
        migrated = Store(legacy)
        migrated.initialize()
        with migrated.connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(records)")}
        self.assertIn("managed_by", columns)


if __name__ == "__main__":
    unittest.main()
