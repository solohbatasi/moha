import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def int_env(name: str, default: int) -> int:
    return int(env(name, str(default)))


APP_ENV = env("APP_ENV", "development").lower()
TEST_MODE = APP_ENV == "development" and env("TEST_MODE", "false").lower() in {"1", "true", "yes"}
TEST_PASSWORD = env("TEST_PASSWORD", "12345678")
TEST_ACCESS_TOKEN = "12345678"
TEST_USER_EMAIL = "codility-test-user@localhost"
JWT_SECRET = env("JWT_SECRET")
DATABASE_URL = env("DATABASE_URL", "postgresql+psycopg://zetech:local-only-change-me@127.0.0.1:5432/zetech_learning")
OTP_TTL_SECONDS = int_env("OTP_TTL_SECONDS", 600)
OTP_RESEND_SECONDS = int_env("OTP_RESEND_SECONDS", 60)
OTP_MAX_ATTEMPTS = int_env("OTP_MAX_ATTEMPTS", 5)
APP_PRICE_KES = int_env("APP_PRICE_KES", 100)
MPESA_ENV = env("MPESA_ENV", "sandbox").lower()
MPESA_TIMEOUT_SECONDS = int_env("MPESA_TIMEOUT_SECONDS", 20)


def required(name: str) -> str:
    value = env(name)
    if not value:
        raise RuntimeError(f"Missing required backend setting: {name}")
    return value
