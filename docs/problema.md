# Anexo Técnico — Desafio 5: Bot no Teams para Tickets do Jira

Este material complementa o briefing principal do Hackathon Biopark. Ele deve ser usado pelos times que escolherem o desafio de Planejamento e precisarem do detalhamento funcional, regras de negócio, exemplos de interação e orientações técnicas para desenvolver a solução.

> Este anexo não define pesos, pontuação, ranking ou critérios formais de avaliação. Esses pontos ficam a cargo da banca avaliadora.

---

## Objetivo do desafio

Construir um assistente inteligente integrado ao Microsoft Teams que permita aos usuários consultar, acompanhar e interagir com tickets do Jira em linguagem natural.

A solução deve permitir que o usuário:

1. consulte os próprios tickets pendentes, em andamento ou atrasados;
2. receba informações resumidas sobre status e pendências;
3. faça perguntas em linguagem natural;
4. registre comentários em tickets autorizados;
5. visualize e atualize apenas tickets vinculados ao seu usuário.

---

## Contexto do problema

O acompanhamento de tickets no Jira pode exigir consultas frequentes, troca de contexto e navegação manual pela plataforma. Em uma empresa com vários projetos em andamento, isso dificulta a visibilidade de pendências, atrasos e atualizações necessárias.

O desafio propõe aproximar o usuário das informações do Jira por meio do Microsoft Teams, criando uma experiência conversacional mais rápida, simples e controlada por permissões.

---

## Escopo funcional esperado

### 1) Interface no Microsoft Teams

A solução deve funcionar como um bot ou assistente conversacional no Microsoft Teams.

Para fins de hackathon, a integração pode ser:

- funcional no Teams;
- simulada em uma interface equivalente;
- demonstrada por um fluxo que represente claramente entrada do usuário, interpretação do comando e resposta do bot.

### 2) Consulta de tickets

O usuário deve conseguir consultar tickets vinculados a ele.

Exemplos de comandos:

- *Qual status dos meus tickets?*
- *Quais tickets estão atrasados?*
- *Tenho alguma pendência no projeto Carmel?*
- *Liste meus tickets em andamento.*

### 3) Resposta resumida

A resposta do bot deve ser objetiva e fácil de ler no Teams. Ela deve conter, sempre que possível:

- chave do ticket;
- nome resumido da atividade ou entrega;
- empreendimento/projeto, quando aplicável;
- status atual;
- indicação de atraso ou pendência;
- tempo sem atualização, se disponível.

### 4) Comentários em tickets

O usuário deve conseguir solicitar o registro de comentários em tickets específicos.

Exemplo:

> `Comente no CARM-145: aguardando retorno do fornecedor`

A solução deve validar se o usuário tem permissão para comentar no ticket antes de registrar ou simular a atualização.

### 5) Controle de acesso

O bot deve fornecer informações apenas sobre tickets vinculados ao usuário. O vínculo pode considerar:

- usuário como responsável;
- e-mail atribuído ao ticket;
- solicitante;
- gestor do espaço;
- outra regra definida pela empresa para os projetos de teste.

---

## Fonte de dados

A integração deve considerar a documentação oficial da Jira Cloud REST API v3:

<https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/#about>

Para o hackathon, os times podem trabalhar com:

- ambiente Jira de teste;
- projetos reais controlados:
  - **HACKATHON 01** — sigla `SPF01`
  - **HACKATHON 02** — sigla `ELIO`
- base mockada de tickets;
- respostas simuladas da API, desde que o fluxo funcional esteja claro.

---

## Estratégia sugerida da solução

### Etapa 1 — Identificar o usuário

Antes de consultar ou atualizar qualquer ticket, a solução precisa identificar quem está fazendo a solicitação.

**O que resolver nesta etapa:**

- reconhecer o usuário que enviou a mensagem;
- associar o usuário do Teams ao usuário ou e-mail utilizado no Jira;
- armazenar ou simular esse vínculo de forma simples.

**Regra mínima recomendada:** o bot só deve retornar informações de tickets vinculados ao usuário identificado.

### Etapa 2 — Interpretar o comando

A solução deve transformar a mensagem em uma intenção de ação.

Exemplos de intenções:

- listar tickets;
- consultar status;
- filtrar atrasos;
- buscar tickets por projeto;
- adicionar comentário;
- explicar que o comando não foi entendido.

**Sugestão de abordagem:** os participantes podem usar:

- regras simples de palavras-chave;
- expressões regulares;
- modelo de IA para classificação de intenção;
- combinação de IA com validações determinísticas.

### Etapa 3 — Consultar tickets permitidos

Depois de identificar a intenção, a solução deve consultar a base de tickets.

**O que buscar.** A aplicação deve montar uma resposta com dados como:

- chave do ticket;
- resumo;
- projeto;
- responsável;
- status;
- prioridade;
- data de criação;
- data da última atualização;
- indicação de atraso, quando houver regra disponível.

**Cuidados esperados:**

- não retornar tickets de outros usuários sem permissão;
- tratar ticket inexistente;
- tratar ausência de tickets pendentes;
- limitar a quantidade de resultados para manter a resposta legível no Teams.

### Etapa 4 — Responder no Teams

A resposta deve ser curta, organizada e útil para tomada de ação.

**Exemplo de resposta**

> **Usuário:** Qual status dos meus tickets?
>
> **Bot:**
>
> - `VLB1-112` — Arquitetônico Villa Bella 1 — aguardando aprovação há 5 dias
> - `CARM-145` — Hidrossanitário Carmel — atraso de 3 dias
> - `TI-201` — Book Comercial Verona I — sem atualização

**Boa prática:** evitar respostas longas demais. Se houver muitos tickets, o bot pode resumir os principais e informar que existem outros itens disponíveis para consulta.

### Etapa 5 — Registrar comentário

Quando o usuário solicitar um comentário, o bot deve:

1. identificar o ticket;
2. validar se o ticket existe;
3. validar se o usuário tem vínculo/permissão;
4. registrar ou simular o comentário;
5. confirmar a ação ao usuário.

**Exemplo**

> **Usuário:** Comente no CARM-145: aguardando retorno do fornecedor
>
> **Bot:** Comentário registrado no ticket CARM-145.

Se o usuário não tiver permissão:

> **Bot:** Você não possui permissão para atualizar o ticket CARM-145.

---

## Regras de negócio sugeridas

**Regra 1 — Exibir apenas tickets vinculados ao usuário.** O bot não deve permitir que um usuário visualize tickets sem vínculo autorizado.

**Regra 2 — Comentário somente em ticket autorizado.** O usuário só pode comentar ou atualizar tickets nos quais esteja como responsável ou possua e-mail atribuído, conforme regra definida.

**Regra 3 — Respostas devem ser rastreáveis.** Sempre que possível, a resposta deve apresentar a chave do ticket para facilitar conferência no Jira.

**Regra 4 — Comando ambíguo deve pedir esclarecimento.** Se o comando não for claro, o bot deve solicitar mais informações em vez de executar uma ação incorreta.

**Regra 5 — Credenciais não devem ficar fixas no código.** Tokens, URLs e credenciais devem ficar em arquivo de configuração, `.env` ou variável de ambiente.

---

## Arquitetura sugerida para os times

### Módulos recomendados

1. **Interface Teams** — recebe mensagens dos usuários e envia respostas.
2. **Identificação do usuário** — associa o usuário do Teams ao usuário/e-mail do Jira.
3. **Interpretação de comando** — classifica a intenção da mensagem e extrai parâmetros.
4. **Integração Jira** — consulta tickets e registra comentários.
5. **Controle de permissão** — valida quais tickets podem ser visualizados ou atualizados.
6. **Formatação de resposta** — organiza mensagens curtas, úteis e legíveis para o Teams.
7. **Log de execução** — registra consultas, tentativas de atualização, erros e permissões negadas.

### Proposta de fluxo ponta a ponta

1. usuário envia mensagem no Teams;
2. bot identifica usuário e e-mail associado;
3. bot interpreta intenção e parâmetros da mensagem;
4. solução consulta tickets permitidos no Jira ou base de teste;
5. solução aplica regras de permissão;
6. bot responde com status, pendências ou confirmação;
7. se houver comentário, solução valida permissão e registra/simula atualização;
8. solução registra log da operação.

---

## O que entregar no hackathon

### Entrega mínima viável

- bot ou interface simulada de conversa;
- consulta de tickets vinculados ao usuário;
- resposta com status dos tickets;
- identificação de tickets atrasados ou pendentes;
- registro ou simulação de comentário em ticket autorizado;
- bloqueio de consulta ou comentário sem permissão;
- uso da documentação da Jira API ou base mockada coerente;
- demonstração funcional do fluxo.

### Diferenciais

- resumo diário de pendências por usuário no Teams;
- filtros por projeto, prioridade, vencimento ou status;
- histórico das interações feitas pelo bot;
- tratamento de comandos ambíguos com pergunta de confirmação;
- painel simples com volume de tickets consultados, atrasados ou comentados;
- fallback quando a API estiver indisponível;
- logs amigáveis para suporte.

---

## Materiais de apoio previstos

Para viabilizar a construção da solução durante o hackathon, os participantes devem receber, sempre que possível:

- regra de negócio e documentação do fluxo;
- acesso de usuário administrador ao ambiente Jira com API habilitada;
- acesso ao ambiente Microsoft Teams ou ambiente de simulação;
- dois projetos de teste em base funcional;
- regras de permissão por usuário;
- exemplos de tickets e usuários;
- exemplos de perguntas esperadas;
- orientação sobre quais atualizações podem ser feitas em ambiente de teste.

---

## Demonstração esperada

Ao final do hackathon, o time deve conseguir demonstrar um fluxo funcional, ainda que com dados de teste.

A demonstração deve mostrar:

- usuário enviando uma pergunta no Teams ou interface simulada;
- bot identificando o usuário;
- bot consultando apenas tickets permitidos;
- resposta com status, atrasos e informações resumidas;
- solicitação de comentário em um ticket específico;
- validação de permissão;
- registro ou simulação do comentário;
- confirmação da ação ao usuário.
