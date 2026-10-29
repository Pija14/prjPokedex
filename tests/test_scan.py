"""Scan: foto → IA → vitrine com a imagem oficial, coleção, raridade e valor em R$.
Nada é gravado; IA, catálogo e cotação simulados."""
import io

import pytest
import requests
from PIL import Image

from database.models import Card
from services import catalog_service, price_service
from services.gemini_service import CardIdentification
from test_gemini import CHARIZARD, FakeResponse, calls, gemini_ok  # noqa: F401  (calls é fixture)

BASE = {"id": "base1", "name": "Base", "ptcgoCode": "BS", "printedTotal": 102, "releaseDate": "1999/01/09"}
CHARIZARD_CATALOG = {
    "id": "base1-4", "name": "Charizard", "number": "4", "rarity": "Rare Holo", "set": BASE,
    "images": {"small": "https://images.pokemontcg.io/base1/4.png", "large": "https://images.pokemontcg.io/base1/4_hires.png"},
    "tcgplayer": {"updatedAt": "2026/10/15", "prices": {"holofoil": {"low": 499.99, "mid": 587.98, "market": 954.65}}},
    "cardmarket": {"updatedAt": "2026/07/01", "prices": {"averageSellPrice": 1531.0, "trendPrice": 4184.6}},
}
RATES = {"USD": 5.0, "EUR": 6.0, "date": "29/10/2026"}


def photo(width=600, height=800) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 60, 40)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture()
def catalog(monkeypatch):
    def fake_get(path, params):
        if path == "sets":
            return {"data": [BASE]}
        return {"data": [CHARIZARD_CATALOG]}

    monkeypatch.setattr(catalog_service, "_get", fake_get)


@pytest.fixture()
def rates(monkeypatch):
    monkeypatch.setattr(price_service, "_fetch_rates", lambda: dict(RATES))


def post_scan(client, **headers):
    payload = {"image": (io.BytesIO(photo()), "carta.jpg")}
    return client.post("/scan", data=payload, content_type="multipart/form-data", headers=headers)


# ---------- Página e menu ----------

def test_pagina_scan_e_menu(client):
    response = client.get("/scan")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "data-scan" in html and 'capture="environment"' in html
    assert 'href="/scan"' in client.get("/").get_data(as_text=True)


# ---------- Fluxo completo ----------

def test_api_scan_sem_imagem(client):
    response = client.post("/api/scan", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "image" in response.get_json()["errors"]


def test_api_scan_reconhece_em_reais_e_nao_grava_nada(app, client, calls, catalog, rates, upload_dir):
    calls.responses.append(gemini_ok(CHARIZARD | {"extra": {"set_code": "BS"}}))
    response = client.post("/api/scan", data={"image": (io.BytesIO(photo()), "carta.jpg")},
                           content_type="multipart/form-data")
    assert response.status_code == 200
    data = response.get_json()
    assert data["card"]["pokemon_name"] == "Charizard"
    assert data["card"]["collection_source"] == "catalogo"
    assert data["images"] == {"official": "https://images.pokemontcg.io/base1/4_hires.png"}  # sem a foto tirada
    assert data["price"]["main"] == {"name": "holofoil", "source": "TCGplayer", "label": "Holo", "value": 4773.25}
    assert data["price"]["cardmarket"] == 9186.0
    assert (data["price"]["updated_at"], data["price"]["rate_date"]) == ("15/10/2026", "29/10/2026")
    assert "ligapokemon.com.br" in data["price"]["liga_url"]
    assert data["add_url"].startswith("/cards/new?")
    with app.app_context():
        assert Card.query.count() == 0
    assert not upload_dir.exists() or not any(upload_dir.iterdir())


def test_fragmento_da_vitrine_so_imagem_oficial_e_reais(client, calls, catalog, rates):
    calls.responses.append(gemini_ok(CHARIZARD))
    response = post_scan(client, **{"X-Scan-Fragment": "1"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<html" not in html  # só a vitrine
    assert "Charizard" in html and "R$ 4.773,25" in html and "R$ 9.186,00" in html
    assert "US$" not in html and "€" not in html
    assert "4_hires.png" in html and "data:image" not in html
    assert "Liga Pokémon" in html


def test_sem_js_pagina_inteira_com_resultado(client, calls, catalog, rates):
    calls.responses.append(gemini_ok(CHARIZARD))
    html = post_scan(client).get_data(as_text=True)
    assert "<html" in html and 'data-state="result"' in html and "Charizard" in html


def test_fragmento_erro_nao_e_carta(client, calls):
    calls.responses.append(gemini_ok({"is_pokemon_card": False, "reason": "é uma foto de gato"}))
    response = post_scan(client, **{"X-Scan-Fragment": "1"})
    assert response.status_code == 422
    assert "gato" in response.get_json()["error"]


def test_carta_fora_do_catalogo(client, calls):
    """Catálogo fora do ar (padrão dos testes): sem imagem oficial nem valor, mas com o link da Liga."""
    calls.responses.append(gemini_ok(CHARIZARD))
    html = post_scan(client, **{"X-Scan-Fragment": "1"}).get_data(as_text=True)
    assert "Sem preço de referência" in html and "ligapokemon.com.br" in html
    assert "Imagem oficial indisponível" in html and "<img" not in html


def test_cadastrar_vindo_do_scan_preenche_formulario(client):
    html = client.get("/cards/new?pokemon_name=Charizard&card_number=4/102").get_data(as_text=True)
    assert 'value="Charizard"' in html and 'value="4/102"' in html


# ---------- Valor em R$ ----------

def ident(ref_prices=None, name="Charizard"):
    catalog = {"ref_prices": ref_prices} if ref_prices else None
    return CardIdentification(pokemon_name=name, catalog=catalog)


def test_preco_prefere_tcgplayer_e_converte_variantes(rates):
    q = price_service.quote(ident({
        "tcgplayer": {"variants": {"reverseHolofoil": 2.5, "normal": 1.2}, "updated_at": "2026/10/15"},
        "cardmarket": {"average": 1.0, "trend": 1.1, "updated_at": "2026/07/01"},
    }))
    assert q.source == "referencia"
    assert (q.main["label"], q.main["value"]) == ("Normal", 6.0)
    assert [(v["label"], v["value"]) for v in q.variants] == [("Reverse Holo", 12.5)]
    assert q.cardmarket == 6.0


def test_preco_cai_para_cardmarket(rates):
    q = price_service.quote(ident({"cardmarket": {"average": None, "trend": 3.456, "updated_at": "2026/07/01"}}))
    assert (q.main["source"], q.main["value"]) == ("Cardmarket", 20.74)
    assert q.cardmarket is None and q.updated_at == "01/07/2026"


def test_sem_preco_no_catalogo():
    q = price_service.quote(ident())
    assert (q.source, q.main, q.missing) == (None, None, "sem_preco")
    assert q.liga_url == "https://www.ligapokemon.com.br/?view=cards%2Fsearch&card=Charizard"
    assert price_service.liga_search_url("  ") is None


def test_sem_cotacao_nao_mostra_moeda_estrangeira():
    """Sem cotação (padrão dos testes), não há valor: nunca exibe US$ ou €."""
    q = price_service.quote(ident({"tcgplayer": {"variants": {"normal": 1.2}}}))
    assert (q.main, q.missing) == (None, "sem_cotacao")


def test_cotacao_le_awesomeapi_e_guarda_em_cache(monkeypatch):
    monkeypatch.undo()  # volta o _fetch_rates real, com a rede simulada abaixo
    hits = []

    def fake_get(url, timeout=None):
        hits.append(url)
        return FakeResponse(200, {"USDBRL": {"bid": "5.3462", "create_date": "2026-10-29 05:25:56"},
                                  "EURBRL": {"bid": "5.9591"}})

    monkeypatch.setattr(price_service.requests, "get", fake_get)
    monkeypatch.setitem(price_service._rates_cache, "rates", None)
    assert price_service.rates() == {"USD": 5.3462, "EUR": 5.9591, "date": "29/10/2026"}
    price_service.rates()
    assert len(hits) == 1  # segunda vez veio do cache


def test_cotacao_fora_do_ar(monkeypatch):
    monkeypatch.undo()

    def fail(url, timeout=None):
        raise requests.ConnectionError

    monkeypatch.setattr(price_service.requests, "get", fail)
    monkeypatch.setitem(price_service._rates_cache, "rates", None)
    assert price_service.rates() is None


def test_catalogo_traz_imagem_e_precos(app, catalog):
    with app.app_context():
        m = catalog_service.resolve("Charizard", "4/102", "BS")
    assert m.image_large.endswith("4_hires.png")
    assert m.ref_prices["tcgplayer"]["variants"] == {"holofoil": 954.65}
    assert m.ref_prices["cardmarket"]["average"] == 1531.0
