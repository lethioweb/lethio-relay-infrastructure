from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCATION = (ROOT / "nginx/lethio-off-relay-location.conf").read_text(encoding="utf-8")
RATE_LIMIT = (ROOT / "nginx/lethio-off-relay-rate-limit.conf").read_text(encoding="utf-8")
SERVICE = (ROOT / "systemd/lethio-off-relay.service").read_text(encoding="utf-8")


class NginxPolicyTest(unittest.TestCase):
    def test_public_surface_is_one_exact_location(self) -> None:
        self.assertEqual(LOCATION.count("location = /v1/off/contributions"), 1)
        self.assertIn("limit_except POST", LOCATION)

    def test_endpoint_is_unlogged(self) -> None:
        blocks = re.split(r"(?m)(?=^location )", LOCATION)
        for block in blocks[1:]:
            self.assertIn("access_log off;", block)
            self.assertIn("error_log /dev/null crit;", block)

    def test_client_identity_is_not_forwarded(self) -> None:
        self.assertIn('proxy_set_header X-Forwarded-For "";', LOCATION)
        self.assertIn('proxy_set_header X-Real-IP "";', LOCATION)
        self.assertNotIn("$proxy_add_x_forwarded_for", LOCATION)

    def test_request_target_is_fixed(self) -> None:
        self.assertIn('set $args "";', LOCATION)
        self.assertIn(
            "proxy_pass http://127.0.0.1:8087/v1/off/contributions;", LOCATION
        )

    def test_body_and_time_are_bounded(self) -> None:
        for directive in (
            "client_max_body_size 2k;",
            "client_body_timeout 5s;",
            "proxy_connect_timeout 1s;",
            "proxy_send_timeout 5s;",
            "proxy_read_timeout 10s;",
        ):
            self.assertIn(directive, LOCATION)

    def test_edge_failures_are_fixed_json(self) -> None:
        expected = {
            "404": "not_found",
            "413": "refused",
            "429": "rate_limited",
            "503": "unavailable",
        }
        for status, state in expected.items():
            self.assertIn(f"return {status} '{{\"status\":\"{state}\"}}';", LOCATION)

    def test_rate_limit_is_bounded_volatile_memory(self) -> None:
        self.assertRegex(
            RATE_LIMIT,
            r"limit_req_zone\s+\$binary_remote_addr\s+"
            r"zone=lethio_off_relay_per_ip:1m\s+rate=6r/m;",
        )


class SystemdPolicyTest(unittest.TestCase):
    def test_relay_is_loopback_only_and_unprivileged(self) -> None:
        self.assertIn("User=lethio-off-relay", SERVICE)
        self.assertIn("Group=lethio-off-relay", SERVICE)
        self.assertIn("LETHIO_RELAY_LISTEN_HOST=127.0.0.1", SERVICE)

    def test_credential_is_referenced_by_path_not_value(self) -> None:
        self.assertIn(
            "LETHIO_RELAY_OFF_CREDENTIALS_FILE=/etc/lethio-off-relay/off-credentials.json",
            SERVICE,
        )
        self.assertNotRegex(SERVICE, r"OFF_(?:PASSWORD|USER_ID)=")

    def test_service_has_no_routine_log_sink(self) -> None:
        self.assertIn("StandardOutput=null", SERVICE)
        self.assertIn("StandardError=null", SERVICE)
        self.assertIn("LimitCORE=0", SERVICE)

    def test_service_has_no_capabilities_or_writable_application_path(self) -> None:
        self.assertIn("ProtectSystem=strict", SERVICE)
        self.assertIn("ReadOnlyPaths=/opt/lethio-off-relay/current", SERVICE)
        self.assertRegex(SERVICE, r"(?m)^CapabilityBoundingSet=$")
        self.assertRegex(SERVICE, r"(?m)^AmbientCapabilities=$")
        self.assertNotIn("ReadWritePaths=", SERVICE)


if __name__ == "__main__":
    unittest.main()
