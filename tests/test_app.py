from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotlet.app import main
from dotlet.store import Store


class PasswordCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "dotlet.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_command(self, *arguments: str) -> int:
        return main(["--database", str(self.database), "set-password", "admin", *arguments])

    def test_prompt_sets_confirmed_password(self) -> None:
        with patch("dotlet.app.getpass.getpass", side_effect=["chosen-test-password", "chosen-test-password"]):
            self.assertEqual(self.run_command("--prompt"), 0)
        self.assertTrue(Store(self.database).authenticate("admin", "chosen-test-password"))

    def test_prompt_rejects_mismatched_passwords(self) -> None:
        errors = io.StringIO()
        with patch("dotlet.app.getpass.getpass", side_effect=["chosen-test-password", "different-test-password"]):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(self.run_command("--prompt"), 2)
        self.assertIn("passwords do not match", errors.getvalue())
        self.assertFalse(Store(self.database).has_users())

    def test_prompt_rejects_short_password_without_traceback(self) -> None:
        errors = io.StringIO()
        with patch("dotlet.app.getpass.getpass", side_effect=["too-short", "too-short"]):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(self.run_command("--prompt"), 2)
        self.assertIn("at least 12 characters", errors.getvalue())

    def test_default_generates_and_prints_random_password(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(self.run_command(), 0)
        generated = output.getvalue().strip()
        self.assertGreaterEqual(len(generated), 12)
        self.assertTrue(Store(self.database).authenticate("admin", generated))


if __name__ == "__main__":
    unittest.main()
