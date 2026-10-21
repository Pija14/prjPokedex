"""Confirmação no catálogo e nomes em português (catálogo simulado, nenhuma chamada real)."""
import json

import pytest

from conftest import PNG, image
from services import catalog_service, gemini_service
from services.translations import rarity_pt, set_name_pt

SETS = [
    {"id": "base1", "name": "Base", "ptcgoCode": "BS", "printedTotal": 102, "releaseDate": "1999/01/09"},
    {"id": "ecard1", "name": "Expedition Base Set", "ptcgoCode": "EX", "printedTotal": 165, "releaseDate": "2002/09/15"},
    {"id": "sv3pt5", "name": "151", "ptcgoCode": None, "printedTotal": 165, "releaseDate": "2023/09/22"},
    {"id": "swsh12pt5", "name": "Crown Zenith", "ptcgoCode": "CRZ", "printedTotal": 159, "releaseDate": "2023/01/20"},
    {"id": "sv4pt5", "name": "Paldean Fates", "ptcgoCode": "PAF", "printedTotal": 91, "releaseDate": "2024/01/26"},
]
CARDS = [
    {"id": "ecard1-6", "name": "Charizard", "number": "6", "rarity": "Rare Holo", "set": SETS[1]},
    {"id": "sv3pt5-6", "name": "Charizard ex", "number": "6", "rarity": "Double Rare", "set": SETS[2]},
    {"id": "swsh12pt5-160", "name": "Pikachu", "number": "160", "rarity": "Rare Secret", "set": SETS[3]},
]


@pytest.fixture()
def catalog(monkeypatch):
    """Catálogo simulado; `catalog.calls` guarda as consultas e `catalog.down` o deixa fora do ar."""
    class State:
        calls = []
        down = False

    def fake_get(path, params):
        State.calls.append((path, params))
        if State.down:
            return None
        if path == "sets":
            return {"data": SETS}
        number = params["q"].split("number:")[1].split()[0]
        return {"data": [c for c in CARDS if c["number"] == number]}

    monkeypatch.setattr(catalog_service, "_get", fake_get)
    return State


@pytest.mark.parametrize("printed, expected", [
    ("006/165", ("6", 165)), ("4/102", ("4", 102)), ("SV049/SV094", ("SV49", 94)), ("TG01/TG30", ("TG1", 30)),
    ("25", ("25", None)), ("", (None, None)), (None, (None, None)),
])
def test_parse_number(printed, expected):
    assert catalog_service.parse_number(printed) == expected


def test_confirma_pelo_codigo_impresso(app, catalog):
    with app.app_context():
        m = catalog_service.resolve("Pikachu", "160/159", "CRZ")
    assert (m.set_name, m.rarity, m.matched_by) == ("Crown Zenith", "Rare Secret", "carta")
    assert "set.id:swsh12pt5" in catalog.calls[-1][1]["q"]


def test_desempata_pelo_nome_exato(app, catalog):
    """Dois sets com 165 cartas e um Charizard nº 6 em cada: vale o nome impresso."""
    with app.app_context():
        assert catalog_service.resolve("Charizard ex", "006/165").set_name == "151"
        assert catalog_service.resolve("Charizard", "006/165").set_name == "Expedition Base Set"


def test_so_o_set_quando_a_carta_nao_aparece(app, catalog):
    with app.app_context():
        m = catalog_service.resolve("Gardevoir ex", "086/091", "PAF")
    assert (m.set_name, m.rarity, m.matched_by) == ("Paldean Fates", None, "set")


def test_sem_confirmacao_nao_inventa(app, catalog):
    with app.app_context():
        assert catalog_service.resolve("Mewtwo", "999/165") is None  # dois sets possíveis e carta inexistente
        assert catalog_service.resolve("Mewtwo", None) is None


def test_lista_de_sets_fica_em_cache(app, catalog, tmp_path):
    with app.app_context():
        catalog_service.get_sets()
        catalog_service.get_sets()
        assert sum(1 for path, _ in catalog.calls if path == "sets") == 1
        assert json.loads((tmp_path / "catalog_sets.json").read_text(encoding="utf-8"))["sets"] == SETS
        catalog_service._memory["sets"] = None  # reinício do servidor: lê do arquivo, sem nova consulta
        assert catalog_service.get_sets() == SETS
        assert sum(1 for path, _ in catalog.calls if path == "sets") == 1


def test_traducoes():
    assert rarity_pt("Rare Holo") == "Rara Holo"
    assert rarity_pt("Special Illustration Rare") == "Rara Ilustração Especial"
    assert rarity_pt("Rara Dupla") == "Rara Dupla"  # já em português
    assert rarity_pt("Algo Novo") == "Algo Novo" and rarity_pt(None) is None
    assert set_name_pt("Crown Zenith") == "Realeza Absoluta"
    assert set_name_pt("151") == "Escarlate e Violeta 151"
    assert set_name_pt("Base") == "Base Set"
    assert set_name_pt("Jungle") == "Jungle"  # sem nome oficial conhecido: mantém o do catálogo


def _identify(client, monkeypatch, card: dict):
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "modelo-a")
    body = {"candidates": [{"content": {"parts": [{"text": json.dumps(card)}]}}]}
    monkeypatch.setattr(gemini_service.requests, "post",
                        lambda *a, **k: type("R", (), {"status_code": 200, "json": lambda self: body})())
    return client.post("/api/cards/identify", data={"image": image(PNG)}, content_type="multipart/form-data").get_json()


def test_identificacao_usa_o_catalogo_e_portugues(client, monkeypatch, catalog):
    d = _identify(client, monkeypatch, {"pokemon_name": "Charizard ex", "collection_name": "Obsidian Flames",
                                        "card_number": "006/165", "rarity": "Ultra Rare", "language": "Inglês"})
    assert d["collection_source"] == "catalogo"
    assert d["prefill"]["collection_name"] == "Escarlate e Violeta 151"  # o chute da IA foi corrigido
    assert d["prefill"]["rarity"] == "Rara Dupla"  # raridade oficial do catálogo, em português
    assert d["catalog"]["set_name"] == "151" and d["catalog"]["card_id"] == "sv3pt5-6"


def test_catalogo_fora_do_ar_mantem_sugestao_da_ia(client, monkeypatch, catalog):
    catalog.down = True
    d = _identify(client, monkeypatch, {"pokemon_name": "Pikachu", "collection_name": "Crown Zenith",
                                        "card_number": "160/159", "rarity": "Secret Rare", "language": "Português"})
    assert d["collection_source"] == "ia"
    assert d["prefill"]["collection_name"] == "Realeza Absoluta" and d["prefill"]["rarity"] == "Rara Secreta"


def test_carta_japonesa_nao_consulta_o_catalogo(client, monkeypatch, catalog):
    d = _identify(client, monkeypatch, {"pokemon_name": "Pikachu", "card_number": "006/165", "language": "Japonês"})
    assert catalog.calls == [] and d["collection_source"] is None
