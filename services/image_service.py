"""Armazenamento seguro das imagens das cartas em static/images/cards/."""
import io
import uuid
from pathlib import Path

from flask import current_app, url_for
from werkzeug.datastructures import FileStorage

# Assinatura (primeiros bytes) de cada formato aceito: não confiamos só na extensão do arquivo.
_SIGNATURES = {
    "jpg": lambda h: h.startswith(b"\xff\xd8\xff"),
    "png": lambda h: h.startswith(b"\x89PNG\r\n\x1a\n"),
    "webp": lambda h: h[:4] == b"RIFF" and h[8:12] == b"WEBP",
}


class ImageError(ValueError):
    """Imagem recusada (formato, conteúdo ou tamanho)."""


_MIME_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def has_file(file: FileStorage | None) -> bool:
    return bool(file and file.filename)


def detect_type(data: bytes) -> str | None:
    """Formato pelo conteúdo (assinatura), não pelo nome. Ex.: 'jpg'."""
    return next((ext for ext, check in _SIGNATURES.items() if check(data[:16])), None)


def read_for_analysis(file: FileStorage) -> tuple[bytes, str]:
    """Lê a imagem em memória (sem salvar) para enviar ao reconhecimento. Devolve (bytes, mime)."""
    max_bytes = current_app.config["MAX_IMAGE_MB"] * 1024 * 1024
    data = file.stream.read(max_bytes + 1)
    if not data:
        raise ImageError("Envie a foto da carta.")
    if len(data) > max_bytes:
        raise ImageError(f"Imagem grande demais. O limite é {current_app.config['MAX_IMAGE_MB']} MB.")
    kind = detect_type(data)
    if kind is None:
        raise ImageError("O arquivo não é uma imagem válida. Envie JPG, PNG ou WEBP.")
    return data, _MIME_TYPES[kind]


def enhance_for_display(data: bytes, box=None, max_height: int = 900) -> bytes:
    """Versão "vitrine" da foto, só em memória: recorta a carta (caixa da IA), endireita a orientação
    e realça cor, contraste e nitidez. Devolve WEBP; nada é salvo."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    with Image.open(io.BytesIO(data)) as source:
        img = ImageOps.exif_transpose(source).convert("RGB")
    crop = _crop_box(box, img.width, img.height)
    if crop:
        img = img.crop(crop)
    if img.height > max_height:
        img = img.resize((round(img.width * max_height / img.height), max_height), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Color(img).enhance(1.12)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=85)
    return out.getvalue()


def _crop_box(box, width: int, height: int) -> tuple[int, int, int, int] | None:
    """[ymin, xmin, ymax, xmax] normalizado 0–1000 (formato do Gemini) → caixa em pixels, com 2% de folga.
    Caixas inválidas ou pequenas demais (leitura errada da IA) são ignoradas: fica a foto inteira."""
    try:
        ymin, xmin, ymax, xmax = (max(0.0, min(1000.0, float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    if ymax - ymin < 200 or xmax - xmin < 150:
        return None
    pad = 20
    left, top = (xmin - pad) * width / 1000, (ymin - pad) * height / 1000
    right, bottom = (xmax + pad) * width / 1000, (ymax + pad) * height / 1000
    return max(0, round(left)), max(0, round(top)), min(width, round(right)), min(height, round(bottom))


def _extension(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return "jpg" if ext == "jpeg" else ext


def save_image(file: FileStorage) -> str:
    """Valida e grava a imagem com nome único. Devolve o caminho relativo a static/."""
    config = current_app.config
    allowed = ", ".join(sorted(e.upper() for e in config["ALLOWED_IMAGE_EXTENSIONS"]))
    ext = _extension(file.filename or "")
    if ext not in _SIGNATURES or ext not in {_extension(f"x.{e}") for e in config["ALLOWED_IMAGE_EXTENSIONS"]}:
        raise ImageError(f"Formato não aceito. Envie {allowed}.")

    stream = file.stream
    header = stream.read(16)
    if not _SIGNATURES[ext](header):
        raise ImageError("O arquivo não é uma imagem válida (o conteúdo não confere com a extensão).")
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if size > config["MAX_IMAGE_MB"] * 1024 * 1024:
        raise ImageError(f"Imagem grande demais. O limite é {config['MAX_IMAGE_MB']} MB.")
    if size == 0:
        raise ImageError("O arquivo de imagem está vazio.")

    folder = Path(config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"  # nome gerado: seguro e sem colisão
    file.save(folder / name)
    return f"{config['UPLOAD_URL_PREFIX']}/{name}"


def delete_image(relative_path: str | None) -> None:
    """Remove a imagem, só se ela estiver dentro da pasta de uploads."""
    if not relative_path:
        return
    folder = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    target = (folder / Path(relative_path).name).resolve()
    if target.parent == folder and target.is_file():
        target.unlink()


def image_url(relative_path: str | None) -> str | None:
    return url_for("static", filename=relative_path) if relative_path else None
