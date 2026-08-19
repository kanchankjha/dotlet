from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotlet.apply import apply, configuration_is_valid, find_tool, install_empty_configuration, main
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

    def test_install_recovery_creates_safe_empty_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "bind"
            old = os.environ.get("DOTLET_ALLOW_UNPRIVILEGED_APPLY")
            os.environ["DOTLET_ALLOW_UNPRIVILEGED_APPLY"] = "1"
            try:
                install_empty_configuration(target, "/usr/bin/true")
                configuration = target / "named.conf.generated"
                self.assertTrue(configuration.exists())
                self.assertTrue(configuration_is_valid(target, "/usr/bin/true"))
                self.assertNotIn('zone "', configuration.read_text())
                self.assertIn("127.0.0.0/8", configuration.read_text())
                self.assertNotIn(".dotlet-recovery-", configuration.read_text())
            finally:
                if old is None:
                    os.environ.pop("DOTLET_ALLOW_UNPRIVILEGED_APPLY", None)
                else:
                    os.environ["DOTLET_ALLOW_UNPRIVILEGED_APPLY"] = old

    def test_install_recovery_replaces_invalid_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "bind"
            target.mkdir()
            (target / "named.conf.generated").write_text("invalid")
            old = os.environ.get("DOTLET_ALLOW_UNPRIVILEGED_APPLY")
            os.environ["DOTLET_ALLOW_UNPRIVILEGED_APPLY"] = "1"
            try:
                install_empty_configuration(target, "/usr/bin/true")
                self.assertNotEqual((target / "named.conf.generated").read_text(), "invalid")
            finally:
                if old is None:
                    os.environ.pop("DOTLET_ALLOW_UNPRIVILEGED_APPLY", None)
                else:
                    os.environ["DOTLET_ALLOW_UNPRIVILEGED_APPLY"] = old

    def test_install_mode_continues_with_last_valid_configuration(self) -> None:
        errors = io.StringIO()
        arguments = ["dotlet-apply", "--install"]
        with patch.object(sys, "argv", arguments):
            with patch("dotlet.apply.find_tool", return_value="/usr/bin/true"):
                with patch("dotlet.apply.apply", side_effect=RuntimeError("invalid saved zone")):
                    with patch("dotlet.apply.configuration_is_valid", return_value=True):
                        with contextlib.redirect_stderr(errors):
                            self.assertEqual(main(), 0)
        self.assertIn("continuing with the last valid configuration", errors.getvalue())

    def test_normal_apply_still_reports_invalid_configuration(self) -> None:
        errors = io.StringIO()
        with patch.object(sys, "argv", ["dotlet-apply"]):
            with patch("dotlet.apply.find_tool", return_value="/usr/bin/true"):
                with patch("dotlet.apply.apply", side_effect=RuntimeError("invalid saved zone")):
                    with contextlib.redirect_stderr(errors):
                        self.assertEqual(main(), 1)
        self.assertIn("invalid saved zone", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
