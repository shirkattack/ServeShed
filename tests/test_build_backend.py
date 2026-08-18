from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import serveshed_build
from serveshed import __version__


class BuildBackendTests(unittest.TestCase):
    def test_version_has_one_source_of_truth(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        expected = project["project"]["version"]
        self.assertEqual(expected, __version__)
        self.assertEqual(expected, serveshed_build.VERSION)
        self.assertIn(expected, serveshed_build.WHEEL_NAME)


if __name__ == "__main__":
    unittest.main()
