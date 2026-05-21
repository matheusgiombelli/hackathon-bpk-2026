# Integração Microsoft Teams ↔ Backend Local (FastAPI) via Cloudflare Tunnel

## Visão Geral

Esta documentação descreve como funciona a arquitetura de comunicação entre o Microsoft Teams e o backend local do projeto durante o desenvolvimento do hackathon.

O objetivo da solução é permitir que o Microsoft Teams envie mensagens para um bot executado localmente na máquina dos desenvolvedores, utilizando um túnel seguro da Cloudflare para expor temporariamente o backend FastAPI na internet.

A aplicação não depende de hospedagem no Azure para execução do backend. O Azure/Microsoft será utilizado apenas para registro e habilitação do bot dentro do ecossistema do Teams.

Este documento é complementar ao `architecture.md`, que descreve a arquitetura interna do bot em sete camadas. Aqui o foco está na camada de transporte e conectividade — como uma mensagem do Teams chega até o código que vai processá-la.

---

# Arquitetura Geral

```text
Microsoft Teams
        ↓
Microsoft Bot Registration
        ↓
Cloudflare Tunnel (HTTPS público)
        ↓
FastAPI local (localhost:8000)
        ↓
Bot Framework SDK (Camada 1 — Adaptador Teams)
        ↓
Resolução de Identidade (Camada 2)
        ↓
NLU via Pydantic AI (Camada 3)
        ↓
Validação e Autorização (Camada 4)
        ↓
Cliente Jira (Camada 5)
        ↓
Formatação (Camada 6)
        ↓
Observabilidade transversal (Camada 7)
        ↓
Jira Cloud REST API v3
```

A nomenclatura por camadas segue o que está definido em `architecture.md`.

---

# Objetivo da Arquitetura

A proposta desta arquitetura é:

* permitir desenvolvimento totalmente local;
* evitar custos com hospedagem durante o hackathon;
* integrar com Microsoft Teams real;
* manter uma arquitetura próxima de ambiente corporativo;
* facilitar debugging e iteração rápida;
* desacoplar completamente a lógica de negócio do canal Teams.

---

# Papel de Cada Camada

## Microsoft Teams

Interface conversacional utilizada pelos usuários finais.

Responsável por:

* receber mensagens do usuário;
* enviar eventos ao bot;
* exibir respostas do backend.

O formato de resposta é texto com markdown leve, conforme definido em `architecture.md`. Adaptive Cards foram considerados e ficaram como evolução futura, fora do escopo inicial.

---

## Microsoft Bot Registration

O ecossistema Microsoft exige que o bot seja registrado para funcionar dentro do Teams.

Nesta arquitetura:

* o Azure NÃO hospeda o backend;
* o Azure apenas registra o bot;
* o Teams utiliza este registro para localizar o endpoint público do bot.

O endpoint configurado será o endereço HTTPS gerado pelo Cloudflare Tunnel.

Exemplo:

```text
https://example.trycloudflare.com/api/messages
```

---

## Cloudflare Tunnel

O Cloudflare Tunnel expõe o backend local na internet de forma segura.

Funções:

* criar URL HTTPS pública;
* encaminhar requisições para localhost;
* evitar necessidade de deploy;
* eliminar necessidade de abrir portas manualmente;
* permitir comunicação do Teams com a máquina local.

Fluxo:

```text
Teams → Cloudflare → localhost:8000
```

---

## Backend FastAPI

O FastAPI hospeda o endpoint que recebe os eventos do Teams. Ele atua como camada HTTP fina; a lógica do bot é executada pelo Bot Framework SDK e pelos módulos das sete camadas internas.

Responsabilidades:

* expor o endpoint `/api/messages`;
* repassar o `Activity` recebido ao `BotFrameworkAdapter`;
* gerenciar ciclo de vida da aplicação (startup, shutdown, configuração);
* expor health check e endpoints auxiliares de operação, se necessário.

Nenhuma regra de negócio mora no FastAPI. Ele é apenas o transporte HTTP que recebe a requisição do Teams (via Cloudflare) e entrega ao SDK do bot.

---

# Estrutura do Projeto

A estrutura segue o esboço definido em `architecture.md`, organizada por camadas. A pasta `adapters/` da Camada 1 é onde o FastAPI e o Bot Framework SDK se encontram.

```text
projeto/
├── src/
│   ├── main.py                     # entrypoint FastAPI
│   ├── config.py
│   │
│   ├── adapters/
│   │   └── teams.py                # Camada 1 — Bot Framework SDK + endpoint FastAPI
│   │
│   ├── identity/
│   │   └── resolver.py             # Camada 2
│   │
│   ├── nlu/
│   │   ├── agent.py                # Camada 3 — Pydantic AI
│   │   └── tools.py                # Definição das ferramentas
│   │
│   ├── rules/
│   │   └── authorization.py        # Camada 4
│   │
│   ├── jira/
│   │   └── client.py               # Camada 5
│   │
│   ├── formatting/
│   │   └── responses.py            # Camada 6
│   │
│   ├── observability/
│   │   └── logging_config.py       # Camada 7
│   │
│   └── cache/
│       ├── conversational.py
│       └── jira_cache.py
│
├── data/
│   └── user_mapping.json           # Mapeamento Teams → Jira
│
├── tests/
│   ├── test_authorization.py
│   ├── test_identity.py
│   └── ...
│
├── .env.example
├── requirements.txt
└── README.md
```

Não há pasta `db/`: o projeto não usa banco de dados (sem Redis, sem SQLite, sem Postgres). Estado conversacional e cache vivem em memória via `cachetools.TTLCache`, conforme `architecture.md`.

---

# SDK Único — Bot Framework

O projeto utilizará apenas o Microsoft Bot Framework SDK como adaptador de entrada do Teams.

Alternativas (como `teams.py`) foram avaliadas e descartadas para o escopo do hackathon: manter dois SDKs em paralelo multiplica complexidade sem benefício direto ao desafio. O Bot Framework SDK é maduro, oficial, e suficiente para todos os cenários previstos.

A lógica de negócio permanece centralizada nos módulos das camadas 2 a 7. Caso futuramente se queira avaliar outro SDK, basta criar um novo adapter em `src/adapters/` sem tocar nas camadas internas.

---

# Fluxo de Comunicação

## 1. Usuário envia mensagem

Exemplo:

```text
"Quais tickets estão atrasados?"
```

---

## 2. Teams envia evento ao bot

O Teams envia um payload HTTP para:

```text
POST /api/messages
```

---

## 3. Cloudflare Tunnel encaminha a requisição

```text
https://xxxxx.trycloudflare.com
        ↓
http://localhost:8000
```

---

## 4. Adapter recebe a mensagem (Camada 1)

O adapter:

* recebe o `Activity` via Bot Framework SDK;
* extrai `teams_user_id`, `teams_user_email`, `texto_mensagem`;
* gera `correlation_id` para a interação;
* repassa para a Camada 2.

---

## 5. Camadas internas processam a solicitação

Fluxo interno (resumido — detalhes em `architecture.md`):

```text
Mensagem
   ↓
Resolução de identidade (Camada 2)
   ↓
NLU via Pydantic AI (Camada 3) → intent + parâmetros
   ↓
Validação e autorização (Camada 4)
   ↓
Cliente Jira (Camada 5)
   ↓
Formatação (Camada 6)
   ↓
Resposta
```

---

## 6. Resposta retorna ao Teams

O usuário recebe:

* texto com markdown leve;
* confirmações para operações destrutivas;
* mensagens de erro ou alertas de permissão amigáveis.

---

# Identificação do Usuário

O Teams fornece informações do usuário autenticado pelo Azure AD.

Campo principal:

```json
from.aadObjectId
```

Combinado com o email do usuário (também disponível no `Activity`), este identificador é mapeado para o `jira_account_id` na Camada 2.

Fluxo:

```text
Teams User (aadObjectId + email)
        ↓
Mapeamento (data/user_mapping.json + fallback Jira API)
        ↓
jira_account_id
```

A partir daí o `jira_account_id` é fixado para o restante da requisição e nunca passa pelo LLM.

---

# Controle de Permissões

O LLM NÃO possui acesso direto ao Jira.

O backend sempre valida permissões antes de qualquer operação, via funções centralizadas na Camada 4 (`usuario_pode_ver`, `usuario_pode_comentar`).

Fluxo:

```text
LLM interpreta intenção e extrai parâmetros (Camada 3)
        ↓
Backend valida schema, existência e autorização (Camada 4)
        ↓
Jira executa (Camada 5)
```

Princípio adotado:

> O LLM sugere a ação. O backend autoriza a execução.

---

# Comunicação com o LLM

O LLM é utilizado apenas para:

* interpretação de intenção;
* extração de parâmetros;
* tratamento de linguagem natural;
* resolução de ambiguidades (via ferramenta `pedir_esclarecimento`).

Exemplo:

Entrada:

```text
"Tenho algo atrasado no Carmel?"
```

Saída esperada (escolha de ferramenta + argumentos):

```json
{
  "tool": "listar_tickets",
  "arguments": {
    "projeto": "CARM",
    "atrasados": true
  }
}
```

O `jira_account_id` não aparece nos argumentos: é injetado pela execução via `RunContext` do Pydantic AI.

---

# Estratégia de Tool Calling

Tool calling é implementado com **Pydantic AI**. Cada ferramenta é uma função Python decorada com `@agent.tool`, com schema validado por Pydantic. As ferramentas estão definidas em `src/nlu/tools.py` e descritas em detalhe na seção 6 de `architecture.md`:

* `listar_tickets`
* `detalhar_ticket`
* `comentar_ticket`
* `pedir_esclarecimento`
* `comando_fora_de_escopo`

A execução real chama o cliente Jira da Camada 5:

```python
@agent.tool
async def listar_tickets(
    ctx: RunContext[Deps],
    status: str | None = None,
    projeto: str | None = None,
    atrasados: bool = False,
    limite: int = 10,
) -> list[Ticket]:
    return await ctx.deps.jira.search_tickets(
        account_id=ctx.deps.account_id,   # injetado, não vem do LLM
        status=status,
        projeto=projeto,
        atrasados=atrasados,
        limite=limite,
    )
```

---

# Estratégia de Contexto Multiusuário

O contexto conversacional fica no backend, em memória, via `cachetools.TTLCache`. Não há persistência em banco.

Estrutura por conversa (chave = `teams_conversation_id`):

```python
ConversationContext
├── teams_user_id
├── jira_account_id
├── pending_action          # ferramenta aguardando confirmação
├── pending_args            # argumentos da ação pendente
└── created_at
```

Características:

* TTL de 2 a 5 minutos;
* limpeza automática pela própria `TTLCache`;
* cada usuário/conversa possui contexto isolado por chave;
* **não armazena histórico longo de mensagens** — o bot é stateless por design, exceto pela ação pendente aguardando confirmação.

Caso futuramente se queira histórico conversacional persistente, será necessário introduzir um backend de armazenamento (decisão que envolve revisão da seção 4.4 de `architecture.md`).

---

# Desenvolvimento Local

## Inicializar FastAPI

```bash
uvicorn src.main:app --reload --port 8000
```

---

## Inicializar Cloudflare Tunnel

```bash
cloudflared tunnel --url http://localhost:8000
```

---

## URL pública gerada

Exemplo:

```text
https://my-bot.trycloudflare.com
```

Endpoint final configurado no Bot Registration:

```text
https://my-bot.trycloudflare.com/api/messages
```

Para túneis nomeados (URL estável entre execuções), configurar via `cloudflared tunnel create <nome>` e arquivo de configuração — recomendado para a demo final.

---

# Vantagens da Arquitetura

## Desenvolvimento rápido

Sem necessidade de deploy contínuo.

## Baixo custo

Backend totalmente local.

## Segurança

Cloudflare fornece HTTPS seguro automaticamente.

## Arquitetura enterprise

Mesmo localmente, a estrutura segue padrões reais de integração corporativa.

## Escalabilidade futura

A arquitetura permite:

* migrar para Azure App Service ou Container Apps;
* migrar para Kubernetes;
* adicionar novos canais (Slack, WhatsApp) criando novos adapters em `src/adapters/`;
* trocar o provedor LLM mudando configuração do Pydantic AI;
* introduzir persistência (Redis, banco) caso o cenário exija.

---

# Decisão Arquitetural Final

A arquitetura oficial do projeto será:

* Backend Python com FastAPI hospedando o endpoint do bot;
* Execução local durante desenvolvimento;
* Exposição segura via Cloudflare Tunnel;
* Integração Microsoft Teams via Bot Registration (Azure apenas para registro, não para hospedagem);
* Microsoft Bot Framework SDK como único adapter de entrada;
* Pydantic AI como framework de tool calling;
* LLM utilizado apenas como camada NLU;
* Permissões e regras mantidas no backend, em código testável;
* Estado conversacional em `cachetools.TTLCache`, sem banco de dados;
* Resposta em texto com markdown leve (Adaptive Cards como evolução futura);
* Jira Cloud REST API v3 como fonte oficial de dados.

---

# Próximos Passos

## Infraestrutura

* [ ] Configurar FastAPI com endpoint `/api/messages`
* [ ] Configurar Cloudflare Tunnel (avaliar tunnel nomeado para a demo)
* [ ] Criar Bot Registration no Azure
* [ ] Configurar variáveis de ambiente (`.env.example` → `.env`)

## Backend

* [ ] Implementar adapter do Bot Framework (Camada 1)
* [ ] Implementar resolução de identidade (Camada 2)
* [ ] Implementar Permission Service (Camada 4)
* [ ] Implementar cliente Jira com timeout, retry e circuit breaker (Camada 5)
* [ ] Implementar formatação de respostas (Camada 6)
* [ ] Configurar `structlog` com propagação de `correlation_id` (Camada 7)

## IA

* [ ] Configurar Pydantic AI com OpenRouter
* [ ] Implementar as cinco ferramentas (`listar_tickets`, `detalhar_ticket`, `comentar_ticket`, `pedir_esclarecimento`, `comando_fora_de_escopo`)
* [ ] Implementar fluxo de confirmação para `comentar_ticket`

## Teams

* [ ] Configurar manifesto do bot
* [ ] Configurar escopos
* [ ] Testar mensagens via Bot Framework Emulator (desenvolvimento)
* [ ] Testar mensagens via Teams real (demo)
