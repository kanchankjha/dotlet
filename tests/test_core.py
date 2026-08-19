from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dotlet.core import Record, ValidationError, Zone, next_serial, render_all, validate_networks, validate_record


class CoreTests(unittest.TestCase):
    def test_ipv4_and_ipv6_records(self) -> None:
        self.assertEqual(validate_record("A", "192.0.2.7"), ("A", "192.0.2.7"))
        self.assertEqual(validate_record("AAAA", "2001:db8::7"), ("AAAA", "2001:db8::7"))
        with self.assertRaises(ValidationError):
            validate_record("A", "2001:db8::7")

    def test_structured_records_are_normalized(self) -> None:
        self.assertEqual(validate_record("mx", "10 mail.example.test"), ("MX", "10 mail.example.test."))
        self.assertEqual(validate_record("TXT", 'hello "dns"'), ("TXT", '"hello \\"dns\\""'))
        self.assertEqual(validate_record("CAA", "0 issue letsencrypt.org"), ("CAA", '0 issue "letsencrypt.org"'))

    def test_network_validation_accepts_both_families(self) -> None:
        self.assertEqual(validate_networks("192.0.2.4/24, 2001:db8::1/64"), ["192.0.2.0/24", "2001:db8::/64"])

    def test_serial_uses_date_and_increments(self) -> None:
        now = datetime(2026, 8, 19, tzinfo=timezone.utc)
        self.assertEqual(next_serial(0, now), 2026081900)
        self.assertEqual(next_serial(2026081900, now), 2026081901)

    def test_rendered_config_listens_on_ipv4_and_ipv6(self) -> None:
        zone = Zone(1, "example.test", 300, "ns1.example.test", "hostmaster.example.test", 2026081900)
        records = [Record(1, 1, "www", "A", "192.0.2.10"), Record(2, 1, "www", "AAAA", "2001:db8::10")]
        output = render_all([zone], records, {"recursion": "no", "trusted_networks": "192.0.2.0/24\n2001:db8::/64"}, Path("/etc/bind/dotlet/zones"))
        config = output["named.conf.generated"]
        self.assertIn("listen-on port 53 { any; };", config)
        self.assertIn("listen-on-v6 port 53 { any; };", config)
        self.assertIn("recursion no;", config)
        self.assertIn("www IN AAAA 2001:db8::10", output["zones/db.example.test"])


if __name__ == "__main__":
    unittest.main()
