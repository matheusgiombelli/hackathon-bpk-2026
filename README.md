# Bot Teams + Jira — Biopark Hackathon 2026

Assistente conversacional no Microsoft Teams para gestão de tickets Jira :D

## Arquitetura

```
Teams → Cloudflare Tunnel → FastAPI /api/messages
  └─ Layer 1: Teams Adapter (Bot Framework SDK)
  └─ Layer 2: Identity Resolution (Teams email → Jira account_id)
  └─ Layer 3: NLU via Pydantic AI + OpenRouter
  └─ Layer 4: Authorization (usuario_pode_ver / usuario_pode_comentar)
  └─ Layer 5: Jira Client (httpx + retry + circuit breaker)
  └─ Layer 6: Response Formatting
  └─ Layer 7: Structured Logging (structlog)
```

## Setup

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Edite .env com suas credenciais
```

Campos obrigatórios:
- `JIRA_URL` — ex: `https://biopark.atlassian.net`
- `JIRA_EMAIL` — seu email Jira
- `JIRA_API_TOKEN` — gere em https://id.atlassian.com/manage-profile/security/api-tokens
- `OPENROUTER_API_KEY` — gere em https://openrouter.ai/keys
- `OPENROUTER_MODEL` — padrão: `anthropic/claude-3-haiku`

Para rodar **localmente com o Bot Framework Emulator**, deixe `MICROSOFT_APP_ID` e `MICROSOFT_APP_PASSWORD` vazios.

### 3. Configurar mapeamento de usuários

Edite `data/user_mapping.json` com os emails Teams → account_id Jira da sua equipe.

Para encontrar o `jira_account_id` de um usuário:
```
GET https://SEU-DOMINIO.atlassian.net/rest/api/3/user/search?query=email@empresa.com
```

### 4. Rodar o servidor

```bash
uvicorn src.main:app --reload --port 8000
```

### 5. Testar localmente (Bot Framework Emulator)

1. Baixe o [Bot Framework Emulator](https://github.com/microsoft/BotFramework-Emulator/releases)
2. Abra: "Open Bot" → URL: `http://localhost:8000/api/messages`
3. Deixe App ID e Password em branco
4. Envie: _"Quais meus tickets estão atrasados?"_

> No emulator o `from.name` é usado como email. Adicione um usuário com `teams_email = "User"` no `user_mapping.json` ou habilite o modo stub (app_id vazio já ativa automaticamente).

### 6. Expor via Cloudflare Tunnel (Teams real)

```bash
cloudflared tunnel --url http://localhost:8000
```

Configure o URL gerado como messaging endpoint no Azure Bot Registration.

## Testes

```bash
pytest tests/ -v
```

## Comandos de exemplo

| Mensagem | Ação |
|----------|------|
| `Quais meus tickets pendentes?` | Lista tickets com status pendente |
| `Tenho algo atrasado no CARM?` | Lista tickets atrasados no projeto Carmel |
| `Detalha o CARM-145` | Mostra detalhes do ticket |
| `Comente no CARM-145: aguardando retorno` | Pede confirmação e registra comentário |
| `sim` | Confirma ação pendente |
| `não` | Cancela ação pendente |

## Estrutura

```
src/
├── main.py                  # FastAPI entrypoint
├── config.py                # Settings via .env
├── adapters/teams.py        # Layer 1 — Bot Framework adapter
├── identity/resolver.py     # Layer 2 — Teams → Jira identity
├── nlu/agent.py             # Layer 3 — Pydantic AI agent
├── nlu/tools.py             # Layer 3 — Tool definitions (5 tools)
├── rules/authorization.py   # Layer 4 — Permission checks
├── jira/client.py           # Layer 5 — Jira REST API (retry + circuit breaker)
├── jira/models.py           # Pydantic models
├── formatting/responses.py  # Layer 6 — Response formatting
├── observability/           # Layer 7 — structlog JSON
└── cache/                   # TTLCache: conversation state + Jira responses

data/user_mapping.json       # Teams email → Jira account_id
tests/                       # Unit tests (auth + identity, no LLM/network)
```
