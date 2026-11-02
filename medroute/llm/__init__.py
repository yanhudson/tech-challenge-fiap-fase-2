"""Integração com LLMs pré-treinadas: contrato, provedores, prompts, validação e modo offline."""

from .assistant import OFFLINE_BANNER, AssistantOutput, RouteAssistant
from .base import AssistantTurn, Conversation, LLMClient, LLMError, ToolCall, ToolResult, ToolSpec
from .client import PROVIDERS, create_client

__all__ = [
    "OFFLINE_BANNER",
    "PROVIDERS",
    "AssistantOutput",
    "AssistantTurn",
    "Conversation",
    "LLMClient",
    "LLMError",
    "RouteAssistant",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "create_client",
]
