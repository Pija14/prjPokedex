"""Define (ou troca) o usuário e a senha do CardDex no arquivo .env.

Uso:  python scripts/set_password.py
A senha é pedida sem aparecer na tela e só o hash (scrypt) é gravado.
Também cria um SECRET_KEY aleatório se ainda não houver um.
"""
import getpass
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from werkzeug.security import generate_password_hash  # noqa: E402

ENV_FILE = ROOT / ".env"
MIN_LENGTH = 8


def set_env_value(text: str, key: str, value: str) -> str:
    line = f"{key}='{value}'"  # aspas simples: o '$' do hash não é interpretado
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text)
    return text.rstrip("\n") + ("\n" if text.strip() else "") + line + "\n"


def current_value(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
    return match.group(1).strip().strip("'\"") if match else ""


def main() -> int:
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    default_user = current_value(text, "ADMIN_USERNAME") or "admin"
    username = (input(f"Usuário [{default_user}]: ").strip() or default_user).lower()
    if not re.fullmatch(r"[a-z0-9._@-]{3,60}", username):
        print("Usuário inválido: use 3 a 60 letras, números, ponto, hífen, @ ou _.")
        return 1
    password = getpass.getpass(f"Nova senha (mínimo {MIN_LENGTH} caracteres): ")
    if len(password) < MIN_LENGTH:
        print(f"Senha curta demais: use pelo menos {MIN_LENGTH} caracteres.")
        return 1
    if getpass.getpass("Repita a senha: ") != password:
        print("As senhas não conferem.")
        return 1

    text = set_env_value(text, "ADMIN_USERNAME", username)
    text = set_env_value(text, "ADMIN_PASSWORD_HASH", generate_password_hash(password))
    secret = current_value(text, "SECRET_KEY")
    if len(secret) < 32 or secret.startswith("troque"):
        text = set_env_value(text, "SECRET_KEY", secrets.token_hex(32))
    ENV_FILE.write_text(text, encoding="utf-8")
    print(f"Pronto: usuário '{username}' gravado em {ENV_FILE.name}. Reinicie o CardDex para valer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
