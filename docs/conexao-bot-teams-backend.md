# Integração Microsoft Teams ↔ Backend Local (FastAPI) via Cloudflare Tunnel

## Visão Geral

Esta documentação descreve como funciona a arquitetura de comunicação entre o Microsoft Teams e o backend local do projeto durante o desenvolvimento do hackathon.

O objetivo da solução é permitir que o Microsoft Teams envie mensagens para um bot executado localmente na máquina dos desenvolvedores, utilizando um túnel seguro da Cloudflare para expor temporariamente o backend FastAPI na internet.

A aplicação não depende de hospedagem no Azure para execução do backend. O Azure/Microsoft será utilizado apenas para registro e habilitação do bot dentro do ecossistema do Teams.

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
Bot Framework SDK / teams.py
        ↓
Core Orchestrator
        ├── NLU / LLM
        ├── Jira Service
        ├── Permission Service
        ├── Formatter
        └── Logger
        ↓
Jira Cloud REST API v3
```

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
* exibir respostas do backend;
* renderizar Adaptive Cards.

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

O FastAPI será o núcleo da aplicação.

Responsabilidades:

* receber eventos do Teams;
* autenticar e processar mensagens;
* chamar serviços internos;
* integrar com Jira;
* comunicar com o LLM;
* aplicar regras de negócio;
* formatar respostas.

---

# Estrutura do Projeto

```text
app/
├── main.py
├── config.py
│
├── adapters/
│   ├── botframework_adapter.py
│   └── teams_py_adapter.py
│
├── core/
│   ├── orchestrator.py
│   ├── nlu_service.py
│   ├── jira_service.py
│   ├── permission_service.py
│   ├── formatter.py
│   └── logger.py
│
├── models/
│   ├── intent.py
│   ├── ticket.py
│   └── user_context.py
│
└── db/
    ├── database.py
    └── repositories.py
```

---

# Estratégia Multi-SDK

O projeto utilizará:

* Bot Framework SDK
* teams.py

Ambos funcionarão como adapters de entrada.

A lógica de negócio permanecerá centralizada no `core/`.

Arquitetura:

```text
Bot Framework SDK ─┐
                   ├── Core Orchestrator
teams.py          ─┘
```

Benefícios:

* desacoplamento;
* facilidade de manutenção;
* comparação entre SDKs;
* possibilidade de migração futura;
* reutilização total da lógica de negócio.

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

## 4. Adapter recebe a mensagem

O adapter:

* extrai dados do Teams;
* identifica usuário;
* envia conteúdo ao orchestrator.

---

## 5. Orchestrator processa a solicitação

Fluxo interno:

```text
Mensagem
   ↓
NLU / LLM
   ↓
Intent + parâmetros
   ↓
Permission Service
   ↓
Jira Service
   ↓
Formatter
   ↓
Resposta
```

---

## 6. Resposta retorna ao Teams

O usuário recebe:

* texto simples;
* cards;
* status;
* confirmações;
* erros;
* alertas de permissão.

---

# Identificação do Usuário

O Teams fornece informações do usuário autenticado.

Campo principal:

```json
from.aadObjectId
```

Este identificador será associado ao usuário do Jira.

Fluxo:

```text
Teams User ID
        ↓
Mapeamento interno
        ↓
E-mail Jira
```

---

# Controle de Permissões

O LLM NÃO possui acesso direto ao Jira.

O backend sempre valida permissões antes de qualquer operação.

Fluxo correto:

```text
LLM interpreta
        ↓
Backend valida
        ↓
Jira executa
```

Princípio adotado:

> O LLM sugere a ação. O backend autoriza a execução.

---

# Comunicação com o LLM

O LLM será utilizado apenas para:

* interpretação de intenção;
* extração de parâmetros;
* tratamento de linguagem natural;
* resolução de ambiguidades.

Exemplo:

Entrada:

```text
"Tenho algo atrasado no Carmel?"
```

Saída esperada:

```json
{
  "intent": "list_overdue",
  "project": "CARMEL"
}
```

---

# Estratégia de Tool Calling

O backend executará as ações reais.

Exemplo:

```python
jira_service.search_tickets(
    user_email=user.email,
    project="CARMEL",
    overdue=True
)
```

---

# Estratégia de Contexto Multiusuário

O contexto conversacional NÃO ficará no LLM.

Ele será mantido no backend.

Estrutura:

```python
ConversationContext
├── teams_user_id
├── jira_email
├── current_project
├── last_ticket
├── pending_action
└── conversation_history
```

Cada usuário possuirá contexto isolado.

---

# Desenvolvimento Local

## Inicializar FastAPI

```bash
uvicorn app.main:app --reload --port 8000
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

Endpoint final:

```text
https://my-bot.trycloudflare.com/api/messages
```

---

# Vantagens da Arquitetura

## Desenvolvimento rápido

Sem necessidade de deploy contínuo.

---

## Baixo custo

Backend totalmente local.

---

## Segurança

Cloudflare fornece HTTPS seguro automaticamente.

---

## Arquitetura enterprise

Mesmo localmente, a estrutura segue padrões reais de integração corporativa.

---

## Escalabilidade futura

A arquitetura permite:

* migrar para Azure;
* migrar para Kubernetes;
* adicionar novos canais;
* adicionar múltiplos LLMs;
* separar microserviços futuramente.

---

# Decisão Arquitetural Final

A arquitetura oficial do projeto será:

* Backend Python com FastAPI;
* Execução local durante desenvolvimento;
* Exposição segura via Cloudflare Tunnel;
* Integração Microsoft Teams via Bot Registration;
* Uso simultâneo de Bot Framework SDK e teams.py;
* LLM utilizado apenas como camada NLU;
* Permissões e regras mantidas no backend;
* Jira Cloud REST API v3 como fonte oficial de dados.

---

# Próximos Passos

## Infraestrutura

* [ ] Configurar FastAPI
* [ ] Configurar Cloudflare Tunnel
* [ ] Criar Bot Registration
* [ ] Configurar endpoint `/api/messages`

## Backend

* [ ] Implementar adapters
* [ ] Criar orchestrator
* [ ] Integrar Jira API
* [ ] Criar Permission Service

## IA

* [ ] Implementar NLU
* [ ] Implementar tool calling
* [ ] Implementar contexto multiusuário

## Teams

* [ ] Configurar manifesto
* [ ] Configurar escopos
* [ ] Testar mensagens
* [ ] Implementar Adaptive Cards
