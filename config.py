from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
SUPPORTED_LANGUAGES = {"uz", "ru", "en"}


def _load_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        raise ValueError(f".env fayli mavjud emas: {ENV_FILE}")
    raw = dotenv_values(ENV_FILE, interpolate=False)
    return {str(k): str(v or "").strip().strip("\"").strip("'") for k, v in raw.items() if k}


ENV = _load_env()


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_path: str
    ceo_owner_id: int
    bot_username: str
    log_level: str
    default_language: str
    pagination_size: int
    ceo_initial_password: str
    admin_session_minutes: int
    admin_login_max_attempts: int
    admin_login_lock_minutes: int


def required(name: str) -> str:
    value = ENV.get(name, "").strip()
    if not value or value.lower() in {"your_bot_token", "paste_your_bot_token_here", "your_token_here"}:
        raise ValueError(f"{name} topilmadi yoki placeholder turibdi. .env faylini tekshiring: {ENV_FILE}")
    return value


def from_env() -> Config:
    token = required("BOT_TOKEN")
    try:
        owner = int(required("CEO_OWNER_ID"))
    except ValueError as exc:
        raise ValueError("CEO_OWNER_ID musbat Telegram ID bo‘lishi kerak.") from exc
    if owner <= 0:
        raise ValueError("CEO_OWNER_ID musbat Telegram ID bo‘lishi kerak.")

    lang = ENV.get("DEFAULT_LANGUAGE", "uz").lower() or "uz"
    if lang not in SUPPORTED_LANGUAGES:
        lang = "uz"
    try:
        page = int(ENV.get("PAGINATION_SIZE", "8") or 8)
    except ValueError:
        page = 8
    page = max(4, min(20, page))

    db_value = ENV.get("DATABASE_PATH", "movies.db") or "movies.db"
    db_path = Path(db_value)
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    ceo_password = required("CEO_INITIAL_PASSWORD")
    try:
        session_minutes = int(ENV.get("ADMIN_SESSION_MINUTES", "720") or 720)
        max_attempts = int(ENV.get("ADMIN_LOGIN_MAX_ATTEMPTS", "5") or 5)
        lock_minutes = int(ENV.get("ADMIN_LOGIN_LOCK_MINUTES", "15") or 15)
    except ValueError as exc:
        raise ValueError("Admin security sozlamalari son bo‘lishi kerak.") from exc
    session_minutes = max(5, min(10080, session_minutes))
    max_attempts = max(3, min(10, max_attempts))
    lock_minutes = max(1, min(1440, lock_minutes))

    return Config(
        bot_token=token,
        database_path=str(db_path),
        ceo_owner_id=owner,
        bot_username=ENV.get("BOT_USERNAME", "").lstrip("@"),
        log_level=(ENV.get("LOG_LEVEL", "INFO") or "INFO").upper(),
        default_language=lang,
        pagination_size=page,
        ceo_initial_password=ceo_password,
        admin_session_minutes=session_minutes,
        admin_login_max_attempts=max_attempts,
        admin_login_lock_minutes=lock_minutes,
    )


config = from_env()
BOT_TOKEN = config.bot_token
LOG_LEVEL = config.log_level
