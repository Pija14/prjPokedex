"""Reconhecimento de cartas Pokémon TCG pela foto, com o Google Gemini.

    foto ──▶ identify_card(imagem) ──▶ Gemini (visão) ──▶ JSON ──▶ CardIdentification
        ──▶ card_service.form_defaults(prefill=...) ──▶ usuário revisa e confirma ──▶ salvar

A chave fica só no servidor, na variável de ambiente GEMINI_API_KEY (.env, fora do git).
Nunca é enviada ao navegador.
"""
import base64
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

logger = logging.getLogger("carddex.gemini")

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# No plano gratuito cada modelo tem a própria cota diária e às vezes um fica sobrecarregado:
# com reservas, quando um recusa (429/503/404), o próximo atende.
DEFAULT_MODELS = "gemini-3-flash-preview,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-flash-latest"
RETRY_STATUS = {404, 429, 500, 503}
TIMEOUT_PER_MODEL = 40  # segundos
TOTAL_DEADLINE = 75

PROMPT = """You identify Pokémon Trading Card Game (TCG) cards from a photo. Return ONLY valid JSON:
{
  "is_pokemon_card": true,
  "pokemon_name": "name exactly as printed on the card, including suffixes like ex, V, VMAX, GX (e.g. \\"Charizard ex\\")",
  "collection_name": "set/expansion name in English ONLY if it is printed or you are sure from the set symbol (e.g. \\"Base Set\\", \\"151\\"); null otherwise. It is checked later against the official catalog using card_number and extra.set_code, so never guess",
  "card_number": "collector number as printed (e.g. \\"004/102\\", \\"SV049/SV094\\", \\"TG01/TG30\\"); null if not visible",
  "rarity": "one of: Common, Uncommon, Rare, Holo Rare, Reverse Holo, Double Rare, Ultra Rare, Illustration Rare, Special Illustration Rare, Hyper Rare, Secret Rare, Promo, or null",
  "language": "card language in Brazilian Portuguese (Português, Inglês, Japonês, Espanhol, Francês, Alemão, Italiano, Coreano, Chinês)",
  "confidence": 0.0,
  "extra": {"hp": "", "types": [], "stage": "", "set_code": "", "regulation_mark": "", "illustrator": "", "year": "", "card_type": "Pokémon | Treinador | Energia", "edition": "", "notes": "", "card_box": [0, 0, 1000, 1000]}
}
Rules:
- The set is identified from what is PRINTED at the bottom of the card: the collector number with the set total (e.g. 006/165) and the set code printed next to it (extra.set_code, e.g. MEW, PAL, SVI, CRZ, BRS; usually 2-4 capital letters). Transcribe both exactly, character by character. Leave extra.set_code "" if no code is printed (older cards show only a set symbol).
- Read what is printed; do not invent. Use null (or "" inside extra) for anything not visible or uncertain.
- extra.edition ("1ª Edição", "Shadowless", "Reverse Holo", "Promo"...) ONLY if the stamp or feature is clearly visible in the photo; otherwise "". Never guess editions or variants: they change the card value a lot.
- extra.types and extra.stage in Brazilian Portuguese (Fogo, Água, Planta, Elétrico, Psíquico, Lutador, Escuridão, Metal, Fada, Dragão, Incolor; Básico, Estágio 1, Estágio 2). extra.notes: at most one short sentence in Brazilian Portuguese, only with useful visible details (e.g. damage, signature, stamp); otherwise "".
- Rarity comes from the rarity symbol near the card number: ● Common, ◆ Uncommon, ★ Rare; ★ with holographic artwork = Holo Rare; two black stars = Double Rare; two silver stars = Ultra Rare; one gold star = Illustration Rare; two gold stars = Special Illustration Rare; three gold stars = Hyper Rare; number above the set total (e.g. 110/102) = Secret Rare; promo stamp = Promo.
- For Trainer or Energy cards, put the card name in pokemon_name and set extra.card_type accordingly.
- extra.card_box: bounding box of the whole card in the photo as [ymin, xmin, ymax, xmax], integers normalized 0-1000.
- confidence: 0 to 1, how sure you are about name, set and number together.
- If the image is not a Pokémon TCG card, return {"is_pokemon_card": false, "reason": "short reason in Brazilian Portuguese"}."""


class GeminiError(RuntimeError):
    """Falha ao reconhecer a carta; `message` é exibível ao usuário."""

    status = 502


class GeminiNotConfiguredError(GeminiError):
    status = 503


class NotACardError(GeminiError):
    status = 422


class GeminiTimeoutError(GeminiError):
    status = 504


@dataclass
class CardIdentification:
    """Dados reconhecidos; os nomes batem com os campos de `Card`."""

    pokemon_name: str | None = None
    collection_name: str | None = None
    card_number: str | None = None
    rarity: str | None = None
    language: str | None = None
    confidence: float | None = None  # 0–1, para a tela pedir revisão quando baixa
    extra: dict = field(default_factory=dict)  # HP, tipos, ilustrador, código do set...
    model: str | None = None
    # De onde veio a coleção: "catalogo" (carta conferida), "codigo" (set pelo código/número impresso),
    # "ia" (só a leitura da IA, sem confirmação) ou None (não identificada).
    collection_source: str | None = None
    catalog: dict | None = None  # dados do catálogo oficial (nomes em inglês)

    def as_prefill(self) -> dict:
        """Formato aceito por card_service.form_defaults(prefill=...)."""
        internal = {"confidence", "extra", "model", "collection_source", "catalog"}
        return {k: v for k, v in asdict(self).items() if k not in internal and v}

    def to_dict(self) -> dict:
        return asdict(self) | {"prefill": self.as_prefill()}


def api_key() -> str:
    """Lê GEMINI_API_KEY tolerando erros comuns ao colar: espaços, aspas e o prefixo "GEMINI_API_KEY="."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key.upper().startswith("GEMINI_API_KEY="):
        key = key.split("=", 1)[1].strip()
    return key.strip("\"'").strip()


def is_configured() -> bool:
    return bool(api_key())


def models() -> list[str]:
    names = [os.getenv("GEMINI_MODEL", "")] + os.getenv("GEMINI_FALLBACK_MODELS", DEFAULT_MODELS).split(",")
    return list(dict.fromkeys(n.strip() for n in names if n.strip()))


def identify_card(image: str | Path | bytes, mime_type: str = "image/jpeg") -> CardIdentification:
    """Identifica a carta na imagem (caminho do arquivo ou bytes)."""
    data = Path(image).read_bytes() if isinstance(image, (str, Path)) else image
    result, model = generate_json([{"text": PROMPT}, image_part(data, mime_type)])
    return _parse(result, model)


def image_part(data: bytes, mime_type: str) -> dict:
    return {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(data).decode()}}


def generate_json(parts: list[dict], *, thinking: str = "low", deadline_s: float = TOTAL_DEADLINE,
                  timeout_s: float = TIMEOUT_PER_MODEL) -> tuple[dict, str]:
    """Envia texto + imagens ao Gemini e devolve (JSON da resposta, modelo que respondeu).

    Tenta os modelos de reserva quando um recusa (cota, sobrecarga) até o prazo total.
    """
    key = api_key()
    if not key:
        raise GeminiNotConfiguredError("IA indisponível: defina GEMINI_API_KEY no arquivo .env do servidor.")
    deadline = time.monotonic() + deadline_s
    response, last_model, timed_out = None, None, False
    for model in models():
        remaining = deadline - time.monotonic()
        if remaining < 5:
            break
        config = {"responseMimeType": "application/json", "temperature": 0.1}
        if model.startswith("gemini-3"):
            config["thinkingConfig"] = {"thinkingLevel": thinking}
        try:
            response = requests.post(
                API_URL.format(model=model),
                json={"contents": [{"parts": parts}], "generationConfig": config},
                headers={"x-goog-api-key": key},  # no cabeçalho, não na URL: não aparece em logs
                timeout=min(timeout_s, remaining),
            )
        except requests.Timeout:
            logger.warning("Gemini %s: sem resposta a tempo", model)
            response, timed_out = None, True
            continue
        except requests.RequestException as exc:
            logger.warning("Gemini %s: falha de conexão (%s)", model, type(exc).__name__)
            response = None
            continue
        last_model = model
        if response.status_code not in RETRY_STATUS:
            break
        logger.warning("Gemini %s: HTTP %s, tentando o próximo modelo", model, response.status_code)

    if response is None:
        if timed_out:
            raise GeminiTimeoutError("A IA demorou demais para responder. Tente novamente.")
        raise GeminiError("Sem conexão com a IA. Verifique a internet do computador.")
    if response.status_code >= 400:
        raise GeminiError(_error_message(response))
    try:
        result = response.json()
        content = result["candidates"][0]["content"]["parts"]
        text = next(p["text"] for p in content if p.get("text") and not p.get("thought"))
        data = json.loads(_strip_fences(text))
    except (KeyError, IndexError, StopIteration, ValueError, TypeError) as exc:
        raise GeminiError("A IA respondeu num formato inesperado. Tente novamente.") from exc
    if not isinstance(data, dict):
        raise GeminiError("A IA respondeu num formato inesperado. Tente novamente.")
    return data, last_model


def _error_message(response: requests.Response) -> str:
    try:
        error = response.json().get("error", {})
    except ValueError:
        error = {}
    text = f"{error.get('status', '')} {error.get('message', '')}".lower()
    if "api key not valid" in text or "api_key_invalid" in json.dumps(error).lower():
        return "A chave do Gemini (GEMINI_API_KEY) é inválida."
    if response.status_code == 429 or "resource_exhausted" in text:
        return "Limite diário de uso da IA atingido. Tente mais tarde (ou preencha manualmente)."
    if response.status_code in (500, 503):
        return "A IA está sobrecarregada no momento. Tente novamente em instantes."
    if response.status_code == 403:
        return "A chave do Gemini não tem permissão para este modelo."
    return "A IA não conseguiu responder agora. Tente novamente."


def _parse(data: dict, model: str | None) -> CardIdentification:
    if data.get("is_pokemon_card") is False:
        raise NotACardError(f"Não parece uma carta Pokémon TCG: {_text(data.get('reason'), 160) or 'tente outra foto.'}")

    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    extra = {k: v for k, v in extra.items() if v not in (None, "", [], {})}
    confidence = data.get("confidence")
    try:
        confidence = max(0.0, min(1.0, float(confidence))) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    identification = CardIdentification(
        pokemon_name=_text(data.get("pokemon_name"), 120),
        collection_name=_text(data.get("collection_name"), 120),
        card_number=_text(data.get("card_number"), 30),
        rarity=_text(data.get("rarity"), 60),
        language=_text(data.get("language"), 40),
        confidence=confidence,
        extra=extra,
        model=model,
    )
    if not identification.pokemon_name:
        raise NotACardError("Não consegui ler o nome da carta. Tente uma foto mais nítida, de frente e com boa luz.")
    return identification


def _text(value, max_len: int) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = " ".join(str(value).split())
    return text[:max_len] if text and text.lower() not in {"null", "none", "unknown", "desconhecido"} else None


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
