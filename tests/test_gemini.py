"""Reconhecimento pela IA, com as respostas do Google simuladas (nenhuma chamada real)."""
import json

import pytest
import requests

from conftest import PNG, image
from services import gemini_service


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


def gemini_ok(data: dict) -> FakeResponse:
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(data)}]}}]})


CHARIZARD = {"is_pokemon_card": True, "pokemon_name": "Charizard", "collection_name": "Base Set", "card_number": "4/102",
             "rarity": "Holo Rare", "language": "Inglês", "confidence": 0.95,
             "extra": {"hp": "120", "types": ["Fogo"], "illustrator": "Mitsuhiro Arita", "notes": "", "edition": None}}


class CallLog(list):
    """Lista das chamadas feitas, com a fila de respostas simuladas em `.responses`."""

    def __init__(self):
        super().__init__()
        self.responses = []


@pytest.fixture()
def calls(monkeypatch):
    """Registra as chamadas e devolve respostas na ordem configurada em `calls.responses`."""
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")
    monkeypatch.setenv("GEMINI_MODEL", "")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "modelo-a,modelo-b")
    log = CallLog()

    def fake_post(url, json=None, headers=None, timeout=None):
        log.append({"url": url, "json": json, "headers": headers})
        item = fake_post.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    fake_post.responses = log.responses
    monkeypatch.setattr(gemini_service.requests, "post", fake_post)
    return log


def identify(client):
    return client.post("/api/cards/identify", data={"image": image(PNG)}, content_type="multipart/form-data")


def test_identifica_e_devolve_prefill(client, calls):
    calls.responses.append(gemini_ok(CHARIZARD))
    r = identify(client)
    assert r.status_code == 200
    d = r.get_json()
    assert d["prefill"] == {"pokemon_name": "Charizard", "collection_name": "Base Set", "card_number": "4/102",
                            "rarity": "Holo Rare", "language": "Inglês"}
    assert d["confidence"] == 0.95 and d["extra"] == {"hp": "120", "types": ["Fogo"], "illustrator": "Mitsuhiro Arita"}
    assert d["model"] == "modelo-a"
    sent = calls[0]
    assert sent["headers"] == {"x-goog-api-key": "chave-de-teste"} and "key=" not in sent["url"]  # chave no cabeçalho
    assert sent["json"]["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "image/png"


def test_troca_de_modelo_quando_um_recusa(client, calls):
    calls.responses.extend([FakeResponse(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}), gemini_ok(CHARIZARD)])
    r = identify(client)
    assert r.status_code == 200 and r.get_json()["model"] == "modelo-b"
    assert [c["url"].split("/models/")[1].split(":")[0] for c in calls] == ["modelo-a", "modelo-b"]


def test_cota_esgotada_em_todos(client, calls):
    calls.responses.extend([FakeResponse(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})] * 2)
    r = identify(client)
    assert r.status_code == 502 and "Limite diário" in r.get_json()["error"]


def test_nao_e_carta(client, calls):
    calls.responses.append(gemini_ok({"is_pokemon_card": False, "reason": "É uma foto de paisagem."}))
    r = identify(client)
    assert r.status_code == 422 and "paisagem" in r.get_json()["error"]


def test_resposta_invalida(client, calls):
    calls.responses.append(FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "não é json"}]}}]}))
    assert identify(client).status_code == 502


def test_sem_conexao(client, calls):
    calls.responses.extend([requests.ConnectionError(), requests.ConnectionError()])
    r = identify(client)
    assert r.status_code == 502 and "conexão" in r.get_json()["error"]


def test_sem_chave(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = identify(client)
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.get_json()["error"]


def test_imagem_invalida_nao_chama_a_ia(client, calls):
    r = client.post("/api/cards/identify", data={"image": image(b"texto qualquer" * 10, "x.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 400 and calls == []
    assert client.post("/api/cards/identify").status_code == 400


def test_chave_colada_com_aspas_ou_prefixo(monkeypatch):
    for value in ['"AQ.abc"', "GEMINI_API_KEY=AQ.abc", "  AQ.abc  "]:
        monkeypatch.setenv("GEMINI_API_KEY", value)
        assert gemini_service.api_key() == "AQ.abc"


def test_formulario_mostra_painel_da_ia(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert "data-ai-panel" in client.get("/cards/new").get_data(as_text=True)
    monkeypatch.delenv("GEMINI_API_KEY")
    html = client.get("/cards/new").get_data(as_text=True)
    assert "data-ai-panel" not in html and "IA desligada" in html
