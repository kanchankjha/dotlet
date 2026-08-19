from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotlet.apply import apply, find_tool
from dotlet.store import Store


class ApplyTests(unittest.TestCase):
    def test_tools_are_resolved_from_path(self) -> None:
        with patch("dotlet.apply.shutil.which", return_value="/usr/bin/named-checkconf"):
            self.assertEqual(find_tool("named-checkconf"), "/usr/bin/named-checkconf")
        with patch("dotlet.apply.shutil.which", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "bind9-utils"):
                find_tool("named-checkconf")

    def test_apply_generates_validated_tree_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            database = root / "dotlet.db"
            store = Store(database)
            store.initialize()
            zone_id = store.add_zone("example.test", 300, "ns1.example.test", "hostmaster.example.test", "admin")
            store.add_record(zone_id, "router", "A", "192.0.2.1", None, "admin")
            old = os.environ.get("DOTLET_ALLOW_UNPRIVILEGED_APPLY")
            os.environ["DOTLET_ALLOW_UNPRIVILEGED_APPLY"] = "1"
            try:
                kwargs = dict(checkconf="/usr/bin/true", checkzone="/usr/bin/true", rndc="/usr/bin/true")
                apply(database, root / "bind", root / "backups", **kwargs)
                self.assertTrue((root / "bind/named.conf.generated").exists())
                self.assertIn("192.0.2.1", (root / "bind/zones/db.example.test").read_text())
                apply(database, root / "bind", root / "backups", **kwargs)
                self.assertEqual(len(list((root / "backups").iterdir())), 1)
            finally:
                if old is None:
                    os.environ.pop("DOTLET_ALLOW_UNPRIVILEGED_APPLY", None)
                else:
                    os.environ["DOTLET_ALLOW_UNPRIVILEGED_APPLY"] = old

    def test_failed_reload_restores_previous_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            database = root / "dotlet.db"
            target = root / "bind"
            target.mkdir()
            (target / "marker").write_text("previous")
            store = Store(database)
            store.initialize()
            store.add_zone("example.test", 300, "ns1.example.test", "hostmaster.example.test", "admin")
            old = os.environ.get("DOTLET_ALLOW_UNPRIVILEGED_APPLY")
            os.environ["DOTLET_ALLOW_UNPRIVILEGED_APPLY"] = "1"
            try:
                with self.assertRaises(RuntimeError):
                    apply(database, target, root / "backups", checkconf="/usr/bin/true", checkzone="/usr/bin/true", rndc="/usr/bin/false")
                self.assertEqual((target / "marker").read_text(), "previous")
            finally:
                if old is None:
                    os.environ.pop("DOTLET_ALLOW_UNPRIVILEGED_APPLY", None)
                else:
                    os.environ["DOTLET_ALLOW_UNPRIVILEGED_APPLY"] = old


if __name__ == "__main__":
    unittest.main()
