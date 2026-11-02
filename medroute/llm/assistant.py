"""
Assistente de rotas: une dados, prompts, cliente e validação.

Sem cliente de LLM, responde por templates determinísticos, sempre identificados
por um aviso, para que o resultado nunca seja confundido com texto de LLM.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from ..metrics import facts_for_llm, find_patterns, find_route
from . import offline, prompts
from .prompts import Prompt
from .quality import check_stop_order, find_unsupported_numbers

OFFLINE_BANNER = "[MODO OFFLINE: texto gerado por template determinístico, sem LLM]"


@dataclass
class AssistantOutput:
    text: str
    source: str  # "offline" ou "provedor/modelo"
    warnings: List[str] = field(default_factory=list)


def route_facts(plan: dict, route: dict) -> dict:
    """Seleciona apenas os dados de uma rota, sem as coordenadas."""
    return {
        "veiculo": f'{route["vehicle_name"]} ({route["vehicle_id"]})',
        "refrigerado": route["refrigerated"],
        "saida": plan["departure"],
        "centro_de_distribuicao": plan["depot"]["name"],
        "distancia_km": route["distance_km"],
        "carga_kg": route["load_kg"],
        "retorno": route["return_time"],
        "paradas": [
            {key: value for key, value in stop.items() if key not in ("lat", "lon")}
            for stop in route["stops"]
        ],
    }


class RouteAssistant:
    """
    Gera instruções, relatórios, sugestões e respostas sobre um plano.

    Parameters:
    - client: objeto com `label` e `complete(system, user, effort)`, como LLMClient.
      Com None, o assistente funciona em modo offline.
    """

    def __init__(self, client=None):
        self.client = client

    @property
    def is_offline(self) -> bool:
        return self.client is None

    def _offline(self, text: str) -> AssistantOutput:
        return AssistantOutput(f"{OFFLINE_BANNER}\n\n{text}", "offline")

    def _complete(self, prompt: Prompt) -> str:
        return self.client.complete(prompt.system, prompt.user, effort=prompt.effort)

    def _number_warnings(self, text: str, facts: object) -> List[str]:
        unsupported = find_unsupported_numbers(text, facts)
        if not unsupported:
            return []
        return [
            "Confira estes valores, que não aparecem nos dados enviados: "
            f"{', '.join(unsupported)}. Podem ser cálculos da LLM ou erros."
        ]

    def _generate(self, prompt: Prompt, facts: object) -> AssistantOutput:
        text = self._complete(prompt)
        return AssistantOutput(text, self.client.label, self._number_warnings(text, facts))

    def driver_instructions(self, plan: dict, vehicle: str) -> AssistantOutput:
        """
        Gera as instruções de rota de um veículo.

        Se a ordem das paradas vier errada, pede uma nova resposta uma única vez. Se
        o erro persistir, devolve o texto com um aviso, para revisão humana.

        Parameters:
        - plan: resumo do plano.
        - vehicle: identificador ou nome do veículo.

        Returns:
        AssistantOutput: o texto, a origem e os avisos.
        """
        route = find_route(plan, vehicle)
        if self.is_offline:
            return self._offline(offline.render_driver_instructions(route, plan))

        facts = route_facts(plan, route)
        prompt = prompts.driver_instructions_prompt(facts)
        text = self._complete(prompt)
        problems = check_stop_order(text, route)
        if problems:
            text = self._complete(prompts.retry_message(prompt, problems))
            problems = check_stop_order(text, route)

        warnings = [
            f"Não entregue este texto ao motorista sem revisão. {problem}" for problem in problems
        ]
        warnings.extend(self._number_warnings(text, facts))
        return AssistantOutput(text, self.client.label, warnings)

    def daily_report(self, plan: dict) -> AssistantOutput:
        """Gera o relatório diário de um plano."""
        if self.is_offline:
            return self._offline(offline.render_daily_report(plan))
        facts = facts_for_llm(plan)
        return self._generate(prompts.daily_report_prompt(facts), facts)

    def weekly_report(self, history: dict) -> AssistantOutput:
        """Gera o relatório semanal a partir do histórico."""
        patterns = find_patterns(history)
        if self.is_offline:
            return self._offline(offline.render_weekly_report(patterns))
        return self._generate(prompts.weekly_report_prompt(patterns), patterns)

    def suggest_improvements(self, history: dict) -> AssistantOutput:
        """Sugere melhorias com base nos padrões do histórico."""
        patterns = find_patterns(history)
        if self.is_offline:
            return self._offline(offline.render_improvements(patterns))
        return self._generate(prompts.improvements_prompt(patterns), patterns)

    def answer(self, question: str, plan: dict, history: Optional[dict] = None) -> AssistantOutput:
        """Responde a uma pergunta em linguagem natural sobre o plano e o histórico."""
        patterns = find_patterns(history) if history is not None else None
        if self.is_offline:
            return self._offline(offline.answer_question(question, plan, patterns))
        facts = facts_for_llm(plan)
        data = {"plano": facts, "historico": patterns}
        return self._generate(prompts.question_prompt(question, facts, patterns), data)
