from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    # Nota OFICIAL de uma empresa de grading (ex.: PSA 10). Nunca é preenchida pela IA.
    grading_company: Mapped[str | None] = mapped_column(String(20))
    official_grade: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    evaluations: Mapped[list["CardGradingEvaluation"]] = relationship(
        back_populates="card", cascade="all, delete-orphan", passive_deletes=True,
        order_by="desc(CardGradingEvaluation.created_at), desc(CardGradingEvaluation.id)",
    )

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
            "grading_company": self.grading_company,
            "official_grade": self.official_grade,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }

    def __repr__(self) -> str:
        return f"<Card {self.id} {self.pokemon_name!r}>"


class CardGradingEvaluation(db.Model):
    """ESTIMATIVA visual da condição feita pela IA (não é nota oficial). Guardada à parte da nota oficial do card."""

    __tablename__ = "card_grading_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True)
    estimated_range: Mapped[str] = mapped_column(String(10), nullable=False)  # "8-9", "9"
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)  # low | medium | high
    centering_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    corners_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    edges_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    surface_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    analysis_json: Mapped[str] = mapped_column(Text, nullable=False)  # análise completa, já validada
    model: Mapped[str | None] = mapped_column(String(60))
    # Nota oficial que o card tinha no momento (para comparar no futuro "IA antes do envio" x "PSA oficial").
    official_grade_at_time: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    card: Mapped[Card] = relationship(back_populates="evaluations")

    @property
    def analysis(self) -> dict:
        import json
        return json.loads(self.analysis_json)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "card_id": self.card_id,
            "estimated_range": self.estimated_range,
            "confidence": self.confidence,
            "scores": {k: (float(v) if v is not None else None) for k, v in (
                ("centering", self.centering_score), ("corners", self.corners_score),
                ("edges", self.edges_score), ("surface", self.surface_score))},
            "analysis": self.analysis,
            "model": self.model,
            "official_grade_at_time": self.official_grade_at_time,
            "created_at": _iso(self.created_at),
            "is_official": False,
        }

    def __repr__(self) -> str:
        return f"<CardGradingEvaluation {self.id} card={self.card_id} {self.estimated_range}>"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite devolve datas sem fuso; foram gravadas em UTC.
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
