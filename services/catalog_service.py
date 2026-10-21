"""Catálogo público de cartas (api.pokemontcg.io) para CONFIRMAR o set e a raridade.

A IA lê o que está impresso (nome, número 006/165, código do set como MEW/CRZ); aqui o set
é identificado pelo código ou pelo total do número, e a carta é conferida no catálogo.
Se o catálogo estiver fora do ar, nada quebra: fica a sugestão da IA, marcada como não confirmada.
"""
import json
import logging
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from flask import current_app, has_app_context

logger = logging.getLogger("carddex.catalog")

API = "https://api.pokemontcg.io/v2"
SETS_CACHE_DAYS = 7
TIMEOUT = (4, 8)  # conectar, ler
RETRIES = 3  # a API costuma devolver 500/502 de vez em quando
BUDGET = 15  # segundos no máximo por consulta (com as novas tentativas): o catálogo não pode travar o cadastro


@dataclass
class CatalogMatch:
    set_id: str
    set_name: str  # em inglês, como no catálogo
    set_code: str | None
    printed_total: int | None
    release_date: str | None
    rarity: str | None = None  # em inglês, como no catálogo
    card_id: str | None = None
    matched_by: str = ""  # "carta" (confirmada no catálogo) | "set" (só o set, pelo código/total)

    def to_dict(self) -> dict:
        return asdict(self)


def _get(path: str, params: dict) -> dict | None:
    deadline = time.monotonic() + BUDGET
    for attempt in range(RETRIES):
        if time.monotonic() > deadline - 2:
            break
        try:
            response = requests.get(f"{API}/{path}", params=params, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.json()
            if response.status_code not in (429, 500, 502, 503, 504):
                logger.warning("Catálogo %s: HTTP %s", path, response.status_code)
                return None
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Catálogo %s: %s", path, type(exc).__name__)
        time.sleep(0.4 * (attempt + 1))
    return None


def _cache_file() -> Path | None:
    if not has_app_context():
        return None
    return Path(current_app.config["DATA_DIR"]) / "catalog_sets.json"


_memory: dict = {"sets": None, "loaded_at": 0.0}


def get_sets() -> list[dict]:
    """Lista de sets (≈170), em memória e em data/catalog_sets.json por alguns dias."""
    max_age = SETS_CACHE_DAYS * 86400
    if _memory["sets"] and time.time() - _memory["loaded_at"] < max_age:
        return _memory["sets"]
    cache = _cache_file()
    cached = None
    if cache and cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
    if cached and time.time() - cached.get("fetched_at", 0) < max_age:
        _memory.update(sets=cached["sets"], loaded_at=cached["fetched_at"])
        return cached["sets"]
    data = _get("sets", {"select": "id,name,ptcgoCode,printedTotal,total,releaseDate,series", "pageSize": 250})
    if data and data.get("data"):
        sets = data["data"]
        _memory.update(sets=sets, loaded_at=time.time())
        if cache:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"fetched_at": time.time(), "sets": sets}), encoding="utf-8")
            except OSError:
                pass
        return sets
    return cached["sets"] if cached else []  # catálogo fora do ar: usa o cache antigo, se houver


def _norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def parse_number(card_number: str | None) -> tuple[str | None, int | None]:
    """'006/165' → ('6', 165) · 'SV049/SV094' → ('SV49', 94) · 'TG01/TG30' → ('TG1', 30) · '25' → ('25', None)."""
    if not card_number:
        return None, None
    match = re.match(r"^\s*([A-Za-z]*)0*(\d+)([a-z]?)\s*(?:/\s*[A-Za-z]*0*(\d+))?", card_number.strip())
    if not match:
        return None, None
    prefix, digits, suffix, total = match.groups()
    return f"{prefix.upper()}{int(digits)}{suffix}", int(total) if total else None


def find_sets(set_code: str | None, printed_total: int | None, name_hint: str | None = None) -> list[dict]:
    sets = get_sets()
    if not sets:
        return []
    if set_code:
        code = set_code.strip().upper()
        by_code = [s for s in sets if (s.get("ptcgoCode") or "").upper() == code]
        if by_code:
            return by_code
    candidates = [s for s in sets if printed_total and s.get("printedTotal") == printed_total]
    if name_hint and len(candidates) > 1:
        hint = _norm(name_hint)
        named = [s for s in candidates if _norm(s["name"]) in hint or hint in _norm(s["name"])]
        if named:
            return named
    return candidates


def _match_from(set_data: dict, card: dict | None, matched_by: str) -> CatalogMatch:
    return CatalogMatch(
        set_id=set_data["id"], set_name=set_data["name"], set_code=set_data.get("ptcgoCode"),
        printed_total=set_data.get("printedTotal"), release_date=set_data.get("releaseDate"),
        rarity=(card or {}).get("rarity"), card_id=(card or {}).get("id"), matched_by=matched_by,
    )


def resolve(pokemon_name: str | None, card_number: str | None, set_code: str | None = None,
            set_name_hint: str | None = None) -> CatalogMatch | None:
    """Confirma o set (e, se possível, a carta) no catálogo. None = não deu para confirmar."""
    number, printed_total = parse_number(card_number)
    if not number:
        return None
    candidates = find_sets(set_code, printed_total, set_name_hint)
    set_ids = [s["id"] for s in candidates][:6]
    base_name = re.sub(r"\s+(ex|gx|v|vmax|vstar|δ|lv\.?\s*x)$", "", (pokemon_name or "").strip(), flags=re.I)
    if pokemon_name:
        query = f'name:"{base_name}*" number:{number}'
        if set_ids:
            query += " (" + " OR ".join(f"set.id:{sid}" for sid in set_ids) + ")"
        data = _get("cards", {"q": query, "select": "id,name,number,rarity,set", "pageSize": 20})
        cards = (data or {}).get("data") or []
        if set_ids:
            cards = [c for c in cards if c["set"]["id"] in set_ids] or cards
        if printed_total:
            cards = [c for c in cards if c["set"].get("printedTotal") == printed_total] or cards
        exact = [c for c in cards if _norm(c["name"]) == _norm(pokemon_name)]
        cards = exact or cards  # "Charizard ex" (151) e "Charizard" (Expedition) têm o mesmo número
        if len(cards) == 1 or (cards and len({c["set"]["id"] for c in cards}) == 1):
            card = cards[0]
            return _match_from(card["set"], card, "carta")
    if len(candidates) == 1:
        return _match_from(candidates[0], None, "set")
    return None


# Cartas japonesas, coreanas e chinesas têm numeração própria: o catálogo (internacional) não serve.
_OTHER_NUMBERING = {"japonês", "japones", "coreano", "chinês", "chines"}


def confirm(identification):
    """Confere a leitura da IA no catálogo e deixa coleção e raridade em português."""
    from services.translations import rarity_pt, set_name_pt

    language = (identification.language or "").strip().lower()
    match = None
    if language not in _OTHER_NUMBERING:
        try:
            match = resolve(identification.pokemon_name, identification.card_number,
                            identification.extra.get("set_code"), identification.collection_name)
        except Exception:  # o catálogo nunca pode impedir o cadastro
            logger.exception("Falha ao consultar o catálogo")
    if match:
        identification.collection_name = match.set_name
        if match.rarity:
            identification.rarity = match.rarity
        identification.collection_source = "catalogo" if match.matched_by == "carta" else "codigo"
        identification.catalog = match.to_dict()
    elif identification.collection_name:
        identification.collection_source = "ia"
    identification.collection_name = set_name_pt(identification.collection_name)
    identification.rarity = rarity_pt(identification.rarity)
    return identification
