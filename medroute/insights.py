"""
Insights do plano e da semana, calculados em Python a partir das métricas.

Cada regra compara um número com um limite e diz o que fazer. Não há LLM aqui, então
os alertas funcionam sem chave de API e não dependem de texto gerado.
"""

from dataclasses import dataclass
from typing import List

from .data import parse_clock
from .metrics import format_number

SATURATED_PCT = 90.0
UNDERUSED_PCT = 40.0
TIGHT_SLACK_MIN = 30
LEVEL_ORDER = {"critical": 0, "warning": 1, "good": 2, "info": 3}


@dataclass(frozen=True)
class Insight:
    level: str  # "critical", "warning", "good" ou "info"
    title: str
    detail: str
    action: str = ""


def _ranked(insights: List[Insight]) -> List[Insight]:
    return sorted(insights, key=lambda insight: LEVEL_ORDER[insight.level])


def _names(items: List[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} e {items[-1]}"


def _shift_minutes(plan: dict) -> float:
    if not plan.get("shift_end"):
        return 0.0
    return float((parse_clock(plan["shift_end"]) - parse_clock(plan["departure"])) % (24 * 60)) or 24.0 * 60


def fleet_rows(plan: dict) -> List[dict]:
    """Quanto cada veículo usa dos seus limites: carga, autonomia e jornada."""
    shift = _shift_minutes(plan)
    rows = []
    for route in plan["routes"]:
        shift_pct = round(100.0 * route["duration_min"] / shift, 1) if shift else 0.0
        rows.append(
            {
                "vehicle_id": route["vehicle_id"],
                "vehicle_name": route["vehicle_name"],
                "stops": len(route["stops"]),
                "capacity_pct": route["capacity_used_pct"],
                "range_pct": route["range_used_pct"],
                "shift_pct": shift_pct,
                "load_kg": route["load_kg"],
                "capacity_kg": route["capacity_kg"],
                "distance_km": route["distance_km"],
                "range_km": route["range_km"],
                "duration_min": route["duration_min"],
                "cost_brl": route["cost_brl"],
            }
        )
    return rows


def slack_rows(plan: dict) -> List[dict]:
    """Entregas com prazo, da menor para a maior folga. Folga negativa significa atraso."""
    rows = []
    for route in plan["routes"]:
        for stop in route["stops"]:
            if stop["deadline"] is None:
                continue
            rows.append(
                {
                    "id": stop["id"],
                    "name": stop["name"],
                    "vehicle_name": route["vehicle_name"],
                    "priority": stop["priority"],
                    "arrival": stop["arrival"],
                    "deadline": stop["deadline"],
                    "slack_min": parse_clock(stop["deadline"]) - parse_clock(stop["arrival"]),
                }
            )
    return sorted(rows, key=lambda row: row["slack_min"])


def _feasibility_insight(plan: dict) -> List[Insight]:
    totals = plan["totals"]
    if totals["feasible"]:
        return []
    violations = totals["violations"]
    parts = []
    if violations["overload_kg"] > 0:
        parts.append(f"{format_number(violations['overload_kg'])} kg acima da capacidade")
    if violations["range_excess_km"] > 0:
        parts.append(f"{format_number(violations['range_excess_km'])} km acima da autonomia")
    if violations["shift_excess_min"] > 0:
        parts.append(f"{format_number(violations['shift_excess_min'])} min acima da jornada")
    if violations["cold_chain_violations"] > 0:
        parts.append(f"{violations['cold_chain_violations']} item(ns) refrigerado(s) em veículo comum")
    return [
        Insight(
            "critical",
            "O plano viola limites da operação",
            f"Excedentes: {_names(parts)}.",
            "Não execute este plano. Revise a frota ou as entregas e otimize de novo.",
        )
    ]


def _delay_insights(plan: dict) -> List[Insight]:
    late = [row for row in slack_rows(plan) if row["slack_min"] < 0]
    critical_late = [row for row in late if row["priority"] == "crítica"]
    insights = []
    if critical_late:
        names = _names([f"{row['name']} ({row['id']})" for row in critical_late])
        insights.append(
            Insight(
                "critical",
                f"{len(critical_late)} entrega(s) crítica(s) com atraso previsto",
                f"Atrasadas: {names}.",
                "Avise as unidades agora, ou antecipe a saída ou acrescente um veículo.",
            )
        )
    other_late = len(late) - len(critical_late)
    if other_late:
        insights.append(
            Insight(
                "warning",
                f"{other_late} entrega(s) não crítica(s) com atraso previsto",
                "O plano priorizou as entregas mais urgentes.",
                "Veja na tabela de folga quais são e avise os destinos.",
            )
        )

    tight = [row for row in slack_rows(plan) if 0 <= row["slack_min"] < TIGHT_SLACK_MIN and row["priority"] == "crítica"]
    if tight:
        first = tight[0]
        insights.append(
            Insight(
                "warning",
                f"{len(tight)} entrega(s) crítica(s) com menos de {TIGHT_SLACK_MIN} min de folga",
                f"A menor folga é de {first['slack_min']} min: {first['name']} ({first['id']}), "
                f"chegada às {first['arrival']} para o prazo das {first['deadline']}.",
                "Um trânsito pesado pode causar atraso. Confirme a saída no horário.",
            )
        )
    return insights


def _fleet_insights(plan: dict) -> List[Insight]:
    insights = []
    rows = fleet_rows(plan)
    limits = (("capacity_pct", "da carga"), ("range_pct", "da autonomia"), ("shift_pct", "da jornada"))
    for row in rows:
        for key, label in limits:
            if row[key] >= SATURATED_PCT:
                insights.append(
                    Insight(
                        "warning",
                        f"{row['vehicle_name']} está sem folga",
                        f"Usa {format_number(row[key])}% {label}.",
                        "Um pedido a mais ou um desvio pode não caber. Tenha uma alternativa.",
                    )
                )
                break

    underused = [row for row in rows if row["capacity_pct"] < UNDERUSED_PCT]
    if underused and len(rows) > 1:
        names = _names([f"{row['vehicle_name']} ({format_number(row['capacity_pct'])}%)" for row in underused])
        insights.append(
            Insight(
                "info",
                "Veículo(s) com pouca carga",
                f"Abaixo de {format_number(UNDERUSED_PCT, 0)}% da capacidade: {names}.",
                "Avalie se um veículo menor faria essa rota. A saída pode se justificar pelos prazos.",
            )
        )
    if plan["unused_vehicles"]:
        insights.append(
            Insight(
                "info",
                "Veículo(s) parado(s) neste plano",
                f"Sem rota: {_names(plan['unused_vehicles'])}.",
                "Há folga na frota para encaixar pedidos de última hora.",
            )
        )
    if len(rows) > 1 and plan["totals"]["cost_brl"] > 0:
        priciest = max(rows, key=lambda row: row["cost_brl"])
        share = 100.0 * priciest["cost_brl"] / plan["totals"]["cost_brl"]
        insights.append(
            Insight(
                "info",
                f"{priciest['vehicle_name']} concentra o custo",
                f"R$ {format_number(priciest['cost_brl'], 2)}, ou {format_number(share, 0)}% do custo do dia.",
                "O otimizador não minimiza reais diretamente; compare o custo por km da frota.",
            )
        )
    return insights


def _comparison_insights(plan: dict) -> List[Insight]:
    comparison = plan.get("comparison")
    if not comparison:
        return []
    caveat = "A referência é um despacho simulado, não a operação real."
    saved = comparison["distance_km_saved"]
    gain = comparison["critical_on_time_gain_points"]
    insights = []
    if saved > 0:
        insights.append(
            Insight(
                "good",
                f"{format_number(saved)} km a menos que o despacho simples",
                f"Redução de {format_number(comparison['distance_saved_pct'])}% na distância "
                f"e de R$ {format_number(comparison['cost_brl_saved'], 2)} no custo. {caveat}",
            )
        )
    elif saved < 0:
        insights.append(
            Insight(
                "info",
                f"{format_number(-saved)} km a mais que o despacho simples",
                f"O otimizador equilibra distância, prioridade e prazos, e não só os quilômetros. {caveat}",
            )
        )
    else:
        insights.append(
            Insight(
                "info",
                "Mesma distância do despacho simples",
                "Com poucas entregas, a ordem simples já pode ser a melhor. O ganho aparece com mais paradas.",
            )
        )
    if gain > 0:
        insights.append(
            Insight(
                "good",
                f"{format_number(gain)} pontos a mais de críticas no prazo",
                f"O despacho simples entregaria {format_number(comparison['reference_totals']['critical_on_time_rate_pct'])}% "
                f"das críticas no prazo; este plano entrega {format_number(plan['totals']['critical_on_time_rate_pct'])}%.",
            )
        )
    return insights


def plan_insights(plan: dict) -> List[Insight]:
    """Lista os insights do plano, dos mais urgentes para os informativos."""
    return _ranked(
        _feasibility_insight(plan) + _delay_insights(plan) + _fleet_insights(plan) + _comparison_insights(plan)
    )


def week_insights(patterns: dict) -> List[Insight]:
    """Lista os insights de um período, a partir de metrics.find_patterns."""
    insights = []
    service = patterns["service_level"]
    savings = patterns["savings"]
    days = patterns["period"]["days"]

    if service["infeasible_days"]:
        insights.append(
            Insight(
                "critical",
                f"{service['infeasible_days']} de {days} dia(s) violaram limites da operação",
                "Nesses dias, a frota não comportou a demanda dentro dos limites.",
                "Revise a capacidade da frota para os dias de pico.",
            )
        )
    if service["average_critical_on_time_rate_pct"] < 100:
        insights.append(
            Insight(
                "critical",
                "Entregas críticas atrasaram no período",
                f"Média de {format_number(service['average_critical_on_time_rate_pct'])}% no prazo.",
                "Veja as entregas com atraso recorrente abaixo.",
            )
        )
    else:
        insights.append(
            Insight("good", "Todas as entregas críticas no prazo", f"Em todos os {days} dia(s) do período.")
        )

    recurring = [stop for stop in patterns["recurring_late_stops"] if stop["occurrences"] > 1]
    if recurring:
        names = _names([f"{stop['name']} ({stop['occurrences']}x)" for stop in recurring])
        insights.append(
            Insight(
                "warning",
                "Atrasos que se repetem",
                f"Destinos: {names}.",
                "Um atraso recorrente pede outro prazo, outra rota ou outro veículo.",
            )
        )
    if patterns["saturated_vehicles"]:
        insights.append(
            Insight(
                "warning",
                "Veículo(s) sempre perto do limite",
                f"Com uso médio acima de 85%: {_names(patterns['saturated_vehicles'])}.",
                "Eles têm pouca margem para o aumento da demanda.",
            )
        )
    if patterns["underused_vehicles"]:
        insights.append(
            Insight(
                "info",
                "Veículo(s) pouco usados",
                f"Pouca carga ou poucos dias de uso: {_names(patterns['underused_vehicles'])}.",
                "Avalie a necessidade deles nesta frota.",
            )
        )
    if savings["distance_km_saved"] > 0:
        insights.append(
            Insight(
                "good",
                f"{format_number(savings['distance_km_saved'])} km a menos no período",
                f"Redução de {format_number(savings['distance_saved_pct'])}% e de "
                f"R$ {format_number(savings['cost_brl_saved'], 2)} em relação a um despacho simulado.",
            )
        )
    peak = patterns["peak_day"]
    insights.append(
        Insight(
            "info",
            f"Pico de carga: {peak['weekday']}",
            f"{format_number(peak['load_kg'])} kg em {peak['deliveries']} entregas.",
            "Reforce a equipe de carregamento nesse dia.",
        )
    )
    return _ranked(insights)
