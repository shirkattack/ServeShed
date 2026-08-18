from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from serveshed.backup import execute_backup, initialize_nas, inspect_nas, plan_backup
from tests.helpers import TemporarySettings


class FakeCompose:
    def dump_database(self, database: str) -> str:
        return f"-- dump for {database}\n"


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporarySettings()
        self.settings = self.temp.settings
        self.settings.nas_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_unmounted_nas_is_fail_closed(self) -> None:
        with patch("serveshed.backup.os.path.ismount", return_value=False):
            state = inspect_nas(self.settings)
            self.assertFalse(state.ready)
            self.assertIsNone(plan_backup(self.settings).destination)
            with self.assertRaisesRegex(RuntimeError, "not a mount point"):
                initialize_nas(self.settings, execute=True)

    def test_marker_enables_versioned_backup(self) -> None:
        when = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        with patch("serveshed.backup.os.path.ismount", return_value=True):
            state = initialize_nas(self.settings, execute=True)
            self.assertTrue(state.ready)
            destination = execute_backup(
                self.settings,
                compose=FakeCompose(),  # type: ignore[arg-type]
                now=when,
            )
        self.assertEqual("20260814T120000Z", destination.name)
        self.assertTrue((destination / "postgres/phoenix.sql").is_file())
        self.assertTrue((destination / "checksums.sha256").is_file())
        self.assertTrue((destination / "project/examples/simple_client.py").is_file())
        self.assertTrue((destination / "project/LICENSE").is_file())
        self.assertTrue((destination / "project/config/hermes/.env.example").is_file())
        self.assertFalse((destination / "project/.env").exists())
        self.assertFalse((destination / "project/config/hermes/.env").exists())


if __name__ == "__main__":
    unittest.main()
