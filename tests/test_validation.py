from __future__ import annotations

import unittest

from serveshed.validation import ValidationStatus, validate_repository
from tests.helpers import TemporarySettings


class ValidationTests(unittest.TestCase):
    def test_repository_contract_has_no_static_failures(self) -> None:
        temp = TemporarySettings()
        try:
            findings = validate_repository(temp.settings)
        finally:
            temp.cleanup()
        failures = [finding for finding in findings if finding.status is ValidationStatus.FAIL]
        self.assertEqual([], failures, [finding.as_dict() for finding in failures])
        warnings = [finding.name for finding in findings if finding.status is ValidationStatus.WARN]
        self.assertEqual(["docker-compose-render"], warnings)


if __name__ == "__main__":
    unittest.main()
