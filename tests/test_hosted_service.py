from __future__ import annotations

import argparse
import os
import unittest
from unittest import mock

from kalshi_research_bot import cli


class HostedWebRefreshTests(unittest.TestCase):
    """The repository's start command must mean what the deployed one means.

    Production runs the dashboard with a 300-second self-refresh. The hosted
    entry point used to hardcode `refresh_seconds=0`, so adopting the
    repository's `service-start` command would have quietly stopped the
    refreshes that `/readyz` reports `fresh_data_ready` from.
    """

    def _refresh(self, value: str | None) -> int:
        env = {k: v for k, v in os.environ.items() if k != "DASHBOARD_REFRESH_SECONDS"}
        if value is not None:
            env["DASHBOARD_REFRESH_SECONDS"] = value
        with mock.patch.dict(os.environ, env, clear=True):
            return cli.hosted_web_refresh_seconds()

    def test_unset_keeps_refreshing(self) -> None:
        self.assertEqual(self._refresh(None), cli.HOSTED_WEB_REFRESH_SECONDS)
        self.assertGreater(cli.HOSTED_WEB_REFRESH_SECONDS, 0)

    def test_blank_is_treated_as_unset(self) -> None:
        self.assertEqual(self._refresh("   "), cli.HOSTED_WEB_REFRESH_SECONDS)

    def test_explicit_cadence_is_honoured(self) -> None:
        self.assertEqual(self._refresh("600"), 600)

    def test_zero_disables_refreshing(self) -> None:
        """A deployment whose data comes only from collector workers may opt out."""

        self.assertEqual(self._refresh("0"), 0)

    def test_negative_is_clamped_not_rejected(self) -> None:
        self.assertEqual(self._refresh("-5"), 0)

    def test_unparseable_falls_back_rather_than_crashing(self) -> None:
        self.assertEqual(self._refresh("every-5-minutes"), cli.HOSTED_WEB_REFRESH_SECONDS)

    def test_web_role_starts_the_server_with_that_cadence(self) -> None:
        env = {
            "HAWKNETIC_SERVICE": "web",
            "PORT": "8080",
            "DASHBOARD_REFRESH_SECONDS": "300",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(cli, "run_server") as started:
                exit_code = cli.run_hosted_service(argparse.Namespace())

        self.assertEqual(exit_code, 0)
        started.assert_called_once_with(host="0.0.0.0", port=8080, refresh_seconds=300)


if __name__ == "__main__":
    unittest.main()
