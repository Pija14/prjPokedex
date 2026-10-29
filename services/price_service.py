"""Valor da carta para o Scan (só exibição: nada é gravado).

A Liga Pokémon (referência de preço no Brasil) não tem API e bloqueia acesso automatizado
(desafio do Cloudflare), então o servidor não lê os preços dela: a tela oferece o link da busca
na Liga, que abre no navegador da pessoa. O valor exibido é a referência internacional que o
catálogo (api.pokemontcg.io) já devolve junto da carta: TCGplayer (US$) e Cardmarket (€).
"""
import re
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

LIGA_SEARCH = "https://www.ligapokemon.com.br/"

# Variantes do TCGplayer, da mais comum para a mais específica, com o nome exibido.
VARIANT_LABELS = {
    "normal": "Normal",
    "holofoil": "Holo",
    "reverseHolofoil": "Reverse Holo",
    "1stEditionNormal": "1ª Edição",
    "1stEditionHolofoil": "1ª Edição Holo",
    "unlimited": "Unlimited",
    "unlimitedHolofoil": "Unlimited Holo",
}


@dataclass
class PriceQuote:
    liga_url: str | None
    source: str | None = None  # "referencia" (preço internacional) | None (sem preço)
    main: dict | None = None  # destaque: {"name", "source", "label", "value", "currency"}
    variants: list[dict] | None = None  # outras variantes TCGplayer
    cardmarket: dict | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _date_br(value: str | None) -> str | None:
    """'2026/10/15' (formato do catálogo) → '15/10/2026'."""
    match = re.match(r"^(\d{4})[/-](\d{2})[/-](\d{2})", value or "")
    return f"{match[3]}/{match[2]}/{match[1]}" if match else None


def liga_search_url(name: str | None) -> str | None:
    """Busca da carta na Liga Pokémon (o resultado lista as edições com os preços em R$)."""
    name = (name or "").strip()
    if not name:
        return None
    return f"{LIGA_SEARCH}?{urlencode({'view': 'cards/search', 'card': name})}"


def quote(identification) -> PriceQuote:
    """Monta o valor a exibir a partir da carta reconhecida (e conferida no catálogo)."""
    result = PriceQuote(liga_url=liga_search_url(identification.pokemon_name))
    ref = (identification.catalog or {}).get("ref_prices") or {}
    tcg = ref.get("tcgplayer") or {}
    variants = [
        {"name": key, "source": "TCGplayer", "label": VARIANT_LABELS.get(key, key), "value": round(float(value), 2), "currency": "USD"}
        for key, value in (tcg.get("variants") or {}).items() if value
    ]
    variants.sort(key=lambda v: list(VARIANT_LABELS).index(v["name"]) if v["name"] in VARIANT_LABELS else 99)
    cardmarket = ref.get("cardmarket")
    if variants:
        main, *others = variants
        result.main, result.variants = main, others
        result.updated_at = _date_br(tcg.get("updated_at"))
    elif cardmarket and (cardmarket.get("trend") or cardmarket.get("average")):
        value = cardmarket.get("average") or cardmarket.get("trend")
        result.main = {"name": "cardmarket", "source": "Cardmarket", "label": "média de venda", "value": round(float(value), 2), "currency": "EUR"}
        result.updated_at = _date_br(cardmarket.get("updated_at"))
    if cardmarket and result.main and result.main["currency"] != "EUR":
        result.cardmarket = cardmarket
    if result.main:
        result.source = "referencia"
    return result
