# Bot Teams + Jira — Arquitetura e Decisões Técnicas

Documento consolidado das decisões tomadas para o desafio de construção do assistente conversacional integrado ao Microsoft Teams para gestão de tickets do Jira.

---

## 1. Visão Geral

### Objetivo

Construir um assistente conversacional no Microsoft Teams que permita aos usuários consultar, acompanhar e interagir com tickets do Jira em linguagem natural, com:

- Consulta de tickets vinculados ao próprio usuário (pendentes, em andamento, atrasados).
- Resumo de status e pendências.
- Registro de comentários em tickets autorizados.
- Controle estrito de permissões (usuário só acessa o que lhe pertence).

### Filosofia da Solução

O ponto central da arquitetura é **isolar regras de negócio do LLM**. O modelo de linguagem atua exclusivamente como classificador de intenção e extrator de parâmetros. Tudo que envolve decisão de negócio, autorização, montagem de chamadas à API e validação acontece em código determinístico.

Princípios fundamentais:

- **O LLM nunca decide endpoint, nunca inventa chave de ticket, nunca decide se o usuário tem permissão.**
- A identidade do usuário é resolvida uma vez por requisição, propagada via contexto, e nunca trafega pelo LLM.
- Operações destrutivas (comentários) exigem confirmação explícita.
- Toda autorização é checada em código testável, isolado, sem dependência de IA.

---

## 2. Arquitetura em Sete Camadas

O fluxo de uma requisição atravessa sete camadas bem definidas, da borda para o núcleo.

### Camada 1 — Adaptador Teams

Microsoft Bot Framework SDK recebe a mensagem. Extrai três informações e nada mais:

- `teams_user_id`
- `teams_user_email`
- `texto_mensagem`

Nenhuma lógica de negócio mora aqui. O Bot Framework garante autenticação via Azure AD, então o email do usuário chega confiável — não vem do conteúdo da mensagem, e portanto não é manipulável pelo próprio usuário via texto.

### Camada 2 — Resolução de Identidade

Mapeia `teams_user_email` para `jira_account_id`.

- Lookup inicial em arquivo de mapeamento estático (JSON).
- Fallback dinâmico via Jira API (busca por email).
- Cache em memória após primeira resolução.
- Se não houver correspondente Jira, o fluxo para aqui com mensagem clara.

A partir desta camada, qualquer operação carrega o `jira_account_id` resolvido. **Esse valor nunca mais é influenciado pelo LLM.** É o ponto onde se ancora toda a segurança subsequente: a partir daqui, qualquer chamada usa o `account_id` resolvido, jamais um valor vindo do modelo.

### Camada 3 — NLU (Tool Calling)

O LLM recebe o texto da mensagem e a lista de ferramentas disponíveis. O prompt do sistema é explícito em três pontos:

1. Você só pode escolher uma das ferramentas disponíveis.
2. Nunca invente chaves de ticket, projetos ou usuários.
3. Se o pedido for ambíguo, chame a ferramenta `pedir_esclarecimento`.

**Ferramentas definidas:**

- `listar_tickets(status?, projeto?, atrasados?, limite?)`
- `detalhar_ticket(chave)`
- `comentar_ticket(chave, texto)`
- `pedir_esclarecimento(motivo, sugestoes?)`
- `comando_fora_de_escopo(motivo)`

O `jira_account_id` **não** é parâmetro de nenhuma ferramenta. É injetado pela camada de execução via contexto. Essa omissão é deliberada: o LLM não tem como influenciar qual usuário será consultado.

### Camada 4 — Validação e Autorização

Recebe a ferramenta escolhida e os argumentos. Executa em ordem:

1. Validação de schema (Pydantic).
2. Validação semântica (o ticket existe?).
3. Autorização (o ticket está vinculado ao usuário identificado na Camada 2?).

Duas funções centralizadas e testáveis:

- `usuario_pode_ver(account_id, ticket)`
- `usuario_pode_comentar(account_id, ticket)`

Toda operação obrigatoriamente passa por uma delas. Vínculo considera responsável, reporter ou outras regras definidas — mas tudo em código, nunca em prompt.

### Camada 5 — Integração Jira

Cliente HTTP da Jira REST API v3 com qualidades não negociáveis:

- Timeout explícito (5 a 10 segundos).
- Retry com backoff exponencial em 5xx e 429.
- Circuit breaker para evitar martelar a API indisponível.
- Logging de cada chamada com `correlation_id`.
- JQL parametrizado por código a partir de argumentos validados (nunca concatenação de strings).

Sobre JQL parametrizado: o princípio é análogo ao de prevenção de SQL injection. A linguagem JQL aceita injeção semelhante quando montada por concatenação. Para `listar_tickets`, a query final fica próxima de `assignee = currentUser() AND status != Done`, mas construída programaticamente a partir dos parâmetros já validados pelo schema.

### Camada 6 — Formatação de Resposta

Texto simples com markdown leve, montado deterministicamente a partir dos dados retornados. O Teams renderiza `**negrito**`, listas e código inline sem custo extra. A resposta apresenta a chave do ticket sempre que aplicável (rastreabilidade).

A formatação é determinística por padrão. Caso se queira humanizar mais a resposta no futuro, é possível passar os dados já obtidos para o LLM com instrução estrita de apenas reorganizar, jamais inventar campos. Adaptive Cards do Teams foram considerados como alternativa (permitem botões de ação direta, como "comentar neste ticket") e ficam visualmente melhores, mas foram descartados para o escopo inicial por aumentarem a complexidade de renderização e o tempo de implementação. Podem ser adotados em uma evolução posterior.

### Camada 7 — Observabilidade

Log estruturado em JSON com `correlation_id` por interação, atravessando todas as camadas via `contextvars`. Saída para arquivo com rotação. Cobre tanto necessidade de depuração quanto o requisito de rastreabilidade do anexo, e serve como base para um eventual painel de uso (citado como diferencial possível).

---

## 3. Stack Técnico Consolidado

| Componente | Escolha |
|------------|---------|
| Linguagem | Python |
| Framework de Tool Calling | Pydantic AI |
| Provedor LLM | OpenRouter (modelos open-source gratuitos) |
| Bot SDK | Microsoft Bot Framework SDK (`botbuilder-core`, `botbuilder-schema`) |
| Ambiente de desenvolvimento | Bot Framework Emulator (local) |
| Túnel para Teams real | cloudflared (Cloudflare Tunnel) |
| Cliente HTTP Jira | `httpx` (async, retry, timeout nativos) |
| Cache (memória) | `cachetools.TTLCache` |
| Persistência estática | Arquivo JSON versionado |
| Logging | `structlog` |
| Formato de resposta | Texto + markdown leve |

---

## 4. Decisões Detalhadas

### 4.1 Framework de Tool Calling — Pydantic AI

**Motivos da escolha:**

- Validação automática via Pydantic. Se o LLM enviar campo errado ou tipo incorreto, falha na borda antes de tocar no Jira.
- Agnóstico de provedor: muda Anthropic, OpenAI, Gemini, Ollama, OpenRouter mudando uma string.
- API enxuta. Decoradores `@agent.tool` em funções Python normais. Sem cadeias, sem LCEL, sem grafos.
- Suporte a dependências injetadas via `RunContext`, exatamente onde o `jira_account_id` resolvido e o cliente Jira são injetados sem o LLM enxergar.
- Boa testabilidade com modo de teste e modelos mock.

**Pontos de atenção:**

- Biblioteca relativamente nova (lançada fim de 2024). Comunidade menor que LangChain, mas documentação oficial é boa.

### 4.2 Provedor LLM — OpenRouter

**Motivos:**

- Acesso unificado a praticamente qualquer modelo via API compatível com OpenAI.
- Permite experimentar modelos diferentes durante o desenvolvimento sem trocar código.
- Custo baixo, paga por uso.
- Possibilidade de usar modelos open-source gratuitos hospedados na própria plataforma.

**Estratégia:**

Começar com modelo open-source gratuito disponível no OpenRouter (avaliar disponibilidade na hora). Se a qualidade de tool calling não for suficiente, mover para um modelo pago barato e bom em tool calling.

### 4.3 Ambiente de Execução — Bot Framework Emulator + Cloudflared

**Desenvolvimento:**

Bot Framework Emulator local. Zero infraestrutura, zero rede externa. O anexo do desafio permite explicitamente demo simulada.

**Para Teams real (demo final, se aplicável):**

Cloudflare Tunnel (`cloudflared`). Vantagens sobre alternativas:

- URL estável quando configurado com tunnel nomeado.
- Gratuito sem limite prático de requisições.
- Roda como serviço de fundo.

### 4.4 Persistência de Dados

Estratégia em três níveis:

**Arquivo JSON estático (versionado no Git):**

- Mapeamento de usuários de teste (`teams_email` → `jira_account_id`).
- Configuração de regras de permissão (se necessário customizar).

**Memória do processo (`cachetools.TTLCache`):**

- Cache de identidade resolvida.
- Estado conversacional temporário.
- Cache de respostas Jira.

**Sem persistência externa:**

- Dados do Jira (tickets, projetos, usuários) — fonte da verdade é a própria API.
- Sem Redis, sem SQLite, sem Postgres.

Redis foi considerado para cache distribuído de identidade e respostas, mas descartado para o escopo atual: a aplicação roda em um único processo, o ganho de durabilidade não compensa a infraestrutura adicional, e o `cachetools.TTLCache` resolve todos os casos de uso identificados. Pode ser introduzido posteriormente se a aplicação for horizontalizada.

### 4.5 Estado Conversacional Temporário

**Implementação:**

- Biblioteca: `cachetools.TTLCache` em memória.
- Chave: `teams_conversation_id`.
- Valor: objeto com `pending_action`, `pending_args`, `created_at`.
- TTL: 2 a 5 minutos.
- Limpeza: automática pela própria `TTLCache`.

**Fluxo de uso:**

1. Usuário envia "comente no CARM-145: aguardando retorno do fornecedor".
2. NLU classifica como `comentar_ticket`, extrai argumentos.
3. Em vez de executar direto, o bot salva no cache e responde "Confirma o comentário X no ticket CARM-145?".
4. Usuário responde "sim".
5. Bot busca no cache pelo `conversation_id`, encontra a ação pendente, executa.
6. Bot remove do cache após execução (ou deixa expirar).

Se o usuário demorar mais que o TTL para confirmar, o cache expira e o bot responde "Não há ação pendente para confirmar, pode repetir o pedido?".

### 4.6 Cache da Jira API

**Implementação:**

- Biblioteca: `cachetools.TTLCache` (instância separada do cache conversacional).
- Chave: hash dos parâmetros relevantes da consulta + identidade do usuário.
- TTL: 30 a 60 segundos.
- Escopo: apenas leituras (GET). Comentários e mutações nunca passam por cache.
- Invalidação opcional: se o usuário comenta em um ticket, invalida cache daquele ticket.

### 4.7 Formato de Resposta

Texto simples com markdown leve. O Teams renderiza `**negrito**`, listas e código inline. Resposta sempre apresenta a chave do ticket para rastreabilidade.

Exemplo de resposta esperada:

```
VLB1-112 - Arquitetônico Villa Bella 1 - aguardando aprovação há 5 dias
CARM-145 - Hidrossanitário Carmel - atraso de 3 dias
TI-201 - Book Comercial Verona I - sem atualização
```

Limite de resultados por listagem (sugestão: 10 tickets). Se houver mais, o bot resume os principais e informa que existem outros itens disponíveis.

### 4.8 Logging

**Biblioteca:** `structlog`.

**Configuração mínima:**

- Saída única para arquivo JSON com rotação (`RotatingFileHandler` ou `TimedRotatingFileHandler`).
- Stdout colorido em desenvolvimento (opcional).
- Cadeia de processadores: `merge_contextvars`, sanitização de campos sensíveis (`token`, `authorization`), `add_log_level`, `TimeStamper` ISO 8601, formatação de exceções, `JSONRenderer`.

**Propagação de contexto:**

Na entrada da requisição (Camada 1), gera-se um `correlation_id` (UUID) e faz-se `bind_contextvars(correlation_id=..., user_email=...)`. Daí em diante, todo log produzido naquele contexto async carrega esses campos automaticamente via `contextvars`. Funciona corretamente através de fronteiras async (Bot Framework e httpx são async).

**Eventos registrados por camada:**

- Camada 1: `message_received` com `teams_user_email`, `teams_conversation_id`, `text_length`, `correlation_id`.
- Camada 2: `identity_resolved` ou `identity_unresolved`.
- Camada 3: `intent_classified` com `tool_chosen`, `arguments` (sanitizados), `llm_latency_ms`, `model_used`, `tokens_used`.
- Camada 4: `authorization_check` com `tool`, `ticket_key`, `result` (allowed/denied), `reason`.
- Camada 5: `jira_request` com `endpoint`, `method`, `latency_ms`, `status_code`, `cache_hit`.
- Camada 6: `response_sent` com `length`, `total_latency_ms`.
- Erros: `error` com `stage`, `exception_type`, `message`, stack trace.

Eventos adicionais:

- `startup` e `shutdown` da aplicação, com versão, configuração resolvida (sem segredos), provedor LLM ativo.
- `config_loaded` com hash da configuração.
- `rate_limit_hit` quando Jira API ou LLM retornar 429.

**Princípio:** nunca logar credenciais, tokens, ou conteúdo sensível. Sanitização ocorre no primeiro processador da cadeia, garantindo proteção uniforme.

---

## 5. Pontos Críticos de Robustez

Decisões que separam um protótipo de algo que aguenta uso real.

### 5.1 Identidade Fixada por Requisição

Tudo que envolve "qual usuário" é resolvido uma vez na Camada 2 e propagado por contexto (injeção de dependência via `RunContext` do Pydantic AI). Nunca passa pelo LLM. Elimina por design a classe de bug "modelo inventou que o usuário é outro".

### 5.2 Confirmação Explícita para Operações Destrutivas

Comentar em ticket é destrutivo: fica registrado e notifica gente. Primeira vez que o usuário pede comentário, o bot retorna confirmação ("Você confirma o comentário X no ticket Y?") e só executa após "sim". Protege contra interpretação errada de intenção pelo LLM e atende ao requisito do anexo sobre tratamento de comandos ambíguos.

### 5.3 Idempotência em Comentários

Hash do conteúdo + chave do ticket + usuário + janela de tempo curta (1 minuto). Segunda requisição com mesmo hash retorna sucesso sem registrar novamente. Evita comentário duplicado em caso de retry de rede.

### 5.4 Limites de Quantidade

Listagens limitadas (sugestão: 10 tickets). Informa quando há mais. Razões: legibilidade no Teams e custo de tokens caso resultados passem pelo LLM para reformatação.

### 5.5 Credenciais

Variáveis de ambiente, nunca em código (requisito do anexo sobre tratamento de credenciais). Para Jira, OAuth 2.0 (3LO) em produção, ou API token + email com permissões mínimas no ambiente de teste. Tokens OpenRouter também em env.

### 5.6 Fallback Gracioso

- Jira API fora: "estou sem acesso ao Jira no momento, tente em alguns minutos".
- LLM falha: "não consegui entender, pode reformular?".
- Nenhuma stack trace para o usuário.

### 5.7 Testes da Camada de Autorização

Camada 4 (autorização) tem teste unitário obrigatório. Função pura, sem LLM, sem rede. Cenários:

- Usuário tenta ver ticket de outro.
- Usuário tenta comentar em ticket que não é dele.
- Ticket inexistente.
- Casos válidos (responsável, reporter, regras customizadas).

Este é o piso de segurança do sistema.

### 5.8 JQL Parametrizado

JQL nunca é montada por concatenação de strings. Parâmetros validados pelo schema, montagem por código com escape adequado. Princípio análogo ao de SQL injection — JQL aceita injeção semelhante quando construída de forma ingênua.

---

## 6. Definição Detalhada das Ferramentas (Tools)

Estrutura sugerida usando Pydantic AI. O `jira_account_id` é injetado via `RunContext`, nunca aparece como parâmetro.

### `listar_tickets`

**Parâmetros:**

- `status` (opcional): `pendente`, `em_andamento`, `concluido`, ou lista.
- `projeto` (opcional): sigla do projeto (ex: `CARM`, `SPF01`, `ELIO`).
- `atrasados` (opcional, bool): filtra apenas tickets com atraso.
- `limite` (opcional, int): teto de resultados (default 10).

**Comportamento:**

Monta JQL com `assignee = currentUser()` (ou equivalente para o `jira_account_id` injetado), aplica filtros adicionais, executa via Camada 5.

### `detalhar_ticket`

**Parâmetros:**

- `chave` (obrigatório): chave do ticket (ex: `CARM-145`).

**Comportamento:**

Valida existência. Valida autorização via `usuario_pode_ver`. Retorna detalhes.

### `comentar_ticket`

**Parâmetros:**

- `chave` (obrigatório): chave do ticket.
- `texto` (obrigatório): conteúdo do comentário.

**Comportamento:**

Não executa imediatamente. Salva como ação pendente no cache conversacional. Retorna pedido de confirmação ao usuário.

### `pedir_esclarecimento`

**Parâmetros:**

- `motivo` (obrigatório): razão pela qual o pedido foi ambíguo.
- `sugestoes` (opcional, lista): possíveis interpretações para o usuário escolher.

**Comportamento:**

Retorna ao usuário texto pedindo esclarecimento. Não toca no Jira.

### `comando_fora_de_escopo`

**Parâmetros:**

- `motivo` (obrigatório): por que o pedido está fora do escopo.

**Comportamento:**

Retorna mensagem explicando o que o bot consegue fazer. Não toca no Jira.

---

## 7. Estrutura de Diretórios Sugerida (Esboço)

Esboço inicial, sujeito a refinamento na próxima etapa:

```
projeto/
├── src/
│   ├── adapters/
│   │   └── teams.py            # Camada 1
│   ├── identity/
│   │   └── resolver.py         # Camada 2
│   ├── nlu/
│   │   ├── agent.py            # Camada 3 (Pydantic AI)
│   │   └── tools.py            # Definição das ferramentas
│   ├── rules/
│   │   └── authorization.py    # Camada 4
│   ├── jira/
│   │   └── client.py           # Camada 5
│   ├── formatting/
│   │   └── responses.py        # Camada 6
│   ├── observability/
│   │   └── logging_config.py   # Camada 7
│   ├── cache/
│   │   ├── conversational.py
│   │   └── jira_cache.py
│   └── config.py
├── data/
│   └── user_mapping.json       # Mapeamento Teams → Jira
├── tests/
│   ├── test_authorization.py
│   ├── test_identity.py
│   └── ...
├── .env.example
├── requirements.txt
└── README.md
```

---

## 8. Pendências e Próximos Passos

Pontos ainda não totalmente decididos ou aprofundados:

1. **Estrutura de pastas finalizada** com convenções de import e organização interna de cada módulo.
2. **Estratégia de testes detalhada**: o que mockar, fixtures para Jira API, mocks do LLM.
3. **Simulação de múltiplos usuários no Bot Framework Emulator** para demonstrar regras de permissão sem precisar de várias contas Teams reais.
4. **Plano de demo**: roteiro de cenários cobrindo todos os pontos do anexo, garantindo apresentação fluida.
5. **Definição de qual modelo open-source no OpenRouter usar** após avaliação prática de qualidade de tool calling.
6. **Configuração de retry e circuit breaker** na Camada 5 (parâmetros concretos).
7. **Avaliação posterior de Adaptive Cards** como evolução da Camada 6, caso o escopo permita.
8. **Eventual divisão de tarefas no time**.

---

## 9. Resumo Executivo das Decisões

| Tema | Decisão |
|------|---------|
| Filosofia | LLM apenas como NLU; regras de negócio em código determinístico |
| Linguagem | Python |
| Tool calling | Pydantic AI |
| Provedor LLM | OpenRouter (modelos open-source gratuitos) |
| Bot SDK | Microsoft Bot Framework SDK |
| Dev | Bot Framework Emulator local |
| Demo Teams real | Cloudflared |
| HTTP client | httpx |
| Cache | cachetools.TTLCache (em memória) |
| Persistência estática | JSON versionado |
| Sem banco de dados | Sem Redis, SQLite, Postgres |
| Logging | structlog em JSON com rotação de arquivo |
| Formato de resposta | Texto + markdown leve (Adaptive Cards considerado para evolução futura) |
| Confirmação | Obrigatória para operações destrutivas (comentários) |
| Identidade | Resolvida uma vez, injetada via contexto, nunca via LLM |
| TTL estado conversacional | 2 a 5 minutos |
| TTL cache Jira | 30 a 60 segundos |
| Credenciais | Variáveis de ambiente |
