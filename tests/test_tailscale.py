from __future__ import annotations

import unittest
from unittest.mock import patch

from serveshed.tailscale import plan
from tests.helpers import TemporarySettings


class TailscaleTests(unittest.TestCase):
    def test_default_plan_is_serve_only_and_never_public(self) -> None:
        temporary = TemporarySettings()
        try:
            with patch("serveshed.tailscale.command_exists", return_value=False):
                result = plan(temporary.settings)
        finally:
            temporary.cleanup()

        rendered = "\n".join((*result.commands, *result.rollback, *result.notes)).lower()
        self.assertIn("tailscale serve", rendered)
        self.assertIn(str(temporary.settings.openwebui_port), "\n".join(result.commands))
        self.assertIn("admin-console action", rendered)
        self.assertNotIn("funnel", "\n".join(result.commands).lower())
        self.assertNotIn("--ssh", "\n".join(result.commands).lower())
        self.assertIn("ssh is optional", rendered)
        self.assertNotIn("11434", rendered)
        self.assertNotIn("8000", rendered)


if __name__ == "__main__":
    unittest.main()
