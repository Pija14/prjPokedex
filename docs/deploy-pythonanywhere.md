# Publicar o CardDex no PythonAnywhere (plano gratuito)

Resultado: o CardDex fica em **https://SEU-USUARIO.pythonanywhere.com**, com HTTPS, acessível pelo celular de qualquer lugar (4G ou Wi-Fi), protegido por **usuário e senha**. Leva uns 15 minutos.

> Nos comandos abaixo, troque `SEU-USUARIO` pelo seu nome de usuário do PythonAnywhere.

## 1. Criar a conta

1. Acesse https://www.pythonanywhere.com/registration/register/beginner/ e crie uma conta **Beginner** (gratuita).
2. O nome de usuário vira o endereço do site (`SEU-USUARIO.pythonanywhere.com`) — escolha com calma.

## 2. Baixar o código do GitHub

1. No painel, abra **Consoles → Bash**.
2. Rode:

```bash
git clone https://github.com/Pija14/prjPokedex.git
cd prjPokedex
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configurar o `.env` (segredos ficam só no servidor)

Ainda no console Bash, dentro de `prjPokedex`:

```bash
cp .env.example .env
nano .env
```

No editor, deixe assim (as outras linhas podem ficar como estão):

```text
APP_ENV=production
GEMINI_API_KEY=cole-aqui-a-sua-chave-do-gemini
```

Salve com **Ctrl+O**, **Enter** e saia com **Ctrl+X**. Depois crie o usuário e a senha de acesso:

```bash
python scripts/set_password.py
```

O script pergunta o usuário e a senha (mínimo 8 caracteres; a senha não aparece enquanto você digita), grava só o **hash** no `.env` e cria um `SECRET_KEY` aleatório. Para trocar a senha no futuro, rode o mesmo comando e recarregue o site (passo 5).

## 4. Criar o site

1. Abra a aba **Web → Add a new web app → Next**.
2. Escolha **Manual configuration** (não "Flask") → **Python 3.11** → **Next**.
3. Na página do site, preencha:
   - **Source code:** `/home/SEU-USUARIO/prjPokedex`
   - **Working directory:** `/home/SEU-USUARIO/prjPokedex`
   - **Virtualenv:** `/home/SEU-USUARIO/prjPokedex/.venv`
4. Em **Code**, clique no link do **WSGI configuration file** (`/var/www/SEU-USUARIO_pythonanywhere_com_wsgi.py`), **apague todo o conteúdo** e cole:

```python
import sys

path = "/home/SEU-USUARIO/prjPokedex"
if path not in sys.path:
    sys.path.insert(0, path)

from wsgi import application  # noqa: E402,F401
```

   Clique em **Save**.
5. Em **Static files**, adicione (deixa as imagens e o CSS mais rápidos):
   - **URL:** `/static/` → **Directory:** `/home/SEU-USUARIO/prjPokedex/static/`
6. Em **Security**, ligue **Force HTTPS**.

## 5. Ligar

1. No topo da aba **Web**, clique em **Reload SEU-USUARIO.pythonanywhere.com**.
2. Abra **https://SEU-USUARIO.pythonanywhere.com** no celular e entre com o usuário e a senha.

O banco (`data/carddex.db`) é criado sozinho no primeiro acesso.

## Atualizar depois de novas versões

```bash
cd ~/prjPokedex
git pull
source .venv/bin/activate
pip install -r requirements.txt
```

Depois, **Reload** na aba Web. O `.env`, o banco e as fotos não são afetados pelo `git pull` (estão fora do git).

## Se algo der errado

- **"Something went wrong" / erro 500:** aba **Web → Log files → Error log**. A mensagem `CardDex em produção sem configuração de segurança` indica que falta rodar `python scripts/set_password.py` (passo 3).
- **A IA não responde:** confira `GEMINI_API_KEY` no `.env` e o Error log. No plano gratuito o PythonAnywhere só libera alguns sites; o Gemini (`*.googleapis.com`) está na lista liberada.
- **Esqueci a senha:** rode `python scripts/set_password.py` no console e dê Reload.

## Limites do plano gratuito

- **Renovar a cada 3 meses:** o PythonAnywhere pede para clicar em **"Run until 3 months from today"** na aba Web; se esquecer, o site é pausado (os dados continuam lá).
- **Espaço:** 512 MB no total (código + banco + fotos). Uma foto de carta tem de 200 KB a 3 MB.
- **Backup:** baixe as pastas `data/` e `static/images/cards/` pela aba **Files** de tempos em tempos.
