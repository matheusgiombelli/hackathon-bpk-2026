"""
Pydantic AI agent — Layer 3.
The LLM acts exclusively as an intent classifier and parameter extractor.
All business logic, authorization, and data access happen in the tools.
"""
from __future__ import annotations

import structlog
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel

from src.config import settings
from src.nlu.tools import (
    Deps,
    comentar_ticket,
    comando_fora_de_escopo,
    detalhar_ticket,
    listar_tickets,
    pedir_esclarecimento,
)

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """
Você é um assistente de gestão de tickets Jira integrado ao Microsoft Teams da Biopark.

Seu único papel é interpretar o que o usuário quer e chamar a ferramenta correta.
Você NÃO executa nenhuma lógica de negócio diretamente.

Ferramentas disponíveis:
- listar_tickets: listar tickets do usuário com filtros opcionais
- detalhar_ticket: obter detalhes de um ticket específico (necessário fornecer a chave, ex: CARM-145)
- comentar_ticket: adicionar comentário em um ticket (sempre requer confirmação)
- pedir_esclarecimento: quando o pedido for ambíguo ou incompleto
- comando_fora_de_escopo: quando o pedido não puder ser atendido por nenhuma ferramenta

Regras obrigatórias:
1. Sempre chame exatamente uma ferramenta por mensagem.
2. NUNCA invente chaves de ticket, projetos ou usuários.
3. NUNCA decida permissões — a ferramenta cuida disso.
4. Se o usuário mencionar uma chave de ticket (padrão PROJ-NNN), use-a exatamente como informada.
5. Se o pedido mencionar projeto use o código do projeto (ex: CARM para Carmel).
6. Quando a ferramenta retornar um resultado, responda com o resultado EXATAMENTE como recebido, sem alterar ou adicionar texto.
7. Se não tiver certeza do que o usuário quer, use pedir_esclarecimento.

Projetos conhecidos: SPF01 (HACKATHON 01), ELIO (HACKATHON 02), CARM (Carmel).
""".strip()

from pydantic_ai.providers.openai import OpenAIProvider

_agent: "Agent[Deps, str] | None" = None


def _build_agent() -> "Agent[Deps, str]":
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurado. Defina no arquivo .env e reinicie."
        )
    model = OpenAIModel(
        model_name=settings.openrouter_model,
        provider=OpenAIProvider(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        ),
    )
    a: Agent[Deps, str] = Agent(
        model=model,
        deps_type=Deps,
        result_type=str,
        system_prompt=SYSTEM_PROMPT,
        retries=1,
    )
    a.tool(listar_tickets)
    a.tool(detalhar_ticket)
    a.tool(comentar_ticket)
    a.tool(pedir_esclarecimento)
    a.tool(comando_fora_de_escopo)
    return a


def _get_agent() -> "Agent[Deps, str]":
    global _agent
    if _agent is None:
        _agent = _build_agent()
    return _agent


async def run(user_message: str, deps: Deps) -> str:
    """Run the NLU agent. Falls back to keyword matching if no API key is set."""
    import time

    # Keyword fallback when OpenRouter key is absent
    if not settings.openrouter_api_key:
        from src.nlu import keyword_fallback
        logger.info("nlu_mode", mode="keyword_fallback")
        return await keyword_fallback.run(user_message, deps)

    start = time.monotonic()
    try:
        a = _get_agent()
        result = await a.run(user_message, deps=deps)
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "intent_classified",
            latency_ms=latency_ms,
            model=settings.openrouter_model,
        )
        return result.data
    except RuntimeError as e:
        logger.error("nlu_config_error", error=str(e))
        return str(e)
    except Exception as e:
        logger.error("nlu_agent_error", error=str(e))
        return "Não consegui entender o pedido. Pode reformular?"
