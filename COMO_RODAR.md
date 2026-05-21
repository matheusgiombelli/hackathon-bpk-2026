# Como rodar o Jira Bot localmente

## Pré-requisitos

- Python 3.11 ou superior
- Acesso ao Jira Cloud (URL, e-mail e API token)

---

## 1. Clonar e entrar na pasta

```bash
git clone <url-do-repo>
cd hackathon-bpk-2026
```

---

## 2. Criar e ativar o ambiente virtual

```bash
python -m venv .venv
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
.venv\Scripts\activate.bat
```

**Linux/Mac:**
```bash
source .venv/bin/activate
```

---

## 3. Instalar dependências

```bash
pip install -r requirements.txt
```

---

## 4. Configurar variáveis de ambiente

Copie o arquivo de exemplo e preencha com suas credenciais:

```bash
cp .env.example .env
```

Abra `.env` e preencha:

```env
JIRA_URL=https://seu-dominio.atlassian.net
JIRA_EMAIL=seu-email@dominio.com
JIRA_API_TOKEN=seu-token-aqui
```

### Como gerar o Jira API Token

1. Acesse https://id.atlassian.com/manage-profile/security/api-tokens
2. Clique em **Create API token**
3. Dê um nome (ex: `hackathon-bot`) e copie o valor gerado
4. Cole em `JIRA_API_TOKEN` no `.env`

### Mapeamento de usuários (`data/user_mapping.json`)

O bot precisa saber qual `account_id` do Jira corresponde ao usuário do chat.
Edite `data/user_mapping.json` e adicione seu e-mail:

```json
{
  "users": [
    {
      "teams_email": "seu-email@dominio.com",
      "teams_user_id": "seu-id",
      "jira_account_id": "712020:xxxx-xxxx-xxxx",
      "display_name": "Seu Nome"
    },
    {
      "teams_email": "User",
      "teams_user_id": "emulator-user",
      "jira_account_id": "712020:xxxx-xxxx-xxxx",
      "display_name": "Usuario Web Chat"
    }
  ]
}
```

> O campo `"teams_email": "User"` é o mapeamento usado pelo web chat (`localhost:8000`).

Para encontrar seu `jira_account_id`: acesse o Jira, vá em seu perfil → a URL conterá o ID no formato `712020:xxxxxxxx-xxxx-...`.

---

## 5. Subir o servidor

```bash
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Para desenvolvimento com reload automático:

```bash
python -m uvicorn src.main:app --reload --port 8000
```

---

## 6. Acessar o bot

Abra o navegador em:

```
http://localhost:8000
```

Você verá o chat web integrado ao Jira. Digite os comandos abaixo para testar.

---

## Comandos disponíveis

| Comando | Descrição |
|---|---|
| `meus tickets` | Lista todos os seus tickets no Jira |
| `tickets atrasados` | Mostra tickets com prazo vencido |
| `detalha KAN-5` | Exibe detalhes de um ticket específico |
| `comenta no KAN-5: seu texto` | Inicia fluxo de comentário (pede confirmação) |
| `sim` | Confirma a ação pendente |
| `não` | Cancela a ação pendente |
| `ajuda` | Lista os comandos disponíveis |

---

## Verificar saúde da API

```bash
curl http://localhost:8000/health
```

Resposta esperada:
```json
{"status": "ok", "model": "anthropic/claude-3-haiku", "jira_url": "https://seu-dominio.atlassian.net"}
```

---

## Rodar os testes

```bash
pytest tests/ -v
```

---

## Variáveis opcionais

| Variável | Padrão | Descrição |
|---|---|---|
| `OPENROUTER_API_KEY` | vazio | Chave para NLU via LLM (sem ela usa modo keyword) |
| `OPENROUTER_MODEL` | `anthropic/claude-3-haiku` | Modelo usado pelo agente NLU |
| `MICROSOFT_APP_ID` | vazio | ID do bot no Teams (deixe vazio para uso local) |
| `MICROSOFT_APP_PASSWORD` | vazio | Senha do bot no Teams (deixe vazio para uso local) |
| `LOG_LEVEL` | `INFO` | Nível de log (`DEBUG`, `INFO`, `WARNING`) |
| `PORT` | `8000` | Porta do servidor |

> Sem `OPENROUTER_API_KEY`, o bot usa um fallback baseado em palavras-chave que cobre todos os comandos principais.

---

## Estrutura do projeto

```
src/
  adapters/teams.py     # Integração Bot Framework
  cache/                # Cache de conversas e Jira
  config.py             # Configurações via .env
  formatting/           # Formatação das respostas
  identity/             # Resolução de identidade email → Jira
  jira/                 # Cliente Jira (busca, detalhes, comentários)
  nlu/                  # Agente NLU (LLM ou keyword fallback)
  rules/                # Regras de autorização
  main.py               # Endpoints FastAPI
data/
  user_mapping.json     # Mapeamento email → jira_account_id
static/
  index.html            # Interface web chat
tests/                  # Testes automatizados
```
