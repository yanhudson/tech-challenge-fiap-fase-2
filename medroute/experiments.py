"""Experimentos do relatório técnico: comparativo, ablação e sensibilidade."""

import csv
import time
from dataclasses import replace
from pathlib import Path
from statistics import mean, stdev
from typing import Dict, List, Optional, Sequence, Tuple

from .baselines import nearest_neighbour_routes, ortools_routes, sequential_routes
from .benchmark_att48 import att_48_cities_locations, att_48_cities_order
from .engine import GAConfig, GAResult, run_genetic_algorithm
from .fitness import DEFAULT_WEIGHTS, DISTANCE_ONLY_WEIGHTS, FitnessWeights, evaluate_routes
from .metrics import format_number, summarize_plan
from .models import Problem


COMPARISON_COLUMNS = (
    ("method", "Método"),
    ("runs", "Execuções"),
    ("fitness_mean", "Fitness média"),
    ("fitness_std", "Desvio"),
    ("fitness_best", "Melhor fitness"),
    ("distance_km_mean", "Distância (km)"),
    ("cost_brl_mean", "Custo (R$)"),
    ("route_minutes_mean", "Tempo em rota (min)"),
    ("vehicles_mean", "Veículos"),
    ("on_time_pct_mean", "No prazo (%)"),
    ("critical_on_time_pct_mean", "Críticas no prazo (%)"),
    ("feasible_runs", "Execuções viáveis"),
    ("time_s_mean", "Tempo de execução (s)"),
)

ABLATION_COLUMNS = (
    ("variant", "Variante"),
    ("runs", "Execuções"),
    ("distance_mean", "Distância média"),
    ("distance_std", "Desvio"),
    ("distance_best", "Melhor distância"),
    ("gap_to_optimum_pct", "Acima do ótimo (%)"),
    ("time_s_mean", "Tempo de execução (s)"),
)


def _spread(values: Sequence[float]) -> float:
    return stdev(values) if len(values) > 1 else 0.0


def _column_decimals(rows: Sequence[dict], key: str) -> int:
    """Usa em toda a coluna a maior quantidade de casas decimais encontrada nela."""
    floats = [row[key] for row in rows if isinstance(row[key], float)]
    return max((len(str(value).split(".")[1]) for value in floats), default=0)


def _plan_row(method: str, plans: Sequence[dict], times_s: Sequence[float]) -> dict:
    totals = [plan["totals"] for plan in plans]
    fitness = [item["fitness"] for item in totals]
    return {
        "method": method,
        "runs": len(plans),
        "fitness_mean": round(mean(fitness), 1),
        "fitness_std": round(_spread(fitness), 1),
        "fitness_best": round(min(fitness), 1),
        "distance_km_mean": round(mean(item["distance_km"] for item in totals), 1),
        "cost_brl_mean": round(mean(item["cost_brl"] for item in totals), 2),
        "route_minutes_mean": round(mean(item["route_minutes"] for item in totals), 1),
        "vehicles_mean": round(mean(item["vehicles_used"] for item in totals), 1),
        "on_time_pct_mean": round(mean(item["on_time_rate_pct"] for item in totals), 1),
        "critical_on_time_pct_mean": round(mean(item["critical_on_time_rate_pct"] for item in totals), 1),
        "feasible_runs": sum(1 for item in totals if item["feasible"]),
        "time_s_mean": round(mean(times_s), 2),
    }


def run_method_comparison(
    problem: Problem,
    config: GAConfig = GAConfig(),
    weights: FitnessWeights = DEFAULT_WEIGHTS,
    n_seeds: int = 10,
    ortools_time_limit_s: int = 30,
) -> Tuple[List[dict], GAResult]:
    """
    Compara o algoritmo genético com as demais abordagens na mesma instância.

    Parameters:
    - problem: a instância de roteamento.
    - config: parâmetros do algoritmo genético.
    - weights: pesos da fitness, iguais para todos os métodos.
    - n_seeds: quantidade de execuções do algoritmo genético.
    - ortools_time_limit_s: tempo máximo do OR-Tools.

    Returns:
    Uma linha de resultados por método e a melhor execução do algoritmo genético.
    """
    rows: List[dict] = []

    for method, build in (
        ("Despacho sem otimização", sequential_routes),
        ("Vizinho mais próximo", nearest_neighbour_routes),
    ):
        started = time.perf_counter()
        routes = build(problem)
        elapsed = time.perf_counter() - started
        rows.append(_plan_row(method, [summarize_plan(problem, routes, method, weights)], [elapsed]))

    try:
        started = time.perf_counter()
        routes = ortools_routes(problem, weights, ortools_time_limit_s)
        elapsed = time.perf_counter() - started
        if routes is not None:
            rows.append(_plan_row("OR-Tools", [summarize_plan(problem, routes, "OR-Tools", weights)], [elapsed]))
    except RuntimeError as error:
        print(f"Aviso: comparativo sem OR-Tools. {error}")

    best_result: Optional[GAResult] = None
    plans = []
    times_s = []
    for seed in range(n_seeds):
        result = run_genetic_algorithm(problem, replace(config, seed=seed), weights)
        plans.append(summarize_plan(problem, result.best_routes, "Algoritmo genético", weights))
        times_s.append(result.elapsed_s)
        if best_result is None or result.evaluation.fitness < best_result.evaluation.fitness:
            best_result = result
    rows.append(_plan_row("Algoritmo genético", plans, times_s))

    return rows, best_result


def att48_optimal_distance() -> float:
    """Distância euclidiana da rota ótima conhecida do att48."""
    problem = Problem.from_points(att_48_cities_locations, "att48")
    route = [city - 1 for city in att_48_cities_order[1:-1]]
    return evaluate_routes([route], problem, DISTANCE_ONLY_WEIGHTS).distance_km


def base_code_config(n_generations: int) -> GAConfig:
    """
    Reproduz o laço de tsp.py: roleta, troca de vizinhos e sem cruzamento efetivo.

    O crossover "none" equivale a order_crossover(parent1, parent1), que devolve uma
    cópia do pai. A diferença é que aqui cada par de pais gera dois filhos.
    """
    return GAConfig(
        population_size=100,
        n_generations=n_generations,
        crossover="none",
        selection="roulette",
        mutation_probability=0.5,
        mutation_operators=("adjacent_swap",),
        elitism=1,
        seeded_fraction=0.0,
        stagnation_limit=None,
    )


def run_att48_ablation(n_seeds: int = 5, n_generations: int = 1500) -> List[dict]:
    """
    Mede, no att48, o efeito de cada correção feita sobre o código base.

    As variantes têm a mesma população e o mesmo número de gerações, para que a
    diferença venha dos operadores, não do orçamento de busca.

    Parameters:
    - n_seeds: quantidade de execuções por variante.
    - n_generations: gerações por execução.

    Returns:
    Uma linha por variante, com a distância e a distância em relação ao ótimo.
    """
    problem = Problem.from_points(att_48_cities_locations, "att48")
    optimum = att48_optimal_distance()
    base = base_code_config(n_generations)
    tsp_operators = ("inversion", "relocation", "gene_swap")

    variants = [
        ("Código base (sem cruzamento efetivo)", base),
        ("Base + OX corrigido", replace(base, crossover="ox", crossover_probability=1.0)),
        (
            "Base + OX + novas mutações",
            replace(base, crossover="ox", crossover_probability=1.0, mutation_operators=tsp_operators),
        ),
        (
            "Base + OX + novas mutações + torneio e elitismo de 4",
            replace(
                base,
                crossover="ox",
                crossover_probability=1.0,
                mutation_operators=tsp_operators,
                selection="tournament",
                elitism=4,
            ),
        ),
        (
            "Todas as anteriores + vizinho mais próximo",
            replace(
                base,
                crossover="ox",
                crossover_probability=1.0,
                mutation_operators=tsp_operators,
                selection="tournament",
                elitism=4,
                seeded_fraction=0.1,
            ),
        ),
    ]

    rows = []
    for name, config in variants:
        distances = []
        times_s = []
        for seed in range(n_seeds):
            result = run_genetic_algorithm(problem, replace(config, seed=seed), DISTANCE_ONLY_WEIGHTS)
            distances.append(result.evaluation.distance_km)
            times_s.append(result.elapsed_s)
        rows.append(
            {
                "variant": name,
                "runs": n_seeds,
                "distance_mean": round(mean(distances), 1),
                "distance_std": round(_spread(distances), 1),
                "distance_best": round(min(distances), 1),
                "gap_to_optimum_pct": round(100.0 * (mean(distances) - optimum) / optimum, 1),
                "time_s_mean": round(mean(times_s), 2),
            }
        )
    return rows


def run_sensitivity(
    problem: Problem,
    config: GAConfig = GAConfig(),
    weights: FitnessWeights = DEFAULT_WEIGHTS,
    n_seeds: int = 5,
) -> List[dict]:
    """
    Varia um parâmetro por vez em relação à configuração de referência.

    Parameters:
    - problem: a instância de roteamento.
    - config: configuração de referência.
    - weights: pesos da fitness.
    - n_seeds: quantidade de execuções por configuração.

    Returns:
    Uma linha por configuração.
    """
    without_promotion = tuple(
        name for name in config.mutation_operators if name != "priority_promotion"
    )
    variations: List[Tuple[str, Dict[str, object]]] = [
        ("Referência", {}),
        ("População de 100", {"population_size": 100}),
        ("População de 400", {"population_size": 400}),
        ("Mutação de 20%", {"mutation_probability": 0.2}),
        ("Mutação de 80%", {"mutation_probability": 0.8}),
        ("Cruzamento PMX", {"crossover": "pmx"}),
        ("Seleção por roleta", {"selection": "roulette"}),
        ("Elitismo de 1", {"elitism": 1}),
        ("Sem semente do vizinho mais próximo", {"seeded_fraction": 0.0}),
        ("Sem promoção de prioridade", {"mutation_operators": without_promotion}),
    ]

    rows = []
    for name, changes in variations:
        variant = replace(config, **changes)
        plans = []
        times_s = []
        for seed in range(n_seeds):
            result = run_genetic_algorithm(problem, replace(variant, seed=seed), weights)
            plans.append(summarize_plan(problem, result.best_routes, name, weights))
            times_s.append(result.elapsed_s)
        rows.append(_plan_row(name, plans, times_s))
    return rows


def write_csv(rows: Sequence[dict], path: Path) -> None:
    """Salva as linhas em CSV com BOM, para abrir corretamente no Excel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: Sequence[dict], columns: Sequence[Tuple[str, str]]) -> str:
    """Monta uma tabela em Markdown a partir de pares (chave, título)."""
    header = "| " + " | ".join(title for _, title in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    decimals = {key: _column_decimals(rows, key) for key, _ in columns}
    lines = [header, separator]
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row[key]
            cells.append(format_number(value, decimals[key]) if isinstance(value, float) else str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def replace_marked_section(text: str, marker: str, content: str) -> str:
    """Substitui o trecho entre <!-- BEGIN:marker --> e <!-- END:marker -->."""
    begin = f"<!-- BEGIN:{marker} -->"
    end = f"<!-- END:{marker} -->"
    start_index = text.find(begin)
    end_index = text.find(end)
    if start_index == -1 or end_index == -1 or end_index < start_index:
        raise ValueError(f"Marcadores de '{marker}' não encontrados.")
    return text[: start_index + len(begin)] + "\n" + content + "\n" + text[end_index:]
