import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from services import catalog_service, price_service  # noqa: E402

# Menores arquivos válidos de cada formato (só a assinatura importa para a validação).
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64


@pytest.fixture(autouse=True)
def catalog_offline(monkeypatch):
    """Nenhum teste fala com o catálogo real; os de catálogo trocam `_get` por respostas simuladas."""
    monkeypatch.setattr(catalog_service, "_get", lambda path, params: None)
    monkeypatch.setitem(catalog_service._memory, "sets", None)
    monkeypatch.setitem(catalog_service._memory, "loaded_at", 0.0)
    # Cotação do dólar/euro também simulada (sem cotação = sem valor); test_scan define uma fixa.
    monkeypatch.setattr(price_service, "_fetch_rates", lambda: None)
    monkeypatch.setitem(price_service._rates_cache, "rates", None)
    monkeypatch.setitem(price_service._rates_cache, "loaded_at", 0.0)


@pytest.fixture()
def app(tmp_path):
    app = create_app(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        UPLOAD_FOLDER=tmp_path / "cards",
        ADMIN_USERNAME="",  # independente do .env local: login testado em test_auth.py
        ADMIN_PASSWORD_HASH="",
        IS_PRODUCTION=False,
        DATA_DIR=tmp_path,
    )
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def upload_dir(app):
    return Path(app.config["UPLOAD_FOLDER"])


def image(data: bytes = PNG, name: str = "carta.png"):
    return (io.BytesIO(data), name)
