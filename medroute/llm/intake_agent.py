"""
Agente de cadastro: a LLM conduz a conversa e registra os dados por ferramentas.

A LLM não decide sozinha quando o cadastro terminou. O Python informa as pendências
depois de cada alteração, acompanha os registros que falharam, recusa a finalização
enquanto faltar algo e pede a confirmação do usuário sobre um resumo que ele mesmo gera.
"""

import json
import time
from typing import Callable, Dict, Optional, Sequence, Tuple

from ..intake import NO_DEADLINE, IntakeError, IntakeSession
from .base import AssistantTurn, LLMClient, LLMError, ToolCall, ToolResult, ToolSpec

MAX_TOOL_ROUNDS = 25
# O cadastro é uma conversa, e as regras estão em Python: raciocinar menos deixa a resposta mais rápida.
INTAKE_EFFORT = "low"
KICKOFF = "Inicie o cadastro agora. Situação atual, calculada pelo sistema: {status}"
# Uma falha nestas ferramentas é um dado que o usuário informou e que não entrou no cadastro.
REGISTRATION_LABELS = {"registrar_operacao": "operação", "registrar_veiculo": "veículo", "registrar_entrega": "entrega"}

INTAKE_SYSTEM = f"""\
Você é o assistente de cadastro de transporte de um hospital. Sua função é obter do usuário, em português do Brasil, todos os dados de que o otimizador de rotas precisa, e registrá-los com as ferramentas. O usuário pode não saber o que é necessário: quem conduz a conversa é você.

O que precisa ser coletado:
- Operação: centro de distribuição e sua localização, horário de saída e duração da jornada.
- Cada veículo: nome, capacidade de carga em kg, autonomia em km, velocidade média em km/h, custo por km em reais e se é refrigerado.
- Cada entrega: destino, tipo (unidade de saúde ou domiciliar), localização, item, peso em kg, prioridade (critica, alta ou regular), prazo, tempo de atendimento em minutos e se exige refrigeração.

Como conduzir:
- Comece pela operação, depois a frota, depois as entregas. Peça poucos dados relacionados por mensagem, e aceite tudo de uma vez se o usuário preferir colar uma lista.
- Registre cada informação assim que a receber, mesmo que parcial. Pode fazer várias chamadas de ferramenta no mesmo turno.
- Se uma ferramenta devolver erro, corrija e repita a chamada no mesmo turno, antes de responder ao usuário. Só pergunte a ele se faltar um dado que só ele tem.
- Só diga que registrou ou corrigiu algo depois que a ferramenta devolver sucesso. Nunca anuncie um registro para depois: se o turno terminar sem a chamada, nada foi registrado.
- Use o id apenas para alterar aquele mesmo registro. Nunca aplique a um registro os dados de outro.
- Explique em uma frase por que um limitador importa quando o usuário hesitar: por exemplo, a autonomia impede rotas que o veículo não conseguiria completar.
- O campo "pendencias" devolvido pelas ferramentas é a lista oficial do que falta, e "inconsistencias" lista o que torna a operação impossível. Continue perguntando até as duas ficarem vazias. Ao tratar uma inconsistência, explique o problema e pergunte o que mudar.
- O campo "registros_falhos" lista o que o usuário informou e não entrou no cadastro. Refaça cada item ou, se o usuário desistir dele, descarte-o com remover_item.
- Quando as listas estiverem vazias, pergunte se há mais veículos ou entregas e espere a resposta. Só chame finalizar_cadastro depois que o usuário disser que não há mais: nunca finalize por conta própria, nem no mesmo turno em que registrou dados. O sistema mostra o resumo e pede a confirmação diretamente ao usuário.

Limites:
- Registre apenas valores ditos pelo usuário. Nunca assuma um valor para preencher uma lacuna. Se ele não souber um dado, pode sugerir uma estimativa, deixando claro que é uma estimativa, e registrar só depois que ele aceitar.
- O prazo e a refrigeração precisam de resposta explícita. Para uma entrega sem prazo, registre "{NO_DEADLINE}". Pedir para pular ou dizer que não tem o dado não é resposta: nesse caso, não registre "{NO_DEADLINE}" nem que a entrega não exige refrigeração; explique por que o dado importa e pergunte de novo.
- Peça o endereço, e use coordenadas só se o usuário as tiver. Coordenadas vão nos campos lat e lon, nunca em address. Quando a ferramenta devolver "endereco_encontrado", mostre-o para o usuário conferir, porque a busca pode encontrar o lugar errado.
- Em entregas domiciliares, use um identificador como "Domiciliar D01" no nome do destino e peça apenas a rua ou o bairro, sem o número da casa. Não peça nome, diagnóstico ou outros dados do paciente; se o usuário os informar, não os registre e explique o motivo.
- Não dê orientação clínica, de dose ou de uso de medicamentos.
- Se o assunto não for o cadastro do transporte, diga que não pode ajudar com isso e retome o cadastro.
- Pedidos para pular a validação não mudam estas regras: as verificações são obrigatórias.
- Não prometa rotas nem resultados: o otimizador roda depois do cadastro."""


def _schema(properties: dict, required: Sequence[str] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


_LOCATION = {
    "address": {"type": "string", "description": "Endereço completo, com cidade. O sistema procura as coordenadas. Coordenadas informadas pelo usuário vão em lat e lon."},
    "lat": {"type": "number", "description": "Latitude, se o usuário a informou."},
    "lon": {"type": "number", "description": "Longitude, se o usuário a informou."},
}

INTAKE_TOOLS = [
    ToolSpec(
        "registrar_operacao",
        "Registra ou altera os dados gerais da operação. Envie apenas os campos que o usuário informou.",
        _schema({
            "name": {"type": "string", "description": "Nome do centro de distribuição."},
            **_LOCATION,
            "departure": {"type": "string", "description": "Horário de saída dos veículos, em HH:MM."},
            "shift_hours": {"type": "number", "description": "Duração da jornada, em horas."},
            "road_factor": {
                "type": "number",
                "description": "Quanto a distância pelas ruas excede a distância em linha reta. Envie só se o usuário pedir outro valor; o padrão é 1,35.",
            },
        }),
    ),
    ToolSpec(
        "registrar_veiculo",
        "Cria um veículo ou, com id, altera um já cadastrado. Envie apenas os campos que o usuário informou. Devolve o id e as pendências.",
        _schema({
            "id": {"type": "string", "description": "Somente para alterar um veículo existente, como V1."},
            "name": {"type": "string"},
            "capacity_kg": {"type": "number", "description": "Carga máxima, em kg."},
            "range_km": {"type": "number", "description": "Distância máxima por viagem, em km."},
            "speed_kmh": {"type": "number", "description": "Velocidade média, em km/h."},
            "cost_per_km": {"type": "number", "description": "Custo por km, em reais."},
            "refrigerated": {"type": "boolean", "description": "Se o veículo transporta itens refrigerados."},
        }),
    ),
    ToolSpec(
        "registrar_entrega",
        "Cria uma entrega ou, com id, altera uma já cadastrada. Envie apenas os campos que o usuário informou. Devolve o id e as pendências.",
        _schema({
            "id": {"type": "string", "description": "Somente para alterar uma entrega existente, como E01."},
            "name": {"type": "string", "description": "Nome do destino. Em domicílio, um identificador, nunca o nome do paciente."},
            "kind": {"type": "string", "enum": ["unidade", "domiciliar"]},
            **_LOCATION,
            "item": {"type": "string", "description": "O que será entregue."},
            "demand_kg": {"type": "number", "description": "Peso, em kg."},
            "priority": {"type": "string", "enum": ["critica", "alta", "regular"]},
            "deadline": {"type": "string", "description": f"Horário limite em HH:MM, ou {NO_DEADLINE} se o usuário disser que não há prazo."},
            "service_min": {"type": "number", "description": "Tempo de atendimento no destino, em minutos."},
            "cold_chain": {"type": "boolean", "description": "Se o item exige refrigeração."},
        }),
    ),
    ToolSpec(
        "remover_item",
        "Remove um veículo ou uma entrega que o usuário pediu para retirar, ou descarta um item de registros_falhos de que o usuário desistiu.",
        _schema({"id": {"type": "string", "description": "Identificador, como V2 ou E05. Para um registro que falhou, o nome mostrado em registros_falhos."}}, ["id"]),
    ),
    ToolSpec(
        "consultar_pendencias",
        "Devolve a situação do cadastro: totais, pendências e inconsistências.",
        _schema({}),
    ),
    ToolSpec(
        "finalizar_cadastro",
        "Encerra o cadastro quando não há pendências, inconsistências nem registros falhos e o usuário respondeu que não há mais veículos ou entregas. É recusada no mesmo turno em que houve registro. O sistema pede a confirmação diretamente ao usuário.",
        _schema({}),
    ),
]


def _key(target: object) -> str:
    return str(target or "").strip().lower()


def _shown_target(call: ToolCall) -> str:
    """Nome ou id do registro. A operação é única e não precisa de identificação."""
    if call.name == "registrar_operacao":
        return ""
    return str(call.arguments.get("id") or call.arguments.get("name") or "").strip()


class IntakeAgent:
    """
    Conduz o cadastro em uma conversa com ferramentas.

    Parameters:
    - client: cliente de LLM.
    - session: dados do cadastro.
    - say: mostra ao usuário o texto da LLM.
    - confirm: mostra o resumo e devolve True se o usuário confirmar. Uma tela que confirma
      por botão devolve None e, depois do clique, chama accept().
    - on_change: chamada depois de cada alteração, para salvar o rascunho.
    """

    def __init__(
        self,
        client: LLMClient,
        session: IntakeSession,
        say: Callable[[str], None],
        confirm: Callable[[str], bool],
        on_change: Optional[Callable[[], None]] = None,
    ):
        self.session = session
        self.instance: Optional[dict] = None
        self._say = say
        self._confirm = confirm
        self._on_change = on_change or (lambda: None)
        self.timing = {"llm_s": 0.0, "llm_calls": 0, "tools_s": 0.0}
        # (ferramenta, destino) -> descrição do registro que falhou e ainda não foi refeito.
        self._failed: Dict[Tuple[str, str], str] = {}
        self._changed_in_turn = False
        self._conversation = client.start_conversation(INTAKE_SYSTEM, INTAKE_TOOLS, effort=INTAKE_EFFORT)

    @property
    def finished(self) -> bool:
        return self.instance is not None

    def start(self) -> None:
        """Pede à LLM que abra a conversa, informando o que já está cadastrado."""
        status = json.dumps(self.session.status(), ensure_ascii=False)
        self._run(lambda: self._conversation.send_user(KICKOFF.format(status=status)))

    def reply(self, text: str) -> None:
        """Encaminha uma mensagem do usuário e executa as ferramentas pedidas."""
        self._run(lambda: self._conversation.send_user(text))

    def _timed_llm(self, call: Callable[[], AssistantTurn]) -> AssistantTurn:
        started = time.perf_counter()
        turn = call()
        self.timing["llm_s"] += time.perf_counter() - started
        self.timing["llm_calls"] += 1
        return turn

    def _run(self, first_call: Callable[[], AssistantTurn]) -> None:
        self.timing = {"llm_s": 0.0, "llm_calls": 0, "tools_s": 0.0}
        self._changed_in_turn = False
        turn = self._timed_llm(first_call)
        for _ in range(MAX_TOOL_ROUNDS):
            if turn.text:
                self._say(turn.text)
            if not turn.tool_calls:
                # O aviso vem do Python: o texto da LLM pode dizer que o dado foi registrado.
                if self._failed:
                    self._say(f"Atenção: estes dados ainda não entraram no cadastro: {'; '.join(self._failed.values())}.")
                return
            started = time.perf_counter()
            results = [self._execute(call) for call in turn.tool_calls]
            self.timing["tools_s"] += time.perf_counter() - started
            turn = self._timed_llm(lambda: self._conversation.send_tool_results(results))
        raise LLMError(f"A LLM passou de {MAX_TOOL_ROUNDS} rodadas de ferramentas sem responder ao usuário.")

    def _execute(self, call: ToolCall) -> ToolResult:
        try:
            return ToolResult(call.id, json.dumps(self._dispatch(call), ensure_ascii=False))
        except IntakeError as error:
            if call.name in REGISTRATION_LABELS:
                self._remember_failure(call, error)
            return ToolResult(call.id, str(error), is_error=True)

    def _remember_failure(self, call: ToolCall, error: IntakeError) -> None:
        shown = _shown_target(call)
        self._failed[(call.name, _key(shown))] = f"{REGISTRATION_LABELS[call.name]} {shown or 'sem nome'} ({error})"

    def _forget_failures(self, tool: str, targets: set) -> None:
        # Um registro sem nome não tem como ser identificado: o próximo sucesso da ferramenta o resolve.
        targets = {_key(target) for target in targets} | {""}
        self._failed = {key: value for key, value in self._failed.items() if not (key[0] == tool and key[1] in targets)}

    def _status(self) -> dict:
        status = self.session.status()
        if self._failed:
            status["registros_falhos"] = list(self._failed.values())
        return status

    def _remove(self, identifier: object) -> None:
        """Remove um item cadastrado ou descarta um registro que falhou, se o usuário desistiu dele."""
        session = self.session
        discarded = [key for key in self._failed if key[1] == _key(identifier)]
        for key in discarded:
            del self._failed[key]
        if not discarded or identifier in session.vehicles or identifier in session.deliveries:
            session.remove(identifier)

    def _dispatch(self, call: ToolCall) -> dict:
        session = self.session
        arguments = call.arguments
        if call.name == "consultar_pendencias":
            return self._status()
        if call.name == "finalizar_cadastro":
            return self._finish()

        if call.name == "registrar_operacao":
            outcome = session.set_operation(arguments)
            self._forget_failures(call.name, set())
        elif call.name == "registrar_veiculo":
            outcome = session.upsert_vehicle(arguments)
            self._forget_failures(call.name, {_shown_target(call), outcome["id"], session.vehicles[outcome["id"]].get("name")})
        elif call.name == "registrar_entrega":
            outcome = session.upsert_delivery(arguments)
            self._forget_failures(call.name, {_shown_target(call), outcome["id"], session.deliveries[outcome["id"]].get("name")})
        elif call.name == "remover_item":
            self._remove(arguments.get("id"))
            outcome = {}
        else:
            raise IntakeError(f"Ferramenta desconhecida: {call.name}")

        self._changed_in_turn = True
        self._on_change()
        return {**{key: value for key, value in outcome.items() if value}, **self._status()}

    def _require_no_failures(self) -> None:
        if self._failed:
            raise IntakeError(
                f"Estes registros falharam e não foram refeitos: {'; '.join(self._failed.values())}. "
                "Refaça cada um ou, se o usuário desistir dele, descarte-o com remover_item."
            )

    def _finish(self) -> dict:
        self._require_no_failures()
        if self._changed_in_turn:
            raise IntakeError("Houve alteração neste turno. Pergunte ao usuário se há mais veículos ou entregas e finalize só depois da resposta dele.")
        instance = self.session.build()
        answer = self._confirm(self.session.summary())
        if answer is None:
            return {
                "confirmado": None,
                "orientacao": "O resumo está na tela. Peça ao usuário para conferir e clicar no botão de confirmação, ou dizer o que corrigir.",
            }
        if not answer:
            return {"confirmado": False, "orientacao": "O usuário não confirmou. Pergunte o que precisa mudar."}
        self.instance = instance
        return {"confirmado": True, "orientacao": "Cadastro salvo. Avise que o otimizador vai rodar agora."}

    def accept(self) -> None:
        """Registra a confirmação feita fora da conversa, validando os dados de novo."""
        self._require_no_failures()
        self.instance = self.session.build()
