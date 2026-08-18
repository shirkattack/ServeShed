from __future__ import annotations

import unittest
from typing import ClassVar
from unittest.mock import Mock, patch

from serveshed import banner


class PlainLenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original = banner.COLOUR
        banner.COLOUR = True

    def tearDown(self) -> None:
        banner.COLOUR = self._original

    def test_plain_len_ignores_sgr_codes(self) -> None:
        styled = banner.c("hello", banner.BOLD, banner.LAMP)
        self.assertEqual(5, banner.plain_len(styled))

    def test_plain_len_counts_hyperlink_text_once(self) -> None:
        # A domain containing "m" (or a backslash) used to break the old
        # "scan for the first m or backslash" terminator search, since that
        # search can't tell an OSC 8 sequence's own opening/closing escapes
        # apart from the visible URL text sitting between them.
        url = "https://example.com"
        self.assertEqual(len(url), banner.plain_len(banner.link(url)))

    def test_plain_len_handles_url_without_m_too(self) -> None:
        url = "http://127.0.0.1:8080"
        self.assertEqual(len(url), banner.plain_len(banner.link(url)))


class ParseSizeGibTests(unittest.TestCase):
    def test_parses_gb_and_gib(self) -> None:
        self.assertEqual(5.6, banner.parse_size_gib("5.6 GB"))
        self.assertEqual(6.6, banner.parse_size_gib("6.6 GiB"))

    def test_parses_mb(self) -> None:
        self.assertAlmostEqual(0.5, banner.parse_size_gib("512 MB"), places=3)

    def test_unparseable_returns_none(self) -> None:
        self.assertIsNone(banner.parse_size_gib("not a size"))
        self.assertIsNone(banner.parse_size_gib(""))


class ParseProcessorSplitTests(unittest.TestCase):
    def test_full_gpu_is_resident(self) -> None:
        self.assertEqual(("resident", 1.0), banner.parse_processor_split("100% GPU"))

    def test_full_cpu_is_spilling_at_zero(self) -> None:
        self.assertEqual(("spilling", 0.0), banner.parse_processor_split("100% CPU"))

    def test_split_reports_gpu_fraction(self) -> None:
        residency, fraction = banner.parse_processor_split("43%/57% CPU/GPU")
        self.assertEqual("spilling", residency)
        self.assertAlmostEqual(0.57, fraction)


class CheckHostOllamaCollisionTests(unittest.TestCase):
    def test_reports_when_something_listens_on_11434(self) -> None:
        with patch("serveshed.banner.socket.socket") as mock_socket_cls:
            mock_socket = Mock()
            mock_socket.connect_ex.return_value = 0
            mock_socket_cls.return_value.__enter__.return_value = mock_socket
            warning = banner.check_host_ollama_collision()
        self.assertIsNotNone(warning)
        self.assertIn("11434", warning)

    def test_silent_when_port_is_closed(self) -> None:
        with patch("serveshed.banner.socket.socket") as mock_socket_cls:
            mock_socket = Mock()
            mock_socket.connect_ex.return_value = 111  # ECONNREFUSED
            mock_socket_cls.return_value.__enter__.return_value = mock_socket
            self.assertIsNone(banner.check_host_ollama_collision())


class CheckStaleContainersTests(unittest.TestCase):
    def test_reports_containers_under_a_different_project_name(self) -> None:
        result = Mock(stdout="homelab\nhomelab\n")
        with patch("serveshed.banner.subprocess.run", return_value=result):
            warning = banner.check_stale_containers("/repo", "serveshed")
        self.assertIsNotNone(warning)
        self.assertIn("homelab", warning)

    def test_silent_when_only_the_current_project_is_running(self) -> None:
        result = Mock(stdout="serveshed\nserveshed\n")
        with patch("serveshed.banner.subprocess.run", return_value=result):
            self.assertIsNone(banner.check_stale_containers("/repo", "serveshed"))

    def test_silent_when_nothing_is_running(self) -> None:
        result = Mock(stdout="")
        with patch("serveshed.banner.subprocess.run", return_value=result):
            self.assertIsNone(banner.check_stale_containers("/repo", "serveshed"))


class RenderSmokeTests(unittest.TestCase):
    _GPU: ClassVar[dict[str, object]] = {
        "name": "RTX 5070 Ti",
        "used_gib": 0.5,
        "total_gib": 16.0,
        "temp_c": 50.0,
        "watts": 30.0,
        "cap_w": 300.0,
    }

    def test_render_does_not_crash_on_an_empty_rig(self) -> None:
        output = banner.render(banner.Rig())
        self.assertIn("serveshed", output)

    def test_core_target_does_not_claim_a_runtime_holds_the_card(self) -> None:
        output = banner.render(banner.Rig(profile="core", runtime=None, gpu=self._GPU))
        self.assertNotIn("holds the card", output)
        self.assertIn("core only", output)

    def test_render_uses_configured_ports_not_defaults(self) -> None:
        rig = banner.Rig(
            gateway=banner.Service("Bifrost", 18080, banner.GATEWAY_NOTE),
            surfaces=[
                banner.Service("Open WebUI", 13000, "chat + history"),
                banner.Service("Phoenix", 16006, "traces · content logging ON"),
            ],
        )
        output = banner.render(rig)
        self.assertIn(":18080", output)
        self.assertIn(":13000", output)
        self.assertIn(":16006", output)
        self.assertNotIn(":8080", output)

    def test_zero_resolved_aliases_is_not_reported_as_a_rejected_key(self) -> None:
        output = banner.render(banner.Rig(gateway_aliases=0))
        self.assertIn("0 aliases resolve", output)
        self.assertNotIn("key rejected", output)

    def test_missing_virtual_key_reports_skipped_probe_not_rejection(self) -> None:
        rig = banner.Rig(gateway_key_present=False)
        with patch.object(banner.Service, "listening", return_value=True):
            output = banner.render(rig)
        self.assertIn("auth probe skipped", output)
        self.assertNotIn("key rejected", output)

    def test_unknown_residency_reports_inventory_unavailable_not_not_pulled(self) -> None:
        rig = banner.Rig(models=[banner.Model("local/qwen-fast", "default", "unknown")])
        output = banner.render(rig)
        self.assertIn("inventory unavailable", output)
        self.assertNotIn("not pulled", output)

    def test_render_shows_every_model_and_warning(self) -> None:
        rig = banner.Rig(
            profile="chat",
            runtime="ollama",
            gpu={
                "name": "RTX 5070 Ti",
                "used_gib": 5.0,
                "total_gib": 16.0,
                "temp_c": 60.0,
                "watts": 150.0,
                "cap_w": 300.0,
            },
            models=[
                banner.Model(
                    "local/qwen-fast", "default", "resident", gib=5.6, ttl="4 minutes from now"
                ),
                banner.Model("local/embed", "review-gated", "registered"),
            ],
            gateway_aliases=6,
            warnings=["NAS marker missing -- backups will refuse to run"],
        )
        output = banner.render(rig)
        self.assertIn("local/qwen-fast", output)
        self.assertIn("local/embed", output)
        self.assertIn("NAS marker missing", output)
        self.assertIn("6 aliases resolve", output)


if __name__ == "__main__":
    unittest.main()
