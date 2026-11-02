"""
Modo offline: templates determinísticos e respostas por regras.

Não é uma LLM. Permite rodar o projeto e os testes sem chave de API e serve de
referência para comparar com o texto gerado pela LLM.
"""

import re
import unicodedata
from collections import Counter
from typing import Iterable, List, Optional

from ..metrics import format_number

NO_LLM_ANSWER = (
    "Não sei responder a essa pergunta em modo offline, que só reconhece parada, veículo, "
    "item e indicadores do plano. Para perguntas livres, configure uma LLM (veja o README)."
)

STOPWORDS = {
    "qual", "quais", "quantas", "quantos", "quando", "onde", "como", "quem", "porque", "para",
    "entrega", "entregas", "entregar", "entregue", "veiculo", "veiculos", "rota", "rotas", "parada",
    "paradas", "plano", "total", "dia", "hoje", "semana", "esta", "este", "essa", "esse", "sera", "chega",
    "chegar", "chegada", "leva", "levar", "tem", "tenho", "uma", "umas", "uns", "com", "sem", "dos", "das",
    "que", "mais", "menos", "foi", "sao", "prazo", "prazos",
}


def _normalize(text: str) -> str:
    """Passa para minúsculas e remove os acentos, para comparar textos."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokens(text: str) -> List[str]:
    return [token.rstrip("s") for token in re.findall(r"[a-z0-9]+", _normalize(text))]


def _all_stops(plan: dict) -> Iterable[tuple]:
    for route in plan["routes"]:
        for stop in route["stops"]:
            yield route, stop


def _stop_lines(stop: dict) -> List[str]:
    prefix = "URGENTE: " if stop["priority"] == "crítica" else ""
    deadline = f"Prazo: {stop['deadline']}." if stop["deadline"] else "Sem prazo definido."
    lines = [
        f"{stop['sequence']}. {prefix}{stop['name']} ({stop['id']})",
        f"   Chegada prevista: {stop['arrival']}. {deadline}",
        f"   Entregar: {stop['item']}, {format_number(stop['demand_kg'])} kg.",
    ]
    if stop["cold_chain"]:
        lines.append("   Manter refrigerado; conferir a temperatura na entrega.")
    if stop["late_min"] > 0:
        lines.append(f"   AVISO: atraso previsto de {format_number(stop['late_min'])} min. Avise a central.")
    return lines


def render_driver_instructions(route: dict, plan: dict) -> str:
    """Monta as instruções de rota de um veículo."""
    depot = plan["depot"]["name"]
    lines = [
        f"ROTA: {route['vehicle_name']} ({route['vehicle_id']})",
        (
            f"Saída às {plan['departure']} de {depot}. Distância: {format_number(route['distance_km'])} km. "
            f"Carga: {format_number(route['load_kg'])} kg. Retorno previsto: {route['return_time']}."
        ),
        "",
    ]
    for stop in route["stops"]:
        lines.extend(_stop_lines(stop))
    lines.extend(["", f"Ao terminar, retorne ao {depot}."])
    return "\n".join(lines)


def _attention_lines(plan: dict) -> List[str]:
    violations = plan["totals"]["violations"]
    lines = []
    if violations["overload_kg"] > 0:
        lines.append(f"- Excesso de carga: {format_number(violations['overload_kg'])} kg.")
    if violations["range_excess_km"] > 0:
        lines.append(f"- Autonomia excedida: {format_number(violations['range_excess_km'])} km.")
    if violations["shift_excess_min"] > 0:
        lines.append(f"- Jornada excedida: {format_number(violations['shift_excess_min'])} min.")
    if violations["cold_chain_violations"] > 0:
        lines.append(f"- Itens refrigerados em veículo comum: {violations['cold_chain_violations']}.")
    return lines


def render_daily_report(plan: dict) -> str:
    """Monta o relatório diário a partir das métricas do plano."""
    totals = plan["totals"]
    lines = [
        "## Resumo do dia",
        (
            f"Método: {plan['method']}. {totals['deliveries']} entregas, com "
            f"{totals['vehicles_used']} de {totals['vehicles_total']} veículos. "
            f"Entregas críticas no prazo: {format_number(totals['critical_on_time_rate_pct'])}%."
        ),
        "",
        "## Eficiência",
        f"- Distância total: {format_number(totals['distance_km'])} km",
        f"- Tempo somado em rota: {format_number(totals['route_minutes'])} min",
        f"- Custo estimado: R$ {format_number(totals['cost_brl'], 2)}",
        f"- Último retorno ao CD: {totals['last_return']}",
    ]
    for route in plan["routes"]:
        lines.append(
            f"- {route['vehicle_name']}: {len(route['stops'])} paradas, {format_number(route['distance_km'])} km, "
            f"{format_number(route['capacity_used_pct'])}% da carga, {format_number(route['range_used_pct'])}% da autonomia"
        )

    lines.extend(["", "## Economia de tempo e recursos"])
    comparison = plan.get("comparison")
    if comparison:
        lines.extend(
            [
                f"Comparação com: {comparison['reference_method']}. Não é a operação real.",
                f"- Distância: {format_number(comparison['distance_km_saved'])} km ({format_number(comparison['distance_saved_pct'])}%)",
                f"- Custo: R$ {format_number(comparison['cost_brl_saved'], 2)} ({format_number(comparison['cost_saved_pct'])}%)",
                f"- Tempo em rota: {format_number(comparison['route_minutes_saved'])} min "
                f"({format_number(comparison['route_minutes_saved_pct'])}%)",
            ]
        )
    else:
        lines.append("Não há referência para calcular a economia deste plano.")

    lines.extend(
        [
            "",
            "## Atendimento",
            f"- No prazo: {format_number(totals['on_time_rate_pct'])}% do total",
            f"- Críticas no prazo: {format_number(totals['critical_on_time_rate_pct'])}%",
        ]
    )
    late = [stop for _, stop in _all_stops(plan) if stop["late_min"] > 0]
    for stop in late:
        lines.append(
            f"- Atraso previsto em {stop['name']} ({stop['id']}): {format_number(stop['late_min'])} min, "
            f"prioridade {stop['priority']}"
        )

    attention = _attention_lines(plan)
    lines.extend(["", "## Pontos de atenção"])
    lines.extend(attention or ["Nenhum ponto de atenção."])
    return "\n".join(lines)


def render_weekly_report(patterns: dict) -> str:
    """Monta o relatório semanal a partir dos padrões do período."""
    period = patterns["period"]
    totals = patterns["totals"]
    savings = patterns["savings"]
    service = patterns["service_level"]
    peak = patterns["peak_day"]

    lines = [
        "## Resumo da semana",
        (
            f"De {period['start']} a {period['end']} ({period['days']} dias): {totals['deliveries']} entregas. "
            f"Críticas no prazo, em média: {format_number(service['average_critical_on_time_rate_pct'])}%."
        ),
        "",
        "## Indicadores",
        f"- Distância: {format_number(totals['distance_km'])} km",
        f"- Tempo em rota: {format_number(totals['route_minutes'])} min",
        f"- Custo estimado: R$ {format_number(totals['cost_brl'], 2)}",
        "",
        "## Economia de tempo e recursos",
        f"Comparação com: {patterns['reference_method']}. {patterns['data_note']}",
        f"- Distância: {format_number(savings['distance_km_saved'])} km ({format_number(savings['distance_saved_pct'])}%)",
        f"- Custo: R$ {format_number(savings['cost_brl_saved'], 2)} ({format_number(savings['cost_saved_pct'])}%)",
        f"- Tempo em rota: {format_number(savings['route_minutes_saved'])} min ({format_number(savings['route_minutes_saved_pct'])}%)",
        "",
        "## Nível de serviço",
        f"- No prazo, em média: {format_number(service['average_on_time_rate_pct'])}%",
        f"- Críticas no prazo, em média: {format_number(service['average_critical_on_time_rate_pct'])}%",
        f"- Dias com violação de restrição: {service['infeasible_days']}",
    ]
    for stop in patterns["recurring_late_stops"]:
        lines.append(
            f"- Atrasos em {stop['name']} ({stop['id']}): {stop['occurrences']} dia(s), "
            f"média de {format_number(stop['average_late_min'])} min"
        )

    lines.extend(["", "## Uso da frota"])
    for vehicle in patterns["fleet_usage"]:
        lines.append(
            f"- {vehicle['vehicle_name']}: {vehicle['days_used']} dia(s), "
            f"{format_number(vehicle['average_capacity_used_pct'])}% da carga e "
            f"{format_number(vehicle['average_range_used_pct'])}% da autonomia, em média"
        )
    lines.append(f"- Dia de maior carga: {peak['weekday']} ({peak['date']}), {format_number(peak['load_kg'])} kg")
    return "\n".join(lines)


def _suggestion(title: str, pattern: str, suggestion: str, impact: str, metric: str) -> List[str]:
    return [
        f"### {title}",
        f"- Padrão: {pattern}",
        f"- Sugestão: {suggestion}",
        f"- Impacto: {impact}",
        f"- Como medir: {metric}",
        "",
    ]


def render_improvements(patterns: dict) -> str:
    """Aplica regras simples aos padrões do período para sugerir melhorias."""
    lines: List[str] = []

    recurring = [stop for stop in patterns["recurring_late_stops"] if stop["occurrences"] >= 2]
    if recurring:
        names = ", ".join(f"{stop['name']} ({stop['id']})" for stop in recurring)
        lines += _suggestion(
            "Revisar prazos com atraso recorrente",
            f"Atrasos previstos em mais de um dia: {names}.",
            "Avaliar uma saída mais cedo para esses destinos ou revisar o prazo combinado.",
            "Menos entregas fora do prazo nesses destinos.",
            "Atrasos por destino e pontualidade das entregas críticas.",
        )

    if patterns["saturated_vehicles"]:
        lines += _suggestion(
            "Reduzir a pressão sobre veículos saturados",
            f"Uso médio de carga ou autonomia a partir de 85%: {', '.join(patterns['saturated_vehicles'])}.",
            "Avaliar um veículo de apoio nos dias de pico ou uma redistribuição da frota.",
            "Mais folga para pedidos urgentes de última hora.",
            "Uso médio de carga e de autonomia por veículo.",
        )

    if patterns["underused_vehicles"]:
        lines += _suggestion(
            "Reavaliar veículos pouco usados",
            f"Usados em menos da metade dos dias ou com menos de 40% da carga: {', '.join(patterns['underused_vehicles'])}.",
            "Avaliar remanejar esses veículos ou mantê-los como reserva.",
            "Menor custo com frota parada, se a reserva não for necessária.",
            "Dias de uso e custo total da frota.",
        )

    if patterns["service_level"]["infeasible_days"] > 0:
        lines += _suggestion(
            "Investigar dias com violação de restrição",
            f"{patterns['service_level']['infeasible_days']} dia(s) com plano que viola alguma restrição.",
            "Aumentar o tempo de otimização nesses dias ou revisar a capacidade da frota.",
            "Planos que a operação consegue cumprir.",
            "Quantidade de dias com violação.",
        )

    peak = patterns["peak_day"]
    lines += _suggestion(
        "Preparar a operação para o dia de pico",
        f"Maior carga em {peak['weekday']} ({peak['date']}): {format_number(peak['load_kg'])} kg.",
        "Avaliar se parte dos pedidos regulares desse dia pode ser antecipada.",
        "Carga mais equilibrada ao longo da semana.",
        "Carga por dia da semana.",
    )
    return "\n".join(lines).rstrip()


def _describe_stop(route: dict, stop: dict) -> str:
    deadline = f"prazo {stop['deadline']}" if stop["deadline"] else "sem prazo definido"
    status = f"atraso previsto de {format_number(stop['late_min'])} min" if stop["late_min"] > 0 else "no prazo"
    return (
        f"{stop['id']} ({stop['name']}, {stop['item']}): {route['vehicle_name']}, parada {stop['sequence']}, "
        f"chegada às {stop['arrival']}, {deadline}, {status}."
    )


def _answer_by_stop_id(question: str, plan: dict) -> Optional[str]:
    identifiers = {identifier.upper() for identifier in re.findall(r"\b[eE]\d{2}\b", question)}
    if not identifiers:
        return None
    lines = [_describe_stop(route, stop) for route, stop in _all_stops(plan) if stop["id"] in identifiers]
    found = {stop["id"] for _, stop in _all_stops(plan) if stop["id"] in identifiers}
    lines.extend(f"{identifier} não está neste plano." for identifier in sorted(identifiers - found))
    return "\n".join(lines)


def _mentions_name(normalized_question: str, name: str, first_words: Counter) -> bool:
    """Reconhece o nome completo ou a primeira palavra, se só um veículo a usar."""
    normalized_name = _normalize(name)
    if normalized_name in normalized_question:
        return True
    first_word = normalized_name.split()[0]
    return first_words[first_word] == 1 and re.search(rf"\b{re.escape(first_word)}\b", normalized_question) is not None


def _answer_by_vehicle(question: str, plan: dict) -> Optional[str]:
    normalized = _normalize(question)
    names = [route["vehicle_name"] for route in plan["routes"]] + list(plan["unused_vehicles"])
    first_words = Counter(_normalize(name).split()[0] for name in names)
    for route in plan["routes"]:
        identifier = route["vehicle_id"].lower()
        if re.search(rf"\b{re.escape(identifier)}\b", normalized) or _mentions_name(
            normalized, route["vehicle_name"], first_words
        ):
            ids = ", ".join(stop["id"] for stop in route["stops"])
            return (
                f"{route['vehicle_name']} ({route['vehicle_id']}): {len(route['stops'])} paradas ({ids}), "
                f"{format_number(route['distance_km'])} km, {format_number(route['load_kg'])} kg, "
                f"{format_number(route['capacity_used_pct'])}% da carga, custo de R$ {format_number(route['cost_brl'], 2)}, "
                f"retorno às {route['return_time']}."
            )
    for name in plan["unused_vehicles"]:
        if _mentions_name(normalized, name, first_words):
            return f"{name} não tem rota neste plano."
    return None


def _answer_by_stop_text(question: str, plan: dict) -> Optional[str]:
    ignored = {word.rstrip("s") for word in STOPWORDS}
    wanted = {token for token in _tokens(question) if len(token) >= 4 and token not in ignored}
    if not wanted:
        return None
    lines = []
    for route, stop in _all_stops(plan):
        searchable = set(_tokens(f"{stop['item']} {stop['name']}"))
        if wanted & searchable:
            lines.append(_describe_stop(route, stop))
    return "\n".join(lines) if lines else None


def _answer_by_totals(question: str, plan: dict, patterns: Optional[dict]) -> Optional[str]:
    normalized = _normalize(question)
    totals = plan["totals"]

    if "economi" in normalized:
        if patterns is not None and any(word in normalized for word in ("semana", "periodo", "acumulad")):
            savings = patterns["savings"]
            return (
                f"No período, em relação a {patterns['reference_method']}: {format_number(savings['distance_km_saved'])} km, "
                f"R$ {format_number(savings['cost_brl_saved'], 2)} e {format_number(savings['route_minutes_saved'])} min."
            )
        comparison = plan.get("comparison")
        if comparison:
            return (
                f"Em relação a {comparison['reference_method']}: {format_number(comparison['distance_km_saved'])} km, "
                f"R$ {format_number(comparison['cost_brl_saved'], 2)} e {format_number(comparison['route_minutes_saved'])} min."
            )
        return "Este plano não tem referência para calcular a economia."
    if "atras" in normalized:
        late = [f"{stop['id']} ({format_number(stop['late_min'])} min)" for _, stop in _all_stops(plan) if stop["late_min"] > 0]
        return f"Atrasos previstos: {', '.join(late)}." if late else "Nenhuma entrega com atraso previsto."
    if "critic" in normalized or "urgent" in normalized:
        critical = [stop["id"] for _, stop in _all_stops(plan) if stop["priority"] == "crítica"]
        return (
            f"Entregas críticas: {len(critical)} ({', '.join(critical)}), "
            f"{format_number(totals['critical_on_time_rate_pct'])}% no prazo."
        )
    if "refriger" in normalized or "cadeia fria" in normalized or "geladeira" in normalized:
        cold = [f"{stop['id']} ({route['vehicle_id']})" for route, stop in _all_stops(plan) if stop["cold_chain"]]
        return f"Entregas com cadeia fria: {', '.join(cold)}." if cold else "Nenhuma entrega com cadeia fria."
    if any(word in normalized for word in ("distancia", "quilomet", " km")):
        return f"Distância total: {format_number(totals['distance_km'])} km."
    if any(word in normalized for word in ("custo", "gasto", "reais")):
        return f"Custo estimado: R$ {format_number(totals['cost_brl'], 2)}."
    if any(word in normalized for word in ("termina", "retorno", "volta", "horario")):
        return f"Saída às {plan['departure']}. Último retorno ao CD às {totals['last_return']}."
    if "veiculo" in normalized or "frota" in normalized:
        used = ", ".join(route["vehicle_name"] for route in plan["routes"])
        return f"{totals['vehicles_used']} de {totals['vehicles_total']} veículos em uso: {used}."
    if "entrega" in normalized:
        return f"{totals['deliveries']} entregas, {format_number(totals['on_time_rate_pct'])}% no prazo."
    return None


def answer_question(question: str, plan: dict, patterns: Optional[dict] = None) -> str:
    """
    Responde por regras: parada, veículo, item ou nome e, por fim, indicadores.

    Parameters:
    - question: pergunta em linguagem natural.
    - plan: resumo do plano.
    - patterns: padrões do histórico, quando houver.

    Returns:
    str: a resposta, ou um aviso de que a pergunta exige uma LLM.
    """
    return (
        _answer_by_stop_id(question, plan)
        or _answer_by_vehicle(question, plan)
        or _answer_by_stop_text(question, plan)
        or _answer_by_totals(question, plan, patterns)
        or NO_LLM_ANSWER
    )
