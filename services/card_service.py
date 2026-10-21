"""Regras de negócio das cartas: validação, normalização, consultas e resumo da coleção.

As rotas (páginas HTML e API) chamam estas funções; nenhuma regra fica nas rotas.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from werkzeug.datastructures import FileStorage

from database.database import db
from database.models import Card
from services import image_service

RARITY_SUGGESTIONS = [  # nomes em português (ver services/translations.py)
    "Comum", "Incomum", "Rara", "Rara Holo", "Holo Reversa", "Rara Dupla", "Ultra Rara",
    "Rara Ilustração", "Rara Ilustração Especial", "Hiper Rara", "Rara Secreta", "Promo",
]
LANGUAGES = ["Português", "Inglês", "Japonês", "Espanhol", "Francês", "Alemão", "Italiano", "Coreano", "Chinês"]

TEXT_FIELDS = {  # campo: tamanho máximo
    "pokemon_name": 120, "collection_name": 120, "card_number": 30,
    "rarity": 60, "language": 40, "price_source": 120,
}
MAX_PRICE = Decimal("9999999999.99")


class ValidationError(ValueError):
    """Dados inválidos; `errors` mapeia campo → mensagem."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


# ---------- normalização ----------
def parse_price(value) -> Decimal | None:
    """Aceita 1.250,00 · 1250,00 · 1250.00 · R$ 1.250,00 · 1250. Vazio = sem preço."""
    if value is None:
        return None
    if isinstance(value, (int, Decimal)):
        text = str(value)
    elif isinstance(value, float):
        text = repr(value)
    else:
        text = str(value)
    text = re.sub(r"(?i)r\$|\s", "", text)
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", text):
        raise ValueError("Informe o valor como 1.250,00 ou 1250.00.")
    try:
        price = Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Valor inválido.") from exc
    if price > MAX_PRICE:
        raise ValueError("Valor alto demais.")
    return price


def parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("Data inválida (use AAAA-MM-DD).") from exc


def clean_card_data(data, partial: bool = False) -> dict:
    """Valida e normaliza os campos recebidos. Em `partial` (PUT/edição), só os enviados."""
    errors: dict[str, str] = {}
    clean: dict = {}
    for field, max_len in TEXT_FIELDS.items():
        if partial and field not in data:
            continue
        text = " ".join(str(data.get(field) or "").split())
        if len(text) > max_len:
            errors[field] = f"Use no máximo {max_len} caracteres."
        clean[field] = text or None
    if (not partial or "pokemon_name" in data) and not clean.get("pokemon_name"):
        errors["pokemon_name"] = "Informe o nome do Pokémon."

    if not partial or "price" in data:
        try:
            clean["price"] = parse_price(data.get("price"))
        except ValueError as exc:
            errors["price"] = str(exc)
    if not partial or "price_date" in data:
        try:
            clean["price_date"] = parse_date(data.get("price_date"))
        except ValueError as exc:
            errors["price_date"] = str(exc)

    if errors:
        raise ValidationError(errors)
    return clean


# ---------- consultas ----------
def list_cards(q: str = "", collection: str = "", rarity: str = "") -> list[Card]:
    query = select(Card)
    if q := (q or "").strip():
        like = f"%{q}%"
        query = query.where(or_(Card.pokemon_name.ilike(like), Card.card_number.ilike(like)))
    if collection := (collection or "").strip():
        query = query.where(Card.collection_name == collection)
    if rarity := (rarity or "").strip():
        query = query.where(Card.rarity == rarity)
    return list(db.session.scalars(query.order_by(Card.created_at.desc(), Card.id.desc())))


NO_COLLECTION = "Coleção não informada"


def _number_key(card: Card) -> tuple:
    """Ordem do álbum: 001, 002… 160/159 (secretas no fim); prefixos (TG01, SV049) depois dos números; sem número por último."""
    match = re.match(r"\s*([A-Za-z]*)0*(\d+)", card.card_number or "")
    if not match:
        return (2, "", 0, (card.card_number or "").lower(), card.pokemon_name.lower())
    prefix, digits = match.groups()
    return (1 if prefix else 0, prefix.upper(), int(digits), (card.card_number or "").lower(), card.pokemon_name.lower())


def group_by_collection(cards: list[Card]) -> list[dict]:
    """Agrupa as cartas por coleção (em ordem alfabética, as sem coleção por último), cada grupo em ordem de número."""
    groups: dict[str, list[Card]] = {}
    for card in cards:
        groups.setdefault((card.collection_name or "").strip(), []).append(card)
    result = []
    for name in sorted(groups, key=lambda n: (n == "", n.casefold())):
        items = sorted(groups[name], key=_number_key)
        result.append({
            "name": name or NO_COLLECTION,
            "cards": items,
            "count": len(items),
            "value": sum((c.price for c in items if c.price is not None), Decimal("0")),
        })
    return result


def get_card(card_id: int) -> Card | None:
    return db.session.get(Card, card_id)


def filter_options() -> dict[str, list[str]]:
    def distinct(column):
        return [v for v in db.session.scalars(select(column).where(column.is_not(None)).distinct().order_by(column))]

    return {"collections": distinct(Card.collection_name), "rarities": distinct(Card.rarity)}


def collection_summary(recent: int = 4) -> dict:
    total_cards = db.session.scalar(select(func.count(Card.id))) or 0
    prices = db.session.scalars(select(Card.price).where(Card.price.is_not(None)))
    total_value = sum((Decimal(p) for p in prices), Decimal("0.00"))
    collections = db.session.scalar(select(func.count(func.distinct(Card.collection_name)))) or 0
    latest = list(db.session.scalars(select(Card).order_by(Card.created_at.desc(), Card.id.desc()).limit(recent)))
    return {"total_cards": total_cards, "total_value": total_value, "collections": collections, "recent": latest}


# ---------- escrita ----------
def _apply(card: Card, clean: dict) -> None:
    for field, value in clean.items():
        setattr(card, field, value)
    if card.price is not None and card.price_date is None:
        card.price_date = date.today()
    if card.price is None and "price" in clean:
        card.price_date = None


def create_card(data, image: FileStorage | None = None) -> Card:
    clean = clean_card_data(data)
    image_path = _store_image(image)
    card = Card(image_path=image_path)
    _apply(card, clean)
    db.session.add(card)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        image_service.delete_image(image_path)
        raise
    return card


def update_card(card: Card, data, image: FileStorage | None = None, remove_image: bool = False, partial: bool = True) -> Card:
    clean = clean_card_data(data, partial=partial)
    new_image = _store_image(image)
    old_image = card.image_path
    _apply(card, clean)
    if new_image or remove_image:
        card.image_path = new_image
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        image_service.delete_image(new_image)
        raise
    if (new_image or remove_image) and old_image:
        image_service.delete_image(old_image)
    return card


def delete_card(card: Card) -> None:
    image_path = card.image_path
    db.session.delete(card)
    db.session.commit()
    image_service.delete_image(image_path)


def _store_image(image: FileStorage | None) -> str | None:
    if not image_service.has_file(image):
        return None
    try:
        return image_service.save_image(image)
    except image_service.ImageError as exc:
        raise ValidationError({"image": str(exc)}) from exc


# ---------- apoio às telas ----------
def form_defaults(card: Card | None = None, prefill: dict | None = None) -> dict:
    """Valores iniciais do formulário. `prefill` é o ponto onde entrarão os dados
    identificados pelo Gemini (foto → identificação → formulário preenchido → confirmar)."""
    values = {field: "" for field in TEXT_FIELDS} | {"price": "", "price_date": ""}
    if card:
        values.update({field: getattr(card, field) or "" for field in TEXT_FIELDS})
        values["price"] = format_price_input(card.price)
        values["price_date"] = card.price_date.isoformat() if card.price_date else ""
    if prefill:
        values.update({k: ("" if v is None else str(v)) for k, v in prefill.items() if k in values})
    return values


def format_price_input(price: Decimal | None) -> str:
    if price is None:
        return ""
    whole, cents = f"{price:.2f}".split(".")
    return f"{int(whole):,}".replace(",", ".") + f",{cents}"


_TIER_PATTERNS = [  # do mais raro para o mais comum; palavras inteiras
    ("secret", r"\b(secret|secreta|hyper|hiper|gold|dourada|rainbow|arco)\b|special illustration|ilustra\w* especial"),
    ("ultra", r"\b(ultra|illustration|ilustra\w*|double|dupla|ex|gx|v|vmax|vstar|full art)\b"),
    ("holo", r"\b(holo|holográfica|holografica|promo|brilhante)\b"),
    ("uncommon", r"\b(uncommon|incomum)\b"),
    ("rare", r"\b(rare|rara|raro)\b"),
]


def rarity_tier(rarity: str | None) -> str:
    """Nível visual do badge de raridade: none, common, uncommon, rare, holo, ultra ou secret."""
    text = (rarity or "").lower()
    if not text.strip():
        return "none"
    for tier, pattern in _TIER_PATTERNS:
        if re.search(pattern, text):
            return tier
    return "common"
