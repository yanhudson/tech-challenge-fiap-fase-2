"""
Métricas do plano e padrões do histórico.

Tudo é calculado aqui, em Python. A LLM recebe estes dados prontos e apenas redige
o texto, o que reduz o risco de números inventados.
"""

import copy
import math
from statistics import mean
from typing import Dict, List, Optional, Sequence

from .fitness import DEFAULT_WEIGHTS, FitnessWeights, evaluate_routes
from .models import PRIORITY_LABELS, Priority, Problem


def format_number(value: float, decimals: int = 1) -> str:
    """Formata um número no padrão brasileiro: 1.234,5."""
    return f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _percent(part: float, whole: float) -> float:
    if whole <= 0 or math.isinf(whole):
        return 0.0
    return round(100.0 * part / whole, 1)


def _rate(on_time: int, total: int) -> float:
    return round(100.0 * on_time / total, 1) if total else 100.0


def summarize_plan(
    problem: Problem,
    routes: Sequence[Sequence[int]],
    method: str,
    weights: FitnessWeights = DEFAULT_WEIGHTS,
) -> dict:
    """
    Gera o resumo completo de um plano em um dicionário serializável em JSON.

    Esse resumo é a fonte única de dados do mapa, dos relatórios e da LLM.

    Parameters:
    - problem: a instância de roteamento.
    - routes: a lista de paradas de cada veículo.
    - method: nome do método que gerou o plano.
    - weights: pesos da fitness.

    Returns:
    dict: dados da instância, totais e rotas com as paradas em ordem.
    """
    evaluation = evaluate_routes(routes, problem, weights)

    by_priority = {
        PRIORITY_LABELS[priority]: {"total": 0, "on_time": 0}
        for priority in Priority
    }
    route_summaries = []
    total_cost = 0.0
    total_load = 0.0
    total_minutes = 0.0
    makespan = 0.0
    late_deliveries = 0
    unused_vehicles = []

    for result in evaluation.routes:
        vehicle = problem.vehicles[result.vehicle_index]
        if not result.stops:
            unused_vehicles.append(vehicle.name)
            continue

        stops = []
        for sequence, (node, arrival, late) in enumerate(
            zip(result.stops, result.arrivals_min, result.lateness_min), start=1
        ):
            delivery = problem.delivery(node)
            label = PRIORITY_LABELS[delivery.priority]
            by_priority[label]["total"] += 1
            if late > 0:
                late_deliveries += 1
            else:
                by_priority[label]["on_time"] += 1
            stops.append(
                {
                    "sequence": sequence,
                    "id": delivery.id,
                    "name": delivery.name,
                    "kind": delivery.kind,
                    "lat": delivery.lat,
                    "lon": delivery.lon,
                    "item": delivery.item,
                    "demand_kg": delivery.demand_kg,
                    "priority": label,
                    "cold_chain": delivery.requires_cold_chain,
                    "arrival": problem.clock(arrival),
                    "deadline": (
                        problem.clock(delivery.deadline_min)
                        if delivery.deadline_min is not None
                        else None
                    ),
                    "late_min": round(late, 1),
                }
            )

        cost = result.distance_km * vehicle.cost_per_km
        total_cost += cost
        total_load += result.load_kg
        total_minutes += result.duration_min
        makespan = max(makespan, result.duration_min)

        route_summaries.append(
            {
                "vehicle_index": result.vehicle_index,
                "vehicle_id": vehicle.id,
                "vehicle_name": vehicle.name,
                "refrigerated": vehicle.refrigerated,
                "capacity_kg": vehicle.capacity_kg,
                "range_km": vehicle.range_km,
                "distance_km": round(result.distance_km, 1),
                "duration_min": round(result.duration_min, 1),
                "return_time": problem.clock(result.duration_min),
                "load_kg": round(result.load_kg, 1),
                "capacity_used_pct": _percent(result.load_kg, vehicle.capacity_kg),
                "range_used_pct": _percent(result.distance_km, vehicle.range_km),
                "cost_brl": round(cost, 2),
                "stops": stops,
            }
        )

    n_stops = sum(item["total"] for item in by_priority.values())
    critical = by_priority[PRIORITY_LABELS[Priority.CRITICAL]]

    return {
        "instance": problem.name,
        "method": method,
        "departure": problem.clock(0),
        "shift_end": problem.clock(problem.shift_min) if not math.isinf(problem.shift_min) else None,
        "depot": {"name": problem.depot.name, "lat": problem.depot.lat, "lon": problem.depot.lon},
        "totals": {
            "distance_km": round(evaluation.distance_km, 1),
            "cost_brl": round(total_cost, 2),
            "route_minutes": round(total_minutes, 1),
            "makespan_min": round(makespan, 1),
            "last_return": problem.clock(makespan),
            "vehicles_used": len(route_summaries),
            "vehicles_total": problem.n_vehicles,
            "deliveries": n_stops,
            "load_kg": round(total_load, 1),
            "on_time_rate_pct": _rate(n_stops - late_deliveries, n_stops),
            "critical_on_time_rate_pct": _rate(critical["on_time"], critical["total"]),
            "on_time_by_priority": by_priority,
            "late_deliveries": late_deliveries,
            "fitness": round(evaluation.fitness, 1),
            "feasible": evaluation.is_feasible,
            "violations": {
                "overload_kg": round(evaluation.overload_kg, 1),
                "range_excess_km": round(evaluation.range_excess_km, 1),
                "shift_excess_min": round(evaluation.shift_excess_min, 1),
                "cold_chain_violations": evaluation.cold_violations,
            },
        },
        "routes": route_summaries,
        "unused_vehicles": unused_vehicles,
    }


def compute_savings(plan: dict, reference: dict) -> dict:
    """Compara um plano com outro de referência, resolvendo a mesma instância."""
    current = plan["totals"]
    base = reference["totals"]

    def saved(key: str) -> float:
        return round(base[key] - current[key], 2)

    return {
        "reference_method": reference["method"],
        "distance_km_saved": saved("distance_km"),
        "distance_saved_pct": _percent(saved("distance_km"), base["distance_km"]),
        "cost_brl_saved": saved("cost_brl"),
        "cost_saved_pct": _percent(saved("cost_brl"), base["cost_brl"]),
        "route_minutes_saved": saved("route_minutes"),
        "route_minutes_saved_pct": _percent(saved("route_minutes"), base["route_minutes"]),
        "critical_on_time_gain_points": round(
            current["critical_on_time_rate_pct"] - base["critical_on_time_rate_pct"], 1
        ),
        "reference_totals": {
            "distance_km": base["distance_km"],
            "cost_brl": base["cost_brl"],
            "route_minutes": base["route_minutes"],
            "critical_on_time_rate_pct": base["critical_on_time_rate_pct"],
            "on_time_rate_pct": base["on_time_rate_pct"],
        },
    }


def facts_for_llm(plan: dict) -> dict:
    """Remove do plano as coordenadas, que a LLM não usa, reduzindo tokens e exposição."""
    facts = copy.deepcopy(plan)
    facts["depot"] = {"name": plan["depot"]["name"]}
    for route in facts["routes"]:
        for stop in route["stops"]:
            stop.pop("lat", None)
            stop.pop("lon", None)
    return facts


def find_route(plan: dict, vehicle: str) -> dict:
    """Localiza a rota pelo identificador ou pelo nome do veículo."""
    wanted = vehicle.strip().lower()
    for route in plan["routes"]:
        if wanted in (route["vehicle_id"].lower(), route["vehicle_name"].lower()):
            return route
    available = ", ".join(route["vehicle_id"] for route in plan["routes"])
    raise KeyError(f"Veículo '{vehicle}' não tem rota neste plano. Disponíveis: {available}.")


def build_day_record(date_text: str, weekday: str, plan: dict, reference: dict) -> dict:
    """Resume um dia simulado para o histórico semanal."""
    late_stops = [
        {
            "id": stop["id"],
            "name": stop["name"],
            "priority": stop["priority"],
            "late_min": stop["late_min"],
        }
        for route in plan["routes"]
        for stop in route["stops"]
        if stop["late_min"] > 0
    ]
    vehicles = [
        {
            "vehicle_id": route["vehicle_id"],
            "vehicle_name": route["vehicle_name"],
            "capacity_used_pct": route["capacity_used_pct"],
            "range_used_pct": route["range_used_pct"],
        }
        for route in plan["routes"]
    ]
    totals = plan["totals"]
    return {
        "date": date_text,
        "weekday": weekday,
        "totals": {
            "distance_km": totals["distance_km"],
            "cost_brl": totals["cost_brl"],
            "route_minutes": totals["route_minutes"],
            "deliveries": totals["deliveries"],
            "load_kg": totals["load_kg"],
            "vehicles_used": totals["vehicles_used"],
            "on_time_rate_pct": totals["on_time_rate_pct"],
            "critical_on_time_rate_pct": totals["critical_on_time_rate_pct"],
            "late_deliveries": totals["late_deliveries"],
            "feasible": totals["feasible"],
        },
        "savings": compute_savings(plan, reference),
        "vehicles": vehicles,
        "unused_vehicles": plan["unused_vehicles"],
        "late_stops": late_stops,
    }


def find_patterns(history: dict) -> dict:
    """
    Calcula, a partir do histórico, os indicadores e padrões do período.

    Os relatórios e as sugestões de melhoria da LLM se baseiam neste resultado.

    Parameters:
    - history: histórico gerado por simulation.simulate_week.

    Returns:
    dict: totais, economia, pontualidade, atrasos recorrentes e uso da frota.
    """
    days: List[dict] = history["days"]
    if not days:
        raise ValueError("O histórico não tem dias registrados.")

    total_km = sum(day["totals"]["distance_km"] for day in days)
    total_cost = sum(day["totals"]["cost_brl"] for day in days)
    total_minutes = sum(day["totals"]["route_minutes"] for day in days)
    reference_km = sum(day["savings"]["reference_totals"]["distance_km"] for day in days)
    reference_cost = sum(day["savings"]["reference_totals"]["cost_brl"] for day in days)
    reference_minutes = sum(day["savings"]["reference_totals"]["route_minutes"] for day in days)

    late_by_stop: Dict[str, dict] = {}
    for day in days:
        for stop in day["late_stops"]:
            entry = late_by_stop.setdefault(
                stop["id"],
                {"id": stop["id"], "name": stop["name"], "priority": stop["priority"], "occurrences": 0, "_late": []},
            )
            entry["occurrences"] += 1
            entry["_late"].append(stop["late_min"])

    recurring_late = sorted(late_by_stop.values(), key=lambda entry: entry["occurrences"], reverse=True)[:5]
    recurring_late = [
        {
            "id": entry["id"],
            "name": entry["name"],
            "priority": entry["priority"],
            "occurrences": entry["occurrences"],
            "average_late_min": round(mean(entry["_late"]), 1),
        }
        for entry in recurring_late
    ]

    usage: Dict[str, dict] = {}
    for day in days:
        for vehicle in day["vehicles"]:
            entry = usage.setdefault(
                vehicle["vehicle_name"],
                {"vehicle_name": vehicle["vehicle_name"], "days_used": 0, "_capacity": [], "_range": []},
            )
            entry["days_used"] += 1
            entry["_capacity"].append(vehicle["capacity_used_pct"])
            entry["_range"].append(vehicle["range_used_pct"])
        for name in day["unused_vehicles"]:
            usage.setdefault(name, {"vehicle_name": name, "days_used": 0, "_capacity": [], "_range": []})

    fleet_usage = [
        {
            "vehicle_name": entry["vehicle_name"],
            "days_used": entry["days_used"],
            "average_capacity_used_pct": round(mean(entry["_capacity"]), 1) if entry["_capacity"] else 0.0,
            "average_range_used_pct": round(mean(entry["_range"]), 1) if entry["_range"] else 0.0,
        }
        for entry in usage.values()
    ]
    underused = [
        entry["vehicle_name"]
        for entry in fleet_usage
        if entry["days_used"] < len(days) / 2 or entry["average_capacity_used_pct"] < 40
    ]
    saturated = [
        entry["vehicle_name"]
        for entry in fleet_usage
        if entry["average_capacity_used_pct"] >= 85 or entry["average_range_used_pct"] >= 85
    ]

    peak_day = max(days, key=lambda day: day["totals"]["load_kg"])

    return {
        "period": {"start": days[0]["date"], "end": days[-1]["date"], "days": len(days)},
        "method": history.get("method"),
        "reference_method": history.get("reference_method"),
        "data_note": history.get("note"),
        "totals": {
            "deliveries": sum(day["totals"]["deliveries"] for day in days),
            "distance_km": round(total_km, 1),
            "cost_brl": round(total_cost, 2),
            "route_minutes": round(total_minutes, 1),
        },
        "savings": {
            "distance_km_saved": round(reference_km - total_km, 1),
            "distance_saved_pct": _percent(reference_km - total_km, reference_km),
            "cost_brl_saved": round(reference_cost - total_cost, 2),
            "cost_saved_pct": _percent(reference_cost - total_cost, reference_cost),
            "route_minutes_saved": round(reference_minutes - total_minutes, 1),
            "route_minutes_saved_pct": _percent(reference_minutes - total_minutes, reference_minutes),
        },
        "service_level": {
            "average_on_time_rate_pct": round(mean(day["totals"]["on_time_rate_pct"] for day in days), 1),
            "average_critical_on_time_rate_pct": round(
                mean(day["totals"]["critical_on_time_rate_pct"] for day in days), 1
            ),
            "infeasible_days": sum(1 for day in days if not day["totals"]["feasible"]),
        },
        "recurring_late_stops": recurring_late,
        "fleet_usage": fleet_usage,
        "underused_vehicles": underused,
        "saturated_vehicles": saturated,
        "peak_day": {
            "date": peak_day["date"],
            "weekday": peak_day["weekday"],
            "load_kg": peak_day["totals"]["load_kg"],
            "deliveries": peak_day["totals"]["deliveries"],
        },
        "daily": [
            {
                "date": day["date"],
                "weekday": day["weekday"],
                "deliveries": day["totals"]["deliveries"],
                "distance_km": day["totals"]["distance_km"],
                "reference_distance_km": day["savings"]["reference_totals"]["distance_km"],
                "critical_on_time_rate_pct": day["totals"]["critical_on_time_rate_pct"],
            }
            for day in days
        ],
    }


def attach_comparison(plan: dict, reference: Optional[dict]) -> dict:
    """Inclui no plano a economia em relação à referência, quando ela existir."""
    if reference is not None:
        plan["comparison"] = compute_savings(plan, reference)
    return plan
