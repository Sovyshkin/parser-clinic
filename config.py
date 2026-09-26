from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    telegram_bot_token: str
    admin_telegram_id: int
    search_api_key: str
    search_api_url: str
    search_provider: str = "brave"
    search_engine_id: str = ""
    search_api_key_param: str = "key"
    search_api_key_header: str = ""
    search_query_param: str = "q"
    search_limit_param: str = "num"
    search_start_param: str = "start"
    brave_country: str = "ru"
    brave_search_lang: str = "ru"
    excluded_domains: set[str] = field(default_factory=set)
    database_path: Path = BASE_DIR / "data" / "clinics.db"
    excel_path: Path = BASE_DIR / "data" / "clinics.xlsx"
    request_timeout: float = 20.0
    request_retries: int = 2
    concurrency: int = 3
    min_delay: float = 0.7
    max_delay: float = 1.8
    max_pages_per_site: int = 5
    playwright_enabled: bool = True
    user_agent: str = (
        "Mozilla/5.0 (compatible; ClinicContactsBot/1.0; "
        "+https://example.invalid/bot-info)"
    )

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or BASE_DIR / ".env")
        defaults = {
            "yandex.ru",
            "google.com",
            "google.ru",
            "2gis.ru",
            "zoon.ru",
            "prodoctorov.ru",
            "vk.com",
            "t.me",
            "telegram.me",
            "youtube.com",
            "ok.ru",
        }
        extra = {
            value.strip().lower()
            for value in os.getenv("EXCLUDED_DOMAINS", "").split(",")
            if value.strip()
        }
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            admin_telegram_id=_as_int(os.getenv("ADMIN_TELEGRAM_ID"), 0),
            search_api_key=os.getenv("SEARCH_API_KEY", "").strip(),
            search_api_url=os.getenv("SEARCH_API_URL", "").strip(),
            search_provider=os.getenv("SEARCH_PROVIDER", "brave").strip().lower(),
            search_engine_id=os.getenv("SEARCH_ENGINE_ID", "").strip(),
            search_api_key_param=os.getenv("SEARCH_API_KEY_PARAM", "key").strip(),
            search_api_key_header=os.getenv("SEARCH_API_KEY_HEADER", "").strip(),
            search_query_param=os.getenv("SEARCH_QUERY_PARAM", "q").strip(),
            search_limit_param=os.getenv("SEARCH_LIMIT_PARAM", "num").strip(),
            search_start_param=os.getenv("SEARCH_START_PARAM", "start").strip(),
            brave_country=os.getenv("BRAVE_COUNTRY", "ru").strip().lower(),
            brave_search_lang=os.getenv("BRAVE_SEARCH_LANG", "ru").strip().lower(),
            excluded_domains=defaults | extra,
            request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),
            request_retries=_as_int(os.getenv("REQUEST_RETRIES"), 2),
            concurrency=max(1, _as_int(os.getenv("CONCURRENCY"), 3)),
            min_delay=float(os.getenv("MIN_DELAY", "0.7")),
            max_delay=float(os.getenv("MAX_DELAY", "1.8")),
            max_pages_per_site=min(5, max(1, _as_int(os.getenv("MAX_PAGES_PER_SITE"), 5))),
            playwright_enabled=_as_bool(os.getenv("PLAYWRIGHT_ENABLED"), True),
            user_agent=os.getenv("USER_AGENT", cls.__dataclass_fields__["user_agent"].default),
        )

    def validate_for_bot(self) -> None:
        missing: list[str] = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.admin_telegram_id:
            missing.append("ADMIN_TELEGRAM_ID")
        if not self.search_api_key:
            missing.append("SEARCH_API_KEY")
        if self.search_provider != "brave" and not self.search_api_url:
            missing.append("SEARCH_API_URL")
        if missing:
            raise RuntimeError(f"Не заполнены обязательные переменные: {', '.join(missing)}")
