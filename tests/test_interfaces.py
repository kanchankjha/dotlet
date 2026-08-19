from __future__ import annotations

import unittest
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from dotlet.interfaces import InterfaceSync, parse_interface_addresses
from dotlet.store import Store


PAYLOAD = [
    {
        "ifname": "lo",
        "flags": ["LOOPBACK", "UP"],
        "addr_info": [{"family": "inet", "local": "127.0.0.1", "scope": "host"}],
    },
    {
        "ifname": "eth0",
        "flags": ["BROADCAST", "UP", "LOWER_UP"],
        "addr_info": [
            {"family": "inet", "local": "192.0.2.10", "scope": "global"},
            {"family": "inet6", "local": "2001:db8::10", "scope": "global"},
            {"family": "inet6", "local": "fe80::10", "scope": "link"},
            {"family": "inet6", "local": "2001:db8::99", "scope": "global", "temporary": True},
        ],
    },
    {
        "ifname": "wlan0",
        "flags": ["BROADCAST"],
        "addr_info": [{"family": "inet", "local": "198.51.100.20", "scope": "global"}],
    },
    {
        "ifname": "docker0",
        "flags": ["BROADCAST", "UP"],
        "addr_info": [{"family": "inet", "local": "172.17.0.1", "scope": "global"}],
    },
]


class InterfaceTests(unittest.TestCase):
    def test_wildcard_includes_eligible_addresses_only(self) -> None:
        self.assertEqual(
            parse_interface_addresses(PAYLOAD, "*", include_ipv4=True, include_ipv6=True),
            ["192.0.2.10", "2001:db8::10"],
        )

    def test_address_families_can_be_selected(self) -> None:
        self.assertEqual(
            parse_interface_addresses(PAYLOAD, "eth0", include_ipv4=False, include_ipv6=True),
            ["2001:db8::10"],
        )

    def test_explicit_virtual_interface_is_allowed(self) -> None:
        self.assertEqual(
            parse_interface_addresses(PAYLOAD, "docker0", include_ipv4=True, include_ipv6=False),
            ["172.17.0.1"],
        )

    def test_sync_discovers_records_and_runs_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = Store(Path(raw) / "dotlet.db")
            store.initialize()
            store.add_zone("home.arpa", 300, "ns1.home.arpa", "hostmaster.home.arpa", "admin")
            store.update_settings(
                False,
                "127.0.0.0/8 ::1/128",
                "admin",
                auto_sync=True,
                sync_interfaces="*",
                sync_ipv4=True,
                sync_ipv6=True,
            )
            sync = InterfaceSync(store, ["/usr/bin/true"], threading.Lock(), interval=2)
            with patch("dotlet.interfaces.discover_interface_addresses", return_value=["192.0.2.10", "2001:db8::10"]):
                self.assertEqual(sync.sync_once(), 2)
            _, records, _ = store.snapshot()
            self.assertEqual(
                {(record.type, record.value) for record in records},
                {("A", "192.0.2.10"), ("AAAA", "2001:db8::10")},
            )


if __name__ == "__main__":
    unittest.main()
