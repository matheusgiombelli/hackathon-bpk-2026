# CONTEXT.md — Biopark Hackathon 2026 · Desafio 5

Estado atual do projeto, o que foi feito, e o que falta para a demo funcionar.

---

## O QUE É ESSE PROJETO

Bot conversacional no Microsoft Teams que permite aos usuários consultar e interagir com tickets Jira em linguagem natural. O usuário manda mensagem no Teams, o bot interpreta a intenção via LLM, consulta o Jira com as permissões corretas, e responde de forma formatada.

**Projetos Jira de teste:** `SPF01` (HACKATHON 01) e `ELIO` (HACKATHON 02)

---

## STACK

| Componente | Tecnologia |
|---|---|
| Linguagem | Python 3.12 |
| API server | FastAPI + uvicorn |
| Bot SDK | Microsoft Bot Framework SDK (`botbuilder-core`) |
| NLU / Tool calling | Pydantic AI 0.4.3 |
| LLM | OpenRouter (padrão: `anthropic/claude-3-haiku`) |
| HTTP client Jira | `httpx` (async, timeout, retry via `tenacity`) |
| Cache | `cachetools.TTLCache` (em memória, sem banco) |
| Logging | `structlog` (JSON estruturado) |
| Tunnel dev→Teams | Cloudflare Tunnel (`cloudflared`) |

---

## ARQUITETURA (7 CAMADAS)

```
Teams → Cloudflare Tunnel → POST /api/messages (FastAPI)
   │
   ├─ [1] src/adapters/teams.py      Extrai user_id, email, texto. Gera correlation_id.
   │                                  Verifica confirmação pendente ANTES do NLU.
   │
   ├─ [2] src/identity/resolver.py   teams_email → jira_account_id
   │                                  Ordem: TTLCache → user_mapping.json → Jira API
   │
   ├─ [3] src/nlu/agent.py           Pydantic AI roda o LLM com 5 tools definidas.
   │       src/nlu/tools.py          O LLM só escolhe a tool e os parâmetros.
   │                                  jira_account_id é INJETADO via RunContext — LLM nunca vê.
   │
   ├─ [4] src/rules/authorization.py usuario_pode_ver() / usuario_pode_comentar()
   │                                  Código puro, sem LLM, testável, sem rede.
   │
   ├─ [5] src/jira/client.py         Jira REST API v3 via httpx.
   │                                  Timeout 10s, retry 3x backoff, circuit breaker.
   │                                  JQL construído parametricamente (sem concatenação).
   │
   ├─ [6] src/formatting/responses.py Markdown leve para Teams. Determinístico.
   │
   └─ [7] src/observability/          structlog JSON + correlation_id via contextvars.
```

**Princípio central:** O LLM nunca decide permissão, nunca inventa chave de ticket, nunca escolhe qual usuário consultar. Ele só lê a mensagem e chama a tool certa com os parâmetros certos.

---

## FLUXO DE CONFIRMAÇÃO (comentários)

Comentar em ticket é destrutivo. O fluxo é:

1. Usuário: `"Comente no CARM-145: aguardando fornecedor"`
2. NLU chama tool `comentar_ticket` → tool valida permissão → salva no `conv_cache` → retorna pedido de confirmação
3. Bot responde: `"Confirma o comentário X no CARM-145? Responda sim ou não."`
4. Usuário: `"sim"` → adapter intercepta ANTES do NLU → executa comentário via Jira → limpa cache
5. Usuário: `"não"` → adapter limpa cache → responde "Ação cancelada."

---

## 5 TOOLS DO LLM

| Tool | O que faz | Parâmetros LLM |
|---|---|---|
| `listar_tickets` | Lista tickets do usuário | `status`, `projeto`, `atrasados`, `limite` |
| `detalhar_ticket` | Detalhes de um ticket | `chave` (ex: CARM-145) |
| `comentar_ticket` | Solicita confirmação de comentário | `chave`, `texto` |
| `pedir_esclarecimento` | Pede mais info ao usuário | `motivo`, `sugestoes` |
| `comando_fora_de_escopo` | Informa que não pode ajudar | `motivo` |

`jira_account_id` não é parâmetro de nenhuma tool — injetado via `RunContext[Deps]`.

---

## ESTADO DOS TESTES

```
17/17 passando — pytest tests/ -v
```

Cobrem: autorização (pode_ver, pode_comentar, is_overdue), resolução de identidade (cache, case insensitive, miss).
Não cobrem (falta): tools com mock do Jira client, fluxo de confirmação end-to-end.

---

## ARQUIVOS IMPORTANTES

```
.env.example          → template de credenciais (copiar para .env e preencher)
data/user_mapping.json → mapeamento teams_email → jira_account_id (PRECISA ATUALIZAR)
src/config.py          → todos os parâmetros configuráveis
src/nlu/tools.py       → lógica das 5 tools (onde mais bugs podem aparecer)
src/adapters/teams.py  → orquestração principal, fluxo de confirmação
src/jira/client.py     → toda integração com Jira REST API v3
```

---

## PARA RODAR AGORA

```bash
# 1. Credenciais (OBRIGATÓRIO antes de qualquer teste real)
cp .env.example .env
# Edite .env com:
#   JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN
#   OPENROUTER_API_KEY, OPENROUTER_MODEL

# 2. Mapeamento de usuários (OBRIGATÓRIO para permissões funcionarem)
# Edite data/user_mapping.json com os emails reais da equipe → jira account_ids
# Para achar o account_id: GET https://DOMINIO.atlassian.net/rest/api/3/myself

# 3. Subir servidor
uvicorn src.main:app --reload --port 8000

# 4. Testar (Bot Framework Emulator)
# Baixar: https://github.com/microsoft/BotFramework-Emulator/releases
# Abrir bot: http://localhost:8000/api/messages (sem app id / password)
# Obs: no emulator, o "from.name" vira o email. Adicionar "User" no user_mapping.json
#      OU deixar MICROSOFT_APP_ID vazio (modo stub já está ativo automaticamente).

# 5. Rodar testes
pytest tests/ -v
```

---

## O QUE FALTA PARA A DEMO

### Bloqueadores absolutos (sem isso não funciona)

- [ ] **Preencher `.env`** com credenciais reais (Jira + OpenRouter)
- [ ] **Atualizar `data/user_mapping.json`** com os emails e account_ids reais dos usuários de teste
- [ ] **Testar no emulator** com mensagens reais contra o Jira de teste

### Para conectar no Teams real

- [ ] Criar Azure Bot Registration (gratuito, só para registrar — backend roda local)
- [ ] Rodar `cloudflared tunnel --url http://localhost:8000` para gerar URL pública
- [ ] Configurar o URL gerado como messaging endpoint no Azure Bot Registration
- [ ] Configurar `MICROSOFT_APP_ID` e `MICROSOFT_APP_PASSWORD` no `.env`

### Melhorias desejáveis para a apresentação

- [ ] Testar edge cases: ticket inexistente, usuário sem permissão, Jira fora do ar
- [ ] Adicionar filtro por prioridade na tool `listar_tickets` (atualmente só status/projeto/atrasados)
- [ ] Melhorar mensagem de boas-vindas com exemplos dos projetos SPF01 e ELIO
- [ ] Testes da camada NLU com mock do Jira client (sem rede)
- [ ] Testes do fluxo de confirmação de comentário

### Diferenciais do hackathon (se sobrar tempo)

- [ ] Resumo diário automático no Teams (pendências do dia)
- [ ] Filtro por prazo: "tickets vencendo esta semana"
- [ ] Painel simples: `/stats` mostra volume de tickets por status

---

## DECISÕES TOMADAS (para não discutir de novo)

| Tema | Decisão | Razão |
|---|---|---|
| Banco de dados | Nenhum | TTLCache em memória é suficiente, sem overhead |
| Auth Teams | Bot Framework SDK | Oficial, Azure AD valida email automaticamente |
| LLM provider | OpenRouter | Acesso a qualquer modelo, chave única, barato |
| Tool calling | Pydantic AI | Validação de schema automática, DI via RunContext |
| Formato resposta | Texto + markdown leve | Adaptive Cards descartados (complexidade demais para hackathon) |
| Persistência usuários | JSON versionado | Simples, sem infraestrutura, suficiente para demo |
| Confirmação comentários | Regex antes do NLU | Determinístico, não passa pelo LLM |

---

## VARIÁVEIS DE AMBIENTE

| Variável | Obrigatório | Default | Descrição |
|---|---|---|---|
| `JIRA_URL` | SIM | — | `https://DOMINIO.atlassian.net` |
| `JIRA_EMAIL` | SIM | — | Email da conta de serviço Jira |
| `JIRA_API_TOKEN` | SIM | — | Token gerado em id.atlassian.com |
| `OPENROUTER_API_KEY` | SIM | — | Chave OpenRouter |
| `OPENROUTER_MODEL` | não | `anthropic/claude-3-haiku` | Modelo LLM |
| `MICROSOFT_APP_ID` | não* | vazio | Vazio = modo emulator local |
| `MICROSOFT_APP_PASSWORD` | não* | vazio | Vazio = modo emulator local |
| `TICKET_LIST_LIMIT` | não | `10` | Máx tickets por listagem |
| `CONVERSATION_CACHE_TTL` | não | `300` | Segundos para expirar confirmação pendente |
| `JIRA_CACHE_TTL` | não | `60` | Segundos de cache nas respostas Jira |

*Obrigatório para Teams real. Para emulator local, deixar vazio.

---

## COMO O LLM É USADO (e o que ele NÃO faz)

**Faz:**
- Lê a mensagem do usuário
- Decide qual das 5 tools chamar
- Extrai parâmetros da mensagem (status, chave do ticket, texto do comentário)
- Pede esclarecimento quando ambíguo

**NÃO faz:**
- Não decide se o usuário tem permissão
- Não inventa chaves de ticket
- Não sabe qual usuário está logado (só vê a mensagem)
- Não acessa o Jira diretamente
- Não formata a resposta final (a tool já retorna o texto formatado)
