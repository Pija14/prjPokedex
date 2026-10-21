# CardDex

**CardDex** é uma aplicação web para gerenciar a sua coleção pessoal de cartas **Pokémon TCG** — inspirada no conceito de uma Pokédex, mas para cartas.

## Objetivo

Cadastrar as cartas da coleção (com foto), encontrar qualquer uma em segundos e saber quanto a coleção vale.

A visão final do produto:

```text
📷 Foto  →  🤖 Gemini identifica a carta  →  🔎 consulta de preço  →  👤 você confirma  →  💾 salvo no CardDex
```

Hoje a foto já é **reconhecida pelo Gemini** e preenche o formulário; a **consulta de preço** ainda é manual (ver [Reconhecimento pela foto](#reconhecimento-pela-foto-gemini)).

## Tecnologias

- **Backend:** Python 3.10+ · Flask · SQLAlchemy (via Flask-SQLAlchemy) · SQLite
- **Frontend:** HTML (templates Jinja) · CSS · JavaScript puro — sem frameworks
- **Testes:** pytest

## Estrutura do projeto

```text
prjPokedex/
├── app.py                  # cria o app (create_app), registra rotas, login/CSRF e sobe o servidor
├── wsgi.py                 # entrada para servidores de produção (PythonAnywhere)
├── config.py               # configuração (caminhos, limites de upload, variáveis de ambiente)
├── requirements.txt        # dependências da aplicação
├── requirements-dev.txt    # + pytest
├── .env.example            # modelo de variáveis de ambiente (copie para .env)
├── database/
│   ├── database.py         # instância do SQLAlchemy e criação automática do banco
│   └── models.py           # modelo Card (tabela cards)
├── routes/
│   ├── auth.py             # entrar / sair
│   ├── pages.py            # páginas HTML (Home, Coleção, Adicionar, Detalhes, Editar, Excluir)
│   └── cards.py            # API REST JSON (/api/cards)
├── services/
│   ├── card_service.py     # regras de negócio: validação, preço, busca, filtros, resumo
│   ├── image_service.py    # upload seguro das imagens
│   ├── auth_service.py     # login (senha com hash), limite de tentativas, CSRF
│   └── gemini_service.py   # contrato do reconhecimento por imagem (ainda não implementado)
├── templates/              # base.html, index.html, cards.html, card_form.html, card_detail.html, partials/, errors/
├── static/
│   ├── css/style.css       # identidade visual (mobile-first)
│   ├── js/app.js           # busca/filtro instantâneos, prévia da imagem, confirmação de exclusão
│   └── images/             # logo.svg e cards/ (uploads das cartas)
├── data/                   # carddex.db é criado aqui na primeira execução
├── scripts/set_password.py # define usuário e senha no .env
├── docs/                   # guia de publicação no PythonAnywhere
└── tests/                  # testes do serviço, da API, da IA e do login
```

**Camadas:** as rotas só recebem a requisição e devolvem a resposta; as regras ficam em `services/`; o acesso a dados em `database/`. As páginas HTML e a API REST chamam os **mesmos** serviços — e os próximos (`gemini_service`, `price_service`, `collection_service`) entram na mesma camada.

## Como instalar e executar

Pré-requisito: **Python 3.10 ou superior** (`python --version`).

```bash
# 1. Na pasta do projeto, crie o ambiente virtual
python -m venv .venv

# 2. Ative o ambiente
.venv\Scripts\activate          # Windows (PowerShell ou CMD)
source .venv/bin/activate       # Linux / macOS

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Copie as variáveis de ambiente e coloque sua GEMINI_API_KEY no .env
#    (sem a chave, o cadastro manual funciona normalmente)
copy .env.example .env          # Windows
cp .env.example .env            # Linux / macOS

# 5. Execute
python app.py
```

Abra **http://localhost:5000**. O banco `data/carddex.db` é criado automaticamente na primeira execução.

### Usar no celular (rede local)

O servidor escuta em `0.0.0.0`, então o celular na **mesma rede Wi-Fi** consegue acessar:

1. Ao iniciar, o terminal mostra o endereço, por exemplo: `No celular (mesma rede Wi-Fi): http://192.168.0.10:5000`. (Também dá para ver o IP com `ipconfig` no Windows — campo "Endereço IPv4".)
2. Abra esse endereço no navegador do celular.
3. Se não abrir no Windows, permita o Python no **Firewall do Windows** (redes privadas) quando ele perguntar, ou libere a porta 5000.

Em "Adicionar Card", o campo de imagem abre a **câmera traseira** do celular.

### Login (usuário e senha)

Para exigir login (obrigatório quando publicado na internet):

```bash
python scripts/set_password.py
```

O script pede usuário e senha e grava no `.env` só o **hash** da senha (scrypt) e um `SECRET_KEY` aleatório. Reinicie o CardDex. Sem usuário/senha configurados, o uso local continua aberto, como antes. A sessão fica salva no aparelho por 30 dias; o menu tem **Sair**.

Proteções: todas as telas e a API exigem login; formulários e chamadas da API com token CSRF; 5 tentativas erradas bloqueiam o IP por 15 minutos; cookie `HttpOnly`, `SameSite=Lax` e `Secure` em produção. Com `APP_ENV=production` o app **não sobe** sem usuário, senha e `SECRET_KEY`, e o modo debug fica sempre desligado.

### Publicar na internet (PythonAnywhere, grátis)

Passo a passo completo em **[docs/deploy-pythonanywhere.md](docs/deploy-pythonanywhere.md)** — o CardDex fica em `https://SEU-USUARIO.pythonanywhere.com`, com HTTPS, acessível pelo celular de qualquer lugar.

### Testes

```bash
pip install -r requirements-dev.txt
pytest
```

## Funcionalidades atuais

- **Home** com resumo da coleção (cards cadastrados, valor total, número de coleções e últimos adicionados).
- **Reconhecimento pela foto (Gemini):** ao escolher a foto em "Adicionar Card", a IA identifica nome, coleção, número, raridade e idioma (e mostra HP, tipo, estágio, edição, ilustrador, código do set e ano). Os campos preenchidos pela IA ficam marcados com **IA**; o que você já digitou não é sobrescrito; você revisa, informa o valor e salva. Na edição, "Identificar com IA" completa só os campos vazios.
- **Adicionar Card** manual: nome do Pokémon, coleção, número, raridade, idioma, valor, data e fonte do valor, imagem.
- **Upload de imagem** (JPG, JPEG, PNG, WEBP; até 8 MB): valida a extensão **e o conteúdo** do arquivo; nome gerado (sem colisão); a imagem antiga é apagada ao trocar ou excluir a carta.
- **Minha Coleção** em cards visuais, com **busca** por nome ou número e **filtros** por coleção e raridade (instantâneos; também funcionam por link, ex.: `/cards?collection=Base%20Set`).
- **Detalhes** com imagem grande e todas as informações; **Editar** e **Excluir** (com confirmação).
- **Valores em reais** guardados como decimal (sem erro de arredondamento); aceita `1.250,00`, `1250,00` ou `1250.00`. Sem data informada, o valor é registrado com a data de hoje.
- **API REST** (JSON):

  | Método | Endpoint | Descrição |
  |---|---|---|
  | GET | `/api/cards?q=&collection=&rarity=` | lista (com filtros opcionais) |
  | GET | `/api/cards/<id>` | uma carta |
  | POST | `/api/cards/identify` | reconhece a carta da foto (`image`, multipart) e devolve os dados — não salva nada |
  | POST | `/api/cards` | cria (JSON ou `multipart/form-data` com `image`) |
  | PUT | `/api/cards/<id>` | altera só os campos enviados (JSON ou multipart; `remove_image=1` remove a imagem) |
  | DELETE | `/api/cards/<id>` | exclui (e apaga a imagem) |

  Erros de validação: `400 {"errors": {"campo": "mensagem"}}`; não encontrado: `404 {"error": "..."}`.

- **Responsivo**, priorizando o celular: header + cards em uma coluna no celular; sidebar e grade de 3–4 colunas no desktop.

## Banco de dados e imagens fora do git

`data/*.db` e `static/images/cards/*` estão no `.gitignore`, por decisão:

- são **dados pessoais** da sua coleção, não código;
- mudam a cada uso — versionar geraria conflitos e um histórico enorme de arquivos binários;
- a **estrutura** do banco não se perde: o código recria as tabelas automaticamente.

**Backup:** copie as pastas `data/` e `static/images/cards/` juntas.

> Observação: as tabelas são criadas automaticamente, mas **alterações** futuras de estrutura (novas colunas) vão pedir migração — quando isso acontecer, entra o Alembic.

## Reconhecimento pela foto (Gemini)

```text
foto → (app reduz para 1600 px só para a análise) → POST /api/cards/identify
     → gemini_service.identify_card → JSON → formulário preenchido → você confirma → card_service salva (com a foto original)
```

- A chave fica **só no servidor**, em `GEMINI_API_KEY` no `.env` (fora do git), e vai no cabeçalho da requisição — nunca na URL nem no navegador. Crie a sua em https://aistudio.google.com/apikey.
- **Plano gratuito:** cada modelo do Gemini tem um limite diário (cerca de 20 pedidos por modelo). O CardDex tenta vários modelos em sequência (`GEMINI_FALLBACK_MODELS`); quando todos esgotam, avisa e você preenche manualmente.
- Respostas típicas em 3 a 7 segundos. Foto que não é uma carta → mensagem clara, sem preencher nada.
- A IA lê o que está impresso; edição/variante (ex.: 1ª Edição) só quando o selo aparece na foto. **Sempre confira** antes de salvar.

## Funcionalidades futuras

Consulta automática de preço, histórico de preços, dashboard da coleção, wishlist e PWA (instalar no celular).

## Roadmap

```text
[x] Estrutura inicial
[x] Banco SQLite
[x] Cadastro manual
[x] Upload de imagem
[x] Minha coleção
[x] Detalhes do card
[x] Integração Gemini
[x] Reconhecimento automático do card
[ ] Consulta automática de preço
[ ] Histórico de preços
[ ] Dashboard da coleção
[ ] Wishlist
[ ] PWA
```

## Avisos

- `python app.py` usa o servidor de **desenvolvimento** do Flask, para uso local. Publicado, o CardDex roda pelo `wsgi.py` (ver guia do PythonAnywhere).
- Sem `ADMIN_USERNAME`/`ADMIN_PASSWORD_HASH` no `.env`, não há login: qualquer pessoa na sua rede Wi-Fi que souber o endereço consegue acessar. Para publicar, configure a senha.
- As imagens das cartas em `/static/images/cards/` têm nomes aleatórios e não exigem login para abrir (o restante, sim).
- CardDex é um projeto pessoal, sem vínculo com The Pokémon Company, Nintendo, Creatures ou Game Freak. Nenhuma marca, logo ou arte oficial é usada na interface.
