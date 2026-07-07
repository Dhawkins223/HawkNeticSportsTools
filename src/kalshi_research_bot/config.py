from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def repo_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[2].joinpath(*parts)
