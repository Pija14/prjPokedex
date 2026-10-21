# CardDex

**CardDex** é uma aplicação web para gerenciar a sua coleção pessoal de cartas **Pokémon TCG** — inspirada no conceito de uma Pokédex, mas para cartas.

## Objetivo

Cadastrar as cartas da coleção (com foto), encontrar qualquer uma em segundos e saber quanto a coleção vale.

A visão final do produto:

```text
📷 Foto  →  🤖 Gemini identifica a carta  →  🔎 consulta de preço  →  👤 você confirma  →  💾 salvo no CardDex
```

**Nesta primeira etapa** o cadastro é **manual**. A arquitetura já está preparada para o reconhecimento por imagem (ver [Preparado para o Gemini](#preparado-para-o-gemini)).

## Tecnologias

- **Backend:** Python 3.10+ · Flask · SQLAlchemy (via Flask-SQLAlchemy) · SQLite
- **Frontend:** HTML (templates Jinja) · CSS · JavaScript puro — sem frameworks
- **Testes:** pytest

## Estrutura do projeto

```text
prjPokedex/
├── app.py                  # cria o app (create_app), registra rotas e sobe o servidor
├── config.py               # configuração (caminhos, limites de upload, variáveis de ambiente)
├── requirements.txt        # dependências da aplicação
├── requirements-dev.txt    # + pytest
├── .env.example            # modelo de variáveis de ambiente (copie para .env)
├── database/
│   ├── database.py         # instância do SQLAlchemy e criação automática do banco
│   └── models.py           # modelo Card (tabela cards)
├── routes/
│   ├── pages.py            # páginas HTML (Home, Coleção, Adicionar, Detalhes, Editar, Excluir)
│   └── cards.py            # API REST JSON (/api/cards)
├── services/
│   ├── card_service.py     # regras de negócio: validação, preço, busca, filtros, resumo
│   ├── image_service.py    # upload seguro das imagens
│   └── gemini_service.py   # contrato do reconhecimento por imagem (ainda não implementado)
├── templates/              # base.html, index.html, cards.html, card_form.html, card_detail.html, partials/, errors/
├── static/
│   ├── css/style.css       # identidade visual (mobile-first)
│   ├── js/app.js           # busca/filtro instantâneos, prévia da imagem, confirmação de exclusão
│   └── images/             # logo.svg e cards/ (uploads das cartas)
├── data/                   # carddex.db é criado aqui na primeira execução
└── tests/                  # testes do serviço e da API
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

# 4. (Opcional) copie as variáveis de ambiente
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

### Testes

```bash
pip install -r requirements-dev.txt
pytest
```

## Funcionalidades atuais

- **Home** com resumo da coleção (cards cadastrados, valor total, número de coleções e últimos adicionados).
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

## Preparado para o Gemini

`services/gemini_service.py` já define o contrato:

```python
identify_card(image_path) -> CardIdentification   # pokemon_name, collection_name, card_number, rarity, language, confidence, extra
```

e `CardIdentification.as_prefill()` devolve os dados no formato aceito por `card_service.form_defaults(prefill=...)`, que é quem preenche o formulário. O fluxo da próxima etapa será:

```text
foto → image_service salva → gemini_service.identify_card → formulário preenchido → você confirma → card_service salva
```

A chave fica **só no servidor**, na variável `GEMINI_API_KEY` do `.env` (nunca no navegador nem no git).

## Funcionalidades futuras

Reconhecimento automático da carta pela foto (Gemini), consulta automática de preço, histórico de preços, dashboard da coleção, wishlist e PWA (instalar no celular).

## Roadmap

```text
[x] Estrutura inicial
[x] Banco SQLite
[x] Cadastro manual
[x] Upload de imagem
[x] Minha coleção
[x] Detalhes do card
[ ] Integração Gemini
[ ] Reconhecimento automático do card
[ ] Consulta automática de preço
[ ] Histórico de preços
[ ] Dashboard da coleção
[ ] Wishlist
[ ] PWA
```

## Avisos

- O servidor do Flask (`python app.py`) é de **desenvolvimento**, para uso local. Não há autenticação: qualquer pessoa na sua rede Wi-Fi que souber o endereço consegue acessar.
- CardDex é um projeto pessoal, sem vínculo com The Pokémon Company, Nintendo, Creatures ou Game Freak. Nenhuma marca, logo ou arte oficial é usada na interface.
