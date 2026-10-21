"""Configuração do CardDex. Valores sensíveis vêm do ambiente (.env), nunca do código."""
import os
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
    SECRET_KEY = os.getenv("SECRET_KEY") or "carddex-dev-local"  # usado só para as mensagens flash

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

    # Futuro: reconhecimento da carta pelo Gemini (services/gemini_service.py).
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    DEBUG = _env_bool("FLASK_DEBUG", default=True)
