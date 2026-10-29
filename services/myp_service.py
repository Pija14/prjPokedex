"""Preço da carta no Brasil pela MYP Cards (mypcards.com), em R$. Só leitura, nada é gravado.

A MYP não tem API pública: a busca e a página do produto são lidas como HTML (o robots.txt do site
permite essas páginas). É frágil por natureza — se o layout mudar, lookup() devolve None e o Scan
mostra o valor de referência. Sempre se identifica como CardDex e guarda as respostas em cache.

    nome + número (071/084) + código do set (PBL) ──▶ busca ──▶ item certo ──▶ página do produto
        ──▶ preço médio, menor preço e último vendido
"""
import html
import logging
import re
import time
from dataclasses import asdict, dataclass

import requests

from services.catalog_service import _norm, parse_number

logger = logging.getLogger("carddex.myp")

BASE = "https://mypcards.com"
HEADERS = {"User-Agent": "CardDex/1.0 (colecao pessoal de cartas)", "Accept-Language": "pt-BR,pt;q=0.9"}
TIMEOUT = (4, 8)  # conectar, ler
BUDGET = 15  # segundos no máximo por consulta: o preço não pode travar o Scan
MAX_PAGES = 3  # a busca devolve ~52 itens por página (cartas e produtos misturados)
CACHE_SECONDS = 30 * 60


@dataclass
class MypPrice:
    url: str
    title: str  # como aparece na MYP, ex.: "Charizard ex (006/165)"
    set_name: str | None
    set_code: str | None
    average: float | None = None  # preço médio dos anúncios
    lowest: float | None = None  # menor preço anunciado
    last_sold: float | None = None
    last_sold_detail: str | None = None  # ex.: "NM · Normal · Português"

    def to_dict(self) -> dict:
        return asdict(self)


_cache: dict = {}


def _get(path: str, params: dict | None = None, deadline: float | None = None) -> str | None:
    if deadline and time.monotonic() > deadline:
        return None
    try:
        response = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("MYP %s: %s", path, type(exc).__name__)
        return None
    if response.status_code != 200:
        logger.warning("MYP %s: HTTP %s", path, response.status_code)
        return None
    return response.text


def _money(text: str | None) -> float | None:
    """'R$ 1.234,56' → 1234.56"""
    match = re.search(r"(\d[\d.]*,\d{2})", text or "")
    return float(match[1].replace(".", "").replace(",", ".")) if match else None


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_search(page: str) -> list[dict]:
    """Itens da busca: {"title", "number", "set_name", "set_code", "href", "price"}."""
    items = []
    for body in re.findall(r'(?s)<li class="stream-item" data-key="\d+">(.*?)</li>', page):
        title = re.search(r'<h3 title="([^"]*)"', body)
        href = re.search(r'href="(/pokemon/produto/\d+/[^"]*)"', body)
        if not (title and href):
            continue
        title = html.unescape(title[1]).strip()
        number = re.search(r"\(([^()]+)\)\s*$", title)
        edition = re.search(r'class="card-edicao" title="([^"]*)">([^<]*)<', body)
        price = re.search(r'class="card-preco[^"]*"[^>]*>(.*?)<', body, re.S)
        items.append({
            "title": title,
            "number": number[1].strip() if number else None,
            "set_name": html.unescape(edition[1]).strip() if edition else None,
            "set_code": edition[2].strip() if edition else None,
            "href": href[1],
            "price": _money(price[1]) if price else None,
        })
    return items


def parse_product(page: str) -> dict:
    """Resumo de preços da página do produto: médio, menor e último vendido."""
    summary = {}
    block = re.search(r'(?s)<div class="resumo-precos">(.*?)</div>', page)
    if not block:
        return summary
    for kind, attrs, inner in re.findall(r'(?s)<span class="resumo-preco resumo-preco--(\w+)"([^>]*)>(.*?)</span></span>', block[1]):
        title = html.unescape(re.search(r'title="([^"]*)"', attrs)[1]) if 'title="' in attrs else ""
        value = _money(_text(inner))
        if kind == "menor":
            summary["lowest"] = value
            average = re.search(r"m[ée]dio\s*R\$\s*([\d.,]+)", title, re.I)
            summary["average"] = _money(average[1]) if average else None
        elif kind == "ultimo":
            summary["last_sold"] = value
            detail = re.search(r"\(([^()]+)\)", title)
            summary["last_sold_detail"] = detail[1] if detail else None
    return summary


def _same_number(item_number: str | None, number: str, total: int | None) -> bool:
    item_num, item_total = parse_number(item_number)
    if not item_num or item_num.upper() != number.upper():
        return False
    return total is None or item_total is None or item_total == total


def _candidates(items: list[dict], name: str, number: str, total: int | None) -> list[dict]:
    first_word = _norm(name).split(" ")[0]
    return [i for i in items if _same_number(i["number"], number, total) and first_word in _norm(i["title"])]


def _pick(candidates: list[dict], set_code: str | None) -> dict | None:
    """Com o código do set, só vale a coleção certa (reimpressões têm o mesmo número: 004/102 da
    coleção Base e da 30th Celebration). Sem código, só se não houver dúvida. Ambíguo → None."""
    if set_code:
        return next((i for i in candidates if (i["set_code"] or "").upper() == set_code.upper()), None)
    if candidates and len({i["set_code"] for i in candidates}) == 1:
        return candidates[0]
    return None  # mesmo número em coleções diferentes e sem código para desempatar: melhor não chutar


def lookup(name: str | None, card_number: str | None, set_code: str | None = None) -> MypPrice | None:
    """Preço da carta na MYP Cards. Nunca lança exceção: qualquer falha vira None."""
    number, total = parse_number(card_number)
    if not name or not number:
        return None
    key = (_norm(name), number.upper(), total, (set_code or "").upper())
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        result = _lookup(name, number, total, set_code)
    except Exception:  # layout mudou ou algo inesperado: o Scan segue com o valor de referência
        logger.exception("MYP: falha ao ler o preço de %s %s", name, card_number)
        result = None
    _cache[key] = (time.time(), result)
    return result


def _lookup(name: str, number: str, total: int | None, set_code: str | None) -> MypPrice | None:
    deadline = time.monotonic() + BUDGET
    candidates: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        params = {"ProdutoSearch[query]": name}
        if page > 1:
            params["page"] = page
        found = _get("/pokemon", params, deadline)
        items = parse_search(found) if found else []
        if not items:  # fim dos resultados (ou falha)
            break
        candidates += _candidates(items, name, number, total)
        if set_code and _pick(candidates, set_code):
            break  # achou a coleção certa: não precisa das próximas páginas
    match = _pick(candidates, set_code)
    if not match:
        return None
    price = MypPrice(url=f"{BASE}{match['href']}", title=match["title"], set_name=match["set_name"],
                     set_code=match["set_code"], lowest=match["price"])
    product = _get(match["href"], deadline=deadline)
    if product:
        summary = parse_product(product)
        price.average = summary.get("average")
        price.lowest = summary.get("lowest") or price.lowest
        price.last_sold = summary.get("last_sold")
        price.last_sold_detail = summary.get("last_sold_detail")
    return price if (price.average or price.lowest) else None
