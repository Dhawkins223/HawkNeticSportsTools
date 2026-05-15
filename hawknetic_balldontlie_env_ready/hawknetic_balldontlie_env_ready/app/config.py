from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ[key] = value


for dotenv_path in dict.fromkeys((Path.cwd() / ".env", BASE_DIR.parent / ".env", BASE_DIR / ".env")):
    _load_dotenv_file(dotenv_path)

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    app_name: str = "HawkNetic"
    secret_key: str = os.getenv("HAWKNETIC_SECRET_KEY", "dev-only-change-me")
    database_path: Path = Path(os.getenv("HAWKNETIC_DB_PATH", DATA_DIR / "hawknetic.sqlite"))
    database_url: str = os.getenv("DATABASE_URL", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_publishable_key: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    stripe_price_starter: str = os.getenv("STRIPE_PRICE_STARTER", "")
    stripe_price_pro: str = os.getenv("STRIPE_PRICE_PRO", "")
    stripe_price_elite: str = os.getenv("STRIPE_PRICE_ELITE", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    base_url: str = os.getenv("HAWKNETIC_BASE_URL", "http://127.0.0.1:8000")
    environment: str = os.getenv("HAWKNETIC_ENV", "local")
    balldontlie_api_key: str = os.getenv("BALLDONTLIE_API_KEY", "")
    balldontlie_base_url: str = os.getenv("BALLDONTLIE_BASE_URL", "https://api.balldontlie.io/v1")
    balldontlie_v2_base_url: str = os.getenv("BALLDONTLIE_V2_BASE_URL", "https://api.balldontlie.io/nba/v2")
    balldontlie_timeout_seconds: float = float(os.getenv("BALLDONTLIE_TIMEOUT_SECONDS", "20"))
    support_email: str = os.getenv("HAWKNETIC_SUPPORT_EMAIL", "HawkNetic@gmail.com")


settings = Settings()
