from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_SCRIPT = ROOT / "scripts" / "local.sh"


class LocalWorkflowEntrypointTests(unittest.TestCase):
    def _run(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(LOCAL_SCRIPT), command],
            cwd=ROOT,
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_help_does_not_require_local_configuration_or_docker(self) -> None:
        result = self._run("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage: scripts/local.sh <command>", result.stdout)
        self.assertIn("test", result.stdout)

    def test_unknown_command_is_rejected_before_runtime_preflight(self) -> None:
        result = self._run("not-a-command")

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown local workflow command: not-a-command", result.stderr)
        self.assertNotIn("POSTGRES_PASSWORD", result.stderr)
        self.assertNotIn("Docker is required", result.stderr)

    def test_database_workflow_explains_the_missing_canonical_runtime(self) -> None:
        result = self._run("test")

        self.assertEqual(result.returncode, 127)
        self.assertIn("Docker is required", result.stderr)
        self.assertIn("repository Codespace", result.stderr)
        self.assertNotIn("command not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
