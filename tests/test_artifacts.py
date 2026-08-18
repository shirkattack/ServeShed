from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from serveshed.artifacts import (
    ArtifactError,
    percentile,
    verify_checksums,
    write_checksums,
    write_jsonl,
)


class ArtifactTests(unittest.TestCase):
    def test_checksum_manifest_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw)
            target = run_dir / "summary.json"
            target.write_text("{}\n", encoding="utf-8")
            write_checksums(run_dir)
            initial = verify_checksums(run_dir)
            self.assertTrue(all(item.ok for item in initial))

            target.write_text('{"changed":true}\n', encoding="utf-8")
            changed = verify_checksums(run_dir)
            self.assertFalse(changed[0].ok)

    def test_percentile_interpolates(self) -> None:
        self.assertEqual(1.0, percentile([1.0], 95))
        self.assertAlmostEqual(3.85, percentile([1.0, 2.0, 3.0, 4.0], 95))

    def test_write_jsonl_replaces_with_exact_payload_set(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "input.jsonl"
            write_jsonl(target, ({"id": "one"}, {"id": "two"}))
            write_jsonl(target, ({"id": "selected"},))
            rows = [json.loads(line) for line in target.read_text().splitlines()]
            self.assertEqual([{"id": "selected"}], rows)

    def test_checksum_manifest_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw) / "run"
            run_dir.mkdir()
            (run_dir / "checksums.sha256").write_text(
                f"{'0' * 64}  ../outside.txt\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ArtifactError, "Unsafe checksum path"):
                verify_checksums(run_dir)

    def test_checksum_manifest_detects_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw)
            (run_dir / "summary.json").write_text("{}\n", encoding="utf-8")
            write_checksums(run_dir)
            (run_dir / "extra.json").write_text("{}\n", encoding="utf-8")
            results = verify_checksums(run_dir)
            extra = next(item for item in results if item.path == "extra.json")
            self.assertFalse(extra.ok)
            self.assertIn("not listed", extra.detail)


if __name__ == "__main__":
    unittest.main()
