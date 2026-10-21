from decimal import Decimal

import pytest

from services import card_service, gemini_service
from services.card_service import ValidationError, parse_price, rarity_tier


@pytest.mark.parametrize("text, expected", [
    ("1.250,00", Decimal("1250.00")),
    ("1250,5", Decimal("1250.50")),
    ("1250.00", Decimal("1250.00")),
    ("R$ 1.250,00", Decimal("1250.00")),
    ("1.250.000", Decimal("1250000.00")),
    ("80", Decimal("80.00")),
    ("", None),
    (None, None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", ["abc", "12,345", "-5", "1,2,3"])
def test_parse_price_invalido(text):
    with pytest.raises(ValueError):
        parse_price(text)


def test_nome_obrigatorio_e_limites(app):
    with app.app_context(), pytest.raises(ValidationError) as exc:
        card_service.create_card({"pokemon_name": "  ", "card_number": "x" * 31, "price": "abc"})
    assert set(exc.value.errors) == {"pokemon_name", "card_number", "price"}


def test_cria_normaliza_e_data_do_preco(app):
    with app.app_context():
        card = card_service.create_card({"pokemon_name": "  Charizard  ", "collection_name": "Base   Set", "price": "1.250,00"})
        assert (card.pokemon_name, card.collection_name, card.price) == ("Charizard", "Base Set", Decimal("1250.00"))
        assert card.price_date is not None  # preço sem data → hoje


def test_busca_filtros_e_resumo(app):
    with app.app_context():
        card_service.create_card({"pokemon_name": "Charizard", "collection_name": "Base Set", "rarity": "Holo Rare", "card_number": "004/102", "price": "1250"})
        card_service.create_card({"pokemon_name": "Pikachu", "collection_name": "Base Set", "rarity": "Common", "price": "15,90"})
        card_service.create_card({"pokemon_name": "Charmander", "collection_name": "Jungle", "rarity": "Common"})
        assert [c.pokemon_name for c in card_service.list_cards(q="char")] == ["Charmander", "Charizard"]
        assert [c.pokemon_name for c in card_service.list_cards(q="004")] == ["Charizard"]
        assert len(card_service.list_cards(collection="Base Set")) == 2
        assert [c.pokemon_name for c in card_service.list_cards(collection="Base Set", rarity="Common")] == ["Pikachu"]
        summary = card_service.collection_summary()
        assert (summary["total_cards"], summary["total_value"], summary["collections"]) == (3, Decimal("1265.90"), 2)
        assert card_service.filter_options() == {"collections": ["Base Set", "Jungle"], "rarities": ["Common", "Holo Rare"]}


def test_form_defaults_aceita_prefill_do_gemini(app):
    identificacao = gemini_service.CardIdentification(pokemon_name="Mewtwo", collection_name="Base Set", card_number="10/102", confidence=0.9)
    values = card_service.form_defaults(prefill=identificacao.as_prefill())
    assert (values["pokemon_name"], values["collection_name"], values["card_number"], values["price"]) == ("Mewtwo", "Base Set", "10/102", "")


@pytest.mark.parametrize("rarity, tier", [
    ("Common", "common"), ("Uncommon", "uncommon"), ("Rare", "rare"), ("Holo Rare", "holo"),
    ("Reverse Holo", "holo"), ("Double Rare", "ultra"), ("Illustration Rare", "ultra"), ("Pokémon ex", "ultra"),
    ("Special Illustration Rare", "secret"), ("Secret Rare", "secret"), ("Hyper Rare", "secret"), ("", "none"), (None, "none"),
])
def test_rarity_tier(rarity, tier):
    assert rarity_tier(rarity) == tier
