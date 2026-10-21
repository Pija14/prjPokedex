"""Avaliação visual da condição da carta por IA (estimativa de faixa estilo PSA).

    foto da frente + foto do verso ──▶ check_photo (segurança e qualidade)
        ──▶ Gemini (PROMPT) ──▶ validate_analysis ──▶ regra conservadora ──▶ CardGradingEvaluation

É uma ESTIMATIVA feita a partir das fotos, nunca uma nota oficial: a nota oficial fica em
Card.grading_company/official_grade e nunca é alterada aqui. As fotos são analisadas em memória
e descartadas (não são gravadas).
"""
import io
import json
import logging
import math
import re
import threading

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

from database.database import db
from database.models import Card, CardGradingEvaluation
from services import gemini_service, image_service

logger = logging.getLogger("carddex.grader")

MIN_SIDE_PX = 600  # lado menor mínimo da foto
MIN_BRIGHTNESS = 40  # 0–255
MIN_SHARPNESS = 10.0  # variância do Laplaciano (foto reduzida a ~1000 px): só barra desfoque forte; o resto a IA avalia
MAX_BLOWN_OUT = 0.35  # fração de pixels estourados (reflexo/flash)
GRADING_DEADLINE = 110  # segundos: analisar 2 fotos com raciocínio leva mais que identificar
GRADING_TIMEOUT_PER_MODEL = 80

CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
CRITERIA = ("centering", "corners", "edges", "surface")
DEFECT_TYPES = {"edge_whitening", "corner_damage", "surface_scratch", "dent", "print_defect",
                "centering_issue", "stain", "crease", "unknown"}
SEVERITIES = {"minor", "moderate", "major"}
CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")

MISSING_PHOTO_MESSAGE = "Para realizar uma avaliação mais confiável, envie fotos da frente e do verso da carta."
PHOTO_TIPS = ["com boa iluminação;", "sem reflexos;", "mostrando a carta inteira;", "mantendo a câmera paralela à carta."]

PROMPT = """You are a careful trading card condition inspector. You receive TWO photos of the SAME Pokémon TCG card:
image 1 = FRONT, image 2 = BACK. Estimate its visual condition in the style of PSA grading criteria.
This is NOT an official PSA grade and you must never present it as one.

Evaluate each criterion separately, using both photos:
- centering: left/right and top/bottom border balance on front and back. Give approximate ratios ("aprox. 55/45")
  ONLY if the borders are clearly visible; never invent exact measurements.
- corners: each of the 4 corners (front and back): whitening, wear, dings, rounding, cuts.
- edges: top, bottom, left, right edges: whitening, chipping, nicks, print defects, damage.
- surface: scratches, scuffs, stains, marks, print lines, dents, pressure marks, creases.

Rules:
- Report only what is visible. Do not invent defects. Mark a defect "visible": true only when it is clearly seen;
  use "visible": false for a POSSIBLE defect you cannot confirm (e.g. a glare spot that may hide a scratch).
- If a criterion cannot be judged from the photos (blur, glare, crop, sleeve/toploader reflections), set its
  "score" to null, its "confidence" to "low" and explain why in "assessment".
- Surface is often hard to judge from phone photos: if you cannot see it properly, confidence must be "low".
- Consider the photo quality. If the photos do not show a card, or are too dark/blurry/cropped to evaluate,
  set photo_quality.usable to false and list the problems.
- Scores are 1-10 (half points allowed). overall.estimated_range is a RANGE like "7-8", "8-9", "9-10";
  use a single number ("9") only with strong evidence. When in doubt between two grades, give the range.
  Be conservative: the overall range must not be higher than the weakest criterion allows.
- confidence values: "low", "medium" or "high".
- All texts (assessment, description, summary, issues) in Brazilian Portuguese, short and objective.
- Never write that this is an official PSA grade.

Return ONLY valid JSON:
{
  "photo_quality": {"usable": true, "issues": ["..."]},
  "overall": {"estimated_range": "8-9", "confidence": "medium"},
  "centering": {"score": 9, "assessment": "...", "front_lr": "aprox. 55/45", "front_tb": "", "back_lr": "", "back_tb": "", "confidence": "medium"},
  "corners": {"score": 9, "assessment": "...", "corners": {"top_left": "...", "top_right": "...", "bottom_left": "...", "bottom_right": "..."}, "confidence": "medium"},
  "edges": {"score": 8, "assessment": "...", "confidence": "medium"},
  "surface": {"score": 9, "assessment": "...", "confidence": "low"},
  "defects": [{"type": "edge_whitening | corner_damage | surface_scratch | dent | print_defect | centering_issue | stain | crease | unknown",
               "location": "front_bottom_edge", "severity": "minor | moderate | major", "visible": true, "description": "..."}],
  "summary": "..."
}"""


# ---------- erros (todos com `status` HTTP e mensagem exibível) ----------
class GradingError(RuntimeError):
    status = 400


class MissingPhotoError(GradingError):
    status = 400


class PhotoQualityError(GradingError):
    """Foto insuficiente para avaliar: a tela mostra as dicas para refazer a foto."""

    status = 422

    def __init__(self, message: str, issues: list[str] | None = None):
        super().__init__(message)
        self.issues = issues or []
        self.tips = PHOTO_TIPS


class GradingBusyError(GradingError):
    status = 409


class InvalidAnalysisError(GradingError):
    status = 502


# ---------- trava: uma avaliação por card de cada vez ----------
_lock = threading.Lock()
_in_progress: set[int] = set()


def is_busy(card_id: int) -> bool:
    with _lock:
        return card_id in _in_progress


# ---------- fotos ----------
def check_photo(data: bytes, side: str) -> None:
    """Recusa fotos que não permitem uma avaliação confiável (antes de gastar a cota da IA)."""
    label = "da frente" if side == "front" else "do verso"
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            width, height = img.size
            gray = _flatten(img).convert("L")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise PhotoQualityError(f"Não foi possível abrir a foto {label}.") from exc
    if min(width, height) < MIN_SIDE_PX:
        raise PhotoQualityError(f"A foto {label} é pequena demais ({width}×{height} px). Use pelo menos {MIN_SIDE_PX} px no lado menor.",
                                ["resolução baixa"])
    gray.thumbnail((1000, 1000))
    if ImageStat.Stat(gray).mean[0] < MIN_BRIGHTNESS:
        raise PhotoQualityError(f"A foto {label} está muito escura.", ["imagem muito escura"])
    if sharpness(gray) < MIN_SHARPNESS:
        raise PhotoQualityError(f"A foto {label} parece desfocada.", ["imagem muito desfocada"])
    histogram = gray.histogram()
    if sum(histogram[250:]) / max(1, sum(histogram)) > MAX_BLOWN_OUT:
        raise PhotoQualityError(f"A foto {label} tem reflexo ou brilho estourado demais.", ["reflexo excessivo"])


def _flatten(img: Image.Image) -> Image.Image:
    """PNG com transparência: fundo cinza neutro (não conta como brilho estourado)."""
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (128, 128, 128, 255))
        return Image.alpha_composite(background, rgba)
    return img


def sharpness(gray: Image.Image) -> float:
    """Variância do Laplaciano: valores baixos = pouca borda nítida = foto desfocada."""
    laplacian = gray.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    return ImageStat.Stat(laplacian).var[0]


def _read(file: FileStorage | None, side: str) -> tuple[bytes, str]:
    if not image_service.has_file(file):
        raise MissingPhotoError(MISSING_PHOTO_MESSAGE)
    label = "da frente" if side == "front" else "do verso"
    try:
        data, mime = image_service.read_for_analysis(file)  # tipo pelo conteúdo, limite de tamanho
    except image_service.ImageError as exc:
        raise MissingPhotoError(f"Foto {label}: {exc}") from exc
    check_photo(data, side)
    return data, mime


# ---------- validação da resposta ----------
def _text(value, max_len: int = 400) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return " ".join(str(value).split())[:max_len]


def _confidence(value, default: str = "low") -> str:
    value = _text(value, 10).lower()
    return value if value in CONFIDENCE_ORDER else default


def _score(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise InvalidAnalysisError("A IA respondeu num formato inesperado. Tente novamente.")
    try:
        number = float(str(value).replace(",", "."))
    except ValueError as exc:
        raise InvalidAnalysisError("A IA respondeu num formato inesperado. Tente novamente.") from exc
    if not math.isfinite(number) or not 1 <= number <= 10:
        raise InvalidAnalysisError("A IA respondeu com uma nota fora da escala de 1 a 10.")
    return round(number * 2) / 2


def parse_range(value) -> tuple[int, int]:
    """'8-9' · '8–9' · 'PSA 8 - 9' · '9' → (8, 9) / (9, 9)."""
    text = re.sub(r"(?i)psa|\s", "", _text(value, 20)).replace("–", "-").replace("—", "-")
    match = re.fullmatch(r"(10|[1-9])(?:-(10|[1-9]))?", text)
    if not match:
        raise InvalidAnalysisError("A IA não devolveu uma faixa estimada válida. Tente novamente.")
    low = int(match.group(1))
    high = int(match.group(2) or low)
    if low > high or high - low > 3:
        raise InvalidAnalysisError("A IA não devolveu uma faixa estimada válida. Tente novamente.")
    return low, high


def format_range(low: int, high: int) -> str:
    return str(low) if low == high else f"{low}-{high}"


def validate_analysis(data: dict) -> dict:
    """Confere o JSON da IA e devolve uma versão normalizada (só os campos conhecidos)."""
    if not isinstance(data, dict) or not isinstance(data.get("overall"), dict):
        raise InvalidAnalysisError("A IA respondeu num formato inesperado. Tente novamente.")
    quality = data.get("photo_quality") if isinstance(data.get("photo_quality"), dict) else {}
    issues = [_text(i, 120) for i in quality.get("issues") or [] if _text(i, 120)][:6] if isinstance(quality.get("issues"), list) else []
    clean = {"photo_quality": {"usable": quality.get("usable") is not False, "issues": issues}}

    for name in CRITERIA:
        block = data.get(name)
        if not isinstance(block, dict):
            raise InvalidAnalysisError("A IA respondeu num formato inesperado. Tente novamente.")
        item = {"score": _score(block.get("score")), "assessment": _text(block.get("assessment")),
                "confidence": _confidence(block.get("confidence"))}
        if item["score"] is None:
            item["confidence"] = "low"  # não avaliável pela foto
        if name == "centering":
            item.update({k: _text(block.get(k), 40) for k in ("front_lr", "front_tb", "back_lr", "back_tb")})
        if name == "corners":
            corners = block.get("corners") if isinstance(block.get("corners"), dict) else {}
            item["corners"] = {k: _text(corners.get(k), 200) for k in CORNERS}
        clean[name] = item

    defects = []
    for raw in data.get("defects") or []:
        if not isinstance(raw, dict):
            continue
        kind = _text(raw.get("type"), 30).lower()
        severity = _text(raw.get("severity"), 10).lower()
        defects.append({
            "type": kind if kind in DEFECT_TYPES else "unknown",
            "location": _text(raw.get("location"), 60),
            "severity": severity if severity in SEVERITIES else "minor",
            "visible": raw.get("visible") is not False,
            "description": _text(raw.get("description"), 300),
        })
    clean["defects"] = defects[:20]

    low, high = parse_range(data["overall"].get("estimated_range"))
    clean["overall"] = {"estimated_range": format_range(low, high),
                        "confidence": _confidence(data["overall"].get("confidence"))}
    clean["summary"] = _text(data.get("summary"), 800)
    return clean


def apply_conservative_rules(analysis: dict) -> dict:
    """Regra conservadora aplicada pelo servidor (não só pedida à IA). Registra os ajustes feitos."""
    overall = analysis["overall"]
    low, high = parse_range(overall["estimated_range"])
    original = overall["estimated_range"]
    notes = []
    scores = [analysis[c]["score"] for c in CRITERIA if analysis[c]["score"] is not None]
    if scores:
        cap = math.floor(min(scores)) + 1  # a faixa não passa do critério mais fraco + 1
        if high > cap:
            high = max(1, min(10, cap))
            low = min(low, high)
            notes.append("O topo da faixa foi limitado pelo critério com a menor nota.")
    if any(analysis[c]["confidence"] == "low" for c in CRITERIA) and overall["confidence"] == "high":
        overall["confidence"] = "medium"
        notes.append("Confiança geral reduzida: algum critério não pôde ser bem avaliado pelas fotos.")
    if low == high and overall["confidence"] != "high" and low > 1:
        low -= 1
        notes.append("Com confiança abaixo de alta, a estimativa é mostrada como faixa.")
    overall["estimated_range"] = format_range(low, high)
    overall["ai_estimated_range"] = original
    analysis["adjustments"] = notes
    return analysis


# ---------- avaliação ----------
def evaluate_card(card: Card, front_image: FileStorage | None, back_image: FileStorage | None) -> CardGradingEvaluation:
    """Avalia a carta pelas fotos da frente e do verso e salva no histórico. Não altera a nota oficial."""
    if not image_service.has_file(front_image) or not image_service.has_file(back_image):
        raise MissingPhotoError(MISSING_PHOTO_MESSAGE)
    with _lock:
        if card.id in _in_progress:
            raise GradingBusyError("Já existe uma avaliação desta carta em andamento. Aguarde o resultado.")
        _in_progress.add(card.id)
    try:
        front = _read(front_image, "front")
        back = _read(back_image, "back")
        parts = [{"text": PROMPT}, {"text": "Image 1: FRONT"}, gemini_service.image_part(*front),
                 {"text": "Image 2: BACK"}, gemini_service.image_part(*back)]
        raw, model = gemini_service.generate_json(parts, thinking="medium", deadline_s=GRADING_DEADLINE,
                                                  timeout_s=GRADING_TIMEOUT_PER_MODEL)
        analysis = validate_analysis(raw)
        if not analysis["photo_quality"]["usable"] or all(analysis[c]["score"] is None for c in CRITERIA):
            raise PhotoQualityError("Não foi possível realizar uma avaliação confiável.", analysis["photo_quality"]["issues"])
        analysis = apply_conservative_rules(analysis)
        evaluation = CardGradingEvaluation(
            card_id=card.id,
            estimated_range=analysis["overall"]["estimated_range"],
            confidence=analysis["overall"]["confidence"],
            centering_score=analysis["centering"]["score"],
            corners_score=analysis["corners"]["score"],
            edges_score=analysis["edges"]["score"],
            surface_score=analysis["surface"]["score"],
            analysis_json=json.dumps(analysis, ensure_ascii=False),
            model=model,
            official_grade_at_time=f"{card.grading_company} {card.official_grade}" if card.official_grade else None,
        )
        db.session.add(evaluation)
        db.session.commit()
        logger.info("Avaliação %s do card %s: faixa %s (%s)", evaluation.id, card.id, evaluation.estimated_range, model)
        return evaluation
    finally:
        with _lock:
            _in_progress.discard(card.id)


def get_evaluation(card: Card, evaluation_id: int) -> CardGradingEvaluation | None:
    evaluation = db.session.get(CardGradingEvaluation, evaluation_id)
    return evaluation if evaluation and evaluation.card_id == card.id else None


def delete_evaluation(evaluation: CardGradingEvaluation) -> None:
    db.session.delete(evaluation)
    db.session.commit()
