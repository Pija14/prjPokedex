from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.database import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Card(db.Model):
    """Uma carta da coleção. Preço em Decimal (nunca float) para não perder centavos."""

    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pokemon_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    collection_name: Mapped[str | None] = mapped_column(String(120), index=True)
    card_number: Mapped[str | None] = mapped_column(String(30))
    rarity: Mapped[str | None] = mapped_column(String(60), index=True)
    language: Mapped[str | None] = mapped_column(String(40))
    image_path: Mapped[str | None] = mapped_column(String(255))  # relativo a static/
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_source: Mapped[str | None] = mapped_column(String(120))
    price_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self, image_url: str | None = None) -> dict:
        return {
            "id": self.id,
            "pokemon_name": self.pokemon_name,
            "collection_name": self.collection_name,
            "card_number": self.card_number,
            "rarity": self.rarity,
            "language": self.language,
            "image_path": self.image_path,
            "image_url": image_url,
            "price": f"{self.price:.2f}" if self.price is not None else None,
            "price_source": self.price_source,
            "price_date": self.price_date.isoformat() if self.price_date else None,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }

    def __repr__(self) -> str:
        return f"<Card {self.id} {self.pokemon_name!r}>"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite devolve datas sem fuso; foram gravadas em UTC.
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
