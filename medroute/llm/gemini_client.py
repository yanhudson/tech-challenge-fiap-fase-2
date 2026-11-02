"""Provedor Gemini, pelo SDK oficial do Google (google-genai)."""

from typing import List, Sequence

from .base import AssistantTurn, Conversation, LLMClient, LLMError, ToolCall, ToolResult, ToolSpec

DEFAULT_MODEL = "gemini-3.5-flash-lite"
# O plano gratuito atinge o limite por minuto com facilidade, e o SDK não repete por padrão.
RETRY_ATTEMPTS = 4
TIMEOUT_MS = 120_000
_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
_BAD_TOOL_CALL = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS"}


def _finish_reason(candidate) -> str:
    reason = candidate.finish_reason
    return getattr(reason, "name", str(reason)) if reason is not None else "STOP"


def _text_of(content) -> str:
    """Junta o texto da resposta, sem os resumos de raciocínio."""
    parts = (content.parts or []) if content else []
    return "\n".join(part.text for part in parts if part.text and not part.thought).strip()


class GeminiClient(LLMClient):
    provider = "gemini"
    data_notice = (
        "No plano gratuito do Gemini, o Google pode usar o conteúdo enviado, e revisores humanos podem lê-lo. "
        "Use apenas dados fictícios ou uma cota paga."
    )

    def __init__(self, model: str = DEFAULT_MODEL, http_client=None):
        try:
            import httpx
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:
            raise LLMError("Pacote google-genai não instalado. Execute: pip install -r requirements.txt") from exc

        self.model = model
        self.types = types
        self._api_errors = (errors.APIError, errors.UnknownApiResponseError, httpx.HTTPError)
        self._client_error = errors.APIError
        self._client = genai.Client(
            http_options=types.HttpOptions(
                httpx_client=http_client,
                timeout=TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=RETRY_ATTEMPTS),
            )
        )

    def _failure(self, error: Exception) -> LLMError:
        code = error.code if isinstance(error, self._client_error) else None
        if code in (401, 403) or "API_KEY_INVALID" in str(error):
            hint = "Confira GEMINI_API_KEY no arquivo .env."
        elif code == 404:
            hint = "Modelo não encontrado. Para listar os modelos: python -m medroute llm-models"
        elif code == 429:
            hint = "Limite de uso atingido. O plano gratuito limita pedidos por minuto e por dia; aguarde e tente de novo."
        elif code == 400:
            hint = "O pedido foi rejeitado pela API."
        elif code is None:
            hint = "Não foi possível conectar. Confira a internet."
        else:
            hint = "Erro no serviço. Tente de novo mais tarde."
        return LLMError(f"Falha ao chamar {self.label}: {error}\n{hint}")

    def create_content(self, system: str, contents: list, effort: str, max_tokens: int, tools: Sequence[ToolSpec] = ()):
        """
        Faz a chamada à API e transforma bloqueio e resposta cortada em LLMError.

        Returns:
        O conteúdo gerado pelo modelo, no formato do SDK.
        """
        types = self.types
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_level=effort.upper()),
        )
        if tools:
            # As ferramentas alteram o cadastro, então quem as executa é a aplicação.
            config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=tool.input_schema if tool.input_schema.get("properties") else None,
                        )
                        for tool in tools
                    ]
                )
            ]

        try:
            response = self._client.models.generate_content(model=self.model, contents=contents, config=config)
        except self._api_errors as error:
            raise self._failure(error) from error

        if not response.candidates:
            feedback = response.prompt_feedback
            reason = feedback.block_reason if feedback else None
            raise LLMError(f"{self.label} bloqueou o pedido (motivo: {getattr(reason, 'name', reason) or 'não informado'}).")

        candidate = response.candidates[0]
        reason = _finish_reason(candidate)
        if reason in _BLOCKED:
            raise LLMError(f"{self.label} recusou o pedido (motivo: {reason}).")
        if reason == "MAX_TOKENS":
            raise LLMError(f"A resposta de {self.label} foi cortada ao atingir o limite de {max_tokens} tokens.")
        if reason in _BAD_TOOL_CALL:
            raise LLMError(f"{self.label} fez uma chamada de ferramenta inválida (motivo: {reason}).")
        return candidate.content

    def complete(self, system: str, user: str, effort: str = "medium", max_tokens: int = 16000) -> str:
        content = self.create_content(system, [self._user_text(user)], effort, max_tokens)
        text = _text_of(content)
        if not text:
            raise LLMError(f"{self.label} devolveu uma resposta vazia.")
        return text

    def _user_text(self, text: str):
        return self.types.Content(role="user", parts=[self.types.Part(text=text)])

    def start_conversation(self, system: str, tools: Sequence[ToolSpec], effort: str = "medium") -> Conversation:
        return GeminiConversation(self, system, tools, effort)

    def list_models(self) -> List[str]:
        try:
            return sorted(model.name.removeprefix("models/") for model in self._client.models.list())
        except self._api_errors as error:
            raise self._failure(error) from error


class GeminiConversation(Conversation):
    def __init__(self, client: GeminiClient, system: str, tools: Sequence[ToolSpec], effort: str, max_tokens: int = 16000):
        self._client = client
        self._system = system
        self._tools = tools
        self._effort = effort
        self._max_tokens = max_tokens
        self._contents: list = []
        self._pending_calls: dict = {}  # id visto pela aplicação -> chamada original
        self._call_count = 0

    def _advance(self) -> AssistantTurn:
        content = self._client.create_content(
            self._system, self._contents, self._effort, self._max_tokens, self._tools
        )
        parts = (content.parts or []) if content else []
        # O conteúdo volta sem alteração: as assinaturas de raciocínio são obrigatórias
        # nas chamadas de ferramenta e não podem mudar de lugar.
        if parts:
            self._contents.append(content)

        calls = []
        for part in parts:
            if part.function_call:
                self._call_count += 1
                # O Gemini nem sempre informa o id da chamada.
                call_id = part.function_call.id or f"chamada-{self._call_count}"
                self._pending_calls[call_id] = part.function_call
                calls.append(ToolCall(call_id, part.function_call.name, dict(part.function_call.args or {})))

        text = _text_of(content)
        if not text and not calls:
            raise LLMError(f"{self._client.label} devolveu uma resposta vazia.")
        return AssistantTurn(text, calls)

    def send_user(self, text: str) -> AssistantTurn:
        self._contents.append(self._client._user_text(text))
        return self._advance()

    def send_tool_results(self, results: Sequence[ToolResult]) -> AssistantTurn:
        types = self._client.types
        parts = []
        for result in results:
            call = self._pending_calls.pop(result.call_id)
            key = "error" if result.is_error else "result"
            parts.append(
                types.Part(
                    function_response=types.FunctionResponse(id=call.id, name=call.name, response={key: result.content})
                )
            )
        self._contents.append(types.Content(role="user", parts=parts))
        return self._advance()
