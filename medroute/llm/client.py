"""
Registro de provedores de LLM e criação do cliente.

Para trocar de provedor, crie um módulo que implemente LLMClient (veja base.py) e
acrescente uma entrada em PROVIDERS. O restante do projeto não muda.

Uma falha de API nunca vira modo offline em silêncio: quem pediu uma LLM recebe o
erro, para não confundir um template com texto de LLM.
"""

import os
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .base import LLMClient, LLMError


def _load_env() -> None:
    """Lê o arquivo .env, quando o python-dotenv está instalado."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _gemini(model: str, http_client) -> LLMClient:
    # A importação fica aqui para que o SDK só seja exigido de quem usa o provedor.
    from .gemini_client import GeminiClient

    return GeminiClient(model, http_client)


@dataclass(frozen=True)
class ProviderSpec:
    factory: Callable[[str, object], LLMClient]
    default_model: str
    credential_envs: Tuple[str, ...]  # basta uma delas; o primeiro nome aparece nas mensagens


# A ordem define a procura por credenciais no modo automático.
PROVIDERS = {
    "gemini": ProviderSpec(_gemini, "gemini-3.5-flash-lite", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
}


def _has_credentials(spec: ProviderSpec) -> bool:
    return any(os.environ.get(name) for name in spec.credential_envs)


def create_client(
    provider: str = "auto",
    model: Optional[str] = None,
    http_client=None,
) -> Optional[LLMClient]:
    """
    Cria o cliente do provedor escolhido.

    Parameters:
    - provider: "auto", "offline" ou um nome de PROVIDERS. No modo automático, vale
      LLM_PROVIDER e depois a primeira credencial encontrada no ambiente.
    - model: modelo a usar. Sem ele, vale LLM_MODEL e depois o padrão do provedor.
    - http_client: cliente HTTP alternativo, usado nos testes.

    Returns:
    O cliente, ou None para o modo offline. Um provedor pedido explicitamente e sem
    credencial gera LLMError, em vez de cair no modo offline.
    """
    _load_env()

    chosen = provider
    if chosen == "auto":
        chosen = os.environ.get("LLM_PROVIDER") or "auto"
    if chosen == "offline":
        return None
    if chosen == "auto":
        chosen = next((name for name, spec in PROVIDERS.items() if _has_credentials(spec)), None)
        if chosen is None:
            return None

    spec = PROVIDERS.get(chosen)
    if spec is None:
        raise LLMError(f"Provedor desconhecido: {chosen}. Opções: {', '.join(PROVIDERS)}, offline.")
    if not _has_credentials(spec):
        raise LLMError(f"Defina {spec.credential_envs[0]} no ambiente ou no arquivo .env para usar {chosen}.")

    return spec.factory(model or os.environ.get("LLM_MODEL") or spec.default_model, http_client)
