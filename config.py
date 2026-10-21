"""Configuração do CardDex. Valores sensíveis vêm do ambiente (.env), nunca do código."""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


class Config:
    APP_ENV = os.getenv("APP_ENV", "development").strip().lower()  # development | production
    IS_PRODUCTION = APP_ENV == "production"

    # Assina o cookie da sessão (login) e as mensagens. Em produção é obrigatória e secreta.
    SECRET_KEY = os.getenv("SECRET_KEY") or "carddex-dev-local"

    DATA_DIR = BASE_DIR / "data"
    DATABASE_PATH = DATA_DIR / "carddex.db"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or f"sqlite:///{DATABASE_PATH.as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Uploads das cartas: separados dos assets do app (logo etc.) em static/images/.
    UPLOAD_FOLDER = BASE_DIR / "static" / "images" / "cards"
    UPLOAD_URL_PREFIX = "images/cards"  # relativo a static/
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
    MAX_IMAGE_MB = 8
    MAX_CONTENT_LENGTH = (MAX_IMAGE_MB + 1) * 1024 * 1024  # margem para os campos do formulário

    # Reconhecimento da carta pelo Gemini (services/gemini_service.py).
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # Login de um único dono da coleção. Gere com: python scripts/set_password.py
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
    ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.getenv("SESSION_DAYS", "30")))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION  # cookie só por HTTPS em produção

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    # Em produção o modo debug fica sempre desligado (ele expõe um console de depuração).
    DEBUG = _env_bool("FLASK_DEBUG", default=True) and not IS_PRODUCTION
