"""Armazenamento seguro das imagens das cartas em static/images/cards/."""
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


def has_file(file: FileStorage | None) -> bool:
    return bool(file and file.filename)


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
