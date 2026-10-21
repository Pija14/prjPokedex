"""Reconhecimento de cartas pelo Google Gemini — AINDA NÃO IMPLEMENTADO.

Contrato planejado:

    imagem da carta ──▶ identify_card(image_path) ──▶ Gemini Vision ──▶ JSON estruturado
        ──▶ CardIdentification ──▶ card_service.form_defaults(prefill=...) ──▶ usuário confirma ──▶ salvar

A chave fica só no servidor, na variável de ambiente GEMINI_API_KEY (ver .env.example).
Nunca envie a chave ao navegador nem a grave no repositório.
"""
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


class GeminiNotConfiguredError(RuntimeError):
    """GEMINI_API_KEY não definida no ambiente do servidor."""


@dataclass
class CardIdentification:
    """Dados que o Gemini deverá devolver; os nomes batem com os campos de `Card`."""

    pokemon_name: str | None = None
    collection_name: str | None = None
    card_number: str | None = None
    rarity: str | None = None
    language: str | None = None
    confidence: float | None = None  # 0–1, para o app pedir revisão quando baixa
    extra: dict = field(default_factory=dict)  # outras informações visíveis (HP, tipo, ilustrador...)

    def as_prefill(self) -> dict:
        """Formato aceito por card_service.form_defaults(prefill=...)."""
        return {k: v for k, v in asdict(self).items() if k not in {"confidence", "extra"} and v}


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def identify_card(image_path: str | Path) -> CardIdentification:
    """Identifica a carta na imagem. Será implementado na próxima etapa."""
    if not is_configured():
        raise GeminiNotConfiguredError("Defina GEMINI_API_KEY no .env para usar o reconhecimento automático.")
    raise NotImplementedError("O reconhecimento de cartas pelo Gemini ainda não foi implementado.")
