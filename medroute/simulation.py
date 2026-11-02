"""Simulação de uma semana de operação, que alimenta os relatórios periódicos."""

import random
from dataclasses import replace
from datetime import date, timedelta

from .baselines import sequential_routes
from .data import generate_daily_problem
from .engine import GAConfig, run_genetic_algorithm
from .fitness import DEFAULT_WEIGHTS, FitnessWeights
from .metrics import attach_comparison, build_day_record, summarize_plan
from .models import Problem

GA_METHOD = "Algoritmo genético"
REFERENCE_METHOD = "Despacho sem otimização (simulado)"
WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


def optimize_plan(problem: Problem, config: GAConfig = GAConfig()) -> tuple:
    """
    Otimiza as rotas e compara o resultado com o despacho sem otimização.

    Returns:
    tuple: o resumo do plano, com a comparação, e o resultado do algoritmo genético.
    """
    result = run_genetic_algorithm(problem, config)
    plan = summarize_plan(problem, result.best_routes, GA_METHOD)
    reference = summarize_plan(problem, sequential_routes(problem), REFERENCE_METHOD)
    return attach_comparison(plan, reference), result


def simulate_week(
    base_problem: Problem,
    start_date: str = "2026-11-02",
    n_days: int = 5,
    seed: int = 42,
    config: GAConfig = GAConfig(),
    weights: FitnessWeights = DEFAULT_WEIGHTS,
) -> dict:
    """
    Otimiza as rotas de cada dia e registra o resultado no histórico.

    Parameters:
    - base_problem: instância com a frota e as entregas possíveis.
    - start_date: primeiro dia, no formato AAAA-MM-DD.
    - n_days: quantidade de dias simulados.
    - seed: semente que torna a simulação reproduzível.
    - config: parâmetros do algoritmo genético.
    - weights: pesos da fitness.

    Returns:
    dict: histórico serializável em JSON, um registro por dia.
    """
    start = date.fromisoformat(start_date)
    days = []
    for offset in range(n_days):
        current = start + timedelta(days=offset)
        day_seed = seed + offset
        problem = generate_daily_problem(base_problem, random.Random(day_seed), current.isoformat())
        result = run_genetic_algorithm(problem, replace(config, seed=day_seed), weights)
        plan = summarize_plan(problem, result.best_routes, GA_METHOD, weights)
        reference = summarize_plan(problem, sequential_routes(problem), REFERENCE_METHOD, weights)
        days.append(build_day_record(current.isoformat(), WEEKDAYS[current.weekday()], plan, reference))

    return {
        "instance": base_problem.name,
        "method": GA_METHOD,
        "reference_method": REFERENCE_METHOD,
        "seed": seed,
        "note": (
            "Demanda sintética. A economia é medida contra um despacho simulado, "
            "não contra a operação real do hospital."
        ),
        "days": days,
    }
