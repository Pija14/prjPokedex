"""Valor da carta para o Scan, sempre em reais (só exibição: nada é gravado).

A Liga Pokémon (referência de preço no Brasil) não tem API e bloqueia acesso automatizado
(desafio do Cloudflare), então o servidor não lê os preços dela: a tela oferece o link da busca
na Liga, que abre no navegador da pessoa. O valor exibido é a referência internacional que o
catálogo (api.pokemontcg.io) devolve junto da carta — TCGplayer (US$) e Cardmarket (€) —
convertida para R$ pela cotação do dia (AwesomeAPI). Sem cotação, não há valor: nunca em US$/€.
"""
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urlencode

import requests

logger = logging.getLogger("carddex.price")

LIGA_SEARCH = "https://www.ligapokemon.com.br/"
RATES_API = "https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL"
RATES_CACHE_SECONDS = 6 * 3600
TIMEOUT = (3, 5)  # conectar, ler

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
    source: str | None = None  # "referencia" (preço internacional convertido) | None (sem preço)
    main: dict | None = None  # destaque: {"name", "source", "label", "value"} — value em R$
    variants: list[dict] | None = None  # outras variantes TCGplayer, em R$
    cardmarket: float | None = None  # média de venda no Cardmarket, em R$
    updated_at: str | None = None  # data do preço no catálogo
    rate_date: str | None = None  # data da cotação usada na conversão
    missing: str | None = None  # por que não há valor: "sem_preco" | "sem_cotacao"

    def to_dict(self) -> dict:
        return asdict(self)


_rates_cache: dict = {"rates": None, "loaded_at": 0.0}


def _fetch_rates() -> dict | None:
    """Cotação de compra do dólar e do euro em reais: {"USD": 5.34, "EUR": 5.96, "date": "29/10/2026"}."""
    try:
        response = requests.get(RATES_API, timeout=TIMEOUT)
        if response.status_code != 200:
            logger.warning("Cotação: HTTP %s", response.status_code)
            return None
        data = response.json()
        rates = {"USD": float(data["USDBRL"]["bid"]), "EUR": float(data["EURBRL"]["bid"])}
        created = data["USDBRL"].get("create_date") or ""
        rates["date"] = datetime.strptime(created[:10], "%Y-%m-%d").strftime("%d/%m/%Y") if created else None
        return rates
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        logger.warning("Cotação: %s", type(exc).__name__)
        return None


def rates() -> dict | None:
    """Cotação em memória por algumas horas; se a API falhar, vale a última que funcionou."""
    if _rates_cache["rates"] and time.time() - _rates_cache["loaded_at"] < RATES_CACHE_SECONDS:
        return _rates_cache["rates"]
    fresh = _fetch_rates()
    if fresh:
        _rates_cache.update(rates=fresh, loaded_at=time.time())
        return fresh
    return _rates_cache["rates"]


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
    """Monta o valor em R$ a partir da carta reconhecida (e conferida no catálogo)."""
    result = PriceQuote(liga_url=liga_search_url(identification.pokemon_name))
    ref = (identification.catalog or {}).get("ref_prices") or {}
    tcg = ref.get("tcgplayer") or {}
    cardmarket = ref.get("cardmarket") or {}
    cm_value = cardmarket.get("average") or cardmarket.get("trend")
    usd_variants = {k: v for k, v in (tcg.get("variants") or {}).items() if v}
    if not usd_variants and not cm_value:
        result.missing = "sem_preco"
        return result
    rate = rates()
    if not rate:
        result.missing = "sem_cotacao"
        return result

    def to_brl(value, currency):
        return round(float(value) * rate[currency], 2)

    variants = [
        {"name": key, "source": "TCGplayer", "label": VARIANT_LABELS.get(key, key), "value": to_brl(value, "USD")}
        for key, value in usd_variants.items()
    ]
    variants.sort(key=lambda v: list(VARIANT_LABELS).index(v["name"]) if v["name"] in VARIANT_LABELS else 99)
    if variants:
        result.main, *others = variants
        result.variants = others
        result.updated_at = _date_br(tcg.get("updated_at"))
        result.cardmarket = to_brl(cm_value, "EUR") if cm_value else None
    else:
        result.main = {"name": "cardmarket", "source": "Cardmarket", "label": "média de venda",
                       "value": to_brl(cm_value, "EUR")}
        result.updated_at = _date_br(cardmarket.get("updated_at"))
    result.source = "referencia"
    result.rate_date = rate.get("date")
    return result
