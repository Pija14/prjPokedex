"""Login do dono da coleção, proteção CSRF e configuração de produção."""
import re

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from conftest import PNG, image
from services import auth_service

PASSWORD = "senha-forte-123"


@pytest.fixture()
def secure_app(tmp_path):
    auth_service._failures.clear()
    return create_app(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{(tmp_path / 'auth.db').as_posix()}",
        UPLOAD_FOLDER=tmp_path / "cards",
        ADMIN_USERNAME="rafael",
        ADMIN_PASSWORD_HASH=generate_password_hash(PASSWORD),
    )


@pytest.fixture()
def web(secure_app):
    return secure_app.test_client()


def csrf_from(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(web, password=PASSWORD, username="rafael"):
    token = csrf_from(web.get("/login").get_data(as_text=True))
    return web.post("/login", data={"username": username, "password": password, "csrf_token": token, "next": "/cards"})


def test_paginas_e_api_exigem_login(web):
    r = web.get("/cards")
    assert r.status_code == 302 and r.headers["Location"].startswith("/login?next=/cards")
    assert web.get("/api/cards").status_code == 401
    assert web.post("/api/cards/identify").status_code == 401
    assert web.get("/static/images/logo.svg").status_code == 200  # estáticos continuam públicos


def test_login_errado_e_certo(web):
    r = login(web, password="errada")
    assert r.status_code == 401 and "incorretos" in r.get_data(as_text=True)
    r = login(web)
    assert r.status_code == 302 and r.headers["Location"] == "/cards"
    assert web.get("/cards").status_code == 200
    assert web.get("/api/cards").status_code == 200


def test_usuario_sem_diferenciar_maiusculas(web):
    assert login(web, username="  Rafael ").status_code == 302


def test_bloqueia_apos_muitas_tentativas(web):
    for _ in range(auth_service.MAX_FAILURES):
        login(web, password="errada")
    r = login(web)  # mesmo com a senha certa
    assert r.status_code == 429 and "Muitas tentativas" in r.get_data(as_text=True)


def test_next_nao_redireciona_para_fora(web):
    token = csrf_from(web.get("/login").get_data(as_text=True))
    r = web.post("/login", data={"username": "rafael", "password": PASSWORD, "csrf_token": token, "next": "https://site-malicioso.com/"})
    assert r.headers["Location"] == "/"


def test_csrf_obrigatorio_em_formularios_e_api(web):
    login(web)
    html = web.get("/cards/new").get_data(as_text=True)
    token = csrf_from(html)
    assert web.post("/cards/new", data={"pokemon_name": "Mew"}).status_code == 400  # sem token
    r = web.post("/cards/new", data={"pokemon_name": "Mew", "csrf_token": token, "image": image(PNG)}, content_type="multipart/form-data")
    assert r.status_code == 302
    assert web.post("/api/cards", json={"pokemon_name": "Mew"}).status_code == 400  # API sem cabeçalho
    assert web.post("/api/cards", json={"pokemon_name": "Mew"}, headers={"X-CSRF-Token": token}).status_code == 201


def test_logout(web):
    login(web)
    token = csrf_from(web.get("/cards/new").get_data(as_text=True))
    r = web.post("/logout", data={"csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"] == "/login"
    assert web.get("/cards").status_code == 302


def test_formulario_inclui_token_e_menu_tem_sair(web):
    login(web)
    html = web.get("/").get_data(as_text=True)
    assert 'name="csrf-token"' in html and "/logout" in html


def test_producao_nao_sobe_sem_senha(tmp_path, monkeypatch):
    base = dict(SQLALCHEMY_DATABASE_URI=f"sqlite:///{(tmp_path / 'p.db').as_posix()}", IS_PRODUCTION=True, UPLOAD_FOLDER=tmp_path)
    with pytest.raises(RuntimeError, match="ADMIN_USERNAME"):
        create_app(**base, ADMIN_USERNAME="", ADMIN_PASSWORD_HASH="", SECRET_KEY="x" * 40)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(**base, ADMIN_USERNAME="rafael", ADMIN_PASSWORD_HASH="hash", SECRET_KEY="curta")
    app = create_app(**base, ADMIN_USERNAME="rafael", ADMIN_PASSWORD_HASH="hash", SECRET_KEY="x" * 40)
    assert app.config["IS_PRODUCTION"]


def test_sem_senha_configurada_app_continua_aberto(client):
    assert client.get("/cards").status_code == 200  # uso local sem login, como antes
