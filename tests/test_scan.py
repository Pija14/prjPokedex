"""Scan: foto → IA → vitrine com coleção, raridade e valor. Nada é gravado; IA e catálogo simulados."""
import io

import pytest
from PIL import Image

from app import money
from database.models import Card
from services import catalog_service, image_service, price_service
from services.gemini_service import CardIdentification
from test_gemini import CHARIZARD, calls, gemini_ok  # noqa: F401  (calls é fixture)

BASE = {"id": "base1", "name": "Base", "ptcgoCode": "BS", "printedTotal": 102, "releaseDate": "1999/01/09"}
CHARIZARD_CATALOG = {
    "id": "base1-4", "name": "Charizard", "number": "4", "rarity": "Rare Holo", "set": BASE,
    "images": {"small": "https://images.pokemontcg.io/base1/4.png", "large": "https://images.pokemontcg.io/base1/4_hires.png"},
    "tcgplayer": {"updatedAt": "2026/10/15", "prices": {"holofoil": {"low": 499.99, "mid": 587.98, "market": 954.65}}},
    "cardmarket": {"updatedAt": "2026/07/01", "prices": {"averageSellPrice": 1531.0, "trendPrice": 4184.6}},
}


def photo(width=600, height=800, fmt="JPEG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 60, 40)).save(out, fmt)
    return out.getvalue()


@pytest.fixture()
def catalog(monkeypatch):
    def fake_get(path, params):
        if path == "sets":
            return {"data": [BASE]}
        return {"data": [CHARIZARD_CATALOG]}

    monkeypatch.setattr(catalog_service, "_get", fake_get)


def post_scan(client, data=None, **headers):
    payload = {"image": (io.BytesIO(data or photo()), "carta.jpg")}
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


def test_api_scan_reconhece_e_nao_grava_nada(app, client, calls, catalog, upload_dir):
    calls.responses.append(gemini_ok(CHARIZARD | {"extra": {"set_code": "BS", "card_box": [50, 50, 950, 950]}}))
    response = client.post("/api/scan", data={"image": (io.BytesIO(photo()), "carta.jpg")},
                           content_type="multipart/form-data")
    assert response.status_code == 200
    data = response.get_json()
    assert data["card"]["pokemon_name"] == "Charizard"
    assert data["card"]["collection_source"] == "catalogo"
    assert data["images"]["photo"].startswith("data:image/webp;base64,")
    assert data["images"]["official"].endswith("4_hires.png")
    assert data["price"]["main"] == {"name": "holofoil", "source": "TCGplayer", "label": "Holo",
                                     "value": 954.65, "currency": "USD"}
    assert data["price"]["updated_at"] == "15/10/2026"
    assert "ligapokemon.com.br" in data["price"]["liga_url"]
    assert data["add_url"].startswith("/cards/new?")
    with app.app_context():
        assert Card.query.count() == 0
    assert not upload_dir.exists() or not any(upload_dir.iterdir())


def test_fragmento_da_vitrine(client, calls, catalog):
    calls.responses.append(gemini_ok(CHARIZARD))
    response = post_scan(client, **{"X-Scan-Fragment": "1"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<html" not in html  # só a vitrine
    assert "Charizard" in html and "US$ 954,65" in html and "€ 1.531,00" in html
    assert "Liga Pokémon" in html and 'data-view="official"' in html


def test_sem_js_pagina_inteira_com_resultado(client, calls, catalog):
    calls.responses.append(gemini_ok(CHARIZARD))
    html = post_scan(client).get_data(as_text=True)
    assert "<html" in html and 'data-state="result"' in html and "Charizard" in html


def test_fragmento_erro_nao_e_carta(client, calls):
    calls.responses.append(gemini_ok({"is_pokemon_card": False, "reason": "é uma foto de gato"}))
    response = post_scan(client, **{"X-Scan-Fragment": "1"})
    assert response.status_code == 422
    assert "gato" in response.get_json()["error"]


def test_sem_preco_mostra_link_da_liga(client, calls):
    """Catálogo fora do ar (padrão dos testes): sem valor de referência, mas com o link da Liga."""
    calls.responses.append(gemini_ok(CHARIZARD))
    html = post_scan(client, **{"X-Scan-Fragment": "1"}).get_data(as_text=True)
    assert "Sem preço de referência" in html and "ligapokemon.com.br" in html
    assert 'data-view="official"' not in html


def test_cadastrar_vindo_do_scan_preenche_formulario(client):
    html = client.get("/cards/new?pokemon_name=Charizard&card_number=4/102").get_data(as_text=True)
    assert 'value="Charizard"' in html and 'value="4/102"' in html


# ---------- Realce da foto ----------

def test_realce_recorta_pela_caixa_da_ia():
    out = image_service.enhance_for_display(photo(1000, 1000), [100, 200, 900, 800])
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "WEBP"
        assert img.size == (640, 840)  # caixa + 2% de folga de cada lado


@pytest.mark.parametrize("box", [None, "x", [1, 2, 3], [0, 0, 50, 50], [900, 900, 100, 100]])
def test_realce_ignora_caixa_invalida(box):
    out = image_service.enhance_for_display(photo(1200, 1200, "PNG"), box)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (900, 900)  # foto inteira, reduzida para 900 px de altura


# ---------- Valor ----------

def ident(ref_prices=None, name="Charizard"):
    catalog = {"ref_prices": ref_prices} if ref_prices else None
    return CardIdentification(pokemon_name=name, catalog=catalog)


def test_preco_prefere_tcgplayer_e_lista_variantes():
    q = price_service.quote(ident({
        "tcgplayer": {"variants": {"reverseHolofoil": 2.5, "normal": 1.2}, "updated_at": "2026/10/15"},
        "cardmarket": {"average": 1.0, "trend": 1.1, "updated_at": "2026/07/01"},
    }))
    assert q.source == "referencia"
    assert (q.main["label"], q.main["value"]) == ("Normal", 1.2)
    assert [v["label"] for v in q.variants] == ["Reverse Holo"]
    assert q.cardmarket["average"] == 1.0


def test_preco_cai_para_cardmarket():
    q = price_service.quote(ident({"cardmarket": {"average": None, "trend": 3.456, "updated_at": "2026/07/01"}}))
    assert (q.main["source"], q.main["value"], q.main["currency"]) == ("Cardmarket", 3.46, "EUR")
    assert q.cardmarket is None and q.updated_at == "01/07/2026"


def test_sem_preco():
    q = price_service.quote(ident())
    assert q.source is None and q.main is None
    assert q.liga_url == "https://www.ligapokemon.com.br/?view=cards%2Fsearch&card=Charizard"
    assert price_service.liga_search_url("  ") is None


def test_catalogo_traz_imagem_e_precos(app, catalog):
    with app.app_context():
        m = catalog_service.resolve("Charizard", "4/102", "BS")
    assert m.image_large.endswith("4_hires.png")
    assert m.ref_prices["tcgplayer"]["variants"] == {"holofoil": 954.65}
    assert m.ref_prices["cardmarket"]["average"] == 1531.0


def test_filtro_money():
    assert money(954.65, "USD") == "US$ 954,65"
    assert money(1531, "EUR") == "€ 1.531,00"
    assert money(None, "USD") == "—"
