# Arquitetura robusta inicial
Vou detalhar a arquitetura considerando os pontos de falha reais que aparecem em produção desse tipo de sistema. Pense em sete camadas, da borda para dentro:

1. Adaptador Teams. Bot Framework SDK recebe a mensagem. Aqui você extrai três coisas e nada mais: teams_user_id, teams_user_email, texto_mensagem. Nenhuma lógica de negócio mora aqui. Importante: o Bot Framework já garante autenticação via Azure AD, então o teams_user_email chega confiável, não vem do conteúdo da mensagem.

2. Resolução de identidade. Mapeia teams_user_email para jira_account_id. Esse mapeamento deve ser cacheado (Redis ou memória) com TTL razoável. Se o usuário do Teams não tem correspondente no Jira, o fluxo para aqui com mensagem clara. Esse é o ponto onde você ancora toda a segurança subsequente: a partir daqui, qualquer operação carrega o jira_account_id resolvido, nunca um valor vindo do LLM.

3. NLU (tool calling). O LLM recebe o texto e a lista de ferramentas. O prompt do sistema deve ser explícito em três coisas: (a) você só pode escolher uma das ferramentas disponíveis, (b) nunca invente chaves de ticket, projetos ou usuários, (c) se o pedido for ambíguo, chame a ferramenta pedir_esclarecimento. As ferramentas que eu definiria são poucas e bem delimitadas:
- listar_tickets(status?, projeto?, atrasados?, limite?)
- detalhar_ticket(chave)
- comentar_ticket(chave, texto)
- pedir_esclarecimento(motivo, sugestoes?)
- comando_fora_de_escopo(motivo)
Note que jira_account_id não está nos parâmetros de nenhuma ferramenta. Ele é injetado pela camada de execução, não vem do LLM. Isso é deliberado.

4. Validação e autorização. Recebe a ferramenta escolhida e os argumentos. Aqui rodam, em ordem: validação do schema (Pydantic), validação semântica (o ticket existe?), e autorização (esse ticket está vinculado ao usuário identificado na camada 2?). Para a autorização, defina uma função única usuario_pode_ver(account_id, ticket) e outra usuario_pode_comentar(account_id, ticket), e que toda operação passe por uma delas. Regra do anexo: vínculo pode ser responsável, reporter, ou regra customizada — mas isso vive em código, não em prompt.

5. Integração Jira. Cliente HTTP da Jira API v3 com algumas qualidades não negociáveis: timeout explícito (5 a 10 segundos), retry com backoff exponencial em erros 5xx e 429, circuit breaker para evitar martelar a API quando ela está fora, e logging de cada chamada com correlation ID. Use JQL parametrizado, nunca concatene strings (princípio análogo ao de SQL injection, e o JQL aceita injeção parecida). Para listar_tickets, a JQL fica algo como assignee = currentUser() AND status != Done, mas montada por código a partir dos parâmetros validados.

6. Formatação de resposta. Recomendo determinístico para começar: templates simples que recebem a lista de tickets e produzem markdown ou Adaptive Cards do Teams. Se quiser humanizar mais, passe os dados já fetchados para o LLM com a instrução estrita de apenas reorganizar, jamais inventar campos. Adaptive Cards são preferíveis a markdown puro porque permitem botões de ação direta (por exemplo, "comentar neste ticket") e ficam visualmente muito melhores no Teams.

7. Observabilidade. Log estruturado (JSON) com correlation ID por interação, registrando: usuário identificado, intenção classificada, ferramenta chamada, argumentos, resultado da autorização, latência das chamadas Jira, e resposta final. Isso é tanto para depuração quanto para a Regra 5 do anexo (rastreabilidade) e para o diferencial mencionado de painel de uso.




Pontos críticos de robustez
Algumas decisões que separam protótipo de algo que aguenta:
Tudo que envolve "qual usuário" é fixado uma vez por requisição. Resolvido na camada 2, propagado por contexto (injeção de dependência ou middleware), nunca passa pelo LLM. Isso elimina por design a classe de bug "modelo inventou que o usuário é outro".
Comandos destrutivos exigem confirmação explícita. Comentar em ticket é destrutivo (fica registrado, notifica gente). A primeira vez que o usuário pede para comentar, retorne uma confirmação ("Você confirma o comentário X no ticket Y?") e só execute após "sim". Isso protege contra interpretação errada da intenção pelo LLM e também atende à Regra 4 sobre comandos ambíguos.
Idempotência em comentários. Gere um hash do conteúdo + chave do ticket + usuário + janela de tempo curta (digamos, 1 minuto). Se chegar uma segunda requisição com mesmo hash, retorne sucesso sem registrar de novo. Evita comentário duplicado em caso de retry de rede.
Limites de quantidade. Limite resultados de listagem (por exemplo, 10 tickets), e informe quando há mais. Tanto por experiência (Regra do anexo) quanto por custo de tokens caso você passe os resultados para o LLM formatar.
Credenciais. Variáveis de ambiente, nunca em código (Regra 5 do anexo). Para a Jira, use OAuth 2.0 (3LO) se possível, ou API token + email com permissões mínimas para o ambiente de teste. Tokens do Anthropic/OpenAI também em env.
Fallback gracioso. Se a Jira API estiver fora, o bot responde "estou sem acesso ao Jira no momento, tente em alguns minutos" em vez de quebrar. Se o LLM falhar, responda "não consegui entender, pode reformular?". Nada de stack trace para o usuário.
Testes da camada de regras. A camada 4 (autorização) tem que ter teste unitário. Não tem LLM nem rede, é função pura. Testa cenários: usuário tenta ver ticket de outro, usuário tenta comentar em ticket que não é dele, ticket inexistente, etc. Esse é o piso de segurança.
