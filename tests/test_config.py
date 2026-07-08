from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from kalshi_research_bot.config import repo_path


def test_repo_path_uses_research_data_dir_for_data_paths() -> None:
    with patch.dict("os.environ", {"RESEARCH_DATA_DIR": "/railway/data"}):
        assert repo_path("data", "today_paper_view.json") == Path("/railway/data/today_paper_view.json")


def test_repo_path_keeps_non_data_paths_in_repo() -> None:
    with patch.dict("os.environ", {"RESEARCH_DATA_DIR": "/railway/data"}):
        assert repo_path("config", "public_intel.local.json").as_posix().endswith(
            "kalshi-research-bot/config/public_intel.local.json"
        )
