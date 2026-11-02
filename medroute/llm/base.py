"""
Contrato entre a aplicação e os provedores de LLM.

O restante do projeto conhece apenas estes tipos. Para adicionar um provedor, basta
implementar LLMClient e Conversation em um módulo novo e registrá-lo em client.py.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Sequence


class LLMError(RuntimeError):
    """Falha de configuração ou de chamada à LLM."""


@dataclass(frozen=True)
class ToolSpec:
    """Ferramenta oferecida à LLM. `input_schema` é um JSON Schema."""

    name: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class AssistantTurn:
    text: str
    tool_calls: List[ToolCall] = field(default_factory=list)


class Conversation(ABC):
    """
    Conversa com ferramentas.

    O histórico fica no formato nativo do provedor, dentro da implementação. Assim,
    quem usa a conversa não depende de como cada API representa as mensagens.
    """

    @abstractmethod
    def send_user(self, text: str) -> AssistantTurn:
        """Envia uma mensagem do usuário e devolve a resposta da LLM."""

    @abstractmethod
    def send_tool_results(self, results: Sequence[ToolResult]) -> AssistantTurn:
        """Devolve de uma só vez os resultados das ferramentas pedidas no último turno."""


class LLMClient(ABC):
    provider: str
    model: str
    data_notice: str = ""  # o que o usuário precisa saber antes de enviar dados a este provedor

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"

    @abstractmethod
    def complete(self, system: str, user: str, effort: str = "medium", max_tokens: int = 16000) -> str:
        """
        Envia um prompt e devolve o texto gerado.

        Parameters:
        - system: instruções de papel e regras.
        - user: dados e tarefa.
        - effort: "low", "medium" ou "high". Quem não tiver esse controle pode ignorá-lo.
        - max_tokens: tamanho máximo da resposta.

        Returns:
        str: o texto gerado, nunca vazio.
        """

    @abstractmethod
    def start_conversation(self, system: str, tools: Sequence[ToolSpec], effort: str = "medium") -> Conversation:
        """Abre uma conversa com as ferramentas indicadas."""

    @abstractmethod
    def list_models(self) -> List[str]:
        """Lista os modelos disponíveis para esta credencial."""
